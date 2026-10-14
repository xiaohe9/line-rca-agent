"""Kernel behaviour: the trace sequence is the product, so it is what gets asserted."""

from __future__ import annotations

import json

from line_rca_agent.contracts import Goal, ToolResult
from line_rca_agent.executors import ReActExecutor
from line_rca_agent.kernel import AgentKernel
from line_rca_agent.memory import WorkingMemory
from line_rca_agent.planners import PlanExecutePlanner
from line_rca_agent.providers import ScriptedProvider, tool_call
from line_rca_agent.tools import FunctionTool, InMemoryToolRegistry
from line_rca_agent.trace import InMemoryTraceSink

PLAN_JSON = json.dumps(
    {
        "rationale": "check the defect distribution first, it discriminates cheapest",
        "steps": [
            {
                "id": "s1",
                "description": "pull defect distribution for the batch",
                "tool": "defects",
            },
            {"id": "s2", "description": "compare against the previous batch", "tool": None},
        ],
    }
)


async def _defects(arguments: dict[str, object]) -> ToolResult:
    return ToolResult(
        ok=True,
        content=f"batch={arguments.get('batch')} scratch_rate=0.41 top=划伤",
        data={"scratch_rate": 0.41},
    )


def _defects_tool() -> FunctionTool:
    return FunctionTool(
        name="defects",
        description="defect distribution for a batch",
        input_schema={
            "type": "object",
            "properties": {"batch": {"type": "string"}},
            "required": ["batch"],
        },
        handler=_defects,
    )


def _kernel(
    provider: ScriptedProvider, *, max_steps: int = 8
) -> tuple[AgentKernel, InMemoryTraceSink]:
    sink = InMemoryTraceSink()
    tools = InMemoryToolRegistry([_defects_tool()])
    kernel = AgentKernel(
        planner=PlanExecutePlanner(provider),
        executor=ReActExecutor(provider, tools),
        tools=tools,
        memory=WorkingMemory(),
        sink=sink,
        max_steps=max_steps,
    )
    return kernel, sink


async def _collect(kernel: AgentKernel, goal: Goal) -> list[dict[str, object]]:
    return [event.to_dict() async for event in kernel.run(goal)]


async def test_happy_path_event_sequence() -> None:
    provider = ScriptedProvider(
        [
            PLAN_JSON,
            tool_call("defects", batch="B-2041"),
            "根因：镀膜工序划伤，证据是 B-2041 划伤占比 41%。建议检查传送带夹具。",
        ]
    )
    kernel, sink = _kernel(provider)

    events = await _collect(kernel, Goal(text="为什么 B-2041 批次良率下降？"))
    types = [event["type"] for event in events]

    assert types == [
        "run.started",
        "plan.created",
        "step.started",
        "tool.called",
        "tool.result",
        "step.started",
        "thought",
        "answer",
        "run.finished",
    ]
    # Sequence numbers are the frontend's ordering guarantee.
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    # Every event is schema-versioned, and the sink saw exactly what was yielded.
    assert {event["schema_version"] for event in events} == {"1"}
    assert sink.types() == types

    plan_event = next(event for event in events if event["type"] == "plan.created")
    assert len(plan_event["payload"]["steps"]) == 2  # type: ignore[index]

    tool_result = next(event for event in events if event["type"] == "tool.result")
    assert tool_result["payload"]["ok"] is True  # type: ignore[index]
    assert "0.41" in tool_result["payload"]["observation"]  # type: ignore[index]

    answer = next(event for event in events if event["type"] == "answer")
    assert "镀膜" in answer["payload"]["text"]  # type: ignore[index]


async def test_finished_run_is_written_to_memory() -> None:
    provider = ScriptedProvider([PLAN_JSON, "done: 根因是划伤"])
    memory = WorkingMemory()
    tools = InMemoryToolRegistry([_defects_tool()])
    kernel = AgentKernel(
        planner=PlanExecutePlanner(provider),
        executor=ReActExecutor(provider, tools),
        tools=tools,
        memory=memory,
    )

    await _collect(kernel, Goal(text="良率为什么下降"))

    assert len(memory) == 1
    recalled = await memory.recall("良率为什么下降")
    assert recalled and "划伤" in recalled[0].content


async def test_unknown_tool_becomes_an_observation_not_a_crash() -> None:
    provider = ScriptedProvider(
        [
            PLAN_JSON,
            tool_call("teleport", batch="B-1"),
            "我无法用现有工具验证，缺少遥测数据。",
        ]
    )
    kernel, _ = _kernel(provider)

    events = await _collect(kernel, Goal(text="良率下降"))
    failed = next(event for event in events if event["type"] == "tool.result")

    assert failed["payload"]["ok"] is False  # type: ignore[index]
    assert "unknown tool 'teleport'" in failed["payload"]["observation"]  # type: ignore[index]
    assert "defects" in failed["payload"]["observation"]  # type: ignore[index]
    assert events[-1]["type"] == "run.finished"


async def test_step_budget_is_enforced() -> None:
    provider = ScriptedProvider(
        [PLAN_JSON, tool_call("defects", batch="B-1")],
        repeat_last=True,
    )
    kernel, _ = _kernel(provider, max_steps=2)

    events = await _collect(kernel, Goal(text="良率下降"))

    assert events[-1]["type"] == "run.failed"
    assert events[-1]["payload"]["stage"] == "budget"  # type: ignore[index]
    assert sum(1 for event in events if event["type"] == "step.started") == 2


async def test_planner_failure_is_reported_as_an_event() -> None:
    kernel, _ = _kernel(ScriptedProvider([]))

    events = await _collect(kernel, Goal(text="良率下降"))

    assert [event["type"] for event in events] == ["run.started", "run.failed"]
    assert events[-1]["payload"]["stage"] == "plan"  # type: ignore[index]
    assert "RuntimeError" in events[-1]["payload"]["error"]  # type: ignore[index]


async def test_events_serialise_to_sse_frames() -> None:
    provider = ScriptedProvider([PLAN_JSON, "根因是划伤"])
    kernel, _ = _kernel(provider)

    events = [event async for event in kernel.run(Goal(text="良率下降"))]
    frames = [event.to_sse() for event in events]

    assert frames[0].startswith("event: run.started\n")
    assert frames[0].endswith("\n\n")
    payload = json.loads(frames[0].split("data: ", 1)[1].strip())
    assert payload["schema_version"] == "1"
    assert payload["run_id"].startswith("run-")


def test_parse_plan_degrades_gracefully() -> None:
    from line_rca_agent.planners import parse_plan

    # Well-formed JSON.
    plan = parse_plan(PLAN_JSON)
    assert [step.id for step in plan.steps] == ["s1", "s2"]
    assert plan.steps[1].tool is None

    # Fenced JSON, as models usually emit it.
    fenced = parse_plan(f"```json\n{PLAN_JSON}\n```")
    assert fenced.steps[0].description == "pull defect distribution for the batch"

    # Prose instead of JSON: degrade to a single step carrying the raw text.
    prose = parse_plan("先查缺陷分布，再对比上一批次。")
    assert len(prose.steps) == 1
    assert prose.steps[0].description == "先查缺陷分布，再对比上一批次。"
    assert prose.rationale.startswith("fallback")

    # Structurally valid JSON with no usable steps must not yield an empty plan.
    empty = parse_plan('{"rationale": "x", "steps": []}')
    assert len(empty.steps) == 1
    assert empty.rationale.startswith("fallback")

    # Empty input still produces an executable plan.
    assert len(parse_plan("").steps) == 1
