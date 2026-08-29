from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.services.catalog_recommendations import (
    CatalogRecommendationApprovalReservation,
    CatalogRecommendationSeed,
)
from datariver.domain.catalog_recommendations import (
    CatalogRecommendation,
    CatalogRecommendationDecision,
    CatalogRecommendationKind,
    CatalogRecommendationState,
)
from datariver.domain.common import ConflictError, ForbiddenError, NotFoundError, utc_now
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import (
    CatalogRecommendationEventModel,
    CatalogRecommendationModel,
)


class CatalogRecommendationNotFound(NotFoundError):
    code = "catalog_recommendation_not_found"


class SqlCatalogRecommendationStore:
    """Workspace-RLS persistence with preview replay and decision CAS."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _preview_operation(subject_id: UUID) -> str:
        return f"catalog.metadata-recommendation.preview:{subject_id}"

    async def reserve_preview(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[CatalogRecommendation, ...] | None:
        digest = hashlib.sha256(f"{workspace_id}:{subject_id}:{idempotency_key}".encode()).digest()[
            :8
        ]
        await self._session.execute(
            select(func.pg_advisory_xact_lock(int.from_bytes(digest, "big", signed=True)))
        )
        existing = await SqlIdempotencyStore(self._session).get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=self._preview_operation(subject_id),
        )
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            await self._session.rollback()
            raise ConflictError("The idempotency key was reused with a different preview.")
        try:
            recommendation_ids = tuple(UUID(str(value)) for value in existing.result["ids"])
        except (KeyError, TypeError, ValueError) as error:
            await self._session.rollback()
            raise ConflictError("The recommendation preview replay is invalid.") from error
        values = await self.get_many(
            workspace_id=workspace_id,
            recommendation_ids=recommendation_ids,
        )
        if len(values) != len(recommendation_ids):
            await self._session.rollback()
            raise ConflictError("The recommendation preview replay is unavailable.")
        await self._session.rollback()
        return values

    async def abort_preview(self) -> None:
        await self._session.rollback()

    async def save_preview(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        idempotency_key: str,
        request_hash: str,
        seeds: Sequence[CatalogRecommendationSeed],
    ) -> tuple[CatalogRecommendation, ...]:
        now = utc_now()
        values: list[CatalogRecommendationModel] = []
        for seed in sorted(seeds, key=_semantic_lock_key):
            digest = hashlib.sha256(_semantic_lock_key(seed).encode()).digest()[:8]
            await self._session.execute(
                select(func.pg_advisory_xact_lock(int.from_bytes(digest, "big", signed=True)))
            )
        for seed in seeds:
            field_path_key = seed.field_path or ""
            existing = await self._session.scalar(
                select(CatalogRecommendationModel).where(
                    CatalogRecommendationModel.workspace_id == workspace_id,
                    CatalogRecommendationModel.asset_id == seed.asset_id,
                    CatalogRecommendationModel.field_path_key == field_path_key,
                    CatalogRecommendationModel.vocabulary_id == seed.vocabulary_id,
                    CatalogRecommendationModel.kind == seed.kind.value,
                    CatalogRecommendationModel.source_version == seed.source_version,
                )
            )
            if existing is not None:
                if not _same_current_evidence(existing, seed):
                    raise ConflictError(
                        "The existing recommendation semantic key has stale evidence.",
                        details={"code": "RECOMMENDATION_INPUT_STALE"},
                    )
                values.append(existing)
                continue
            model = CatalogRecommendationModel(
                id=seed.recommendation_id,
                workspace_id=seed.workspace_id,
                asset_id=seed.asset_id,
                field_path_key=field_path_key,
                vocabulary_id=seed.vocabulary_id,
                kind=seed.kind.value,
                source_version=seed.source_version,
                provider_source_version=seed.provider_source_version,
                vocabulary_source_version=seed.vocabulary_source_version,
                aspect_name=seed.aspect_name,
                aspect_source_version=seed.aspect_source_version,
                aspect_content_hash=seed.aspect_content_hash,
                target_binding_hash=seed.target_binding_hash,
                input_context_hash=seed.input_context_hash,
                confidence=seed.confidence,
                reason=seed.reason,
                evidence=list(seed.evidence),
                provider=seed.provider,
                model=seed.model,
                prompt_version=seed.prompt_version,
                rule_version=seed.rule_version,
                state=CatalogRecommendationState.NEEDS_DECISION.value,
                version=1,
                created_by=seed.created_by,
                decision_actor_id=None,
                change_request_id=None,
                decision_key_hash=None,
                decision_request_hash=None,
                decision_kind=None,
                decision_expected_version=None,
                created_at=now,
                updated_at=now,
            )
            self._session.add(model)
            await self._session.flush((model,))
            self._session.add(
                CatalogRecommendationEventModel(
                    id=seed.recommendation_id,
                    workspace_id=workspace_id,
                    recommendation_id=seed.recommendation_id,
                    recommendation_version=1,
                    decision=CatalogRecommendationDecision.PREVIEWED.value,
                    actor_id=subject_id,
                    reason=None,
                    change_request_id=None,
                    request_hash=request_hash,
                    occurred_at=now,
                )
            )
            values.append(model)
        await SqlIdempotencyStore(self._session).save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=self._preview_operation(subject_id),
            request_hash=request_hash,
            result={"ids": [str(value.id) for value in values]},
        )
        await self._session.commit()
        return tuple(_to_domain(value) for value in values)

    async def get_many(
        self,
        *,
        workspace_id: UUID,
        recommendation_ids: Sequence[UUID],
        for_update: bool = False,
    ) -> tuple[CatalogRecommendation, ...]:
        if not recommendation_ids:
            return ()
        statement = select(CatalogRecommendationModel).where(
            CatalogRecommendationModel.workspace_id == workspace_id,
            CatalogRecommendationModel.id.in_(tuple(recommendation_ids)),
        )
        if for_update:
            statement = statement.order_by(CatalogRecommendationModel.id).with_for_update()
        models = tuple((await self._session.scalars(statement)).all())
        by_id = {value.id: value for value in models}
        return tuple(_to_domain(by_id[value]) for value in recommendation_ids if value in by_id)

    async def get_approval_replay(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        recommendation_ids: tuple[UUID, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendationApprovalReservation | None:
        models = tuple(
            (
                await self._session.scalars(
                    select(CatalogRecommendationModel).where(
                        CatalogRecommendationModel.workspace_id == workspace_id,
                        CatalogRecommendationModel.id.in_(recommendation_ids),
                    )
                )
            ).all()
        )
        by_id = {value.id: value for value in models}
        if len(models) != len(recommendation_ids) or set(by_id) != set(recommendation_ids):
            return None
        ordered = tuple(by_id[value] for value in recommendation_ids)
        matching_key = all(
            value.decision_kind == "APPROVE"
            and value.decision_actor_id is not None
            and value.decision_key_hash
            == _decision_key_hash(value.decision_actor_id, idempotency_key)
            for value in ordered
        )
        if not matching_key:
            return None
        if any(value.decision_actor_id != subject_id for value in ordered):
            raise ForbiddenError("The approval replay belongs to another subject.")
        if any(value.decision_request_hash != request_hash for value in ordered):
            raise ConflictError("The approval idempotency key was reused with another request.")
        change_ids = {value.change_request_id for value in ordered}
        if (
            all(value.state == CatalogRecommendationState.APPROVED.value for value in ordered)
            and len(change_ids) == 1
            and None not in change_ids
        ):
            return CatalogRecommendationApprovalReservation(
                recommendations=tuple(_to_domain(value) for value in ordered),
                completed_change_request_id=next(iter(change_ids)),
            )
        return None

    async def get_rejection_replay(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        recommendation_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendation | None:
        model = await self._session.scalar(
            select(CatalogRecommendationModel).where(
                CatalogRecommendationModel.workspace_id == workspace_id,
                CatalogRecommendationModel.id == recommendation_id,
            )
        )
        if model is None:
            return None
        matching_key = (
            model.decision_actor_id is not None
            and model.decision_key_hash
            == _decision_key_hash(model.decision_actor_id, idempotency_key)
        )
        if model.decision_kind != "REJECT" or not matching_key:
            return None
        if model.decision_actor_id != subject_id:
            raise ForbiddenError("The rejection replay belongs to another subject.")
        if model.decision_request_hash != request_hash:
            raise ConflictError("The rejection idempotency key was reused with another request.")
        if model.state != CatalogRecommendationState.REJECTED.value:
            return None
        return _to_domain(model)

    async def reserve_approval(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        recommendation_ids: tuple[UUID, ...],
        expected_versions: tuple[int, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogRecommendationApprovalReservation:
        models = await self._locked_models(workspace_id, recommendation_ids)
        if all(
            value.decision_kind == "APPROVE"
            and value.decision_actor_id is not None
            and value.decision_key_hash
            == _decision_key_hash(value.decision_actor_id, idempotency_key)
            for value in models
        ):
            if any(value.decision_actor_id != subject_id for value in models):
                await self._session.rollback()
                raise ForbiddenError("The approval replay belongs to another subject.")
            if any(value.decision_request_hash != request_hash for value in models):
                await self._session.rollback()
                raise ConflictError("The approval idempotency key was reused with another request.")
            change_ids = {value.change_request_id for value in models}
            completed = (
                next(iter(change_ids)) if len(change_ids) == 1 and None not in change_ids else None
            )
            recommendations = tuple(_to_domain(value) for value in models)
            await self._session.rollback()
            return CatalogRecommendationApprovalReservation(
                recommendations=recommendations,
                completed_change_request_id=completed,
            )
        for value, expected_version in zip(models, expected_versions, strict=True):
            if (
                value.state != CatalogRecommendationState.NEEDS_DECISION.value
                or value.version != expected_version
                or value.decision_actor_id is not None
                or value.decision_kind is not None
            ):
                await self._session.rollback()
                raise ConflictError(
                    "The recommendation decision version is stale.",
                    details={"code": "RECOMMENDATION_CAS_MISMATCH"},
                )
        # The FOR UPDATE locks remain owned by the shared Governance transaction. No Product
        # mutation is persisted until the Change Request and decision event commit atomically.
        return CatalogRecommendationApprovalReservation(
            recommendations=tuple(_to_domain(value) for value in models),
            completed_change_request_id=None,
        )

    async def abort_decision(self) -> None:
        await self._session.rollback()

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
    ) -> tuple[CatalogRecommendation, ...]:
        models = await self._locked_models(workspace_id, recommendation_ids)
        key_hash = _decision_key_hash(actor_id, idempotency_key)
        now = utc_now()
        events: list[CatalogRecommendationEventModel] = []
        for value, expected_version in zip(models, expected_versions, strict=True):
            if (
                value.state != CatalogRecommendationState.NEEDS_DECISION.value
                or value.version != expected_version
                or value.decision_actor_id is not None
                or value.decision_kind is not None
            ):
                raise ConflictError(
                    "The recommendation decision version is stale.",
                    details={"code": "RECOMMENDATION_CAS_MISMATCH"},
                )
            value.state = CatalogRecommendationState.APPROVED.value
            value.decision_actor_id = actor_id
            value.decision_key_hash = key_hash
            value.decision_request_hash = request_hash
            value.decision_kind = "APPROVE"
            value.decision_expected_version = expected_version
            value.change_request_id = change_request_id
            value.version += 1
            value.updated_at = now
            events.append(
                CatalogRecommendationEventModel(
                    id=_event_id(value.id, value.version),
                    workspace_id=workspace_id,
                    recommendation_id=value.id,
                    recommendation_version=value.version,
                    decision=CatalogRecommendationDecision.APPROVED.value,
                    actor_id=actor_id,
                    reason=reason,
                    change_request_id=change_request_id,
                    request_hash=request_hash,
                    occurred_at=now,
                )
            )
        # The insert validator reads the aggregate row, so persist all guarded state transitions
        # before appending their matching events. Both flushes remain in the shared transaction.
        await self._session.flush()
        self._session.add_all(events)
        await self._session.flush()
        return tuple(_to_domain(value) for value in models)

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
    ) -> CatalogRecommendation:
        model = (await self._locked_models(workspace_id, (recommendation_id,)))[0]
        existing_key_matches = (
            model.decision_actor_id is not None
            and model.decision_key_hash
            == _decision_key_hash(model.decision_actor_id, idempotency_key)
        )
        if (
            model.state == CatalogRecommendationState.REJECTED.value
            and model.decision_kind == "REJECT"
            and existing_key_matches
            and model.decision_request_hash == request_hash
        ):
            if model.decision_actor_id != actor_id:
                await self._session.rollback()
                raise ForbiddenError("The rejection replay belongs to another subject.")
            await self._session.rollback()
            return _to_domain(model)
        if (
            model.state != CatalogRecommendationState.NEEDS_DECISION.value
            or model.version != expected_version
            or model.decision_kind is not None
        ):
            await self._session.rollback()
            raise ConflictError(
                "The recommendation decision version is stale.",
                details={"code": "RECOMMENDATION_CAS_MISMATCH"},
            )
        now = utc_now()
        key_hash = _decision_key_hash(actor_id, idempotency_key)
        model.state = CatalogRecommendationState.REJECTED.value
        model.decision_actor_id = actor_id
        model.decision_key_hash = key_hash
        model.decision_request_hash = request_hash
        model.decision_kind = "REJECT"
        model.decision_expected_version = expected_version
        model.version += 1
        model.updated_at = now
        # The event insert guard validates the already-transitioned aggregate row.
        await self._session.flush()
        self._session.add(
            CatalogRecommendationEventModel(
                id=_event_id(model.id, model.version),
                workspace_id=workspace_id,
                recommendation_id=model.id,
                recommendation_version=model.version,
                decision=CatalogRecommendationDecision.REJECTED.value,
                actor_id=actor_id,
                reason=reason,
                change_request_id=None,
                request_hash=request_hash,
                occurred_at=now,
            )
        )
        await self._session.commit()
        return _to_domain(model)

    async def _locked_models(
        self,
        workspace_id: UUID,
        recommendation_ids: tuple[UUID, ...],
    ) -> tuple[CatalogRecommendationModel, ...]:
        models = tuple(
            (
                await self._session.scalars(
                    select(CatalogRecommendationModel)
                    .where(
                        CatalogRecommendationModel.workspace_id == workspace_id,
                        CatalogRecommendationModel.id.in_(recommendation_ids),
                    )
                    .order_by(CatalogRecommendationModel.id)
                    .with_for_update()
                )
            ).all()
        )
        by_id = {value.id: value for value in models}
        if len(models) != len(recommendation_ids) or set(by_id) != set(recommendation_ids):
            await self._session.rollback()
            raise CatalogRecommendationNotFound("The catalog recommendation does not exist.")
        return tuple(by_id[value] for value in recommendation_ids)


def _to_domain(model: CatalogRecommendationModel) -> CatalogRecommendation:
    return CatalogRecommendation(
        recommendation_id=model.id,
        workspace_id=model.workspace_id,
        asset_id=model.asset_id,
        field_path=model.field_path_key or None,
        vocabulary_id=model.vocabulary_id,
        kind=CatalogRecommendationKind(model.kind),
        source_version=model.source_version,
        provider_source_version=model.provider_source_version,
        vocabulary_source_version=model.vocabulary_source_version,
        aspect_name=model.aspect_name,
        aspect_source_version=model.aspect_source_version,
        aspect_content_hash=model.aspect_content_hash,
        target_binding_hash=model.target_binding_hash,
        input_context_hash=model.input_context_hash,
        confidence=float(model.confidence),
        reason=model.reason,
        evidence=tuple(model.evidence),
        provider=model.provider,
        model=model.model,
        prompt_version=model.prompt_version,
        rule_version=model.rule_version,
        state=CatalogRecommendationState(model.state),
        version=model.version,
        created_by=model.created_by,
        decision_actor_id=model.decision_actor_id,
        change_request_id=model.change_request_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _event_id(recommendation_id: UUID, version: int) -> UUID:
    raw = bytearray(hashlib.sha256(f"{recommendation_id}:{version}".encode()).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _decision_key_hash(subject_id: UUID, idempotency_key: str) -> str:
    return hashlib.sha256(f"{subject_id}:{idempotency_key}".encode()).hexdigest()


def _semantic_lock_key(seed: CatalogRecommendationSeed) -> str:
    return ":".join(
        (
            str(seed.workspace_id),
            str(seed.asset_id),
            seed.field_path or "",
            str(seed.vocabulary_id),
            seed.kind.value,
            seed.source_version,
        )
    )


def _same_current_evidence(
    existing: CatalogRecommendationModel,
    seed: CatalogRecommendationSeed,
) -> bool:
    return (
        existing.provider_source_version == seed.provider_source_version
        and existing.vocabulary_source_version == seed.vocabulary_source_version
        and existing.aspect_name == seed.aspect_name
        and existing.aspect_source_version == seed.aspect_source_version
        and existing.aspect_content_hash == seed.aspect_content_hash
        and existing.target_binding_hash == seed.target_binding_hash
        and existing.input_context_hash == seed.input_context_hash
    )
