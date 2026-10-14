"""The `fake` provider: a first-class LLM backend, not a test helper.

It is what makes `LRC_DEMO_MODE=1` real — the whole product runs, streams and produces
trace events with no API key and no network. CI runs against it, and the demo deployment
is the same code path as production with a different provider injected.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from line_rca_agent.contracts import Completion, Message, ToolCall


class ScriptedProvider:
    """Returns pre-scripted completions in order."""

    name = "fake"

    def __init__(
        self,
        script: Sequence[Completion | str | dict[str, Any]],
        *,
        repeat_last: bool = False,
    ) -> None:
        self._script = [self._coerce(item) for item in script]
        self._index = 0
        self._repeat_last = repeat_last
        self.calls: list[tuple[Message, ...]] = []

    @staticmethod
    def _coerce(item: Completion | str | dict[str, Any]) -> Completion:
        if isinstance(item, Completion):
            return item
        if isinstance(item, str):
            return Completion(content=item)
        calls = tuple(
            ToolCall(name=call["name"], arguments=call.get("arguments", {}))
            for call in item.get("tool_calls", [])
        )
        return Completion(content=item.get("content", ""), tool_calls=calls)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] = (),
    ) -> Completion:
        self.calls.append(tuple(messages))
        if self._index >= len(self._script):
            if self._repeat_last and self._script:
                return self._script[-1]
            msg = (
                f"ScriptedProvider exhausted after {len(self._script)} completion(s); "
                "add more script entries or pass repeat_last=True."
            )
            raise RuntimeError(msg)
        item = self._script[self._index]
        self._index += 1
        return item


def tool_call(name: str, **arguments: Any) -> dict[str, Any]:
    """Readable shorthand for scripted tool calls."""
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}]}
