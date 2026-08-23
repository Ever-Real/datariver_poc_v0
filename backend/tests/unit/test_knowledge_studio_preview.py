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
    KnowledgeStudioDraftRecord,
    KnowledgeStudioMappingRuleRecord,
    KnowledgeStudioPreflightRecord,
    KnowledgeStudioSamplePage,
    KnowledgeStudioSourceAccess,
    KnowledgeStudioSourceDataset,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioSourceProbe,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioValidationEvidence,
)
from datariver.application.ports import (
    KnowledgeStudioSampleReader,
    KnowledgeStudioSourceReader,
    KnowledgeStudioStore,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_studio_preview import (
    KnowledgeStudioPreviewService,
    build_class_preview_graph,
)
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import PreconditionFailedError

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2")
DOMAIN_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3")
DRAFT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b0")
ASSET_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b4")
BINDING_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b5")
SOURCE_REFERENCE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b6")
PREFLIGHT_RECEIPT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b7")
NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)


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


def subject() -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.RESTRICTED,
        allowed_domain_ids=frozenset({DOMAIN_ID}),
        allowed_actions=frozenset({Action.KG_READ}),
    )


def draft(*, version: int = 7) -> KnowledgeStudioDraftRecord:
    return KnowledgeStudioDraftRecord(
        draft_id=DRAFT_ID,
        workspace_id=WORKSPACE_ID,
        author_id=SUBJECT_ID,
        kind="CREATE",
        state="DRAFT",
        current_step="ABOX",
        name="Employee graph",
        endpoint_alias="employee_graph",
        endpoint_aliases=("employee_graph",),
        domain_id=DOMAIN_ID,
        domain_source_version="domain-v1",
        classification=Classification.INTERNAL,
        base_graph_id=None,
        base_ontology_version_id=None,
        base_release_id=None,
        last_autosaved_at=NOW,
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def elements() -> tuple[KnowledgeStudioTBoxElementRecord, ...]:
    return (
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
            version=2,
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
            version=2,
        ),
    )


