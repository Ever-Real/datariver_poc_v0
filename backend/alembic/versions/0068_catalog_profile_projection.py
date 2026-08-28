"""Add the governed DataHub Profile projection boundary.

Revision ID: 0068
Revises: 0067
Create Date: 2026-07-30
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from hashlib import sha256

from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from datariver.infrastructure.db import models as _models  # noqa: F401
from datariver.infrastructure.db.base import Base

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_TABLE_NAMES = ("asset_profile_snapshots", "column_profile_metrics")
_STATEMENT_BOUNDARY = "-- datariver-statement-boundary"
_PROFILE_SCHEMA_CONTRACT_HASH = "810d80b2f26addf93529f3747a8b06c6d6e03b56564fd928055a6b7d370a6473"
_PROFILE_CATALOG_CONTRACT_HASH = "9631a4f5cc7aafab5e7832ec946b2a78233f6154997db18b2595ad62a3dc002d"

_RETENTION_V4_SQL = """
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
            contract_version IN ('POLICY_BOOK_V2', 'POLICY_BOOK_V3', 'POLICY_BOOK_V4')
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
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT', 'QUALITY_PROFILE'
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    DROP CONSTRAINT IF EXISTS ck_legal_holds_data_class;
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    ADD CONSTRAINT ck_legal_holds_data_class CHECK (
        data_class IN (
            'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT', 'QUALITY_PROFILE'
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    DROP CONSTRAINT IF EXISTS ck_legal_holds_scope_shape;
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
                'QUALITY_RULE_SET', 'QUALITY_VALIDATION_RUN', 'PROFILE_SNAPSHOT'
            )
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    DROP CONSTRAINT IF EXISTS ck_legal_holds_resource_semantics;
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
        OR (
            resource_type = 'PROFILE_SNAPSHOT'
            AND data_class = 'QUALITY_PROFILE'
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_hold_generations
    DROP CONSTRAINT IF EXISTS ck_legal_hold_generations_data_class;
-- datariver-statement-boundary
ALTER TABLE retention.legal_hold_generations
    DROP CONSTRAINT IF EXISTS ck_legal_hold_generations_ck_legal_hold_generations_data_class;
-- datariver-statement-boundary
ALTER TABLE retention.legal_hold_generations
    ADD CONSTRAINT ck_legal_hold_generations_data_class CHECK (
        data_class IN (
            'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT', 'QUALITY_PROFILE'
        )
    );
-- datariver-statement-boundary
INSERT INTO retention.legal_hold_generations (
    id, workspace_id, data_class, generation, resolution_hash,
    version, created_at, updated_at
)
SELECT
    gen_random_uuid(), workspace.id, 'QUALITY_PROFILE', 1,
    encode(sha256(convert_to('', 'UTF8')), 'hex'),
    1, transaction_timestamp(), transaction_timestamp()
FROM platform.workspaces AS workspace
ON CONFLICT (workspace_id, data_class) DO NOTHING;
"""

_RESOLVER_V4_SQL = """
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
    expected_class_count integer;
BEGIN
    IF p_resource_id IS NULL
       OR p_basis_at IS DISTINCT FROM transaction_timestamp()
       OR NOT (
           (
               p_data_class IN ('QUALITY_RULE', 'QUALITY_AUDIT')
               AND p_resource_type = 'QUALITY_RULE_SET'
           )
           OR (
               p_data_class IN ('QUALITY_RESULT', 'QUALITY_AUDIT')
               AND p_resource_type = 'QUALITY_VALIDATION_RUN'
           )
           OR (
               p_data_class = 'QUALITY_PROFILE'
               AND p_resource_type = 'PROFILE_SNAPSHOT'
           )
       ) THEN
        RAISE EXCEPTION 'invalid Quality retention binding request'
            USING ERRCODE = '23514';
    END IF;

    SELECT policy.* INTO selected_policy
    FROM retention.policy_versions AS policy
    WHERE policy.workspace_id = p_workspace_id
      AND policy.state = 'ACTIVE'
      AND (
          (
              p_data_class = 'QUALITY_PROFILE'
              AND policy.contract_version = 'POLICY_BOOK_V4'
          )
          OR (
              p_data_class <> 'QUALITY_PROFILE'
              AND policy.contract_version IN ('POLICY_BOOK_V3', 'POLICY_BOOK_V4')
          )
      )
      AND policy.effective_from <= p_basis_at
      AND (policy.effective_until IS NULL OR policy.effective_until > p_basis_at)
    FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quality retention requires an effective policy book'
            USING ERRCODE = '23514';
    END IF;

    expected_class_count := CASE selected_policy.contract_version
        WHEN 'POLICY_BOOK_V3' THEN 7
        WHEN 'POLICY_BOOK_V4' THEN 8
        ELSE 0
    END;
    IF (
        SELECT count(*) <> expected_class_count
            OR bool_or(class_rule.data_class NOT IN (
                'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
                'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT', 'QUALITY_PROFILE'
            ))
            OR (
                selected_policy.contract_version = 'POLICY_BOOK_V3'
                AND bool_or(class_rule.data_class = 'QUALITY_PROFILE')
            )
            OR (
                selected_policy.contract_version = 'POLICY_BOOK_V4'
                AND count(*) FILTER (
                    WHERE class_rule.data_class = 'QUALITY_PROFILE'
                ) <> 1
            )
        FROM retention.policy_class_rules AS class_rule
        WHERE class_rule.workspace_id = p_workspace_id
          AND class_rule.policy_id = selected_policy.id
          AND class_rule.policy_hash = selected_policy.payload_hash
          AND class_rule.policy_number = selected_policy.policy_number
    ) THEN
        RAISE EXCEPTION 'Quality retention policy class set is incomplete'
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

_PROFILE_ROLE_ASSERTION_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'datariver_catalog_profile'
          AND rolcanlogin IS TRUE
          AND rolsuper IS FALSE
          AND rolcreatedb IS FALSE
          AND rolcreaterole IS FALSE
          AND rolreplication IS FALSE
          AND rolbypassrls IS FALSE
    ) THEN
        RAISE EXCEPTION
            'datariver_catalog_profile must be a safe NOBYPASSRLS login role';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members AS membership
        JOIN pg_roles AS member_role ON member_role.oid = membership.member
        JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
        WHERE member_role.rolname = 'datariver_catalog_profile'
           OR (
               granted_role.rolname = 'datariver_catalog_profile'
               AND member_role.rolname NOT IN (
                   current_user, session_user, 'datariver_migrator'
               )
           )
    ) THEN
        RAISE EXCEPTION 'datariver_catalog_profile role membership is unsafe';
    END IF;
