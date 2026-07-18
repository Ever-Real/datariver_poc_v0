from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

import pytest

from datariver.application.classification_access import (
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    DataHubAspectSnapshot,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    CatalogChangeTargetReader,
    CatalogIndexReader,
    DataHubGateway,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog_description import (
    CatalogDescriptionService,
    GovernedChangeRequestCreator,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.governance import ChangeRequest


class FakeClassificationAccess:
    async def resolve(self, **_: object) -> ClassificationAccessSnapshot:
        return static_classification_access_floor()


class FakeIndex:
    def __init__(self, detail: CatalogAssetDetail, events: list[str]) -> None:
        self.detail = detail
        self.current = detail.index
        self.events = events
        self.locked = False

    async def get_authorized_asset(self, **_: object) -> CatalogAssetDetail | None:
        self.events.append("catalog-read")
        return self.detail

    async def get_authorized_assets_by_external_urns(
        self, *, lock_for_share: bool = False, **_: object
    ) -> tuple[CatalogAssetIndex, ...]:
        self.events.append("target-lock")
        self.locked = lock_for_share
        return (self.current,)


class FakeAuthorization:
    def __init__(self, events: list[str], denied: Action | None = None) -> None:
        self.events = events
        self.denied = denied

    async def authorize(self, *, action: Action, **_: object) -> None:
        self.events.append(f"authorize:{action.value}")
        if action is self.denied:
            raise ForbiddenError("denied")


class FakeDataHub:
    def __init__(self, snapshot: DataHubAspectSnapshot, events: list[str]) -> None:
        self.snapshot = snapshot
        self.events = events
        self.calls = 0

    async def read_aspect(self, **_: object) -> DataHubAspectSnapshot:
        self.events.append("datahub-read")
        self.calls += 1
        return self.snapshot


class FakeGovernance:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.arguments: dict[str, Any] | None = None
        self.result = cast(ChangeRequest, object())

    async def create_change_request(self, **arguments: Any) -> ChangeRequest:
        self.events.append("governance-create")
        self.arguments = arguments
        return self.result


def _fixture(
    *, denied: Action | None = None
) -> tuple[
    CatalogDescriptionService,
    FakeIndex,
    FakeDataHub,
    FakeGovernance,
    SubjectAttributes,
    EnvironmentAttributes,
    list[str],
]:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    asset = CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,lab.wafer,PROD)",
        asset_type="DATASET",
        name="wafer",
        description="projection description",
        platform="postgres",
        domain_id=uuid4(),
        system_id=uuid4(),
        owner_department_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        lifecycle="ACTIVE",
        source_version="projection-v3",
        observed_at=now,
    )
    detail = CatalogAssetDetail(asset, (), (), (), (), {}, "projection-v3", now)
    document = {
        "description": "Current description",
        "customProperties": {"tier": "gold"},
        "name": "wafer",
    }
    snapshot = DataHubAspectSnapshot(
        urn=asset.external_urn,
        aspect_name="datasetProperties",
        content_hash=canonical_json_hash(document),
        source_version="provider-v7",
        observed_at=now,
        document=MappingProxyType(document),
    )
    events: list[str] = []
    index = FakeIndex(detail, events)
    datahub = FakeDataHub(snapshot, events)
    governance = FakeGovernance(events)
    service = CatalogDescriptionService(
        index=cast(CatalogIndexReader, index),
        target_reader=cast(CatalogChangeTargetReader, index),
        classification_access=cast(ClassificationAccessResolver, FakeClassificationAccess()),
        authorization=cast(AuthorizationService, FakeAuthorization(events, denied=denied)),
        datahub=cast(DataHubGateway, datahub),
        governance=cast(GovernedChangeRequestCreator, governance),
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.CONFIDENTIAL,
    )
    return service, index, datahub, governance, subject, EnvironmentAttributes(now), events


