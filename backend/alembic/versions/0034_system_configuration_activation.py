"""Version TEST-passed system settings and activate them for process startup.

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from datariver.infrastructure.db.migration_definition_fingerprint import (
    RelationDefinitionFingerprintV1,
    read_relation_definition_fingerprint_v1,
)

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
EXPECTED_OBJECT_COUNT = 5

_CANONICAL_COLUMNS = (
    "workspace_id|uuid|uuid||NO",
    "profile_id|uuid|uuid||NO",
    "configuration_version|integer|int4||NO",
    "configuration_hash|character varying|varchar|64|NO",
    "configuration_yaml|text|text||NO",
    "endpoint_url|character varying|varchar|2048|YES",
    "created_by|uuid|uuid||NO",
    "test_status|character varying|varchar|32|YES",
    "test_scope|character varying|varchar|32|YES",
    "test_latency_ms|integer|int4||YES",
    "tested_at|timestamp with time zone|timestamptz||YES",
    "tested_by|uuid|uuid||YES",
    "activated_at|timestamp with time zone|timestamptz||YES",
    "activated_by|uuid|uuid||YES",
    "id|uuid|uuid||NO",
    "created_at|timestamp with time zone|timestamptz||NO",
    "updated_at|timestamp with time zone|timestamptz||NO",
)
_CANONICAL_CONSTRAINTS = (
    "ck_external_service_profile_versions_activation_evidence_shape",
    "ck_external_service_profile_versions_configuration_hash_sha256",
    "ck_external_service_profile_versions_configuration_vers_2afc",
    "ck_external_service_profile_versions_latency_non_negative",
    "ck_external_service_profile_versions_test_evidence_shape",
    "ck_external_service_profile_versions_test_scope_vocabulary",
    "ck_external_service_profile_versions_test_status_vocabulary",
    "fk_external_service_profile_versions_activator",
    "fk_external_service_profile_versions_creator",
    "fk_external_service_profile_versions_profile",
    "fk_external_service_profile_versions_tester",
    "fk_external_service_profile_versions_workspace_id_workspaces",
    "pk_external_service_profile_versions",
    "uq_external_service_profile_versions_workspace_id_id",
    "uq_external_service_profile_versions_workspace_id_profi_c8c5",
)
_CANONICAL_DEFINITION_FINGERPRINT = RelationDefinitionFingerprintV1(
    "761ea62942edabd1dc2ab4709c82b60f51ab1a92de280d65e6a0190612b70790",
    "48e37f5205aee433ae1beb8df2c86ce848f7d2cc652093134b75aad9133c4122",
    "d0966462ecba0c8c90ff6d38cb07d19fd621d7ffccd5d22ab9cc7d9fb351235b",
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "true|true",
)
_CANONICAL_PROFILE_FINGERPRINT = RelationDefinitionFingerprintV1(
    "2db456f551262f8f5db47cbd54f6f1f53cdef8d1209e0a3c63eb63eba56c7924",
    "3bd8541567798b5a221d6957c9e2396c15c3af09efe82081eb23c73ba7bfd255",
    "8baee280feb3c75405e8c454ad5622c0d01b5edca16a787b355413d303544645",
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "true|true",
)


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


def _is_canonical_schema() -> bool:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    ARRAY(
                        SELECT column_name || '|' || data_type || '|' || udt_name
                            || '|' || COALESCE(character_maximum_length::text, '')
                            || '|' || is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'platform'
                          AND table_name = 'external_service_profile_versions'
                        ORDER BY ordinal_position
                    ) AS columns,
                    ARRAY(
                        SELECT conname FROM pg_constraint
                        WHERE conrelid =
                            to_regclass('platform.external_service_profile_versions')
                        ORDER BY conname
                    ) AS constraints,
                    ARRAY(
                        SELECT index_class.relname
                        FROM pg_index AS index_state
                        JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
                        WHERE index_state.indrelid =
                            to_regclass('platform.external_service_profile_versions')
                          AND NOT EXISTS (
                              SELECT 1 FROM pg_constraint
                              WHERE conindid = index_state.indexrelid
                          )
                        ORDER BY index_class.relname
                    ) AS indexes,
                    ARRAY(
                        SELECT polname FROM pg_policy
                        WHERE polrelid =
                            to_regclass('platform.external_service_profile_versions')
                        ORDER BY polname
                    ) AS policies,
                    ARRAY(
                        SELECT column_name || '|' || data_type || '|' || udt_name
                            || '|' || COALESCE(character_maximum_length::text, '')
                            || '|' || is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'platform'
                          AND table_name = 'external_service_profiles'
                          AND column_name = 'activated_version'
                    ) AS activation_column,
                    ARRAY(
                        SELECT conname FROM pg_constraint
                        WHERE conrelid = to_regclass('platform.external_service_profiles')
                          AND conname = 'ck_external_service_profiles_activated_version_range'
                    ) AS activation_constraint,
                    COALESCE((
                        SELECT relrowsecurity AND relforcerowsecurity
                        FROM pg_class
                        WHERE oid =
                            to_regclass('platform.external_service_profile_versions')
                    ), FALSE) AS force_rls
                """
            )
        )
        .mappings()
        .one()
    )
    return (
        tuple(sorted(row["columns"])) == tuple(sorted(_CANONICAL_COLUMNS))
        and tuple(row["constraints"]) == _CANONICAL_CONSTRAINTS
        and tuple(row["indexes"]) == ("ix_external_service_profile_versions_workspace_profile",)
        and tuple(row["policies"])
        == ("knowledge_worker_inference_profile_versions", "workspace_isolation")
        and tuple(row["activation_column"]) == ("activated_version|integer|int4||YES",)
        and tuple(row["activation_constraint"])
        == ("ck_external_service_profiles_activated_version_range",)
        and bool(row["force_rls"])
        and read_relation_definition_fingerprint_v1(
            op.get_bind(), "platform.external_service_profile_versions"
        )
        == _CANONICAL_DEFINITION_FINGERPRINT
        and read_relation_definition_fingerprint_v1(
            op.get_bind(), "platform.external_service_profiles"
        )
        == _CANONICAL_PROFILE_FINGERPRINT
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
        if existing_objects != EXPECTED_OBJECT_COUNT or not _is_canonical_schema():
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
