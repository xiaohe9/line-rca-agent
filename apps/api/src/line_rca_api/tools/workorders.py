"""Work-order tools: the point where an analysis stops being advice and becomes an action.

`create_work_order` closes over the current `run_id`, so every order it writes is traceable
back to the reasoning that produced it.
"""

from __future__ import annotations

from typing import Any

from line_rca_agent.contracts import Tool, ToolResult
from line_rca_agent.tools import FunctionTool
from line_rca_api.db.repositories import WorkOrderDraft, WorkOrderRepository

PRIORITIES = ("low", "medium", "high")

CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "station": {"type": "string", "description": "station to be serviced"},
        "symptom": {"type": "string", "description": "what was observed, with the numbers"},
        "action": {"type": "string", "description": "what the technician should do"},
        "priority": {"type": "string", "enum": list(PRIORITIES), "default": "medium"},
        "batch": {"type": "string", "description": "affected batch id, if any"},
        "root_cause": {"type": "string", "description": "suspected root cause, if established"},
    },
    "required": ["station", "symptom", "action"],
    "additionalProperties": False,
}

LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["open", "in_progress", "closed"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    },
    "additionalProperties": False,
}

SIMILAR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "symptom or station to search past orders for"},
    },
    "required": ["text"],
    "additionalProperties": False,
}


def _render(record: Any) -> str:
    return (
        f"{record.id} [{record.status}/{record.priority}] station={record.station} "
        f"batch={record.batch_id or '-'}\n"
        f"  symptom: {record.symptom}\n"
        f"  root cause: {record.root_cause or '(not recorded)'}\n"
        f"  action: {record.action}"
    )


async def _create(
    repo: WorkOrderRepository, run_id: str | None, arguments: dict[str, Any]
) -> ToolResult:
    required = ("station", "symptom", "action")
    missing = [name for name in required if not str(arguments.get(name, "")).strip()]
    if missing:
        return ToolResult(
            ok=False,
            content=f"missing required field(s): {', '.join(missing)}",
            error="invalid_arguments",
        )

    priority = str(arguments.get("priority") or "medium")
    if priority not in PRIORITIES:
        priority = "medium"
    batch_id = str(arguments.get("batch") or "").strip() or None
    root_cause = str(arguments.get("root_cause") or "").strip() or None

    record = await repo.create(
        WorkOrderDraft(
            station=str(arguments["station"]).strip(),
            symptom=str(arguments["symptom"]).strip(),
            action=str(arguments["action"]).strip(),
            priority=priority,
            batch_id=batch_id,
            root_cause=root_cause,
            run_id=run_id,
        )
    )
    return ToolResult(
        ok=True,
        content=f"work order created: {_render(record)}\nlinked run: {run_id or '(none)'}",
        data={"workOrderId": record.id, "status": record.status, "runId": run_id},
    )


async def _list(repo: WorkOrderRepository, arguments: dict[str, Any]) -> ToolResult:
    raw_limit = arguments.get("limit", 10)
    limit = raw_limit if isinstance(raw_limit, int) else 10
    status = str(arguments.get("status") or "").strip() or None
    records = await repo.list_recent(status=status, limit=max(1, min(limit, 50)))
    if not records:
        return ToolResult(ok=True, content="no work orders match.", data={"count": 0})
    return ToolResult(
        ok=True,
        content="\n".join(_render(record) for record in records),
        data={"count": len(records), "ids": [record.id for record in records]},
    )


async def _similar(repo: WorkOrderRepository, arguments: dict[str, Any]) -> ToolResult:
    text = str(arguments.get("text", "")).strip()
    if not text:
        return ToolResult(
            ok=False, content="missing required field: text", error="invalid_arguments"
        )
    records = await repo.find_similar(text, limit=3)
    if not records:
        return ToolResult(
            ok=True,
            content=f"no past work order resembles '{text}'.",
            data={"count": 0},
        )
    return ToolResult(
        ok=True,
        content="\n\n".join(_render(record) for record in records),
        data={"count": len(records), "ids": [record.id for record in records]},
    )


def build_work_order_tools(repo: WorkOrderRepository, *, run_id: str | None = None) -> list[Tool]:
    return [
        FunctionTool(
            name="create_work_order",
            description=(
                "Open a maintenance work order. Call this once a root cause and a corrective "
                "action are established; it is how the analysis turns into work on the line."
            ),
            input_schema=CREATE_SCHEMA,
            handler=lambda arguments: _create(repo, run_id, arguments),
        ),
        FunctionTool(
            name="list_work_orders",
            description="List recent work orders, optionally filtered by status.",
            input_schema=LIST_SCHEMA,
            handler=lambda arguments: _list(repo, arguments),
        ),
        FunctionTool(
            name="find_similar_cases",
            description=(
                "Search past work orders for a similar symptom or station. Use this to check "
                "whether the failure mode has been seen and fixed before."
            ),
            input_schema=SIMILAR_SCHEMA,
            handler=lambda arguments: _similar(repo, arguments),
        ),
    ]
