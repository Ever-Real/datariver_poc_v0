"""Add durable governed Catalog metadata recommendations.

Revision ID: 0101
Revises: 0100
Create Date: 2026-08-29 19:00:00.000000
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0101"
down_revision: str | Sequence[str] | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKSPACE = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"

_EXPECTED_COLUMNS = {
    "metadata_recommendations": {
        "workspace_id": ("uuid", True),
        "asset_id": ("uuid", True),
        "field_path_key": ("character varying(2000)", True),
        "vocabulary_id": ("uuid", True),
        "kind": ("character varying(16)", True),
        "source_version": ("character varying(255)", True),
        "provider_source_version": ("character varying(255)", True),
        "vocabulary_source_version": ("character varying(255)", True),
        "aspect_name": ("character varying(32)", True),
        "aspect_source_version": ("character varying(255)", True),
        "aspect_content_hash": ("character varying(64)", True),
        "target_binding_hash": ("character varying(64)", True),
        "input_context_hash": ("character varying(64)", True),
        "confidence": ("numeric(6,5)", True),
        "reason": ("character varying(2000)", True),
        "evidence": ("jsonb", True),
        "provider": ("character varying(128)", True),
        "model": ("character varying(128)", True),
        "prompt_version": ("character varying(128)", True),
        "rule_version": ("character varying(128)", True),
        "state": ("character varying(32)", True),
        "version": ("integer", True),
        "created_by": ("uuid", True),
        "decision_actor_id": ("uuid", False),
        "change_request_id": ("uuid", False),
        "decision_key_hash": ("character varying(64)", False),
        "decision_request_hash": ("character varying(64)", False),
        "decision_kind": ("character varying(16)", False),
        "decision_expected_version": ("integer", False),
        "id": ("uuid", True),
        "created_at": ("timestamp with time zone", True),
        "updated_at": ("timestamp with time zone", True),
    },
    "metadata_recommendation_events": {
        "workspace_id": ("uuid", True),
        "recommendation_id": ("uuid", True),
        "recommendation_version": ("integer", True),
        "decision": ("character varying(16)", True),
        "actor_id": ("uuid", True),
        "reason": ("character varying(2000)", False),
        "change_request_id": ("uuid", False),
        "request_hash": ("character varying(64)", True),
        "occurred_at": ("timestamp with time zone", True),
        "id": ("uuid", True),
    },
}
_EXPECTED_CONSTRAINTS = {
    "metadata_recommendations": {
        "pk_metadata_recommendations",
        "uq_metadata_recommendations_workspace_id_id",
        "uq_metadata_recommendations_semantic_key",
        "ck_metadata_recommendations_kind_vocabulary",
        "ck_metadata_recommendations_kind_aspect",
        "ck_metadata_recommendations_state_vocabulary",
        "ck_metadata_recommendations_field_path_key_bounded",
        "ck_metadata_recommendations_source_versions_bounded",
        "ck_metadata_recommendations_binding_hashes_sha256",
        "ck_metadata_recommendations_confidence_range",
        "ck_metadata_recommendations_reason_bounded",
        "ck_metadata_recommendations_evidence_bounded_array",
        "ck_metadata_recommendations_provider_provenance_bounded",
        "ck_metadata_recommendations_version_positive",
        "ck_metadata_recommendations_decision_reservation_shape",
        "ck_metadata_recommendations_decision_state_shape",
        "fk_metadata_recommendations_asset",
        "fk_metadata_recommendations_vocabulary",
        "fk_metadata_recommendations_creator",
        "fk_metadata_recommendations_decision_actor",
        "fk_metadata_recommendations_change_request",
        "fk_metadata_recommendations_workspace_id_workspaces",
    },
    "metadata_recommendation_events": {
        "pk_metadata_recommendation_events",
        "uq_metadata_recommendation_events_workspace_id_id",
        "uq_metadata_recommendation_events_version",
        "ck_metadata_recommendation_events_decision_vocabulary",
        "ck_metadata_recommendation_events_version_positive",
        "ck_metadata_recommendation_events_request_hash_sha256",
        "ck_metadata_recommendation_events_reason_bounded",
        "ck_metadata_recommendation_events_change_request_shape",
        "fk_metadata_recommendation_events_recommendation",
        "fk_metadata_recommendation_events_actor",
        "fk_metadata_recommendation_events_change_request",
        "fk_metadata_recommendation_events_workspace_id_workspaces",
    },
}
_EXPECTED_INDEXES = {
    "metadata_recommendations": {
        "pk_metadata_recommendations",
        "uq_metadata_recommendations_workspace_id_id",
        "uq_metadata_recommendations_semantic_key",
        "ix_metadata_recommendations_workspace_state_created",
    },
    "metadata_recommendation_events": {
        "pk_metadata_recommendation_events",
        "uq_metadata_recommendation_events_workspace_id_id",
        "uq_metadata_recommendation_events_version",
        "ix_metadata_recommendation_events_workspace_recommendation",
    },
}
_EXPECTED_DEFINITION_HASH = "521099576a6a7c00c841d83e8e0bc60f60a8a66abd430c41f866873f10892c7f"


class _CompleteStateMismatch(RuntimeError):
    """Exact Product-owned schema state differs from the governed contract."""


def _schema_state() -> str:
    if op.get_context().as_sql:
        return "ABSENT"
    bind = op.get_bind()
    owned = int(
        bind.execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = 'catalog'
                       AND c.relname IN ('metadata_recommendations',
                                         'metadata_recommendation_events'))
                  + (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'catalog' AND p.proname IN (
                       'validate_metadata_recommendation_insert',
                       'guard_metadata_recommendation_mutation',
                       'guard_metadata_recommendation_event_immutability',
                       'validate_metadata_recommendation_event_insert'))
                  + (SELECT count(*) FROM pg_policies WHERE schemaname = 'catalog'
                     AND tablename IN ('metadata_recommendations',
                                       'metadata_recommendation_events'))
                """
            )
        ).scalar_one()
    )
    if owned == 0:
        return "ABSENT"
    try:
        _assert_complete_state(bind)
    except (_CompleteStateMismatch, KeyError, TypeError, ValueError) as error:
        raise RuntimeError("0101 catalog recommendation schema is partial or malformed.") from error
    return "COMPLETE"


