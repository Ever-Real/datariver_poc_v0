from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    CatalogMetadataVocabularyListItem,
    CatalogMetadataVocabularyPage,
    CatalogVocabularySyncReservation,
    CatalogVocabularySyncResult,
    DataHubVocabularyEntry,
    DataHubVocabularyScanPage,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    CatalogMetadataVocabularyProjection,
    DataHubGateway,
)
from datariver.application.services.authorization import (
    AuthorizationService,
    NullDecisionWriter,
)
from datariver.application.services.catalog_metadata_vocabulary import (
    CatalogMetadataVocabularyService,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError


class _Gateway:
    def __init__(
        self,
        page: DataHubVocabularyScanPage,
        *,
        error: ExternalDependencyError | None = None,
    ) -> None:
        self.page = page
        self.error = error
        self.calls: list[tuple[str, str | None, int]] = []

    async def scan_vocabulary(
        self,
        *,
        kind: str,
        cursor: str | None,
        limit: int,
    ) -> DataHubVocabularyScanPage:
        self.calls.append((kind, cursor, limit))
        if self.error is not None:
            raise self.error
        return self.page


class _Projection:
    def __init__(
        self,
        *,
        replayed: CatalogVocabularySyncResult | None = None,
        cursor: str | None = None,
    ) -> None:
        self.replayed = replayed
        self.cursor = cursor
        self.released = False
        self.abandoned = False
        self.upsert_arguments: dict[str, Any] | None = None
        self.list_arguments: dict[str, Any] | None = None

    async def reserve_scan(self, **_: Any) -> CatalogVocabularySyncReservation:
        return CatalogVocabularySyncReservation(cursor=self.cursor, replayed=self.replayed)

    async def release_scan(self) -> None:
        self.released = True

    async def abandon_scan(self, **_: Any) -> None:
        self.abandoned = True

    async def upsert_scan(self, **arguments: Any) -> CatalogVocabularySyncResult:
        self.upsert_arguments = arguments
        page = cast(DataHubVocabularyScanPage, arguments["page"])
        return CatalogVocabularySyncResult(
            upserted=len(page.items),
            inactivated=0,
            next_offset=cast(int | None, arguments["next_offset"]),
            total=page.total,
            observed_at=page.observed_at,
            inactivation_status=(
                "NOT_FINAL" if page.next_cursor is not None else "SUPPRESSED_UNVERIFIED_SNAPSHOT"
            ),
        )

    async def list_active(self, **arguments: Any) -> CatalogMetadataVocabularyPage:
        self.list_arguments = arguments
        return CatalogMetadataVocabularyPage(
            items=(
                CatalogMetadataVocabularyListItem(
                    vocabulary_id=uuid4(),
                    kind=cast(str, arguments["kind"]),
                    display_name="Business Critical",
                    source_version="a" * 64,
                ),
            ),
            next_cursor=None,
        )


def _subject(
    workspace_id: UUID,
    *,
    admin: bool,
    steward: bool = False,
    active: bool = True,
) -> SubjectAttributes:
    groups = set()
    job_function = None
    if admin:
        groups.add("security-administrators")
    if steward:
        groups.add("data-stewards")
        job_function = "DATA_STEWARD"
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=active,
        department_id=None,
        groups=frozenset(groups),
        job_function=job_function,
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.CATALOG_SYNC}),
    )


def _service(
    gateway: _Gateway,
    projection: _Projection,
) -> CatalogMetadataVocabularyService:
    return CatalogMetadataVocabularyService(
        datahub=cast(DataHubGateway, gateway),
        projection=cast(CatalogMetadataVocabularyProjection, projection),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )


@pytest.mark.asyncio
async def test_admin_syncs_one_bounded_kind_page_and_persists_server_cursor() -> None:
    workspace_id = uuid4()
    observed_at = datetime.now(UTC)
    page = DataHubVocabularyScanPage(
        items=(
            DataHubVocabularyEntry(
                provider_ref="urn:li:tag:critical",
                kind="TAG",
                display_name="Business Critical",
                source_version="a" * 64,
            ),
        ),
        next_cursor="provider-next",
        total=2,
        observed_at=observed_at,
    )
    gateway = _Gateway(page)
    projection = _Projection(cursor="provider-current")

    result = await _service(gateway, projection).sync_page(
        workspace_id=workspace_id,
        sync_id=uuid4(),
        kind="TAG",
        offset=1,
        limit=50,
        subject=_subject(workspace_id, admin=True),
        environment=EnvironmentAttributes(requested_at=observed_at),
        request_id="vocabulary-sync",
        idempotency_key="vocabulary-sync-key",
        request_hash="b" * 64,
    )

    assert gateway.calls == [("TAG", "provider-current", 50)]
    assert result.next_offset == 2
    assert projection.upsert_arguments is not None
    assert projection.upsert_arguments["cursor"] == "provider-current"


