from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

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
    DataHubAssetEnrichment,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import CatalogIndexReader, DataHubGateway, DecisionWriter
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog_metadata_compiler import (
    CatalogMetadataVocabularyReference,
)
from datariver.application.services.catalog_recommendations import (
    CatalogRecommendationApprovalReservation,
    CatalogRecommendationApprovalTarget,
    CatalogRecommendationSeed,
    CatalogRecommendationService,
)
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog_recommendations import (
    CatalogRecommendation,
    CatalogRecommendationDraft,
    CatalogRecommendationProviderResult,
    CatalogRecommendationState,
)
from datariver.domain.common import ConflictError, ForbiddenError, canonical_json_hash


class FakeClassificationAccess:
    async def resolve(self, **_: object) -> ClassificationAccessSnapshot:
        return static_classification_access_floor()


class FakeIndex:
    def __init__(self, details: dict[UUID, CatalogAssetDetail], events: list[str]) -> None:
        self.details = details
        self.events = events

    async def get_authorized_asset(
        self,
        *,
        asset_id: UUID,
        **_: object,
    ) -> CatalogAssetDetail | None:
        self.events.append(f"catalog:{asset_id}")
        return self.details.get(asset_id)


class FakeAuthorization:
    def __init__(self, events: list[str], denied: Action | None = None) -> None:
        self.events = events
        self.denied = denied
        self.denied_resource_id: UUID | None = None
        self.denied_resource_type: str | None = None

    async def authorize(self, *, action: Action, resource: object, **_: object) -> None:
        self.events.append(f"authorize:{action.value}")
        typed_resource = cast(Any, resource)
        if (
            action is self.denied
            or typed_resource.resource_id == self.denied_resource_id
            or typed_resource.resource_type == self.denied_resource_type
        ):
            raise ForbiddenError("denied")

    async def authorize_change_target(
        self,
        *,
        action: Action,
        resource: object,
        **_: object,
    ) -> None:
        self.events.append(f"authorize:{action.value}")
        typed_resource = cast(Any, resource)
        if (
            action is self.denied
            or typed_resource.resource_id == self.denied_resource_id
            or typed_resource.resource_type == self.denied_resource_type
        ):
            raise ForbiddenError("denied")


class CapturingDecisionWriter:
    def __init__(self) -> None:
        self.decisions: list[tuple[str, tuple[str, ...]]] = []

    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del subject_id, workspace_id, resource_id, request_id
        self.decisions.append((action, decision.reason_codes))


class FakeVocabulary:
    def __init__(
        self,
        values: dict[UUID, CatalogMetadataVocabularyReference],
        events: list[str],
    ) -> None:
        self.values = values
        self.events = events

    async def resolve_any(
        self,
        *,
        vocabulary_ids: tuple[UUID, ...],
        **_: object,
    ) -> dict[UUID, CatalogMetadataVocabularyReference]:
        self.events.append("vocabulary")
        values = {value: self.values[value] for value in vocabulary_ids if value in self.values}
        if len(values) != len(vocabulary_ids):
            raise ConflictError("inactive vocabulary")
        return values


class FakeDataHub:
    def __init__(
        self,
        enrichment: DataHubAssetEnrichment,
        aspects: dict[str, DataHubAspectSnapshot],
        events: list[str],
    ) -> None:
        self.enrichment = enrichment
        self.aspects = aspects
        self.events = events
        self.apply_calls = 0

    async def get_asset(self, external_urn: str) -> DataHubAssetEnrichment:
        del external_urn
        self.events.append("datahub-detail")
        return self.enrichment

    async def read_aspect(
        self,
        *,
        external_urn: str,
        aspect_name: str,
    ) -> DataHubAspectSnapshot:
        del external_urn
        self.events.append(f"datahub-aspect:{aspect_name}")
        return self.aspects[aspect_name]

    async def apply_change(self, **_: object) -> object:
        self.apply_calls += 1
        raise AssertionError("Recommendation mode must not mutate DataHub.")


