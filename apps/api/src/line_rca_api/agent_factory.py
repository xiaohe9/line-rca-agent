"""Composition root: the one place that turns settings into a wired kernel.

Everything above this line depends on `Protocol`s; everything below is a concrete choice.
This is what makes `LRC_LLM_PROVIDER=fake` (offline demo, CI) and a real provider the same
code path with a different injection — no conditionals inside the kernel.
"""

from __future__ import annotations

from line_rca_agent.contracts import LLMProvider
from line_rca_agent.executors import ReActExecutor
from line_rca_agent.kernel import AgentKernel
from line_rca_agent.memory import WorkingMemory
from line_rca_agent.planners import PlanExecutePlanner
from line_rca_agent.providers import ScriptedProvider
from line_rca_agent.tools import InMemoryToolRegistry
from line_rca_agent.trace import NullTraceSink, StdoutTraceSink, TraceSink
from line_rca_api.config import Settings
from line_rca_api.demo import demo_script, register_demo_tools


class NotYetImplementedError(RuntimeError):
    """A configuration option that is planned but not wired up yet."""


def build_trace_sink(settings: Settings) -> TraceSink:
    match settings.trace_sink:
        case "null":
            return NullTraceSink()
        case "stdout":
            return StdoutTraceSink()
        case other:
            # Deliberately loud: silently downgrading observability in production would be
            # worse than failing to start.
            raise NotYetImplementedError(
                f"trace sink '{other}' is not wired up yet (planned for M5); "
                "use 'stdout' or 'null'."
            )


def build_provider(settings: Settings) -> LLMProvider:
    match settings.llm_provider:
        case "fake":
            return ScriptedProvider(demo_script())
        case other:
            raise NotYetImplementedError(
                f"LLM provider '{other}' is not wired up yet (planned for M3). "
                "Set LRC_LLM_PROVIDER=fake or LRC_DEMO_MODE=1 to run offline."
            )


def build_kernel(settings: Settings) -> AgentKernel:
    provider = build_provider(settings)
    tools = register_demo_tools(InMemoryToolRegistry())
    return AgentKernel(
        planner=PlanExecutePlanner(provider),
        executor=ReActExecutor(provider, tools),
        tools=tools,
        memory=WorkingMemory(),
        sink=build_trace_sink(settings),
        max_steps=settings.agent_max_steps,
    )
