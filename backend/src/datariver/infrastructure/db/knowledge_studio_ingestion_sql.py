from __future__ import annotations

STUDIO_INGESTION_FUNCTION_SIGNATURES = (
    "knowledge.request_studio_ingestion_v1(uuid,uuid,integer,text,text,integer,text,jsonb,jsonb,integer)",
    "knowledge.cancel_studio_ingestion_v1(uuid,uuid,integer,text)",
    "knowledge.retry_studio_ingestion_v1(uuid,uuid,integer)",
    "knowledge.claim_studio_ingestion_v1(uuid,text,text,integer)",
    "knowledge.freeze_studio_ingestion_source_access_v1(uuid,uuid,uuid,bigint,text,text,integer,integer)",
    "knowledge.assert_studio_ingestion_source_statement_fence_v1(uuid,uuid,uuid,bigint,text,text)",
    "knowledge.renew_studio_ingestion_v1(uuid,uuid,uuid,bigint,text,text,integer,text,integer)",
    "knowledge.ensure_studio_ingestion_current_v1(uuid,uuid,uuid,bigint,text,text,text,integer,text,jsonb)",
    "knowledge.begin_studio_ingestion_completion_v1(uuid,uuid,uuid,bigint,text,text)",
    "knowledge.append_studio_ingestion_result_batch_v1(uuid,uuid,uuid,bigint,text,text,uuid,jsonb,jsonb)",
    "knowledge.complete_studio_ingestion_v1(uuid,uuid,uuid,bigint,text,text,uuid,text,text,integer,integer,text)",
    "knowledge.fail_studio_ingestion_v1(uuid,uuid,uuid,bigint,text,text,text,text,boolean,boolean)",
)

STUDIO_INGESTION_INTERNAL_FUNCTION_SIGNATURES = (
    "knowledge.append_studio_ingestion_event_v1(uuid,uuid,uuid,text,text,uuid,text,jsonb)",
    "knowledge.emit_studio_ingestion_outbox_v1(uuid,uuid,text,integer)",
    "knowledge.current_studio_ingestion_service_can_v1(uuid,text,integer,uuid)",
    "knowledge.current_studio_ingestion_human_can_v1(uuid,uuid,integer,uuid)",
    "knowledge.current_studio_ingestion_lease_matches_v1(uuid,uuid,uuid,bigint,text,text)",
)

STUDIO_INGESTION_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.append_studio_ingestion_event_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_state text,
    p_reason_code text,
    p_actor_id uuid,
    p_actor_kind text,
    p_details jsonb
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    next_sequence integer;
    now_at timestamptz := transaction_timestamp();
    evidence_hash text;
