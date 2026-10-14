"""Test fixtures.

Integration tests need a real Postgres, because the schema, the seed data and the SQL are all
part of what the endpoints promise. Point `LRC_TEST_DATABASE_URL` at one (the compose stack
provides it) or the integration tests skip with an explicit reason rather than silently
passing.

Database preparation shells out to `python -m line_rca_api.db.bootstrap --reset` — the same
command production uses — instead of building the schema in-process. That avoids crossing
event loops with asyncpg, and it means the tests exercise the real bootstrap path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from line_rca_api.db.session import sessionmaker_for
from line_rca_api.deps import provide_session
from line_rca_api.main import app

TEST_DATABASE_URL = os.environ.get("LRC_TEST_DATABASE_URL")

SKIP_REASON = (
    "LRC_TEST_DATABASE_URL is not set. Start Postgres with `docker compose up -d postgres` "
    "and set LRC_TEST_DATABASE_URL=postgresql+asyncpg://lrc:lrc@localhost:5432/lrc"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip(SKIP_REASON)
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def prepared_database(database_url: str) -> Iterator[str]:
    """Reset the schema through the real migration, then seed.

    WARNING: this drops and recreates the tables in whatever database it is pointed at.
    Use a dedicated database if the data matters.
    """
    environment = {**os.environ, "LRC_DATABASE_URL": database_url}
    completed = subprocess.run(
        [sys.executable, "-m", "line_rca_api.db.bootstrap", "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if completed.returncode != 0:
        pytest.fail(
            "database bootstrap failed; the integration tests cannot run.\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    yield database_url

    # Leave the database as the tests found it. Some tests write (a work order, an ingested
    # telemetry sample), and without this the residue shows up in the local demo — which is
    # exactly how a test row labelled source='mqtt' ended up in a live run once.
    subprocess.run(
        [sys.executable, "-m", "line_rca_api.db.bootstrap", "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.fixture(scope="session")
def client(prepared_database: str) -> Iterator[TestClient]:
    """A session-scoped client so every request shares one event loop.

    asyncpg connections are loop-bound, so a fresh client per test would hand a pooled
    connection to the wrong loop.
    """

    async def override_session():  # type: ignore[no-untyped-def]
        async with sessionmaker_for(prepared_database)() as session:
            yield session

    app.dependency_overrides[provide_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
async def session_factory(prepared_database: str):  # type: ignore[no-untyped-def]
    """A sessionmaker bound to *this test's* event loop.

    The application's `sessionmaker_for` is deliberately not reused: it is created inside the
    TestClient's own loop, and handing that pool to pytest's loop produces
    "got Future attached to a different loop". Async tests own their engine.
    """
    engine = create_async_engine(prepared_database, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