@pytest.mark.asyncio
async def test_preview_is_typed_opaque_and_authorizes_before_provider_read() -> None:
    service, index, datahub, _, subject, environment, events = _fixture()

    preview = await service.preview(
        asset_id=index.detail.index.asset_id,
        description="Proposed description",
        subject=subject,
        environment=environment,
        request_id="preview",
    )

    assert preview.target_ref.startswith("urn:li:dataset:")
    assert preview.aspect_name == "datasetProperties"
    assert preview.current_description == "Current description"
    assert preview.proposed_description == "Proposed description"
    assert preview.before_hash == datahub.snapshot.content_hash
    assert preview.after_hash == canonical_json_hash(
        {
            "description": "Proposed description",
            "customProperties": {"tier": "gold"},
            "name": "wafer",
        }
    )
    assert len(preview.preview_etag) == 66
    assert preview.preview_etag.startswith('"')
    assert preview.preview_etag.endswith('"')
    assert not hasattr(preview, "document")
    assert events == [
        "catalog-read",
        "authorize:catalog.read",
        "authorize:change.create",
        "datahub-read",
    ]


@pytest.mark.asyncio
async def test_create_rechecks_composite_locks_target_and_merges_only_description() -> None:
    service, index, _, governance, subject, environment, events = _fixture()
    preview = await service.preview(
        asset_id=index.detail.index.asset_id,
        description="Proposed description",
        subject=subject,
        environment=environment,
        request_id="preview",
    )
    events.clear()

    result = await service.create_change_request(
        asset_id=index.detail.index.asset_id,
        expected_preview_etag=preview.preview_etag,
        description="Proposed description",
        title="Update wafer description",
        change_description="Correct the governed definition",
        number="CR-2026-TYPED",
        subject=subject,
        environment=environment,
        request_id="create",
        idempotency_key="typed-description-0001",
        request_hash="a" * 64,
    )

    assert result is governance.result
    assert index.locked is True
    assert events == [
        "catalog-read",
        "authorize:catalog.read",
        "authorize:change.create",
        "datahub-read",
        "target-lock",
        "governance-create",
    ]
    assert governance.arguments is not None
    assert governance.arguments["classification"] is Classification.CONFIDENTIAL
    assert governance.arguments["require_raw_operator_gate"] is False
    item = governance.arguments["items"][0]
    assert item.target_ref == index.detail.index.external_urn
    assert item.before_hash == preview.before_hash
    assert item.after_hash == preview.after_hash
    assert item.after_document == {
        "description": "Proposed description",
        "customProperties": {"tier": "gold"},
        "name": "wafer",
    }


@pytest.mark.asyncio
async def test_column_description_change_preserves_the_schema_document_and_field_identity() -> None:
    service, index, datahub, governance, subject, environment, _ = _fixture()
    schema_document = {
        "dataset": index.detail.index.external_urn,
        "fields": [
            {"fieldPath": "event_id", "description": "Legacy identifier", "type": "BIGINT"},
            {"fieldPath": "event_time", "description": "Event time", "type": "TIMESTAMP"},
        ],
        "platform": "postgres",
    }
    datahub.snapshot = replace(
        datahub.snapshot,
        aspect_name="schemaMetadata",
        document=MappingProxyType(schema_document),
        content_hash=canonical_json_hash(schema_document),
    )

    preview = await service.preview_column_description(
        asset_id=index.detail.index.asset_id,
        field_path="event_id",
        description="Immutable event identifier",
        subject=subject,
        environment=environment,
        request_id="column-preview",
    )

    assert preview.aspect_name == "schemaMetadata"
    assert preview.field_path == "event_id"
    assert preview.current_description == "Legacy identifier"
    assert preview.before_hash == datahub.snapshot.content_hash
    assert preview.after_hash == canonical_json_hash(
        {
            "dataset": index.detail.index.external_urn,
            "fields": [
                {
                    "fieldPath": "event_id",
                    "description": "Immutable event identifier",
                    "type": "BIGINT",
                },
                {"fieldPath": "event_time", "description": "Event time", "type": "TIMESTAMP"},
            ],
            "platform": "postgres",
        }
    )

    await service.create_column_description_change_request(
        asset_id=index.detail.index.asset_id,
        expected_preview_etag=preview.preview_etag,
        field_path="event_id",
        description="Immutable event identifier",
        title="event_id column description update",
        change_description="Clarify the primary event identifier.",
        number="CR-FAB-260717-7F2A",
        subject=subject,
        environment=environment,
        request_id="column-create",
        idempotency_key="typed-column-description-0001",
        request_hash="f" * 64,
    )

    assert governance.arguments is not None
    item = governance.arguments["items"][0]
    assert item.aspect_name == "schemaMetadata"
    assert item.before_hash == preview.before_hash
    assert item.after_hash == preview.after_hash
    assert item.after_document["fields"][0] == {
        "fieldPath": "event_id",
        "description": "Immutable event identifier",
        "type": "BIGINT",
    }
    assert item.after_document["fields"][1] == {
        "fieldPath": "event_time",
        "description": "Event time",
        "type": "TIMESTAMP",
    }


