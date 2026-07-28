from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from datariver.application.dto import (
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioSourceDataset,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioTBoxElementRecord,
)
from datariver.application.ports import KnowledgeStudioSourceReader, KnowledgeStudioStore
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2")
REVIEWER_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b5")
DOMAIN_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3")
DRAFT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b0")
SOURCE_ASSET_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b4")
STUDIO_RELEASE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b6")
GRAPH_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b7")
ONTOLOGY_VERSION_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b8")
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


def subject(
    *,
    allowed_domains: frozenset[UUID],
    subject_id: UUID = SUBJECT_ID,
    allowed_actions: frozenset[Action] | None = None,
    authentication_assurance: AuthenticationAssurance = AuthenticationAssurance.UNKNOWN,
    authentication_time: datetime | None = None,
    groups: frozenset[str] = frozenset(),
    job_function: str | None = None,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=subject_id,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=groups,
        job_function=job_function,
        clearance=Classification.RESTRICTED,
        allowed_domain_ids=allowed_domains,
        allowed_actions=allowed_actions
        or frozenset({Action.KG_CREATE, Action.KG_READ, Action.KG_EDIT}),
        authentication_assurance=authentication_assurance,
        authentication_time=authentication_time,
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


def service(store: object, *, sources: object | None = None) -> KnowledgeStudioService:
    return KnowledgeStudioService(
        store=cast(KnowledgeStudioStore, store),
        authorization=AuthorizationService(decision_writer=MemoryDecisionWriter()),
        sources=(cast(KnowledgeStudioSourceReader, sources) if sources is not None else None),
    )


def abox() -> KnowledgeStudioABoxRecord:
    return KnowledgeStudioABoxRecord(
        draft=replace(draft(), current_step="ABOX"),
        tbox_elements=(
            KnowledgeStudioTBoxElementRecord(
                stable_element_id="class.employee",
                kind="CLASS",
                canonical_name="Employee",
                display_name="Employee",
                parent_stable_element_id=None,
                source_stable_element_id=None,
                target_stable_element_id=None,
                data_type=None,
                nullable=None,
                ordinal=0,
                version=3,
            ),
            KnowledgeStudioTBoxElementRecord(
                stable_element_id="property.employee.name",
                kind="PROPERTY",
                canonical_name="name",
                display_name="Name",
                parent_stable_element_id="class.employee",
                source_stable_element_id=None,
                target_stable_element_id=None,
                data_type="STRING",
                nullable=False,
                ordinal=1,
                version=3,
            ),
        ),
        bindings=(),
    )


def source_detail(
    *,
    classification: Classification = Classification.INTERNAL,
    source_version: str = "source-v1",
    stale_at: datetime | None = None,
) -> KnowledgeStudioSourceDetail:
    return KnowledgeStudioSourceDetail(
        dataset=KnowledgeStudioSourceDataset(
            asset_id=SOURCE_ASSET_ID,
            name="hr_employee",
            asset_type="DATASET",
            platform="postgres",
            database_name="hr",
            schema_name="public",
            classification=classification,
            source_version=source_version,
            projection_source_version="projection-v3",
            field_paths=("emp_id", "emp_nm"),
            fields_truncated=False,
        ),
        observed_at=NOW,
        stale_at=stale_at,
    )


def reviewer(
    *,
    assurance: AuthenticationAssurance = AuthenticationAssurance.HARDWARE_WEBAUTHN,
    job_function: str | None = None,
    groups: frozenset[str] = frozenset(),
) -> SubjectAttributes:
    return subject(
        subject_id=REVIEWER_ID,
        allowed_domains=frozenset({DOMAIN_ID}),
        allowed_actions=frozenset({Action.KG_REVIEW, Action.KG_PUBLISH}),
        authentication_assurance=assurance,
        authentication_time=NOW,
        job_function=job_function,
        groups=groups,
    )


def release() -> KnowledgeStudioReleaseRecord:
    return KnowledgeStudioReleaseRecord(
        studio_release_id=STUDIO_RELEASE_ID,
        graph_id=GRAPH_ID,
        ontology_version_id=ONTOLOGY_VERSION_ID,
        release_no=1,
        state="ACTIVE",
        contract_version="KNOWLEDGE_STUDIO_RELEASE_V1",
        contract_hash="a" * 64,
        tbox_hash="b" * 64,
        abox_hash="c" * 64,
        supersedes_studio_release_id=None,
        reviewed_by=REVIEWER_ID,
        published_by=REVIEWER_ID,
        published_at=NOW,
        archived_studio_release_id=None,
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


@pytest.mark.asyncio
async def test_abox_binding_uses_authorized_exact_source_contract_and_tbox_targets() -> None:
    current_abox = abox()
    binding_result = cast(
        KnowledgeStudioBindingRecord,
        SimpleNamespace(binding_id=UUID(int=99)),
    )
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current_abox.draft),
        get_abox=AsyncMock(return_value=current_abox),
        save_abox_binding=AsyncMock(return_value=(current_abox.draft, binding_result)),
    )
    sources = SimpleNamespace(get_dataset=AsyncMock(return_value=source_detail()))
    rules = (
        ("SUBJECT_ID", "emp_id", "class.employee"),
        ("PROPERTY", "emp_nm", "property.employee.name"),
    )

    result = await service(store, sources=sources).save_abox_binding(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        draft_id=DRAFT_ID,
        target_stable_element_id="class.employee",
        source_asset_id=SOURCE_ASSET_ID,
        source_version="source-v1",
        projection_source_version="projection-v3",
        rules=rules,
        expected_version=1,
        idempotency_key="idempotency-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result == (current_abox.draft, binding_result)
    sources.get_dataset.assert_awaited_once()
    store.save_abox_binding.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        author_id=SUBJECT_ID,
        draft_id=DRAFT_ID,
        target_stable_element_id="class.employee",
        source_asset_id=SOURCE_ASSET_ID,
        source_version="source-v1",
        projection_source_version="projection-v3",
        source_classification=int(Classification.INTERNAL),
        source_name="hr_employee",
        rules=rules,
        expected_version=1,
        idempotency_key="idempotency-key",
        request_hash="request-hash",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "source",
        "requested_version",
        "requested_projection_version",
        "error_type",
        "message",
    ),
    [
        (
            source_detail(classification=Classification.CONFIDENTIAL),
            "source-v1",
            "projection-v3",
            ConflictError,
            "classification exceeds",
        ),
        (
            source_detail(source_version="source-v2"),
            "source-v1",
            "projection-v3",
            ConflictError,
            "schema changed",
        ),
        (
            source_detail(stale_at=NOW),
            "source-v1",
            "projection-v3",
            ConflictError,
            "stale Dataset",
        ),
        (
            source_detail(),
            "source-v1",
            "projection-v2",
            ConflictError,
            "catalog projection changed",
        ),
    ],
)
async def test_abox_binding_fails_closed_for_unsafe_source_contracts(
    source: KnowledgeStudioSourceDetail,
    requested_version: str,
    requested_projection_version: str,
    error_type: type[Exception],
    message: str,
) -> None:
    current_abox = abox()
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current_abox.draft),
        get_abox=AsyncMock(return_value=current_abox),
        save_abox_binding=AsyncMock(),
    )
    sources = SimpleNamespace(get_dataset=AsyncMock(return_value=source))

    with pytest.raises(error_type, match=message):
        await service(store, sources=sources).save_abox_binding(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            target_stable_element_id="class.employee",
            source_asset_id=SOURCE_ASSET_ID,
            source_version=requested_version,
            projection_source_version=requested_projection_version,
            rules=(("SUBJECT_ID", "emp_id", "class.employee"),),
            expected_version=1,
            idempotency_key="idempotency-key",
            request_hash="request-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.save_abox_binding.assert_not_awaited()


@pytest.mark.asyncio
async def test_abox_binding_rejects_a_field_not_returned_by_the_catalog() -> None:
    current_abox = abox()
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current_abox.draft),
        get_abox=AsyncMock(return_value=current_abox),
        save_abox_binding=AsyncMock(),
    )
    sources = SimpleNamespace(get_dataset=AsyncMock(return_value=source_detail()))

    with pytest.raises(ValidationError, match="server-returned Dataset schema"):
        await service(store, sources=sources).save_abox_binding(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            target_stable_element_id="class.employee",
            source_asset_id=SOURCE_ASSET_ID,
            source_version="source-v1",
            projection_source_version="projection-v3",
            rules=(("PROPERTY", "invented_field", "property.employee.name"),),
            expected_version=1,
            idempotency_key="idempotency-key",
            request_hash="request-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.save_abox_binding.assert_not_awaited()


@pytest.mark.asyncio
async def test_abox_read_rejects_a_draft_that_has_not_advanced_to_data_enricher() -> None:
    record = replace(abox(), draft=draft())
    store = SimpleNamespace(get_abox=AsyncMock(return_value=record))

    with pytest.raises(ConflictError, match="Open Data Enricher"):
        await service(store).get_abox(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )


@pytest.mark.asyncio
async def test_author_can_submit_an_abox_draft_for_independent_review() -> None:
    current = replace(draft(), current_step="ABOX", version=7)
    submitted = replace(current, state="REVIEW", version=8)
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current),
        submit_review=AsyncMock(return_value=submitted),
    )

    result = await service(store).submit_review(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="submit-review",
        request_hash="submit-review-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.state == "REVIEW"
    store.submit_review.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        author_id=SUBJECT_ID,
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="submit-review",
        request_hash="submit-review-hash",
    )


