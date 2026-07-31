from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from datariver.application.knowledge_asset_contracts import (
    KnowledgeAssetPage,
    KnowledgeAssetSummary,
    KnowledgeAssetVersionPage,
    KnowledgeChatCandidate,
    KnowledgeGraphChatScope,
)
from datariver.application.knowledge_asset_ports import KnowledgeAssetRepository
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_assets import (
    KnowledgeAssetService,
    KnowledgeGraphScopeService,
)
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError, ValidationError
from datariver.domain.knowledge_assets import (
    KnowledgeDeliveryPolicy,
    normalize_route_terms,
    validate_delivery_policy,
)
from datariver.infrastructure.db.knowledge_assets import (
    _decode_cursor,
    _decode_version_cursor,
    _encode_cursor,
    _encode_version_cursor,
    _policy_result,
    _replayed_policy,
)

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0001")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0002")
DOMAIN_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0003")
GRAPH_A_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0004")
GRAPH_B_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0005")
RELEASE_A_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0006")
RELEASE_B_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0007")
POLICY_A_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0008")
POLICY_B_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c0009")
NOW = datetime(2026, 7, 31, 6, 0, tzinfo=UTC)


def test_version_cursor_is_canonical_and_rejects_tampering() -> None:
    cursor = _encode_version_cursor(created_at=NOW, event_id=RELEASE_A_ID)

    assert _decode_version_cursor(cursor) == (NOW, RELEASE_A_ID)
    with pytest.raises(ValidationError, match="version cursor is invalid"):
        _decode_version_cursor(cursor + "=")


def test_asset_cursor_binds_the_exact_domain_filter_without_breaking_unfiltered_cursors() -> None:
    domain_cursor = _encode_cursor(
        sort="NAME_ASC",
        key="finance graph",
        graph_id=GRAPH_A_ID,
        domain_id=DOMAIN_ID,
    )

    assert _decode_cursor(
        domain_cursor,
        sort="NAME_ASC",
        domain_id=DOMAIN_ID,
    ) == ("finance graph", GRAPH_A_ID)
    with pytest.raises(ValidationError, match="page cursor is invalid"):
        _decode_cursor(domain_cursor, sort="NAME_ASC", domain_id=GRAPH_B_ID)
    with pytest.raises(ValidationError, match="page cursor is invalid"):
        _decode_cursor(domain_cursor, sort="NAME_ASC")

    unfiltered_cursor = _encode_cursor(
        sort="NAME_ASC",
        key="finance graph",
        graph_id=GRAPH_A_ID,
    )
    assert _decode_cursor(unfiltered_cursor, sort="NAME_ASC") == (
        "finance graph",
        GRAPH_A_ID,
    )
    with pytest.raises(ValidationError, match="page cursor is invalid"):
        _decode_cursor(unfiltered_cursor, sort="NAME_ASC", domain_id=DOMAIN_ID)


class MemoryDecisionWriter:
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
        del decision, subject_id, workspace_id, resource_id, action, request_id


def _subject(*, allowed_actions: frozenset[Action]) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_domain_ids=frozenset({DOMAIN_ID}),
        allowed_actions=allowed_actions,
    )


def _policy(
    *,
    graph_id: UUID,
    policy_id: UUID,
    priority: int,
    any_terms: tuple[str, ...],
    all_terms: tuple[str, ...] = (),
    excluded_terms: tuple[str, ...] = (),
) -> KnowledgeDeliveryPolicy:
    return KnowledgeDeliveryPolicy(
        policy_id=policy_id,
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        api_enabled=False,
        chat_enabled=True,
        priority=priority,
        match_any_terms=any_terms,
        match_all_terms=all_terms,
        excluded_terms=excluded_terms,
        created_by=SUBJECT_ID,
        updated_by=SUBJECT_ID,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def _asset(
    *,
    graph_id: UUID,
    release_id: UUID,
    policy: KnowledgeDeliveryPolicy,
) -> KnowledgeAssetSummary:
    return KnowledgeAssetSummary(
        graph_id=graph_id,
        slug=f"graph-{graph_id}",
        name=f"Graph {graph_id}",
        graph_type="DOMAIN",
        status="PUBLISHED",
        classification=Classification.INTERNAL,
        domain_id=DOMAIN_ID,
        domain_name="Finance",
        creator_name="SUA Han",
        creator_email="sua.han@example.com",
        editor_name="SUA Han",
        editor_email="sua.han@example.com",
        active_studio_release_id=None,
        active_studio_release_no=None,
        active_release_id=release_id,
        active_release_no=1,
        class_count=0,
        property_count=0,
        relationship_count=0,
        binding_count=0,
        source_count=0,
        node_count=1,
        edge_count=0,
        projection_state="SHADOW_VERIFIED",
        created_at=NOW,
        updated_at=NOW,
        version=1,
        delivery_policy=policy,
    )


def _chat_candidate(asset: KnowledgeAssetSummary) -> KnowledgeChatCandidate:
    assert asset.active_release_id is not None
    assert asset.delivery_policy is not None
    return KnowledgeChatCandidate(
        graph_id=asset.graph_id,
        release_id=asset.active_release_id,
        domain_id=asset.domain_id,
        classification=asset.classification,
        delivery_policy=asset.delivery_policy,
    )


def _authorization() -> AuthorizationService:
    return AuthorizationService(decision_writer=MemoryDecisionWriter())


@pytest.mark.asyncio
async def test_asset_list_forwards_the_exact_domain_filter_after_kg_read() -> None:
    page = KnowledgeAssetPage(items=(), next_cursor=None)
    repository = SimpleNamespace(list_assets=AsyncMock(return_value=page))
    service = KnowledgeAssetService(
        repository=cast(KnowledgeAssetRepository, repository),
        authorization=_authorization(),
    )

    result = await service.list_assets(
        workspace_id=WORKSPACE_ID,
        subject=_subject(allowed_actions=frozenset({Action.KG_READ})),
        query=" finance ",
        domain_id=DOMAIN_ID,
        sort="NAME_ASC",
        cursor=None,
        limit=25,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="knowledge-assets-domain",
    )

    assert result is page
    repository.list_assets.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        clearance=int(Classification.INTERNAL),
        allowed_domain_ids=frozenset({DOMAIN_ID}),
        query="finance",
        domain_id=DOMAIN_ID,
        sort="NAME_ASC",
        cursor=None,
        limit=25,
    )


