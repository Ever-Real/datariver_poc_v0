from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    ApiProductRecord,
    ApiProductVersionRecord,
    ConsumerGrantRecord,
    InvocationAuthorizationRecord,
    InvocationResultRecord,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import SharingStore
from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.retention import RetentionDataClass
from datariver.domain.sharing import (
    ApiProduct,
    ApiProductState,
    ApiProductVersionState,
    ConsumerGrant,
    ConsumerGrantState,
)
from datariver.domain.sharing_invocation import (
    CanonicalInvocationResult,
    CompletedInvocation,
    InvocationRequestBinding,
    canonical_invocation_request_hash,
    execute_or_replay_invocation,
    validate_canonical_result,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.knowledge import (
    governed_release_ids,
    require_governed_release_base,
)
from datariver.infrastructure.db.models.knowledge import ReleaseModel
from datariver.infrastructure.db.models.platform import (
    SubjectModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.models.sharing import (
    ApiProductModel,
    ApiProductVersionModel,
    ConsumerGrantModel,
)


@dataclass(frozen=True, slots=True)
class _InvocationRetentionBinding:
    data_class: RetentionDataClass
    policy_id: UUID
    policy_hash: str


@dataclass(frozen=True, slots=True)
class _PreparedInvocation:
    status: str
    invocation_id: UUID | None
    result_hash: str | None
    result_size_bytes: int | None
    retention_policy_id: UUID | None
    retention_policy_hash: str | None
    retention_data_class: str | None
    retention_until: datetime | None
    result_document: str | None
    minute_units: int
    month_units: int


async def _unreachable_executor() -> dict[str, Any]:  # pragma: no cover - replay never calls it
    raise AssertionError("A completed or legacy invocation must never execute again.")


def _version_record(model: ApiProductVersionModel) -> ApiProductVersionRecord:
    return ApiProductVersionRecord(
        version_id=model.id,
        product_id=model.product_id,
        graph_id=model.graph_id,
        release_id=model.release_id,
        version_no=model.version_no,
        surface=model.surface,
        contract_document=model.contract_document,
        maximum_hops=model.maximum_hops,
        maximum_nodes=model.maximum_nodes,
        timeout_ms=model.timeout_ms,
        state=model.state,
        published_at=model.published_at,
    )


def _product_record(
    model: ApiProductModel, versions: tuple[ApiProductVersionRecord, ...] = ()
) -> ApiProductRecord:
    visible_version_ids = {version.version_id for version in versions}
    return ApiProductRecord(
        product_id=model.id,
        workspace_id=model.workspace_id,
        slug=model.slug,
        name=model.name,
        description=model.description,
        graph_id=model.graph_id,
        classification=Classification(model.classification),
        owner_id=model.owner_id,
        state=model.state,
        current_version_id=(
            model.current_version_id if model.current_version_id in visible_version_ids else None
        ),
        version=model.version,
        versions=versions,
    )


def _grant_record(model: ConsumerGrantModel) -> ConsumerGrantRecord:
    return ConsumerGrantRecord(
        grant_id=model.id,
        product_id=model.product_id,
        product_version_id=model.product_version_id,
        contract_version=model.contract_version,
        consumer_subject_id=model.consumer_subject_id,
        consumer_issuer=model.consumer_issuer,
        consumer_client_id=model.consumer_client_id,
        scopes=tuple(model.scopes),
        maximum_classification=Classification(model.maximum_classification),
        requests_per_minute=model.requests_per_minute,
        monthly_quota=model.monthly_quota,
        valid_from=model.valid_from,
        expires_at=model.expires_at,
        state=model.state,
        version=model.version,
    )


class SqlSharingStore(SharingStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_product(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        name: str,
        description: str,
        graph_id: UUID,
        release_id: UUID,
        classification: int,
        owner_id: UUID,
        surface: str,
        contract_document: dict[str, Any],
        maximum_hops: int,
        maximum_nodes: int,
        timeout_ms: int,
        idempotency_key: str,
        request_hash: str,
    ) -> ApiProductRecord:
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.product.create",
        )
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.product.create",
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            existing_product = await self.get_product(
                workspace_id=workspace_id,
                product_id=UUID(str(existing.result["product_id"])),
                clearance=int(Classification.RESTRICTED),
            )
            if existing_product is None:
                raise ConflictError("The idempotent API product result is unavailable.")
            if existing_product.owner_id != owner_id:
                raise ConflictError("The idempotent API product result is bound to another owner.")
            return existing_product

        release = await self._require_release(workspace_id, graph_id, release_id)
        self._validate_release_bound(
            release=release,
            surface=surface,
            maximum_nodes=maximum_nodes,
        )
        product_id = uuid7()
        version_id = uuid7()
        product = ApiProductModel(
            id=product_id,
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            description=description,
            graph_id=graph_id,
            classification=classification,
            owner_id=owner_id,
            state=ApiProductState.DRAFT.value,
            current_version_id=None,
            version=1,
        )
        product_version = ApiProductVersionModel(
            id=version_id,
            workspace_id=workspace_id,
            product_id=product_id,
            graph_id=graph_id,
            release_id=release_id,
            version_no=1,
            surface=surface,
            contract_document=contract_document,
            maximum_hops=maximum_hops,
            maximum_nodes=maximum_nodes,
            timeout_ms=timeout_ms,
            state=ApiProductVersionState.DRAFT.value,
            created_by=owner_id,
        )
        self._session.add_all((product, product_version))
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.product.create",
            request_hash=request_hash,
            result={"product_id": str(product_id)},
        )
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="sharing.product.created.v1",
                    aggregate_type="api_product",
                    aggregate_id=product_id,
                    workspace_id=workspace_id,
                    payload={"version_id": str(version_id), "release_id": str(release_id)},
                )
            ]
        )
        await self._commit_or_conflict("An API product with this slug already exists.")
        return _product_record(product, (_version_record(product_version),))

    async def list_products(
        self, *, workspace_id: UUID, clearance: int
    ) -> tuple[ApiProductRecord, ...]:
        products = tuple(
            (
                await self._session.scalars(
                    select(ApiProductModel)
                    .where(
                        ApiProductModel.workspace_id == workspace_id,
                        ApiProductModel.classification <= clearance,
                    )
                    .order_by(ApiProductModel.slug)
                )
            ).all()
        )
        versions = await self._versions_for_products(
            workspace_id, {product.id for product in products}
        )
        return tuple(
            _product_record(product, versions[product.id])
            for product in products
            if versions[product.id]
        )

    async def get_product(
        self, *, workspace_id: UUID, product_id: UUID, clearance: int
    ) -> ApiProductRecord | None:
        product = await self._session.scalar(
            select(ApiProductModel).where(
                ApiProductModel.workspace_id == workspace_id,
                ApiProductModel.id == product_id,
                ApiProductModel.classification <= clearance,
            )
        )
        if product is None:
            return None
        versions = await self._versions_for_products(workspace_id, {product.id})
        if not versions[product.id]:
            return None
        return _product_record(product, versions[product.id])

    async def create_version(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        release_id: UUID,
        actor_id: UUID,
        surface: str,
        contract_document: dict[str, Any],
        maximum_hops: int,
        maximum_nodes: int,
        timeout_ms: int,
        idempotency_key: str,
        request_hash: str,
    ) -> ApiProductVersionRecord:
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.product.version.create",
        )
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.product.version.create",
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            version = await self._session.get(
                ApiProductVersionModel, UUID(str(existing.result["version_id"]))
            )
            if (
                version is None
                or version.workspace_id != workspace_id
                or version.product_id != product_id
            ):
                raise ConflictError("The idempotent product version result is unavailable.")
            product = await self._locked_product(workspace_id, product_id)
            if product.owner_id != actor_id or version.graph_id != product.graph_id:
                raise ConflictError(
                    "The idempotent product version result is bound to another owner or product."
                )
            await self._require_release(
                workspace_id,
                version.graph_id,
                version.release_id,
            )
            return _version_record(version)

        product = await self._locked_product(workspace_id, product_id)
        if product.owner_id != actor_id:
            raise ForbiddenError("Only the API product owner can create a version.")
        if product.state == ApiProductState.RETIRED.value:
            raise ConflictError("A retired API product cannot receive a new version.")
        release = await self._require_release(workspace_id, product.graph_id, release_id)
        self._validate_release_bound(
            release=release,
            surface=surface,
            maximum_nodes=maximum_nodes,
        )
        draft = await self._session.scalar(
            select(ApiProductVersionModel.id).where(
                ApiProductVersionModel.workspace_id == workspace_id,
                ApiProductVersionModel.product_id == product_id,
                ApiProductVersionModel.state == ApiProductVersionState.DRAFT.value,
            )
        )
        if draft is not None:
            raise ConflictError("Publish or remove the existing draft version first.")
        latest = await self._session.scalar(
            select(func.max(ApiProductVersionModel.version_no)).where(
                ApiProductVersionModel.workspace_id == workspace_id,
                ApiProductVersionModel.product_id == product_id,
            )
        )
        version_id = uuid7()
        version = ApiProductVersionModel(
            id=version_id,
            workspace_id=workspace_id,
            product_id=product_id,
            graph_id=product.graph_id,
            release_id=release_id,
            version_no=int(latest or 0) + 1,
            surface=surface,
            contract_document=contract_document,
            maximum_hops=maximum_hops,
            maximum_nodes=maximum_nodes,
            timeout_ms=timeout_ms,
            state=ApiProductVersionState.DRAFT.value,
            created_by=actor_id,
        )
        self._session.add(version)
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.product.version.create",
            request_hash=request_hash,
            result={"version_id": str(version_id)},
        )
        await self._commit_or_conflict("The API product version could not be created.")
        return _version_record(version)

    async def publish_version(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> ApiProductRecord:
        product = await self._locked_product(workspace_id, product_id)
        domain = ApiProduct(
            product_id=product.id,
            workspace_id=product.workspace_id,
            owner_id=product.owner_id,
            classification=Classification(product.classification),
            state=ApiProductState(product.state),
            version=product.version,
        )
        domain.publish(actor_id=actor_id, expected_version=expected_version)
        version = await self._session.scalar(
            select(ApiProductVersionModel)
            .where(
                ApiProductVersionModel.workspace_id == workspace_id,
                ApiProductVersionModel.product_id == product_id,
                ApiProductVersionModel.id == version_id,
            )
            .with_for_update()
        )
        if version is None:
            raise NotFoundError("The API product version does not exist.")
        if version.state != ApiProductVersionState.DRAFT.value:
            raise ConflictError("Only a draft API product version can be published.")
        await self._require_release(
            workspace_id,
            version.graph_id,
            version.release_id,
        )
        if product.current_version_id is not None:
            previous = await self._session.get(ApiProductVersionModel, product.current_version_id)
            if previous is not None:
                previous.state = ApiProductVersionState.DEPRECATED.value
        now = utc_now()
        version.state = ApiProductVersionState.PUBLISHED.value
        version.published_by = actor_id
        version.published_at = now
        product.state = domain.state.value
        product.version = domain.version
        product.current_version_id = version.id
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="sharing.product.published.v1",
                    aggregate_type="api_product",
                    aggregate_id=product_id,
                    workspace_id=workspace_id,
                    payload={"version_id": str(version.id), "release_id": str(version.release_id)},
                )
            ]
        )
        await self._session.flush()
        versions = await self._versions_for_products(workspace_id, {product.id})
        result = _product_record(product, versions[product.id])
        await self._session.commit()
        return result

    async def create_grant(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        consumer_subject_id: UUID,
        consumer_client_id: str,
        scopes: frozenset[str],
        maximum_classification: int,
        requests_per_minute: int,
        monthly_quota: int,
        valid_from: datetime,
        expires_at: datetime,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> ConsumerGrantRecord:
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.grant.create",
        )
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.grant.create",
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            grant = await self._session.get(
                ConsumerGrantModel, UUID(str(existing.result["grant_id"]))
            )
            if (
                grant is None
                or grant.workspace_id != workspace_id
                or grant.product_id != product_id
                or grant.consumer_subject_id != consumer_subject_id
            ):
                raise ConflictError("The idempotent consumer grant result is unavailable.")
            product = await self._locked_product(workspace_id, product_id)
            if product.owner_id != actor_id:
                raise ConflictError(
                    "The idempotent consumer grant result is bound to another owner."
                )
            consumer_issuer = await self._require_service_consumer(
                workspace_id=workspace_id,
                subject_id=consumer_subject_id,
            )
            if (
                grant.contract_version != "SUBJECT_CLIENT_V2"
                or grant.consumer_issuer != consumer_issuer
            ):
                raise ConflictError(
                    "The idempotent consumer grant result has a different identity binding."
                )
            version = await self._session.get(ApiProductVersionModel, grant.product_version_id)
            if (
                version is None
                or version.workspace_id != workspace_id
                or version.product_id != product_id
                or version.graph_id != product.graph_id
            ):
                raise ConflictError("The idempotent consumer grant version is unavailable.")
            await self._require_release(
                workspace_id,
                version.graph_id,
                version.release_id,
            )
            return _grant_record(grant)

        product = await self._locked_product(workspace_id, product_id)
        if product.owner_id != actor_id:
            raise ForbiddenError("Only the API product owner can grant consumers.")
        if product.state != ApiProductState.PUBLISHED.value or product.current_version_id is None:
            raise ConflictError("The API product must be published before granting access.")
        version = await self._session.get(ApiProductVersionModel, product.current_version_id)
        if version is None or version.state != ApiProductVersionState.PUBLISHED.value:
            raise ConflictError("The current API product version is unavailable.")
        await self._require_release(
            workspace_id,
            version.graph_id,
            version.release_id,
        )
        consumer_issuer = await self._require_service_consumer(
            workspace_id=workspace_id,
            subject_id=consumer_subject_id,
        )
        allowed_scopes = version.contract_document.get("scopes", [])
        if not isinstance(allowed_scopes, list) or not scopes.issubset(
            {str(value) for value in allowed_scopes}
        ):
            raise ValidationError("The grant contains a scope outside the product contract.")
        if maximum_classification < product.classification:
            raise ValidationError("The grant classification ceiling is below the product.")
        if expires_at <= valid_from:
            raise ValidationError("The grant expiration must be after its start time.")
        legacy_grant = await self._session.scalar(
            select(ConsumerGrantModel)
            .where(
                ConsumerGrantModel.workspace_id == workspace_id,
                ConsumerGrantModel.product_version_id == version.id,
                ConsumerGrantModel.consumer_client_id == consumer_client_id,
                ConsumerGrantModel.contract_version == "LEGACY_CLIENT_V1",
                ConsumerGrantModel.state == ConsumerGrantState.ACTIVE.value,
            )
            .with_for_update()
        )
        if legacy_grant is not None:
            legacy_grant.contract_version = "SUBJECT_CLIENT_V2"
            legacy_grant.consumer_subject_id = consumer_subject_id
            legacy_grant.consumer_issuer = consumer_issuer
            legacy_grant.scopes = sorted(scopes)
            legacy_grant.maximum_classification = maximum_classification
            legacy_grant.requests_per_minute = requests_per_minute
            legacy_grant.monthly_quota = monthly_quota
            legacy_grant.valid_from = valid_from
            legacy_grant.expires_at = expires_at
            legacy_grant.version += 1
            await idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation="sharing.grant.create",
                request_hash=request_hash,
                result={"grant_id": str(legacy_grant.id)},
            )
            await SqlOutboxWriter(self._session).add_events(
                [
                    DomainEvent.create(
                        event_type="sharing.grant.identity-bound.v2",
                        aggregate_type="consumer_grant",
                        aggregate_id=legacy_grant.id,
                        workspace_id=workspace_id,
                        payload={
                            "product_id": str(product_id),
                            "product_version_id": str(version.id),
                            "consumer_subject_id": str(consumer_subject_id),
                            "consumer_client_id": consumer_client_id,
                            "preserved_legacy_usage": True,
                        },
                    )
                ]
            )
            await self._commit_or_conflict(
                "The legacy client grant could not be bound to this service Subject."
            )
            return _grant_record(legacy_grant)
        grant_id = uuid7()
        grant = ConsumerGrantModel(
            id=grant_id,
            workspace_id=workspace_id,
            product_id=product_id,
            product_version_id=version.id,
            contract_version="SUBJECT_CLIENT_V2",
            consumer_subject_id=consumer_subject_id,
            consumer_issuer=consumer_issuer,
            consumer_client_id=consumer_client_id,
            scopes=sorted(scopes),
            maximum_classification=maximum_classification,
            requests_per_minute=requests_per_minute,
            monthly_quota=monthly_quota,
            valid_from=valid_from,
            expires_at=expires_at,
            state=ConsumerGrantState.ACTIVE.value,
            created_by=actor_id,
            version=1,
        )
        self._session.add(grant)
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="sharing.grant.create",
            request_hash=request_hash,
            result={"grant_id": str(grant_id)},
        )
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="sharing.grant.created.v1",
                    aggregate_type="consumer_grant",
                    aggregate_id=grant_id,
                    workspace_id=workspace_id,
                    payload={
                        "product_id": str(product_id),
                        "product_version_id": str(version.id),
                        "consumer_subject_id": str(consumer_subject_id),
                        "consumer_client_id": consumer_client_id,
                    },
                )
            ]
        )
        await self._commit_or_conflict("This client already has a grant for the product version.")
        return _grant_record(grant)

    async def list_grants(
        self, *, workspace_id: UUID, product_id: UUID
    ) -> tuple[ConsumerGrantRecord, ...]:
        values = await self._session.scalars(
            select(ConsumerGrantModel)
            .join(
                ApiProductVersionModel,
                (ApiProductVersionModel.workspace_id == ConsumerGrantModel.workspace_id)
                & (ApiProductVersionModel.id == ConsumerGrantModel.product_version_id)
                & (ApiProductVersionModel.product_id == ConsumerGrantModel.product_id),
            )
            .where(
                ConsumerGrantModel.workspace_id == workspace_id,
                ConsumerGrantModel.product_id == product_id,
                ApiProductVersionModel.release_id.in_(
                    governed_release_ids(
                        workspace_id=workspace_id,
                        graph_id=ApiProductVersionModel.graph_id,
                    ).correlate(ApiProductVersionModel)
                ),
            )
            .order_by(ConsumerGrantModel.created_at.desc())
        )
        return tuple(_grant_record(value) for value in values)

    async def revoke_grant(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        grant_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> ConsumerGrantRecord:
        product = await self._locked_product(workspace_id, product_id)
        if product.owner_id != actor_id:
            raise ForbiddenError("Only the API product owner can revoke a grant.")
        grant = await self._session.scalar(
            select(ConsumerGrantModel)
            .where(
                ConsumerGrantModel.workspace_id == workspace_id,
                ConsumerGrantModel.product_id == product_id,
                ConsumerGrantModel.id == grant_id,
            )
            .with_for_update()
        )
        if grant is None:
            raise NotFoundError("The API consumer grant does not exist.")
        if grant.version != expected_version:
            raise ConflictError("The API consumer grant was modified by another request.")
        if grant.state != ConsumerGrantState.ACTIVE.value:
            raise ConflictError("The API consumer grant is already revoked.")
        grant.state = ConsumerGrantState.REVOKED.value
        grant.revoked_by = actor_id
        grant.revoked_at = utc_now()
        grant.version += 1
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="sharing.grant.revoked.v1",
                    aggregate_type="consumer_grant",
                    aggregate_id=grant.id,
                    workspace_id=workspace_id,
                    payload={"product_id": str(product_id)},
                )
            ]
        )
        await self._session.commit()
        return _grant_record(grant)

    async def execute_invocation(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        actor_id: UUID,
        consumer_issuer: str,
        consumer_client_id: str,
        security_scopes: frozenset[str],
        effective_classification: int,
        requested_scope: str,
        operation: str,
        result_type: str,
        payload_document: dict[str, Any],
        invocation_key: str,
        request_id: str,
        result_builder: Callable[[InvocationAuthorizationRecord], Awaitable[dict[str, Any]]],
    ) -> InvocationResultRecord:
        try:
            product = await self._invocation_product(workspace_id, product_id)
            if product.current_version_id is None:
                raise ForbiddenError(
                    "No active current-version grant exists for this API consumer."
                )
            version = await self._session.scalar(
                select(ApiProductVersionModel)
                .where(
                    ApiProductVersionModel.workspace_id == workspace_id,
                    ApiProductVersionModel.product_id == product_id,
                    ApiProductVersionModel.id == product.current_version_id,
                    ApiProductVersionModel.state == ApiProductVersionState.PUBLISHED.value,
                )
                .with_for_update(read=True)
            )
            if version is None:
                raise ForbiddenError(
                    "No active current-version grant exists for this API consumer."
                )
            grant = await self._session.scalar(
                select(ConsumerGrantModel)
                .where(
                    ConsumerGrantModel.workspace_id == workspace_id,
                    ConsumerGrantModel.product_id == product_id,
                    ConsumerGrantModel.product_version_id == version.id,
                    ConsumerGrantModel.contract_version == "SUBJECT_CLIENT_V2",
                    ConsumerGrantModel.consumer_subject_id == actor_id,
                    ConsumerGrantModel.consumer_issuer == consumer_issuer,
                    ConsumerGrantModel.consumer_client_id == consumer_client_id,
                )
                .with_for_update()
            )
            if grant is None:
                raise ForbiddenError(
                    "No active current-version grant exists for this API consumer."
                )
            await self._require_current_service_consumer(
                workspace_id=workspace_id,
                subject_id=actor_id,
                issuer=consumer_issuer,
            )
            now = await self._database_time()
            domain_grant = ConsumerGrant(
                grant_id=grant.id,
                workspace_id=grant.workspace_id,
                product_id=grant.product_id,
                product_version_id=grant.product_version_id,
                consumer_client_id=grant.consumer_client_id,
                scopes=frozenset(grant.scopes),
                maximum_classification=Classification(grant.maximum_classification),
                valid_from=grant.valid_from,
                expires_at=grant.expires_at,
                requests_per_minute=grant.requests_per_minute,
                monthly_quota=grant.monthly_quota,
                state=ConsumerGrantState(grant.state),
            )
            domain_grant.authorize(
                now=now,
                consumer_client_id=consumer_client_id,
                requested_scope=requested_scope,
                product_classification=Classification(product.classification),
            )
            release = await self._require_release(
                workspace_id,
                version.graph_id,
                version.release_id,
            )
            self._validate_invocation_contract(
                version=version,
                requested_scope=requested_scope,
                operation=operation,
                result_type=result_type,
            )
            classification = min(effective_classification, grant.maximum_classification)
            security_scope_hash = canonical_json_hash(sorted(security_scopes))
            contract_hash = canonical_json_hash(
                {
                    "contract": version.contract_document,
                    "maximum_hops": version.maximum_hops,
                    "maximum_nodes": version.maximum_nodes,
                    "timeout_ms": version.timeout_ms,
                }
            )
            binding = InvocationRequestBinding(
                workspace_id=workspace_id,
                subject_id=actor_id,
                consumer_issuer=consumer_issuer,
                consumer_client_id=consumer_client_id,
                security_scopes=security_scopes,
                grant_id=grant.id,
                product_id=product.id,
                product_version_id=version.id,
                graph_id=version.graph_id,
                release_id=version.release_id,
                release_content_hash=release.content_hash,
                contract_hash=contract_hash,
                effective_classification=classification,
                surface=version.surface,
                operation=operation,
                result_type=result_type,
                requested_scope=requested_scope,
                payload_document=payload_document,
                request_id=request_id,
                invocation_key=invocation_key,
            )
            request_hash = canonical_invocation_request_hash(binding)
            key_hash = hashlib.sha256(invocation_key.encode("utf-8")).hexdigest()
            prepared = await self._prepare_invocation(
                binding=binding,
                request_hash=request_hash,
                security_scope_hash=security_scope_hash,
                key_hash=key_hash,
            )
            if prepared.status == "REPLAY":
                return await self._replay_prepared_invocation(
                    prepared=prepared,
                    binding=binding,
                    request_hash=request_hash,
                    grant=grant,
                    product=product,
                    version=version,
                )
            if prepared.status == "LEGACY":
                raise ConflictError(
                    "The legacy invocation has no replayable result; use a new idempotency key."
                )
            if prepared.status in {"CONFLICT", "CORRUPT"}:
                raise ConflictError(
                    "The invocation key was used with a different or invalid result binding."
                )
            if prepared.status == "EXPIRED":
                raise ConflictError("The stored invocation result is no longer replayable.")
            if prepared.status == "DENIED":
                raise ForbiddenError(
                    "The current consumer, release or retention state denies this invocation."
                )
            if prepared.status != "NEW":
                raise ConflictError("The invocation preparation returned an invalid state.")
            if prepared.minute_units >= grant.requests_per_minute:
                raise RateLimitError(
                    "The API consumer per-minute quota has been exhausted.",
                    details={"retry_after_seconds": 60},
                )
            if prepared.month_units >= grant.monthly_quota:
                raise RateLimitError("The API consumer monthly quota has been exhausted.")

            retention = self._prepared_retention(prepared)
            invocation_id = uuid7()
            authorization = self._authorization(
                invocation_id=invocation_id,
                requested_scope=requested_scope,
                grant=grant,
                product=product,
                version=version,
                maximum_classification=classification,
            )

            async def execute() -> dict[str, Any]:
                try:
                    async with asyncio.timeout(version.timeout_ms / 1000):
                        return await result_builder(authorization)
                except TimeoutError as error:
                    raise ExternalDependencyError(
                        "The API-product execution exceeded its contract timeout.",
                        dependency="api_product_runtime",
                        retryable=True,
                    ) from error

            result_document = await execute_or_replay_invocation(
                existing=None,
                request_hash=request_hash,
                executor=execute,
            )
            canonical_result = validate_canonical_result(result_document)
            completion = await self._complete_invocation(
                binding=binding,
                authorization=authorization,
                request_hash=request_hash,
                security_scope_hash=security_scope_hash,
                key_hash=key_hash,
                canonical_result=canonical_result,
                retention=retention,
            )
            if completion == "RATE_MINUTE":
                raise RateLimitError(
                    "The API consumer per-minute quota has been exhausted.",
                    details={"retry_after_seconds": 60},
                )
            if completion == "RATE_MONTH":
                raise RateLimitError("The API consumer monthly quota has been exhausted.")
            if completion == "OVERSIZE":
                raise ValidationError("The API-product result exceeds the 1 MiB contract.")
            if completion == "RETENTION_DENIED":
                raise ConflictError(
                    "The active retention policy no longer permits this invocation result."
                )
            if completion != "RECORDED":
                raise ConflictError(
                    "The invocation could not be committed under its current authorization."
                )
            await self._session.commit()
            return InvocationResultRecord(
                authorization=authorization,
                result_document=canonical_result.document,
                replayed=False,
            )
        except Exception:
            await self._session.rollback()
            raise

    async def _locked_product(self, workspace_id: UUID, product_id: UUID) -> ApiProductModel:
        product = await self._session.scalar(
            select(ApiProductModel)
            .where(
                ApiProductModel.workspace_id == workspace_id,
                ApiProductModel.id == product_id,
            )
            .with_for_update()
        )
        if product is None:
            raise NotFoundError("The API product does not exist.")
        return product

    async def _invocation_product(self, workspace_id: UUID, product_id: UUID) -> ApiProductModel:
        product = await self._session.scalar(
            select(ApiProductModel)
            .where(
                ApiProductModel.workspace_id == workspace_id,
                ApiProductModel.id == product_id,
                ApiProductModel.state == ApiProductState.PUBLISHED.value,
            )
            .with_for_update(read=True)
        )
        if product is None:
            raise ForbiddenError("No active API product exists for this invocation.")
        return product

    async def _require_service_consumer(self, *, workspace_id: UUID, subject_id: UUID) -> str:
        row = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    SubjectModel.id == subject_id,
                    SubjectModel.active.is_(True),
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == subject_id,
                    WorkspaceMembershipModel.active.is_(True),
                    WorkspaceMembershipModel.job_function == "SERVICE_ACCOUNT",
                    WorkspaceMembershipModel.access_expires_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise ValidationError(
                "A consumer grant requires an active non-expiring service-account membership."
            )
        subject, _membership = row
        issuer = subject.issuer
        if not isinstance(issuer, str) or not issuer:
            raise ValidationError("The service-account Subject issuer is unavailable.")
        return issuer

    async def _require_current_service_consumer(
        self, *, workspace_id: UUID, subject_id: UUID, issuer: str
    ) -> None:
        try:
            current_issuer = await self._require_service_consumer(
                workspace_id=workspace_id,
                subject_id=subject_id,
            )
        except ValidationError as error:
            raise ForbiddenError("The API consumer identity is not active.") from error
        if current_issuer != issuer:
            raise ForbiddenError("The API consumer issuer does not match its grant.")

    async def _database_time(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("PostgreSQL did not return a transaction timestamp.")
        return value

    @staticmethod
    def _validate_invocation_contract(
        *,
        version: ApiProductVersionModel,
        requested_scope: str,
        operation: str,
        result_type: str,
    ) -> None:
        expected = {
            "SNAPSHOT": ("snapshot.read", "snapshot-v1", "SNAPSHOT_V1"),
            "NEIGHBORS": ("neighbors.query", "neighbors-v1", "NEIGHBORS_V1"),
            "CHAT": ("chat.query", "chat-v1", "CHAT_LOCAL_V1"),
        }.get(version.surface)
        if expected is None:
            raise ValidationError("The API product surface is not executable.")
        expected_scope, expected_template, expected_result_type = expected
        scopes = version.contract_document.get("scopes")
        response_schema = version.contract_document.get("response_schema")
        if (
            requested_scope != expected_scope
            or operation != expected_result_type
            or result_type != expected_result_type
            or not isinstance(scopes, list)
            or expected_scope not in {str(value) for value in scopes}
            or version.contract_document.get("query_template") != expected_template
            or not isinstance(response_schema, dict)
            or response_schema.get("type") != "object"
            or response_schema.get("additionalProperties", False) is not False
        ):
            raise ValidationError("The API product execution contract is invalid.")

    async def _prepare_invocation(
        self,
        *,
        binding: InvocationRequestBinding,
        request_hash: str,
        security_scope_hash: str,
        key_hash: str,
    ) -> _PreparedInvocation:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT *
                    FROM sharing.prepare_api_invocation_v2(
                        CAST(:workspace_id AS uuid),
                        CAST(:subject_id AS uuid),
                        CAST(:grant_id AS uuid),
                        :invocation_key_hash,
                        :legacy_invocation_key,
                        :consumer_issuer,
                        :consumer_client_id,
                        CAST(:product_id AS uuid),
                        CAST(:product_version_id AS uuid),
                        CAST(:graph_id AS uuid),
                        CAST(:release_id AS uuid),
                        :release_content_hash,
                        :surface,
                        :requested_scope,
                        CAST(:effective_classification AS integer),
                        :security_scope_hash,
                        :request_hash,
                        :result_type
                    )
                    """
                    ),
                    {
                        "workspace_id": binding.workspace_id,
                        "subject_id": binding.subject_id,
                        "grant_id": binding.grant_id,
                        "invocation_key_hash": key_hash,
                        "legacy_invocation_key": binding.invocation_key,
                        "consumer_issuer": binding.consumer_issuer,
                        "consumer_client_id": binding.consumer_client_id,
                        "product_id": binding.product_id,
                        "product_version_id": binding.product_version_id,
                        "graph_id": binding.graph_id,
                        "release_id": binding.release_id,
                        "release_content_hash": binding.release_content_hash,
                        "surface": binding.surface,
                        "requested_scope": binding.requested_scope,
                        "effective_classification": binding.effective_classification,
                        "security_scope_hash": security_scope_hash,
                        "request_hash": request_hash,
                        "result_type": binding.result_type,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _PreparedInvocation(
            status=str(row["status"]),
            invocation_id=row["invocation_id"],
            result_hash=row["stored_result_hash"],
            result_size_bytes=row["stored_result_size_bytes"],
            retention_policy_id=row["stored_retention_policy_id"],
            retention_policy_hash=row["stored_retention_policy_hash"],
            retention_data_class=row["stored_retention_data_class"],
            retention_until=row["stored_retention_until"],
            result_document=row["result_document"],
            minute_units=int(row["minute_units"]),
            month_units=int(row["month_units"]),
        )

    async def _complete_invocation(
        self,
        *,
        binding: InvocationRequestBinding,
        authorization: InvocationAuthorizationRecord,
        request_hash: str,
        security_scope_hash: str,
        key_hash: str,
        canonical_result: CanonicalInvocationResult,
        retention: _InvocationRetentionBinding,
    ) -> str:
        status = await self._session.scalar(
            text(
                """
                SELECT status
                FROM sharing.complete_api_invocation_v2(
                    CAST(:workspace_id AS uuid),
                    CAST(:subject_id AS uuid),
                    CAST(:grant_id AS uuid),
                    CAST(:invocation_id AS uuid),
                    :invocation_key_hash,
                    :legacy_invocation_key,
                    :consumer_issuer,
                    :consumer_client_id,
                    CAST(:product_id AS uuid),
                    CAST(:product_version_id AS uuid),
                    CAST(:graph_id AS uuid),
                    CAST(:release_id AS uuid),
                    :release_content_hash,
                    :surface,
                    :requested_scope,
                    :request_id,
                    CAST(:effective_classification AS integer),
                    :security_scope_hash,
                    :request_hash,
                    :result_type,
                    :result_document,
                    :retention_data_class,
                    CAST(:retention_policy_id AS uuid),
                    :retention_policy_hash
                )
                """
            ),
            {
                "workspace_id": binding.workspace_id,
                "subject_id": binding.subject_id,
                "grant_id": binding.grant_id,
                "invocation_id": authorization.invocation_id,
                "invocation_key_hash": key_hash,
                "legacy_invocation_key": binding.invocation_key,
                "consumer_issuer": binding.consumer_issuer,
                "consumer_client_id": binding.consumer_client_id,
                "product_id": binding.product_id,
                "product_version_id": binding.product_version_id,
                "graph_id": binding.graph_id,
                "release_id": binding.release_id,
                "release_content_hash": binding.release_content_hash,
                "surface": binding.surface,
                "requested_scope": binding.requested_scope,
                "request_id": binding.request_id,
                "effective_classification": binding.effective_classification,
                "security_scope_hash": security_scope_hash,
                "request_hash": request_hash,
                "result_type": binding.result_type,
                "result_document": canonical_result.encoded.decode("utf-8"),
                "retention_data_class": retention.data_class.value,
                "retention_policy_id": retention.policy_id,
                "retention_policy_hash": retention.policy_hash,
            },
        )
        if not isinstance(status, str):
            raise RuntimeError("PostgreSQL did not return an invocation completion state.")
        return status

    @staticmethod
    def _prepared_retention(prepared: _PreparedInvocation) -> _InvocationRetentionBinding:
        if (
            prepared.retention_policy_id is None
            or prepared.retention_policy_hash is None
            or prepared.retention_data_class is None
        ):
            raise ConflictError("The current Sharing result retention binding is unavailable.")
        try:
            data_class = RetentionDataClass(prepared.retention_data_class)
        except ValueError as error:
            raise ConflictError(
                "The current Sharing result retention data class is invalid."
            ) from error
        return _InvocationRetentionBinding(
            data_class=data_class,
            policy_id=prepared.retention_policy_id,
            policy_hash=prepared.retention_policy_hash,
        )

    async def _replay_prepared_invocation(
        self,
        *,
        prepared: _PreparedInvocation,
        binding: InvocationRequestBinding,
        request_hash: str,
        grant: ConsumerGrantModel,
        product: ApiProductModel,
        version: ApiProductVersionModel,
    ) -> InvocationResultRecord:
        if (
            prepared.invocation_id is None
            or prepared.result_hash is None
            or prepared.result_size_bytes is None
            or prepared.retention_policy_id is None
            or prepared.retention_policy_hash is None
            or prepared.retention_data_class is None
            or prepared.retention_until is None
            or prepared.result_document is None
        ):
            raise ConflictError("The stored invocation result evidence is incomplete.")
        if await self._database_time() >= prepared.retention_until:
            raise ConflictError("The stored invocation result is no longer replayable.")
        try:
            decoded_result = json.loads(prepared.result_document)
        except (TypeError, ValueError) as error:
            raise ConflictError("The stored invocation result is not valid JSON.") from error
        canonical_result = validate_canonical_result(decoded_result)
        if (
            prepared.result_document != canonical_result.encoded.decode("utf-8")
            or prepared.result_size_bytes != canonical_result.size_bytes
            or prepared.result_hash != canonical_result.content_hash
        ):
            raise ConflictError("The stored invocation result evidence failed integrity checks.")
        document = await execute_or_replay_invocation(
            existing=CompletedInvocation(
                invocation_id=prepared.invocation_id,
                request_hash=request_hash,
                result_document=canonical_result.document,
            ),
            request_hash=request_hash,
            executor=_unreachable_executor,
        )
        authorization = self._authorization(
            invocation_id=prepared.invocation_id,
            requested_scope=binding.requested_scope,
            grant=grant,
            product=product,
            version=version,
            maximum_classification=binding.effective_classification,
        )
        await self._session.commit()
        return InvocationResultRecord(
            authorization=authorization,
            result_document=document,
            replayed=True,
        )

    async def _require_release(
        self, workspace_id: UUID, graph_id: UUID, release_id: UUID
    ) -> ReleaseModel:
        release = await require_governed_release_base(
            self._session,
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
        )
        if release is None:
            raise ValidationError("The pinned governed graph release does not exist.")
        return release

    @staticmethod
    def _validate_release_bound(*, release: ReleaseModel, surface: str, maximum_nodes: int) -> None:
        if surface in {"SNAPSHOT", "CHAT"} and release.node_count > maximum_nodes:
            raise ValidationError(
                "The pinned release exceeds this full-view API product's node limit."
            )

    async def _versions_for_products(
        self, workspace_id: UUID, product_ids: set[UUID]
    ) -> defaultdict[UUID, tuple[ApiProductVersionRecord, ...]]:
        grouped_lists: defaultdict[UUID, list[ApiProductVersionRecord]] = defaultdict(list)
        if product_ids:
            values = await self._session.scalars(
                select(ApiProductVersionModel)
                .where(
                    ApiProductVersionModel.workspace_id == workspace_id,
                    ApiProductVersionModel.product_id.in_(product_ids),
                    ApiProductVersionModel.release_id.in_(
                        governed_release_ids(
                            workspace_id=workspace_id,
                            graph_id=ApiProductVersionModel.graph_id,
                        ).correlate(ApiProductVersionModel)
                    ),
                )
                .order_by(ApiProductVersionModel.product_id, ApiProductVersionModel.version_no)
            )
            for value in values:
                grouped_lists[value.product_id].append(_version_record(value))
        grouped: defaultdict[UUID, tuple[ApiProductVersionRecord, ...]] = defaultdict(tuple)
        grouped.update({key: tuple(value) for key, value in grouped_lists.items()})
        return grouped

    @staticmethod
    def _authorization(
        *,
        invocation_id: UUID,
        requested_scope: str,
        grant: ConsumerGrantModel,
        product: ApiProductModel,
        version: ApiProductVersionModel,
        maximum_classification: int,
    ) -> InvocationAuthorizationRecord:
        return InvocationAuthorizationRecord(
            invocation_id=invocation_id,
            grant_id=grant.id,
            product_id=product.id,
            product_version_id=version.id,
            graph_id=product.graph_id,
            release_id=version.release_id,
            surface=version.surface,
            requested_scope=requested_scope,
            maximum_classification=Classification(maximum_classification),
            maximum_hops=version.maximum_hops,
            maximum_nodes=version.maximum_nodes,
            timeout_ms=version.timeout_ms,
        )

    async def _commit_or_conflict(self, message: str) -> None:
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(message) from error
