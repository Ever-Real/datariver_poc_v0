"""Version TEST-passed system settings and activate them for process startup.

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
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
                     WHERE table_schema = 'platform'
                       AND table_name = 'external_service_profiles'
                       AND column_name = 'activated_version')
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('platform.external_service_profiles')
                         AND conname = 'ck_external_service_profiles_activated_version_range')
                    + (to_regclass('platform.external_service_profile_versions') IS NOT NULL)::int
                    + (to_regclass(
                         'platform.ix_external_service_profile_versions_workspace_profile'
                       ) IS NOT NULL)::int
                    + (SELECT count(*) FROM pg_policies
                       WHERE schemaname = 'platform'
                         AND tablename = 'external_service_profile_versions'
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
                GRANT SELECT, INSERT, UPDATE
                    ON platform.external_service_profile_versions TO datariver_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_upload') THEN
                GRANT USAGE ON SCHEMA platform TO datariver_upload;
                GRANT SELECT ON platform.external_service_profiles,
                    platform.external_service_profile_versions TO datariver_upload;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN
                GRANT USAGE ON SCHEMA platform TO datariver_governance;
                GRANT SELECT ON platform.external_service_profiles,
                    platform.external_service_profile_versions TO datariver_governance;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_export') THEN
                GRANT SELECT ON platform.external_service_profiles,
                    platform.external_service_profile_versions TO datariver_export;
            END IF;
        END
        $datariver$;
        """
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The System Settings activation schema is only partially present.")
        _install_security_contract()
        return
    op.add_column(
        "external_service_profiles",
        sa.Column("activated_version", sa.Integer(), nullable=True),
        schema="platform",
    )
    op.create_check_constraint(
        "activated_version_range",
        "external_service_profiles",
        "activated_version IS NULL OR (activated_version > 0 AND activated_version <= version)",
        schema="platform",
    )
    op.create_table(
        "external_service_profile_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_version", sa.Integer(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_yaml", sa.Text(), nullable=False),
        sa.Column("endpoint_url", sa.String(length=2048), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("test_status", sa.String(length=32), nullable=True),
        sa.Column("test_scope", sa.String(length=32), nullable=True),
        sa.Column("test_latency_ms", sa.Integer(), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tested_by", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.Uuid(), nullable=True),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("configuration_version > 0", name="configuration_version_positive"),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="configuration_hash_sha256",
        ),
        sa.CheckConstraint(
            "test_status IS NULL OR test_status IN "
            "('AVAILABLE', 'AUTHENTICATION_REQUIRED', 'UNAVAILABLE')",
            name="test_status_vocabulary",
        ),
        sa.CheckConstraint(
            "test_scope IS NULL OR test_scope IN "
            "('HTTP_HEALTH', 'MODEL_DISCOVERY', 'TRANSPORT_ONLY')",
            name="test_scope_vocabulary",
        ),
        sa.CheckConstraint(
            "test_latency_ms IS NULL OR test_latency_ms >= 0",
            name="latency_non_negative",
        ),
        sa.CheckConstraint(
            "(test_status IS NULL AND test_scope IS NULL AND test_latency_ms IS NULL "
            "AND tested_at IS NULL AND tested_by IS NULL) OR "
            "(test_status IS NOT NULL AND test_scope IS NOT NULL AND test_latency_ms IS NOT NULL "
            "AND tested_at IS NOT NULL AND tested_by IS NOT NULL)",
            name="test_evidence_shape",
        ),
        sa.CheckConstraint(
            "(activated_at IS NULL AND activated_by IS NULL) OR "
            "(activated_at IS NOT NULL AND activated_by IS NOT NULL "
            "AND test_status = 'AVAILABLE')",
            name="activation_evidence_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "profile_id"],
            [
                "platform.external_service_profiles.workspace_id",
                "platform.external_service_profiles.id",
            ],
            name="fk_external_service_profile_versions_profile",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_external_service_profile_versions_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_external_service_profile_versions_tester",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "activated_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_external_service_profile_versions_activator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "profile_id", "configuration_version"),
        schema="platform",
    )
    op.create_index(
        "ix_external_service_profile_versions_workspace_profile",
        "external_service_profile_versions",
        ["workspace_id", "profile_id", "configuration_version"],
        schema="platform",
    )
    op.execute(
        """
        INSERT INTO platform.external_service_profile_versions (
            id, workspace_id, profile_id, configuration_version, configuration_hash,
            configuration_yaml, endpoint_url, created_by, created_at, updated_at
        )
        SELECT gen_random_uuid(), workspace_id, id, version,
               md5(configuration_yaml) || md5('migration:' || configuration_yaml),
               configuration_yaml, endpoint_url, updated_by, created_at, updated_at
        FROM platform.external_service_profiles
        """
    )
    op.execute("ALTER TABLE platform.external_service_profile_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.external_service_profile_versions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON platform.external_service_profile_versions "
        f"USING (workspace_id = {RLS_SETTING}) WITH CHECK (workspace_id = {RLS_SETTING})"
    )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical activation shape.
    pass
