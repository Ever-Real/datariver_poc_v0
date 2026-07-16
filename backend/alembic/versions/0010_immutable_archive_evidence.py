# ruff: noqa: S608 -- fixed table names render compatibility DDL only.

"""Persist append-only immutable archive verification evidence.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention.archive_capability_attestations (
            workspace_id uuid NOT NULL,
            configuration_fingerprint varchar(64) NOT NULL,
            encryption_profile_fingerprint varchar(64) NOT NULL,
            runtime_principal_fingerprint varchar(64) NOT NULL,
            probe_contract_version varchar(100) NOT NULL,
            challenge_hash varchar(64) NOT NULL,
            object_bucket varchar(63) NOT NULL,
            observed_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            versioning_enabled boolean NOT NULL,
            object_lock_enabled boolean NOT NULL,
            compliance_retention_supported boolean NOT NULL,
            checksum_sha256_supported boolean NOT NULL,
            full_readback_verified boolean NOT NULL,
            retention_shorten_denied boolean NOT NULL,
            retained_version_delete_denied boolean NOT NULL,
            state varchar(20) NOT NULL,
            failure_code varchar(100),
            payload_hash varchar(64) NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            id uuid CONSTRAINT pk_archive_capability_attestations PRIMARY KEY,
            CONSTRAINT uq_archive_capability_attestations_workspace_id_id
                UNIQUE (workspace_id, id),
            CONSTRAINT uq_archive_capability_attestations_workspace_id_fingerprint
                UNIQUE (
                    workspace_id, id, configuration_fingerprint,
                    encryption_profile_fingerprint, runtime_principal_fingerprint
                ),
            CONSTRAINT uq_archive_capability_attestations_observation
                UNIQUE (workspace_id, configuration_fingerprint, observed_at),
            CONSTRAINT fk_archive_capability_attestations_workspace_id_workspaces
                FOREIGN KEY (workspace_id) REFERENCES platform.workspaces(id),
            CONSTRAINT ck_archive_capability_attestations_configuration_finger_b129
                CHECK (configuration_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_archive_capability_attestations_encryption_profile_f_cb90
                CHECK (encryption_profile_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_archive_capability_attestations_runtime_principal_fi_3a6d
                CHECK (runtime_principal_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_archive_capability_attestations_challenge_hash_sha256
                CHECK (challenge_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_archive_capability_attestations_probe_contract_version
                CHECK (length(probe_contract_version) BETWEEN 1 AND 100),
            CONSTRAINT ck_archive_capability_attestations_object_bucket
                CHECK (object_bucket ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'),
            CONSTRAINT ck_archive_capability_attestations_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_archive_capability_attestations_observation_window CHECK (
                expires_at > observed_at
                AND expires_at <= observed_at + INTERVAL '24 hours'
            ),
            CONSTRAINT ck_archive_capability_attestations_state
                CHECK (state IN ('VERIFIED', 'FAILED')),
            CONSTRAINT ck_archive_capability_attestations_state_shape CHECK (
                (state = 'VERIFIED' AND failure_code IS NULL
                    AND versioning_enabled AND object_lock_enabled
                    AND compliance_retention_supported AND checksum_sha256_supported
                    AND full_readback_verified AND retention_shorten_denied
                    AND retained_version_delete_denied) OR
                (state = 'FAILED' AND failure_code IS NOT NULL
                    AND length(btrim(failure_code)) BETWEEN 1 AND 100)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_archive_capability_attestations_workspace_observed
        ON retention.archive_capability_attestations (
            workspace_id, configuration_fingerprint, observed_at
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention.immutable_archive_receipts (
            workspace_id uuid NOT NULL,
            source varchar(32) NOT NULL,
            source_partition varchar(64) NOT NULL,
            source_start timestamptz NOT NULL,
            source_end timestamptz NOT NULL,
            retention_policy_id uuid NOT NULL,
            retention_policy_hash varchar(64) NOT NULL,
            row_count bigint NOT NULL,
            byte_count bigint NOT NULL,
            manifest_hash varchar(64) NOT NULL,
            content_sha256 varchar(64) NOT NULL,
            provider_checksum varchar(512) NOT NULL,
            provider_checksum_algorithm varchar(20) NOT NULL,
            provider_checksum_encoding varchar(20) NOT NULL,
            provider_checksum_type varchar(30) NOT NULL,
            provider_checksum_normalized_sha256 varchar(64) NOT NULL,
            readback_sha256 varchar(64) NOT NULL,
            readback_byte_count bigint NOT NULL,
            object_bucket varchar(63) NOT NULL,
            object_key varchar(1024) NOT NULL,
            object_version_id varchar(1024) NOT NULL,
            retention_mode varchar(20) NOT NULL,
            retention_until timestamptz NOT NULL,
            requested_retention_until timestamptz NOT NULL,
            readback_retention_until timestamptz NOT NULL,
            legal_hold boolean NOT NULL,
            written_at timestamptz NOT NULL,
            content_verified_at timestamptz NOT NULL,
            retention_verified_at timestamptz NOT NULL,
            verified_at timestamptz NOT NULL,
            canonicalization_version varchar(100) NOT NULL,
            media_type varchar(255) NOT NULL,
            media_type_version varchar(100) NOT NULL,
            compression varchar(50) NOT NULL,
            compression_version varchar(100) NOT NULL,
            worker_principal_fingerprint varchar(64) NOT NULL,
            correlation_id varchar(100) NOT NULL,
            capability_attestation_id uuid NOT NULL,
            capability_fingerprint varchar(64) NOT NULL,
            encryption_profile_fingerprint varchar(64) NOT NULL,
            payload_hash varchar(64) NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            id uuid CONSTRAINT pk_immutable_archive_receipts PRIMARY KEY,
            CONSTRAINT uq_immutable_archive_receipts_workspace_id_id
                UNIQUE (workspace_id, id),
            CONSTRAINT uq_immutable_archive_receipts_source_manifest
                UNIQUE (workspace_id, source, source_start, source_end, manifest_hash),
            CONSTRAINT uq_immutable_archive_receipts_object_version
                UNIQUE (object_bucket, object_key, object_version_id),
            CONSTRAINT fk_immutable_archive_receipts_workspace_id_workspaces
                FOREIGN KEY (workspace_id) REFERENCES platform.workspaces(id),
            CONSTRAINT fk_immutable_archive_receipts_capability_attestation
                FOREIGN KEY (
                    workspace_id, capability_attestation_id, capability_fingerprint,
                    encryption_profile_fingerprint, worker_principal_fingerprint
                ) REFERENCES retention.archive_capability_attestations (
                    workspace_id, id, configuration_fingerprint,
                    encryption_profile_fingerprint, runtime_principal_fingerprint
                ),
            CONSTRAINT fk_immutable_archive_receipts_retention_policy
                FOREIGN KEY (workspace_id, retention_policy_id, retention_policy_hash)
                REFERENCES retention.policy_versions(workspace_id, id, payload_hash),
            CONSTRAINT ck_immutable_archive_receipts_source CHECK (
                source IN ('OUTBOX_EVENTS', 'INBOX_MESSAGES', 'POLICY_DECISIONS',
                    'ASSISTANT_RUNS')
            ),
            CONSTRAINT ck_immutable_archive_receipts_source_partition CHECK (
                source_partition ~ '^[a-z][a-z0-9_]{1,49}_[0-9]{4}_[0-9]{2}$'
            ),
            CONSTRAINT ck_immutable_archive_receipts_row_count_positive
                CHECK (row_count > 0),
            CONSTRAINT ck_immutable_archive_receipts_byte_count_positive
                CHECK (byte_count > 0),
            CONSTRAINT ck_immutable_archive_receipts_source_range
                CHECK (source_end > source_start),
            CONSTRAINT ck_immutable_archive_receipts_manifest_hash_sha256
                CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_content_sha256
                CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_provider_checksum
                CHECK (length(provider_checksum) BETWEEN 1 AND 512),
            CONSTRAINT ck_immutable_archive_receipts_checksum_algorithm
                CHECK (provider_checksum_algorithm = 'SHA256'),
            CONSTRAINT ck_immutable_archive_receipts_checksum_encoding
                CHECK (provider_checksum_encoding IN ('HEX', 'BASE64')),
            CONSTRAINT ck_immutable_archive_receipts_checksum_type
                CHECK (provider_checksum_type = 'FULL_OBJECT'),
            CONSTRAINT ck_immutable_archive_receipts_provider_checksum_normali_0a26
                CHECK (provider_checksum_normalized_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_readback_sha256
                CHECK (readback_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_readback_byte_count_positive
                CHECK (readback_byte_count > 0),
            CONSTRAINT ck_immutable_archive_receipts_content_readback_match CHECK (
                content_sha256 = readback_sha256
                AND content_sha256 = provider_checksum_normalized_sha256
                AND byte_count = readback_byte_count
            ),
            CONSTRAINT ck_immutable_archive_receipts_object_bucket
                CHECK (object_bucket ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'),
            CONSTRAINT ck_immutable_archive_receipts_object_key
                CHECK (length(object_key) BETWEEN 1 AND 1024 AND object_key !~ '^/'),
            CONSTRAINT ck_immutable_archive_receipts_object_version_id CHECK (
                length(object_version_id) BETWEEN 1 AND 1024
                AND lower(btrim(object_version_id)) <> 'null'
            ),
            CONSTRAINT ck_immutable_archive_receipts_retention_mode
                CHECK (retention_mode = 'COMPLIANCE'),
            CONSTRAINT ck_immutable_archive_receipts_retention_readback_match CHECK (
                retention_until = requested_retention_until
                AND retention_until = readback_retention_until
                AND retention_until > verified_at
            ),
            CONSTRAINT ck_immutable_archive_receipts_verification_timeline CHECK (
                written_at <= content_verified_at
                AND written_at <= retention_verified_at
                AND content_verified_at <= verified_at
                AND retention_verified_at <= verified_at
            ),
            CONSTRAINT ck_immutable_archive_receipts_retention_policy_hash_sha256
                CHECK (retention_policy_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_capability_fingerprint_sha256
                CHECK (capability_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_encryption_profile_finger_8ae8
                CHECK (encryption_profile_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_worker_principal_fingerpr_6ec4
                CHECK (worker_principal_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_immutable_archive_receipts_correlation_id
                CHECK (length(correlation_id) BETWEEN 1 AND 100),
            CONSTRAINT ck_immutable_archive_receipts_format_metadata CHECK (
                length(canonicalization_version) BETWEEN 1 AND 100
                AND length(media_type) BETWEEN 1 AND 255
                AND length(media_type_version) BETWEEN 1 AND 100
                AND length(compression) BETWEEN 1 AND 50
                AND length(compression_version) BETWEEN 1 AND 100
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_immutable_archive_receipts_workspace_source
        ON retention.immutable_archive_receipts (workspace_id, source, source_partition)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_immutable_archive_receipts_workspace_verified
        ON retention.immutable_archive_receipts (workspace_id, verified_at)
        """
    )
    for table in ("archive_capability_attestations", "immutable_archive_receipts"):
        op.execute(f"ALTER TABLE retention.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE retention.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            DO $datariver$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'retention' AND tablename = '{table}'
                      AND policyname = 'workspace_isolation'
                ) THEN
                    CREATE POLICY workspace_isolation ON retention.{table}
                    USING (
                        workspace_id = NULLIF(
                            current_setting('app.workspace_id', true), ''
                        )::uuid
                    )
                    WITH CHECK (
                        workspace_id = NULLIF(
                            current_setting('app.workspace_id', true), ''
                        )::uuid
                    );
                END IF;
            END
            $datariver$
            """
        )
    _assert_archive_evidence_contract()
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT ON retention.archive_capability_attestations,
                    retention.immutable_archive_receipts TO datariver_app;
                REVOKE INSERT, UPDATE, DELETE
                    ON retention.archive_capability_attestations,
                        retention.immutable_archive_receipts
                    FROM datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Compatibility bridge: the regenerated 0001 owns this canonical evidence schema.
    pass


def _assert_archive_evidence_contract() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'retention'
                  AND table_name = 'archive_capability_attestations'
            ) <> 21 OR (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'retention'
                  AND table_name = 'immutable_archive_receipts'
            ) <> 43 THEN
                RAISE EXCEPTION 'immutable archive evidence column contract is invalid';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_immutable_archive_receipts_capability_attestation'
                  AND conrelid = 'retention.immutable_archive_receipts'::regclass
                  AND convalidated
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_immutable_archive_receipts_retention_policy'
                  AND conrelid = 'retention.immutable_archive_receipts'::regclass
                  AND convalidated
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_immutable_archive_receipts_content_readback_match'
                  AND conrelid = 'retention.immutable_archive_receipts'::regclass
                  AND convalidated
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_archive_capability_attestations_state_shape'
                  AND conrelid = 'retention.archive_capability_attestations'::regclass
                  AND convalidated
            ) THEN
                RAISE EXCEPTION 'immutable archive evidence constraints are incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_class table_row
                JOIN pg_namespace namespace_row
                  ON namespace_row.oid = table_row.relnamespace
                WHERE namespace_row.nspname = 'retention'
                  AND table_row.relname IN (
                      'archive_capability_attestations', 'immutable_archive_receipts'
                  )
                  AND (NOT table_row.relrowsecurity OR NOT table_row.relforcerowsecurity)
            ) OR (
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'retention'
                  AND tablename IN (
                      'archive_capability_attestations', 'immutable_archive_receipts'
                  )
                  AND policyname = 'workspace_isolation'
                  AND permissive = 'PERMISSIVE' AND cmd = 'ALL'
                  AND roles = ARRAY['public']::name[]
                  AND qual LIKE '%app.workspace_id%'
                  AND with_check LIKE '%app.workspace_id%'
            ) <> 2 THEN
                RAISE EXCEPTION 'immutable archive evidence RLS contract is invalid';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'retention'
                  AND indexname = 'ix_archive_capability_attestations_workspace_observed'
                  AND indexdef LIKE '%(workspace_id, configuration_fingerprint, observed_at)%'
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'retention'
                  AND indexname = 'ix_immutable_archive_receipts_workspace_source'
                  AND indexdef LIKE '%(workspace_id, source, source_partition)%'
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'retention'
                  AND indexname = 'ix_immutable_archive_receipts_workspace_verified'
                  AND indexdef LIKE '%(workspace_id, verified_at)%'
            ) THEN
                RAISE EXCEPTION 'immutable archive evidence index contract is invalid';
            END IF;
        END
        $datariver$
        """
    )
