"""Bind change workflow decisions and test evidence to immutable revision rounds.

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
EXPECTED_OBJECT_COUNT = 10


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (to_regclass('governance.change_request_rounds') IS NOT NULL)::int
                    + (to_regclass('governance.change_test_runs') IS NOT NULL)::int
                    + (SELECT count(*) FROM information_schema.columns
                       WHERE table_schema = 'governance' AND table_name = 'change_requests'
                         AND column_name IN (
                           'requester_department_id', 'current_round_id', 'current_round_number'))
                    + (SELECT count(*) FROM information_schema.columns
                       WHERE table_schema = 'governance'
                         AND table_name IN (
                           'approvals', 'state_transitions', 'change_request_attachments')
                         AND column_name = 'round_id')
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('governance.approvals')
                         AND conname =
                           'uq_approvals_change_request_id_round_id_stage_actor_id')
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('governance.change_request_attachments')
                         AND conname = 'uq_change_request_attachment_round_identity')
                """
            )
        )
        .scalar_one()
    )


def _install_security_contract() -> None:
    op.execute(
        """DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            GRANT SELECT, INSERT, UPDATE ON governance.change_request_rounds TO datariver_app;
            GRANT SELECT, INSERT ON governance.change_test_runs TO datariver_app;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_worker') THEN
            GRANT SELECT ON governance.change_request_rounds,
                governance.change_test_runs TO datariver_worker;
        END IF;
        END $datariver$"""
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The CR revision/test-evidence schema is only partially present.")
        _install_security_contract()
        return
    op.create_table(
        "change_request_rounds",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "round_number > 0", name="ck_change_request_rounds_round_number_positive"
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_change_request_rounds_evidence_hash_valid",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id"],
            ["governance.change_requests.workspace_id", "governance.change_requests.id"],
            name="fk_change_request_rounds_request",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_change_request_rounds"),
        sa.UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "round_number",
            # Match SQLAlchemy's deterministic PostgreSQL truncation in regenerated 0001.
            name="uq_change_request_rounds_workspace_id_change_request_id_1e58",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "id",
            name="uq_change_request_rounds_workspace_id_change_request_id_id",
        ),
        schema="governance",
    )
    op.create_index(
        "ix_change_request_rounds_request",
        "change_request_rounds",
        ["workspace_id", "change_request_id"],
        schema="governance",
    )
    op.execute("ALTER TABLE governance.change_request_rounds ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance.change_request_rounds FORCE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY workspace_isolation ON governance.change_request_rounds
        USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
        WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"""
    )

    op.add_column(
        "change_requests",
        sa.Column("requester_department_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_requests",
        sa.Column("current_round_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_requests",
        sa.Column("current_round_number", sa.Integer(), server_default="1", nullable=False),
        schema="governance",
    )
    op.execute(
        """
        WITH inserted AS (
            INSERT INTO governance.change_request_rounds (
                id, workspace_id, change_request_id, round_number,
                submitted_by, submitted_at, closed_at, evidence_hash
            )
            SELECT
                gen_random_uuid(), workspace_id, id, 1,
                requester_id, created_at, NULL,
                encode(sha256(convert_to('LEGACY_ROUND_V1:' || id::text, 'UTF8')), 'hex')
            FROM governance.change_requests
            RETURNING workspace_id, change_request_id, id
        )
        UPDATE governance.change_requests AS request
        SET current_round_id = inserted.id
        FROM inserted
        WHERE request.workspace_id = inserted.workspace_id
          AND request.id = inserted.change_request_id
        """
    )
    op.alter_column("change_requests", "current_round_id", nullable=False, schema="governance")
    op.alter_column(
        "change_requests",
        "current_round_number",
        server_default=None,
        schema="governance",
    )
    op.create_foreign_key(
        "fk_change_requests_current_round",
        "change_requests",
        "change_request_rounds",
        ["workspace_id", "id", "current_round_id"],
        ["workspace_id", "change_request_id", "id"],
        source_schema="governance",
        referent_schema="governance",
        deferrable=True,
        initially="DEFERRED",
    )

    round_backfills = {
        "approvals": """UPDATE governance.approvals AS child
            SET round_id = request.current_round_id
            FROM governance.change_requests AS request
            WHERE child.workspace_id = request.workspace_id
              AND child.change_request_id = request.id""",
        "state_transitions": """UPDATE governance.state_transitions AS child
            SET round_id = request.current_round_id
            FROM governance.change_requests AS request
            WHERE child.workspace_id = request.workspace_id
              AND child.change_request_id = request.id""",
        "change_request_attachments": """UPDATE governance.change_request_attachments AS child
            SET round_id = request.current_round_id
            FROM governance.change_requests AS request
            WHERE child.workspace_id = request.workspace_id
              AND child.change_request_id = request.id""",
    }
    for table_name, round_backfill in round_backfills.items():
        op.add_column(
            table_name,
            sa.Column("round_id", sa.Uuid(), nullable=True),
            schema="governance",
        )
        op.execute(round_backfill)
        op.alter_column(table_name, "round_id", nullable=False, schema="governance")
        op.create_foreign_key(
            f"fk_{table_name}_round",
            table_name,
            "change_request_rounds",
            ["workspace_id", "change_request_id", "round_id"],
            ["workspace_id", "change_request_id", "id"],
            source_schema="governance",
            referent_schema="governance",
            ondelete="RESTRICT",
        )

    op.drop_constraint(
        "uq_approvals_change_request_id_stage_actor_id",
        "approvals",
        schema="governance",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_approvals_change_request_id_round_id_stage_actor_id",
        "approvals",
        ["change_request_id", "round_id", "stage", "actor_id"],
        schema="governance",
    )
    op.create_unique_constraint(
        "uq_change_request_attachment_round_identity",
        "change_request_attachments",
        ["workspace_id", "change_request_id", "round_id", "id"],
        schema="governance",
    )

    op.create_table(
        "change_test_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "bounded_summary",
            postgresql.JSONB(none_as_null=True),
            nullable=False,
        ),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "state IN ('PASSED', 'FAILED')",
            name="ck_change_test_runs_state_vocabulary",
        ),
        sa.CheckConstraint(
            "plan_hash ~ '^[0-9a-f]{64}$'", name="ck_change_test_runs_plan_hash_valid"
        ),
        sa.CheckConstraint(
            "result_hash ~ '^[0-9a-f]{64}$'", name="ck_change_test_runs_result_hash_valid"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(bounded_summary) = 'object'",
            name="ck_change_test_runs_summary_object",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id", "round_id"],
            [
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ],
            name="fk_change_test_runs_round",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "system_id"],
            ["platform.data_systems.workspace_id", "platform.data_systems.id"],
            name="fk_change_test_runs_system",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id", "round_id", "attachment_id"],
            [
                "governance.change_request_attachments.workspace_id",
                "governance.change_request_attachments.change_request_id",
                "governance.change_request_attachments.round_id",
                "governance.change_request_attachments.id",
            ],
            name="fk_change_test_runs_attachment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_change_test_runs"),
        sa.UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "round_id",
            "id",
            name="uq_change_test_runs_workspace_id_change_request_id_round_id_id",
        ),
        schema="governance",
    )
    op.create_index(
        "ix_change_test_runs_round_system",
        "change_test_runs",
        ["workspace_id", "change_request_id", "round_id", "system_id"],
        schema="governance",
    )
    op.execute("ALTER TABLE governance.change_test_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance.change_test_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY workspace_isolation ON governance.change_test_runs
        USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
        WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"""
    )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical round/test shape.
    pass
