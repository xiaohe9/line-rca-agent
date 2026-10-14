"""ReAct executor: thought -> one tool call -> observation, repeated until answered.

It is a pure function of (goal, plan, history): it does not emit trace events and does not
know the kernel exists. The kernel reconstructs the event stream from the `StepResult`,
which is what keeps this class unit-testable with a scripted provider.

The system prompt carries the anti-hallucination contract that actually matters in a
zero-tolerance industrial setting: no number may appear in an answer unless a tool returned
it, and missing evidence must be named rather than filled in.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from line_rca_agent.contracts import (
    Executor,
    Goal,
    LLMProvider,
    Message,
    Plan,
    StepResult,
    ToolRegistry,
)

REACT_SYSTEM_PROMPT = """\
You are the execution half of an industrial root-cause-analysis agent on a production line.

Work one step at a time:
- Call at most one tool per turn and wait for its observation.
- Every number, batch id, device id or defect type you state must come from a tool result.
  If a tool did not return it, you do not know it — say so instead.
- If the evidence is insufficient to name a root cause, do not guess: state exactly which
  measurement is missing and stop. A refusal is a correct answer.
- When the evidence is sufficient, give a final answer that names the most likely root
  cause, the evidence that supports it, and the recommended action.
"""


def _render_history(history: Sequence[StepResult]) -> str:
    if not history:
        return "(no observations yet)"
    lines: list[str] = []
    for index, item in enumerate(history, start=1):
        if item.tool_name:
            lines.append(
                f"{index}. [{item.tool_name}] "
                f"args={json.dumps(item.tool_arguments, ensure_ascii=False)}"
                f"\n   -> ok={item.ok} {item.observation}"
            )
        else:
            lines.append(f"{index}. (no tool) {item.observation}")
    return "\n".join(lines)


class ReActExecutor:
    name = "react"

    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        *,
        system_prompt: str = REACT_SYSTEM_PROMPT,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._system_prompt = system_prompt

    async def step(
        self,
        goal: Goal,
        plan: Plan,
        history: Sequence[StepResult],
    ) -> StepResult:
        step_id = f"s{len(history) + 1}"
        checklist = "\n".join(f"- {step.id}: {step.description}" for step in plan.steps)
        messages = [
            Message(role="system", content=self._system_prompt),
            Message(
                role="user",
                content=(
                    f"Goal: {goal.text}\n\n"
                    f"Plan:\n{checklist}\n\n"
                    f"Observations so far:\n{_render_history(history)}"
                ),
            ),
        ]

        completion = await self._provider.complete(messages, tools=self._tools.schemas())
        thought = completion.content

        if not completion.tool_calls:
            return StepResult(
                step_id=step_id,
                ok=True,
                thought=thought,
                observation=completion.content,
                finished=True,
                answer=completion.content,
            )

        call = completion.tool_calls[0]
        tool = self._tools.get(call.name)
        if tool is None:
            # Unknown tool is an observation, not a crash: the model gets to correct itself
            # within the kernel's step budget.
            return StepResult(
                step_id=step_id,
                ok=False,
                thought=thought,
                tool_name=call.name,
                tool_arguments=call.arguments,
                observation=(
                    f"unknown tool '{call.name}'. Available tools: {', '.join(self._tools.names())}"
                ),
            )

        result = await tool.run(call.arguments)
        return StepResult(
            step_id=step_id,
            ok=result.ok,
            thought=thought,
            tool_name=call.name,
            tool_arguments=call.arguments,
            observation=result.content,
        )


# Re-exported so callers can type against the Protocol when injecting a double.
__all__ = ["REACT_SYSTEM_PROMPT", "Executor", "ReActExecutor"]
