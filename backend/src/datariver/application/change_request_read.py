from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from datariver.domain.governance import ChangeState


class ChangeRequestStateGroup(StrEnum):
    """Bounded server-owned groupings for Change Request read projections."""

    REGISTERED = "REGISTERED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


CHANGE_REQUEST_STATES_BY_GROUP: Final[Mapping[ChangeRequestStateGroup, frozenset[ChangeState]]] = {
    ChangeRequestStateGroup.REGISTERED: frozenset({ChangeState.REGISTERED}),
    ChangeRequestStateGroup.IN_PROGRESS: frozenset(
        {
            ChangeState.IN_REVIEW,
            ChangeState.TESTING,
            ChangeState.FINAL_REVIEW,
            ChangeState.APPLY_QUEUED,
            ChangeState.APPLYING,
            ChangeState.APPLY_FAILED,
            ChangeState.CHANGES_REQUESTED,
        }
    ),
    ChangeRequestStateGroup.COMPLETED: frozenset({ChangeState.APPLIED, ChangeState.COMPLETED}),
    ChangeRequestStateGroup.CLOSED: frozenset({ChangeState.REJECTED, ChangeState.CANCELLED}),
}

CHANGE_REQUEST_DASHBOARD_SCAN_LIMIT: Final = 2_000


@dataclass(frozen=True, slots=True)
class ChangeRequestStateCountSnapshot:
    counts: Mapping[ChangeState, int] | None
    complete: bool


def change_request_states_for_group(
    group: ChangeRequestStateGroup,
) -> frozenset[ChangeState]:
    return CHANGE_REQUEST_STATES_BY_GROUP[group]


def change_request_group_counts(
    state_counts: Mapping[ChangeState, int],
) -> dict[ChangeRequestStateGroup, int]:
    return {
        group: sum(state_counts.get(state, 0) for state in states)
        for group, states in CHANGE_REQUEST_STATES_BY_GROUP.items()
    }
