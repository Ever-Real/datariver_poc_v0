from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError, canonical_json_hash

MAXIMUM_DOCUMENT_TITLE_CHARACTERS = 500
MAXIMUM_DOCUMENT_SUMMARY_CHARACTERS = 2_000
MAXIMUM_APPLICABILITY_SCOPE_CHARACTERS = 4_000
MAXIMUM_SANITIZED_HTML_BYTES = 1_048_576
MAXIMUM_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAXIMUM_ATTACHMENTS_PER_VERSION = 25
MAXIMUM_DOCUMENT_VERSIONS_PER_PAGE = 100
MAXIMUM_KNOWLEDGE_CHUNKS = 512
MAXIMUM_KNOWLEDGE_CHUNK_CHARACTERS = 2_000
MAXIMUM_GOVERNANCE_CONCEPTS = 64
MAXIMUM_GOVERNANCE_CONCEPT_REFERENCE_CHARACTERS = 500

_VERSION_TAG = re.compile(r"^v([1-9][0-9]{0,8})$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class GovernanceDocumentKind(StrEnum):
    DOCUMENT = "DOCUMENT"
    TEMPLATE = "TEMPLATE"


class GovernanceDocumentCategory(StrEnum):
    POLICY = "POLICY"
    STANDARD_TERMINOLOGY = "STANDARD_TERMINOLOGY"
    SECURITY_GUIDE = "SECURITY_GUIDE"
    OTHER = "OTHER"


class GovernanceDocumentState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class GovernanceDocumentVersionState(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class GovernanceDocumentSourceFormat(StrEnum):
    HTML = "HTML"
    MARKDOWN = "MARKDOWN"
    DOCX = "DOCX"


class GovernanceDocumentArtifactState(StrEnum):
    PENDING = "PENDING"
    STORED = "STORED"
    FAILED = "FAILED"


class GovernanceDocumentKnowledgeState(StrEnum):
    PENDING = "PENDING"
    PROJECTING = "PROJECTING"
    READY = "READY"
    FAILED = "FAILED"


class GovernanceDocumentReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class GovernanceDocumentConceptKind(StrEnum):
    DATASET = "DATASET"
    TERM = "TERM"


def normalized_bounded_text(
    value: str,
    *,
    label: str,
    maximum_characters: int,
    allow_empty: bool = False,
) -> str:
    normalized = value.strip()
    if (
        (not normalized and not allow_empty)
        or len(normalized) > maximum_characters
        or any(ord(character) < 32 and character not in "\n\t" for character in normalized)
    ):
        raise ValidationError(f"The Governance Document {label} is outside its bounded contract.")
    return normalized


def validate_document_identity(
    *,
    kind: GovernanceDocumentKind,
    category: GovernanceDocumentCategory,
    title: str,
    summary: str,
    classification: Classification,
) -> tuple[str, str]:
    del kind, category
    normalized_title = normalized_bounded_text(
        title,
        label="title",
        maximum_characters=MAXIMUM_DOCUMENT_TITLE_CHARACTERS,
    )
    normalized_summary = normalized_bounded_text(
        summary,
        label="summary",
        maximum_characters=MAXIMUM_DOCUMENT_SUMMARY_CHARACTERS,
        allow_empty=True,
    )
    if classification not in set(Classification):
        raise ValidationError("The Governance Document classification is invalid.")
    return normalized_title, normalized_summary


def version_tag(version_number: int) -> str:
    if not 1 <= version_number <= 999_999_999:
        raise ValidationError("The Governance Document version number is invalid.")
    return f"v{version_number}"


def validate_version_tag(value: str, *, version_number: int) -> str:
    normalized = value.strip()
    match = _VERSION_TAG.fullmatch(normalized)
    if match is None or int(match.group(1)) != version_number:
        raise ValidationError("The Governance Document version tag is invalid.")
    return normalized


def validate_content_hash(value: str) -> str:
    normalized = value.strip().lower()
    if _HASH.fullmatch(normalized) is None:
        raise ValidationError("The Governance Document content hash is invalid.")
    return normalized


@dataclass(frozen=True, slots=True)
class GovernanceDocumentSummary:
    document_id: UUID
    workspace_id: UUID
    kind: GovernanceDocumentKind
    category: GovernanceDocumentCategory
    title: str
    summary: str
    classification: Classification
    state: GovernanceDocumentState
    owner_subject_id: UUID
    current_published_version_id: UUID | None
    current_version_number: int | None
    created_at: datetime
    updated_at: datetime
    version: int
    allowed_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GovernanceDocumentVersion:
    version_id: UUID
    workspace_id: UUID
    document_id: UUID
    version_number: int
    version_tag: str
    state: GovernanceDocumentVersionState
    title: str
    summary: str
    applicability_scope: str
    sanitized_html: str
    plain_text: str
    content_sha256: str
    size_bytes: int
    sanitizer_policy_version: str
    sanitizer_policy_sha256: str
    source_format: GovernanceDocumentSourceFormat
    source_template_version_id: UUID | None
    author_id: UUID
    submitted_at: datetime | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    published_at: datetime | None
    artifact_state: GovernanceDocumentArtifactState
    knowledge_state: GovernanceDocumentKnowledgeState
    created_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class GovernanceDocumentProjectionClaim:
    version: GovernanceDocumentVersion
    kind: GovernanceDocumentKind
    category: GovernanceDocumentCategory
    classification: Classification


@dataclass(frozen=True, slots=True)
class GovernanceDocumentConcept:
    kind: GovernanceDocumentConceptKind
    reference: str

    def __post_init__(self) -> None:
        if (
            not self.reference
            or len(self.reference) > MAXIMUM_GOVERNANCE_CONCEPT_REFERENCE_CHARACTERS
            or self.reference != self.reference.strip()
            or any(ord(character) < 32 for character in self.reference)
        ):
            raise ValueError("Governance document concept reference is invalid.")


@dataclass(frozen=True, slots=True)
class GovernanceDocumentAttachment:
    attachment_id: UUID
    workspace_id: UUID
    document_id: UUID
    document_version_id: UUID
    original_name: str
    content_type: str
    size_bytes: int
    content_sha256: str
    uploaded_by: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GovernanceDocumentReview:
    review_id: UUID
    workspace_id: UUID
    document_id: UUID
    document_version_id: UUID
    decision: GovernanceDocumentReviewDecision
    reviewer_id: UUID
    reason: str
    policy_decision_id: UUID
    authentication_assurance: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GovernanceDocumentDetail:
    document: GovernanceDocumentSummary
    versions: tuple[GovernanceDocumentVersion, ...]
    reviews: tuple[GovernanceDocumentReview, ...]
    attachments: tuple[GovernanceDocumentAttachment, ...]


@dataclass(frozen=True, slots=True)
class GovernanceDocumentPage:
    items: tuple[GovernanceDocumentSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class GovernanceDocumentCapabilityAxis:
    id: str
    state: str
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class GovernanceDocumentCapability:
    observed_at: datetime
    valid_until: datetime
    cache_scope: str
    axes: tuple[GovernanceDocumentCapabilityAxis, ...]


@dataclass(frozen=True, slots=True)
class GovernanceDocumentBlueprint:
    blueprint_id: str
    blueprint_version: str
    category: GovernanceDocumentCategory
    title: str
    summary: str
    applicability_scope: str
    sanitized_html: str
    content_sha256: str
    sanitizer_policy_version: str
    sanitizer_policy_sha256: str


@dataclass(frozen=True, slots=True)
class GovernanceKnowledgeEvidence:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    version_tag: str
    ordinal: int
    excerpt: str
    content_sha256: str
    score_basis_points: int
    classification: Classification
    published_at: datetime


def governance_document_request_hash(
    *,
    contract: str,
    workspace_id: UUID,
    actor_id: UUID,
    document: dict[str, object],
) -> str:
    return canonical_json_hash(
        {
            "contract": contract,
            "workspace_id": str(workspace_id),
            "actor_id": str(actor_id),
            "document": document,
        }
    )
