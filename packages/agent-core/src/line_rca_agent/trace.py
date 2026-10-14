"""The trace event contract.

This is the interface the whole product hangs off: the Web UI's reasoning timeline, the
SSE stream and the exported report all consume exactly these events. It is versioned so
the frontend can pin to a schema instead of guessing at backend structures.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

SCHEMA_VERSION = "1"


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    PLAN_CREATED = "plan.created"
    STEP_STARTED = "step.started"
    THOUGHT = "thought"
    TOOL_CALLED = "tool.called"
    TOOL_RESULT = "tool.result"
    GUARDRAIL_BLOCKED = "guardrail.blocked"
    MEMORY_RECALLED = "memory.recalled"
    ANSWER = "answer"
    RUN_FINISHED = "run.finished"
    RUN_FAILED = "run.failed"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    run_id: str
    seq: int
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = str(self.type)
        return data

    def to_sse(self) -> str:
        """Encode as one Server-Sent Events frame: `event:` name + JSON `data:`."""
        body = json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.type}\ndata: {body}\n\n"


@runtime_checkable
class TraceSink(Protocol):
    async def emit(self, event: TraceEvent) -> None: ...


class NullTraceSink:
    """Discards everything. Useful in unit tests that assert on results, not events."""

    async def emit(self, event: TraceEvent) -> None:
        return None


class InMemoryTraceSink:
    """Keeps every event so tests can assert on the exact sequence."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [str(e.type) for e in self.events]


class StdoutTraceSink:
    """One JSON object per line — greppable in dev, friendly to `jq`."""

    def __init__(self, stream: Any | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    async def emit(self, event: TraceEvent) -> None:
        self._stream.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        self._stream.flush()


class FanOutTraceSink:
    """Fans one event out to many sinks; one failing sink never breaks the run."""

    def __init__(self, *sinks: TraceSink) -> None:
        self._sinks = list(sinks)
        self.failures: list[str] = []

    async def emit(self, event: TraceEvent) -> None:
        for sink in self._sinks:
            try:
                await sink.emit(event)
            except Exception as exc:  # noqa: BLE001 - observability must never break a run
                self.failures.append(f"{type(sink).__name__}: {exc}")
