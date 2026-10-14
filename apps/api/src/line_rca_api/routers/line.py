"""Read-only views over the line data, for the UI and for humans poking at the API.

These are deliberately thin: the agent's tools are the interesting path, and the UI needs a
way to show what the agent was looking at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from line_rca_api.db.repositories import SqlDefectRepository, SqlWorkOrderRepository
from line_rca_api.deps import SessionDep

router = APIRouter(prefix="/api", tags=["line"])


@router.get("/batches")
async def list_batches(
    session: SessionDep,
    limit: int = Query(6, ge=1, le=50),
) -> dict[str, Any]:
    batches = await SqlDefectRepository(session).recent_batches(limit=limit)
    return {
        "batches": [
            {
                "batchId": batch.batch_id,
                "product": batch.product,
                "units": batch.units,
                "defects": batch.defects,
                "defectRate": round(batch.defect_rate, 4),
                "producedAt": batch.produced_at.isoformat(),
                "source": batch.source,
            }
            for batch in batches
        ]
    }


@router.get("/batches/{batch_id}/defects")
async def batch_defects(batch_id: str, session: SessionDep) -> dict[str, Any]:
    repo = SqlDefectRepository(session)
    summary = await repo.batch_summary(batch_id)
    if summary is None:
        return {"batchId": batch_id, "found": False, "defects": []}
    breakdown = await repo.defect_breakdown(batch_id)
    return {
        "batchId": batch_id,
        "found": True,
        "defectRate": round(summary.defect_rate, 4),
        "units": summary.units,
        "defects": summary.defects,
        "breakdown": [
            {"station": item.station, "defectType": item.defect_type, "count": item.count}
            for item in breakdown
        ],
    }


@router.get("/workorders")
async def list_work_orders(
    session: SessionDep,
    status: str | None = Query(None, pattern="^(open|in_progress|closed)$"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    orders = await SqlWorkOrderRepository(session).list_recent(status=status, limit=limit)
    return {
        "workOrders": [
            {
                "id": order.id,
                "batchId": order.batch_id,
                "station": order.station,
                "symptom": order.symptom,
                "rootCause": order.root_cause,
                "action": order.action,
                "priority": order.priority,
                "status": order.status,
                "createdAt": _iso(order.created_at),
            }
            for order in orders
        ]
    }


def _iso(value: datetime) -> str:
    return value.isoformat()