END
$$;
"""

_PROFILE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION catalog.current_profile_collector_can_v1(
    p_workspace_id uuid,
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
    SELECT session_user = 'datariver_catalog_profile'
       AND p_workspace_id IS NOT DISTINCT FROM
           NULLIF(current_setting('app.workspace_id', true), '')::uuid
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
             AND jsonb_typeof(
                 COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
             ) = 'array'
             AND jsonb_array_length(
                 COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
             ) = 2
             AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                 @> '["service-accounts","catalog-profile-collectors"]'::jsonb
             AND COALESCE(
                 membership.attributes -> 'allowed_actions', '[]'::jsonb
             ) = '["catalog.profile.collect"]'::jsonb
             AND NOT (
                 COALESCE(
                     membership.attributes -> 'denied_actions', '[]'::jsonb
                 ) ? 'catalog.profile.collect'
             )
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
REVOKE ALL ON FUNCTION catalog.current_profile_collector_can_v1(
    uuid, integer, uuid, uuid
) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION catalog.read_profile_target_v1(
    p_workspace_id uuid,
    p_asset_id uuid
)
RETURNS TABLE (
    external_urn text,
    source_version varchar,
    classification integer,
    system_id uuid,
    domain_id uuid
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, catalog
AS $$
DECLARE
    selected_asset catalog.assets_projection%ROWTYPE;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Profile target security context mismatch'
            USING ERRCODE = '42501';
    END IF;
    SELECT asset.* INTO selected_asset
    FROM catalog.assets_projection AS asset
    WHERE asset.workspace_id = p_workspace_id
      AND asset.id = p_asset_id
      AND asset.deleted_at IS NULL
      AND asset.lifecycle = 'ACTIVE';
    IF NOT FOUND OR NOT catalog.current_profile_collector_can_v1(
        selected_asset.workspace_id,
        selected_asset.classification,
        selected_asset.system_id,
        selected_asset.domain_id
    ) THEN
        RAISE EXCEPTION 'Profile target is unavailable'
            USING ERRCODE = '42501';
    END IF;
    external_urn := selected_asset.external_urn;
    source_version := selected_asset.source_version;
    classification := selected_asset.classification;
    system_id := selected_asset.system_id;
    domain_id := selected_asset.domain_id;
    RETURN NEXT;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION catalog.read_profile_target_v1(uuid, uuid) FROM PUBLIC;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION catalog.project_asset_profile_v1(
    p_workspace_id uuid,
    p_asset_id uuid,
    p_payload jsonb
)
RETURNS TABLE (
    snapshot_id uuid,
    snapshot_identity_hash text,
    created boolean,
    last_observed_at timestamptz
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, catalog, retention
AS $$
DECLARE
    selected_asset catalog.assets_projection%ROWTYPE;
    resolved record;
    current_field jsonb;
    target_scope_hash text;
    calculated_identity_hash text;
    inserted_snapshot_id uuid;
    existing_snapshot catalog.asset_profile_snapshots%ROWTYPE;
    basis_at timestamptz := transaction_timestamp();
    observed_at timestamptz;
    profiled_at timestamptz;
    stale_at timestamptz;
    profile_kind text;
    profile_completeness text;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR jsonb_typeof(p_payload) <> 'object'
       OR ARRAY(
           SELECT key
           FROM jsonb_object_keys(p_payload) AS key
           ORDER BY key COLLATE "C"
       ) IS DISTINCT FROM ARRAY[
           'asset_source_version', 'classification', 'column_count', 'columns',
           'completeness', 'domain_id', 'normalized_payload_hash', 'observed_at',
           'profile_kind', 'profiled_at', 'provenance_fingerprint',
           'provenance_key_id', 'provider_config_hash', 'provider_contract_hash',
           'provider_query_hash', 'provider_version', 'row_count', 'size_bytes',
           'source_watermark_hash', 'stale_at', 'system_id'
       ]::text[] THEN
        RAISE EXCEPTION 'invalid Profile projection payload'
            USING ERRCODE = '23514';
    END IF;

    SELECT asset.* INTO selected_asset
    FROM catalog.assets_projection AS asset
    WHERE asset.workspace_id = p_workspace_id
      AND asset.id = p_asset_id
      AND asset.deleted_at IS NULL
      AND asset.lifecycle = 'ACTIVE'
    FOR KEY SHARE;
    IF NOT FOUND OR NOT catalog.current_profile_collector_can_v1(
        selected_asset.workspace_id,
        selected_asset.classification,
        selected_asset.system_id,
        selected_asset.domain_id
    ) THEN
        RAISE EXCEPTION 'Profile target is unavailable'
            USING ERRCODE = '42501';
    END IF;

    IF p_payload ->> 'asset_source_version' IS DISTINCT FROM selected_asset.source_version
       OR (p_payload ->> 'classification')::integer
            IS DISTINCT FROM selected_asset.classification
       OR NULLIF(p_payload ->> 'system_id', '')::uuid
            IS DISTINCT FROM selected_asset.system_id
       OR NULLIF(p_payload ->> 'domain_id', '')::uuid
            IS DISTINCT FROM selected_asset.domain_id
       OR jsonb_typeof(p_payload -> 'columns') <> 'array'
       OR jsonb_array_length(p_payload -> 'columns') > 1000
       OR (p_payload ->> 'provider_version') IS NULL
       OR char_length(p_payload ->> 'provider_version') NOT BETWEEN 1 AND 64
       OR (p_payload ->> 'asset_source_version') IS NULL
       OR char_length(p_payload ->> 'asset_source_version') NOT BETWEEN 1 AND 255 THEN
        RAISE EXCEPTION 'Profile target or collection contract drift'
            USING ERRCODE = '23514';
    END IF;

    profile_kind := p_payload ->> 'profile_kind';
    profile_completeness := p_payload ->> 'completeness';
    observed_at := (p_payload ->> 'observed_at')::timestamptz;
    profiled_at := (p_payload ->> 'profiled_at')::timestamptz;
    stale_at := (p_payload ->> 'stale_at')::timestamptz;
    IF profile_kind NOT IN ('FULL', 'SAMPLE', 'PARTITION', 'QUERY', 'UNKNOWN')
       OR profile_completeness NOT IN ('COMPLETE', 'PARTIAL')
       OR observed_at IS NULL
       OR profiled_at IS NULL
       OR stale_at IS NULL
       OR observed_at > basis_at + interval '5 minutes'
       OR profiled_at > observed_at + interval '5 minutes'
       OR stale_at <= profiled_at
       OR jsonb_typeof(p_payload -> 'row_count') NOT IN ('number', 'null')
       OR jsonb_typeof(p_payload -> 'column_count') NOT IN ('number', 'null')
       OR jsonb_typeof(p_payload -> 'size_bytes') NOT IN ('number', 'null')
       OR (
           p_payload ->> 'row_count' IS NOT NULL
           AND (
               (p_payload ->> 'row_count')::numeric < 0
               OR (p_payload ->> 'row_count')::numeric > 9223372036854775807
               OR trunc((p_payload ->> 'row_count')::numeric)
                    <> (p_payload ->> 'row_count')::numeric
           )
       )
       OR (
           p_payload ->> 'column_count' IS NOT NULL
           AND (
               (p_payload ->> 'column_count')::numeric < 0
               OR (p_payload ->> 'column_count')::numeric > 9223372036854775807
               OR trunc((p_payload ->> 'column_count')::numeric)
                    <> (p_payload ->> 'column_count')::numeric
           )
       )
       OR (
           p_payload ->> 'size_bytes' IS NOT NULL
           AND (
               (p_payload ->> 'size_bytes')::numeric < 0
               OR (p_payload ->> 'size_bytes')::numeric > 9223372036854775807
               OR trunc((p_payload ->> 'size_bytes')::numeric)
                    <> (p_payload ->> 'size_bytes')::numeric
           )
       )
       OR (
           profile_kind IN ('PARTITION', 'QUERY')
           AND (
               char_length(COALESCE(p_payload ->> 'provenance_key_id', ''))
                   NOT BETWEEN 1 AND 128
               OR COALESCE(p_payload ->> 'provenance_fingerprint', '')
                   !~ '^[0-9a-f]{64}$'
           )
       )
       OR (
           profile_kind NOT IN ('PARTITION', 'QUERY')
           AND (
               p_payload ->> 'provenance_key_id' IS NOT NULL
               OR p_payload ->> 'provenance_fingerprint' IS NOT NULL
           )
       )
       OR EXISTS (
           SELECT 1
           FROM unnest(ARRAY[
               p_payload ->> 'normalized_payload_hash',
               p_payload ->> 'provider_config_hash',
               p_payload ->> 'provider_contract_hash',
               p_payload ->> 'provider_query_hash',
               p_payload ->> 'source_watermark_hash'
           ]) AS hash_value
           WHERE hash_value IS NULL OR hash_value !~ '^[0-9a-f]{64}$'
       ) THEN
        RAISE EXCEPTION 'invalid Profile metric or provenance shape'
            USING ERRCODE = '23514';
    END IF;

    FOR current_field IN
        SELECT value FROM jsonb_array_elements(p_payload -> 'columns')
    LOOP
        IF jsonb_typeof(current_field) <> 'object'
           OR ARRAY(
               SELECT key
               FROM jsonb_object_keys(current_field) AS key
               ORDER BY key COLLATE "C"
           ) IS DISTINCT FROM ARRAY[
               'field_path', 'null_count', 'null_proportion',
               'unique_count', 'unique_proportion'
           ]::text[]
           OR char_length(COALESCE(current_field ->> 'field_path', ''))
                NOT BETWEEN 1 AND 4096
           OR current_field ->> 'field_path'
                IS DISTINCT FROM btrim(current_field ->> 'field_path')
           OR jsonb_typeof(current_field -> 'null_count') NOT IN ('number', 'null')
           OR jsonb_typeof(current_field -> 'unique_count') NOT IN ('number', 'null')
           OR jsonb_typeof(current_field -> 'null_proportion') NOT IN ('number', 'null')
           OR jsonb_typeof(current_field -> 'unique_proportion') NOT IN ('number', 'null')
           OR (
               current_field ->> 'null_count' IS NOT NULL
               AND (
                   (current_field ->> 'null_count')::numeric < 0
                   OR (current_field ->> 'null_count')::numeric > 9223372036854775807
                   OR trunc((current_field ->> 'null_count')::numeric)
                        <> (current_field ->> 'null_count')::numeric
               )
           )
           OR (
               current_field ->> 'unique_count' IS NOT NULL
               AND (
                   (current_field ->> 'unique_count')::numeric < 0
                   OR (current_field ->> 'unique_count')::numeric > 9223372036854775807
                   OR trunc((current_field ->> 'unique_count')::numeric)
                        <> (current_field ->> 'unique_count')::numeric
               )
           )
           OR (
               current_field ->> 'null_proportion' IS NOT NULL
               AND (current_field ->> 'null_proportion')::numeric NOT BETWEEN 0 AND 1
           )
           OR (
               current_field ->> 'unique_proportion' IS NOT NULL
               AND (current_field ->> 'unique_proportion')::numeric NOT BETWEEN 0 AND 1
           )
           OR (
               p_payload ->> 'row_count' IS NOT NULL
               AND current_field ->> 'null_count' IS NOT NULL
               AND (current_field ->> 'null_count')::numeric
                    > (p_payload ->> 'row_count')::numeric
           )
           OR (
               p_payload ->> 'row_count' IS NOT NULL
               AND current_field ->> 'unique_count' IS NOT NULL
               AND (current_field ->> 'unique_count')::numeric
                    > (p_payload ->> 'row_count')::numeric
           ) THEN
            RAISE EXCEPTION 'invalid Profile column metric'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_payload -> 'columns') AS field_value
        GROUP BY field_value ->> 'field_path'
        HAVING count(*) <> 1
    ) OR (
        profile_completeness = 'COMPLETE'
        AND (
            p_payload ->> 'row_count' IS NULL
            OR p_payload ->> 'column_count' IS NULL
            OR p_payload ->> 'size_bytes' IS NULL
            OR (p_payload ->> 'column_count')::bigint
                <> jsonb_array_length(p_payload -> 'columns')
            OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements(p_payload -> 'columns') AS field_value
                WHERE field_value ->> 'null_count' IS NULL
                   OR field_value ->> 'null_proportion' IS NULL
                   OR field_value ->> 'unique_count' IS NULL
                   OR field_value ->> 'unique_proportion' IS NULL
            )
        )
    ) THEN
        RAISE EXCEPTION 'ambiguous or incomplete Profile column set'
            USING ERRCODE = '23514';
    END IF;

    target_scope_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'CATALOG_PROFILE_TARGET_SCOPE_V1',
        'workspace_id', selected_asset.workspace_id::text,
        'asset_id', selected_asset.id::text,
        'classification', selected_asset.classification,
        'system_id', selected_asset.system_id::text,
        'domain_id', selected_asset.domain_id::text,
        'source_version', selected_asset.source_version
    )::text, 'UTF8')), 'hex');
    calculated_identity_hash := encode(sha256(convert_to(jsonb_build_object(
        'contract', 'CATALOG_PROFILE_SNAPSHOT_IDENTITY_V1',
        'workspace_id', p_workspace_id::text,
        'asset_id', p_asset_id::text,
        'profiled_at', profiled_at,
        'profile_kind', profile_kind,
        'target_scope_hash', target_scope_hash,
        'provider_version', p_payload ->> 'provider_version',
        'provider_contract_hash', p_payload ->> 'provider_contract_hash',
        'provider_query_hash', p_payload ->> 'provider_query_hash',
        'provider_config_hash', p_payload ->> 'provider_config_hash',
        'source_watermark_hash', p_payload ->> 'source_watermark_hash',
        'normalized_payload_hash', p_payload ->> 'normalized_payload_hash',
        'provenance_key_id', p_payload ->> 'provenance_key_id',
        'provenance_fingerprint', p_payload ->> 'provenance_fingerprint'
    )::text, 'UTF8')), 'hex');

    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_workspace_id::text || ':' || p_asset_id::text || ':' ||
        calculated_identity_hash,
        0
    ));
    SELECT snapshot.* INTO existing_snapshot
    FROM catalog.asset_profile_snapshots AS snapshot
    WHERE snapshot.workspace_id = p_workspace_id
      AND snapshot.asset_id = p_asset_id
      AND snapshot.snapshot_identity_hash = calculated_identity_hash
    FOR UPDATE;
    IF FOUND THEN
        UPDATE catalog.asset_profile_snapshots AS snapshot
        SET last_observed_at = GREATEST(snapshot.last_observed_at, observed_at)
        WHERE snapshot.workspace_id = p_workspace_id
          AND snapshot.id = existing_snapshot.id
        RETURNING snapshot.last_observed_at
        INTO last_observed_at;
        snapshot_id := existing_snapshot.id;
        snapshot_identity_hash := calculated_identity_hash;
        created := false;
        RETURN NEXT;
        RETURN;
    END IF;

    inserted_snapshot_id := gen_random_uuid();
    SELECT * INTO resolved
    FROM retention.resolve_quality_binding_v1(
        p_workspace_id,
        'QUALITY_PROFILE',
        'PROFILE_SNAPSHOT',
        inserted_snapshot_id,
        basis_at
    );
    INSERT INTO catalog.asset_profile_snapshots (
        id, workspace_id, asset_id, asset_source_version,
        snapshot_identity_hash, profile_kind, completeness,
        profiled_at, first_observed_at, last_observed_at, stale_at,
        row_count, column_count, size_bytes,
        provenance_key_id, provenance_fingerprint,
        provider_version, provider_contract_hash, provider_query_hash,
        provider_config_hash, source_watermark_hash, normalized_payload_hash,
        classification, system_id, domain_id, target_scope_hash,
        profile_retention_kind, profile_retention_policy_id,
        profile_retention_policy_number, profile_retention_policy_hash,
        profile_retention_basis_at, profile_retain_until,
        profile_hold_generation, profile_hold_hash
    )
    VALUES (
        inserted_snapshot_id, p_workspace_id, p_asset_id, selected_asset.source_version,
        calculated_identity_hash, profile_kind, profile_completeness,
        profiled_at, observed_at, observed_at, stale_at,
        NULLIF(p_payload ->> 'row_count', '')::bigint,
        NULLIF(p_payload ->> 'column_count', '')::bigint,
        NULLIF(p_payload ->> 'size_bytes', '')::bigint,
        p_payload ->> 'provenance_key_id',
        p_payload ->> 'provenance_fingerprint',
        p_payload ->> 'provider_version',
        p_payload ->> 'provider_contract_hash',
        p_payload ->> 'provider_query_hash',
        p_payload ->> 'provider_config_hash',
        p_payload ->> 'source_watermark_hash',
        p_payload ->> 'normalized_payload_hash',
        selected_asset.classification, selected_asset.system_id,
        selected_asset.domain_id, target_scope_hash,
        'QUALITY_PROFILE', resolved.policy_id, resolved.policy_number,
        resolved.policy_hash, basis_at, resolved.retain_until,
        resolved.hold_generation, resolved.hold_hash
    );
    INSERT INTO catalog.column_profile_metrics (
        id, workspace_id, snapshot_id, field_path,
        null_count_available, null_count,
        null_proportion_available, null_proportion,
        unique_count_available, unique_count,
        unique_proportion_available, unique_proportion,
        classification, target_scope_hash,
        profile_retention_policy_id, profile_retention_policy_number,
        profile_retention_policy_hash, profile_retain_until,
        profile_hold_generation, profile_hold_hash
    )
    SELECT
        gen_random_uuid(), p_workspace_id, inserted_snapshot_id,
        field_value ->> 'field_path',
        field_value ->> 'null_count' IS NOT NULL,
        NULLIF(field_value ->> 'null_count', '')::bigint,
        field_value ->> 'null_proportion' IS NOT NULL,
        NULLIF(field_value ->> 'null_proportion', '')::numeric,
        field_value ->> 'unique_count' IS NOT NULL,
        NULLIF(field_value ->> 'unique_count', '')::bigint,
        field_value ->> 'unique_proportion' IS NOT NULL,
        NULLIF(field_value ->> 'unique_proportion', '')::numeric,
        selected_asset.classification, target_scope_hash,
        resolved.policy_id, resolved.policy_number, resolved.policy_hash,
        resolved.retain_until, resolved.hold_generation, resolved.hold_hash
    FROM jsonb_array_elements(p_payload -> 'columns') AS field_value;

    snapshot_id := inserted_snapshot_id;
    snapshot_identity_hash := calculated_identity_hash;
    created := true;
    last_observed_at := observed_at;
    RETURN NEXT;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION catalog.project_asset_profile_v1(uuid, uuid, jsonb) FROM PUBLIC;
"""

