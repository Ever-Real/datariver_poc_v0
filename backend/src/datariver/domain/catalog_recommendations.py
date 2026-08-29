from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import ValidationError

MAXIMUM_RECOMMENDATIONS = 100
MAXIMUM_RECOMMENDATION_EVIDENCE = 10
MAXIMUM_RECOMMENDATION_EVIDENCE_LENGTH = 1_000
MAXIMUM_RECOMMENDATION_REASON_LENGTH = 2_000
MAXIMUM_RECOMMENDATION_VERSION_LENGTH = 128
MAXIMUM_RECOMMENDATION_FIELD_PATH_LENGTH = 2_000


class CatalogRecommendationKind(StrEnum):
    TAG = "TAG"
    TERM = "TERM"


class CatalogRecommendationState(StrEnum):
    NEEDS_DECISION = "NEEDS_DECISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CatalogRecommendationDecision(StrEnum):
    PREVIEWED = "PREVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class CatalogRecommendationVocabulary:
    vocabulary_id: UUID
    kind: CatalogRecommendationKind
    display_name: str
    source_version: str

    def __post_init__(self) -> None:
        _bounded_text(self.display_name, "vocabulary display name", 500)
        _bounded_text(self.source_version, "vocabulary source version", 255)


@dataclass(frozen=True, slots=True)
class CatalogRecommendationContext:
    asset_id: UUID
    source_version: str
    provider_source_version: str
    name: str
    description: str | None
    platform: str | None
    database_name: str | None
    schema_name: str | None
    field_path: str | None
    field_native_type: str | None
    vocabulary: tuple[CatalogRecommendationVocabulary, ...]
    assigned_vocabulary_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _bounded_text(self.source_version, "catalog source version", 255)
        _bounded_text(self.provider_source_version, "catalog provider source version", 255)
        _bounded_text(self.name, "catalog asset name", 500)
        _optional_bounded_text(self.description, "catalog description", 10_000)
        _optional_bounded_text(self.platform, "catalog platform", 100)
        _optional_bounded_text(self.database_name, "catalog database", 255)
        _optional_bounded_text(self.schema_name, "catalog schema", 255)
        _optional_bounded_text(
            self.field_path,
            "catalog field path",
            MAXIMUM_RECOMMENDATION_FIELD_PATH_LENGTH,
        )
        _optional_bounded_text(self.field_native_type, "catalog field native type", 500)
        if not self.vocabulary or len(self.vocabulary) > MAXIMUM_RECOMMENDATIONS:
            raise ValidationError("The recommendation vocabulary is outside the bounded contract.")
        vocabulary_ids = tuple(item.vocabulary_id for item in self.vocabulary)
        if len(vocabulary_ids) != len(set(vocabulary_ids)):
            raise ValidationError("The recommendation vocabulary contains duplicate identities.")
        if len(self.assigned_vocabulary_ids) != len(set(self.assigned_vocabulary_ids)) or not set(
            self.assigned_vocabulary_ids
        ).issubset(vocabulary_ids):
            raise ValidationError("The assigned recommendation vocabulary is invalid.")

    def provider_document(self) -> dict[str, object]:
        """Return only bounded local identities and authorized metadata.

        Vocabulary synonym and hierarchy keys are intentionally absent because the current
        canonical Catalog vocabulary projection does not own either value.
        """

        document: dict[str, object] = {
            "asset_id": str(self.asset_id),
            "source_version": self.source_version,
            "provider_source_version": self.provider_source_version,
            "name": self.name,
            "vocabulary": [
                {
                    "vocabulary_id": str(item.vocabulary_id),
                    "kind": item.kind.value,
                    "display_name": item.display_name,
                }
                for item in self.vocabulary
            ],
            "assigned_vocabulary_ids": [str(value) for value in self.assigned_vocabulary_ids],
        }
        for key, value in (
            ("description", self.description),
            ("platform", self.platform),
            ("database_name", self.database_name),
            ("schema_name", self.schema_name),
            ("field_path", self.field_path),
            ("field_native_type", self.field_native_type),
        ):
            if value is not None:
                document[key] = value
        return document


@dataclass(frozen=True, slots=True)
class CatalogRecommendationDraft:
    vocabulary_id: UUID
    confidence: float
    reason: str
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValidationError("Recommendation confidence must be between zero and one.")
        _bounded_text(
            self.reason,
            "recommendation reason",
            MAXIMUM_RECOMMENDATION_REASON_LENGTH,
        )
        if not 1 <= len(self.evidence) <= MAXIMUM_RECOMMENDATION_EVIDENCE:
            raise ValidationError("Recommendation evidence is outside the bounded contract.")
        for value in self.evidence:
            _bounded_text(
                value,
                "recommendation evidence",
                MAXIMUM_RECOMMENDATION_EVIDENCE_LENGTH,
            )


@dataclass(frozen=True, slots=True)
class CatalogRecommendationProviderResult:
    recommendations: tuple[CatalogRecommendationDraft, ...]
    provider: str
    model: str
    prompt_version: str
    rule_version: str
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.truncated:
            raise ValidationError("A truncated recommendation result cannot be accepted.")
        if len(self.recommendations) > MAXIMUM_RECOMMENDATIONS:
            raise ValidationError("The provider returned too many recommendations.")
        ids = tuple(item.vocabulary_id for item in self.recommendations)
        if len(ids) != len(set(ids)):
            raise ValidationError("The provider returned duplicate recommendation identities.")
        for value, label in (
            (self.provider, "recommendation provider"),
            (self.model, "recommendation model"),
            (self.prompt_version, "recommendation prompt version"),
            (self.rule_version, "recommendation rule version"),
        ):
            _bounded_text(value, label, MAXIMUM_RECOMMENDATION_VERSION_LENGTH)


@dataclass(frozen=True, slots=True)
class CatalogRecommendation:
    recommendation_id: UUID
    workspace_id: UUID
    asset_id: UUID
    field_path: str | None
    vocabulary_id: UUID
    kind: CatalogRecommendationKind
    source_version: str
    provider_source_version: str
    vocabulary_source_version: str
    aspect_name: str
    aspect_source_version: str
    aspect_content_hash: str
    target_binding_hash: str
    input_context_hash: str
    confidence: float
    reason: str
    evidence: tuple[str, ...]
    provider: str
    model: str
    prompt_version: str
    rule_version: str
    state: CatalogRecommendationState
    version: int
    created_by: UUID
    decision_actor_id: UUID | None
    change_request_id: UUID | None
    created_at: datetime
    updated_at: datetime


def _bounded_text(value: str, label: str, maximum: int) -> None:
    if value != value.strip() or not value or len(value) > maximum or "\x00" in value:
        raise ValidationError(f"The {label} is outside the bounded contract.")


def _optional_bounded_text(value: str | None, label: str, maximum: int) -> None:
    if value is not None:
        _bounded_text(value, label, maximum)
