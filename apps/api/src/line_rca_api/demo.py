"""The scripted conversation used by the `fake` provider.

This is what makes `LRC_DEMO_MODE=1` real: no API key, no network, and the *same* tools and
the same trace a live model would produce. The tools read from the database, so the numbers
below come from the seeded simulated dataset rather than from constants in this file.
"""

from __future__ import annotations

import json
from typing import Any

from line_rca_agent.contracts import Completion
from line_rca_agent.providers import tool_call

DEMO_BATCH = "B-2041"
DEMO_STATION = "镀膜"

DEMO_PLAN = json.dumps(
    {
        "rationale": "locate the loss, test the suspect station, check for a past occurrence, act",
        "steps": [
            {
                "id": "s1",
                "description": f"pull the defect distribution for {DEMO_BATCH}",
                "tool": "query_defects",
            },
            {
                "id": "s2",
                "description": f"check telemetry at {DEMO_STATION}",
                "tool": "query_telemetry",
            },
            {
                "id": "s3",
                "description": "look for a matching past work order",
                "tool": "find_similar_cases",
            },
            {
                "id": "s4",
                "description": "open a work order for the confirmed cause",
                "tool": "create_work_order",
            },
        ],
    }
)

DEMO_ANSWER = (
    f"根因（最可能）：{DEMO_STATION}工位传送机构异常，导致镜片表面划伤。\n"
    "\n"
    "证据：\n"
    f"1) {DEMO_BATCH} 不良率 40.98%，前五批在 1.90%–4.00% 之间；\n"
    f"2) 该批 486 个不良中有 372 个集中在{DEMO_STATION}工位的划伤，缺陷高度集中；\n"
    f"3) {DEMO_STATION}工位振动 0.199 mm，基线 0.06 mm，偏高约 3.3 倍；\n"
    "4) 历史上出现过同一失效模式（WO-20260901-001），当时的原因是导向轮磨损。\n"
    "\n"
    "建议：停机检查传送夹具与导向轮，更换磨损件并重新标定平行度，复测振动后恢复投产。\n"
    "已开立维修工单。\n"
    "\n"
    "数据来源：simulated 数据集，非真实产线数据。"
)


def demo_script(
    batch: str = DEMO_BATCH, station: str = DEMO_STATION
) -> list[Completion | str | dict[str, Any]]:
    return [
        DEMO_PLAN,
        tool_call("query_defects", batch=batch),
        tool_call("query_telemetry", station=station),
        tool_call("find_similar_cases", text=station),
        tool_call(
            "create_work_order",
            station=station,
            batch=batch,
            priority="high",
            symptom=f"{batch} 划伤占比 41%，{station}工位振动 0.199mm 超基线 3.3 倍",
            root_cause=f"{station}工位传送夹具导向轮磨损导致镜片划伤",
            action="停机检查传送夹具与导向轮，更换磨损件并重新标定平行度，复测振动后恢复投产",
        ),
        DEMO_ANSWER,
    ]