@pytest.mark.asyncio
async def test_column_description_rejects_a_schema_field_that_drifted() -> None:
    service, index, datahub, governance, subject, environment, _ = _fixture()
    schema_document = {"fields": [{"fieldPath": "event_id", "description": "Identifier"}]}
    datahub.snapshot = replace(
        datahub.snapshot,
        aspect_name="schemaMetadata",
        document=MappingProxyType(schema_document),
        content_hash=canonical_json_hash(schema_document),
    )

    with pytest.raises(ConflictError, match="schema field is no longer available"):
        await service.preview_column_description(
            asset_id=index.detail.index.asset_id,
            field_path="removed_column",
            description="Will not be submitted",
            subject=subject,
            environment=environment,
            request_id="column-drift",
        )

    assert governance.arguments is None


@pytest.mark.asyncio
async def test_controlled_metadata_preserves_provider_document_and_uses_one_governed_aspect() -> (
    None
):
    service, index, datahub, governance, subject, environment, _ = _fixture()
    tag_document = {
        "tags": [{"tag": "urn:li:tag:legacy"}],
        "auditStamp": {"actor": "urn:li:corpuser:ingestor"},
    }
    datahub.snapshot = replace(
        datahub.snapshot,
        aspect_name="globalTags",
        document=MappingProxyType(tag_document),
        content_hash=canonical_json_hash(tag_document),
    )

    preview = await service.preview_controlled_metadata(
        asset_id=index.detail.index.asset_id,
        aspect_name="globalTags",
        refs=("urn:li:tag:governed",),
        subject=subject,
        environment=environment,
        request_id="tags-preview",
    )

    assert preview.current_refs == ("urn:li:tag:legacy",)
    assert preview.proposed_refs == ("urn:li:tag:governed",)
    assert preview.before_hash == datahub.snapshot.content_hash
    assert preview.after_hash == canonical_json_hash(
        {
            "tags": [{"tag": "urn:li:tag:governed"}],
            "auditStamp": {"actor": "urn:li:corpuser:ingestor"},
        }
    )

    await service.create_controlled_metadata_change_request(
        asset_id=index.detail.index.asset_id,
        aspect_name="globalTags",
        refs=("urn:li:tag:governed",),
        expected_preview_etag=preview.preview_etag,
        title="Apply governed tag",
        change_description="Replace the legacy tag after catalog review.",
        number="CR-FAB-260718-9A3C",
        subject=subject,
        environment=environment,
        request_id="tags-create",
        idempotency_key="controlled-metadata-change-0001",
        request_hash="c" * 64,
    )

    assert governance.arguments is not None
    assert governance.arguments["require_raw_operator_gate"] is False
    item = governance.arguments["items"][0]
    assert item.aspect_name == "globalTags"
    assert item.before_hash == preview.before_hash
    assert item.after_hash == preview.after_hash
    assert item.after_document == {
        "tags": [{"tag": "urn:li:tag:governed"}],
        "auditStamp": {"actor": "urn:li:corpuser:ingestor"},
    }


@pytest.mark.asyncio
async def test_controlled_metadata_rejects_wrong_urn_family_and_multiple_domains() -> None:
    service, index, _, _, subject, environment, _ = _fixture()

    with pytest.raises(ValidationError, match="controlled metadata reference"):
        await service.preview_controlled_metadata(
            asset_id=index.detail.index.asset_id,
            aspect_name="globalTags",
            refs=("urn:li:glossaryTerm:not-a-tag",),
            subject=subject,
            environment=environment,
            request_id="invalid-tag",
        )
    with pytest.raises(ValidationError, match="at most one controlled domain"):
        await service.preview_controlled_metadata(
            asset_id=index.detail.index.asset_id,
            aspect_name="domains",
            refs=("urn:li:domain:fab", "urn:li:domain:yield"),
            subject=subject,
            environment=environment,
            request_id="invalid-domain",
        )


