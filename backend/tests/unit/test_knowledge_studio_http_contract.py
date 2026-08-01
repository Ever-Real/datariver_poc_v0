from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from starlette.responses import Response

from datariver.application.dto import (
    KnowledgeStudioCatalogFieldMetadata,
    KnowledgeStudioSourceDataset,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioTBoxProposalRecord,
)
from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalJobRecord,
    KnowledgeStudioProposalJobResult,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio import TBoxProposalMode
from datariver.domain.knowledge_studio_proposal_jobs import (
    KnowledgeStudioProposalInputKind,
    KnowledgeStudioProposalJobStage,
    KnowledgeStudioProposalJobState,
)
from datariver.interfaces.http.routes import knowledge_studio as knowledge_studio_routes
from datariver.interfaces.http.routes.knowledge_studio import (
    _proposal_job_response,
    _proposal_response,
    _public_source_reference,
)
from datariver.interfaces.http.schemas import KnowledgeStudioTBoxProposalJobRequest


def test_tbox_proposal_response_redacts_private_object_store_coordinates() -> None:
    proposal = KnowledgeStudioTBoxProposalRecord(
        proposal_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1001"),
        draft_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1002"),
        target_block_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1003"),
        state="READY",
        mode="MERGE_INTO_CURRENT",
        merge_strategy="KEEP_ORIGINAL",
        base_draft_version=3,
        prompt="Infer a bounded T-Box.",
        elements=(),
        conflicts=(),
        model_binding={"provider": "configured"},
        source_reference={
            "contract_version": "KNOWLEDGE_STUDIO_DOCUMENT_SOURCE_V1",
            "filename": "governed.pdf",
            "content_sha256": "a" * 64,
            "bucket": "private-bucket",
            "object_key": "knowledge-studio/private/object.pdf",
        },
        error_code=None,
        version=1,
        created_at=datetime(2026, 7, 31, tzinfo=UTC),
        updated_at=datetime(2026, 7, 31, tzinfo=UTC),
        applied_at=None,
        rejected_at=None,
    )

    response = _proposal_response(proposal)

    assert response.source_reference == {
        "contract_version": "KNOWLEDGE_STUDIO_DOCUMENT_SOURCE_V1",
        "filename": "governed.pdf",
        "content_sha256": "a" * 64,
    }


def test_public_source_reference_recursively_redacts_private_coordinates() -> None:
    assert _public_source_reference(
        {
            "contract_version": "KNOWLEDGE_STUDIO_DOCUMENT_SOURCE_V1",
            "pipeline_evidence": {
                "bucket": "private-bucket",
                "object_key": "private/key",
                "content_sha256": "b" * 64,
            },
        }
    ) == {
        "contract_version": "KNOWLEDGE_STUDIO_DOCUMENT_SOURCE_V1",
        "pipeline_evidence": {"content_sha256": "b" * 64},
    }


def test_proposal_job_response_exposes_only_bounded_control_plane_state() -> None:
    now = datetime(2026, 7, 31, tzinfo=UTC)
    record = KnowledgeStudioProposalJobRecord(
        job_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1004"),
        workspace_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1005"),
        draft_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1002"),
        requested_by=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1006"),
        input_kind=KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA,
        mode=TBoxProposalMode.MERGE_INTO_CURRENT,
        target_block_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1003"),
        state=KnowledgeStudioProposalJobState.SUCCEEDED,
        stage=KnowledgeStudioProposalJobStage.COMPLETED,
        progress_percent=100,
        attempt_count=1,
        maximum_attempts=3,
        next_attempt_at=now,
        last_failure_code=None,
        version=4,
        created_at=now,
        updated_at=now,
        completed_at=now,
        result=KnowledgeStudioProposalJobResult(
            proposal_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1001"),
            evidence_hash="a" * 64,
        ),
    )

    document = _proposal_job_response(record).model_dump(mode="json")

    assert document["result_proposal_id"] == "019fa57b-52de-74c0-9f5e-06ae7b1c1001"
    serialized = str(document).lower()
    for forbidden in ("bucket", "object_key", "prompt", "excerpt", "provider_body"):
        assert forbidden not in serialized


