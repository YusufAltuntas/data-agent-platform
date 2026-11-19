"""Metrics (design §9): the API's /api/metrics and the worker's run, LLM and tool metrics.

Counters are read before and after, so values left by other tests do not matter.
"""

import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from prometheus_client import REGISTRY
from pydantic import SecretStr

from dap.api.app import create_app
from dap.observability import metrics
from dap.observability.metrics import WORKER_REGISTRY
from dap.settings import Settings

pytestmark = pytest.mark.anyio

STARTED = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _settings() -> Settings:
    return Settings(
        postgres_password=SecretStr("x"),
        ds_sales_ro_password=SecretStr("x"),
        ds_hr_ro_password=SecretStr("x"),
        dap_fernet_key=SecretStr("x"),
        rabbitmq_password=SecretStr("x"),
        litellm_master_key=SecretStr("x"),
    )


def _worker_value(name: str, **labels: str) -> float:
    return WORKER_REGISTRY.get_sample_value(name, labels) or 0.0


class Delta:
    """How much worker samples grew since the block started."""

    def __init__(self, *samples: tuple[str, dict[str, str]]) -> None:
        self._samples = samples
        self._before = [_worker_value(name, **labels) for name, labels in samples]

    def __call__(self) -> list[float]:
        return [
            _worker_value(name, **labels) - before
            for (name, labels), before in zip(self._samples, self._before, strict=True)
        ]


# --- API ------------------------------------------------------------------------------------


async def test_api_metrics_endpoint_serves_the_request_duration_histogram_without_auth() -> None:
    app = create_app(_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/healthz")).status_code == 200
        response = await client.get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'http_request_duration_seconds_bucket{handler="/api/healthz"' in response.text
    assert "# TYPE dap_runs_created_total counter" in response.text
    # The worker's metrics are served by the worker, not by the API.
    assert "dap_run_duration_seconds" not in response.text
    # Buckets fine enough for API latencies of a few milliseconds.
    for le in ("0.005", "0.01", "0.025", "0.05", "0.25", "2.5"):
        assert f'http_request_duration_seconds_bucket{{handler="/api/healthz",le="{le}"' in (
            response.text
        )


def test_runs_created_counter_is_labelled_by_team() -> None:
    before = REGISTRY.get_sample_value("dap_runs_created_total", {"team": "hr"}) or 0.0
    metrics.RUNS_CREATED.labels(team="hr").inc()
    after = REGISTRY.get_sample_value("dap_runs_created_total", {"team": "hr"})
    assert after == before + 1


# --- worker events --------------------------------------------------------------------------


def test_llm_call_counts_tokens_by_model_and_direction_and_cost_by_team() -> None:
    delta = Delta(
        ("dap_llm_tokens_total", {"model": "gpt-x", "direction": "prompt"}),
        ("dap_llm_tokens_total", {"model": "gpt-x", "direction": "completion"}),
        ("dap_llm_cost_usd_total", {"team": "sales"}),
    )
    payload = {
        "step": 1,
        "model": "gpt-x",
        "text": None,
        "tool_calls": [],
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "cost_usd": 0.25,
    }

    metrics.record_event("sales", "llm_call", payload)
    metrics.record_event("sales", "llm_call", {**payload, "cost_usd": None})

    assert delta() == pytest.approx([240, 60, 0.25])


def test_tool_results_count_by_tool_and_outcome() -> None:
    delta = Delta(
        ("dap_tool_calls_total", {"tool": "run_sql", "outcome": "ok"}),
        ("dap_tool_calls_total", {"tool": "run_sql", "outcome": "error"}),
    )

    metrics.record_event(
        "sales", "tool_result", {"step": 1, "id": "a", "name": "run_sql", "ok": True}
    )
    metrics.record_event(
        "sales", "tool_result", {"step": 1, "id": "b", "name": "run_sql", "ok": False}
    )
    metrics.record_event("sales", "tool_call", {"step": 1, "id": "c", "name": "run_sql"})

    assert delta() == [1, 1]


def test_an_unknown_tool_name_is_counted_as_unknown() -> None:
    delta = Delta(("dap_tool_calls_total", {"tool": "unknown", "outcome": "error"}))

    metrics.record_event("sales", "tool_result", {"name": "drop_everything", "ok": False})

    assert delta() == [1]
    assert _worker_value("dap_tool_calls_total", tool="drop_everything", outcome="error") == 0


def test_run_finished_counts_the_status_and_observes_the_duration() -> None:
    delta = Delta(
        ("dap_runs_finished_total", {"status": "succeeded"}),
        ("dap_run_duration_seconds_count", {}),
        ("dap_run_duration_seconds_sum", {}),
    )

    metrics.record_run_finished("succeeded", STARTED, STARTED + timedelta(seconds=4))

    assert delta() == pytest.approx([1, 1, 4])


def test_a_run_that_never_started_is_counted_without_a_duration() -> None:
    delta = Delta(
        ("dap_runs_finished_total", {"status": "failed"}),
        ("dap_run_duration_seconds_count", {}),
    )

    metrics.record_run_finished("failed", None, STARTED)

    assert delta() == [1, 0]


def test_a_metrics_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    metrics.record_event("sales", "llm_call", {"model": "m"})  # no token counts
    metrics.record_event("sales", "tool_result", {})
    assert [r.levelname for r in caplog.records] == ["ERROR", "ERROR"]


class _TimeLimitedCounter:
    def labels(self, **labels: Any) -> Any:
        raise SoftTimeLimitExceeded()


def test_the_soft_time_limit_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics, "RUNS_FINISHED", _TimeLimitedCounter())
    with pytest.raises(SoftTimeLimitExceeded):
        metrics.record_run_finished("succeeded", STARTED, STARTED)


