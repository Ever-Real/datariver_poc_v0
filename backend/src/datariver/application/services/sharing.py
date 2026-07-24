from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from datariver.application.dto import (
    ApiProductRecord,
    ApiProductVersionRecord,
    ConsumerGrantRecord,
    InvocationAuthorizationRecord,
    InvocationResultRecord,
)
from datariver.application.ports import SharingStore
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)


class SharingService:
    def __init__(self, *, store: SharingStore, authorization: AuthorizationService) -> None:
        self._store = store
        self._authorization = authorization

    async def create_product(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        graph_id: UUID,
        release_id: UUID,
        classification: Classification,
        slug: str,
        name: str,
        description: str,
        surface: str,
        contract_document: dict[str, Any],
        maximum_hops: int,
        maximum_nodes: int,
        timeout_ms: int,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ApiProductRecord:
        await self._authorize(
            subject=subject,
            product_id=graph_id,
            workspace_id=workspace_id,
            owner_id=subject.subject_id,
            classification=classification,
            lifecycle="DRAFT",
            action=Action.SHARING_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.create_product(
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            description=description,
            graph_id=graph_id,
            release_id=release_id,
            classification=int(classification),
            owner_id=subject.subject_id,
            surface=surface,
            contract_document=contract_document,
            maximum_hops=maximum_hops,
            maximum_nodes=maximum_nodes,
            timeout_ms=timeout_ms,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def list_products(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ApiProductRecord, ...]:
        await self._authorize(
            subject=subject,
            product_id=workspace_id,
            workspace_id=workspace_id,
            owner_id=None,
            classification=Classification.PUBLIC,
            lifecycle="ACTIVE",
            action=Action.SHARING_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.list_products(
            workspace_id=workspace_id, clearance=int(subject.clearance)
        )

    async def get_product(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        action: Action = Action.SHARING_MANAGE,
    ) -> ApiProductRecord | None:
        product = await self._store.get_product(
            workspace_id=workspace_id,
            product_id=product_id,
            clearance=int(subject.clearance),
        )
        if product is None:
            return None
        await self._authorize_product(
            product=product,
            subject=subject,
            action=action,
            environment=environment,
            request_id=request_id,
        )
        return product

    async def create_version(
        self,
        *,
        product: ApiProductRecord,
        workspace_id: UUID,
        subject: SubjectAttributes,
        release_id: UUID,
        surface: str,
        contract_document: dict[str, Any],
        maximum_hops: int,
        maximum_nodes: int,
        timeout_ms: int,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ApiProductVersionRecord:
        await self._authorize_product(
            product=product,
            subject=subject,
            action=Action.SHARING_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.create_version(
            workspace_id=workspace_id,
            product_id=product.product_id,
            release_id=release_id,
            actor_id=subject.subject_id,
            surface=surface,
            contract_document=contract_document,
            maximum_hops=maximum_hops,
            maximum_nodes=maximum_nodes,
            timeout_ms=timeout_ms,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def publish_version(
        self,
        *,
        product: ApiProductRecord,
        workspace_id: UUID,
        version_id: UUID,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ApiProductRecord:
        await self._authorize_product(
            product=product,
            subject=subject,
            action=Action.SHARING_PUBLISH,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.publish_version(
            workspace_id=workspace_id,
            product_id=product.product_id,
            version_id=version_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
        )

    async def create_grant(
        self,
        *,
        product: ApiProductRecord,
        workspace_id: UUID,
        consumer_subject_id: UUID,
        consumer_client_id: str,
        scopes: frozenset[str],
        maximum_classification: Classification,
        requests_per_minute: int,
        monthly_quota: int,
        valid_from: datetime,
        expires_at: datetime,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ConsumerGrantRecord:
        await self._authorize_product(
            product=product,
            subject=subject,
            action=Action.SHARING_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.create_grant(
            workspace_id=workspace_id,
            product_id=product.product_id,
            consumer_subject_id=consumer_subject_id,
            consumer_client_id=consumer_client_id,
            scopes=scopes,
            maximum_classification=int(maximum_classification),
            requests_per_minute=requests_per_minute,
            monthly_quota=monthly_quota,
            valid_from=valid_from,
            expires_at=expires_at,
            actor_id=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def list_grants(
        self,
        *,
        product: ApiProductRecord,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ConsumerGrantRecord, ...]:
        await self._authorize_product(
            product=product,
            subject=subject,
            action=Action.SHARING_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.list_grants(
            workspace_id=workspace_id, product_id=product.product_id
        )

    async def revoke_grant(
        self,
        *,
        product: ApiProductRecord,
        workspace_id: UUID,
        grant_id: UUID,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ConsumerGrantRecord:
        await self._authorize_product(
            product=product,
            subject=subject,
            action=Action.SHARING_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.revoke_grant(
            workspace_id=workspace_id,
            product_id=product.product_id,
            grant_id=grant_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
        )

    async def execute_invocation(
        self,
        *,
        product: ApiProductRecord,
        workspace_id: UUID,
        consumer_issuer: str,
        consumer_client_id: str,
        requested_scope: str,
        operation: str,
        result_type: str,
        payload_document: dict[str, Any],
        invocation_key: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        result_builder: Callable[[InvocationAuthorizationRecord], Awaitable[dict[str, Any]]],
    ) -> InvocationResultRecord:
        await self._authorize_product(
            product=product,
            subject=subject,
            action=Action.SHARING_INVOKE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.execute_invocation(
            workspace_id=workspace_id,
            product_id=product.product_id,
            actor_id=subject.subject_id,
            consumer_issuer=consumer_issuer,
            consumer_client_id=consumer_client_id,
            security_scopes=_subject_security_scopes(subject),
            effective_classification=int(subject.clearance),
            requested_scope=requested_scope,
            operation=operation,
            result_type=result_type,
            payload_document=payload_document,
            invocation_key=invocation_key,
            request_id=request_id,
            result_builder=result_builder,
        )

    async def _authorize_product(
        self,
        *,
        product: ApiProductRecord,
        subject: SubjectAttributes,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorize(
            subject=subject,
            product_id=product.product_id,
            workspace_id=product.workspace_id,
            owner_id=product.owner_id if action is not Action.SHARING_INVOKE else None,
            classification=product.classification,
            lifecycle=product.state,
            action=action,
            environment=environment,
            request_id=request_id,
        )

    async def _authorize(
        self,
        *,
        subject: SubjectAttributes,
        product_id: UUID,
        workspace_id: UUID,
        owner_id: UUID | None,
        classification: Classification,
        lifecycle: str,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=product_id,
                workspace_id=workspace_id,
                resource_type="api_product",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=classification,
                lifecycle=lifecycle,
                owner_subject_id=owner_id,
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )


def _subject_security_scopes(subject: SubjectAttributes) -> frozenset[str]:
    values = {
        f"active:{str(subject.active).lower()}",
        f"clearance:{int(subject.clearance)}",
        f"department:{subject.department_id or '-'}",
        f"job_function:{subject.job_function or '-'}",
    }
    values.update(f"group:{value}" for value in subject.groups)
    values.update(f"system:{value}" for value in subject.allowed_system_ids)
    values.update(f"domain:{value}" for value in subject.allowed_domain_ids)
    values.update(f"allow:{value.value}" for value in subject.allowed_actions)
    values.update(f"deny:{value.value}" for value in subject.denied_actions)
    return frozenset(values)