_PROFILE_RLS_AND_GRANTS_SQL = """
ALTER TABLE catalog.asset_profile_snapshots ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE catalog.asset_profile_snapshots FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
CREATE POLICY workspace_isolation ON catalog.asset_profile_snapshots
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
);
-- datariver-statement-boundary
ALTER TABLE catalog.column_profile_metrics ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE catalog.column_profile_metrics FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
CREATE POLICY workspace_isolation ON catalog.column_profile_metrics
USING (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
)
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
);
-- datariver-statement-boundary
REVOKE ALL ON catalog.asset_profile_snapshots FROM PUBLIC, datariver_catalog_profile;
-- datariver-statement-boundary
REVOKE ALL ON catalog.column_profile_metrics FROM PUBLIC, datariver_catalog_profile;
-- datariver-statement-boundary
REVOKE ALL ON ALL SEQUENCES IN SCHEMA catalog FROM datariver_catalog_profile;
-- datariver-statement-boundary
GRANT USAGE ON SCHEMA catalog TO datariver_catalog_profile;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION catalog.read_profile_target_v1(uuid, uuid)
TO datariver_catalog_profile;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION catalog.project_asset_profile_v1(uuid, uuid, jsonb)
TO datariver_catalog_profile;
"""

_RETENTION_V3_RESTORE_SQL = """
ALTER TABLE retention.policy_versions
    DROP CONSTRAINT IF EXISTS ck_policy_versions_contract_shape;
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
    ADD CONSTRAINT ck_policy_class_rules_data_class CHECK (
        data_class IN (
            'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT'
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    DROP CONSTRAINT IF EXISTS ck_legal_holds_data_class;
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    ADD CONSTRAINT ck_legal_holds_data_class CHECK (
        data_class IN (
            'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT'
        )
    );
-- datariver-statement-boundary
ALTER TABLE retention.legal_holds
    DROP CONSTRAINT IF EXISTS ck_legal_holds_scope_shape;
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
    DROP CONSTRAINT IF EXISTS ck_legal_holds_resource_semantics;
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
ALTER TABLE retention.legal_hold_generations
    DROP CONSTRAINT IF EXISTS ck_legal_hold_generations_data_class;
-- datariver-statement-boundary
ALTER TABLE retention.legal_hold_generations
    ADD CONSTRAINT ck_legal_hold_generations_data_class CHECK (
        data_class IN (
            'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA',
            'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT'
        )
    );
"""