def binding() -> KnowledgeStudioBindingRecord:
    return KnowledgeStudioBindingRecord(
        binding_id=BINDING_ID,
        target_stable_element_id="class.employee",
        source_reference_id=SOURCE_REFERENCE_ID,
        source_asset_id=ASSET_ID,
        source_name="hr_employee",
        source_version="datahub-v4",
        projection_source_version="projection-v3",
        source_classification=Classification.INTERNAL,
        readiness="DRAFT",
        tbox_version=2,
        version=3,
        rules=(
            KnowledgeStudioMappingRuleRecord(
                rule_id=UUID(int=101),
                ordinal=0,
                method="SUBJECT_ID",
                source_field_path="emp_id",
                target_stable_element_id="class.employee",
                transform_id="IDENTITY",
                transform_version="1",
                source_unit=None,
                canonical_unit=None,
            ),
            KnowledgeStudioMappingRuleRecord(
                rule_id=UUID(int=102),
                ordinal=1,
                method="PROPERTY",
                source_field_path="emp_nm",
                target_stable_element_id="property.employee.name",
                transform_id="IDENTITY",
                transform_version="1",
                source_unit=None,
                canonical_unit=None,
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def abox(
    *, bindings: tuple[KnowledgeStudioBindingRecord, ...] | None = None
) -> KnowledgeStudioABoxRecord:
    return KnowledgeStudioABoxRecord(
        draft=draft(),
        tbox_elements=elements(),
        bindings=(binding(),) if bindings is None else bindings,
    )


def source_detail() -> KnowledgeStudioSourceDetail:
    return KnowledgeStudioSourceDetail(
        dataset=KnowledgeStudioSourceDataset(
            asset_id=ASSET_ID,
            name="hr_employee",
            asset_type="TABLE",
            platform="postgres",
            database_name="hr",
            schema_name="public",
            classification=Classification.INTERNAL,
            source_version="datahub-v4",
            projection_source_version="projection-v3",
            field_paths=("emp_id", "emp_nm"),
            fields_truncated=False,
        ),
        observed_at=NOW,
        stale_at=None,
    )


def sample_page() -> KnowledgeStudioSamplePage:
    return KnowledgeStudioSamplePage(
        source_reference_id=SOURCE_REFERENCE_ID,
        source_version="datahub-v4",
        projection_source_version="projection-v3",
        rows=(
            {"emp_id": "E-001", "emp_nm": "Kim"},
            {"emp_id": "E-002", "emp_nm": "Lee"},
        ),
        observed_at=NOW,
    )


def service(
    store: object,
    *,
    sources: object | None,
    samples: object | None,
) -> KnowledgeStudioPreviewService:
    if isinstance(store, SimpleNamespace) and not hasattr(store, "record_preflight"):

        async def record_preflight(**values: object) -> KnowledgeStudioPreflightRecord:
            return KnowledgeStudioPreflightRecord(
                status=cast(str, values["status"]),
                valid=cast(bool, values["valid"]),
                draft_version=cast(int, values["expected_version"]),
                checked_at=cast(datetime, values["checked_at"]),
                evidence=cast(
                    tuple[KnowledgeStudioValidationEvidence, ...],
                    values["evidence"],
                ),
                receipt_id=PREFLIGHT_RECEIPT_ID,
                contract_hash="a" * 64,
            )

        store.record_preflight = AsyncMock(side_effect=record_preflight)
    return KnowledgeStudioPreviewService(
        store=cast(KnowledgeStudioStore, store),
        authorization=AuthorizationService(decision_writer=MemoryDecisionWriter()),
        sources=cast(KnowledgeStudioSourceReader, sources) if sources is not None else None,
        samples=cast(KnowledgeStudioSampleReader, samples) if samples is not None else None,
    )


def test_class_preview_traverses_typed_rules_and_returns_no_cypher() -> None:
    graph, evidence = build_class_preview_graph(
        target=elements()[0],
        elements=elements(),
        binding=binding(),
        sample=sample_page(),
    )

    assert evidence == ()
    assert len(graph.nodes) == 2
    assert graph.edges == ()
    assert graph.nodes[0].identity == "E-001"
    assert graph.nodes[0].properties == {"name": "Kim"}
    assert graph.nodes[0].node_id.startswith("preview:")
    assert not hasattr(graph, "cypher")


@pytest.mark.asyncio
async def test_preview_revalidates_source_and_passes_only_persisted_fields_to_sample_reader() -> (
    None
):
    store = SimpleNamespace(get_abox=AsyncMock(return_value=abox()))
    sources = SimpleNamespace(get_dataset=AsyncMock(return_value=source_detail()))
    samples = SimpleNamespace(sample_rows=AsyncMock(return_value=sample_page()))

    result = await service(store, sources=sources, samples=samples).preview_binding(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        target_stable_element_id="class.employee",
        sample_limit=5,
        expected_version=7,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "READY"
    assert result.dry_run is True
    assert result.sample_size == 2
    request = samples.sample_rows.await_args.kwargs["source"]
    assert request.asset_id == ASSET_ID
    assert request.field_paths == ("emp_id", "emp_nm")
    assert request.limit == 5
    assert not hasattr(request, "query")


@pytest.mark.asyncio
async def test_preview_never_fabricates_rows_when_no_physical_reader_is_configured() -> None:
    store = SimpleNamespace(get_abox=AsyncMock(return_value=abox()))
    sources = SimpleNamespace(get_dataset=AsyncMock(return_value=source_detail()))

    result = await service(store, sources=sources, samples=None).preview_binding(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        target_stable_element_id="class.employee",
        sample_limit=5,
        expected_version=7,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "UNAVAILABLE"
    assert result.graph.nodes == ()
    assert result.evidence[0].code == "SOURCE_ROW_READER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_preview_rejects_a_stale_tbox_binding_before_any_source_read() -> None:
    stale_binding = replace(binding(), tbox_version=1)
    store = SimpleNamespace(get_abox=AsyncMock(return_value=abox(bindings=(stale_binding,))))
    sources = SimpleNamespace(get_dataset=AsyncMock())
    samples = SimpleNamespace(sample_rows=AsyncMock())

    result = await service(store, sources=sources, samples=samples).preview_binding(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        target_stable_element_id="class.employee",
        sample_limit=5,
        expected_version=7,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "INVALID"
    assert result.evidence[0].code == "BINDING_TBOX_STALE"
    sources.get_dataset.assert_not_awaited()
    samples.sample_rows.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_checks_required_mapping_and_batch_source_access() -> None:
    store = SimpleNamespace(get_abox=AsyncMock(return_value=abox()))
    sources = SimpleNamespace(
        validate_dataset_access=AsyncMock(
            return_value=(
                KnowledgeStudioSourceAccess(
                    asset_id=ASSET_ID,
                    classification=Classification.INTERNAL,
                    projection_source_version="projection-v3",
                ),
            )
        )
    )
    samples = SimpleNamespace(
        probe_access=AsyncMock(
            return_value=(
                KnowledgeStudioSourceProbe(
                    source_reference_id=SOURCE_REFERENCE_ID,
                    source_version="datahub-v4",
                    projection_source_version="projection-v3",
                    accessible=True,
                    observed_at=NOW,
                ),
            )
        )
    )

    result = await service(store, sources=sources, samples=samples).preflight(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="preflight-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "PASS"
    assert result.valid is True
    assert result.evidence == ()
    sources.validate_dataset_access.assert_awaited_once_with(
        subject=subject(),
        asset_ids=(ASSET_ID,),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )
    probe_sources = samples.probe_access.await_args.kwargs["sources"]
    assert len(probe_sources) == 1
    assert probe_sources[0].field_paths == ("emp_id", "emp_nm")


@pytest.mark.asyncio
async def test_preflight_returns_all_required_mapping_evidence_without_source_calls() -> None:
    store = SimpleNamespace(get_abox=AsyncMock(return_value=abox(bindings=())))
    sources = SimpleNamespace(validate_dataset_access=AsyncMock())
    samples = SimpleNamespace(probe_access=AsyncMock())

    result = await service(store, sources=sources, samples=samples).preflight(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="preflight-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "FAIL"
    assert result.valid is False
    assert [item.code for item in result.evidence] == ["REQUIRED_CLASS_UNBOUND"]
    sources.validate_dataset_access.assert_not_awaited()
    samples.probe_access.assert_not_awaited()


def test_preflight_requires_every_vector_property_to_have_a_mapping() -> None:
    class_element, property_element = elements()
    current_binding = binding()
    vector_abox = KnowledgeStudioABoxRecord(
        draft=draft(),
        tbox_elements=(
            class_element,
            replace(property_element, nullable=True, vector_index_enabled=True),
        ),
        bindings=(
            replace(
                current_binding,
                rules=tuple(rule for rule in current_binding.rules if rule.method == "SUBJECT_ID"),
            ),
        ),
    )

    evidence = KnowledgeStudioPreviewService._mapping_evidence(vector_abox)

    assert [item.code for item in evidence] == ["VECTOR_PROPERTY_UNMAPPED"]


@pytest.mark.asyncio
async def test_preflight_never_probes_a_physical_source_after_catalog_access_is_denied() -> None:
    store = SimpleNamespace(get_abox=AsyncMock(return_value=abox()))
    sources = SimpleNamespace(validate_dataset_access=AsyncMock(return_value=()))
    samples = SimpleNamespace(probe_access=AsyncMock())

    result = await service(store, sources=sources, samples=samples).preflight(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="preflight-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "FAIL"
    assert result.valid is False
    assert [item.code for item in result.evidence] == ["SOURCE_METADATA_ACCESS_INVALID"]
    samples.probe_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_etag_fails_before_any_source_read() -> None:
    store = SimpleNamespace(get_abox=AsyncMock(return_value=abox()))
    sources = SimpleNamespace(get_dataset=AsyncMock())
    samples = SimpleNamespace(sample_rows=AsyncMock())

    with pytest.raises(PreconditionFailedError):
        await service(store, sources=sources, samples=samples).preview_binding(
            workspace_id=WORKSPACE_ID,
            subject=subject(),
            draft_id=DRAFT_ID,
            target_stable_element_id="class.employee",
            sample_limit=5,
            expected_version=6,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )

    sources.get_dataset.assert_not_awaited()
    samples.sample_rows.assert_not_awaited()


def test_managed_preflight_validates_metadata_lineage_contract_exactly() -> None:
    current_abox = abox()
    managed_draft = replace(
        current_abox.draft,
        managed_intent="metadata-lineage",
        managed_graph_type="CATALOG_MIRROR",
        accepted_proposal_id="contract.semantic.metadata-lineage",
        accepted_proposal_hash="9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96",
        source_contract_hash="8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb",
        mapping_contract_hash="f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3",
        classification=Classification.INTERNAL,
    )
    dataset_class = KnowledgeStudioTBoxElementRecord(
        stable_element_id="class.dataset",
        kind="CLASS",
        canonical_name="Dataset",
        display_name="Dataset",
        parent_stable_element_id=None,
        source_stable_element_id=None,
        target_stable_element_id=None,
        data_type=None,
        nullable=None,
        ordinal=0,
        version=1,
    )
    depends_on_rel = KnowledgeStudioTBoxElementRecord(
        stable_element_id="rel.dataset_depends_on",
        kind="RELATION",
        canonical_name="DEPENDS_ON",
        display_name="Depends On",
        parent_stable_element_id=None,
        source_stable_element_id="class.dataset",
        target_stable_element_id="class.dataset",
        data_type=None,
        nullable=None,
        ordinal=1,
        version=1,
    )
    managed_abox = replace(
        current_abox,
        draft=managed_draft,
        tbox_elements=(dataset_class, depends_on_rel),
        bindings=(),
    )

    evidence = KnowledgeStudioPreviewService._managed_preflight(managed_abox)

    assert len(evidence) == 1
    assert evidence[0].severity == "INFO"
    assert evidence[0].code == "MANAGED_CONTRACT_VALID"


def test_managed_preflight_fails_with_generic_abox_bindings() -> None:
    current_abox = abox()
    managed_draft = replace(
        current_abox.draft,
        managed_intent="metadata-lineage",
        managed_graph_type="CATALOG_MIRROR",
        accepted_proposal_id="contract.semantic.metadata-lineage",
        accepted_proposal_hash="9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96",
        source_contract_hash="8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb",
        mapping_contract_hash="f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3",
        classification=Classification.INTERNAL,
    )
    managed_abox = replace(
        current_abox,
        draft=managed_draft,
        tbox_elements=(),
    )

    evidence = KnowledgeStudioPreviewService._managed_preflight(managed_abox)
    codes = [e.code for e in evidence]

    assert "UNEXPECTED_GENERIC_BINDING" in codes
    assert "TBOX_CLASSES_MISMATCH" in codes
    assert "TBOX_RELATIONS_MISMATCH" in codes


def test_managed_preflight_fails_on_missing_or_mismatched_intent_fields() -> None:
    current_abox = abox()
    managed_draft = replace(
        current_abox.draft,
        managed_intent="metadata-lineage",
        managed_graph_type="SOME_OTHER_TYPE",
        accepted_proposal_id="wrong.id",
        accepted_proposal_hash="wrong.hash",
        source_contract_hash="wrong.hash",
        mapping_contract_hash="wrong.hash",
        classification=Classification.CONFIDENTIAL,
    )
    managed_abox = replace(
        current_abox,
        draft=managed_draft,
        tbox_elements=(),
        bindings=(),
    )

    evidence = KnowledgeStudioPreviewService._managed_preflight(managed_abox)
    codes = [e.code for e in evidence]

    assert "INVALID_MANAGED_GRAPH_TYPE" in codes
    assert "INVALID_PROPOSAL_ID" in codes
    assert "INVALID_PROPOSAL_HASH" in codes
    assert "INVALID_SOURCE_HASH" in codes
    assert "INVALID_MAPPING_HASH" in codes
    assert "CLASSIFICATION_TOO_HIGH" in codes


@pytest.mark.asyncio
async def test_preflight_passes_for_valid_metadata_lineage_managed_intent() -> None:
    current_abox = abox()
    managed_draft = replace(
        current_abox.draft,
        managed_intent="metadata-lineage",
        managed_graph_type="CATALOG_MIRROR",
        accepted_proposal_id="contract.semantic.metadata-lineage",
        accepted_proposal_hash="9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96",
        source_contract_hash="8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb",
        mapping_contract_hash="f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3",
        classification=Classification.INTERNAL,
    )
    dataset_class = KnowledgeStudioTBoxElementRecord(
        stable_element_id="class.dataset",
        kind="CLASS",
        canonical_name="Dataset",
        display_name="Dataset",
        parent_stable_element_id=None,
        source_stable_element_id=None,
        target_stable_element_id=None,
        data_type=None,
        nullable=None,
        ordinal=0,
        version=1,
    )
    depends_on_rel = KnowledgeStudioTBoxElementRecord(
        stable_element_id="rel.dataset_depends_on",
        kind="RELATION",
        canonical_name="DEPENDS_ON",
        display_name="Depends On",
        parent_stable_element_id=None,
        source_stable_element_id="class.dataset",
        target_stable_element_id="class.dataset",
        data_type=None,
        nullable=None,
        ordinal=1,
        version=1,
    )
    managed_abox = replace(
        current_abox,
        draft=managed_draft,
        tbox_elements=(dataset_class, depends_on_rel),
        bindings=(),
    )
    store = SimpleNamespace(
        get_abox=AsyncMock(return_value=managed_abox),
        record_preflight=AsyncMock(
            return_value=KnowledgeStudioPreflightRecord(
                status="PASS", valid=True, evidence=(), checked_at=NOW, draft_version=7
            )
        ),
    )
    sources = SimpleNamespace(validate_dataset_access=AsyncMock())
    samples = SimpleNamespace(probe_access=AsyncMock())

    result = await service(store, sources=sources, samples=samples).preflight(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="preflight-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "PASS"
    store.record_preflight.assert_awaited_once()
    record_kwargs = store.record_preflight.await_args.kwargs
    assert record_kwargs["status"] == "PASS"
    assert record_kwargs["valid"] is True
    assert record_kwargs["evidence"][0].code == "MANAGED_CONTRACT_VALID"
    sources.validate_dataset_access.assert_not_awaited()
    samples.probe_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_passes_for_valid_data_glossary_managed_intent() -> None:
    current_abox = abox()
    managed_draft = replace(
        current_abox.draft,
        managed_intent="data-glossary",
        managed_graph_type="CURATED_KNOWLEDGE",
        accepted_proposal_id="contract.semantic.data-glossary",
        accepted_proposal_hash="670ac1d49ab091debe23bc706cc479576af226ea55d73fa5ffd2c1a4993836d1",
        source_contract_hash="12cba3de9e71c2453d94c2f625839593d627ea60f6143097a49a9d3782a089d8",
        mapping_contract_hash="ed3160311a3058f9e61bc8478b07175d96b6fe3c035b55fb4fe94455a6098e7f",
        classification=Classification.INTERNAL,
    )

    tbox_elements = [
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="class.business_term",
            kind="CLASS",
            canonical_name="BusinessTerm",
            display_name="BusinessTerm",
            parent_stable_element_id=None,
            source_stable_element_id=None,
            target_stable_element_id=None,
            data_type=None,
            nullable=None,
            ordinal=0,
            version=1,
        ),
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="class.glossary_node",
            kind="CLASS",
            canonical_name="GlossaryNode",
            display_name="GlossaryNode",
            parent_stable_element_id=None,
            source_stable_element_id=None,
            target_stable_element_id=None,
            data_type=None,
            nullable=None,
            ordinal=1,
            version=1,
        ),
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="class.table",
            kind="CLASS",
            canonical_name="Table",
            display_name="Table",
            parent_stable_element_id=None,
            source_stable_element_id=None,
            target_stable_element_id=None,
            data_type=None,
            nullable=None,
            ordinal=2,
            version=1,
        ),
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="class.column",
            kind="CLASS",
            canonical_name="Column",
            display_name="Column",
            parent_stable_element_id=None,
            source_stable_element_id=None,
            target_stable_element_id=None,
            data_type=None,
            nullable=None,
            ordinal=3,
            version=1,
        ),
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="rel.term_has_parent",
            kind="RELATION",
            canonical_name="HAS_PARENT_NODE",
            display_name="HAS_PARENT_NODE",
            parent_stable_element_id=None,
            source_stable_element_id="class.business_term",
            target_stable_element_id="class.glossary_node",
            data_type=None,
            nullable=None,
            ordinal=4,
            version=1,
        ),
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="rel.node_has_parent",
            kind="RELATION",
            canonical_name="HAS_PARENT_NODE",
            display_name="HAS_PARENT_NODE",
            parent_stable_element_id=None,
            source_stable_element_id="class.glossary_node",
            target_stable_element_id="class.glossary_node",
            data_type=None,
            nullable=None,
            ordinal=5,
            version=1,
        ),
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="rel.table_mapped_to_term",
            kind="RELATION",
            canonical_name="MAPPED_TO_TERM",
            display_name="MAPPED_TO_TERM",
            parent_stable_element_id=None,
            source_stable_element_id="class.table",
            target_stable_element_id="class.business_term",
            data_type=None,
            nullable=None,
            ordinal=6,
            version=1,
        ),
        KnowledgeStudioTBoxElementRecord(
            stable_element_id="rel.column_mapped_to_term",
            kind="RELATION",
            canonical_name="MAPPED_TO_TERM",
            display_name="MAPPED_TO_TERM",
            parent_stable_element_id=None,
            source_stable_element_id="class.column",
            target_stable_element_id="class.business_term",
            data_type=None,
            nullable=None,
            ordinal=7,
            version=1,
        ),
    ]

    managed_abox = replace(
        current_abox,
        draft=managed_draft,
        tbox_elements=tuple(tbox_elements),
        bindings=(),
    )
    store = SimpleNamespace(
        get_abox=AsyncMock(return_value=managed_abox),
        record_preflight=AsyncMock(
            return_value=KnowledgeStudioPreflightRecord(
                status="PASS", valid=True, evidence=(), checked_at=NOW, draft_version=7
            )
        ),
    )
    sources = SimpleNamespace(validate_dataset_access=AsyncMock())
    samples = SimpleNamespace(probe_access=AsyncMock())

    result = await service(store, sources=sources, samples=samples).preflight(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="preflight-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "PASS"
    store.record_preflight.assert_awaited_once()
    record_kwargs = store.record_preflight.await_args.kwargs
    assert record_kwargs["status"] == "PASS"
    assert record_kwargs["valid"] is True
    assert record_kwargs["evidence"][0].code == "MANAGED_CONTRACT_VALID"
    sources.validate_dataset_access.assert_not_awaited()
    samples.probe_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_fails_for_unknown_managed_intent() -> None:
    current_abox = abox()
    managed_draft = replace(
        current_abox.draft,
        managed_intent="some-unknown-intent",
    )
    managed_abox = replace(
        current_abox,
        draft=managed_draft,
        tbox_elements=(),
        bindings=(),
    )
    store = SimpleNamespace(
        get_abox=AsyncMock(return_value=managed_abox),
        record_preflight=AsyncMock(
            return_value=KnowledgeStudioPreflightRecord(
                status="FAIL", valid=False, evidence=(), checked_at=NOW, draft_version=7
            )
        ),
    )
    sources = SimpleNamespace(validate_dataset_access=AsyncMock())
    samples = SimpleNamespace(probe_access=AsyncMock())

    result = await service(store, sources=sources, samples=samples).preflight(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="preflight-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "FAIL"
    store.record_preflight.assert_awaited_once()
    record_kwargs = store.record_preflight.await_args.kwargs
    assert record_kwargs["status"] == "FAIL"
    assert record_kwargs["valid"] is False
    assert record_kwargs["evidence"][0].code == "UNKNOWN_MANAGED_INTENT"
    sources.validate_dataset_access.assert_not_awaited()
    samples.probe_access.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_intent", [None, ""])
async def test_preflight_fails_for_partial_managed_metadata_with_empty_intent(
    empty_intent: str | None,
) -> None:
    current_abox = abox()
    managed_draft = replace(
        current_abox.draft,
        managed_intent=empty_intent,
        managed_graph_type="CATALOG_MIRROR",  # other field present
    )
    managed_abox = replace(
        current_abox,
        draft=managed_draft,
        tbox_elements=(),
        bindings=(),
    )
    store = SimpleNamespace(
        get_abox=AsyncMock(return_value=managed_abox),
        record_preflight=AsyncMock(
            return_value=KnowledgeStudioPreflightRecord(
                status="FAIL", valid=False, evidence=(), checked_at=NOW, draft_version=7
            )
        ),
    )
    sources = SimpleNamespace(validate_dataset_access=AsyncMock())
    samples = SimpleNamespace(probe_access=AsyncMock())

    result = await service(store, sources=sources, samples=samples).preflight(
        workspace_id=WORKSPACE_ID,
        subject=subject(),
        draft_id=DRAFT_ID,
        expected_version=7,
        idempotency_key="preflight-key",
        request_hash="request-hash",
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.status == "FAIL"
    store.record_preflight.assert_awaited_once()
    record_kwargs = store.record_preflight.await_args.kwargs
    assert record_kwargs["status"] == "FAIL"
    assert record_kwargs["valid"] is False
    assert record_kwargs["evidence"][0].code == "UNKNOWN_MANAGED_INTENT"
    sources.validate_dataset_access.assert_not_awaited()
    samples.probe_access.assert_not_awaited()
