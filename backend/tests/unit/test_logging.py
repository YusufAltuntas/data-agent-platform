"""JSON logs (design §9): every line is one JSON object; lines of a run carry its ids."""

import io
import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from dap.observability.logging import configure_logging, run_context

RUN_ID = uuid.UUID("0f6c2a8e-6d1b-4a57-9a43-1c2d3e4f5a6b")


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    """Configured logging into a buffer; the root logger is restored afterwards."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    uvicorn = logging.getLogger("uvicorn.access")
    uvicorn_state = (list(uvicorn.handlers), uvicorn.propagate)
    stream = io.StringIO()
    configure_logging(stream=stream)
    yield stream
    root.handlers[:] = handlers
    root.setLevel(level)
    uvicorn.handlers[:], uvicorn.propagate = uvicorn_state
    structlog.reset_defaults()


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_stdlib_records_come_out_as_json(stream: io.StringIO) -> None:
    logging.getLogger("dap.worker.runner").warning("run %s failed", "abc")

    [line] = _lines(stream)
    assert line["event"] == "run abc failed"
    assert (line["level"], line["logger"]) == ("warning", "dap.worker.runner")
    assert "timestamp" in line


def test_structlog_records_come_out_as_json(stream: io.StringIO) -> None:
    structlog.get_logger("dap.api").info("started", port=8000)

    [line] = _lines(stream)
    assert (line["event"], line["port"], line["level"]) == ("started", 8000, "info")


def test_lines_inside_a_run_carry_run_id_and_trace_id(stream: io.StringIO) -> None:
    logger = logging.getLogger("dap.worker.runner")
    with run_context(RUN_ID, RUN_ID.hex):
        logger.info("inside")
    logger.info("after")

    inside, after = _lines(stream)
    assert (inside["run_id"], inside["trace_id"]) == (str(RUN_ID), RUN_ID.hex)
    assert "run_id" not in after
    assert "trace_id" not in after


def test_without_tracing_only_run_id_is_bound(stream: io.StringIO) -> None:
    with run_context(RUN_ID, None):
        logging.getLogger("dap.worker.runner").info("inside")

    [line] = _lines(stream)
    assert line["run_id"] == str(RUN_ID)
    assert "trace_id" not in line


def test_exceptions_are_rendered_into_the_json_line(stream: io.StringIO) -> None:
    try:
        raise RuntimeError("bug")
    except RuntimeError:
        logging.getLogger("dap.worker.runner").exception("run failed")

    [line] = _lines(stream)
    assert "RuntimeError: bug" in line["exception"]


def test_library_loggers_with_own_handlers_go_through_the_json_formatter() -> None:
    access = logging.getLogger("uvicorn.access")
    handlers, propagate = list(access.handlers), access.propagate
    access.addHandler(logging.NullHandler())
    access.propagate = False
    root = logging.getLogger()
    root_handlers, level = list(root.handlers), root.level
    stream = io.StringIO()
    try:
        configure_logging(stream=stream)
        configure_logging(stream=stream)  # configuring twice installs one handler, not two
        access.info("GET /api/healthz 200")
    finally:
        root.handlers[:] = root_handlers
        root.setLevel(level)
        access.handlers[:], access.propagate = handlers, propagate
        structlog.reset_defaults()

    [line] = _lines(stream)
    assert (line["event"], line["logger"]) == ("GET /api/healthz 200", "uvicorn.access")
