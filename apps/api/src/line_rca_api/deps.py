"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from line_rca_agent.kernel import AgentKernel
from line_rca_api.agent_factory import build_kernel
from line_rca_api.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def provide_kernel(settings: SettingsDep) -> AgentKernel:
    """A fresh kernel per request.

    Not cached on purpose: the demo provider is scripted and therefore single-use, and once
    persistence lands in M2 each request will want its own memory handle anyway.
    """
    return build_kernel(settings)


KernelDep = Annotated[AgentKernel, Depends(provide_kernel)]
