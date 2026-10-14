"""Persistence models.

Scope note: this is the operational data a production line already produces — batches,
AOI defect records, equipment telemetry, and the maintenance work orders that close the
loop. Episodic (vector) memory arrives in M3; the `vector` extension is available in the
image and does not need to be created until something uses it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from line_rca_api.db.base import Base


class Batch(Base):
    """One production batch. Yield is derived, never stored twice."""

    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    product: Mapped[str] = mapped_column(String(64))
    station: Mapped[str] = mapped_column(String(32), index=True)
    units: Mapped[int] = mapped_column(Integer)
    defects: Mapped[int] = mapped_column(Integer)
    produced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(16), default="simulated")

    defect_records: Mapped[list[DefectRecord]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def yield_rate(self) -> float:
        return 1.0 - (self.defects / self.units) if self.units else 0.0

    def __repr__(self) -> str:
        return f"<Batch {self.id} units={self.units} defects={self.defects}>"


class DefectRecord(Base):
    """An aggregated AOI finding: what kind of defect, where, and how many."""

    __tablename__ = "defect_records"
    __table_args__ = (Index("ix_defect_records_batch_station", "batch_id", "station"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    defect_type: Mapped[str] = mapped_column(String(32))
    station: Mapped[str] = mapped_column(String(32))
    count: Mapped[int] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    batch: Mapped[Batch] = relationship(back_populates="defect_records")


class TelemetrySample(Base):
    """A single equipment measurement, always with the baseline it should be read against.

    Storing the baseline alongside the value is deliberate: a root-cause claim has to say
    "0.19 mm versus a baseline of 0.06 mm", and reconstructing the baseline later from a
    changing configuration would silently rewrite history.
    """

    __tablename__ = "telemetry_samples"
    __table_args__ = (Index("ix_telemetry_samples_station_metric", "station", "metric"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station: Mapped[str] = mapped_column(String(32), index=True)
    metric: Mapped[str] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Float)
    baseline: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(16), default="simulated")


class WorkOrder(Base):
    """A maintenance work order.

    `run_id` links the order back to the agent run that recommended it, which is what makes
    a recommendation auditable after the fact: the trace is still there to be read.
    """

    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    station: Mapped[str] = mapped_column(String(32), index=True)
    symptom: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
