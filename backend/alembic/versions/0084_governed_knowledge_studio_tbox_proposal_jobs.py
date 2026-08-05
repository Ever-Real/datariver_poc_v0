"""Add governed durable Knowledge Studio T-Box Proposal jobs.

Revision ID: 0084
Revises: 0083
Create Date: 2026-07-31
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SIGNATURES,
    TBOX_PROPOSAL_JOB_INTERNAL_FUNCTION_SIGNATURES,
    TBOX_PROPOSAL_JOB_WORKER_FUNCTION_SIGNATURES,
)

revision: str = "0084"
down_revision: str | Sequence[str] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTHORIZATION_FUNCTION_START = (
    "CREATE OR REPLACE FUNCTION knowledge.current_tbox_proposal_authorization_hash_v1("
)
_AUTHORIZATION_FUNCTION_END = (
    "\n\nCREATE OR REPLACE FUNCTION knowledge.current_tbox_proposal_human_can_v1("
)
_REVISION_0084_AUTHORIZATION_SHA256 = (
    "9c89eaa41c1b4b5b60d358ac6416336a568f605a5f397d4a216485acd7e823f9"
)
_REVISION_0084_AUTHORIZATION_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.current_tbox_proposal_authorization_hash_v1(
    p_workspace_id uuid,
    p_subject_id uuid
)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam, knowledge
AS $$
    SELECT knowledge.tbox_proposal_json_hash_v1(jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_PROPOSAL_REQUEST_AUTHORIZATION_V1',
        'subject_id', membership.subject_id::text,
        'workspace_id', membership.workspace_id::text,
        'active', subject.active AND membership.active AND (
            membership.access_expires_at IS NULL
            OR membership.access_expires_at > transaction_timestamp()
        ),
        'department_id', CASE WHEN membership.department_id IS NULL THEN NULL
            ELSE to_jsonb(membership.department_id::text) END,
        'groups', COALESCE((
            SELECT jsonb_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(
                COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
            ) AS item(value)
        ), '[]'::jsonb),
        'job_function', membership.job_function,
        'clearance', membership.clearance,
        'allowed_system_ids', COALESCE((
            SELECT jsonb_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(
                COALESCE(membership.attributes -> 'allowed_system_ids', '[]'::jsonb)
            ) AS item(value)
        ), '[]'::jsonb),
        'allowed_domain_ids', COALESCE((
            SELECT jsonb_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(
                COALESCE(membership.attributes -> 'allowed_domain_ids', '[]'::jsonb)
            ) AS item(value)
        ), '[]'::jsonb),
        'allowed_actions', COALESCE((
            SELECT jsonb_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(
                COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)
            ) AS item(value)
        ), '[]'::jsonb),
        'denied_actions', COALESCE((
            SELECT jsonb_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(
                COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb)
            ) AS item(value)
        ), '[]'::jsonb),
        'builtin_policy_version', 'builtin-abac-v3'
    ))
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = p_subject_id
$$;
""".strip()


def _revision_0084_function_sql() -> str:
    """Return the Proposal functions with the authorization contract as of 0084."""

    if hashlib.sha256(_REVISION_0084_AUTHORIZATION_FUNCTION_SQL.encode()).hexdigest() != (
        _REVISION_0084_AUTHORIZATION_SHA256
    ):
        raise RuntimeError("0084 authorization function snapshot changed")
    if (
        TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL.count(_AUTHORIZATION_FUNCTION_START) != 1
        or TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL.count(_AUTHORIZATION_FUNCTION_END) != 1
    ):
        raise RuntimeError("0084 authorization function boundary changed")
    prefix, _separator, remainder = TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL.partition(
        _AUTHORIZATION_FUNCTION_START
    )
    _current, _separator, suffix = remainder.partition(_AUTHORIZATION_FUNCTION_END)
    pinned = (
        prefix + _REVISION_0084_AUTHORIZATION_FUNCTION_SQL + _AUTHORIZATION_FUNCTION_END + suffix
    )
    if "iam.canonical_admin_bindings" in pinned or "iam.profile_role_assignments" in pinned:
        raise RuntimeError("0084 function SQL references a post-0084 Role authority table")
    return pinned