@pytest.mark.asyncio
async def test_independent_hardware_reviewer_can_publish_exact_review_draft() -> None:
    review_draft = replace(draft(), state="REVIEW", current_step="ABOX", version=8)
    published = replace(
        review_draft,
        state="PUBLISHED",
        version=9,
        submitted_preflight_check_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b9"),
        reviewed_by=REVIEWER_ID,
        reviewed_at=NOW,
        review_reason="Mapping contract and evidence reviewed.",
        published_by=REVIEWER_ID,
        published_at=NOW,
        materialized_graph_id=GRAPH_ID,
        materialized_ontology_version_id=ONTOLOGY_VERSION_ID,
        published_studio_release_id=STUDIO_RELEASE_ID,
    )
    release_record = release()
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=review_draft),
        publish_draft=AsyncMock(return_value=(published, release_record)),
    )

    result = await service(store).publish_draft(
        workspace_id=WORKSPACE_ID,
        subject=reviewer(),
        draft_id=DRAFT_ID,
        review_reason="Mapping contract and evidence reviewed.",
        expected_version=8,
        idempotency_key="publish-review",
        request_hash="publish-review-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result == (published, release_record)
    store.publish_draft.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        actor_id=REVIEWER_ID,
        draft_id=DRAFT_ID,
        review_reason="Mapping contract and evidence reviewed.",
        expected_version=8,
        idempotency_key="publish-review",
        request_hash="publish-review-hash",
    )


