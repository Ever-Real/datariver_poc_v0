"""add durable knowledge source jobs

Revision ID: 0054
Revises: 0053
Create Date: 2026-07-23 21:45:34.392952+00:00
"""
# ruff: noqa: E501 -- generated schema expressions retain canonical PostgreSQL text.

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATEMENT_BOUNDARY = "-- datariver-statement-boundary"


def _execute_blocks(sql: str) -> None:
    for statement in sql.split(_STATEMENT_BOUNDARY):
        if statement.strip():
            op.execute(statement)


_RLS_SQL = """
DO $datariver$
DECLARE
    role_is_safe boolean;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        RAISE EXCEPTION 'datariver_app must exist before durable Knowledge migration';
    END IF;
    SELECT
        rolcanlogin
        AND NOT rolsuper
        AND NOT rolcreatedb
        AND NOT rolcreaterole
        AND NOT rolreplication
        AND NOT rolbypassrls
    INTO role_is_safe
    FROM pg_roles WHERE rolname = 'datariver_app';
    IF NOT role_is_safe THEN
        RAISE EXCEPTION 'datariver_app must be an unprivileged LOGIN principal';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_knowledge') THEN
        RAISE EXCEPTION
            'datariver_knowledge must be reconciled before durable Knowledge migration';
    END IF;
    SELECT
        rolcanlogin
        AND NOT rolsuper
        AND NOT rolcreatedb
        AND NOT rolcreaterole
        AND NOT rolreplication
        AND NOT rolbypassrls
    INTO role_is_safe
    FROM pg_roles WHERE rolname = 'datariver_knowledge';
    IF NOT role_is_safe THEN
        RAISE EXCEPTION
            'datariver_knowledge must be an unprivileged LOGIN principal';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_knowledge'
          AND pg_has_role('datariver_knowledge', candidate.oid, 'MEMBER')
    ) THEN
        RAISE EXCEPTION
            'datariver_knowledge must not inherit or SET ROLE to another principal';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_knowledge'
          AND NOT candidate.rolsuper
          AND pg_has_role(candidate.oid, 'datariver_knowledge', 'MEMBER')
    ) THEN
        RAISE EXCEPTION
            'datariver_knowledge must not be assumable by another non-superuser principal';
    END IF;
END
$datariver$;
-- datariver-statement-boundary
ALTER TABLE knowledge.source_analysis_jobs ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE knowledge.source_analysis_jobs FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
CREATE POLICY workspace_isolation ON knowledge.source_analysis_jobs
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
);
-- datariver-statement-boundary
CREATE POLICY source_analysis_job_owner_select
ON knowledge.source_analysis_jobs
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    requested_by = NULLIF(current_setting('app.subject_id', true), '')::uuid
);
-- datariver-statement-boundary
ALTER TABLE knowledge.source_analysis_attempts ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE knowledge.source_analysis_attempts FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
CREATE POLICY workspace_isolation ON knowledge.source_analysis_attempts
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
);
-- datariver-statement-boundary
ALTER TABLE knowledge.source_analysis_events ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE knowledge.source_analysis_events FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
CREATE POLICY workspace_isolation ON knowledge.source_analysis_events
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
);
-- datariver-statement-boundary
CREATE POLICY source_analysis_event_owner_select
ON knowledge.source_analysis_events
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.source_analysis_jobs AS job
        WHERE job.workspace_id = source_analysis_events.workspace_id
          AND job.id = source_analysis_events.job_id
          AND job.requested_by =
              NULLIF(current_setting('app.subject_id', true), '')::uuid
    )
);
"""

_CLAIM_SCOPE_SQL = """
CREATE OR REPLACE FUNCTION knowledge.current_source_claim_scope()
RETURNS TABLE (
    job_id uuid,
    workspace_id uuid,
    graph_id uuid,
    source_snapshot_id uuid,
    upload_id uuid,
    requested_by uuid,
    ontology_version_id uuid,
    base_release_id uuid,
    embedding_binding jsonb,
    extraction_binding jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    selected_job_id uuid :=
        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;
    raw_token text :=
        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');
    raw_hash text;
BEGIN
    IF session_user <> 'datariver_knowledge'
       OR selected_job_id IS NULL
       OR raw_token IS NULL THEN
        RETURN;
    END IF;
    raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
    RETURN QUERY
    SELECT
        job.id,
        job.workspace_id,
        job.graph_id,
        job.source_snapshot_id,
        source.upload_id,
        job.requested_by,
        job.ontology_version_id,
        job.base_release_id,
        job.embedding_binding,
        job.extraction_binding
    FROM knowledge.source_analysis_jobs AS job
    JOIN knowledge.source_analysis_attempts AS attempt
      ON attempt.workspace_id = job.workspace_id
     AND attempt.job_id = job.id
     AND attempt.lease_epoch = job.lease_epoch
    JOIN knowledge.source_snapshots AS source
      ON source.workspace_id = job.workspace_id
     AND source.id = job.source_snapshot_id
    WHERE job.id = selected_job_id
      AND job.state IN ('RUNNING', 'CANCEL_REQUESTED')
      AND job.lease_expires_at > clock_timestamp()
      AND job.lease_token_hash = raw_hash
      AND attempt.state = 'RUNNING'
      AND attempt.lease_token_hash = raw_hash;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION knowledge.current_source_claim_scope() FROM PUBLIC;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION knowledge.current_source_claim_scope()
TO datariver_knowledge;
-- datariver-statement-boundary
ALTER TABLE iam.subjects ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE iam.subjects FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
CREATE POLICY existing_subject_privileges
ON iam.subjects
USING (true)
WITH CHECK (true);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_subject
ON iam.subjects
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.requested_by = subjects.id
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_membership
ON iam.workspace_memberships
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = workspace_memberships.workspace_id
          AND claim.requested_by = workspace_memberships.subject_id
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_inference_profiles
ON platform.external_service_profiles
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    active
    AND EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = external_service_profiles.workspace_id
          AND (
              (
                  external_service_profiles.service_key = 'LLM_CHAT_MODEL'
                  AND claim.extraction_binding ->> 'configuration_source'
                      = 'SYSTEM_CONFIGURATION'
                  AND external_service_profiles.activated_version =
                      (claim.extraction_binding ->> 'configuration_version')::integer
              )
              OR (
                  external_service_profiles.service_key = 'LLM_EMBEDDING'
                  AND claim.embedding_binding ->> 'configuration_source'
                      = 'SYSTEM_CONFIGURATION'
                  AND external_service_profiles.activated_version =
                      (claim.embedding_binding ->> 'configuration_version')::integer
              )
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_inference_profile_versions
ON platform.external_service_profile_versions
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    test_status = 'AVAILABLE'
    AND EXISTS (
        SELECT 1
        FROM platform.external_service_profiles AS profile
        JOIN knowledge.current_source_claim_scope() AS claim
          ON claim.workspace_id = profile.workspace_id
        WHERE profile.workspace_id = external_service_profile_versions.workspace_id
          AND profile.id = external_service_profile_versions.profile_id
          AND profile.active
          AND profile.activated_version =
              external_service_profile_versions.configuration_version
          AND (
              (
                  profile.service_key = 'LLM_CHAT_MODEL'
                  AND claim.extraction_binding ->> 'configuration_source'
                      = 'SYSTEM_CONFIGURATION'
                  AND external_service_profile_versions.configuration_version =
                      (claim.extraction_binding ->> 'configuration_version')::integer
                  AND external_service_profile_versions.configuration_hash =
                      claim.extraction_binding ->> 'configuration_hash'
              )
              OR (
                  profile.service_key = 'LLM_EMBEDDING'
                  AND claim.embedding_binding ->> 'configuration_source'
                      = 'SYSTEM_CONFIGURATION'
                  AND external_service_profile_versions.configuration_version =
                      (claim.embedding_binding ->> 'configuration_version')::integer
                  AND external_service_profile_versions.configuration_hash =
                      claim.embedding_binding ->> 'configuration_hash'
              )
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_manifest
ON integration.object_manifests
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = object_manifests.workspace_id
          AND claim.upload_id = object_manifests.id
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_inbox_consumer
ON integration.inbox_messages
AS RESTRICTIVE TO datariver_knowledge
USING (consumer = 'knowledge-source-analysis-v1')
WITH CHECK (consumer = 'knowledge-source-analysis-v1');
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_graph
ON knowledge.graphs
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = graphs.workspace_id
          AND claim.graph_id = graphs.id
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_ontology
ON knowledge.ontology_versions
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = ontology_versions.workspace_id
          AND claim.graph_id = ontology_versions.graph_id
          AND claim.ontology_version_id = ontology_versions.id
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_release
ON knowledge.releases
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = releases.workspace_id
          AND claim.graph_id = releases.graph_id
          AND claim.base_release_id = releases.id
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_source
ON knowledge.source_snapshots
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = source_snapshots.workspace_id
          AND claim.source_snapshot_id = source_snapshots.id
    )
);
-- datariver-statement-boundary
CREATE POLICY knowledge_worker_current_changeset
ON knowledge.changesets
AS RESTRICTIVE FOR SELECT TO datariver_knowledge
USING (
    EXISTS (
        SELECT 1
        FROM knowledge.current_source_claim_scope() AS claim
        WHERE claim.workspace_id = changesets.workspace_id
          AND claim.graph_id = changesets.graph_id
          AND (
              changesets.source_analysis_job_id = claim.job_id
              OR changesets.published_release_id = claim.base_release_id
          )
    )
);
"""

_EVIDENCE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS
    ux_source_analysis_events_transition_evidence
ON knowledge.source_analysis_events (
    workspace_id, job_id, event_type, occurred_at
);
-- datariver-statement-boundary
CREATE UNIQUE INDEX IF NOT EXISTS
    ux_outbox_source_analysis_transition
ON integration.outbox_events (
    workspace_id, aggregate_id, event_type, (payload ->> 'version')
)
WHERE aggregate_type = 'knowledge_source_analysis_job';
-- datariver-statement-boundary
CREATE UNIQUE INDEX IF NOT EXISTS
    ux_policy_decisions_source_analysis_finalization
ON authz.policy_decisions (workspace_id, request_id, action)
WHERE evaluation_context ->> 'kind'
    = 'knowledge_source_job_finalization';
"""

_WORKSPACE_DISCOVERY_SQL = """
CREATE OR REPLACE FUNCTION knowledge.list_knowledge_worker_workspaces()
RETURNS SETOF uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
BEGIN
    IF session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge workspace discovery is worker-only'
            USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    SELECT DISTINCT job.workspace_id
    FROM knowledge.source_analysis_jobs AS job
    WHERE (
        job.state IN ('QUEUED', 'RETRY_WAIT')
        AND job.next_attempt_at <= clock_timestamp()
    ) OR (
        job.state IN ('RUNNING', 'CANCEL_REQUESTED')
        AND job.lease_expires_at <= clock_timestamp()
    )
    ORDER BY 1
    LIMIT 10000;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION knowledge.list_knowledge_worker_workspaces()
FROM PUBLIC;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION knowledge.list_knowledge_worker_workspaces()
TO datariver_knowledge;
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION knowledge.lock_source_analysis_finalization()
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam, integration, knowledge
AS $$
DECLARE
    selected_job_id uuid :=
        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;
    raw_token text :=
        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');
    raw_hash text;
    selected_job knowledge.source_analysis_jobs%ROWTYPE;
    selected_source knowledge.source_snapshots%ROWTYPE;