_ROLE_ASSERTION_SQL = """
DO $datariver$
DECLARE
    role_name text;
    role_is_safe boolean;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['datariver_app', 'datariver_knowledge_proposal']
    LOOP
        SELECT
            rolcanlogin
            AND NOT rolsuper
            AND NOT rolcreatedb
            AND NOT rolcreaterole
            AND NOT rolreplication
            AND NOT rolbypassrls
        INTO role_is_safe
        FROM pg_roles
        WHERE rolname = role_name;
        IF NOT COALESCE(role_is_safe, false) THEN
            RAISE EXCEPTION '% must be a safe NOBYPASSRLS LOGIN role', role_name;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_knowledge_proposal'
          AND pg_has_role('datariver_knowledge_proposal', candidate.oid, 'MEMBER')
    ) OR EXISTS (
        SELECT 1 FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_knowledge_proposal'
          AND NOT candidate.rolsuper
          AND pg_has_role(candidate.oid, 'datariver_knowledge_proposal', 'MEMBER')
    ) THEN
        RAISE EXCEPTION 'datariver_knowledge_proposal role membership is unsafe';
    END IF;
END
$datariver$;
""".strip()

_UPLOAD_PROFILE_SQL = """
ALTER TABLE integration.object_manifests
    DROP CONSTRAINT ck_object_manifests_content_profile_allowlist;
ALTER TABLE integration.object_manifests
    ADD CONSTRAINT ck_object_manifests_content_profile_allowlist CHECK (
        content_profile IN (
            'FORMAT_ONLY_V1',
            'DATASET_DESCRIPTION_CSV_V1',
            'DATASET_DESCRIPTION_XLSX_V1',
            'CATALOG_METADATA_ROWS_CSV_V1',
            'CATALOG_METADATA_ROWS_XLSX_V1',
            'KNOWLEDGE_STUDIO_DOCUMENT_V1'
        )
    );
""".strip()

