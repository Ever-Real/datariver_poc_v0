from __future__ import annotations

TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SIGNATURES = (
    "knowledge.request_tbox_proposal_job_v1("
    "uuid,uuid,uuid,uuid,text,text,integer,text,text,text,jsonb,text,text,jsonb,text,text,integer,text"
    ")",
    "knowledge.get_owned_tbox_proposal_job_v1(uuid,uuid,uuid,uuid)",
    "knowledge.list_owned_tbox_proposal_jobs_v1(uuid,uuid,uuid,integer,text)",
    "knowledge.cancel_tbox_proposal_job_v1(uuid,uuid,uuid,uuid,integer,text,text,text)",
    "knowledge.retry_tbox_proposal_job_v1(uuid,uuid,uuid,uuid,integer,text,text)",
)

TBOX_PROPOSAL_JOB_WORKER_FUNCTION_SIGNATURES = (
    "knowledge.claim_tbox_proposal_job_v1(uuid,text,text,integer)",
    "knowledge.renew_tbox_proposal_job_v1(uuid,uuid,uuid,bigint,text,text,integer,text,integer)",
    "knowledge.ensure_tbox_proposal_job_current_v1(uuid,uuid,uuid,bigint,text,text,jsonb)",
    "knowledge.complete_tbox_proposal_job_v1("
    "uuid,uuid,uuid,bigint,text,text,text,jsonb,jsonb,text,jsonb,jsonb,text"
    ")",
    "knowledge.fail_tbox_proposal_job_v1("
    "uuid,uuid,uuid,bigint,text,text,text,text,boolean,boolean"
    ")",
)

TBOX_PROPOSAL_JOB_INTERNAL_FUNCTION_SIGNATURES = (
    "knowledge.tbox_proposal_canonical_json_v1(jsonb)",
    "knowledge.tbox_proposal_json_hash_v1(jsonb)",
    "knowledge.current_tbox_proposal_authorization_hash_v1(uuid,uuid)",
    "knowledge.current_tbox_proposal_human_can_v1(uuid,uuid,integer,uuid)",
    "knowledge.current_tbox_proposal_service_can_v1(uuid,integer,uuid)",
    "knowledge.tbox_proposal_job_document_v1(uuid,uuid)",
    "knowledge.tbox_proposal_job_pins_v1(uuid,uuid)",
    "knowledge.tbox_proposal_current_elements_v1(uuid,uuid)",
    "knowledge.tbox_proposal_job_drift_v1(uuid,uuid,jsonb)",
    "knowledge.tbox_proposal_lease_matches_v1(uuid,uuid,uuid,bigint,text,text)",
    "knowledge.append_tbox_proposal_event_v1(uuid,uuid,uuid,text,text,text,text,jsonb)",
    "knowledge.emit_tbox_proposal_outbox_v1(uuid,uuid,text,integer)",
    "knowledge.reject_tbox_proposal_evidence_mutation_v1()",
    "knowledge.enforce_tbox_proposal_job_pin_immutability_v1()",
    "knowledge.enforce_tbox_proposal_attempt_immutability_v1()",
    "knowledge.enforce_tbox_proposal_content_safety_v1()",
)


TBOX_PROPOSAL_JOB_SUPPORT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.tbox_proposal_canonical_json_v1(p_value jsonb)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    value_kind text := jsonb_typeof(p_value);
    rendered text;
BEGIN
    IF value_kind = 'object' THEN
        SELECT '{' || COALESCE(string_agg(
            to_jsonb(entry.key)::text || ':' ||
                knowledge.tbox_proposal_canonical_json_v1(entry.value),
            ',' ORDER BY entry.key
        ), '') || '}'
        INTO rendered
        FROM jsonb_each(p_value) AS entry;
        RETURN rendered;
    ELSIF value_kind = 'array' THEN
        SELECT '[' || COALESCE(string_agg(
            knowledge.tbox_proposal_canonical_json_v1(item.value),
            ',' ORDER BY item.ordinality
        ), '') || ']'
        INTO rendered
        FROM jsonb_array_elements(p_value) WITH ORDINALITY AS item(value, ordinality);
        RETURN rendered;
    END IF;
    RETURN p_value::text;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.tbox_proposal_json_hash_v1(p_value jsonb)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, knowledge
AS $$
    SELECT encode(sha256(convert_to(
        knowledge.tbox_proposal_canonical_json_v1(p_value), 'UTF8'
    )), 'hex')
$$;

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

