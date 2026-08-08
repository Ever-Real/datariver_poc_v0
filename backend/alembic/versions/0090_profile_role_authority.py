"""Add server-managed profile Role authority and governed Admin transitions.

Revision ID: 0090
Revises: 0089
Create Date: 2026-08-01
"""

# ruff: noqa: S608 -- SQL uses only fixed source-owned function signatures.

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from datariver.infrastructure.db.identity_provisioning_sql import (
    IDENTITY_PROVISIONING_FUNCTION_SQL,
    IDENTITY_PROVISIONING_FUNCTION_SQL_V3,
    IDENTITY_PROVISIONING_SIGNATURE,
    IDENTITY_PROVISIONING_SIGNATURE_V3,
)
from datariver.infrastructure.db.profile_role_sql import (
    CANONICAL_ADMIN_PROFILE_TRANSITION_FUNCTION_SQL,
    CANONICAL_ADMIN_PROFILE_TRANSITION_SIGNATURE,
    PROFILE_ROLE_ASSIGNMENT_FUNCTION_SQL,
    PROFILE_ROLE_ASSIGNMENT_SIGNATURE,
    PROFILE_ROLE_SECURITY_SQL,
)

revision: str = "0090"
down_revision: str | Sequence[str] | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("profile_role_assignments", schema="iam"): return
    op.create_table(
        "profile_role_assignments",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("materialized_actions_hash", sa.String(length=64), nullable=False),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("assurance", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint(
            "tier IN ('VIEWER', 'ENGINEER_STEWARD', 'MANAGER')",
            name="ck_profile_role_assignments_tier_vocabulary",
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'REVOKED')",
            name="ck_profile_role_assignments_state_vocabulary",
        ),
        sa.CheckConstraint(
            "policy_version = 'PROFILE_ROLE_POLICY_V1'",
            name="ck_profile_role_assignments_policy_version",
        ),
        sa.CheckConstraint(
            "membership_version > 0",
            name="ck_profile_role_assignments_membership_version_positive",
        ),
        sa.CheckConstraint(
            "materialized_actions_hash ~ '^[0-9a-f]{64}$'",
            name="ck_profile_role_assignments_actions_hash_sha256",
        ),
        sa.CheckConstraint(
            "char_length(trim(reason)) BETWEEN 1 AND 4000",
            name="ck_profile_role_assignments_reason_bounded",
        ),
        sa.CheckConstraint(
            "assurance IN ('PASSWORD_REAUTH', 'HARDWARE_WEBAUTHN')",
            name="ck_profile_role_assignments_assurance_vocabulary",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["platform.workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_profile_role_assignments_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "assigned_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_profile_role_assignments_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "subject_id"),
        schema="iam",
    )
    op.create_index(if_not_exists=True, "ix_profile_role_assignments_workspace_tier",
        "profile_role_assignments",
        ["workspace_id", "tier", "state"],
        schema="iam",
    )
    op.create_table(
        "profile_role_assignment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("previous_tier", sa.String(length=32), nullable=True),
        sa.Column("next_tier", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("assurance", sa.String(length=32), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('ASSIGNED', 'CHANGED', 'PROMOTED_TO_ADMIN', 'DEMOTED_FROM_ADMIN')",
            name="ck_profile_role_assignment_events_event_type_vocabulary",
        ),
        sa.CheckConstraint(
            "previous_tier IS NULL OR previous_tier IN "
            "('VIEWER', 'ENGINEER_STEWARD', 'MANAGER', 'ADMIN')",
            name="ck_profile_role_assignment_events_previous_tier_vocabulary",
        ),
        sa.CheckConstraint(
            "next_tier IN ('VIEWER', 'ENGINEER_STEWARD', 'MANAGER', 'ADMIN')",
            name="ck_profile_role_assignment_events_next_tier_vocabulary",
        ),
        sa.CheckConstraint(
            "policy_version = 'PROFILE_ROLE_POLICY_V1'",
            name="ck_profile_role_assignment_events_policy_version",
        ),
        sa.CheckConstraint(
            "membership_version > 0",
            name="ck_profile_role_assignment_events_membership_version_positive",
        ),
        sa.CheckConstraint(
            "assignment_version > 0",
            name="ck_profile_role_assignment_events_assignment_version_positive",
        ),
        sa.CheckConstraint(
            "char_length(trim(reason)) BETWEEN 1 AND 4000",
            name="ck_profile_role_assignment_events_reason_bounded",
        ),
        sa.CheckConstraint(
            "assurance IN ('PASSWORD_REAUTH', 'HARDWARE_WEBAUTHN')",
            name="ck_profile_role_assignment_events_assurance_vocabulary",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["platform.workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_profile_role_assignment_events_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_profile_role_assignment_events_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_profile_role_assignment_events_workspace_id"
        ),
        schema="iam",
    )
    op.create_index(if_not_exists=True, "ix_profile_role_assignment_events_workspace_subject_occurred",
        "profile_role_assignment_events",
        ["workspace_id", "subject_id", "occurred_at"],
        schema="iam",
    )

    op.drop_constraint(
        "ck_canonical_admin_bindings_development_bootstrap_only",
        "canonical_admin_bindings",
        schema="iam",
        type_="check",
    )
    op.create_check_constraint(
        "ck_canonical_admin_bindings_binding_source_vocabulary",
        "canonical_admin_bindings",
        "binding_source IN ('LOCAL_DEVELOPMENT_BOOTSTRAP', 'GOVERNED_ADMIN_ASSIGNMENT')",
        schema="iam",
    )
    op.execute(PROFILE_ROLE_ASSIGNMENT_FUNCTION_SQL)
    op.execute(CANONICAL_ADMIN_PROFILE_TRANSITION_FUNCTION_SQL)
    for statement in PROFILE_ROLE_SECURITY_SQL:
        op.execute(statement)
    op.execute(IDENTITY_PROVISIONING_FUNCTION_SQL_V3)
    op.execute(f"REVOKE ALL ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE_V3} FROM PUBLIC")
    op.execute(
        f"""
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        REVOKE EXECUTE ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE} FROM datariver_app;
        GRANT EXECUTE ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE_V3} TO datariver_app;
    END IF;
END
$datariver$;
"""
    )


def downgrade() -> None:
    op.execute(
        """
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM iam.profile_role_assignments)
       OR EXISTS (SELECT 1 FROM iam.profile_role_assignment_events)
       OR EXISTS (
           SELECT 1 FROM iam.canonical_admin_bindings
           WHERE binding_source = 'GOVERNED_ADMIN_ASSIGNMENT'
       ) THEN
        RAISE EXCEPTION '0090 downgrade is blocked by profile Role or governed Admin history';
    END IF;
END
$datariver$
"""
    )
    op.execute(f"DROP FUNCTION IF EXISTS {CANONICAL_ADMIN_PROFILE_TRANSITION_SIGNATURE}")
    op.execute(f"DROP FUNCTION IF EXISTS {PROFILE_ROLE_ASSIGNMENT_SIGNATURE}")
    op.execute(f"DROP FUNCTION IF EXISTS {IDENTITY_PROVISIONING_SIGNATURE_V3}")
    op.execute(IDENTITY_PROVISIONING_FUNCTION_SQL)
    op.execute(
        f"""
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT EXECUTE ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE} TO datariver_app;
    END IF;
END
$datariver$;
"""
    )
    op.execute(
        "DROP POLICY IF EXISTS canonical_admin_bindings_governed_update "
        "ON iam.canonical_admin_bindings"
    )
    op.execute(
        "DROP POLICY IF EXISTS canonical_admin_bindings_governed_insert "
        "ON iam.canonical_admin_bindings"
    )
    op.drop_constraint(
        "ck_canonical_admin_bindings_binding_source_vocabulary",
        "canonical_admin_bindings",
        schema="iam",
        type_="check",
    )
    op.create_check_constraint(
        "ck_canonical_admin_bindings_development_bootstrap_only",
        "canonical_admin_bindings",
        "binding_source = 'LOCAL_DEVELOPMENT_BOOTSTRAP'",
        schema="iam",
    )
    op.drop_index(
        "ix_profile_role_assignment_events_workspace_subject_occurred",
        table_name="profile_role_assignment_events",
        schema="iam",
    )
    op.drop_table("profile_role_assignment_events", schema="iam")
    op.drop_index(
        "ix_profile_role_assignments_workspace_tier",
        table_name="profile_role_assignments",
        schema="iam",
    )
    op.drop_table("profile_role_assignments", schema="iam")