def _assert_complete_state(bind: sa.engine.Connection) -> None:
    for table_name, expected in _EXPECTED_COLUMNS.items():
        rows = bind.execute(
            sa.text(
                """
                SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull
                FROM pg_attribute a
                WHERE a.attrelid = to_regclass(:qualified_table)
                  AND a.attnum > 0 AND NOT a.attisdropped
                """
            ),
            {"qualified_table": f"catalog.{table_name}"},
        ).all()
        observed = {str(row[0]): (str(row[1]), bool(row[2])) for row in rows}
        if observed != expected:
            raise _CompleteStateMismatch(f"Unexpected columns for catalog.{table_name}.")

        constraints = {
            str(value)
            for value in bind.execute(
                sa.text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = to_regclass(:qualified_table)
                    """
                ),
                {"qualified_table": f"catalog.{table_name}"},
            ).scalars()
        }
        if constraints != _EXPECTED_CONSTRAINTS[table_name]:
            raise _CompleteStateMismatch(f"Unexpected constraints for catalog.{table_name}.")

        indexes = {
            str(value)
            for value in bind.execute(
                sa.text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'catalog' AND tablename = :table_name
                    """
                ),
                {"table_name": table_name},
            ).scalars()
        }
        if indexes != _EXPECTED_INDEXES[table_name]:
            raise _CompleteStateMismatch(f"Unexpected indexes for catalog.{table_name}.")

    row = bind.execute(
        sa.text(
            """
            SELECT
              (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'catalog'
                 AND c.relname IN ('metadata_recommendations',
                                   'metadata_recommendation_events')
                 AND c.relrowsecurity AND c.relforcerowsecurity) AS rls_count,
              (SELECT count(*) FROM pg_policies
               WHERE schemaname = 'catalog'
                 AND tablename IN ('metadata_recommendations',
                                   'metadata_recommendation_events')
                 AND policyname = 'workspace_isolation'
                 AND qual LIKE '%workspace_id%current_setting%'
                 AND with_check LIKE '%workspace_id%current_setting%') AS policy_count,
              (SELECT count(*) FROM pg_trigger
               WHERE tgrelid IN (to_regclass('catalog.metadata_recommendations'),
                                 to_regclass('catalog.metadata_recommendation_events'))
                 AND NOT tgisinternal
                 AND tgname IN ('validate_metadata_recommendation_insert',
                                'guard_metadata_recommendation_mutation',
                                'validate_metadata_recommendation_event_insert',
                                'guard_metadata_recommendation_event_immutability')
               ) AS trigger_count,
              (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname = 'catalog' AND p.proname IN (
                 'validate_metadata_recommendation_insert',
                 'guard_metadata_recommendation_mutation',
                 'guard_metadata_recommendation_event_immutability',
                 'validate_metadata_recommendation_event_insert')
                 AND p.prosecdef IS FALSE) AS function_count
            """
        )
    ).one()
    if tuple(int(value) for value in row) != (2, 2, 4, 4):
        raise _CompleteStateMismatch("Unexpected RLS, policy, trigger or function shape.")

    definitions = tuple(
        str(value)
        for value in bind.execute(
            sa.text(
                """
                WITH definitions AS (
                  SELECT 'constraint:' || conname || ':' || pg_get_constraintdef(oid, true) value
                  FROM pg_constraint
                  WHERE conrelid IN (to_regclass('catalog.metadata_recommendations'),
                                     to_regclass('catalog.metadata_recommendation_events'))
                  UNION ALL
                  SELECT 'index:' || indexname || ':' || indexdef
                  FROM pg_indexes WHERE schemaname = 'catalog'
                    AND tablename IN ('metadata_recommendations',
                                      'metadata_recommendation_events')
                  UNION ALL
                  SELECT 'trigger:' || tgname || ':' || pg_get_triggerdef(oid, true)
                  FROM pg_trigger
                  WHERE tgrelid IN (to_regclass('catalog.metadata_recommendations'),
                                    to_regclass('catalog.metadata_recommendation_events'))
                    AND NOT tgisinternal
                  UNION ALL
                  SELECT 'function:' || p.proname || ':' || pg_get_functiondef(p.oid)
                  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                  WHERE n.nspname = 'catalog' AND p.proname IN (
                    'validate_metadata_recommendation_insert',
                    'guard_metadata_recommendation_mutation',
                    'guard_metadata_recommendation_event_immutability',
                    'validate_metadata_recommendation_event_insert')
                  UNION ALL
                  SELECT 'policy:' || tablename || ':' || policyname || ':'
                         || coalesce(qual, '') || ':' || coalesce(with_check, '')
                  FROM pg_policies WHERE schemaname = 'catalog'
                    AND tablename IN ('metadata_recommendations',
                                      'metadata_recommendation_events')
                )
                SELECT value FROM definitions ORDER BY value
                """
            )
        ).scalars()
    )
    observed_hash = hashlib.sha256("\n".join(definitions).encode()).hexdigest()
    if observed_hash != _EXPECTED_DEFINITION_HASH:
        raise _CompleteStateMismatch("Unexpected governed SQL definition hash.")

    update_columns = {
        str(value)
        for value in bind.execute(
            sa.text(
                """
                SELECT column_name FROM information_schema.column_privileges
                WHERE grantor <> grantee AND grantee = 'datariver_app'
                  AND table_schema = 'catalog' AND table_name = 'metadata_recommendations'
                  AND privilege_type = 'UPDATE'
                """
            )
        ).scalars()
    }
    expected_update_columns = {
        "state",
        "version",
        "updated_at",
        "change_request_id",
        "decision_key_hash",
        "decision_request_hash",
        "decision_kind",
        "decision_expected_version",
        "decision_actor_id",
    }
    if update_columns != expected_update_columns:
        raise _CompleteStateMismatch("Unexpected recommendation update-column grants.")
    defaults = {
        (str(row[0]), str(row[1])): str(row[2])
        for row in bind.execute(
            sa.text(
                """
                SELECT c.relname, a.attname, pg_get_expr(d.adbin, d.adrelid)
                FROM pg_attrdef d
                JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
                JOIN pg_class c ON c.oid = d.adrelid
                WHERE d.adrelid IN (to_regclass('catalog.metadata_recommendations'),
                                    to_regclass('catalog.metadata_recommendation_events'))
                """
            )
        )
    }
    expected_defaults = {
        ("metadata_recommendations", "created_at"): "CURRENT_TIMESTAMP",
        ("metadata_recommendations", "updated_at"): "CURRENT_TIMESTAMP",
        ("metadata_recommendation_events", "occurred_at"): "CURRENT_TIMESTAMP",
    }
    if defaults != expected_defaults:
        raise _CompleteStateMismatch("Unexpected recommendation column defaults.")
    table_privileges = {
        (str(row[0]), str(row[1]))
        for row in bind.execute(
            sa.text(
                """
                SELECT table_name, privilege_type
                FROM information_schema.table_privileges
                WHERE grantee = 'datariver_app' AND table_schema = 'catalog'
                  AND table_name IN ('metadata_recommendations',
                                     'metadata_recommendation_events')
                """
            )
        )
    }
    expected_table_privileges = {
        ("metadata_recommendations", "SELECT"),
        ("metadata_recommendations", "INSERT"),
        ("metadata_recommendation_events", "SELECT"),
        ("metadata_recommendation_events", "INSERT"),
    }
    if table_privileges != expected_table_privileges:
        raise _CompleteStateMismatch("Unexpected recommendation table privileges.")


