"""Add fixed Quality authoring and manual execution commands.

Revision ID: 0071
Revises: 0070
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0071"
down_revision: str | Sequence[str] | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COMMAND_SQL = r"""
CREATE OR REPLACE FUNCTION quality.review_rule_set_version_command_v2(
    p_workspace_id uuid,
    p_version_id uuid,
    p_decision text,
    p_reason text,
    p_policy_decision_id uuid,
    p_expected_version integer
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, retention
AS $$
DECLARE
    candidate quality.rule_set_versions%ROWTYPE;
    evidence record;
    audit_binding record;
BEGIN
    SELECT * INTO candidate
    FROM quality.rule_set_versions
    WHERE workspace_id = p_workspace_id AND id = p_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quality Rule Set Version is unavailable'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO evidence
    FROM quality.require_human_decision_v1(
        p_workspace_id,
        NULLIF(current_setting('app.subject_id', true), '')::uuid,
        p_version_id,
        'quality.rule.review',
        p_policy_decision_id,
        false
    );
    SELECT * INTO audit_binding
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id,
        'QUALITY_AUDIT',
        'QUALITY_RULE_SET',
        candidate.rule_set_id,
        transaction_timestamp()
    );
    RETURN quality.review_rule_set_version_v1(
        p_workspace_id,
        p_version_id,
        p_decision,
        p_reason,
        p_policy_decision_id,
        evidence.assurance_hash,
        p_expected_version,
        audit_binding.policy_id,
        audit_binding.policy_number,
        audit_binding.policy_hash,
        audit_binding.retain_until,
        audit_binding.hold_generation,
        audit_binding.hold_hash
    );
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.review_rule_set_version_command_v2(
    uuid, uuid, text, text, uuid, integer
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.activate_rule_set_version_command_v2(
    p_workspace_id uuid,
    p_version_id uuid,
    p_policy_decision_id uuid,
    p_idempotency_key_hash text,
    p_expected_version integer
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, retention
AS $$
DECLARE
    candidate quality.rule_set_versions%ROWTYPE;
    evidence record;
    rule_binding record;
    audit_binding record;
    schedule_binding_hash text;
    retention_binding_hash text;
BEGIN
    SELECT * INTO candidate
    FROM quality.rule_set_versions
    WHERE workspace_id = p_workspace_id AND id = p_version_id;
    IF NOT FOUND OR candidate.schedule_mode <> 'MANUAL_ONLY'
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Quality Rule Set Version is unavailable'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO evidence
    FROM quality.require_human_decision_v1(
        p_workspace_id,
        NULLIF(current_setting('app.subject_id', true), '')::uuid,
        p_version_id,
        'quality.rule.activate',
        p_policy_decision_id,
        true
    );
    SELECT * INTO rule_binding
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id,
        'QUALITY_RULE',
        'QUALITY_RULE_SET',
        candidate.rule_set_id,
        transaction_timestamp()
    );
    SELECT * INTO audit_binding
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id,
        'QUALITY_AUDIT',
        'QUALITY_RULE_SET',
        candidate.rule_set_id,
        transaction_timestamp()
    );
    schedule_binding_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_SCHEDULE_BINDING_V1',
        'mode', candidate.schedule_mode,
        'profile_id', candidate.schedule_profile_id,
        'profile_version', candidate.schedule_profile_version,
        'profile_hash', candidate.schedule_profile_hash
    )::text, 'UTF8')), 'hex');
    retention_binding_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_COMMAND_RETENTION_BINDING_V1',
        'rule_policy_id', rule_binding.policy_id::text,
        'rule_policy_number', rule_binding.policy_number,
        'rule_policy_hash', rule_binding.policy_hash,
        'rule_retain_until', rule_binding.retain_until,
        'rule_hold_generation', rule_binding.hold_generation,
        'rule_hold_hash', rule_binding.hold_hash,
        'audit_policy_id', audit_binding.policy_id::text,
        'audit_policy_number', audit_binding.policy_number,
        'audit_policy_hash', audit_binding.policy_hash,
        'audit_retain_until', audit_binding.retain_until,
        'audit_hold_generation', audit_binding.hold_generation,
        'audit_hold_hash', audit_binding.hold_hash
    )::text, 'UTF8')), 'hex');
    RETURN quality.activate_rule_set_version_v1(
        p_workspace_id,
        p_version_id,
        p_policy_decision_id,
        evidence.assurance_hash,
        evidence.authorization_hash,
        schedule_binding_hash,
        retention_binding_hash,
        p_idempotency_key_hash,
        p_expected_version,
        audit_binding.policy_id,
        audit_binding.policy_number,
        audit_binding.policy_hash,
        audit_binding.retain_until,
        audit_binding.hold_generation,
        audit_binding.hold_hash
    );
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.activate_rule_set_version_command_v2(
    uuid, uuid, uuid, text, integer
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.request_manual_validation_run_v1(
    p_workspace_id uuid,
    p_rule_set_id uuid,
    p_policy_decision_id uuid
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, catalog, retention, integration
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    parent quality.rule_sets%ROWTYPE;
    candidate quality.rule_set_versions%ROWTYPE;
    result_binding record;
    audit_binding record;
    decision_evidence record;
    run_id uuid := gen_random_uuid();
    cutoff_at timestamptz := transaction_timestamp();
    profile_context_hash text;
    security_context_hash text;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'invalid Quality manual Run request'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO parent
    FROM quality.rule_sets
    WHERE workspace_id = p_workspace_id
      AND id = p_rule_set_id
      AND state = 'ACTIVE'
    FOR KEY SHARE;
    SELECT * INTO candidate
    FROM quality.rule_set_versions
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = p_rule_set_id
      AND state = 'ACTIVE'
    FOR KEY SHARE;
    IF parent.id IS NULL
       OR candidate.id IS NULL
       OR candidate.schedule_mode <> 'MANUAL_ONLY'
       OR NOT EXISTS (
           SELECT 1
           FROM quality.rule_definitions AS definition
           WHERE definition.workspace_id = p_workspace_id
             AND definition.rule_set_version_id = candidate.id
       )
       OR NOT quality.current_target_matches_v1(
           p_workspace_id,
           candidate.asset_id,
           candidate.classification,
           candidate.system_id,
           candidate.domain_id,
           candidate.lifecycle,
           candidate.source_version,
           'quality.run.request'
       ) THEN
        RAISE EXCEPTION 'invalid Quality manual Run request'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO decision_evidence
    FROM quality.require_human_decision_v1(
        p_workspace_id,
        actor_id,
        candidate.id,
        'quality.run.request',
        p_policy_decision_id,
        false
    );
    SELECT * INTO result_binding
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id,
        'QUALITY_RESULT',
        'QUALITY_VALIDATION_RUN',
        run_id,
        cutoff_at
    );
    SELECT * INTO audit_binding
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id,
        'QUALITY_AUDIT',
        'QUALITY_VALIDATION_RUN',
        run_id,
        cutoff_at
    );
    SELECT COALESCE(
        (
            SELECT snapshot.snapshot_identity_hash
            FROM catalog.asset_profile_snapshots AS snapshot
            WHERE snapshot.workspace_id = p_workspace_id
              AND snapshot.asset_id = candidate.asset_id
              AND snapshot.asset_source_version = candidate.source_version
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
        'asset_id', candidate.asset_id::text,
        'classification', candidate.classification,
        'system_id', candidate.system_id::text,
        'domain_id', candidate.domain_id::text,
        'lifecycle', candidate.lifecycle,
        'source_version', candidate.source_version
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
        run_id, p_workspace_id, candidate.rule_set_id,
        candidate.id, candidate.asset_id,
        candidate.target_binding_hash, candidate.schema_hash,
        candidate.source_connection_profile_id,
        candidate.source_connection_profile_version,
        candidate.source_connection_profile_hash,
        candidate.workload_profile_id,
        candidate.workload_profile_version,
        candidate.workload_profile_hash,
        security_context_hash, profile_context_hash,
        candidate.score_policy_id,
        candidate.score_policy_version,
        candidate.score_policy_hash,
        NULL, 'MANUAL', actor_id,
        NULL, NULL, NULL, NULL, false,
        'QUEUED', 'UNKNOWN', NULL, NULL, NULL, NULL,
        NULL, 0, 3, cutoff_at, 0, NULL, NULL, NULL,
        NULL, NULL, NULL, candidate.workload_profile_hash, NULL, NULL,
        'QUALITY_RESULT', result_binding.policy_id, result_binding.policy_number,
        result_binding.policy_hash, cutoff_at, result_binding.retain_until,
        result_binding.hold_generation, result_binding.hold_hash,
        'QUALITY_AUDIT', audit_binding.policy_id, audit_binding.policy_number,
        audit_binding.policy_hash, cutoff_at, audit_binding.retain_until,
        audit_binding.hold_generation, audit_binding.hold_hash,
        cutoff_at, cutoff_at, 1
    );
    INSERT INTO quality.run_events (
        id, workspace_id, run_id, sequence, state, reason_code,
        actor_id, actor_kind, evidence_hash,
        audit_retention_policy_id, audit_retention_policy_number,
        audit_retention_policy_hash, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, run_id, 1, 'QUEUED',
        'MANUAL_REQUEST_ACCEPTED', actor_id, 'HUMAN',
        decision_evidence.authorization_hash,
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
    RETURN run_id;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.request_manual_validation_run_v1(
    uuid, uuid, uuid
) FROM PUBLIC;
-- datariver-statement-boundary

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT EXECUTE ON FUNCTION quality.review_rule_set_version_command_v2(
            uuid, uuid, text, text, uuid, integer
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.activate_rule_set_version_command_v2(
            uuid, uuid, uuid, text, integer
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.request_manual_validation_run_v1(
            uuid, uuid, uuid
        ) TO datariver_app;
    END IF;
END
$$;
"""


def upgrade() -> None:
    for statement in _COMMAND_SQL.split("-- datariver-statement-boundary"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS quality.request_manual_validation_run_v1(uuid, uuid, uuid)")
    op.execute(
        "DROP FUNCTION IF EXISTS quality.activate_rule_set_version_command_v2("
        "uuid, uuid, uuid, text, integer)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.review_rule_set_version_command_v2("
        "uuid, uuid, text, text, uuid, integer)"
    )
