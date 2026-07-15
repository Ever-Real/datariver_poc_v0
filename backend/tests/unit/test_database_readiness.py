from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.session import Database


class ScalarRows:
    def __init__(self, revisions: tuple[str, ...]) -> None:
        self._revisions = revisions

    def scalars(self) -> ScalarRows:
        return self

    def all(self) -> list[str]:
        return list(self._revisions)


class FakeConnection:
    def __init__(
        self,
        revisions: tuple[str, ...],
        error: SQLAlchemyError | None = None,
    ) -> None:
        self._revisions = revisions
        self._error = error

    async def execute(self, _: object) -> ScalarRows:
        if self._error is not None:
            raise self._error
        return ScalarRows(self._revisions)


class ConnectionContext:
    def __init__(
        self,
        connection: FakeConnection,
        *,
        block: bool = False,
    ) -> None:
        self._connection = connection
        self._block = block

    async def __aenter__(self) -> FakeConnection:
        if self._block:
            await asyncio.Event().wait()
        return self._connection

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeEngine:
    def __init__(
        self,
        revisions: tuple[str, ...] = (REQUIRED_DATABASE_REVISION,),
        *,
        error: SQLAlchemyError | None = None,
        block: bool = False,
    ) -> None:
        self._context = ConnectionContext(
            FakeConnection(revisions, error),
            block=block,
        )

    def connect(self) -> ConnectionContext:
        return self._context


def database_with(engine: FakeEngine) -> Database:
    database = object.__new__(Database)
    cast(Any, database).engine = cast(AsyncEngine, engine)
    return database


@pytest.mark.asyncio
async def test_database_readiness_requires_the_packaged_sole_head() -> None:
    ready = await database_with(FakeEngine()).readiness(
        required_revision=REQUIRED_DATABASE_REVISION,
        timeout_seconds=0.1,
    )
    wrong = await database_with(FakeEngine(("0003",))).readiness(
        required_revision=REQUIRED_DATABASE_REVISION,
        timeout_seconds=0.1,
    )
    multiple = await database_with(FakeEngine(("0003", "0004"))).readiness(
        required_revision=REQUIRED_DATABASE_REVISION,
        timeout_seconds=0.1,
    )

    assert ready.ready is True and ready.code is None
    assert wrong.code == "SCHEMA_REVISION_MISMATCH"
    assert multiple.code == "SCHEMA_REVISION_MISMATCH"


@pytest.mark.asyncio
async def test_database_readiness_maps_timeout_and_connection_failure() -> None:
    timed_out = await database_with(FakeEngine(block=True)).readiness(
        required_revision=REQUIRED_DATABASE_REVISION,
        timeout_seconds=0.01,
    )
    unavailable = await database_with(
        FakeEngine(error=SQLAlchemyError("provider detail must not escape"))
    ).readiness(
        required_revision=REQUIRED_DATABASE_REVISION,
        timeout_seconds=0.1,
    )

    assert timed_out.code == "DATABASE_READINESS_TIMEOUT"
    assert unavailable.code == "DATABASE_UNAVAILABLE"


def test_packaged_revision_matches_the_alembic_head() -> None:
    backend = Path(__file__).resolve().parents[2]
    script = ScriptDirectory(dir=str(backend / "alembic"))

    assert script.get_current_head() == REQUIRED_DATABASE_REVISION