class FakeProvider:
    maximum_classification = Classification.RESTRICTED

    def __init__(
        self,
        result: CatalogRecommendationProviderResult,
        events: list[str],
        *,
        filter_to_supplied: bool,
    ) -> None:
        self.result = result
        self.events = events
        self.calls = 0
        self.document: dict[str, object] | None = None
        self.filter_to_supplied = filter_to_supplied
        self.on_recommend: Callable[[], None] | None = None

    async def recommend(self, *, context: object) -> CatalogRecommendationProviderResult:
        self.events.append("provider")
        self.calls += 1
        self.document = cast(Any, context).provider_document()
        if self.on_recommend is not None:
            self.on_recommend()
        if not self.filter_to_supplied:
            return self.result
        allowed = {value.vocabulary_id for value in cast(Any, context).vocabulary}
        return replace(
            self.result,
            recommendations=tuple(
                value for value in self.result.recommendations if value.vocabulary_id in allowed
            ),
        )


class FakeStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.values: dict[UUID, CatalogRecommendation] = {}
        self.preview_replay: tuple[CatalogRecommendation, ...] | None = None
        self.saved = 0
        self.reserved = 0
        self.aborted = 0
        self.approval_replay: CatalogRecommendationApprovalReservation | None = None
        self.rejection_replay: CatalogRecommendation | None = None
        self.aborted_decisions = 0
        self.fail_finalize = False

    async def reserve_preview(self, **_: object) -> tuple[CatalogRecommendation, ...] | None:
        self.events.append("store-reserve-preview")
        return self.preview_replay

    async def abort_preview(self) -> None:
        self.aborted += 1

    async def save_preview(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        idempotency_key: str,
        request_hash: str,
        seeds: Sequence[CatalogRecommendationSeed],
    ) -> tuple[CatalogRecommendation, ...]:
        del workspace_id, subject_id, idempotency_key, request_hash
        self.events.append("store-save-preview")
        now = datetime.now(UTC)
        result = tuple(
            CatalogRecommendation(
                recommendation_id=value.recommendation_id,
                workspace_id=value.workspace_id,
                asset_id=value.asset_id,
                field_path=value.field_path,
                vocabulary_id=value.vocabulary_id,
                kind=value.kind,
                source_version=value.source_version,
                provider_source_version=value.provider_source_version,
                vocabulary_source_version=value.vocabulary_source_version,
                aspect_name=value.aspect_name,
                aspect_source_version=value.aspect_source_version,
                aspect_content_hash=value.aspect_content_hash,
                target_binding_hash=value.target_binding_hash,
                input_context_hash=value.input_context_hash,
                confidence=value.confidence,
                reason=value.reason,
                evidence=value.evidence,
                provider=value.provider,
                model=value.model,
                prompt_version=value.prompt_version,
                rule_version=value.rule_version,
                state=CatalogRecommendationState.NEEDS_DECISION,
                version=1,
                created_by=value.created_by,
                decision_actor_id=None,
                change_request_id=None,
                created_at=now,
                updated_at=now,
            )
            for value in seeds
        )
        self.values.update({value.recommendation_id: value for value in result})
        self.saved += len(result)
        return result

    async def get_many(
        self,
        *,
        workspace_id: UUID,
        recommendation_ids: Sequence[UUID],
        for_update: bool = False,
    ) -> tuple[CatalogRecommendation, ...]:
        del workspace_id, for_update
        return tuple(self.values[value] for value in recommendation_ids if value in self.values)

    async def get_approval_replay(
        self,
        *,
        subject_id: UUID,
        **_: object,
    ) -> CatalogRecommendationApprovalReservation | None:
        if self.approval_replay is not None and any(
            value.decision_actor_id != subject_id for value in self.approval_replay.recommendations
        ):
            raise ForbiddenError("The approval replay belongs to another subject.")
        return self.approval_replay

    async def get_rejection_replay(self, **_: object) -> CatalogRecommendation | None:
        return self.rejection_replay

    async def reserve_approval(
        self,
        *,
        recommendation_ids: tuple[UUID, ...],
        expected_versions: tuple[int, ...],
        **_: object,
    ) -> CatalogRecommendationApprovalReservation:
        self.events.append("store-reserve-approval")
        values = tuple(self.values[value] for value in recommendation_ids)
        if any(
            value.version != expected
            for value, expected in zip(values, expected_versions, strict=True)
        ):
            raise ConflictError("CAS")
        self.reserved += 1
        return CatalogRecommendationApprovalReservation(values, None)

    async def abort_decision(self) -> None:
        self.events.append("store-abort-decision")
        self.aborted_decisions += 1

    async def finalize_approval(
        self,
        *,
        recommendation_ids: tuple[UUID, ...],
        expected_versions: tuple[int, ...],
        actor_id: UUID,
        change_request_id: UUID,
        **_: object,
    ) -> tuple[CatalogRecommendation, ...]:
        self.events.append("store-finalize-approval")
        if self.fail_finalize:
            raise ConflictError("finalize failed")
        current = tuple(self.values[value] for value in recommendation_ids)
        if any(
            value.version != expected
            for value, expected in zip(current, expected_versions, strict=True)
        ):
            raise ConflictError("CAS")
        values = tuple(
            replace(
                value,
                state=CatalogRecommendationState.APPROVED,
                decision_actor_id=actor_id,
                change_request_id=change_request_id,
                version=value.version + 1,
            )
            for value in current
        )
        self.values.update({value.recommendation_id: value for value in values})
        self.approval_replay = CatalogRecommendationApprovalReservation(
            values,
            change_request_id,
        )
        return values

    async def reject(
        self,
        *,
        recommendation_id: UUID,
        expected_version: int,
        **_: object,
    ) -> CatalogRecommendation:
        self.events.append("store-reject")
        value = self.values[recommendation_id]
        if value.version != expected_version:
            raise ConflictError("CAS")
        value = replace(
            value,
            state=CatalogRecommendationState.REJECTED,
            decision_actor_id=cast(UUID, _.get("actor_id")),
            version=value.version + 1,
        )
        self.values[recommendation_id] = value
        self.rejection_replay = value
        return value


