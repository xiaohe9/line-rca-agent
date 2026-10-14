"""The agent as a diagnoser, so the evaluation can put it next to the baseline.

The comparison is only worth anything if both sides see the same evidence.

* The **deterministic baseline** receives the two windows as arrays and applies a fixed,
  calibrated threshold to a statistic chosen in advance. Its whole design is that one number.
* The **agent** receives a plain table of per-sensor summaries — median, spread, minimum and
  maximum, for the reference and for the investigation window — with **no ranking, no
  normalisation, and no threshold**. It also gets one query tool, for the case where a sensor
  changed its relationship to its neighbours without changing its level or its spread. It has
  to decide what "anomalous" means.

That asymmetry is the experiment. If planning a comparison is worth anything, it should show up
here; if it is not, the numbers will say so.

One detail decides whether the experiment is even valid: the kernel's planner renders
`Goal.context`, but the ReAct executor does **not** — it builds its prompt from `goal.text`
alone. Evidence placed in `context` would therefore be visible while planning and invisible
while answering. The table goes in `text`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from eval.diagnoser import Diagnosis
from eval.injection import Case, group_of
from line_rca_agent.contracts import Goal, LLMProvider, Tool, ToolResult
from line_rca_agent.executors import ReActExecutor
from line_rca_agent.kernel import AgentKernel
from line_rca_agent.memory import WorkingMemory
from line_rca_agent.planners import PlanExecutePlanner
from line_rca_agent.tools import FunctionTool, InMemoryToolRegistry
from line_rca_agent.trace import NullTraceSink

REPORT_TOOL = "report_root_cause"
NO_FAULT_TOOL = "report_no_fault"
CORRELATION_TOOL = "peer_correlation"
CORRELATION_TABLE_TOOL = "peer_correlation_table"
EPSILON = 1e-9


def _correlation_of(left: np.ndarray, right: np.ndarray) -> float:
    """Pearson r, or 0 when either side does not vary. Never nan."""
    if np.std(left) <= EPSILON or np.std(right) <= EPSILON:
        return 0.0
    value = float(np.corrcoef(left, right)[0, 1])
    return 0.0 if np.isnan(value) else value


def sensor_table(case: Case) -> str:
    """The evidence, as text.

    No ranking and no threshold: those are the baseline's design decisions and the agent has to
    make its own. The derived columns are here because the first version of this table withheld
    them, and the agent then scored **0 of 25 faults, reporting "no fault" on every case**. That
    run measured whether a language model can compute a standard error across 313 rows in its
    head, which is a known no, and had nothing to do with diagnosis. Handing over the same
    per-sensor quantities the baseline computes — and still no threshold, no ranking, and no
    correction for comparing 313 sensors at once — makes the question the interesting one: can
    the agent decide what counts as anomalous, and can it do better than one fixed cutoff.
    """
    reference = case.reference
    window = case.window
    n_reference = reference.shape[0]
    n_window = window.shape[0]
    header = (
        " sensor    ref_med    ref_sd   win_med   win_sd    win_min    win_max"
        "  shift_se  spread  outliers"
    )
    rows = [header]
    for index in range(reference.shape[1]):
        reference_column = reference[:, index]
        window_column = window[:, index]
        reference_median = float(np.median(reference_column))
        reference_sd = float(np.std(reference_column))
        window_median = float(np.median(window_column))
        window_sd = float(np.std(window_column))

        # The standard error of the difference of two medians, which is what makes a shift
        # comparable across sensors with different spreads.
        standard_error = 1.2533 * reference_sd * float(np.sqrt(1.0 / n_window + 1.0 / n_reference))
        shift_in_se = abs(window_median - reference_median) / max(standard_error, EPSILON)
        spread_ratio = window_sd / max(reference_sd, EPSILON)
        spread = abs(np.log(max(spread_ratio, EPSILON)))
        outliers = 0
        if reference_sd > EPSILON:
            outliers = int(np.sum(np.abs(window_column - reference_median) > 8.0 * reference_sd))

        rows.append(
            f"{index:>7}"
            f"{reference_median:>11.4f}"
            f"{reference_sd:>10.4f}"
            f"{window_median:>10.4f}"
            f"{window_sd:>9.4f}"
            f"{float(window_column.min()):>11.4f}"
            f"{float(window_column.max()):>11.4f}"
            f"{shift_in_se:>10.2f}"
            f"{spread:>8.2f}"
            f"{outliers:>10}"
        )
    return "\n".join(rows)


def build_prompt(case: Case) -> str:
    n_sensors = case.reference.shape[1]
    per_group = case.sensors_per_group
    n_groups = group_of(n_sensors - 1, per_group) + 1
    return (
        "A production line has one suspect sensor.\n\n"
        f"INVESTIGATION WINDOW: {case.window.shape[0]} consecutive production entities, "
        "the period under review.\n"
        f"REFERENCE WINDOW: {case.reference.shape[0]} immediately preceding entities from the "
        "same line, during a period known to be good.\n\n"
        f"There are {n_sensors} sensors, numbered 0..{n_sensors - 1}. They belong to subsystems "
        f"of {per_group}, so group = sensor // {per_group} and there are {n_groups} groups.\n\n"
        "Below is every sensor's summary. `shift_se` is the median shift in units of the standard "
        "error of that shift, `spread` is the absolute log ratio of the two standard deviations, "
        "and `outliers` counts window points more than 8 reference deviations from the reference "
        "median. You have **no threshold and no ranking** — deciding what counts as anomalous is "
        "your job, and there are over three hundred sensors, so a value that merely looks large "
        "may just be the largest of many.\n\n"
        f"{sensor_table(case)}\n\n"
        "Decide whether one sensor behaves differently in the investigation window than in the "
        "reference window. A fault can show up as a level shift, a collapsed or inflated "
        "spread, a run of outliers, or a changed relationship to the other sensors in its "
        f"group — call `{CORRELATION_TABLE_TOOL}` for that one, since it never shows up in the "
        f"columns above; `{CORRELATION_TOOL}` gives a single sensor in more detail.\n\n"
        f"Finish by calling exactly one of `{REPORT_TOOL}` or `{NO_FAULT_TOOL}`. Some windows "
        "contain a fault and some do not; report one only when the evidence supports it, and "
        "say so plainly when it does not."
    )


class AgentDiagnoser:
    """Runs the real kernel — Plan-and-Execute planner, ReAct executor — once per case."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        sensors_per_group: int,
        max_steps: int = 8,
        name: str | None = None,
    ) -> None:
        self._provider = provider
        self._sensors_per_group = sensors_per_group
        self._max_steps = max_steps
        self._name = name or f"agent-{provider.name}"
        #: Cases where the provider or the kernel raised. Counted and reported rather than
        #: swallowed, because a run that silently scored failures as "no fault" would look
        #: like a cautious agent instead of a broken one.
        self.failures: list[str] = []
        self.calls = 0
        #: Runs that hit the step limit without ever calling a reporting tool. Tracked
        #: separately because the first real run did exactly this on every case, and the
        #: harness scored it as "the agent saw no fault" — the opposite of what happened.
        self.exhausted = 0
        #: What the agent said and why, per case. Without this a 0% detection rate is a number
        #: with no explanation, and the explanation is the interesting part.
        self.answers: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def threshold(self) -> float:
        """The agent has no threshold. Reported as zero so the harness has something to print."""
        return 0.0

    def _correlation(self, case: Case, sensor: int) -> str:
        group = group_of(sensor, self._sensors_per_group)
        start = group * self._sensors_per_group
        stop = min(start + self._sensors_per_group, case.reference.shape[1])
        if not start <= sensor < stop or stop - start < 2:
            return f"sensor {sensor} has no peers to compare against"

        def peers(matrix: np.ndarray) -> np.ndarray:
            local = sensor - start
            return np.delete(matrix[:, start:stop], local, axis=1).mean(axis=1)

        def correlation(left: np.ndarray, right: np.ndarray) -> float:
            if np.std(left) <= EPSILON or np.std(right) <= EPSILON:
                return 0.0
            value = float(np.corrcoef(left, right)[0, 1])
            return 0.0 if np.isnan(value) else value

        in_reference = correlation(case.reference[:, sensor], peers(case.reference))
        in_window = correlation(case.window[:, sensor], peers(case.window))
        return (
            f"sensor {sensor} (group {group}) correlation with the mean of its "
            f"{stop - start - 1} peers:\n"
            f"  reference {in_reference:+.3f}\n"
            f"  window    {in_window:+.3f}\n"
            f"  change    {abs(in_reference - in_window):.3f}"
        )

    def _correlation_table(self, case: Case) -> str:
        """Every sensor's correlation change, in one table.

        The single-sensor version exists for follow-up, but as the only way to see relationships
        it was a trap: at one sensor per step, surveying the line costs 313 steps, and the first
        real run spent its entire budget on four of them. A fixed test reads the whole matrix at
        once, so the agent has to be able to as well.
        """
        reference = case.reference
        window = case.window
        per_group = self._sensors_per_group
        n_sensors = reference.shape[1]
        rows = [" sensor  corr_ref  corr_win   change"]
        for sensor in range(n_sensors):
            start = (sensor // per_group) * per_group
            stop = min(start + per_group, n_sensors)
            if stop - start < 2:
                rows.append(f"{sensor:>7}       n/a       n/a      n/a")
                continue
            local = sensor - start
            peers_reference = np.delete(reference[:, start:stop], local, axis=1).mean(axis=1)
            peers_window = np.delete(window[:, start:stop], local, axis=1).mean(axis=1)
            in_reference = _correlation_of(reference[:, sensor], peers_reference)
            in_window = _correlation_of(window[:, sensor], peers_window)
            rows.append(
                f"{sensor:>7}{in_reference:>10.3f}{in_window:>10.3f}"
                f"{abs(in_reference - in_window):>9.3f}"
            )
        return "\n".join(rows)

    def _tools(self, case: Case, captured: dict[str, Any]) -> list[Tool]:
        async def correlation_tool(arguments: dict[str, Any]) -> ToolResult:
            raw = arguments.get("sensor")
            if not isinstance(raw, int):
                return ToolResult(ok=False, content="sensor must be an integer", error="bad_args")
            if not 0 <= raw < case.reference.shape[1]:
                return ToolResult(
                    ok=False,
                    content=f"sensor {raw} is out of range 0..{case.reference.shape[1] - 1}",
                    error="out_of_range",
                )
            return ToolResult(ok=True, content=self._correlation(case, raw))

        async def correlation_table_tool(arguments: dict[str, Any]) -> ToolResult:
            return ToolResult(ok=True, content=self._correlation_table(case))

        async def report_tool(arguments: dict[str, Any]) -> ToolResult:
            captured[REPORT_TOOL] = arguments
            return ToolResult(ok=True, content="recorded")

        async def no_fault_tool(arguments: dict[str, Any]) -> ToolResult:
            captured[NO_FAULT_TOOL] = arguments
            return ToolResult(ok=True, content="recorded")

        return [
            FunctionTool(
                name=CORRELATION_TABLE_TOOL,
                description=(
                    "The correlation comparison for every sensor at once, as one table. Use this "
                    "first: querying sensors one at a time costs a step each."
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=correlation_table_tool,
            ),
            FunctionTool(
                name=CORRELATION_TOOL,
                description=(
                    "Pearson correlation between one sensor and the mean of the other sensors in "
                    "its group, computed separately for the reference window and the "
                    "investigation window. Use it when a sensor's level and spread look normal "
                    "but you suspect it stopped tracking its neighbours."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"sensor": {"type": "integer", "description": "sensor index"}},
                    "required": ["sensor"],
                    "additionalProperties": False,
                },
                handler=correlation_tool,
            ),
            FunctionTool(
                name=REPORT_TOOL,
                description=("Record your diagnosis. Call this instead of answering in prose."),
                input_schema={
                    "type": "object",
                    "properties": {
                        "candidates": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": (
                                "subsystem groups you consider most likely, most likely first, "
                                "at most three"
                            ),
                        },
                        "sensor": {
                            "type": "integer",
                            "description": "the single sensor you believe is at fault",
                        },
                        "reasoning": {"type": "string", "description": "why, briefly"},
                    },
                    "required": ["candidates", "sensor", "reasoning"],
                    "additionalProperties": False,
                },
                handler=report_tool,
            ),
            FunctionTool(
                name=NO_FAULT_TOOL,
                description=(
                    "Record that this window looks healthy. Call this instead of answering in "
                    "prose when no sensor stands out."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"reasoning": {"type": "string"}},
                    "required": ["reasoning"],
                    "additionalProperties": False,
                },
                handler=no_fault_tool,
            ),
        ]

    def _record(self, case: Case, reasoning: str, candidates: tuple[int, ...]) -> None:
        self.answers.append(
            {
                "kind": case.fault.kind if case.fault else "control",
                "truthGroup": case.truth_group,
                "reported": list(candidates),
                "reasoning": " ".join(reasoning.split())[:400],
            }
        )

    def _to_diagnosis(self, case: Case, captured: dict[str, Any]) -> Diagnosis:
        n_groups = group_of(case.reference.shape[1] - 1, self._sensors_per_group) + 1
        answer = captured.get(REPORT_TOOL)
        if not isinstance(answer, dict):
            declined = captured.get(NO_FAULT_TOOL)
            self._record(
                case,
                str(declined.get("reasoning", "")) if isinstance(declined, dict) else "",
                (),
            )
            return Diagnosis(ranked_groups=(), scores={}, flagged=False)

        raw = answer.get("candidates")
        candidates = (
            [item for item in raw if isinstance(item, int)] if isinstance(raw, list) else []
        )
        if not candidates:
            sensor = answer.get("sensor")
            if isinstance(sensor, int) and 0 <= sensor < case.reference.shape[1]:
                candidates = [group_of(sensor, self._sensors_per_group)]

        valid = tuple(dict.fromkeys(group for group in candidates if 0 <= group < n_groups))
        self._record(case, str(answer.get("reasoning", "")), valid)
        if not valid:
            return Diagnosis(ranked_groups=(), scores={}, flagged=False)
        return Diagnosis(ranked_groups=valid, scores={}, flagged=True)

    async def _diagnose(self, case: Case) -> Diagnosis:
        captured: dict[str, Any] = {}
        registry = InMemoryToolRegistry(self._tools(case, captured))
        kernel = AgentKernel(
            planner=PlanExecutePlanner(self._provider),
            executor=ReActExecutor(self._provider, registry),
            tools=registry,
            memory=WorkingMemory(),
            sink=NullTraceSink(),
            max_steps=self._max_steps,
        )
        try:
            exhausted = False
            async for event in kernel.run(Goal(text=build_prompt(case))):
                if event.type == "run.failed":
                    exhausted = True
                # Reporting ends the investigation. A real deployment would have opened a work
                # order by now, and leaving the loop running produced an ambiguity that mattered:
                # one trace diagnosed the frozen sensor correctly and then retracted it twice,
                # so "first report wins" and "last report wins" gave different scores. Making the
                # report terminal removes the ambiguity instead of resolving it in either side's
                # favour.
                if event.type == "tool.result" and (
                    REPORT_TOOL in captured or NO_FAULT_TOOL in captured
                ):
                    break
            self.calls += 1
            # A run that reported and then failed to wrap up in prose still produced a
            # diagnosis, so only a run that never reported counts as having run out of steps.
            if exhausted and REPORT_TOOL not in captured and NO_FAULT_TOOL not in captured:
                self.exhausted += 1
                self.failures.append(
                    f"hit the {self._max_steps}-step limit without calling a reporting tool"
                )
        except Exception as exc:  # noqa: BLE001 - one bad call must not end a 50-case run
            self.failures.append(f"{type(exc).__name__}: {exc}")
            return Diagnosis(ranked_groups=(), scores={}, flagged=False)
        return self._to_diagnosis(case, captured)

    def diagnose(self, case: Case) -> Diagnosis:
        # The harness is synchronous and this is the only asynchronous diagnoser, so the loop
        # is created per case. Each completion opens its own client, so nothing is bound to a
        # loop that is about to close.
        return asyncio.run(self._diagnose(case))