BEGIN
    IF p_state NOT IN (
        'PENDING','RUNNING','RETRY_WAIT','CANCEL_REQUESTED',
        'SUCCESS','FAILED','STALE','CANCELLED'
    )
       OR p_actor_kind NOT IN ('HUMAN','SERVICE')
       OR char_length(COALESCE(p_reason_code, '')) NOT BETWEEN 1 AND 100
       OR jsonb_typeof(p_details) <> 'object'
       OR octet_length(p_details::text) > 8192 THEN
        RAISE EXCEPTION 'invalid Studio ingestion transition evidence'
            USING ERRCODE = '23514';
    END IF;
    SELECT COALESCE(max(event.sequence), 0) + 1
    INTO next_sequence
    FROM knowledge.studio_ingestion_events AS event
    WHERE event.workspace_id = p_workspace_id
      AND event.job_id = p_job_id;
    evidence_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'STUDIO_INGESTION_EVENT_V1',
        'workspace_id', p_workspace_id,
        'job_id', p_job_id,
        'attempt_id', p_attempt_id,
        'sequence', next_sequence,
        'state', p_state,
        'reason_code', p_reason_code,
        'actor_id', p_actor_id,
        'actor_kind', p_actor_kind,
        'details', p_details,
        'occurred_at', now_at
    )::text, 'UTF8')), 'hex');
    INSERT INTO knowledge.studio_ingestion_events (
        id, workspace_id, job_id, sequence, attempt_id, state, reason_code,
        actor_id, actor_kind, evidence_hash, details_document, occurred_at
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, p_job_id, next_sequence, p_attempt_id,
        p_state, p_reason_code, p_actor_id, p_actor_kind, evidence_hash,
        p_details, now_at
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.emit_studio_ingestion_outbox_v1(
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
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, 'knowledge_studio_ingestion',
        p_job_id, 'knowledge.studio-ingestion.' || lower(p_state) || '.v1',
        1, jsonb_build_object(
            'job_id', p_job_id,
            'state', p_state,
            'version', p_version
        ), transaction_timestamp(), NULL, NULL, NULL, 0, NULL
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.current_studio_ingestion_service_can_v1(
    p_workspace_id uuid,
    p_action text,
    p_classification integer,
    p_domain_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam
AS $$
    SELECT session_user = 'datariver_knowledge_ingestion'
       AND p_workspace_id IS NOT DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       AND p_action = 'kg.ingestion.execute'
       AND EXISTS (
           SELECT 1
           FROM platform.workspaces AS workspace
           JOIN iam.workspace_memberships AS membership
             ON membership.workspace_id = workspace.id
           JOIN iam.subjects AS subject
             ON subject.id = membership.subject_id
           WHERE workspace.id = p_workspace_id
             AND workspace.status = 'ACTIVE'
             AND membership.subject_id =
                 NULLIF(current_setting('app.subject_id', true), '')::uuid
             AND subject.active IS TRUE
             AND membership.active IS TRUE
             AND (
                 membership.access_expires_at IS NULL
                 OR membership.access_expires_at > transaction_timestamp()
             )
             AND membership.job_function = 'SERVICE_ACCOUNT'
             AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                 = '["service-accounts","knowledge-ingestion-workers"]'::jsonb
             AND COALESCE(
                 membership.attributes -> 'allowed_actions', '[]'::jsonb
             ) = '["kg.ingestion.execute"]'::jsonb
             AND COALESCE(
                 membership.attributes -> 'denied_actions', '[]'::jsonb
             ) = '[]'::jsonb
             AND membership.clearance >= p_classification
             AND (
                 p_classification = 0
                 OR p_domain_id IS NULL
                 OR COALESCE(
                     membership.attributes -> 'allowed_domain_ids', '[]'::jsonb
                 ) ? p_domain_id::text
             )
       )
$$;

CREATE OR REPLACE FUNCTION knowledge.current_studio_ingestion_human_can_v1(
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
           JOIN iam.subjects AS subject
             ON subject.id = membership.subject_id
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

CREATE OR REPLACE FUNCTION knowledge.request_studio_ingestion_v1(
    p_workspace_id uuid,
    p_draft_id uuid,
    p_expected_version integer,
    p_request_hash text,
    p_manifest_id text,
    p_manifest_version integer,
    p_manifest_hash text,
    p_source_profile_pins jsonb,
    p_embedding_binding jsonb,
    p_maximum_attempts integer
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
    studio_release knowledge.studio_releases%ROWTYPE;
    graph knowledge.graphs%ROWTYPE;
    ontology knowledge.ontology_versions%ROWTYPE;
    binding record;
    profile_pin jsonb;
    rules jsonb;
    job_id uuid := gen_random_uuid();
    global_pin_hash text;
    binding_pin_hash text;
    embedding_hash text;
    vector_target_count integer := 0;
    binding_count integer;
    source_count integer;
    now_at timestamptz := transaction_timestamp();
    base_hash text;
    locked_authorization_hash text;
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR actor_id IS NULL
       OR p_expected_version < 1
       OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR char_length(COALESCE(p_manifest_id, '')) NOT BETWEEN 1 AND 255
       OR p_manifest_id IS DISTINCT FROM btrim(p_manifest_id)
       OR p_manifest_version < 1
       OR p_manifest_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_source_profile_pins) <> 'array'
       OR jsonb_array_length(p_source_profile_pins) NOT BETWEEN 1 AND 500
       OR p_maximum_attempts NOT BETWEEN 1 AND 20
       OR (
           p_embedding_binding IS NOT NULL
           AND (
               jsonb_typeof(p_embedding_binding) <> 'object'
               OR octet_length(p_embedding_binding::text) > 8192
           )
       ) THEN
        RAISE EXCEPTION 'invalid Studio ingestion request'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO draft
    FROM knowledge.studio_drafts
    WHERE workspace_id = p_workspace_id AND id = p_draft_id
    FOR UPDATE;
    IF NOT FOUND
       OR draft.version <> p_expected_version
       OR draft.state <> 'PUBLISHED'
       OR draft.current_step <> 'ABOX'
       OR draft.materialized_graph_id IS NULL
       OR draft.materialized_ontology_version_id IS NULL
       OR draft.published_studio_release_id IS NULL THEN
        RAISE EXCEPTION 'Studio ingestion requires an exact published Draft'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO graph
    FROM knowledge.graphs
    WHERE workspace_id = p_workspace_id
      AND id = draft.materialized_graph_id
    FOR UPDATE;
    SELECT * INTO studio_release
    FROM knowledge.studio_releases
    WHERE workspace_id = p_workspace_id
      AND graph_id = graph.id
      AND id = draft.published_studio_release_id
    FOR SHARE;
    SELECT * INTO ontology
    FROM knowledge.ontology_versions
    WHERE workspace_id = p_workspace_id
      AND graph_id = graph.id
      AND id = draft.materialized_ontology_version_id
    FOR SHARE;
    IF graph.id IS NULL
       OR graph.status <> 'PUBLISHED'
       OR graph.active_studio_release_id IS DISTINCT FROM studio_release.id
       OR studio_release.state <> 'ACTIVE'
       OR studio_release.source_draft_id IS DISTINCT FROM draft.id
       OR studio_release.source_draft_version <> draft.version - 1
       OR studio_release.ontology_version_id IS DISTINCT FROM ontology.id
       OR ontology.status <> 'PUBLISHED' THEN
        RAISE EXCEPTION 'Studio release pins changed before ingestion'
            USING ERRCODE = '55000';
    END IF;
    IF NOT knowledge.current_studio_ingestion_human_can_v1(
        p_workspace_id, actor_id, graph.classification, graph.domain_ref_id
    ) THEN
        RAISE EXCEPTION 'Studio ingestion requester is not authorized'
            USING ERRCODE = '42501';
    END IF;
    PERFORM 1
    FROM platform.workspaces AS workspace
    JOIN iam.workspace_memberships AS membership
      ON membership.workspace_id = workspace.id
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE workspace.id = p_workspace_id
      AND workspace.status = 'ACTIVE'
      AND membership.subject_id = actor_id
      AND subject.active IS TRUE
      AND membership.active IS TRUE
      AND (
          membership.access_expires_at IS NULL
          OR membership.access_expires_at > now_at
      )
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND membership.clearance >= graph.classification
      AND COALESCE(
          membership.attributes -> 'allowed_actions', '[]'::jsonb
      ) ? 'kg.edit'
      AND NOT (
          COALESCE(
              membership.attributes -> 'denied_actions', '[]'::jsonb
          ) ? 'kg.edit'
      )
      AND (
          graph.classification = 0
          OR graph.domain_ref_id IS NULL
          OR COALESCE(
              membership.attributes -> 'allowed_domain_ids', '[]'::jsonb
          ) ? graph.domain_ref_id::text
      )
    FOR SHARE OF workspace, membership, subject;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Studio ingestion requester is not authorized'
            USING ERRCODE = '42501';
    END IF;
    SELECT encode(sha256(convert_to(jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_INGESTION_REQUEST_AUTHORIZATION_DB_V1',
        'workspace_id', membership.workspace_id,
        'subject_id', membership.subject_id,
        'subject_active', subject.active,
        'membership_active', membership.active,
        'access_expires_at', membership.access_expires_at,
        'job_function', membership.job_function,
        'clearance', membership.clearance,
        'attributes', membership.attributes
    )::text, 'UTF8')), 'hex')
    INTO locked_authorization_hash
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = actor_id;
    SELECT count(*) INTO source_count
    FROM jsonb_array_elements(p_source_profile_pins) AS pin
    WHERE jsonb_typeof(pin) = 'object'
      AND (
          pin - ARRAY[
              'asset_id','source_version','projection_source_version',
              'connection_profile_id','connection_profile_version',
              'connection_profile_hash'
          ]
      ) = '{}'::jsonb
      AND (pin ->> 'asset_id') IS NOT NULL
      AND char_length(COALESCE(pin ->> 'source_version', '')) BETWEEN 1 AND 255
      AND char_length(COALESCE(pin ->> 'projection_source_version', ''))
          BETWEEN 1 AND 255
      AND char_length(COALESCE(pin ->> 'connection_profile_id', ''))
          BETWEEN 1 AND 255
      AND (pin ->> 'connection_profile_version') ~ '^[1-9][0-9]*$'
      AND pin ->> 'connection_profile_hash' ~ '^[0-9a-f]{64}$';
    IF source_count <> jsonb_array_length(p_source_profile_pins)
       OR source_count <> (
           SELECT count(DISTINCT pin ->> 'asset_id')
           FROM jsonb_array_elements(p_source_profile_pins) AS pin
       ) THEN
        RAISE EXCEPTION 'Studio source profile pins are invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT count(*) INTO binding_count
    FROM knowledge.abox_binding_versions
    WHERE workspace_id = p_workspace_id
      AND studio_release_id = studio_release.id;
    IF binding_count NOT BETWEEN 1 AND 500 THEN
        RAISE EXCEPTION 'Studio Release has no bounded A-Box Binding set'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_source_profile_pins) AS pin
        WHERE NOT EXISTS (
            SELECT 1
            FROM knowledge.abox_binding_versions AS binding_version
            JOIN knowledge.source_references AS source
              ON source.workspace_id = binding_version.workspace_id
             AND source.id = binding_version.source_reference_id
            WHERE binding_version.workspace_id = p_workspace_id
              AND binding_version.studio_release_id = studio_release.id
              AND source.catalog_asset_id::text = pin ->> 'asset_id'
        )
    ) OR EXISTS (
        SELECT 1
        FROM knowledge.abox_binding_versions AS binding_version
        JOIN knowledge.source_references AS source
          ON source.workspace_id = binding_version.workspace_id
         AND source.id = binding_version.source_reference_id
        WHERE binding_version.workspace_id = p_workspace_id
          AND binding_version.studio_release_id = studio_release.id
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements(p_source_profile_pins) AS pin
              WHERE pin ->> 'asset_id' = source.catalog_asset_id::text
          )
    ) THEN
        RAISE EXCEPTION 'Studio source profile pins do not match released Bindings'
            USING ERRCODE = '23514';
    END IF;
    FOR binding IN
        SELECT
            binding_version.*,
            source.catalog_asset_id,
            source.source_version,
            source.projection_source_version,
            source.classification AS source_classification,
            source.selection_hash,
            target.canonical_name AS target_class_canonical_name,
            target.kind AS target_kind
        FROM knowledge.abox_binding_versions AS binding_version
        JOIN knowledge.source_references AS source
          ON source.workspace_id = binding_version.workspace_id
         AND source.id = binding_version.source_reference_id
        JOIN knowledge.ontology_elements AS target
          ON target.workspace_id = binding_version.workspace_id
         AND target.ontology_version_id = binding_version.ontology_version_id
         AND target.id = binding_version.target_ontology_element_id
        WHERE binding_version.workspace_id = p_workspace_id
          AND binding_version.studio_release_id = studio_release.id
        ORDER BY binding_version.ordinal
    LOOP
        IF binding.target_kind <> 'CLASS'
           OR binding.source_classification > graph.classification THEN
            RAISE EXCEPTION 'Studio DB ingestion v1 supports Class bindings only'
                USING ERRCODE = '23514';
        END IF;
        SELECT pin INTO profile_pin
        FROM jsonb_array_elements(p_source_profile_pins) AS pin
        WHERE pin ->> 'asset_id' = binding.catalog_asset_id::text;
        IF profile_pin IS NULL
           OR profile_pin ->> 'source_version' IS DISTINCT FROM binding.source_version
           OR profile_pin ->> 'projection_source_version'
                IS DISTINCT FROM binding.projection_source_version
           OR char_length(COALESCE(profile_pin ->> 'connection_profile_id', ''))
                NOT BETWEEN 1 AND 255
           OR (profile_pin ->> 'connection_profile_version')::integer < 1
           OR profile_pin ->> 'connection_profile_hash' !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'Studio Binding has no exact source profile pin'
                USING ERRCODE = '55000';
        END IF;
        SELECT jsonb_agg(
            jsonb_build_object(
                'method', rule.method,
                'source_field_path', rule.source_field_path,
                'target_stable_element_id', rule.target_stable_element_id,
                'target_canonical_name', element.canonical_name,
                'target_data_type', CASE
                    WHEN rule.method = 'PROPERTY'
                    THEN element.element_document ->> 'data_type'
                    ELSE NULL
                END,
                'target_nullable', CASE
                    WHEN rule.method = 'PROPERTY'
                    THEN element.element_document -> 'nullable'
                    ELSE NULL
                END,
                'vector_index_enabled', CASE
                    WHEN rule.method = 'PROPERTY'
                    THEN COALESCE(
                        (element.element_document ->> 'vector_index_enabled')::boolean,
                        false
                    )
                    ELSE false
                END,
                'transform_id', rule.transform_id,
                'transform_version', rule.transform_version
            )
            ORDER BY rule.ordinal
        ) INTO rules
        FROM knowledge.abox_mapping_rule_versions AS rule
        JOIN knowledge.ontology_elements AS element
          ON element.workspace_id = rule.workspace_id
         AND element.ontology_version_id = rule.ontology_version_id
         AND element.id = rule.target_ontology_element_id
        WHERE rule.workspace_id = p_workspace_id
          AND rule.binding_version_id = binding.id
          AND rule.method IN ('SUBJECT_ID','PROPERTY');
        IF rules IS NULL
           OR (
               SELECT count(*)
               FROM jsonb_array_elements(rules) AS rule
               WHERE rule ->> 'method' = 'SUBJECT_ID'
           ) <> 1
           OR (
               SELECT count(*)
               FROM knowledge.abox_mapping_rule_versions AS rule
               WHERE rule.workspace_id = p_workspace_id
                 AND rule.binding_version_id = binding.id
           ) <> jsonb_array_length(rules) THEN
            RAISE EXCEPTION 'Studio Binding Mapping is unsupported or incomplete'
                USING ERRCODE = '23514';
        END IF;
        vector_target_count := vector_target_count + (
            SELECT count(*)
            FROM jsonb_array_elements(rules) AS rule
            WHERE (rule ->> 'vector_index_enabled')::boolean IS TRUE
        );
    END LOOP;
    IF vector_target_count > 0 AND p_embedding_binding IS NULL THEN
        RAISE EXCEPTION 'Vector mappings require an exact embedding binding'
            USING ERRCODE = '23514';
    END IF;
    embedding_hash := CASE
        WHEN p_embedding_binding IS NULL THEN NULL
        ELSE encode(sha256(convert_to(p_embedding_binding::text, 'UTF8')), 'hex')
    END;
    SELECT content_hash INTO base_hash
    FROM knowledge.releases
    WHERE workspace_id = p_workspace_id
      AND graph_id = graph.id
      AND id = graph.active_release_id;
    global_pin_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_DB_INGESTION_PIN_V1',
        'graph_id', graph.id,
        'graph_version', graph.version,
        'studio_release_id', studio_release.id,
        'studio_contract_hash', studio_release.contract_hash,
        'ontology_version_id', ontology.id,
        'ontology_checksum', ontology.checksum,
        'manifest_id', p_manifest_id,
        'manifest_version', p_manifest_version,
        'manifest_hash', p_manifest_hash,
        'source_profile_pins', p_source_profile_pins,
        'embedding_binding_hash', embedding_hash,
        'requester_authorization_hash', locked_authorization_hash
    )::text, 'UTF8')), 'hex');
    INSERT INTO knowledge.studio_ingestion_jobs (
        id, workspace_id, graph_id, draft_id, studio_release_id,
        studio_release_no, studio_contract_hash, ontology_version_id,
        ontology_checksum, requested_by, graph_version, graph_classification,
        graph_domain_ref_id, graph_domain_source_version, vector_target_count,
        state, progress_percent, stage, manifest_id, manifest_version,
        manifest_hash, pin_hash, request_hash, requester_authorization_hash,
        embedding_binding_document, embedding_binding_hash,
        base_release_id, base_release_hash, attempt_count, maximum_attempts,
        current_attempt_id, next_attempt_at, lease_epoch, lease_token_hash,
        lease_owner_fingerprint, lease_started_at, lease_expires_at,
        source_access_started_at, source_access_deadline, result_changeset_id,
        result_evidence_hash, source_read_receipt_hash, last_failure_code,
        cancel_requested_by, cancel_requested_at, cancel_reason, completed_at,
        created_at, updated_at, version
    )
    VALUES (
        job_id, p_workspace_id, graph.id, draft.id, studio_release.id,
        studio_release.release_no, studio_release.contract_hash, ontology.id,
        ontology.checksum, actor_id, graph.version, graph.classification,
        graph.domain_ref_id, graph.domain_source_version, vector_target_count,
        'PENDING', 0, 'QUEUED', p_manifest_id, p_manifest_version,
        p_manifest_hash, global_pin_hash, p_request_hash,
        locked_authorization_hash, p_embedding_binding, embedding_hash,
        graph.active_release_id, base_hash, 0, p_maximum_attempts,
        NULL, now_at, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, now_at, now_at, 1
    );
    FOR binding IN
        SELECT
            binding_version.*,
            source.catalog_asset_id,
            source.source_version,
            source.projection_source_version,
            source.classification AS source_classification,
            source.selection_hash,
            target.canonical_name AS target_class_canonical_name
        FROM knowledge.abox_binding_versions AS binding_version
        JOIN knowledge.source_references AS source
          ON source.workspace_id = binding_version.workspace_id
         AND source.id = binding_version.source_reference_id
        JOIN knowledge.ontology_elements AS target
          ON target.workspace_id = binding_version.workspace_id
         AND target.ontology_version_id = binding_version.ontology_version_id
         AND target.id = binding_version.target_ontology_element_id
        WHERE binding_version.workspace_id = p_workspace_id
          AND binding_version.studio_release_id = studio_release.id
        ORDER BY binding_version.ordinal
    LOOP
        SELECT pin INTO profile_pin
        FROM jsonb_array_elements(p_source_profile_pins) AS pin
        WHERE pin ->> 'asset_id' = binding.catalog_asset_id::text;
        SELECT jsonb_agg(
            jsonb_build_object(
                'method', rule.method,
                'source_field_path', rule.source_field_path,
                'target_stable_element_id', rule.target_stable_element_id,
                'target_canonical_name', element.canonical_name,
                'target_data_type', CASE
                    WHEN rule.method = 'PROPERTY'
                    THEN element.element_document ->> 'data_type'
                    ELSE NULL
                END,
                'target_nullable', CASE
                    WHEN rule.method = 'PROPERTY'
                    THEN element.element_document -> 'nullable'
                    ELSE NULL
                END,
                'vector_index_enabled', CASE
                    WHEN rule.method = 'PROPERTY'
                    THEN COALESCE(
                        (element.element_document ->> 'vector_index_enabled')::boolean,
                        false
                    )
                    ELSE false
                END,
                'transform_id', rule.transform_id,
                'transform_version', rule.transform_version
            )
            ORDER BY rule.ordinal
        ) INTO rules
        FROM knowledge.abox_mapping_rule_versions AS rule
        JOIN knowledge.ontology_elements AS element
          ON element.workspace_id = rule.workspace_id
         AND element.ontology_version_id = rule.ontology_version_id
         AND element.id = rule.target_ontology_element_id
        WHERE rule.workspace_id = p_workspace_id
          AND rule.binding_version_id = binding.id;
        binding_pin_hash := encode(sha256(convert_to(jsonb_build_object(
            'contract', 'STUDIO_INGESTION_BINDING_PIN_V1',
            'job_pin_hash', global_pin_hash,
            'binding_version_id', binding.id,
            'mapping_hash', binding.mapping_hash,
            'source_reference_id', binding.source_reference_id,
            'source_version', binding.source_version,
            'projection_source_version', binding.projection_source_version,
            'selection_hash', binding.selection_hash,
            'profile', profile_pin,
            'rules', rules
        )::text, 'UTF8')), 'hex');
        INSERT INTO knowledge.studio_ingestion_binding_pins (
            id, workspace_id, job_id, ordinal, studio_release_id,
            binding_version_id, source_reference_id, source_asset_id,
            source_version, projection_source_version, source_classification,
            selection_hash, target_class_stable_id,
            target_class_canonical_name, mapping_hash, connection_profile_id,
            connection_profile_version, connection_profile_hash,
            rules_document, pin_hash, created_at
        )
        VALUES (
            gen_random_uuid(), p_workspace_id, job_id, binding.ordinal,
            studio_release.id, binding.id, binding.source_reference_id,
            binding.catalog_asset_id, binding.source_version,
            binding.projection_source_version, binding.source_classification,
            binding.selection_hash, binding.target_stable_element_id,
            binding.target_class_canonical_name, binding.mapping_hash,
            profile_pin ->> 'connection_profile_id',
            (profile_pin ->> 'connection_profile_version')::integer,
            profile_pin ->> 'connection_profile_hash',
            rules, binding_pin_hash, now_at
        );
    END LOOP;
    PERFORM knowledge.append_studio_ingestion_event_v1(
        p_workspace_id, job_id, NULL, 'PENDING', 'REQUESTED',
        actor_id, 'HUMAN', jsonb_build_object('pin_hash', global_pin_hash)
    );
    PERFORM knowledge.emit_studio_ingestion_outbox_v1(
        p_workspace_id, job_id, 'PENDING', 1
    );
    RETURN jsonb_build_object('job_id', job_id::text);