class FakeGovernance:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.change_request_id = uuid4()
        self.arguments: dict[str, Any] | None = None
        self.fail_before_commit: Exception | None = None
        self.calls = 0
        self.created = 0

    async def create_catalog_recommendation_change_request(self, **arguments: Any) -> Any:
        self.events.append("governance")
        self.calls += 1
        self.arguments = arguments
        if self.fail_before_commit is not None:
            raise self.fail_before_commit
        change_request = SimpleNamespace(change_request_id=self.change_request_id)
        recommendation_finalizer = arguments.get("recommendation_finalizer")
        if recommendation_finalizer is not None:
            await recommendation_finalizer.finalize_catalog_recommendation_approval(
                change_request=change_request
            )
        self.created += 1
        return change_request


def _fixture(
    *,
    provider_result: CatalogRecommendationProviderResult | None = None,
    denied: Action | None = None,
    assigned_tag: bool = False,
    truncated: bool = False,
) -> tuple[
    CatalogRecommendationService,
    CatalogAssetIndex,
    UUID,
    UUID,
    SubjectAttributes,
    EnvironmentAttributes,
    FakeProvider,
    FakeStore,
    FakeDataHub,
    FakeGovernance,
    FakeIndex,
    list[str],
]:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    asset = CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:(urn:li:dataPlatform:generic,db.schema.asset,PROD)",
        asset_type="DATASET",
        name="asset",
        description="projection",
        platform="generic",
        domain_id=uuid4(),
        system_id=uuid4(),
        owner_department_id=uuid4(),
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="catalog-v1",
        observed_at=now,
        database_name="db",
        schema_name="schema",
    )
    detail = CatalogAssetDetail(asset, (), (), (), (), {}, "catalog-v1", now)
    enrichment = DataHubAssetEnrichment(
        ownership=(),
        glossary_terms=(),
        tags=(),
        schema_fields=({"fieldPath": "field_a", "nativeDataType": "text"},),
        quality={},
        raw_version="provider-v1",
        observed_at=now,
        description="current metadata",
        schema_fields_total=1,
        schema_fields_truncated=truncated,
        schema_fields_total_exact=True,
    )
    tag_id = uuid4()
    term_id = uuid4()
    tag_ref = "urn:li:tag:exact"
    tag_document = {"tags": [{"tag": tag_ref}]} if assigned_tag else {"tags": []}
    term_document: dict[str, list[dict[str, str]]] = {"terms": []}
    aspects = {
        "globalTags": DataHubAspectSnapshot(
            urn=asset.external_urn,
            aspect_name="globalTags",
            content_hash=canonical_json_hash(tag_document),
            source_version="tag-aspect-v1",
            observed_at=now,
            document=tag_document,
        ),
        "glossaryTerms": DataHubAspectSnapshot(
            urn=asset.external_urn,
            aspect_name="glossaryTerms",
            content_hash=canonical_json_hash(term_document),
            source_version="term-aspect-v1",
            observed_at=now,
            document=term_document,
        ),
    }
    events: list[str] = []
    index = FakeIndex({asset.asset_id: detail}, events)
    datahub = FakeDataHub(enrichment, aspects, events)
    vocabulary = FakeVocabulary(
        {
            tag_id: CatalogMetadataVocabularyReference(
                tag_id,
                "TAG",
                tag_ref,
                "tag-v1",
                "Exact tag",
            ),
            term_id: CatalogMetadataVocabularyReference(
                term_id,
                "TERM",
                "urn:li:glossaryTerm:term",
                "term-v1",
                "Term",
            ),
        },
        events,
    )
    result = provider_result or CatalogRecommendationProviderResult(
        recommendations=(
            CatalogRecommendationDraft(tag_id, 0.8, "tag reason", ("tag evidence",)),
            CatalogRecommendationDraft(term_id, 0.7, "term reason", ("term evidence",)),
        ),
        provider="typed-provider",
        model="model-v1",
        prompt_version="prompt-v1",
        rule_version="rule-v1",
    )
    provider = FakeProvider(
        result,
        events,
        filter_to_supplied=provider_result is None,
    )
    store = FakeStore(events)
    governance = FakeGovernance(events)
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.INTERNAL,
    )
    service = CatalogRecommendationService(
        index=cast(CatalogIndexReader, index),
        classification_access=cast(ClassificationAccessResolver, FakeClassificationAccess()),
        authorization=cast(AuthorizationService, FakeAuthorization(events, denied)),
        datahub=cast(DataHubGateway, datahub),
        vocabulary=vocabulary,
        provider=provider,
        store=store,
        governance=governance,
    )
    return (
        service,
        asset,
        tag_id,
        term_id,
        subject,
        EnvironmentAttributes(now),
        provider,
        store,
        datahub,
        governance,
        index,
        events,
    )