@pytest.mark.asyncio
async def test_empty_description_removes_only_the_description_field() -> None:
    service, index, _, governance, subject, environment, _ = _fixture()
    preview = await service.preview(
        asset_id=index.detail.index.asset_id,
        description="",
        subject=subject,
        environment=environment,
        request_id="preview-clear",
    )

    await service.create_change_request(
        asset_id=index.detail.index.asset_id,
        expected_preview_etag=preview.preview_etag,
        description="",
        title="Clear description",
        change_description="Remove the obsolete description",
        number="CR-2026-CLEAR",
        subject=subject,
        environment=environment,
        request_id="create-clear",
        idempotency_key="typed-description-clear-0001",
        request_hash="b" * 64,
    )

    assert governance.arguments is not None
    assert governance.arguments["items"][0].after_document == {
        "customProperties": {"tier": "gold"},
        "name": "wafer",
    }


@pytest.mark.asyncio
async def test_create_rejects_preview_or_target_drift_before_governance() -> None:
    service, index, datahub, governance, subject, environment, _ = _fixture()
    preview = await service.preview(
        asset_id=index.detail.index.asset_id,
        description="Proposed description",
        subject=subject,
        environment=environment,
        request_id="preview",
    )
    datahub.snapshot = replace(datahub.snapshot, source_version="provider-v8")

    with pytest.raises(ConflictError, match="preview is stale"):
        await service.create_change_request(
            asset_id=index.detail.index.asset_id,
            expected_preview_etag=preview.preview_etag,
            description="Proposed description",
            title="Update",
            change_description="Provider changed",
            number="CR-2026-DRIFT",
            subject=subject,
            environment=environment,
            request_id="drift",
            idempotency_key="typed-description-drift-0001",
            request_hash="c" * 64,
        )
    assert governance.arguments is None

    index.current = replace(index.detail.index, asset_id=uuid4())
    with pytest.raises(ConflictError, match="catalog target changed"):
        await service.create_change_request(
            asset_id=index.detail.index.asset_id,
            expected_preview_etag=preview.preview_etag,
            description="Proposed description",
            title="Update",
            change_description="Asset replacement changed",
            number="CR-2026-ASSET-DRIFT",
            subject=subject,
            environment=environment,
            request_id="asset-drift",
            idempotency_key="typed-description-asset-drift-0001",
            request_hash="e" * 64,
        )
    assert governance.arguments is None

    index.current = index.detail.index
    datahub.snapshot = replace(datahub.snapshot, source_version="provider-v7")
    index.current = replace(index.current, domain_id=uuid4())
    with pytest.raises(ConflictError, match="catalog target changed"):
        await service.create_change_request(
            asset_id=index.detail.index.asset_id,
            expected_preview_etag=preview.preview_etag,
            description="Proposed description",
            title="Update",
            change_description="Target changed",
            number="CR-2026-TARGET-DRIFT",
            subject=subject,
            environment=environment,
            request_id="target-drift",
            idempotency_key="typed-description-target-drift-0001",
            request_hash="d" * 64,
        )
    assert governance.arguments is None


@pytest.mark.asyncio
async def test_noop_and_denied_change_never_reach_governance_or_provider() -> None:
    service, index, _, governance, subject, environment, _ = _fixture()
    with pytest.raises(ValidationError, match="does not change"):
        await service.preview(
            asset_id=index.detail.index.asset_id,
            description="Current description",
            subject=subject,
            environment=environment,
            request_id="noop",
        )
    assert governance.arguments is None

    denied_service, denied_index, datahub, _, subject, environment, _ = _fixture(
        denied=Action.CHANGE_CREATE
    )
    with pytest.raises(ForbiddenError):
        await denied_service.preview(
            asset_id=denied_index.detail.index.asset_id,
            description="Changed",
            subject=subject,
            environment=environment,
            request_id="denied",
        )
    assert datahub.calls == 0


@pytest.mark.asyncio
async def test_invalid_provider_document_is_rejected_without_governance() -> None:
    service, index, datahub, governance, subject, environment, _ = _fixture()
    invalid_document = MappingProxyType(
        {
            "description": "Current description",
            "customProperties": MappingProxyType({"score": float("nan")}),
        }
    )
    datahub.snapshot = replace(
        datahub.snapshot,
        document=invalid_document,
        content_hash=canonical_json_hash(
            {"description": "Current description", "customProperties": {"score": None}}
        ),
    )

    with pytest.raises(ExternalDependencyError, match="invalid datasetProperties document"):
        await service.preview(
            asset_id=index.detail.index.asset_id,
            description="Changed",
            subject=subject,
            environment=environment,
            request_id="invalid-provider-document",
        )

    assert governance.arguments is None
