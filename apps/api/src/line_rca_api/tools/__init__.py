"""The tool set the agent can act through.

Every tool is built from a repository Protocol, so this layer is unit-testable with in-memory
fakes and the SQL layer is tested separately against a real database.
"""

from __future__ import annotations

from line_rca_agent.tools import InMemoryToolRegistry
from line_rca_api.db.repositories import (
    DefectRepository,
    TelemetryRepository,
    WorkOrderRepository,
)
from line_rca_api.tools.defects import build_defect_tools
from line_rca_api.tools.telemetry import build_telemetry_tools
from line_rca_api.tools.workorders import build_work_order_tools


def register_line_tools(
    registry: InMemoryToolRegistry,
    *,
    defects: DefectRepository,
    telemetry: TelemetryRepository,
    work_orders: WorkOrderRepository,
    run_id: str | None = None,
) -> InMemoryToolRegistry:
    for tool in (
        *build_defect_tools(defects),
        *build_telemetry_tools(telemetry),
        *build_work_order_tools(work_orders, run_id=run_id),
    ):
        registry.register(tool)
    return registry


__all__ = ["register_line_tools"]
