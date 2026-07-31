from __future__ import annotations

from typing import Protocol
from uuid import UUID

from datariver.application.knowledge_asset_contracts import (
    KnowledgeAssetOperationalDetail,
    KnowledgeAssetPage,
    KnowledgeAssetSummary,
    KnowledgeChatCandidate,
    KnowledgeGraphChatScope,
)
from datariver.domain.authz import EnvironmentAttributes, SubjectAttributes
from datariver.domain.knowledge_assets import KnowledgeDeliveryPolicy


class KnowledgeAssetRepository(Protocol):
    async def list_assets(
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        query: str,
        sort: str,
        cursor: str | None,
        limit: int,
    ) -> KnowledgeAssetPage: ...

    async def get_asset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
    ) -> KnowledgeAssetSummary | None: ...

    async def get_asset_by_alias(
        self,
        *,
        workspace_id: UUID,
        alias: str,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        require_api_enabled: bool,
    ) -> KnowledgeAssetSummary | None: ...

    async def get_operational_detail(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
    ) -> KnowledgeAssetOperationalDetail | None: ...

    async def save_delivery_policy(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        actor_id: UUID,
        api_enabled: bool,
        chat_enabled: bool,
        priority: int,
        match_any_terms: tuple[str, ...],
        match_all_terms: tuple[str, ...],
        excluded_terms: tuple[str, ...],
        expected_version: int | None,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeDeliveryPolicy: ...

    async def list_chat_candidates(
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        requested_graph_id: UUID | None,
        normalized_question: str | None,
        limit: int,
    ) -> tuple[KnowledgeChatCandidate, ...]: ...


class KnowledgeGraphScopeResolver(Protocol):
    async def resolve_graph_scope(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        question: str,
        requested_graph_id: UUID | None,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeGraphChatScope | None: ...
