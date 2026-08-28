"""Add immutable editable Change Request revision snapshots.

Revision ID: 0092
Revises: 0091
Create Date: 2026-08-02
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import op

revision: str = "0092"
down_revision: str | Sequence[str] | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_ITEM_ORDINAL_CONSTRAINT = "uq_change_request_items_change_request_id_ordinal"
_CURRENT_ITEM_SCOPE_MATCH = "AND item.change_request_id = request.id"
_CURRENT_ITEM_SCOPE_REPLACEMENT = """AND item.change_request_id = request.id
              AND EXISTS (
                  SELECT 1
                  FROM governance.change_request_round_items AS round_item
                  WHERE round_item.workspace_id = item.workspace_id
                    AND round_item.change_request_id = item.change_request_id
                    AND round_item.round_id = request.current_round_id
                    AND round_item.item_id = item.id
              )"""
_EXPECTED_CURRENT_ITEM_SCOPE_COUNT = 8
_ROUND_SNAPSHOT_COLUMNS = (
    "revision_kind",
    "title",
    "request_date",
    "request_department",
    "request_reason",
    "request_content",
    "requested_due_date",
    "priority",
    "urgency",
    "classification",
    "selected_system_id",
)


def _load_previous_revision() -> ModuleType:
    path = Path(__file__).with_name("0091_align_governance_attachment_authorization.py")
    spec = importlib.util.spec_from_file_location(
        "datariver_governance_attachment_authorization_0091",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the 0091 attachment authorization contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PREVIOUS_REVISION = _load_previous_revision()
PREVIOUS_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL = str(
    _PREVIOUS_REVISION.FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL
)
if (
    PREVIOUS_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL.count(_CURRENT_ITEM_SCOPE_MATCH)
    != _EXPECTED_CURRENT_ITEM_SCOPE_COUNT
):
    raise RuntimeError("The 0091 current-item authorization contract changed unexpectedly.")
FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL = (
    PREVIOUS_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL.replace(
        _CURRENT_ITEM_SCOPE_MATCH,
        _CURRENT_ITEM_SCOPE_REPLACEMENT,
    )
)


def _schema_state() -> str:
    if op.get_context().as_sql:
        return "LEGACY"
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT
                (
                    SELECT count(*)
                    FROM information_schema.columns
                    WHERE table_schema = 'governance'
                      AND table_name = 'change_request_rounds'
                      AND column_name IN (
                          'revision_kind', 'title', 'request_date',
                          'request_department', 'request_reason', 'request_content',
                          'requested_due_date', 'priority', 'urgency',
                          'classification', 'selected_system_id'
                      )
                ) AS round_column_count,
                to_regclass('governance.change_request_round_items') IS NOT NULL
                    AS association_exists,
                (
                    SELECT count(*)
                    FROM pg_constraint
                    WHERE conrelid = 'governance.change_request_items'::regclass
                      AND conname = :legacy_constraint
                ) AS legacy_ordinal_count
            """
            ),
            {
                "legacy_constraint": _LEGACY_ITEM_ORDINAL_CONSTRAINT,
            },
        )
        .one()
    )
    observed = (
        int(row.round_column_count),
        bool(row.association_exists),
        int(row.legacy_ordinal_count),
    )
    if observed == (0, False, 1):
        return "LEGACY"
    if observed == (len(_ROUND_SNAPSHOT_COLUMNS), True, 0):
        return "CURRENT"
    raise RuntimeError("0092 found a partial editable Change Request revision schema.")


def _assert_upgrade_preconditions() -> None:
    op.execute(
        """DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM governance.change_requests
                WHERE char_length(trim(title)) = 0
                   OR classification NOT BETWEEN 0 AND 3
                   OR (priority IS NOT NULL
                       AND priority NOT IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL'))
                   OR (urgency IS NOT NULL
                       AND urgency NOT IN ('NORMAL', 'URGENT', 'EMERGENCY'))
            ) THEN
                RAISE EXCEPTION
                    '0092 cannot snapshot an invalid existing Change Request.';
            END IF;
            IF (
                SELECT count(*)
                FROM pg_constraint
                WHERE conrelid = 'governance.change_request_items'::regclass
                  AND conname = 'uq_change_request_items_change_request_id_ordinal'
            ) <> 1 THEN
                RAISE EXCEPTION
                    '0092 requires the exact legacy Change Request item ordinal contract.';
            END IF;
        END
        $datariver$"""
    )


