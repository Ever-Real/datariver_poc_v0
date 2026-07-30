from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.domain.authz import SubjectAttributes
from datariver.domain.governance_documents import (
    GovernanceDocumentAttachment,
    GovernanceDocumentCategory,
    GovernanceDocumentDetail,
    GovernanceDocumentKind,
    GovernanceDocumentPage,
    GovernanceDocumentProjectionClaim,
    GovernanceDocumentReviewDecision,
    GovernanceDocumentSourceFormat,
    GovernanceDocumentVersion,
    GovernanceKnowledgeEvidence,
)


class GovernanceDocumentRepository(Protocol):
    async def database_now(self) -> datetime: ...

    async def list_documents(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        kind: GovernanceDocumentKind | None,
        category: GovernanceDocumentCategory | None,
        include_archived: bool,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> GovernanceDocumentPage: ...

    async def get_document(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        subject: SubjectAttributes,
    ) -> GovernanceDocumentDetail | None: ...

    async def get_published_template_version(
        self,
        *,
        workspace_id: UUID,
        version_id: UUID,
        subject: SubjectAttributes,
    ) -> GovernanceDocumentVersion | None: ...

    async def create_document(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
        kind: GovernanceDocumentKind,
        category: GovernanceDocumentCategory,
        title: str,
        summary: str,
        classification: int,
        applicability_scope: str,
        sanitized_html: str,
        plain_text: str,
        content_sha256: str,
        sanitizer_policy_version: str,
        sanitizer_policy_sha256: str,
        source_format: GovernanceDocumentSourceFormat,
        source_template_version_id: UUID | None,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail: ...

    async def create_version(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        title: str,
        summary: str,
        applicability_scope: str,
        sanitized_html: str,
        plain_text: str,
        content_sha256: str,
        sanitizer_policy_version: str,
        sanitizer_policy_sha256: str,
        source_format: GovernanceDocumentSourceFormat,
        source_template_version_id: UUID | None,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail: ...

    async def submit_version(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail: ...

    async def review_version(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        reviewer_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        decision: GovernanceDocumentReviewDecision,
        reason: str,
        policy_decision_id: UUID,
        authentication_assurance: str,
        request_id: str,
    ) -> GovernanceDocumentDetail: ...

    async def archive_document(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail: ...

    async def add_attachment(
        self,
        *,
        attachment_id: UUID,
        workspace_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        original_name: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        bucket: str,
        object_key: str,
        provider_version_id: str,
        etag: str,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentAttachment: ...

    async def search_knowledge(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        query: str,
        query_vector: Sequence[float] | None,
        provider: str | None,
        model: str | None,
        limit: int,
    ) -> tuple[GovernanceKnowledgeEvidence, ...]: ...


class GovernanceDocumentProjectionRepository(Protocol):
    async def claim_next_projection(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> GovernanceDocumentProjectionClaim | None: ...

    async def store_artifact_receipt(
        self,
        *,
        version: GovernanceDocumentVersion,
        bucket: str,
        content_key: str,
        content_version_id: str,
        content_etag: str,
        manifest_key: str,
        manifest_version_id: str,
        manifest_etag: str,
        manifest_sha256: str,
    ) -> None: ...
    async def store_projection(
        self,
        *,
        version: GovernanceDocumentVersion,
        chunks: Sequence[tuple[int, str, str, Sequence[float]]],
        provider: str,
        model: str,
        graph_projection_hash: str | None,
    ) -> None: ...

    async def fail_projection(
        self,
        *,
        version: GovernanceDocumentVersion,
        failure_code: str,
        retryable: bool,
    ) -> None: ...


class GovernanceDocumentGraphProjector(Protocol):
    async def replace_version(
        self,
        *,
        claim: GovernanceDocumentProjectionClaim,
        chunks: Sequence[tuple[int, str, str]],
    ) -> str: ...
