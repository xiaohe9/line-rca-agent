"""initial operational schema

Revision ID: 0001
Revises:
Create Date: 2026-10-14

Batches, AOI defect records, equipment telemetry and maintenance work orders.
Episodic vector memory is deliberately absent: it arrives with the feature that uses it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("product", sa.String(length=64), nullable=False),
        sa.Column("station", sa.String(length=32), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("defects", sa.Integer(), nullable=False),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batches")),
    )
    op.create_index(op.f("ix_batches_station"), "batches", ["station"])
    op.create_index(op.f("ix_batches_produced_at"), "batches", ["produced_at"])

    op.create_table(
        "defect_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.String(length=32), nullable=False),
        sa.Column("defect_type", sa.String(length=32), nullable=False),
        sa.Column("station", sa.String(length=32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batches.id"],
            name=op.f("fk_defect_records_batch_id_batches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_defect_records")),
    )
    op.create_index(op.f("ix_defect_records_batch_id"), "defect_records", ["batch_id"])
    op.create_index("ix_defect_records_batch_station", "defect_records", ["batch_id", "station"])

    op.create_table(
        "telemetry_samples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("station", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("baseline", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_samples")),
    )
    op.create_index(op.f("ix_telemetry_samples_station"), "telemetry_samples", ["station"])
    op.create_index(op.f("ix_telemetry_samples_recorded_at"), "telemetry_samples", ["recorded_at"])
    op.create_index(
        "ix_telemetry_samples_station_metric", "telemetry_samples", ["station", "metric"]
    )

    op.create_table(
        "work_orders",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.String(length=32), nullable=True),
        sa.Column("station", sa.String(length=32), nullable=False),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batches.id"],
            name=op.f("fk_work_orders_batch_id_batches"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_orders")),
    )
    op.create_index(op.f("ix_work_orders_station"), "work_orders", ["station"])
    op.create_index(op.f("ix_work_orders_status"), "work_orders", ["status"])
    op.create_index(op.f("ix_work_orders_batch_id"), "work_orders", ["batch_id"])
    op.create_index(op.f("ix_work_orders_run_id"), "work_orders", ["run_id"])


def downgrade() -> None:
    op.drop_table("work_orders")
    op.drop_table("telemetry_samples")
    op.drop_table("defect_records")
    op.drop_table("batches")