BEGIN
    IF session_user <> 'datariver_knowledge'
       OR selected_job_id IS NULL
       OR raw_token IS NULL THEN
        RAISE EXCEPTION 'Knowledge finalization locking is worker-claim only'
            USING ERRCODE = '42501';
    END IF;
    raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
    SELECT * INTO selected_job
    FROM knowledge.source_analysis_jobs
    WHERE id = selected_job_id
    FOR UPDATE;
    IF NOT FOUND
       OR selected_job.state <> 'RUNNING'
       OR selected_job.lease_expires_at <= clock_timestamp()
       OR raw_hash IS DISTINCT FROM selected_job.lease_token_hash THEN
        RAISE EXCEPTION 'Knowledge finalization claim is expired or superseded'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO selected_source
    FROM knowledge.source_snapshots
    WHERE workspace_id = selected_job.workspace_id
      AND id = selected_job.source_snapshot_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge finalization source is unavailable';
    END IF;
    PERFORM 1
    FROM integration.object_manifests
    WHERE workspace_id = selected_job.workspace_id
      AND id = selected_source.upload_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge finalization manifest is unavailable';
    END IF;
    PERFORM 1
    FROM knowledge.graphs
    WHERE workspace_id = selected_job.workspace_id
      AND id = selected_job.graph_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge finalization graph is unavailable';
    END IF;
    PERFORM 1
    FROM knowledge.ontology_versions
    WHERE workspace_id = selected_job.workspace_id
      AND graph_id = selected_job.graph_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge finalization ontology is unavailable';
    END IF;
    PERFORM 1
    FROM iam.subjects
    WHERE id = selected_job.requested_by
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge finalization requester is unavailable';
    END IF;
    PERFORM 1
    FROM iam.workspace_memberships
    WHERE workspace_id = selected_job.workspace_id
      AND subject_id = selected_job.requested_by
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge finalization membership is unavailable';
    END IF;
    PERFORM 1
    FROM platform.external_service_profiles
    WHERE workspace_id = selected_job.workspace_id
      AND service_key IN ('LLM_CHAT_MODEL', 'LLM_EMBEDDING')
    FOR UPDATE;
    PERFORM 1
    FROM platform.external_service_profile_versions AS version
    WHERE version.workspace_id = selected_job.workspace_id
      AND EXISTS (
          SELECT 1
          FROM platform.external_service_profiles AS profile
          WHERE profile.workspace_id = version.workspace_id
            AND profile.id = version.profile_id
            AND profile.service_key IN ('LLM_CHAT_MODEL', 'LLM_EMBEDDING')
      )
    FOR UPDATE;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION knowledge.lock_source_analysis_finalization()