END
$$;
""".strip()

STUDIO_INGESTION_WORKER_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.cancel_studio_ingestion_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_expected_version integer,
    p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam, knowledge
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    now_at timestamptz := transaction_timestamp();
    target_state text;
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR actor_id IS NULL
       OR char_length(COALESCE(btrim(p_reason), '')) NOT BETWEEN 1 AND 500 THEN
        RAISE EXCEPTION 'invalid Studio ingestion cancellation'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO job
    FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    IF NOT FOUND
       OR job.requested_by IS DISTINCT FROM actor_id
       OR job.version <> p_expected_version
       OR NOT knowledge.current_studio_ingestion_human_can_v1(
           p_workspace_id, actor_id,
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state NOT IN ('PENDING','RETRY_WAIT','RUNNING') THEN
        RAISE EXCEPTION 'Studio ingestion cancellation changed concurrently'
            USING ERRCODE = '55000';
    END IF;
    target_state := CASE WHEN job.state = 'RUNNING' THEN 'CANCEL_REQUESTED'
                         ELSE 'CANCELLED' END;
    UPDATE knowledge.studio_ingestion_jobs
    SET state = target_state,
        stage = CASE WHEN target_state = 'CANCELLED' THEN 'COMPLETED' ELSE stage END,
        last_failure_code = NULL,
        cancel_requested_by = actor_id,
        cancel_requested_at = now_at,
        cancel_reason = btrim(p_reason),
        completed_at = CASE WHEN target_state = 'CANCELLED' THEN now_at ELSE NULL END,
        updated_at = now_at,
        version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    RETURNING * INTO job;
    PERFORM knowledge.append_studio_ingestion_event_v1(
        p_workspace_id, p_job_id, job.current_attempt_id, target_state,
        'CANCEL_REQUESTED', actor_id, 'HUMAN',
        jsonb_build_object('reason', btrim(p_reason))
    );
    PERFORM knowledge.emit_studio_ingestion_outbox_v1(
        p_workspace_id, p_job_id, target_state, job.version
    );
    RETURN jsonb_build_object(
        'job_id', p_job_id::text, 'state', target_state, 'version', job.version
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.retry_studio_ingestion_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_expected_version integer
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, iam, knowledge
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    now_at timestamptz := transaction_timestamp();
BEGIN
    IF session_user <> 'datariver_app'
       OR p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR actor_id IS NULL THEN
        RAISE EXCEPTION 'invalid Studio ingestion retry'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO job
    FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    IF NOT FOUND
       OR job.requested_by IS DISTINCT FROM actor_id
       OR job.version <> p_expected_version
       OR NOT knowledge.current_studio_ingestion_human_can_v1(
           p_workspace_id, actor_id,
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state NOT IN ('FAILED','STALE','CANCELLED')
       OR job.attempt_count >= 20 THEN
        RAISE EXCEPTION 'Studio ingestion retry changed concurrently'
            USING ERRCODE = '55000';
    END IF;
    UPDATE knowledge.studio_ingestion_jobs
    SET state = 'RETRY_WAIT', stage = 'QUEUED', progress_percent = 0,
        maximum_attempts = greatest(maximum_attempts, attempt_count + 1),
        next_attempt_at = now_at, last_failure_code = 'MANUAL_RETRY',
        cancel_requested_by = NULL, cancel_requested_at = NULL, cancel_reason = NULL,
        completed_at = NULL, updated_at = now_at, version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    RETURNING * INTO job;
    PERFORM knowledge.append_studio_ingestion_event_v1(
        p_workspace_id, p_job_id, job.current_attempt_id, 'RETRY_WAIT',
        'MANUAL_RETRY', actor_id, 'HUMAN',
        jsonb_build_object('attempt_count', job.attempt_count)
    );
    PERFORM knowledge.emit_studio_ingestion_outbox_v1(
        p_workspace_id, p_job_id, 'RETRY_WAIT', job.version
    );
    RETURN jsonb_build_object(
        'job_id', p_job_id::text, 'state', 'RETRY_WAIT', 'version', job.version
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.claim_studio_ingestion_v1(
    p_workspace_id uuid,
    p_worker_fingerprint text,
    p_lease_token text,
    p_lease_seconds integer
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam, catalog, integration, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    previous_attempt knowledge.studio_ingestion_attempts%ROWTYPE;
    attempt_id uuid := gen_random_uuid();
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    now_at timestamptz := transaction_timestamp();
    token_hash text;
    new_epoch bigint;
    new_attempt integer;
    drift_code text;
    claim_document jsonb;
    workspace_available boolean;
    current_authorization_hash text;
BEGIN
    IF char_length(COALESCE(p_worker_fingerprint, '')) NOT BETWEEN 1 AND 255
       OR p_worker_fingerprint IS DISTINCT FROM btrim(p_worker_fingerprint)
       OR char_length(COALESCE(p_lease_token, '')) NOT BETWEEN 32 AND 200
       OR p_lease_seconds NOT BETWEEN 60 AND 3600
       OR NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute', 0, NULL
       ) THEN
        RAISE EXCEPTION 'invalid Studio ingestion claim'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO job
    FROM knowledge.studio_ingestion_jobs AS candidate
    WHERE candidate.workspace_id = p_workspace_id
      AND candidate.state IN ('RUNNING','CANCEL_REQUESTED')
      AND candidate.lease_expires_at <= now_at
      AND knowledge.current_studio_ingestion_service_can_v1(
          candidate.workspace_id, 'kg.ingestion.execute',
          candidate.graph_classification, candidate.graph_domain_ref_id
      )
    ORDER BY candidate.lease_expires_at, candidate.id
    FOR UPDATE SKIP LOCKED
    LIMIT 1;
    IF FOUND THEN
        SELECT * INTO previous_attempt
        FROM knowledge.studio_ingestion_attempts
        WHERE workspace_id = p_workspace_id AND id = job.current_attempt_id
        FOR UPDATE;
        UPDATE knowledge.studio_ingestion_attempts
        SET state = 'SUPERSEDED', stage = 'COMPLETED',
            retryable = (job.state <> 'CANCEL_REQUESTED'),
            failure_code = 'LEASE_EXPIRED', finished_at = now_at
        WHERE workspace_id = p_workspace_id
          AND id = previous_attempt.id
          AND job_id = job.id
          AND state = 'RUNNING'
          AND lease_epoch = job.lease_epoch
          AND lease_token_hash = job.lease_token_hash;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Studio ingestion expired attempt fence is invalid'
                USING ERRCODE = '55000';
        END IF;
        IF job.state = 'CANCEL_REQUESTED' THEN
            UPDATE knowledge.studio_ingestion_jobs
            SET state = 'CANCELLED', stage = 'COMPLETED',
                lease_token_hash = NULL, lease_owner_fingerprint = NULL,
                lease_started_at = NULL, lease_expires_at = NULL,
                completed_at = now_at, updated_at = now_at, version = version + 1
            WHERE workspace_id = p_workspace_id AND id = job.id
            RETURNING * INTO job;
            PERFORM knowledge.append_studio_ingestion_event_v1(
                p_workspace_id, job.id, previous_attempt.id, 'CANCELLED',
                'CANCELLED_AFTER_LEASE_EXPIRY', actor_id, 'SERVICE',
                jsonb_build_object('lease_epoch', job.lease_epoch)
            );
            PERFORM knowledge.emit_studio_ingestion_outbox_v1(
                p_workspace_id, job.id, 'CANCELLED', job.version
            );
        ELSIF job.attempt_count >= job.maximum_attempts THEN
            UPDATE knowledge.studio_ingestion_jobs
            SET state = 'STALE', stage = 'COMPLETED',
                last_failure_code = 'LEASE_EXHAUSTED',
                lease_token_hash = NULL, lease_owner_fingerprint = NULL,
                lease_started_at = NULL, lease_expires_at = NULL,
                completed_at = now_at, updated_at = now_at, version = version + 1
            WHERE workspace_id = p_workspace_id AND id = job.id
            RETURNING * INTO job;
            PERFORM knowledge.append_studio_ingestion_event_v1(
                p_workspace_id, job.id, previous_attempt.id, 'STALE',
                'LEASE_EXHAUSTED', actor_id, 'SERVICE',
                jsonb_build_object('lease_epoch', job.lease_epoch)
            );
            PERFORM knowledge.emit_studio_ingestion_outbox_v1(
                p_workspace_id, job.id, 'STALE', job.version
            );
        ELSE
            UPDATE knowledge.studio_ingestion_jobs
            SET state = 'RETRY_WAIT', stage = 'QUEUED', progress_percent = 0,
                next_attempt_at = now_at + interval '5 seconds',
                last_failure_code = 'LEASE_EXPIRED',
                lease_token_hash = NULL, lease_owner_fingerprint = NULL,
                lease_started_at = NULL, lease_expires_at = NULL,
                updated_at = now_at, version = version + 1
            WHERE workspace_id = p_workspace_id AND id = job.id
            RETURNING * INTO job;
            PERFORM knowledge.append_studio_ingestion_event_v1(
                p_workspace_id, job.id, previous_attempt.id, 'RETRY_WAIT',
                'LEASE_EXPIRED', actor_id, 'SERVICE',
                jsonb_build_object('lease_epoch', job.lease_epoch)
            );
            PERFORM knowledge.emit_studio_ingestion_outbox_v1(
                p_workspace_id, job.id, 'RETRY_WAIT', job.version
            );
        END IF;
    END IF;
    SELECT * INTO job
    FROM knowledge.studio_ingestion_jobs AS candidate
    WHERE candidate.workspace_id = p_workspace_id
      AND candidate.state IN ('PENDING','RETRY_WAIT')
      AND candidate.next_attempt_at <= now_at
      AND knowledge.current_studio_ingestion_service_can_v1(
          candidate.workspace_id, 'kg.ingestion.execute',
          candidate.graph_classification, candidate.graph_domain_ref_id
      )
    ORDER BY candidate.next_attempt_at, candidate.created_at, candidate.id
    FOR UPDATE SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           job.graph_classification, job.graph_domain_ref_id
       ) THEN
        RETURN NULL;
    END IF;
    SELECT true INTO workspace_available
    FROM platform.workspaces
    WHERE id = p_workspace_id AND status = 'ACTIVE'
    FOR SHARE;
    PERFORM 1 FROM knowledge.graphs
    WHERE workspace_id = job.workspace_id AND id = job.graph_id
    FOR SHARE;
    PERFORM 1 FROM knowledge.studio_releases
    WHERE workspace_id = job.workspace_id
      AND graph_id = job.graph_id
      AND id = job.studio_release_id
    FOR SHARE;
    PERFORM 1 FROM knowledge.ontology_versions
    WHERE workspace_id = job.workspace_id
      AND graph_id = job.graph_id
      AND id = job.ontology_version_id
    FOR SHARE;
    IF job.base_release_id IS NOT NULL THEN
        PERFORM 1 FROM knowledge.releases
        WHERE workspace_id = job.workspace_id
          AND graph_id = job.graph_id
          AND id = job.base_release_id
        FOR SHARE;
    END IF;
    PERFORM 1
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = job.workspace_id
      AND membership.subject_id = job.requested_by
    FOR SHARE OF membership, subject;
    SELECT encode(sha256(convert_to(jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_INGESTION_REQUEST_AUTHORIZATION_DB_V1',
        'workspace_id', membership.workspace_id,
        'subject_id', membership.subject_id,
        'subject_active', subject.active,
        'membership_active', membership.active,
        'access_expires_at', membership.access_expires_at,
        'job_function', membership.job_function,
        'clearance', membership.clearance,
        'attributes', membership.attributes
    )::text, 'UTF8')), 'hex')
    INTO current_authorization_hash
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = job.workspace_id
      AND membership.subject_id = job.requested_by;
    SELECT CASE
        WHEN NOT COALESCE(workspace_available, false)
        THEN 'STALE_WORKSPACE'
        WHEN graph.id IS NULL
          OR graph.version <> job.graph_version
          OR graph.status <> 'PUBLISHED'
          OR graph.classification <> job.graph_classification
          OR graph.domain_ref_id IS DISTINCT FROM job.graph_domain_ref_id
          OR graph.domain_source_version IS DISTINCT FROM job.graph_domain_source_version
          OR graph.active_studio_release_id IS DISTINCT FROM job.studio_release_id
          OR graph.active_release_id IS DISTINCT FROM job.base_release_id
        THEN 'STALE_GRAPH'
        WHEN studio_release.id IS NULL
          OR studio_release.state <> 'ACTIVE'
          OR studio_release.contract_hash <> job.studio_contract_hash
          OR studio_release.ontology_version_id <> job.ontology_version_id
        THEN 'STALE_STUDIO_RELEASE'
        WHEN ontology.id IS NULL OR ontology.checksum <> job.ontology_checksum
        THEN 'STALE_ONTOLOGY'
        WHEN job.base_release_id IS NOT NULL
          AND (base_release.id IS NULL OR base_release.content_hash <> job.base_release_hash)
        THEN 'STALE_BASE_RELEASE'
        WHEN NOT (
            COALESCE(subject.active, false)
            AND COALESCE(membership.active, false)
            AND (
                membership.access_expires_at IS NULL
                OR membership.access_expires_at > now_at
            )
            AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
            AND membership.clearance >= job.graph_classification
            AND COALESCE(
                membership.attributes -> 'allowed_actions', '[]'::jsonb
            ) ? 'kg.edit'
            AND NOT (
                COALESCE(
                    membership.attributes -> 'denied_actions', '[]'::jsonb
                ) ? 'kg.edit'
            )
            AND (
                job.graph_classification = 0
                OR job.graph_domain_ref_id IS NULL
                OR COALESCE(
                    membership.attributes -> 'allowed_domain_ids', '[]'::jsonb
                ) ? job.graph_domain_ref_id::text
            )
        )
        THEN 'STALE_REQUESTER_AUTHORIZATION'
        WHEN current_authorization_hash IS DISTINCT FROM
             job.requester_authorization_hash
        THEN 'STALE_REQUESTER_AUTHORIZATION'
        ELSE NULL
    END INTO drift_code
    FROM knowledge.graphs AS graph
    LEFT JOIN knowledge.studio_releases AS studio_release
      ON studio_release.workspace_id = graph.workspace_id
     AND studio_release.graph_id = graph.id
     AND studio_release.id = job.studio_release_id
    LEFT JOIN knowledge.ontology_versions AS ontology
      ON ontology.workspace_id = graph.workspace_id
     AND ontology.graph_id = graph.id
     AND ontology.id = job.ontology_version_id
    LEFT JOIN knowledge.releases AS base_release
      ON base_release.workspace_id = graph.workspace_id
     AND base_release.graph_id = graph.id
     AND base_release.id = job.base_release_id
    LEFT JOIN iam.workspace_memberships AS membership
      ON membership.workspace_id = job.workspace_id
     AND membership.subject_id = job.requested_by
    LEFT JOIN iam.subjects AS subject ON subject.id = job.requested_by
    WHERE graph.workspace_id = job.workspace_id AND graph.id = job.graph_id;
    IF NOT FOUND THEN
        drift_code := 'STALE_GRAPH';
    END IF;
    IF drift_code IS NOT NULL THEN
        UPDATE knowledge.studio_ingestion_jobs
        SET state = 'STALE', stage = 'COMPLETED',
            last_failure_code = drift_code, completed_at = now_at,
            updated_at = now_at, version = version + 1
        WHERE workspace_id = p_workspace_id AND id = job.id
        RETURNING * INTO job;
        PERFORM knowledge.append_studio_ingestion_event_v1(
            p_workspace_id, job.id, job.current_attempt_id, 'STALE',
            drift_code, actor_id, 'SERVICE', '{}'::jsonb
        );
        PERFORM knowledge.emit_studio_ingestion_outbox_v1(
            p_workspace_id, job.id, 'STALE', job.version
        );
        RETURN NULL;
    END IF;
    token_hash := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    new_epoch := job.lease_epoch + 1;
    new_attempt := job.attempt_count + 1;
    INSERT INTO knowledge.studio_ingestion_attempts (
        id, workspace_id, job_id, attempt_no, lease_epoch, lease_token_hash,
        worker_fingerprint, state, stage, claimed_at, lease_expires_at,
        source_access_started_at, source_access_deadline,
        source_read_receipt_hash, materialization_hash, result_evidence_hash,
        retryable, failure_code, finished_at
    )
    VALUES (
        attempt_id, p_workspace_id, job.id, new_attempt, new_epoch, token_hash,
        p_worker_fingerprint, 'RUNNING', 'SOURCE_READ', now_at,
        now_at + make_interval(secs => p_lease_seconds),
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
    );
    UPDATE knowledge.studio_ingestion_jobs
    SET state = 'RUNNING', stage = 'SOURCE_READ', progress_percent = 10,
        attempt_count = new_attempt, current_attempt_id = attempt_id,
        lease_epoch = new_epoch, lease_token_hash = token_hash,
        lease_owner_fingerprint = p_worker_fingerprint,
        lease_started_at = now_at,
        lease_expires_at = now_at + make_interval(secs => p_lease_seconds),
        source_access_started_at = NULL, source_access_deadline = NULL,
        last_failure_code = NULL, updated_at = now_at, version = version + 1
    WHERE workspace_id = p_workspace_id AND id = job.id
    RETURNING * INTO job;
    PERFORM knowledge.append_studio_ingestion_event_v1(
        p_workspace_id, job.id, attempt_id, 'RUNNING', 'WORKER_CLAIMED',
        actor_id, 'SERVICE', jsonb_build_object(
            'attempt_no', new_attempt, 'lease_epoch', new_epoch,
            'worker_fingerprint', p_worker_fingerprint
        )
    );
    SELECT jsonb_build_object(
        'workspace_id', job.workspace_id::text,
        'job_id', job.id::text,
        'graph_id', job.graph_id::text,
        'draft_id', job.draft_id::text,
        'studio_release_id', job.studio_release_id::text,
        'ontology_version_id', job.ontology_version_id::text,
        'requested_by', job.requested_by::text,
        'graph_classification', job.graph_classification,
        'manifest_id', job.manifest_id,
        'manifest_version', job.manifest_version,
        'manifest_hash', job.manifest_hash,
        'pin_hash', job.pin_hash,
        'embedding_binding', job.embedding_binding_document,
        'bindings', (
            SELECT jsonb_agg(jsonb_build_object(
                'pin_id', pin.id::text,
                'binding_version_id', pin.binding_version_id::text,
                'source_reference_id', pin.source_reference_id::text,
                'source_asset_id', pin.source_asset_id::text,
                'source_version', pin.source_version,
                'projection_source_version', pin.projection_source_version,
                'source_classification', pin.source_classification,
                'target_class_stable_id', pin.target_class_stable_id,
                'target_class_canonical_name', pin.target_class_canonical_name,
                'mapping_hash', pin.mapping_hash,
                'connection_profile_id', pin.connection_profile_id,
                'connection_profile_version', pin.connection_profile_version,
                'connection_profile_hash', pin.connection_profile_hash,
                'rules', pin.rules_document
            ) ORDER BY pin.ordinal)
            FROM knowledge.studio_ingestion_binding_pins AS pin
            WHERE pin.workspace_id = job.workspace_id AND pin.job_id = job.id
        ),
        'attempt_id', attempt_id::text,
        'attempt_no', new_attempt,
        'lease_epoch', new_epoch,
        'worker_fingerprint', p_worker_fingerprint
    ) INTO claim_document;
    RETURN claim_document;
END
$$;
""".strip()

