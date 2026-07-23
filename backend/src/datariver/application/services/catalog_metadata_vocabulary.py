from __future__ import annotations

import asyncio
from uuid import UUID

from datariver.application.dto import (
    CatalogMetadataVocabularyPage,
    CatalogVocabularySyncResult,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    CatalogMetadataVocabularyProjection,
    DataHubGateway,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.registration_worker import (
    SERVICE_ACCOUNT_GROUP,
    SERVICE_ACCOUNT_JOB_FUNCTION,
    require_registration_operator_identity,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError

_KINDS = frozenset({"DOMAIN", "TAG", "TERM"})


def require_catalog_vocabulary_sync_admin(
    subject: SubjectAttributes,
) -> SubjectAttributes:
    """Require the canonical active human security-administrator identity."""

    require_registration_operator_identity(subject)
    if (
        subject.job_function == SERVICE_ACCOUNT_JOB_FUNCTION
        or SERVICE_ACCOUNT_GROUP in subject.groups
        or "security-administrators" not in subject.groups
    ):
        raise ForbiddenError(
            "Catalog vocabulary reconciliation requires an active human security administrator."
        )
    return subject


class CatalogMetadataVocabularyService:
    def __init__(
        self,
        *,
        datahub: DataHubGateway,
        projection: CatalogMetadataVocabularyProjection,
        authorization: AuthorizationService,
        provider_budget_seconds: float = 10.0,
    ) -> None:
        if not 0 < provider_budget_seconds <= 10:
            raise ValueError("The vocabulary provider budget is invalid.")
        self._datahub = datahub
        self._projection = projection
        self._authorization = authorization
        self._provider_budget_seconds = provider_budget_seconds

    async def sync_page(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        kind: str,
        offset: int,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogVocabularySyncResult:
        require_catalog_vocabulary_sync_admin(subject)
        if subject.workspace_id != workspace_id:
            raise ForbiddenError("The vocabulary workspace does not match the current subject.")
        if kind not in _KINDS or offset < 0 or not 1 <= limit <= 100:
            raise ValueError("The catalog vocabulary sync request is invalid.")
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="catalog_vocabulary_projection",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.RESTRICTED,
                lifecycle="ACTIVE",
            ),
            action=Action.CATALOG_SYNC,
            environment=environment,
            request_id=request_id,
        )
        operation = f"catalog.datahub.vocabulary.sync:{kind}:{offset}:{limit}"
        reservation = await self._projection.reserve_scan(
            workspace_id=workspace_id,
            sync_id=sync_id,
            kind=kind,
            offset=offset,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation,
        )
        if reservation.replayed is not None:
            return reservation.replayed
        try:
            try:
                async with asyncio.timeout(self._provider_budget_seconds):
                    page = await self._datahub.scan_vocabulary(
                        kind=kind,
                        cursor=reservation.cursor,
                        limit=limit,
                    )
            except TimeoutError as error:
                raise ExternalDependencyError(
                    "DataHub exceeded the vocabulary synchronization budget.",
                    dependency="datahub",
                    retryable=True,
                    provider_code="VOCABULARY_SYNC_TIMEOUT",
                ) from error
        except ExternalDependencyError as error:
            if reservation.cursor is not None and not error.details.get("retryable", False):
                await self._projection.abandon_scan(
                    workspace_id=workspace_id,
                    sync_id=sync_id,
                    kind=kind,
                )
            else:
                await self._projection.release_scan()
            raise
        except BaseException:
            await self._projection.release_scan()
            raise
        if any(item.kind != kind for item in page.items):
            if reservation.cursor is not None:
                await self._projection.abandon_scan(
                    workspace_id=workspace_id,
                    sync_id=sync_id,
                    kind=kind,
                )
            else:
                await self._projection.release_scan()
            raise ExternalDependencyError(
                "DataHub returned a cross-kind vocabulary page.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        next_offset = offset + 1 if page.next_cursor is not None else None
        try:
            return await self._projection.upsert_scan(
                workspace_id=workspace_id,
                sync_id=sync_id,
                kind=kind,
                offset=offset,
                cursor=reservation.cursor,
                next_offset=next_offset,
                page=page,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                operation=operation,
            )
        except BaseException:
            await self._projection.release_scan()
            raise

    async def list_active(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        query: str | None,
        cursor: str | None,
        limit: int,
        subject: SubjectAttributes,
    ) -> CatalogMetadataVocabularyPage:
        require_registration_operator_identity(subject)
        if subject.workspace_id != workspace_id:
            raise ForbiddenError("The vocabulary workspace does not match the current subject.")
        normalized_query = query.strip() if query is not None else None
        if (
            kind not in _KINDS
            or not 1 <= limit <= 50
            or (normalized_query is not None and not 1 <= len(normalized_query) <= 200)
        ):
            raise ValueError("The catalog vocabulary query is invalid.")
        return await self._projection.list_active(
            workspace_id=workspace_id,
            kind=kind,
            query=normalized_query,
            cursor=cursor,
            limit=limit,
        )
