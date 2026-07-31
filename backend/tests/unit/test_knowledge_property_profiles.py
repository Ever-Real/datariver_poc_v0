from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from datariver.application.knowledge_property_profiles import (
    KnowledgePropertyProfileRepository,
    KnowledgePropertyProfileService,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError, ValidationError
from datariver.domain.knowledge_property_profiles import (
    KnowledgePropertyProfile,
    KnowledgePropertyTarget,
    PropertyProfileLifecycle,
    validate_property_profile_values,
)

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2")
DOMAIN_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3")
GRAPH_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b4")
RELEASE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b5")
VERSION_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b6")
ELEMENT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b7")
PROFILE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b8")
NOW = datetime(2026, 7, 31, 1, 2, 3, tzinfo=UTC)


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


def _target() -> KnowledgePropertyTarget:
    return KnowledgePropertyTarget(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        graph_name="고객 지식 그래프",
        studio_release_id=RELEASE_ID,
        release_no=3,
        ontology_version_id=VERSION_ID,
        ontology_element_id=ELEMENT_ID,
        stable_property_id="property.customer.name",
        property_name="고객명",
        owner_class_id="class.customer",
        data_type="STRING",
        property_urn=f"urn:uuid:{ELEMENT_ID}",
        classification=int(Classification.INTERNAL),
        domain_id=DOMAIN_ID,
    )


def _profile() -> KnowledgePropertyProfile:
    return KnowledgePropertyProfile(
        profile_id=PROFILE_ID,
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        studio_release_id=RELEASE_ID,
        ontology_version_id=VERSION_ID,
        ontology_element_id=ELEMENT_ID,
        stable_property_id="property.customer.name",
        description="고객의 정식 명칭",
        unit=None,
        synonyms=("고객명", "Customer name"),
        lifecycle=PropertyProfileLifecycle.ACTIVE,
        created_by=SUBJECT_ID,
        updated_by=SUBJECT_ID,
        archived_by=None,
        created_at=NOW,
        updated_at=NOW,
        archived_at=None,
        version=1,
    )


def _subject(*, allowed_domains: frozenset[UUID]) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_domain_ids=allowed_domains,
        allowed_actions=frozenset({Action.KG_READ, Action.KG_EDIT}),
    )


def _service(repository: object) -> KnowledgePropertyProfileService:
    return KnowledgePropertyProfileService(
        repository=cast(KnowledgePropertyProfileRepository, repository),
        authorization=AuthorizationService(decision_writer=MemoryDecisionWriter()),
    )


def test_property_profile_values_are_unicode_normalized_and_casefold_deduplicated() -> None:
    description, unit, synonyms = validate_property_profile_values(
        description="  고객의 정식 명칭  ",
        unit=" 명 ",
        synonyms=("고객명", "Customer", "customer"),
    )

    assert description == "고객의 정식 명칭"
    assert unit == "명"
    assert synonyms == ("고객명", "Customer")

    with pytest.raises(ValidationError, match="at least one managed value"):
        validate_property_profile_values(description=" ", unit=None, synonyms=())

    with pytest.raises(ValidationError, match="cannot be blank"):
        validate_property_profile_values(description=None, unit=None, synonyms=(" ",))

    with pytest.raises(ValidationError, match="unit is invalid"):
        validate_property_profile_values(description=None, unit="kg\nDROP", synonyms=())

    multiline_description, _, _ = validate_property_profile_values(
        description="첫 줄\n둘째 줄",
        unit=None,
        synonyms=(),
    )
    assert multiline_description == "첫 줄\n둘째 줄"


@pytest.mark.asyncio
async def test_create_profile_authorizes_the_exact_graph_and_persists_normalized_values() -> None:
    repository = SimpleNamespace(
        get_target=AsyncMock(return_value=_target()),
        create_profile=AsyncMock(return_value=_profile()),
    )
    environment = EnvironmentAttributes(requested_at=NOW)

    result = await _service(repository).create_profile(
        workspace_id=WORKSPACE_ID,
        subject=_subject(allowed_domains=frozenset({DOMAIN_ID})),
        ontology_element_id=ELEMENT_ID,
        description="  고객의 정식 명칭 ",
        unit=None,
        synonyms=("고객명", "Customer", "customer"),
        idempotency_key="knowledge-profile-create",
        request_hash="hash",
        environment=environment,
        request_id="request",
    )

    assert result == _profile()
    repository.create_profile.assert_awaited_once_with(
        target=_target(),
        actor_id=SUBJECT_ID,
        description="고객의 정식 명칭",
        unit=None,
        synonyms=("고객명", "Customer"),
        idempotency_key="knowledge-profile-create",
        request_hash="hash",
    )


@pytest.mark.asyncio
async def test_profile_mutation_is_denied_outside_the_graph_domain() -> None:
    repository = SimpleNamespace(
        get_target=AsyncMock(return_value=_target()),
        create_profile=AsyncMock(),
    )

    with pytest.raises(ForbiddenError):
        await _service(repository).create_profile(
            workspace_id=WORKSPACE_ID,
            subject=_subject(allowed_domains=frozenset()),
            ontology_element_id=ELEMENT_ID,
            description="고객의 정식 명칭",
            unit=None,
            synonyms=(),
            idempotency_key="knowledge-profile-denied",
            request_hash="hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    repository.create_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_list_passes_the_callers_clearance_and_domain_scope() -> None:
    repository = SimpleNamespace(list_items=AsyncMock(return_value=()))
    subject = _subject(allowed_domains=frozenset({DOMAIN_ID}))

    result = await _service(repository).list_items(
        workspace_id=WORKSPACE_ID,
        subject=subject,
        query="  고객명 ",
        limit=100,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result == ()
    repository.list_items.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        clearance=int(Classification.INTERNAL),
        allowed_domain_ids=frozenset({DOMAIN_ID}),
        query="고객명",
        limit=100,
    )