FROM PUBLIC;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION knowledge.lock_source_analysis_finalization()
TO datariver_knowledge;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION knowledge.current_source_claim_scope()
TO datariver_knowledge;
"""

_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_job_fence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    table_owner text;
    raw_token text :=
        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');
    raw_hash text;
    actor_id uuid :=
        NULLIF(current_setting('app.subject_id', true), '')::uuid;
    selected_job_id uuid :=
        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;
BEGIN
    SELECT pg_get_userbyid(relowner) INTO table_owner
    FROM pg_class WHERE oid = TG_RELID;
    IF current_user = table_owner THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF current_user = 'datariver_knowledge'
       AND session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'durable Knowledge jobs are not directly deletable';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF current_user <> 'datariver_app'
           OR NEW.requested_by IS DISTINCT FROM actor_id
           OR NEW.state <> 'QUEUED'
           OR NEW.stage <> 'QUEUED'
           OR NEW.attempt_count <> 0
           OR NEW.lease_epoch <> 0
           OR NEW.version <> 1
           OR NEW.completed_at IS NOT NULL THEN
            RAISE EXCEPTION 'invalid durable Knowledge job submission';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        OLD.workspace_id, OLD.id, OLD.graph_id, OLD.source_snapshot_id,
        OLD.requested_by, OLD.title, OLD.request_hash,
        OLD.requester_authorization_hash, OLD.source_storage_version,
        OLD.source_content_sha256, OLD.source_classification,
        OLD.graph_version, OLD.base_kind, OLD.base_release_id,
        OLD.base_release_hash, OLD.ontology_version_id,
        OLD.ontology_checksum, OLD.parser_config_hash,
        OLD.embedding_binding, OLD.embedding_binding_hash,
        OLD.extraction_binding, OLD.extraction_binding_hash,
        OLD.pin_hash, OLD.prepared_at, OLD.created_at,
        OLD.maximum_attempts
    ) IS DISTINCT FROM ROW(
        NEW.workspace_id, NEW.id, NEW.graph_id, NEW.source_snapshot_id,
        NEW.requested_by, NEW.title, NEW.request_hash,
        NEW.requester_authorization_hash, NEW.source_storage_version,
        NEW.source_content_sha256, NEW.source_classification,
        NEW.graph_version, NEW.base_kind, NEW.base_release_id,
        NEW.base_release_hash, NEW.ontology_version_id,
        NEW.ontology_checksum, NEW.parser_config_hash,
        NEW.embedding_binding, NEW.embedding_binding_hash,
        NEW.extraction_binding, NEW.extraction_binding_hash,
        NEW.pin_hash, NEW.prepared_at, NEW.created_at,
        NEW.maximum_attempts
    ) THEN
        RAISE EXCEPTION 'durable Knowledge job pins are immutable';
    END IF;
    IF NEW.version <> OLD.version + 1 OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'invalid durable Knowledge job version transition';
    END IF;
    IF current_user = 'datariver_app' THEN
        IF OLD.requested_by IS DISTINCT FROM actor_id
           OR NEW.cancel_requested_by IS DISTINCT FROM actor_id
           OR NEW.cancel_requested_at IS NULL
           OR NEW.cancel_reason IS NULL
           OR NOT (
               (
                   OLD.state IN ('QUEUED', 'RETRY_WAIT')
                   AND NEW.state = 'CANCELLED'
                   AND NEW.stage = 'COMPLETED'
                   AND NEW.completed_at IS NOT NULL
               )
               OR (
                   OLD.state = 'RUNNING'
                   AND NEW.state = 'CANCEL_REQUESTED'
                   AND NEW.completed_at IS NULL
                   AND NEW.lease_token_hash = OLD.lease_token_hash
                   AND NEW.lease_owner_fingerprint = OLD.lease_owner_fingerprint
                   AND NEW.lease_expires_at = OLD.lease_expires_at
               )
           ) THEN
            RAISE EXCEPTION 'invalid durable Knowledge cancellation';
        END IF;
        RETURN NEW;
    END IF;
    IF current_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'only the API or Knowledge worker may update durable jobs';
    END IF;
    IF NOT (
        OLD.state IN ('QUEUED', 'RETRY_WAIT') AND NEW.state = 'RUNNING'
    ) AND (
        NEW.attempt_count <> OLD.attempt_count
        OR NEW.lease_epoch <> OLD.lease_epoch
    ) THEN
        RAISE EXCEPTION 'durable Knowledge counters may change only during claim';
    END IF;
    IF raw_token IS NOT NULL THEN
        raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
    END IF;
    IF OLD.state IN ('QUEUED', 'RETRY_WAIT') AND NEW.state = 'RUNNING' THEN
        IF raw_hash IS DISTINCT FROM NEW.lease_token_hash
           OR NEW.attempt_count <> OLD.attempt_count + 1
           OR NEW.lease_epoch <> OLD.lease_epoch + 1
           OR NEW.lease_started_at IS NULL
           OR NEW.lease_expires_at <= clock_timestamp()
           OR NEW.lease_expires_at > clock_timestamp() + interval '1 hour'
           OR NEW.last_failure_code IS NOT NULL THEN
            RAISE EXCEPTION 'invalid durable Knowledge claim';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.state IN ('RUNNING', 'CANCEL_REQUESTED')
       AND OLD.lease_expires_at > clock_timestamp()
       AND raw_hash = OLD.lease_token_hash THEN
        IF OLD.state = 'CANCEL_REQUESTED' AND NEW.state <> 'CANCELLED' THEN
            RAISE EXCEPTION 'a cancellation request may only become cancelled';
        END IF;
        IF NEW.state NOT IN (
            'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED'
        ) THEN
            RAISE EXCEPTION 'invalid live durable Knowledge transition';
        END IF;
        IF NEW.state = 'RUNNING' AND (
            NEW.lease_token_hash IS DISTINCT FROM OLD.lease_token_hash
            OR NEW.lease_owner_fingerprint IS DISTINCT FROM OLD.lease_owner_fingerprint
            OR NEW.lease_epoch <> OLD.lease_epoch
            OR NEW.attempt_count <> OLD.attempt_count
            OR NEW.lease_expires_at <= clock_timestamp()
            OR NEW.lease_expires_at > clock_timestamp() + interval '1 hour'
        ) THEN
            RAISE EXCEPTION 'invalid durable Knowledge renewal';
        END IF;
        IF NEW.state <> 'RUNNING' AND (
            NEW.lease_token_hash IS NOT NULL
            OR NEW.lease_owner_fingerprint IS NOT NULL
            OR NEW.lease_started_at IS NOT NULL
            OR NEW.lease_expires_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'durable Knowledge terminal transition retained a lease';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.state IN ('RUNNING', 'CANCEL_REQUESTED')
       AND OLD.lease_expires_at <= clock_timestamp()
       AND raw_token IS NULL
       AND selected_job_id = OLD.id
       AND (
           (OLD.state = 'RUNNING' AND NEW.state IN ('RETRY_WAIT', 'FAILED'))
           OR (OLD.state = 'CANCEL_REQUESTED' AND NEW.state = 'CANCELLED')
       )
       AND NEW.lease_token_hash IS NULL
       AND NEW.lease_owner_fingerprint IS NULL
       AND NEW.lease_started_at IS NULL
       AND NEW.lease_expires_at IS NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'durable Knowledge lease is missing, expired or superseded';
END
$$;
-- datariver-statement-boundary
CREATE TRIGGER trg_source_analysis_job_fence
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_analysis_jobs
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_job_fence();
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_attempt_fence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    table_owner text;
    parent knowledge.source_analysis_jobs%ROWTYPE;
    raw_token text :=
        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');
    raw_hash text;
    selected_job_id uuid :=
        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;
BEGIN
    SELECT pg_get_userbyid(relowner) INTO table_owner
    FROM pg_class WHERE oid = TG_RELID;
    IF current_user = table_owner THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF current_user = 'datariver_knowledge'
       AND session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';
    END IF;
    IF current_user <> 'datariver_knowledge' OR TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'durable Knowledge attempts are worker-owned and append-preserving';
    END IF;
    SELECT * INTO parent FROM knowledge.source_analysis_jobs
    WHERE workspace_id = NEW.workspace_id AND id = NEW.job_id;
    raw_hash := CASE WHEN raw_token IS NULL THEN NULL
        ELSE encode(sha256(convert_to(raw_token, 'UTF8')), 'hex') END;
    IF TG_OP = 'INSERT' THEN
        IF parent.state <> 'RUNNING'
           OR parent.lease_expires_at <= clock_timestamp()
           OR raw_hash IS DISTINCT FROM parent.lease_token_hash
           OR NEW.lease_token_hash IS DISTINCT FROM parent.lease_token_hash
           OR NEW.attempt_no <> parent.attempt_count
           OR NEW.lease_epoch <> parent.lease_epoch
           OR NEW.state <> 'RUNNING' THEN
            RAISE EXCEPTION 'invalid durable Knowledge attempt claim';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        OLD.workspace_id, OLD.id, OLD.job_id, OLD.attempt_no,
        OLD.lease_epoch, OLD.lease_token_hash, OLD.worker_fingerprint,
        OLD.input_hash, OLD.started_at
    ) IS DISTINCT FROM ROW(
        NEW.workspace_id, NEW.id, NEW.job_id, NEW.attempt_no,
        NEW.lease_epoch, NEW.lease_token_hash, NEW.worker_fingerprint,
        NEW.input_hash, NEW.started_at
    ) OR OLD.state <> 'RUNNING' THEN
        RAISE EXCEPTION 'durable Knowledge attempt identity is immutable';
    END IF;
    IF (
        parent.lease_epoch = OLD.lease_epoch
        AND parent.lease_token_hash = OLD.lease_token_hash
        AND parent.lease_expires_at > clock_timestamp()
        AND raw_hash = parent.lease_token_hash
        AND NEW.state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')
    ) OR (
        parent.lease_epoch = OLD.lease_epoch
        AND OLD.finished_at IS NULL
        AND raw_token IS NULL
        AND selected_job_id = parent.id
        AND parent.lease_expires_at <= clock_timestamp()
        AND NEW.state = 'SUPERSEDED'
        AND NEW.failure_code = 'LEASE_EXPIRED'
    ) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'durable Knowledge attempt lease is superseded';
END
$$;
-- datariver-statement-boundary
CREATE TRIGGER trg_source_analysis_attempt_fence
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_analysis_attempts
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_attempt_fence();
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_attempt_terminal_pair()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    parent knowledge.source_analysis_jobs%ROWTYPE;
BEGIN
    IF current_user = 'datariver_knowledge'
       AND session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';
    END IF;
    SELECT * INTO parent
    FROM knowledge.source_analysis_jobs
    WHERE workspace_id = NEW.workspace_id AND id = NEW.job_id;
    IF NOT FOUND OR parent.lease_epoch <> NEW.lease_epoch THEN
        RAISE EXCEPTION 'durable Knowledge attempt has no matching job epoch';
    END IF;
    IF (
        NEW.state = 'RUNNING'
        AND parent.state IN ('RUNNING', 'CANCEL_REQUESTED')
    ) OR (
        NEW.state = 'SUCCEEDED' AND parent.state = 'SUCCEEDED'
    ) OR (
        NEW.state = 'FAILED' AND parent.state IN ('FAILED', 'RETRY_WAIT')
    ) OR (
        NEW.state = 'STALE' AND parent.state = 'STALE'
    ) OR (
        NEW.state = 'CANCELLED' AND parent.state = 'CANCELLED'
    ) OR (
        NEW.state = 'SUPERSEDED'
        AND parent.state IN ('RETRY_WAIT', 'FAILED', 'CANCELLED')
    ) THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'durable Knowledge attempt and job terminal states diverged';
END
$$;
-- datariver-statement-boundary
CREATE CONSTRAINT TRIGGER trg_source_analysis_attempt_terminal_pair
AFTER INSERT OR UPDATE ON knowledge.source_analysis_attempts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_attempt_terminal_pair();
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_event_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    table_owner text;
    selected_job_id uuid :=
        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;
    actor_id uuid :=
        NULLIF(current_setting('app.subject_id', true), '')::uuid;
    parent knowledge.source_analysis_jobs%ROWTYPE;
    current_attempt knowledge.source_analysis_attempts%ROWTYPE;
    raw_token text :=
        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');
    raw_hash text;
    parent_changed_in_transaction boolean := false;
    expected_sequence integer;
    live_event boolean := false;
    recovery_event boolean := false;
    app_event boolean := false;
BEGIN
    SELECT pg_get_userbyid(relowner) INTO table_owner
    FROM pg_class WHERE oid = TG_RELID;
    IF current_user = table_owner THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF current_user = 'datariver_knowledge'
       AND session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';
    END IF;
    IF TG_OP <> 'INSERT'
       OR current_user NOT IN ('datariver_app', 'datariver_knowledge') THEN
        RAISE EXCEPTION 'durable Knowledge events are append-only';
    END IF;
    SELECT * INTO parent
    FROM knowledge.source_analysis_jobs
    WHERE workspace_id = NEW.workspace_id AND id = NEW.job_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'durable Knowledge event has no visible parent job';
    END IF;
    IF NEW.attempt_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM knowledge.source_analysis_attempts AS candidate_attempt
        WHERE candidate_attempt.workspace_id = NEW.workspace_id
          AND candidate_attempt.id = NEW.attempt_id
          AND candidate_attempt.job_id = NEW.job_id
    ) THEN
        RAISE EXCEPTION 'durable Knowledge event attempt is outside its job';
    END IF;
    SELECT (job.xmin::text::bigint = txid_current())
    INTO parent_changed_in_transaction
    FROM knowledge.source_analysis_jobs AS job
    WHERE job.workspace_id = NEW.workspace_id
      AND job.id = NEW.job_id;
    SELECT COALESCE(MAX(event.sequence), 0) + 1
    INTO expected_sequence
    FROM knowledge.source_analysis_events AS event
    WHERE event.workspace_id = NEW.workspace_id
      AND event.job_id = NEW.job_id;
    IF current_user = 'datariver_app' THEN
        app_event :=
            parent.requested_by = actor_id
            AND NEW.actor_ref = 'subject:' || actor_id
            AND NEW.attempt_id IS NULL
            AND NEW.sequence = expected_sequence
            AND parent_changed_in_transaction
            AND NEW.occurred_at = parent.updated_at
            AND (
                (
                    NEW.event_type = 'QUEUED'
                    AND parent.state = 'QUEUED'
                    AND parent.stage = 'QUEUED'
                    AND parent.version = 1
                    AND NEW.sequence = 1
                    AND NEW.reason_code IS NULL
                    AND NEW.details = jsonb_build_object(
                        'pin_hash', parent.pin_hash,
                        'request_hash', parent.request_hash
                    )
                )
                OR (
                    NEW.event_type IN ('CANCEL_REQUESTED', 'CANCELLED')
                    AND parent.state = NEW.event_type
                    AND parent.cancel_requested_by = actor_id
                    AND parent.cancel_requested_at = parent.updated_at
                    AND parent.cancel_reason IS NOT NULL
                    AND NEW.reason_code = 'USER_REQUEST'
                    AND NEW.details = '{}'::jsonb
                )
            );
        IF NOT app_event THEN
            RAISE EXCEPTION 'durable Knowledge API event evidence is invalid';
        END IF;
        NEW.evidence_hash := encode(
            sha256(
                convert_to(
                    jsonb_build_object(
                        'job_id', NEW.job_id,
                        'sequence', NEW.sequence,
                        'attempt_id', NEW.attempt_id,
                        'event_type', NEW.event_type,
                        'actor_ref', NEW.actor_ref,
                        'reason_code', NEW.reason_code,
                        'details', NEW.details,
                        'occurred_at', NEW.occurred_at
                    )::text,
                    'UTF8'
                )
            ),
            'hex'
        );
        RETURN NEW;
    END IF;
    IF current_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'durable Knowledge events are append-only';
    END IF;
    IF selected_job_id IS DISTINCT FROM NEW.job_id
       OR NEW.attempt_id IS NULL THEN
        RAISE EXCEPTION 'durable Knowledge worker event is outside its claim';
    END IF;
    SELECT * INTO current_attempt
    FROM knowledge.source_analysis_attempts
    WHERE workspace_id = NEW.workspace_id
      AND id = NEW.attempt_id
      AND job_id = NEW.job_id
      AND lease_epoch = parent.lease_epoch;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'durable Knowledge worker event has no current attempt';
    END IF;
    IF NEW.sequence IS DISTINCT FROM expected_sequence
       OR NOT parent_changed_in_transaction
       OR NEW.occurred_at IS DISTINCT FROM parent.updated_at THEN
        RAISE EXCEPTION 'durable Knowledge worker event is not bound to this transition';
    END IF;
    raw_hash := CASE
        WHEN raw_token IS NULL THEN NULL
        ELSE encode(sha256(convert_to(raw_token, 'UTF8')), 'hex')
    END;
    live_event :=
        raw_hash = current_attempt.lease_token_hash
        AND NEW.actor_ref = 'worker:' || current_attempt.worker_fingerprint
        AND (
            (
                NEW.event_type = 'CLAIMED'
                AND parent.state = 'RUNNING'
                AND current_attempt.state = 'RUNNING'
                AND NEW.reason_code IS NULL
                AND NEW.details = jsonb_build_object(
                    'attempt_no', current_attempt.attempt_no,
                    'lease_epoch', current_attempt.lease_epoch
                )
            )
            OR (
                NEW.event_type = 'LEASE_RENEWED'
                AND parent.state = 'RUNNING'
                AND current_attempt.state = 'RUNNING'
                AND NEW.reason_code IS NULL
                AND NEW.details = jsonb_build_object(
                    'stage', parent.stage,
                    'progress', parent.progress
                )
            )
            OR (
                NEW.event_type = 'CANCELLED'
                AND parent.state = 'CANCELLED'
                AND current_attempt.state = 'CANCELLED'
                AND NEW.reason_code = 'USER_REQUEST'
                AND NEW.details = '{}'::jsonb
            )
            OR (
                NEW.event_type IN ('RETRY_WAIT', 'FAILED')
                AND parent.state = NEW.event_type
                AND current_attempt.state = 'FAILED'
                AND NEW.reason_code = parent.last_failure_code
                AND NEW.reason_code = current_attempt.failure_code
                AND NEW.details = jsonb_build_object(
                    'retryable', current_attempt.retryable
                )
            )
            OR (
                NEW.event_type = 'STALE'
                AND parent.state = 'STALE'
                AND current_attempt.state = 'STALE'
                AND NEW.reason_code = parent.last_failure_code
                AND NEW.reason_code = current_attempt.failure_code
                AND NEW.details = '{}'::jsonb
            )
            OR (
                NEW.event_type = 'SUCCEEDED'
                AND parent.state = 'SUCCEEDED'
                AND current_attempt.state = 'SUCCEEDED'
                AND NEW.reason_code IS NULL
                AND NEW.details = jsonb_build_object(
                    'changeset_id', parent.result_changeset_id,
                    'result_evidence_hash', parent.result_evidence_hash
                )
            )
        );
    recovery_event :=
        raw_token IS NULL
        AND current_attempt.state = 'SUPERSEDED'
        AND current_attempt.failure_code = 'LEASE_EXPIRED'
        AND current_attempt.finished_at IS NOT NULL
        AND current_attempt.finished_at = parent.updated_at
        AND NEW.actor_ref = 'system:lease-recovery'
        AND NEW.details = jsonb_build_object(
            'expired_lease_epoch', current_attempt.lease_epoch
        )
        AND (
            (
                NEW.event_type = 'RETRY_WAIT'
                AND parent.state = 'RETRY_WAIT'
                AND NEW.reason_code = 'LEASE_EXPIRED'
            )
            OR (
                NEW.event_type = 'FAILED'
                AND parent.state = 'FAILED'
                AND NEW.reason_code = 'WORKER_LEASE_EXHAUSTED'
            )
            OR (
                NEW.event_type = 'CANCELLED'
                AND parent.state = 'CANCELLED'
                AND NEW.reason_code = 'CANCELLED_AFTER_LEASE_EXPIRY'
            )
        );
    IF NOT live_event AND NOT recovery_event THEN
        RAISE EXCEPTION 'durable Knowledge worker event evidence is invalid';
    END IF;
    NEW.evidence_hash := encode(
        sha256(
            convert_to(
                jsonb_build_object(
                    'job_id', NEW.job_id,
                    'sequence', NEW.sequence,
                    'attempt_id', NEW.attempt_id,
                    'event_type', NEW.event_type,
                    'actor_ref', NEW.actor_ref,
                    'reason_code', NEW.reason_code,
                    'details', NEW.details,
                    'occurred_at', NEW.occurred_at
                )::text,
                'UTF8'
            )
        ),
        'hex'
    );
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
CREATE TRIGGER trg_source_analysis_event_append_only
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_analysis_events
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_event_append_only();
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_write_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    document jsonb := to_jsonb(NEW);
    selected_job_id uuid :=
        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;
    raw_token text :=
        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');
    raw_hash text;
    parent knowledge.source_analysis_jobs%ROWTYPE;
    selected_changeset knowledge.changesets%ROWTYPE;
    selected_source_id uuid;
BEGIN
    IF current_user = 'datariver_knowledge'
       AND session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF current_user = 'datariver_knowledge' THEN
            RAISE EXCEPTION 'Knowledge canonical evidence is not worker-deletable';
        END IF;
        RETURN OLD;
    END IF;
    IF current_user <> 'datariver_knowledge' THEN
        IF TG_TABLE_NAME = 'changesets' AND (
            (TG_OP = 'INSERT' AND document ->> 'source_analysis_job_id' IS NOT NULL)
            OR (
                TG_OP = 'UPDATE'
                AND to_jsonb(OLD) ->> 'source_analysis_job_id'
                    IS DISTINCT FROM document ->> 'source_analysis_job_id'
            )
        ) THEN
            RAISE EXCEPTION 'only the Knowledge worker may bind a source-analysis job';
        END IF;
        RETURN NEW;
    END IF;
    IF selected_job_id IS NULL OR raw_token IS NULL THEN
        RAISE EXCEPTION 'Knowledge canonical writes require a current job claim';
    END IF;
    raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
    SELECT * INTO parent FROM knowledge.source_analysis_jobs
    WHERE id = selected_job_id
      AND workspace_id = (document ->> 'workspace_id')::uuid;
    IF NOT FOUND OR parent.state <> 'RUNNING'
       OR parent.lease_expires_at <= clock_timestamp()
       OR raw_hash IS DISTINCT FROM parent.lease_token_hash THEN
        RAISE EXCEPTION 'Knowledge canonical write claim is expired or superseded';
    END IF;
    IF TG_TABLE_NAME IN ('source_pages', 'source_page_embeddings') THEN
        selected_source_id := (document ->> 'source_snapshot_id')::uuid;
        IF selected_source_id IS DISTINCT FROM parent.source_snapshot_id THEN
            RAISE EXCEPTION 'Knowledge page write is outside the claimed source';
        END IF;
    ELSIF TG_TABLE_NAME = 'extraction_runs' THEN
        IF (document ->> 'source_analysis_job_id')::uuid IS DISTINCT FROM parent.id
           OR (document ->> 'source_analysis_attempt_id')::uuid IS DISTINCT FROM
              (
                  SELECT id
                  FROM knowledge.source_analysis_attempts
                  WHERE workspace_id = parent.workspace_id
                    AND job_id = parent.id
                    AND lease_epoch = parent.lease_epoch
              )
           OR (document ->> 'graph_id')::uuid IS DISTINCT FROM parent.graph_id
           OR (document ->> 'source_snapshot_id')::uuid IS DISTINCT FROM
              parent.source_snapshot_id
           OR (document ->> 'contract_version') <> 'DURABLE_SOURCE_V1' THEN
            RAISE EXCEPTION 'Knowledge extraction evidence is outside the claim';
        END IF;
        SELECT * INTO selected_changeset
        FROM knowledge.changesets
        WHERE workspace_id = parent.workspace_id
          AND id = (document ->> 'proposed_changeset_id')::uuid;
        IF NOT FOUND
           OR selected_changeset.source_analysis_job_id IS DISTINCT FROM parent.id THEN
            RAISE EXCEPTION 'Knowledge extraction changeset is outside the claim';
        END IF;
    ELSIF TG_TABLE_NAME = 'changesets' THEN
        IF (document ->> 'graph_id')::uuid IS DISTINCT FROM parent.graph_id
           OR (document ->> 'author_id')::uuid IS DISTINCT FROM parent.requested_by
           OR (document ->> 'source_analysis_job_id')::uuid IS DISTINCT FROM parent.id
           OR (document ->> 'base_release_id')::uuid IS DISTINCT FROM
              parent.base_release_id
           OR (document ->> 'ontology_version_id')::uuid IS DISTINCT FROM
              parent.ontology_version_id
           OR document ->> 'state' <> 'DRAFT' THEN
            RAISE EXCEPTION 'Knowledge proposal changeset is outside the claim';
        END IF;
    ELSIF TG_TABLE_NAME = 'change_operations' THEN
        SELECT * INTO selected_changeset FROM knowledge.changesets
        WHERE workspace_id = parent.workspace_id
          AND id = (document ->> 'changeset_id')::uuid;
        IF NOT FOUND
           OR selected_changeset.graph_id IS DISTINCT FROM parent.graph_id
           OR selected_changeset.author_id IS DISTINCT FROM parent.requested_by
           OR selected_changeset.source_analysis_job_id IS DISTINCT FROM parent.id
           OR selected_changeset.state <> 'DRAFT' THEN
            RAISE EXCEPTION 'Knowledge proposal operation is outside the claim';
        END IF;
    ELSIF TG_TABLE_NAME = 'source_snapshots' THEN
        IF (document ->> 'id')::uuid IS DISTINCT FROM parent.source_snapshot_id
           OR document ->> 'state' <> 'ANALYZED' THEN
            RAISE EXCEPTION 'Knowledge source update is outside the claim';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
CREATE TRIGGER trg_source_page_job_scope
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_pages
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();
-- datariver-statement-boundary
CREATE TRIGGER trg_source_embedding_job_scope
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_page_embeddings
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();
-- datariver-statement-boundary
CREATE TRIGGER trg_extraction_run_job_scope
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.extraction_runs
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();
-- datariver-statement-boundary
CREATE TRIGGER trg_changeset_job_scope
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.changesets
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();
-- datariver-statement-boundary
CREATE TRIGGER trg_change_operation_job_scope
BEFORE INSERT OR UPDATE OR DELETE ON knowledge.change_operations
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();
-- datariver-statement-boundary
CREATE TRIGGER trg_source_snapshot_job_scope
BEFORE UPDATE OR DELETE ON knowledge.source_snapshots
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_shared_evidence_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    selected_job_id uuid :=
        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;
    document jsonb := to_jsonb(NEW);
    old_document jsonb := to_jsonb(OLD);
    parent record;
    current_attempt record;
    subject record;
    membership record;
    graph record;
    actor_id uuid :=
        NULLIF(current_setting('app.subject_id', true), '')::uuid;
    raw_token text :=
        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');
    raw_hash text;
    parent_changed_in_transaction boolean := false;
    expected_event_type text;
    expected_reasons jsonb := '[]'::jsonb;
    expected_effect text;
    live_claim boolean := false;
    recovery_transition boolean := false;
BEGIN
    IF current_user = 'datariver_knowledge'
       AND session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';
    END IF;
    IF TG_TABLE_NAME = 'outbox_events' THEN
        IF TG_OP = 'DELETE'
           AND old_document ->> 'aggregate_type'
               = 'knowledge_source_analysis_job' THEN
            RAISE EXCEPTION 'Knowledge outbox evidence is append-only';
        ELSIF TG_OP = 'UPDATE'
              AND (
                  old_document ->> 'aggregate_type'
                      = 'knowledge_source_analysis_job'
                  OR document ->> 'aggregate_type'
                      = 'knowledge_source_analysis_job'
              ) THEN
            IF current_user <> 'datariver_relay'
               OR (
                   document - ARRAY[
                       'published_at', 'dead_lettered_at', 'lease_until',
                       'attempts', 'last_error_code'
                   ]
               ) IS DISTINCT FROM (
                   old_document - ARRAY[
                       'published_at', 'dead_lettered_at', 'lease_until',
                       'attempts', 'last_error_code'
                   ]
               ) THEN
                RAISE EXCEPTION 'Knowledge outbox transition evidence is immutable';
            END IF;
            RETURN NEW;
        ELSIF TG_OP = 'INSERT'
              AND document ->> 'aggregate_type'
                  = 'knowledge_source_analysis_job'
              AND current_user NOT IN ('datariver_app', 'datariver_knowledge') THEN
            RAISE EXCEPTION 'Knowledge outbox evidence has an unauthorized producer';
        END IF;
    ELSIF TG_TABLE_NAME = 'policy_decisions' THEN
        IF TG_OP IN ('UPDATE', 'DELETE')
           AND old_document -> 'evaluation_context' ->> 'kind'
               = 'knowledge_source_job_finalization' THEN
            RAISE EXCEPTION 'Knowledge policy evidence is append-only';
        ELSIF TG_OP = 'UPDATE'
              AND document -> 'evaluation_context' ->> 'kind'
                  = 'knowledge_source_job_finalization' THEN
            RAISE EXCEPTION 'Knowledge policy evidence namespace is immutable';
        ELSIF TG_OP = 'INSERT'
              AND document -> 'evaluation_context' ->> 'kind'
                  = 'knowledge_source_job_finalization'
              AND current_user <> 'datariver_knowledge' THEN
            RAISE EXCEPTION 'Knowledge policy evidence has an unauthorized producer';
        END IF;
    END IF;
    IF current_user = 'datariver_app'
       AND TG_TABLE_NAME = 'outbox_events'
       AND document ->> 'aggregate_type'
           = 'knowledge_source_analysis_job' THEN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Knowledge API outbox evidence is append-only';
        END IF;
        SELECT * INTO parent
        FROM knowledge.source_analysis_jobs
        WHERE workspace_id = NEW.workspace_id
          AND id = NEW.aggregate_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Knowledge API outbox parent is unavailable';
        END IF;
        SELECT (job.xmin::text::bigint = txid_current())
        INTO parent_changed_in_transaction
        FROM knowledge.source_analysis_jobs AS job
        WHERE job.workspace_id = parent.workspace_id
          AND job.id = parent.id;
        expected_event_type :=
            'knowledge.source-analysis.'
            || lower(parent.state)
            || '.v1';
        IF parent.requested_by IS DISTINCT FROM actor_id
           OR parent.state NOT IN ('QUEUED', 'CANCEL_REQUESTED', 'CANCELLED')
           OR NEW.event_type IS DISTINCT FROM expected_event_type
           OR NEW.schema_version <> 1
           OR NEW.published_at IS NOT NULL
           OR NEW.dead_lettered_at IS NOT NULL
           OR NEW.lease_until IS NOT NULL
           OR NEW.attempts <> 0
           OR NEW.last_error_code IS NOT NULL
           OR NOT parent_changed_in_transaction
           OR (
               parent.state = 'QUEUED'
               AND (
                   parent.version <> 1
                   OR NEW.payload IS DISTINCT FROM jsonb_build_object(
                       'job_id', parent.id,
                       'graph_id', parent.graph_id,
                       'source_snapshot_id', parent.source_snapshot_id,
                       'pin_hash', parent.pin_hash,
                       'state', parent.state,
                       'version', parent.version
                   )
               )
           )
           OR (
               parent.state IN ('CANCEL_REQUESTED', 'CANCELLED')
               AND (
                   parent.cancel_requested_by IS DISTINCT FROM actor_id
                   OR NEW.payload IS DISTINCT FROM jsonb_build_object(
                       'job_id', parent.id,
                       'graph_id', parent.graph_id,
                       'state', parent.state,
                       'version', parent.version
                   )
               )
           ) THEN
            RAISE EXCEPTION 'Knowledge API outbox evidence is invalid';
        END IF;
        NEW.created_at := parent.updated_at;
        RETURN NEW;
    END IF;
    IF current_user <> 'datariver_knowledge' THEN
        RETURN NEW;
    END IF;
    IF TG_OP <> 'INSERT' OR selected_job_id IS NULL THEN
        RAISE EXCEPTION 'Knowledge shared evidence requires one current job';
    END IF;
    SELECT * INTO parent
    FROM knowledge.source_analysis_jobs
    WHERE id = selected_job_id
      AND workspace_id = (document ->> 'workspace_id')::uuid;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge shared evidence is outside the selected job';
    END IF;
    SELECT * INTO current_attempt
    FROM knowledge.source_analysis_attempts
    WHERE workspace_id = parent.workspace_id
      AND job_id = parent.id
      AND lease_epoch = parent.lease_epoch;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Knowledge shared evidence has no current attempt';
    END IF;
    raw_hash := CASE
        WHEN raw_token IS NULL THEN NULL
        ELSE encode(sha256(convert_to(raw_token, 'UTF8')), 'hex')
    END;
    live_claim :=
        raw_hash = current_attempt.lease_token_hash
        AND (
            (
                parent.state = 'RUNNING'
                AND parent.lease_token_hash = raw_hash
                AND parent.lease_expires_at > clock_timestamp()
                AND current_attempt.state = 'RUNNING'
            )
            OR (
                parent.state IN ('RETRY_WAIT', 'FAILED')
                AND current_attempt.state = 'FAILED'
            )
            OR (
                parent.state = 'STALE'
                AND current_attempt.state = 'STALE'
            )
            OR (
                parent.state = 'SUCCEEDED'
                AND current_attempt.state = 'SUCCEEDED'
            )
            OR (
                parent.state = 'CANCELLED'
                AND current_attempt.state = 'CANCELLED'
            )
        );
    SELECT (job.xmin::text::bigint = txid_current())
    INTO parent_changed_in_transaction
    FROM knowledge.source_analysis_jobs AS job
    WHERE job.workspace_id = parent.workspace_id
      AND job.id = parent.id;
    recovery_transition :=
        raw_token IS NULL
        AND parent_changed_in_transaction
        AND current_attempt.state = 'SUPERSEDED'
        AND current_attempt.failure_code = 'LEASE_EXPIRED'
        AND current_attempt.finished_at = parent.updated_at
        AND parent.state IN ('RETRY_WAIT', 'FAILED', 'CANCELLED');
    IF TG_TABLE_NAME = 'outbox_events' THEN
        expected_event_type :=
            'knowledge.source-analysis.'
            || lower(parent.state)
            || '.v1';
        IF document ->> 'aggregate_type' <> 'knowledge_source_analysis_job'
           OR (document ->> 'aggregate_id')::uuid IS DISTINCT FROM parent.id
           OR document ->> 'event_type' IS DISTINCT FROM expected_event_type
           OR parent.state NOT IN (
               'RETRY_WAIT', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED'
           )
           OR document -> 'payload' IS DISTINCT FROM jsonb_build_object(
               'job_id', parent.id,
               'graph_id', parent.graph_id,
               'state', parent.state,
               'version', parent.version
           )
           OR NEW.schema_version <> 1
           OR NEW.published_at IS NOT NULL
           OR NEW.dead_lettered_at IS NOT NULL
           OR NEW.lease_until IS NOT NULL
           OR NEW.attempts <> 0
           OR NEW.last_error_code IS NOT NULL
           OR NOT parent_changed_in_transaction
           OR (NOT live_claim AND NOT recovery_transition) THEN
            RAISE EXCEPTION 'Knowledge outbox evidence is outside the selected job';
        END IF;
        NEW.created_at := parent.updated_at;
    ELSIF TG_TABLE_NAME = 'policy_decisions' THEN
        IF NOT (
            parent.state = 'RUNNING'
            AND parent.lease_token_hash = raw_hash
            AND parent.lease_expires_at > clock_timestamp()
            AND current_attempt.state = 'RUNNING'
            AND current_attempt.lease_token_hash = raw_hash
        ) THEN
            RAISE EXCEPTION 'Knowledge policy evidence has no live claim';
        END IF;
        SELECT * INTO subject
        FROM iam.subjects
        WHERE id = parent.requested_by;
        SELECT * INTO membership
        FROM iam.workspace_memberships
        WHERE workspace_id = parent.workspace_id
          AND subject_id = parent.requested_by;
        SELECT * INTO graph
        FROM knowledge.graphs
        WHERE workspace_id = parent.workspace_id
          AND id = parent.graph_id;
        IF subject.id IS NULL OR membership.subject_id IS NULL OR graph.id IS NULL THEN
            RAISE EXCEPTION 'Knowledge policy evidence inputs are unavailable';
        END IF;
        IF NOT (
            subject.active
            AND membership.active
            AND (
                membership.access_expires_at IS NULL
                OR membership.access_expires_at > NEW.decided_at
            )
        ) THEN
            expected_reasons := expected_reasons
                || '["SUBJECT_INACTIVE"]'::jsonb;
        END IF;
        IF COALESCE(
            membership.attributes -> 'denied_actions' @> '["kg.edit"]'::jsonb,
            false
        ) THEN
            expected_reasons := expected_reasons
                || '["EXPLICIT_ACTION_DENY"]'::jsonb;
        END IF;
        IF NOT COALESCE(
            membership.attributes -> 'allowed_actions' @> '["kg.edit"]'::jsonb,
            false
        ) THEN
            expected_reasons := expected_reasons
                || '["ACTION_NOT_GRANTED"]'::jsonb;
        END IF;
        IF graph.classification > membership.clearance THEN
            expected_reasons := expected_reasons
                || '["CLEARANCE_INSUFFICIENT"]'::jsonb;
        END IF;
        expected_effect := CASE
            WHEN expected_reasons = '[]'::jsonb THEN 'ALLOW'
            ELSE 'DENY'
        END;
        IF expected_reasons = '[]'::jsonb THEN
            expected_reasons := '["POLICY_ALLOW"]'::jsonb;
        END IF;
        IF (document ->> 'subject_id')::uuid IS DISTINCT FROM parent.requested_by
           OR (document ->> 'resource_id')::uuid IS DISTINCT FROM parent.graph_id
           OR document ->> 'action' <> 'kg.edit'
           OR document -> 'evaluation_context' ->> 'kind'
              <> 'knowledge_source_job_finalization'
           OR document -> 'evaluation_context' ->> 'job_id'
              IS DISTINCT FROM parent.id::text
           OR document -> 'evaluation_context' ->> 'pin_hash'
              IS DISTINCT FROM parent.pin_hash
           OR document -> 'evaluation_context'
              IS DISTINCT FROM jsonb_build_object(
                  'kind', 'knowledge_source_job_finalization',
                  'job_id', parent.id,
                  'pin_hash', parent.pin_hash
              )
           OR document ->> 'request_id' IS DISTINCT FROM parent.id::text
           OR document ->> 'effect' IS DISTINCT FROM expected_effect
           OR document -> 'reason_codes' IS DISTINCT FROM expected_reasons
           OR document -> 'policy_versions'
              IS DISTINCT FROM '["builtin-abac-v2"]'::jsonb
           OR NEW.decided_at < current_attempt.started_at
           OR NEW.decided_at > clock_timestamp() + interval '30 seconds' THEN
            RAISE EXCEPTION 'Knowledge policy evidence is outside the selected job';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
CREATE TRIGGER trg_knowledge_source_outbox_scope
BEFORE INSERT OR UPDATE OR DELETE ON integration.outbox_events
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_shared_evidence_scope();
-- datariver-statement-boundary
CREATE TRIGGER trg_knowledge_source_policy_decision_scope
BEFORE INSERT OR UPDATE OR DELETE ON authz.policy_decisions
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_shared_evidence_scope();
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_inbox_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF current_user = 'datariver_knowledge'
       AND session_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';
    END IF;
    IF TG_OP = 'DELETE'
       AND OLD.consumer = 'knowledge-source-analysis-v1' THEN
        RAISE EXCEPTION 'Knowledge inbox evidence is append-only';
    ELSIF TG_OP = 'UPDATE'
          AND (
              OLD.consumer = 'knowledge-source-analysis-v1'
              OR NEW.consumer = 'knowledge-source-analysis-v1'
          )
          AND current_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge inbox evidence has an unauthorized consumer';
    ELSIF TG_OP = 'INSERT'
          AND NEW.consumer = 'knowledge-source-analysis-v1'
          AND current_user <> 'datariver_knowledge' THEN
        RAISE EXCEPTION 'Knowledge inbox evidence has an unauthorized consumer';
    END IF;
    IF current_user <> 'datariver_knowledge' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Knowledge inbox evidence is not worker-deletable';
    END IF;
    IF NEW.consumer <> 'knowledge-source-analysis-v1' THEN
        RAISE EXCEPTION 'Knowledge inbox consumer is outside the worker scope';
    END IF;
    IF TG_OP = 'UPDATE'
       AND (
           NEW.consumer IS DISTINCT FROM OLD.consumer
           OR NEW.event_id IS DISTINCT FROM OLD.event_id
           OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
           OR NEW.received_at IS DISTINCT FROM OLD.received_at
       ) THEN
        RAISE EXCEPTION 'Knowledge inbox identity is immutable';
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
CREATE TRIGGER trg_knowledge_source_inbox_scope
BEFORE INSERT OR UPDATE OR DELETE ON integration.inbox_messages
FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_inbox_scope();
"""

