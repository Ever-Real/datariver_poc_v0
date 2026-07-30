"""Add the bounded Quality execution plane.

Revision ID: 0069
Revises: 0068
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATEMENT_BOUNDARY = "-- datariver-statement-boundary"

_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION quality.current_quality_service_can_v1(
    p_workspace_id uuid,
    p_action text,
    p_classification integer DEFAULT 0,
    p_system_id uuid DEFAULT NULL,
    p_domain_id uuid DEFAULT NULL
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam
AS $$
    SELECT p_workspace_id IS NOT DISTINCT FROM
               NULLIF(current_setting('app.workspace_id', true), '')::uuid
       AND (
           (p_action = 'quality.dispatch' AND session_user = 'datariver_app')
           OR (p_action = 'quality.execute' AND session_user = 'datariver_quality')
       )
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
             AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb) =
                 CASE p_action
                     WHEN 'quality.dispatch'
                     THEN '["service-accounts","quality-dispatchers"]'::jsonb
                     WHEN 'quality.execute'
                     THEN '["service-accounts","quality-workers"]'::jsonb
                 END
             AND COALESCE(
                 membership.attributes -> 'allowed_actions', '[]'::jsonb
             ) = jsonb_build_array(p_action)
             AND COALESCE(
                 membership.attributes -> 'denied_actions', '[]'::jsonb
             ) = '[]'::jsonb
             AND membership.clearance >= p_classification
             AND (
                 p_classification = 0
                 OR p_system_id IS NULL
                 OR COALESCE(
                     membership.attributes -> 'allowed_system_ids', '[]'::jsonb
                 ) ? p_system_id::text
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
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.current_quality_service_can_v1(
    uuid, text, integer, uuid, uuid
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.current_quality_target_matches_v1(
    p_workspace_id uuid,
    p_asset_id uuid,
    p_classification integer,
    p_system_id uuid,
    p_domain_id uuid,
    p_lifecycle text,
    p_source_version text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, catalog, quality
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM catalog.assets_projection AS asset
        WHERE asset.workspace_id = p_workspace_id
          AND asset.id = p_asset_id
          AND asset.deleted_at IS NULL
          AND asset.lifecycle = 'ACTIVE'
          AND asset.lifecycle = p_lifecycle
          AND asset.source_version = p_source_version
          AND asset.classification = p_classification
          AND asset.system_id IS NOT DISTINCT FROM p_system_id
          AND asset.domain_id IS NOT DISTINCT FROM p_domain_id
          AND quality.current_quality_service_can_v1(
              asset.workspace_id, 'quality.execute', asset.classification,
              asset.system_id, asset.domain_id
          )
    )
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.current_quality_target_matches_v1(
    uuid, uuid, integer, uuid, uuid, text, text
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.dispatch_due_validation_runs_v1(
    p_workspace_id uuid,
    p_call_id text,
    p_max_due_schedules integer,
    p_max_created_runs integer
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, catalog, retention, integration
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    call_hash text;
    request_hash text;
    result_hash text;
    receipt_id uuid := gen_random_uuid();
    cutoff_at timestamptz := transaction_timestamp();
    selected_schedule quality.rule_schedules%ROWTYPE;
    selected_version quality.rule_set_versions%ROWTYPE;
    result_binding record;
    audit_binding record;
    receipt_binding record;
    run_id uuid;
    created_ids jsonb := '[]'::jsonb;
    created_count integer := 0;
    skipped_count integer := 0;
    interval_seconds integer;
    profile_context_hash text;
    security_context_hash text;
    existing_receipt quality.dispatch_call_receipts%ROWTYPE;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR char_length(COALESCE(p_call_id, '')) NOT BETWEEN 1 AND 200
       OR p_call_id IS DISTINCT FROM btrim(p_call_id)
       OR p_max_due_schedules NOT BETWEEN 1 AND 100
       OR p_max_created_runs NOT BETWEEN 1 AND 100
       OR NOT quality.current_quality_service_can_v1(
           p_workspace_id, 'quality.dispatch', 0, NULL, NULL
       ) THEN
        RAISE EXCEPTION 'invalid Quality dispatch request'
            USING ERRCODE = '42501';
    END IF;
    call_hash := encode(sha256(convert_to(p_call_id, 'UTF8')), 'hex');
    request_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_DISPATCH_REQUEST_V1',
        'workspace_id', p_workspace_id::text,
        'service_subject_id', actor_id::text,
        'call_id_hash', call_hash,
        'max_due_schedules', p_max_due_schedules,
        'max_created_runs', p_max_created_runs
    )::text, 'UTF8')), 'hex');
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_workspace_id::text || ':' || actor_id::text || ':' || call_hash, 0
    ));
    SELECT * INTO existing_receipt
    FROM quality.dispatch_call_receipts AS receipt
    WHERE receipt.workspace_id = p_workspace_id
      AND receipt.service_subject_id = actor_id
      AND receipt.call_id_hash = call_hash;
    IF FOUND THEN
        IF existing_receipt.request_hash <> request_hash THEN
            RAISE EXCEPTION 'Quality dispatch idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        SELECT COALESCE(jsonb_agg(link.run_id::text ORDER BY link.ordinal), '[]'::jsonb)
        INTO created_ids
        FROM quality.dispatch_run_links AS link
        WHERE link.workspace_id = p_workspace_id
          AND link.dispatch_receipt_id = existing_receipt.id;
        RETURN jsonb_build_object(
            'created_run_ids', created_ids,
            'created_run_count', existing_receipt.created_run_count,
            'skipped_window_count', existing_receipt.skipped_window_count,
            'replayed', true
        );
    END IF;

    FOR selected_schedule IN
        SELECT schedule.*
        FROM quality.rule_schedules AS schedule
        JOIN quality.rule_set_versions AS version
          ON version.workspace_id = schedule.workspace_id
         AND version.id = schedule.rule_set_version_id
        WHERE schedule.workspace_id = p_workspace_id
          AND schedule.state = 'ACTIVE'
          AND schedule.next_due_at <= cutoff_at
          AND version.state = 'ACTIVE'
          AND version.schedule_mode = 'SCHEDULED'
        ORDER BY schedule.next_due_at, schedule.id
        FOR UPDATE OF schedule SKIP LOCKED
        LIMIT p_max_due_schedules
    LOOP
        EXIT WHEN created_count >= p_max_created_runs;
        SELECT * INTO selected_version
        FROM quality.rule_set_versions AS version
        WHERE version.workspace_id = p_workspace_id
          AND version.id = selected_schedule.rule_set_version_id
        FOR KEY SHARE;
        interval_seconds := NULL;
        IF jsonb_typeof(selected_schedule.cadence) = 'object'
           AND ARRAY(
               SELECT key FROM jsonb_object_keys(selected_schedule.cadence) AS key
               ORDER BY key COLLATE "C"
           ) = ARRAY['contract','interval_seconds']::text[]
           AND selected_schedule.cadence ->> 'contract' = 'FIXED_INTERVAL_V1'
           AND jsonb_typeof(selected_schedule.cadence -> 'interval_seconds') = 'number'
           AND (selected_schedule.cadence ->> 'interval_seconds')::numeric
               = trunc((selected_schedule.cadence ->> 'interval_seconds')::numeric)
           AND (selected_schedule.cadence ->> 'interval_seconds')::numeric
               BETWEEN 60 AND 2678400 THEN
            interval_seconds :=
                (selected_schedule.cadence ->> 'interval_seconds')::integer;
        END IF;
        IF interval_seconds IS NULL
           OR selected_schedule.current_window_key IS NULL
           OR char_length(selected_schedule.current_window_key) NOT BETWEEN 1 AND 255
           OR selected_version.id IS NULL
           OR NOT EXISTS (
               SELECT 1
               FROM catalog.assets_projection AS asset
               WHERE asset.workspace_id = p_workspace_id
                 AND asset.id = selected_version.asset_id
                 AND asset.deleted_at IS NULL
                 AND asset.lifecycle = selected_version.lifecycle
                 AND asset.source_version = selected_version.source_version
                 AND asset.classification = selected_version.classification
                 AND asset.system_id IS NOT DISTINCT FROM selected_version.system_id
                 AND asset.domain_id IS NOT DISTINCT FROM selected_version.domain_id
           )
           OR NOT EXISTS (
               SELECT 1 FROM quality.rule_definitions AS definition
               WHERE definition.workspace_id = p_workspace_id
                 AND definition.rule_set_version_id = selected_version.id
           ) THEN
            skipped_count := skipped_count + 1;
            CONTINUE;
        END IF;
        run_id := gen_random_uuid();
        SELECT * INTO result_binding
        FROM retention.resolve_quality_binding_v1(
            p_workspace_id, 'QUALITY_RESULT', 'QUALITY_VALIDATION_RUN',
            run_id, cutoff_at
        );
        SELECT * INTO audit_binding
        FROM retention.resolve_quality_binding_v1(
            p_workspace_id, 'QUALITY_AUDIT', 'QUALITY_VALIDATION_RUN',
            run_id, cutoff_at
        );
        SELECT COALESCE(
            (
                SELECT snapshot.snapshot_identity_hash
                FROM catalog.asset_profile_snapshots AS snapshot
                WHERE snapshot.workspace_id = p_workspace_id
                  AND snapshot.asset_id = selected_version.asset_id
                  AND snapshot.asset_source_version = selected_version.source_version
                  AND snapshot.profile_kind IN ('FULL', 'PARTITION')
                  AND snapshot.completeness = 'COMPLETE'
                  AND snapshot.stale_at > cutoff_at
                  AND snapshot.profile_retain_until > cutoff_at
                ORDER BY snapshot.profiled_at DESC, snapshot.id DESC
                LIMIT 1
            ),
            encode(sha256(convert_to(
                'QUALITY_PROFILE_CONTEXT_UNAVAILABLE_V1', 'UTF8'
            )), 'hex')
        ) INTO profile_context_hash;
        security_context_hash := encode(sha256(convert_to(jsonb_build_object(
            'contract', 'QUALITY_SECURITY_CONTEXT_V1',
            'asset_id', selected_version.asset_id::text,
            'classification', selected_version.classification,
            'system_id', selected_version.system_id::text,
            'domain_id', selected_version.domain_id::text,
            'lifecycle', selected_version.lifecycle,
            'source_version', selected_version.source_version
        )::text, 'UTF8')), 'hex');
        INSERT INTO quality.validation_runs (
            id, workspace_id, rule_set_id, rule_set_version_id, asset_id,
            target_binding_hash, schema_hash,
            source_connection_profile_id, source_connection_profile_version,
            source_connection_profile_hash,
            workload_profile_id, workload_profile_version, workload_profile_hash,
            security_context_hash, datahub_profile_context_hash,
            score_policy_id, score_policy_version, score_policy_hash,
            retry_of_run_id, trigger_kind, requested_by,
            schedule_id, schedule_version, canonical_window_key, due_at, is_late,
            state, quality_outcome, score, passed_count,
            advisory_failed_count, blocking_failed_count,
            current_attempt_id, attempt_count, maximum_attempts, next_attempt_at,
            lease_epoch, lease_token_hash, lease_owner_fingerprint, lease_until,
            heartbeat_at, source_started_at, source_access_deadline,
            hard_timeout_contract_hash, completed_at, failure_code,
            result_retention_kind, result_retention_policy_id,
            result_retention_policy_number, result_retention_policy_hash,
            result_retention_basis_at, result_retain_until,
            result_hold_generation, result_hold_hash,
            audit_retention_kind, audit_retention_policy_id,
            audit_retention_policy_number, audit_retention_policy_hash,
            audit_retention_basis_at, audit_retain_until,
            audit_hold_generation, audit_hold_hash,
            created_at, updated_at, version
        )
        VALUES (
            run_id, p_workspace_id, selected_version.rule_set_id,
            selected_version.id, selected_version.asset_id,
            selected_version.target_binding_hash, selected_version.schema_hash,
            selected_version.source_connection_profile_id,
            selected_version.source_connection_profile_version,
            selected_version.source_connection_profile_hash,
            selected_version.workload_profile_id,
            selected_version.workload_profile_version,
            selected_version.workload_profile_hash,
            security_context_hash, profile_context_hash,
            selected_version.score_policy_id,
            selected_version.score_policy_version,
            selected_version.score_policy_hash,
            NULL, 'SCHEDULED', NULL,
            selected_schedule.id, selected_schedule.version,
            selected_schedule.current_window_key, selected_schedule.next_due_at,
            cutoff_at > selected_schedule.next_due_at
                + make_interval(secs => selected_schedule.late_grace_seconds),
            'QUEUED', 'UNKNOWN', NULL, NULL, NULL, NULL,
            NULL, 0, 3, cutoff_at, 0, NULL, NULL, NULL,
            NULL, NULL, NULL, selected_version.workload_profile_hash, NULL, NULL,
            'QUALITY_RESULT', result_binding.policy_id, result_binding.policy_number,
            result_binding.policy_hash, cutoff_at, result_binding.retain_until,
            result_binding.hold_generation, result_binding.hold_hash,
            'QUALITY_AUDIT', audit_binding.policy_id, audit_binding.policy_number,
            audit_binding.policy_hash, cutoff_at, audit_binding.retain_until,
            audit_binding.hold_generation, audit_binding.hold_hash,
            cutoff_at, cutoff_at, 1
        )
        ON CONFLICT (workspace_id, schedule_id, canonical_window_key) DO NOTHING;
        IF FOUND THEN
            created_count := created_count + 1;
            created_ids := created_ids || jsonb_build_array(run_id::text);
            INSERT INTO quality.run_events (
                id, workspace_id, run_id, sequence, state, reason_code,
                actor_id, actor_kind, evidence_hash,
                audit_retention_policy_id, audit_retention_policy_number,
                audit_retention_policy_hash, audit_retain_until,
                audit_hold_generation, audit_hold_hash, occurred_at
            )
            VALUES (
                gen_random_uuid(), p_workspace_id, run_id, 1, 'QUEUED',
                'SCHEDULE_WINDOW_DUE', actor_id, 'SERVICE',
                encode(sha256(convert_to(jsonb_build_object(
                    'contract', 'QUALITY_RUN_QUEUED_EVENT_V1',
                    'schedule_id', selected_schedule.id::text,
                    'window_key', selected_schedule.current_window_key,
                    'due_at', selected_schedule.next_due_at
                )::text, 'UTF8')), 'hex'),
                audit_binding.policy_id, audit_binding.policy_number,
                audit_binding.policy_hash, audit_binding.retain_until,
                audit_binding.hold_generation, audit_binding.hold_hash, cutoff_at
            );
            INSERT INTO integration.outbox_events (
                id, workspace_id, aggregate_type, aggregate_id, event_type,
                schema_version, payload, created_at, published_at,
                dead_lettered_at, lease_until, attempts, last_error_code
            )
            VALUES (
                gen_random_uuid(), p_workspace_id, 'quality_validation_run', run_id,
                'quality.validation_run.queued.v1', 1,
                jsonb_build_object('run_id', run_id::text, 'state', 'QUEUED'),
                cutoff_at, NULL, NULL, NULL, 0, NULL
            );
        ELSE
            skipped_count := skipped_count + 1;
        END IF;
        UPDATE quality.rule_schedules
        SET next_due_at = selected_schedule.next_due_at
                + make_interval(secs => interval_seconds),
            current_window_key = encode(sha256(convert_to(jsonb_build_object(
                'contract', 'QUALITY_FIXED_WINDOW_V1',
                'schedule_id', selected_schedule.id::text,
                'due_at', selected_schedule.next_due_at
                    + make_interval(secs => interval_seconds)
            )::text, 'UTF8')), 'hex'),
            updated_at = cutoff_at
        WHERE workspace_id = p_workspace_id
          AND id = selected_schedule.id
          AND version = selected_schedule.version;
    END LOOP;

    SELECT * INTO receipt_binding
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id, 'QUALITY_AUDIT', 'QUALITY_VALIDATION_RUN',
        receipt_id, cutoff_at
    );
    result_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_DISPATCH_RESULT_V1',
        'created_run_ids', created_ids,
        'created_run_count', created_count,
        'skipped_window_count', skipped_count
    )::text, 'UTF8')), 'hex');
    INSERT INTO quality.dispatch_call_receipts (
        id, workspace_id, service_subject_id, call_id_hash, request_hash,
        result_hash, idempotency_hash, cutoff_at,
        evaluator_contract_version, tzdb_version, contract_hash,
        max_due_schedules, max_created_runs, created_run_count,
        skipped_window_count, created_run_list_hash, skipped_range_hash,
        audit_retention_kind, audit_retention_policy_id,
        audit_retention_policy_number, audit_retention_policy_hash,
        audit_retention_basis_at, audit_retain_until,
        audit_hold_generation, audit_hold_hash, created_at, updated_at
    )
    VALUES (
        receipt_id, p_workspace_id, actor_id, call_hash, request_hash,
        result_hash,
        encode(sha256(convert_to(
            'QUALITY_DISPATCH_IDEMPOTENCY_V1:' || actor_id::text || ':' || call_hash,
            'UTF8'
        )), 'hex'),
        cutoff_at, 'FIXED_INTERVAL_EVALUATOR_V1', 'UTC',
        encode(sha256(convert_to('QUALITY_DISPATCH_CONTRACT_V1', 'UTF8')), 'hex'),
        p_max_due_schedules, p_max_created_runs, created_count, skipped_count,
        encode(sha256(convert_to(created_ids::text, 'UTF8')), 'hex'),
        encode(sha256(convert_to(skipped_count::text, 'UTF8')), 'hex'),
        'QUALITY_AUDIT', receipt_binding.policy_id, receipt_binding.policy_number,
        receipt_binding.policy_hash, cutoff_at, receipt_binding.retain_until,
        receipt_binding.hold_generation, receipt_binding.hold_hash,
        cutoff_at, cutoff_at
    );
    INSERT INTO quality.dispatch_run_links (
        id, workspace_id, dispatch_receipt_id, run_id, ordinal,
        receipt_audit_policy_id, receipt_audit_policy_number,
        receipt_audit_policy_hash, receipt_audit_retain_until,
        receipt_audit_hold_generation, receipt_audit_hold_hash,
        run_result_policy_id, run_result_policy_number, run_result_policy_hash,
        run_result_retain_until, run_result_hold_generation, run_result_hold_hash,
        run_audit_policy_id, run_audit_policy_number, run_audit_policy_hash,
        run_audit_retain_until, run_audit_hold_generation, run_audit_hold_hash,
        created_at
    )
    SELECT
        gen_random_uuid(), p_workspace_id, receipt_id, run.id, item.ordinality::integer,
        receipt_binding.policy_id, receipt_binding.policy_number,
        receipt_binding.policy_hash, receipt_binding.retain_until,
        receipt_binding.hold_generation, receipt_binding.hold_hash,
        run.result_retention_policy_id, run.result_retention_policy_number,
        run.result_retention_policy_hash, run.result_retain_until,
        run.result_hold_generation, run.result_hold_hash,
        run.audit_retention_policy_id, run.audit_retention_policy_number,
        run.audit_retention_policy_hash, run.audit_retain_until,
        run.audit_hold_generation, run.audit_hold_hash, cutoff_at
    FROM jsonb_array_elements_text(created_ids) WITH ORDINALITY AS item(run_id, ordinality)
    JOIN quality.validation_runs AS run
      ON run.workspace_id = p_workspace_id
     AND run.id = item.run_id::uuid;
    RETURN jsonb_build_object(
        'created_run_ids', created_ids,
        'created_run_count', created_count,
        'skipped_window_count', skipped_count,
        'replayed', false
    );
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.dispatch_due_validation_runs_v1(
    uuid, text, integer, integer
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.claim_validation_run_v1(
    p_workspace_id uuid,
    p_worker_fingerprint text,
    p_lease_token text,
    p_lease_seconds integer
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality
AS $$
DECLARE
    candidate quality.validation_runs%ROWTYPE;
    selected_version quality.rule_set_versions%ROWTYPE;
    previous_attempt quality.validation_attempts%ROWTYPE;
    attempt_id uuid := gen_random_uuid();
    token_hash text;
    now_at timestamptz := transaction_timestamp();
    new_epoch bigint;
    new_attempt integer;
    claim_document jsonb;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR char_length(COALESCE(p_worker_fingerprint, '')) NOT BETWEEN 1 AND 255
       OR p_worker_fingerprint IS DISTINCT FROM btrim(p_worker_fingerprint)
       OR char_length(COALESCE(p_lease_token, '')) NOT BETWEEN 32 AND 200
       OR p_lease_seconds NOT BETWEEN 60 AND 90000
       OR NOT quality.current_quality_service_can_v1(
           p_workspace_id, 'quality.execute', 0, NULL, NULL
       ) THEN
        RAISE EXCEPTION 'invalid Quality claim request'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO candidate
    FROM quality.validation_runs AS run
    WHERE run.workspace_id = p_workspace_id
      AND (
          (run.state IN ('QUEUED','RETRY_WAIT') AND run.next_attempt_at <= now_at)
          OR (
              run.state = 'RUNNING'
              AND run.lease_until <= now_at
          )
      )
    ORDER BY
        CASE WHEN run.state = 'RUNNING' THEN 0 ELSE 1 END,
        run.next_attempt_at, run.id
    FOR UPDATE SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT * INTO selected_version
    FROM quality.rule_set_versions AS version
    WHERE version.workspace_id = p_workspace_id
      AND version.id = candidate.rule_set_version_id
    FOR KEY SHARE;
    IF selected_version.state <> 'ACTIVE'
       OR candidate.result_retain_until <= now_at
       OR candidate.audit_retain_until <= now_at
       OR NOT quality.current_quality_target_matches_v1(
           p_workspace_id, candidate.asset_id, selected_version.classification,
           selected_version.system_id, selected_version.domain_id,
           selected_version.lifecycle, selected_version.source_version
       ) THEN
        RETURN NULL;
    END IF;
    IF candidate.state = 'RUNNING' THEN
        SELECT * INTO previous_attempt
        FROM quality.validation_attempts AS attempt
        WHERE attempt.workspace_id = p_workspace_id
          AND attempt.id = candidate.current_attempt_id
        FOR UPDATE;
        IF candidate.attempt_count >= candidate.maximum_attempts THEN
            UPDATE quality.validation_attempts
            SET state = 'STALE', failure_code = 'LEASE_EXHAUSTED',
                finished_at = now_at
            WHERE workspace_id = p_workspace_id AND id = previous_attempt.id;
            UPDATE quality.validation_runs
            SET state = 'STALE', completed_at = now_at,
                failure_code = 'LEASE_EXHAUSTED',
                lease_token_hash = NULL, lease_owner_fingerprint = NULL,
                lease_until = NULL, heartbeat_at = NULL,
                version = version + 1, updated_at = now_at
            WHERE workspace_id = p_workspace_id AND id = candidate.id;
            INSERT INTO integration.outbox_events (
                id, workspace_id, aggregate_type, aggregate_id, event_type,
                schema_version, payload, created_at, published_at,
                dead_lettered_at, lease_until, attempts, last_error_code
            )
            VALUES (
                gen_random_uuid(), p_workspace_id, 'quality_validation_run',
                candidate.id, 'quality.validation_run.stale.v1', 1,
                jsonb_build_object('run_id', candidate.id::text, 'state', 'STALE'),
                now_at, NULL, NULL, NULL, 0, NULL
            );
            RETURN NULL;
        END IF;
        UPDATE quality.validation_attempts
        SET state = 'SUPERSEDED', failure_code = 'LEASE_EXPIRED',
            finished_at = now_at
        WHERE workspace_id = p_workspace_id AND id = previous_attempt.id;
    END IF;
    token_hash := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');
    new_epoch := candidate.lease_epoch + 1;
    new_attempt := candidate.attempt_count + 1;
    INSERT INTO quality.validation_attempts (
        id, workspace_id, run_id, attempt_no, lease_epoch, lease_token_hash,
        worker_fingerprint, state, claimed_at, lease_until,
        source_started_at, source_access_deadline,
        compiler_result_hash, gx_result_hash, normalized_result_hash,
        failure_code, finished_at,
        result_retention_policy_id, result_retention_policy_number,
        result_retention_policy_hash, result_retain_until,
        result_hold_generation, result_hold_hash,
        audit_retention_policy_id, audit_retention_policy_number,
        audit_retention_policy_hash, audit_retain_until,
        audit_hold_generation, audit_hold_hash
    )
    VALUES (
        attempt_id, p_workspace_id, candidate.id, new_attempt, new_epoch, token_hash,
        p_worker_fingerprint, 'RUNNING', now_at,
        now_at + make_interval(secs => p_lease_seconds),
        NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        candidate.result_retention_policy_id,
        candidate.result_retention_policy_number,
        candidate.result_retention_policy_hash, candidate.result_retain_until,
        candidate.result_hold_generation, candidate.result_hold_hash,
        candidate.audit_retention_policy_id,
        candidate.audit_retention_policy_number,
        candidate.audit_retention_policy_hash, candidate.audit_retain_until,
        candidate.audit_hold_generation, candidate.audit_hold_hash
    );
    UPDATE quality.validation_runs
    SET state = 'RUNNING', current_attempt_id = attempt_id,
        attempt_count = new_attempt, lease_epoch = new_epoch,
        lease_token_hash = token_hash,
        lease_owner_fingerprint = p_worker_fingerprint,
        lease_until = now_at + make_interval(secs => p_lease_seconds),
        heartbeat_at = now_at, source_started_at = NULL,
        source_access_deadline = NULL, failure_code = NULL,
        version = version + 1, updated_at = now_at
    WHERE workspace_id = p_workspace_id AND id = candidate.id;
    INSERT INTO quality.run_events (
        id, workspace_id, run_id, sequence, state, reason_code,
        actor_id, actor_kind, evidence_hash,
        audit_retention_policy_id, audit_retention_policy_number,
        audit_retention_policy_hash, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    SELECT
        gen_random_uuid(), p_workspace_id, candidate.id,
        COALESCE(max(event.sequence), 0) + 1, 'RUNNING', 'WORKER_CLAIMED',
        NULLIF(current_setting('app.subject_id', true), '')::uuid, 'SERVICE',
        encode(sha256(convert_to(jsonb_build_object(
            'contract', 'QUALITY_RUN_CLAIM_EVENT_V1',
            'attempt_id', attempt_id::text,
            'lease_epoch', new_epoch,
            'worker_fingerprint', p_worker_fingerprint
        )::text, 'UTF8')), 'hex'),
        candidate.audit_retention_policy_id,
        candidate.audit_retention_policy_number,
        candidate.audit_retention_policy_hash, candidate.audit_retain_until,
        candidate.audit_hold_generation, candidate.audit_hold_hash, now_at
    FROM quality.run_events AS event
    WHERE event.workspace_id = p_workspace_id AND event.run_id = candidate.id;
    SELECT jsonb_build_object(
        'workspace_id', p_workspace_id::text,
        'run_id', candidate.id::text,
        'attempt_id', attempt_id::text,
        'lease_epoch', new_epoch,
        'asset_id', candidate.asset_id::text,
        'source_connection_profile_id', candidate.source_connection_profile_id,
        'source_connection_profile_version', candidate.source_connection_profile_version,
        'source_connection_profile_hash', candidate.source_connection_profile_hash,
        'workload_profile_id', candidate.workload_profile_id,
        'workload_profile_version', candidate.workload_profile_version,
        'workload_profile_hash', candidate.workload_profile_hash,
        'compiler_hash', selected_version.compiler_hash,
        'rules', (
            SELECT jsonb_agg(jsonb_build_object(
                'rule_definition_id', definition.id::text,
                'ordinal', definition.ordinal,
                'field_identifier', definition.field_identifier,
                'kind', definition.kind,
                'severity', definition.severity,
                'parameters', definition.parameters,
                'definition_hash', definition.definition_hash
            ) ORDER BY definition.ordinal)
            FROM quality.rule_definitions AS definition
            WHERE definition.workspace_id = p_workspace_id
              AND definition.rule_set_version_id = candidate.rule_set_version_id
        )
    ) INTO claim_document;
    RETURN claim_document;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.claim_validation_run_v1(
    uuid, text, text, integer
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.freeze_source_access_v1(
    p_workspace_id uuid,
    p_run_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_hard_timeout_seconds integer,
    p_cancel_timeout_seconds integer,
    p_close_timeout_seconds integer,
    p_completion_timeout_seconds integer
)
RETURNS timestamptz
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality
AS $$
DECLARE
    selected_run quality.validation_runs%ROWTYPE;
    selected_version quality.rule_set_versions%ROWTYPE;
    token_hash text;
    deadline timestamptz;
    now_at timestamptz := transaction_timestamp();
BEGIN
    token_hash := encode(sha256(convert_to(COALESCE(p_lease_token, ''), 'UTF8')), 'hex');
    SELECT * INTO selected_run
    FROM quality.validation_runs AS run
    WHERE run.workspace_id = p_workspace_id AND run.id = p_run_id
    FOR UPDATE;
    SELECT * INTO selected_version
    FROM quality.rule_set_versions AS version
    WHERE version.workspace_id = p_workspace_id
      AND version.id = selected_run.rule_set_version_id
    FOR KEY SHARE;
    IF p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR NOT quality.current_quality_service_can_v1(
           p_workspace_id, 'quality.execute', selected_version.classification,
           selected_version.system_id, selected_version.domain_id
       )
       OR selected_run.state <> 'RUNNING'
       OR selected_run.current_attempt_id <> p_attempt_id
       OR selected_run.lease_epoch <> p_lease_epoch
       OR selected_run.lease_token_hash <> token_hash
       OR selected_run.lease_until <= now_at
       OR selected_run.source_started_at IS NOT NULL
       OR selected_version.state <> 'ACTIVE'
       OR p_hard_timeout_seconds NOT BETWEEN 1 AND 86400
       OR p_cancel_timeout_seconds NOT BETWEEN 1 AND 300
       OR p_close_timeout_seconds NOT BETWEEN 1 AND 300
       OR p_completion_timeout_seconds NOT BETWEEN 1 AND 300
       OR p_hard_timeout_seconds + p_cancel_timeout_seconds
            + p_close_timeout_seconds + p_completion_timeout_seconds
            >= extract(epoch FROM selected_run.lease_until - now_at)
       OR selected_run.hard_timeout_contract_hash
            <> selected_run.workload_profile_hash
       OR NOT quality.current_quality_target_matches_v1(
           p_workspace_id, selected_run.asset_id, selected_version.classification,
           selected_version.system_id, selected_version.domain_id,
           selected_version.lifecycle, selected_version.source_version
       ) THEN
        RAISE EXCEPTION 'Quality source access fence denied'
            USING ERRCODE = '42501';
    END IF;
    deadline := now_at + make_interval(secs => p_hard_timeout_seconds);
    UPDATE quality.validation_runs
    SET source_started_at = now_at, source_access_deadline = deadline,
        heartbeat_at = now_at, version = version + 1, updated_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_run_id;
    UPDATE quality.validation_attempts
    SET source_started_at = now_at, source_access_deadline = deadline
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND run_id = p_run_id AND lease_epoch = p_lease_epoch
      AND lease_token_hash = token_hash AND state = 'RUNNING';
    RETURN deadline;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.freeze_source_access_v1(
    uuid, uuid, uuid, bigint, text, integer, integer, integer, integer
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.assert_source_statement_fence_v1(
    p_workspace_id uuid,
    p_run_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality
AS $$
DECLARE
    selected_run quality.validation_runs%ROWTYPE;
    selected_version quality.rule_set_versions%ROWTYPE;
    now_at timestamptz := transaction_timestamp();
    remaining_ms numeric;
BEGIN
    SELECT * INTO selected_run
    FROM quality.validation_runs AS run
    WHERE run.workspace_id = p_workspace_id AND run.id = p_run_id;
    SELECT * INTO selected_version
    FROM quality.rule_set_versions AS version
    WHERE version.workspace_id = p_workspace_id
      AND version.id = selected_run.rule_set_version_id;
    IF p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR NOT quality.current_quality_service_can_v1(
           p_workspace_id, 'quality.execute', selected_version.classification,
           selected_version.system_id, selected_version.domain_id
       )
       OR selected_run.state <> 'RUNNING'
       OR selected_run.current_attempt_id <> p_attempt_id
       OR selected_run.lease_epoch <> p_lease_epoch
       OR selected_run.lease_token_hash <>
            encode(sha256(convert_to(COALESCE(p_lease_token, ''), 'UTF8')), 'hex')
       OR selected_run.lease_until <= now_at
       OR selected_run.source_started_at IS NULL
       OR selected_run.source_access_deadline <= now_at
       OR selected_version.state <> 'ACTIVE'
       OR NOT quality.current_quality_target_matches_v1(
           p_workspace_id, selected_run.asset_id, selected_version.classification,
           selected_version.system_id, selected_version.domain_id,
           selected_version.lifecycle, selected_version.source_version
       ) THEN
        RAISE EXCEPTION 'Quality source statement fence denied'
            USING ERRCODE = '42501';
    END IF;
    remaining_ms := floor(extract(epoch FROM
        LEAST(selected_run.lease_until, selected_run.source_access_deadline) - now_at
    ) * 1000);
    RETURN LEAST(remaining_ms, 86400000)::integer;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.assert_source_statement_fence_v1(
    uuid, uuid, uuid, bigint, text
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.complete_validation_run_v1(
    p_workspace_id uuid,
    p_run_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_call_id text,
    p_compiler_result_hash text,
    p_gx_result_hash text,
    p_normalized_result_hash text,
    p_results jsonb
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, integration
AS $$
DECLARE
    selected_run quality.validation_runs%ROWTYPE;
    selected_version quality.rule_set_versions%ROWTYPE;
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    token_hash text;
    call_hash text;
    request_hash text;
    result_document jsonb;
    receipt quality.execution_call_receipts%ROWTYPE;
    calculated_passed_count integer;
    calculated_advisory_count integer;
    calculated_blocking_count integer;
    calculated_total_count integer;
    calculated_outcome text;
    calculated_score integer;
    now_at timestamptz := transaction_timestamp();
BEGIN
    token_hash := encode(sha256(convert_to(COALESCE(p_lease_token, ''), 'UTF8')), 'hex');
    call_hash := encode(sha256(convert_to(COALESCE(p_call_id, ''), 'UTF8')), 'hex');
    request_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_EXECUTION_COMPLETE_REQUEST_V1',
        'run_id', p_run_id::text, 'attempt_id', p_attempt_id::text,
        'lease_epoch', p_lease_epoch, 'lease_token_hash', token_hash,
        'compiler_result_hash', p_compiler_result_hash,
        'gx_result_hash', p_gx_result_hash,
        'normalized_result_hash', p_normalized_result_hash,
        'results', p_results
    )::text, 'UTF8')), 'hex');
    SELECT * INTO receipt
    FROM quality.execution_call_receipts AS value
    WHERE value.workspace_id = p_workspace_id
      AND value.service_subject_id = actor_id
      AND value.run_id = p_run_id
      AND value.call_id_hash = call_hash;
    IF FOUND THEN
        IF receipt.request_hash <> request_hash THEN
            RAISE EXCEPTION 'Quality execution idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN true;
    END IF;
    SELECT * INTO selected_run
    FROM quality.validation_runs AS run
    WHERE run.workspace_id = p_workspace_id AND run.id = p_run_id
    FOR UPDATE;
    SELECT * INTO selected_version
    FROM quality.rule_set_versions AS version
    WHERE version.workspace_id = p_workspace_id
      AND version.id = selected_run.rule_set_version_id
    FOR KEY SHARE;
    IF p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR char_length(COALESCE(p_call_id, '')) NOT BETWEEN 1 AND 200
       OR p_results IS NULL OR jsonb_typeof(p_results) <> 'array'
       OR jsonb_array_length(p_results) NOT BETWEEN 1 AND 1000
       OR p_compiler_result_hash !~ '^[0-9a-f]{64}$'
       OR p_gx_result_hash !~ '^[0-9a-f]{64}$'
       OR p_normalized_result_hash !~ '^[0-9a-f]{64}$'
       OR NOT quality.current_quality_service_can_v1(
           p_workspace_id, 'quality.execute', selected_version.classification,
           selected_version.system_id, selected_version.domain_id
       )
       OR selected_run.state <> 'RUNNING'
       OR selected_run.current_attempt_id <> p_attempt_id
       OR selected_run.lease_epoch <> p_lease_epoch
       OR selected_run.lease_token_hash <> token_hash
       OR selected_run.lease_until <= now_at
       OR selected_run.source_started_at IS NULL
       OR selected_run.source_access_deadline <= now_at
       OR selected_version.state <> 'ACTIVE'
       OR NOT quality.current_quality_target_matches_v1(
           p_workspace_id, selected_run.asset_id, selected_version.classification,
           selected_version.system_id, selected_version.domain_id,
           selected_version.lifecycle, selected_version.source_version
       )
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements(p_results) AS item
           WHERE jsonb_typeof(item) <> 'object'
              OR ARRAY(
                  SELECT key FROM jsonb_object_keys(item) AS key
                  ORDER BY key COLLATE "C"
              ) IS DISTINCT FROM ARRAY[
                  'duration_ms','evaluated_count','missing_count','missing_ratio',
                  'outcome','result_hash','rule_definition_id',
                  'unexpected_count','unexpected_ratio'
              ]::text[]
              OR COALESCE(item ->> 'result_hash', '') !~ '^[0-9a-f]{64}$'
              OR COALESCE(item ->> 'outcome', '')
                    NOT IN ('PASS','ADVISORY_FAIL','BLOCKING_FAIL')
              OR jsonb_typeof(item -> 'evaluated_count') <> 'number'
              OR jsonb_typeof(item -> 'missing_count') <> 'number'
              OR jsonb_typeof(item -> 'unexpected_count') <> 'number'
              OR jsonb_typeof(item -> 'duration_ms') <> 'number'
              OR jsonb_typeof(item -> 'missing_ratio') <> 'number'
              OR jsonb_typeof(item -> 'unexpected_ratio') <> 'number'
              OR (item ->> 'evaluated_count')::numeric < 0
              OR (item ->> 'missing_count')::numeric < 0
              OR (item ->> 'unexpected_count')::numeric < 0
              OR (item ->> 'duration_ms')::numeric < 0
              OR (item ->> 'missing_ratio')::numeric NOT BETWEEN 0 AND 1
              OR (item ->> 'unexpected_ratio')::numeric NOT BETWEEN 0 AND 1
       )
       OR (
           SELECT count(DISTINCT item ->> 'rule_definition_id')
           FROM jsonb_array_elements(p_results) AS item
       ) <> jsonb_array_length(p_results)
       OR (
           SELECT count(*) FROM quality.rule_definitions AS definition
           WHERE definition.workspace_id = p_workspace_id
             AND definition.rule_set_version_id = selected_run.rule_set_version_id
       ) <> jsonb_array_length(p_results)
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements(p_results) AS item
           LEFT JOIN quality.rule_definitions AS definition
             ON definition.workspace_id = p_workspace_id
            AND definition.rule_set_version_id = selected_run.rule_set_version_id
            AND definition.id = (item ->> 'rule_definition_id')::uuid
           WHERE definition.id IS NULL
              OR item ->> 'outcome' IS DISTINCT FROM CASE
                  WHEN (item ->> 'unexpected_count')::bigint = 0 THEN 'PASS'
                  WHEN definition.severity = 'BLOCKING' THEN 'BLOCKING_FAIL'
                  ELSE 'ADVISORY_FAIL'
              END
              OR (item ->> 'unexpected_count')::bigint
                    > (item ->> 'evaluated_count')::bigint
       ) THEN
        RAISE EXCEPTION 'Quality completion fence or result contract denied'
            USING ERRCODE = '42501';
    END IF;
    SELECT
        count(*) FILTER (WHERE item ->> 'outcome' = 'PASS'),
        count(*) FILTER (WHERE item ->> 'outcome' = 'ADVISORY_FAIL'),
        count(*) FILTER (WHERE item ->> 'outcome' = 'BLOCKING_FAIL'),
        count(*)
    INTO calculated_passed_count, calculated_advisory_count,
         calculated_blocking_count, calculated_total_count
    FROM jsonb_array_elements(p_results) AS item;
    calculated_outcome := CASE
        WHEN calculated_blocking_count > 0 THEN 'FAIL'
        WHEN calculated_advisory_count > 0 THEN 'WARN'
        ELSE 'PASS'
    END;
    calculated_score := round(
        (calculated_passed_count::numeric * 100) / calculated_total_count
    )::integer;
    UPDATE quality.validation_attempts
    SET state = 'SUCCEEDED', compiler_result_hash = p_compiler_result_hash,
        gx_result_hash = p_gx_result_hash,
        normalized_result_hash = p_normalized_result_hash,
        failure_code = NULL, finished_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND run_id = p_run_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    INSERT INTO quality.expectation_results (
        id, workspace_id, run_id, attempt_id, run_state,
        rule_set_version_id, rule_definition_id, outcome,
        evaluated_count, missing_count, unexpected_count,
        missing_ratio, unexpected_ratio, duration_ms, result_hash,
        result_retention_policy_id, result_retention_policy_number,
        result_retention_policy_hash, result_retain_until,
        result_hold_generation, result_hold_hash, occurred_at
    )
    SELECT
        gen_random_uuid(), p_workspace_id, p_run_id, p_attempt_id, 'SUCCEEDED',
        selected_run.rule_set_version_id, (item ->> 'rule_definition_id')::uuid,
        item ->> 'outcome', (item ->> 'evaluated_count')::bigint,
        (item ->> 'missing_count')::bigint,
        (item ->> 'unexpected_count')::bigint,
        (item ->> 'missing_ratio')::numeric,
        (item ->> 'unexpected_ratio')::numeric,
        (item ->> 'duration_ms')::bigint, item ->> 'result_hash',
        selected_run.result_retention_policy_id,
        selected_run.result_retention_policy_number,
        selected_run.result_retention_policy_hash,
        selected_run.result_retain_until,
        selected_run.result_hold_generation, selected_run.result_hold_hash, now_at
    FROM jsonb_array_elements(p_results) AS item;
    UPDATE quality.validation_runs
    SET state = 'SUCCEEDED', quality_outcome = calculated_outcome,
        score = calculated_score, passed_count = calculated_passed_count,
        advisory_failed_count = calculated_advisory_count,
        blocking_failed_count = calculated_blocking_count, completed_at = now_at,
        failure_code = NULL, lease_token_hash = NULL,
        lease_owner_fingerprint = NULL, lease_until = NULL, heartbeat_at = NULL,
        version = version + 1, updated_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_run_id;
    INSERT INTO quality.run_events (
        id, workspace_id, run_id, sequence, state, reason_code,
        actor_id, actor_kind, evidence_hash,
        audit_retention_policy_id, audit_retention_policy_number,
        audit_retention_policy_hash, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    SELECT
        gen_random_uuid(), p_workspace_id, p_run_id,
        COALESCE(max(event.sequence), 0) + 1, 'SUCCEEDED', 'WORKER_COMPLETED',
        actor_id, 'SERVICE',
        encode(sha256(convert_to(jsonb_build_object(
            'contract', 'QUALITY_RUN_COMPLETION_EVENT_V1',
            'attempt_id', p_attempt_id::text,
            'lease_epoch', p_lease_epoch,
            'normalized_result_hash', p_normalized_result_hash
        )::text, 'UTF8')), 'hex'),
        selected_run.audit_retention_policy_id,
        selected_run.audit_retention_policy_number,
        selected_run.audit_retention_policy_hash,
        selected_run.audit_retain_until,
        selected_run.audit_hold_generation, selected_run.audit_hold_hash, now_at
    FROM quality.run_events AS event
    WHERE event.workspace_id = p_workspace_id AND event.run_id = p_run_id;
    result_document := jsonb_build_object(
        'state', 'SUCCEEDED', 'quality_outcome', calculated_outcome,
        'score', calculated_score, 'passed_count', calculated_passed_count,
        'advisory_failed_count', calculated_advisory_count,
        'blocking_failed_count', calculated_blocking_count
    );
    INSERT INTO quality.execution_call_receipts (
        id, workspace_id, service_subject_id, run_id, attempt_id, lease_epoch,
        lease_token_hash, call_id_hash, request_hash, result_hash,
        idempotency_hash, audit_retention_policy_id,
        audit_retention_policy_number, audit_retention_policy_hash,
        audit_retain_until, audit_hold_generation, audit_hold_hash,
        created_at, updated_at
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, actor_id, p_run_id, p_attempt_id,
        p_lease_epoch, token_hash, call_hash, request_hash,
        encode(sha256(convert_to(result_document::text, 'UTF8')), 'hex'),
        encode(sha256(convert_to(
            'QUALITY_EXECUTION_IDEMPOTENCY_V1:' || actor_id::text || ':' ||
            p_run_id::text || ':' || call_hash, 'UTF8'
        )), 'hex'),
        selected_run.audit_retention_policy_id,
        selected_run.audit_retention_policy_number,
        selected_run.audit_retention_policy_hash,
        selected_run.audit_retain_until,
        selected_run.audit_hold_generation, selected_run.audit_hold_hash,
        now_at, now_at
    );
    INSERT INTO integration.outbox_events (
        id, workspace_id, aggregate_type, aggregate_id, event_type,
        schema_version, payload, created_at, published_at,
        dead_lettered_at, lease_until, attempts, last_error_code
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, 'quality_validation_run', p_run_id,
        'quality.validation_run.succeeded.v1', 1,
        jsonb_build_object(
            'run_id', p_run_id::text, 'state', 'SUCCEEDED',
            'quality_outcome', calculated_outcome, 'score', calculated_score
        ),
        now_at, NULL, NULL, NULL, 0, NULL
    );
    RETURN true;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.complete_validation_run_v1(
    uuid, uuid, uuid, bigint, text, text, text, text, text, jsonb
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.fail_validation_run_v1(
    p_workspace_id uuid,
    p_run_id uuid,
    p_attempt_id uuid,
    p_lease_epoch bigint,
    p_lease_token text,
    p_call_id text,
    p_failure_code text,
    p_retryable boolean
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, integration
AS $$
DECLARE
    selected_run quality.validation_runs%ROWTYPE;
    selected_version quality.rule_set_versions%ROWTYPE;
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    token_hash text;
    call_hash text;
    request_hash text;
    target_state text;
    attempt_state text;
    event_type text;
    now_at timestamptz := transaction_timestamp();
    existing_receipt quality.execution_call_receipts%ROWTYPE;
BEGIN
    token_hash := encode(sha256(convert_to(COALESCE(p_lease_token, ''), 'UTF8')), 'hex');
    call_hash := encode(sha256(convert_to(COALESCE(p_call_id, ''), 'UTF8')), 'hex');
    request_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_EXECUTION_FAILURE_REQUEST_V1',
        'run_id', p_run_id::text, 'attempt_id', p_attempt_id::text,
        'lease_epoch', p_lease_epoch, 'lease_token_hash', token_hash,
        'failure_code', p_failure_code, 'retryable', p_retryable
    )::text, 'UTF8')), 'hex');
    SELECT * INTO existing_receipt
    FROM quality.execution_call_receipts AS receipt
    WHERE receipt.workspace_id = p_workspace_id
      AND receipt.service_subject_id = actor_id
      AND receipt.run_id = p_run_id
      AND receipt.call_id_hash = call_hash;
    IF FOUND THEN
        IF existing_receipt.request_hash <> request_hash THEN
            RAISE EXCEPTION 'Quality execution idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN true;
    END IF;
    SELECT * INTO selected_run
    FROM quality.validation_runs AS run
    WHERE run.workspace_id = p_workspace_id AND run.id = p_run_id
    FOR UPDATE;
    SELECT * INTO selected_version
    FROM quality.rule_set_versions AS version
    WHERE version.workspace_id = p_workspace_id
      AND version.id = selected_run.rule_set_version_id;
    IF p_workspace_id IS DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR char_length(COALESCE(p_call_id, '')) NOT BETWEEN 1 AND 200
       OR COALESCE(p_failure_code, '') !~ '^[A-Z][A-Z0-9_]{0,99}$'
       OR NOT quality.current_quality_service_can_v1(
           p_workspace_id, 'quality.execute', selected_version.classification,
           selected_version.system_id, selected_version.domain_id
       )
       OR selected_run.state NOT IN ('RUNNING','CANCEL_REQUESTED')
       OR selected_run.current_attempt_id <> p_attempt_id
       OR selected_run.lease_epoch <> p_lease_epoch
       OR selected_run.lease_token_hash <> token_hash
       OR selected_run.lease_until <= now_at THEN
        RAISE EXCEPTION 'Quality failure fence denied'
            USING ERRCODE = '42501';
    END IF;
    IF selected_run.state = 'CANCEL_REQUESTED' THEN
        target_state := 'CANCELLED';
        attempt_state := 'CANCELLED';
    ELSIF p_retryable AND selected_run.attempt_count < selected_run.maximum_attempts THEN
        target_state := 'RETRY_WAIT';
        attempt_state := 'RETRYABLE_FAILED';
    ELSE
        target_state := 'FAILED';
        attempt_state := 'FAILED';
    END IF;
    event_type := CASE target_state
        WHEN 'RETRY_WAIT' THEN 'quality.validation_run.retry_wait.v1'
        WHEN 'CANCELLED' THEN 'quality.validation_run.cancelled.v1'
        ELSE 'quality.validation_run.failed.v1'
    END;
    UPDATE quality.validation_attempts
    SET state = attempt_state, failure_code = p_failure_code, finished_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_attempt_id
      AND run_id = p_run_id AND state = 'RUNNING'
      AND lease_epoch = p_lease_epoch AND lease_token_hash = token_hash;
    UPDATE quality.validation_runs
    SET state = target_state, quality_outcome = 'UNKNOWN', score = NULL,
        completed_at = CASE
            WHEN target_state IN ('FAILED','CANCELLED') THEN now_at ELSE NULL
        END,
        next_attempt_at = CASE
            WHEN target_state = 'RETRY_WAIT' THEN now_at + interval '30 seconds'
            ELSE next_attempt_at
        END,
        failure_code = p_failure_code, lease_token_hash = NULL,
        lease_owner_fingerprint = NULL, lease_until = NULL, heartbeat_at = NULL,
        version = version + 1, updated_at = now_at
    WHERE workspace_id = p_workspace_id AND id = p_run_id;
    INSERT INTO quality.run_events (
        id, workspace_id, run_id, sequence, state, reason_code,
        actor_id, actor_kind, evidence_hash,
        audit_retention_policy_id, audit_retention_policy_number,
        audit_retention_policy_hash, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    SELECT
        gen_random_uuid(), p_workspace_id, p_run_id,
        COALESCE(max(event.sequence), 0) + 1, target_state,
        CASE target_state
            WHEN 'RETRY_WAIT' THEN 'WORKER_RETRYABLE_FAILURE'
            WHEN 'CANCELLED' THEN 'WORKER_CANCELLED'
            ELSE 'WORKER_FAILURE'
        END,
        actor_id, 'SERVICE',
        encode(sha256(convert_to(jsonb_build_object(
            'contract', 'QUALITY_RUN_FAILURE_EVENT_V1',
            'attempt_id', p_attempt_id::text,
            'lease_epoch', p_lease_epoch,
            'failure_code', p_failure_code,
            'state', target_state
        )::text, 'UTF8')), 'hex'),
        selected_run.audit_retention_policy_id,
        selected_run.audit_retention_policy_number,
        selected_run.audit_retention_policy_hash,
        selected_run.audit_retain_until,
        selected_run.audit_hold_generation, selected_run.audit_hold_hash, now_at
    FROM quality.run_events AS event
    WHERE event.workspace_id = p_workspace_id AND event.run_id = p_run_id;
    INSERT INTO quality.execution_call_receipts (
        id, workspace_id, service_subject_id, run_id, attempt_id, lease_epoch,
        lease_token_hash, call_id_hash, request_hash, result_hash,
        idempotency_hash, audit_retention_policy_id,
        audit_retention_policy_number, audit_retention_policy_hash,
        audit_retain_until, audit_hold_generation, audit_hold_hash,
        created_at, updated_at
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, actor_id, p_run_id, p_attempt_id,
        p_lease_epoch, token_hash, call_hash, request_hash,
        encode(sha256(convert_to(jsonb_build_object(
            'state', target_state, 'failure_code', p_failure_code
        )::text, 'UTF8')), 'hex'),
        encode(sha256(convert_to(
            'QUALITY_EXECUTION_IDEMPOTENCY_V1:' || actor_id::text || ':' ||
            p_run_id::text || ':' || call_hash, 'UTF8'
        )), 'hex'),
        selected_run.audit_retention_policy_id,
        selected_run.audit_retention_policy_number,
        selected_run.audit_retention_policy_hash,
        selected_run.audit_retain_until,
        selected_run.audit_hold_generation, selected_run.audit_hold_hash,
        now_at, now_at
    );
    INSERT INTO integration.outbox_events (
        id, workspace_id, aggregate_type, aggregate_id, event_type,
        schema_version, payload, created_at, published_at,
        dead_lettered_at, lease_until, attempts, last_error_code
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, 'quality_validation_run', p_run_id,
        event_type, 1,
        jsonb_build_object(
            'run_id', p_run_id::text, 'state', target_state,
            'failure_code', p_failure_code
        ),
        now_at, NULL, NULL, NULL, 0, NULL
    );
    RETURN true;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.fail_validation_run_v1(
    uuid, uuid, uuid, bigint, text, text, text, boolean
) FROM PUBLIC;
"""

