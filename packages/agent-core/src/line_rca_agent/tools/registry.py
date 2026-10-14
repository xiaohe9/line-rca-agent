"""Tool registry.

`FunctionTool` exists so a tool definition is one readable expression, and so that a tool
failure becomes an observation the agent can react to instead of an exception that kills
the run. The JSON Schema returned here is the same description a future MCP server will
advertise, so the local tool set and the MCP tool set cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from line_rca_agent.contracts import Tool, ToolResult

ToolHandler = Callable[[dict[str, Any]], Awaitable[ToolResult]]


class FunctionTool:
    """Adapts an async function into the `Tool` protocol."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        self.name = name
        self.description = description
        self._input_schema = input_schema
        self._handler = handler

    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            return await self._handler(arguments)
        except Exception as exc:  # noqa: BLE001 - a broken tool must not kill the run
            return ToolResult(
                ok=False,
                content=f"tool '{self.name}' raised {type(exc).__name__}: {exc}",
                error=str(exc),
            )


class InMemoryToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {tool.name: tool for tool in tools}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema(),
            }
            for tool in self._tools.values()
        ]

    def __len__(self) -> int:
        return len(self._tools)


def build_registry(tools: Sequence[Tool]) -> InMemoryToolRegistry:
    return InMemoryToolRegistry(tools)
