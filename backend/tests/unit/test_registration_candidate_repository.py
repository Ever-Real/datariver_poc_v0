from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.infrastructure.db.models.integration import UploadRegistrationCandidateModel
from datariver.infrastructure.db.registration import SqlUploadCandidateReader


class _ScalarRows:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values

    def all(self) -> tuple[object, ...]:
        return self._values


class _Session:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values
        self.statements: list[object] = []

    async def scalars(self, statement: object) -> _ScalarRows:
        self.statements.append(statement)
        return _ScalarRows(self._values)


@pytest.mark.asyncio
async def test_candidate_reader_is_workspace_receipt_keyset_scoped_and_maps_v2_evidence() -> None:
    workspace_id = uuid4()
    receipt_id = uuid4()
    candidate_id = uuid4()
    target_id = uuid4()
    created_at = datetime(2035, 1, 1, tzinfo=UTC)
    model = UploadRegistrationCandidateModel(
        id=candidate_id,
        workspace_id=workspace_id,
        receipt_id=receipt_id,
        ordinal=7,
        target_asset_id=target_id,
        candidate_kind="DATASET_DESCRIPTION_UPDATE",
        proposed_description="submitted description",
        evidence_version="DATASET_DESCRIPTION_CANDIDATE_V2",
        submitted_platform="postgres",
        submitted_database_name="rd",
        submitted_schema_name="public",
        submitted_table_name="experiment",
        submitted_identity_hash="a" * 64,
        candidate_hash="b" * 64,
        created_at=created_at,
    )
    session = _Session((model,))
    reader = SqlUploadCandidateReader(cast(AsyncSession, session))

    values = await reader.list_candidates(
        workspace_id=workspace_id,
        receipt_id=receipt_id,
        after_ordinal=6,
        limit=21,
    )

    assert len(session.statements) == 1
    statement = cast(ClauseElement, session.statements[0]).compile()
    sql = str(statement)
    assert "upload_registration_candidates.workspace_id" in sql
    assert "upload_registration_candidates.receipt_id" in sql
    assert "upload_registration_candidates.ordinal >" in sql
    assert "ORDER BY integration.upload_registration_candidates.ordinal ASC" in sql
    assert {workspace_id, receipt_id, 6, 21}.issubset(set(statement.params.values()))
    assert len(values) == 1
    assert values[0].candidate_id == candidate_id
    assert values[0].target_asset_id == target_id
    assert values[0].submitted_platform == "postgres"
    assert values[0].submitted_database_name == "rd"
    assert values[0].submitted_schema_name == "public"
    assert values[0].submitted_table_name == "experiment"
    assert values[0].submitted_identity_hash == "a" * 64
    assert values[0].candidate_hash == "b" * 64
