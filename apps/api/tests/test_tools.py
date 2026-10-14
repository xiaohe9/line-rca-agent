"""Tool-layer tests with no database.

The tools depend on repository *Protocols*, so they can be exercised against small fakes.
That keeps this suite fast and makes a failure point at the tool rather than at Postgres.
The SQL behind the same Protocols is covered by the integration tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from line_rca_agent.tools import InMemoryToolRegistry
from line_rca_api.db.repositories import (
    BatchSummary,
    DefectCount,
    TelemetryReading,
    WorkOrderDraft,
    WorkOrderRecord,
)
from line_rca_api.tools import register_line_tools

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)

BATCHES = {
    "B-2040": BatchSummary("B-2040", "光学镜片 A2", 1200, 48, 0.04, NOW, "simulated"),
    "B-2041": BatchSummary("B-2041", "光学镜片 A2", 1186, 486, 0.4098, NOW, "simulated"),
}

BREAKDOWNS = {
    "B-2041": [
        DefectCount("镀膜", "划伤", 372),
        DefectCount("镀膜", "气泡", 10),
    ]
}

READINGS = {
    "镀膜": [
        TelemetryReading("镀膜", "vibrationMm", 0.199, 0.06, NOW, "simulated"),
        TelemetryReading("镀膜", "temperatureC", 68.4, 68.0, NOW, "simulated"),
    ]
}

HISTORICAL = WorkOrderRecord(
    id="WO-20260901-001",
    batch_id="B-2039",
    station="镀膜",
    symptom="镀膜后镜片表面出现细密划痕",
    root_cause="传送夹具导向轮磨损",
    action="更换导向轮",
    priority="high",
    status="closed",
    created_at=NOW,
)


class FakeDefects:
    async def recent_batches(self, limit: int = 6) -> list[BatchSummary]:
        return list(BATCHES.values())[:limit]

    async def batch_summary(self, batch_id: str) -> BatchSummary | None:
        return BATCHES.get(batch_id)

    async def defect_breakdown(self, batch_id: str) -> list[DefectCount]:
        return BREAKDOWNS.get(batch_id, [])


class FakeTelemetry:
    async def stations(self) -> list[str]:
        return sorted(READINGS)

    async def latest_readings(self, station: str) -> list[TelemetryReading]:
        return READINGS.get(station, [])


class FakeWorkOrders:
    def __init__(self) -> None:
        self.created: list[WorkOrderDraft] = []

    async def create(self, draft: WorkOrderDraft) -> WorkOrderRecord:
        self.created.append(draft)
        return WorkOrderRecord(
            id=f"WO-20261014-{len(self.created):03d}",
            batch_id=draft.batch_id,
            station=draft.station,
            symptom=draft.symptom,
            root_cause=draft.root_cause,
            action=draft.action,
            priority=draft.priority,
            status="open",
            created_at=NOW,
        )

    async def list_recent(
        self, *, status: str | None = None, limit: int = 10
    ) -> list[WorkOrderRecord]:
        return [HISTORICAL][:limit]

    async def find_similar(self, text: str, *, limit: int = 3) -> list[WorkOrderRecord]:
        return [HISTORICAL] if "镀膜" in text else []


@pytest.fixture
def work_orders() -> FakeWorkOrders:
    return FakeWorkOrders()


@pytest.fixture
def registry(work_orders: FakeWorkOrders) -> InMemoryToolRegistry:
    return register_line_tools(
        InMemoryToolRegistry(),
        defects=FakeDefects(),
        telemetry=FakeTelemetry(),
        work_orders=work_orders,
        run_id="run-test123",
    )


async def call(registry: InMemoryToolRegistry, name: str, **arguments: object):
    tool = registry.get(name)
    assert tool is not None, f"{name} is not registered"
    return await tool.run(arguments)


def test_registry_exposes_the_expected_tools(registry: InMemoryToolRegistry) -> None:
    assert registry.names() == [
        "create_work_order",
        "find_similar_cases",
        "list_work_orders",
        "query_defects",
        "query_telemetry",
    ]
    for schema in registry.schemas():
        assert schema["inputSchema"]["type"] == "object"


async def test_query_defects_reports_the_concentration(registry: InMemoryToolRegistry) -> None:
    result = await call(registry, "query_defects", batch="B-2041")

    assert result.ok is True
    assert "40.98%" in result.content
    assert "镀膜 / 划伤 / 372" in result.content
    # Provenance travels with the data rather than being asserted somewhere else.
    assert "simulated" in result.content
    assert result.data["breakdown"][0] == {"station": "镀膜", "defectType": "划伤", "count": 372}


async def test_query_defects_lists_known_batches_when_unknown(
    registry: InMemoryToolRegistry,
) -> None:
    result = await call(registry, "query_defects", batch="B-9999")

    assert result.ok is False
    assert result.error == "unknown_batch"
    assert "B-2040" in result.content and "B-2041" in result.content


async def test_query_defects_requires_a_batch(registry: InMemoryToolRegistry) -> None:
    result = await call(registry, "query_defects")
    assert result.ok is False
    assert result.error == "invalid_arguments"


async def test_query_telemetry_flags_only_real_deviations(
    registry: InMemoryToolRegistry,
) -> None:
    result = await call(registry, "query_telemetry", station="镀膜")

    assert result.ok is True
    assert result.data["deviations"] == [
        {"metric": "vibrationMm", "value": 0.199, "baseline": 0.06, "ratio": 3.317}
    ]
    assert "vibrationMm" in result.content
    assert "deviation" in result.content


async def test_query_telemetry_lists_stations_when_unknown(
    registry: InMemoryToolRegistry,
) -> None:
    result = await call(registry, "query_telemetry", station="不存在的工位")

    assert result.ok is False
    assert result.error == "unknown_station"
    assert "镀膜" in result.content


async def test_create_work_order_records_the_run_that_recommended_it(
    registry: InMemoryToolRegistry, work_orders: FakeWorkOrders
) -> None:
    result = await call(
        registry,
        "create_work_order",
        station="镀膜",
        symptom="划伤占比 41%",
        action="更换导向轮",
        batch="B-2041",
        priority="high",
    )

    assert result.ok is True
    assert result.data["workOrderId"].startswith("WO-")
    assert result.data["runId"] == "run-test123"
    assert "run-test123" in result.content
    assert work_orders.created[0].run_id == "run-test123"
    assert work_orders.created[0].batch_id == "B-2041"


async def test_create_work_order_refuses_incomplete_input(
    registry: InMemoryToolRegistry, work_orders: FakeWorkOrders
) -> None:
    result = await call(registry, "create_work_order", station="镀膜", symptom="划伤")

    assert result.ok is False
    assert result.error == "invalid_arguments"
    assert "action" in result.content
    assert work_orders.created == [], "nothing should be written for an invalid call"


async def test_create_work_order_normalises_an_unknown_priority(
    registry: InMemoryToolRegistry, work_orders: FakeWorkOrders
) -> None:
    await call(
        registry,
        "create_work_order",
        station="镀膜",
        symptom="划伤",
        action="检查",
        priority="urgent!!",
    )
    assert work_orders.created[0].priority == "medium"


async def test_find_similar_cases_reports_a_match_and_a_miss(
    registry: InMemoryToolRegistry,
) -> None:
    hit = await call(registry, "find_similar_cases", text="镀膜")
    assert hit.ok is True
    assert "WO-20260901-001" in hit.content
    assert "导向轮" in hit.content

    miss = await call(registry, "find_similar_cases", text="封装")
    assert miss.ok is True
    assert miss.data["count"] == 0


async def test_list_work_orders_returns_records(registry: InMemoryToolRegistry) -> None:
    result = await call(registry, "list_work_orders", status="closed", limit=5)
    assert result.ok is True
    assert result.data["ids"] == ["WO-20260901-001"]


async def test_query_telemetry_reports_provenance_from_the_data(
    registry: InMemoryToolRegistry,
) -> None:
    result = await call(registry, "query_telemetry", station="镀膜")

    assert result.data["sources"] == ["simulated"]
    assert "(source: simulated)" in result.content


async def test_query_telemetry_does_not_hard_code_its_provenance() -> None:
    """Readings can arrive over MQTT; a tool that always says "simulated" would lie."""

    class LiveTelemetry:
        async def stations(self) -> list[str]:
            return ["镀膜"]

        async def latest_readings(self, station: str) -> list[TelemetryReading]:
            return [TelemetryReading("镀膜", "vibrationMm", 0.2, 0.06, NOW, "mqtt")]

    live = register_line_tools(
        InMemoryToolRegistry(),
        defects=FakeDefects(),
        telemetry=LiveTelemetry(),
        work_orders=FakeWorkOrders(),
    )

    result = await call(live, "query_telemetry", station="镀膜")

    assert result.data["sources"] == ["mqtt"]
    assert "(source: mqtt)" in result.content
    assert "simulated" not in result.content
