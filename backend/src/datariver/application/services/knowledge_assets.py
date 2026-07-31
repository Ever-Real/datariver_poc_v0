from __future__ import annotations

import unicodedata
from uuid import UUID

from datariver.application.knowledge_asset_contracts import (
    KnowledgeAssetOperationalDetail,
    KnowledgeAssetPage,
    KnowledgeAssetSummary,
    KnowledgeAssetVersionPage,
    KnowledgeGraphChatScope,
)
from datariver.application.knowledge_asset_ports import (
    KnowledgeAssetRepository,
    KnowledgeGraphScopeResolver,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import NotFoundError
from datariver.domain.knowledge_assets import (
    KnowledgeDeliveryPolicy,
    validate_delivery_policy,
)


class KnowledgeAssetService:
    def __init__(
        self,
        *,
        repository: KnowledgeAssetRepository,
        authorization: AuthorizationService,
    ) -> None:
        self._repository = repository
        self._authorization = authorization

    async def list_assets(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        query: str,
        domain_id: UUID | None,
        sort: str,
        cursor: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeAssetPage:
        await self._authorization.authorize(
            subject=subject,
            resource=_resource(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                domain_id=None,
                classification=Classification.PUBLIC,
            ),
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return await self._repository.list_assets(
            workspace_id=workspace_id,
            clearance=int(subject.clearance),
            allowed_domain_ids=subject.allowed_domain_ids,
            query=query.strip(),
            domain_id=domain_id,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )

    async def get_detail(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeAssetOperationalDetail:
        detail = await self._repository.get_operational_detail(
            workspace_id=workspace_id,
            graph_id=graph_id,
            clearance=int(subject.clearance),
            allowed_domain_ids=subject.allowed_domain_ids,
        )
        if detail is None:
            raise NotFoundError("The Knowledge Asset does not exist.")
        await self._authorize_asset(
            asset=detail.asset,
            subject=subject,
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return detail

    async def list_versions(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        subject: SubjectAttributes,
        cursor: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeAssetVersionPage:
        asset = await self._repository.get_asset(
            workspace_id=workspace_id,
            graph_id=graph_id,
            clearance=int(subject.clearance),
            allowed_domain_ids=subject.allowed_domain_ids,
        )
        if asset is None:
            raise NotFoundError("The Knowledge Asset does not exist.")
        await self._authorize_asset(
            asset=asset,
            subject=subject,
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return await self._repository.list_version_events(
            workspace_id=workspace_id,
            graph_id=graph_id,
            cursor=cursor,
            limit=limit,
        )

    async def resolve_api_asset(
        self,
        *,
        workspace_id: UUID,
        alias: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeAssetSummary:
        asset = await self._repository.get_asset_by_alias(
            workspace_id=workspace_id,
            alias=alias,
            clearance=int(subject.clearance),
            allowed_domain_ids=subject.allowed_domain_ids,
            require_api_enabled=True,
        )
        if asset is None or asset.active_release_id is None:
            raise NotFoundError("The enabled Knowledge Asset endpoint does not exist.")
        await self._authorize_asset(
            asset=asset,
            subject=subject,
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return asset

    async def save_delivery_policy(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        subject: SubjectAttributes,
        api_enabled: bool,
        chat_enabled: bool,
        priority: int,
        match_any_terms: tuple[str, ...],
        match_all_terms: tuple[str, ...],
        excluded_terms: tuple[str, ...],
        expected_version: int | None,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeDeliveryPolicy:
        asset = await self._repository.get_asset(
            workspace_id=workspace_id,
            graph_id=graph_id,
            clearance=int(subject.clearance),
            allowed_domain_ids=subject.allowed_domain_ids,
        )
        if asset is None:
            raise NotFoundError("The Knowledge Asset does not exist.")
        await self._authorize_asset(
            asset=asset,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        any_terms, all_terms, excluded = validate_delivery_policy(
            chat_enabled=chat_enabled,
            priority=priority,
            match_any_terms=match_any_terms,
            match_all_terms=match_all_terms,
            excluded_terms=excluded_terms,
        )
        return await self._repository.save_delivery_policy(
            workspace_id=workspace_id,
            graph_id=graph_id,
            actor_id=subject.subject_id,
            api_enabled=api_enabled,
            chat_enabled=chat_enabled,
            priority=priority,
            match_any_terms=any_terms,
            match_all_terms=all_terms,
            excluded_terms=excluded,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def _authorize_asset(
        self,
        *,
        asset: KnowledgeAssetSummary,
        subject: SubjectAttributes,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=_resource(
                resource_id=asset.graph_id,
                workspace_id=subject.workspace_id,
                domain_id=asset.domain_id,
                classification=asset.classification,
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )


def _resource(
    *,
    resource_id: UUID,
    workspace_id: UUID,
    domain_id: UUID | None,
    classification: Classification,
) -> ResourceAttributes:
    return ResourceAttributes(
        resource_id=resource_id,
        workspace_id=workspace_id,
        resource_type="knowledge_graph",
        owner_department_id=None,
        system_id=None,
        domain_id=domain_id,
        classification=classification,
        lifecycle="ACTIVE",
        owner_subject_id=None,
    )


class KnowledgeGraphScopeService(KnowledgeGraphScopeResolver):
    def __init__(
        self,
        *,
        repository: KnowledgeAssetRepository,
        authorization: AuthorizationService,
    ) -> None:
        self._repository = repository
        self._authorization = authorization

    async def resolve_graph_scope(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        question: str,
        requested_graph_id: UUID | None,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeGraphChatScope | None:
        candidates = await self._repository.list_chat_candidates(
            workspace_id=workspace_id,
            clearance=int(subject.clearance),
            allowed_domain_ids=subject.allowed_domain_ids,
            requested_graph_id=requested_graph_id,
            normalized_question=(
                None
                if requested_graph_id is not None
                else unicodedata.normalize("NFC", question).casefold()
            ),
            limit=2,
        )
        if requested_graph_id is not None:
            selected = next(
                (item for item in candidates if item.graph_id == requested_graph_id),
                None,
            )
        else:
            matching = tuple(item for item in candidates if item.delivery_policy.matches(question))
            ranked = sorted(
                matching,
                key=lambda item: (
                    item.delivery_policy.priority,
                    len(
                        set(item.delivery_policy.match_all_terms)
                        | set(item.delivery_policy.match_any_terms)
                    ),
                ),
                reverse=True,
            )
            selected = ranked[0] if ranked else None
            if len(ranked) > 1 and selected is not None:
                selected_policy = selected.delivery_policy
                next_policy = ranked[1].delivery_policy
                if selected_policy.priority == next_policy.priority and len(
                    set(selected_policy.match_all_terms) | set(selected_policy.match_any_terms)
                ) == len(set(next_policy.match_all_terms) | set(next_policy.match_any_terms)):
                    return None
        if selected is None:
            return None
        await self._authorization.authorize(
            subject=subject,
            resource=_resource(
                resource_id=selected.graph_id,
                workspace_id=workspace_id,
                domain_id=selected.domain_id,
                classification=selected.classification,
            ),
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return KnowledgeGraphChatScope(
            graph_id=selected.graph_id,
            release_id=selected.release_id,
            policy_id=selected.delivery_policy.policy_id,
            policy_version=selected.delivery_policy.version,
            policy_hash=selected.delivery_policy.content_hash(),
            domain_id=selected.domain_id,
            classification=selected.classification,
        )
