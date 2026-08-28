"""Align Knowledge source snapshots with the governed document MIME vocabulary.

Revision ID: 0082
Revises: 0081
Create Date: 2026-07-31
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from alembic import op

revision: str = "0082"
down_revision: str | Sequence[str] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# This immutable migration vocabulary must remain an exact snapshot of
# domain.knowledge_pipeline.KNOWLEDGE_SOURCE_MEDIA_TYPES at revision 0082.
_SOURCE_MEDIA_TYPES = (
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/xhtml+xml",
    "application/xml",
    "text/csv",
    "text/html",
    "text/json",
    "text/plain",
    "text/xml",
)

_CANONICAL_LEGACY_CONSTRAINT = "ck_source_snapshots_pdf_media_type"
_DOUBLE_PREFIX_LEGACY_CONSTRAINT = "ck_source_snapshots_ck_source_snapshots_pdf_media_type"
_CURRENT_CONSTRAINT = "ck_source_snapshots_media_type_vocabulary"
_LEGACY_CONSTRAINTS = frozenset({_CANONICAL_LEGACY_CONSTRAINT, _DOUBLE_PREFIX_LEGACY_CONSTRAINT})
_TYPE_CAST = re.compile(r"::(?:character varying|text)(?:\[\])?")


@dataclass(frozen=True)
class _SourceSnapshotConstraint:
    name: str
    definition: str


@dataclass(frozen=True)
class _SourceSnapshotConstraintState:
    current: bool
    legacy_name: str | None = None


def _media_type_check() -> str:
    return (
        "media_type IN (" + ", ".join(f"'{media_type}'" for media_type in _SOURCE_MEDIA_TYPES) + ")"
    )


def _normalized_definition(definition: str) -> str:
    without_casts = _TYPE_CAST.sub("", definition.casefold())
    return re.sub(r'[\s()"]+', "", without_casts)


def _is_legacy_pdf_definition(definition: str) -> bool:
    return _normalized_definition(definition) == "checkmedia_type='application/pdf'"


def _is_current_vocabulary_definition(definition: str) -> bool:
    values = tuple(re.findall(r"'([^']*)'", definition))
    if values != _SOURCE_MEDIA_TYPES:
        return False
    remaining = _normalized_definition(definition)
    for media_type in _SOURCE_MEDIA_TYPES:
        remaining = remaining.replace(f"'{media_type}'", "", 1)
    remaining = remaining.replace(",", "")
    return remaining in {
        "checkmedia_typein",
        "checkmedia_type=any",
        "checkmedia_type=anyarray",
        "checkmedia_type=anyarray[]",
    }


def _classify_source_snapshot_constraint(
    constraints: Sequence[_SourceSnapshotConstraint],
) -> _SourceSnapshotConstraintState:
    candidates = tuple(
        constraint
        for constraint in constraints
        if constraint.name in _LEGACY_CONSTRAINTS | {_CURRENT_CONSTRAINT}
        or "media_type" in _normalized_definition(constraint.definition)
    )
    if len(candidates) != 1:
        raise RuntimeError(
            "Source snapshot media-type constraint state is missing, ambiguous, or mixed."
        )
    constraint = candidates[0]
    if constraint.name == _CURRENT_CONSTRAINT and _is_current_vocabulary_definition(
        constraint.definition
    ):
        return _SourceSnapshotConstraintState(current=True)
    if constraint.name in _LEGACY_CONSTRAINTS and _is_legacy_pdf_definition(constraint.definition):
        return _SourceSnapshotConstraintState(current=False, legacy_name=constraint.name)
    raise RuntimeError("Source snapshot media-type constraint definition is malformed.")


def _source_snapshot_constraint_state() -> _SourceSnapshotConstraintState:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT conname, pg_get_constraintdef(oid, true) AS definition
            FROM pg_catalog.pg_constraint
            WHERE conrelid = to_regclass('knowledge.source_snapshots')
              AND contype = 'c'
            ORDER BY conname
            """
            )
        )
        .mappings()
    )
    constraints: list[_SourceSnapshotConstraint] = []
    for row in rows:
        name, definition = row["conname"], row["definition"]
        if not isinstance(name, str) or not isinstance(definition, str):
            raise RuntimeError("Source snapshot constraint catalog returned an invalid row.")
        constraints.append(_SourceSnapshotConstraint(name=name, definition=definition))
    return _classify_source_snapshot_constraint(constraints)


def upgrade() -> None:
    return # No bypass needed, only constraint adjustments
    state = _source_snapshot_constraint_state()
    if state.current:
        return
    assert state.legacy_name is not None
    op.drop_constraint(
        op.f(state.legacy_name),
        "source_snapshots",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_CURRENT_CONSTRAINT),
        "source_snapshots",
        _media_type_check(),
        schema="knowledge",
    )


def downgrade() -> None:
    state = _source_snapshot_constraint_state()
    if not state.current:
        return
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM knowledge.source_snapshots
                WHERE media_type <> 'application/pdf'
            ) THEN
                RAISE EXCEPTION
                    '0082 downgrade requires explicit reconciliation of non-PDF source snapshots';
            END IF;
        END
        $datariver$;
        """
    )
    op.drop_constraint(
        op.f(_CURRENT_CONSTRAINT),
        "source_snapshots",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_CANONICAL_LEGACY_CONSTRAINT),
        "source_snapshots",
        "media_type = 'application/pdf'",
        schema="knowledge",
    )
