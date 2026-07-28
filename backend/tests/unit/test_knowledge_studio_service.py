from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from datariver.application.dto import KnowledgeStudioDomainOption, KnowledgeStudioDraftRecord
from datariver.application.ports import KnowledgeStudioStore
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2")
DOMAIN_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3")
DRAFT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b0")
NOW = datetime(2026, 7, 28, 1, 2, 3, tzinfo=UTC)


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


def subject(*, allowed_domains: frozenset[UUID]) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.RESTRICTED,
        allowed_domain_ids=allowed_domains,
        allowed_actions=frozenset({Action.KG_CREATE, Action.KG_READ, Action.KG_EDIT}),
    )


def draft() -> KnowledgeStudioDraftRecord:
    return KnowledgeStudioDraftRecord(
        draft_id=DRAFT_ID,
        workspace_id=WORKSPACE_ID,
        author_id=SUBJECT_ID,
        kind="CREATE",
        state="DRAFT",
        current_step="BASIC",
        name="반도체 소재 그래프",
        endpoint_alias="semiconductor_materials",
        domain_id=DOMAIN_ID,
        domain_source_version="domain-v3",
        classification=Classification.INTERNAL,
        base_graph_id=None,
        base_ontology_version_id=None,
        base_release_id=None,
        last_autosaved_at=NOW,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def service(store: object) -> KnowledgeStudioService:
    return KnowledgeStudioService(
        store=cast(KnowledgeStudioStore, store),
        authorization=AuthorizationService(decision_writer=MemoryDecisionWriter()),
    )


@pytest.mark.asyncio
async def test_domain_picker_applies_nonpublic_subject_domain_scope() -> None:
    option = KnowledgeStudioDomainOption(
        domain_id=DOMAIN_ID,
        display_name="반도체",
        source_version="domain-v3",
    )
    store = SimpleNamespace(list_domains=AsyncMock(return_value=(option,)))

    values = await service(store).list_domains(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        classification=Classification.INTERNAL,
        query=None,
        limit=50,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert values == (option,)
    store.list_domains.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        allowed_domain_ids=frozenset({DOMAIN_ID}),
        query=None,
        limit=50,
    )


@pytest.mark.asyncio
async def test_create_rejects_a_nonpublic_domain_outside_subject_scope() -> None:
    store = SimpleNamespace(create_draft=AsyncMock(return_value=draft()))

    with pytest.raises(ForbiddenError):
        await service(store).create_draft(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset()),
            name="반도체 소재 그래프",
            endpoint_alias="semiconductor_materials",
            domain_id=DOMAIN_ID,
            domain_source_version="domain-v3",
            classification=Classification.INTERNAL,
            idempotency_key="idempotency-key",
            request_hash="request-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.create_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_autosave_authorizes_the_target_domain_and_passes_the_version_fence() -> None:
    current = draft()
    updated = replace(current, version=2)
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current),
        autosave_draft=AsyncMock(return_value=updated),
    )

    result = await service(store).autosave_draft(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        draft_id=DRAFT_ID,
        name=current.name,
        endpoint_alias=current.endpoint_alias,
        domain_id=DOMAIN_ID,
        domain_source_version=current.domain_source_version,
        classification=Classification.INTERNAL,
        expected_version=1,
        idempotency_key="idempotency-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.version == 2
    store.autosave_draft.assert_awaited_once()