def upgrade() -> None:
    if _schema_state() == "COMPLETE":
        return
    op.create_table(
        "metadata_recommendations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("field_path_key", sa.String(length=2_000), nullable=False),
        sa.Column("vocabulary_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("provider_source_version", sa.String(length=255), nullable=False),
        sa.Column("vocabulary_source_version", sa.String(length=255), nullable=False),
        sa.Column("aspect_name", sa.String(length=32), nullable=False),
        sa.Column("aspect_source_version", sa.String(length=255), nullable=False),
        sa.Column("aspect_content_hash", sa.String(length=64), nullable=False),
        sa.Column("target_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("input_context_hash", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.Column("reason", sa.String(length=2_000), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("rule_version", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("decision_actor_id", sa.Uuid(), nullable=True),
        sa.Column("change_request_id", sa.Uuid(), nullable=True),
        sa.Column("decision_key_hash", sa.String(length=64), nullable=True),
        sa.Column("decision_request_hash", sa.String(length=64), nullable=True),
        sa.Column("decision_kind", sa.String(length=16), nullable=True),
        sa.Column("decision_expected_version", sa.Integer(), nullable=True),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('TAG', 'TERM')",
            name="kind_vocabulary",
        ),
        sa.CheckConstraint(
            "(kind = 'TAG' AND aspect_name = 'globalTags') OR "
            "(kind = 'TERM' AND aspect_name = 'glossaryTerms')",
            name="kind_aspect",
        ),
        sa.CheckConstraint(
            "state IN ('NEEDS_DECISION', 'APPROVED', 'REJECTED')",
            name="state_vocabulary",
        ),
        sa.CheckConstraint(
            "char_length(field_path_key) <= 2000 "
            "AND (field_path_key = '' OR field_path_key = btrim(field_path_key))",
            name="field_path_key_bounded",
        ),
        sa.CheckConstraint(
            "char_length(source_version) BETWEEN 1 AND 255 "
            "AND char_length(provider_source_version) BETWEEN 1 AND 255 "
            "AND char_length(vocabulary_source_version) BETWEEN 1 AND 255 "
            "AND char_length(aspect_source_version) BETWEEN 1 AND 255",
            name="source_versions_bounded",
        ),
        sa.CheckConstraint(
            "aspect_content_hash ~ '^[0-9a-f]{64}$' "
            "AND target_binding_hash ~ '^[0-9a-f]{64}$' "
            "AND input_context_hash ~ '^[0-9a-f]{64}$'",
            name="binding_hashes_sha256",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000 AND reason = btrim(reason)",
            name="reason_bounded",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'array' "
            "AND jsonb_array_length(evidence) BETWEEN 1 AND 10 "
            "AND NOT jsonb_path_exists(evidence, '$[*] ? (@.type() != \"string\")')",
            name="evidence_bounded_array",
        ),
        sa.CheckConstraint(
            "char_length(provider) BETWEEN 1 AND 128 "
            "AND char_length(model) BETWEEN 1 AND 128 "
            "AND char_length(prompt_version) BETWEEN 1 AND 128 "
            "AND char_length(rule_version) BETWEEN 1 AND 128",
            name="provider_provenance_bounded",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "(decision_actor_id IS NULL AND decision_key_hash IS NULL "
            "AND decision_request_hash IS NULL AND decision_kind IS NULL "
            "AND decision_expected_version IS NULL) OR "
            "(decision_key_hash ~ '^[0-9a-f]{64}$' "
            "AND decision_request_hash ~ '^[0-9a-f]{64}$' "
            "AND decision_actor_id IS NOT NULL "
            "AND decision_kind IN ('APPROVE', 'REJECT') "
            "AND decision_expected_version >= 1)",
            name="decision_reservation_shape",
        ),
        sa.CheckConstraint(
            "(state = 'NEEDS_DECISION' AND change_request_id IS NULL "
            "AND decision_actor_id IS NULL AND decision_kind IS NULL) OR "
            "(state = 'APPROVED' AND change_request_id IS NOT NULL "
            "AND decision_kind = 'APPROVE') OR "
            "(state = 'REJECTED' AND change_request_id IS NULL "
            "AND decision_kind = 'REJECT')",
            name="decision_state_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["catalog.assets_projection.workspace_id", "catalog.assets_projection.id"],
            name="fk_metadata_recommendations_asset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "vocabulary_id", "kind"],
            [
                "catalog.vocabulary_entries.workspace_id",
                "catalog.vocabulary_entries.id",
                "catalog.vocabulary_entries.kind",
            ],
            name="fk_metadata_recommendations_vocabulary",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_metadata_recommendations_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id"],
            ["governance.change_requests.workspace_id", "governance.change_requests.id"],
            name="fk_metadata_recommendations_change_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "decision_actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_metadata_recommendations_decision_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_metadata_recommendations"),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_metadata_recommendations_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "asset_id",
            "field_path_key",
            "vocabulary_id",
            "kind",
            "source_version",
            name="uq_metadata_recommendations_semantic_key",
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_metadata_recommendations_workspace_state_created",
        "metadata_recommendations",
        ["workspace_id", "state", "created_at", "id"],
        schema="catalog",
    )
    op.create_table(
        "metadata_recommendation_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=2_000), nullable=True),
        sa.Column("change_request_id", sa.Uuid(), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('PREVIEWED', 'APPROVED', 'REJECTED')",
            name="decision_vocabulary",
        ),
        sa.CheckConstraint(
            "recommendation_version >= 1",
            name="version_positive",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="request_hash_sha256",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR (char_length(reason) BETWEEN 1 AND 2000 AND reason = btrim(reason))",
            name="reason_bounded",
        ),
        sa.CheckConstraint(
            "(decision = 'APPROVED' AND change_request_id IS NOT NULL) OR "
            "(decision <> 'APPROVED' AND change_request_id IS NULL)",
            name="change_request_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "recommendation_id"],
            [
                "catalog.metadata_recommendations.workspace_id",
                "catalog.metadata_recommendations.id",
            ],
            name="fk_metadata_recommendation_events_recommendation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_metadata_recommendation_events_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id"],
            ["governance.change_requests.workspace_id", "governance.change_requests.id"],
            name="fk_metadata_recommendation_events_change_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_metadata_recommendation_events"),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_metadata_recommendation_events_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "recommendation_id",
            "recommendation_version",
            name="uq_metadata_recommendation_events_version",
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_metadata_recommendation_events_workspace_recommendation",
        "metadata_recommendation_events",
        ["workspace_id", "recommendation_id", "occurred_at", "id"],
        schema="catalog",
    )
    install_guards(op.execute)
    for table in ("metadata_recommendations", "metadata_recommendation_events"):
        op.execute(f"ALTER TABLE catalog.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catalog.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY workspace_isolation ON catalog.{table} "
            f"USING (workspace_id = {_WORKSPACE}) WITH CHECK (workspace_id = {_WORKSPACE})"
        )
    op.execute("GRANT SELECT, INSERT ON catalog.metadata_recommendations TO datariver_app")
    op.execute(
        "GRANT UPDATE (state, version, updated_at, change_request_id, decision_key_hash, "
        "decision_request_hash, decision_kind, decision_expected_version, decision_actor_id) "
        "ON catalog.metadata_recommendations TO datariver_app"
    )
    op.execute("GRANT SELECT, INSERT ON catalog.metadata_recommendation_events TO datariver_app")


def install_guards(execute: Callable[[str], object]) -> None:
    """Install the same protected SQL in 0101 and the regenerated canonical baseline."""

    execute(
        """
        CREATE FUNCTION catalog.validate_metadata_recommendation_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.created_by IS DISTINCT FROM
               NULLIF(current_setting('app.subject_id', true), '')::uuid
               OR EXISTS (
                   SELECT 1
                   FROM jsonb_array_elements_text(NEW.evidence) AS item(value)
                   WHERE char_length(item.value) NOT BETWEEN 1 AND 1000
                      OR item.value <> btrim(item.value)
               ) THEN
                RAISE EXCEPTION 'invalid catalog metadata recommendation insert';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    execute(
        """
        CREATE TRIGGER validate_metadata_recommendation_insert
        BEFORE INSERT ON catalog.metadata_recommendations
        FOR EACH ROW EXECUTE FUNCTION catalog.validate_metadata_recommendation_insert()
        """
    )
    execute(
        """
        CREATE FUNCTION catalog.guard_metadata_recommendation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'catalog metadata recommendations cannot be deleted';
            END IF;
            IF ROW(
                OLD.workspace_id, OLD.asset_id, OLD.field_path_key, OLD.vocabulary_id,
                OLD.kind, OLD.source_version, OLD.provider_source_version,
                OLD.vocabulary_source_version, OLD.aspect_name, OLD.aspect_source_version,
                OLD.aspect_content_hash, OLD.target_binding_hash, OLD.input_context_hash,
                OLD.confidence, OLD.reason, OLD.evidence, OLD.provider, OLD.model,
                OLD.prompt_version, OLD.rule_version, OLD.created_by, OLD.created_at
            ) IS DISTINCT FROM ROW(
                NEW.workspace_id, NEW.asset_id, NEW.field_path_key, NEW.vocabulary_id,
                NEW.kind, NEW.source_version, NEW.provider_source_version,
                NEW.vocabulary_source_version, NEW.aspect_name, NEW.aspect_source_version,
                NEW.aspect_content_hash, NEW.target_binding_hash, NEW.input_context_hash,
                NEW.confidence, NEW.reason, NEW.evidence, NEW.provider, NEW.model,
                NEW.prompt_version, NEW.rule_version, NEW.created_by, NEW.created_at
            ) OR NEW.version <> OLD.version + 1 OR NEW.updated_at < OLD.updated_at THEN
                RAISE EXCEPTION 'catalog metadata recommendation immutable evidence changed';
            END IF;
            IF OLD.state <> 'NEEDS_DECISION' THEN
                RAISE EXCEPTION 'catalog metadata recommendation is terminal';
            END IF;
            IF NEW.state = 'APPROVED' THEN
                IF OLD.decision_kind IS NOT NULL OR NEW.decision_kind <> 'APPROVE'
                   OR NEW.decision_actor_id IS DISTINCT FROM
                      NULLIF(current_setting('app.subject_id', true), '')::uuid
                   OR NEW.decision_expected_version IS DISTINCT FROM OLD.version
                   OR NEW.change_request_id IS NULL THEN
                    RAISE EXCEPTION 'invalid catalog metadata recommendation approval';
                END IF;
            ELSIF NEW.state = 'REJECTED' THEN
                IF OLD.decision_kind IS NOT NULL OR NEW.decision_kind <> 'REJECT'
                   OR NEW.decision_actor_id IS DISTINCT FROM
                      NULLIF(current_setting('app.subject_id', true), '')::uuid
                   OR NEW.decision_expected_version IS DISTINCT FROM OLD.version
                   OR NEW.change_request_id IS NOT NULL THEN
                    RAISE EXCEPTION 'invalid catalog metadata recommendation rejection';
                END IF;
            ELSE
                RAISE EXCEPTION 'invalid catalog metadata recommendation transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    execute(
        """
        CREATE TRIGGER guard_metadata_recommendation_mutation
        BEFORE UPDATE OR DELETE ON catalog.metadata_recommendations
        FOR EACH ROW EXECUTE FUNCTION catalog.guard_metadata_recommendation_mutation()
        """
    )
    execute(
        """
        CREATE FUNCTION catalog.guard_metadata_recommendation_event_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'catalog metadata recommendation events are append-only';
        END;
        $$
        """
    )
    execute(
        """
        CREATE FUNCTION catalog.validate_metadata_recommendation_event_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.actor_id IS DISTINCT FROM
               NULLIF(current_setting('app.subject_id', true), '')::uuid
               OR NOT EXISTS (
                   SELECT 1
                   FROM catalog.metadata_recommendations AS recommendation
                   WHERE recommendation.workspace_id = NEW.workspace_id
                     AND recommendation.id = NEW.recommendation_id
                     AND recommendation.version = NEW.recommendation_version
                     AND (
                         (NEW.decision = 'PREVIEWED'
                          AND recommendation.state = 'NEEDS_DECISION'
                          AND recommendation.version = 1
                          AND recommendation.created_by = NEW.actor_id)
                         OR (NEW.decision = 'APPROVED'
                         AND recommendation.state = 'APPROVED'
                             AND recommendation.decision_actor_id = NEW.actor_id
                             AND recommendation.change_request_id = NEW.change_request_id)
                         OR (NEW.decision = 'REJECTED'
                             AND recommendation.state = 'REJECTED'
                             AND recommendation.decision_actor_id = NEW.actor_id)
                     )
               ) THEN
                RAISE EXCEPTION 'invalid catalog metadata recommendation event insert';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    execute(
        """
        CREATE TRIGGER validate_metadata_recommendation_event_insert
        BEFORE INSERT ON catalog.metadata_recommendation_events
        FOR EACH ROW EXECUTE FUNCTION catalog.validate_metadata_recommendation_event_insert()
        """
    )
    execute(
        """
        CREATE TRIGGER guard_metadata_recommendation_event_immutability
        BEFORE UPDATE OR DELETE ON catalog.metadata_recommendation_events
        FOR EACH ROW EXECUTE FUNCTION catalog.guard_metadata_recommendation_event_immutability()
        """
    )


def downgrade() -> None:
    raise RuntimeError("0101 is a forward-only governed-state migration")