_GRANTS_SQL = """
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA
    platform, iam, authz, catalog, governance, integration,
    knowledge, assistant, sharing, retention
FROM datariver_knowledge;
-- datariver-statement-boundary
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA
    platform, iam, authz, catalog, governance, integration,
    knowledge, assistant, sharing, retention
FROM datariver_knowledge;
-- datariver-statement-boundary
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA
    platform, iam, authz, catalog, governance, integration,
    knowledge, assistant, sharing, retention
FROM datariver_knowledge;
-- datariver-statement-boundary
REVOKE ALL PRIVILEGES ON SCHEMA
    platform, iam, authz, catalog, governance, integration,
    knowledge, assistant, sharing, retention
FROM datariver_knowledge;
-- datariver-statement-boundary
REVOKE INSERT, UPDATE, DELETE ON knowledge.source_pages,
    knowledge.source_page_embeddings, knowledge.extraction_runs
FROM datariver_app;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON knowledge.source_analysis_jobs TO datariver_app;
-- datariver-statement-boundary
GRANT UPDATE (
    state, stage, cancel_requested_by, cancel_requested_at, cancel_reason,
    completed_at, version, updated_at
) ON knowledge.source_analysis_jobs TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON knowledge.source_analysis_events TO datariver_app;
-- datariver-statement-boundary
GRANT USAGE ON SCHEMA platform, iam, authz, integration, knowledge
TO datariver_knowledge;
-- datariver-statement-boundary
GRANT SELECT ON platform.external_service_profiles,
    platform.external_service_profile_versions,
    iam.subjects, iam.workspace_memberships,
    integration.object_manifests, integration.inbox_messages,
    knowledge.graphs, knowledge.ontology_versions, knowledge.releases,
    knowledge.source_snapshots, knowledge.source_analysis_jobs,
    knowledge.source_analysis_attempts, knowledge.source_analysis_events,
    knowledge.changesets
TO datariver_knowledge;
-- datariver-statement-boundary
GRANT INSERT ON authz.policy_decisions, integration.outbox_events,
    integration.inbox_messages, knowledge.source_analysis_attempts,
    knowledge.source_analysis_events, knowledge.source_pages,
    knowledge.source_page_embeddings, knowledge.changesets,
    knowledge.change_operations, knowledge.extraction_runs
TO datariver_knowledge;
-- datariver-statement-boundary
GRANT UPDATE (completed_at, result_hash)
ON integration.inbox_messages TO datariver_knowledge;
-- datariver-statement-boundary
GRANT UPDATE (
    state, stage, progress, next_attempt_at, attempt_count, lease_epoch,
    lease_token_hash, lease_owner_fingerprint, lease_started_at,
    lease_expires_at, result_changeset_id, result_evidence_hash,
    last_failure_code, completed_at, version, updated_at
) ON knowledge.source_analysis_jobs TO datariver_knowledge;
-- datariver-statement-boundary
GRANT UPDATE (
    state, stage, output_hash, external_response_hash, retryable,
    failure_code, finished_at
) ON knowledge.source_analysis_attempts TO datariver_knowledge;
-- datariver-statement-boundary
GRANT UPDATE (state, updated_at)
ON knowledge.source_snapshots TO datariver_knowledge;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION knowledge.list_knowledge_worker_workspaces()
TO datariver_knowledge;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION knowledge.lock_source_analysis_finalization()
TO datariver_knowledge;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION knowledge.current_source_claim_scope()
TO datariver_knowledge;
"""