@pytest.mark.asyncio
async def test_preview_authorizes_suppresses_and_omits_absent_fields() -> None:
    (
        service,
        asset,
        tag_id,
        term_id,
        subject,
        environment,
        provider,
        store,
        datahub,
        _,
        _,
        events,
    ) = _fixture(assigned_tag=True)

    values = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path="field_a",
        source_version="catalog-v1",
        vocabulary_ids=(tag_id, term_id),
        subject=subject,
        environment=environment,
        request_id="preview",
        idempotency_key="recommend-preview-0001",
        request_hash="a" * 64,
    )

    assert [value.vocabulary_id for value in values] == [term_id]
    assert values[0].state is CatalogRecommendationState.NEEDS_DECISION
    assert store.saved == 1
    assert datahub.apply_calls == 0
    assert provider.document is not None
    assert "synonyms" not in str(provider.document)
    assert "hierarchy" not in str(provider.document)
    assert "provider_ref" not in str(provider.document)
    assert events.index("authorize:change.create") < events.index("datahub-detail")
    assert events.index("datahub-aspect:glossaryTerms") < events.index("provider")
    assert str(tag_id) in cast(list[str], provider.document["assigned_vocabulary_ids"])


@pytest.mark.asyncio
async def test_preview_replay_does_not_call_provider_or_duplicate_state() -> None:
    service, asset, tag_id, _, subject, environment, provider, store, *_ = _fixture()
    first = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="first",
        idempotency_key="recommend-preview-0002",
        request_hash="b" * 64,
    )
    store.preview_replay = first

    replay = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="replay",
        idempotency_key="recommend-preview-0002",
        request_hash="b" * 64,
    )

    assert replay == first
    assert provider.calls == 1
    assert store.saved == 1


