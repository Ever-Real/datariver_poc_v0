from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class GovernanceDocumentModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_governance_documents_workspace_id"),
        ForeignKeyConstraint(
            ("workspace_id", "owner_subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_governance_documents_owner",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "archived_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_governance_documents_archiver",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "current_published_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
            name="fk_governance_documents_current_version",
        ),
        CheckConstraint("kind IN ('DOCUMENT','TEMPLATE')", name="kind_vocabulary"),
        CheckConstraint(
            "category IN ('POLICY','STANDARD_TERMINOLOGY','SECURITY_GUIDE','OTHER')",
            name="category_vocabulary",
        ),
        CheckConstraint("state IN ('DRAFT','ACTIVE','ARCHIVED')", name="state_vocabulary"),
        CheckConstraint("classification BETWEEN 0 AND 3", name="classification_range"),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 500",
            name="title_length",
        ),
        CheckConstraint(
            "char_length(summary) <= 2000",
            name="summary_length",
        ),
        CheckConstraint(
            "(state = 'DRAFT' AND current_published_version_id IS NULL "
            "AND archived_at IS NULL AND archived_by IS NULL AND archived_reason IS NULL) OR "
            "(state = 'ACTIVE' AND current_published_version_id IS NOT NULL "
            "AND archived_at IS NULL AND archived_by IS NULL AND archived_reason IS NULL) OR "
            "(state = 'ARCHIVED' AND archived_at IS NOT NULL "
            "AND archived_by IS NOT NULL AND archived_reason IS NOT NULL)",
            name="lifecycle_shape",
        ),
        Index(
            "ix_governance_documents_list",
            "workspace_id",
            "kind",
            "state",
            text("updated_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_governance_documents_title",
            "workspace_id",
            text("lower(title)"),
            "id",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    classification: Mapped[int] = mapped_column(nullable=False)
    owner_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    owner_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    state: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    current_published_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    archived_reason: Mapped[str | None] = mapped_column(String(2_000))


class GovernanceDocumentVersionModel(Base, UuidPrimaryKeyMixin, VersionMixin):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_governance_document_versions_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "document_id",
            "version_number",
            name="uq_governance_document_versions_number",
        ),
        UniqueConstraint(
            "workspace_id",
            "document_id",
            "version_tag",
            name="uq_governance_document_versions_tag",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_id"),
            ("governance.documents.workspace_id", "governance.documents.id"),
            ondelete="RESTRICT",
            name="fk_governance_document_versions_document",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "author_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_governance_document_versions_author",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "reviewed_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_governance_document_versions_reviewer",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_template_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            use_alter=True,
            ondelete="RESTRICT",
            name="fk_governance_document_versions_template",
        ),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("version_tag ~ '^v[1-9][0-9]{0,8}$'", name="version_tag_valid"),
        CheckConstraint(
            "state IN ('DRAFT','IN_REVIEW','PUBLISHED','REJECTED','SUPERSEDED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "source_format IN ('HTML','MARKDOWN','DOCX')",
            name="source_format_vocabulary",
        ),
        CheckConstraint(
            "artifact_state IN ('PENDING','STORED','FAILED')",
            name="artifact_state_vocabulary",
        ),
        CheckConstraint(
            "knowledge_state IN ('PENDING','PROJECTING','READY','FAILED')",
            name="knowledge_state_vocabulary",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_valid",
        ),
        CheckConstraint(
            "sanitizer_policy_sha256 ~ '^[0-9a-f]{64}$'",
            name="sanitizer_policy_sha256_valid",
        ),
        CheckConstraint(
            "size_bytes BETWEEN 1 AND 1048576",
            name="size_bytes_range",
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 500",
            name="title_length",
        ),
        CheckConstraint(
            "char_length(summary) <= 2000",
            name="summary_length",
        ),
        CheckConstraint(
            "char_length(applicability_scope) <= 4000",
            name="applicability_scope_length",
        ),
        CheckConstraint(
            "(state = 'DRAFT' AND submitted_at IS NULL AND reviewed_by IS NULL "
            "AND reviewed_at IS NULL AND published_at IS NULL) OR "
            "(state = 'IN_REVIEW' AND submitted_at IS NOT NULL AND reviewed_by IS NULL "
            "AND reviewed_at IS NULL AND published_at IS NULL) OR "
            "(state = 'REJECTED' AND submitted_at IS NOT NULL AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND published_at IS NULL) OR "
            "(state IN ('PUBLISHED','SUPERSEDED') AND submitted_at IS NOT NULL "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND published_at IS NOT NULL)",
            name="lifecycle_shape",
        ),
        CheckConstraint(
            "reviewed_by IS NULL OR reviewed_by <> author_id",
            name="maker_checker_distinct",
        ),
        CheckConstraint(
            "failure_code IS NULL OR (artifact_state = 'FAILED' OR knowledge_state = 'FAILED')",
            name="failure_code_shape",
        ),
        Index(
            "ix_governance_document_versions_history",
            "workspace_id",
            "document_id",
            text("version_number DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_governance_document_versions_projection",
            "knowledge_state",
            "next_attempt_at",
            "lease_until",
            "id",
            postgresql_where=text(
                "state = 'PUBLISHED' AND knowledge_state IN ('PENDING','FAILED')"
            ),
        ),
        Index(
            "uq_governance_document_versions_live_candidate",
            "workspace_id",
            "document_id",
            unique=True,
            postgresql_where=text("state IN ('DRAFT','IN_REVIEW')"),
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False)
    version_tag: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    applicability_scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sanitized_html: Mapped[str] = mapped_column(Text, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    sanitizer_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    sanitizer_policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    source_template_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_state: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    knowledge_state: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    projection_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class GovernanceDocumentReviewModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "document_reviews"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_governance_document_reviews_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "document_version_id",
            name="uq_governance_document_reviews_version",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_id"),
            ("governance.documents.workspace_id", "governance.documents.id"),
            ondelete="RESTRICT",
            name="fk_governance_document_reviews_document",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_governance_document_reviews_version",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "reviewer_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_governance_document_reviews_reviewer",
        ),
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="decision_vocabulary"),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000",
            name="reason_length",
        ),
        Index(
            "ix_governance_document_reviews_history",
            "workspace_id",
            "document_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(2_000), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    authentication_assurance: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class GovernanceDocumentEventModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "document_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_governance_document_events_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "document_id",
            "sequence",
            name="uq_governance_document_events_sequence",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_id"),
            ("governance.documents.workspace_id", "governance.documents.id"),
            ondelete="RESTRICT",
            name="fk_governance_document_events_document",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_governance_document_events_version",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "actor_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_governance_document_events_actor",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "event_type IN ('CREATED','VERSION_CREATED','SUBMITTED','APPROVED',"
            "'REJECTED','PUBLISHED','ARCHIVED','ATTACHMENT_ADDED','ARTIFACT_STORED',"
            "'KNOWLEDGE_PROJECTED','PROJECTION_FAILED')",
            name="event_type_vocabulary",
        ),
        Index(
            "ix_governance_document_events_history",
            "workspace_id",
            "document_id",
            "sequence",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    sequence: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class GovernanceDocumentArtifactReceiptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "document_artifact_receipts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "document_version_id",
            name="uq_governance_document_artifact_receipts_version",
        ),
        UniqueConstraint(
            "bucket",
            "content_object_key",
            "content_provider_version_id",
            name="uq_governance_document_artifact_content",
        ),
        UniqueConstraint(
            "bucket",
            "manifest_object_key",
            "manifest_provider_version_id",
            name="uq_governance_document_artifact_manifest",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_id"),
            ("governance.documents.workspace_id", "governance.documents.id"),
            ondelete="RESTRICT",
            name="fk_governance_document_artifact_receipts_document",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_governance_document_artifact_receipts_version",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_valid"),
        CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="manifest_sha256_valid"),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    content_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_provider_version_id: Mapped[str] = mapped_column(String(1_000), nullable=False)
    content_etag: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_provider_version_id: Mapped[str] = mapped_column(String(1_000), nullable=False)
    manifest_etag: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class GovernanceDocumentAttachmentModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "document_attachments"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_document_attachments_workspace_id",
        ),
        UniqueConstraint(
            "bucket",
            "object_key",
            "provider_version_id",
            name="uq_governance_document_attachments_object",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_id"),
            ("governance.documents.workspace_id", "governance.documents.id"),
            ondelete="RESTRICT",
            name="fk_governance_document_attachments_document",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_governance_document_attachments_version",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "uploaded_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_governance_document_attachments_uploader",
        ),
        CheckConstraint(
            "size_bytes BETWEEN 1 AND 26214400",
            name="size_bytes_range",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_valid"),
        Index(
            "ix_governance_document_attachments_version",
            "workspace_id",
            "document_version_id",
            "created_at",
            "id",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    provider_version_id: Mapped[str] = mapped_column(String(1_000), nullable=False)
    etag: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class GovernanceDocumentKnowledgeChunkModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "document_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_document_knowledge_chunks_workspace_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "document_version_id",
            "ordinal",
            name="uq_governance_document_knowledge_chunks_ordinal",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_id"),
            ("governance.documents.workspace_id", "governance.documents.id"),
            ondelete="RESTRICT",
            name="fk_governance_document_knowledge_chunks_document",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_governance_document_knowledge_chunks_version",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_valid"),
        CheckConstraint(
            "embedding_dimension BETWEEN 1 AND 16384",
            name="embedding_dimension_range",
        ),
        Index(
            "ix_governance_document_knowledge_chunks_search",
            "workspace_id",
            "document_id",
            "document_version_id",
            "ordinal",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON_DOCUMENT, nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    graph_node_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class GovernanceDocumentProjectionReceiptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "document_projection_receipts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "document_version_id",
            name="uq_governance_document_projection_receipts_version",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_id"),
            ("governance.documents.workspace_id", "governance.documents.id"),
            ondelete="RESTRICT",
            name="fk_governance_document_projection_receipts_document",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "document_version_id"),
            (
                "governance.document_versions.workspace_id",
                "governance.document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_governance_document_projection_receipts_version",
        ),
        CheckConstraint("projection_hash ~ '^[0-9a-f]{64}$'", name="projection_hash_valid"),
        CheckConstraint(
            "graph_projection_hash IS NULL OR graph_projection_hash ~ '^[0-9a-f]{64}$'",
            name="graph_projection_hash_valid",
        ),
        CheckConstraint("chunk_count BETWEEN 1 AND 512", name="chunk_count_range"),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    chunk_count: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_projection_hash: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