_GRANT_SQL = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT EXECUTE ON FUNCTION quality.dispatch_due_validation_runs_v1(
            uuid, text, integer, integer
        ) TO datariver_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_quality') THEN
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA quality, catalog, integration
            FROM datariver_quality;
        REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA quality, catalog, integration
            FROM datariver_quality;
        REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA quality
            FROM datariver_quality;
        GRANT USAGE ON SCHEMA quality TO datariver_quality;
        GRANT EXECUTE ON FUNCTION quality.claim_validation_run_v1(
            uuid, text, text, integer
        ) TO datariver_quality;
        GRANT EXECUTE ON FUNCTION quality.freeze_source_access_v1(
            uuid, uuid, uuid, bigint, text, integer, integer, integer, integer
        ) TO datariver_quality;
        GRANT EXECUTE ON FUNCTION quality.assert_source_statement_fence_v1(
            uuid, uuid, uuid, bigint, text
        ) TO datariver_quality;
        GRANT EXECUTE ON FUNCTION quality.complete_validation_run_v1(
            uuid, uuid, uuid, bigint, text, text, text, text, text, jsonb
        ) TO datariver_quality;
        GRANT EXECUTE ON FUNCTION quality.fail_validation_run_v1(
            uuid, uuid, uuid, bigint, text, text, text, boolean
        ) TO datariver_quality;
    END IF;
END
$$;
"""


def _execute_script(script: str) -> None:
    for statement in script.split(_STATEMENT_BOUNDARY):
        normalized = statement.strip()
        if normalized:
            op.execute(normalized)


def upgrade() -> None:
    _execute_script(_FUNCTION_SQL)
    op.execute(_GRANT_SQL)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS quality.fail_validation_run_v1("
        "uuid, uuid, uuid, bigint, text, text, text, boolean)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.complete_validation_run_v1("
        "uuid, uuid, uuid, bigint, text, text, text, text, text, jsonb)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.assert_source_statement_fence_v1("
        "uuid, uuid, uuid, bigint, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.freeze_source_access_v1("
        "uuid, uuid, uuid, bigint, text, integer, integer, integer, integer)"
    )
    op.execute("DROP FUNCTION IF EXISTS quality.claim_validation_run_v1(uuid, text, text, integer)")
    op.execute(
        "DROP FUNCTION IF EXISTS quality.dispatch_due_validation_runs_v1("
        "uuid, text, integer, integer)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.current_quality_target_matches_v1("
        "uuid, uuid, integer, uuid, uuid, text, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.current_quality_service_can_v1("
        "uuid, text, integer, uuid, uuid)"
    )
