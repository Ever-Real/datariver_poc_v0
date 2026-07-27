from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from datariver.domain.common import ConflictError, ValidationError


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