@pytest.mark.asyncio
async def test_preview_invalid_provider_identity_fails_without_state_or_provider_mutation() -> None:
    invalid_id = uuid4()
    result = CatalogRecommendationProviderResult(
        recommendations=(CatalogRecommendationDraft(invalid_id, 0.5, "reason", ("evidence",)),),
        provider="provider",
        model="model",
        prompt_version="prompt",
        rule_version="rule",
    )
    service, asset, tag_id, _, subject, environment, provider, store, datahub, *_ = _fixture(
        provider_result=result
    )

    with pytest.raises(ExternalDependencyError, match="identity outside"):
        await service.preview(
            workspace_id=subject.workspace_id,
            asset_id=asset.asset_id,
            field_path=None,
            source_version="catalog-v1",
            vocabulary_ids=(tag_id,),
            subject=subject,
            environment=environment,
            request_id="invalid-provider",
            idempotency_key="recommend-preview-0003",
            request_hash="c" * 64,
        )

    assert store.saved == 0
    assert store.aborted == 1
    assert provider.calls == 1
    assert datahub.apply_calls == 0


@pytest.mark.asyncio
async def test_preview_rechecks_current_input_after_provider_before_state() -> None:
    service, asset, tag_id, _, subject, environment, provider, store, datahub, *_ = _fixture()
    provider.on_recommend = lambda: setattr(
        datahub,
        "enrichment",
        replace(datahub.enrichment, raw_version="provider-v2"),
    )

    with pytest.raises(ConflictError, match="changed while the provider"):
        await service.preview(
            workspace_id=subject.workspace_id,
            asset_id=asset.asset_id,
            field_path=None,
            source_version="catalog-v1",
            vocabulary_ids=(tag_id,),
            subject=subject,
            environment=environment,
            request_id="provider-race",
            idempotency_key="recommend-preview-race",
            request_hash="8" * 64,
        )

    assert provider.calls == 1
    assert store.saved == 0
    assert store.aborted == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["cross-workspace", "authorization", "inactive-vocabulary"])
async def test_preview_auth_and_vocabulary_fail_before_provider_or_state(case: str) -> None:
    denied = Action.CATALOG_READ if case == "authorization" else None
    service, asset, tag_id, _, subject, environment, provider, store, *_ = _fixture(denied=denied)
    workspace_id = uuid4() if case == "cross-workspace" else subject.workspace_id
    vocabulary_ids = (uuid4(),) if case == "inactive-vocabulary" else (tag_id,)

    with pytest.raises((ForbiddenError, ConflictError)):
        await service.preview(
            workspace_id=workspace_id,
            asset_id=asset.asset_id,
            field_path=None,
            source_version="catalog-v1",
            vocabulary_ids=vocabulary_ids,
            subject=subject,
            environment=environment,
            request_id=case,
            idempotency_key="recommend-preview-0004",
            request_hash="d" * 64,
        )

    assert provider.calls == 0
    assert store.saved == 0


@pytest.mark.asyncio
async def test_systemless_public_target_denies_before_datahub_provider_or_state() -> None:
    (
        service,
        asset,
        tag_id,
        _,
        subject,
        environment,
        provider,
        store,
        _,
        _,
        index,
        events,
    ) = _fixture()
    decision_writer = CapturingDecisionWriter()
    cast(Any, service)._authorization = AuthorizationService(
        decision_writer=cast(DecisionWriter, decision_writer)
    )
    subject = replace(
        subject,
        allowed_actions=frozenset({Action.CATALOG_READ, Action.CHANGE_CREATE}),
    )
    index.details[asset.asset_id] = replace(
        index.details[asset.asset_id],
        index=replace(asset, system_id=None, classification=Classification.PUBLIC),
    )

    with pytest.raises(ForbiddenError) as exc_info:
        await service.preview(
            workspace_id=subject.workspace_id,
            asset_id=asset.asset_id,
            field_path=None,
            source_version="catalog-v1",
            vocabulary_ids=(tag_id,),
            subject=subject,
            environment=environment,
            request_id="system-scope-required",
            idempotency_key="recommend-preview-system-scope-required",
            request_hash="7" * 64,
        )

    assert exc_info.value.details["reason_codes"] == ("SYSTEM_SCOPE_REQUIRED",)
    assert decision_writer.decisions == [
        (Action.CATALOG_READ.value, ("POLICY_ALLOW",)),
        (Action.CHANGE_CREATE.value, ("SYSTEM_SCOPE_REQUIRED",)),
    ]
    assert "datahub-detail" not in events
    assert not any(event.startswith("datahub-aspect:") for event in events)
    assert provider.calls == 0
    assert store.saved == 0
    assert store.reserved == 0
    assert not any(event.startswith("store-") for event in events)


