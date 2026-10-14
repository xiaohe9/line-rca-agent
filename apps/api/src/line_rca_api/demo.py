"""Demo tool set and scripted conversation.

Two jobs, both deliberate:

1. Tools are registered through the same `FunctionTool` + registry path production tools
   will use, so the demo exercises the real code path rather than a shortcut.
2. The data is **canned and labelled as such** in every observation. It is not real
   production data and nothing here pretends otherwise — the README's data section says
   the same thing.
"""

from __future__ import annotations

import json
from typing import Any

from line_rca_agent.contracts import Completion, ToolResult
from line_rca_agent.providers import tool_call
from line_rca_agent.tools import FunctionTool, InMemoryToolRegistry

DEMO_BATCHES: dict[str, dict[str, Any]] = {
    "B-2041": {
        "scratchRate": 0.41,
        "topDefect": "划伤",
        "station": "镀膜",
        "deltaVsPreviousBatch": 0.37,
    },
    "B-2040": {
        "scratchRate": 0.04,
        "topDefect": "异物",
        "station": "镀膜",
        "deltaVsPreviousBatch": 0.0,
    },
}


def _demo_note() -> str:
    return "(simulated demo dataset — not real production data)"


async def _query_defects(arguments: dict[str, Any]) -> ToolResult:
    batch = str(arguments.get("batch", ""))
    record = DEMO_BATCHES.get(batch)
    if record is None:
        return ToolResult(
            ok=False,
            content=f"no defect record for batch '{batch}'. {_demo_note()}",
            error="unknown_batch",
        )
    return ToolResult(
        ok=True,
        content=f"batch={batch} scratchRate={record['scratchRate']} "
        f"topDefect={record['topDefect']} station={record['station']} {_demo_note()}",
        data=record,
    )


async def _query_telemetry(arguments: dict[str, Any]) -> ToolResult:
    station = str(arguments.get("station", ""))
    return ToolResult(
        ok=True,
        content=f"station={station} temperatureC=71.2 vibrationMm=0.19 beltSpeed=0.98 "
        f"(baseline temperatureC=68.0 vibrationMm=0.06) {_demo_note()}",
        data={"temperatureC": 71.2, "vibrationMm": 0.19, "baselineVibrationMm": 0.06},
    )


def register_demo_tools(registry: InMemoryToolRegistry) -> InMemoryToolRegistry:
    registry.register(
        FunctionTool(
            name="query_defects",
            description="Defect distribution for one production batch.",
            input_schema={
                "type": "object",
                "properties": {"batch": {"type": "string", "description": "batch id, e.g. B-2041"}},
                "required": ["batch"],
                "additionalProperties": False,
            },
            handler=_query_defects,
        )
    )
    registry.register(
        FunctionTool(
            name="query_telemetry",
            description="Equipment telemetry versus baseline for one station.",
            input_schema={
                "type": "object",
                "properties": {"station": {"type": "string", "description": "station name"}},
                "required": ["station"],
                "additionalProperties": False,
            },
            handler=_query_telemetry,
        )
    )
    return registry


DEMO_PLAN = json.dumps(
    {
        "rationale": "cheapest discriminating check is the defect distribution for the batch",
        "steps": [
            {
                "id": "s1",
                "description": "pull the defect distribution for the batch",
                "tool": "query_defects",
            },
            {
                "id": "s2",
                "description": "compare equipment telemetry at the suspect station",
                "tool": "query_telemetry",
            },
        ],
    }
)

DEMO_ANSWER = (
    "根因（最可能）：镀膜工位传送机构异常导致的表面划伤。\n"
    "证据：1) B-2041 划伤占比 41%，上一批次 B-2040 仅 4%，差值 37 个百分点；"
    "2) 镀膜工位振动 0.19 mm，基线 0.06 mm，偏高约 3 倍。\n"
    "建议：停机检查镀膜工位传送夹具与导向轮，复测振动后再投产。\n"
    f"数据来源：{_demo_note()}"
)


def demo_script(
    batch: str = "B-2041", station: str = "镀膜"
) -> list[Completion | str | dict[str, Any]]:
    return [
        DEMO_PLAN,
        tool_call("query_defects", batch=batch),
        tool_call("query_telemetry", station=station),
        DEMO_ANSWER,
    ]
