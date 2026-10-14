"""Application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from line_rca_api.config import get_settings
from line_rca_api.routers import analyze, health, line

DESCRIPTION = """\
Industrial production-line root-cause-analysis agent.

Runs offline by default (`LRC_DEMO_MODE=1`): the `fake` LLM provider plus a
**simulated** demo dataset, so the full streaming trace works with no API key.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="line-rca-agent",
        description=DESCRIPTION,
        version="0.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(analyze.router)
    app.include_router(line.router)
    return app


app = create_app()
