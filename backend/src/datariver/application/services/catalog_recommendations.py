from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataAspect,
    CatalogMetadataCandidateDraft,
    CatalogMetadataCandidateKind,
    CatalogMetadataOperation,
    CatalogMetadataRecordKind,
    CatalogMetadataRowEvidence,
)
from datariver.application.change_numbers import change_request_number
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    CatalogAssetIndex,
    DataHubAspectSnapshot,
    DataHubAssetEnrichment,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import CatalogIndexReader, DataHubGateway
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog_description import controlled_metadata_refs
from datariver.application.services.catalog_metadata_compiler import (
    CatalogMetadataVocabularyReference,
    compile_catalog_metadata_mutation,
)
from datariver.application.services.governance import CatalogRecommendationApprovalFinalizer
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog import is_dataset_asset_type
from datariver.domain.catalog_recommendations import (
    MAXIMUM_RECOMMENDATIONS,
    CatalogRecommendation,
    CatalogRecommendationContext,
    CatalogRecommendationDraft,
    CatalogRecommendationKind,
    CatalogRecommendationProviderResult,
    CatalogRecommendationState,
    CatalogRecommendationVocabulary,
)
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
    uuid7,
)
from datariver.domain.governance import ChangeItem, ChangeRequest, change_target_binding_hash


class CatalogRecommendationProvider(Protocol):
    maximum_classification: Classification

    async def recommend(
        self,
        *,
        context: CatalogRecommendationContext,
    ) -> CatalogRecommendationProviderResult: ...


@dataclass(frozen=True, slots=True)
class CatalogRecommendationSeed:
    recommendation_id: UUID
    workspace_id: UUID
    asset_id: UUID
    field_path: str | None
    vocabulary_id: UUID
    kind: CatalogRecommendationKind
    source_version: str
    provider_source_version: str
    vocabulary_source_version: str
    aspect_name: str
    aspect_source_version: str
    aspect_content_hash: str
    target_binding_hash: str
    input_context_hash: str
    confidence: float
    reason: str
    evidence: tuple[str, ...]
    provider: str
    model: str
    prompt_version: str
    rule_version: str
    created_by: UUID


@dataclass(frozen=True, slots=True)
class CatalogRecommendationApprovalReservation:
    recommendations: tuple[CatalogRecommendation, ...]
    completed_change_request_id: UUID | None


class CatalogRecommendationVocabularyResolver(Protocol):
    async def resolve_any(
        self,
        *,
        workspace_id: UUID,
        vocabulary_ids: tuple[UUID, ...],
    ) -> Mapping[UUID, CatalogMetadataVocabularyReference]: ...


