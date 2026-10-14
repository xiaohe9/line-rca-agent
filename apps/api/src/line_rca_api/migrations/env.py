"""Alembic environment.

The database URL is injected by the caller (`line_rca_api.db.bootstrap` or alembic.ini), so
the same migration chain works from the CLI and from inside a container where no ini file
was shipped.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from line_rca_api.db import models  # noqa: F401  (imported so tables register on Base)
from line_rca_api.db.base import Base

config = context.config

# The programmatic entry point sets sqlalchemy.url explicitly; the CLI falls back to the
# environment so `alembic upgrade head` works without editing this file.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", os.environ.get("LRC_DATABASE_URL", ""))

if config.config_file_name is not None and config.get_main_option("configure_logging") == "1":
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