def _assert_current_contract() -> None:
    op.execute(
        """DO $datariver$
        DECLARE
            expected_constraint text;
        BEGIN
            FOREACH expected_constraint IN ARRAY ARRAY[
                'ck_change_request_rounds_revision_kind_vocabulary',
                'ck_change_request_rounds_title_required',
                'ck_change_request_rounds_priority_vocabulary',
                'ck_change_request_rounds_urgency_vocabulary',
                'ck_change_request_rounds_classification_range',
                'fk_change_request_rounds_selected_system',
                'pk_change_request_round_items',
                'ck_change_request_round_items_ordinal_non_negative',
                'uq_change_request_round_items_ordinal',
                'fk_change_request_round_items_round',
                'fk_change_request_round_items_item'
            ] LOOP
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = expected_constraint
                      AND conrelid IN (
                          'governance.change_request_rounds'::regclass,
                          'governance.change_request_round_items'::regclass
                      )
                ) THEN
                    RAISE EXCEPTION
                        '0092 current schema constraint % is missing', expected_constraint;
                END IF;
            END LOOP;
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('revision_kind', 'character varying', 'varchar', 16, 'NO'),
                        ('title', 'character varying', 'varchar', 500, 'NO'),
                        ('request_date', 'date', 'date', NULL, 'YES'),
                        ('request_department', 'character varying', 'varchar', 500, 'NO'),
                        ('request_reason', 'text', 'text', NULL, 'NO'),
                        ('request_content', 'text', 'text', NULL, 'NO'),
                        ('requested_due_date', 'date', 'date', NULL, 'YES'),
                        ('priority', 'character varying', 'varchar', 16, 'YES'),
                        ('urgency', 'character varying', 'varchar', 16, 'YES'),
                        ('classification', 'integer', 'int4', NULL, 'NO'),
                        ('selected_system_id', 'uuid', 'uuid', NULL, 'YES')
                ) AS expected(
                    column_name, data_type, udt_name, character_maximum_length, is_nullable
                )
                LEFT JOIN information_schema.columns AS actual
                  ON actual.table_schema = 'governance'
                 AND actual.table_name = 'change_request_rounds'
                 AND actual.column_name = expected.column_name
                WHERE actual.column_name IS NULL
                   OR actual.data_type IS DISTINCT FROM expected.data_type
                   OR actual.udt_name IS DISTINCT FROM expected.udt_name
                   OR actual.character_maximum_length
                        IS DISTINCT FROM expected.character_maximum_length
                   OR actual.is_nullable IS DISTINCT FROM expected.is_nullable
            ) THEN
                RAISE EXCEPTION '0092 current round snapshot columns are invalid';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'governance'
                  AND table_name = 'change_request_rounds'
                  AND column_name = 'snapshot_hash'
            ) THEN
                RAISE EXCEPTION '0092 forbids a second round snapshot hash';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('workspace_id', 'uuid', 'uuid'),
                        ('change_request_id', 'uuid', 'uuid'),
                        ('round_id', 'uuid', 'uuid'),
                        ('item_id', 'uuid', 'uuid'),
                        ('ordinal', 'integer', 'int4')
                ) AS expected(column_name, data_type, udt_name)
                LEFT JOIN information_schema.columns AS actual
                  ON actual.table_schema = 'governance'
                 AND actual.table_name = 'change_request_round_items'
                 AND actual.column_name = expected.column_name
                WHERE actual.column_name IS NULL
                   OR actual.data_type IS DISTINCT FROM expected.data_type
                   OR actual.udt_name IS DISTINCT FROM expected.udt_name
                   OR actual.is_nullable <> 'NO'
            ) OR (
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'governance'
                  AND table_name = 'change_request_round_items'
            ) <> 5 THEN
                RAISE EXCEPTION '0092 current round item columns are invalid';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_class
                WHERE oid = 'governance.change_request_round_items'::regclass
                  AND relrowsecurity IS TRUE
                  AND relforcerowsecurity IS TRUE
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_policy
                WHERE polrelid = 'governance.change_request_round_items'::regclass
                  AND polname = 'workspace_isolation'
            ) THEN
                RAISE EXCEPTION '0092 current round item RLS contract is invalid';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM governance.change_request_rounds AS round
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM governance.change_request_round_items AS round_item
                    WHERE round_item.workspace_id = round.workspace_id
                      AND round_item.change_request_id = round.change_request_id
                      AND round_item.round_id = round.id
                )
            ) OR EXISTS (
                SELECT 1
                FROM governance.change_request_items AS item
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM governance.change_request_round_items AS round_item
                    WHERE round_item.workspace_id = item.workspace_id
                      AND round_item.change_request_id = item.change_request_id
                      AND round_item.item_id = item.id
                )
            ) THEN
                RAISE EXCEPTION '0092 current round item association is incomplete';
            END IF;
        END
        $datariver$"""
    )


