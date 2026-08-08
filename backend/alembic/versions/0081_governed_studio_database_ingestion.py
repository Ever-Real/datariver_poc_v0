import sqlalchemy as sa
"""Add governed Knowledge Studio database ingestion execution plane.

Revision ID: 0081
Revises: 0080
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_ingestion_sql import (
    STUDIO_INGESTION_ALL_FUNCTION_SQL,
    STUDIO_INGESTION_FUNCTION_SIGNATURES,
    STUDIO_INGESTION_INTERNAL_FUNCTION_SIGNATURES,
)

revision: str = "0081"
down_revision: str | Sequence[str] | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_ASSERTION_SQL = """
DO $datariver$
DECLARE
    role_name text;
    role_is_safe boolean;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['datariver_app', 'datariver_knowledge_ingestion']
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
        SELECT 1
        FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_knowledge_ingestion'
          AND pg_has_role('datariver_knowledge_ingestion', candidate.oid, 'MEMBER')
    ) OR EXISTS (
        SELECT 1
        FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_knowledge_ingestion'
          AND NOT candidate.rolsuper
          AND pg_has_role(candidate.oid, 'datariver_knowledge_ingestion', 'MEMBER')
    ) THEN
        RAISE EXCEPTION 'datariver_knowledge_ingestion role membership is unsafe';
    END IF;
END
$datariver$;
""".strip()

_LEGACY_GUARD_SQL = """
DO $datariver$
BEGIN
    LOCK TABLE knowledge.studio_ingestion_jobs IN ACCESS EXCLUSIVE MODE;
    IF EXISTS (SELECT 1 FROM knowledge.studio_ingestion_jobs) THEN
        RAISE EXCEPTION
            '0081 requires explicit reconciliation of legacy Studio ingestion jobs';
    END IF;
END
$datariver$;
""".strip()

_TABLES_SQL = """
DROP TABLE knowledge.studio_ingestion_jobs;