@pytest.mark.asyncio
async def test_asset_list_denies_missing_kg_read_before_repository_access() -> None:
    repository = SimpleNamespace(list_assets=AsyncMock())
    service = KnowledgeAssetService(
        repository=cast(KnowledgeAssetRepository, repository),
        authorization=_authorization(),
    )

    with pytest.raises(ForbiddenError, match="requested action is not permitted"):
        await service.list_assets(
            workspace_id=WORKSPACE_ID,
            subject=_subject(allowed_actions=frozenset()),
            query="",
            domain_id=DOMAIN_ID,
            sort="NAME_ASC",
            cursor=None,
            limit=25,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="knowledge-assets-domain-denied",
        )

    repository.list_assets.assert_not_awaited()


def test_delivery_terms_are_unicode_normalized_deduplicated_and_safe() -> None:
    assert normalize_route_terms(("  재무 ", "Finance", "finance")) == ("재무", "finance")
    any_terms, all_terms, excluded = validate_delivery_policy(
        chat_enabled=True,
        priority=500,
        match_any_terms=(" 재무 ",),
        match_all_terms=(" 결산 ",),
        excluded_terms=(" 인사 ",),
    )
    assert (any_terms, all_terms, excluded) == (("재무",), ("결산",), ("인사",))

    with pytest.raises(ValidationError, match="requires at least one"):
        validate_delivery_policy(
            chat_enabled=True,
            priority=100,
            match_any_terms=(),
            match_all_terms=(),
            excluded_terms=(),
        )
    with pytest.raises(ValidationError, match="both required and excluded"):
        validate_delivery_policy(
            chat_enabled=True,
            priority=100,
            match_any_terms=("재무",),
            match_all_terms=(),
            excluded_terms=("재무",),
        )
    with pytest.raises(ValidationError, match="both ANY and ALL"):
        validate_delivery_policy(
            chat_enabled=True,
            priority=100,
            match_any_terms=("재무",),
            match_all_terms=("재무",),
            excluded_terms=(),
        )
    with pytest.raises(ValidationError, match="one line"):
        normalize_route_terms(("재무\nDROP",))


def test_delivery_policy_idempotency_replays_the_original_response_snapshot() -> None:
    original = _policy(
        graph_id=GRAPH_A_ID,
        policy_id=POLICY_A_ID,
        priority=300,
        any_terms=("재무",),
        excluded_terms=("인사",),
    )

    replayed = _replayed_policy(
        _policy_result(original),
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_A_ID,
    )

    assert replayed == original


@pytest.mark.asyncio
async def test_graph_scope_selects_one_authorized_active_release_by_policy_rank() -> None:
    low = _asset(
        graph_id=GRAPH_A_ID,
        release_id=RELEASE_A_ID,
        policy=_policy(
            graph_id=GRAPH_A_ID,
            policy_id=POLICY_A_ID,
            priority=100,
            any_terms=("재무",),
        ),
    )
    high = _asset(
        graph_id=GRAPH_B_ID,
        release_id=RELEASE_B_ID,
        policy=_policy(
            graph_id=GRAPH_B_ID,
            policy_id=POLICY_B_ID,
            priority=200,
            any_terms=("재무",),
            all_terms=("결산",),
        ),
    )
    repository = SimpleNamespace(
        list_chat_candidates=AsyncMock(return_value=(_chat_candidate(low), _chat_candidate(high)))
    )
    service = KnowledgeGraphScopeService(
        repository=cast(KnowledgeAssetRepository, repository),
        authorization=_authorization(),
    )

    result = await service.resolve_graph_scope(
        workspace_id=WORKSPACE_ID,
        subject=_subject(allowed_actions=frozenset({Action.KG_READ})),
        question="재무 결산 기준을 알려줘",
        requested_graph_id=None,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="knowledge-scope",
    )

    assert result == KnowledgeGraphChatScope(
        graph_id=GRAPH_B_ID,
        release_id=RELEASE_B_ID,
        policy_id=POLICY_B_ID,
        policy_version=1,
        policy_hash=high.delivery_policy.content_hash() if high.delivery_policy is not None else "",
        domain_id=DOMAIN_ID,
        classification=Classification.INTERNAL,
    )
    repository.list_chat_candidates.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        clearance=int(Classification.INTERNAL),
        allowed_domain_ids=frozenset({DOMAIN_ID}),
        requested_graph_id=None,
        normalized_question="재무 결산 기준을 알려줘",
        limit=2,
    )


