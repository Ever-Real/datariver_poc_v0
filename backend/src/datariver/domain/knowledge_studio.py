from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import (
    ConflictError,
    PreconditionFailedError,
    ValidationError,
)

DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION = "datariver-default-domains-v1"
DEFAULT_TBOX_BLOCK_WEIGHT = 50
DEFAULT_KNOWLEDGE_DOMAINS = (
    ("general", "General"),
    ("data-governance", "Data Governance"),
    ("research-development", "R&D"),
    ("finance", "Finance"),
    ("space-system", "Space System"),
)


def default_knowledge_domain_id(workspace_id: UUID, slug: str) -> UUID:
    """Return the migration-compatible identity for one workspace default domain."""

    value = f"{workspace_id}:knowledge-default-domain:{slug}".encode()
    return UUID(hashlib.md5(value, usedforsecurity=False).hexdigest())


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


class TBoxBlockKind(StrEnum):
    DIRECT = "DIRECT"
    DOCUMENT_SCHEMA = "DOCUMENT_SCHEMA"
    CATALOG_METADATA = "CATALOG_METADATA"
    ASSET_RELEASE = "ASSET_RELEASE"
    LLM_ASSISTANT = "LLM_ASSISTANT"


class TBoxOperationKind(StrEnum):
    UPSERT_ELEMENT = "UPSERT_ELEMENT"
    DELETE_ELEMENT = "DELETE_ELEMENT"
    SET_LAYOUT = "SET_LAYOUT"


class TBoxProposalMode(StrEnum):
    MERGE_INTO_CURRENT = "MERGE_INTO_CURRENT"
    APPEND_LAYER = "APPEND_LAYER"


class TBoxMergeStrategy(StrEnum):
    KEEP_ORIGINAL = "KEEP_ORIGINAL"
    ACCEPT_PROPOSAL = "ACCEPT_PROPOSAL"
    RESOLVE = "RESOLVE"


class TBoxMergeResolution(StrEnum):
    KEEP_ORIGINAL = "KEEP_ORIGINAL"
    ACCEPT_PROPOSAL = "ACCEPT_PROPOSAL"
    RENAME_PROPOSAL = "RENAME_PROPOSAL"


class StudioIngestionState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"


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


def validate_tbox_name(value: str, *, field_name: str) -> str:
    if value != value.strip() or not 1 <= len(value) <= 255:
        raise ValidationError(f"{field_name} must contain between 1 and 255 characters.")
    if not (("A" <= value[0] <= "Z") or ("a" <= value[0] <= "z")):
        raise ValidationError(f"{field_name} must start with an ASCII letter.")
    for character in value[1:]:
        if not (
            "A" <= character <= "Z"
            or "a" <= character <= "z"
            or "0" <= character <= "9"
            or character == "_"
        ):
            raise ValidationError(
                f"{field_name} may contain ASCII letters, digits and underscores."
            )
    return value


