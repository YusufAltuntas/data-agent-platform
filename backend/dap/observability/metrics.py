"""Prometheus metrics (design §9) for the API and the worker.

The API's metrics live in the default registry and are served at `/api/metrics`. The worker's
live in `WORKER_REGISTRY` and are served on their own port by the worker's parent process.
Under the prefork pool the children record them: with `PROMETHEUS_MULTIPROC_DIR` set,
`prometheus_client` writes every sample to that directory and the endpoint adds up the files.
Without it (the solo pool on the host) the registry is served as it is.

Recording a metric never fails a run: an error is logged and swallowed, except the run's soft
time limit, which always reaches the caller so the run ends as `timeout`.
"""

import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from wsgiref.simple_server import WSGIServer

from billiard.exceptions import SoftTimeLimitExceeded
from prometheus_client import CollectorRegistry, Counter, Histogram, multiprocess, start_http_server

from dap.agent.tools import TOOL_SCHEMAS

MULTIPROC_DIR_ENV = "PROMETHEUS_MULTIPROC_DIR"  # read by prometheus_client itself

logger = logging.getLogger(__name__)

# The tool name comes from the model; any other name is one series, not one per invention.
KNOWN_TOOLS = frozenset(schema["function"]["name"] for schema in TOOL_SCHEMAS)
UNKNOWN_TOOL = "unknown"

# --- API ------------------------------------------------------------------------------------

RUNS_CREATED = Counter("dap_runs_created_total", "Runs accepted and queued.", ["team"])

# --- worker ---------------------------------------------------------------------------------

WORKER_REGISTRY = CollectorRegistry()

# The soft time limit is 120 s and the hard one 150 s (K10).
RUN_DURATION_BUCKETS = (0.5, 1, 2.5, 5, 10, 20, 30, 45, 60, 90, 120, 150)

RUN_DURATION = Histogram(
    "dap_run_duration_seconds",
    "Time from a run's start to its final status.",
    buckets=RUN_DURATION_BUCKETS,
    registry=WORKER_REGISTRY,
)
RUNS_FINISHED = Counter(
    "dap_runs_finished_total",
    "Runs that reached a final status.",
    ["status"],
    registry=WORKER_REGISTRY,
)
LLM_TOKENS = Counter(
    "dap_llm_tokens_total", "LLM tokens used.", ["model", "direction"], registry=WORKER_REGISTRY
)
LLM_COST = Counter("dap_llm_cost_usd_total", "LLM cost in USD.", ["team"], registry=WORKER_REGISTRY)
TOOL_CALLS = Counter(
    "dap_tool_calls_total", "Agent tool calls.", ["tool", "outcome"], registry=WORKER_REGISTRY
)


@contextmanager
def _metrics_errors_logged(message: str, *args: Any) -> Iterator[None]:
    """Log and swallow a metrics failure; let the run's soft time limit through."""
    try:
        yield
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception(message, *args)


def record_event(team: str, event_type: str, payload: Mapping[str, Any]) -> None:
    """Count an agent loop event: tokens and cost of an `llm_call`, the outcome of a tool."""
    with _metrics_errors_logged("could not record metrics for the %s event", event_type):
        if event_type == "llm_call":
            model = payload["model"]
            LLM_TOKENS.labels(model=model, direction="prompt").inc(payload["prompt_tokens"])
            LLM_TOKENS.labels(model=model, direction="completion").inc(payload["completion_tokens"])
            if payload["cost_usd"] is not None:
                LLM_COST.labels(team=team).inc(payload["cost_usd"])
        elif event_type == "tool_result":
            outcome = "ok" if payload["ok"] else "error"
            tool = payload["name"] if payload["name"] in KNOWN_TOOLS else UNKNOWN_TOOL
            TOOL_CALLS.labels(tool=tool, outcome=outcome).inc()


def record_run_finished(status: str, started_at: datetime | None, finished_at: datetime) -> None:
    """Count the run's final status and, if it ever started, observe its duration."""
    with _metrics_errors_logged("could not record metrics for a %s run", status):
        RUNS_FINISHED.labels(status=str(status)).inc()
        if started_at is not None:
            RUN_DURATION.observe((finished_at - started_at).total_seconds())


def start_worker_metrics_server(port: int, addr: str = "0.0.0.0") -> WSGIServer:
    """Serve the worker's metrics at `/metrics` from a daemon thread of this process."""
    if MULTIPROC_DIR_ENV in os.environ:
        # The documented multiprocess setup: a fresh registry that reads the directory.
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    else:
        registry = WORKER_REGISTRY
    server, _ = start_http_server(port, addr=addr, registry=registry)
    return server


def mark_process_dead(pid: int) -> None:
    """Bookkeeping for a pool child that exited (multiprocess mode only); its counts stay."""
    if MULTIPROC_DIR_ENV in os.environ:
        multiprocess.mark_process_dead(pid)  # type: ignore[no-untyped-call]