STUDIO_INGESTION_FINALIZATION_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION knowledge.current_studio_ingestion_lease_matches_v1(
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
        FROM knowledge.studio_ingestion_jobs AS job
        JOIN knowledge.studio_ingestion_attempts AS attempt
          ON attempt.workspace_id = job.workspace_id
         AND attempt.job_id = job.id
         AND attempt.id = job.current_attempt_id
        WHERE job.workspace_id = p_workspace_id
          AND job.id = p_job_id
          AND attempt.id = p_attempt_id
          AND job.lease_epoch = p_lease_epoch
          AND attempt.lease_epoch = p_lease_epoch
          AND job.lease_token_hash = encode(
              sha256(convert_to(p_lease_token, 'UTF8')), 'hex'
          )
          AND attempt.lease_token_hash = job.lease_token_hash
          AND attempt.worker_fingerprint = job.lease_owner_fingerprint
          AND job.lease_owner_fingerprint = p_worker_fingerprint
          AND attempt.state = 'RUNNING'
    )
$$;

CREATE OR REPLACE FUNCTION knowledge.freeze_studio_ingestion_source_access_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_hard_timeout_seconds integer,
    p_completion_margin_seconds integer
)
RETURNS timestamptz
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    now_at timestamptz := clock_timestamp();
    deadline timestamptz;