def validate_tbox_aliases(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > 50:
        raise ValidationError("A T-Box element can contain at most 50 aliases.")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value != value.strip() or not 1 <= len(value) <= 255:
            raise ValidationError("A T-Box alias must contain between 1 and 255 characters.")
        identity = value.casefold()
        if identity in seen:
            raise ValidationError("A T-Box alias can appear only once.")
        seen.add(identity)
        normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class TBoxElementInput:
    stable_element_id: str
    kind: TBoxElementKind
    canonical_name: str
    display_name: str
    parent_stable_element_id: str | None = None
    source_stable_element_id: str | None = None
    target_stable_element_id: str | None = None
    data_type: str | None = None
    nullable: bool | None = None
    definition: str | None = None
    aliases: tuple[str, ...] = ()
    unit: str | None = None
    vector_index_enabled: bool = False
    layout_x: float | None = None
    layout_y: float | None = None

    def validate(self) -> None:
        validate_stable_element_id(self.stable_element_id)
        validate_tbox_name(self.canonical_name, field_name="Canonical name")
        if self.display_name != self.display_name.strip() or not 1 <= len(self.display_name) <= 255:
            raise ValidationError("Display name must contain between 1 and 255 characters.")
        validate_tbox_aliases(self.aliases)
        if self.definition is not None and (
            self.definition != self.definition.strip() or not 1 <= len(self.definition) <= 4_000
        ):
            raise ValidationError("A T-Box definition must contain between 1 and 4,000 characters.")
        if self.unit is not None and (
            self.unit != self.unit.strip() or not 1 <= len(self.unit) <= 100
        ):
            raise ValidationError("A T-Box unit must contain between 1 and 100 characters.")
        if (self.layout_x is None) != (self.layout_y is None):
            raise ValidationError("T-Box layout coordinates must be supplied together.")
        if self.layout_x is not None and (
            abs(self.layout_x) > 100_000 or abs(self.layout_y or 0) > 100_000
        ):
            raise ValidationError("T-Box layout coordinates are outside the supported canvas.")
        if self.kind is TBoxElementKind.CLASS:
            if any(
                value is not None
                for value in (
                    self.parent_stable_element_id,
                    self.source_stable_element_id,
                    self.target_stable_element_id,
                    self.data_type,
                    self.nullable,
                    self.unit,
                )
            ):
                raise ValidationError("A Class cannot carry Property or Relation shape fields.")
            if self.vector_index_enabled:
                raise ValidationError("Only a textual Property can target a Vector Index.")
        elif self.kind is TBoxElementKind.PROPERTY:
            if (
                self.parent_stable_element_id is None
                or self.source_stable_element_id is not None
                or self.target_stable_element_id is not None
                or self.data_type is None
                or self.nullable is None
            ):
                raise ValidationError("A Property requires one parent Class and a data type.")
            validate_stable_element_id(self.parent_stable_element_id)
            validate_tbox_name(self.data_type, field_name="Property data type")
            if self.vector_index_enabled and self.data_type.upper() not in {
                "STRING",
                "TEXT",
            }:
                raise ValidationError("Vector Index targets must use the STRING or TEXT data type.")
        else:
            if (
                self.parent_stable_element_id is not None
                or self.source_stable_element_id is None
                or self.target_stable_element_id is None
                or self.data_type is not None
                or self.nullable is not None
                or self.unit is not None
                or self.vector_index_enabled
            ):
                raise ValidationError("A Relation requires source and target Classes only.")
            validate_stable_element_id(self.source_stable_element_id)
            validate_stable_element_id(self.target_stable_element_id)


@dataclass(frozen=True, slots=True)
class TBoxOperationInput:
    operation: TBoxOperationKind
    stable_element_id: str
    element: TBoxElementInput | None = None
    layout_x: float | None = None
    layout_y: float | None = None

    def validate(self) -> None:
        validate_stable_element_id(self.stable_element_id)
        if self.operation is TBoxOperationKind.UPSERT_ELEMENT:
            if (
                self.element is None
                or self.element.stable_element_id != self.stable_element_id
                or self.layout_x is not None
                or self.layout_y is not None
            ):
                raise ValidationError("UPSERT_ELEMENT requires one matching typed element.")
            self.element.validate()
            return
        if self.element is not None:
            raise ValidationError("Only UPSERT_ELEMENT accepts an element document.")
        if self.operation is TBoxOperationKind.DELETE_ELEMENT:
            if self.layout_x is not None or self.layout_y is not None:
                raise ValidationError("DELETE_ELEMENT cannot carry layout coordinates.")
            return
        if self.layout_x is None or self.layout_y is None:
            raise ValidationError("SET_LAYOUT requires both canvas coordinates.")
        if abs(self.layout_x) > 100_000 or abs(self.layout_y) > 100_000:
            raise ValidationError("T-Box layout coordinates are outside the supported canvas.")


def validate_tbox_element_set(elements: tuple[TBoxElementInput, ...]) -> None:
    if len(elements) > 500:
        raise ValidationError("A T-Box Draft can contain at most 500 elements.")
    by_id: dict[str, TBoxElementInput] = {}
    names: set[tuple[TBoxElementKind, str]] = set()
    for element in elements:
        element.validate()
        if element.stable_element_id in by_id:
            raise ValidationError("A stable T-Box element ID can appear only once.")
        name_identity = (element.kind, element.canonical_name.casefold())
        if name_identity in names:
            raise ValidationError("A canonical T-Box name can appear only once per kind.")
        by_id[element.stable_element_id] = element
        names.add(name_identity)
    for element in elements:
        if element.kind is TBoxElementKind.PROPERTY:
            parent = by_id.get(element.parent_stable_element_id or "")
            if parent is None or parent.kind is not TBoxElementKind.CLASS:
                raise ValidationError("A Property parent must be an accepted Class.")
        elif element.kind is TBoxElementKind.RELATION:
            source = by_id.get(element.source_stable_element_id or "")
            target = by_id.get(element.target_stable_element_id or "")
            if (
                source is None
                or target is None
                or source.kind is not TBoxElementKind.CLASS
                or target.kind is not TBoxElementKind.CLASS
            ):
                raise ValidationError("Relation endpoints must be accepted Classes.")


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
