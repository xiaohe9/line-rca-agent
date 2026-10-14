"""Liveness plus a self-description the frontend can render without extra calls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from line_rca_agent.trace import SCHEMA_VERSION
from line_rca_api.deps import KernelDep, SettingsDep

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(settings: SettingsDep, kernel: KernelDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "env": settings.env,
        "demoMode": settings.demo_mode,
        "provider": settings.llm_provider,
        "orchestrator": {"planner": kernel.planner.name, "executor": kernel.executor.name},
        "tools": kernel.tools.names(),
        "maxSteps": kernel.max_steps,
        "traceSchemaVersion": SCHEMA_VERSION,
    }


@router.get("/config")
async def public_config(settings: SettingsDep) -> dict[str, Any]:
    """Everything the frontend is allowed to know. Never returns credentials."""
    return {
        "env": settings.env,
        "demoMode": settings.demo_mode,
        "traceSchemaVersion": SCHEMA_VERSION,
    }