BEGIN
    SELECT * INTO job
    FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= now_at
       OR job.source_access_deadline IS NOT NULL
       OR p_hard_timeout_seconds NOT BETWEEN 1 AND 3600
       OR p_completion_margin_seconds NOT BETWEEN 1 AND 600 THEN
        RAISE EXCEPTION 'invalid Studio source-access freeze'
            USING ERRCODE = '55000';
    END IF;
    deadline := least(
        now_at + make_interval(secs => p_hard_timeout_seconds),
        job.lease_expires_at - make_interval(secs => p_completion_margin_seconds)
    );
    IF deadline <= now_at THEN
        RAISE EXCEPTION 'Studio source-access budget is exhausted'
            USING ERRCODE = '57014';
    END IF;
    UPDATE knowledge.studio_ingestion_jobs
    SET source_access_started_at = now_at, source_access_deadline = deadline,
        updated_at = transaction_timestamp(), version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id;
    UPDATE knowledge.studio_ingestion_attempts
    SET source_access_started_at = now_at, source_access_deadline = deadline
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND job_id = p_job_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Studio source-access attempt is unavailable'
            USING ERRCODE = '55000';
    END IF;
    RETURN deadline;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.assert_studio_ingestion_source_statement_fence_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text
)
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    now_at timestamptz := clock_timestamp();
    remaining integer;
BEGIN
    SELECT * INTO job
    FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= now_at
       OR job.source_access_deadline IS NULL
       OR job.source_access_deadline <= now_at THEN
        RAISE EXCEPTION 'Studio source statement is outside its fence'
            USING ERRCODE = '57014';
    END IF;
    remaining := floor(
        extract(epoch FROM (job.source_access_deadline - now_at)) * 1000
    )::integer;
    RETURN greatest(1, remaining);
END
$$;

CREATE OR REPLACE FUNCTION knowledge.renew_studio_ingestion_v1(
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
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    now_at timestamptz := clock_timestamp();
    new_expiry timestamptz;
BEGIN
    SELECT * INTO job
    FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= now_at
       OR p_lease_seconds NOT BETWEEN 60 AND 3600
       OR p_stage NOT IN ('MAPPING','EMBEDDING','FINALIZING')
       OR p_progress_percent NOT BETWEEN 20 AND 99
       OR p_progress_percent < job.progress_percent
       OR (
           CASE p_stage
               WHEN 'MAPPING' THEN 2
               WHEN 'EMBEDDING' THEN 3
               WHEN 'FINALIZING' THEN 4
               ELSE 0
           END
           <
           CASE job.stage
               WHEN 'SOURCE_READ' THEN 1
               WHEN 'MAPPING' THEN 2
               WHEN 'EMBEDDING' THEN 3
               WHEN 'FINALIZING' THEN 4
               ELSE 5
           END
       ) THEN
        RAISE EXCEPTION 'invalid Studio ingestion renewal'
            USING ERRCODE = '55000';
    END IF;
    new_expiry := now_at + make_interval(secs => p_lease_seconds);
    UPDATE knowledge.studio_ingestion_jobs
    SET stage = p_stage, progress_percent = p_progress_percent,
        lease_started_at = now_at, lease_expires_at = new_expiry,
        updated_at = transaction_timestamp(), version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id;
    UPDATE knowledge.studio_ingestion_attempts
    SET stage = p_stage, lease_expires_at = new_expiry
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND job_id = p_job_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Studio ingestion renewal attempt is unavailable'
            USING ERRCODE = '55000';
    END IF;
    RETURN new_expiry;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.ensure_studio_ingestion_current_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_manifest_id text,
    p_manifest_version integer,
    p_manifest_hash text,
    p_embedding_binding jsonb
)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, iam, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    graph knowledge.graphs%ROWTYPE;
    studio_release knowledge.studio_releases%ROWTYPE;
    ontology knowledge.ontology_versions%ROWTYPE;
    base_release knowledge.releases%ROWTYPE;
    membership iam.workspace_memberships%ROWTYPE;
    subject iam.subjects%ROWTYPE;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    current_authorization_hash text;
