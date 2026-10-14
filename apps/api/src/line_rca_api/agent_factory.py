"""Composition root: the one place that turns settings plus a session into a wired kernel.

Everything above this line depends on `Protocol`s; everything below is a concrete choice.
This is what makes `LRC_LLM_PROVIDER=fake` (offline demo, CI) and a real provider the same
code path with a different injection — no conditionals inside the kernel.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from line_rca_agent.contracts import LLMProvider
from line_rca_agent.executors import ReActExecutor
from line_rca_agent.kernel import AgentKernel
from line_rca_agent.memory import WorkingMemory
from line_rca_agent.planners import PlanExecutePlanner
from line_rca_agent.providers import ScriptedProvider
from line_rca_agent.tools import InMemoryToolRegistry
from line_rca_agent.trace import NullTraceSink, StdoutTraceSink, TraceSink
from line_rca_api.config import Settings
from line_rca_api.db.repositories import (
    SqlDefectRepository,
    SqlTelemetryRepository,
    SqlWorkOrderRepository,
)
from line_rca_api.demo import demo_script
from line_rca_api.providers import OpenAiCompatProvider
from line_rca_api.tools import register_line_tools


class NotYetImplementedError(RuntimeError):
    """A configuration option that is planned but not wired up yet."""


class ConfigurationError(RuntimeError):
    """The selected provider cannot be built from the current settings."""


#: Where each known provider lives by default. `openai_compat` has none on purpose: pointing
#: at an arbitrary compatible endpoint requires saying which one.
DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
    "openai_compat": "",
}

DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "ollama": "",
    "openai_compat": "",
}

#: Local inference needs no credential.
PROVIDERS_WITHOUT_KEYS = frozenset({"ollama"})


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
        case "deepseek" | "openai_compat" | "ollama" as provider:
            base_url = settings.llm_base_url or DEFAULT_BASE_URLS[provider]
            if not base_url:
                raise ConfigurationError(f"LRC_LLM_BASE_URL is required for provider '{provider}'.")
            model = settings.llm_model or DEFAULT_MODELS[provider]
            if not model:
                raise ConfigurationError(f"LRC_LLM_MODEL is required for provider '{provider}'.")
            api_key = settings.resolved_api_key
            if not api_key and provider not in PROVIDERS_WITHOUT_KEYS:
                raise ConfigurationError(
                    f"provider '{provider}' needs a key: set LRC_LLM_API_KEY or DEEPSEEK_API_KEY, "
                    "or use LRC_LLM_PROVIDER=fake to run offline."
                )
            return OpenAiCompatProvider(
                name=provider,
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout=settings.llm_timeout_seconds,
            )
        case other:
            raise ConfigurationError(
                f"unknown LLM provider '{other}'. Use fake, deepseek, openai_compat or ollama."
            )


def build_kernel(
    settings: Settings,
    session: AsyncSession,
    *,
    run_id: str | None = None,
) -> AgentKernel:
    provider = build_provider(settings)
    tools = register_line_tools(
        InMemoryToolRegistry(),
        defects=SqlDefectRepository(session),
        telemetry=SqlTelemetryRepository(session),
        work_orders=SqlWorkOrderRepository(session),
        run_id=run_id,
    )
    return AgentKernel(
        planner=PlanExecutePlanner(provider),
        executor=ReActExecutor(provider, tools),
        tools=tools,
        memory=WorkingMemory(),
        sink=build_trace_sink(settings),
        max_steps=settings.agent_max_steps,
    )