CREATE OR REPLACE FUNCTION knowledge.current_tbox_proposal_human_can_v1(
    p_workspace_id uuid,
    p_actor_id uuid,
    p_classification integer,
    p_domain_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam
AS $$
    SELECT session_user = 'datariver_app'
       AND p_workspace_id IS NOT DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       AND p_actor_id IS NOT DISTINCT FROM
           NULLIF(current_setting('app.subject_id', true), '')::uuid
       AND EXISTS (
           SELECT 1
           FROM platform.workspaces AS workspace
           JOIN iam.workspace_memberships AS membership
             ON membership.workspace_id = workspace.id
           JOIN iam.subjects AS subject ON subject.id = membership.subject_id
           WHERE workspace.id = p_workspace_id
             AND workspace.status = 'ACTIVE'
             AND membership.subject_id = p_actor_id
             AND subject.active IS TRUE
             AND membership.active IS TRUE
             AND (
                 membership.access_expires_at IS NULL
                 OR membership.access_expires_at > transaction_timestamp()
             )
             AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
             AND membership.clearance >= p_classification
             AND COALESCE(
                 membership.attributes -> 'allowed_actions', '[]'::jsonb
             ) ? 'kg.edit'
             AND NOT (
                 COALESCE(
                     membership.attributes -> 'denied_actions', '[]'::jsonb
                 ) ? 'kg.edit'
             )
             AND (
                 p_classification = 0
                 OR p_domain_id IS NULL
                 OR COALESCE(
                     membership.attributes -> 'allowed_domain_ids', '[]'::jsonb
                 ) ? p_domain_id::text
             )
       )
$$;

CREATE OR REPLACE FUNCTION knowledge.current_tbox_proposal_service_can_v1(
    p_workspace_id uuid,
    p_classification integer,
    p_domain_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam
AS $$
    SELECT session_user = 'datariver_knowledge_proposal'
       AND p_workspace_id IS NOT DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       AND EXISTS (
           SELECT 1
           FROM platform.workspaces AS workspace
           JOIN iam.workspace_memberships AS membership
             ON membership.workspace_id = workspace.id
           JOIN iam.subjects AS subject ON subject.id = membership.subject_id
           WHERE workspace.id = p_workspace_id
             AND workspace.status = 'ACTIVE'
             AND membership.subject_id =
                 NULLIF(current_setting('app.subject_id', true), '')::uuid
             AND subject.active IS TRUE
             AND membership.active IS TRUE
             AND membership.access_expires_at IS NULL
             AND membership.job_function = 'SERVICE_ACCOUNT'
             AND membership.clearance >= p_classification
             AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                 = '["service-accounts","knowledge-proposal-workers"]'::jsonb
             AND COALESCE(
                 membership.attributes -> 'allowed_actions', '[]'::jsonb
             ) = '["kg.proposal.execute"]'::jsonb
             AND COALESCE(
                 membership.attributes -> 'denied_actions', '[]'::jsonb
             ) = '[]'::jsonb
             AND COALESCE(
                 membership.attributes -> 'allowed_system_ids', '[]'::jsonb
             ) = '[]'::jsonb
       )
$$;

CREATE OR REPLACE FUNCTION knowledge.tbox_proposal_job_document_v1(
    p_workspace_id uuid,
    p_job_id uuid
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
    SELECT jsonb_build_object(
        'job_id', job.id::text,
        'workspace_id', job.workspace_id::text,
        'draft_id', job.draft_id::text,
        'requested_by', job.requested_by::text,
        'input_kind', job.input_kind,
        'mode', job.mode,
        'target_block_id', CASE WHEN job.target_block_id IS NULL THEN NULL
            ELSE to_jsonb(job.target_block_id::text) END,
        'state', job.state,
        'stage', job.stage,
        'progress_percent', job.progress_percent,
        'attempt_count', job.attempt_count,
        'maximum_attempts', job.maximum_attempts,
        'next_attempt_at', job.next_attempt_at,
        'last_failure_code', job.last_failure_code,
        'version', job.version,
        'created_at', job.created_at,
        'updated_at', job.updated_at,
        'completed_at', job.completed_at,
        'result', CASE WHEN job.result_proposal_id IS NULL THEN NULL ELSE
            jsonb_build_object(
                'proposal_id', job.result_proposal_id::text,
                'evidence_hash', job.result_evidence_hash
            ) END,
        'supersedes_job_id', CASE WHEN job.supersedes_job_id IS NULL THEN NULL
            ELSE to_jsonb(job.supersedes_job_id::text) END
    )
    FROM knowledge.tbox_proposal_jobs AS job
    WHERE job.workspace_id = p_workspace_id AND job.id = p_job_id
$$;

CREATE OR REPLACE FUNCTION knowledge.tbox_proposal_job_pins_v1(
    p_workspace_id uuid,
    p_job_id uuid
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
    SELECT jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_TBOX_PROPOSAL_JOB_PINS_V1',
        'workspace_id', job.workspace_id::text,
        'draft_id', job.draft_id::text,
        'requested_by', job.requested_by::text,
        'input_kind', job.input_kind,
        'mode', job.mode,
        'target_block_id', CASE WHEN job.target_block_id IS NULL THEN NULL
            ELSE to_jsonb(job.target_block_id::text) END,
        'base_draft_version', job.base_draft_version,
        'base_tbox_hash', job.base_tbox_hash,
        'source', CASE WHEN job.input_kind = 'DOCUMENT_SCHEMA' THEN
            jsonb_build_object(
                'kind', 'DOCUMENT_SCHEMA',
                'manifest_id', job.manifest_id::text,
                'manifest_version', job.manifest_version,
                'content_sha256', job.source_content_hash,
                'media_type', job.source_media_type,
                'size_bytes', job.source_size_bytes,
                'classification', job.source_classification,
                'content_profile', job.source_content_profile,
                'validation_evidence_hash', job.source_validation_evidence_hash,
                'filename', job.source_filename
            ) ELSE job.catalog_source_document END,
        'parser_configuration_hash', job.parser_config_hash,
        'schema_binding', job.schema_binding_document,
        'requester_authorization_hash', job.requester_authorization_hash,
        'prepared_at', job.prepared_at
    )
    FROM knowledge.tbox_proposal_jobs AS job
    WHERE job.workspace_id = p_workspace_id AND job.id = p_job_id
$$;

CREATE OR REPLACE FUNCTION knowledge.tbox_proposal_current_elements_v1(
    p_workspace_id uuid,
    p_draft_id uuid
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'stable_element_id', element.stable_element_id,
        'kind', element.kind,
        'canonical_name', element.canonical_name,
        'display_name', element.display_name,
        'parent_stable_element_id', CASE
            WHEN element.kind = 'CLASS' THEN class_detail.parent_stable_class_id
            WHEN element.kind = 'PROPERTY' THEN property_detail.owner_stable_class_id
            ELSE NULL END,
        'hierarchy_relation', CASE
            WHEN class_detail.parent_stable_class_id IS NULL THEN NULL
            ELSE class_detail.hierarchy_relation END,
        'source_stable_element_id', relationship_detail.source_stable_class_id,
        'target_stable_element_id', relationship_detail.target_stable_class_id,
        'data_type', property_detail.data_type,
        'nullable', property_detail.nullable,
        'definition', element.definition,
        'aliases', element.aliases,
        'unit', property_detail.unit,
        'vector_index_enabled', COALESCE(property_detail.vector_index_enabled, false),
        'metadata_reference_id', CASE
            WHEN element.kind = 'CLASS' THEN class_detail.metadata_reference_id
            WHEN element.kind = 'PROPERTY' THEN property_detail.metadata_reference_id
            ELSE relationship_detail.metadata_reference_id END,
        'metadata_reference_urn', CASE
            WHEN element.kind = 'CLASS' THEN class_detail.metadata_reference_urn
            WHEN element.kind = 'PROPERTY' THEN property_detail.metadata_reference_urn
            ELSE relationship_detail.metadata_reference_urn END,
        'layout_x', element.layout_x,
        'layout_y', element.layout_y
    ) ORDER BY element.ordinal, element.stable_element_id), '[]'::jsonb)
    FROM knowledge.tbox_draft_elements AS element
    LEFT JOIN knowledge.tbox_classes AS class_detail
      ON class_detail.workspace_id = element.workspace_id
     AND class_detail.draft_id = element.draft_id
     AND class_detail.stable_class_id = element.stable_element_id
    LEFT JOIN knowledge.tbox_properties AS property_detail
      ON property_detail.workspace_id = element.workspace_id
     AND property_detail.draft_id = element.draft_id
     AND property_detail.stable_property_id = element.stable_element_id
    LEFT JOIN knowledge.tbox_relationships AS relationship_detail
      ON relationship_detail.workspace_id = element.workspace_id
     AND relationship_detail.draft_id = element.draft_id
     AND relationship_detail.stable_relationship_id = element.stable_element_id
    WHERE element.workspace_id = p_workspace_id
      AND element.draft_id = p_draft_id
$$;
""".strip()


TBOX_PROPOSAL_JOB_GUARD_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.tbox_proposal_job_drift_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_schema_binding jsonb
)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam, catalog, integration, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
    manifest integration.object_manifests%ROWTYPE;
    asset catalog.assets_projection%ROWTYPE;
    current_authorization_hash text;
    current_validation_hash text;
BEGIN
    SELECT * INTO job
    FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id;
    IF job.id IS NULL THEN
        RETURN 'STALE_JOB';
    END IF;
    SELECT * INTO draft
    FROM knowledge.studio_drafts
    WHERE workspace_id = job.workspace_id AND id = job.draft_id;
    IF draft.id IS NULL OR draft.author_id <> job.requested_by
       OR draft.state <> 'DRAFT' OR draft.current_step <> 'TBOX'
       OR draft.version <> job.base_draft_version THEN
        RETURN 'STALE_DRAFT';
    END IF;
    IF job.target_block_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM knowledge.tbox_draft_blocks AS block
        WHERE block.workspace_id = job.workspace_id
          AND block.draft_id = job.draft_id
          AND block.id = job.target_block_id
    ) THEN
        RETURN 'STALE_TARGET_BLOCK';
    END IF;
    current_authorization_hash :=
        knowledge.current_tbox_proposal_authorization_hash_v1(
            job.workspace_id, job.requested_by
        );
    IF current_authorization_hash IS DISTINCT FROM job.requester_authorization_hash
       OR NOT EXISTS (
           SELECT 1
           FROM iam.workspace_memberships AS membership
           JOIN iam.subjects AS subject ON subject.id = membership.subject_id
           WHERE membership.workspace_id = job.workspace_id
             AND membership.subject_id = job.requested_by
             AND subject.active IS TRUE AND membership.active IS TRUE
             AND (
                 membership.access_expires_at IS NULL
                 OR membership.access_expires_at > transaction_timestamp()
             )
             AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
             AND membership.clearance >= draft.classification
             AND COALESCE(
                 membership.attributes -> 'allowed_actions', '[]'::jsonb
             ) ? 'kg.edit'
             AND NOT (
                 COALESCE(
                     membership.attributes -> 'denied_actions', '[]'::jsonb
                 ) ? 'kg.edit'
             )
             AND (
                 draft.classification = 0 OR draft.domain_ref_id IS NULL
                 OR COALESCE(
                     membership.attributes -> 'allowed_domain_ids', '[]'::jsonb
                 ) ? draft.domain_ref_id::text
             )
       ) THEN
        RETURN 'STALE_AUTHORIZATION';
    END IF;
    IF p_schema_binding IS NOT NULL AND (
        jsonb_typeof(p_schema_binding) <> 'object'
        OR octet_length(p_schema_binding::text) > 8192
        OR knowledge.tbox_proposal_json_hash_v1(p_schema_binding)
            <> job.schema_binding_hash
        OR p_schema_binding <> job.schema_binding_document
    ) THEN
        RETURN 'STALE_MODEL_BINDING';
    END IF;
    IF job.input_kind = 'DOCUMENT_SCHEMA' THEN
        SELECT * INTO manifest
        FROM integration.object_manifests
        WHERE workspace_id = job.workspace_id AND id = job.manifest_id;
        current_validation_hash := knowledge.tbox_proposal_json_hash_v1(
            jsonb_build_object(
                'contract', 'KNOWLEDGE_STUDIO_UPLOAD_VALIDATION_EVIDENCE_V1',
                'manifest_id', manifest.id::text,
                'manifest_version', manifest.version,
                'validation_summary', manifest.validation_summary
            )
        );
        IF manifest.id IS NULL OR manifest.state <> 'ACCEPTED'
           OR manifest.owner_id <> job.requested_by
           OR manifest.version <> job.manifest_version
           OR manifest.actual_sha256 IS DISTINCT FROM job.source_content_hash
           OR manifest.actual_mime IS DISTINCT FROM job.source_media_type
           OR manifest.actual_size_bytes IS DISTINCT FROM job.source_size_bytes
           OR manifest.classification IS DISTINCT FROM job.source_classification
           OR manifest.classification > draft.classification
           OR manifest.classification > 1
           OR manifest.content_profile <> 'KNOWLEDGE_STUDIO_DOCUMENT_V1'
           OR manifest.content_profile IS DISTINCT FROM job.source_content_profile
           OR manifest.display_name IS DISTINCT FROM job.source_filename
           OR current_validation_hash IS DISTINCT FROM
               job.source_validation_evidence_hash
           OR manifest.validation_summary ->> 'profile_configuration_hash'
               IS DISTINCT FROM job.parser_config_hash THEN
            RETURN 'STALE_SOURCE';
        END IF;
    ELSE
        SELECT * INTO asset
        FROM catalog.assets_projection
        WHERE workspace_id = job.workspace_id AND id = job.catalog_asset_id;
        IF asset.id IS NULL OR asset.deleted_at IS NOT NULL
           OR asset.lifecycle <> 'ACTIVE'
           OR asset.classification IS DISTINCT FROM job.source_classification
           OR asset.classification > draft.classification
           OR asset.classification > 1
           OR asset.source_version IS DISTINCT FROM
               job.catalog_source_document ->> 'projection_source_version'
           OR asset.name IS DISTINCT FROM job.catalog_source_document ->> 'name'
           OR asset.asset_type IS DISTINCT FROM
               job.catalog_source_document ->> 'asset_type'
           OR knowledge.tbox_proposal_json_hash_v1(job.catalog_source_document)
               <> job.catalog_source_hash THEN
            RETURN 'STALE_SOURCE';
        END IF;
    END IF;
    IF job.state = 'CANCEL_REQUESTED' THEN
        RETURN 'STALE_CANCEL_REQUESTED';
    END IF;
    RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.tbox_proposal_lease_matches_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM knowledge.tbox_proposal_jobs AS job
        JOIN knowledge.tbox_proposal_attempts AS attempt
          ON attempt.workspace_id = job.workspace_id
         AND attempt.job_id = job.id
         AND attempt.id = job.current_attempt_id
        WHERE job.workspace_id = p_workspace_id
          AND job.id = p_job_id
          AND job.current_attempt_id = p_attempt_id
          AND job.lease_epoch = p_lease_epoch
          AND job.lease_token_hash = encode(
              sha256(convert_to(p_lease_token, 'UTF8')), 'hex'
          )
          AND job.lease_owner_fingerprint = p_worker_fingerprint
          AND attempt.lease_epoch = p_lease_epoch
          AND attempt.lease_token_hash = job.lease_token_hash
          AND attempt.worker_fingerprint = p_worker_fingerprint
          AND attempt.state = 'RUNNING'
          AND attempt.finished_at IS NULL
    )
$$;

CREATE OR REPLACE FUNCTION knowledge.append_tbox_proposal_event_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_state text,
    p_stage text,
    p_actor_kind text,
    p_actor_ref text,
    p_details jsonb
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    next_sequence bigint;
    occurred timestamptz := transaction_timestamp();
    evidence_hash text;
BEGIN
    IF p_state NOT IN (
        'QUEUED','RUNNING','RETRY_WAIT','CANCEL_REQUESTED',
        'SUCCEEDED','FAILED','STALE','CANCELLED'
    ) OR p_stage NOT IN (
        'QUEUED','SOURCE_VALIDATION','PARSING','INFERENCE',
        'VALIDATING','FINALIZING','COMPLETED'
    ) OR p_actor_kind NOT IN ('HUMAN','SERVICE')
      OR char_length(COALESCE(p_actor_ref, '')) NOT BETWEEN 1 AND 300
      OR jsonb_typeof(p_details) <> 'object'
      OR octet_length(p_details::text) > 8192
      OR p_details::text ~*
          '"(bucket|object_key|excerpt|prompt|provider_body|content)"\\s*:'
    THEN
        RAISE EXCEPTION 'invalid T-Box Proposal transition evidence'
            USING ERRCODE = '55000';
    END IF;
    SELECT COALESCE(max(event.sequence), 0) + 1
    INTO next_sequence
    FROM knowledge.tbox_proposal_events AS event
    WHERE event.workspace_id = p_workspace_id AND event.job_id = p_job_id;
    evidence_hash := knowledge.tbox_proposal_json_hash_v1(jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_TBOX_PROPOSAL_JOB_EVENT_V1',
        'workspace_id', p_workspace_id::text,
        'job_id', p_job_id::text,
        'attempt_id', CASE WHEN p_attempt_id IS NULL THEN NULL
            ELSE to_jsonb(p_attempt_id::text) END,
        'sequence', next_sequence,
        'state', p_state,
        'stage', p_stage,
        'actor_kind', p_actor_kind,
        'actor_ref', p_actor_ref,
        'details', p_details,
        'occurred_at', occurred
    ));
    INSERT INTO knowledge.tbox_proposal_events (
        workspace_id, job_id, sequence, attempt_id, state, stage,
        actor_kind, actor_ref, reason_code, details_document,
        evidence_hash, occurred_at
    ) VALUES (
        p_workspace_id, p_job_id, next_sequence, p_attempt_id, p_state, p_stage,
        p_actor_kind, p_actor_ref, p_details ->> 'reason_code', p_details,
        evidence_hash, occurred
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.emit_tbox_proposal_outbox_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_state text,
    p_version integer
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, integration
AS $$
BEGIN
    INSERT INTO integration.outbox_events (
        id, workspace_id, aggregate_type, aggregate_id, event_type,
        schema_version, payload, created_at, published_at, dead_lettered_at,
        lease_until, attempts, last_error_code
    ) VALUES (
        gen_random_uuid(), p_workspace_id, 'knowledge_tbox_proposal_job',
        p_job_id, 'knowledge.tbox-proposal-job.' || lower(p_state) || '.v1',
        1, jsonb_build_object(
            'job_id', p_job_id::text,
            'state', p_state,
            'version', p_version
        ), transaction_timestamp(), NULL, NULL, NULL, 0, NULL
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.reject_tbox_proposal_evidence_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'T-Box Proposal evidence is append-only'
        USING ERRCODE = '55000';
END
$$;

CREATE OR REPLACE FUNCTION knowledge.enforce_tbox_proposal_job_pin_immutability_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF ROW(
        NEW.id, NEW.workspace_id, NEW.draft_id, NEW.target_block_id,
        NEW.requested_by, NEW.input_kind, NEW.mode, NEW.base_draft_version,
        NEW.base_tbox_hash, NEW.request_hash, NEW.requester_authorization_hash,
        NEW.parser_config_hash, NEW.schema_binding_document,
        NEW.schema_binding_hash, NEW.source_pin_hash, NEW.pin_hash,
        NEW.prepared_at, NEW.manifest_id, NEW.manifest_version,
        NEW.source_content_hash, NEW.source_media_type, NEW.source_size_bytes,
        NEW.source_classification, NEW.source_content_profile,
        NEW.source_validation_evidence_hash, NEW.source_filename,
        NEW.catalog_asset_id, NEW.catalog_source_document,
        NEW.catalog_source_hash, NEW.maximum_attempts,
        NEW.supersedes_job_id, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.id, OLD.workspace_id, OLD.draft_id, OLD.target_block_id,
        OLD.requested_by, OLD.input_kind, OLD.mode, OLD.base_draft_version,
        OLD.base_tbox_hash, OLD.request_hash, OLD.requester_authorization_hash,
        OLD.parser_config_hash, OLD.schema_binding_document,
        OLD.schema_binding_hash, OLD.source_pin_hash, OLD.pin_hash,
        OLD.prepared_at, OLD.manifest_id, OLD.manifest_version,
        OLD.source_content_hash, OLD.source_media_type, OLD.source_size_bytes,
        OLD.source_classification, OLD.source_content_profile,
        OLD.source_validation_evidence_hash, OLD.source_filename,
        OLD.catalog_asset_id, OLD.catalog_source_document,
        OLD.catalog_source_hash, OLD.maximum_attempts,
        OLD.supersedes_job_id, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'T-Box Proposal job pins are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.enforce_tbox_proposal_attempt_immutability_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF ROW(
        NEW.id, NEW.workspace_id, NEW.job_id, NEW.attempt_no,
        NEW.lease_epoch, NEW.lease_token_hash, NEW.worker_fingerprint,
        NEW.claimed_at
    ) IS DISTINCT FROM ROW(
        OLD.id, OLD.workspace_id, OLD.job_id, OLD.attempt_no,
        OLD.lease_epoch, OLD.lease_token_hash, OLD.worker_fingerprint,
        OLD.claimed_at
    ) THEN
        RAISE EXCEPTION 'T-Box Proposal attempt pins are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.enforce_tbox_proposal_content_safety_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF char_length(NEW.prompt) > 512
       OR NEW.prompt ~ '[\\x00-\\x1F\\x7F]'
       OR NOT (
           NEW.prompt = 'Governed Schema Assistant proposal'
           OR NEW.prompt = 'Governed Asset Release proposal'
           OR NEW.prompt LIKE 'Document schema proposal: %'
           OR NEW.prompt LIKE 'Catalog schema proposal: %'
       )
       OR (
           NEW.source_reference_document IS NOT NULL
           AND (
               jsonb_typeof(NEW.source_reference_document) <> 'object'
               OR octet_length(NEW.source_reference_document::text) > 65536
               OR NEW.source_reference_document::text ~*
                   '"(bucket|object_key|excerpt|prompt|provider_body|content)"\\s*:'
           )
       )
    THEN
        RAISE EXCEPTION 'T-Box Proposal content contains unsafe retained input'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
""".strip()


TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.request_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_draft_id uuid,
    p_requested_by uuid,
    p_target_block_id uuid,
    p_input_kind text,
    p_mode text,
    p_base_draft_version integer,
    p_base_tbox_hash text,
    p_request_hash text,
    p_requester_authorization_hash text,
    p_source_pin jsonb,
    p_source_pin_hash text,
    p_parser_configuration_hash text,
    p_schema_binding jsonb,
    p_schema_binding_hash text,
    p_pin_hash text,
    p_maximum_attempts integer,
    p_idempotency_key text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam, catalog, integration, knowledge
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    draft knowledge.studio_drafts%ROWTYPE;
    manifest integration.object_manifests%ROWTYPE;
    asset catalog.assets_projection%ROWTYPE;
    job_id uuid := gen_random_uuid();
    now_at timestamptz := transaction_timestamp();
    key_hash text := encode(sha256(convert_to(p_idempotency_key, 'UTF8')), 'hex');
    replay integration.idempotency_keys%ROWTYPE;
    source_manifest_id uuid;
    source_asset_id uuid;
    validation_hash text;
    result jsonb;
BEGIN
    IF session_user <> 'datariver_app'
       OR actor_id IS DISTINCT FROM p_requested_by
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_input_kind NOT IN ('DOCUMENT_SCHEMA','CATALOG_SCHEMA')
       OR p_mode NOT IN ('MERGE_INTO_CURRENT','APPEND_LAYER')
       OR (p_mode = 'MERGE_INTO_CURRENT') <> (p_target_block_id IS NOT NULL)
       OR p_base_draft_version < 1
       OR p_base_tbox_hash !~ '^[0-9a-f]{64}$'
       OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_requester_authorization_hash !~ '^[0-9a-f]{64}$'
       OR p_source_pin_hash !~ '^[0-9a-f]{64}$'
       OR p_parser_configuration_hash !~ '^[0-9a-f]{64}$'
       OR p_schema_binding_hash !~ '^[0-9a-f]{64}$'
       OR p_pin_hash !~ '^[0-9a-f]{64}$'
       OR p_maximum_attempts NOT BETWEEN 1 AND 20
       OR char_length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
       OR p_idempotency_key <> btrim(p_idempotency_key)
       OR jsonb_typeof(p_source_pin) <> 'object'
       OR octet_length(p_source_pin::text) > 65536
       OR jsonb_typeof(p_schema_binding) <> 'object'
       OR octet_length(p_schema_binding::text) > 8192
       OR knowledge.tbox_proposal_json_hash_v1(p_source_pin) <> p_source_pin_hash
       OR knowledge.tbox_proposal_json_hash_v1(p_schema_binding)
           <> p_schema_binding_hash
    THEN
        RAISE EXCEPTION 'invalid T-Box Proposal job request'
            USING ERRCODE = '55000';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_workspace_id::text || ':' || 'knowledge.tbox-proposal.request.v1' || ':' ||
            p_idempotency_key, 0
    ));
    SELECT * INTO replay
    FROM integration.idempotency_keys
    WHERE workspace_id = p_workspace_id
      AND operation = 'knowledge.tbox-proposal.request.v1'
      AND integration.idempotency_keys.key_hash = key_hash;
    IF replay.workspace_id IS NOT NULL THEN
        IF replay.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'T-Box Proposal idempotency key was reused'
                USING ERRCODE = '55000';
        END IF;
        RETURN knowledge.tbox_proposal_job_document_v1(
            p_workspace_id, (replay.result ->> 'job_id')::uuid
        );
    END IF;
    SELECT * INTO draft
    FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = p_draft_id
    FOR UPDATE;
    IF draft.id IS NULL OR draft.author_id <> actor_id
       OR draft.state <> 'DRAFT' OR draft.current_step <> 'TBOX'
       OR draft.version <> p_base_draft_version
       OR NOT knowledge.current_tbox_proposal_human_can_v1(
           p_workspace_id, actor_id, draft.classification, draft.domain_ref_id
       ) OR knowledge.current_tbox_proposal_authorization_hash_v1(
           p_workspace_id, actor_id
       ) IS DISTINCT FROM p_requester_authorization_hash
    THEN
        RAISE EXCEPTION 'T-Box Proposal requester or Draft pin is stale'
            USING ERRCODE = '42501';
    END IF;
    IF p_target_block_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM knowledge.tbox_draft_blocks AS block
        WHERE block.workspace_id = p_workspace_id
          AND block.draft_id = p_draft_id
          AND block.id = p_target_block_id
    ) THEN
        RAISE EXCEPTION 'T-Box Proposal target block is unavailable'
            USING ERRCODE = '55000';
    END IF;
    IF p_input_kind = 'DOCUMENT_SCHEMA' THEN
        IF (p_source_pin - ARRAY[
            'kind','manifest_id','manifest_version','content_sha256','media_type',
            'size_bytes','classification','content_profile',
            'validation_evidence_hash','filename'
        ]) <> '{}'::jsonb OR p_source_pin ->> 'kind' <> 'DOCUMENT_SCHEMA'
           OR COALESCE(p_source_pin ->> 'manifest_id', '') !~
               '^[0-9a-fA-F-]{36}$'
           OR COALESCE(p_source_pin ->> 'manifest_version', '') !~ '^[1-9][0-9]*$'
           OR p_source_pin ->> 'content_sha256' !~ '^[0-9a-f]{64}$'
           OR COALESCE(p_source_pin ->> 'size_bytes', '') !~ '^[1-9][0-9]*$'
           OR (p_source_pin ->> 'size_bytes')::bigint > 10485760
           OR COALESCE(p_source_pin ->> 'classification', '') NOT IN ('0','1')
           OR p_source_pin ->> 'content_profile'
               <> 'KNOWLEDGE_STUDIO_DOCUMENT_V1'
           OR p_source_pin ->> 'validation_evidence_hash' !~ '^[0-9a-f]{64}$'
           OR char_length(COALESCE(p_source_pin ->> 'filename', ''))
               NOT BETWEEN 1 AND 255
           OR p_source_pin ->> 'filename' ~ '[/\\]'
        THEN
            RAISE EXCEPTION 'invalid accepted-upload Proposal pin'
                USING ERRCODE = '55000';
        END IF;
        source_manifest_id := (p_source_pin ->> 'manifest_id')::uuid;
        SELECT * INTO manifest
        FROM integration.object_manifests
        WHERE workspace_id = p_workspace_id AND id = source_manifest_id
        FOR SHARE;
        validation_hash := knowledge.tbox_proposal_json_hash_v1(
            jsonb_build_object(
                'contract', 'KNOWLEDGE_STUDIO_UPLOAD_VALIDATION_EVIDENCE_V1',
                'manifest_id', manifest.id::text,
                'manifest_version', manifest.version,
                'validation_summary', manifest.validation_summary
            )
        );
        IF manifest.id IS NULL OR manifest.owner_id <> actor_id
           OR manifest.state <> 'ACCEPTED'
           OR manifest.version <> (p_source_pin ->> 'manifest_version')::integer
           OR manifest.actual_sha256 IS DISTINCT FROM
               p_source_pin ->> 'content_sha256'
           OR manifest.actual_mime IS DISTINCT FROM p_source_pin ->> 'media_type'
           OR manifest.actual_size_bytes IS DISTINCT FROM
               (p_source_pin ->> 'size_bytes')::bigint
           OR manifest.classification IS DISTINCT FROM
               (p_source_pin ->> 'classification')::integer
           OR manifest.classification > draft.classification
           OR manifest.classification > 1
           OR manifest.content_profile <> 'KNOWLEDGE_STUDIO_DOCUMENT_V1'
           OR manifest.display_name IS DISTINCT FROM p_source_pin ->> 'filename'
           OR validation_hash IS DISTINCT FROM
               p_source_pin ->> 'validation_evidence_hash'
           OR manifest.validation_summary ->> 'profile_configuration_hash'
               IS DISTINCT FROM p_parser_configuration_hash
        THEN
            RAISE EXCEPTION 'accepted-upload Proposal pin is stale'
                USING ERRCODE = '55000';
        END IF;
    ELSE
        IF (p_source_pin - ARRAY[
            'kind','asset_id','name','asset_type','classification','source_version',
            'projection_source_version','selected_field_paths','platform',
            'database_name','schema_name','domain','tags','glossary_terms'
        ]) <> '{}'::jsonb OR p_source_pin ->> 'kind' <> 'CATALOG_SCHEMA'
           OR COALESCE(p_source_pin ->> 'asset_id', '') !~
               '^[0-9a-fA-F-]{36}$'
           OR COALESCE(p_source_pin ->> 'classification', '') NOT IN ('0','1')
           OR jsonb_typeof(p_source_pin -> 'selected_field_paths') <> 'array'
           OR jsonb_array_length(p_source_pin -> 'selected_field_paths')
               NOT BETWEEN 1 AND 100
           OR octet_length(p_source_pin::text) > 65536
        THEN
            RAISE EXCEPTION 'invalid Catalog Proposal pin'
                USING ERRCODE = '55000';
        END IF;
        source_asset_id := (p_source_pin ->> 'asset_id')::uuid;
        SELECT * INTO asset
        FROM catalog.assets_projection
        WHERE workspace_id = p_workspace_id AND id = source_asset_id
        FOR SHARE;
        IF asset.id IS NULL OR asset.deleted_at IS NOT NULL
           OR asset.lifecycle <> 'ACTIVE'
           OR asset.classification <> (p_source_pin ->> 'classification')::integer
           OR asset.classification > draft.classification OR asset.classification > 1
           OR asset.source_version IS DISTINCT FROM
               p_source_pin ->> 'projection_source_version'
           OR asset.name IS DISTINCT FROM p_source_pin ->> 'name'
           OR asset.asset_type IS DISTINCT FROM p_source_pin ->> 'asset_type'
           OR EXISTS (
               SELECT 1
               FROM jsonb_array_elements_text(
                   p_source_pin -> 'selected_field_paths'
               ) AS selected(value)
               WHERE char_length(selected.value) NOT BETWEEN 1 AND 2000
                  OR NOT asset.column_names ? selected.value
           )
           OR (
               SELECT count(*) <> count(DISTINCT selected.value)
               FROM jsonb_array_elements_text(
                   p_source_pin -> 'selected_field_paths'
               ) AS selected(value)
           )
        THEN
            RAISE EXCEPTION 'Catalog Proposal pin is stale'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    INSERT INTO knowledge.tbox_proposal_jobs (
        id, workspace_id, draft_id, target_block_id, requested_by,
        input_kind, mode, base_draft_version, base_tbox_hash, request_hash,
        requester_authorization_hash, parser_config_hash,
        schema_binding_document, schema_binding_hash, source_pin_hash, pin_hash,
        prepared_at, manifest_id, manifest_version, source_content_hash,
        source_media_type, source_size_bytes, source_classification,
        source_content_profile, source_validation_evidence_hash, source_filename,
        catalog_asset_id, catalog_source_document, catalog_source_hash,
        state, stage, progress_percent, attempt_count, maximum_attempts,
        next_attempt_at, current_attempt_id, lease_epoch, lease_token_hash,
        lease_owner_fingerprint, lease_started_at, lease_expires_at,
        cancel_requested_by, cancel_requested_at, cancel_reason,
        result_proposal_id, result_evidence_hash, last_failure_code,
        completed_at, supersedes_job_id, created_at, updated_at, version
    ) VALUES (
        job_id, p_workspace_id, p_draft_id, p_target_block_id, actor_id,
        p_input_kind, p_mode, p_base_draft_version, p_base_tbox_hash,
        p_request_hash, p_requester_authorization_hash,
        p_parser_configuration_hash, p_schema_binding, p_schema_binding_hash,
        p_source_pin_hash, p_pin_hash, now_at,
        source_manifest_id,
        CASE WHEN p_input_kind = 'DOCUMENT_SCHEMA'
            THEN (p_source_pin ->> 'manifest_version')::integer ELSE NULL END,
        CASE WHEN p_input_kind = 'DOCUMENT_SCHEMA'
            THEN p_source_pin ->> 'content_sha256' ELSE NULL END,
        CASE WHEN p_input_kind = 'DOCUMENT_SCHEMA'
            THEN p_source_pin ->> 'media_type' ELSE NULL END,
        CASE WHEN p_input_kind = 'DOCUMENT_SCHEMA'
            THEN (p_source_pin ->> 'size_bytes')::integer ELSE NULL END,
        (p_source_pin ->> 'classification')::integer,
        CASE WHEN p_input_kind = 'DOCUMENT_SCHEMA'
            THEN p_source_pin ->> 'content_profile' ELSE NULL END,
        CASE WHEN p_input_kind = 'DOCUMENT_SCHEMA'
            THEN p_source_pin ->> 'validation_evidence_hash' ELSE NULL END,
        CASE WHEN p_input_kind = 'DOCUMENT_SCHEMA'
            THEN p_source_pin ->> 'filename' ELSE NULL END,
        source_asset_id,
        CASE WHEN p_input_kind = 'CATALOG_SCHEMA' THEN p_source_pin ELSE NULL END,
        CASE WHEN p_input_kind = 'CATALOG_SCHEMA' THEN p_source_pin_hash ELSE NULL END,
        'QUEUED', 'QUEUED', 0, 0, p_maximum_attempts,
        now_at, NULL, 0, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        now_at, now_at, 1
    );
    PERFORM knowledge.append_tbox_proposal_event_v1(
        p_workspace_id, job_id, NULL, 'QUEUED', 'QUEUED',
        'HUMAN', actor_id::text,
        jsonb_build_object('reason_code', 'REQUESTED')
    );
    PERFORM knowledge.emit_tbox_proposal_outbox_v1(
        p_workspace_id, job_id, 'QUEUED', 1
    );
    result := knowledge.tbox_proposal_job_document_v1(p_workspace_id, job_id);
    INSERT INTO integration.idempotency_keys (
        workspace_id, operation, key_hash, request_hash, result,
        created_at, expires_at
    ) VALUES (
        p_workspace_id, 'knowledge.tbox-proposal.request.v1', key_hash,
        p_request_hash, jsonb_build_object('job_id', job_id::text),
        now_at, now_at + interval '24 hours'
    );
    RETURN result;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.get_owned_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_draft_id uuid,
    p_job_id uuid,
    p_actor_id uuid
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_actor_id IS DISTINCT FROM
           NULLIF(current_setting('app.subject_id', true), '')::uuid
    THEN
        RAISE EXCEPTION 'T-Box Proposal job read is not permitted'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO job FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND draft_id = p_draft_id
      AND id = p_job_id AND requested_by = p_actor_id;
    IF job.id IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = job.workspace_id AND id = job.draft_id;
    IF draft.id IS NULL OR draft.author_id <> p_actor_id
       OR NOT knowledge.current_tbox_proposal_human_can_v1(
           p_workspace_id, p_actor_id, draft.classification, draft.domain_ref_id
       ) THEN
        RAISE EXCEPTION 'T-Box Proposal job read is not permitted'
            USING ERRCODE = '42501';
    END IF;
    RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, p_job_id);
