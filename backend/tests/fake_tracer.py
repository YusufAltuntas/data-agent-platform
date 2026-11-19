"""An in-memory `Tracer` for tests: it records the spans instead of sending them."""

from dataclasses import dataclass, field
from typing import Any

from dap.observability.tracing import Span


@dataclass
class FakeSpan:
    id: str
    name: str
    input: Any
    trace_id: str
    parent: "FakeSpan | None" = None
    output: Any = None
    error: bool = False
    ended: bool = False
    children: list["FakeSpan"] = field(default_factory=list)

    def start_child(self, name: str, input: Any) -> Span:
        child = FakeSpan(f"{len(self.children) + 1:016x}", name, input, self.trace_id, self)
        self.children.append(child)
        return child

    def end(self, output: Any, *, error: bool = False) -> None:
        assert not self.ended, f"span {self.name} ended twice"
        self.output, self.error, self.ended = output, error, True


class FakeTracer:
    enabled = True

    def __init__(self) -> None:
        self.traces: list[FakeSpan] = []
        self.flushes = 0

    def start_trace(self, trace_id: str, name: str, input: Any) -> Span:
        self.traces.append(FakeSpan("f" * 16, name, input, trace_id))
        return self.traces[-1]

    def flush(self) -> None:
        self.flushes += 1
