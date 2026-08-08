"""Add the governed Knowledge source document upload profile.

Revision ID: 0085
Revises: 0084
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0085"
down_revision: str | Sequence[str] | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_object_manifests_content_profile_allowlist"
_LEGACY_PROFILES = (
    "FORMAT_ONLY_V1",
    "DATASET_DESCRIPTION_CSV_V1",
    "DATASET_DESCRIPTION_XLSX_V1",
    "CATALOG_METADATA_ROWS_CSV_V1",
    "CATALOG_METADATA_ROWS_XLSX_V1",
    "KNOWLEDGE_STUDIO_DOCUMENT_V1",
)
_KNOWLEDGE_SOURCE_PROFILE = "KNOWLEDGE_SOURCE_DOCUMENT_V1"
_LEGACY_MARKER_CONSTRAINT = "ck_object_manifests_legacy_knowledge_source_evidence"
_GRAPH_BINDING_CONSTRAINT = "ck_object_manifests_knowledge_source_graph_binding"
_GRAPH_BINDING_FK = "fk_object_manifests_workspace_id_knowledge_source_graph_id_graphs"
_MANIFEST_GRAPH_UQ = "uq_object_manifests_workspace_graph_id_id"
_SNAPSHOT_MANIFEST_GRAPH_FK = "fk_source_snapshots_manifest_graph"
_SNAPSHOT_GRAPH_UQ = "uq_source_snapshots_workspace_graph_id"
_JOB_SNAPSHOT_GRAPH_FK = "fk_source_analysis_jobs_snapshot_graph"
_LEGACY_SNAPSHOT_MANIFEST_FK = (
    "fk_source_snapshots_workspace_id_upload_id_object_manifests"
)
_LEGACY_JOB_SNAPSHOT_FK = "fk_source_analysis_jobs_workspace_id_source_snapshot_id_54e6"
_JOB_PROFILE_CONSTRAINT = "ck_source_analysis_jobs_source_content_profile_allowlist"
_JOB_EVIDENCE_CONSTRAINT = "ck_source_analysis_jobs_evidence_hashes"
_STATEMENT_BOUNDARY = "-- datariver-statement-boundary"

_SOURCE_ANALYSIS_POLICY_V3_UPGRADE_SQL = """
DO $datariver$
DECLARE
    function_oid regprocedure := to_regprocedure(
        'knowledge.enforce_source_analysis_shared_evidence_scope()'
    );
    definition text;
    upgraded_definition text;
    expected_token text := $token$'["builtin-abac-v2"]'::jsonb$token$;
    replacement_token text := $token$'["builtin-abac-v3"]'::jsonb$token$;
BEGIN
    IF function_oid IS NULL THEN
        RAISE EXCEPTION 'source-analysis shared evidence function is unavailable';
    END IF;
    SELECT pg_get_functiondef(function_oid) INTO definition;
    IF (
        length(definition) - length(replace(definition, expected_token, ''))
    ) / length(expected_token) <> 1
       OR position(replacement_token IN definition) > 0
    THEN
        RAISE EXCEPTION 'source-analysis policy evidence version is unexpected';
    END IF;
    upgraded_definition := replace(
        definition,
        expected_token,
        replacement_token
    );
    EXECUTE upgraded_definition;
END
$datariver$
"""

_SOURCE_ANALYSIS_POLICY_V2_DOWNGRADE_SQL = """
DO $datariver$
DECLARE
    function_oid regprocedure := to_regprocedure(
        'knowledge.enforce_source_analysis_shared_evidence_scope()'
    );
    definition text;
    downgraded_definition text;
    expected_token text := $token$'["builtin-abac-v3"]'::jsonb$token$;
    replacement_token text := $token$'["builtin-abac-v2"]'::jsonb$token$;
BEGIN
    IF function_oid IS NULL THEN
        RAISE EXCEPTION 'source-analysis shared evidence function is unavailable';
    END IF;
    SELECT pg_get_functiondef(function_oid) INTO definition;
    IF (
        length(definition) - length(replace(definition, expected_token, ''))
    ) / length(expected_token) <> 1
       OR position(replacement_token IN definition) > 0
    THEN
        RAISE EXCEPTION 'source-analysis policy evidence version is unexpected';
    END IF;
    downgraded_definition := replace(
        definition,
        expected_token,
        replacement_token
    );
    EXECUTE downgraded_definition;
