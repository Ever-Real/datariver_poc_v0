from __future__ import annotations

import pytest

from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.knowledge_studio import (
    StudioDraftState,
    TBoxBlockPrecedence,
    require_studio_transition,
    validate_endpoint_alias,
)


@pytest.mark.parametrize(
    "value",
    [
        "semiconductor_materials",
        "a12",
        "metadata_lineage_2026",
    ],
)
def test_endpoint_alias_accepts_the_approved_ascii_contract(value: str) -> None:
    assert validate_endpoint_alias(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "ab",
        "1graph",
        "Graph",
        "graph-name",
        "graph name",
        "그래프",
        "a" * 101,
    ],
)
def test_endpoint_alias_rejects_values_outside_the_approved_contract(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_endpoint_alias(value)


def test_tbox_precedence_enforces_weight_and_ordinal_bounds() -> None:
    assert sorted(
        [
            TBoxBlockPrecedence(weight=50, ordinal=2),
            TBoxBlockPrecedence(weight=90, ordinal=0),
            TBoxBlockPrecedence(weight=50, ordinal=3),
        ],
        key=lambda value: (value.weight, value.ordinal),
    )[-1] == TBoxBlockPrecedence(weight=90, ordinal=0)

    with pytest.raises(ValidationError):
        TBoxBlockPrecedence(weight=101, ordinal=0)
    with pytest.raises(ValidationError):
        TBoxBlockPrecedence(weight=50, ordinal=-1)


def test_studio_lifecycle_requires_review_before_publication() -> None:
    require_studio_transition(StudioDraftState.DRAFT, StudioDraftState.REVIEW)
    require_studio_transition(StudioDraftState.REVIEW, StudioDraftState.PUBLISHED)
    require_studio_transition(StudioDraftState.DRAFT, StudioDraftState.DISCARDED)

    with pytest.raises(ConflictError):
        require_studio_transition(StudioDraftState.DRAFT, StudioDraftState.PUBLISHED)
    with pytest.raises(ConflictError):
        require_studio_transition(StudioDraftState.DISCARDED, StudioDraftState.DRAFT)
