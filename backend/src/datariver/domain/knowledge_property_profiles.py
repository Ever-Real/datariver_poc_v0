from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import ValidationError

MAX_PROPERTY_PROFILE_SYNONYMS = 50


class PropertyProfileLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


def normalize_optional_profile_text(
    value: str | None,
    *,
    field_name: str,
    maximum_length: int,
    allow_multiline: bool = False,
) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        return None
    if len(normalized) > maximum_length or any(
        ord(character) < 32 and not (allow_multiline and character in {"\n", "\t"})
        for character in normalized
    ):
        raise ValidationError(f"The Property profile {field_name} is invalid.")
    return normalized


def normalize_profile_synonyms(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > MAX_PROPERTY_PROFILE_SYNONYMS:
        raise ValidationError("A Property profile accepts at most 50 synonyms.")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = normalize_optional_profile_text(
            raw_value,
            field_name="synonym",
            maximum_length=200,
        )
        if value is None:
            raise ValidationError("Property profile synonyms cannot be blank.")
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class KnowledgePropertyTarget:
    workspace_id: UUID
    graph_id: UUID
    graph_name: str
    studio_release_id: UUID
    release_no: int
    ontology_version_id: UUID
    ontology_element_id: UUID
    stable_property_id: str
    property_name: str
    owner_class_id: str
    data_type: str
    property_urn: str
    classification: int
    domain_id: UUID | None


@dataclass(frozen=True, slots=True)
class KnowledgePropertyProfile:
    profile_id: UUID
    workspace_id: UUID
    graph_id: UUID
    studio_release_id: UUID
    ontology_version_id: UUID
    ontology_element_id: UUID
    stable_property_id: str
    description: str | None
    unit: str | None
    synonyms: tuple[str, ...]
    lifecycle: PropertyProfileLifecycle
    created_by: UUID
    updated_by: UUID
    archived_by: UUID | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int


def validate_property_profile_values(
    *,
    description: str | None,
    unit: str | None,
    synonyms: tuple[str, ...],
) -> tuple[str | None, str | None, tuple[str, ...]]:
    normalized_description = normalize_optional_profile_text(
        description,
        field_name="description",
        maximum_length=2_000,
        allow_multiline=True,
    )
    normalized_unit = normalize_optional_profile_text(
        unit,
        field_name="unit",
        maximum_length=100,
    )
    normalized_synonyms = normalize_profile_synonyms(synonyms)
    if normalized_description is None and normalized_unit is None and not normalized_synonyms:
        raise ValidationError("A Property profile must contain at least one managed value.")
    return normalized_description, normalized_unit, normalized_synonyms
