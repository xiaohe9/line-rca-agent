"""The agent surface: a streaming run, a collected run, and the tool catalogue.

Two shapes of the same execution on purpose:

* `POST /api/analyze` streams SSE frames — this is what the UI's reasoning timeline renders.
* `POST /api/analyze/collect` returns the identical event list as JSON — this is what the
  evaluation harness and the tests consume, so neither has to parse a stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from line_rca_agent.contracts import Goal
from line_rca_api.deps import KernelDep

router = APIRouter(prefix="/api", tags=["agent"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Stops nginx (and Cloudflare Tunnel) from buffering the stream into silence.
    "X-Accel-Buffering": "no",
}


class AnalyzeRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000, description="The question to investigate.")
    context: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools")
async def list_tools(kernel: KernelDep) -> dict[str, Any]:
    return {"tools": kernel.tools.schemas()}


@router.post("/analyze")
async def analyze(request: AnalyzeRequest, kernel: KernelDep) -> StreamingResponse:
    goal = Goal(text=request.goal, context=request.context)

    async def frames() -> AsyncIterator[str]:
        async for event in kernel.run(goal):
            yield event.to_sse()

    return StreamingResponse(frames(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/analyze/collect")
async def analyze_collect(request: AnalyzeRequest, kernel: KernelDep) -> dict[str, Any]:
    goal = Goal(text=request.goal, context=request.context)
    events = [event.to_dict() async for event in kernel.run(goal)]
    answer = next(
        (event["payload"].get("text") for event in events if event["type"] == "answer"),
        None,
    )
    failed = next((event for event in events if event["type"] == "run.failed"), None)
    return {
        "goal": request.goal,
        "events": events,
        "answer": answer,
        "failed": failed["payload"] if failed else None,
    }