def _install_security_contract() -> None:
    op.execute(
        """DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE UPDATE ON governance.change_request_rounds FROM datariver_app;
                REVOKE UPDATE, DELETE ON governance.change_request_round_items
                    FROM datariver_app;
                GRANT UPDATE (closed_at) ON governance.change_request_rounds TO datariver_app;
                GRANT SELECT, INSERT ON governance.change_request_round_items TO datariver_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN
                REVOKE INSERT, UPDATE, DELETE ON governance.change_request_round_items
                    FROM datariver_governance;
                GRANT SELECT ON governance.change_request_round_items TO datariver_governance;
            END IF;
        END
        $datariver$"""
    )


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("change_request_round_items", schema="governance"):
        return
    state = _schema_state()
    if state == "CURRENT":
        _assert_current_contract()
        _install_security_contract()
        op.execute(FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL)
        return
    _assert_upgrade_preconditions()

    round_columns = (
        sa.Column("revision_kind", sa.String(length=16), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("request_date", sa.Date(), nullable=True),
        sa.Column("request_department", sa.String(length=500), nullable=True),
        sa.Column("request_reason", sa.Text(), nullable=True),
        sa.Column("request_content", sa.Text(), nullable=True),
        sa.Column("requested_due_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("urgency", sa.String(length=16), nullable=True),
        sa.Column("classification", sa.Integer(), nullable=True),
        sa.Column("selected_system_id", sa.Uuid(), nullable=True),
    )
    for column in round_columns:
        op.add_column("change_request_rounds", column, schema="governance")

    op.create_check_constraint(
        op.f("ck_change_request_rounds_revision_kind_vocabulary"),
        "change_request_rounds",
        "revision_kind IN ('LEGACY', 'INITIAL', 'EDITED')",
        schema="governance",
    )
    op.create_check_constraint(
        op.f("ck_change_request_rounds_title_required"),
        "change_request_rounds",
        "char_length(trim(title)) > 0",
        schema="governance",
    )
    op.create_check_constraint(
        op.f("ck_change_request_rounds_priority_vocabulary"),
        "change_request_rounds",
        "priority IS NULL OR priority IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')",
        schema="governance",
    )
    op.create_check_constraint(
        op.f("ck_change_request_rounds_urgency_vocabulary"),
        "change_request_rounds",
        "urgency IS NULL OR urgency IN ('NORMAL', 'URGENT', 'EMERGENCY')",
        schema="governance",
    )
    op.create_check_constraint(
        op.f("ck_change_request_rounds_classification_range"),
        "change_request_rounds",
        "classification BETWEEN 0 AND 3",
        schema="governance",
    )
    op.create_foreign_key(
        "fk_change_request_rounds_selected_system",
        "change_request_rounds",
        "data_systems",
        ["workspace_id", "selected_system_id"],
        ["workspace_id", "id"],
        source_schema="governance",
        referent_schema="platform",
        ondelete="RESTRICT",
    )

    op.create_table(
        "change_request_round_items",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id", "round_id"],
            [
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ],
            name="fk_change_request_round_items_round",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id", "item_id"],
            [
                "governance.change_request_items.workspace_id",
                "governance.change_request_items.change_request_id",
                "governance.change_request_items.id",
            ],
            name="fk_change_request_round_items_item",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "change_request_id",
            "round_id",
            "item_id",
            name="pk_change_request_round_items",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_change_request_round_items_ordinal_non_negative"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "round_id",
            "ordinal",
            name="uq_change_request_round_items_ordinal",
        ),
        schema="governance",
    )
    op.create_index("ix_change_request_round_items_current",
        "change_request_round_items",
        ["workspace_id", "change_request_id", "round_id", "ordinal"],
        schema="governance",
     if_not_exists=True)
    op.execute(
        """
        WITH selected_system AS (
            SELECT
                request.workspace_id,
                request.id AS change_request_id,
                CASE
                    WHEN count(DISTINCT system.id) = 1 THEN (
                        array_agg(DISTINCT system.id ORDER BY system.id)
                            FILTER (WHERE system.id IS NOT NULL)
                    )[1]
                    ELSE NULL
                END AS selected_system_id
            FROM governance.change_requests AS request
            LEFT JOIN governance.change_request_items AS item
              ON item.workspace_id = request.workspace_id
             AND item.change_request_id = request.id
            LEFT JOIN platform.data_systems AS system
              ON system.workspace_id = item.workspace_id
             AND system.id = COALESCE(item.routing_system_id, item.target_system_id)
            GROUP BY request.workspace_id, request.id
        )
        UPDATE governance.change_request_rounds AS round
        SET revision_kind = 'LEGACY',
            title = request.title,
            request_date = NULL,
            request_department = '',
            request_reason = request.description,
            request_content = '',
            requested_due_date = request.requested_due_date,
            priority = request.priority,
            urgency = request.urgency,
            classification = request.classification,
            selected_system_id = selected_system.selected_system_id
        FROM governance.change_requests AS request
        JOIN selected_system
          ON selected_system.workspace_id = request.workspace_id
         AND selected_system.change_request_id = request.id
        WHERE round.workspace_id = request.workspace_id
          AND round.change_request_id = request.id
        """
    )
    op.execute(
        """
        INSERT INTO governance.change_request_round_items (
            workspace_id,
            change_request_id,
            round_id,
            item_id,
            ordinal
        )
        SELECT
            round.workspace_id,
            round.change_request_id,
            round.id,
            item.id,
            item.ordinal
        FROM governance.change_request_rounds AS round
        JOIN governance.change_request_items AS item
          ON item.workspace_id = round.workspace_id
         AND item.change_request_id = round.change_request_id
        ORDER BY round.workspace_id, round.change_request_id, round.round_number, item.ordinal
        """
    )
    op.execute("ALTER TABLE governance.change_request_round_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance.change_request_round_items FORCE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY workspace_isolation ON governance.change_request_round_items
        USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
        WITH CHECK (
            workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
        )"""
    )

    for column_name in (
        "revision_kind",
        "title",
        "request_department",
        "request_reason",
        "request_content",
        "classification",
    ):
        op.alter_column(
            "change_request_rounds",
            column_name,
            nullable=False,
            schema="governance",
        )

    op.drop_constraint(
        _LEGACY_ITEM_ORDINAL_CONSTRAINT,
        "change_request_items",
        schema="governance",
        type_="unique",
    )
    _assert_current_contract()
    _install_security_contract()
    op.execute(FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL)


def _assert_downgrade_preconditions() -> None:
    op.execute(
        """DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM governance.change_request_rounds
                WHERE revision_kind = 'EDITED'
            ) THEN
                RAISE EXCEPTION
                    '0092 downgrade is blocked by editable Change Request history.';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM governance.change_request_items
                GROUP BY change_request_id, ordinal
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    '0092 downgrade cannot restore the legacy item ordinal identity.';
            END IF;
        END
        $datariver$"""
    )


def downgrade() -> None:
    _assert_downgrade_preconditions()
    op.execute(PREVIOUS_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL)
    op.execute(
        """DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE SELECT, INSERT ON governance.change_request_round_items
                    FROM datariver_app;
                REVOKE UPDATE (closed_at) ON governance.change_request_rounds
                    FROM datariver_app;
                GRANT UPDATE ON governance.change_request_rounds TO datariver_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN
                REVOKE SELECT ON governance.change_request_round_items
                    FROM datariver_governance;
            END IF;
        END
        $datariver$"""
    )
    op.create_unique_constraint(
        _LEGACY_ITEM_ORDINAL_CONSTRAINT,
        "change_request_items",
        ["change_request_id", "ordinal"],
        schema="governance",
    )
    op.drop_index(
        "ix_change_request_round_items_current",
        table_name="change_request_round_items",
        schema="governance",
    )
    op.drop_table("change_request_round_items", schema="governance")

    op.drop_constraint(
        "fk_change_request_rounds_selected_system",
        "change_request_rounds",
        schema="governance",
        type_="foreignkey",
    )
    for constraint_name in (
        "ck_change_request_rounds_classification_range",
        "ck_change_request_rounds_urgency_vocabulary",
        "ck_change_request_rounds_priority_vocabulary",
        "ck_change_request_rounds_title_required",
        "ck_change_request_rounds_revision_kind_vocabulary",
    ):
        op.drop_constraint(
            op.f(constraint_name),
            "change_request_rounds",
            schema="governance",
            type_="check",
        )
    for column_name in (
        "selected_system_id",
        "classification",
        "urgency",
        "priority",
        "requested_due_date",
        "request_content",
        "request_reason",
        "request_department",
        "request_date",
        "title",
        "revision_kind",
    ):
        op.drop_column("change_request_rounds", column_name, schema="governance")