END
$datariver$
"""

_LEGACY_MARKER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION integration.protect_legacy_knowledge_source_marker()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.legacy_knowledge_source_eligible THEN
        RAISE EXCEPTION 'legacy Knowledge source eligibility is migration-owned';
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.legacy_knowledge_source_eligible
           IS DISTINCT FROM OLD.legacy_knowledge_source_eligible THEN
        RAISE EXCEPTION 'legacy Knowledge source eligibility is immutable';
    END IF;
    RETURN NEW;
END
$$
"""

_LEGACY_MARKER_TRIGGER_SQL = """
CREATE TRIGGER trg_object_manifest_legacy_knowledge_source_marker
BEFORE INSERT OR UPDATE OF legacy_knowledge_source_eligible
ON integration.object_manifests
FOR EACH ROW EXECUTE FUNCTION integration.protect_legacy_knowledge_source_marker()
"""

_LEGACY_GRAPH_BINDING_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION knowledge.bind_legacy_source_manifest_graph_v1(
    p_workspace_id uuid,
    p_upload_id uuid,
    p_graph_id uuid
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, integration, knowledge
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    manifest integration.object_manifests%ROWTYPE;
    target_graph knowledge.graphs%ROWTYPE;
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
          NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR actor_id IS NULL
    THEN
        RAISE EXCEPTION 'legacy Knowledge source graph binding is not permitted'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO target_graph
    FROM knowledge.graphs
    WHERE workspace_id = p_workspace_id AND id = p_graph_id
    FOR SHARE;

    SELECT * INTO manifest
    FROM integration.object_manifests
    WHERE workspace_id = p_workspace_id AND id = p_upload_id
    FOR UPDATE;

    IF target_graph.id IS NULL
       OR manifest.id IS NULL
       OR manifest.owner_id <> actor_id
       OR NOT manifest.legacy_knowledge_source_eligible
       OR manifest.content_profile <> 'FORMAT_ONLY_V1'
       OR manifest.state <> 'ACCEPTED'
       OR manifest.mime <> 'application/pdf'
       OR manifest.actual_mime IS DISTINCT FROM manifest.mime
       OR manifest.actual_size_bytes IS DISTINCT FROM manifest.size_bytes
       OR manifest.actual_sha256 IS DISTINCT FROM manifest.sha256
       OR manifest.size_bytes NOT BETWEEN 1 AND 52428800
       OR manifest.classification NOT BETWEEN 0 AND 1
       OR manifest.classification > target_graph.classification
       OR manifest.validation_attempts <= 0
       OR manifest.validation_summary ->> 'content_type' IS DISTINCT FROM manifest.mime
       OR manifest.validation_summary ->> 'sha256' IS DISTINCT FROM manifest.sha256
       OR manifest.validation_summary -> 'size_bytes'
          IS DISTINCT FROM to_jsonb(manifest.size_bytes)
       OR manifest.validation_summary ->> 'validator_version'
          IS DISTINCT FROM 'integrity-format-v1'
       OR manifest.validation_summary ->> 'coverage'
          IS DISTINCT FROM 'FULL_SIGNATURE'
    THEN
        RAISE EXCEPTION 'legacy Knowledge source graph binding evidence is invalid'
            USING ERRCODE = '42501';
    END IF;

    IF manifest.knowledge_source_graph_id IS NULL THEN
        UPDATE integration.object_manifests
        SET knowledge_source_graph_id = p_graph_id
        WHERE workspace_id = p_workspace_id AND id = p_upload_id;
    ELSIF manifest.knowledge_source_graph_id <> p_graph_id THEN
        RAISE EXCEPTION 'legacy Knowledge source is bound to a different graph'
            USING ERRCODE = '23514';
    END IF;
    RETURN p_graph_id;
END
$$
"""

_GRAPH_BINDING_FENCE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION integration.protect_knowledge_source_graph_binding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    binder_owner name;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.knowledge_source_graph_id IS NOT NULL
           AND NEW.content_profile <> 'KNOWLEDGE_SOURCE_DOCUMENT_V1' THEN
            RAISE EXCEPTION 'only governed Knowledge source ingress may set a graph binding'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.knowledge_source_graph_id
       IS NOT DISTINCT FROM OLD.knowledge_source_graph_id THEN
        RETURN NEW;
    END IF;
    SELECT pg_get_userbyid(proowner) INTO binder_owner
    FROM pg_proc
    WHERE oid = to_regprocedure(
        'knowledge.bind_legacy_source_manifest_graph_v1(uuid,uuid,uuid)'
    );
    IF OLD.knowledge_source_graph_id IS NOT NULL
       OR NEW.knowledge_source_graph_id IS NULL
       OR NOT OLD.legacy_knowledge_source_eligible
       OR NOT NEW.legacy_knowledge_source_eligible
       OR binder_owner IS NULL
       OR current_user <> binder_owner
    THEN
        RAISE EXCEPTION 'Knowledge source graph binding is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$
"""

_GRAPH_BINDING_FENCE_TRIGGER_SQL = """
CREATE TRIGGER trg_object_manifest_knowledge_source_graph_binding
BEFORE INSERT OR UPDATE
ON integration.object_manifests
FOR EACH ROW EXECUTE FUNCTION integration.protect_knowledge_source_graph_binding()
"""

_JOB_VALIDATION_PINS_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION knowledge.protect_source_analysis_validation_pins()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.source_content_profile IS DISTINCT FROM OLD.source_content_profile
       OR NEW.source_validation_evidence_hash
           IS DISTINCT FROM OLD.source_validation_evidence_hash THEN
        RAISE EXCEPTION 'durable Knowledge source validation pins are immutable';
    END IF;
    RETURN NEW;
END
$$
"""

_JOB_VALIDATION_PINS_TRIGGER_SQL = """
CREATE TRIGGER trg_source_analysis_validation_pins
BEFORE UPDATE OF source_content_profile, source_validation_evidence_hash
ON knowledge.source_analysis_jobs
FOR EACH ROW EXECUTE FUNCTION knowledge.protect_source_analysis_validation_pins()
"""

_LEGACY_GRAPH_BINDING_GRANT_SQL = """
REVOKE ALL ON FUNCTION
knowledge.bind_legacy_source_manifest_graph_v1(uuid, uuid, uuid) FROM PUBLIC
"""

_LEGACY_GRAPH_BINDING_APP_GRANT_SQL = """
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT EXECUTE ON FUNCTION
        knowledge.bind_legacy_source_manifest_graph_v1(uuid, uuid, uuid)
        TO datariver_app;
    END IF;
END
$datariver$
"""

_MANIFEST_RUNTIME_FENCES_SQL = f"""
{_LEGACY_MARKER_FUNCTION_SQL}
{_STATEMENT_BOUNDARY}
{_LEGACY_MARKER_TRIGGER_SQL}
{_STATEMENT_BOUNDARY}
{_LEGACY_GRAPH_BINDING_FUNCTION_SQL}
{_STATEMENT_BOUNDARY}
{_GRAPH_BINDING_FENCE_FUNCTION_SQL}
{_STATEMENT_BOUNDARY}
{_GRAPH_BINDING_FENCE_TRIGGER_SQL}
{_STATEMENT_BOUNDARY}
{_LEGACY_GRAPH_BINDING_GRANT_SQL}
{_STATEMENT_BOUNDARY}
{_LEGACY_GRAPH_BINDING_APP_GRANT_SQL}
"""

_JOB_RUNTIME_FENCES_SQL = f"""
{_JOB_VALIDATION_PINS_FUNCTION_SQL}
{_STATEMENT_BOUNDARY}
{_JOB_VALIDATION_PINS_TRIGGER_SQL}
"""

_RUNTIME_FENCES_SQL = (
    _MANIFEST_RUNTIME_FENCES_SQL
    + f"\n{_STATEMENT_BOUNDARY}\n"
    + _JOB_RUNTIME_FENCES_SQL
    + f"\n{_STATEMENT_BOUNDARY}\n"
    + _SOURCE_ANALYSIS_POLICY_V3_UPGRADE_SQL
)


def split_postgresql_statements(sql: str) -> tuple[str, ...]:
    return tuple(
        statement.strip() for statement in sql.split(_STATEMENT_BOUNDARY) if statement.strip()
    )


def _allowlist(profiles: tuple[str, ...]) -> str:
    return "content_profile IN (" + ", ".join(f"'{profile}'" for profile in profiles) + ")"


def upgrade() -> None:
    if "legacy_knowledge_source_eligible" in [c["name"] for c in sa.inspect(op.get_bind()).get_columns("object_manifests", schema="integration")]: return
    op.add_column(
        "object_manifests",
        sa.Column(
            "legacy_knowledge_source_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="integration",
    )
    op.add_column(
        "object_manifests",
        sa.Column("knowledge_source_graph_id", sa.Uuid(), nullable=True),
        schema="integration",
    )
    op.execute(
        """
        UPDATE integration.object_manifests
        SET legacy_knowledge_source_eligible = true
        WHERE state = 'ACCEPTED'
          AND content_profile = 'FORMAT_ONLY_V1'
          AND mime = 'application/pdf'
          AND actual_mime = mime
          AND actual_size_bytes = size_bytes
          AND actual_sha256 = sha256
          AND size_bytes > 0
          AND size_bytes <= 52428800
          AND classification BETWEEN 0 AND 1
          AND validation_attempts > 0
          AND validation_summary ->> 'content_type' = mime
          AND validation_summary ->> 'sha256' = sha256
          AND validation_summary -> 'size_bytes' = to_jsonb(size_bytes)
          AND validation_summary ->> 'validator_version' = 'integrity-format-v1'
          AND validation_summary ->> 'coverage' = 'FULL_SIGNATURE'
        """
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT source.workspace_id, source.upload_id
                FROM knowledge.source_snapshots AS source
                GROUP BY source.workspace_id, source.upload_id
                HAVING count(DISTINCT source.graph_id) > 1
            ) THEN
                RAISE EXCEPTION
                    '0085 requires reconciliation of uploads bound to multiple Knowledge graphs';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM knowledge.source_analysis_jobs AS job
                JOIN knowledge.source_snapshots AS source
                  ON source.workspace_id = job.workspace_id
                 AND source.id = job.source_snapshot_id
                WHERE job.graph_id <> source.graph_id
            ) THEN
                RAISE EXCEPTION
                    '0085 requires reconciliation of source jobs bound to another graph';
            END IF;
        END
        $datariver$;
        """
    )
    op.execute(
        """
        UPDATE integration.object_manifests AS manifest
        SET knowledge_source_graph_id = source.graph_id
        FROM knowledge.source_snapshots AS source
        WHERE manifest.workspace_id = source.workspace_id
          AND manifest.id = source.upload_id
        """
    )
    op.create_foreign_key(
        op.f(_GRAPH_BINDING_FK),
        "object_manifests",
        "graphs",
        ["workspace_id", "knowledge_source_graph_id"],
        ["workspace_id", "id"],
        source_schema="integration",
        referent_schema="knowledge",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        _MANIFEST_GRAPH_UQ,
        "object_manifests",
        ["workspace_id", "knowledge_source_graph_id", "id"],
        schema="integration",
    )
    op.create_unique_constraint(
        _SNAPSHOT_GRAPH_UQ,
        "source_snapshots",
        ["workspace_id", "graph_id", "id"],
        schema="knowledge",
    )
    op.drop_constraint(
        _LEGACY_SNAPSHOT_MANIFEST_FK,
        "source_snapshots",
        schema="knowledge",
        type_="foreignkey",
    )
    op.create_foreign_key(
        _SNAPSHOT_MANIFEST_GRAPH_FK,
        "source_snapshots",
        "object_manifests",
        ["workspace_id", "graph_id", "upload_id"],
        ["workspace_id", "knowledge_source_graph_id", "id"],
        source_schema="knowledge",
        referent_schema="integration",
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        _LEGACY_JOB_SNAPSHOT_FK,
        "source_analysis_jobs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.create_foreign_key(
        _JOB_SNAPSHOT_GRAPH_FK,
        "source_analysis_jobs",
        "source_snapshots",
        ["workspace_id", "graph_id", "source_snapshot_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        op.f(_CONSTRAINT_NAME),
        "object_manifests",
        schema="integration",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_CONSTRAINT_NAME),
        "object_manifests",
        _allowlist((*_LEGACY_PROFILES, _KNOWLEDGE_SOURCE_PROFILE)),
        schema="integration",
    )
    op.create_check_constraint(
        op.f(_LEGACY_MARKER_CONSTRAINT),
        "object_manifests",
        "NOT legacy_knowledge_source_eligible OR ("
        "content_profile = 'FORMAT_ONLY_V1' AND mime = 'application/pdf' "
        "AND actual_mime = mime AND actual_size_bytes = size_bytes "
        "AND actual_sha256 = sha256 AND size_bytes > 0 AND size_bytes <= 52428800 "
        "AND classification BETWEEN 0 AND 1 AND validation_attempts > 0 "
        "AND validation_summary ->> 'content_type' = mime "
        "AND validation_summary ->> 'sha256' = sha256 "
        "AND validation_summary -> 'size_bytes' = to_jsonb(size_bytes) "
        "AND validation_summary ->> 'validator_version' = 'integrity-format-v1' "
        "AND validation_summary ->> 'coverage' = 'FULL_SIGNATURE')",
        schema="integration",
    )
    op.create_check_constraint(
        op.f(_GRAPH_BINDING_CONSTRAINT),
        "object_manifests",
        "(content_profile = 'KNOWLEDGE_SOURCE_DOCUMENT_V1' "
        "AND knowledge_source_graph_id IS NOT NULL "
        "AND NOT legacy_knowledge_source_eligible) OR "
        "(legacy_knowledge_source_eligible AND content_profile = 'FORMAT_ONLY_V1') OR "
        "(content_profile <> 'KNOWLEDGE_SOURCE_DOCUMENT_V1' "
        "AND NOT legacy_knowledge_source_eligible)",
        schema="integration",
    )
    for statement in split_postgresql_statements(_MANIFEST_RUNTIME_FENCES_SQL):
        op.execute(statement)

    op.add_column(
        "source_analysis_jobs",
        sa.Column("source_content_profile", sa.String(length=100), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "source_analysis_jobs",
        sa.Column("source_validation_evidence_hash", sa.String(length=64), nullable=True),
        schema="knowledge",
    )
    op.execute(
        """
        UPDATE knowledge.source_analysis_jobs AS job
        SET source_content_profile = manifest.content_profile,
            source_validation_evidence_hash = encode(sha256(
                int4send(octet_length(convert_to(
                    'KNOWLEDGE_SOURCE_LEGACY_VALIDATION_EVIDENCE_V1', 'UTF8'
                ))) || convert_to('KNOWLEDGE_SOURCE_LEGACY_VALIDATION_EVIDENCE_V1', 'UTF8') ||
                int4send(octet_length(convert_to(manifest.id::text, 'UTF8'))) ||
                    convert_to(manifest.id::text, 'UTF8') ||
                int4send(octet_length(convert_to(manifest.version::text, 'UTF8'))) ||
                    convert_to(manifest.version::text, 'UTF8') ||
                int4send(octet_length(convert_to(manifest.content_profile, 'UTF8'))) ||
                    convert_to(manifest.content_profile, 'UTF8') ||
                int4send(octet_length(convert_to(
                    manifest.legacy_knowledge_source_eligible::text, 'UTF8'
                ))) || convert_to(manifest.legacy_knowledge_source_eligible::text, 'UTF8') ||
                int4send(octet_length(convert_to(manifest.mime, 'UTF8'))) ||
                    convert_to(manifest.mime, 'UTF8') ||
                int4send(octet_length(convert_to(manifest.size_bytes::text, 'UTF8'))) ||
                    convert_to(manifest.size_bytes::text, 'UTF8') ||
                int4send(octet_length(convert_to(manifest.sha256, 'UTF8'))) ||
                    convert_to(manifest.sha256, 'UTF8') ||
                int4send(octet_length(convert_to(COALESCE(manifest.actual_mime, ''), 'UTF8'))) ||
                    convert_to(COALESCE(manifest.actual_mime, ''), 'UTF8') ||
                int4send(octet_length(convert_to(
                    COALESCE(manifest.actual_size_bytes::text, ''), 'UTF8'
                ))) || convert_to(COALESCE(manifest.actual_size_bytes::text, ''), 'UTF8') ||
                int4send(octet_length(convert_to(COALESCE(manifest.actual_sha256, ''), 'UTF8'))) ||
                    convert_to(COALESCE(manifest.actual_sha256, ''), 'UTF8') ||
                int4send(octet_length(convert_to(
                    COALESCE(manifest.validation_summary ->> 'validator_version', ''), 'UTF8'
                ))) || convert_to(
                    COALESCE(manifest.validation_summary ->> 'validator_version', ''), 'UTF8'
                ) ||
                int4send(octet_length(convert_to(
                    COALESCE(manifest.validation_summary ->> 'content_type', ''), 'UTF8'
                ))) || convert_to(
                    COALESCE(manifest.validation_summary ->> 'content_type', ''), 'UTF8'
                ) ||
                int4send(octet_length(convert_to(
                    COALESCE(manifest.validation_summary ->> 'size_bytes', ''), 'UTF8'
                ))) || convert_to(
                    COALESCE(manifest.validation_summary ->> 'size_bytes', ''), 'UTF8'
                ) ||
                int4send(octet_length(convert_to(
                    COALESCE(manifest.validation_summary ->> 'sha256', ''), 'UTF8'
                ))) || convert_to(
                    COALESCE(manifest.validation_summary ->> 'sha256', ''), 'UTF8'
                ) ||
                int4send(octet_length(convert_to(
                    COALESCE(manifest.validation_summary ->> 'coverage', ''), 'UTF8'
                ))) || convert_to(
                    COALESCE(manifest.validation_summary ->> 'coverage', ''), 'UTF8'
                )
            ), 'hex')
        FROM knowledge.source_snapshots AS source,
             integration.object_manifests AS manifest
        WHERE source.workspace_id = job.workspace_id
          AND source.id = job.source_snapshot_id
          AND manifest.workspace_id = source.workspace_id
          AND manifest.id = source.upload_id
        """
    )
    op.alter_column(
        "source_analysis_jobs",
        "source_content_profile",
        existing_type=sa.String(length=100),
        nullable=False,
        schema="knowledge",
    )
    op.alter_column(
        "source_analysis_jobs",
        "source_validation_evidence_hash",
        existing_type=sa.String(length=64),
        nullable=False,
        schema="knowledge",
    )
    op.drop_constraint(
        op.f(_JOB_EVIDENCE_CONSTRAINT),
        "source_analysis_jobs",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_JOB_EVIDENCE_CONSTRAINT),
        "source_analysis_jobs",
        "source_content_sha256 ~ '^[0-9a-f]{64}$' AND "
        "source_validation_evidence_hash ~ '^[0-9a-f]{64}$' AND "
        "ontology_checksum ~ '^[0-9a-f]{64}$' AND "
        "parser_config_hash ~ '^[0-9a-f]{64}$' AND "
        "embedding_binding_hash ~ '^[0-9a-f]{64}$' AND "
        "extraction_binding_hash ~ '^[0-9a-f]{64}$' AND "
        "pin_hash ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$' AND "
        "requester_authorization_hash ~ '^[0-9a-f]{64}$'",
        schema="knowledge",
    )
    op.create_check_constraint(
        op.f(_JOB_PROFILE_CONSTRAINT),
        "source_analysis_jobs",
        _allowlist((*_LEGACY_PROFILES, _KNOWLEDGE_SOURCE_PROFILE)).replace(
            "content_profile", "source_content_profile"
        ),
        schema="knowledge",
    )
    for statement in split_postgresql_statements(_JOB_RUNTIME_FENCES_SQL):
        op.execute(statement)
    op.execute(_SOURCE_ANALYSIS_POLICY_V3_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM integration.object_manifests
                WHERE content_profile = 'KNOWLEDGE_SOURCE_DOCUMENT_V1'
            ) THEN
                RAISE EXCEPTION
                    '0085 downgrade requires explicit reconciliation of Knowledge source uploads';
            END IF;
        END
        $datariver$;
        """
    )
    op.drop_constraint(
        _JOB_SNAPSHOT_GRAPH_FK,
        "source_analysis_jobs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_source_analysis_jobs_workspace_id_source_snapshot_id_source_snapshots"),
        "source_analysis_jobs",
        "source_snapshots",
        ["workspace_id", "source_snapshot_id"],
        ["workspace_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        _SNAPSHOT_MANIFEST_GRAPH_FK,
        "source_snapshots",
        schema="knowledge",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_source_snapshots_workspace_id_upload_id_object_manifests"),
        "source_snapshots",
        "object_manifests",
        ["workspace_id", "upload_id"],
        ["workspace_id", "id"],
        source_schema="knowledge",
        referent_schema="integration",
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        _SNAPSHOT_GRAPH_UQ,
        "source_snapshots",
        schema="knowledge",
        type_="unique",
    )
    op.drop_constraint(
        _MANIFEST_GRAPH_UQ,
        "object_manifests",
        schema="integration",
        type_="unique",
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_source_analysis_validation_pins "
        "ON knowledge.source_analysis_jobs"
    )
    op.execute("DROP FUNCTION IF EXISTS knowledge.protect_source_analysis_validation_pins()")
    op.drop_constraint(
        op.f(_JOB_PROFILE_CONSTRAINT),
        "source_analysis_jobs",
        schema="knowledge",
        type_="check",
    )
    op.drop_constraint(
        op.f(_JOB_EVIDENCE_CONSTRAINT),
        "source_analysis_jobs",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_JOB_EVIDENCE_CONSTRAINT),
        "source_analysis_jobs",
        "source_content_sha256 ~ '^[0-9a-f]{64}$' AND "
        "ontology_checksum ~ '^[0-9a-f]{64}$' AND "
        "parser_config_hash ~ '^[0-9a-f]{64}$' AND "
        "embedding_binding_hash ~ '^[0-9a-f]{64}$' AND "
        "extraction_binding_hash ~ '^[0-9a-f]{64}$' AND "
        "pin_hash ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$' AND "
        "requester_authorization_hash ~ '^[0-9a-f]{64}$'",
        schema="knowledge",
    )
    op.drop_column("source_analysis_jobs", "source_validation_evidence_hash", schema="knowledge")
    op.drop_column("source_analysis_jobs", "source_content_profile", schema="knowledge")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_object_manifest_legacy_knowledge_source_marker "
        "ON integration.object_manifests"
    )
    op.execute("DROP FUNCTION IF EXISTS integration.protect_legacy_knowledge_source_marker()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_object_manifest_knowledge_source_graph_binding "
        "ON integration.object_manifests"
    )
    op.execute("DROP FUNCTION IF EXISTS integration.protect_knowledge_source_graph_binding()")
    op.execute(
        "DROP FUNCTION IF EXISTS knowledge.bind_legacy_source_manifest_graph_v1(uuid, uuid, uuid)"
    )
    op.drop_constraint(
        op.f(_GRAPH_BINDING_CONSTRAINT),
        "object_manifests",
        schema="integration",
        type_="check",
    )
    op.drop_constraint(
        op.f(_LEGACY_MARKER_CONSTRAINT),
        "object_manifests",
        schema="integration",
        type_="check",
    )
    op.drop_constraint(
        op.f(_GRAPH_BINDING_FK),
        "object_manifests",
        schema="integration",
        type_="foreignkey",
    )
    op.drop_column("object_manifests", "knowledge_source_graph_id", schema="integration")
    op.drop_column("object_manifests", "legacy_knowledge_source_eligible", schema="integration")
    op.drop_constraint(
        op.f(_CONSTRAINT_NAME),
        "object_manifests",
        schema="integration",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_CONSTRAINT_NAME),
        "object_manifests",
        _allowlist(_LEGACY_PROFILES),
        schema="integration",
    )
    op.execute(_SOURCE_ANALYSIS_POLICY_V2_DOWNGRADE_SQL)