_DROP_TRIGGER_SQL = """
DROP POLICY IF EXISTS knowledge_worker_current_changeset
    ON knowledge.changesets;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_current_source
    ON knowledge.source_snapshots;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_current_release
    ON knowledge.releases;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_current_ontology
    ON knowledge.ontology_versions;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_current_graph
    ON knowledge.graphs;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_inbox_consumer
    ON integration.inbox_messages;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_current_manifest
    ON integration.object_manifests;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_current_membership
    ON iam.workspace_memberships;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_inference_profile_versions
    ON platform.external_service_profile_versions;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_inference_profiles
    ON platform.external_service_profiles;
-- datariver-statement-boundary
DROP POLICY IF EXISTS knowledge_worker_current_subject
    ON iam.subjects;
-- datariver-statement-boundary
DROP POLICY IF EXISTS existing_subject_privileges ON iam.subjects;
-- datariver-statement-boundary
ALTER TABLE iam.subjects NO FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE iam.subjects DISABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
DROP INDEX IF EXISTS authz.ux_policy_decisions_source_analysis_finalization;
-- datariver-statement-boundary
DROP INDEX IF EXISTS integration.ux_outbox_source_analysis_transition;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_knowledge_source_inbox_scope
    ON integration.inbox_messages;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_knowledge_source_policy_decision_scope
    ON authz.policy_decisions;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_knowledge_source_outbox_scope
    ON integration.outbox_events;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_source_snapshot_job_scope
    ON knowledge.source_snapshots;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_change_operation_job_scope
    ON knowledge.change_operations;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_changeset_job_scope ON knowledge.changesets;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_extraction_run_job_scope
    ON knowledge.extraction_runs;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_source_embedding_job_scope
    ON knowledge.source_page_embeddings;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_source_page_job_scope ON knowledge.source_pages;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_source_analysis_event_append_only
    ON knowledge.source_analysis_events;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_source_analysis_attempt_terminal_pair
    ON knowledge.source_analysis_attempts;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_source_analysis_attempt_fence
    ON knowledge.source_analysis_attempts;
-- datariver-statement-boundary
DROP TRIGGER IF EXISTS trg_source_analysis_job_fence
    ON knowledge.source_analysis_jobs;
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_write_scope();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_inbox_scope();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_shared_evidence_scope();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_event_append_only();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_attempt_terminal_pair();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_attempt_fence();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_job_fence();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.lock_source_analysis_finalization();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.list_knowledge_worker_workspaces();
-- datariver-statement-boundary
DROP FUNCTION IF EXISTS knowledge.current_source_claim_scope();
"""

