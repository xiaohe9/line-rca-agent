"""Deterministic simulated production-line data.

Everything this module writes is marked `source="simulated"` and every tool observation
repeats that label. It is a stand-in for a real MES/AOI feed, not a sample of one — the
project must never be mistaken for a deployed factory system.

The dataset is fixed-seed so that a demo, a test and a screenshot all show the same numbers,
and so an evaluation run is reproducible.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from line_rca_api.db.models import Batch, DefectRecord, TelemetrySample, WorkOrder

SEED = 20261014
BASE_TIME = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
PRODUCTION_INTERVAL = timedelta(minutes=40)

PRODUCT = "光学镜片 A2"
STATIONS = ("镀膜", "蚀刻", "封装", "贴片")
DEFECT_TYPES = ("划伤", "异物", "气泡", "尺寸偏差", "缺胶")
METRICS: tuple[tuple[str, float, float], ...] = (
    # metric, baseline, normal jitter
    ("temperatureC", 68.0, 1.2),
    ("vibrationMm", 0.06, 0.008),
    ("beltSpeed", 1.00, 0.02),
)

#: batch id, units, defect rate. B-2041 is the anomaly the demo investigates.
BATCH_PLAN: tuple[tuple[str, int, float], ...] = (
    ("B-2036", 1200, 0.021),
    ("B-2037", 1180, 0.026),
    ("B-2038", 1210, 0.019),
    ("B-2039", 1195, 0.024),
    ("B-2040", 1200, 0.040),
    ("B-2041", 1186, 0.410),
)

ANOMALOUS_BATCH = "B-2041"
ANOMALOUS_STATION = "镀膜"
ANOMALOUS_DEFECT = "划伤"


async def seed_all(session: AsyncSession, *, reset: bool = False) -> dict[str, int]:
    """Populate the operational tables. Idempotent when the caller checks emptiness first."""
    if reset:
        await session.execute(delete(WorkOrder))
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(DefectRecord))
        await session.execute(delete(Batch))
        await session.commit()

    rng = random.Random(SEED)  # noqa: S311 (deterministic simulation, not security)
    station_weights = {"镀膜": 0.35, "蚀刻": 0.25, "封装": 0.25, "贴片": 0.15}
    type_weights = {"划伤": 0.30, "异物": 0.22, "气泡": 0.20, "尺寸偏差": 0.18, "缺胶": 0.10}

    defect_rows = 0
    for index, (batch_id, units, rate) in enumerate(BATCH_PLAN):
        produced_at = BASE_TIME + PRODUCTION_INTERVAL * index
        total_defects = max(1, round(units * rate))
        session.add(
            Batch(
                id=batch_id,
                product=PRODUCT,
                station=ANOMALOUS_STATION,
                units=units,
                defects=total_defects,
                produced_at=produced_at,
                source="simulated",
            )
        )

        # The anomalous batch concentrates its damage on one station and one defect type —
        # that concentration is exactly the signal a root-cause agent has to notice.
        is_anomalous = batch_id == ANOMALOUS_BATCH
        weights = (
            {station: (0.85 if station == ANOMALOUS_STATION else 0.05) for station in STATIONS}
            if is_anomalous
            else station_weights
        )
        for station, station_share in weights.items():
            station_defects = round(total_defects * station_share)
            if station_defects <= 0:
                continue
            types = (
                {name: (0.9 if name == ANOMALOUS_DEFECT else 0.025) for name in DEFECT_TYPES}
                if is_anomalous and station == ANOMALOUS_STATION
                else type_weights
            )
            for defect_type, type_share in types.items():
                count = round(station_defects * type_share)
                if count <= 0:
                    continue
                session.add(
                    DefectRecord(
                        batch_id=batch_id,
                        defect_type=defect_type,
                        station=station,
                        count=count,
                        first_seen_at=produced_at + timedelta(minutes=5),
                    )
                )
                defect_rows += 1

    telemetry_rows = 0
    for station in STATIONS:
        for step in range(12):
            recorded_at = BASE_TIME + timedelta(minutes=20 * step)
            # Vibration at the suspect station climbs over the last two batches.
            degraded = station == ANOMALOUS_STATION and step >= 8
            for metric, baseline, jitter in METRICS:
                value = baseline + rng.uniform(-jitter, jitter)
                if degraded and metric == "vibrationMm":
                    value = 0.19 + rng.uniform(-0.01, 0.01)
                elif degraded and metric == "temperatureC":
                    value = 71.2 + rng.uniform(-0.4, 0.4)
                session.add(
                    TelemetrySample(
                        station=station,
                        metric=metric,
                        value=round(value, 4),
                        baseline=baseline,
                        recorded_at=recorded_at,
                        source="simulated",
                    )
                )
                telemetry_rows += 1

    # One closed historical order describing the same failure mode. It is what an
    # experienced engineer would recall, and it is what memory recall has to find.
    session.add(
        WorkOrder(
            id="WO-20260901-001",
            batch_id="B-2039",
            station=ANOMALOUS_STATION,
            symptom="镀膜后镜片表面出现细密划痕，划伤占比升至 2.4%",
            root_cause="传送夹具导向轮磨损，导致镜片在传送过程中与金属导轨摩擦",
            action="更换导向轮并重新标定传送平行度，复测振动值",
            priority="high",
            status="closed",
            run_id=None,
        )
    )

    await session.commit()
    return {
        "batches": len(BATCH_PLAN),
        "defect_records": defect_rows,
        "telemetry_samples": telemetry_rows,
        "work_orders": 1,
    }


async def is_empty(session: AsyncSession) -> bool:
    return not await session.scalar(select(func.count()).select_from(Batch))