_TABLES_SQL = """
CREATE TABLE knowledge.tbox_proposal_jobs (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    draft_id uuid NOT NULL,
    target_block_id uuid,
    requested_by uuid NOT NULL,
    input_kind varchar(32) NOT NULL,
    mode varchar(32) NOT NULL,
    base_draft_version integer NOT NULL,
    base_tbox_hash varchar(64) NOT NULL,
    request_hash varchar(64) NOT NULL,
    requester_authorization_hash varchar(64) NOT NULL,
    parser_config_hash varchar(64) NOT NULL,
    schema_binding_document jsonb NOT NULL,
    schema_binding_hash varchar(64) NOT NULL,
    source_pin_hash varchar(64) NOT NULL,
    pin_hash varchar(64) NOT NULL,
    prepared_at timestamptz NOT NULL,
    manifest_id uuid,
    manifest_version integer,
    source_content_hash varchar(64),
    source_media_type varchar(255),
    source_size_bytes integer,
    source_classification integer,
    source_content_profile varchar(100),
    source_validation_evidence_hash varchar(64),
    source_filename varchar(255),
    catalog_asset_id uuid,
    catalog_source_document jsonb,
    catalog_source_hash varchar(64),
    state varchar(24) NOT NULL,
    stage varchar(32) NOT NULL,
    progress_percent integer NOT NULL,
    attempt_count integer NOT NULL,
    maximum_attempts integer NOT NULL,
    next_attempt_at timestamptz NOT NULL,
    current_attempt_id uuid,
    lease_epoch bigint NOT NULL,
    lease_token_hash varchar(64),
    lease_owner_fingerprint varchar(255),
    lease_started_at timestamptz,
    lease_expires_at timestamptz,
    cancel_requested_by uuid,
    cancel_requested_at timestamptz,
    cancel_reason text,
    result_proposal_id uuid,
    result_evidence_hash varchar(64),
    last_failure_code varchar(100),
    completed_at timestamptz,
    supersedes_job_id uuid,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL,
    CONSTRAINT uq_tbox_proposal_jobs_workspace_id UNIQUE (workspace_id, id),
    CONSTRAINT uq_tbox_proposal_jobs_workspace_draft_id
        UNIQUE (workspace_id, draft_id, id),
    CONSTRAINT fk_tbox_proposal_jobs_draft
        FOREIGN KEY (workspace_id, draft_id)
        REFERENCES knowledge.studio_drafts (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_jobs_target_block
        FOREIGN KEY (workspace_id, draft_id, target_block_id)
        REFERENCES knowledge.tbox_draft_blocks (workspace_id, draft_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_jobs_requester
        FOREIGN KEY (workspace_id, requested_by)
        REFERENCES iam.workspace_memberships (workspace_id, subject_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_jobs_manifest
        FOREIGN KEY (workspace_id, manifest_id)
        REFERENCES integration.object_manifests (workspace_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_jobs_catalog_asset
        FOREIGN KEY (workspace_id, catalog_asset_id)
        REFERENCES catalog.assets_projection (workspace_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_jobs_canceller
        FOREIGN KEY (workspace_id, cancel_requested_by)
        REFERENCES iam.workspace_memberships (workspace_id, subject_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_jobs_result_proposal
        FOREIGN KEY (workspace_id, draft_id, result_proposal_id)
        REFERENCES knowledge.tbox_proposals (workspace_id, draft_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_jobs_supersedes
        FOREIGN KEY (workspace_id, supersedes_job_id)
        REFERENCES knowledge.tbox_proposal_jobs (workspace_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_tbox_proposal_jobs_input_kind_vocabulary CHECK (
        input_kind IN ('DOCUMENT_SCHEMA','CATALOG_SCHEMA')
    ),
    CONSTRAINT ck_tbox_proposal_jobs_mode_vocabulary CHECK (
        mode IN ('MERGE_INTO_CURRENT','APPEND_LAYER')
    ),
    CONSTRAINT ck_tbox_proposal_jobs_mode_target_shape CHECK (
        (mode = 'MERGE_INTO_CURRENT' AND target_block_id IS NOT NULL)
        OR (mode = 'APPEND_LAYER' AND target_block_id IS NULL)
    ),
    CONSTRAINT ck_tbox_proposal_jobs_state_vocabulary CHECK (
        state IN (
            'QUEUED','RUNNING','RETRY_WAIT','CANCEL_REQUESTED',
            'SUCCEEDED','FAILED','STALE','CANCELLED'
        )
    ),
    CONSTRAINT ck_tbox_proposal_jobs_stage_vocabulary CHECK (
        stage IN (
            'QUEUED','SOURCE_VALIDATION','PARSING','INFERENCE',
            'VALIDATING','FINALIZING','COMPLETED'
        )
    ),
    CONSTRAINT ck_tbox_proposal_jobs_source_versions_positive CHECK (
        base_draft_version >= 1 AND (manifest_version IS NULL OR manifest_version >= 1)
    ),
    CONSTRAINT ck_tbox_proposal_jobs_source_size_range CHECK (
        source_size_bytes IS NULL OR source_size_bytes BETWEEN 1 AND 10485760
    ),
    CONSTRAINT ck_tbox_proposal_jobs_source_classification_range CHECK (
        source_classification IS NULL OR source_classification BETWEEN 0 AND 1
    ),
    CONSTRAINT ck_tbox_proposal_jobs_positive_counters CHECK (
        attempt_count >= 0 AND maximum_attempts BETWEEN 1 AND 20
        AND attempt_count <= maximum_attempts
        AND lease_epoch >= attempt_count AND version >= 1
    ),
    CONSTRAINT ck_tbox_proposal_jobs_evidence_hashes CHECK (
        request_hash ~ '^[0-9a-f]{64}$'
        AND requester_authorization_hash ~ '^[0-9a-f]{64}$'
        AND base_tbox_hash ~ '^[0-9a-f]{64}$'
        AND parser_config_hash ~ '^[0-9a-f]{64}$'
        AND schema_binding_hash ~ '^[0-9a-f]{64}$'
        AND source_pin_hash ~ '^[0-9a-f]{64}$'
        AND pin_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_tbox_proposal_jobs_schema_binding_bounded CHECK (
        jsonb_typeof(schema_binding_document) = 'object'
        AND octet_length(schema_binding_document::text) <= 8192
    ),
    CONSTRAINT ck_tbox_proposal_jobs_source_pin_shape CHECK (
        (
            input_kind = 'DOCUMENT_SCHEMA'
            AND manifest_id IS NOT NULL AND manifest_version IS NOT NULL
            AND source_content_hash ~ '^[0-9a-f]{64}$'
            AND source_media_type IS NOT NULL AND source_size_bytes IS NOT NULL
            AND source_classification IS NOT NULL AND source_content_profile IS NOT NULL
            AND source_validation_evidence_hash ~ '^[0-9a-f]{64}$'
            AND source_filename IS NOT NULL
            AND catalog_asset_id IS NULL AND catalog_source_document IS NULL
            AND catalog_source_hash IS NULL
        ) OR (
            input_kind = 'CATALOG_SCHEMA'
            AND manifest_id IS NULL AND manifest_version IS NULL
            AND source_content_hash IS NULL AND source_media_type IS NULL
            AND source_size_bytes IS NULL AND source_content_profile IS NULL
            AND source_validation_evidence_hash IS NULL AND source_filename IS NULL
            AND source_classification IS NOT NULL AND catalog_asset_id IS NOT NULL
            AND jsonb_typeof(catalog_source_document) = 'object'
            AND octet_length(catalog_source_document::text) <= 65536
            AND catalog_source_hash ~ '^[0-9a-f]{64}$'
        )
    ),
    CONSTRAINT ck_tbox_proposal_jobs_lease_token_hash CHECK (
        lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_tbox_proposal_jobs_lease_shape CHECK (
        (
            state IN ('RUNNING','CANCEL_REQUESTED')
            AND current_attempt_id IS NOT NULL AND lease_token_hash IS NOT NULL
            AND lease_owner_fingerprint IS NOT NULL AND lease_started_at IS NOT NULL
            AND lease_expires_at IS NOT NULL
        ) OR (
            state NOT IN ('RUNNING','CANCEL_REQUESTED')
            AND current_attempt_id IS NULL AND lease_token_hash IS NULL
            AND lease_owner_fingerprint IS NULL AND lease_started_at IS NULL
            AND lease_expires_at IS NULL
        )
    ),
    CONSTRAINT ck_tbox_proposal_jobs_result_shape CHECK (
        (
            state = 'SUCCEEDED' AND result_proposal_id IS NOT NULL
            AND result_evidence_hash ~ '^[0-9a-f]{64}$'
            AND completed_at IS NOT NULL AND last_failure_code IS NULL
        ) OR (
            state <> 'SUCCEEDED' AND result_proposal_id IS NULL
            AND result_evidence_hash IS NULL
        )
    ),
    CONSTRAINT ck_tbox_proposal_jobs_failure_shape CHECK (
        (
            state IN ('FAILED','STALE','RETRY_WAIT')
            AND last_failure_code IS NOT NULL
        ) OR (
            state NOT IN ('FAILED','STALE','RETRY_WAIT')
            AND last_failure_code IS NULL
        )
    ),
    CONSTRAINT ck_tbox_proposal_jobs_cancel_shape CHECK (
        (
            state IN ('CANCEL_REQUESTED','CANCELLED')
            AND cancel_requested_by IS NOT NULL
            AND cancel_requested_at IS NOT NULL AND cancel_reason IS NOT NULL
        ) OR (
            state NOT IN ('CANCEL_REQUESTED','CANCELLED')
            AND cancel_requested_by IS NULL
            AND cancel_requested_at IS NULL AND cancel_reason IS NULL
        )
    ),
    CONSTRAINT ck_tbox_proposal_jobs_terminal_completion CHECK (
        (state IN ('SUCCEEDED','FAILED','STALE','CANCELLED'))
        = (completed_at IS NOT NULL)
    ),
    CONSTRAINT ck_tbox_proposal_jobs_terminal_stage CHECK (
        (state IN ('SUCCEEDED','FAILED','STALE','CANCELLED'))
        = (stage = 'COMPLETED')
    ),
    CONSTRAINT ck_tbox_proposal_jobs_state_progress CHECK (
        (state IN ('QUEUED','RETRY_WAIT') AND progress_percent = 0)
        OR (state IN ('RUNNING','CANCEL_REQUESTED')
            AND progress_percent BETWEEN 1 AND 99)
        OR (state = 'SUCCEEDED' AND progress_percent = 100)
        OR (state IN ('FAILED','STALE','CANCELLED')
            AND progress_percent BETWEEN 0 AND 99)
    )
);

CREATE TABLE knowledge.tbox_proposal_attempts (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    job_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    lease_epoch bigint NOT NULL,
    lease_token_hash varchar(64) NOT NULL,
    worker_fingerprint varchar(255) NOT NULL,
    state varchar(24) NOT NULL,
    stage varchar(32) NOT NULL,
    claimed_at timestamptz NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    retryable boolean,
    output_hash varchar(64),
    failure_code varchar(100),
    finished_at timestamptz,
    CONSTRAINT uq_tbox_proposal_attempts_workspace_id UNIQUE (workspace_id, id),
    CONSTRAINT uq_tbox_proposal_attempts_workspace_job_id
        UNIQUE (workspace_id, job_id, id),
    CONSTRAINT uq_tbox_proposal_attempts_job_attempt_no
        UNIQUE (workspace_id, job_id, attempt_no),
    CONSTRAINT uq_tbox_proposal_attempts_job_lease_epoch
        UNIQUE (workspace_id, job_id, lease_epoch),
    CONSTRAINT fk_tbox_proposal_attempts_job
        FOREIGN KEY (workspace_id, job_id)
        REFERENCES knowledge.tbox_proposal_jobs (workspace_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_tbox_proposal_attempts_state_vocabulary CHECK (
        state IN ('RUNNING','SUCCEEDED','FAILED','STALE','CANCELLED','SUPERSEDED')
    ),
    CONSTRAINT ck_tbox_proposal_attempts_stage_vocabulary CHECK (
        stage IN (
            'SOURCE_VALIDATION','PARSING','INFERENCE',
            'VALIDATING','FINALIZING','COMPLETED'
        )
    ),
    CONSTRAINT ck_tbox_proposal_attempts_claim_shape CHECK (
        attempt_no >= 1 AND lease_epoch >= 1
        AND lease_token_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_tbox_proposal_attempts_output_hash CHECK (
        output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_tbox_proposal_attempts_finished_shape CHECK (
        (state = 'RUNNING' AND finished_at IS NULL)
        OR (state <> 'RUNNING' AND finished_at IS NOT NULL)
    )
);

ALTER TABLE knowledge.tbox_proposal_jobs
    ADD CONSTRAINT fk_tbox_proposal_jobs_current_attempt
    FOREIGN KEY (workspace_id, id, current_attempt_id)
    REFERENCES knowledge.tbox_proposal_attempts (workspace_id, job_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE knowledge.tbox_proposal_events (
    workspace_id uuid NOT NULL,
    job_id uuid NOT NULL,
    sequence bigint NOT NULL,
    attempt_id uuid,
    state varchar(24) NOT NULL,
    stage varchar(32) NOT NULL,
    actor_kind varchar(16) NOT NULL,
    actor_ref varchar(300) NOT NULL,
    reason_code varchar(100),
    details_document jsonb NOT NULL,
    evidence_hash varchar(64) NOT NULL,
    occurred_at timestamptz NOT NULL,
    PRIMARY KEY (workspace_id, job_id, sequence),
    CONSTRAINT fk_tbox_proposal_events_job
        FOREIGN KEY (workspace_id, job_id)
        REFERENCES knowledge.tbox_proposal_jobs (workspace_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tbox_proposal_events_attempt
        FOREIGN KEY (workspace_id, job_id, attempt_id)
        REFERENCES knowledge.tbox_proposal_attempts (workspace_id, job_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_tbox_proposal_events_sequence_positive CHECK (sequence >= 1),
    CONSTRAINT ck_tbox_proposal_events_state_vocabulary CHECK (
        state IN (
            'QUEUED','RUNNING','RETRY_WAIT','CANCEL_REQUESTED',
            'SUCCEEDED','FAILED','STALE','CANCELLED'
        )
    ),
    CONSTRAINT ck_tbox_proposal_events_stage_vocabulary CHECK (
        stage IN (
            'QUEUED','SOURCE_VALIDATION','PARSING','INFERENCE',
            'VALIDATING','FINALIZING','COMPLETED'
        )
    ),
    CONSTRAINT ck_tbox_proposal_events_evidence_shape CHECK (
        actor_kind IN ('HUMAN','SERVICE')
        AND char_length(actor_ref) BETWEEN 1 AND 300
        AND evidence_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_tbox_proposal_events_details_document_bounded CHECK (
        jsonb_typeof(details_document) = 'object'
        AND octet_length(details_document::text) <= 8192
    )
);

CREATE INDEX ix_tbox_proposal_jobs_owner_state
ON knowledge.tbox_proposal_jobs
    (workspace_id, draft_id, requested_by, state, created_at DESC, id DESC);
CREATE INDEX ix_tbox_proposal_jobs_claim
ON knowledge.tbox_proposal_jobs
    (workspace_id, next_attempt_at, created_at, id)
WHERE state IN ('QUEUED','RETRY_WAIT');
CREATE INDEX ix_tbox_proposal_jobs_expired
ON knowledge.tbox_proposal_jobs (workspace_id, lease_expires_at, id)
WHERE state IN ('RUNNING','CANCEL_REQUESTED');
CREATE UNIQUE INDEX ux_tbox_proposal_jobs_one_successor
ON knowledge.tbox_proposal_jobs (workspace_id, supersedes_job_id)
WHERE supersedes_job_id IS NOT NULL;
CREATE INDEX ix_tbox_proposal_attempts_job
ON knowledge.tbox_proposal_attempts (workspace_id, job_id, attempt_no);
CREATE INDEX ix_tbox_proposal_events_job
ON knowledge.tbox_proposal_events (workspace_id, job_id, sequence);
""".strip()

