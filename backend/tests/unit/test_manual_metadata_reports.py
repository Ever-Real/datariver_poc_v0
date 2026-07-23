from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.manual_metadata_reports import ManualMetadataReportService
from datariver.domain.authz import (
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError, NotFoundError, ValidationError
from datariver.domain.manual_metadata import ManualMetadataSubmission


class _Authorization:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def authorize(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class _Repository:
    def __init__(self, values: list[ManualMetadataSubmission]) -> None:
        self.values = values
        self.list_calls: list[dict[str, object]] = []

    async def list(self, **kwargs: object) -> list[ManualMetadataSubmission]:
        self.list_calls.append(kwargs)
        return self.values[: cast(int, kwargs["limit"])]

    async def get(self, *, submission_id: UUID, **_: object) -> ManualMetadataSubmission | None:
        return next(
            (value for value in self.values if value.submission_id == submission_id),
            None,
        )

    async def list_attempts(self, **_: object) -> tuple[()]:
        return ()


class _Uow:
    def __init__(self, repository: _Repository) -> None:
        self.manual_metadata_submissions = repository

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set_security_context(self, **_: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _submission(
    *,
    workspace_id: UUID,
    requester_id: UUID,
    created_at: datetime,
) -> ManualMetadataSubmission:
    value = ManualMetadataSubmission.queue(
        workspace_id=workspace_id,
        asset_id=uuid4(),
        external_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,wafer,PROD)",
        requester_id=requester_id,
        source_version="source-v1",
        provider_source_version="b" * 64,
        serial_number=int(created_at.timestamp()),
        description="description",
        domain=None,
        tags=(),
        terms=(),
        columns=(),
        bucket="datariver-infoschema",
        object_key=f"{uuid4()}.csv",
        csv_sha256="a" * 64,
        csv_size_bytes=1,
        row_count=1,
    )
    value.created_at = created_at
    value.updated_at = created_at
    value.next_attempt_at = created_at
    value.events.clear()
    return value


def _subject(
    *,
    workspace_id: UUID,
    subject_id: UUID,
    admin: bool = False,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=subject_id,
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"} if admin else {"data-stewards"}),
        job_function="SECURITY_ADMIN" if admin else "DATA_STEWARD",
        clearance=Classification.RESTRICTED,
    )


def _fixture(
    *,
    values: list[ManualMetadataSubmission],
) -> tuple[ManualMetadataReportService, _Repository, _Authorization]:
    repository = _Repository(values)
    authorization = _Authorization()
    uow = _Uow(repository)
    service = ManualMetadataReportService(
        authorization=cast(AuthorizationService, authorization),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
    )
    return service, repository, authorization


@pytest.mark.asyncio
async def test_owner_history_is_keyset_bounded_and_cursor_is_scope_bound() -> None:
    workspace_id = uuid4()
    requester_id = uuid4()
    now = datetime(2026, 7, 23, tzinfo=UTC)
    values = [
        _submission(
            workspace_id=workspace_id,
            requester_id=requester_id,
            created_at=now - timedelta(seconds=index),
        )
        for index in range(3)
    ]
    service, repository, _ = _fixture(values=values)
    subject = _subject(workspace_id=workspace_id, subject_id=requester_id)

    page = await service.list(
        workspace_id=workspace_id,
        subject=subject,
        environment=EnvironmentAttributes(now),
        request_id="history",
        scope="mine",
        state=None,
        cursor=None,
        limit=2,
    )

    assert len(page.items) == 2
    assert page.next_cursor is not None
    assert repository.list_calls[0]["requester_id"] == requester_id
    assert repository.list_calls[0]["limit"] == 3

    with pytest.raises(ValidationError):
        await service.list(
            workspace_id=workspace_id,
            subject=subject,
            environment=EnvironmentAttributes(now),
            request_id="history-stale",
            scope="mine",
            state="FAILED",
            cursor=page.next_cursor,
            limit=2,
        )


@pytest.mark.asyncio
async def test_only_security_admin_may_request_workspace_history() -> None:
    workspace_id = uuid4()
    subject = _subject(workspace_id=workspace_id, subject_id=uuid4())
    service, _, authorization = _fixture(values=[])

    with pytest.raises(ForbiddenError):
        await service.list(
            workspace_id=workspace_id,
            subject=subject,
            environment=EnvironmentAttributes(datetime.now(UTC)),
            request_id="workspace-history",
            scope="workspace",
            state=None,
            cursor=None,
            limit=25,
        )

    assert authorization.calls == []


@pytest.mark.asyncio
async def test_detail_hides_another_requesters_submission_but_admin_can_read_it() -> None:
    workspace_id = uuid4()
    owner_id = uuid4()
    value = _submission(
        workspace_id=workspace_id,
        requester_id=owner_id,
        created_at=datetime(2026, 7, 23, tzinfo=UTC),
    )
    service, _, _ = _fixture(values=[value])
    environment = EnvironmentAttributes(datetime.now(UTC))

    with pytest.raises(NotFoundError):
        await service.get(
            workspace_id=workspace_id,
            submission_id=value.submission_id,
            subject=_subject(workspace_id=workspace_id, subject_id=uuid4()),
            environment=environment,
            request_id="hidden",
        )

    report = await service.get(
        workspace_id=workspace_id,
        submission_id=value.submission_id,
        subject=_subject(workspace_id=workspace_id, subject_id=uuid4(), admin=True),
        environment=environment,
        request_id="admin-detail",
    )

    assert report.submission.submission_id == value.submission_id
    assert report.attempts == ()
