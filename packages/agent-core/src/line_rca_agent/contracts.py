"""The seams of the kernel: every collaborator is a `Protocol`, never a concrete class.

Keeping these structural (not nominal) means an adapter in `apps/api` can satisfy them
without importing the kernel, and tests can substitute trivial doubles.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
#  LLM conversation primitives
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Completion:
    """One LLM turn: free text, tool calls, or both."""

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


# --------------------------------------------------------------------------- #
#  Goal / plan / step
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Goal:
    text: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    description: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Plan:
    steps: tuple[Step, ...]
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StepResult:
    """What one executor turn produced.

    Deliberately carries the tool call *and* the observation instead of emitting trace
    events itself: the kernel owns the event stream, the executor stays a pure function
    of (goal, plan, history). That is what makes executors swappable and unit-testable.
    """

    step_id: str
    ok: bool
    thought: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    finished: bool = False
    answer: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryItem:
    key: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Protocols — the replaceable parts
# --------------------------------------------------------------------------- #


@runtime_checkable
class LLMProvider(Protocol):
    """A chat model. `fake` is a first-class implementation, not a test hack."""

    name: str

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] = (),
    ) -> Completion: ...


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the arguments. Shared with the MCP descriptor."""
        ...

    async def run(self, arguments: dict[str, Any]) -> ToolResult: ...


@runtime_checkable
class ToolRegistry(Protocol):
    def get(self, name: str) -> Tool | None: ...
    def names(self) -> list[str]: ...
    def schemas(self) -> list[dict[str, Any]]: ...


@runtime_checkable
class Memory(Protocol):
    async def write(self, item: MemoryItem) -> None: ...
    async def recall(self, query: str, *, limit: int = 5) -> list[MemoryItem]: ...


@runtime_checkable
class Planner(Protocol):
    name: str

    async def plan(self, goal: Goal, *, context: str = "") -> Plan: ...


@runtime_checkable
class Executor(Protocol):
    name: str

    async def step(
        self,
        goal: Goal,
        plan: Plan,
        history: Sequence[StepResult],
    ) -> StepResult: ...