def _profile_tables() -> Iterable[object]:
    for table_name in _PROFILE_TABLE_NAMES:
        yield Base.metadata.tables[f"catalog.{table_name}"]


def _execute_script(sql: str) -> None:
    for statement in sql.split(_STATEMENT_BOUNDARY):
        cleaned = statement.strip()
        if cleaned:
            op.execute(cleaned)


def _schema_contract_hash() -> str:
    rendered: list[str] = []
    dialect = postgresql.dialect()
    for table in _profile_tables():
        rendered.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        rendered.extend(
            str(CreateIndex(index).compile(dialect=dialect)).strip()
            for index in sorted(
                table.indexes,  # type: ignore[attr-defined]
                key=lambda value: value.name or "",
            )
        )
    return sha256("\n-- contract-item --\n".join(rendered).encode()).hexdigest()


def _catalog_contract_document(bind: object) -> list[list[str]]:
    rows = bind.execute(  # type: ignore[attr-defined]
        text(
            """
            WITH managed_tables(schema_name, table_name) AS (
                VALUES
                    ('catalog'::text, 'asset_profile_snapshots'::text),
                    ('catalog'::text, 'column_profile_metrics'::text)
            ),
            contract_items AS (
                SELECT
                    'column'::text AS category,
                    namespace.nspname || '.' || relation.relname || '.' ||
                        attribute.attname AS identity,
                    jsonb_build_object(
                        'type', format_type(attribute.atttypid, attribute.atttypmod),
                        'not_null', attribute.attnotnull,
                        'default', pg_get_expr(default_value.adbin, default_value.adrelid)
                    )::text AS definition
                FROM managed_tables
                JOIN pg_namespace AS namespace
                  ON namespace.nspname = managed_tables.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed_tables.table_name
                JOIN pg_attribute AS attribute
                  ON attribute.attrelid = relation.oid
                 AND attribute.attnum > 0
                 AND NOT attribute.attisdropped
                LEFT JOIN pg_attrdef AS default_value
                  ON default_value.adrelid = relation.oid
                 AND default_value.adnum = attribute.attnum

                UNION ALL
                SELECT
                    CASE constraint_value.contype
                        WHEN 'f' THEN 'foreign_key'
                        WHEN 'u' THEN 'unique'
                        WHEN 'p' THEN 'primary_key'
                        ELSE 'check'
                    END,
                    namespace.nspname || '.' || relation.relname || '.' ||
                        constraint_value.conname,
                    pg_get_constraintdef(constraint_value.oid, true)
                FROM managed_tables
                JOIN pg_namespace AS namespace
                  ON namespace.nspname = managed_tables.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed_tables.table_name
                JOIN pg_constraint AS constraint_value
                  ON constraint_value.conrelid = relation.oid

                UNION ALL
                SELECT
                    'index',
                    schemaname || '.' || tablename || '.' || indexname,
                    indexdef
                FROM pg_indexes
                WHERE (schemaname, tablename) IN (
                    ('catalog', 'asset_profile_snapshots'),
                    ('catalog', 'column_profile_metrics')
                )

                UNION ALL
                SELECT
                    'rls',
                    namespace.nspname || '.' || relation.relname,
                    jsonb_build_object(
                        'enabled', relation.relrowsecurity,
                        'forced', relation.relforcerowsecurity
                    )::text
                FROM managed_tables
                JOIN pg_namespace AS namespace
                  ON namespace.nspname = managed_tables.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = managed_tables.table_name

                UNION ALL
                SELECT
                    'policy',
                    schemaname || '.' || tablename || '.' || policyname,
                    jsonb_build_object(
                        'permissive', permissive,
                        'roles', roles,
                        'command', cmd,
                        'using', qual,
                        'check', with_check
                    )::text
                FROM pg_policies
                WHERE (schemaname, tablename) IN (
                    ('catalog', 'asset_profile_snapshots'),
                    ('catalog', 'column_profile_metrics')
                )

                UNION ALL
                SELECT
                    'function',
                    procedure_value.oid::regprocedure::text,
                    pg_get_functiondef(procedure_value.oid)
                FROM pg_proc AS procedure_value
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure_value.pronamespace
                WHERE namespace.nspname IN ('catalog', 'retention')
                  AND procedure_value.proname IN (
                      'current_profile_collector_can_v1',
                      'read_profile_target_v1',
                      'project_asset_profile_v1',
                      'resolve_quality_binding_v1'
                  )

                UNION ALL
                SELECT
                    'function_grant',
                    procedure_value.oid::regprocedure::text || '.' ||
                        COALESCE(grantee.rolname, 'PUBLIC') || '.' ||
                        privilege.privilege_type,
                    privilege.is_grantable::text
                FROM pg_proc AS procedure_value
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure_value.pronamespace
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(procedure_value.proacl, acldefault('f', procedure_value.proowner))
                ) AS privilege
                LEFT JOIN pg_roles AS grantee ON grantee.oid = privilege.grantee
                WHERE namespace.nspname IN ('catalog', 'retention')
                  AND procedure_value.proname IN (
                      'current_profile_collector_can_v1',
                      'read_profile_target_v1',
                      'project_asset_profile_v1',
                      'resolve_quality_binding_v1'
                  )

                UNION ALL
                SELECT
                    'table_grant',
                    privilege.table_schema || '.' || privilege.table_name || '.' ||
                        privilege.grantee || '.' || privilege.privilege_type,
                    privilege.is_grantable
                FROM information_schema.role_table_grants AS privilege
                WHERE (privilege.table_schema, privilege.table_name) IN (
                    ('catalog', 'asset_profile_snapshots'),
                    ('catalog', 'column_profile_metrics')
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
                WHERE role_value.rolname = 'datariver_catalog_profile'

                UNION ALL
                SELECT
                    'role_membership',
                    member_role.rolname || '->' || granted_role.rolname,
                    membership.admin_option::text
                FROM pg_auth_members AS membership
                JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
                JOIN pg_roles AS member_role ON member_role.oid = membership.member
                WHERE granted_role.rolname = 'datariver_catalog_profile'
                   OR member_role.rolname = 'datariver_catalog_profile'
            )
            SELECT category, identity, definition
            FROM contract_items
            ORDER BY category, identity, definition
            """
        )
    ).all()
    return [[str(value) for value in row] for row in rows]


