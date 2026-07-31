from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from datariver.application.dto import KnowledgeStudioTBoxProposalRecord
from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalJobRecord,
    KnowledgeStudioProposalJobResult,
)
from datariver.domain.knowledge_studio import TBoxProposalMode
from datariver.domain.knowledge_studio_proposal_jobs import (
    KnowledgeStudioProposalInputKind,
    KnowledgeStudioProposalJobStage,
    KnowledgeStudioProposalJobState,
)
from datariver.interfaces.http.routes.knowledge_studio import (
    _proposal_job_response,
    _proposal_response,
    _public_source_reference,
)


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
