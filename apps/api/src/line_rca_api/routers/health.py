"""Liveness, readiness, and a self-description the frontend can render without extra calls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from line_rca_agent.trace import SCHEMA_VERSION
from line_rca_api.deps import RuntimeDep, SessionDep, SettingsDep

router = APIRouter(tags=["ops"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Process liveness. Touches nothing, so a database blip cannot restart the container."""
    return {"status": "ok"}


@router.get("/health")
async def health(settings: SettingsDep, runtime: RuntimeDep) -> dict[str, Any]:
    """Self-description of the live composition.

    Requires the database on purpose: this API can do nothing useful without it, so
    "database reachable and the agent wired up" is the honest meaning of healthy here.
    Use `/live` when you need to distinguish a dead process from a dead dependency.
    """
    kernel = runtime.kernel
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


@router.get("/ready")
async def ready(session: SessionDep) -> dict[str, Any]:
    """Readiness: can we actually reach the database?"""
    await session.execute(text("select 1"))
    return {"status": "ready"}


@router.get("/config")
async def public_config(settings: SettingsDep) -> dict[str, Any]:
    """Everything the frontend is allowed to know. Never returns credentials."""
    return {
        "env": settings.env,
        "demoMode": settings.demo_mode,
        "traceSchemaVersion": SCHEMA_VERSION,
    }
