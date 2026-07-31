from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from datariver.interfaces.http.schemas import PageMeta


class GovernanceDocumentCapabilityAxisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal[
        "read",
        "create",
        "edit",
        "review",
        "publish",
        "archive",
        "template_manage",
        "artifact_storage",
        "knowledge_projection",
    ]
    state: Literal["AVAILABLE", "DENIED", "UNAVAILABLE"]
    reason_code: str | None = None


class GovernanceDocumentLimitsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_html_bytes: int = Field(ge=1)
    max_attachment_bytes: int = Field(ge=1)
    max_attachments_per_version: int = Field(ge=1)


class GovernanceDocumentCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["GOVERNANCE_DOCUMENT_CAPABILITY_V1"] = (
        "GOVERNANCE_DOCUMENT_CAPABILITY_V1"
    )
    observed_at: datetime
    valid_until: datetime
    cache_scope: str = Field(pattern=r"^[0-9a-f]{64}$")
    axes: list[GovernanceDocumentCapabilityAxisResponse]
    limits: GovernanceDocumentLimitsResponse


class GovernanceDocumentSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    workspace_id: UUID
    kind: Literal["DOCUMENT", "TEMPLATE"]
    category: Literal["POLICY", "STANDARD_TERMINOLOGY", "SECURITY_GUIDE", "OTHER"]
    title: str
    summary: str
    classification: int = Field(ge=0, le=3)
    state: Literal["DRAFT", "ACTIVE", "ARCHIVED"]
    owner_subject_id: UUID
    current_published_version_id: UUID | None
    current_version_number: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)
    allowed_actions: list[
        Literal[
            "read",
            "create_version",
            "submit",
            "review",
            "publish",
            "archive",
            "add_attachment",
            "download_attachment",
            "instantiate_template",
        ]
    ]


class GovernanceDocumentVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    workspace_id: UUID
    document_id: UUID
    version_number: int = Field(ge=1)
    version_tag: str = Field(pattern=r"^v[1-9][0-9]{0,8}$")
    state: Literal["DRAFT", "IN_REVIEW", "PUBLISHED", "REJECTED", "SUPERSEDED"]
    title: str
    summary: str
    applicability_scope: str
    sanitized_html: str
    plain_text: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=1_048_576)
    sanitizer_policy_version: str
    sanitizer_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_format: Literal["HTML", "MARKDOWN", "DOCX"]
    source_template_version_id: UUID | None
    author_id: UUID
    submitted_at: datetime | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    published_at: datetime | None
    artifact_state: Literal["PENDING", "STORED", "FAILED"]
    knowledge_state: Literal["PENDING", "PROJECTING", "READY", "FAILED"]
    created_at: datetime
    version: int = Field(ge=1)


class GovernanceDocumentReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: UUID
    workspace_id: UUID
    document_id: UUID
    document_version_id: UUID
    decision: Literal["APPROVE", "REJECT"]
    reviewer_id: UUID
    reason: str
    policy_decision_id: UUID
    authentication_assurance: str
    created_at: datetime


class GovernanceDocumentAttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID
    workspace_id: UUID
    document_id: UUID
    document_version_id: UUID
    original_name: str
    content_type: str
    size_bytes: int = Field(ge=1, le=25 * 1024 * 1024)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    uploaded_by: UUID
    created_at: datetime


class GovernanceDocumentAttachmentDownloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment: GovernanceDocumentAttachmentResponse
    url: str
    expires_at: datetime


class GovernanceDocumentDetailItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: GovernanceDocumentSummaryResponse
    versions: list[GovernanceDocumentVersionResponse]
    reviews: list[GovernanceDocumentReviewResponse]
    attachments: list[GovernanceDocumentAttachmentResponse]


class GovernanceDocumentReadMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_scope: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    authorization_valid_until: datetime


class GovernanceDocumentListResponse(GovernanceDocumentReadMetadata):
    items: list[GovernanceDocumentSummaryResponse]
    page: PageMeta


class GovernanceDocumentDetailResponse(GovernanceDocumentReadMetadata):
    item: GovernanceDocumentDetailItemResponse


class GovernanceDocumentCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: GovernanceDocumentDetailItemResponse


class GovernanceDocumentBlueprintResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str
    blueprint_version: str
    category: Literal["POLICY", "STANDARD_TERMINOLOGY", "SECURITY_GUIDE"]
    title: str
    summary: str
    applicability_scope: str
    sanitized_html: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sanitizer_policy_version: str
    sanitizer_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GovernanceDocumentBlueprintListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["GOVERNANCE_DOCUMENT_BLUEPRINTS_V1"] = (
        "GOVERNANCE_DOCUMENT_BLUEPRINTS_V1"
    )
    items: list[GovernanceDocumentBlueprintResponse]


class GovernanceDocumentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["DOCUMENT", "TEMPLATE"]
    category: Literal["POLICY", "STANDARD_TERMINOLOGY", "SECURITY_GUIDE", "OTHER"]
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2_000)
    classification: int = Field(ge=0, le=3)
    applicability_scope: str = Field(default="", max_length=4_000)
    sanitized_html: str | None = None
    source_template_version_id: UUID | None = None

    @model_validator(mode="after")
    def require_content_or_template(self) -> GovernanceDocumentCreateRequest:
        if self.sanitized_html is None and self.source_template_version_id is None:
            raise ValueError("sanitized_html or source_template_version_id is required")
        return self


class GovernanceDocumentVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=2_000)
    applicability_scope: str = Field(default="", max_length=4_000)
    sanitized_html: str
    source_template_version_id: UUID | None = None


class GovernanceDocumentReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=2_000)


class GovernanceDocumentArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2_000)


class GovernanceKnowledgeEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    version_tag: str
    ordinal: int = Field(ge=1)
    excerpt: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    score_basis_points: int = Field(ge=0, le=10_000)
    classification: int = Field(ge=0, le=3)
    published_at: datetime


class GovernanceKnowledgeEvidenceListResponse(GovernanceDocumentReadMetadata):
    items: list[GovernanceKnowledgeEvidenceResponse]


class GovernanceRagSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)