CREATE TABLE knowledge.studio_ingestion_jobs (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    graph_id uuid NOT NULL,
    draft_id uuid NOT NULL,
    studio_release_id uuid NOT NULL,
    studio_release_no integer NOT NULL,
    studio_contract_hash varchar(64) NOT NULL,
    ontology_version_id uuid NOT NULL,
    ontology_checksum varchar(64) NOT NULL,
    requested_by uuid NOT NULL,
    graph_version integer NOT NULL,
    graph_classification integer NOT NULL,
    graph_domain_ref_id uuid,
    graph_domain_source_version varchar(255),
    vector_target_count integer NOT NULL DEFAULT 0,
    state varchar(24) NOT NULL DEFAULT 'PENDING',
    progress_percent integer NOT NULL DEFAULT 0,
    stage varchar(32) NOT NULL DEFAULT 'QUEUED',
    manifest_id varchar(255) NOT NULL,
    manifest_version integer NOT NULL,
    manifest_hash varchar(64) NOT NULL,
    pin_hash varchar(64) NOT NULL,
    request_hash varchar(64) NOT NULL,
    requester_authorization_hash varchar(64) NOT NULL,
    embedding_binding_document jsonb,
    embedding_binding_hash varchar(64),
    base_release_id uuid,
    base_release_hash varchar(64),
    attempt_count integer NOT NULL DEFAULT 0,
    maximum_attempts integer NOT NULL,
    current_attempt_id uuid,
    next_attempt_at timestamptz NOT NULL,
    lease_epoch bigint NOT NULL DEFAULT 0,
    lease_token_hash varchar(64),
    lease_owner_fingerprint varchar(255),
    lease_started_at timestamptz,
    lease_expires_at timestamptz,
    source_access_started_at timestamptz,
    source_access_deadline timestamptz,
    result_changeset_id uuid,
    result_evidence_hash varchar(64),
    source_read_receipt_hash varchar(64),
    last_failure_code varchar(100),
    cancel_requested_by uuid,
    cancel_requested_at timestamptz,
    cancel_reason varchar(500),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL,
    CONSTRAINT uq_studio_ingestion_jobs_workspace_id UNIQUE (workspace_id, id),
    CONSTRAINT uq_studio_ingestion_jobs_workspace_graph_id
        UNIQUE (workspace_id, graph_id, id),
    CONSTRAINT uq_studio_ingestion_jobs_workspace_release_id
        UNIQUE (workspace_id, studio_release_id, id),
    CONSTRAINT fk_studio_ingestion_jobs_graph
        FOREIGN KEY (workspace_id, graph_id)
        REFERENCES knowledge.graphs (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_jobs_draft
        FOREIGN KEY (workspace_id, draft_id)
        REFERENCES knowledge.studio_drafts (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_jobs_release
        FOREIGN KEY (workspace_id, graph_id, studio_release_id)
        REFERENCES knowledge.studio_releases (workspace_id, graph_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_jobs_ontology
        FOREIGN KEY (workspace_id, graph_id, ontology_version_id)
        REFERENCES knowledge.ontology_versions (workspace_id, graph_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_jobs_base_release
        FOREIGN KEY (workspace_id, graph_id, base_release_id)
        REFERENCES knowledge.releases (workspace_id, graph_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_jobs_requester
        FOREIGN KEY (workspace_id, requested_by)
        REFERENCES iam.workspace_memberships (workspace_id, subject_id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_jobs_canceller
        FOREIGN KEY (workspace_id, cancel_requested_by)
        REFERENCES iam.workspace_memberships (workspace_id, subject_id) ON DELETE RESTRICT,
    CONSTRAINT ck_studio_ingestion_jobs_state_vocabulary CHECK (
        state IN (
            'PENDING','RUNNING','RETRY_WAIT','CANCEL_REQUESTED',
            'SUCCESS','FAILED','STALE','CANCELLED'
        )
    ),
    CONSTRAINT ck_studio_ingestion_jobs_stage_vocabulary CHECK (
        stage IN ('QUEUED','SOURCE_READ','MAPPING','EMBEDDING','FINALIZING','COMPLETED')
    ),
    CONSTRAINT ck_studio_ingestion_jobs_progress CHECK (
        progress_percent BETWEEN 0 AND 100
    ),
    CONSTRAINT ck_studio_ingestion_jobs_classification CHECK (
        graph_classification BETWEEN 0 AND 3
    ),
    CONSTRAINT ck_studio_ingestion_jobs_domain_reference CHECK (
        (graph_domain_ref_id IS NULL AND graph_domain_source_version IS NULL)
        OR (graph_domain_ref_id IS NOT NULL AND graph_domain_source_version IS NOT NULL)
    ),
    CONSTRAINT ck_studio_ingestion_jobs_counters CHECK (
        graph_version >= 1
        AND studio_release_no >= 1
        AND manifest_version >= 1
        AND vector_target_count >= 0
        AND attempt_count BETWEEN 0 AND maximum_attempts
        AND maximum_attempts BETWEEN 1 AND 20
        AND lease_epoch >= attempt_count
        AND version >= 1
    ),
    CONSTRAINT ck_studio_ingestion_jobs_hashes CHECK (
        studio_contract_hash ~ '^[0-9a-f]{64}$'
        AND ontology_checksum ~ '^[0-9a-f]{64}$'
        AND manifest_hash ~ '^[0-9a-f]{64}$'
        AND pin_hash ~ '^[0-9a-f]{64}$'
        AND request_hash ~ '^[0-9a-f]{64}$'
        AND requester_authorization_hash ~ '^[0-9a-f]{64}$'
        AND (embedding_binding_hash IS NULL
             OR embedding_binding_hash ~ '^[0-9a-f]{64}$')
        AND (base_release_hash IS NULL OR base_release_hash ~ '^[0-9a-f]{64}$')
        AND (result_evidence_hash IS NULL
             OR result_evidence_hash ~ '^[0-9a-f]{64}$')
        AND (source_read_receipt_hash IS NULL
             OR source_read_receipt_hash ~ '^[0-9a-f]{64}$')
        AND (lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$')
    ),
    CONSTRAINT ck_studio_ingestion_jobs_embedding_binding CHECK (
        (embedding_binding_document IS NULL AND embedding_binding_hash IS NULL)
        OR (
            jsonb_typeof(embedding_binding_document) = 'object'
            AND embedding_binding_hash IS NOT NULL
            AND octet_length(embedding_binding_document::text) <= 8192
        )
    ),
    CONSTRAINT ck_studio_ingestion_jobs_base_release CHECK (
        (base_release_id IS NULL AND base_release_hash IS NULL)
        OR (base_release_id IS NOT NULL AND base_release_hash IS NOT NULL)
    ),
    CONSTRAINT ck_studio_ingestion_jobs_lease_shape CHECK (
        (
            state IN ('RUNNING','CANCEL_REQUESTED')
            AND current_attempt_id IS NOT NULL
            AND lease_token_hash IS NOT NULL
            AND lease_owner_fingerprint IS NOT NULL
            AND lease_started_at IS NOT NULL
            AND lease_expires_at IS NOT NULL
        )
        OR (
            state NOT IN ('RUNNING','CANCEL_REQUESTED')
            AND lease_token_hash IS NULL
            AND lease_owner_fingerprint IS NULL
            AND lease_started_at IS NULL
            AND lease_expires_at IS NULL
        )
    ),
    CONSTRAINT ck_studio_ingestion_jobs_result_shape CHECK (
        (
            state = 'SUCCESS'
            AND result_changeset_id IS NOT NULL
            AND result_evidence_hash IS NOT NULL
            AND source_read_receipt_hash IS NOT NULL
            AND completed_at IS NOT NULL
            AND last_failure_code IS NULL
        )
        OR (
            state <> 'SUCCESS'
            AND result_changeset_id IS NULL
            AND result_evidence_hash IS NULL
            AND source_read_receipt_hash IS NULL
        )
    ),
    CONSTRAINT ck_studio_ingestion_jobs_failure_shape CHECK (
        (
            state IN ('FAILED','STALE','RETRY_WAIT')
            AND last_failure_code IS NOT NULL
        )
        OR (
            state NOT IN ('FAILED','STALE','RETRY_WAIT')
            AND last_failure_code IS NULL
        )
    ),
    CONSTRAINT ck_studio_ingestion_jobs_cancel_shape CHECK (
        (
            state IN ('CANCEL_REQUESTED','CANCELLED')
            AND cancel_requested_by IS NOT NULL
            AND cancel_requested_at IS NOT NULL
            AND cancel_reason IS NOT NULL
        )
        OR (
            state NOT IN ('CANCEL_REQUESTED','CANCELLED')
            AND cancel_requested_by IS NULL
            AND cancel_requested_at IS NULL
            AND cancel_reason IS NULL
        )
    ),
    CONSTRAINT ck_studio_ingestion_jobs_terminal CHECK (
        (state IN ('SUCCESS','FAILED','STALE','CANCELLED')) = (completed_at IS NOT NULL)
        AND (state IN ('SUCCESS','FAILED','STALE','CANCELLED')) = (stage = 'COMPLETED')
    ),
    CONSTRAINT ck_studio_ingestion_jobs_progress_state CHECK (
        (state IN ('PENDING','RETRY_WAIT') AND progress_percent = 0)
        OR (
            state IN ('RUNNING','CANCEL_REQUESTED')
            AND progress_percent BETWEEN 1 AND 99
        )
        OR (state = 'SUCCESS' AND progress_percent = 100)
        OR (
            state IN ('FAILED','STALE','CANCELLED')
            AND progress_percent BETWEEN 0 AND 99
        )
    ),
    CONSTRAINT ck_studio_ingestion_jobs_source_window CHECK (
        source_access_deadline IS NULL
        OR (
            source_access_started_at IS NOT NULL
            AND source_access_deadline > source_access_started_at
        )
    )
);

CREATE TABLE knowledge.studio_ingestion_binding_pins (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    job_id uuid NOT NULL,
    ordinal integer NOT NULL,
    studio_release_id uuid NOT NULL,
    binding_version_id uuid NOT NULL,
    source_reference_id uuid NOT NULL,
    source_asset_id uuid NOT NULL,
    source_version varchar(255) NOT NULL,
    projection_source_version varchar(255) NOT NULL,
    source_classification integer NOT NULL,
    selection_hash varchar(64) NOT NULL,
    target_class_stable_id varchar(128) NOT NULL,
    target_class_canonical_name varchar(255) NOT NULL,
    mapping_hash varchar(64) NOT NULL,
    connection_profile_id varchar(255) NOT NULL,
    connection_profile_version integer NOT NULL,
    connection_profile_hash varchar(64) NOT NULL,
    rules_document jsonb NOT NULL,
    pin_hash varchar(64) NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT uq_studio_ingestion_binding_pins_workspace_id
        UNIQUE (workspace_id, id),
    CONSTRAINT uq_studio_ingestion_binding_pins_job_ordinal
        UNIQUE (workspace_id, job_id, ordinal),
    CONSTRAINT uq_studio_ingestion_binding_pins_job_binding
        UNIQUE (workspace_id, job_id, binding_version_id),
    CONSTRAINT fk_studio_ingestion_binding_pins_job
        FOREIGN KEY (workspace_id, job_id)
        REFERENCES knowledge.studio_ingestion_jobs (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_binding_pins_binding
        FOREIGN KEY (workspace_id, studio_release_id, binding_version_id)
        REFERENCES knowledge.abox_binding_versions
            (workspace_id, studio_release_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_binding_pins_source
        FOREIGN KEY (workspace_id, source_reference_id)
        REFERENCES knowledge.source_references (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_binding_pins_asset
        FOREIGN KEY (workspace_id, source_asset_id)
        REFERENCES catalog.assets_projection (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_studio_ingestion_binding_pins_shape CHECK (
        ordinal >= 0
        AND source_classification BETWEEN 0 AND 3
        AND connection_profile_version >= 1
        AND selection_hash ~ '^[0-9a-f]{64}$'
        AND mapping_hash ~ '^[0-9a-f]{64}$'
        AND connection_profile_hash ~ '^[0-9a-f]{64}$'
        AND pin_hash ~ '^[0-9a-f]{64}$'
        AND jsonb_typeof(rules_document) = 'array'
        AND jsonb_array_length(rules_document) BETWEEN 1 AND 1000
        AND octet_length(rules_document::text) <= 1048576
    )
);

CREATE TABLE knowledge.studio_ingestion_attempts (
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
    source_access_started_at timestamptz,
    source_access_deadline timestamptz,
    source_read_receipt_hash varchar(64),
    materialization_hash varchar(64),
    result_evidence_hash varchar(64),
    retryable boolean,
    failure_code varchar(100),
    finished_at timestamptz,
    CONSTRAINT uq_studio_ingestion_attempts_workspace_id UNIQUE (workspace_id, id),
    CONSTRAINT uq_studio_ingestion_attempts_job_id
        UNIQUE (workspace_id, job_id, id),
    CONSTRAINT uq_studio_ingestion_attempts_job_attempt
        UNIQUE (workspace_id, job_id, attempt_no),
    CONSTRAINT uq_studio_ingestion_attempts_job_epoch
        UNIQUE (workspace_id, job_id, lease_epoch),
    CONSTRAINT fk_studio_ingestion_attempts_job
        FOREIGN KEY (workspace_id, job_id)
        REFERENCES knowledge.studio_ingestion_jobs (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_studio_ingestion_attempts_state CHECK (
        state IN ('RUNNING','SUCCESS','FAILED','STALE','CANCELLED','SUPERSEDED')
    ),
    CONSTRAINT ck_studio_ingestion_attempts_stage CHECK (
        stage IN ('SOURCE_READ','MAPPING','EMBEDDING','FINALIZING','COMPLETED')
    ),
    CONSTRAINT ck_studio_ingestion_attempts_claim CHECK (
        attempt_no >= 1
        AND lease_epoch >= 1
        AND lease_token_hash ~ '^[0-9a-f]{64}$'
        AND char_length(worker_fingerprint) BETWEEN 1 AND 255
    ),
    CONSTRAINT ck_studio_ingestion_attempts_finished CHECK (
        (state = 'RUNNING' AND finished_at IS NULL)
        OR (state <> 'RUNNING' AND finished_at IS NOT NULL)
    ),
    CONSTRAINT ck_studio_ingestion_attempts_hashes CHECK (
        (source_read_receipt_hash IS NULL
         OR source_read_receipt_hash ~ '^[0-9a-f]{64}$')
        AND (materialization_hash IS NULL OR materialization_hash ~ '^[0-9a-f]{64}$')
        AND (result_evidence_hash IS NULL OR result_evidence_hash ~ '^[0-9a-f]{64}$')
    ),
    CONSTRAINT ck_studio_ingestion_attempts_source_window CHECK (
        source_access_deadline IS NULL
        OR (
            source_access_started_at IS NOT NULL
            AND source_access_deadline > source_access_started_at
        )
    )
);

CREATE TABLE knowledge.studio_ingestion_events (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    job_id uuid NOT NULL,
    sequence integer NOT NULL,
    attempt_id uuid,
    state varchar(24) NOT NULL,
    reason_code varchar(100) NOT NULL,
    actor_id uuid NOT NULL,
    actor_kind varchar(16) NOT NULL,
    evidence_hash varchar(64) NOT NULL,
    details_document jsonb NOT NULL,
    occurred_at timestamptz NOT NULL,
    CONSTRAINT uq_studio_ingestion_events_sequence
        UNIQUE (workspace_id, job_id, sequence),
    CONSTRAINT uq_studio_ingestion_events_evidence
        UNIQUE (workspace_id, job_id, state, reason_code, evidence_hash),
    CONSTRAINT fk_studio_ingestion_events_job
        FOREIGN KEY (workspace_id, job_id)
        REFERENCES knowledge.studio_ingestion_jobs (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_events_attempt
        FOREIGN KEY (workspace_id, job_id, attempt_id)
        REFERENCES knowledge.studio_ingestion_attempts
            (workspace_id, job_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_events_actor
        FOREIGN KEY (workspace_id, actor_id)
        REFERENCES iam.workspace_memberships (workspace_id, subject_id) ON DELETE RESTRICT,
    CONSTRAINT ck_studio_ingestion_events_shape CHECK (
        sequence >= 1
        AND state IN (
            'PENDING','RUNNING','RETRY_WAIT','CANCEL_REQUESTED',
            'SUCCESS','FAILED','STALE','CANCELLED'
        )
        AND actor_kind IN ('HUMAN','SERVICE')
        AND evidence_hash ~ '^[0-9a-f]{64}$'
        AND jsonb_typeof(details_document) = 'object'
        AND octet_length(details_document::text) <= 8192
    )
);

CREATE TABLE knowledge.studio_ingestion_vector_receipts (
    id uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    job_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    changeset_id uuid NOT NULL,
    ontology_version_id uuid NOT NULL,
    property_ontology_element_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    property_stable_id varchar(128) NOT NULL,
    content_hash varchar(64) NOT NULL,
    embedding_binding_hash varchar(64) NOT NULL,
    dimension integer NOT NULL,
    vector_document jsonb NOT NULL,
    vector_hash varchar(64) NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT uq_studio_ingestion_vector_receipts_workspace_id
        UNIQUE (workspace_id, id),
    CONSTRAINT uq_studio_ingestion_vector_receipts_entity_property
        UNIQUE (workspace_id, job_id, entity_id, property_stable_id),
    CONSTRAINT fk_studio_ingestion_vector_receipts_job
        FOREIGN KEY (workspace_id, job_id)
        REFERENCES knowledge.studio_ingestion_jobs (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_vector_receipts_attempt
        FOREIGN KEY (workspace_id, job_id, attempt_id)
        REFERENCES knowledge.studio_ingestion_attempts
            (workspace_id, job_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_vector_receipts_changeset
        FOREIGN KEY (workspace_id, changeset_id)
        REFERENCES knowledge.changesets (workspace_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_studio_ingestion_vector_receipts_property
        FOREIGN KEY (
            workspace_id, ontology_version_id, property_ontology_element_id
        )
        REFERENCES knowledge.ontology_elements (
            workspace_id, ontology_version_id, id
        ) ON DELETE RESTRICT,
    CONSTRAINT ck_studio_ingestion_vector_receipts_shape CHECK (
        content_hash ~ '^[0-9a-f]{64}$'
        AND embedding_binding_hash ~ '^[0-9a-f]{64}$'
        AND vector_hash ~ '^[0-9a-f]{64}$'
        AND dimension BETWEEN 1 AND 16384
        AND jsonb_typeof(vector_document) = 'array'
        AND jsonb_array_length(vector_document) = dimension
        AND octet_length(vector_document::text) <= 4194304
    )
);

ALTER TABLE knowledge.studio_ingestion_jobs
    ADD CONSTRAINT fk_studio_ingestion_jobs_current_attempt
    FOREIGN KEY (workspace_id, id, current_attempt_id)
    REFERENCES knowledge.studio_ingestion_attempts (workspace_id, job_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE knowledge.changesets
    ADD COLUMN studio_ingestion_job_id uuid;
ALTER TABLE knowledge.changesets
    ADD CONSTRAINT uq_changesets_studio_ingestion_job
    UNIQUE (workspace_id, studio_ingestion_job_id);
ALTER TABLE knowledge.changesets
    ADD CONSTRAINT uq_changesets_studio_ingestion_result
    UNIQUE (workspace_id, id, studio_ingestion_job_id);
ALTER TABLE knowledge.changesets
    ADD CONSTRAINT ck_changesets_one_automated_source
    CHECK (num_nonnulls(source_analysis_job_id, studio_ingestion_job_id) <= 1);
ALTER TABLE knowledge.changesets
    ADD CONSTRAINT fk_changesets_studio_ingestion_job
    FOREIGN KEY (workspace_id, graph_id, studio_ingestion_job_id)
    REFERENCES knowledge.studio_ingestion_jobs (workspace_id, graph_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE knowledge.studio_ingestion_jobs
    ADD CONSTRAINT fk_studio_ingestion_jobs_result_changeset
    FOREIGN KEY (workspace_id, result_changeset_id, id)
    REFERENCES knowledge.changesets
        (workspace_id, id, studio_ingestion_job_id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE knowledge.studio_ingestion_vector_receipts
    DROP CONSTRAINT fk_studio_ingestion_vector_receipts_changeset;
ALTER TABLE knowledge.studio_ingestion_vector_receipts
    ADD CONSTRAINT fk_studio_ingestion_vector_receipts_changeset
    FOREIGN KEY (workspace_id, changeset_id, job_id)
    REFERENCES knowledge.changesets
        (workspace_id, id, studio_ingestion_job_id)
    ON DELETE RESTRICT;

CREATE INDEX ix_studio_ingestion_jobs_claim
ON knowledge.studio_ingestion_jobs (workspace_id, next_attempt_at, created_at, id)
WHERE state IN ('PENDING','RETRY_WAIT');
CREATE INDEX ix_studio_ingestion_jobs_expired
ON knowledge.studio_ingestion_jobs (workspace_id, lease_expires_at, id)
WHERE state IN ('RUNNING','CANCEL_REQUESTED');
CREATE INDEX ix_studio_ingestion_jobs_graph_created
ON knowledge.studio_ingestion_jobs (workspace_id, graph_id, created_at DESC, id DESC);
CREATE INDEX ix_studio_ingestion_jobs_draft_created
ON knowledge.studio_ingestion_jobs (workspace_id, draft_id, created_at DESC, id DESC);
CREATE INDEX ix_studio_ingestion_binding_pins_job
ON knowledge.studio_ingestion_binding_pins (workspace_id, job_id, ordinal);
CREATE INDEX ix_studio_ingestion_attempts_job
ON knowledge.studio_ingestion_attempts (workspace_id, job_id, attempt_no);
CREATE INDEX ix_studio_ingestion_events_job
ON knowledge.studio_ingestion_events (workspace_id, job_id, sequence);
CREATE INDEX ix_studio_ingestion_vector_receipts_job
ON knowledge.studio_ingestion_vector_receipts (workspace_id, job_id, entity_id);
""".strip()

_RLS_AND_IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION knowledge.enforce_studio_ingestion_changeset_provenance_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
BEGIN
    IF TG_OP = 'INSERT'
       AND NEW.studio_ingestion_job_id IS NOT NULL
       AND session_user <> 'datariver_knowledge_ingestion' THEN
        RAISE EXCEPTION 'Studio ingestion Changeset provenance is function-owned'
            USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.studio_ingestion_job_id
            IS DISTINCT FROM OLD.studio_ingestion_job_id THEN
            RAISE EXCEPTION 'Studio ingestion Changeset provenance is immutable'
                USING ERRCODE = '55000';
        END IF;
        IF OLD.studio_ingestion_job_id IS NOT NULL
           AND ROW(
               NEW.workspace_id, NEW.graph_id, NEW.base_release_id,
               NEW.ontology_version_id, NEW.author_id,
               NEW.source_analysis_job_id, NEW.created_at
           ) IS DISTINCT FROM ROW(
               OLD.workspace_id, OLD.graph_id, OLD.base_release_id,
               OLD.ontology_version_id, OLD.author_id,
               OLD.source_analysis_job_id, OLD.created_at
           ) THEN
            RAISE EXCEPTION 'Studio ingestion Changeset pins are immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.enforce_studio_ingestion_operation_scope_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    target_workspace_id uuid := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.workspace_id ELSE NEW.workspace_id END;
    target_changeset_id uuid := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.changeset_id ELSE NEW.changeset_id END;
    studio_job_id uuid;
    previous_studio_job_id uuid;
BEGIN
    SELECT studio_ingestion_job_id
    INTO studio_job_id
    FROM knowledge.changesets
    WHERE workspace_id = target_workspace_id
      AND id = target_changeset_id;
    IF TG_OP = 'UPDATE' THEN
        SELECT studio_ingestion_job_id
        INTO previous_studio_job_id
        FROM knowledge.changesets
        WHERE workspace_id = OLD.workspace_id
          AND id = OLD.changeset_id;
    END IF;
    IF COALESCE(studio_job_id, previous_studio_job_id) IS NOT NULL
       AND session_user <> 'datariver_knowledge_ingestion' THEN
        RAISE EXCEPTION 'Studio ingestion operations are function-owned'
            USING ERRCODE = '42501';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.reject_studio_ingestion_evidence_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Studio ingestion evidence is append-only'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER enforce_studio_ingestion_changeset_provenance
BEFORE INSERT OR UPDATE ON knowledge.changesets
FOR EACH ROW EXECUTE FUNCTION
    knowledge.enforce_studio_ingestion_changeset_provenance_v1();
CREATE TRIGGER enforce_studio_ingestion_operation_scope
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.change_operations
FOR EACH ROW EXECUTE FUNCTION
    knowledge.enforce_studio_ingestion_operation_scope_v1();
CREATE TRIGGER reject_studio_ingestion_binding_pin_mutation
BEFORE UPDATE OR DELETE ON knowledge.studio_ingestion_binding_pins
FOR EACH ROW EXECUTE FUNCTION knowledge.reject_studio_ingestion_evidence_mutation_v1();
CREATE TRIGGER reject_studio_ingestion_attempt_mutation
BEFORE DELETE ON knowledge.studio_ingestion_attempts
FOR EACH ROW EXECUTE FUNCTION knowledge.reject_studio_ingestion_evidence_mutation_v1();
CREATE TRIGGER reject_studio_ingestion_event_mutation
BEFORE UPDATE OR DELETE ON knowledge.studio_ingestion_events
FOR EACH ROW EXECUTE FUNCTION knowledge.reject_studio_ingestion_evidence_mutation_v1();
CREATE TRIGGER reject_studio_ingestion_vector_receipt_mutation
BEFORE UPDATE OR DELETE ON knowledge.studio_ingestion_vector_receipts
FOR EACH ROW EXECUTE FUNCTION knowledge.reject_studio_ingestion_evidence_mutation_v1();

ALTER TABLE knowledge.studio_ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_binding_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_binding_pins FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_events FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_vector_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.studio_ingestion_vector_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY studio_ingestion_jobs_workspace
ON knowledge.studio_ingestion_jobs
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND (
        session_user = 'datariver_knowledge_ingestion'
        OR requested_by =
            NULLIF(current_setting('app.subject_id', true), '')::uuid
    )
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND (
        session_user = 'datariver_knowledge_ingestion'
        OR requested_by =
            NULLIF(current_setting('app.subject_id', true), '')::uuid
    )
);
CREATE POLICY studio_ingestion_binding_pins_workspace
ON knowledge.studio_ingestion_binding_pins
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND (
        session_user = 'datariver_knowledge_ingestion'
        OR EXISTS (
            SELECT 1
            FROM knowledge.studio_ingestion_jobs AS job
            WHERE job.workspace_id = studio_ingestion_binding_pins.workspace_id
              AND job.id = studio_ingestion_binding_pins.job_id
              AND job.requested_by =
                  NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
    )
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND (
        session_user = 'datariver_knowledge_ingestion'
        OR EXISTS (
            SELECT 1
            FROM knowledge.studio_ingestion_jobs AS job
            WHERE job.workspace_id = studio_ingestion_binding_pins.workspace_id
              AND job.id = studio_ingestion_binding_pins.job_id
              AND job.requested_by =
                  NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
    )
);
CREATE POLICY studio_ingestion_attempts_workspace
ON knowledge.studio_ingestion_attempts
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND session_user = 'datariver_knowledge_ingestion'
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND session_user = 'datariver_knowledge_ingestion'
);
CREATE POLICY studio_ingestion_events_workspace
ON knowledge.studio_ingestion_events
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND (
        session_user = 'datariver_knowledge_ingestion'
        OR EXISTS (
            SELECT 1
            FROM knowledge.studio_ingestion_jobs AS job
            WHERE job.workspace_id = studio_ingestion_events.workspace_id
              AND job.id = studio_ingestion_events.job_id
              AND job.requested_by =
                  NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
    )
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND (
        session_user = 'datariver_knowledge_ingestion'
        OR EXISTS (
            SELECT 1
            FROM knowledge.studio_ingestion_jobs AS job
            WHERE job.workspace_id = studio_ingestion_events.workspace_id
              AND job.id = studio_ingestion_events.job_id
              AND job.requested_by =
                  NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
    )
);
CREATE POLICY studio_ingestion_vector_receipts_workspace
ON knowledge.studio_ingestion_vector_receipts
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND session_user = 'datariver_knowledge_ingestion'
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND session_user = 'datariver_knowledge_ingestion'
);
""".strip()

_GRANTS_SQL = """
DO $datariver$
BEGIN
    REVOKE ALL PRIVILEGES ON knowledge.studio_ingestion_jobs,
        knowledge.studio_ingestion_binding_pins,
        knowledge.studio_ingestion_attempts,
        knowledge.studio_ingestion_events,
        knowledge.studio_ingestion_vector_receipts
        FROM datariver_app, datariver_knowledge_ingestion;
    REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA knowledge
        FROM datariver_knowledge_ingestion;
    REVOKE ALL PRIVILEGES ON SCHEMA knowledge
        FROM datariver_knowledge_ingestion;

    GRANT SELECT ON knowledge.studio_ingestion_jobs,
        knowledge.studio_ingestion_binding_pins,
        knowledge.studio_ingestion_events
        TO datariver_app;

    GRANT USAGE ON SCHEMA knowledge TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.request_studio_ingestion_v1(
        uuid, uuid, integer, text, text, integer, text, jsonb, jsonb, integer
    ) TO datariver_app;
    GRANT EXECUTE ON FUNCTION knowledge.cancel_studio_ingestion_v1(
        uuid, uuid, integer, text
    ) TO datariver_app;
    GRANT EXECUTE ON FUNCTION knowledge.retry_studio_ingestion_v1(
        uuid, uuid, integer
    ) TO datariver_app;

    GRANT EXECUTE ON FUNCTION knowledge.claim_studio_ingestion_v1(
        uuid, text, text, integer
    ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.freeze_studio_ingestion_source_access_v1(
        uuid, uuid, uuid, bigint, text, text, integer, integer
    ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION
        knowledge.assert_studio_ingestion_source_statement_fence_v1(
            uuid, uuid, uuid, bigint, text, text
        ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.renew_studio_ingestion_v1(
        uuid, uuid, uuid, bigint, text, text, integer, text, integer
    ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.ensure_studio_ingestion_current_v1(
        uuid, uuid, uuid, bigint, text, text, text, integer, text, jsonb
    ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.begin_studio_ingestion_completion_v1(
        uuid, uuid, uuid, bigint, text, text
    ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.append_studio_ingestion_result_batch_v1(
        uuid, uuid, uuid, bigint, text, text, uuid, jsonb, jsonb
    ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.complete_studio_ingestion_v1(
        uuid, uuid, uuid, bigint, text, text, uuid, text, text,
        integer, integer, text
    ) TO datariver_knowledge_ingestion;
    GRANT EXECUTE ON FUNCTION knowledge.fail_studio_ingestion_v1(
        uuid, uuid, uuid, bigint, text, text, text, text, boolean, boolean
    ) TO datariver_knowledge_ingestion;
END
$datariver$;
""".strip()


def split_postgresql_statements(sql: str) -> tuple[str, ...]:
    """Split a PostgreSQL script without breaking quoted or dollar-quoted bodies."""
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
    if "catalog.sync" in op.get_bind().execute(sa.text("SELECT allowed_actions FROM iam.access_roles WHERE role_key = 'canonical-admin'")).scalar(): return
    op.execute(_ROLE_ASSERTION_SQL)
    op.execute(_LEGACY_GUARD_SQL)
    _execute_sql_script(_TABLES_SQL)
    _execute_sql_script(_RLS_AND_IMMUTABILITY_SQL)
    _execute_sql_script(STUDIO_INGESTION_ALL_FUNCTION_SQL)
    for signature in (
        *STUDIO_INGESTION_FUNCTION_SIGNATURES,
        *STUDIO_INGESTION_INTERNAL_FUNCTION_SIGNATURES,
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "knowledge.reject_studio_ingestion_evidence_mutation_v1() FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "knowledge.enforce_studio_ingestion_changeset_provenance_v1() FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION knowledge.enforce_studio_ingestion_operation_scope_v1() FROM PUBLIC"
    )
    op.execute(_GRANTS_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0081 is append-only and requires an explicit operator-authored reconciliation downgrade."
    )