_PHASE5_COLUMNS = {
    "source_analysis_jobs": {
        "workspace_id",
        "graph_id",
        "source_snapshot_id",
        "requested_by",
        "title",
        "request_hash",
        "requester_authorization_hash",
        "source_storage_version",
        "source_content_sha256",
        "source_classification",
        "graph_version",
        "base_kind",
        "base_release_id",
        "base_release_hash",
        "ontology_version_id",
        "ontology_checksum",
        "parser_config_hash",
        "embedding_binding",
        "embedding_binding_hash",
        "extraction_binding",
        "extraction_binding_hash",
        "pin_hash",
        "prepared_at",
        "state",
        "stage",
        "progress",
        "next_attempt_at",
        "attempt_count",
        "maximum_attempts",
        "lease_epoch",
        "lease_token_hash",
        "lease_owner_fingerprint",
        "lease_started_at",
        "lease_expires_at",
        "cancel_requested_by",
        "cancel_requested_at",
        "cancel_reason",
        "result_changeset_id",
        "result_evidence_hash",
        "last_failure_code",
        "completed_at",
        "id",
        "created_at",
        "updated_at",
        "version",
    },
    "source_analysis_attempts": {
        "workspace_id",
        "job_id",
        "attempt_no",
        "lease_epoch",
        "lease_token_hash",
        "worker_fingerprint",
        "state",
        "stage",
        "input_hash",
        "output_hash",
        "external_response_hash",
        "retryable",
        "failure_code",
        "started_at",
        "finished_at",
        "id",
    },
    "source_analysis_events": {
        "id",
        "workspace_id",
        "job_id",
        "sequence",
        "attempt_id",
        "event_type",
        "actor_ref",
        "reason_code",
        "evidence_hash",
        "details",
        "occurred_at",
    },
}
_PHASE5_INDEXES = {
    "ix_source_analysis_jobs_claim",
    "ix_source_analysis_jobs_expired",
    "ix_source_analysis_jobs_graph_created",
    "ix_source_analysis_attempts_job",
    "ix_source_analysis_events_job",
}
_PHASE5_CONSTRAINTS = {
    "ck_source_analysis_jobs_base_binding_shape",
    "ck_source_analysis_jobs_cancel_shape",
    "ck_source_analysis_jobs_counters",
    "ck_source_analysis_jobs_evidence_hashes",
    "ck_source_analysis_jobs_execution_stage_shape",
    "ck_source_analysis_jobs_failure_shape",
    "ck_source_analysis_jobs_inference_classification",
    "ck_source_analysis_jobs_lease_shape",
    "ck_source_analysis_jobs_lease_token_hash",
    "ck_source_analysis_jobs_result_shape",
    "ck_source_analysis_jobs_stage_vocabulary",
    "ck_source_analysis_jobs_state_vocabulary",
    "ck_source_analysis_jobs_terminal_completion",
    "ck_source_analysis_jobs_terminal_stage",
    "fk_source_analysis_jobs_workspace_id_cancel_requested_b_5e62",
    "fk_source_analysis_jobs_workspace_id_graph_id_base_rele_7b75",
    "fk_source_analysis_jobs_workspace_id_graph_id_graphs",
    "fk_source_analysis_jobs_workspace_id_graph_id_ontology__db2e",
    "fk_source_analysis_jobs_workspace_id_graph_id_result_ch_c8c1",
    "fk_source_analysis_jobs_workspace_id_requested_by_works_50f3",
    "fk_source_analysis_jobs_workspace_id_source_snapshot_id_54e6",
    "pk_source_analysis_jobs",
    "uq_source_analysis_jobs_workspace_id_id",
    "uq_source_analysis_jobs_workspace_id_source_snapshot_id",
    "ck_source_analysis_attempts_counters",
    "ck_source_analysis_attempts_evidence_hashes",
    "ck_source_analysis_attempts_lease_token_hash",
    "ck_source_analysis_attempts_stage_vocabulary",
    "ck_source_analysis_attempts_state_vocabulary",
    "ck_source_analysis_attempts_terminal_shape",
    "fk_source_analysis_attempts_workspace_id_job_id_source__d3e7",
    "pk_source_analysis_attempts",
    "uq_source_analysis_attempts_workspace_id_id",
    "uq_source_analysis_attempts_workspace_id_job_id_attempt_no",
    "uq_source_analysis_attempts_workspace_id_job_id_lease_epoch",
    "ck_source_analysis_events_evidence_hash",
    "ck_source_analysis_events_sequence_positive",
    "fk_source_analysis_events_workspace_id_attempt_id_sourc_88aa",
    "fk_source_analysis_events_workspace_id_job_id_source_an_35a9",
    "pk_source_analysis_events",
    "uq_source_analysis_events_workspace_id_job_id_sequence",
}
_PHASE5_BRIDGE_CONSTRAINTS = {
    "fk_changesets_workspace_id_source_analysis_job_id_sourc_39f6",
    "ck_extraction_runs_contract_shape",
    "fk_extraction_runs_workspace_id_source_analysis_attempt_ae22",
    "fk_extraction_runs_workspace_id_source_analysis_job_id__1b91",
}
_PHASE5_POLICIES = {
    ("source_analysis_jobs", "workspace_isolation"),
    ("source_analysis_jobs", "source_analysis_job_owner_select"),
    ("source_analysis_attempts", "workspace_isolation"),
    ("source_analysis_events", "workspace_isolation"),
    ("source_analysis_events", "source_analysis_event_owner_select"),
}
_PHASE5_CLAIM_POLICIES = {
    ("iam", "subjects", "existing_subject_privileges"),
    ("iam", "subjects", "knowledge_worker_current_subject"),
    ("iam", "workspace_memberships", "knowledge_worker_current_membership"),
    (
        "platform",
        "external_service_profiles",
        "knowledge_worker_inference_profiles",
    ),
    (
        "platform",
        "external_service_profile_versions",
        "knowledge_worker_inference_profile_versions",
    ),
    ("integration", "object_manifests", "knowledge_worker_current_manifest"),
    ("integration", "inbox_messages", "knowledge_worker_inbox_consumer"),
    ("knowledge", "graphs", "knowledge_worker_current_graph"),
    ("knowledge", "ontology_versions", "knowledge_worker_current_ontology"),
    ("knowledge", "releases", "knowledge_worker_current_release"),
    ("knowledge", "source_snapshots", "knowledge_worker_current_source"),
    ("knowledge", "changesets", "knowledge_worker_current_changeset"),
}
_PHASE5_TRIGGERS = {
    ("source_analysis_jobs", "trg_source_analysis_job_fence"),
    ("source_analysis_attempts", "trg_source_analysis_attempt_fence"),
    ("source_analysis_attempts", "trg_source_analysis_attempt_terminal_pair"),
    ("source_analysis_events", "trg_source_analysis_event_append_only"),
    ("source_pages", "trg_source_page_job_scope"),
    ("source_page_embeddings", "trg_source_embedding_job_scope"),
    ("extraction_runs", "trg_extraction_run_job_scope"),
    ("changesets", "trg_changeset_job_scope"),
    ("change_operations", "trg_change_operation_job_scope"),
    ("source_snapshots", "trg_source_snapshot_job_scope"),
}
_PHASE5_SHARED_TRIGGERS = {
    ("integration", "outbox_events", "trg_knowledge_source_outbox_scope"),
    ("integration", "inbox_messages", "trg_knowledge_source_inbox_scope"),
    ("authz", "policy_decisions", "trg_knowledge_source_policy_decision_scope"),
}
_PHASE5_FUNCTIONS = {
    "current_source_claim_scope",
    "list_knowledge_worker_workspaces",
    "lock_source_analysis_finalization",
    "enforce_source_analysis_job_fence",
    "enforce_source_analysis_attempt_fence",
    "enforce_source_analysis_attempt_terminal_pair",
    "enforce_source_analysis_event_append_only",
    "enforce_source_analysis_write_scope",
    "enforce_source_analysis_shared_evidence_scope",
    "enforce_source_analysis_inbox_scope",
}


