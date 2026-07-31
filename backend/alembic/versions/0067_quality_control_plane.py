# ruff: noqa: S608 -- SQL is rendered only from fixed schema constants.
"""Add the governed Quality control-plane schema.

Revision ID: 0067
Revises: 0066
Create Date: 2026-07-30
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from hashlib import sha256

from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable

from datariver.infrastructure.db import models as _models  # noqa: F401
from datariver.infrastructure.db.base import Base

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QUALITY_TABLE_NAMES = (
    "dispatch_call_receipts",
    "rule_sets",
    "rule_set_versions",
    "rule_command_events",
    "rule_definitions",
    "rule_reviews",
    "rule_schedules",
    "validation_runs",
    "dispatch_run_links",
    "expectation_results",
    "run_events",
    "validation_attempts",
    "execution_call_receipts",
)
_APP_READ_TABLES = ", ".join(f"quality.{name}" for name in _QUALITY_TABLE_NAMES)
_APP_INSERT_TABLES = ", ".join(
    f"quality.{name}"
    for name in (
        "rule_sets",
        "rule_set_versions",
        "rule_definitions",
    )
)
_IMMUTABLE_TABLES = (
    "rule_definitions",
    "rule_reviews",
    "rule_command_events",
    "expectation_results",
    "run_events",
    "dispatch_call_receipts",
    "dispatch_run_links",
    "execution_call_receipts",
)
_STATEMENT_BOUNDARY = "-- datariver-statement-boundary"
_QUALITY_SCHEMA_CONTRACT_HASH = "76d6d89959da297d70117ebc3ce0fb023416be6cf5ecf26e361d4bb7e0320477"
_POST_0067_INDEX_NAMES = frozenset(
    {
        "ix_quality_expectation_results_issues",
        "ix_quality_rule_sets_list",
        "ix_quality_validation_runs_list",
    }
)
_QUALITY_CATALOG_CONTRACT_HASH = "43149d67578f8f1e59c3739e9a8c16ae736103f685a3ad50a28e4014a49ab343"
_QUALITY_CANONICAL_HEAD_CONTRACT_HASH = (
    "06392589dd401f2f797aa9b5aacf674399b0b6442429092edf332759db9841f1"
)

_RETENTION_ALLOWLIST_SQL = """
ALTER TABLE retention.policy_versions
    DROP CONSTRAINT IF EXISTS ck_policy_versions_contract_shape;
-- datariver-statement-boundary
ALTER TABLE retention.policy_versions
    DROP CONSTRAINT IF EXISTS ck_policy_versions_ck_policy_versions_contract_shape;