@pytest.mark.asyncio
async def test_publish_fails_closed_without_phishing_resistant_assurance() -> None:
    review_draft = replace(draft(), state="REVIEW", current_step="ABOX", version=8)
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=review_draft),
        publish_draft=AsyncMock(),
    )

    with pytest.raises(ForbiddenError) as error:
        await service(store).publish_draft(
            workspace_id=WORKSPACE_ID,
            subject=reviewer(assurance=AuthenticationAssurance.OTHER_MFA),
            draft_id=DRAFT_ID,
            review_reason="Reviewed.",
            expected_version=8,
            idempotency_key="publish-review",
            request_hash="publish-review-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    assert "PHISHING_RESISTANT_AUTH_REQUIRED" in str(error.value.details)
    store.publish_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_author_and_service_accounts_cannot_publish_a_review_draft() -> None:
    review_draft = replace(draft(), state="REVIEW", current_step="ABOX", version=8)
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=review_draft),
        publish_draft=AsyncMock(),
    )

    with pytest.raises(ConflictError, match="cannot review or publish"):
        await service(store).publish_draft(
            workspace_id=WORKSPACE_ID,
            subject=subject(
                allowed_domains=frozenset({DOMAIN_ID}),
                allowed_actions=frozenset({Action.KG_REVIEW, Action.KG_PUBLISH}),
                authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                authentication_time=NOW,
            ),
            draft_id=DRAFT_ID,
            review_reason="Self review.",
            expected_version=8,
            idempotency_key="self-publish",
            request_hash="self-publish-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    with pytest.raises(ValidationError, match="independent human reviewer"):
        await service(store).publish_draft(
            workspace_id=WORKSPACE_ID,
            subject=reviewer(job_function="SERVICE_ACCOUNT"),
            draft_id=DRAFT_ID,
            review_reason="Automated review.",
            expected_version=8,
            idempotency_key="service-publish",
            request_hash="service-publish-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.publish_draft.assert_not_awaited()
