"""Add expiring human memberships and governed six-month renewal requests.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
EXPECTED_OBJECT_COUNT = 5


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'iam' AND table_name = 'workspace_memberships'
                       AND column_name = 'access_expires_at')
                    + (to_regclass('iam.membership_renewal_requests') IS NOT NULL)::int
                    + (to_regclass('iam.ix_membership_renewals_workspace_state_created')
                       IS NOT NULL)::int
                    + (to_regclass('iam.uq_membership_renewals_pending_subject')
                       IS NOT NULL)::int
                    + (SELECT count(*) FROM pg_policies
                       WHERE schemaname = 'iam' AND tablename = 'membership_renewal_requests'
                         AND policyname = 'workspace_isolation')
                """
            )
        )
        .scalar_one()
    )


def _install_security_contract() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT, UPDATE ON iam.membership_renewal_requests
                    TO datariver_app;
                GRANT UPDATE (access_expires_at, version, updated_at)
                    ON iam.workspace_memberships TO datariver_app;
            END IF;
        END
        $datariver$;
        """
    )
    _install_default_workspace_resolver()


def _install_default_workspace_resolver() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION iam.resolve_default_workspace(
            p_issuer text,
            p_external_subject text
        )
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, iam, platform
        AS $datariver$
            SELECT membership.workspace_id
            FROM iam.subjects AS subject
            JOIN iam.workspace_memberships AS membership
              ON membership.subject_id = subject.id
            JOIN platform.workspaces AS workspace
              ON workspace.id = membership.workspace_id
            WHERE subject.issuer = p_issuer
              AND subject.external_subject = p_external_subject
              AND subject.active IS TRUE
              AND membership.active IS TRUE
              AND (
                  membership.access_expires_at IS NULL
                  OR membership.access_expires_at > CURRENT_TIMESTAMP
              )
              AND workspace.status = 'ACTIVE'
            ORDER BY
              CASE WHEN membership.attributes ->> 'default_workspace' = 'true'
                THEN 0 ELSE 1 END,
              workspace.slug ASC,
              membership.workspace_id ASC
            LIMIT 1
        $datariver$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION iam.resolve_default_workspace(text, text) FROM PUBLIC")
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT EXECUTE ON FUNCTION iam.resolve_default_workspace(text, text)
                    TO datariver_app;
            END IF;
        END
        $datariver$;
        """
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The membership renewal schema is only partially present.")
        _install_security_contract()
        return
    op.add_column(
        "workspace_memberships",
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="iam",
    )
    op.execute(
        """
        UPDATE iam.workspace_memberships
        SET access_expires_at = GREATEST(
            created_at + INTERVAL '6 months',
            CURRENT_TIMESTAMP + INTERVAL '30 days'
        )
        WHERE COALESCE(job_function, '') <> 'SERVICE_ACCOUNT'
          AND NOT (COALESCE(attributes -> 'groups', '[]'::jsonb) ? 'service-accounts')
        """
    )
    op.create_table(
        "membership_renewal_requests",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("target_subject_id", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=4000), nullable=False),
        sa.Column("current_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("checker_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(length=4000), nullable=True),
        sa.Column("decision_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("requester_id = target_subject_id", name="self_request"),
        sa.CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED')", name="state"),
        sa.CheckConstraint("requested_expires_at > current_expires_at", name="extension_positive"),
        sa.CheckConstraint(
            "checker_id IS NULL OR checker_id <> target_subject_id",
            name="independent_checker",
        ),
        sa.CheckConstraint(
            "(state = 'PENDING' AND checker_id IS NULL AND decision_reason IS NULL "
            "AND decision_policy_decision_id IS NULL AND decided_at IS NULL) OR "
            "(state IN ('APPROVED', 'REJECTED') AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name="state_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "target_subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_membership_renewals_target_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_membership_renewals_requester_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_membership_renewals_checker_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        schema="iam",
    )
    op.create_index(
        "ix_membership_renewals_workspace_state_created",
        "membership_renewal_requests",
        ["workspace_id", "state", "created_at"],
        schema="iam",
    )
    op.create_index(
        "uq_membership_renewals_pending_subject",
        "membership_renewal_requests",
        ["workspace_id", "target_subject_id"],
        unique=True,
        postgresql_where=sa.text("state = 'PENDING'"),
        schema="iam",
    )
    op.execute("ALTER TABLE iam.membership_renewal_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.membership_renewal_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON iam.membership_renewal_requests "
        f"USING (workspace_id = {RLS_SETTING}) "
        f"WITH CHECK (workspace_id = {RLS_SETTING})"
    )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical renewal shape.
    pass