-- datariver-statement-boundary
ALTER TABLE retention.policy_versions
    ADD CONSTRAINT ck_policy_versions_contract_shape CHECK (
        (
            contract_version = 'SINGLE_DEADLINE_V1'
            AND effective_from IS NULL
            AND effective_until IS NULL
            AND execution_authorization_hours IS NULL
        )
        OR (
            contract_version IN ('POLICY_BOOK_V2', 'POLICY_BOOK_V3')
            AND effective_from IS NOT NULL
            AND (effective_until IS NULL OR effective_until > effective_from)
            AND execution_authorization_hours BETWEEN 1 AND 168
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.policy_class_rules
    DROP CONSTRAINT IF EXISTS ck_policy_class_rules_data_class;
-- datariver-statement-boundary
ALTER TABLE retention.policy_class_rules
    DROP CONSTRAINT IF EXISTS ck_policy_class_rules_ck_policy_class_rules_data_class;
-- datariver-statement-boundary
ALTER TABLE retention.policy_class_rules
    ADD CONSTRAINT ck_policy_class_rules_data_class CHECK (
        data_class IN (
            'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT'
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    DROP CONSTRAINT ck_legal_holds_data_class,
    ADD CONSTRAINT ck_legal_holds_data_class CHECK (
        data_class IN (
            'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT'
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    ADD COLUMN resource_type varchar(40);
-- datariver-statement-boundary
UPDATE retention.legal_holds
SET resource_type = 'LEGACY_UNTYPED'
WHERE scope = 'RESOURCE';
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    DROP CONSTRAINT ck_legal_holds_scope_shape;
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    ADD CONSTRAINT ck_legal_holds_scope_shape CHECK (
        (scope = 'WORKSPACE' AND scope_id IS NULL AND resource_type IS NULL)
        OR (scope = 'SUBJECT' AND scope_id IS NOT NULL AND resource_type IS NULL)
        OR (
            scope = 'RESOURCE'
            AND scope_id IS NOT NULL
            AND resource_type IN (
                'LEGACY_UNTYPED', 'CHAT_SESSION', 'UPLOAD_OBJECT',
                'QUALITY_RULE_SET', 'QUALITY_VALIDATION_RUN'
            )
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    ADD CONSTRAINT ck_legal_holds_resource_semantics CHECK (
        scope <> 'RESOURCE'
        OR (
            resource_type = 'LEGACY_UNTYPED'
            AND data_class IN (
                'COMPLETED_OPERATIONS', 'CHAT_CONTENT',
                'AUDIT_EVIDENCE', 'OBJECT_DATA'
            )
        )
        OR (resource_type = 'CHAT_SESSION' AND data_class = 'CHAT_CONTENT')
        OR (resource_type = 'UPLOAD_OBJECT' AND data_class = 'OBJECT_DATA')
        OR (
            resource_type = 'QUALITY_RULE_SET'
            AND data_class IN ('QUALITY_RULE', 'QUALITY_AUDIT')
        )
        OR (
            resource_type = 'QUALITY_VALIDATION_RUN'
            AND data_class IN ('QUALITY_RESULT', 'QUALITY_AUDIT')
        )
    );
-- datariver-statement-boundary
DROP INDEX retention.ix_legal_holds_workspace_blocking_scope;
-- datariver-statement-boundary
CREATE INDEX ix_legal_holds_workspace_blocking_scope
ON retention.legal_holds (workspace_id, data_class, scope, resource_type, scope_id)
WHERE state <> 'RELEASED';
"""

_HOLD_GENERATION_SQL = """
CREATE OR REPLACE FUNCTION retention.advance_legal_hold_generation(
    p_workspace_id uuid,
    p_data_class text,
    p_event_kind text,
    p_hold_id uuid,
    p_hold_version integer,
    p_payload_hash text,
    p_scope text,
    p_resource_type text,
    p_scope_id uuid,
    p_state text
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, retention
AS $$
DECLARE
    event_hash text;
BEGIN
    event_hash := encode(
        sha256(convert_to(jsonb_build_object(
            'contract', 'LEGAL_HOLD_GENERATION_EVENT_V1',
            'event_kind', p_event_kind,
            'hold_id', p_hold_id::text,
            'hold_version', p_hold_version,
            'payload_hash', p_payload_hash,
            'scope', p_scope,
            'resource_type', p_resource_type,
            'scope_id', p_scope_id::text,
            'state', p_state
        )::text, 'UTF8')),
        'hex'
    );

    INSERT INTO retention.legal_hold_generations (
        id, workspace_id, data_class, generation, resolution_hash,
        version, created_at, updated_at
    )
    VALUES (
        gen_random_uuid(), p_workspace_id, p_data_class, 1,
        encode(sha256(convert_to(
            'LEGAL_HOLD_GENERATION_V1:1:' || event_hash, 'UTF8'
        )), 'hex'),
        1, transaction_timestamp(), transaction_timestamp()
    )
    ON CONFLICT (workspace_id, data_class) DO UPDATE
    SET generation = retention.legal_hold_generations.generation + 1,
        resolution_hash = encode(sha256(convert_to(
            retention.legal_hold_generations.resolution_hash || ':' ||
            (retention.legal_hold_generations.generation + 1)::text || ':' ||
            event_hash,
            'UTF8'
        )), 'hex'),
        version = retention.legal_hold_generations.version + 1,
        updated_at = transaction_timestamp();
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION retention.advance_legal_hold_generation(
    uuid, text, text, uuid, integer, text, text, text, uuid, text
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION retention.refresh_legal_hold_generation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, retention
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM retention.advance_legal_hold_generation(
            OLD.workspace_id, OLD.data_class, 'DELETE', OLD.id, OLD.version,
            OLD.payload_hash, OLD.scope, OLD.resource_type, OLD.scope_id, OLD.state
        );
        RETURN OLD;
    END IF;
    PERFORM retention.advance_legal_hold_generation(
        NEW.workspace_id, NEW.data_class, TG_OP, NEW.id, NEW.version,
        NEW.payload_hash, NEW.scope, NEW.resource_type, NEW.scope_id, NEW.state
    );
    IF TG_OP = 'UPDATE'
       AND (OLD.workspace_id, OLD.data_class) IS DISTINCT FROM
           (NEW.workspace_id, NEW.data_class) THEN
        PERFORM retention.advance_legal_hold_generation(
            OLD.workspace_id, OLD.data_class, 'UPDATE_OLD', OLD.id, OLD.version,
            OLD.payload_hash, OLD.scope, OLD.resource_type, OLD.scope_id, OLD.state
        );
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION retention.refresh_legal_hold_generation() FROM PUBLIC;
-- datariver-statement-boundary

CREATE TRIGGER refresh_legal_hold_generation
AFTER INSERT OR UPDATE OR DELETE ON retention.legal_holds
FOR EACH ROW EXECUTE FUNCTION retention.refresh_legal_hold_generation();
-- datariver-statement-boundary

INSERT INTO retention.legal_hold_generations (
    id, workspace_id, data_class, generation, resolution_hash,
    version, created_at, updated_at
)
SELECT
    gen_random_uuid(),
    workspace.id,
    kind.data_class,
    1,
    encode(sha256(convert_to(COALESCE(active_holds.hold_set, ''), 'UTF8')), 'hex'),
    1,
    transaction_timestamp(),
    transaction_timestamp()
FROM platform.workspaces AS workspace
CROSS JOIN (
    VALUES
        ('QUALITY_RULE'::text),
        ('QUALITY_RESULT'::text),
        ('QUALITY_AUDIT'::text)
) AS kind(data_class)
LEFT JOIN LATERAL (
    SELECT string_agg(
        hold.id::text || ':' || hold.version::text || ':' ||
        hold.payload_hash || ':' || hold.scope || ':' ||
        COALESCE(hold.resource_type, '-') || ':' ||
        COALESCE(hold.scope_id::text, '-'),
        '|' ORDER BY hold.id
    ) AS hold_set
    FROM retention.legal_holds AS hold
    WHERE hold.workspace_id = workspace.id
      AND hold.data_class = kind.data_class
      AND hold.state <> 'RELEASED'
) AS active_holds ON true
ON CONFLICT (workspace_id, data_class) DO NOTHING;
"""

_RESOLVER_SQL = """
CREATE OR REPLACE FUNCTION retention.resolve_quality_binding_v1(
    p_workspace_id uuid,
    p_data_class text,
    p_resource_type text,
    p_resource_id uuid,
    p_basis_at timestamptz
)
RETURNS TABLE (
    policy_id uuid,
    policy_number integer,
    policy_hash text,
    retain_until timestamptz,
    hold_generation bigint,
    hold_hash text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, retention
AS $$
DECLARE
    selected_policy retention.policy_versions%ROWTYPE;
    selected_rule retention.policy_class_rules%ROWTYPE;
    selected_generation retention.legal_hold_generations%ROWTYPE;
BEGIN
    IF p_data_class NOT IN ('QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT')
       OR p_resource_type NOT IN ('QUALITY_RULE_SET', 'QUALITY_VALIDATION_RUN')
       OR p_resource_id IS NULL
       OR p_basis_at IS DISTINCT FROM transaction_timestamp() THEN
        RAISE EXCEPTION 'invalid Quality retention binding request'
            USING ERRCODE = '23514';
    END IF;

    SELECT policy.* INTO selected_policy
    FROM retention.policy_versions AS policy
    WHERE policy.workspace_id = p_workspace_id
      AND policy.state = 'ACTIVE'
      AND policy.contract_version = 'POLICY_BOOK_V3'
      AND policy.effective_from <= p_basis_at
      AND (policy.effective_until IS NULL OR policy.effective_until > p_basis_at)
    FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quality retention requires an effective POLICY_BOOK_V3'
            USING ERRCODE = '23514';
    END IF;

    SELECT class_rule.* INTO selected_rule
    FROM retention.policy_class_rules AS class_rule
    WHERE class_rule.workspace_id = p_workspace_id
      AND class_rule.policy_id = selected_policy.id
      AND class_rule.policy_hash = selected_policy.payload_hash
      AND class_rule.policy_number = selected_policy.policy_number
      AND class_rule.data_class = p_data_class
    FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quality retention class rule is unavailable'
            USING ERRCODE = '23514';
    END IF;

    SELECT generation.* INTO selected_generation
    FROM retention.legal_hold_generations AS generation
    WHERE generation.workspace_id = p_workspace_id
      AND generation.data_class = p_data_class
    FOR UPDATE;
    IF NOT FOUND THEN
        INSERT INTO retention.legal_hold_generations (
            id, workspace_id, data_class, generation, resolution_hash,
            version, created_at, updated_at
        )
        VALUES (
            gen_random_uuid(), p_workspace_id, p_data_class, 1,
            encode(sha256(convert_to('', 'UTF8')), 'hex'),
            1, transaction_timestamp(), transaction_timestamp()
        )
        ON CONFLICT (workspace_id, data_class) DO NOTHING;
        SELECT generation.* INTO selected_generation
        FROM retention.legal_hold_generations AS generation
        WHERE generation.workspace_id = p_workspace_id
          AND generation.data_class = p_data_class
        FOR UPDATE;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM retention.legal_holds AS hold
        WHERE hold.workspace_id = p_workspace_id
          AND hold.data_class = p_data_class
          AND hold.state <> 'RELEASED'
          AND hold.scope = 'RESOURCE'
          AND hold.scope_id = p_resource_id
          AND hold.resource_type IS DISTINCT FROM p_resource_type
          AND hold.resource_type <> 'LEGACY_UNTYPED'
    ) THEN
        RAISE EXCEPTION 'ambiguous typed Quality Legal Hold resolution'
            USING ERRCODE = '23514';
    END IF;

    policy_id := selected_policy.id;
    policy_number := selected_policy.policy_number;
    policy_hash := selected_policy.payload_hash;
    retain_until := CASE selected_rule.unit
        WHEN 'DAYS' THEN p_basis_at + make_interval(days => selected_rule.minimum_value)
        WHEN 'MONTHS' THEN p_basis_at + make_interval(months => selected_rule.minimum_value)
        WHEN 'YEARS' THEN p_basis_at + make_interval(years => selected_rule.minimum_value)
        ELSE NULL
    END;
    hold_generation := selected_generation.generation;
    hold_hash := selected_generation.resolution_hash;
    IF retain_until IS NULL OR retain_until <= p_basis_at THEN
        RAISE EXCEPTION 'invalid Quality retention deadline'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEXT;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION retention.resolve_quality_binding_v1(
    uuid, text, text, uuid, timestamptz
) FROM PUBLIC;
"""

_QUALITY_SECURITY_SQL = """
CREATE OR REPLACE FUNCTION quality.current_human_can(
    p_workspace_id uuid,
    p_action text,
    p_classification integer,
    p_system_id uuid,
    p_domain_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam
AS $$
    SELECT EXISTS (
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
          AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
          AND NOT (
              COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
              ? 'service-accounts'
          )
          AND membership.clearance >= p_classification
          AND (
              p_system_id IS NULL
              OR p_classification = 0
              OR COALESCE(
                  membership.attributes -> 'allowed_system_ids',
                  '[]'::jsonb
              ) ? p_system_id::text
          )
          AND (
              p_domain_id IS NULL
              OR p_classification = 0
              OR COALESCE(
                  membership.attributes -> 'allowed_domain_ids',
                  '[]'::jsonb
              ) ? p_domain_id::text
          )
          AND COALESCE(
              membership.attributes -> 'allowed_actions',
              '[]'::jsonb
          ) ? p_action
          AND NOT (
              COALESCE(
                  membership.attributes -> 'denied_actions',
                  '[]'::jsonb
              ) ? p_action
          )
    )
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.current_human_can(
    uuid, text, integer, uuid, uuid
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.can_read_asset(
    p_workspace_id uuid,
    p_asset_id uuid,
    p_pinned_classification integer DEFAULT NULL,
    p_pinned_system_id uuid DEFAULT NULL,
    p_pinned_domain_id uuid DEFAULT NULL
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, catalog, quality
AS $$
    SELECT quality.current_human_can(
        asset.workspace_id,
        'quality.read',
        GREATEST(asset.classification, COALESCE(p_pinned_classification, 0)),
        CASE
            WHEN p_pinned_system_id IS NOT NULL
                 AND asset.system_id IS DISTINCT FROM p_pinned_system_id
            THEN NULL
            ELSE COALESCE(p_pinned_system_id, asset.system_id)
        END,
        CASE
            WHEN p_pinned_domain_id IS NOT NULL
                 AND asset.domain_id IS DISTINCT FROM p_pinned_domain_id
            THEN NULL
            ELSE COALESCE(p_pinned_domain_id, asset.domain_id)
        END
    )
    AND (
        p_pinned_system_id IS NULL
        OR asset.system_id IS NOT DISTINCT FROM p_pinned_system_id
        OR (
            quality.current_human_can(
                asset.workspace_id,
                'quality.read',
                GREATEST(asset.classification, COALESCE(p_pinned_classification, 0)),
                asset.system_id,
                asset.domain_id
            )
            AND quality.current_human_can(
                asset.workspace_id,
                'quality.read',
                GREATEST(asset.classification, COALESCE(p_pinned_classification, 0)),
                p_pinned_system_id,
                p_pinned_domain_id
            )
        )
    )
    AND (
        p_pinned_domain_id IS NULL
        OR asset.domain_id IS NOT DISTINCT FROM p_pinned_domain_id
        OR (
            quality.current_human_can(
                asset.workspace_id,
                'quality.read',
                GREATEST(asset.classification, COALESCE(p_pinned_classification, 0)),
                asset.system_id,
                asset.domain_id
            )
            AND quality.current_human_can(
                asset.workspace_id,
                'quality.read',
                GREATEST(asset.classification, COALESCE(p_pinned_classification, 0)),
                p_pinned_system_id,
                p_pinned_domain_id
            )
        )
    )
    FROM catalog.assets_projection AS asset
    WHERE asset.workspace_id = p_workspace_id
      AND asset.id = p_asset_id
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.can_read_asset(uuid, uuid, integer, uuid, uuid) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.current_target_matches_v1(
    p_workspace_id uuid,
    p_asset_id uuid,
    p_classification integer,
    p_system_id uuid,
    p_domain_id uuid,
    p_lifecycle text,
    p_source_version text,
    p_action text
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
          AND quality.current_human_can(
              asset.workspace_id, p_action, asset.classification,
              asset.system_id, asset.domain_id
          )
    )
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.current_target_matches_v1(
    uuid, uuid, integer, uuid, uuid, text, text, text
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.enforce_rule_set_binding_v1()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, retention
AS $$
DECLARE
    resolved_rule record;
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    workspace_id uuid := NULLIF(current_setting('app.workspace_id', true), '')::uuid;
BEGIN
    IF NEW.workspace_id IS DISTINCT FROM workspace_id
       OR NEW.created_by IS DISTINCT FROM actor_id
       OR NEW.updated_by IS DISTINCT FROM actor_id
       OR NEW.state <> 'ACTIVE'
       OR NEW.archived_at IS NOT NULL
       OR NEW.version <> 1 THEN
        RAISE EXCEPTION 'invalid initial Quality rule-set actor or state'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO resolved_rule
    FROM retention.resolve_quality_binding_v1(
        NEW.workspace_id, 'QUALITY_RULE', 'QUALITY_RULE_SET',
        NEW.id, NEW.rule_retention_basis_at
    );
    IF ROW(
        NEW.rule_retention_policy_id,
        NEW.rule_retention_policy_number,
        NEW.rule_retention_policy_hash,
        NEW.rule_retain_until,
        NEW.rule_hold_generation,
        NEW.rule_hold_hash
    ) IS DISTINCT FROM ROW(
        resolved_rule.policy_id,
        resolved_rule.policy_number,
        resolved_rule.policy_hash,
        resolved_rule.retain_until,
        resolved_rule.hold_generation,
        resolved_rule.hold_hash
    ) THEN
        RAISE EXCEPTION 'Quality rule-set retention binding drift'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.enforce_rule_set_binding_v1() FROM PUBLIC;
-- datariver-statement-boundary

CREATE TRIGGER enforce_rule_set_binding
BEFORE INSERT ON quality.rule_sets
FOR EACH ROW EXECUTE FUNCTION quality.enforce_rule_set_binding_v1();
"""

_IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION quality.reject_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'Quality evidence is append-only'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.reject_evidence_mutation() FROM PUBLIC;
"""

_RUN_ATTEMPT_INVARIANT_SQL = """
CREATE OR REPLACE FUNCTION quality.assert_run_attempt_shape_v1()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality
AS $$
DECLARE
    selected_run quality.validation_runs%ROWTYPE;
    selected_attempt quality.validation_attempts%ROWTYPE;
BEGIN
    IF TG_TABLE_NAME = 'validation_runs' THEN
        selected_run := NEW;
    ELSE
        SELECT * INTO selected_run
        FROM quality.validation_runs AS run
        WHERE run.workspace_id = NEW.workspace_id
          AND run.current_attempt_id = NEW.id;
        IF NOT FOUND THEN
            RETURN NEW;
        END IF;
    END IF;
    IF selected_run.current_attempt_id IS NULL THEN
        IF selected_run.state NOT IN ('QUEUED', 'CANCELLED')
           OR selected_run.attempt_count <> 0
           OR selected_run.lease_epoch <> 0 THEN
            RAISE EXCEPTION 'Quality run requires a current attempt'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO selected_attempt
    FROM quality.validation_attempts AS attempt
    WHERE attempt.workspace_id = selected_run.workspace_id
      AND attempt.run_id = selected_run.id
      AND attempt.id = selected_run.current_attempt_id;
    IF NOT FOUND
       OR selected_attempt.attempt_no <> selected_run.attempt_count
       OR selected_attempt.lease_epoch <> selected_run.lease_epoch
       OR (
           selected_run.state IN ('RUNNING', 'CANCEL_REQUESTED')
           AND selected_attempt.lease_token_hash
               IS DISTINCT FROM selected_run.lease_token_hash
       )
       OR NOT (
        (selected_run.state IN ('RUNNING', 'CANCEL_REQUESTED')
            AND selected_attempt.state = 'RUNNING')
        OR (selected_run.state = 'RETRY_WAIT'
            AND selected_attempt.state = 'RETRYABLE_FAILED')
        OR (selected_run.state = 'SUCCEEDED'
            AND selected_attempt.state = 'SUCCEEDED')
        OR (selected_run.state = 'FAILED'
            AND selected_attempt.state = 'FAILED')
        OR (selected_run.state = 'STALE'
            AND selected_attempt.state = 'STALE')
        OR (selected_run.state = 'CANCELLED'
            AND selected_attempt.state IN ('CANCELLED', 'RETRYABLE_FAILED'))
    ) THEN
        RAISE EXCEPTION 'Quality run/current-attempt state mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.assert_run_attempt_shape_v1() FROM PUBLIC;
-- datariver-statement-boundary
CREATE CONSTRAINT TRIGGER enforce_run_attempt_shape
AFTER INSERT OR UPDATE ON quality.validation_runs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quality.assert_run_attempt_shape_v1();
-- datariver-statement-boundary
CREATE CONSTRAINT TRIGGER enforce_run_attempt_shape
AFTER INSERT OR UPDATE ON quality.validation_attempts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quality.assert_run_attempt_shape_v1();
"""

_RUN_RESULT_INVARIANT_SQL = """
CREATE OR REPLACE FUNCTION quality.assert_run_results_shape_v1()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality
AS $$
DECLARE
    selected_run quality.validation_runs%ROWTYPE;
    target_workspace_id uuid;
    target_run_id uuid;
    expected_count bigint;
    actual_count bigint;
    actual_passed bigint;
    actual_advisory bigint;
    actual_blocking bigint;
    expected_outcome text;
BEGIN
    IF TG_TABLE_NAME = 'validation_runs' THEN
        selected_run := NEW;
    ELSE
        IF TG_OP = 'DELETE' THEN
            target_workspace_id := OLD.workspace_id;
            target_run_id := OLD.run_id;
        ELSE
            target_workspace_id := NEW.workspace_id;
            target_run_id := NEW.run_id;
        END IF;
        SELECT * INTO selected_run
        FROM quality.validation_runs AS run
        WHERE run.workspace_id = target_workspace_id
          AND run.id = target_run_id;
        IF NOT FOUND THEN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END IF;
    END IF;

    SELECT count(*) INTO actual_count
    FROM quality.expectation_results AS result
    WHERE result.workspace_id = selected_run.workspace_id
      AND result.run_id = selected_run.id;
    IF selected_run.state <> 'SUCCEEDED' THEN
        IF actual_count <> 0 THEN
            RAISE EXCEPTION 'Only a successful Quality run may own results'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT count(*) INTO expected_count
        FROM quality.rule_definitions AS definition
        WHERE definition.workspace_id = selected_run.workspace_id
          AND definition.rule_set_version_id = selected_run.rule_set_version_id;
        SELECT
            count(*) FILTER (WHERE result.outcome = 'PASS'),
            count(*) FILTER (WHERE result.outcome = 'ADVISORY_FAIL'),
            count(*) FILTER (WHERE result.outcome = 'BLOCKING_FAIL')
        INTO actual_passed, actual_advisory, actual_blocking
        FROM quality.expectation_results AS result
        WHERE result.workspace_id = selected_run.workspace_id
          AND result.run_id = selected_run.id;
        expected_outcome := CASE
            WHEN actual_blocking > 0 THEN 'FAIL'
            WHEN actual_advisory > 0 THEN 'WARN'
            ELSE 'PASS'
        END;
        IF expected_count = 0
           OR actual_count <> expected_count
           OR selected_run.passed_count IS DISTINCT FROM actual_passed
           OR selected_run.advisory_failed_count IS DISTINCT FROM actual_advisory
           OR selected_run.blocking_failed_count IS DISTINCT FROM actual_blocking
           OR selected_run.quality_outcome IS DISTINCT FROM expected_outcome THEN
            RAISE EXCEPTION 'Quality successful-run result coverage is incomplete'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.assert_run_results_shape_v1() FROM PUBLIC;
-- datariver-statement-boundary
CREATE CONSTRAINT TRIGGER enforce_run_results_shape
AFTER INSERT OR UPDATE ON quality.validation_runs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quality.assert_run_results_shape_v1();
-- datariver-statement-boundary
CREATE CONSTRAINT TRIGGER enforce_run_results_shape
AFTER INSERT OR UPDATE OR DELETE ON quality.expectation_results
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION quality.assert_run_results_shape_v1();
"""

_TRANSITION_SQL = """
CREATE OR REPLACE FUNCTION quality.require_human_decision_v1(
    p_workspace_id uuid,
    p_subject_id uuid,
    p_resource_id uuid,
    p_action text,
    p_policy_decision_id uuid,
    p_require_hardware boolean
)
RETURNS TABLE(
    authentication_time timestamptz,
    authorization_hash text,
    assurance_hash text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, authz
AS $$
DECLARE
    selected_decision authz.policy_decisions%ROWTYPE;
BEGIN
    IF p_subject_id IS DISTINCT FROM
       NULLIF(current_setting('app.subject_id', true), '')::uuid
       OR p_workspace_id IS DISTINCT FROM
          NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Quality command security context mismatch'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO selected_decision
    FROM authz.policy_decisions
    WHERE workspace_id = p_workspace_id
      AND id = p_policy_decision_id
      AND subject_id = p_subject_id
      AND resource_id = p_resource_id
      AND action = p_action
      AND effect = 'ALLOW'
      AND decided_at <= transaction_timestamp()
      AND decided_at >= transaction_timestamp() - interval '15 minutes';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quality command authorization decision is invalid'
            USING ERRCODE = '42501';
    END IF;
    IF selected_decision.evaluation_context ->> 'authentication_time' IS NOT NULL THEN
        authentication_time :=
            (selected_decision.evaluation_context ->> 'authentication_time')::timestamptz;
        IF authentication_time > selected_decision.decided_at
           OR authentication_time > transaction_timestamp() THEN
            RAISE EXCEPTION 'authentication evidence is invalid'
                USING ERRCODE = '42501';
        END IF;
    END IF;
    IF p_require_hardware THEN
        IF selected_decision.evaluation_context ->> 'authentication_assurance'
           <> 'HARDWARE_WEBAUTHN'
           OR authentication_time IS NULL THEN
            RAISE EXCEPTION 'recent hardware WebAuthn is required'
                USING ERRCODE = '42501';
        END IF;
        IF authentication_time < transaction_timestamp() - interval '15 minutes' THEN
            RAISE EXCEPTION 'hardware WebAuthn evidence is stale or invalid'
                USING ERRCODE = '42501';
        END IF;
    END IF;
    authorization_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_AUTHORIZATION_EVIDENCE_V1',
        'decision_id', selected_decision.id::text,
        'workspace_id', selected_decision.workspace_id::text,
        'subject_id', selected_decision.subject_id::text,
        'resource_id', selected_decision.resource_id::text,
        'action', selected_decision.action,
        'effect', selected_decision.effect,
        'reason_codes', selected_decision.reason_codes,
        'policy_versions', selected_decision.policy_versions,
        'evaluation_context', selected_decision.evaluation_context,
        'request_id', selected_decision.request_id,
        'decided_at', selected_decision.decided_at
    )::text, 'UTF8')), 'hex');
    assurance_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_ASSURANCE_EVIDENCE_V1',
        'decision_id', selected_decision.id::text,
        'assurance',
            selected_decision.evaluation_context ->> 'authentication_assurance',
        'authentication_time', authentication_time
    )::text, 'UTF8')), 'hex');
    RETURN NEXT;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.require_human_decision_v1(
    uuid, uuid, uuid, text, uuid, boolean
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.review_rule_set_version_v1(
    p_workspace_id uuid,
    p_version_id uuid,
    p_decision text,
    p_reason text,
    p_policy_decision_id uuid,
    p_assurance_hash text,
    p_expected_version integer,
    p_audit_policy_id uuid,
    p_audit_policy_number integer,
    p_audit_policy_hash text,
    p_audit_retain_until timestamptz,
    p_audit_hold_generation bigint,
    p_audit_hold_hash text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, retention
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    candidate quality.rule_set_versions%ROWTYPE;
    resolved record;
    decision_evidence record;
    review_id uuid := gen_random_uuid();
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'invalid Quality review command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO candidate
    FROM quality.rule_set_versions
    WHERE workspace_id = p_workspace_id AND id = p_version_id
    FOR UPDATE;
    IF NOT FOUND OR candidate.state <> 'PROPOSED'
       OR candidate.version <> p_expected_version
       OR p_decision NOT IN ('APPROVE','REJECT')
       OR char_length(btrim(p_reason)) NOT BETWEEN 1 AND 4000
       OR actor_id = candidate.author_id
       OR NOT quality.current_target_matches_v1(
           p_workspace_id, candidate.asset_id, candidate.classification,
           candidate.system_id, candidate.domain_id, candidate.lifecycle,
           candidate.source_version, 'quality.rule.review'
       ) THEN
        RAISE EXCEPTION 'invalid Quality review command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO decision_evidence
    FROM quality.require_human_decision_v1(
        p_workspace_id, actor_id, p_version_id, 'quality.rule.review',
        p_policy_decision_id, false
    );
    IF p_assurance_hash IS DISTINCT FROM decision_evidence.assurance_hash THEN
        RAISE EXCEPTION 'Quality review assurance evidence drift'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO resolved
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id, 'QUALITY_AUDIT', 'QUALITY_RULE_SET',
        candidate.rule_set_id, transaction_timestamp()
    );
    IF ROW(
        p_audit_policy_id, p_audit_policy_number, p_audit_policy_hash,
        p_audit_retain_until, p_audit_hold_generation, p_audit_hold_hash
    ) IS DISTINCT FROM ROW(
        resolved.policy_id, resolved.policy_number, resolved.policy_hash,
        resolved.retain_until, resolved.hold_generation, resolved.hold_hash
    ) THEN
        RAISE EXCEPTION 'Quality review retention binding drift'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO quality.rule_reviews (
        id, workspace_id, rule_set_version_id, decision, actor_id, reason,
        policy_decision_id, assurance_hash, target_binding_hash,
        audit_retention_kind, audit_retention_policy_id,
        audit_retention_policy_number, audit_retention_policy_hash,
        audit_retention_basis_at, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    VALUES (
        review_id, p_workspace_id, p_version_id, p_decision, actor_id, btrim(p_reason),
        p_policy_decision_id, p_assurance_hash, candidate.target_binding_hash,
        'QUALITY_AUDIT', p_audit_policy_id, p_audit_policy_number,
        p_audit_policy_hash, transaction_timestamp(), p_audit_retain_until,
        p_audit_hold_generation, p_audit_hold_hash, transaction_timestamp()
    );
    UPDATE quality.rule_set_versions
    SET state = CASE p_decision WHEN 'APPROVE' THEN 'APPROVED' ELSE 'REJECTED' END,
        reviewed_by = actor_id,
        reviewed_at = transaction_timestamp(),
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id AND id = p_version_id;
    RETURN review_id;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.review_rule_set_version_v1(
    uuid, uuid, text, text, uuid, text, integer,
    uuid, integer, text, timestamptz, bigint, text
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.activate_rule_set_version_v1(
    p_workspace_id uuid,
    p_version_id uuid,
    p_policy_decision_id uuid,
    p_webauthn_evidence_hash text,
    p_authorization_hash text,
    p_schedule_binding_hash text,
    p_retention_binding_hash text,
    p_idempotency_key_hash text,
    p_expected_version integer,
    p_audit_policy_id uuid,
    p_audit_policy_number integer,
    p_audit_policy_hash text,
    p_audit_retain_until timestamptz,
    p_audit_hold_generation bigint,
    p_audit_hold_hash text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, retention
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    candidate quality.rule_set_versions%ROWTYPE;
    prior_active quality.rule_set_versions%ROWTYPE;
    parent quality.rule_sets%ROWTYPE;
    resolved_rule record;
    resolved_audit record;
    decision_evidence record;
    existing_command quality.rule_command_events%ROWTYPE;
    calculated_schedule_hash text;
    calculated_retention_hash text;
    calculated_request_hash text;
    superseded_schedule_hash text;
    superseded_retention_hash text;
    supersede_request_hash text;
    supersede_idempotency_hash text;
    supersede_command_id uuid := gen_random_uuid();
    command_id uuid := gen_random_uuid();
    next_sequence bigint;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'invalid Quality activation command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO candidate
    FROM quality.rule_set_versions
    WHERE workspace_id = p_workspace_id AND id = p_version_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quality Rule Set Version is unavailable'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO parent
    FROM quality.rule_sets
    WHERE workspace_id = p_workspace_id AND id = candidate.rule_set_id
    FOR UPDATE;
    SELECT * INTO prior_active
    FROM quality.rule_set_versions
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = candidate.rule_set_id
      AND state = 'ACTIVE'
      AND id <> p_version_id
    FOR UPDATE;
    calculated_request_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_ACTIVATE_REQUEST_V1',
        'workspace_id', p_workspace_id::text,
        'version_id', p_version_id::text,
        'actor_id', actor_id::text,
        'policy_decision_id', p_policy_decision_id::text,
        'webauthn_evidence_hash', p_webauthn_evidence_hash,
        'authorization_hash', p_authorization_hash,
        'schedule_binding_hash', p_schedule_binding_hash,
        'retention_binding_hash', p_retention_binding_hash,
        'expected_version', p_expected_version,
        'audit_policy_id', p_audit_policy_id::text,
        'audit_policy_number', p_audit_policy_number,
        'audit_policy_hash', p_audit_policy_hash,
        'audit_retain_until', p_audit_retain_until,
        'audit_hold_generation', p_audit_hold_generation,
        'audit_hold_hash', p_audit_hold_hash
    )::text, 'UTF8')), 'hex');
    SELECT * INTO existing_command
    FROM quality.rule_command_events
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = candidate.rule_set_id
      AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing_command.command = 'ACTIVATE'
           AND existing_command.rule_set_version_id = p_version_id
           AND existing_command.request_hash = calculated_request_hash THEN
            RETURN existing_command.id;
        END IF;
        RAISE EXCEPTION 'Quality activation idempotency conflict'
            USING ERRCODE = '23505';
    END IF;
    IF candidate.state <> 'APPROVED'
       OR candidate.version <> p_expected_version
       OR parent.state <> 'ACTIVE'
       OR actor_id = candidate.author_id
       OR candidate.schedule_mode <> 'MANUAL_ONLY'
       OR NOT EXISTS (
           SELECT 1 FROM quality.rule_definitions AS definition
           WHERE definition.workspace_id = p_workspace_id
             AND definition.rule_set_version_id = p_version_id
       )
       OR NOT quality.current_target_matches_v1(
           p_workspace_id, candidate.asset_id, candidate.classification,
           candidate.system_id, candidate.domain_id, candidate.lifecycle,
           candidate.source_version, 'quality.rule.activate'
       ) THEN
        RAISE EXCEPTION 'invalid Quality activation command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO decision_evidence
    FROM quality.require_human_decision_v1(
        p_workspace_id, actor_id, p_version_id, 'quality.rule.activate',
        p_policy_decision_id, true
    );
    IF p_authorization_hash IS DISTINCT FROM decision_evidence.authorization_hash
       OR p_webauthn_evidence_hash IS DISTINCT FROM decision_evidence.assurance_hash THEN
        RAISE EXCEPTION 'Quality activation authorization evidence drift'
            USING ERRCODE = '23514';
    END IF;
    calculated_schedule_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_SCHEDULE_BINDING_V1',
        'mode', candidate.schedule_mode,
        'profile_id', candidate.schedule_profile_id,
        'profile_version', candidate.schedule_profile_version,
        'profile_hash', candidate.schedule_profile_hash
    )::text, 'UTF8')), 'hex');
    IF p_schedule_binding_hash IS DISTINCT FROM calculated_schedule_hash THEN
        RAISE EXCEPTION 'Quality activation schedule evidence drift'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO resolved_rule
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id, 'QUALITY_RULE', 'QUALITY_RULE_SET',
        candidate.rule_set_id, transaction_timestamp()
    );
    IF ROW(
        candidate.rule_retention_policy_id,
        candidate.rule_retention_policy_number,
        candidate.rule_retention_policy_hash,
        candidate.rule_hold_generation,
        candidate.rule_hold_hash
    ) IS DISTINCT FROM ROW(
        resolved_rule.policy_id, resolved_rule.policy_number,
        resolved_rule.policy_hash, resolved_rule.hold_generation,
        resolved_rule.hold_hash
    ) OR candidate.rule_retain_until <= transaction_timestamp() THEN
        RAISE EXCEPTION 'Quality Rule retention binding drift'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO resolved_audit
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id, 'QUALITY_AUDIT', 'QUALITY_RULE_SET',
        candidate.rule_set_id, transaction_timestamp()
    );
    IF ROW(
        p_audit_policy_id, p_audit_policy_number, p_audit_policy_hash,
        p_audit_retain_until, p_audit_hold_generation, p_audit_hold_hash
    ) IS DISTINCT FROM ROW(
        resolved_audit.policy_id, resolved_audit.policy_number,
        resolved_audit.policy_hash, resolved_audit.retain_until,
        resolved_audit.hold_generation, resolved_audit.hold_hash
    ) THEN
        RAISE EXCEPTION 'Quality activation audit binding drift'
            USING ERRCODE = '23514';
    END IF;
    calculated_retention_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_COMMAND_RETENTION_BINDING_V1',
        'rule_policy_id', resolved_rule.policy_id::text,
        'rule_policy_number', resolved_rule.policy_number,
        'rule_policy_hash', resolved_rule.policy_hash,
        'rule_retain_until', resolved_rule.retain_until,
        'rule_hold_generation', resolved_rule.hold_generation,
        'rule_hold_hash', resolved_rule.hold_hash,
        'audit_policy_id', resolved_audit.policy_id::text,
        'audit_policy_number', resolved_audit.policy_number,
        'audit_policy_hash', resolved_audit.policy_hash,
        'audit_retain_until', resolved_audit.retain_until,
        'audit_hold_generation', resolved_audit.hold_generation,
        'audit_hold_hash', resolved_audit.hold_hash
    )::text, 'UTF8')), 'hex');
    IF p_retention_binding_hash IS DISTINCT FROM calculated_retention_hash THEN
        RAISE EXCEPTION 'Quality activation retention evidence drift'
            USING ERRCODE = '23514';
    END IF;
    IF prior_active.id IS NOT NULL THEN
        superseded_schedule_hash := encode(sha256(convert_to(jsonb_build_object(
            'contract', 'QUALITY_SCHEDULE_BINDING_V1',
            'mode', prior_active.schedule_mode,
            'profile_id', prior_active.schedule_profile_id,
            'profile_version', prior_active.schedule_profile_version,
            'profile_hash', prior_active.schedule_profile_hash
        )::text, 'UTF8')), 'hex');
        superseded_retention_hash := encode(sha256(convert_to(jsonb_build_object(
            'contract', 'QUALITY_COMMAND_RETENTION_BINDING_V1',
            'rule_policy_id', prior_active.rule_retention_policy_id::text,
            'rule_policy_number', prior_active.rule_retention_policy_number,
            'rule_policy_hash', prior_active.rule_retention_policy_hash,
            'rule_retain_until', prior_active.rule_retain_until,
            'rule_hold_generation', prior_active.rule_hold_generation,
            'rule_hold_hash', prior_active.rule_hold_hash,
            'audit_policy_id', resolved_audit.policy_id::text,
            'audit_policy_number', resolved_audit.policy_number,
            'audit_policy_hash', resolved_audit.policy_hash,
            'audit_retain_until', resolved_audit.retain_until,
            'audit_hold_generation', resolved_audit.hold_generation,
            'audit_hold_hash', resolved_audit.hold_hash
        )::text, 'UTF8')), 'hex');
        supersede_request_hash := encode(sha256(convert_to(jsonb_build_object(
            'contract', 'QUALITY_SUPERSEDE_REQUEST_V1',
            'activation_request_hash', calculated_request_hash,
            'superseded_version_id', prior_active.id::text
        )::text, 'UTF8')), 'hex');
        supersede_idempotency_hash := encode(sha256(convert_to(
            'QUALITY_SUPERSEDE_V1:' || p_idempotency_key_hash || ':' ||
            prior_active.id::text,
            'UTF8'
        )), 'hex');
    END IF;

    UPDATE quality.rule_set_versions
    SET state = 'SUPERSEDED',
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = candidate.rule_set_id
      AND state = 'ACTIVE';
    UPDATE quality.rule_schedules
    SET state = 'INACTIVE',
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = candidate.rule_set_id
      AND state = 'ACTIVE';
    UPDATE quality.rule_set_versions
    SET state = 'ACTIVE',
        activated_by = actor_id,
        activated_at = transaction_timestamp(),
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id AND id = p_version_id;

    SELECT COALESCE(max(sequence), 0) + 1 INTO next_sequence
    FROM quality.rule_command_events
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = candidate.rule_set_id;
    IF prior_active.id IS NOT NULL THEN
        INSERT INTO quality.rule_command_events (
            id, workspace_id, rule_set_id, rule_set_version_id, sequence,
            command, actor_id, actor_kind, webauthn_evidence_hash,
            authentication_time, authorization_hash, target_binding_hash,
            schedule_binding_hash, retention_binding_hash, request_hash,
            idempotency_key_hash,
            audit_retention_kind, audit_retention_policy_id,
            audit_retention_policy_number, audit_retention_policy_hash,
            audit_retention_basis_at, audit_retain_until,
            audit_hold_generation, audit_hold_hash, occurred_at
        )
        VALUES (
            supersede_command_id, p_workspace_id, candidate.rule_set_id,
            prior_active.id, next_sequence, 'SUPERSEDE', actor_id, 'HUMAN',
            decision_evidence.assurance_hash, decision_evidence.authentication_time,
            decision_evidence.authorization_hash, prior_active.target_binding_hash,
            superseded_schedule_hash, superseded_retention_hash,
            supersede_request_hash, supersede_idempotency_hash,
            'QUALITY_AUDIT', p_audit_policy_id, p_audit_policy_number,
            p_audit_policy_hash, transaction_timestamp(), p_audit_retain_until,
            p_audit_hold_generation, p_audit_hold_hash, transaction_timestamp()
        );
        next_sequence := next_sequence + 1;
    END IF;
    INSERT INTO quality.rule_command_events (
        id, workspace_id, rule_set_id, rule_set_version_id, sequence,
        command, actor_id, actor_kind, webauthn_evidence_hash,
        authentication_time, authorization_hash, target_binding_hash,
        schedule_binding_hash, retention_binding_hash, request_hash,
        idempotency_key_hash,
        audit_retention_kind, audit_retention_policy_id,
        audit_retention_policy_number, audit_retention_policy_hash,
        audit_retention_basis_at, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    VALUES (
        command_id, p_workspace_id, candidate.rule_set_id, p_version_id,
        next_sequence, 'ACTIVATE', actor_id, 'HUMAN',
        decision_evidence.assurance_hash, decision_evidence.authentication_time,
        decision_evidence.authorization_hash,
        candidate.target_binding_hash, calculated_schedule_hash,
        calculated_retention_hash, calculated_request_hash, p_idempotency_key_hash,
        'QUALITY_AUDIT', p_audit_policy_id, p_audit_policy_number,
        p_audit_policy_hash, transaction_timestamp(), p_audit_retain_until,
        p_audit_hold_generation, p_audit_hold_hash, transaction_timestamp()
    );
    RETURN command_id;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.activate_rule_set_version_v1(
    uuid, uuid, uuid, text, text, text, text, text, integer,
    uuid, integer, text, timestamptz, bigint, text
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.revoke_rule_set_version_v1(
    p_workspace_id uuid,
    p_version_id uuid,
    p_policy_decision_id uuid,
    p_webauthn_evidence_hash text,
    p_authorization_hash text,
    p_retention_binding_hash text,
    p_idempotency_key_hash text,
    p_expected_version integer,
    p_audit_policy_id uuid,
    p_audit_policy_number integer,
    p_audit_policy_hash text,
    p_audit_retain_until timestamptz,
    p_audit_hold_generation bigint,
    p_audit_hold_hash text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, retention
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    candidate quality.rule_set_versions%ROWTYPE;
    resolved_audit record;
    decision_evidence record;
    existing_command quality.rule_command_events%ROWTYPE;
    calculated_schedule_hash text;
    calculated_retention_hash text;
    calculated_request_hash text;
    command_id uuid := gen_random_uuid();
    next_sequence bigint;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'invalid Quality revoke command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO candidate
    FROM quality.rule_set_versions
    WHERE workspace_id = p_workspace_id AND id = p_version_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invalid Quality revoke command'
            USING ERRCODE = '42501';
    END IF;
    calculated_request_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_REVOKE_REQUEST_V1',
        'workspace_id', p_workspace_id::text,
        'version_id', p_version_id::text,
        'actor_id', actor_id::text,
        'policy_decision_id', p_policy_decision_id::text,
        'webauthn_evidence_hash', p_webauthn_evidence_hash,
        'authorization_hash', p_authorization_hash,
        'retention_binding_hash', p_retention_binding_hash,
        'expected_version', p_expected_version,
        'audit_policy_id', p_audit_policy_id::text,
        'audit_policy_number', p_audit_policy_number,
        'audit_policy_hash', p_audit_policy_hash,
        'audit_retain_until', p_audit_retain_until,
        'audit_hold_generation', p_audit_hold_generation,
        'audit_hold_hash', p_audit_hold_hash
    )::text, 'UTF8')), 'hex');
    SELECT * INTO existing_command
    FROM quality.rule_command_events
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = candidate.rule_set_id
      AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing_command.command = 'REVOKE'
           AND existing_command.rule_set_version_id = p_version_id
           AND existing_command.request_hash = calculated_request_hash THEN
            RETURN existing_command.id;
        END IF;
        RAISE EXCEPTION 'Quality revoke idempotency conflict'
            USING ERRCODE = '23505';
    END IF;
    IF candidate.state <> 'ACTIVE'
       OR candidate.version <> p_expected_version
       OR NOT quality.current_human_can(
           p_workspace_id, 'quality.rule.revoke', candidate.classification,
           candidate.system_id, candidate.domain_id
       ) THEN
        RAISE EXCEPTION 'invalid Quality revoke command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO decision_evidence
    FROM quality.require_human_decision_v1(
        p_workspace_id, actor_id, p_version_id, 'quality.rule.revoke',
        p_policy_decision_id, true
    );
    IF p_authorization_hash IS DISTINCT FROM decision_evidence.authorization_hash
       OR p_webauthn_evidence_hash IS DISTINCT FROM decision_evidence.assurance_hash THEN
        RAISE EXCEPTION 'Quality revoke authorization evidence drift'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO resolved_audit
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id, 'QUALITY_AUDIT', 'QUALITY_RULE_SET',
        candidate.rule_set_id, transaction_timestamp()
    );
    IF ROW(
        p_audit_policy_id, p_audit_policy_number, p_audit_policy_hash,
        p_audit_retain_until, p_audit_hold_generation, p_audit_hold_hash
    ) IS DISTINCT FROM ROW(
        resolved_audit.policy_id, resolved_audit.policy_number,
        resolved_audit.policy_hash, resolved_audit.retain_until,
        resolved_audit.hold_generation, resolved_audit.hold_hash
    ) THEN
        RAISE EXCEPTION 'Quality revoke audit binding drift'
            USING ERRCODE = '23514';
    END IF;
    calculated_schedule_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_SCHEDULE_BINDING_V1',
        'mode', candidate.schedule_mode,
        'profile_id', candidate.schedule_profile_id,
        'profile_version', candidate.schedule_profile_version,
        'profile_hash', candidate.schedule_profile_hash
    )::text, 'UTF8')), 'hex');
    calculated_retention_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_COMMAND_RETENTION_BINDING_V1',
        'rule_policy_id', candidate.rule_retention_policy_id::text,
        'rule_policy_number', candidate.rule_retention_policy_number,
        'rule_policy_hash', candidate.rule_retention_policy_hash,
        'rule_retain_until', candidate.rule_retain_until,
        'rule_hold_generation', candidate.rule_hold_generation,
        'rule_hold_hash', candidate.rule_hold_hash,
        'audit_policy_id', resolved_audit.policy_id::text,
        'audit_policy_number', resolved_audit.policy_number,
        'audit_policy_hash', resolved_audit.policy_hash,
        'audit_retain_until', resolved_audit.retain_until,
        'audit_hold_generation', resolved_audit.hold_generation,
        'audit_hold_hash', resolved_audit.hold_hash
    )::text, 'UTF8')), 'hex');
    IF p_retention_binding_hash IS DISTINCT FROM calculated_retention_hash THEN
        RAISE EXCEPTION 'Quality revoke retention evidence drift'
            USING ERRCODE = '23514';
    END IF;
    UPDATE quality.rule_set_versions
    SET state = 'REVOKED',
        revoked_by = actor_id,
        revoked_at = transaction_timestamp(),
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id AND id = p_version_id;
    UPDATE quality.rule_schedules
    SET state = 'INACTIVE',
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id
      AND rule_set_version_id = p_version_id
      AND state = 'ACTIVE';
    SELECT COALESCE(max(sequence), 0) + 1 INTO next_sequence
    FROM quality.rule_command_events
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = candidate.rule_set_id;
    INSERT INTO quality.rule_command_events (
        id, workspace_id, rule_set_id, rule_set_version_id, sequence,
        command, actor_id, actor_kind, webauthn_evidence_hash,
        authentication_time, authorization_hash, target_binding_hash,
        schedule_binding_hash, retention_binding_hash, request_hash,
        idempotency_key_hash,
        audit_retention_kind, audit_retention_policy_id,
        audit_retention_policy_number, audit_retention_policy_hash,
        audit_retention_basis_at, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    VALUES (
        command_id, p_workspace_id, candidate.rule_set_id, p_version_id,
        next_sequence, 'REVOKE', actor_id, 'HUMAN',
        decision_evidence.assurance_hash, decision_evidence.authentication_time,
        decision_evidence.authorization_hash, candidate.target_binding_hash,
        calculated_schedule_hash, calculated_retention_hash,
        calculated_request_hash, p_idempotency_key_hash,
        'QUALITY_AUDIT', p_audit_policy_id, p_audit_policy_number,
        p_audit_policy_hash, transaction_timestamp(), p_audit_retain_until,
        p_audit_hold_generation, p_audit_hold_hash, transaction_timestamp()
    );
    RETURN command_id;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.revoke_rule_set_version_v1(
    uuid, uuid, uuid, text, text, text, text, integer,
    uuid, integer, text, timestamptz, bigint, text
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION quality.archive_rule_set_v1(
    p_workspace_id uuid,
    p_rule_set_id uuid,
    p_policy_decision_id uuid,
    p_authorization_hash text,
    p_retention_binding_hash text,
    p_idempotency_key_hash text,
    p_expected_version integer,
    p_audit_policy_id uuid,
    p_audit_policy_number integer,
    p_audit_policy_hash text,
    p_audit_retain_until timestamptz,
    p_audit_hold_generation bigint,
    p_audit_hold_hash text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quality, retention, iam
AS $$
DECLARE
    actor_id uuid := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    parent quality.rule_sets%ROWTYPE;
    asset record;
    resolved_audit record;
    decision_evidence record;
    existing_command quality.rule_command_events%ROWTYPE;
    calculated_target_hash text;
    calculated_schedule_hash text;
    calculated_retention_hash text;
    calculated_request_hash text;
    command_id uuid := gen_random_uuid();
    next_sequence bigint;
    is_security_admin boolean;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'invalid Quality archive command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO parent
    FROM quality.rule_sets
    WHERE workspace_id = p_workspace_id AND id = p_rule_set_id
    FOR UPDATE;
    IF parent.id IS NULL THEN
        RAISE EXCEPTION 'invalid Quality archive command'
            USING ERRCODE = '42501';
    END IF;
    calculated_request_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_ARCHIVE_REQUEST_V1',
        'workspace_id', p_workspace_id::text,
        'rule_set_id', p_rule_set_id::text,
        'actor_id', actor_id::text,
        'policy_decision_id', p_policy_decision_id::text,
        'authorization_hash', p_authorization_hash,
        'retention_binding_hash', p_retention_binding_hash,
        'expected_version', p_expected_version,
        'audit_policy_id', p_audit_policy_id::text,
        'audit_policy_number', p_audit_policy_number,
        'audit_policy_hash', p_audit_policy_hash,
        'audit_retain_until', p_audit_retain_until,
        'audit_hold_generation', p_audit_hold_generation,
        'audit_hold_hash', p_audit_hold_hash
    )::text, 'UTF8')), 'hex');
    SELECT * INTO existing_command
    FROM quality.rule_command_events
    WHERE workspace_id = p_workspace_id
      AND rule_set_id = p_rule_set_id
      AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing_command.command = 'ARCHIVE'
           AND existing_command.rule_set_version_id IS NULL
           AND existing_command.request_hash = calculated_request_hash THEN
            RETURN existing_command.id;
        END IF;
        RAISE EXCEPTION 'Quality archive idempotency conflict'
            USING ERRCODE = '23505';
    END IF;
    SELECT classification, system_id, domain_id INTO asset
    FROM catalog.assets_projection
    WHERE workspace_id = p_workspace_id AND id = parent.asset_id;
    IF asset.classification IS NULL THEN
        RAISE EXCEPTION 'invalid Quality archive target'
            USING ERRCODE = '42501';
    END IF;
    SELECT COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
           ? 'security-administrators'
    INTO is_security_admin
    FROM iam.workspace_memberships AS membership
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = actor_id;
    IF parent.state <> 'ACTIVE'
       OR parent.version <> p_expected_version
       OR (actor_id <> parent.created_by AND NOT COALESCE(is_security_admin, false))
       OR EXISTS (
           SELECT 1 FROM quality.rule_set_versions AS version
           WHERE version.workspace_id = p_workspace_id
             AND version.rule_set_id = p_rule_set_id
             AND version.state = 'ACTIVE'
       )
       OR NOT quality.current_human_can(
           p_workspace_id, 'quality.rule.archive',
           asset.classification, asset.system_id, asset.domain_id
       ) THEN
        RAISE EXCEPTION 'invalid Quality archive command'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO decision_evidence
    FROM quality.require_human_decision_v1(
        p_workspace_id, actor_id, p_rule_set_id, 'quality.rule.archive',
        p_policy_decision_id, false
    );
    IF p_authorization_hash IS DISTINCT FROM decision_evidence.authorization_hash THEN
        RAISE EXCEPTION 'Quality archive authorization evidence drift'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO resolved_audit
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id, 'QUALITY_AUDIT', 'QUALITY_RULE_SET',
        p_rule_set_id, transaction_timestamp()
    );
    IF ROW(
        p_audit_policy_id, p_audit_policy_number, p_audit_policy_hash,
        p_audit_retain_until, p_audit_hold_generation, p_audit_hold_hash
    ) IS DISTINCT FROM ROW(
        resolved_audit.policy_id, resolved_audit.policy_number,
        resolved_audit.policy_hash, resolved_audit.retain_until,
        resolved_audit.hold_generation, resolved_audit.hold_hash
    ) THEN
        RAISE EXCEPTION 'Quality archive audit binding drift'
            USING ERRCODE = '23514';
    END IF;
    calculated_target_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_ARCHIVE_TARGET_V1',
        'asset_id', parent.asset_id::text,
        'classification', asset.classification,
        'system_id', asset.system_id::text,
        'domain_id', asset.domain_id::text
    )::text, 'UTF8')), 'hex');
    calculated_schedule_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_ARCHIVE_SCHEDULE_V1',
        'state', 'INACTIVE'
    )::text, 'UTF8')), 'hex');
    calculated_retention_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'QUALITY_COMMAND_RETENTION_BINDING_V1',
        'rule_policy_id', parent.rule_retention_policy_id::text,
        'rule_policy_number', parent.rule_retention_policy_number,
        'rule_policy_hash', parent.rule_retention_policy_hash,
        'rule_retain_until', parent.rule_retain_until,
        'rule_hold_generation', parent.rule_hold_generation,
        'rule_hold_hash', parent.rule_hold_hash,
        'audit_policy_id', resolved_audit.policy_id::text,
        'audit_policy_number', resolved_audit.policy_number,
        'audit_policy_hash', resolved_audit.policy_hash,
        'audit_retain_until', resolved_audit.retain_until,
        'audit_hold_generation', resolved_audit.hold_generation,
        'audit_hold_hash', resolved_audit.hold_hash
    )::text, 'UTF8')), 'hex');
    IF p_retention_binding_hash IS DISTINCT FROM calculated_retention_hash THEN
        RAISE EXCEPTION 'Quality archive retention evidence drift'
            USING ERRCODE = '23514';
    END IF;
    UPDATE quality.rule_sets
    SET state = 'ARCHIVED',
        archived_at = transaction_timestamp(),
        updated_by = actor_id,
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id AND id = p_rule_set_id;
    SELECT COALESCE(max(sequence), 0) + 1 INTO next_sequence
    FROM quality.rule_command_events
    WHERE workspace_id = p_workspace_id AND rule_set_id = p_rule_set_id;
    INSERT INTO quality.rule_command_events (
        id, workspace_id, rule_set_id, rule_set_version_id, sequence,
        command, actor_id, actor_kind, webauthn_evidence_hash,
        authentication_time, authorization_hash, target_binding_hash,
        schedule_binding_hash, retention_binding_hash, request_hash,
        idempotency_key_hash,
        audit_retention_kind, audit_retention_policy_id,
        audit_retention_policy_number, audit_retention_policy_hash,
        audit_retention_basis_at, audit_retain_until,
        audit_hold_generation, audit_hold_hash, occurred_at
    )
    VALUES (
        command_id, p_workspace_id, p_rule_set_id, NULL, next_sequence,
        'ARCHIVE', actor_id, 'HUMAN', NULL, NULL,
        decision_evidence.authorization_hash, calculated_target_hash,
        calculated_schedule_hash, calculated_retention_hash,
        calculated_request_hash, p_idempotency_key_hash,
        'QUALITY_AUDIT', p_audit_policy_id, p_audit_policy_number,
        p_audit_policy_hash, transaction_timestamp(), p_audit_retain_until,
        p_audit_hold_generation, p_audit_hold_hash, transaction_timestamp()
    );
    RETURN command_id;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION quality.archive_rule_set_v1(
    uuid, uuid, uuid, text, text, text, integer,
    uuid, integer, text, timestamptz, bigint, text
) FROM PUBLIC;
"""

_QUALITY_ROLE_ASSERTION_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'datariver_quality'
          AND rolcanlogin IS TRUE
          AND rolsuper IS FALSE
          AND rolcreatedb IS FALSE
          AND rolcreaterole IS FALSE
          AND rolreplication IS FALSE
          AND rolbypassrls IS FALSE
    ) THEN
        RAISE EXCEPTION 'datariver_quality must be a safe NOBYPASSRLS login role';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members AS membership
        JOIN pg_roles AS member_role ON member_role.oid = membership.member
        JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
        WHERE member_role.rolname = 'datariver_quality'
           OR (
               granted_role.rolname = 'datariver_quality'
               AND member_role.rolname NOT IN (
                   current_user,
                   session_user,
                   'datariver_migrator'
               )
           )
    ) THEN
        RAISE EXCEPTION 'datariver_quality role membership is unsafe';
    END IF;
END
$$;
"""

_RLS_AND_GRANTS_SQL = f"""
DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'rule_sets',
        'rule_set_versions',
        'rule_definitions',
        'rule_reviews',
        'rule_command_events',
        'rule_schedules',
        'validation_runs',
        'validation_attempts',
        'expectation_results',
        'run_events',
        'dispatch_call_receipts',
        'dispatch_run_links',
        'execution_call_receipts'
    ]
    LOOP
        EXECUTE format('ALTER TABLE quality.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE quality.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY workspace_isolation ON quality.%I '
            'USING (workspace_id = NULLIF('
            'current_setting(''app.workspace_id'', true), '''')::uuid) '
            'WITH CHECK (workspace_id = NULLIF('
            'current_setting(''app.workspace_id'', true), '''')::uuid)',
            table_name
        );
    END LOOP;
END
$$;
-- datariver-statement-boundary

ALTER TABLE retention.legal_hold_generations ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE retention.legal_hold_generations FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
CREATE POLICY workspace_isolation ON retention.legal_hold_generations
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
);
-- datariver-statement-boundary

CREATE POLICY quality_rule_sets_read ON quality.rule_sets
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (quality.can_read_asset(workspace_id, asset_id, NULL, NULL, NULL));
-- datariver-statement-boundary
CREATE POLICY quality_rule_sets_insert ON quality.rule_sets
AS RESTRICTIVE FOR INSERT TO datariver_app
WITH CHECK (
    created_by = NULLIF(current_setting('app.subject_id', true), '')::uuid
    AND updated_by = created_by
    AND EXISTS (
        SELECT 1 FROM catalog.assets_projection AS asset
        WHERE asset.workspace_id = rule_sets.workspace_id
          AND asset.id = rule_sets.asset_id
          AND asset.deleted_at IS NULL
          AND asset.lifecycle = 'ACTIVE'
          AND quality.current_human_can(
              asset.workspace_id, 'quality.rule.propose',
              asset.classification, asset.system_id, asset.domain_id
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_rule_versions_read ON quality.rule_set_versions
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    quality.can_read_asset(
        workspace_id, asset_id, classification, system_id, domain_id
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_rule_versions_insert ON quality.rule_set_versions
AS RESTRICTIVE FOR INSERT TO datariver_app
WITH CHECK (
    author_id = NULLIF(current_setting('app.subject_id', true), '')::uuid
    AND state = 'PROPOSED'
    AND EXISTS (
        SELECT 1 FROM catalog.assets_projection AS asset
        WHERE asset.workspace_id = rule_set_versions.workspace_id
          AND asset.id = rule_set_versions.asset_id
          AND asset.id = (
              SELECT rule_set.asset_id
              FROM quality.rule_sets AS rule_set
              WHERE rule_set.workspace_id = rule_set_versions.workspace_id
                AND rule_set.id = rule_set_versions.rule_set_id
                AND rule_set.state = 'ACTIVE'
          )
          AND asset.deleted_at IS NULL
          AND asset.lifecycle = rule_set_versions.lifecycle
          AND asset.source_version = rule_set_versions.source_version
          AND asset.classification = rule_set_versions.classification
          AND asset.system_id IS NOT DISTINCT FROM rule_set_versions.system_id
          AND asset.domain_id IS NOT DISTINCT FROM rule_set_versions.domain_id
          AND quality.current_human_can(
              asset.workspace_id, 'quality.rule.propose',
              asset.classification, asset.system_id, asset.domain_id
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_runs_read ON quality.validation_runs
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1
        FROM quality.rule_set_versions AS version
        WHERE version.workspace_id = validation_runs.workspace_id
          AND version.id = validation_runs.rule_set_version_id
          AND quality.can_read_asset(
              version.workspace_id,
              version.asset_id,
              version.classification,
              version.system_id,
              version.domain_id
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_rule_definitions_read ON quality.rule_definitions
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.rule_set_versions AS version
        WHERE version.workspace_id = rule_definitions.workspace_id
          AND version.id = rule_definitions.rule_set_version_id
          AND quality.can_read_asset(
              version.workspace_id, version.asset_id, version.classification,
              version.system_id, version.domain_id
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_rule_definitions_insert ON quality.rule_definitions
AS RESTRICTIVE FOR INSERT TO datariver_app
WITH CHECK (
    EXISTS (
        SELECT 1 FROM quality.rule_set_versions AS version
        WHERE version.workspace_id = rule_definitions.workspace_id
          AND version.id = rule_definitions.rule_set_version_id
          AND version.state = 'PROPOSED'
          AND version.author_id =
              NULLIF(current_setting('app.subject_id', true), '')::uuid
          AND quality.current_human_can(
              version.workspace_id, 'quality.rule.propose',
              version.classification, version.system_id, version.domain_id
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_rule_reviews_read ON quality.rule_reviews
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.rule_set_versions AS version
        WHERE version.workspace_id = rule_reviews.workspace_id
          AND version.id = rule_reviews.rule_set_version_id
          AND quality.can_read_asset(
              version.workspace_id, version.asset_id, version.classification,
              version.system_id, version.domain_id
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_rule_commands_read ON quality.rule_command_events
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.rule_sets AS rule_set
        WHERE rule_set.workspace_id = rule_command_events.workspace_id
          AND rule_set.id = rule_command_events.rule_set_id
          AND quality.can_read_asset(
              rule_set.workspace_id, rule_set.asset_id, NULL, NULL, NULL
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_rule_schedules_read ON quality.rule_schedules
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.rule_set_versions AS version
        WHERE version.workspace_id = rule_schedules.workspace_id
          AND version.id = rule_schedules.rule_set_version_id
          AND quality.can_read_asset(
              version.workspace_id, version.asset_id, version.classification,
              version.system_id, version.domain_id
          )
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_attempts_read ON quality.validation_attempts
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.validation_runs AS run
        WHERE run.workspace_id = validation_attempts.workspace_id
          AND run.id = validation_attempts.run_id
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_results_read ON quality.expectation_results
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.validation_runs AS run
        WHERE run.workspace_id = expectation_results.workspace_id
          AND run.id = expectation_results.run_id
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_run_events_read ON quality.run_events
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.validation_runs AS run
        WHERE run.workspace_id = run_events.workspace_id
          AND run.id = run_events.run_id
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_dispatch_receipts_read ON quality.dispatch_call_receipts
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    quality.current_human_can(
        workspace_id, 'quality.operations.read', 0, NULL, NULL
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_dispatch_links_read ON quality.dispatch_run_links
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    EXISTS (
        SELECT 1 FROM quality.validation_runs AS run
        WHERE run.workspace_id = dispatch_run_links.workspace_id
          AND run.id = dispatch_run_links.run_id
    )
);
-- datariver-statement-boundary
CREATE POLICY quality_execution_receipts_read ON quality.execution_call_receipts
AS RESTRICTIVE FOR SELECT TO datariver_app
USING (
    quality.current_human_can(
        workspace_id, 'quality.operations.read', 0, NULL, NULL
    )
    AND EXISTS (
        SELECT 1 FROM quality.validation_runs AS run
        WHERE run.workspace_id = execution_call_receipts.workspace_id
          AND run.id = execution_call_receipts.run_id
    )
);
-- datariver-statement-boundary

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT USAGE ON SCHEMA quality TO datariver_app;
        GRANT SELECT ON {_APP_READ_TABLES} TO datariver_app;
        GRANT INSERT ON {_APP_INSERT_TABLES} TO datariver_app;
        GRANT SELECT ON retention.legal_hold_generations TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.current_human_can(
            uuid, text, integer, uuid, uuid
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.can_read_asset(
            uuid, uuid, integer, uuid, uuid
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION retention.resolve_quality_binding_v1(
            uuid, text, text, uuid, timestamptz
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.review_rule_set_version_v1(
            uuid, uuid, text, text, uuid, text, integer,
            uuid, integer, text, timestamptz, bigint, text
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.activate_rule_set_version_v1(
            uuid, uuid, uuid, text, text, text, text, text, integer,
            uuid, integer, text, timestamptz, bigint, text
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.revoke_rule_set_version_v1(
            uuid, uuid, uuid, text, text, text, text, integer,
            uuid, integer, text, timestamptz, bigint, text
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION quality.archive_rule_set_v1(
            uuid, uuid, uuid, text, text, text, integer,
            uuid, integer, text, timestamptz, bigint, text
        ) TO datariver_app;
    END IF;
END
$$;
"""


def _quality_tables() -> Iterable[object]:
    for table_name in _QUALITY_TABLE_NAMES:
        yield Base.metadata.tables[f"quality.{table_name}"]


def _quality_deferred_foreign_keys() -> tuple[object, ...]:
    return tuple(
        constraint
        for table in _quality_tables()
        for constraint in table.foreign_key_constraints  # type: ignore[attr-defined]
        if constraint.use_alter
    )


def _create_phase1_quality_tables(bind: object) -> None:
    """Create the frozen 0067 table/index set from mutable head metadata."""
    for table in _quality_tables():
        post_phase_indexes = {
            index
            for index in table.indexes  # type: ignore[attr-defined]
            if index.name in _POST_0067_INDEX_NAMES
        }
        table.indexes.difference_update(post_phase_indexes)  # type: ignore[attr-defined]
        try:
            table.create(bind=bind, checkfirst=False)  # type: ignore[attr-defined]
        finally:
            table.indexes.update(post_phase_indexes)  # type: ignore[attr-defined]


def _execute_script(sql: str) -> None:
    for statement in sql.split(_STATEMENT_BOUNDARY):
        cleaned = statement.strip()
        if cleaned:
            op.execute(cleaned)


def _schema_contract_hash() -> str:
    """Pin the mutable ORM metadata used by this additive historical revision."""
    table_names = (
        "retention.legal_hold_generations",
        *(table.fullname for table in _quality_tables()),
    )
    rendered: list[str] = []
    dialect = postgresql.dialect()
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        create_table_sql = str(CreateTable(table).compile(dialect=dialect)).strip()
        if table_name == "retention.legal_hold_generations":
            # Freeze the 0067 exact set even after the additive 0068 ORM model adds
            # QUALITY_PROFILE.  Historical migration verification must not depend on
            # the mutable head metadata.
            create_table_sql = create_table_sql.replace(", 'QUALITY_PROFILE'", "")
        rendered.append(create_table_sql)
        rendered.extend(
            str(CreateIndex(index).compile(dialect=dialect)).strip()
            for index in sorted(table.indexes, key=lambda value: value.name or "")
            if index.name not in _POST_0067_INDEX_NAMES
        )
    rendered.extend(
        str(AddConstraint(constraint).compile(dialect=dialect)).strip()
        for constraint in sorted(
            _quality_deferred_foreign_keys(),
            key=lambda value: value.name or "",  # type: ignore[attr-defined]
        )
    )
    return sha256("\n-- contract-item --\n".join(rendered).encode()).hexdigest()


def _catalog_contract_document(bind: object) -> list[list[str]]:
    """Read exact PostgreSQL definitions, security, triggers and grants."""
    rows = bind.execute(  # type: ignore[attr-defined]
        text(
            """
            WITH managed_tables(schema_name, table_name) AS (
                SELECT 'quality'::text, unnest(CAST(:quality_tables AS text[]))
                UNION ALL
                VALUES ('retention', 'legal_hold_generations'),
                       ('retention', 'legal_holds'),
                       ('retention', 'policy_versions'),
                       ('retention', 'policy_class_rules')
            ),
            contract_items AS (
                SELECT
                    'column'::text AS category,
                    namespace.nspname || '.' || relation.relname || '.' ||
                        attribute.attname AS identity,
                    jsonb_build_object(
                        'name', attribute.attname,
                        'type', format_type(attribute.atttypid, attribute.atttypmod),
                        'not_null', attribute.attnotnull,
                        'default', pg_get_expr(default_value.adbin, default_value.adrelid),
                        'identity', attribute.attidentity,
                        'generated', attribute.attgenerated
                    )::text AS definition
                FROM managed_tables AS managed
                JOIN pg_namespace AS namespace ON namespace.nspname = managed.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed.table_name
                JOIN pg_attribute AS attribute
                  ON attribute.attrelid = relation.oid
                 AND attribute.attnum > 0
                 AND NOT attribute.attisdropped
                LEFT JOIN pg_attrdef AS default_value
                  ON default_value.adrelid = relation.oid
                 AND default_value.adnum = attribute.attnum

                UNION ALL
                SELECT
                    'constraint',
                    namespace.nspname || '.' || relation.relname || '.' || constraint_value.conname,
                    pg_get_constraintdef(constraint_value.oid, true)
                FROM managed_tables AS managed
                JOIN pg_namespace AS namespace ON namespace.nspname = managed.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed.table_name
                JOIN pg_constraint AS constraint_value
                  ON constraint_value.conrelid = relation.oid

                UNION ALL
                SELECT
                    'index',
                    namespace.nspname || '.' || relation.relname || '.' || index_relation.relname,
                    pg_get_indexdef(index_value.indexrelid)
                FROM managed_tables AS managed
                JOIN pg_namespace AS namespace ON namespace.nspname = managed.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed.table_name
                JOIN pg_index AS index_value ON index_value.indrelid = relation.oid
                JOIN pg_class AS index_relation ON index_relation.oid = index_value.indexrelid
                WHERE index_relation.relname NOT IN (
                    'ix_quality_expectation_results_issues',
                    'ix_quality_rule_sets_list',
                    'ix_quality_validation_runs_list'
                )

                UNION ALL
                SELECT
                    'rls',
                    namespace.nspname || '.' || relation.relname,
                    jsonb_build_object(
                        'enabled', relation.relrowsecurity,
                        'forced', relation.relforcerowsecurity,
                        'owner', pg_get_userbyid(relation.relowner)
                    )::text
                FROM managed_tables AS managed
                JOIN pg_namespace AS namespace ON namespace.nspname = managed.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed.table_name

                UNION ALL
                SELECT
                    'policy',
                    policy.schemaname || '.' || policy.tablename || '.' || policy.policyname,
                    jsonb_build_object(
                        'permissive', policy.permissive,
                        'roles', policy.roles,
                        'command', policy.cmd,
                        'using', policy.qual,
                        'check', policy.with_check
                    )::text
                FROM pg_policies AS policy
                JOIN managed_tables AS managed
                  ON managed.schema_name = policy.schemaname
                 AND managed.table_name = policy.tablename

                UNION ALL
                SELECT
                    'trigger',
                    namespace.nspname || '.' || relation.relname || '.' || trigger_value.tgname,
                    jsonb_build_object(
                        'enabled', trigger_value.tgenabled,
                        'definition', pg_get_triggerdef(trigger_value.oid, true)
                    )::text
                FROM managed_tables AS managed
                JOIN pg_namespace AS namespace ON namespace.nspname = managed.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed.table_name
                JOIN pg_trigger AS trigger_value
                  ON trigger_value.tgrelid = relation.oid
                 AND NOT trigger_value.tgisinternal

                UNION ALL
                SELECT
                    'function',
                    procedure_value.oid::regprocedure::text,
                    jsonb_build_object(
                        'owner', pg_get_userbyid(procedure_value.proowner),
                        'security_definer', procedure_value.prosecdef,
                        'volatility', procedure_value.provolatile,
                        'config', procedure_value.proconfig,
                        'definition', pg_get_functiondef(procedure_value.oid)
                    )::text
                FROM pg_proc AS procedure_value
                JOIN pg_namespace AS namespace ON namespace.oid = procedure_value.pronamespace
                WHERE (
                    namespace.nspname = 'quality'
                    OR (
                        namespace.nspname = 'retention'
                        AND procedure_value.proname IN (
                            'advance_legal_hold_generation',
                            'refresh_legal_hold_generation',
                            'resolve_quality_binding_v1'
                        )
                    )
                )

                UNION ALL
                SELECT
                    'table_grant',
                    grant_value.table_schema || '.' || grant_value.table_name || '.' ||
                        grant_value.grantee || '.' || grant_value.privilege_type,
                    grant_value.is_grantable
                FROM information_schema.table_privileges AS grant_value
                JOIN managed_tables AS managed
                  ON managed.schema_name = grant_value.table_schema
                 AND managed.table_name = grant_value.table_name

                UNION ALL
                SELECT
                    'column_grant',
                    grant_value.table_schema || '.' || grant_value.table_name || '.' ||
                        grant_value.column_name || '.' || grant_value.grantee || '.' ||
                        grant_value.privilege_type,
                    grant_value.is_grantable
                FROM information_schema.column_privileges AS grant_value
                JOIN managed_tables AS managed
                  ON managed.schema_name = grant_value.table_schema
                 AND managed.table_name = grant_value.table_name

                UNION ALL
                SELECT
                    'schema',
                    namespace.nspname,
                    pg_get_userbyid(namespace.nspowner)
                FROM pg_namespace AS namespace
                WHERE namespace.nspname IN ('quality', 'retention')

                UNION ALL
                SELECT
                    'schema_grant',
                    namespace.nspname || '.' ||
                        COALESCE(grantee.rolname, 'PUBLIC') || '.' ||
                        privilege.privilege_type,
                    privilege.is_grantable::text
                FROM pg_namespace AS namespace
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
                ) AS privilege
                LEFT JOIN pg_roles AS grantee ON grantee.oid = privilege.grantee
                WHERE namespace.nspname IN ('quality', 'retention')

                UNION ALL
                SELECT
                    'function_grant',
                    procedure_value.oid::regprocedure::text || '.' ||
                        COALESCE(grantee.rolname, 'PUBLIC') || '.' ||
                        privilege.privilege_type,
                    privilege.is_grantable::text
                FROM pg_proc AS procedure_value
                JOIN pg_namespace AS namespace ON namespace.oid = procedure_value.pronamespace
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(
                        procedure_value.proacl,
                        acldefault('f', procedure_value.proowner)
                    )
                ) AS privilege
                LEFT JOIN pg_roles AS grantee ON grantee.oid = privilege.grantee
                WHERE (
                    namespace.nspname = 'quality'
                    OR (
                        namespace.nspname = 'retention'
                        AND procedure_value.proname IN (
                            'advance_legal_hold_generation',
                            'refresh_legal_hold_generation',
                            'resolve_quality_binding_v1'
                        )
                    )
                )
                UNION ALL
                SELECT
                    'role',
                    role_value.rolname,
                    jsonb_build_object(
                        'login', role_value.rolcanlogin,
                        'super', role_value.rolsuper,
                        'createdb', role_value.rolcreatedb,
                        'createrole', role_value.rolcreaterole,
                        'replication', role_value.rolreplication,
                        'bypassrls', role_value.rolbypassrls
                    )::text
                FROM pg_roles AS role_value
                WHERE role_value.rolname = 'datariver_quality'

                UNION ALL
                SELECT
                    'role_membership',
                    member_role.rolname || '->' || granted_role.rolname,
                    membership.admin_option::text
                FROM pg_auth_members AS membership
                JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
                JOIN pg_roles AS member_role ON member_role.oid = membership.member
                WHERE granted_role.rolname = 'datariver_quality'
                   OR member_role.rolname = 'datariver_quality'
            )
            SELECT category, identity, definition
            FROM contract_items
            ORDER BY category, identity, definition
            """
        ),
        {"quality_tables": list(_QUALITY_TABLE_NAMES)},
    ).all()
    return [[str(value) for value in row] for row in rows]


def _catalog_contract_hash(bind: object) -> str:
    document = _catalog_contract_document(bind)
    return sha256(
        json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _canonical_contract_is_complete(bind: object) -> bool:
    inspector = inspect(bind)  # type: ignore[arg-type]
    schemas = set(inspector.get_schema_names())
    quality_tables = (
        set(inspector.get_table_names(schema="quality")) if "quality" in schemas else set()
    )
    expected = set(_QUALITY_TABLE_NAMES)
    generation_present = inspector.has_table("legal_hold_generations", schema="retention")
    legal_hold_columns = {
        column["name"] for column in inspector.get_columns("legal_holds", schema="retention")
    }
    resource_type_present = "resource_type" in legal_hold_columns
    indicators = bool(quality_tables) or generation_present or resource_type_present
    if not indicators:
        return False
    if quality_tables != expected or not generation_present or not resource_type_present:
        raise RuntimeError("Partial canonical Quality schema detected; refusing 0067 re-entry.")
    actual_hash = _catalog_contract_hash(bind)
    supported_hashes = {
        _QUALITY_CATALOG_CONTRACT_HASH,
        _QUALITY_CANONICAL_HEAD_CONTRACT_HASH,
    }
    if actual_hash not in supported_hashes:
        raise RuntimeError(
            "Canonical Quality definition/security fingerprint is incomplete or drifted "
            f"(expected one of {sorted(supported_hashes)}, got {actual_hash})."
        )
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if _canonical_contract_is_complete(bind):
        return
    if _schema_contract_hash() != _QUALITY_SCHEMA_CONTRACT_HASH:
        raise RuntimeError(
            "Quality 0067 ORM schema contract drifted; refusing historical migration."
        )
    op.execute("CREATE SCHEMA quality")
    op.execute(_QUALITY_ROLE_ASSERTION_SQL)
    _execute_script(_RETENTION_ALLOWLIST_SQL)
    Base.metadata.tables["retention.legal_hold_generations"].create(bind=bind, checkfirst=False)
    _create_phase1_quality_tables(bind)
    for constraint in _quality_deferred_foreign_keys():
        bind.execute(AddConstraint(constraint))  # type: ignore[arg-type]
    _execute_script(_HOLD_GENERATION_SQL)
    _execute_script(_RESOLVER_SQL)
    _execute_script(_QUALITY_SECURITY_SQL)
    _execute_script(_IMMUTABILITY_SQL)
    _execute_script(_RUN_ATTEMPT_INVARIANT_SQL)
    _execute_script(_RUN_RESULT_INVARIANT_SQL)
    _execute_script(_TRANSITION_SQL)
    for table_name in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER reject_evidence_mutation "
            f"BEFORE UPDATE OR DELETE ON quality.{table_name} "
            "FOR EACH ROW EXECUTE FUNCTION quality.reject_evidence_mutation()"
        )
    _execute_script(_RLS_AND_GRANTS_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        """
        DO $$
        DECLARE
            table_name text;
            has_rows boolean;
        BEGIN
            FOREACH table_name IN ARRAY ARRAY[
                'rule_sets','rule_set_versions','rule_definitions','rule_reviews',
                'rule_command_events','rule_schedules','validation_runs',
                'validation_attempts','expectation_results','run_events',
                'dispatch_call_receipts','dispatch_run_links','execution_call_receipts'
            ]
            LOOP
                EXECUTE format('SELECT EXISTS (SELECT 1 FROM quality.%I)', table_name)
                    INTO has_rows;
                IF has_rows THEN
                    RAISE EXCEPTION
                        '0067 downgrade refuses non-empty immutable Quality evidence';
                END IF;
            END LOOP;
            IF EXISTS (
                SELECT 1 FROM retention.legal_holds
                WHERE data_class IN ('QUALITY_RULE','QUALITY_RESULT','QUALITY_AUDIT')
                   OR (
                       resource_type IS NOT NULL
                       AND resource_type <> 'LEGACY_UNTYPED'
                   )
            ) OR EXISTS (
                SELECT 1 FROM retention.policy_class_rules
                WHERE data_class IN ('QUALITY_RULE','QUALITY_RESULT','QUALITY_AUDIT')
            ) THEN
                RAISE EXCEPTION
                    '0067 downgrade refuses governed Quality retention evidence';
            END IF;
        END
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS refresh_legal_hold_generation ON retention.legal_holds")
    op.execute("DROP TRIGGER IF EXISTS enforce_rule_set_binding ON quality.rule_sets")
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "retention.resolve_quality_binding_v1(uuid, text, text, uuid, timestamptz)"
    )
    op.execute("DROP FUNCTION IF EXISTS retention.refresh_legal_hold_generation()")
    op.execute(
        "DROP FUNCTION IF EXISTS retention.advance_legal_hold_generation("
        "uuid, text, text, uuid, integer, text, text, text, uuid, text)"
    )
    for table_name in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS reject_evidence_mutation ON quality.{table_name}")
    run_foreign_keys = {
        foreign_key["name"]
        for foreign_key in inspect(bind).get_foreign_keys("validation_runs", schema="quality")
    }
    if "fk_quality_runs_current_attempt" in run_foreign_keys:
        op.drop_constraint(
            "fk_quality_runs_current_attempt",
            "validation_runs",
            schema="quality",
            type_="foreignkey",
        )
    # RLS policies depend on the Quality authorization functions.  Drop the
    # tables (and therefore their policies) before removing those functions.
    for table in reversed(tuple(_quality_tables())):
        table.drop(bind=bind, checkfirst=False)  # type: ignore[attr-defined]
    Base.metadata.tables["retention.legal_hold_generations"].drop(bind=bind, checkfirst=False)
    op.execute("DROP FUNCTION IF EXISTS quality.reject_evidence_mutation()")
    op.execute("DROP FUNCTION IF EXISTS quality.assert_run_results_shape_v1()")
    op.execute("DROP FUNCTION IF EXISTS quality.assert_run_attempt_shape_v1()")
    op.execute("DROP FUNCTION IF EXISTS quality.enforce_rule_set_binding_v1()")
    op.execute(
        "DROP FUNCTION IF EXISTS quality.archive_rule_set_v1("
        "uuid, uuid, uuid, text, text, text, integer, "
        "uuid, integer, text, timestamptz, bigint, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.revoke_rule_set_version_v1("
        "uuid, uuid, uuid, text, text, text, text, integer, "
        "uuid, integer, text, timestamptz, bigint, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.activate_rule_set_version_v1("
        "uuid, uuid, uuid, text, text, text, text, text, integer, "
        "uuid, integer, text, timestamptz, bigint, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.review_rule_set_version_v1("
        "uuid, uuid, text, text, uuid, text, integer, "
        "uuid, integer, text, timestamptz, bigint, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "quality.require_human_decision_v1(uuid, uuid, uuid, text, uuid, boolean)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS quality.current_target_matches_v1("
        "uuid, uuid, integer, uuid, uuid, text, text, text)"
    )
    op.execute("DROP FUNCTION IF EXISTS quality.can_read_asset(uuid, uuid, integer, uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS quality.current_human_can(uuid, text, integer, uuid, uuid)")
    op.execute("DROP SCHEMA quality")
    _execute_script(
        """
        DROP INDEX retention.ix_legal_holds_workspace_blocking_scope;
        -- datariver-statement-boundary
        ALTER TABLE retention.legal_holds
            DROP CONSTRAINT ck_legal_holds_scope_shape;
        -- datariver-statement-boundary
        ALTER TABLE retention.legal_holds DROP COLUMN resource_type;
        -- datariver-statement-boundary
        ALTER TABLE retention.legal_holds
            ADD CONSTRAINT ck_legal_holds_scope_shape CHECK (
                (scope = 'WORKSPACE' AND scope_id IS NULL)
                OR (scope IN ('SUBJECT', 'RESOURCE') AND scope_id IS NOT NULL)
            );
        -- datariver-statement-boundary
        CREATE INDEX ix_legal_holds_workspace_blocking_scope
            ON retention.legal_holds (workspace_id, data_class, scope, scope_id)
            WHERE state <> 'RELEASED';
        -- datariver-statement-boundary
        ALTER TABLE retention.legal_holds
            DROP CONSTRAINT ck_legal_holds_data_class,
            ADD CONSTRAINT ck_legal_holds_data_class CHECK (
                data_class IN (
                    'COMPLETED_OPERATIONS', 'CHAT_CONTENT',
                    'AUDIT_EVIDENCE', 'OBJECT_DATA'
                )
            );
        -- datariver-statement-boundary
        ALTER TABLE retention.policy_class_rules
            DROP CONSTRAINT ck_policy_class_rules_data_class,
            ADD CONSTRAINT ck_policy_class_rules_data_class CHECK (
                data_class IN (
                    'COMPLETED_OPERATIONS', 'CHAT_CONTENT',
                    'AUDIT_EVIDENCE', 'OBJECT_DATA'
                )
            );
        -- datariver-statement-boundary
        ALTER TABLE retention.policy_versions
            DROP CONSTRAINT ck_policy_versions_contract_shape,
            ADD CONSTRAINT ck_policy_versions_contract_shape CHECK (
                (
                    contract_version = 'SINGLE_DEADLINE_V1'
                    AND effective_from IS NULL
                    AND effective_until IS NULL
                    AND execution_authorization_hours IS NULL
                )
                OR (
                    contract_version = 'POLICY_BOOK_V2'
                    AND effective_from IS NOT NULL
                    AND (effective_until IS NULL OR effective_until > effective_from)
                    AND execution_authorization_hours BETWEEN 1 AND 168
                )
            );
        """
    )
