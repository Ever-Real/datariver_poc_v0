# ruff: noqa: S608 -- table names come from a fixed source-owned allowlist.
"""Add the archive-only retention execution control plane.

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-23
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = {
    "policy_class_rules",
    "execution_jobs",
    "execution_attempts",
    "execution_events",
}
_POLICY_COLUMNS = {
    "contract_version",
    "effective_from",
    "effective_until",
    "execution_authorization_hours",
}
_RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
_RETENTION_EXECUTOR_ID = "00000000-0000-7000-8000-000000000003"
_ARCHIVE_SOURCE_V2_SQL = (
    "source IN ('OUTBOX_EVENTS', 'INBOX_MESSAGES', 'POLICY_DECISIONS', 'ASSISTANT_RUNS', "
    "'ERASURE_EXECUTION_EVIDENCE')"
)


def _archive_source_definition(values: tuple[str, ...]) -> str:
    encoded = ", ".join(f"'{value}'::character varying" for value in values)
    return f"CHECK (source::text = ANY (ARRAY[{encoded}]::text[]))"


_ARCHIVE_SOURCE_LEGACY_DEFINITION = _archive_source_definition(
    ("OUTBOX_EVENTS", "INBOX_MESSAGES", "POLICY_DECISIONS", "ASSISTANT_RUNS")
)
_ARCHIVE_SOURCE_V2_DEFINITION = _archive_source_definition(
    (
        "OUTBOX_EVENTS",
        "INBOX_MESSAGES",
        "POLICY_DECISIONS",
        "ASSISTANT_RUNS",
        "ERASURE_EXECUTION_EVIDENCE",
    )
)
_FINGERPRINT_TABLES = (
    "policy_versions",
    "erasure_requests",
    "immutable_archive_receipts",
    "policy_class_rules",
    "execution_jobs",
    "execution_attempts",
    "execution_events",
)
# PostgreSQL 17 semantic catalog fingerprints over every column, PK/UQ/CHECK/FK, index and RLS
# policy touched or consumed by this revision. Physical column ordinals are deliberately excluded.
# PostgreSQL still renders some generated definitions differently for the fresh canonical baseline
# and the additive 0041 bridge, so both independently rehearsed paths are allowlisted explicitly.
# Update only with reviewed model/migration evidence from both paths.
_EXPECTED_SCHEMA_FINGERPRINTS = frozenset(
    {
        "e7d66e854560db29c126f3768a3eb2d3b635c9a1f6b291bf7255b72149b75478",
        "0dcf7a560a9c9ccd090b4178c63af942283df77e1eae5e6f6841e9976dc16ae2",
    }
)


def _add_policy_contract() -> None:
    op.add_column(
        "policy_versions",
        sa.Column(
            "contract_version",
            sa.String(length=32),
            server_default=sa.text("'SINGLE_DEADLINE_V1'"),
            nullable=False,
        ),
        schema="retention",
    )
    op.add_column(
        "policy_versions",
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        schema="retention",
    )
    op.add_column(
        "policy_versions",
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        schema="retention",
    )
    op.add_column(
        "policy_versions",
        sa.Column("execution_authorization_hours", sa.Integer(), nullable=True),
        schema="retention",
    )
    op.create_check_constraint(
        "ck_policy_versions_contract_shape",
        "policy_versions",
        "(contract_version = 'SINGLE_DEADLINE_V1' AND effective_from IS NULL "
        "AND effective_until IS NULL AND execution_authorization_hours IS NULL) OR "
        "(contract_version = 'POLICY_BOOK_V2' AND effective_from IS NOT NULL "
        "AND (effective_until IS NULL OR effective_until > effective_from) "
        "AND execution_authorization_hours BETWEEN 1 AND 168)",
        schema="retention",
    )
    op.create_unique_constraint(
        "uq_retention_policy_versions_workspace_id_hash_number",
        "policy_versions",
        ["workspace_id", "id", "payload_hash", "policy_number"],
        schema="retention",
    )
    op.create_unique_constraint(
        "uq_erasure_requests_workspace_id_version_hash",
        "erasure_requests",
        ["workspace_id", "id", "version", "payload_hash"],
        schema="retention",
    )
    op.create_unique_constraint(
        "uq_immutable_archive_receipts_workspace_id_manifest",
        "immutable_archive_receipts",
        ["workspace_id", "id", "manifest_hash"],
        schema="retention",
    )


def _create_policy_class_rules() -> None:
    op.create_table(
        "policy_class_rules",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_number", sa.Integer(), nullable=False),
        sa.Column("data_class", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("minimum_value", sa.Integer(), nullable=False),
        sa.Column("maximum_value", sa.Integer(), nullable=False),
        sa.Column("archive_disposition", sa.String(length=24), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            "archive_disposition IN ('NO_ARCHIVE', 'EVIDENCE_ONLY', 'CONTENT_WORM')",
            name="ck_policy_class_rules_archive_disposition",
        ),
        sa.CheckConstraint(
            "data_class IN ('COMPLETED_OPERATIONS', 'CHAT_CONTENT', "
            "'AUDIT_EVIDENCE', 'OBJECT_DATA')",
            name="ck_policy_class_rules_data_class",
        ),
        sa.CheckConstraint(
            "minimum_value >= 0 AND maximum_value >= 1 "
            "AND minimum_value <= maximum_value "
            "AND ((unit = 'DAYS' AND maximum_value <= 36500) "
            "OR (unit = 'MONTHS' AND maximum_value <= 1200) "
            "OR (unit = 'YEARS' AND maximum_value <= 100))",
            name="ck_policy_class_rules_bounds",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_policy_class_rules_payload_hash_sha256",
        ),
        sa.CheckConstraint(
            "unit IN ('DAYS', 'MONTHS', 'YEARS')", name="ck_policy_class_rules_unit"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "policy_id", "policy_hash", "policy_number"],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
                "retention.policy_versions.policy_number",
            ],
            name="fk_retention_policy_class_rules_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name="fk_policy_class_rules_workspace_id_workspaces",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policy_class_rules"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_retention_policy_class_rules_workspace_id_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "policy_id",
            "data_class",
            name="uq_retention_policy_class_rules_workspace_policy_class",
        ),
        schema="retention",
    )
    op.create_index(
        "ix_retention_policy_class_rules_workspace_policy",
        "policy_class_rules",
        ["workspace_id", "policy_id", "data_class"],
        unique=False,
        schema="retention",
    )


def _create_execution_jobs() -> None:
    op.create_table(
        "execution_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("erasure_request_id", sa.Uuid(), nullable=False),
        sa.Column("erasure_request_version", sa.Integer(), nullable=False),
        sa.Column("erasure_request_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("target_owner_id", sa.Uuid(), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("target_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_number", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("checker_id", sa.Uuid(), nullable=False),
        sa.Column("executor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "execution_authorization_valid_until", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("archive_disposition", sa.String(length=24), nullable=False),
        sa.Column("archive_configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("archive_retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("maximum_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_owner_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_receipt_id", sa.Uuid(), nullable=True),
        sa.Column("archive_manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("last_failure_code", sa.String(length=100), nullable=True),
        sa.Column("destructive_state", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            "(state = 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED' "
            "AND archive_receipt_id IS NOT NULL AND archive_manifest_hash IS NOT NULL) OR "
            "(state = 'BLOCKED' "
            "AND (last_failure_code = 'KILL_SWITCH_DISABLED_AFTER_WRITE' "
            "OR last_failure_code LIKE 'POST_WRITE_RECEIPT_%') "
            "AND archive_receipt_id IS NOT NULL AND archive_manifest_hash IS NOT NULL) OR "
            "(state <> 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED' "
            "AND COALESCE(last_failure_code, '') <> 'KILL_SWITCH_DISABLED_AFTER_WRITE' "
            "AND COALESCE(last_failure_code, '') NOT LIKE 'POST_WRITE_RECEIPT_%' "
            "AND archive_receipt_id IS NULL AND archive_manifest_hash IS NULL)",
            name="ck_execution_jobs_archive_receipt_shape",
        ),
        sa.CheckConstraint(
            "(state = 'LEASED' AND lease_token_hash IS NOT NULL "
            "AND lease_owner_fingerprint IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'LEASED' AND lease_token_hash IS NULL "
            "AND lease_owner_fingerprint IS NULL AND lease_until IS NULL)",
            name="ck_execution_jobs_lease_shape",
        ),
        sa.CheckConstraint(
            "archive_disposition = 'EVIDENCE_ONLY'",
            name="ck_execution_jobs_archive_disposition",
        ),
        sa.CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$' "
            "AND erasure_request_payload_hash ~ '^[0-9a-f]{64}$' "
            "AND retention_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND archive_configuration_hash ~ '^[0-9a-f]{64}$' "
            "AND (archive_manifest_hash IS NULL "
            "OR archive_manifest_hash ~ '^[0-9a-f]{64}$')",
            name="ck_execution_jobs_hashes_sha256",
        ),
        sa.CheckConstraint(
            "destructive_state = 'DISABLED_NOT_READY'",
            name="ck_execution_jobs_destructive_disabled",
        ),
        sa.CheckConstraint("kind = 'EXPLICIT_ERASURE_EVIDENCE'", name="ck_execution_jobs_kind"),
        sa.CheckConstraint(
            "lease_owner_fingerprint IS NULL OR lease_owner_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_execution_jobs_lease_owner_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_execution_jobs_lease_token_hash_sha256",
        ),
        sa.CheckConstraint(
            "state IN ('PLANNED', 'LEASED', 'RETRY_WAIT', 'BLOCKED', "
            "'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED')",
            name="ck_execution_jobs_state",
        ),
        sa.CheckConstraint(
            "target_type = 'CHAT_SESSION' AND target_version > 0 "
            "AND target_owner_id IS NOT NULL AND classification BETWEEN 0 AND 3 "
            "AND target_snapshot_hash ~ '^[0-9a-f]{64}$'",
            name="ck_execution_jobs_target_shape",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= maximum_attempts "
            "AND maximum_attempts BETWEEN 1 AND 20 "
            "AND lease_epoch >= 0 AND version > 0",
            name="ck_execution_jobs_counters",
        ),
        sa.CheckConstraint(
            "requester_id <> checker_id "
            "AND checker_id <> target_owner_id "
            "AND executor_id <> requester_id "
            "AND executor_id <> checker_id "
            "AND executor_id <> target_owner_id",
            name="ck_execution_jobs_separation_of_duties",
        ),
        sa.CheckConstraint(
            "archive_retain_until > created_at",
            name="ck_execution_jobs_archive_retention_deadline",
        ),
        sa.CheckConstraint(
            "last_failure_code IS NULL OR length(last_failure_code) BETWEEN 1 AND 100",
            name="ck_execution_jobs_failure_code",
        ),
        sa.ForeignKeyConstraint(
            ["executor_id"],
            ["iam.subjects.id"],
            name="fk_retention_execution_jobs_executor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "archive_receipt_id", "archive_manifest_hash"],
            [
                "retention.immutable_archive_receipts.workspace_id",
                "retention.immutable_archive_receipts.id",
                "retention.immutable_archive_receipts.manifest_hash",
            ],
            name="fk_retention_execution_jobs_archive_receipt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "erasure_request_id",
                "erasure_request_version",
                "erasure_request_payload_hash",
            ],
            [
                "retention.erasure_requests.workspace_id",
                "retention.erasure_requests.id",
                "retention.erasure_requests.version",
                "retention.erasure_requests.payload_hash",
            ],
            name="fk_retention_execution_jobs_erasure_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "retention_policy_id", "retention_policy_hash", "policy_number"],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
                "retention.policy_versions.policy_number",
            ],
            name="fk_retention_execution_jobs_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name="fk_execution_jobs_workspace_id_workspaces",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_jobs"),
        sa.UniqueConstraint(
            "workspace_id", "command_hash", name="uq_retention_execution_jobs_command_hash"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "erasure_request_id",
            name="uq_retention_execution_jobs_erasure_request",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_retention_execution_jobs_workspace_id_id"
        ),
        schema="retention",
    )
    op.create_index(
        "ix_retention_execution_jobs_claim",
        "execution_jobs",
        ["workspace_id", "next_attempt_at", "created_at", "id"],
        unique=False,
        schema="retention",
        postgresql_where=sa.text("state IN ('PLANNED', 'RETRY_WAIT')"),
    )
    op.create_index(
        "ix_retention_execution_jobs_expired_lease",
        "execution_jobs",
        ["workspace_id", "lease_until", "id"],
        unique=False,
        schema="retention",
        postgresql_where=sa.text("state = 'LEASED'"),
    )


def _create_execution_evidence() -> None:
    op.create_table(
        "execution_attempts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=False),
        sa.Column("worker_principal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("external_response_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("destructive_effect_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$' "
            "AND (external_response_hash IS NULL "
            "OR external_response_hash ~ '^[0-9a-f]{64}$')",
            name="ck_execution_attempts_evidence_hashes",
        ),
        sa.CheckConstraint(
            "lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_execution_attempts_lease_token_hash",
        ),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'RETRY_WAIT', 'BLOCKED', "
            "'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED', 'SUPERSEDED')",
            name="ck_execution_attempts_state",
        ),
        sa.CheckConstraint(
            "worker_principal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_execution_attempts_worker_principal_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "attempt_no > 0 AND lease_epoch > 0",
            name="ck_execution_attempts_positive_fence",
        ),
        sa.CheckConstraint(
            "destructive_effect_count = 0",
            name="ck_execution_attempts_destructive_effect_zero",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_execution_attempts_timeline",
        ),
        sa.CheckConstraint(
            "length(correlation_id) BETWEEN 1 AND 100 "
            "AND (failure_code IS NULL OR length(failure_code) BETWEEN 1 AND 100)",
            name="ck_execution_attempts_bounded_text",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "execution_job_id"],
            ["retention.execution_jobs.workspace_id", "retention.execution_jobs.id"],
            name="fk_retention_execution_attempts_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name="fk_execution_attempts_workspace_id_workspaces",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_attempts"),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_job_id",
            "lease_epoch",
            name="uq_retention_execution_attempts_job_fence",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_retention_execution_attempts_workspace_id_id"
        ),
        schema="retention",
    )
    op.create_table(
        "execution_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('PLANNED', 'LEASED', 'RETRY_WAIT', 'BLOCKED', "
            "'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED')",
            name="ck_execution_events_event_type",
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_execution_events_evidence_hash_sha256",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR length(reason_code) BETWEEN 1 AND 100",
            name="ck_execution_events_reason_code",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_execution_events_sequence_positive"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "execution_job_id"],
            ["retention.execution_jobs.workspace_id", "retention.execution_jobs.id"],
            name="fk_retention_execution_events_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name="fk_execution_events_workspace_id_workspaces",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_events"),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_job_id",
            "sequence",
            name="uq_retention_execution_events_job_sequence",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_retention_execution_events_workspace_id_id"
        ),
        schema="retention",
    )
    op.create_index(
        "ix_retention_execution_events_workspace_job_time",
        "execution_events",
        ["workspace_id", "execution_job_id", "occurred_at"],
        unique=False,
        schema="retention",
    )


def _install_security_contract() -> None:
    for table in sorted(_TABLES):
        op.execute(f"ALTER TABLE retention.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE retention.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""DO $datariver$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'retention' AND tablename = '{table}'
                AND policyname = 'workspace_isolation'
            ) THEN
                CREATE POLICY workspace_isolation ON retention.{table}
                USING (workspace_id = {_RLS_SETTING})
                WITH CHECK (workspace_id = {_RLS_SETTING});
            END IF;
            END $datariver$"""
        )
    op.execute(
        """DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            GRANT SELECT, INSERT ON retention.policy_class_rules TO datariver_app;
            GRANT SELECT ON retention.execution_jobs TO datariver_app;
            GRANT SELECT ON retention.execution_attempts, retention.execution_events
                TO datariver_app;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_roles WHERE rolname = 'datariver_retention_scheduler'
        ) THEN
            GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention
                TO datariver_retention_scheduler;
            GRANT SELECT ON platform.workspaces, iam.subjects,
                iam.workspace_memberships, iam.access_roles,
                iam.access_role_assignments, authz.policy_decisions,
                retention.policy_versions, retention.policy_class_rules,
                retention.legal_holds, retention.erasure_requests,
                retention.erasure_request_events,
                assistant.chat_sessions TO datariver_retention_scheduler;
            GRANT SELECT, INSERT ON retention.execution_jobs,
                retention.execution_events TO datariver_retention_scheduler;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_archive') THEN
            GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention
                TO datariver_archive;
            GRANT SELECT ON platform.workspaces, iam.subjects,
                iam.workspace_memberships, iam.access_roles,
                iam.access_role_assignments, authz.policy_decisions,
                retention.policy_versions, retention.policy_class_rules,
                retention.legal_holds, retention.erasure_requests,
                retention.erasure_request_events,
                assistant.chat_sessions, retention.execution_jobs,
                retention.execution_attempts,
                retention.archive_capability_attestations,
                retention.immutable_archive_receipts TO datariver_archive;
            GRANT INSERT ON retention.archive_capability_attestations,
                retention.immutable_archive_receipts,
                retention.execution_attempts TO datariver_archive;
            GRANT SELECT, INSERT ON retention.execution_events TO datariver_archive;
            GRANT UPDATE (state, next_attempt_at, attempt_count, lease_epoch,
                lease_token_hash, lease_owner_fingerprint, lease_until,
                archive_receipt_id, archive_manifest_hash, last_failure_code,
                version, updated_at) ON retention.execution_jobs TO datariver_archive;
            GRANT UPDATE (state, stage, evidence_hash, external_response_hash,
                failure_code, finished_at)
                ON retention.execution_attempts TO datariver_archive;
        END IF;
        END $datariver$"""
    )


