"""The kernel: composes the replaceable parts and owns the trace event stream.

It is a pure coordinator. It never constructs a provider, tool or memory itself — they
are injected — which is why the same kernel runs against `fake` in CI and `deepseek` in
production without a single conditional.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from line_rca_agent.contracts import (
    Executor,
    Goal,
    Memory,
    MemoryItem,
    Planner,
    StepResult,
    ToolRegistry,
)
from line_rca_agent.trace import EventType, NullTraceSink, TraceEvent, TraceSink


@dataclass(slots=True)
class AgentKernel:
    planner: Planner
    executor: Executor
    tools: ToolRegistry
    memory: Memory
    sink: TraceSink = field(default_factory=NullTraceSink)
    max_steps: int = 12

    async def run(self, goal: Goal, *, run_id: str | None = None) -> AsyncIterator[TraceEvent]:
        """Run to completion, yielding every event as it happens.

        Yielding *and* forwarding to the sink means the API layer can stream straight to
        SSE while the sink independently persists or exports the same events.

        `run_id` may be supplied by the caller so that collaborators built alongside the
        kernel — a work-order tool, for instance — can record which run recommended them.
        The kernel does not need to know why.
        """
        run_id = run_id or f"run-{uuid4().hex[:12]}"
        counter = itertools.count(1)

        async def emit(event_type: EventType, payload: dict[str, object]) -> TraceEvent:
            event = TraceEvent(
                run_id=run_id,
                seq=next(counter),
                type=event_type,
                payload=payload,
                ts=datetime.now(UTC).isoformat(),
            )
            await self.sink.emit(event)
            return event

        yield await emit(
            EventType.RUN_STARTED,
            {
                "goal": goal.text,
                "planner": self.planner.name,
                "executor": self.executor.name,
                "tools": self.tools.names(),
                "maxSteps": self.max_steps,
            },
        )

        recalled = await self.memory.recall(goal.text)
        if recalled:
            yield await emit(
                EventType.MEMORY_RECALLED,
                {"items": [{"key": item.key, "content": item.content} for item in recalled]},
            )
        context = "\n".join(item.content for item in recalled)

        try:
            plan = await self.planner.plan(goal, context=context)
        except Exception as exc:  # noqa: BLE001 - surface any planner failure as an event
            yield await emit(
                EventType.RUN_FAILED,
                {"stage": "plan", "error": f"{type(exc).__name__}: {exc}"},
            )
            return

        yield await emit(
            EventType.PLAN_CREATED,
            {
                "rationale": plan.rationale,
                "steps": [
                    {"id": step.id, "description": step.description, "tool": step.tool}
                    for step in plan.steps
                ],
            },
        )

        history: list[StepResult] = []
        for index in range(1, self.max_steps + 1):
            step_id = f"s{index}"
            yield await emit(
                EventType.STEP_STARTED,
                {"stepId": step_id, "index": index, "plannedSteps": len(plan.steps)},
            )

            try:
                result = await self.executor.step(goal, plan, history)
            except Exception as exc:  # noqa: BLE001
                yield await emit(
                    EventType.RUN_FAILED,
                    {
                        "stage": "execute",
                        "stepId": step_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                return

            if result.thought:
                yield await emit(EventType.THOUGHT, {"stepId": step_id, "text": result.thought})

            if result.tool_name:
                yield await emit(
                    EventType.TOOL_CALLED,
                    {
                        "stepId": step_id,
                        "tool": result.tool_name,
                        "arguments": result.tool_arguments,
                    },
                )
                yield await emit(
                    EventType.TOOL_RESULT,
                    {
                        "stepId": step_id,
                        "tool": result.tool_name,
                        "ok": result.ok,
                        "observation": result.observation,
                    },
                )

            history.append(result)

            if result.finished:
                answer = result.answer or result.observation
                await self.memory.write(
                    MemoryItem(
                        key=run_id,
                        content=f"goal={goal.text}\nanswer={answer}",
                        metadata={"runId": run_id},
                    )
                )
                yield await emit(EventType.ANSWER, {"stepId": step_id, "text": answer})
                yield await emit(
                    EventType.RUN_FINISHED,
                    {"runId": run_id, "steps": len(history), "reason": "answered"},
                )
                return

        yield await emit(
            EventType.RUN_FAILED,
            {"stage": "budget", "error": f"step budget exhausted (max_steps={self.max_steps})"},
        )
