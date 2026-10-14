"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from line_rca_agent.kernel import AgentKernel
from line_rca_api.agent_factory import build_kernel
from line_rca_api.config import Settings, get_settings
from line_rca_api.db.session import sessionmaker_for

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def provide_session(settings: SettingsDep) -> AsyncIterator[AsyncSession]:
    if not settings.database_url:
        raise RuntimeError(
            "LRC_DATABASE_URL is not configured. Start the stack with `docker compose up -d` "
            "or point the variable at a Postgres instance."
        )
    async with sessionmaker_for(settings.database_url)() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(provide_session)]


@dataclass(frozen=True, slots=True)
class AgentRuntime:
    """One request's agent, plus the run id its tools have been told about.

    The run id is created here rather than inside the kernel so that a work order written
    during this run can record which run recommended it — which is what makes the
    recommendation auditable after the fact.
    """

    kernel: AgentKernel
    run_id: str


async def provide_runtime(settings: SettingsDep, session: SessionDep) -> AgentRuntime:
    run_id = f"run-{uuid4().hex[:12]}"
    return AgentRuntime(
        kernel=build_kernel(settings, session, run_id=run_id),
        run_id=run_id,
    )


RuntimeDep = Annotated[AgentRuntime, Depends(provide_runtime)]