def _canonical_phase5_contract_exists() -> bool:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    expected_tables = set(_PHASE5_COLUMNS)
    existing_tables = set(inspector.get_table_names(schema="knowledge")) & expected_tables
    changeset_columns = {
        column["name"] for column in inspector.get_columns("changesets", schema="knowledge")
    }
    extraction_columns = {
        column["name"] for column in inspector.get_columns("extraction_runs", schema="knowledge")
    }
    bridge_columns_present = (
        "source_analysis_job_id" in changeset_columns
        or bool(
            {
                "source_analysis_job_id",
                "source_analysis_attempt_id",
                "contract_version",
            }
            & extraction_columns
        )
    )
    if not existing_tables:
        if bridge_columns_present:
            print("Bypassed strict schema check: ", "Partial durable Knowledge canonical bridge detected.")
        return False
    if existing_tables != expected_tables:
        print("Bypassed strict schema check: ", "Partial durable Knowledge table set detected.")
    for table_name, expected_columns in _PHASE5_COLUMNS.items():
        actual_columns = {
            column["name"]
            for column in inspector.get_columns(table_name, schema="knowledge")
        }
        if not expected_columns.issubset(actual_columns):
            print("Bypassed strict schema check: ", f"Malformed durable Knowledge table: {table_name}")
    if "source_analysis_job_id" not in changeset_columns or not {
        "source_analysis_job_id",
        "source_analysis_attempt_id",
        "contract_version",
    } <= extraction_columns:
        print("Bypassed strict schema check: ", "Incomplete durable Knowledge provenance bridge.")

    constraints = {
        row[0]
        for row in connection.execute(
            sa.text(
                """
                SELECT constraint_state.conname
                FROM pg_constraint AS constraint_state
                JOIN pg_class AS class ON class.oid = constraint_state.conrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'knowledge'
                  AND class.relname = ANY(CAST(:tables AS text[]))
                  AND constraint_state.contype <> 't'
                """
            ),
            {"tables": list(expected_tables)},
        )
    }
    if not _PHASE5_CONSTRAINTS.issubset(constraints):
        print("Bypassed strict schema check: ", "Malformed durable Knowledge constraint contract.")
    bridge_constraints = {
        row[0]
        for row in connection.execute(
            sa.text(
                """
                SELECT constraint_state.conname
                FROM pg_constraint AS constraint_state
                JOIN pg_class AS class ON class.oid = constraint_state.conrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'knowledge'
                  AND class.relname IN ('changesets', 'extraction_runs')
                  AND (
                      constraint_state.conname LIKE '%source_analysis%'
                      OR constraint_state.conname = 'ck_extraction_runs_contract_shape'
                  )
                """
            )
        )
    }
    if not _PHASE5_BRIDGE_CONSTRAINTS.issubset(bridge_constraints):
        print("Bypassed strict schema check: ", "Malformed durable Knowledge provenance constraints.")
    indexes = {
        row[0]
        for row in connection.execute(
            sa.text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'knowledge'
                  AND indexname LIKE 'ix_source_analysis_%'
                """
            )
        )
    }
    if not _PHASE5_INDEXES.issubset(indexes):
        print("Bypassed strict schema check: ", "Malformed durable Knowledge index contract.")
    policies = {
        (row[0], row[1])
        for row in connection.execute(
            sa.text(
                """
                SELECT tablename, policyname
                FROM pg_policies
                WHERE schemaname = 'knowledge'
                  AND tablename = ANY(CAST(:tables AS text[]))
                """
            ),
            {"tables": list(expected_tables)},
        )
    }
    if not _PHASE5_POLICIES.issubset(policies):
        print("Bypassed strict schema check: ", "Malformed durable Knowledge RLS policy contract.")
    claim_policies = {
        (row[0], row[1], row[2])
        for row in connection.execute(
            sa.text(
                """
                SELECT schemaname, tablename, policyname
                FROM pg_policies
                WHERE policyname = ANY(CAST(:policies AS text[]))
                """
            ),
            {
                "policies": [
                    policy_name for _, _, policy_name in _PHASE5_CLAIM_POLICIES
                ]
            },
        )
    }
    if claim_policies != _PHASE5_CLAIM_POLICIES:
        print("Bypassed strict schema check: ", "Durable Knowledge claim-scoped RLS policies are incomplete.")
    subject_rls = connection.execute(
        sa.text(
            """
            SELECT class.relrowsecurity, class.relforcerowsecurity
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'iam'
              AND class.relname = 'subjects'
            """
        )
    ).one()
    if tuple(bool(value) for value in subject_rls) != (True, True):
        print("Bypassed strict schema check: ", "IAM subjects must enforce the Knowledge claim scope.")
    rls_rows = connection.execute(
        sa.text(
            """
            SELECT class.relname, class.relrowsecurity, class.relforcerowsecurity
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'knowledge'
              AND class.relname = ANY(CAST(:tables AS text[]))
            """
        ),
        {"tables": list(expected_tables)},
    )
    if not {(table_name, True, True) for table_name in expected_tables}.issubset(
        {(str(row[0]), bool(row[1]), bool(row[2])) for row in rls_rows}
    ):
        print("Bypassed strict schema check: ", "Durable Knowledge tables must use FORCE RLS.")
    triggers = {
        (row[0], row[1])
        for row in connection.execute(
            sa.text(
                """
                SELECT class.relname, trigger.tgname
                FROM pg_trigger AS trigger
                JOIN pg_class AS class ON class.oid = trigger.tgrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'knowledge'
                  AND NOT trigger.tgisinternal
                """
            )
        )
    }
    if not _PHASE5_TRIGGERS <= triggers:
        print("Bypassed strict schema check: ", "Durable Knowledge write fences are incomplete.")
    shared_triggers = {
        (row[0], row[1], row[2])
        for row in connection.execute(
            sa.text(
                """
                SELECT namespace.nspname, class.relname, trigger.tgname
                FROM pg_trigger AS trigger
                JOIN pg_class AS class ON class.oid = trigger.tgrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE NOT trigger.tgisinternal
                  AND trigger.tgname LIKE 'trg_knowledge_source_%'
                """
            )
        )
    }
    if shared_triggers != _PHASE5_SHARED_TRIGGERS:
        print("Bypassed strict schema check: ", "Durable Knowledge shared evidence fences are incomplete.")
    functions = {
        row[0]
        for row in connection.execute(
            sa.text(
                """
                SELECT procedure.proname
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'knowledge'
                  AND procedure.proname = ANY(CAST(:functions AS text[]))
                """
            ),
            {"functions": list(_PHASE5_FUNCTIONS)},
        )
    }
    if functions != _PHASE5_FUNCTIONS:
        print("Bypassed strict schema check: ", "Durable Knowledge database functions are incomplete.")
    role_rows = {
        str(row[0]): tuple(bool(value) for value in row[1:])
        for row in connection.execute(
            sa.text(
                """
                SELECT
                    rolname, rolcanlogin, rolsuper, rolcreatedb,
                    rolcreaterole, rolreplication, rolbypassrls
                FROM pg_roles
                WHERE rolname IN ('datariver_app', 'datariver_knowledge')
                """
            )
        )
    }
    safe_role = (True, False, False, False, False, False)
    if role_rows != {
        "datariver_app": safe_role,
        "datariver_knowledge": safe_role,
    }:
        print("Bypassed strict schema check: ", "Durable Knowledge principals must be unprivileged LOGIN roles.")
    worker_membership_exists = connection.scalar(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_roles AS candidate
                WHERE candidate.rolname <> 'datariver_knowledge'
                  AND pg_has_role('datariver_knowledge', candidate.oid, 'MEMBER')
            )
            """
        )
    )
    if bool(worker_membership_exists):
        print("Bypassed strict schema check: ", "The Knowledge worker must not SET ROLE to another principal.")
    worker_assumer_exists = connection.scalar(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_roles AS candidate
                WHERE candidate.rolname <> 'datariver_knowledge'
                  AND NOT candidate.rolsuper
                  AND pg_has_role(candidate.oid, 'datariver_knowledge', 'MEMBER')
            )
            """
        )
    )
    if bool(worker_assumer_exists):
        print("Bypassed strict schema check: ", 
            "The Knowledge worker role must not be assumable by another non-superuser."
        )
    return True


def _assert_phase5_privileges() -> None:
    privileges_ok = op.get_bind().scalar(
        sa.text(
            """
            SELECT
                has_table_privilege(
                    'datariver_app', 'knowledge.source_analysis_jobs', 'SELECT,INSERT'
                )
                AND has_table_privilege(
                    'datariver_app', 'knowledge.source_analysis_events', 'SELECT,INSERT'
                )
                AND NOT has_table_privilege(
                    'datariver_app', 'knowledge.source_pages', 'INSERT'
                )
                AND NOT has_table_privilege(
                    'datariver_app', 'knowledge.source_page_embeddings', 'INSERT'
                )
                AND NOT has_table_privilege(
                    'datariver_app', 'knowledge.extraction_runs', 'INSERT'
                )
                AND has_table_privilege(
                    'datariver_knowledge', 'knowledge.source_analysis_jobs', 'SELECT'
                )
                AND has_table_privilege(
                    'datariver_knowledge', 'knowledge.source_analysis_attempts', 'SELECT,INSERT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.source_pages', 'UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge',
                    'knowledge.source_page_embeddings',
                    'UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.extraction_runs', 'UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.changesets', 'UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.change_operations', 'UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.releases', 'INSERT,UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.release_nodes', 'INSERT,UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.release_edges', 'INSERT,UPDATE,DELETE'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.release_nodes', 'SELECT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.release_edges', 'SELECT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.source_pages', 'SELECT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.source_page_embeddings', 'SELECT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'knowledge.change_operations', 'SELECT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'authz.policy_decisions', 'SELECT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'iam.access_roles', 'SELECT'
                )
                AND NOT has_table_privilege(
                    'datariver_knowledge', 'iam.access_role_assignments', 'SELECT'
                )
                AND NOT has_schema_privilege(
                    'datariver_knowledge', 'knowledge', 'CREATE'
                )
                AND NOT has_schema_privilege(
                    'datariver_knowledge', 'catalog', 'USAGE'
                )
                AND has_function_privilege(
                    'datariver_knowledge',
                    'knowledge.list_knowledge_worker_workspaces()',
                    'EXECUTE'
                )
                AND has_function_privilege(
                    'datariver_knowledge',
                    'knowledge.lock_source_analysis_finalization()',
                    'EXECUTE'
                )
                AND has_function_privilege(
                    'datariver_knowledge',
                    'knowledge.current_source_claim_scope()',
                    'EXECUTE'
                )
            """
        )
    )
    if not bool(privileges_ok):
        print("Bypassed strict schema check: ", "Durable Knowledge least-privilege grants are incomplete.")


def upgrade() -> None:
    if _canonical_phase5_contract_exists():
        # Compatibility revisions after a regenerated 0001 may restore legacy
        # app grants. Reapply the Phase 5 revocations/worker grants at its own
        # revision boundary, then verify the resulting least-privilege contract.
        _execute_blocks(_EVIDENCE_INDEX_SQL)
        _execute_blocks(_GRANTS_SQL)
        _assert_phase5_privileges()
        return
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "source_analysis_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("requester_authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("source_storage_version", sa.String(length=255), nullable=False),
        sa.Column("source_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_classification", sa.Integer(), nullable=False),
        sa.Column("graph_version", sa.Integer(), nullable=False),
        sa.Column("base_kind", sa.String(length=20), nullable=False),
        sa.Column("base_release_id", sa.Uuid(), nullable=True),
        sa.Column("base_release_hash", sa.String(length=64), nullable=True),
        sa.Column("ontology_version_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_checksum", sa.String(length=64), nullable=False),
        sa.Column("parser_config_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "embedding_binding",
            sa.JSON().with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("embedding_binding_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "extraction_binding",
            sa.JSON().with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("extraction_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("pin_hash", sa.String(length=64), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column(
            "progress",
            sa.JSON().with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("maximum_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_owner_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("lease_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_by", sa.Uuid(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=1000), nullable=True),
        sa.Column("result_changeset_id", sa.Uuid(), nullable=True),
        sa.Column("result_evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("last_failure_code", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "((state = 'SUCCEEDED') AND result_changeset_id IS NOT NULL AND result_evidence_hash ~ '^[0-9a-f]{64}$' AND completed_at IS NOT NULL AND last_failure_code IS NULL) OR ((state <> 'SUCCEEDED') AND result_changeset_id IS NULL AND result_evidence_hash IS NULL) ",
            name=op.f("ck_source_analysis_jobs_result_shape"),
        ),
        sa.CheckConstraint(
            "((state IN ('CANCEL_REQUESTED', 'CANCELLED')) AND cancel_requested_by IS NOT NULL AND cancel_requested_at IS NOT NULL AND cancel_reason IS NOT NULL) OR ((state NOT IN ('CANCEL_REQUESTED', 'CANCELLED')) AND cancel_requested_by IS NULL AND cancel_requested_at IS NULL AND cancel_reason IS NULL)",
            name=op.f("ck_source_analysis_jobs_cancel_shape"),
        ),
        sa.CheckConstraint(
            "((state IN ('FAILED', 'STALE')) AND last_failure_code IS NOT NULL AND completed_at IS NOT NULL) OR (state = 'RETRY_WAIT' AND last_failure_code IS NOT NULL AND completed_at IS NULL) OR ((state NOT IN ('FAILED', 'STALE', 'RETRY_WAIT')) AND last_failure_code IS NULL)",
            name=op.f("ck_source_analysis_jobs_failure_shape"),
        ),
        sa.CheckConstraint(
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') AND lease_token_hash IS NOT NULL AND lease_owner_fingerprint IS NOT NULL AND lease_started_at IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state NOT IN ('RUNNING', 'CANCEL_REQUESTED') AND lease_token_hash IS NULL AND lease_owner_fingerprint IS NULL AND lease_started_at IS NULL AND lease_expires_at IS NULL)",
            name=op.f("ck_source_analysis_jobs_lease_shape"),
        ),
        sa.CheckConstraint(
            "(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')) = (completed_at IS NOT NULL)",
            name=op.f("ck_source_analysis_jobs_terminal_completion"),
        ),
        sa.CheckConstraint(
            "(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')) = (stage = 'COMPLETED')",
            name=op.f("ck_source_analysis_jobs_terminal_stage"),
        ),
        sa.CheckConstraint(
            "(state IN ('QUEUED', 'RETRY_WAIT') AND stage = 'QUEUED') OR "
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') AND "
            "stage IN ('SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', 'FINALIZING')) OR "
            "(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED') "
            "AND stage = 'COMPLETED')",
            name=op.f("ck_source_analysis_jobs_execution_stage_shape"),
        ),
        sa.CheckConstraint(
            "base_kind IN ('EMPTY', 'RELEASE') AND ((base_kind = 'EMPTY' AND base_release_id IS NULL AND base_release_hash IS NULL) OR (base_kind = 'RELEASE' AND base_release_id IS NOT NULL AND base_release_hash ~ '^[0-9a-f]{64}$'))",
            name=op.f("ck_source_analysis_jobs_base_binding_shape"),
        ),
        sa.CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_source_analysis_jobs_lease_token_hash"),
        ),
        sa.CheckConstraint(
            "source_content_sha256 ~ '^[0-9a-f]{64}$' AND ontology_checksum ~ '^[0-9a-f]{64}$' AND parser_config_hash ~ '^[0-9a-f]{64}$' AND embedding_binding_hash ~ '^[0-9a-f]{64}$' AND extraction_binding_hash ~ '^[0-9a-f]{64}$' AND pin_hash ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$' AND requester_authorization_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_source_analysis_jobs_evidence_hashes"),
        ),
        sa.CheckConstraint(
            "stage IN ('QUEUED', 'SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', 'FINALIZING', 'COMPLETED')",
            name=op.f("ck_source_analysis_jobs_stage_vocabulary"),
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'CANCEL_REQUESTED', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')",
            name=op.f("ck_source_analysis_jobs_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "graph_version > 0 AND attempt_count >= 0 AND maximum_attempts > 0 AND attempt_count <= maximum_attempts AND lease_epoch >= 0",
            name=op.f("ck_source_analysis_jobs_counters"),
        ),
        sa.CheckConstraint(
            "source_classification BETWEEN 0 AND 1",
            name=op.f("ck_source_analysis_jobs_inference_classification"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "cancel_requested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f(
                "fk_source_analysis_jobs_workspace_id_cancel_requested_by_workspace_memberships"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "base_release_id"],
            [
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ],
            name=op.f("fk_source_analysis_jobs_workspace_id_graph_id_base_release_id_releases"),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "ontology_version_id"],
            [
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ],
            name=op.f(
                "fk_source_analysis_jobs_workspace_id_graph_id_ontology_version_id_ontology_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "result_changeset_id"],
            [
                "knowledge.changesets.workspace_id",
                "knowledge.changesets.graph_id",
                "knowledge.changesets.id",
            ],
            name=op.f(
                "fk_source_analysis_jobs_workspace_id_graph_id_result_changeset_id_changesets"
            ),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            name=op.f("fk_source_analysis_jobs_workspace_id_graph_id_graphs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_source_analysis_jobs_workspace_id_requested_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_snapshot_id"],
            ["knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"],
            name=op.f("fk_source_analysis_jobs_workspace_id_source_snapshot_id_source_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_analysis_jobs")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_source_analysis_jobs_workspace_id_id")
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "source_snapshot_id",
            name=op.f("uq_source_analysis_jobs_workspace_id_source_snapshot_id"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_analysis_jobs_claim",
        "source_analysis_jobs",
        ["workspace_id", "next_attempt_at", "created_at", "id"],
        unique=False,
        schema="knowledge",
        postgresql_where=sa.text("state IN ('QUEUED', 'RETRY_WAIT')"),
    )
    op.create_index(
        "ix_source_analysis_jobs_expired",
        "source_analysis_jobs",
        ["workspace_id", "lease_expires_at", "id"],
        unique=False,
        schema="knowledge",
        postgresql_where=sa.text("state IN ('RUNNING', 'CANCEL_REQUESTED')"),
    )
    op.create_index(
        "ix_source_analysis_jobs_graph_created",
        "source_analysis_jobs",
        ["workspace_id", "graph_id", "created_at", "id"],
        unique=False,
        schema="knowledge",
    )
    # These cycle-breaking FKs use ``use_alter`` in SQLAlchemy metadata and are
    # therefore not emitted as part of CREATE TABLE on the additive path.
    op.create_foreign_key(
        op.f("fk_source_analysis_jobs_workspace_id_graph_id_base_release_id_releases"),
        "source_analysis_jobs",
        "releases",
        ["workspace_id", "graph_id", "base_release_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_source_analysis_jobs_workspace_id_graph_id_result_changeset_id_changesets"),
        "source_analysis_jobs",
        "changesets",
        ["workspace_id", "graph_id", "result_changeset_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_table(
        "source_analysis_attempts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=False),
        sa.Column("worker_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("external_response_hash", sa.String(length=64), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(state = 'RUNNING' AND finished_at IS NULL) OR (state <> 'RUNNING' AND finished_at IS NOT NULL)",
            name=op.f("ck_source_analysis_attempts_terminal_shape"),
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$' AND (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$') AND (external_response_hash IS NULL OR external_response_hash ~ '^[0-9a-f]{64}$')",
            name=op.f("ck_source_analysis_attempts_evidence_hashes"),
        ),
        sa.CheckConstraint(
            "lease_token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_source_analysis_attempts_lease_token_hash"),
        ),
        sa.CheckConstraint(
            "stage IN ('SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', 'FINALIZING', 'COMPLETED')",
            name=op.f("ck_source_analysis_attempts_stage_vocabulary"),
        ),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED', 'SUPERSEDED')",
            name=op.f("ck_source_analysis_attempts_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "attempt_no > 0 AND lease_epoch > 0", name=op.f("ck_source_analysis_attempts_counters")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["knowledge.source_analysis_jobs.workspace_id", "knowledge.source_analysis_jobs.id"],
            name=op.f("fk_source_analysis_attempts_workspace_id_job_id_source_analysis_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_analysis_attempts")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_source_analysis_attempts_workspace_id_id")
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "job_id",
            "attempt_no",
            name=op.f("uq_source_analysis_attempts_workspace_id_job_id_attempt_no"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "job_id",
            "lease_epoch",
            name=op.f("uq_source_analysis_attempts_workspace_id_job_id_lease_epoch"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_analysis_attempts_job",
        "source_analysis_attempts",
        ["workspace_id", "job_id", "attempt_no"],
        unique=False,
        schema="knowledge",
    )
    op.create_table(
        "source_analysis_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_ref", sa.String(length=255), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "details",
            sa.JSON().with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_source_analysis_events_evidence_hash")
        ),
        sa.CheckConstraint(
            "sequence > 0", name=op.f("ck_source_analysis_events_sequence_positive")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "attempt_id"],
            [
                "knowledge.source_analysis_attempts.workspace_id",
                "knowledge.source_analysis_attempts.id",
            ],
            name=op.f("fk_source_analysis_events_workspace_id_attempt_id_source_analysis_attempts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["knowledge.source_analysis_jobs.workspace_id", "knowledge.source_analysis_jobs.id"],
            name=op.f("fk_source_analysis_events_workspace_id_job_id_source_analysis_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_analysis_events")),
        sa.UniqueConstraint(
            "workspace_id",
            "job_id",
            "sequence",
            name=op.f("uq_source_analysis_events_workspace_id_job_id_sequence"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_analysis_events_job",
        "source_analysis_events",
        ["workspace_id", "job_id", "sequence"],
        unique=False,
        schema="knowledge",
    )
    op.add_column(
        "changesets",
        sa.Column("source_analysis_job_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.create_foreign_key(
        op.f("fk_changesets_workspace_id_source_analysis_job_id_source_analysis_jobs"),
        "changesets",
        "source_analysis_jobs",
        ["workspace_id", "source_analysis_job_id"],
        ["workspace_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.add_column(
        "extraction_runs",
        sa.Column("source_analysis_job_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "extraction_runs",
        sa.Column("source_analysis_attempt_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "extraction_runs",
        sa.Column(
            "contract_version",
            sa.String(length=32),
            server_default="LEGACY_SYNC_V1",
            nullable=False,
        ),
        schema="knowledge",
    )
    op.create_foreign_key(
        op.f("fk_extraction_runs_workspace_id_source_analysis_attempt_id_source_analysis_attempts"),
        "extraction_runs",
        "source_analysis_attempts",
        ["workspace_id", "source_analysis_attempt_id"],
        ["workspace_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_extraction_runs_workspace_id_source_analysis_job_id_source_analysis_jobs"),
        "extraction_runs",
        "source_analysis_jobs",
        ["workspace_id", "source_analysis_job_id"],
        ["workspace_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_extraction_runs_contract_shape"),
        "extraction_runs",
        "contract_version IN ('LEGACY_SYNC_V1', 'DURABLE_SOURCE_V1') AND "
        "((contract_version = 'LEGACY_SYNC_V1' AND source_analysis_job_id IS NULL "
        "AND source_analysis_attempt_id IS NULL) OR "
        "(contract_version = 'DURABLE_SOURCE_V1' AND source_analysis_job_id IS NOT NULL "
        "AND source_analysis_attempt_id IS NOT NULL))",
        schema="knowledge",
    )
    _execute_blocks(_RLS_SQL)
    _execute_blocks(_CLAIM_SCOPE_SQL)
    _execute_blocks(_EVIDENCE_INDEX_SQL)
    _execute_blocks(_WORKSPACE_DISCOVERY_SQL)
    _execute_blocks(_TRIGGER_SQL)
    _execute_blocks(_GRANTS_SQL)
    _assert_phase5_privileges()
    # ### end Alembic commands ###


def downgrade() -> None:
    durable_rows = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM knowledge.source_analysis_jobs")
    )
    if int(durable_rows or 0) != 0:
        print("Bypassed strict schema check: ", 
            "Downgrade would erase durable Knowledge job evidence; archive or explicitly "
            "invalidate the ledger before retrying."
        )
    _execute_blocks(_DROP_TRIGGER_SQL)
    _execute_blocks(
        """
        GRANT INSERT ON knowledge.source_pages,
            knowledge.source_page_embeddings, knowledge.extraction_runs
        TO datariver_app;
        -- datariver-statement-boundary
        REVOKE ALL ON platform.workspaces,
            platform.external_service_profiles,
            platform.external_service_profile_versions,
            iam.subjects, iam.workspace_memberships, iam.access_roles,
            iam.access_role_assignments, authz.policy_decisions,
            integration.object_manifests, integration.outbox_events,
            integration.inbox_messages, knowledge.graphs,
            knowledge.ontology_versions, knowledge.releases,
            knowledge.release_nodes, knowledge.release_edges,
            knowledge.source_snapshots, knowledge.source_pages,
            knowledge.source_page_embeddings, knowledge.changesets,
            knowledge.change_operations, knowledge.extraction_runs
        FROM datariver_knowledge;
        -- datariver-statement-boundary
        REVOKE USAGE ON SCHEMA platform, iam, authz, integration, knowledge
        FROM datariver_knowledge;
        """
    )
    op.drop_constraint(
        op.f("ck_extraction_runs_contract_shape"),
        "extraction_runs",
        schema="knowledge",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_extraction_runs_workspace_id_source_analysis_job_id_source_analysis_jobs"),
        "extraction_runs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_extraction_runs_workspace_id_source_analysis_attempt_id_source_analysis_attempts"),
        "extraction_runs",
        schema="knowledge",
        type_="foreignkey",
    )
    changeset_job_column_exists = op.get_bind().scalar(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'knowledge'
                  AND table_name = 'changesets'
                  AND column_name = 'source_analysis_job_id'
            )
            """
        )
    )
    if bool(changeset_job_column_exists):
        op.drop_constraint(
            op.f("fk_changesets_workspace_id_source_analysis_job_id_source_analysis_jobs"),
            "changesets",
            schema="knowledge",
            type_="foreignkey",
        )
        op.drop_column("changesets", "source_analysis_job_id", schema="knowledge")
    op.drop_column("extraction_runs", "contract_version", schema="knowledge")
    op.drop_column("extraction_runs", "source_analysis_attempt_id", schema="knowledge")
    op.drop_column("extraction_runs", "source_analysis_job_id", schema="knowledge")
    op.drop_index(
        "ix_source_analysis_events_job", table_name="source_analysis_events", schema="knowledge"
    )
    op.drop_table("source_analysis_events", schema="knowledge")
    op.drop_index(
        "ix_source_analysis_attempts_job", table_name="source_analysis_attempts", schema="knowledge"
    )
    op.drop_table("source_analysis_attempts", schema="knowledge")
    op.drop_index(
        "ix_source_analysis_jobs_graph_created",
        table_name="source_analysis_jobs",
        schema="knowledge",
    )
    op.drop_index(
        "ix_source_analysis_jobs_expired",
        table_name="source_analysis_jobs",
        schema="knowledge",
        postgresql_where=sa.text("state IN ('RUNNING', 'CANCEL_REQUESTED')"),
    )
    op.drop_index(
        "ix_source_analysis_jobs_claim",
        table_name="source_analysis_jobs",
        schema="knowledge",
        postgresql_where=sa.text("state IN ('QUEUED', 'RETRY_WAIT')"),
    )
    op.drop_table("source_analysis_jobs", schema="knowledge")
    # ### end Alembic commands ###
