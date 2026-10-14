"""Plan-and-Execute planner.

One upfront plan, then the executor works through it. The contrast with ReAct (interleaved
thought/action, no upfront plan) is the subject of `docs/adr/0001` — both are implemented
in this kernel and must stay interchangeable.

Planning output is untrusted text, so `parse_plan` degrades gracefully instead of raising:
a malformed plan becomes a single-step plan that carries the raw text, which keeps the run
alive and puts the failure in the trace where it can be seen.
"""

from __future__ import annotations

import json
import re
from typing import Any

from line_rca_agent.contracts import Goal, LLMProvider, Message, Plan, Step

PLAN_SYSTEM_PROMPT = """\
You are the planning half of an industrial root-cause-analysis agent for a production line.

Break the goal into the smallest number of investigation steps that can actually be executed
with the available tools. Rules:
- Each step must be checkable against recorded data; never plan a step that guesses.
- Prefer the step that most cheaply discriminates between competing hypotheses first.
- 2 to 5 steps. Do not pad.

Reply with JSON only, no prose and no code fence:
{"rationale": "<one sentence>", "steps": [{"id": "s1", "description": "<what to check>",
"tool": "<tool name or null>", "arguments": {}}]}
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_plan(text: str) -> Plan:
    """Best-effort parse of a planning reply. Never raises."""
    match = _JSON_BLOCK.search(text)
    if match:
        try:
            payload: Any = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("steps"), list):
            steps: list[Step] = []
            for index, raw in enumerate(payload["steps"], start=1):
                if not isinstance(raw, dict):
                    continue
                raw_arguments = raw.get("arguments")
                arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}
                raw_tool = raw.get("tool")
                steps.append(
                    Step(
                        id=str(raw.get("id") or f"s{index}"),
                        description=str(raw.get("description") or "").strip() or "(unspecified)",
                        tool=str(raw_tool) if raw_tool else None,
                        arguments=arguments,
                    )
                )
            if steps:
                return Plan(steps=tuple(steps), rationale=str(payload.get("rationale") or ""))

    fallback = text.strip()[:400] or "(planner returned nothing)"
    return Plan(
        steps=(Step(id="s1", description=fallback),),
        rationale="fallback: planner output was not valid plan JSON",
    )


class PlanExecutePlanner:
    name = "plan-execute"

    def __init__(self, provider: LLMProvider, *, system_prompt: str = PLAN_SYSTEM_PROMPT) -> None:
        self._provider = provider
        self._system_prompt = system_prompt

    async def plan(self, goal: Goal, *, context: str = "") -> Plan:
        user_parts = [f"Goal: {goal.text}"]
        if goal.context:
            user_parts.append(f"Context: {json.dumps(goal.context, ensure_ascii=False)}")
        if context:
            user_parts.append(f"Relevant past cases:\n{context}")
        messages = [
            Message(role="system", content=self._system_prompt),
            Message(role="user", content="\n\n".join(user_parts)),
        ]
        completion = await self._provider.complete(messages)
        return parse_plan(completion.content)