BEGIN
    SELECT * INTO job FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'Studio ingestion claim is stale'
            USING ERRCODE = '55000';
    END IF;
    IF job.manifest_id <> p_manifest_id
       OR job.manifest_version <> p_manifest_version
       OR job.manifest_hash <> p_manifest_hash THEN
        RETURN 'STALE_SOURCE_MANIFEST';
    END IF;
    IF job.embedding_binding_document IS DISTINCT FROM p_embedding_binding THEN
        RETURN 'STALE_EMBEDDING_BINDING';
    END IF;
    SELECT * INTO graph FROM knowledge.graphs
    WHERE workspace_id = p_workspace_id AND id = job.graph_id;
    SELECT * INTO studio_release FROM knowledge.studio_releases
    WHERE workspace_id = p_workspace_id AND graph_id = job.graph_id
      AND id = job.studio_release_id;
    SELECT * INTO ontology FROM knowledge.ontology_versions
    WHERE workspace_id = p_workspace_id AND graph_id = job.graph_id
      AND id = job.ontology_version_id;
    SELECT * INTO base_release FROM knowledge.releases
    WHERE workspace_id = p_workspace_id AND graph_id = job.graph_id
      AND id = job.base_release_id;
    SELECT * INTO membership FROM iam.workspace_memberships
    WHERE workspace_id = p_workspace_id AND subject_id = job.requested_by;
    SELECT * INTO subject FROM iam.subjects WHERE id = job.requested_by;
    IF graph.id IS NULL
       OR graph.version <> job.graph_version
       OR graph.status <> 'PUBLISHED'
       OR graph.classification <> job.graph_classification
       OR graph.domain_ref_id IS DISTINCT FROM job.graph_domain_ref_id
       OR graph.domain_source_version IS DISTINCT FROM job.graph_domain_source_version
       OR graph.active_studio_release_id IS DISTINCT FROM job.studio_release_id
       OR graph.active_release_id IS DISTINCT FROM job.base_release_id THEN
        RETURN 'STALE_GRAPH';
    END IF;
    IF studio_release.id IS NULL
       OR studio_release.state <> 'ACTIVE'
       OR studio_release.contract_hash <> job.studio_contract_hash
       OR studio_release.ontology_version_id <> job.ontology_version_id THEN
        RETURN 'STALE_STUDIO_RELEASE';
    END IF;
    IF ontology.id IS NULL OR ontology.checksum <> job.ontology_checksum THEN
        RETURN 'STALE_ONTOLOGY';
    END IF;
    IF job.base_release_id IS NOT NULL
       AND (
           base_release.id IS NULL
           OR base_release.content_hash <> job.base_release_hash
       ) THEN
        RETURN 'STALE_BASE_RELEASE';
    END IF;
    SELECT encode(sha256(convert_to(jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_INGESTION_REQUEST_AUTHORIZATION_DB_V1',
        'workspace_id', membership.workspace_id,
        'subject_id', membership.subject_id,
        'subject_active', subject.active,
        'membership_active', membership.active,
        'access_expires_at', membership.access_expires_at,
        'job_function', membership.job_function,
        'clearance', membership.clearance,
        'attributes', membership.attributes
    )::text, 'UTF8')), 'hex')
    INTO current_authorization_hash;
    IF subject.id IS NULL OR membership.subject_id IS NULL
       OR NOT subject.active OR NOT membership.active
       OR (
           membership.access_expires_at IS NOT NULL
           AND membership.access_expires_at <= transaction_timestamp()
       )
       OR COALESCE(membership.job_function, '') = 'SERVICE_ACCOUNT'
       OR membership.clearance < job.graph_classification
       OR NOT (
           COALESCE(
               membership.attributes -> 'allowed_actions', '[]'::jsonb
           ) ? 'kg.edit'
       )
       OR (
           COALESCE(
               membership.attributes -> 'denied_actions', '[]'::jsonb
           ) ? 'kg.edit'
       )
       OR (
           job.graph_classification <> 0
           AND job.graph_domain_ref_id IS NOT NULL
           AND NOT (
               COALESCE(
                   membership.attributes -> 'allowed_domain_ids', '[]'::jsonb
               ) ? job.graph_domain_ref_id::text
           )
       )
       OR current_authorization_hash <> job.requester_authorization_hash THEN
        RETURN 'STALE_REQUESTER_AUTHORIZATION';
    END IF;
    RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.begin_studio_ingestion_completion_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    changeset_id uuid := gen_random_uuid();
BEGIN
    SELECT * INTO job FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR job.stage <> 'FINALIZING'
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= clock_timestamp()
       OR job.source_access_deadline IS NULL
       OR EXISTS (
           SELECT 1 FROM knowledge.changesets
           WHERE workspace_id = p_workspace_id
             AND studio_ingestion_job_id = p_job_id
       ) THEN
        RAISE EXCEPTION 'invalid Studio ingestion completion start'
            USING ERRCODE = '55000';
    END IF;
    INSERT INTO knowledge.changesets (
        id, workspace_id, graph_id, base_release_id, ontology_version_id,
        title, state, author_id, source_analysis_job_id,
        studio_ingestion_job_id, reviewed_by, reviewed_at, review_reason,
        published_release_id, created_at, updated_at, version
    )
    VALUES (
        changeset_id, p_workspace_id, job.graph_id, job.base_release_id,
        job.ontology_version_id,
        'Studio DB ingestion ' || left(job.id::text, 8),
        'DRAFT', job.requested_by, NULL, job.id,
        NULL, NULL, NULL, NULL, transaction_timestamp(), transaction_timestamp(), 1
    );
    RETURN changeset_id;
END
$$;

CREATE OR REPLACE FUNCTION knowledge.append_studio_ingestion_result_batch_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_changeset_id uuid,
    p_operations jsonb,
    p_vectors jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    operation jsonb;
    vector_item jsonb;
    provenance_item jsonb;
    property_name text;
    property_value jsonb;
    property_rule jsonb;
    vector_property_value jsonb;
    binding_pin knowledge.studio_ingestion_binding_pins%ROWTYPE;
    property_element knowledge.ontology_elements%ROWTYPE;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    operation_count integer;
    vector_count integer;
    calculated_vector_hash text;
