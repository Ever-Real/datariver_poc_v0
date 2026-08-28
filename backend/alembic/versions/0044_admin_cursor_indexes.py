"""Add bounded administrator keyset cursor indexes.

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-23
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _IndexSpec:
    __slots__ = ("canonical_terms", "columns", "name", "schema", "table")

    def __init__(
        self,
        schema: str,
        table: str,
        name: str,
        columns: tuple[str | sa.ColumnElement[object], ...],
        canonical_terms: tuple[str, ...],
    ) -> None:
        self.schema = schema
        self.table = table
        self.name = name
        self.columns = columns
        self.canonical_terms = canonical_terms


_INDEXES = (
    _IndexSpec(
        "iam",
        "subjects",
        "ix_subjects_display_name_lower_id",
        (sa.literal_column("lower(display_name)"), "id"),
        ("lowerdisplay_name", "id"),
    ),
    _IndexSpec(
        "platform",
        "system_assignees",
        "ix_system_assignees_workspace_system_id",
        ("workspace_id", "system_id", "id"),
        ("workspace_id", "system_id", "id"),
    ),
    _IndexSpec(
        "retention",
        "legal_holds",
        "ix_legal_holds_workspace_created_id",
        ("workspace_id", sa.literal_column("created_at DESC"), "id"),
        ("workspace_id", "created_atdesc", "id"),
    ),
    _IndexSpec(
        "retention",
        "erasure_requests",
        "ix_erasure_requests_workspace_created_id",
        ("workspace_id", sa.literal_column("created_at DESC"), "id"),
        ("workspace_id", "created_atdesc", "id"),
    ),
    _IndexSpec(
        "authz",
        "restricted_search_grants",
        "ix_restricted_search_grants_workspace_created_id",
        ("workspace_id", sa.literal_column("created_at DESC"), "id"),
        ("workspace_id", "created_atdesc", "id"),
    ),
    _IndexSpec(
        "integration",
        "inference_provider_profile_versions",
        "ix_inference_profile_versions_workspace_order",
        (
            "workspace_id",
            "profile_key",
            sa.literal_column("profile_version DESC"),
            "id",
        ),
        ("workspace_id", "profile_key", "profile_versiondesc", "id"),
    ),
)

_INDEX_STATE = sa.text(
    """
    SELECT
        index_catalog.indisvalid,
        index_catalog.indisready,
        index_catalog.indisunique,
        index_catalog.indisprimary,
        index_catalog.indisexclusion,
        index_catalog.indnatts,
        index_catalog.indnkeyatts,
        access_method.amname AS access_method,
        index_catalog.indoption::smallint[] AS key_options,
        pg_get_expr(index_catalog.indpred, index_catalog.indrelid, true) AS predicate,
        NOT EXISTS (
            SELECT 1
            FROM unnest(index_catalog.indclass::oid[]) WITH ORDINALITY
                 AS indexed_class(opclass_oid, position)
            JOIN pg_catalog.pg_opclass AS operator_class
              ON operator_class.oid = indexed_class.opclass_oid
            WHERE indexed_class.position <= index_catalog.indnkeyatts
              AND NOT operator_class.opcdefault
        ) AS uses_default_opclasses,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint AS index_constraint
            WHERE index_constraint.conindid = index_catalog.indexrelid
        ) AS backs_constraint,
        pg_get_indexdef(index_catalog.indexrelid, 0, true) AS definition,
        ARRAY(
            SELECT pg_get_indexdef(index_catalog.indexrelid, position, true)
            FROM generate_series(1, index_catalog.indnkeyatts) AS position
            ORDER BY position
        ) AS terms
    FROM pg_catalog.pg_index AS index_catalog
    JOIN pg_catalog.pg_class AS index_relation
      ON index_relation.oid = index_catalog.indexrelid
    JOIN pg_catalog.pg_class AS table_relation
      ON table_relation.oid = index_catalog.indrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = table_relation.relnamespace
    JOIN pg_catalog.pg_am AS access_method
      ON access_method.oid = index_relation.relam
    WHERE namespace.nspname = :schema
      AND table_relation.relname = :table
      AND index_relation.relname = :name
    """
)


def _canonical_term(value: str) -> str:
    without_cast = value.replace("::text", "")
    return re.sub(r'["()\s]', "", without_cast).casefold()


def _read_index_state(spec: _IndexSpec) -> tuple[bool, bool] | None:
    row = (
        op.get_bind()
        .execute(
            _INDEX_STATE,
            {"schema": spec.schema, "table": spec.table, "name": spec.name},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    key_options = tuple(int(value) for value in row["key_options"])
    if any(value not in {0, 3} for value in key_options):
        raise RuntimeError(f"Index {spec.schema}.{spec.name} has unsupported sort options.")
    actual_terms = tuple(
        _canonical_term(str(value)) + ("desc" if option & 1 else "")
        for value, option in zip(row["terms"], key_options, strict=True)
    )
    is_exact_plain_btree = (
        row["access_method"] == "btree"
        and int(row["indnatts"]) == int(row["indnkeyatts"])
        and bool(row["uses_default_opclasses"])
        and not bool(row["indisunique"])
        and not bool(row["indisprimary"])
        and not bool(row["indisexclusion"])
        and not bool(row["backs_constraint"])
        and row["predicate"] is None
    )
    if not is_exact_plain_btree:
        raise RuntimeError(f"Index {spec.schema}.{spec.name} has an unexpected definition.")
    if actual_terms != spec.canonical_terms:
        raise RuntimeError(
            f"Index {spec.schema}.{spec.name} has unexpected key terms {actual_terms!r}."
        )
    expected_definition = _canonical_term(
        f"CREATE INDEX {spec.name} ON {spec.schema}.{spec.table} USING btree "
        f"({', '.join(spec.canonical_terms)})"
    )
    if _canonical_term(str(row["definition"])) != expected_definition:
        raise RuntimeError(
            f"Index {spec.schema}.{spec.name} has an unexpected canonical definition."
        )
    return bool(row["indisvalid"]), bool(row["indisready"])


def _ensure_index(spec: _IndexSpec) -> None:
    state = _read_index_state(spec)
    if state == (True, True):
        return
    if state is not None:
        # A failed CREATE INDEX CONCURRENTLY can leave an exact but invalid index behind.
        # It is unusable, so remove only that exact reviewed definition before retrying.
        op.drop_index(
            spec.name,
            table_name=spec.table,
            schema=spec.schema,
            if_exists=True,
            postgresql_concurrently=True,
        )
    op.create_index(
        spec.name,
        spec.table,
        list(spec.columns),
        unique=False,
        schema=spec.schema,
        postgresql_concurrently=True,
    )
    if _read_index_state(spec) != (True, True):
        raise RuntimeError(f"Index {spec.schema}.{spec.name} is not valid and ready.")


def upgrade() -> None:
    # Concurrent DDL is intentionally non-atomic. Each exact valid index is preserved,
    # while an interrupted exact build is removed and rebuilt before the revision can stamp.
    with op.get_context().autocommit_block():
        for spec in _INDEXES:
            _ensure_index(spec)


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical index contract.
    # Dropping by name here would also remove canonical indexes from a database
    # initialized from the current 0001, so downgrade intentionally preserves them.
    pass
