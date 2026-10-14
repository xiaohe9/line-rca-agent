"""Async engine and session factory.

Both are cached per URL so the process holds one connection pool regardless of how many
requests are served, while tests can point at a different database without touching globals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@lru_cache(maxsize=8)
def engine_for(url: str) -> AsyncEngine:
    # pool_pre_ping: a managed Postgres drops idle connections, and a stale pooled
    # connection surfacing as a random 500 during a demo is not a good look.
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache(maxsize=8)
def sessionmaker_for(url: str) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine_for(url), expire_on_commit=False)


async def session_scope(url: str) -> AsyncIterator[AsyncSession]:
    """Standalone session for scripts and tests (no FastAPI involved)."""
    async with sessionmaker_for(url)() as session:
        yield session