_HISTORICAL_PROMPT_SANITIZATION_SQL = """
DO $datariver$
BEGIN
    IF EXISTS (
        SELECT 1 FROM knowledge.tbox_proposals
        WHERE source_reference_document IS NOT NULL
          AND jsonb_typeof(source_reference_document) <> 'object'
    ) THEN
        RAISE EXCEPTION
            '0084 requires explicit reconciliation of non-object Proposal source evidence';
    END IF;
    UPDATE knowledge.tbox_proposals
    SET source_reference_document =
            COALESCE(source_reference_document, '{}'::jsonb)
            || jsonb_build_object(
                'legacy_prompt_hash',
                encode(sha256(convert_to(prompt, 'UTF8')), 'hex')
            ),
        prompt = 'Governed Schema Assistant proposal',
        updated_at = transaction_timestamp(),
        version = version + 1;
END
$datariver$;
""".strip()

_RLS_TRIGGERS_SQL = """
CREATE TRIGGER enforce_tbox_proposal_job_pin_immutability
BEFORE UPDATE ON knowledge.tbox_proposal_jobs
FOR EACH ROW EXECUTE FUNCTION
    knowledge.enforce_tbox_proposal_job_pin_immutability_v1();
CREATE TRIGGER reject_tbox_proposal_job_delete
BEFORE DELETE ON knowledge.tbox_proposal_jobs
FOR EACH ROW EXECUTE FUNCTION
    knowledge.reject_tbox_proposal_evidence_mutation_v1();
CREATE TRIGGER enforce_tbox_proposal_attempt_immutability
BEFORE UPDATE ON knowledge.tbox_proposal_attempts
FOR EACH ROW EXECUTE FUNCTION
    knowledge.enforce_tbox_proposal_attempt_immutability_v1();
CREATE TRIGGER reject_tbox_proposal_attempt_delete
BEFORE DELETE ON knowledge.tbox_proposal_attempts
FOR EACH ROW EXECUTE FUNCTION
    knowledge.reject_tbox_proposal_evidence_mutation_v1();
CREATE TRIGGER reject_tbox_proposal_event_mutation
BEFORE UPDATE OR DELETE ON knowledge.tbox_proposal_events
FOR EACH ROW EXECUTE FUNCTION
    knowledge.reject_tbox_proposal_evidence_mutation_v1();
CREATE TRIGGER enforce_tbox_proposal_content_safety
BEFORE INSERT OR UPDATE ON knowledge.tbox_proposals
FOR EACH ROW EXECUTE FUNCTION
    knowledge.enforce_tbox_proposal_content_safety_v1();

ALTER TABLE knowledge.tbox_proposal_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.tbox_proposal_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge.tbox_proposal_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.tbox_proposal_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge.tbox_proposal_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.tbox_proposal_events FORCE ROW LEVEL SECURITY;

CREATE POLICY tbox_proposal_jobs_owner
ON knowledge.tbox_proposal_jobs
USING (
    session_user = 'datariver_app'
    AND workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND requested_by = NULLIF(current_setting('app.subject_id', true), '')::uuid
)
WITH CHECK (
    session_user = 'datariver_app'
    AND workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND requested_by = NULLIF(current_setting('app.subject_id', true), '')::uuid
);
CREATE POLICY tbox_proposal_attempts_deny_direct
ON knowledge.tbox_proposal_attempts
USING (false) WITH CHECK (false);
CREATE POLICY tbox_proposal_events_owner
ON knowledge.tbox_proposal_events
USING (
    session_user = 'datariver_app'
    AND workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND EXISTS (
        SELECT 1 FROM knowledge.tbox_proposal_jobs AS job
        WHERE job.workspace_id = tbox_proposal_events.workspace_id
          AND job.id = tbox_proposal_events.job_id
          AND job.requested_by =
              NULLIF(current_setting('app.subject_id', true), '')::uuid
    )
)
WITH CHECK (false);
""".strip()