@pytest.mark.asyncio
async def test_sync_replay_does_not_call_datahub() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    replayed = CatalogVocabularySyncResult(
        upserted=1,
        inactivated=0,
        next_offset=None,
        total=1,
        observed_at=now,
        inactivation_status="SUPPRESSED_UNVERIFIED_SNAPSHOT",
    )
    gateway = _Gateway(DataHubVocabularyScanPage((), None, 0, now))
    projection = _Projection(replayed=replayed)

    result = await _service(gateway, projection).sync_page(
        workspace_id=workspace_id,
        sync_id=uuid4(),
        kind="DOMAIN",
        offset=0,
        limit=100,
        subject=_subject(workspace_id, admin=True),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="vocabulary-replay",
        idempotency_key="vocabulary-replay-key",
        request_hash="c" * 64,
    )

    assert result is replayed
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_data_steward_can_query_but_cannot_mutate_vocabulary() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    gateway = _Gateway(DataHubVocabularyScanPage((), None, 0, now))
    projection = _Projection()
    service = _service(gateway, projection)
    steward = _subject(workspace_id, admin=False, steward=True)

    page = await service.list_active(
        workspace_id=workspace_id,
        kind="TAG",
        query=" critical ",
        cursor=None,
        limit=20,
        subject=steward,
    )

    assert page.items[0].display_name == "Business Critical"
    assert projection.list_arguments is not None
    assert projection.list_arguments["query"] == "critical"
    with pytest.raises(ForbiddenError, match="security administrator"):
        await service.sync_page(
            workspace_id=workspace_id,
            sync_id=uuid4(),
            kind="TAG",
            offset=0,
            limit=100,
            subject=steward,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="steward-denied",
            idempotency_key="steward-denied-key",
            request_hash="d" * 64,
        )


@pytest.mark.asyncio
async def test_cross_workspace_query_and_inactive_admin_fail_closed() -> None:
    workspace_id = uuid4()
    service = _service(
        _Gateway(DataHubVocabularyScanPage((), None, 0, datetime.now(UTC))),
        _Projection(),
    )
    with pytest.raises(ForbiddenError, match="workspace"):
        await service.list_active(
            workspace_id=workspace_id,
            kind="TERM",
            query=None,
            cursor=None,
            limit=20,
            subject=_subject(uuid4(), admin=True),
        )
    with pytest.raises(ForbiddenError, match="active human"):
        await service.list_active(
            workspace_id=workspace_id,
            kind="TERM",
            query=None,
            cursor=None,
            limit=20,
            subject=_subject(workspace_id, admin=True, active=False),
        )


@pytest.mark.asyncio
async def test_nonretryable_later_page_failure_abandons_durable_run() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    error = ExternalDependencyError(
        "invalid page",
        dependency="datahub",
        retryable=False,
        provider_code="INVALID_RESPONSE",
    )
    gateway = _Gateway(DataHubVocabularyScanPage((), None, 0, now), error=error)
    projection = _Projection(cursor="provider-current")

    with pytest.raises(ExternalDependencyError):
        await _service(gateway, projection).sync_page(
            workspace_id=workspace_id,
            sync_id=uuid4(),
            kind="TERM",
            offset=1,
            limit=100,
            subject=_subject(workspace_id, admin=True),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="invalid-later-page",
            idempotency_key="invalid-later-page-key",
            request_hash="e" * 64,
        )

    assert projection.abandoned is True
    assert projection.released is False


@pytest.mark.asyncio
async def test_cross_kind_later_page_abandons_durable_run() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    page = DataHubVocabularyScanPage(
        items=(
            DataHubVocabularyEntry(
                provider_ref="urn:li:tag:critical",
                kind="TAG",
                display_name="Business Critical",
                source_version="f" * 64,
            ),
        ),
        next_cursor=None,
        total=1,
        observed_at=now,
    )
    projection = _Projection(cursor="provider-current")

    with pytest.raises(
        ExternalDependencyError,
        match="cross-kind vocabulary page",
    ) as exc_info:
        await _service(_Gateway(page), projection).sync_page(
            workspace_id=workspace_id,
            sync_id=uuid4(),
            kind="TERM",
            offset=1,
            limit=100,
            subject=_subject(workspace_id, admin=True),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="cross-kind-later-page",
            idempotency_key="cross-kind-later-page-key",
            request_hash="f" * 64,
        )

    assert exc_info.value.details["provider_code"] == "INVALID_RESPONSE"
    assert exc_info.value.details["retryable"] is False
    assert projection.abandoned is True
    assert projection.released is False


@pytest.mark.asyncio
async def test_cross_kind_first_page_releases_scan() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    page = DataHubVocabularyScanPage(
        items=(
            DataHubVocabularyEntry(
                provider_ref="urn:li:term:critical",
                kind="TERM",
                display_name="Business Critical",
                source_version="1" * 64,
            ),
        ),
        next_cursor=None,
        total=1,
        observed_at=now,
    )
    projection = _Projection()

    with pytest.raises(ExternalDependencyError, match="cross-kind vocabulary page"):
        await _service(_Gateway(page), projection).sync_page(
            workspace_id=workspace_id,
            sync_id=uuid4(),
            kind="TAG",
            offset=0,
            limit=100,
            subject=_subject(workspace_id, admin=True),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="cross-kind-first-page",
            idempotency_key="cross-kind-first-page-key",
            request_hash="1" * 64,
        )

    assert projection.abandoned is False
    assert projection.released is True