def _catalog_contract_hash(bind: object) -> str:
    return sha256(
        json.dumps(
            _catalog_contract_document(bind),
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()


def _canonical_contract_is_complete(bind: object) -> bool:
    inspector = inspect(bind)  # type: ignore[arg-type]
    catalog_tables = set(inspector.get_table_names(schema="catalog"))
    present = catalog_tables & set(_PROFILE_TABLE_NAMES)
    if not present:
        return False
    if present != set(_PROFILE_TABLE_NAMES):
        raise RuntimeError("Partial canonical Catalog Profile schema detected.")
    actual_hash = _catalog_contract_hash(bind)
    if actual_hash != _PROFILE_CATALOG_CONTRACT_HASH:
        raise RuntimeError(
            "Catalog Profile definition/security fingerprint is incomplete or drifted "
            f"(expected {_PROFILE_CATALOG_CONTRACT_HASH}, got {actual_hash})."
        )
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if _canonical_contract_is_complete(bind):
        return
    if _schema_contract_hash() != _PROFILE_SCHEMA_CONTRACT_HASH:
        raise RuntimeError("Catalog Profile ORM schema contract drifted.")
    op.execute(_PROFILE_ROLE_ASSERTION_SQL)
    _execute_script(_RETENTION_V4_SQL)
    for table in _profile_tables():
        table.create(bind=bind, checkfirst=False)  # type: ignore[attr-defined]
    _execute_script(_RESOLVER_V4_SQL)
    _execute_script(_PROFILE_FUNCTION_SQL)
    _execute_script(_PROFILE_RLS_AND_GRANTS_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM catalog.asset_profile_snapshots
            ) OR EXISTS (
                SELECT 1 FROM catalog.column_profile_metrics
            ) THEN
                RAISE EXCEPTION
                    '0068 downgrade refuses non-empty immutable Profile evidence';
            END IF;
            IF EXISTS (
                SELECT 1 FROM retention.policy_versions
                WHERE contract_version = 'POLICY_BOOK_V4'
            ) OR EXISTS (
                SELECT 1 FROM retention.policy_class_rules
                WHERE data_class = 'QUALITY_PROFILE'
            ) OR EXISTS (
                SELECT 1 FROM retention.legal_holds
                WHERE data_class = 'QUALITY_PROFILE'
                   OR resource_type = 'PROFILE_SNAPSHOT'
            ) OR EXISTS (
                SELECT 1 FROM retention.legal_hold_generations
                WHERE data_class = 'QUALITY_PROFILE'
                  AND (
                      generation <> 1
                      OR version <> 1
                      OR resolution_hash <>
                         encode(sha256(convert_to('', 'UTF8')), 'hex')
                  )
            ) THEN
                RAISE EXCEPTION
                    '0068 downgrade refuses governed Profile retention evidence';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION catalog.project_asset_profile_v1(uuid, uuid, jsonb) "
        "FROM datariver_catalog_profile"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION catalog.read_profile_target_v1(uuid, uuid) "
        "FROM datariver_catalog_profile"
    )
    op.execute("DROP FUNCTION catalog.project_asset_profile_v1(uuid, uuid, jsonb)")
    op.execute("DROP FUNCTION catalog.read_profile_target_v1(uuid, uuid)")
    for table in reversed(tuple(_profile_tables())):
        table.drop(bind=bind, checkfirst=False)  # type: ignore[attr-defined]
    op.execute("DROP FUNCTION catalog.current_profile_collector_can_v1(uuid, integer, uuid, uuid)")
    op.execute("DELETE FROM retention.legal_hold_generations WHERE data_class = 'QUALITY_PROFILE'")
    _execute_script(_RETENTION_V3_RESTORE_SQL)
    # The exact 0067 resolver is restored from its frozen migration contract by the
    # canonical generator and by normal Alembic downgrade execution below.
    op.execute(
        """
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
               OR p_resource_type NOT IN (
                   'QUALITY_RULE_SET', 'QUALITY_VALIDATION_RUN'
               )
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
              AND (
                  policy.effective_until IS NULL
                  OR policy.effective_until > p_basis_at
              )
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Quality retention requires an effective POLICY_BOOK_V3'
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
                SELECT 1 FROM retention.legal_holds AS hold
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
                WHEN 'DAYS' THEN
                    p_basis_at + make_interval(days => selected_rule.minimum_value)
                WHEN 'MONTHS' THEN
                    p_basis_at + make_interval(months => selected_rule.minimum_value)
                WHEN 'YEARS' THEN
                    p_basis_at + make_interval(years => selected_rule.minimum_value)
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
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION retention.resolve_quality_binding_v1("
        "uuid, text, text, uuid, timestamptz) FROM PUBLIC"
    )