_GRANTS_SQL = """
DO $datariver$
BEGIN
    REVOKE ALL PRIVILEGES ON knowledge.tbox_proposal_jobs,
        knowledge.tbox_proposal_attempts,
        knowledge.tbox_proposal_events
        FROM datariver_app, datariver_knowledge_proposal;
    REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA knowledge
        FROM datariver_knowledge_proposal;
    REVOKE ALL PRIVILEGES ON SCHEMA knowledge
        FROM datariver_knowledge_proposal;
    GRANT USAGE ON SCHEMA knowledge TO datariver_knowledge_proposal;

    GRANT EXECUTE ON FUNCTION knowledge.request_tbox_proposal_job_v1(
        uuid,uuid,uuid,uuid,text,text,integer,text,text,text,
        jsonb,text,text,jsonb,text,text,integer,text
    ) TO datariver_app;
    GRANT EXECUTE ON FUNCTION knowledge.get_owned_tbox_proposal_job_v1(
        uuid,uuid,uuid,uuid
    ) TO datariver_app;
    GRANT EXECUTE ON FUNCTION knowledge.list_owned_tbox_proposal_jobs_v1(
        uuid,uuid,uuid,integer,text
    ) TO datariver_app;
    GRANT EXECUTE ON FUNCTION knowledge.cancel_tbox_proposal_job_v1(
        uuid,uuid,uuid,uuid,integer,text,text,text
    ) TO datariver_app;
    GRANT EXECUTE ON FUNCTION knowledge.retry_tbox_proposal_job_v1(
        uuid,uuid,uuid,uuid,integer,text,text
    ) TO datariver_app;

    GRANT EXECUTE ON FUNCTION knowledge.claim_tbox_proposal_job_v1(
        uuid,text,text,integer
    ) TO datariver_knowledge_proposal;
    GRANT EXECUTE ON FUNCTION knowledge.renew_tbox_proposal_job_v1(
        uuid,uuid,uuid,bigint,text,text,integer,text,integer
    ) TO datariver_knowledge_proposal;
    GRANT EXECUTE ON FUNCTION knowledge.ensure_tbox_proposal_job_current_v1(
        uuid,uuid,uuid,bigint,text,text,jsonb
    ) TO datariver_knowledge_proposal;
    GRANT EXECUTE ON FUNCTION knowledge.complete_tbox_proposal_job_v1(
        uuid,uuid,uuid,bigint,text,text,text,jsonb,jsonb,text,jsonb,jsonb,text
    ) TO datariver_knowledge_proposal;
    GRANT EXECUTE ON FUNCTION knowledge.fail_tbox_proposal_job_v1(
        uuid,uuid,uuid,bigint,text,text,text,text,boolean,boolean
    ) TO datariver_knowledge_proposal;
END
$datariver$;
""".strip()