def _seed_and_verify_retention_executor(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO iam.subjects (
                id, issuer, external_subject, display_name, email,
                last_login_at, last_login_ip, active, created_at, updated_at
            ) VALUES (
                CAST(:executor_id AS uuid), 'urn:datariver:system',
                'retention-scheduler', 'DataRiver Retention Scheduler', NULL,
                NULL, NULL, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"executor_id": _RETENTION_EXECUTOR_ID},
    )
    row = (
        connection.execute(
            sa.text(
                """
            SELECT issuer, external_subject, display_name, active
            FROM iam.subjects WHERE id = CAST(:executor_id AS uuid)
            """
            ),
            {"executor_id": _RETENTION_EXECUTOR_ID},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or dict(row) != {
        "issuer": "urn:datariver:system",
        "external_subject": "retention-scheduler",
        "display_name": "DataRiver Retention Scheduler",
        "active": True,
    }:
        raise RuntimeError("The retention executor service principal is missing or malformed.")


def _phase2_schema_fingerprint(connection: sa.Connection) -> str:
    parameters = {"tables": list(_FINGERPRINT_TABLES)}
    statements = (
        sa.text(
            """
            SELECT table_name, column_name, data_type, udt_name,
                   character_maximum_length, numeric_precision, numeric_scale,
                   datetime_precision, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'retention'
              AND table_name = ANY(CAST(:tables AS text[]))
            ORDER BY table_name, column_name
            """
        ),
        sa.text(
            """
            SELECT table_state.relname AS table_name, constraint_state.conname,
                   constraint_state.contype, constraint_state.convalidated,
                   constraint_state.condeferrable, constraint_state.condeferred,
                   pg_get_constraintdef(constraint_state.oid, true) AS definition
            FROM pg_constraint AS constraint_state
            JOIN pg_class AS table_state ON table_state.oid = constraint_state.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = table_state.relnamespace
            WHERE namespace.nspname = 'retention'
              AND table_state.relname = ANY(CAST(:tables AS text[]))
            ORDER BY table_state.relname, constraint_state.conname
            """
        ),
        sa.text(
            """
            SELECT table_state.relname AS table_name, index_state.relname AS index_name,
                   pg_get_indexdef(index_state.oid) AS definition
            FROM pg_index AS index_contract
            JOIN pg_class AS table_state ON table_state.oid = index_contract.indrelid
            JOIN pg_class AS index_state ON index_state.oid = index_contract.indexrelid
            JOIN pg_namespace AS namespace ON namespace.oid = table_state.relnamespace
            WHERE namespace.nspname = 'retention'
              AND table_state.relname = ANY(CAST(:tables AS text[]))
            ORDER BY table_state.relname, index_state.relname
            """
        ),
        sa.text(
            """
            SELECT table_state.relname AS table_name,
                   table_state.relrowsecurity AS rls_enabled,
                   table_state.relforcerowsecurity AS rls_forced,
                   policy.policyname, policy.permissive,
                   array_to_string(policy.roles, ',') AS roles, policy.cmd,
                   policy.qual, policy.with_check
            FROM pg_class AS table_state
            JOIN pg_namespace AS namespace ON namespace.oid = table_state.relnamespace
            LEFT JOIN pg_policies AS policy
              ON policy.schemaname = namespace.nspname
             AND policy.tablename = table_state.relname
            WHERE namespace.nspname = 'retention'
              AND table_state.relname = ANY(CAST(:tables AS text[]))
            ORDER BY table_state.relname, policy.policyname
            """
        ),
    )
    document: list[list[dict[str, object]]] = []
    for statement in statements:
        rows = connection.execute(statement, parameters).mappings()
        document.append([dict(row) for row in rows])
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_schema_complete(inspector: sa.Inspector, connection: sa.Connection) -> None:
    expected_columns = {
        "policy_class_rules": {
            "workspace_id",
            "policy_id",
            "policy_hash",
            "policy_number",
            "data_class",
            "unit",
            "minimum_value",
            "maximum_value",
            "archive_disposition",
            "payload_hash",
            "id",
            "created_at",
            "updated_at",
        },
        "execution_jobs": {
            "workspace_id",
            "erasure_request_id",
            "target_snapshot_hash",
            "retention_policy_id",
            "command_hash",
            "state",
            "lease_epoch",
            "lease_token_hash",
            "archive_receipt_id",
            "destructive_state",
            "id",
            "created_at",
            "updated_at",
            "version",
        },
        "execution_attempts": {
            "workspace_id",
            "execution_job_id",
            "lease_epoch",
            "lease_token_hash",
            "state",
            "destructive_effect_count",
            "id",
        },
        "execution_events": {
            "workspace_id",
            "execution_job_id",
            "sequence",
            "event_type",
            "evidence_hash",
            "occurred_at",
            "id",
        },
    }
    for table, required in expected_columns.items():
        actual = {column["name"] for column in inspector.get_columns(table, schema="retention")}
        if not required <= actual:
            raise RuntimeError(f"Incomplete retention execution table: {table}")
    policy_columns = {
        column["name"] for column in inspector.get_columns("policy_versions", schema="retention")
    }
    if not _POLICY_COLUMNS <= policy_columns:
        raise RuntimeError("Incomplete POLICY_BOOK_V2 policy contract columns.")
    if _archive_source_contract(connection) != ("c", True, _ARCHIVE_SOURCE_V2_DEFINITION):
        raise RuntimeError("The immutable archive source vocabulary is incomplete or malformed.")
    actual_fingerprint = _phase2_schema_fingerprint(connection)
    if actual_fingerprint not in _EXPECTED_SCHEMA_FINGERPRINTS:
        raise RuntimeError(
            "The retention execution schema fingerprint is incomplete or malformed: "
            f"{actual_fingerprint}"
        )


def _archive_source_contract(connection: sa.Connection) -> tuple[str, bool, str] | None:
    row = (
        connection.execute(
            sa.text(
                """
                SELECT constraint_state.contype,
                       constraint_state.convalidated,
                       pg_get_constraintdef(constraint_state.oid, true) AS definition
                FROM pg_constraint AS constraint_state
                WHERE constraint_state.conrelid =
                        'retention.immutable_archive_receipts'::regclass
                  AND constraint_state.conname = 'ck_immutable_archive_receipts_source'
                """
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    constraint_type = row["contype"]
    if isinstance(constraint_type, bytes):
        constraint_type = constraint_type.decode("ascii")
    return str(constraint_type), bool(row["convalidated"]), str(row["definition"])


def _reconcile_archive_source(connection: sa.Connection) -> None:
    contract = _archive_source_contract(connection)
    if contract == ("c", True, _ARCHIVE_SOURCE_V2_DEFINITION):
        return
    if contract != ("c", True, _ARCHIVE_SOURCE_LEGACY_DEFINITION):
        raise RuntimeError(
            "Malformed immutable archive source constraint detected; refusing unsafe repair: "
            f"{contract!r}"
        )
    op.drop_constraint(
        op.f("ck_immutable_archive_receipts_source"),
        "immutable_archive_receipts",
        schema="retention",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_immutable_archive_receipts_source"),
        "immutable_archive_receipts",
        _ARCHIVE_SOURCE_V2_SQL,
        schema="retention",
    )


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = set(inspector.get_table_names(schema="retention")) & _TABLES
    policy_columns = {
        column["name"] for column in inspector.get_columns("policy_versions", schema="retention")
    }
    present_policy_columns = policy_columns & _POLICY_COLUMNS
    if existing_tables and existing_tables != _TABLES:
        raise RuntimeError("Partial retention execution schema detected; refusing unsafe repair.")
    if present_policy_columns and present_policy_columns != _POLICY_COLUMNS:
        raise RuntimeError(
            "Partial POLICY_BOOK_V2 policy contract detected; refusing unsafe repair."
        )
    if bool(existing_tables) != bool(present_policy_columns):
        raise RuntimeError("Retention execution tables and policy contract are out of sync.")
    if not existing_tables:
        _add_policy_contract()
        _create_policy_class_rules()
        _create_execution_jobs()
        _create_execution_evidence()
    _seed_and_verify_retention_executor(connection)
    _reconcile_archive_source(connection)
    _install_security_contract()
    inspector.clear_cache()
    _assert_schema_complete(inspector, connection)


def downgrade() -> None:
    # Canonical 0001 owns the evidence schema; destructive downgrade is intentionally disabled.
    pass
