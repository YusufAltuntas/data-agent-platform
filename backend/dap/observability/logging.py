"""JSON logs with structlog (design §9), for the API and the worker alike.

structlog loggers and stdlib `logging` records (ours and the libraries') go through the same
JSON formatter on the root logger. Fields bound with `run_context` appear on every line written
inside it, so each line of a run carries `run_id` and `trace_id`.
"""

import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

import structlog
from structlog.typing import Processor

# Loggers that come with their own handlers; they are routed through the root logger instead.
_SELF_HANDLED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class _JsonHandler(logging.StreamHandler[TextIO]):
    """Marks the handler this module installed, so configuring again replaces only it."""


def configure_logging(level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Send every log record to `stream` (stderr by default) as one JSON object per line."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = _JsonHandler(stream or sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h, _JsonHandler)]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)
    for name in _SELF_HANDLED_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


@contextmanager
def run_context(run_id: uuid.UUID, trace_id: str | None) -> Iterator[None]:
    """Bind `run_id` (and `trace_id` when tracing is on) to every log line inside the block."""
    fields = {"run_id": str(run_id)}
    if trace_id is not None:
        fields["trace_id"] = trace_id
    with structlog.contextvars.bound_contextvars(**fields):
        yield
