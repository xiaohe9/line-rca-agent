"""The seams must hold: doubles satisfy the Protocols, and the kernel stays framework-free.

The import test is intentionally a real assertion rather than documentation: it is what
stops someone from quietly importing FastAPI into the kernel six weeks from now.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from line_rca_agent.contracts import (
    Executor,
    LLMProvider,
    Memory,
    Planner,
    Tool,
    ToolRegistry,
    ToolResult,
)
from line_rca_agent.executors import ReActExecutor
from line_rca_agent.memory import WorkingMemory
from line_rca_agent.planners import PlanExecutePlanner
from line_rca_agent.providers import ScriptedProvider
from line_rca_agent.tools import FunctionTool, InMemoryToolRegistry

SRC = Path(__file__).resolve().parents[1] / "src" / "line_rca_agent"

#: Anything here would couple the kernel to a framework or a vendor SDK.
FORBIDDEN_ROOTS = {
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "psycopg",
    "httpx",
    "httpx2",
    "openai",
    "langchain",
    "langchain_core",
    "langgraph",
    "mcp",
    "pydantic",
    "pydantic_settings",
}


async def _noop_handler(arguments: dict[str, object]) -> ToolResult:
    return ToolResult(ok=True, content="ok")


def _make_tool() -> Tool:
    return FunctionTool(
        name="noop",
        description="does nothing",
        input_schema={"type": "object", "properties": {}},
        handler=_noop_handler,
    )


def test_doubles_satisfy_their_protocols() -> None:
    provider = ScriptedProvider([])
    registry = InMemoryToolRegistry([_make_tool()])

    assert isinstance(provider, LLMProvider)
    assert isinstance(registry, ToolRegistry)
    assert isinstance(WorkingMemory(), Memory)
    assert isinstance(PlanExecutePlanner(provider), Planner)
    assert isinstance(ReActExecutor(provider, registry), Executor)
    assert isinstance(_make_tool(), Tool)


def test_registry_schema_shape_is_mcp_compatible() -> None:
    registry = InMemoryToolRegistry([_make_tool()])
    schema = registry.schemas()[0]

    assert schema["name"] == "noop"
    assert schema["description"] == "does nothing"
    assert schema["inputSchema"]["type"] == "object"


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module_path", sorted(SRC.rglob("*.py")), ids=lambda p: p.name)
def test_kernel_never_imports_a_framework(module_path: Path) -> None:
    offenders = _imported_roots(module_path) & FORBIDDEN_ROOTS
    assert not offenders, (
        f"{module_path.relative_to(SRC)} imports {sorted(offenders)}; "
        "the kernel must stay framework-free (see docs/adr/0001)."
    )
