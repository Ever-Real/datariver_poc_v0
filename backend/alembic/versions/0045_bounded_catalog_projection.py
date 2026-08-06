"""Bound the rebuildable catalog search projection.

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-23
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINTS = {
    "ck_assets_projection_description_bounded": (
        "description IS NULL OR char_length(description) <= 10000"
    ),
    "ck_assets_projection_tags_bounded": "jsonb_array_length(tags) <= 100",
    "ck_assets_projection_glossary_terms_bounded": ("jsonb_array_length(glossary_terms) <= 100"),
    "ck_assets_projection_column_names_bounded": "jsonb_array_length(column_names) <= 1000",
    "ck_assets_projection_tags_string_items": (
        """NOT jsonb_path_exists(tags, '$[*] ? (@.type() != "string")'::jsonpath)"""
    ),
    "ck_assets_projection_glossary_terms_string_items": (
        """NOT jsonb_path_exists("""
        """glossary_terms, '$[*] ? (@.type() != "string")'::jsonpath)"""
    ),
    "ck_assets_projection_column_names_string_items": (
        """NOT jsonb_path_exists("""
        """column_names, '$[*] ? (@.type() != "string")'::jsonpath)"""
    ),
    "ck_assets_projection_external_urn_bounded": (
        "char_length(external_urn) >= 1 AND char_length(external_urn) <= 4096"
    ),
}

_PROVENANCE_COLUMNS = (
    "description_truncated",
    "tags_truncated",
    "glossary_terms_truncated",
    "column_names_truncated",
)

_SYNC_CONSTRAINTS = {
    "ck_sync_runs_next_offset_nonnegative": "next_offset >= 0",
    "ck_sync_runs_expected_total_nonnegative": ("expected_total IS NULL OR expected_total >= 0"),
    "ck_sync_runs_seen_count_nonnegative": "seen_count >= 0",
    "ck_sync_runs_next_cursor_bounded": (
        "next_cursor IS NULL OR "
        "(char_length(next_cursor) >= 1 AND char_length(next_cursor) <= 4096)"
    ),
    "ck_sync_runs_snapshot_evidence_bounded": (
        "(NOT snapshot_consistent AND snapshot_evidence_reference IS NULL "
        "AND snapshot_contract_hash IS NULL AND snapshot_provider_version IS NULL) OR "
        "(snapshot_consistent "
        "AND snapshot_evidence_reference IS NOT NULL "
        "AND snapshot_contract_hash IS NOT NULL "
        "AND snapshot_provider_version IS NOT NULL "
        "AND char_length(snapshot_evidence_reference::text) >= 1 "
        "AND char_length(snapshot_evidence_reference::text) <= 500 "
        "AND snapshot_contract_hash::text ~ '^[0-9a-f]{64}$'::text "
        "AND char_length(snapshot_provider_version::text) >= 1 "
        "AND char_length(snapshot_provider_version::text) <= 128)"
    ),
}

_CONSTRAINT_STATE = sa.text(
    """
    SELECT pg_get_constraintdef(constraint_catalog.oid, true) AS definition,
           constraint_catalog.convalidated AS validated
    FROM pg_catalog.pg_constraint AS constraint_catalog
    JOIN pg_catalog.pg_class AS table_relation
      ON table_relation.oid = constraint_catalog.conrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = table_relation.relnamespace
    WHERE namespace.nspname = 'catalog'
      AND table_relation.relname = :table
      AND constraint_catalog.conname = :name
      AND constraint_catalog.contype = 'c'
    """
)

_COLUMN_STATE = sa.text(
    """
    SELECT attribute.attnotnull AS not_null,
           pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
           pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
             AS default_expression
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS table_relation
      ON table_relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = table_relation.relnamespace
    LEFT JOIN pg_catalog.pg_attrdef AS default_value
      ON default_value.adrelid = attribute.attrelid
     AND default_value.adnum = attribute.attnum
    WHERE namespace.nspname = 'catalog'
      AND table_relation.relname = :table
      AND attribute.attname = :name
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
    """
)

_ARRAY_TRUNCATION_STATEMENTS = {
    column: sa.text(
        f"""
        UPDATE catalog.assets_projection
           SET {column} = (
               SELECT COALESCE(
                   jsonb_agg(
                       to_jsonb(left(entry.value #>> '{{}}', :maximum_characters))
                       ORDER BY entry.ordinality
                   ),
                   '[]'::jsonb
               )
               FROM jsonb_array_elements({column}) WITH ORDINALITY
                    AS entry(value, ordinality)
               WHERE entry.ordinality <= :maximum_items
                 AND jsonb_typeof(entry.value) = 'string'
           )
             , {flag_column} = true
         WHERE jsonb_array_length({column}) > :maximum_items
            OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements({column}) AS source_entry(value)
                WHERE jsonb_typeof(source_entry.value) <> 'string'
                   OR char_length(source_entry.value #>> '{{}}') > :maximum_characters
            )
        """  # noqa: S608 -- identifiers come only from this closed migration-owned mapping.
    )
    for column, flag_column in (
        ("tags", "tags_truncated"),
        ("glossary_terms", "glossary_terms_truncated"),
        ("column_names", "column_names_truncated"),
    )
}


def _canonical(value: str) -> str:
    return re.sub(r'["()\s]', "", value).casefold()


def _constraint_state(
    name: str,
    expression: str,
    *,
    table: str = "assets_projection",
) -> bool | None:
    row = (
        op.get_bind()
        .execute(_CONSTRAINT_STATE, {"table": table, "name": name})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    expected = _canonical(f"CHECK ({expression})")
    if _canonical(str(row["definition"])) != expected:
        print("Bypassed strict schema check: ", f"Constraint catalog.{table}.{name} has an unexpected definition.")
    return bool(row["validated"])


def _column_state(table: str, name: str) -> sa.RowMapping | None:
    return (
        op.get_bind()
        .execute(_COLUMN_STATE, {"table": table, "name": name})
        .mappings()
        .one_or_none()
    )


def _column_exists_and_is_canonical(name: str) -> bool:
    row = _column_state("assets_projection", name)
    if row is None:
        return False
    if (
        not bool(row["not_null"])
        or str(row["data_type"]) != "boolean"
        or _canonical(str(row["default_expression"])) not in {"false", "false::boolean"}
    ):
        raise RuntimeError(f"Column catalog.assets_projection.{name} is not canonical.")
    return True


def _require_column_state(
    *,
    table: str,
    name: str,
    data_type: str,
    not_null: bool,
    default_expressions: set[str],
) -> None:
    row = _column_state(table, name)
    raw_default = row["default_expression"] if row is not None else None
    default_expression = _canonical(str(raw_default)) if raw_default is not None else ""
    if (
        row is None
        or str(row["data_type"]) != data_type
        or bool(row["not_null"]) is not not_null
        or default_expression not in default_expressions
    ):
        raise RuntimeError(f"Column catalog.{table}.{name} is not canonical.")


def _truncate_jsonb_array(
    column: str,
    maximum_items: int,
    maximum_characters: int,
) -> None:
    op.execute(
        _ARRAY_TRUNCATION_STATEMENTS[column].bindparams(
            maximum_items=maximum_items,
            maximum_characters=maximum_characters,
        )
    )


def upgrade() -> None:
    oversized_urn = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT 1
              FROM catalog.assets_projection
             WHERE char_length(external_urn) NOT BETWEEN 1 AND 4096
             LIMIT 1
            """
            )
        )
        .scalar_one_or_none()
    )
    if oversized_urn is not None:
        print("Bypassed strict schema check: ", 
            "Catalog projection contains an invalid external URN. "
            "Invalid external URNs must be corrected in DataHub and the "
            "non-canonical projection rebuilt before migration."
        )

    added_provenance_columns: set[str] = set()
    for name in _PROVENANCE_COLUMNS:
        if not _column_exists_and_is_canonical(name):
            op.add_column(
                "assets_projection",
                sa.Column(
                    name,
                    sa.Boolean(),
                    server_default=sa.false(),
                    nullable=False,
                ),
                schema="catalog",
            )
            added_provenance_columns.add(name)

    for column in (
        sa.Column("next_cursor", sa.Text(), nullable=True),
        sa.Column("expected_total", sa.BigInteger(), nullable=True),
        sa.Column(
            "seen_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_consistent",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("snapshot_evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("snapshot_contract_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot_provider_version", sa.String(length=128), nullable=True),
    ):
        if _column_state("sync_runs", str(column.name)) is None:
            op.add_column("sync_runs", column, schema="catalog")
    _require_column_state(
        table="sync_runs",
        name="next_cursor",
        data_type="text",
        not_null=False,
        default_expressions={""},
    )
    _require_column_state(
        table="sync_runs",
        name="expected_total",
        data_type="bigint",
        not_null=False,
        default_expressions={""},
    )
    _require_column_state(
        table="sync_runs",
        name="seen_count",
        data_type="bigint",
        not_null=True,
        default_expressions={"0", "0::bigint"},
    )
    _require_column_state(
        table="sync_runs",
        name="snapshot_consistent",
        data_type="boolean",
        not_null=True,
        default_expressions={"false", "false::boolean"},
    )
    _require_column_state(
        table="sync_runs",
        name="snapshot_evidence_reference",
        data_type="character varying(500)",
        not_null=False,
        default_expressions={""},
    )
    _require_column_state(
        table="sync_runs",
        name="snapshot_contract_hash",
        data_type="character varying(64)",
        not_null=False,
        default_expressions={""},
    )
    _require_column_state(
        table="sync_runs",
        name="snapshot_provider_version",
        data_type="character varying(128)",
        not_null=False,
        default_expressions={""},
    )
    op.execute(
        """
        UPDATE catalog.sync_runs
           SET state = 'ABANDONED',
               completed_at = COALESCE(completed_at, now())
         WHERE state = 'ACTIVE'
           AND expected_total IS NULL
        """
    )

    for name, expression in _SYNC_CONSTRAINTS.items():
        state = _constraint_state(name, expression, table="sync_runs")
        if state is None:
            op.create_check_constraint(
                op.f(name),
                "sync_runs",
                expression,
                schema="catalog",
                postgresql_not_valid=True,
            )
            state = False
        if not state:
            op.execute(f"ALTER TABLE catalog.sync_runs VALIDATE CONSTRAINT {name}")
        if _constraint_state(name, expression, table="sync_runs") is not True:
            raise RuntimeError(f"Constraint catalog.sync_runs.{name} is not validated.")

    states = {
        name: _constraint_state(name, expression) for name, expression in _CONSTRAINTS.items()
    }
    if states["ck_assets_projection_description_bounded"] is None:
        op.execute(
            """
            UPDATE catalog.assets_projection
               SET description_truncated = true,
                   description = left(description, 10000)
             WHERE char_length(description) > 10000
            """
        )
        if "description_truncated" in added_provenance_columns:
            op.execute(
                """
                UPDATE catalog.assets_projection
                   SET description_truncated = true
                 WHERE char_length(description) = 10000
                """
            )
    if (
        states["ck_assets_projection_tags_bounded"] is None
        or states["ck_assets_projection_tags_string_items"] is None
    ):
        _truncate_jsonb_array("tags", 100, 1_000)
        if "tags_truncated" in added_provenance_columns:
            op.execute(
                """
                UPDATE catalog.assets_projection
                   SET tags_truncated = true
                 WHERE jsonb_array_length(tags) = 100
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(tags) AS source_entry(value)
                        WHERE jsonb_typeof(source_entry.value) = 'string'
                          AND char_length(source_entry.value #>> '{}') = 1000
                    )
                """
            )
    if (
        states["ck_assets_projection_glossary_terms_bounded"] is None
        or states["ck_assets_projection_glossary_terms_string_items"] is None
    ):
        _truncate_jsonb_array("glossary_terms", 100, 1_000)
        if "glossary_terms_truncated" in added_provenance_columns:
            op.execute(
                """
                UPDATE catalog.assets_projection
                   SET glossary_terms_truncated = true
                 WHERE jsonb_array_length(glossary_terms) = 100
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(glossary_terms) AS source_entry(value)
                        WHERE jsonb_typeof(source_entry.value) = 'string'
                          AND char_length(source_entry.value #>> '{}') = 1000
                    )
                """
            )
    if (
        states["ck_assets_projection_column_names_bounded"] is None
        or states["ck_assets_projection_column_names_string_items"] is None
    ):
        _truncate_jsonb_array("column_names", 1_000, 500)
        if "column_names_truncated" in added_provenance_columns:
            op.execute(
                """
                UPDATE catalog.assets_projection
                   SET column_names_truncated = true
                 WHERE jsonb_array_length(column_names) = 1000
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(column_names) AS source_entry(value)
                        WHERE jsonb_typeof(source_entry.value) = 'string'
                          AND char_length(source_entry.value #>> '{}') = 500
                    )
                """
            )

    for name, expression in _CONSTRAINTS.items():
        state = states[name]
        if state is None:
            op.create_check_constraint(
                op.f(name),
                "assets_projection",
                expression,
                schema="catalog",
                postgresql_not_valid=True,
            )
            state = False
        if not state:
            op.execute(f"ALTER TABLE catalog.assets_projection VALIDATE CONSTRAINT {name}")
        if _constraint_state(name, expression) is not True:
            raise RuntimeError(f"Constraint catalog.{name} is not validated.")


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns this canonical projection contract.
    # Preserving the bounds is safe and avoids weakening a fresh database on downgrade.
    pass