@pytest.mark.asyncio
async def test_preview_fails_closed_on_stale_source_and_truncated_field_input() -> None:
    service, asset, tag_id, _, subject, environment, provider, store, *_ = _fixture(truncated=True)
    with pytest.raises(ConflictError, match="source is stale"):
        await service.preview(
            workspace_id=subject.workspace_id,
            asset_id=asset.asset_id,
            field_path=None,
            source_version="stale",
            vocabulary_ids=(tag_id,),
            subject=subject,
            environment=environment,
            request_id="stale",
            idempotency_key="recommend-preview-0005",
            request_hash="e" * 64,
        )
    with pytest.raises(ConflictError, match="incomplete"):
        await service.preview(
            workspace_id=subject.workspace_id,
            asset_id=asset.asset_id,
            field_path="field_a",
            source_version="catalog-v1",
            vocabulary_ids=(tag_id,),
            subject=subject,
            environment=environment,
            request_id="truncated",
            idempotency_key="recommend-preview-0006",
            request_hash="f" * 64,
        )
    assert provider.calls == 0
    assert store.saved == 0


@pytest.mark.asyncio
async def test_approval_compiles_to_cr_without_provider_mutation() -> None:
    (
        service,
        asset,
        tag_id,
        _,
        subject,
        environment,
        provider,
        store,
        datahub,
        governance,
        _,
        events,
    ) = _fixture()
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path="field_a",
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="preview",
        idempotency_key="recommend-preview-0007",
        request_hash="1" * 64,
    )
    events.clear()

    result = await service.approve(
        workspace_id=subject.workspace_id,
        targets=(CatalogRecommendationApprovalTarget(preview[0].recommendation_id, 1),),
        title="Approve recommendation",
        reason="Reviewed evidence",
        subject=subject,
        environment=environment,
        request_id="approve",
        idempotency_key="recommend-approve-0001",
        request_hash="2" * 64,
    )

    assert result.change_request_id == governance.change_request_id
    assert result.recommendations[0].state is CatalogRecommendationState.APPROVED
    assert result.recommendations[0].version == 2
    assert governance.arguments is not None
    assert governance.arguments["require_raw_operator_gate"] is False
    assert governance.arguments["request_type"] == "CATALOG_METADATA_RECOMMENDATION"
    item = governance.arguments["items"][0]
    assert item.aspect_name == "globalTags"
    assert item.after_document == {"tags": [{"tag": "urn:li:tag:exact"}]}
    assert store.reserved == 1
    assert provider.calls == 1
    assert datahub.apply_calls == 0
    assert events.index("datahub-aspect:globalTags") < events.index("store-reserve-approval")
    assert events.index("store-reserve-approval") < events.index("governance")

    replay = await service.approve(
        workspace_id=subject.workspace_id,
        targets=(CatalogRecommendationApprovalTarget(preview[0].recommendation_id, 1),),
        title="Approve recommendation",
        reason="Reviewed evidence",
        subject=subject,
        environment=environment,
        request_id="approve-replay",
        idempotency_key="recommend-approve-0001",
        request_hash="2" * 64,
    )
    assert replay == result
    assert events.count("governance") == 1


