from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    ApiProductRecord,
    ApiProductVersionRecord,
    ConsumerGrantRecord,
    InvocationAuthorizationRecord,
)
from datariver.application.ports import SharingStore
from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    utc_now,
    uuid7,
)
from datariver.domain.sharing import (
    ApiProduct,
    ApiProductState,
    ApiProductVersionState,
    ConsumerGrant,
    ConsumerGrantState,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.knowledge import (
    governed_release_ids,
    require_governed_release_base,
)
from datariver.infrastructure.db.models.knowledge import ReleaseModel
from datariver.infrastructure.db.models.sharing import (
    ApiInvocationModel,
    ApiProductModel,
    ApiProductVersionModel,
    ConsumerGrantModel,
)


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
        await self._session.commit()
        versions = await self._versions_for_products(workspace_id, {product.id})
        return _product_record(product, versions[product.id])

    async def create_grant(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
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
            ):
                raise ConflictError("The idempotent consumer grant result is unavailable.")
            product = await self._locked_product(workspace_id, product_id)
            if product.owner_id != actor_id:
                raise ConflictError(
                    "The idempotent consumer grant result is bound to another owner."
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
        allowed_scopes = version.contract_document.get("scopes", [])
        if not isinstance(allowed_scopes, list) or not scopes.issubset(
            {str(value) for value in allowed_scopes}
        ):
            raise ValidationError("The grant contains a scope outside the product contract.")
        if maximum_classification < product.classification:
            raise ValidationError("The grant classification ceiling is below the product.")
        if expires_at <= valid_from:
            raise ValidationError("The grant expiration must be after its start time.")
        grant_id = uuid7()
        grant = ConsumerGrantModel(
            id=grant_id,
            workspace_id=workspace_id,
            product_id=product_id,
            product_version_id=version.id,
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

    async def authorize_invocation(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        consumer_client_id: str,
        requested_scope: str,
        invocation_key: str,
        request_id: str,
    ) -> InvocationAuthorizationRecord:
        row = (
            await self._session.execute(
                select(ConsumerGrantModel, ApiProductModel, ApiProductVersionModel)
                .join(
                    ApiProductModel,
                    (ApiProductModel.workspace_id == ConsumerGrantModel.workspace_id)
                    & (ApiProductModel.id == ConsumerGrantModel.product_id),
                )
                .join(
                    ApiProductVersionModel,
                    (ApiProductVersionModel.workspace_id == ConsumerGrantModel.workspace_id)
                    & (ApiProductVersionModel.id == ConsumerGrantModel.product_version_id),
                )
                .where(
                    ConsumerGrantModel.workspace_id == workspace_id,
                    ConsumerGrantModel.product_id == product_id,
                    ConsumerGrantModel.consumer_client_id == consumer_client_id,
                    ApiProductModel.state == ApiProductState.PUBLISHED.value,
                    ApiProductModel.current_version_id == ConsumerGrantModel.product_version_id,
                    ApiProductVersionModel.state == ApiProductVersionState.PUBLISHED.value,
                )
                .with_for_update(of=ConsumerGrantModel)
            )
        ).one_or_none()
        if row is None:
            raise ForbiddenError("No active current-version grant exists for this API client.")
        grant, product, version = row
        await self._require_release(
            workspace_id,
            version.graph_id,
            version.release_id,
        )
        now = utc_now()
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
        existing = await self._session.scalar(
            select(ApiInvocationModel).where(
                ApiInvocationModel.workspace_id == workspace_id,
                ApiInvocationModel.grant_id == grant.id,
                ApiInvocationModel.invocation_key == invocation_key,
            )
        )
        if existing is not None:
            return self._authorization(existing, grant, product, version)

        minute_count = await self._usage_count(grant.id, now - timedelta(minutes=1))
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_count = await self._usage_count(grant.id, month_start)
        if minute_count >= grant.requests_per_minute:
            raise RateLimitError(
                "The API consumer per-minute quota has been exhausted.",
                details={"retry_after_seconds": 60},
            )
        if month_count >= grant.monthly_quota:
            raise RateLimitError("The API consumer monthly quota has been exhausted.")
        invocation = ApiInvocationModel(
            id=uuid7(),
            workspace_id=workspace_id,
            grant_id=grant.id,
            invocation_key=invocation_key,
            requested_scope=requested_scope,
            request_id=request_id,
            occurred_at=now,
            units=1,
        )
        self._session.add(invocation)
        await self._session.commit()
        return self._authorization(invocation, grant, product, version)

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

    async def _usage_count(self, grant_id: UUID, since: datetime) -> int:
        value = await self._session.scalar(
            select(func.count(ApiInvocationModel.id)).where(
                ApiInvocationModel.grant_id == grant_id,
                ApiInvocationModel.occurred_at >= since,
            )
        )
        return int(value or 0)

    @staticmethod
    def _authorization(
        invocation: ApiInvocationModel,
        grant: ConsumerGrantModel,
        product: ApiProductModel,
        version: ApiProductVersionModel,
    ) -> InvocationAuthorizationRecord:
        return InvocationAuthorizationRecord(
            invocation_id=invocation.id,
            grant_id=grant.id,
            product_id=product.id,
            product_version_id=version.id,
            graph_id=product.graph_id,
            release_id=version.release_id,
            surface=version.surface,
            requested_scope=invocation.requested_scope,
            maximum_classification=Classification(grant.maximum_classification),
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