BEGIN
    SELECT * INTO job FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    operation_count := CASE WHEN jsonb_typeof(p_operations) = 'array'
                            THEN jsonb_array_length(p_operations) ELSE -1 END;
    vector_count := CASE WHEN jsonb_typeof(p_vectors) = 'array'
                         THEN jsonb_array_length(p_vectors) ELSE -1 END;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR job.stage <> 'FINALIZING'
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= clock_timestamp()
       OR operation_count NOT BETWEEN 0 AND 500
       OR vector_count NOT BETWEEN 0 AND 500
       OR operation_count + vector_count < 1
       OR octet_length(p_operations::text) > 4194304
       OR octet_length(p_vectors::text) > 16777216
       OR NOT EXISTS (
           SELECT 1 FROM knowledge.changesets
           WHERE workspace_id = p_workspace_id
             AND graph_id = job.graph_id
             AND id = p_changeset_id
             AND studio_ingestion_job_id = p_job_id
             AND ontology_version_id = job.ontology_version_id
             AND state = 'DRAFT'
       ) THEN
        RAISE EXCEPTION 'invalid Studio ingestion result batch'
            USING ERRCODE = '55000';
    END IF;
    FOR operation IN SELECT value FROM jsonb_array_elements(p_operations)
    LOOP
        IF jsonb_typeof(operation) <> 'object'
           OR (operation - ARRAY[
               'sequence','operation','entity_kind','stable_entity_id',
               'document','provenance','confidence'
           ]) <> '{}'::jsonb
           OR (operation ->> 'sequence') !~ '^[1-9][0-9]*$'
           OR (operation ->> 'sequence')::integer > 100000
           OR operation ->> 'operation' <> 'UPSERT'
           OR operation ->> 'entity_kind' <> 'NODE'
           OR jsonb_typeof(operation -> 'document') <> 'object'
           OR jsonb_typeof(operation -> 'provenance') <> 'array'
           OR jsonb_array_length(operation -> 'provenance') <> 1
           OR (
               (operation -> 'document') - ARRAY[
                   'entity_type','properties','classification'
               ]
           ) <> '{}'::jsonb
           OR jsonb_typeof(operation -> 'document' -> 'properties') <> 'object'
           OR (operation -> 'document' ->> 'classification') !~ '^[0-3]$'
           OR (operation -> 'document' ->> 'classification')::integer
                > job.graph_classification
           OR (operation ->> 'confidence')::numeric <> 1 THEN
            RAISE EXCEPTION 'invalid Studio typed operation'
                USING ERRCODE = '23514';
        END IF;
        provenance_item := operation -> 'provenance' -> 0;
        IF jsonb_typeof(provenance_item) <> 'object'
           OR (
               provenance_item - ARRAY[
                   'source_ref','source_locator','source_version',
                   'method','confidence'
               ]
           ) <> '{}'::jsonb
           OR provenance_item ->> 'source_ref'
                !~ '^knowledge-studio-binding:[0-9a-f-]{36}$'
           OR provenance_item ->> 'method' <> 'DB_MAPPING_IDENTITY_V1'
           OR (provenance_item ->> 'confidence')::numeric <> 1 THEN
            RAISE EXCEPTION 'invalid Studio operation provenance'
                USING ERRCODE = '23514';
        END IF;
        SELECT * INTO binding_pin
        FROM knowledge.studio_ingestion_binding_pins AS candidate
        WHERE candidate.workspace_id = p_workspace_id
          AND candidate.job_id = p_job_id
          AND candidate.binding_version_id::text =
              substr(
                  provenance_item ->> 'source_ref',
                  char_length('knowledge-studio-binding:') + 1
              )
          AND candidate.target_class_canonical_name =
              operation -> 'document' ->> 'entity_type';
        IF NOT FOUND
           OR (operation -> 'document' ->> 'classification')::integer
                <> binding_pin.source_classification
           OR provenance_item ->> 'source_version' <>
                binding_pin.source_version || '@' ||
                binding_pin.projection_source_version
           OR provenance_item ->> 'source_locator' !~
                (
                    '^catalog-asset:' || binding_pin.source_asset_id::text ||
                    '#identity-sha256=[0-9a-f]{64}$'
                )
           OR EXISTS (
               SELECT 1
               FROM jsonb_each(
                   operation -> 'document' -> 'properties'
               ) AS property(name, value)
               WHERE NOT EXISTS (
                   SELECT 1
                   FROM jsonb_array_elements(binding_pin.rules_document) AS rule
                   WHERE rule ->> 'method' = 'PROPERTY'
                     AND rule ->> 'target_canonical_name' = property.name
               )
           )
           OR EXISTS (
               SELECT 1
               FROM jsonb_array_elements(binding_pin.rules_document) AS rule
               WHERE rule ->> 'method' = 'PROPERTY'
                 AND (rule ->> 'target_nullable')::boolean IS FALSE
                 AND NOT (
                     operation -> 'document' -> 'properties'
                     ? (rule ->> 'target_canonical_name')
                 )
           ) THEN
            RAISE EXCEPTION 'Studio operation is outside its released Binding'
                USING ERRCODE = '23514';
        END IF;
        FOR property_name, property_value IN
            SELECT key, value
            FROM jsonb_each(operation -> 'document' -> 'properties')
        LOOP
            SELECT rule INTO property_rule
            FROM jsonb_array_elements(binding_pin.rules_document) AS rule
            WHERE rule ->> 'method' = 'PROPERTY'
              AND rule ->> 'target_canonical_name' = property_name;
            IF property_rule IS NULL
               OR jsonb_typeof(property_value)
                    NOT IN ('string','number','boolean') THEN
                RAISE EXCEPTION 'Studio operation Property is not a typed Mapping'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;
        INSERT INTO knowledge.change_operations (
            id, workspace_id, changeset_id, sequence, operation, entity_kind,
            stable_entity_id, document, provenance, confidence
        )
        VALUES (
            gen_random_uuid(), p_workspace_id, p_changeset_id,
            (operation ->> 'sequence')::integer,
            operation ->> 'operation', operation ->> 'entity_kind',
            (operation ->> 'stable_entity_id')::uuid,
            operation -> 'document', operation -> 'provenance',
            (operation ->> 'confidence')::double precision
        );
    END LOOP;
    FOR vector_item IN SELECT value FROM jsonb_array_elements(p_vectors)
    LOOP
        IF job.embedding_binding_hash IS NULL
           OR jsonb_typeof(vector_item) <> 'object'
           OR (vector_item - ARRAY[
               'entity_id','property_stable_id','content_hash',
               'dimension','vector','vector_hash'
           ]) <> '{}'::jsonb
           OR vector_item ->> 'content_hash' !~ '^[0-9a-f]{64}$'
           OR vector_item ->> 'vector_hash' !~ '^[0-9a-f]{64}$'
           OR (vector_item ->> 'dimension') !~ '^[1-9][0-9]*$'
           OR (vector_item ->> 'dimension')::integer NOT BETWEEN 1 AND 16384
           OR jsonb_typeof(vector_item -> 'vector') <> 'array'
           OR jsonb_array_length(vector_item -> 'vector')
                <> (vector_item ->> 'dimension')::integer
           OR EXISTS (
               SELECT 1
               FROM jsonb_array_elements_text(vector_item -> 'vector') AS item(value)
               WHERE item.value::numeric NOT BETWEEN -1e100::numeric AND 1e100::numeric
           ) THEN
            RAISE EXCEPTION 'invalid Studio vector receipt'
                USING ERRCODE = '23514';
        END IF;
        calculated_vector_hash := encode(sha256(convert_to(
            replace((vector_item -> 'vector')::text, ', ', ','), 'UTF8'
        )), 'hex');
        IF calculated_vector_hash <> vector_item ->> 'vector_hash' THEN
            RAISE EXCEPTION 'Studio vector receipt hash mismatch'
                USING ERRCODE = '23514';
        END IF;
        SELECT * INTO property_element
        FROM knowledge.ontology_elements
        WHERE workspace_id = p_workspace_id
          AND ontology_version_id = job.ontology_version_id
          AND stable_element_id = vector_item ->> 'property_stable_id'
          AND kind = 'PROPERTY';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Studio vector Property is outside the ontology'
                USING ERRCODE = '23514';
        END IF;
        SELECT operation.document -> 'properties' ->
                   (rule ->> 'target_canonical_name')
        INTO vector_property_value
        FROM knowledge.studio_ingestion_binding_pins AS pin
        CROSS JOIN LATERAL jsonb_array_elements(pin.rules_document) AS rule
        JOIN knowledge.change_operations AS operation
          ON operation.workspace_id = pin.workspace_id
         AND operation.changeset_id = p_changeset_id
         AND operation.stable_entity_id =
             (vector_item ->> 'entity_id')::uuid
         AND operation.document ->> 'entity_type' =
             pin.target_class_canonical_name
        WHERE pin.workspace_id = p_workspace_id
          AND pin.job_id = p_job_id
          AND rule ->> 'method' = 'PROPERTY'
          AND rule ->> 'target_stable_element_id' =
              vector_item ->> 'property_stable_id'
          AND (rule ->> 'vector_index_enabled')::boolean IS TRUE
        LIMIT 1;
        IF NOT FOUND
           OR jsonb_typeof(vector_property_value) <> 'string'
           OR encode(sha256(convert_to(
               regexp_replace(
                   btrim(vector_property_value #>> '{}'),
                   '[[:space:]]+', ' ', 'g'
               ),
               'UTF8'
           )), 'hex') <> vector_item ->> 'content_hash' THEN
            RAISE EXCEPTION 'Studio vector is outside its released Mapping'
                USING ERRCODE = '23514';
        END IF;
        INSERT INTO knowledge.studio_ingestion_vector_receipts (
            id, workspace_id, job_id, attempt_id, changeset_id,
            ontology_version_id, property_ontology_element_id, entity_id,
            property_stable_id, content_hash, embedding_binding_hash,
            dimension, vector_document, vector_hash, created_at
        )
        VALUES (
            gen_random_uuid(), p_workspace_id, p_job_id, p_attempt_id,
            p_changeset_id, job.ontology_version_id, property_element.id,
            (vector_item ->> 'entity_id')::uuid,
            vector_item ->> 'property_stable_id',
            vector_item ->> 'content_hash', job.embedding_binding_hash,
            (vector_item ->> 'dimension')::integer,
            vector_item -> 'vector', vector_item ->> 'vector_hash',
            transaction_timestamp()
        );
    END LOOP;
    RETURN jsonb_build_object(
        'operation_count', operation_count,
        'vector_receipt_count', vector_count
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.complete_studio_ingestion_v1(
    p_workspace_id uuid,
    p_job_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_worker_fingerprint text,
    p_changeset_id uuid,
    p_source_read_receipt_hash text,
    p_result_hash text,
    p_operation_count integer,
    p_vector_receipt_count integer,
    p_call_id text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    graph knowledge.graphs%ROWTYPE;
    studio_release knowledge.studio_releases%ROWTYPE;
    ontology knowledge.ontology_versions%ROWTYPE;
    base_release knowledge.releases%ROWTYPE;
    membership iam.workspace_memberships%ROWTYPE;
    subject iam.subjects%ROWTYPE;
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    now_at timestamptz := transaction_timestamp();
    actual_operations integer;
    actual_vectors integer;
    expected_vectors integer;
    minimum_sequence integer;
    maximum_sequence integer;
    current_authorization_hash text;
    workspace_available boolean;
BEGIN
    SELECT * INTO job FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    SELECT * INTO graph FROM knowledge.graphs
    WHERE workspace_id = p_workspace_id AND id = job.graph_id
    FOR SHARE;
    SELECT * INTO studio_release FROM knowledge.studio_releases
    WHERE workspace_id = p_workspace_id AND graph_id = job.graph_id
      AND id = job.studio_release_id
    FOR SHARE;
    SELECT * INTO ontology FROM knowledge.ontology_versions
    WHERE workspace_id = p_workspace_id AND graph_id = job.graph_id
      AND id = job.ontology_version_id
    FOR SHARE;
    SELECT * INTO base_release FROM knowledge.releases
    WHERE workspace_id = p_workspace_id AND graph_id = job.graph_id
      AND id = job.base_release_id
    FOR SHARE;
    SELECT * INTO membership FROM iam.workspace_memberships
    WHERE workspace_id = p_workspace_id AND subject_id = job.requested_by
    FOR SHARE;
    SELECT * INTO subject FROM iam.subjects
    WHERE id = job.requested_by
    FOR SHARE;
    SELECT true INTO workspace_available
    FROM platform.workspaces
    WHERE id = p_workspace_id AND status = 'ACTIVE'
    FOR SHARE;
    SELECT encode(sha256(convert_to(jsonb_build_object(
        'contract', 'KNOWLEDGE_STUDIO_INGESTION_REQUEST_AUTHORIZATION_DB_V1',
        'workspace_id', membership.workspace_id,
        'subject_id', membership.subject_id,
        'subject_active', subject.active,
        'membership_active', membership.active,
        'access_expires_at', membership.access_expires_at,
        'job_function', membership.job_function,
        'clearance', membership.clearance,
        'attributes', membership.attributes
    )::text, 'UTF8')), 'hex')
    INTO current_authorization_hash;
    SELECT count(*), min(sequence), max(sequence)
    INTO actual_operations, minimum_sequence, maximum_sequence
    FROM knowledge.change_operations
    WHERE workspace_id = p_workspace_id AND changeset_id = p_changeset_id;
    SELECT count(*) INTO actual_vectors
    FROM knowledge.studio_ingestion_vector_receipts
    WHERE workspace_id = p_workspace_id AND job_id = p_job_id
      AND changeset_id = p_changeset_id;
    SELECT count(*) INTO expected_vectors
    FROM knowledge.change_operations AS operation
    JOIN knowledge.studio_ingestion_binding_pins AS pin
      ON pin.workspace_id = operation.workspace_id
     AND pin.job_id = p_job_id
     AND pin.binding_version_id::text = substr(
         operation.provenance -> 0 ->> 'source_ref',
         char_length('knowledge-studio-binding:') + 1
     )
     AND pin.target_class_canonical_name =
         operation.document ->> 'entity_type'
    CROSS JOIN LATERAL jsonb_array_elements(pin.rules_document) AS rule
    WHERE operation.workspace_id = p_workspace_id
      AND operation.changeset_id = p_changeset_id
      AND rule ->> 'method' = 'PROPERTY'
      AND (rule ->> 'vector_index_enabled')::boolean IS TRUE
      AND operation.document -> 'properties'
          ? (rule ->> 'target_canonical_name');
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state <> 'RUNNING'
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= clock_timestamp()
       OR job.stage <> 'FINALIZING'
       OR NOT COALESCE(workspace_available, false)
       OR graph.id IS NULL
       OR graph.version <> job.graph_version
       OR graph.status <> 'PUBLISHED'
       OR graph.classification <> job.graph_classification
       OR graph.domain_ref_id IS DISTINCT FROM job.graph_domain_ref_id
       OR graph.domain_source_version IS DISTINCT FROM job.graph_domain_source_version
       OR graph.active_studio_release_id IS DISTINCT FROM job.studio_release_id
       OR graph.active_release_id IS DISTINCT FROM job.base_release_id
       OR studio_release.id IS NULL
       OR studio_release.state <> 'ACTIVE'
       OR studio_release.contract_hash <> job.studio_contract_hash
       OR studio_release.ontology_version_id <> job.ontology_version_id
       OR ontology.id IS NULL
       OR ontology.checksum <> job.ontology_checksum
       OR (
           job.base_release_id IS NOT NULL
           AND (
               base_release.id IS NULL
               OR base_release.content_hash <> job.base_release_hash
           )
       )
       OR subject.id IS NULL
       OR membership.subject_id IS NULL
       OR NOT subject.active
       OR NOT membership.active
       OR (
           membership.access_expires_at IS NOT NULL
           AND membership.access_expires_at <= now_at
       )
       OR COALESCE(membership.job_function, '') = 'SERVICE_ACCOUNT'
       OR membership.clearance < job.graph_classification
       OR NOT (
           COALESCE(
               membership.attributes -> 'allowed_actions', '[]'::jsonb
           ) ? 'kg.edit'
       )
       OR (
           COALESCE(
               membership.attributes -> 'denied_actions', '[]'::jsonb
           ) ? 'kg.edit'
       )
       OR (
           job.graph_classification <> 0
           AND job.graph_domain_ref_id IS NOT NULL
           AND NOT (
               COALESCE(
                   membership.attributes -> 'allowed_domain_ids', '[]'::jsonb
               ) ? job.graph_domain_ref_id::text
           )
       )
       OR current_authorization_hash <> job.requester_authorization_hash
       OR p_source_read_receipt_hash !~ '^[0-9a-f]{64}$'
       OR p_result_hash !~ '^[0-9a-f]{64}$'
       OR char_length(COALESCE(p_call_id, '')) NOT BETWEEN 1 AND 200
       OR p_operation_count NOT BETWEEN 1 AND 100000
       OR p_vector_receipt_count NOT BETWEEN 0 AND 100000
       OR actual_operations <> p_operation_count
       OR actual_vectors <> p_vector_receipt_count
       OR actual_vectors <> expected_vectors
       OR minimum_sequence <> 1
       OR maximum_sequence <> actual_operations
       OR NOT EXISTS (
           SELECT 1 FROM knowledge.changesets
           WHERE workspace_id = p_workspace_id
             AND graph_id = job.graph_id
             AND id = p_changeset_id
             AND studio_ingestion_job_id = p_job_id
             AND ontology_version_id = job.ontology_version_id
             AND base_release_id IS NOT DISTINCT FROM job.base_release_id
             AND author_id = job.requested_by
             AND state = 'DRAFT'
       ) THEN
        RAISE EXCEPTION 'invalid Studio ingestion completion'
            USING ERRCODE = '55000';
    END IF;
    UPDATE knowledge.studio_ingestion_attempts
    SET state = 'SUCCESS', stage = 'COMPLETED',
        source_read_receipt_hash = p_source_read_receipt_hash,
        materialization_hash = p_result_hash,
        result_evidence_hash = p_result_hash,
        retryable = false, failure_code = NULL, finished_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND job_id = p_job_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Studio ingestion completion attempt is unavailable'
            USING ERRCODE = '55000';
    END IF;
    UPDATE knowledge.studio_ingestion_jobs
    SET state = 'SUCCESS', stage = 'COMPLETED', progress_percent = 100,
        result_changeset_id = p_changeset_id,
        result_evidence_hash = p_result_hash,
        source_read_receipt_hash = p_source_read_receipt_hash,
        lease_token_hash = NULL, lease_owner_fingerprint = NULL,
        lease_started_at = NULL, lease_expires_at = NULL,
        completed_at = now_at, updated_at = now_at, version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    RETURNING * INTO job;
    PERFORM knowledge.append_studio_ingestion_event_v1(
        p_workspace_id, p_job_id, p_attempt_id, 'SUCCESS', 'CHANGESET_CREATED',
        actor_id, 'SERVICE', jsonb_build_object(
            'changeset_id', p_changeset_id,
            'result_evidence_hash', p_result_hash,
            'operation_count', p_operation_count,
            'vector_receipt_count', p_vector_receipt_count,
            'call_id', p_call_id
        )
    );
    PERFORM knowledge.emit_studio_ingestion_outbox_v1(
        p_workspace_id, p_job_id, 'SUCCESS', job.version
    );
    RETURN jsonb_build_object(
        'job_id', p_job_id::text,
        'changeset_id', p_changeset_id::text,
        'state', 'SUCCESS',
        'version', job.version
    );
END
$$;

CREATE OR REPLACE FUNCTION knowledge.fail_studio_ingestion_v1(
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
SET search_path = pg_catalog, knowledge
AS $$
DECLARE
    job knowledge.studio_ingestion_jobs%ROWTYPE;
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    token_hash text := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    now_at timestamptz := transaction_timestamp();
    target_state text;
    attempt_state text;
BEGIN
    SELECT * INTO job FROM knowledge.studio_ingestion_jobs
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    FOR UPDATE;
    IF NOT knowledge.current_studio_ingestion_service_can_v1(
           p_workspace_id, 'kg.ingestion.execute',
           COALESCE(job.graph_classification, 0), job.graph_domain_ref_id
       )
       OR job.state NOT IN ('RUNNING','CANCEL_REQUESTED')
       OR job.current_attempt_id IS DISTINCT FROM p_attempt_id
       OR job.lease_epoch <> p_lease_epoch
       OR job.lease_token_hash IS DISTINCT FROM token_hash
       OR job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint
       OR NOT knowledge.current_studio_ingestion_lease_matches_v1(
           p_workspace_id, p_job_id, p_attempt_id, p_lease_epoch, p_lease_token,
           p_worker_fingerprint
       )
       OR job.lease_expires_at <= clock_timestamp()
       OR char_length(COALESCE(p_call_id, '')) NOT BETWEEN 1 AND 200
       OR p_failure_code !~ '^[A-Z0-9_]{1,100}$' THEN
        RAISE EXCEPTION 'invalid Studio ingestion failure'
            USING ERRCODE = '55000';
    END IF;
    target_state := CASE
        WHEN job.state = 'CANCEL_REQUESTED' THEN 'CANCELLED'
        WHEN p_stale THEN 'STALE'
        WHEN p_retryable AND job.attempt_count < job.maximum_attempts THEN 'RETRY_WAIT'
        ELSE 'FAILED'
    END;
    attempt_state := CASE
        WHEN target_state = 'CANCELLED' THEN 'CANCELLED'
        WHEN target_state = 'STALE' THEN 'STALE'
        ELSE 'FAILED'
    END;
    UPDATE knowledge.studio_ingestion_attempts
    SET state = attempt_state, stage = 'COMPLETED',
        retryable = p_retryable, failure_code = p_failure_code,
        finished_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND job_id = p_job_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Studio ingestion failure attempt is unavailable'
            USING ERRCODE = '55000';
    END IF;
    UPDATE knowledge.studio_ingestion_jobs
    SET state = target_state,
        stage = CASE WHEN target_state = 'RETRY_WAIT' THEN 'QUEUED' ELSE 'COMPLETED' END,
        progress_percent = 0,
        next_attempt_at = CASE
            WHEN target_state = 'RETRY_WAIT'
            THEN now_at + make_interval(
                secs => least(60, 5 * (2 ^ attempt_count))::integer
            )
            ELSE next_attempt_at
        END,
        last_failure_code = CASE
            WHEN target_state = 'CANCELLED' THEN NULL ELSE p_failure_code
        END,
        lease_token_hash = NULL, lease_owner_fingerprint = NULL,
        lease_started_at = NULL, lease_expires_at = NULL,
        completed_at = CASE
            WHEN target_state = 'RETRY_WAIT' THEN NULL ELSE now_at
        END,
        updated_at = now_at, version = version + 1
    WHERE workspace_id = p_workspace_id AND id = p_job_id
    RETURNING * INTO job;
    PERFORM knowledge.append_studio_ingestion_event_v1(
        p_workspace_id, p_job_id, p_attempt_id, target_state,
        p_failure_code, actor_id, 'SERVICE',
        jsonb_build_object('call_id', p_call_id, 'retryable', p_retryable)
    );
    PERFORM knowledge.emit_studio_ingestion_outbox_v1(
        p_workspace_id, p_job_id, target_state, job.version
    );
    RETURN jsonb_build_object(
        'job_id', p_job_id::text,
        'state', target_state,
        'version', job.version
    );
END
$$;
""".strip()

STUDIO_INGESTION_ALL_FUNCTION_SQL = "\n\n".join(
    (
        STUDIO_INGESTION_FUNCTION_SQL,
        STUDIO_INGESTION_WORKER_FUNCTION_SQL,
        STUDIO_INGESTION_FINALIZATION_FUNCTION_SQL,
    )
)
