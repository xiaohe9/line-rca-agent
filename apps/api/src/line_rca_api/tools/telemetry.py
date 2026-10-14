"""Equipment telemetry tool."""

from __future__ import annotations

from typing import Any

from line_rca_agent.contracts import Tool, ToolResult
from line_rca_agent.tools import FunctionTool
from line_rca_api.db.repositories import TelemetryRepository

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "station": {"type": "string", "description": "station name, for example 镀膜"},
    },
    "required": ["station"],
    "additionalProperties": False,
}

#: A reading is flagged when it differs from its baseline by this factor or more.
DEVIATION_RATIO = 1.5


async def _query_telemetry(repo: TelemetryRepository, arguments: dict[str, Any]) -> ToolResult:
    station = str(arguments.get("station", "")).strip()
    if not station:
        return ToolResult(
            ok=False, content="missing required field: station", error="invalid_arguments"
        )

    readings = await repo.latest_readings(station)
    if not readings:
        known = ", ".join(await repo.stations())
        return ToolResult(
            ok=False,
            content=f"no telemetry for station '{station}'. known stations: {known or '(none)'}",
            error="unknown_station",
        )

    lines = [f"station={station} latest reading per metric (value vs baseline):"]
    flagged: list[dict[str, Any]] = []
    for reading in readings:
        ratio = reading.deviation_ratio
        deviates = ratio >= DEVIATION_RATIO or ratio <= (1 / DEVIATION_RATIO)
        marker = "  <-- deviation" if deviates else ""
        lines.append(
            f"  - {reading.metric}: {reading.value:g} vs baseline {reading.baseline:g} "
            f"({ratio:.2f}x) at {reading.recorded_at.isoformat()}{marker}"
        )
        if deviates:
            flagged.append(
                {
                    "metric": reading.metric,
                    "value": reading.value,
                    "baseline": reading.baseline,
                    "ratio": round(ratio, 3),
                }
            )
    lines.append("(source: simulated dataset — not real production data)")

    return ToolResult(
        ok=True,
        content="\n".join(lines),
        data={"station": station, "deviations": flagged, "metrics": len(readings)},
    )


def build_telemetry_tools(repo: TelemetryRepository) -> list[Tool]:
    return [
        FunctionTool(
            name="query_telemetry",
            description=(
                "Latest equipment telemetry for a station, each metric shown against its "
                "baseline, with deviations flagged. Use this to test whether a suspect "
                "station is actually misbehaving."
            ),
            input_schema=SCHEMA,
            handler=lambda arguments: _query_telemetry(repo, arguments),
        )
    ]
