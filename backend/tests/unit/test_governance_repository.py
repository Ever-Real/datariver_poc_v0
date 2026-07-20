from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.authz import Classification
from datariver.domain.governance import ChangeItem, ChangeRequest, change_target_binding_hash
from datariver.infrastructure.db.governance import SqlChangeRequestRepository
from datariver.infrastructure.db.models.governance import ChangeRequestModel


class RecordingSession:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def add(self, value: object) -> None:
        self.events.append(("add", value))

    async def flush(self, values: list[object]) -> None:
        self.events.append(("flush", tuple(values)))

    def add_all(self, values: list[object]) -> None:
        self.events.append(("add_all", tuple(values)))


def make_request() -> ChangeRequest:
    workspace_id = uuid4()
    asset_id = uuid4()
    system_id = uuid4()
    target_ref = "urn:li:dataset:test"
    return ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-2026-000001",
        request_type="CHANGE_INTAKE",
        title="Repository insert ordering",
        description="Parent rows must exist before child rows are inserted.",
        requester_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        items=[
            ChangeItem(
                item_id=uuid4(),
                target_type="DATAHUB_INTAKE",
                target_ref=target_ref,
                operation="REVIEW",
                after_document={"contract": "change-intake-v1"},
                aspect_name="changeIntake",
                before_hash="a" * 64,
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_system_id=system_id,
                target_classification=Classification.CONFIDENTIAL,
                target_lifecycle="ACTIVE",
                target_source_version="1",
                target_observed_at=datetime.now(UTC),
                target_binding_hash=change_target_binding_hash(
                    target_ref=target_ref,
                    asset_id=asset_id,
                    asset_type="DATASET",
                    system_id=system_id,
                    domain_id=None,
                    owner_department_id=None,
                    classification=Classification.CONFIDENTIAL,
                    lifecycle="ACTIVE",
                ),
                routing_system_id=system_id,
            )
        ],
    )


@pytest.mark.asyncio
async def test_new_change_request_flushes_parent_before_rounds_and_items() -> None:
    session = RecordingSession()
    repository = SqlChangeRequestRepository(cast(AsyncSession, cast(Any, session)))

    await repository.add(make_request())

    assert [event[0] for event in session.events] == ["add", "flush", "add_all", "add_all"]
    parent = session.events[0][1]
    assert isinstance(parent, ChangeRequestModel)
    assert session.events[1][1] == (parent,)