class CatalogRecommendationStore(Protocol):
    async def reserve_preview(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[CatalogRecommendation, ...] | None: ...

    async def abort_preview(self) -> None: ...

    async def save_preview(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        idempotency_key: str,
        request_hash: str,
        seeds: Sequence[CatalogRecommendationSeed],
    ) -> tuple[CatalogRecommendation, ...]: ...

    async def get_many(
        self,
        *,
        workspace_id: UUID,
        recommendation_ids: Sequence[UUID],
        for_update: bool = False,
    ) -> tuple[CatalogRecommendation, ...]: ...

    async def get_approval_replay(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        recommendation_ids: tuple[UUID, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendationApprovalReservation | None: ...

    async def get_rejection_replay(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        recommendation_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendation | None: ...

    async def reserve_approval(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        recommendation_ids: tuple[UUID, ...],
        expected_versions: tuple[int, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendationApprovalReservation: ...

    async def abort_decision(self) -> None: ...

    async def finalize_approval(
        self,
        *,
        workspace_id: UUID,
        expected_versions: tuple[int, ...],
        recommendation_ids: tuple[UUID, ...],
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        change_request_id: UUID,
    ) -> tuple[CatalogRecommendation, ...]: ...

    async def reject(
        self,
        *,
        workspace_id: UUID,
        recommendation_id: UUID,
        expected_version: int,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
        reason: str,
    ) -> CatalogRecommendation: ...


class CatalogRecommendationGovernance(Protocol):
    async def create_catalog_recommendation_change_request(
        self,
        *,
        workspace_id: UUID,
        number: str,
        request_type: str,
        title: str,
        description: str,
        requester_id: UUID,
        items: list[ChangeItem],
        subject: SubjectAttributes,
        classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
        require_raw_operator_gate: bool,
        recommendation_finalizer: CatalogRecommendationApprovalFinalizer,
    ) -> ChangeRequest: ...


class UnavailableCatalogRecommendationProvider:
    """Fail closed until deployment supplies an explicitly reviewed typed provider."""

    maximum_classification = Classification.RESTRICTED

    async def recommend(
        self,
        *,
        context: CatalogRecommendationContext,
    ) -> CatalogRecommendationProviderResult:
        del context
        raise ExternalDependencyError(
            "Catalog recommendation provider is unavailable.",
            dependency="catalog_recommendation_provider",
            retryable=False,
            provider_code="NOT_CONFIGURED",
        )


class DeterministicCatalogRecommendationProvider:
    """Rank caller-selected local vocabulary without disclosing metadata externally.

    This intentionally uses only the already-authorized, bounded context assembled by the
    service.  It cannot discover or invent provider identities, and an exact assignment is
    still suppressed again by the service before a durable preview is written.
    """

    maximum_classification = Classification.RESTRICTED
    _provider = "datariver_local_similarity"
    _model = "normalized_token_overlap_v1"
    _prompt_version = "none"
    _rule_version = "catalog-recommendation-local-v1"

    async def recommend(
        self,
        *,
        context: CatalogRecommendationContext,
    ) -> CatalogRecommendationProviderResult:
        assigned = set(context.assigned_vocabulary_ids)
        fields = tuple(
            (label, _recommendation_tokens(value))
            for label, value in (
                ("asset name", context.name),
                ("description", context.description),
                ("platform", context.platform),
                ("database", context.database_name),
                ("schema", context.schema_name),
                ("field path", context.field_path),
                ("field type", context.field_native_type),
            )
            if value
        )
        drafts: list[tuple[float, str, str, CatalogRecommendationDraft]] = []
        for vocabulary in context.vocabulary:
            if vocabulary.vocabulary_id in assigned:
                continue
            candidate_tokens = _recommendation_tokens(vocabulary.display_name)
            if not candidate_tokens:
                continue
            matches = tuple(
                (label, len(candidate_tokens.intersection(tokens)))
                for label, tokens in fields
                if candidate_tokens.intersection(tokens)
            )
            matched_tokens = sum(count for _, count in matches)
            covered_tokens = len(set().union(*(
                candidate_tokens.intersection(tokens) for _, tokens in fields
            ))) if fields else 0
            coverage = covered_tokens / len(candidate_tokens)
            if matched_tokens == 0 or coverage < 0.5:
                continue
            confidence = min(0.95, 0.5 + (coverage * 0.3) + min(len(matches), 3) * 0.05)
            evidence = tuple(
                f"{label}: normalized token overlap {count}/{len(candidate_tokens)}"
                for label, count in matches[:3]
            )
            draft = CatalogRecommendationDraft(
                vocabulary_id=vocabulary.vocabulary_id,
                confidence=round(confidence, 4),
                reason=(
                    "The selected controlled-vocabulary label overlaps the current authorized "
                    "catalog metadata. Review is required before a governed change request."
                ),
                evidence=evidence,
            )
            drafts.append(
                (
                    -draft.confidence,
                    vocabulary.kind.value,
                    unicodedata.normalize("NFKC", vocabulary.display_name).casefold(),
                    draft,
                )
            )
        drafts.sort(key=lambda value: (value[0], value[1], value[2], str(value[3].vocabulary_id)))
        return CatalogRecommendationProviderResult(
            recommendations=tuple(value[3] for value in drafts[:MAXIMUM_RECOMMENDATIONS]),
            provider=self._provider,
            model=self._model,
            prompt_version=self._prompt_version,
            rule_version=self._rule_version,
        )


def _recommendation_tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value)
    # Split camelCase before replacing punctuation, while retaining non-Latin word tokens.
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    normalized = normalized.casefold()
    return frozenset(
        token
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if len(token) >= 2
    )


@dataclass(frozen=True, slots=True)
class CatalogRecommendationApprovalTarget:
    recommendation_id: UUID
    expected_version: int


@dataclass(frozen=True, slots=True)
class CatalogRecommendationApprovalResult:
    recommendations: tuple[CatalogRecommendation, ...]
    change_request_id: UUID


@dataclass(slots=True)
class _CatalogRecommendationTransactionFinalizer:
    store: CatalogRecommendationStore
    workspace_id: UUID
    recommendation_ids: tuple[UUID, ...]
    expected_versions: tuple[int, ...]
    actor_id: UUID
    idempotency_key: str
    request_hash: str
    reason: str
    result: tuple[CatalogRecommendation, ...] | None = None

    async def finalize_catalog_recommendation_approval(
        self,
        *,
        change_request: ChangeRequest,
    ) -> None:
        self.result = await self.store.finalize_approval(
            workspace_id=self.workspace_id,
            recommendation_ids=self.recommendation_ids,
            expected_versions=self.expected_versions,
            actor_id=self.actor_id,
            idempotency_key=self.idempotency_key,
            request_hash=self.request_hash,
            reason=self.reason,
            change_request_id=change_request.change_request_id,
        )


@dataclass(frozen=True, slots=True)
class _CurrentInput:
    asset: CatalogAssetIndex
    enrichment: DataHubAssetEnrichment
    field_native_type: str | None
    vocabulary: Mapping[UUID, CatalogMetadataVocabularyReference]
    aspects: Mapping[CatalogRecommendationKind, DataHubAspectSnapshot]
    assigned_ids: tuple[UUID, ...]
    context: CatalogRecommendationContext


class CatalogRecommendationService:
    """Create durable Tag/Term suggestions; every application remains a governed CR."""

    def __init__(
        self,
        *,
        index: CatalogIndexReader,
        classification_access: ClassificationAccessResolver,
        authorization: AuthorizationService,
        datahub: DataHubGateway,
        vocabulary: CatalogRecommendationVocabularyResolver,
        provider: CatalogRecommendationProvider,
        store: CatalogRecommendationStore,
        governance: CatalogRecommendationGovernance,
    ) -> None:
        self._index = index
        self._classification_access = classification_access
        self._authorization = authorization
        self._datahub = datahub
        self._vocabulary = vocabulary
        self._provider = provider
        self._store = store
        self._governance = governance

    async def preview(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        field_path: str | None,
        source_version: str,
        vocabulary_ids: tuple[UUID, ...],
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[CatalogRecommendation, ...]:
        _validate_request_scope(
            workspace_id=workspace_id,
            subject=subject,
            field_path=field_path,
            source_version=source_version,
            vocabulary_ids=vocabulary_ids,
        )
        current = await self._current_input(
            workspace_id=workspace_id,
            asset_id=asset_id,
            field_path=field_path,
            source_version=source_version,
            vocabulary_ids=vocabulary_ids,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        if current.asset.classification > self._provider.maximum_classification:
            raise ForbiddenError(
                "The recommendation provider is not approved for the target classification."
            )
        replay = await self._store.reserve_preview(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        try:
            result = await self._provider.recommend(context=current.context)
            allowed_ids = set(vocabulary_ids)
            returned_ids = {value.vocabulary_id for value in result.recommendations}
            if not returned_ids.issubset(allowed_ids):
                raise ExternalDependencyError(
                    "The recommendation provider returned an identity outside its supplied set.",
                    dependency="catalog_recommendation_provider",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            refreshed = await self._current_input(
                workspace_id=workspace_id,
                asset_id=asset_id,
                field_path=field_path,
                source_version=source_version,
                vocabulary_ids=vocabulary_ids,
                subject=subject,
                environment=environment,
                request_id=f"{request_id}:provider-return",
            )
            if _current_input_hash(current) != _current_input_hash(refreshed):
                raise ConflictError(
                    "The recommendation input changed while the provider was running.",
                    details={"code": "RECOMMENDATION_INPUT_STALE"},
                )
            current = refreshed
            assigned = set(current.assigned_ids)
            target_binding_hash = _target_binding_hash(current.asset)
            seeds = tuple(
                CatalogRecommendationSeed(
                    recommendation_id=uuid7(),
                    workspace_id=workspace_id,
                    asset_id=asset_id,
                    field_path=field_path,
                    vocabulary_id=draft.vocabulary_id,
                    kind=CatalogRecommendationKind(current.vocabulary[draft.vocabulary_id].kind),
                    source_version=current.asset.source_version,
                    provider_source_version=current.enrichment.raw_version,
                    vocabulary_source_version=(
                        current.vocabulary[draft.vocabulary_id].source_version
                    ),
                    aspect_name=_aspect_name(
                        CatalogRecommendationKind(current.vocabulary[draft.vocabulary_id].kind)
                    ),
                    aspect_source_version=current.aspects[
                        CatalogRecommendationKind(current.vocabulary[draft.vocabulary_id].kind)
                    ].source_version,
                    aspect_content_hash=current.aspects[
                        CatalogRecommendationKind(current.vocabulary[draft.vocabulary_id].kind)
                    ].content_hash,
                    target_binding_hash=target_binding_hash,
                    input_context_hash=_recommendation_input_hash(
                        current=current,
                        vocabulary_id=draft.vocabulary_id,
                    ),
                    confidence=draft.confidence,
                    reason=draft.reason,
                    evidence=draft.evidence,
                    provider=result.provider,
                    model=result.model,
                    prompt_version=result.prompt_version,
                    rule_version=result.rule_version,
                    created_by=subject.subject_id,
                )
                for draft in result.recommendations
                if draft.vocabulary_id not in assigned
            )
            return await self._store.save_preview(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                seeds=seeds,
            )
        except BaseException:
            await self._store.abort_preview()
            raise

    async def approve(
        self,
        *,
        workspace_id: UUID,
        targets: tuple[CatalogRecommendationApprovalTarget, ...],
        title: str,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendationApprovalResult:
        if subject.workspace_id != workspace_id:
            raise ForbiddenError("The recommendation workspace does not match the current subject.")
        if (
            not targets
            or len(targets) > MAXIMUM_RECOMMENDATIONS
            or len({value.recommendation_id for value in targets}) != len(targets)
            or any(value.expected_version < 1 for value in targets)
        ):
            raise ValidationError("The recommendation approval batch is invalid.")
        recommendations = await self._store.get_many(
            workspace_id=workspace_id,
            recommendation_ids=tuple(value.recommendation_id for value in targets),
        )
        if len(recommendations) != len(targets):
            raise ConflictError("One or more recommendations are unavailable.")

        # Complete all local target and exact governed-collection authorization before any
        # DataHub read or decision row lock. A later target denial has no provider/state effect.
        authorized_by_target: dict[tuple[UUID, str | None], CatalogAssetIndex] = {}
        current_by_target: dict[tuple[UUID, str | None], _CurrentInput] = {}
        grouped_ids: dict[tuple[UUID, str | None], list[UUID]] = defaultdict(list)
        for recommendation in recommendations:
            grouped_ids[(recommendation.asset_id, recommendation.field_path)].append(
                recommendation.vocabulary_id
            )
        for asset_id, field_path in grouped_ids:
            source_versions = {
                value.source_version
                for value in recommendations
                if value.asset_id == asset_id and value.field_path == field_path
            }
            if len(source_versions) != 1:
                raise ConflictError("The recommendation batch crosses source versions.")
            authorized_by_target[(asset_id, field_path)] = await self._authorize_asset(
                workspace_id=workspace_id,
                asset_id=asset_id,
                source_version=next(iter(source_versions)),
                subject=subject,
                environment=environment,
                request_id=f"{request_id}:preauthorize:{asset_id}",
            )
        await self._authorize_change_request_collection(
            workspace_id=workspace_id,
            subject=subject,
            classification=max(value.classification for value in authorized_by_target.values()),
            environment=environment,
            request_id=f"{request_id}:preauthorize:collection",
        )
        for (asset_id, field_path), ids in grouped_ids.items():
            current_by_target[(asset_id, field_path)] = await self._current_input(
                workspace_id=workspace_id,
                asset_id=asset_id,
                field_path=field_path,
                source_version=authorized_by_target[(asset_id, field_path)].source_version,
                vocabulary_ids=tuple(ids),
                subject=subject,
                environment=environment,
                request_id=f"{request_id}:{asset_id}",
                authorized_asset=authorized_by_target[(asset_id, field_path)],
            )
        completed = await self._store.get_approval_replay(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            recommendation_ids=tuple(value.recommendation_id for value in targets),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if completed is not None and completed.completed_change_request_id is not None:
            return CatalogRecommendationApprovalResult(
                recommendations=completed.recommendations,
                change_request_id=completed.completed_change_request_id,
            )
        for recommendation in recommendations:
            current = current_by_target[(recommendation.asset_id, recommendation.field_path)]
            reference = current.vocabulary[recommendation.vocabulary_id]
            snapshot = current.aspects[recommendation.kind]
            if (
                recommendation.state is not CatalogRecommendationState.NEEDS_DECISION
                or recommendation.provider_source_version != current.enrichment.raw_version
                or recommendation.vocabulary_source_version != reference.source_version
                or recommendation.aspect_source_version != snapshot.source_version
                or recommendation.aspect_content_hash != snapshot.content_hash
                or recommendation.target_binding_hash != _target_binding_hash(current.asset)
                or recommendation.input_context_hash
                != _recommendation_input_hash(
                    current=current,
                    vocabulary_id=recommendation.vocabulary_id,
                )
                or recommendation.vocabulary_id in current.assigned_ids
            ):
                raise ConflictError(
                    "The recommendation preview is stale.",
                    details={"code": "RECOMMENDATION_STALE"},
                )

        items = self._compile_change_items(recommendations, current_by_target)
        reservation = await self._store.reserve_approval(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            recommendation_ids=tuple(value.recommendation_id for value in targets),
            expected_versions=tuple(value.expected_version for value in targets),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if reservation.completed_change_request_id is not None:
            return CatalogRecommendationApprovalResult(
                recommendations=reservation.recommendations,
                change_request_id=reservation.completed_change_request_id,
            )
        classification = max(current.asset.classification for current in current_by_target.values())
        first_asset = next(iter(current_by_target.values())).asset
        finalizer = _CatalogRecommendationTransactionFinalizer(
            store=self._store,
            workspace_id=workspace_id,
            recommendation_ids=tuple(value.recommendation_id for value in targets),
            expected_versions=tuple(value.expected_version for value in targets),
            actor_id=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
        )

        try:
            change_request = await self._governance.create_catalog_recommendation_change_request(
                workspace_id=workspace_id,
                number=change_request_number(first_asset.platform),
                request_type="CATALOG_METADATA_RECOMMENDATION",
                title=title,
                description=reason,
                requester_id=subject.subject_id,
                items=items,
                subject=subject,
                classification=classification,
                environment=environment,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                require_raw_operator_gate=False,
                recommendation_finalizer=finalizer,
            )
        except BaseException:
            await self._store.abort_decision()
            raise
        if finalizer.result is None:
            await self._store.abort_decision()
            raise ConflictError("The recommendation approval was not committed atomically.")
        return CatalogRecommendationApprovalResult(
            recommendations=finalizer.result,
            change_request_id=change_request.change_request_id,
        )

    async def reject(
        self,
        *,
        workspace_id: UUID,
        recommendation_id: UUID,
        expected_version: int,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendation:
        if subject.workspace_id != workspace_id:
            raise ForbiddenError("The recommendation workspace does not match the current subject.")
        values = await self._store.get_many(
            workspace_id=workspace_id,
            recommendation_ids=(recommendation_id,),
        )
        if len(values) != 1:
            raise ConflictError("The recommendation is unavailable.")
        recommendation = values[0]
        current = await self._current_input(
            workspace_id=workspace_id,
            asset_id=recommendation.asset_id,
            field_path=recommendation.field_path,
            source_version=recommendation.source_version,
            vocabulary_ids=(recommendation.vocabulary_id,),
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        replay = await self._store.get_rejection_replay(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            recommendation_id=recommendation_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        reference = current.vocabulary[recommendation.vocabulary_id]
        snapshot = current.aspects[recommendation.kind]
        if (
            recommendation.state is not CatalogRecommendationState.NEEDS_DECISION
            or recommendation.provider_source_version != current.enrichment.raw_version
            or recommendation.vocabulary_source_version != reference.source_version
            or recommendation.aspect_source_version != snapshot.source_version
            or recommendation.aspect_content_hash != snapshot.content_hash
            or recommendation.target_binding_hash != _target_binding_hash(current.asset)
            or recommendation.input_context_hash
            != _recommendation_input_hash(
                current=current,
                vocabulary_id=recommendation.vocabulary_id,
            )
        ):
            raise ConflictError(
                "The recommendation preview is stale.",
                details={"code": "RECOMMENDATION_STALE"},
            )
        return await self._store.reject(
            workspace_id=workspace_id,
            recommendation_id=recommendation_id,
            expected_version=expected_version,
            actor_id=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
        )

    async def _current_input(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        field_path: str | None,
        source_version: str,
        vocabulary_ids: tuple[UUID, ...],
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        authorized_asset: CatalogAssetIndex | None = None,
    ) -> _CurrentInput:
        asset = authorized_asset or await self._authorize_asset(
            workspace_id=workspace_id,
            asset_id=asset_id,
            source_version=source_version,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        if asset.asset_id != asset_id or asset.source_version != source_version:
            raise ConflictError(
                "The recommendation target source is stale.",
                details={"code": "RECOMMENDATION_SOURCE_STALE"},
            )
        enrichment = await self._datahub.get_asset(asset.external_urn)
        if (
            not enrichment.raw_version
            or enrichment.description_truncated
            or enrichment.tags_truncated
            or enrichment.glossary_terms_truncated
            or (
                field_path is not None
                and (enrichment.schema_fields_truncated or not enrichment.schema_fields_total_exact)
            )
        ):
            raise ConflictError(
                "The current recommendation metadata is incomplete.",
                details={"code": "RECOMMENDATION_INPUT_TRUNCATED"},
            )
        field_native_type = _field_native_type(enrichment, field_path)
        vocabulary = await self._vocabulary.resolve_any(
            workspace_id=workspace_id,
            vocabulary_ids=vocabulary_ids,
        )
        if any(
            value.kind
            not in {
                CatalogRecommendationKind.TAG.value,
                CatalogRecommendationKind.TERM.value,
            }
            or value.display_name is None
            for value in vocabulary.values()
        ):
            raise ConflictError(
                "The controlled recommendation vocabulary is incomplete.",
                details={"code": "CATALOG_VOCABULARY_DRIFT"},
            )
        aspects: dict[CatalogRecommendationKind, DataHubAspectSnapshot] = {}
        for kind in {CatalogRecommendationKind(value.kind) for value in vocabulary.values()}:
            aspect_name = _aspect_name(kind)
            snapshot = await self._datahub.read_aspect(
                external_urn=asset.external_urn,
                aspect_name=aspect_name,
            )
            _validate_aspect(asset, snapshot, aspect_name)
            aspects[kind] = snapshot
        assigned_ids = tuple(
            vocabulary_id
            for vocabulary_id in vocabulary_ids
            if vocabulary[vocabulary_id].provider_ref
            in controlled_metadata_refs(
                document=aspects[
                    CatalogRecommendationKind(vocabulary[vocabulary_id].kind)
                ].document,
                aspect_name=_aspect_name(CatalogRecommendationKind(vocabulary[vocabulary_id].kind)),
            )
        )
        context = CatalogRecommendationContext(
            asset_id=asset.asset_id,
            source_version=asset.source_version,
            provider_source_version=enrichment.raw_version,
            name=asset.name,
            description=enrichment.description,
            platform=asset.platform,
            database_name=asset.database_name,
            schema_name=asset.schema_name,
            field_path=field_path,
            field_native_type=field_native_type,
            vocabulary=tuple(
                CatalogRecommendationVocabulary(
                    vocabulary_id=value.vocabulary_id,
                    kind=CatalogRecommendationKind(value.kind),
                    display_name=value.display_name or "",
                    source_version=value.source_version,
                )
                for value in (vocabulary[vocabulary_id] for vocabulary_id in vocabulary_ids)
            ),
            assigned_vocabulary_ids=assigned_ids,
        )
        return _CurrentInput(
            asset=asset,
            enrichment=enrichment,
            field_native_type=field_native_type,
            vocabulary=vocabulary,
            aspects=aspects,
            assigned_ids=assigned_ids,
            context=context,
        )

    async def _authorize_asset(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        source_version: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogAssetIndex:
        access = await self._classification_access.resolve(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        detail = await self._index.get_authorized_asset(
            subject=subject,
            access=access,
            asset_id=asset_id,
        )
        if detail is None:
            raise ConflictError("The recommendation target is unavailable.")
        asset = detail.index
        if (
            asset.workspace_id != workspace_id
            or not is_dataset_asset_type(asset.asset_type)
            or asset.lifecycle != "ACTIVE"
            or not asset.external_urn.startswith("urn:li:dataset:")
            or asset.source_version != source_version
        ):
            raise ConflictError(
                "The recommendation target source is stale.",
                details={"code": "RECOMMENDATION_SOURCE_STALE"},
            )
        catalog_read_resource = ResourceAttributes(
            resource_id=asset.asset_id,
            workspace_id=workspace_id,
            resource_type="catalog_metadata_recommendation",
            owner_department_id=asset.owner_department_id,
            system_id=asset.system_id,
            domain_id=asset.domain_id,
            classification=asset.classification,
            lifecycle=asset.lifecycle,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=catalog_read_resource,
            action=Action.CATALOG_READ,
            environment=environment,
            request_id=request_id,
        )
        # Reuse the canonical governed Change Target policy rather than approximating its System
        # and classification-snapshot rules in the recommendation service.
        await self._authorization.authorize_change_target(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=asset.asset_id,
                workspace_id=workspace_id,
                resource_type="catalog_asset_change_target",
                owner_department_id=asset.owner_department_id,
                system_id=asset.system_id,
                domain_id=asset.domain_id,
                classification=asset.classification,
                lifecycle=asset.lifecycle,
            ),
            action=Action.CHANGE_CREATE,
            classification_access=access,
            environment=environment,
            request_id=request_id,
        )
        return asset

    async def _authorize_change_request_collection(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="change_request_collection",
                owner_department_id=subject.department_id,
                system_id=None,
                domain_id=None,
                classification=classification,
                lifecycle="ACTIVE",
                requester_id=subject.subject_id,
            ),
            action=Action.CHANGE_CREATE,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    def _compile_change_items(
        recommendations: Sequence[CatalogRecommendation],
        current_by_target: Mapping[tuple[UUID, str | None], _CurrentInput],
    ) -> list[ChangeItem]:
        grouped: dict[tuple[UUID, CatalogRecommendationKind], list[CatalogRecommendation]] = (
            defaultdict(list)
        )
        for recommendation in recommendations:
            grouped[(recommendation.asset_id, recommendation.kind)].append(recommendation)
        items: list[ChangeItem] = []
        for (asset_id, kind), values in grouped.items():
            current = current_by_target[(asset_id, values[0].field_path)]
            aspect_evidence = {
                (
                    current_by_target[(asset_id, value.field_path)].aspects[kind].source_version,
                    current_by_target[(asset_id, value.field_path)].aspects[kind].content_hash,
                )
                for value in values
            }
            if len(aspect_evidence) != 1:
                raise ConflictError(
                    "The recommendation batch observed inconsistent current metadata.",
                    details={"code": "RECOMMENDATION_INPUT_STALE"},
                )
            # A bulk batch can contain the same local vocabulary suggestion from multiple field
            # contexts. It compiles once into the dataset's governed Tag/Term Aspect.
            unique_ids = tuple(dict.fromkeys(value.vocabulary_id for value in values))
            vocabulary = {
                value.vocabulary_id: current_by_target[(asset_id, value.field_path)].vocabulary[
                    value.vocabulary_id
                ]
                for value in values
            }
            candidate = _compiler_candidate(current.asset, kind, unique_ids)
            compiled = compile_catalog_metadata_mutation(
                asset=current.asset,
                snapshot=current.aspects[kind],
                candidate=candidate,
                vocabulary={value: vocabulary[value] for value in unique_ids},
            )
            after_hash = canonical_json_hash(compiled.proposed_document)
            items.append(
                ChangeItem(
                    item_id=uuid7(),
                    target_type="DATAHUB_ASPECT",
                    target_ref=current.asset.external_urn,
                    operation="UPSERT",
                    after_document=dict(compiled.proposed_document),
                    aspect_name=_aspect_name(kind),
                    before_hash=current.aspects[kind].content_hash,
                    after_hash=after_hash,
                    item_contract_hash=canonical_json_hash(
                        {
                            "contract": "catalog-metadata-recommendation-item-v1",
                            "workspace_id": str(current.asset.workspace_id),
                            "asset_id": str(current.asset.asset_id),
                            "aspect_name": _aspect_name(kind),
                            "recommendation_ids": sorted(
                                str(value.recommendation_id) for value in values
                            ),
                            "before_hash": current.aspects[kind].content_hash,
                            "after_hash": after_hash,
                        }
                    ),
                )
            )
        return items


def _validate_request_scope(
    *,
    workspace_id: UUID,
    subject: SubjectAttributes,
    field_path: str | None,
    source_version: str,
    vocabulary_ids: tuple[UUID, ...],
) -> None:
    if subject.workspace_id != workspace_id:
        raise ForbiddenError("The recommendation workspace does not match the current subject.")
    if (
        not source_version.strip()
        or len(source_version) > 255
        or "\x00" in source_version
        or (
            field_path is not None
            and (not field_path.strip() or len(field_path) > 2_000 or "\x00" in field_path)
        )
        or not vocabulary_ids
        or len(vocabulary_ids) > MAXIMUM_RECOMMENDATIONS
        or len(vocabulary_ids) != len(set(vocabulary_ids))
    ):
        raise ValidationError("The recommendation preview request is invalid.")


def _field_native_type(enrichment: DataHubAssetEnrichment, field_path: str | None) -> str | None:
    if field_path is None:
        return None
    matches = tuple(
        value
        for value in enrichment.schema_fields
        if isinstance(value, dict) and value.get("fieldPath") == field_path
    )
    if len(matches) != 1:
        raise ConflictError(
            "The recommendation field is unavailable.",
            details={"code": "RECOMMENDATION_FIELD_STALE"},
        )
    raw = matches[0].get("nativeDataType")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 500 or "\x00" in raw:
        raise ConflictError(
            "The recommendation field metadata is invalid.",
            details={"code": "RECOMMENDATION_FIELD_STALE"},
        )
    return raw


def _validate_aspect(
    asset: CatalogAssetIndex,
    snapshot: DataHubAspectSnapshot,
    aspect_name: str,
) -> None:
    if (
        snapshot.urn != asset.external_urn
        or snapshot.aspect_name != aspect_name
        or not snapshot.source_version
        or canonical_json_hash(snapshot.document) != snapshot.content_hash
    ):
        raise ExternalDependencyError(
            "DataHub returned an invalid controlled metadata snapshot.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )


def _aspect_name(kind: CatalogRecommendationKind) -> str:
    return {
        CatalogRecommendationKind.TAG: CatalogMetadataAspect.GLOBAL_TAGS.value,
        CatalogRecommendationKind.TERM: CatalogMetadataAspect.GLOSSARY_TERMS.value,
    }[kind]


def _target_binding_hash(asset: CatalogAssetIndex) -> str:
    return change_target_binding_hash(
        target_ref=asset.external_urn,
        asset_id=asset.asset_id,
        asset_type=asset.asset_type,
        system_id=asset.system_id,
        domain_id=asset.domain_id,
        owner_department_id=asset.owner_department_id,
        classification=asset.classification,
        lifecycle=asset.lifecycle,
    )


def _recommendation_input_hash(*, current: _CurrentInput, vocabulary_id: UUID) -> str:
    vocabulary = current.vocabulary[vocabulary_id]
    kind = CatalogRecommendationKind(vocabulary.kind)
    return canonical_json_hash(
        {
            "contract": "catalog-metadata-recommendation-input-v1",
            "context": {
                key: value
                for key, value in current.context.provider_document().items()
                if key != "vocabulary" and key != "assigned_vocabulary_ids"
            },
            "vocabulary": {
                "vocabulary_id": str(vocabulary.vocabulary_id),
                "kind": vocabulary.kind,
                "display_name": vocabulary.display_name,
                "source_version": vocabulary.source_version,
                "assigned": vocabulary_id in current.assigned_ids,
            },
            "aspect_name": _aspect_name(kind),
            "aspect_source_version": current.aspects[kind].source_version,
            "aspect_content_hash": current.aspects[kind].content_hash,
        }
    )


def _current_input_hash(current: _CurrentInput) -> str:
    return canonical_json_hash(
        {
            "contract": "catalog-metadata-recommendation-current-input-v1",
            "provider_document": current.context.provider_document(),
            "target_binding_hash": _target_binding_hash(current.asset),
            "vocabulary_source_versions": {
                str(value): current.vocabulary[value].source_version
                for value in sorted(current.vocabulary, key=str)
            },
            "aspects": {
                kind.value: {
                    "source_version": snapshot.source_version,
                    "content_hash": snapshot.content_hash,
                }
                for kind, snapshot in sorted(
                    current.aspects.items(),
                    key=lambda value: value[0].value,
                )
            },
        }
    )


def _compiler_candidate(
    asset: CatalogAssetIndex,
    kind: CatalogRecommendationKind,
    vocabulary_ids: tuple[UUID, ...],
) -> CatalogMetadataCandidateDraft:
    record_kind = {
        CatalogRecommendationKind.TAG: CatalogMetadataRecordKind.DATASET_TAG,
        CatalogRecommendationKind.TERM: CatalogMetadataRecordKind.DATASET_TERM,
    }[kind]
    aspect = CatalogMetadataAspect(_aspect_name(kind))
    candidate_kind = {
        CatalogRecommendationKind.TAG: CatalogMetadataCandidateKind.DATASET_TAG_ADD,
        CatalogRecommendationKind.TERM: CatalogMetadataCandidateKind.DATASET_TERM_ADD,
    }[kind]
    rows = tuple(
        CatalogMetadataRowEvidence(
            workspace_id=asset.workspace_id,
            ordinal=index,
            target_asset_id=asset.asset_id,
            platform=asset.platform or "",
            database_name=asset.database_name or "",
            schema_name=asset.schema_name or "",
            table_name=asset.name,
            record_kind=record_kind,
            aspect_name=aspect,
            operation=CatalogMetadataOperation.ADD,
            field_path=None,
            value_text=None,
            controlled_ref=vocabulary_id,
            semantic_key=f"{record_kind.value}:{vocabulary_id}",
            row_hash=canonical_json_hash(
                {
                    "contract": "catalog-metadata-recommendation-row-v1",
                    "asset_id": str(asset.asset_id),
                    "kind": kind.value,
                    "vocabulary_id": str(vocabulary_id),
                }
            ),
        )
        for index, vocabulary_id in enumerate(vocabulary_ids, start=1)
    )
    identity_hash = canonical_json_hash(
        {
            "asset_id": str(asset.asset_id),
            "source_version": asset.source_version,
        }
    )
    return CatalogMetadataCandidateDraft(
        workspace_id=asset.workspace_id,
        ordinal=1,
        target_asset_id=asset.asset_id,
        platform=asset.platform or "",
        database_name=asset.database_name or "",
        schema_name=asset.schema_name or "",
        table_name=asset.name,
        record_kind=record_kind,
        candidate_kind=candidate_kind,
        aspect_name=aspect,
        rows=rows,
        submitted_identity_hash=identity_hash,
        candidate_hash=canonical_json_hash(
            {
                "contract": "catalog-metadata-recommendation-candidate-v1",
                "identity_hash": identity_hash,
                "row_hashes": [value.row_hash for value in rows],
            }
        ),
    )