@pytest.mark.asyncio
async def test_graph_scope_refuses_an_ambiguous_top_rank() -> None:
    first = _asset(
        graph_id=GRAPH_A_ID,
        release_id=RELEASE_A_ID,
        policy=_policy(
            graph_id=GRAPH_A_ID,
            policy_id=POLICY_A_ID,
            priority=200,
            any_terms=("재무",),
        ),
    )
    second = _asset(
        graph_id=GRAPH_B_ID,
        release_id=RELEASE_B_ID,
        policy=_policy(
            graph_id=GRAPH_B_ID,
            policy_id=POLICY_B_ID,
            priority=200,
            any_terms=("결산",),
        ),
    )
    repository = SimpleNamespace(
        list_chat_candidates=AsyncMock(
            return_value=(_chat_candidate(first), _chat_candidate(second))
        )
    )
    service = KnowledgeGraphScopeService(
        repository=cast(KnowledgeAssetRepository, repository),
        authorization=_authorization(),
    )

    result = await service.resolve_graph_scope(
        workspace_id=WORKSPACE_ID,
        subject=_subject(allowed_actions=frozenset({Action.KG_READ})),
        question="재무 결산",
        requested_graph_id=None,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="knowledge-scope-tie",
    )

    assert result is None


@pytest.mark.asyncio
async def test_delivery_policy_save_normalizes_terms_after_exact_asset_authorization() -> None:
    stored = _policy(
        graph_id=GRAPH_A_ID,
        policy_id=POLICY_A_ID,
        priority=300,
        any_terms=("재무",),
        excluded_terms=("인사",),
    )
    asset = _asset(
        graph_id=GRAPH_A_ID,
        release_id=RELEASE_A_ID,
        policy=stored,
    )
    repository = SimpleNamespace(
        get_asset=AsyncMock(return_value=asset),
        save_delivery_policy=AsyncMock(return_value=stored),
    )
    service = KnowledgeAssetService(
        repository=cast(KnowledgeAssetRepository, repository),
        authorization=_authorization(),
    )

    result = await service.save_delivery_policy(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_A_ID,
        subject=_subject(allowed_actions=frozenset({Action.KG_EDIT})),
        api_enabled=False,
        chat_enabled=True,
        priority=300,
        match_any_terms=(" 재무 ", "재무"),
        match_all_terms=(),
        excluded_terms=(" 인사 ",),
        expected_version=1,
        idempotency_key="knowledge-delivery-policy",
        request_hash="hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="knowledge-policy-save",
    )

    assert result == stored
    repository.save_delivery_policy.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_A_ID,
        actor_id=SUBJECT_ID,
        api_enabled=False,
        chat_enabled=True,
        priority=300,
        match_any_terms=("재무",),
        match_all_terms=(),
        excluded_terms=("인사",),
        expected_version=1,
        idempotency_key="knowledge-delivery-policy",
        request_hash="hash",
    )


@pytest.mark.asyncio
async def test_version_history_requires_the_same_asset_scope_before_repository_read() -> None:
    policy = _policy(
        graph_id=GRAPH_A_ID,
        policy_id=POLICY_A_ID,
        priority=100,
        any_terms=("재무",),
    )
    asset = _asset(
        graph_id=GRAPH_A_ID,
        release_id=RELEASE_A_ID,
        policy=policy,
    )
    page = KnowledgeAssetVersionPage(items=(), next_cursor=None)
    repository = SimpleNamespace(
        get_asset=AsyncMock(return_value=asset),
        list_version_events=AsyncMock(return_value=page),
    )
    service = KnowledgeAssetService(
        repository=cast(KnowledgeAssetRepository, repository),
        authorization=_authorization(),
    )

    result = await service.list_versions(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_A_ID,
        subject=_subject(allowed_actions=frozenset({Action.KG_READ})),
        cursor=None,
        limit=50,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="knowledge-version-history",
    )

    assert result is page
    repository.list_version_events.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_A_ID,
        cursor=None,
        limit=50,
    )
