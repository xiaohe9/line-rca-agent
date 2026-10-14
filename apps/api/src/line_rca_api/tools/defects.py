"""Defect-distribution tool."""

from __future__ import annotations

from typing import Any

from line_rca_agent.contracts import Tool, ToolResult
from line_rca_agent.tools import FunctionTool
from line_rca_api.db.repositories import DefectRepository

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "batch": {"type": "string", "description": "batch id, for example B-2041"},
    },
    "required": ["batch"],
    "additionalProperties": False,
}


async def _query_defects(repo: DefectRepository, arguments: dict[str, Any]) -> ToolResult:
    batch_id = str(arguments.get("batch", "")).strip()
    if not batch_id:
        return ToolResult(
            ok=False, content="missing required field: batch", error="invalid_arguments"
        )

    summary = await repo.batch_summary(batch_id)
    if summary is None:
        known = ", ".join(item.batch_id for item in await repo.recent_batches(limit=6))
        return ToolResult(
            ok=False,
            content=f"no batch '{batch_id}' on record. known batches: {known or '(none)'}",
            error="unknown_batch",
        )

    breakdown = await repo.defect_breakdown(batch_id)
    lines = [
        f"batch={summary.batch_id} product={summary.product} units={summary.units} "
        f"defects={summary.defects} defectRate={summary.defect_rate:.2%}",
        "defects by station and type (descending):",
    ]
    lines.extend(
        f"  - {item.station} / {item.defect_type} / {item.count}" for item in breakdown[:6]
    )
    if summary.source != "production":
        lines.append(f"(source: {summary.source} dataset — not real production data)")

    return ToolResult(
        ok=True,
        content="\n".join(lines),
        data={
            "batchId": summary.batch_id,
            "units": summary.units,
            "defects": summary.defects,
            "defectRate": round(summary.defect_rate, 4),
            "breakdown": [
                {"station": item.station, "defectType": item.defect_type, "count": item.count}
                for item in breakdown[:6]
            ],
        },
    )


def build_defect_tools(repo: DefectRepository) -> list[Tool]:
    return [
        FunctionTool(
            name="query_defects",
            description=(
                "Defect distribution for one production batch: overall defect rate plus the "
                "breakdown by station and defect type. Use this to locate where a yield loss "
                "is concentrated."
            ),
            input_schema=SCHEMA,
            handler=lambda arguments: _query_defects(repo, arguments),
        )
    ]
