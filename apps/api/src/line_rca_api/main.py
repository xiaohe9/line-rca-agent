"""Application factory."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from line_rca_api.config import get_settings
from line_rca_api.routers import analyze, health, line

DESCRIPTION = """\
Industrial production-line root-cause-analysis agent.

Runs offline by default (`LRC_DEMO_MODE=1`): the `fake` LLM provider plus a
**simulated** demo dataset, so the full streaming trace works with no API key.
"""


def _mount_web_app(app: FastAPI) -> bool:
    """Serve the built frontend from this process, when one has been provided.

    This is what makes the demo a single container: no second web server, no reverse proxy,
    no CORS between the two halves. The browser talks to one origin either way, so the same
    built bundle works here and behind nginx in the compose stack.

    The mount is deliberately last and guarded: an API-only deployment (the compose stack)
    has no bundle, and the API routes must keep working when it does not.
    """
    directory = Path(os.environ.get("LRC_WEB_DIST", ""))
    index = directory / "index.html"
    if not directory.is_dir() or not index.is_file():
        return False

    # html=True gives the SPA its fallback: an unknown path returns index.html rather than 404,
    # which is what client-side routing needs.
    app.mount("/", StaticFiles(directory=directory, html=True), name="web")
    return True


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
    _mount_web_app(app)
    return app


app = create_app()
