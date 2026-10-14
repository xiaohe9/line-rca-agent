"""Data access, behind narrow Protocols.

The Protocols are not ceremony: they let the tool layer be unit-tested against in-memory
fakes with no database, while the SQL implementations get their own integration tests. The
kernel never sees any of this — from its side these are just `Tool`s.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from line_rca_api.db.models import Batch, DefectRecord, TelemetrySample, WorkOrder

# --------------------------------------------------------------------------- #
#  value objects — tools return these, so no ORM object escapes the repository
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BatchSummary:
    batch_id: str
    product: str
    units: int
    defects: int
    defect_rate: float
    produced_at: datetime
    #: "simulated" for the bundled dataset. Carried through so that every observation can
    #: label its own provenance instead of a hard-coded string claiming it somewhere else.
    source: str


@dataclass(frozen=True, slots=True)
class DefectCount:
    station: str
    defect_type: str
    count: int


@dataclass(frozen=True, slots=True)
class TelemetryReading:
    station: str
    metric: str
    value: float
    baseline: float
    recorded_at: datetime
    #: Where the reading came from ("simulated", "mqtt", ...). Carried so an observation can
    #: state its own provenance instead of a tool hard-coding one and being wrong later.
    source: str

    @property
    def deviation_ratio(self) -> float:
        return (self.value / self.baseline) if self.baseline else 0.0


@dataclass(frozen=True, slots=True)
class WorkOrderRecord:
    id: str
    batch_id: str | None
    station: str
    symptom: str
    root_cause: str | None
    action: str
    priority: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkOrderDraft:
    station: str
    symptom: str
    action: str
    priority: str = "medium"
    batch_id: str | None = None
    root_cause: str | None = None
    run_id: str | None = None


# --------------------------------------------------------------------------- #
#  Protocols
# --------------------------------------------------------------------------- #


class DefectRepository(Protocol):
    async def recent_batches(self, limit: int = 6) -> list[BatchSummary]: ...
    async def batch_summary(self, batch_id: str) -> BatchSummary | None: ...
    async def defect_breakdown(self, batch_id: str) -> list[DefectCount]: ...


class TelemetryRepository(Protocol):
    async def stations(self) -> list[str]: ...
    async def latest_readings(self, station: str) -> list[TelemetryReading]: ...


class WorkOrderRepository(Protocol):
    async def create(self, draft: WorkOrderDraft) -> WorkOrderRecord: ...
    async def list_recent(
        self, *, status: str | None = None, limit: int = 10
    ) -> list[WorkOrderRecord]: ...
    async def find_similar(self, text: str, *, limit: int = 3) -> list[WorkOrderRecord]: ...


# --------------------------------------------------------------------------- #
#  SQL implementations
# --------------------------------------------------------------------------- #


def _to_batch_summary(batch: Batch) -> BatchSummary:
    return BatchSummary(
        batch_id=batch.id,
        product=batch.product,
        units=batch.units,
        defects=batch.defects,
        defect_rate=batch.defects / batch.units if batch.units else 0.0,
        produced_at=batch.produced_at,
        source=batch.source,
    )


def _to_work_order(order: WorkOrder) -> WorkOrderRecord:
    return WorkOrderRecord(
        id=order.id,
        batch_id=order.batch_id,
        station=order.station,
        symptom=order.symptom,
        root_cause=order.root_cause,
        action=order.action,
        priority=order.priority,
        status=order.status,
        created_at=order.created_at,
    )


class SqlDefectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def recent_batches(self, limit: int = 6) -> list[BatchSummary]:
        result = await self._session.scalars(
            select(Batch).order_by(Batch.produced_at.desc()).limit(limit)
        )
        return [_to_batch_summary(batch) for batch in result]

    async def batch_summary(self, batch_id: str) -> BatchSummary | None:
        batch = await self._session.get(Batch, batch_id)
        return _to_batch_summary(batch) if batch else None

    async def defect_breakdown(self, batch_id: str) -> list[DefectCount]:
        rows = await self._session.execute(
            select(DefectRecord.station, DefectRecord.defect_type, func.sum(DefectRecord.count))
            .where(DefectRecord.batch_id == batch_id)
            .group_by(DefectRecord.station, DefectRecord.defect_type)
            .order_by(func.sum(DefectRecord.count).desc())
        )
        return [
            DefectCount(station=station, defect_type=defect_type, count=int(total))
            for station, defect_type, total in rows
        ]


class SqlTelemetryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def stations(self) -> list[str]:
        rows = await self._session.scalars(
            select(TelemetrySample.station).distinct().order_by(TelemetrySample.station)
        )
        return list(rows)

    async def latest_readings(self, station: str) -> list[TelemetryReading]:
        # One row per metric: the most recent sample. A window function would also work,
        # but DISTINCT ON is clearer here and this table is small.
        latest = (
            select(
                TelemetrySample.metric,
                func.max(TelemetrySample.recorded_at).label("recorded_at"),
            )
            .where(TelemetrySample.station == station)
            .group_by(TelemetrySample.metric)
            .subquery()
        )
        rows = await self._session.scalars(
            select(TelemetrySample)
            .join(
                latest,
                (TelemetrySample.metric == latest.c.metric)
                & (TelemetrySample.recorded_at == latest.c.recorded_at),
            )
            .where(TelemetrySample.station == station)
        )
        return [
            TelemetryReading(
                station=row.station,
                metric=row.metric,
                value=row.value,
                baseline=row.baseline,
                recorded_at=row.recorded_at,
                source=row.source,
            )
            for row in rows
        ]


class SqlWorkOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _next_id(self) -> str:
        # KNOWN LIMITATION: two concurrent creates can race for the same sequence number.
        # The primary key turns that into a failed insert rather than a silent duplicate,
        # and a real deployment would use a database sequence. Left simple on purpose.
        prefix = f"WO-{datetime.now(UTC):%Y%m%d}"
        used = await self._session.scalar(
            select(func.count()).select_from(WorkOrder).where(WorkOrder.id.like(f"{prefix}-%"))
        )
        return f"{prefix}-{int(used or 0) + 1:03d}"

    async def create(self, draft: WorkOrderDraft) -> WorkOrderRecord:
        order = WorkOrder(
            id=await self._next_id(),
            batch_id=draft.batch_id,
            station=draft.station,
            symptom=draft.symptom,
            root_cause=draft.root_cause,
            action=draft.action,
            priority=draft.priority,
            status="open",
            run_id=draft.run_id,
        )
        self._session.add(order)
        await self._session.commit()
        await self._session.refresh(order)
        return _to_work_order(order)

    async def list_recent(
        self, *, status: str | None = None, limit: int = 10
    ) -> list[WorkOrderRecord]:
        statement = select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(limit)
        if status is not None:
            statement = statement.where(WorkOrder.status == status)
        rows = await self._session.scalars(statement)
        return [_to_work_order(row) for row in rows]

    async def find_similar(self, text: str, *, limit: int = 3) -> list[WorkOrderRecord]:
        """Lexical similarity, as a stand-in for vector recall.

        Deliberately crude and labelled as such: M3 replaces this with an embedding search
        over the same table plus pgvector. Having the tool exist now means the agent's
        behaviour does not change shape when the implementation improves.
        """
        needle = max(text.split(), key=len, default="").strip()
        if not needle:
            return []
        pattern = f"%{needle}%"
        rows = await self._session.scalars(
            select(WorkOrder)
            .where(
                or_(
                    WorkOrder.symptom.ilike(pattern),
                    WorkOrder.root_cause.ilike(pattern),
                    WorkOrder.station.ilike(pattern),
                )
            )
            .order_by(WorkOrder.created_at.desc())
            .limit(limit)
        )
        return [_to_work_order(row) for row in rows]