def test_catalog_proposal_request_requires_the_opaque_server_selection_fence() -> None:
    with pytest.raises(ValueError, match="governed Catalog source"):
        KnowledgeStudioTBoxProposalJobRequest(
            input_kind="CATALOG_SCHEMA",
            mode="APPEND_LAYER",
            asset_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1010"),
            selected_field_paths=["order_id"],
        )

    request = KnowledgeStudioTBoxProposalJobRequest(
        input_kind="CATALOG_SCHEMA",
        mode="APPEND_LAYER",
        asset_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1010"),
        selected_field_paths=["order_id"],
        expected_selection_fingerprint="a" * 64,
    )
    assert request.expected_selection_fingerprint == "a" * 64


@pytest.mark.asyncio
async def test_catalog_proposal_stale_selection_fence_creates_no_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1011")
    actor_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1012")
    draft_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1013")
    asset_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1014")
    subject = SubjectAttributes(
        subject_id=actor_id,
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.KG_EDIT}),
    )
    environment = EnvironmentAttributes(requested_at=datetime(2026, 8, 1, tzinfo=UTC))
    studio = SimpleNamespace(
        prepare_tbox_proposal=AsyncMock(
            return_value=SimpleNamespace(
                draft=SimpleNamespace(
                    classification=Classification.INTERNAL,
                    version=2,
                )
            )
        ),
        get_tbox_catalog_source=AsyncMock(
            return_value=KnowledgeStudioSourceDetail(
                dataset=KnowledgeStudioSourceDataset(
                    asset_id=asset_id,
                    name="orders",
                    asset_type="TABLE",
                    classification=Classification.INTERNAL,
                    source_version="datahub-v8",
                    projection_source_version="projection-v4",
                    platform="postgres",
                    database_name="sales",
                    schema_name="public",
                    field_paths=("order_id",),
                    fields_truncated=False,
                    selection_fingerprint="b" * 64,
                ),
                observed_at=datetime(2026, 8, 1, tzinfo=UTC),
                stale_at=None,
            )
        ),
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(
        knowledge_studio_routes,
        "get_container",
        lambda _request: SimpleNamespace(
            settings=SimpleNamespace(knowledge_studio_proposal_worker_enabled=True)
        ),
    )
    monkeypatch.setattr(knowledge_studio_routes, "_service", lambda *_args: studio)
    monkeypatch.setattr(
        knowledge_studio_routes,
        "_proposal_job_service",
        lambda _session: SimpleNamespace(enqueue=enqueue),
    )

    with pytest.raises(ConflictError) as failure:
        await knowledge_studio_routes.create_knowledge_studio_tbox_proposal_job(
            draft_id=draft_id,
            payload=KnowledgeStudioTBoxProposalJobRequest(
                input_kind="CATALOG_SCHEMA",
                mode="APPEND_LAYER",
                asset_id=asset_id,
                selected_field_paths=["order_id"],
                expected_selection_fingerprint="a" * 64,
            ),
            request=cast(Any, object()),
            response=Response(),
            context=cast(
                Any,
                SimpleNamespace(
                    workspace_id=workspace_id,
                    subject=subject,
                    environment=environment,
                    request_id="catalog-stale-fence",
                ),
            ),
            session=cast(Any, object()),
            if_match='"2"',
            idempotency_key="catalog-stale-fence",
        )

    assert failure.value.details == {"code": "CATALOG_PROPOSAL_SELECTION_STALE"}
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_proposal_builds_v2_pin_from_fresh_server_detail_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1021")
    actor_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1022")
    draft_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1023")
    asset_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1024")
    now = datetime(2026, 8, 1, tzinfo=UTC)
    subject = SubjectAttributes(
        subject_id=actor_id,
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.KG_EDIT}),
    )
    source = KnowledgeStudioSourceDetail(
        dataset=KnowledgeStudioSourceDataset(
            asset_id=asset_id,
            name="orders",
            asset_type="TABLE",
            classification=Classification.INTERNAL,
            source_version="datahub-v8",
            projection_source_version="projection-v4",
            platform="postgres",
            database_name="sales",
            schema_name="public",
            field_paths=("amount", "order_id"),
            fields_truncated=False,
            description="Governed order facts",
            field_metadata=(
                KnowledgeStudioCatalogFieldMetadata(
                    field_path="amount",
                    field_type=None,
                    native_data_type="numeric(18,2)",
                    description="Gross amount",
                    description_truncated=False,
                    tags=(),
                    tags_truncated=False,
                    glossary_terms=("Amount",),
                    terms_truncated=False,
                ),
                KnowledgeStudioCatalogFieldMetadata(
                    field_path="order_id",
                    field_type="KEY",
                    native_data_type="uuid",
                    description="Order identifier",
                    description_truncated=False,
                    tags=("gold",),
                    tags_truncated=False,
                    glossary_terms=("Order",),
                    terms_truncated=False,
                ),
            ),
            selection_fingerprint="f" * 64,
        ),
        observed_at=now,
        stale_at=None,
    )
    studio = SimpleNamespace(
        prepare_tbox_proposal=AsyncMock(
            return_value=SimpleNamespace(
                draft=SimpleNamespace(
                    classification=Classification.INTERNAL,
                    version=2,
                )
            )
        ),
        get_tbox_catalog_source=AsyncMock(return_value=source),
    )
    record = KnowledgeStudioProposalJobRecord(
        job_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1025"),
        workspace_id=workspace_id,
        draft_id=draft_id,
        requested_by=actor_id,
        input_kind=KnowledgeStudioProposalInputKind.CATALOG_SCHEMA,
        mode=TBoxProposalMode.APPEND_LAYER,
        target_block_id=None,
        state=KnowledgeStudioProposalJobState.QUEUED,
        stage=KnowledgeStudioProposalJobStage.QUEUED,
        progress_percent=0,
        attempt_count=0,
        maximum_attempts=4,
        next_attempt_at=now,
        last_failure_code=None,
        version=1,
        created_at=now,
        updated_at=now,
        completed_at=None,
        result=None,
    )
    enqueue = AsyncMock(return_value=record)
    monkeypatch.setattr(
        knowledge_studio_routes,
        "get_container",
        lambda _request: SimpleNamespace(
            settings=SimpleNamespace(
                knowledge_studio_proposal_worker_enabled=True,
                knowledge_studio_proposal_job_maximum_attempts=4,
            )
        ),
    )
    monkeypatch.setattr(knowledge_studio_routes, "_service", lambda *_args: studio)
    monkeypatch.setattr(
        knowledge_studio_routes,
        "_proposal_job_service",
        lambda _session: SimpleNamespace(enqueue=enqueue),
    )
    monkeypatch.setattr(
        knowledge_studio_routes,
        "knowledge_studio_proposal_base_tbox_hash",
        lambda _tbox: "c" * 64,
    )
    monkeypatch.setattr(
        knowledge_studio_routes,
        "resolve_knowledge_tbox_schema_binding",
        lambda _settings: ModelBinding(
            provider="enterprise-gateway",
            model="schema-model",
            prompt_version="tbox-v1",
            tool_schema_version="schema-v1",
            configuration_source="DEPLOYMENT",
            configuration_hash="d" * 64,
        ),
    )

    response = Response()
    result = await knowledge_studio_routes.create_knowledge_studio_tbox_proposal_job(
        draft_id=draft_id,
        payload=KnowledgeStudioTBoxProposalJobRequest(
            input_kind="CATALOG_SCHEMA",
            mode="APPEND_LAYER",
            asset_id=asset_id,
            selected_field_paths=["order_id", "amount"],
            expected_selection_fingerprint="f" * 64,
        ),
        request=cast(Any, object()),
        response=response,
        context=cast(
            Any,
            SimpleNamespace(
                workspace_id=workspace_id,
                subject=subject,
                environment=EnvironmentAttributes(requested_at=now),
                request_id="catalog-current-fence",
            ),
        ),
        session=cast(Any, object()),
        if_match='"2"',
        idempotency_key="catalog-current-fence",
    )

    assert result.input_kind == "CATALOG_SCHEMA"
    assert response.headers["ETag"] == '"1"'
    assert enqueue.await_count == 1
    assert enqueue.await_args is not None
    pins = enqueue.await_args.kwargs["pins"]
    document = pins.source.to_document()
    assert document["selected_field_paths"] == ["amount", "order_id"]
    assert document["field_metadata"][0]["description"] == "Gross amount"
    assert document["metadata_fingerprint"] == pins.source.metadata_fingerprint
    assert "expected_selection_fingerprint" not in document