END
$$;

CREATE OR REPLACE FUNCTION knowledge.list_owned_tbox_proposal_jobs_v1(
    p_workspace_id uuid,
    p_draft_id uuid,
    p_actor_id uuid,
    p_limit integer,
    p_cursor text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    draft knowledge.studio_drafts%ROWTYPE;
    cursor_id uuid;
    cursor_created_at timestamptz;
    items jsonb;
    next_cursor text;
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_actor_id IS DISTINCT FROM
           NULLIF(current_setting('app.subject_id', true), '')::uuid
       OR p_limit NOT BETWEEN 1 AND 100
       OR (p_cursor IS NOT NULL AND p_cursor !~ '^[0-9a-fA-F-]{36}$')
    THEN
        RAISE EXCEPTION 'T-Box Proposal job list is not permitted'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = p_draft_id;
    IF draft.id IS NULL OR draft.author_id <> p_actor_id
       OR NOT knowledge.current_tbox_proposal_human_can_v1(
           p_workspace_id, p_actor_id, draft.classification, draft.domain_ref_id
       ) THEN
        RAISE EXCEPTION 'T-Box Proposal job list is not permitted'
            USING ERRCODE = '42501';
    END IF;
    IF p_cursor IS NOT NULL THEN
        cursor_id := p_cursor::uuid;
        SELECT created_at INTO cursor_created_at
        FROM knowledge.tbox_proposal_jobs
        WHERE workspace_id = p_workspace_id AND draft_id = p_draft_id
          AND requested_by = p_actor_id AND id = cursor_id;
        IF cursor_created_at IS NULL THEN
            RAISE EXCEPTION 'invalid T-Box Proposal job cursor'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    WITH page AS (
        SELECT job.id, job.created_at,
               row_number() OVER (ORDER BY job.created_at DESC, job.id DESC) AS position
        FROM knowledge.tbox_proposal_jobs AS job
        WHERE job.workspace_id = p_workspace_id
          AND job.draft_id = p_draft_id
          AND job.requested_by = p_actor_id
          AND (
              cursor_created_at IS NULL
              OR (job.created_at, job.id) < (cursor_created_at, cursor_id)
          )
        ORDER BY job.created_at DESC, job.id DESC
        LIMIT p_limit + 1
    )
    SELECT COALESCE(jsonb_agg(
               knowledge.tbox_proposal_job_document_v1(p_workspace_id, page.id)
               ORDER BY page.position
           ) FILTER (WHERE page.position <= p_limit), '[]'::jsonb),
           max(CASE WHEN page.position = p_limit + 1 THEN (
               SELECT prior.id::text FROM page AS prior
               WHERE prior.position = p_limit
           ) END)
    INTO items, next_cursor
    FROM page;
    RETURN jsonb_build_object('items', items, 'next_cursor', next_cursor);
END
$$;
""".strip()


TBOX_PROPOSAL_JOB_OWNER_TRANSITION_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.cancel_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_draft_id uuid,
    p_job_id uuid,
    p_actor_id uuid,
    p_expected_version integer,
    p_reason text,
    p_request_hash text,
    p_idempotency_key text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, integration, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
    now_at timestamptz := transaction_timestamp();
    operation_name text := 'knowledge.tbox-proposal.cancel:' || p_job_id::text;
    key_hash text := encode(sha256(convert_to(p_idempotency_key, 'UTF8')), 'hex');
    replay integration.idempotency_keys%ROWTYPE;
    target_state text;
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_actor_id IS DISTINCT FROM
           NULLIF(current_setting('app.subject_id', true), '')::uuid
       OR p_expected_version < 1
       OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR char_length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
       OR p_idempotency_key <> btrim(p_idempotency_key)
       OR char_length(COALESCE(p_reason, '')) NOT BETWEEN 1 AND 1000
       OR p_reason <> btrim(p_reason) OR p_reason ~ '[\\x00-\\x1F\\x7F]'
    THEN
        RAISE EXCEPTION 'invalid T-Box Proposal cancellation'
            USING ERRCODE = '55000';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_workspace_id::text || ':' || operation_name || ':' || p_idempotency_key, 0
    ));
    SELECT * INTO replay FROM integration.idempotency_keys
    WHERE workspace_id = p_workspace_id AND operation = operation_name
      AND integration.idempotency_keys.key_hash = key_hash;
    IF replay.workspace_id IS NOT NULL THEN
        IF replay.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'T-Box Proposal cancellation key was reused'
                USING ERRCODE = '55000';
        END IF;
        RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, p_job_id);
    END IF;
    SELECT * INTO job FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND draft_id = p_draft_id
      AND id = p_job_id AND requested_by = p_actor_id
    FOR UPDATE;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = p_draft_id;
    IF job.id IS NULL OR draft.id IS NULL OR draft.author_id <> p_actor_id
       OR job.version <> p_expected_version
       OR NOT knowledge.current_tbox_proposal_human_can_v1(
           p_workspace_id, p_actor_id, draft.classification, draft.domain_ref_id
       ) OR job.state NOT IN ('QUEUED','RETRY_WAIT','RUNNING')
    THEN
        RAISE EXCEPTION 'T-Box Proposal cancellation changed concurrently'
            USING ERRCODE = '55000';
    END IF;
    target_state := CASE WHEN job.state = 'RUNNING'
        THEN 'CANCEL_REQUESTED' ELSE 'CANCELLED' END;
    UPDATE knowledge.tbox_proposal_jobs
    SET state = target_state,
        stage = CASE WHEN target_state = 'CANCELLED' THEN 'COMPLETED' ELSE stage END,
        cancel_requested_by = p_actor_id,
        cancel_requested_at = now_at,
        cancel_reason = p_reason,
        completed_at = CASE WHEN target_state = 'CANCELLED' THEN now_at ELSE NULL END,
        updated_at = now_at,
        version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    RETURNING * INTO job;
    PERFORM knowledge.append_tbox_proposal_event_v1(
        p_workspace_id, p_job_id, job.current_attempt_id,
        target_state, job.stage, 'HUMAN', p_actor_id::text,
        jsonb_build_object(
            'reason_code', 'CANCEL_REQUESTED',
            'reason_hash', encode(sha256(convert_to(p_reason, 'UTF8')), 'hex')
        )
    );
    PERFORM knowledge.emit_tbox_proposal_outbox_v1(
        p_workspace_id, p_job_id, target_state, job.version
    );
    INSERT INTO integration.idempotency_keys (
        workspace_id, operation, key_hash, request_hash, result,
        created_at, expires_at
    ) VALUES (
        p_workspace_id, operation_name, key_hash, p_request_hash,
        jsonb_build_object('job_id', p_job_id::text),
        now_at, now_at + interval '24 hours'
    );
    RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, p_job_id);
END
$$;

CREATE OR REPLACE FUNCTION knowledge.retry_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_draft_id uuid,
    p_job_id uuid,
    p_actor_id uuid,
    p_expected_version integer,
    p_request_hash text,
    p_idempotency_key text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, integration, knowledge
AS $$
DECLARE
    prior_job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
    successor_id uuid := gen_random_uuid();
    now_at timestamptz := transaction_timestamp();
    operation_name text := 'knowledge.tbox-proposal.retry:' || p_job_id::text;
    key_hash text := encode(sha256(convert_to(p_idempotency_key, 'UTF8')), 'hex');
    replay integration.idempotency_keys%ROWTYPE;
    drift_code text;
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_actor_id IS DISTINCT FROM
           NULLIF(current_setting('app.subject_id', true), '')::uuid
       OR p_expected_version < 1 OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR char_length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
       OR p_idempotency_key <> btrim(p_idempotency_key)
    THEN
        RAISE EXCEPTION 'invalid T-Box Proposal retry'
            USING ERRCODE = '55000';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_workspace_id::text || ':' || operation_name || ':' || p_idempotency_key, 0
    ));
    SELECT * INTO replay FROM integration.idempotency_keys
    WHERE workspace_id = p_workspace_id AND operation = operation_name
      AND integration.idempotency_keys.key_hash = key_hash;
    IF replay.workspace_id IS NOT NULL THEN
        IF replay.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'T-Box Proposal retry key was reused'
                USING ERRCODE = '55000';
        END IF;
        RETURN knowledge.tbox_proposal_job_document_v1(
            p_workspace_id, (replay.result ->> 'job_id')::uuid
        );
    END IF;
    SELECT * INTO prior_job FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND draft_id = p_draft_id
      AND id = p_job_id AND requested_by = p_actor_id
    FOR UPDATE;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = p_draft_id;
    IF prior_job.id IS NULL OR draft.id IS NULL OR draft.author_id <> p_actor_id
       OR prior_job.version <> p_expected_version
       OR prior_job.state NOT IN ('FAILED','STALE','CANCELLED')
       OR NOT knowledge.current_tbox_proposal_human_can_v1(
           p_workspace_id, p_actor_id, draft.classification, draft.domain_ref_id
       ) OR EXISTS (
           SELECT 1 FROM knowledge.tbox_proposal_jobs AS successor
           WHERE successor.workspace_id = p_workspace_id
             AND successor.supersedes_job_id = p_job_id
       )
    THEN
        RAISE EXCEPTION 'T-Box Proposal retry changed concurrently'
            USING ERRCODE = '55000';
    END IF;
    drift_code := knowledge.tbox_proposal_job_drift_v1(
        p_workspace_id, p_job_id, prior_job.schema_binding_document
    );
    IF drift_code IS NOT NULL AND drift_code <> 'STALE_CANCEL_REQUESTED' THEN
        RAISE EXCEPTION 'T-Box Proposal retry pins are stale: %', drift_code
            USING ERRCODE = '55000';
    END IF;
    INSERT INTO knowledge.tbox_proposal_jobs (
        id, workspace_id, draft_id, target_block_id, requested_by,
        input_kind, mode, base_draft_version, base_tbox_hash, request_hash,
        requester_authorization_hash, parser_config_hash,
        schema_binding_document, schema_binding_hash, source_pin_hash, pin_hash,
        prepared_at, manifest_id, manifest_version, source_content_hash,
        source_media_type, source_size_bytes, source_classification,
        source_content_profile, source_validation_evidence_hash, source_filename,
        catalog_asset_id, catalog_source_document, catalog_source_hash,
        state, stage, progress_percent, attempt_count, maximum_attempts,
        next_attempt_at, current_attempt_id, lease_epoch, lease_token_hash,
        lease_owner_fingerprint, lease_started_at, lease_expires_at,
        cancel_requested_by, cancel_requested_at, cancel_reason,
        result_proposal_id, result_evidence_hash, last_failure_code,
        completed_at, supersedes_job_id, created_at, updated_at, version
    ) SELECT
        successor_id, workspace_id, draft_id, target_block_id, requested_by,
        input_kind, mode, base_draft_version, base_tbox_hash, p_request_hash,
        requester_authorization_hash, parser_config_hash,
        schema_binding_document, schema_binding_hash, source_pin_hash, pin_hash,
        prepared_at, manifest_id, manifest_version, source_content_hash,
        source_media_type, source_size_bytes, source_classification,
        source_content_profile, source_validation_evidence_hash, source_filename,
        catalog_asset_id, catalog_source_document, catalog_source_hash,
        'QUEUED', 'QUEUED', 0, 0, maximum_attempts,
        now_at, NULL, 0, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        p_job_id, now_at, now_at, 1
    FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id;
    PERFORM knowledge.append_tbox_proposal_event_v1(
        p_workspace_id, successor_id, NULL, 'QUEUED', 'QUEUED',
        'HUMAN', p_actor_id::text,
        jsonb_build_object(
            'reason_code', 'MANUAL_RETRY',
            'supersedes_job_id', p_job_id::text
        )
    );
    PERFORM knowledge.emit_tbox_proposal_outbox_v1(
        p_workspace_id, successor_id, 'QUEUED', 1
    );
    INSERT INTO integration.idempotency_keys (
        workspace_id, operation, key_hash, request_hash, result,
        created_at, expires_at
    ) VALUES (
        p_workspace_id, operation_name, key_hash, p_request_hash,
        jsonb_build_object('job_id', successor_id::text),
        now_at, now_at + interval '24 hours'
    );
    RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, successor_id);
END
$$;
""".strip()


TBOX_PROPOSAL_JOB_WORKER_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.claim_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_worker_fingerprint text,
    p_lease_token text,
    p_lease_seconds integer
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, integration, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
    expired_job knowledge.tbox_proposal_jobs%ROWTYPE;
    attempt_id uuid;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    worker_subject_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    now_at timestamptz := transaction_timestamp();
    lease_until timestamptz;
    drift_code text;
    target_state text;
    attempt_no integer;
    expired_attempt_id uuid;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR char_length(COALESCE(p_worker_fingerprint, '')) NOT BETWEEN 1 AND 255
       OR p_worker_fingerprint <> btrim(p_worker_fingerprint)
       OR char_length(COALESCE(p_lease_token, '')) NOT BETWEEN 32 AND 512
       OR p_lease_seconds NOT BETWEEN 5 AND 3600
       OR NOT knowledge.current_tbox_proposal_service_can_v1(
           p_workspace_id, 0, NULL
       )
    THEN
        RAISE EXCEPTION 'T-Box Proposal claim is not permitted'
            USING ERRCODE = '42501';
    END IF;
    FOR expired_job IN
        SELECT queued.*
        FROM knowledge.tbox_proposal_jobs AS queued
        JOIN knowledge.studio_drafts AS source_draft
          ON source_draft.workspace_id = queued.workspace_id
         AND source_draft.id = queued.draft_id
        WHERE queued.workspace_id = p_workspace_id
          AND queued.state IN ('RUNNING','CANCEL_REQUESTED')
          AND queued.lease_expires_at <= clock_timestamp()
        ORDER BY queued.lease_expires_at, queued.id
        FOR UPDATE OF queued SKIP LOCKED
    LOOP
        SELECT * INTO draft FROM knowledge.studio_drafts
        WHERE workspace_id = expired_job.workspace_id
          AND id = expired_job.draft_id;
        IF NOT knowledge.current_tbox_proposal_service_can_v1(
            p_workspace_id, COALESCE(draft.classification, 0), draft.domain_ref_id
        ) THEN
            CONTINUE;
        END IF;
        expired_attempt_id := expired_job.current_attempt_id;
        target_state := CASE
            WHEN expired_job.state = 'CANCEL_REQUESTED' THEN 'CANCELLED'
            WHEN expired_job.attempt_count < expired_job.maximum_attempts
                THEN 'RETRY_WAIT'
            ELSE 'FAILED'
        END;
        UPDATE knowledge.tbox_proposal_attempts
        SET state = CASE WHEN target_state = 'CANCELLED'
                THEN 'CANCELLED' ELSE 'SUPERSEDED' END,
            stage = 'COMPLETED', retryable = (target_state = 'RETRY_WAIT'),
            failure_code = 'LEASE_EXPIRED', finished_at = now_at
        WHERE workspace_id = p_workspace_id
          AND id = expired_job.current_attempt_id
          AND job_id = expired_job.id AND state = 'RUNNING';
        UPDATE knowledge.tbox_proposal_jobs
        SET state = target_state,
            stage = CASE WHEN target_state = 'RETRY_WAIT'
                THEN 'QUEUED' ELSE 'COMPLETED' END,
            progress_percent = 0,
            current_attempt_id = NULL,
            lease_token_hash = NULL,
            lease_owner_fingerprint = NULL,
            lease_started_at = NULL,
            lease_expires_at = NULL,
            next_attempt_at = CASE WHEN target_state = 'RETRY_WAIT'
                THEN now_at ELSE next_attempt_at END,
            last_failure_code = CASE WHEN target_state = 'CANCELLED'
                THEN NULL ELSE 'LEASE_EXPIRED' END,
            completed_at = CASE WHEN target_state = 'RETRY_WAIT'
                THEN NULL ELSE now_at END,
            updated_at = now_at,
            version = version + 1
        WHERE workspace_id = p_workspace_id AND id = expired_job.id
        RETURNING * INTO expired_job;
        PERFORM knowledge.append_tbox_proposal_event_v1(
            p_workspace_id, expired_job.id, expired_attempt_id,
            target_state, expired_job.stage, 'SERVICE', worker_subject_id::text,
            jsonb_build_object('reason_code', 'LEASE_EXPIRED')
        );
        PERFORM knowledge.emit_tbox_proposal_outbox_v1(
            p_workspace_id, expired_job.id, target_state, expired_job.version
        );
    END LOOP;
    LOOP
        SELECT queued.* INTO job
        FROM knowledge.tbox_proposal_jobs AS queued
        WHERE queued.workspace_id = p_workspace_id
          AND queued.state IN ('QUEUED','RETRY_WAIT')
          AND queued.next_attempt_at <= now_at
        ORDER BY queued.next_attempt_at, queued.created_at, queued.id
        LIMIT 1
        FOR UPDATE SKIP LOCKED;
        IF job.id IS NULL THEN
            RETURN NULL;
        END IF;
        SELECT * INTO draft FROM knowledge.studio_drafts
        WHERE workspace_id = job.workspace_id AND id = job.draft_id;
        IF NOT knowledge.current_tbox_proposal_service_can_v1(
            p_workspace_id, COALESCE(draft.classification, 0), draft.domain_ref_id
        ) THEN
            RAISE EXCEPTION 'T-Box Proposal worker scope is not permitted'
                USING ERRCODE = '42501';
        END IF;
        drift_code := knowledge.tbox_proposal_job_drift_v1(
            p_workspace_id, job.id, NULL
        );
        IF drift_code IS NOT NULL THEN
            UPDATE knowledge.tbox_proposal_jobs
            SET state = 'STALE', stage = 'COMPLETED', progress_percent = 0,
                last_failure_code = drift_code, completed_at = now_at,
                current_attempt_id = NULL, lease_token_hash = NULL,
                lease_owner_fingerprint = NULL, lease_started_at = NULL,
                lease_expires_at = NULL, updated_at = now_at, version = version + 1
            WHERE workspace_id = p_workspace_id AND id = job.id
            RETURNING * INTO job;
            PERFORM knowledge.append_tbox_proposal_event_v1(
                p_workspace_id, job.id, NULL, 'STALE', 'COMPLETED',
                'SERVICE', worker_subject_id::text,
                jsonb_build_object('reason_code', drift_code)
            );
            PERFORM knowledge.emit_tbox_proposal_outbox_v1(
                p_workspace_id, job.id, 'STALE', job.version
            );
            job.id := NULL;
            CONTINUE;
        END IF;
        attempt_id := gen_random_uuid();
        attempt_no := job.attempt_count + 1;
        lease_until := clock_timestamp() + make_interval(secs => p_lease_seconds);
        INSERT INTO knowledge.tbox_proposal_attempts (
            id, workspace_id, job_id, attempt_no, lease_epoch,
            lease_token_hash, worker_fingerprint, state, stage,
            claimed_at, lease_expires_at, retryable, output_hash,
            failure_code, finished_at
        ) VALUES (
            attempt_id, p_workspace_id, job.id, attempt_no,
            job.lease_epoch + 1, token_hash, p_worker_fingerprint,
            'RUNNING', 'SOURCE_VALIDATION', now_at, lease_until,
            NULL, NULL, NULL, NULL
        );
        UPDATE knowledge.tbox_proposal_jobs
        SET state = 'RUNNING', stage = 'SOURCE_VALIDATION',
            progress_percent = 10, attempt_count = attempt_no,
            current_attempt_id = attempt_id, lease_epoch = lease_epoch + 1,
            lease_token_hash = token_hash,
            lease_owner_fingerprint = p_worker_fingerprint,
            lease_started_at = now_at, lease_expires_at = lease_until,
            last_failure_code = NULL, updated_at = now_at, version = version + 1
        WHERE workspace_id = p_workspace_id AND id = job.id
        RETURNING * INTO job;
        PERFORM knowledge.append_tbox_proposal_event_v1(
            p_workspace_id, job.id, attempt_id, 'RUNNING',
            'SOURCE_VALIDATION', 'SERVICE', worker_subject_id::text,
            jsonb_build_object(
                'reason_code', 'CLAIMED',
                'attempt_no', attempt_no,
                'lease_epoch', job.lease_epoch,
                'worker_fingerprint_hash', encode(sha256(
                    convert_to(p_worker_fingerprint, 'UTF8')
                ), 'hex')
            )
        );
        PERFORM knowledge.emit_tbox_proposal_outbox_v1(
            p_workspace_id, job.id, 'RUNNING', job.version
        );
        RETURN jsonb_build_object(
            'job', knowledge.tbox_proposal_job_document_v1(p_workspace_id, job.id),
            'pins', knowledge.tbox_proposal_job_pins_v1(p_workspace_id, job.id),
            'current_elements', knowledge.tbox_proposal_current_elements_v1(
                p_workspace_id, job.draft_id
            ),
            'attempt_id', attempt_id::text,
            'attempt_no', attempt_no,
            'lease_epoch', job.lease_epoch,
            'worker_fingerprint', p_worker_fingerprint,
            'source_locator', CASE WHEN job.input_kind = 'DOCUMENT_SCHEMA' THEN (
                SELECT jsonb_build_object(
                    'bucket', manifest.bucket,
                    'object_key', manifest.object_key
                )
                FROM integration.object_manifests AS manifest
                WHERE manifest.workspace_id = p_workspace_id
                  AND manifest.id = job.manifest_id
            ) ELSE NULL END
        );
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.renew_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_lease_seconds integer,
    p_stage text,
    p_progress_percent integer
)
RETURNS timestamptz
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    lease_until timestamptz;
BEGIN
    SELECT * INTO job FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = job.draft_id;
    IF job.id IS NULL
       OR NOT knowledge.current_tbox_proposal_service_can_v1(
           p_workspace_id, COALESCE(draft.classification, 0), draft.domain_ref_id
       ) OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR job.lease_expires_at <= clock_timestamp()
       OR p_lease_seconds NOT BETWEEN 5 AND 3600
       OR p_stage NOT IN ('PARSING','INFERENCE','VALIDATING','FINALIZING')
       OR p_progress_percent NOT BETWEEN 11 AND 99
       OR p_progress_percent < job.progress_percent
       OR NOT knowledge.tbox_proposal_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch,
           p_lease_token, p_worker_fingerprint
       )
    THEN
        RAISE EXCEPTION 'T-Box Proposal lease was superseded'
            USING ERRCODE = '55000';
    END IF;
    lease_until := clock_timestamp() + make_interval(secs => p_lease_seconds);
    UPDATE knowledge.tbox_proposal_attempts
    SET stage = p_stage, lease_expires_at = lease_until
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND job_id = p_job_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'T-Box Proposal attempt was superseded'
            USING ERRCODE = '55000';
    END IF;
    UPDATE knowledge.tbox_proposal_jobs
    SET stage = p_stage, progress_percent = p_progress_percent,
        lease_expires_at = lease_until, updated_at = transaction_timestamp(),
        version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id;
    RETURN lease_until;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.ensure_tbox_proposal_job_current_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_schema_binding jsonb
)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
BEGIN
    SELECT * INTO job FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = job.draft_id;
    IF job.id IS NULL
       OR NOT knowledge.current_tbox_proposal_service_can_v1(
           p_workspace_id, COALESCE(draft.classification, 0), draft.domain_ref_id
       ) OR job.state NOT IN ('RUNNING','CANCEL_REQUESTED')
       OR job.lease_expires_at <= clock_timestamp()
       OR NOT knowledge.tbox_proposal_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch,
           p_lease_token, p_worker_fingerprint
       )
    THEN
        RAISE EXCEPTION 'T-Box Proposal lease was superseded'
            USING ERRCODE = '55000';
    END IF;
    IF job.state = 'CANCEL_REQUESTED' THEN
        UPDATE knowledge.tbox_proposal_attempts
        SET state = 'CANCELLED', stage = 'COMPLETED', retryable = false,
            failure_code = NULL, finished_at = transaction_timestamp()
        WHERE workspace_id = p_workspace_id AND id = p_attempt_id
          AND job_id = p_job_id AND state = 'RUNNING'
          AND lease_epoch = p_lease_epoch
          AND lease_token_hash = encode(
              sha256(convert_to(p_lease_token, 'UTF8')), 'hex'
          );
        IF NOT FOUND THEN
            RAISE EXCEPTION 'T-Box Proposal cancellation attempt was superseded'
                USING ERRCODE = '55000';
        END IF;
        UPDATE knowledge.tbox_proposal_jobs
        SET state = 'CANCELLED', stage = 'COMPLETED',
            current_attempt_id = NULL, lease_token_hash = NULL,
            lease_owner_fingerprint = NULL, lease_started_at = NULL,
            lease_expires_at = NULL, last_failure_code = NULL,
            completed_at = transaction_timestamp(),
            updated_at = transaction_timestamp(), version = version + 1
        WHERE workspace_id = p_workspace_id AND id = p_job_id
        RETURNING * INTO job;
        PERFORM knowledge.append_tbox_proposal_event_v1(
            p_workspace_id, p_job_id, p_attempt_id,
            'CANCELLED', 'COMPLETED', 'SERVICE',
            NULLIF(current_setting('app.subject_id', true), ''),
            jsonb_build_object('reason_code', 'CANCELLED_BEFORE_PROVIDER')
        );
        PERFORM knowledge.emit_tbox_proposal_outbox_v1(
            p_workspace_id, p_job_id, 'CANCELLED', job.version
        );
        RETURN 'CANCELLED';
    END IF;
    RETURN knowledge.tbox_proposal_job_drift_v1(
        p_workspace_id, p_job_id, p_schema_binding
    );
