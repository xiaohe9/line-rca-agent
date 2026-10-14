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
