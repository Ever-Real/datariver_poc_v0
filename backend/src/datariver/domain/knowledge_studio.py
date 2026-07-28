from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from datariver.domain.common import (
    ConflictError,
    PreconditionFailedError,
    ValidationError,
)


class StudioDraftKind(StrEnum):
    CREATE = "CREATE"
    EDIT = "EDIT"


class StudioDraftState(StrEnum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    PUBLISHED = "PUBLISHED"
    DISCARDED = "DISCARDED"


class StudioStep(StrEnum):
    BASIC = "BASIC"
    TBOX = "TBOX"
    ABOX = "ABOX"


class TBoxElementKind(StrEnum):
    CLASS = "CLASS"
    PROPERTY = "PROPERTY"
    RELATION = "RELATION"


class ABoxMappingMethod(StrEnum):
    SUBJECT_ID = "SUBJECT_ID"
    PROPERTY = "PROPERTY"
    EDGE_LINK = "EDGE_LINK"
    EDGE_PROPERTY = "EDGE_PROPERTY"


class ABoxBindingReadiness(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    STALE = "STALE"


def validate_endpoint_alias(value: str) -> str:
    """Validate the public graph identity without a normalization side effect."""

    if len(value) < 3 or len(value) > 100:
        raise ValidationError("Endpoint alias must contain between 3 and 100 characters.")
    if value[0] < "a" or value[0] > "z":
        raise ValidationError("Endpoint alias must start with a lowercase ASCII letter.")
    for character in value[1:]:
        is_lowercase_letter = "a" <= character <= "z"
        is_digit = "0" <= character <= "9"
        if not (is_lowercase_letter or is_digit or character == "_"):
            raise ValidationError(
                "Endpoint alias may contain lowercase ASCII letters, digits and underscores."
            )
    return value


def validate_studio_name(value: str) -> str:
    if value != value.strip():
        raise ValidationError("Knowledge graph name must not contain surrounding whitespace.")
    if len(value) < 1 or len(value) > 255:
        raise ValidationError("Knowledge graph name must contain between 1 and 255 characters.")
    return value


def require_studio_version(current_version: int, expected_version: int) -> None:
    if current_version != expected_version:
        raise PreconditionFailedError("The Knowledge Studio draft was modified by another editor.")


def validate_stable_element_id(value: str) -> str:
    if value != value.strip() or not 1 <= len(value) <= 128:
        raise ValidationError(
            "A stable T-Box element ID must contain between 1 and 128 characters."
        )
    for character in value:
        if not (
            "a" <= character <= "z"
            or "A" <= character <= "Z"
            or "0" <= character <= "9"
            or character in {"_", "-", ".", ":"}
        ):
            raise ValidationError("A stable T-Box element ID contains an unsupported character.")
    return value


def validate_source_field_path(value: str) -> str:
    if value != value.strip() or not 1 <= len(value) <= 2_000:
        raise ValidationError("A source field path must contain between 1 and 2,000 characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValidationError("A source field path cannot contain control characters.")
    return value


@dataclass(frozen=True, slots=True)
class ABoxMappingRuleInput:
    method: ABoxMappingMethod
    source_field_path: str
    target_stable_element_id: str

    def validate(self) -> None:
        validate_source_field_path(self.source_field_path)
        validate_stable_element_id(self.target_stable_element_id)


def validate_abox_mapping_rules(
    *,
    target_kind: TBoxElementKind,
    target_stable_element_id: str,
    property_parent_by_id: dict[str, str],
    allowed_source_field_paths: frozenset[str],
    rules: tuple[ABoxMappingRuleInput, ...],
) -> None:
    validate_stable_element_id(target_stable_element_id)
    if not 1 <= len(rules) <= 200:
        raise ValidationError("An A-Box binding requires between 1 and 200 mapping rules.")
    seen_targets: set[tuple[ABoxMappingMethod, str]] = set()
    for rule in rules:
        rule.validate()
        if rule.source_field_path not in allowed_source_field_paths:
            raise ValidationError(
                "A mapping field is not present in the server-returned Dataset schema."
            )
        identity = (rule.method, rule.target_stable_element_id)
        if identity in seen_targets:
            if rule.method is ABoxMappingMethod.SUBJECT_ID:
                raise ValidationError("A Class binding can contain at most one SUBJECT_ID rule.")
            raise ValidationError("A mapping target and method can appear only once.")
        seen_targets.add(identity)
        if target_kind is TBoxElementKind.CLASS:
            if rule.method is ABoxMappingMethod.SUBJECT_ID:
                if rule.target_stable_element_id != target_stable_element_id:
                    raise ValidationError("SUBJECT_ID must target the selected Class.")
            elif rule.method is ABoxMappingMethod.PROPERTY:
                if property_parent_by_id.get(rule.target_stable_element_id) != (
                    target_stable_element_id
                ):
                    raise ValidationError(
                        "PROPERTY must target a Property owned by the selected Class."
                    )
            else:
                raise ValidationError("Class bindings accept only SUBJECT_ID or PROPERTY rules.")
        elif target_kind is TBoxElementKind.RELATION:
            if rule.method not in {
                ABoxMappingMethod.EDGE_LINK,
                ABoxMappingMethod.EDGE_PROPERTY,
            }:
                raise ValidationError(
                    "Relation bindings accept only EDGE_LINK or EDGE_PROPERTY rules."
                )
        else:
            raise ValidationError("Only accepted Class or Relation elements can be bound.")


@dataclass(frozen=True, slots=True)
class TBoxBlockPrecedence:
    """Deterministic precedence key used by the overlay fold."""

    weight: int
    ordinal: int

    def __post_init__(self) -> None:
        if self.weight < 0 or self.weight > 100:
            raise ValidationError("T-Box block weight must be between 0 and 100.")
        if self.ordinal < 0:
            raise ValidationError("T-Box block ordinal must be non-negative.")


def require_studio_transition(
    current: StudioDraftState,
    target: StudioDraftState,
) -> None:
    allowed: dict[StudioDraftState, frozenset[StudioDraftState]] = {
        StudioDraftState.DRAFT: frozenset(
            {
                StudioDraftState.REVIEW,
                StudioDraftState.DISCARDED,
            }
        ),
        StudioDraftState.REVIEW: frozenset(
            {
                StudioDraftState.DRAFT,
                StudioDraftState.PUBLISHED,
                StudioDraftState.DISCARDED,
            }
        ),
        StudioDraftState.PUBLISHED: frozenset(),
        StudioDraftState.DISCARDED: frozenset(),
    }
    if target not in allowed[current]:
        raise ConflictError(
            f"Knowledge Studio draft cannot transition from {current.value} to {target.value}."
        )