@pytest.mark.asyncio
async def test_reject_is_cas_guarded_and_records_only_after_current_authorization() -> None:
    service, asset, tag_id, _, subject, environment, _, store, _, _, _, events = _fixture()
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="preview",
        idempotency_key="recommend-preview-0008",
        request_hash="3" * 64,
    )
    with pytest.raises(ConflictError, match="CAS"):
        await service.reject(
            workspace_id=subject.workspace_id,
            recommendation_id=preview[0].recommendation_id,
            expected_version=2,
            reason="Not suitable",
            subject=subject,
            environment=environment,
            request_id="reject-stale",
            idempotency_key="recommend-reject-0001",
            request_hash="4" * 64,
        )
    assert (
        store.values[preview[0].recommendation_id].state
        is CatalogRecommendationState.NEEDS_DECISION
    )

    value = await service.reject(
        workspace_id=subject.workspace_id,
        recommendation_id=preview[0].recommendation_id,
        expected_version=1,
        reason="Not suitable",
        subject=subject,
        environment=environment,
        request_id="reject",
        idempotency_key="recommend-reject-0002",
        request_hash="5" * 64,
    )
    assert value.state is CatalogRecommendationState.REJECTED
    assert events.index("authorize:change.create") < events.index("store-reject")
    reject_calls = events.count("store-reject")
    replay = await service.reject(
        workspace_id=subject.workspace_id,
        recommendation_id=preview[0].recommendation_id,
        expected_version=1,
        reason="Not suitable",
        subject=subject,
        environment=environment,
        request_id="reject-replay",
        idempotency_key="recommend-reject-0002",
        request_hash="5" * 64,
    )
    assert replay == value
    assert events.count("store-reject") == reject_calls


@pytest.mark.asyncio
async def test_bulk_partial_authorization_failure_has_no_decision_or_cr_side_effect() -> None:
    service, asset, tag_id, _, subject, environment, _, store, _, governance, index, _ = _fixture()
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="preview",
        idempotency_key="recommend-preview-0009",
        request_hash="6" * 64,
    )
    missing = replace(
        preview[0],
        recommendation_id=uuid4(),
        asset_id=uuid4(),
    )
    store.values[missing.recommendation_id] = missing
    assert missing.asset_id not in index.details

    with pytest.raises(ConflictError, match="unavailable"):
        await service.approve(
            workspace_id=subject.workspace_id,
            targets=(
                CatalogRecommendationApprovalTarget(preview[0].recommendation_id, 1),
                CatalogRecommendationApprovalTarget(missing.recommendation_id, 1),
            ),
            title="Bulk approval",
            reason="Reviewed",
            subject=subject,
            environment=environment,
            request_id="bulk",
            idempotency_key="recommend-approve-0002",
            request_hash="7" * 64,
        )

    assert store.reserved == 0
    assert governance.arguments is None


@pytest.mark.asyncio
@pytest.mark.parametrize("denied_scope", ["later-target", "collection"])
async def test_bulk_preauthorization_denial_precedes_provider_reads_and_state(
    denied_scope: str,
) -> None:
    (
        service,
        asset,
        tag_id,
        _,
        subject,
        environment,
        provider,
        store,
        _,
        governance,
        index,
        events,
    ) = _fixture()
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="preview-preauthorization",
        idempotency_key="recommend-preview-preauth",
        request_hash="9" * 64,
    )
    second_asset = replace(asset, asset_id=uuid4(), external_urn=asset.external_urn + ":second")
    index.details[second_asset.asset_id] = replace(
        index.details[asset.asset_id],
        index=second_asset,
    )
    second = replace(
        preview[0],
        recommendation_id=uuid4(),
        asset_id=second_asset.asset_id,
    )
    store.values[second.recommendation_id] = second
    authorization = cast(Any, service)._authorization
    if denied_scope == "later-target":
        authorization.denied_resource_id = second_asset.asset_id
    else:
        authorization.denied_resource_type = "change_request_collection"
    events.clear()
    provider.calls = 0

    with pytest.raises(ForbiddenError, match="denied"):
        await service.approve(
            workspace_id=subject.workspace_id,
            targets=tuple(
                CatalogRecommendationApprovalTarget(value.recommendation_id, 1)
                for value in (preview[0], second)
            ),
            title="Bulk preauthorization",
            reason="Reviewed",
            subject=subject,
            environment=environment,
            request_id=f"deny-{denied_scope}",
            idempotency_key=f"recommend-deny-{denied_scope}",
            request_hash="a" * 64,
        )

    assert provider.calls == 0
    assert "datahub-detail" not in events
    assert store.reserved == 0
    assert governance.calls == 0
    assert all(
        value.state is CatalogRecommendationState.NEEDS_DECISION for value in store.values.values()
    )