END
$$;
""".strip()


TBOX_PROPOSAL_JOB_FINALIZATION_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.complete_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_call_id text,
    p_elements jsonb,
    p_conflicts jsonb,
    p_prompt_label text,
    p_model_binding jsonb,
    p_source_reference jsonb,
    p_result_hash text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, integration, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
    now_at timestamptz := transaction_timestamp();
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    proposal_id uuid := gen_random_uuid();
    operation_name text := 'knowledge.tbox-proposal.complete:' || p_job_id::text;
    key_hash text := encode(sha256(convert_to(p_call_id, 'UTF8')), 'hex');
    replay integration.idempotency_keys%ROWTYPE;
    drift_code text;
    element jsonb;
BEGIN
    IF char_length(COALESCE(p_call_id, '')) NOT BETWEEN 1 AND 200
       OR p_result_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_elements) <> 'array'
       OR jsonb_array_length(p_elements) NOT BETWEEN 1 AND 500
       OR octet_length(p_elements::text) > 2097152
       OR jsonb_typeof(p_conflicts) <> 'array'
       OR jsonb_array_length(p_conflicts) > 500
       OR octet_length(p_conflicts::text) > 1048576
       OR jsonb_typeof(p_model_binding) <> 'object'
       OR octet_length(p_model_binding::text) > 8192
       OR jsonb_typeof(p_source_reference) <> 'object'
       OR octet_length(p_source_reference::text) > 65536
       OR p_source_reference::text ~*
           '"(bucket|object_key|excerpt|prompt|provider_body|content)"\\s*:'
       OR char_length(COALESCE(p_prompt_label, '')) NOT BETWEEN 1 AND 512
       OR p_prompt_label <> btrim(p_prompt_label)
       OR p_prompt_label ~ '[\\x00-\\x1F\\x7F]'
       OR NOT (
           p_prompt_label = 'Governed Schema Assistant proposal'
           OR p_prompt_label LIKE 'Document schema proposal: %'
           OR p_prompt_label LIKE 'Catalog schema proposal: %'
       )
    THEN
        RAISE EXCEPTION 'invalid T-Box Proposal completion payload'
            USING ERRCODE = '55000';
    END IF;
    FOR element IN SELECT value FROM jsonb_array_elements(p_elements)
    LOOP
        IF jsonb_typeof(element) <> 'object'
           OR (element - ARRAY[
               'stable_element_id','kind','canonical_name','display_name',
               'parent_stable_element_id','hierarchy_relation',
               'source_stable_element_id','target_stable_element_id','data_type',
               'nullable','definition','aliases','unit','vector_index_enabled',
               'metadata_reference_id','metadata_reference_urn','layout_x','layout_y'
           ]) <> '{}'::jsonb
           OR element ->> 'kind' NOT IN ('CLASS','PROPERTY','RELATION')
           OR char_length(COALESCE(element ->> 'stable_element_id', ''))
               NOT BETWEEN 1 AND 128
           OR char_length(COALESCE(element ->> 'canonical_name', ''))
               NOT BETWEEN 1 AND 255
           OR char_length(COALESCE(element ->> 'display_name', ''))
               NOT BETWEEN 1 AND 255
           OR jsonb_typeof(element -> 'aliases') <> 'array'
           OR jsonb_array_length(element -> 'aliases') > 50
        THEN
            RAISE EXCEPTION 'invalid typed T-Box Proposal element'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_workspace_id::text || ':' || operation_name || ':' || p_call_id, 0
    ));
    SELECT * INTO replay FROM integration.idempotency_keys
    WHERE workspace_id = p_workspace_id AND operation = operation_name
      AND integration.idempotency_keys.key_hash = key_hash;
    IF replay.workspace_id IS NOT NULL THEN
        IF replay.request_hash <> p_result_hash THEN
            RAISE EXCEPTION 'T-Box Proposal completion call was reused'
                USING ERRCODE = '55000';
        END IF;
        RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, p_job_id);
    END IF;
    SELECT * INTO job FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = job.draft_id;
    IF job.id IS NULL
       OR NOT knowledge.current_tbox_proposal_service_can_v1(
           p_workspace_id, COALESCE(draft.classification, 0), draft.domain_ref_id
       ) OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR job.lease_expires_at <= clock_timestamp()
       OR NOT knowledge.tbox_proposal_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch,
           p_lease_token, p_worker_fingerprint
       ) OR knowledge.tbox_proposal_json_hash_v1(p_model_binding)
           <> job.schema_binding_hash
       OR p_model_binding <> job.schema_binding_document
    THEN
        RAISE EXCEPTION 'T-Box Proposal completion lease was superseded'
            USING ERRCODE = '55000';
    END IF;
    drift_code := knowledge.tbox_proposal_job_drift_v1(
        p_workspace_id, p_job_id, p_model_binding
    );
    IF drift_code IS NOT NULL THEN
        RAISE EXCEPTION 'T-Box Proposal completion pins are stale: %', drift_code
            USING ERRCODE = '55000';
    END IF;
    INSERT INTO knowledge.tbox_proposals (
        id, workspace_id, draft_id, target_block_id, created_by,
        state, mode, merge_strategy, base_draft_version, prompt,
        proposal_document, conflicts_document, model_binding_document,
        source_reference_document, error_code, applied_at, rejected_at,
        created_at, updated_at, version
    ) VALUES (
        proposal_id, p_workspace_id, job.draft_id, job.target_block_id,
        job.requested_by, 'READY', job.mode, 'KEEP_ORIGINAL',
        job.base_draft_version, p_prompt_label,
        jsonb_build_object(
            'contract_version', 'KNOWLEDGE_STUDIO_TBOX_PROPOSAL_V1',
            'elements', p_elements
        ), p_conflicts, p_model_binding, p_source_reference,
        NULL, NULL, NULL, now_at, now_at, 1
    );
    UPDATE knowledge.tbox_proposal_attempts
    SET state = 'SUCCEEDED', stage = 'COMPLETED', retryable = false,
        output_hash = p_result_hash, failure_code = NULL, finished_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND job_id = p_job_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'T-Box Proposal completion attempt was superseded'
            USING ERRCODE = '55000';
    END IF;
    UPDATE knowledge.tbox_proposal_jobs
    SET state = 'SUCCEEDED', stage = 'COMPLETED', progress_percent = 100,
        current_attempt_id = NULL, lease_token_hash = NULL,
        lease_owner_fingerprint = NULL, lease_started_at = NULL,
        lease_expires_at = NULL, result_proposal_id = proposal_id,
        result_evidence_hash = p_result_hash, last_failure_code = NULL,
        completed_at = now_at, updated_at = now_at, version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    RETURNING * INTO job;
    PERFORM knowledge.append_tbox_proposal_event_v1(
        p_workspace_id, p_job_id, p_attempt_id, 'SUCCEEDED', 'COMPLETED',
        'SERVICE', NULLIF(current_setting('app.subject_id', true), ''),
        jsonb_build_object(
            'reason_code', 'PROPOSAL_READY',
            'proposal_id', proposal_id::text,
            'result_hash', p_result_hash,
            'call_id_hash', key_hash
        )
    );
    PERFORM knowledge.emit_tbox_proposal_outbox_v1(
        p_workspace_id, p_job_id, 'SUCCEEDED', job.version
    );
    INSERT INTO integration.idempotency_keys (
        workspace_id, operation, key_hash, request_hash, result,
        created_at, expires_at
    ) VALUES (
        p_workspace_id, operation_name, key_hash, p_result_hash,
        jsonb_build_object(
            'job_id', p_job_id::text,
            'proposal_id', proposal_id::text
        ), now_at, now_at + interval '24 hours'
    );
    RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, p_job_id);
END
$$;

CREATE OR REPLACE FUNCTION knowledge.fail_tbox_proposal_job_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_call_id text,
    p_failure_code text,
    p_retryable boolean,
    p_stale boolean
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, integration, knowledge
AS $$
DECLARE
    job knowledge.tbox_proposal_jobs%ROWTYPE;
    draft knowledge.studio_drafts%ROWTYPE;
    now_at timestamptz := transaction_timestamp();
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    operation_name text := 'knowledge.tbox-proposal.fail:' || p_job_id::text;
    key_hash text := encode(sha256(convert_to(p_call_id, 'UTF8')), 'hex');
    request_hash text;
    replay integration.idempotency_keys%ROWTYPE;
    target_state text;
    attempt_state text;
BEGIN
    request_hash := knowledge.tbox_proposal_json_hash_v1(jsonb_build_object(
        'failure_code', p_failure_code,
        'retryable', p_retryable,
        'stale', p_stale
    ));
    IF char_length(COALESCE(p_call_id, '')) NOT BETWEEN 1 AND 200
       OR p_failure_code !~ '^[A-Z0-9_]{1,100}$'
    THEN
        RAISE EXCEPTION 'invalid T-Box Proposal failure payload'
            USING ERRCODE = '55000';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_workspace_id::text || ':' || operation_name || ':' || p_call_id, 0
    ));
    SELECT * INTO replay FROM integration.idempotency_keys
    WHERE workspace_id = p_workspace_id AND operation = operation_name
      AND integration.idempotency_keys.key_hash = key_hash;
    IF replay.workspace_id IS NOT NULL THEN
        IF replay.request_hash <> request_hash THEN
            RAISE EXCEPTION 'T-Box Proposal failure call was reused'
                USING ERRCODE = '55000';
        END IF;
        RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, p_job_id);
    END IF;
    SELECT * INTO job FROM knowledge.tbox_proposal_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    SELECT * INTO draft FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = job.draft_id;
    IF job.id IS NULL
       OR NOT knowledge.current_tbox_proposal_service_can_v1(
           p_workspace_id, COALESCE(draft.classification, 0), draft.domain_ref_id
       ) OR job.state NOT IN ('RUNNING','CANCEL_REQUESTED')
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR job.lease_expires_at <= clock_timestamp()
       OR NOT knowledge.tbox_proposal_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch,
           p_lease_token, p_worker_fingerprint
       )
    THEN
        RAISE EXCEPTION 'T-Box Proposal failure lease was superseded'
            USING ERRCODE = '55000';
    END IF;
    target_state := CASE
        WHEN job.state = 'CANCEL_REQUESTED' THEN 'CANCELLED'
        WHEN p_stale THEN 'STALE'
        WHEN p_retryable AND job.attempt_count < job.maximum_attempts
            THEN 'RETRY_WAIT'
        ELSE 'FAILED'
    END;
    attempt_state := CASE
        WHEN target_state = 'CANCELLED' THEN 'CANCELLED'
        WHEN target_state = 'STALE' THEN 'STALE'
        ELSE 'FAILED'
    END;
    UPDATE knowledge.tbox_proposal_attempts
    SET state = attempt_state, stage = 'COMPLETED', retryable = p_retryable,
        failure_code = p_failure_code, finished_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND job_id = p_job_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'T-Box Proposal failure attempt was superseded'
            USING ERRCODE = '55000';
    END IF;
    UPDATE knowledge.tbox_proposal_jobs
    SET state = target_state,
        stage = CASE WHEN target_state = 'RETRY_WAIT'
            THEN 'QUEUED' ELSE 'COMPLETED' END,
        progress_percent = 0,
        current_attempt_id = NULL, lease_token_hash = NULL,
        lease_owner_fingerprint = NULL, lease_started_at = NULL,
        lease_expires_at = NULL,
        next_attempt_at = CASE WHEN target_state = 'RETRY_WAIT'
            THEN now_at + make_interval(
                secs => least(60, 5 * (2 ^ attempt_count))::integer
            ) ELSE next_attempt_at END,
        last_failure_code = CASE WHEN target_state = 'CANCELLED'
            THEN NULL ELSE p_failure_code END,
        completed_at = CASE WHEN target_state = 'RETRY_WAIT'
            THEN NULL ELSE now_at END,
        updated_at = now_at, version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    RETURNING * INTO job;
    PERFORM knowledge.append_tbox_proposal_event_v1(
        p_workspace_id, p_job_id, p_attempt_id, target_state, job.stage,
        'SERVICE', NULLIF(current_setting('app.subject_id', true), ''),
        jsonb_build_object(
            'reason_code', p_failure_code,
            'retryable', p_retryable,
            'call_id_hash', key_hash
        )
    );
    PERFORM knowledge.emit_tbox_proposal_outbox_v1(
        p_workspace_id, p_job_id, target_state, job.version
    );
    INSERT INTO integration.idempotency_keys (
        workspace_id, operation, key_hash, request_hash, result,
        created_at, expires_at
    ) VALUES (
        p_workspace_id, operation_name, key_hash, request_hash,
        jsonb_build_object('job_id', p_job_id::text),
        now_at, now_at + interval '24 hours'
    );
    RETURN knowledge.tbox_proposal_job_document_v1(p_workspace_id, p_job_id);
END
$$;
""".strip()


TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL = "\n\n".join(
    (
        TBOX_PROPOSAL_JOB_SUPPORT_FUNCTION_SQL,
        TBOX_PROPOSAL_JOB_GUARD_FUNCTION_SQL,
        TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SQL,
        TBOX_PROPOSAL_JOB_OWNER_TRANSITION_FUNCTION_SQL,
        TBOX_PROPOSAL_JOB_WORKER_FUNCTION_SQL,
        TBOX_PROPOSAL_JOB_FINALIZATION_FUNCTION_SQL,
    )
)
