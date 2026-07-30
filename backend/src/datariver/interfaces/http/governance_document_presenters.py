from __future__ import annotations

from datariver.domain.governance_documents import (
    GovernanceDocumentAttachment,
    GovernanceDocumentDetail,
    GovernanceDocumentReview,
    GovernanceDocumentSummary,
    GovernanceDocumentVersion,
    GovernanceKnowledgeEvidence,
)
from datariver.interfaces.http.governance_document_schemas import (
    GovernanceDocumentAttachmentResponse,
    GovernanceDocumentDetailItemResponse,
    GovernanceDocumentReviewResponse,
    GovernanceDocumentSummaryResponse,
    GovernanceDocumentVersionResponse,
    GovernanceKnowledgeEvidenceResponse,
)


def governance_document_summary_response(
    value: GovernanceDocumentSummary,
) -> GovernanceDocumentSummaryResponse:
    return GovernanceDocumentSummaryResponse(
        document_id=value.document_id,
        workspace_id=value.workspace_id,
        kind=value.kind.value,
        category=value.category.value,
        title=value.title,
        summary=value.summary,
        classification=int(value.classification),
        state=value.state.value,
        owner_subject_id=value.owner_subject_id,
        current_published_version_id=value.current_published_version_id,
        current_version_number=value.current_version_number,
        created_at=value.created_at,
        updated_at=value.updated_at,
        version=value.version,
        allowed_actions=list(value.allowed_actions),
    )


def governance_document_version_response(
    value: GovernanceDocumentVersion,
) -> GovernanceDocumentVersionResponse:
    return GovernanceDocumentVersionResponse(
        version_id=value.version_id,
        workspace_id=value.workspace_id,
        document_id=value.document_id,
        version_number=value.version_number,
        version_tag=value.version_tag,
        state=value.state.value,
        title=value.title,
        summary=value.summary,
        applicability_scope=value.applicability_scope,
        sanitized_html=value.sanitized_html,
        plain_text=value.plain_text,
        content_sha256=value.content_sha256,
        size_bytes=value.size_bytes,
        sanitizer_policy_version=value.sanitizer_policy_version,
        sanitizer_policy_sha256=value.sanitizer_policy_sha256,
        source_format=value.source_format.value,
        source_template_version_id=value.source_template_version_id,
        author_id=value.author_id,
        submitted_at=value.submitted_at,
        reviewed_by=value.reviewed_by,
        reviewed_at=value.reviewed_at,
        published_at=value.published_at,
        artifact_state=value.artifact_state.value,
        knowledge_state=value.knowledge_state.value,
        created_at=value.created_at,
        version=value.version,
    )


def governance_document_review_response(
    value: GovernanceDocumentReview,
) -> GovernanceDocumentReviewResponse:
    return GovernanceDocumentReviewResponse(
        review_id=value.review_id,
        workspace_id=value.workspace_id,
        document_id=value.document_id,
        document_version_id=value.document_version_id,
        decision=value.decision.value,
        reviewer_id=value.reviewer_id,
        reason=value.reason,
        policy_decision_id=value.policy_decision_id,
        authentication_assurance=value.authentication_assurance,
        created_at=value.created_at,
    )


def governance_document_attachment_response(
    value: GovernanceDocumentAttachment,
) -> GovernanceDocumentAttachmentResponse:
    return GovernanceDocumentAttachmentResponse(
        attachment_id=value.attachment_id,
        workspace_id=value.workspace_id,
        document_id=value.document_id,
        document_version_id=value.document_version_id,
        original_name=value.original_name,
        content_type=value.content_type,
        size_bytes=value.size_bytes,
        content_sha256=value.content_sha256,
        uploaded_by=value.uploaded_by,
        created_at=value.created_at,
    )


def governance_document_detail_response(
    value: GovernanceDocumentDetail,
) -> GovernanceDocumentDetailItemResponse:
    return GovernanceDocumentDetailItemResponse(
        document=governance_document_summary_response(value.document),
        versions=[governance_document_version_response(item) for item in value.versions],
        reviews=[governance_document_review_response(item) for item in value.reviews],
        attachments=[governance_document_attachment_response(item) for item in value.attachments],
    )


def governance_knowledge_evidence_response(
    value: GovernanceKnowledgeEvidence,
) -> GovernanceKnowledgeEvidenceResponse:
    return GovernanceKnowledgeEvidenceResponse(
        chunk_id=value.chunk_id,
        document_id=value.document_id,
        document_version_id=value.document_version_id,
        document_title=value.document_title,
        version_tag=value.version_tag,
        ordinal=value.ordinal,
        excerpt=value.excerpt,
        content_sha256=value.content_sha256,
        score_basis_points=value.score_basis_points,
        classification=int(value.classification),
        published_at=value.published_at,
    )