def split_postgresql_statements(sql: str) -> tuple[str, ...]:
    """Split PostgreSQL without breaking quoted or dollar-quoted bodies."""
    statements: list[str] = []
    statement_start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    block_comment_depth = 0
    in_line_comment = False
    while index < len(sql):
        if in_line_comment:
            if sql[index] == "\n":
                in_line_comment = False
            index += 1
            continue
        if block_comment_depth:
            if sql.startswith("/*", index):
                block_comment_depth += 1
                index += 2
            elif sql.startswith("*/", index):
                block_comment_depth -= 1
                index += 2
            else:
                index += 1
            continue
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue
        if quote is not None:
            if sql[index] == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if sql.startswith("--", index):
            in_line_comment = True
            index += 2
            continue
        if sql.startswith("/*", index):
            block_comment_depth = 1
            index += 2
            continue
        if sql[index] in {"'", '"'}:
            quote = sql[index]
            index += 1
            continue
        if sql[index] == "$":
            tag_end = sql.find("$", index + 1)
            if tag_end != -1:
                candidate = sql[index : tag_end + 1]
                tag_body = candidate[1:-1]
                if not tag_body or (
                    (tag_body[0].isalpha() or tag_body[0] == "_")
                    and all(character.isalnum() or character == "_" for character in tag_body)
                ):
                    dollar_tag = candidate
                    index = tag_end + 1
                    continue
        if sql[index] == ";":
            statement = sql[statement_start : index + 1].strip()
            if statement:
                statements.append(statement)
            statement_start = index + 1
        index += 1
    remainder = sql[statement_start:].strip()
    if remainder:
        statements.append(remainder)
    if quote is not None or dollar_tag is not None or block_comment_depth:
        raise ValueError("Unterminated quoted PostgreSQL migration script")
    return tuple(statements)


def _execute_sql_script(sql: str) -> None:
    for statement in split_postgresql_statements(sql):
        op.execute(statement)


def upgrade() -> None:
    op.execute(_ROLE_ASSERTION_SQL)
    _execute_sql_script(_UPLOAD_PROFILE_SQL)
    _execute_sql_script(_TABLES_SQL)
    _execute_sql_script(_revision_0084_function_sql())
    op.execute(_HISTORICAL_PROMPT_SANITIZATION_SQL)
    _execute_sql_script(_RLS_TRIGGERS_SQL)
    for signature in (
        *TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SIGNATURES,
        *TBOX_PROPOSAL_JOB_WORKER_FUNCTION_SIGNATURES,
        *TBOX_PROPOSAL_JOB_INTERNAL_FUNCTION_SIGNATURES,
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(_GRANTS_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0084 is append-only and requires an explicit operator-authored reconciliation downgrade."
    )
