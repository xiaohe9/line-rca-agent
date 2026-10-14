"""Bring the database to head and seed the simulated line data.

Run as a command, not on API startup: a service that silently migrates its own database is
hard to reason about, and one that silently seeds production data is worse. In compose this
is a one-shot service the API waits for (`service_completed_successfully`).

    python -m line_rca_api.db.bootstrap            # migrate, then seed if empty
    python -m line_rca_api.db.bootstrap --reset    # drop everything first (dev/test only)

The test suite invokes this same command as a subprocess, so the path exercised by tests is
the path used in production rather than a parallel implementation of it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from line_rca_api.config import get_settings
from line_rca_api.db import models  # noqa: F401  (registers the tables on Base.metadata)
from line_rca_api.db.base import Base
from line_rca_api.db.seed import is_empty, seed_all
from line_rca_api.db.session import sessionmaker_for

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade_to_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


async def _drop_everything(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            # Alembic's bookkeeping table is not part of the model metadata.
            await connection.execute(text("drop table if exists alembic_version"))
    finally:
        await engine.dispose()


async def _seed_if_empty(url: str) -> dict[str, int] | None:
    async with sessionmaker_for(url)() as session:
        if not await is_empty(session):
            return None
        return await seed_all(session)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate and seed the line-rca-agent database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop all tables first. Destructive; intended for development and tests.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_url:
        print("LRC_DATABASE_URL is not set; nothing to migrate.")
        return 1

    if args.reset:
        asyncio.run(_drop_everything(settings.database_url))
        print("schema: dropped")

    upgrade_to_head(settings.database_url)
    print("migrations: at head")

    summary = asyncio.run(_seed_if_empty(settings.database_url))
    if summary is None:
        print("seed: skipped, batches already present")
    else:
        print(f"seed: wrote simulated line data {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