# --- worker endpoint ------------------------------------------------------------------------


@pytest.fixture
def serve() -> Iterator[Any]:
    servers: list[Any] = []

    def start() -> str:
        server = metrics.start_worker_metrics_server(0, addr="127.0.0.1")
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}/metrics"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_worker_endpoint_serves_the_worker_registry(serve: Any) -> None:
    metrics.record_event("hr", "tool_result", {"name": "list_tables", "ok": True})

    body = httpx.get(serve()).text

    assert 'dap_tool_calls_total{outcome="ok",tool="list_tables"}' in body
    assert "dap_runs_created_total" not in body


def test_worker_endpoint_aggregates_child_processes_in_multiprocess_mode(
    serve: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two "pool children" write their samples to the directory; the parent serves the sum."""
    child = textwrap.dedent(
        """
        from datetime import UTC, datetime, timedelta
        from dap.observability import metrics
        t0 = datetime(2026, 11, 19, tzinfo=UTC)
        metrics.record_event("sales", "tool_result", {"name": "run_sql", "ok": False})
        metrics.record_event(
            "sales",
            "llm_call",
            {"model": "m", "prompt_tokens": 10, "completion_tokens": 2, "cost_usd": 0.5},
        )
        metrics.record_run_finished("succeeded", t0, t0 + timedelta(seconds=3))
        """
    )
    env = {"PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}
    for _ in range(2):
        subprocess.run(
            [sys.executable, "-c", child],
            cwd=BACKEND_DIR,
            env={**_inherited_env(), **env},
            check=True,
        )
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

    body = httpx.get(serve()).text

    assert 'dap_tool_calls_total{outcome="error",tool="run_sql"} 2.0' in body
    assert 'dap_llm_tokens_total{direction="prompt",model="m"} 20.0' in body
    assert 'dap_llm_cost_usd_total{team="sales"} 1.0' in body
    assert 'dap_runs_finished_total{status="succeeded"} 2.0' in body
    assert "dap_run_duration_seconds_sum 6.0" in body


def _inherited_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "PROMETHEUS_MULTIPROC_DIR"}


def test_mark_process_dead_is_a_noop_without_multiprocess_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    metrics.mark_process_dead(12345)


def test_mark_process_dead_removes_the_dead_process_live_gauge_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    live = tmp_path / "gauge_livesum_12345.db"
    counter = tmp_path / "counter_12345.db"
    live.touch()
    counter.touch()

    metrics.mark_process_dead(12345)

    assert not live.exists()
    assert counter.exists()  # a dead child's counts stay in the totals