@pytest.mark.asyncio
async def test_governance_denial_rolls_back_locked_batch_without_anonymous_reservation() -> None:
    service, asset, tag_id, _, subject, environment, provider, store, _, governance, *_ = _fixture()
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="preview-governance-race",
        idempotency_key="recommend-preview-governance-race",
        request_hash="b" * 64,
    )
    provider.calls = 0
    governance.fail_before_commit = ForbiddenError("collection revoked")

    with pytest.raises(ForbiddenError, match="revoked"):
        await service.approve(
            workspace_id=subject.workspace_id,
            targets=(CatalogRecommendationApprovalTarget(preview[0].recommendation_id, 1),),
            title="Race denied",
            reason="Reviewed",
            subject=subject,
            environment=environment,
            request_id="governance-race",
            idempotency_key="recommend-governance-race",
            request_hash="c" * 64,
        )

    assert provider.calls == 0
    assert (
        store.values[preview[0].recommendation_id].state
        is CatalogRecommendationState.NEEDS_DECISION
    )
    assert store.values[preview[0].recommendation_id].decision_actor_id is None
    assert store.aborted_decisions == 1
    assert governance.created == 0


@pytest.mark.asyncio
async def test_subject_bound_replay_denies_cross_subject_after_fresh_authorization() -> None:
    service, asset, tag_id, _, subject, environment, _, store, _, governance, *_ = _fixture()
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="preview-subject-replay",
        idempotency_key="recommend-preview-subject-replay",
        request_hash="d" * 64,
    )
    target = CatalogRecommendationApprovalTarget(preview[0].recommendation_id, 1)
    await service.approve(
        workspace_id=subject.workspace_id,
        targets=(target,),
        title="Subject replay",
        reason="Reviewed",
        subject=subject,
        environment=environment,
        request_id="owner",
        idempotency_key="recommend-subject-replay",
        request_hash="e" * 64,
    )
    other_subject = replace(subject, subject_id=uuid4())

    with pytest.raises(ForbiddenError, match="another subject"):
        await service.approve(
            workspace_id=subject.workspace_id,
            targets=(target,),
            title="Subject replay",
            reason="Reviewed",
            subject=other_subject,
            environment=environment,
            request_id="other",
            idempotency_key="recommend-subject-replay",
            request_hash="e" * 64,
        )

    assert governance.created == 1
    assert store.values[target.recommendation_id].decision_actor_id == subject.subject_id


@pytest.mark.asyncio
async def test_finalize_failure_rolls_back_cr_then_retry_creates_one_decision_and_cr() -> None:
    service, asset, tag_id, _, subject, environment, _, store, _, governance, *_ = _fixture()
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        asset_id=asset.asset_id,
        field_path=None,
        source_version="catalog-v1",
        vocabulary_ids=(tag_id,),
        subject=subject,
        environment=environment,
        request_id="preview-finalize-recovery",
        idempotency_key="recommend-preview-finalize-recovery",
        request_hash="f" * 64,
    )
    target = CatalogRecommendationApprovalTarget(preview[0].recommendation_id, 1)

    async def approve() -> object:
        return await service.approve(
            workspace_id=subject.workspace_id,
            targets=(target,),
            title="Finalize recovery",
            reason="Reviewed",
            subject=subject,
            environment=environment,
            request_id="finalize-recovery",
            idempotency_key="recommend-finalize-recovery",
            request_hash="1" * 64,
        )

    store.fail_finalize = True
    with pytest.raises(ConflictError, match="finalize failed"):
        await approve()
    assert governance.created == 0
    assert (
        store.values[preview[0].recommendation_id].state
        is CatalogRecommendationState.NEEDS_DECISION
    )
    assert store.approval_replay is None

    store.fail_finalize = False
    result = cast(Any, await approve())
    replay = await approve()

    assert replay == result
    assert governance.created == 1
    assert result.recommendations[0].version == 2
