from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from datariver.application.dto import (
    KnowledgeGraphRecord,
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioIngestionJobRecord,
    KnowledgeStudioManagedDomainRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioSourceDataset,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioSourcePage,
    KnowledgeStudioTBoxBlockRecord,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioTBoxRecord,
)
from datariver.application.knowledge_studio_ingestion_ports import (
    KnowledgeStudioIngestionSourceResolver,
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
from datariver.domain.common import ConflictError, ForbiddenError, NotFoundError, ValidationError
from datariver.domain.knowledge_studio import (
    TBoxElementInput,
    TBoxElementKind,
    TBoxMergeStrategy,
    TBoxOperationInput,
    TBoxOperationKind,
    TBoxProposalMode,
)
from datariver.domain.knowledge_studio_ingestion import StudioSourceProfilePin

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
FIRST_BLOCK_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c0")
SECOND_BLOCK_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c1")


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
        endpoint_aliases=("semiconductor_materials",),
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


def service(
    store: object,
    *,
    sources: object | None = None,
    ingestion_sources: object | None = None,
) -> KnowledgeStudioService:
    return KnowledgeStudioService(
        store=cast(KnowledgeStudioStore, store),
        authorization=AuthorizationService(decision_writer=MemoryDecisionWriter()),
        sources=(cast(KnowledgeStudioSourceReader, sources) if sources is not None else None),
        ingestion_sources=(
            cast(KnowledgeStudioIngestionSourceResolver, ingestion_sources)
            if ingestion_sources is not None
            else None
        ),
    )


def tbox(*, vector_index_enabled: bool) -> KnowledgeStudioTBoxRecord:
    current = abox()
    elements = tuple(
        replace(
            item,
            block_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c0"),
            vector_index_enabled=(vector_index_enabled if item.kind == "PROPERTY" else False),
        )
        for item in current.tbox_elements
    )
    return KnowledgeStudioTBoxRecord(
        draft=current.draft,
        blocks=(
            KnowledgeStudioTBoxBlockRecord(
                block_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c0"),
                kind="DIRECT",
                title="직접 정의",
                weight=50,
                ordinal=0,
                collapsed=False,
                version=1,
                source_reference=None,
                elements=elements,
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
    )


def layered_tbox() -> KnowledgeStudioTBoxRecord:
    asset = KnowledgeStudioTBoxElementRecord(
        stable_element_id="class.asset",
        kind="CLASS",
        canonical_name="Asset",
        display_name="Asset",
        parent_stable_element_id=None,
        source_stable_element_id=None,
        target_stable_element_id=None,
        data_type=None,
        nullable=None,
        ordinal=0,
        version=1,
        block_id=FIRST_BLOCK_ID,
        locked_by_later_block=True,
    )
    dataset = KnowledgeStudioTBoxElementRecord(
        stable_element_id="class.dataset",
        kind="CLASS",
        canonical_name="Dataset",
        display_name="Dataset",
        parent_stable_element_id=asset.stable_element_id,
        source_stable_element_id=None,
        target_stable_element_id=None,
        data_type=None,
        nullable=None,
        ordinal=1,
        version=1,
        block_id=SECOND_BLOCK_ID,
    )
    return KnowledgeStudioTBoxRecord(
        draft=replace(draft(), current_step="TBOX", version=4),
        blocks=(
            KnowledgeStudioTBoxBlockRecord(
                block_id=FIRST_BLOCK_ID,
                kind="DIRECT",
                title="Core",
                weight=50,
                ordinal=0,
                collapsed=False,
                version=1,
                source_reference=None,
                elements=(asset,),
                created_at=NOW,
                updated_at=NOW,
            ),
            KnowledgeStudioTBoxBlockRecord(
                block_id=SECOND_BLOCK_ID,
                kind="DIRECT",
                title="Catalog",
                weight=60,
                ordinal=1,
                collapsed=False,
                version=1,
                source_reference=None,
                elements=(dataset,),
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
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


def test_keep_original_rewires_nonconflicting_proposal_dependants() -> None:
    original = TBoxElementInput(
        stable_element_id="class:human-document",
        kind=TBoxElementKind.CLASS,
        canonical_name="Document",
        display_name="Human Document",
    )
    proposed_class = TBoxElementInput(
        stable_element_id="class:model-document",
        kind=TBoxElementKind.CLASS,
        canonical_name="Document",
        display_name="Model Document",
    )
    proposed_property = TBoxElementInput(
        stable_element_id="property:model-description",
        kind=TBoxElementKind.PROPERTY,
        canonical_name="description",
        display_name="Description",
        parent_stable_element_id=proposed_class.stable_element_id,
        data_type="TEXT",
        nullable=True,
        vector_index_enabled=True,
    )
    conflicts = KnowledgeStudioService._proposal_conflicts(
        current=(original,),
        proposed=(proposed_class, proposed_property),
    )

    accepted = KnowledgeStudioService._resolve_proposal_elements(
        current=(original,),
        proposed=(proposed_class, proposed_property),
        conflicts=conflicts,
        merge_strategy=TBoxMergeStrategy.KEEP_ORIGINAL,
        resolution_by_conflict={},
    )

    assert accepted == (
        replace(
            proposed_property,
            parent_stable_element_id=original.stable_element_id,
        ),
    )


def test_proposal_integrity_materializes_only_the_hierarchy_default() -> None:
    parent = TBoxElementInput(
        stable_element_id="class.asset",
        kind=TBoxElementKind.CLASS,
        canonical_name="Asset",
        display_name="Asset",
    )
    child = TBoxElementInput(
        stable_element_id="class.dataset",
        kind=TBoxElementKind.CLASS,
        canonical_name="Dataset",
        display_name="Dataset",
        parent_stable_element_id=parent.stable_element_id,
    )

    validated, corrected = KnowledgeStudioService._validate_proposal_integrity(
        current=(parent,),
        proposed=(child,),
    )

    assert corrected == 1
    assert validated[0].hierarchy_relation == "SUBCLASS_OF"


def test_proposal_integrity_rejects_an_unknown_class_reference() -> None:
    invalid = TBoxElementInput(
        stable_element_id="property.ghost.name",
        kind=TBoxElementKind.PROPERTY,
        canonical_name="name",
        display_name="Name",
        parent_stable_element_id="class.ghost",
        data_type="TEXT",
        nullable=True,
    )

    with pytest.raises(ValidationError, match="unknown Class"):
        KnowledgeStudioService._validate_proposal_integrity(
            current=(),
            proposed=(invalid,),
        )


def test_proposal_element_override_accepts_unicode_name_and_property_type() -> None:
    proposed = TBoxElementInput(
        stable_element_id="property.employee.name",
        kind=TBoxElementKind.PROPERTY,
        canonical_name="employeeName",
        display_name="Employee name",
        parent_stable_element_id="class.employee",
        data_type="STRING",
        nullable=True,
    )

    updated = KnowledgeStudioService._override_proposal_element(
        proposed,
        {
            "stable_element_id": proposed.stable_element_id,
            "canonical_name": "임직원명",
            "display_name": "임직원 이름",
            "data_type": "TEXT",
        },
    )

    assert updated.canonical_name == "임직원명"
    assert updated.display_name == "임직원 이름"
    assert updated.data_type == "TEXT"


def test_proposal_element_override_rejects_data_type_for_class() -> None:
    proposed = TBoxElementInput(
        stable_element_id="class.employee",
        kind=TBoxElementKind.CLASS,
        canonical_name="Employee",
        display_name="Employee",
    )

    with pytest.raises(ValidationError, match="Only a proposed Property"):
        KnowledgeStudioService._override_proposal_element(
            proposed,
            {
                "stable_element_id": proposed.stable_element_id,
                "canonical_name": proposed.canonical_name,
                "display_name": proposed.display_name,
                "data_type": "TEXT",
            },
        )


def test_proposal_candidate_cannot_rewrite_a_later_referenced_class() -> None:
    current = layered_tbox()
    first = tuple(
        replace(
            KnowledgeStudioService._tbox_input(item),
            display_name="Changed Asset",
        )
        for item in current.blocks[0].elements
    )
    second = tuple(KnowledgeStudioService._tbox_input(item) for item in current.blocks[1].elements)

    with pytest.raises(ConflictError, match="locked"):
        KnowledgeStudioService._validate_tbox_layer_dependencies(
            record=current,
            elements_by_block=(
                (FIRST_BLOCK_ID, first),
                (SECOND_BLOCK_ID, second),
            ),
        )


@pytest.mark.asyncio
async def test_later_block_reference_locks_earlier_class_mutations() -> None:
    current = layered_tbox()
    store = SimpleNamespace(
        get_tbox=AsyncMock(return_value=current),
        save_tbox_block_elements=AsyncMock(),
    )

    with pytest.raises(ConflictError, match="later T-Box block references"):
        await service(store).apply_tbox_operations(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            block_id=FIRST_BLOCK_ID,
            operations=(
                TBoxOperationInput(
                    operation=TBoxOperationKind.DELETE_ELEMENT,
                    stable_element_id="class.asset",
                ),
            ),
            expected_version=4,
            idempotency_key="delete-locked-class",
            request_hash="delete-locked-class-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    with pytest.raises(ConflictError, match="Property's Class"):
        await service(store).apply_tbox_operations(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            block_id=FIRST_BLOCK_ID,
            operations=(
                TBoxOperationInput(
                    operation=TBoxOperationKind.UPSERT_ELEMENT,
                    stable_element_id="property.asset.description",
                    element=TBoxElementInput(
                        stable_element_id="property.asset.description",
                        kind=TBoxElementKind.PROPERTY,
                        canonical_name="description",
                        display_name="Description",
                        parent_stable_element_id="class.asset",
                        data_type="TEXT",
                        nullable=True,
                    ),
                ),
            ),
            expected_version=4,
            idempotency_key="modify-locked-class-property",
            request_hash="modify-locked-class-property-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.save_tbox_block_elements.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_block_can_reference_an_earlier_class() -> None:
    current = layered_tbox()
    stored = replace(current, draft=replace(current.draft, version=5))
    store = SimpleNamespace(
        get_tbox=AsyncMock(return_value=current),
        save_tbox_block_elements=AsyncMock(return_value=stored),
    )
    table = TBoxElementInput(
        stable_element_id="class.table",
        kind=TBoxElementKind.CLASS,
        canonical_name="Table",
        display_name="Table",
        parent_stable_element_id="class.asset",
    )

    with pytest.raises(ConflictError, match="same block"):
        await service(store).apply_tbox_operations(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            block_id=SECOND_BLOCK_ID,
            operations=(
                TBoxOperationInput(
                    operation=TBoxOperationKind.UPSERT_ELEMENT,
                    stable_element_id="property.asset.description",
                    element=TBoxElementInput(
                        stable_element_id="property.asset.description",
                        kind=TBoxElementKind.PROPERTY,
                        canonical_name="description",
                        display_name="Description",
                        parent_stable_element_id="class.asset",
                        data_type="TEXT",
                        nullable=True,
                    ),
                ),
            ),
            expected_version=4,
            idempotency_key="cross-block-property",
            request_hash="cross-block-property-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    result = await service(store).apply_tbox_operations(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        draft_id=DRAFT_ID,
        block_id=SECOND_BLOCK_ID,
        operations=(
            TBoxOperationInput(
                operation=TBoxOperationKind.UPSERT_ELEMENT,
                stable_element_id=table.stable_element_id,
                element=table,
            ),
        ),
        expected_version=4,
        idempotency_key="reference-earlier-class",
        request_hash="reference-earlier-class-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.draft.version == 5
    store.save_tbox_block_elements.assert_awaited_once()
    stored_blocks = store.save_tbox_block_elements.await_args.kwargs["elements_by_block"]
    assert table in stored_blocks[1][1]


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
        creator_id=SUBJECT_ID,
        query=None,
        limit=50,
    )


@pytest.mark.asyncio
async def test_knowledge_author_can_create_a_managed_domain_without_admin_manage() -> None:
    created = KnowledgeStudioManagedDomainRecord(
        domain_id=DOMAIN_ID,
        workspace_id=WORKSPACE_ID,
        display_name="반도체",
        source_version="domain-v1",
        created_by=SUBJECT_ID,
        asset_count=0,
        lifecycle="ACTIVE",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    store = SimpleNamespace(create_managed_domain=AsyncMock(return_value=created))

    result = await service(store).create_managed_domain(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset()),
        display_name="반도체",
        idempotency_key="create-domain",
        request_hash="create-domain-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="create-domain-request",
    )

    assert result == created
    store.create_managed_domain.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        actor_id=SUBJECT_ID,
        display_name="반도체",
        idempotency_key="create-domain",
        request_hash="create-domain-hash",
    )


@pytest.mark.asyncio
async def test_edit_entry_reuses_or_creates_the_authorized_asset_draft() -> None:
    graph = KnowledgeGraphRecord(
        graph_id=GRAPH_ID,
        workspace_id=WORKSPACE_ID,
        slug="semiconductor-materials",
        name="반도체 소재 그래프",
        graph_type="DOMAIN",
        status="PUBLISHED",
        classification=Classification.INTERNAL,
        active_release_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b9"),
        version=3,
        domain_id=DOMAIN_ID,
        domain_source_version="domain-v3",
    )
    edit_draft = replace(
        draft(),
        kind="EDIT",
        base_graph_id=GRAPH_ID,
        base_ontology_version_id=ONTOLOGY_VERSION_ID,
        base_release_id=graph.active_release_id,
    )
    store = SimpleNamespace(
        get_edit_graph=AsyncMock(return_value=graph),
        create_edit_draft=AsyncMock(return_value=edit_draft),
    )

    result = await service(store).create_edit_draft(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        graph_id=GRAPH_ID,
        idempotency_key="edit-idempotency-key",
        request_hash="e" * 64,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="edit-request",
    )

    assert result.kind == "EDIT"
    assert result.base_graph_id == GRAPH_ID
    store.get_edit_graph.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        clearance=int(Classification.RESTRICTED),
    )
    store.create_edit_draft.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        author_id=SUBJECT_ID,
        graph_id=GRAPH_ID,
        idempotency_key="edit-idempotency-key",
        request_hash="e" * 64,
    )


@pytest.mark.asyncio
async def test_resumable_draft_is_author_scoped_and_reauthorized_for_edit() -> None:
    current = draft()
    store = SimpleNamespace(
        get_owned_live_draft_by_endpoint_alias=AsyncMock(return_value=current),
    )

    result = await service(store).get_resumable_draft(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        endpoint_alias=current.endpoint_alias,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="resume-request",
    )

    assert result == current
    store.get_owned_live_draft_by_endpoint_alias.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        author_id=SUBJECT_ID,
        endpoint_alias=current.endpoint_alias,
    )


@pytest.mark.asyncio
async def test_resumable_draft_does_not_disclose_another_author_or_graph_alias() -> None:
    store = SimpleNamespace(
        get_owned_live_draft_by_endpoint_alias=AsyncMock(return_value=None),
    )

    with pytest.raises(NotFoundError, match="resumable"):
        await service(store).get_resumable_draft(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            endpoint_alias="another_author_alias",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="resume-missing-request",
        )


@pytest.mark.asyncio
async def test_create_rejects_a_nonpublic_domain_outside_subject_scope() -> None:
    store = SimpleNamespace(
        create_draft=AsyncMock(return_value=draft()),
        is_managed_domain_creator=AsyncMock(return_value=False),
    )

    with pytest.raises(ForbiddenError):
        await service(store).create_draft(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset()),
            name="반도체 소재 그래프",
            endpoint_alias="semiconductor_materials",
            endpoint_aliases=("semiconductor_materials",),
            domain_id=DOMAIN_ID,
            domain_source_version="domain-v3",
            classification=Classification.INTERNAL,
            idempotency_key="idempotency-key",
            request_hash="request-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.create_draft.assert_not_awaited()
    store.is_managed_domain_creator.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        domain_id=DOMAIN_ID,
        creator_id=SUBJECT_ID,
        source_version="domain-v3",
    )


@pytest.mark.asyncio
async def test_create_allows_the_author_exact_creator_managed_domain() -> None:
    current = draft()
    store = SimpleNamespace(
        create_draft=AsyncMock(return_value=current),
        is_managed_domain_creator=AsyncMock(return_value=True),
    )

    result = await service(store).create_draft(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset()),
        name=current.name,
        endpoint_alias=current.endpoint_alias,
        endpoint_aliases=current.endpoint_aliases,
        domain_id=current.domain_id,
        domain_source_version=current.domain_source_version,
        classification=current.classification,
        idempotency_key="creator-domain-draft",
        request_hash="creator-domain-draft-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="creator-domain-draft-request",
    )

    assert result is current
    store.create_draft.assert_awaited_once()


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
        endpoint_aliases=current.endpoint_aliases,
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
async def test_tbox_catalog_search_preserves_source_policy_scope() -> None:
    current = replace(draft(), current_step="TBOX")
    page = KnowledgeStudioSourcePage(items=(source_detail().dataset,), next_cursor=None)
    sources = SimpleNamespace(search_datasets=AsyncMock(return_value=page))
    store = SimpleNamespace(get_draft=AsyncMock(return_value=current))

    result = await service(store, sources=sources).search_tbox_catalog_sources(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        draft_id=DRAFT_ID,
        query="employee",
        cursor=None,
        limit=25,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
        domain=None,
        search_fields=None,
    )

    assert result == page
    sources.search_datasets.assert_awaited_once_with(
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        maximum_classification=Classification.INTERNAL,
        query="employee",
        cursor=None,
        limit=25,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
        domain=None,
        search_fields=None,
    )

    store.get_draft.return_value = draft()
    with pytest.raises(ConflictError, match="Open Graph Builder"):
        await service(store, sources=sources).search_tbox_catalog_sources(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            query="employee",
            cursor=None,
            limit=25,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )


@pytest.mark.asyncio
async def test_tbox_catalog_proposal_rejects_a_field_outside_the_exact_source() -> None:
    current = replace(draft(), current_step="TBOX")
    sources = SimpleNamespace(get_dataset=AsyncMock(return_value=source_detail()))
    store = SimpleNamespace(get_draft=AsyncMock(return_value=current))

    with pytest.raises(ValidationError, match="authorized source version"):
        await service(store, sources=sources).create_tbox_catalog_proposal(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            source_asset_id=SOURCE_ASSET_ID,
            selected_field_paths=("not_a_real_field",),
            target_block_id=FIRST_BLOCK_ID,
            mode=TBoxProposalMode.MERGE_INTO_CURRENT,
            expected_version=1,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="catalog-proposal",
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
async def test_ingestion_without_vector_targets_does_not_require_embedding_runtime() -> None:
    published = replace(
        abox().draft,
        state="PUBLISHED",
        materialized_graph_id=GRAPH_ID,
        materialized_ontology_version_id=ONTOLOGY_VERSION_ID,
        published_studio_release_id=STUDIO_RELEASE_ID,
    )
    current = replace(tbox(vector_index_enabled=False), draft=published)
    current_abox = replace(
        abox(),
        draft=published,
        bindings=(
            cast(
                KnowledgeStudioBindingRecord,
                SimpleNamespace(
                    source_asset_id=SOURCE_ASSET_ID,
                    source_version="source-v1",
                    projection_source_version="projection-v3",
                ),
            ),
        ),
    )
    pin = StudioSourceProfilePin(
        workspace_id=WORKSPACE_ID,
        asset_id=SOURCE_ASSET_ID,
        source_version="source-v1",
        projection_source_version="projection-v3",
        connection_profile_id="catalog-primary",
        connection_profile_version=3,
        connection_profile_hash="a" * 64,
    )
    resolver = SimpleNamespace(
        manifest_id="studio-sources",
        manifest_version=2,
        manifest_hash="b" * 64,
        resolve_pin=lambda **_: pin,
    )
    queued = cast(
        KnowledgeStudioIngestionJobRecord,
        SimpleNamespace(state="PENDING"),
    )
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current.draft),
        get_tbox=AsyncMock(return_value=current),
        get_abox=AsyncMock(return_value=current_abox),
        create_ingestion_job=AsyncMock(return_value=queued),
    )

    result = await service(store, ingestion_sources=resolver).create_ingestion_job(
        workspace_id=WORKSPACE_ID,
        subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
        draft_id=DRAFT_ID,
        expected_version=1,
        idempotency_key="ingestion-no-vector",
        request_hash="ingestion-no-vector-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result is queued
    store.create_ingestion_job.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        author_id=SUBJECT_ID,
        draft_id=DRAFT_ID,
        expected_version=1,
        embedding_binding=None,
        manifest_id="studio-sources",
        manifest_version=2,
        manifest_hash="b" * 64,
        source_profile_pins=(pin,),
        idempotency_key="ingestion-no-vector",
        request_hash="ingestion-no-vector-hash",
    )


@pytest.mark.asyncio
async def test_ingestion_rejects_an_unpublished_studio_draft() -> None:
    current = tbox(vector_index_enabled=False)
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current.draft),
        create_ingestion_job=AsyncMock(),
    )

    with pytest.raises(ConflictError, match="immutable published Studio Release"):
        await service(store).create_ingestion_job(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            expected_version=1,
            idempotency_key="ingestion-draft",
            request_hash="ingestion-draft-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.create_ingestion_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_vector_target_fails_closed_without_embedding_runtime() -> None:
    published = replace(
        abox().draft,
        state="PUBLISHED",
        materialized_graph_id=GRAPH_ID,
        materialized_ontology_version_id=ONTOLOGY_VERSION_ID,
        published_studio_release_id=STUDIO_RELEASE_ID,
    )
    current = replace(tbox(vector_index_enabled=True), draft=published)
    current_abox = replace(
        abox(),
        draft=published,
        bindings=(
            cast(
                KnowledgeStudioBindingRecord,
                SimpleNamespace(
                    source_asset_id=SOURCE_ASSET_ID,
                    source_version="source-v1",
                    projection_source_version="projection-v3",
                ),
            ),
        ),
    )
    pin = StudioSourceProfilePin(
        workspace_id=WORKSPACE_ID,
        asset_id=SOURCE_ASSET_ID,
        source_version="source-v1",
        projection_source_version="projection-v3",
        connection_profile_id="catalog-primary",
        connection_profile_version=3,
        connection_profile_hash="a" * 64,
    )
    resolver = SimpleNamespace(
        manifest_id="studio-sources",
        manifest_version=2,
        manifest_hash="b" * 64,
        resolve_pin=lambda **_: pin,
    )
    store = SimpleNamespace(
        get_draft=AsyncMock(return_value=current.draft),
        get_tbox=AsyncMock(return_value=current),
        get_abox=AsyncMock(return_value=current_abox),
        create_ingestion_job=AsyncMock(),
    )

    with pytest.raises(ConflictError, match="governed embedding runtime"):
        await service(store, ingestion_sources=resolver).create_ingestion_job(
            workspace_id=WORKSPACE_ID,
            subject=subject(allowed_domains=frozenset({DOMAIN_ID})),
            draft_id=DRAFT_ID,
            expected_version=1,
            idempotency_key="ingestion-vector",
            request_hash="ingestion-vector-hash",
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    store.create_ingestion_job.assert_not_awaited()


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
