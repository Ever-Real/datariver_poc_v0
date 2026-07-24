"""make Sharing invocation and replay result atomic

Revision ID: 0055
Revises: 0054
Create Date: 2026-07-24 15:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATEMENT_BOUNDARY = "-- datariver-statement-boundary"


def _execute_blocks(sql: str) -> None:
    for statement in sql.split(_STATEMENT_BOUNDARY):
        if statement.strip():
            op.execute(statement)


_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION sharing.prepare_api_invocation_v2(
    p_workspace_id uuid,
    p_subject_id uuid,
    p_grant_id uuid,
    p_invocation_key_hash text,
    p_legacy_invocation_key text,
    p_consumer_issuer text,
    p_consumer_client_id text,
    p_product_id uuid,
    p_product_version_id uuid,
    p_graph_id uuid,
    p_release_id uuid,
    p_release_content_hash text,
    p_surface text,
    p_requested_scope text,
    p_effective_classification integer,
    p_security_scope_hash text,
    p_request_hash text,
    p_result_type text
)
RETURNS TABLE (
    status text,
    invocation_id uuid,
    stored_result_hash text,
    stored_result_size_bytes integer,
    stored_retention_policy_id uuid,
    stored_retention_policy_hash text,
    stored_retention_data_class text,
    stored_retention_until timestamptz,
    result_document text,
    minute_units bigint,
    month_units bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, sharing
SET TimeZone = 'UTC'
AS $$
DECLARE
    stored sharing.api_invocations%ROWTYPE;
    stored_result sharing.api_invocation_results%ROWTYPE;
    product sharing.api_products%ROWTYPE;
    version sharing.api_product_versions%ROWTYPE;
    grant_value sharing.consumer_grants%ROWTYPE;
    consumer iam.workspace_memberships%ROWTYPE;
    consumer_subject iam.subjects%ROWTYPE;
    current_retention_policy_id uuid;
    current_retention_policy_hash text;
    current_retention_data_class text;
    release_valid boolean;
    lineage_count bigint;
    observed_at timestamptz := clock_timestamp();
    observed_month timestamptz :=
        date_trunc('month', observed_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
BEGIN
    IF p_workspace_id IS DISTINCT FROM
            NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_subject_id IS DISTINCT FROM
            NULLIF(current_setting('app.subject_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Sharing invocation context is absent or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF COALESCE(char_length(p_invocation_key_hash), 0) <> 64
       OR COALESCE(char_length(p_release_content_hash), 0) <> 64
       OR COALESCE(char_length(p_security_scope_hash), 0) <> 64
       OR COALESCE(char_length(p_request_hash), 0) <> 64
       OR COALESCE(char_length(p_legacy_invocation_key), 0) NOT BETWEEN 16 AND 200
       OR COALESCE(char_length(p_consumer_issuer), 0) NOT BETWEEN 1 AND 500
       OR COALESCE(char_length(p_consumer_client_id), 0) NOT BETWEEN 3 AND 255
       OR COALESCE(char_length(p_surface), 0) NOT BETWEEN 1 AND 32
       OR COALESCE(char_length(p_requested_scope), 0) NOT BETWEEN 1 AND 100
       OR COALESCE(char_length(p_result_type), 0) NOT BETWEEN 1 AND 32
       OR p_invocation_key_hash !~ '^[0-9a-f]{64}$'
       OR p_security_scope_hash !~ '^[0-9a-f]{64}$'
       OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_release_content_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Sharing invocation hashes are invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO product
    FROM sharing.api_products AS selected_product
    WHERE selected_product.workspace_id = p_workspace_id
      AND selected_product.id = p_product_id
      AND selected_product.graph_id = p_graph_id
      AND selected_product.state = 'PUBLISHED'
      AND selected_product.current_version_id = p_product_version_id
    FOR SHARE;
    SELECT * INTO version
    FROM sharing.api_product_versions AS selected_version
    WHERE selected_version.workspace_id = p_workspace_id
      AND selected_version.product_id = p_product_id
      AND selected_version.id = p_product_version_id
      AND selected_version.graph_id = p_graph_id
      AND selected_version.release_id = p_release_id
      AND selected_version.surface = p_surface
      AND selected_version.state = 'PUBLISHED'
    FOR SHARE;
    SELECT * INTO grant_value
    FROM sharing.consumer_grants AS selected_grant
    WHERE selected_grant.workspace_id = p_workspace_id
      AND selected_grant.id = p_grant_id
      AND selected_grant.product_id = p_product_id
      AND selected_grant.product_version_id = p_product_version_id
      AND selected_grant.contract_version = 'SUBJECT_CLIENT_V2'
      AND selected_grant.consumer_subject_id = p_subject_id
      AND selected_grant.consumer_issuer = p_consumer_issuer
      AND selected_grant.consumer_client_id = p_consumer_client_id
    FOR UPDATE;
    SELECT * INTO consumer
    FROM iam.workspace_memberships AS membership
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = p_subject_id
      AND membership.active
      AND membership.job_function = 'SERVICE_ACCOUNT'
      AND membership.access_expires_at IS NULL
    FOR SHARE;
    SELECT * INTO consumer_subject
    FROM iam.subjects AS subject_value
    WHERE subject_value.id = p_subject_id
      AND subject_value.active
      AND subject_value.issuer = p_consumer_issuer
    FOR SHARE;
    SELECT true INTO release_valid
    FROM knowledge.releases AS release
    WHERE release.workspace_id = p_workspace_id
      AND release.graph_id = p_graph_id
      AND release.id = p_release_id
      AND release.content_hash = p_release_content_hash
    FOR SHARE;
    SELECT count(*) INTO lineage_count
    FROM (
        SELECT changeset.id
        FROM knowledge.changesets AS changeset
        WHERE changeset.workspace_id = p_workspace_id
          AND changeset.graph_id = p_graph_id
          AND changeset.published_release_id = p_release_id
          AND changeset.state = 'PUBLISHED'
          AND changeset.reviewed_by IS NOT NULL
          AND changeset.reviewed_by <> changeset.author_id
          AND changeset.reviewed_at IS NOT NULL
          AND length(btrim(changeset.review_reason)) > 0
        FOR SHARE
    ) AS governed_lineage;
    IF product.id IS NULL
       OR version.id IS NULL
       OR grant_value.id IS NULL
       OR grant_value.state <> 'ACTIVE'
       OR observed_at < grant_value.valid_from
       OR observed_at >= grant_value.expires_at
       OR NOT (grant_value.scopes ? p_requested_scope)
       OR product.classification > grant_value.maximum_classification
       OR p_effective_classification < product.classification
       OR p_effective_classification > grant_value.maximum_classification
       OR p_surface NOT IN ('SNAPSHOT', 'NEIGHBORS', 'CHAT')
       OR (
           p_surface = 'SNAPSHOT'
           AND (
               p_requested_scope <> 'snapshot.read'
               OR p_result_type <> 'SNAPSHOT_V1'
               OR version.contract_document->>'query_template' <> 'snapshot-v1'
           )
       )
       OR (
           p_surface = 'NEIGHBORS'
           AND (
               p_requested_scope <> 'neighbors.query'
               OR p_result_type <> 'NEIGHBORS_V1'
               OR version.contract_document->>'query_template' <> 'neighbors-v1'
           )
       )
       OR (
           p_surface = 'CHAT'
           AND (
               p_requested_scope <> 'chat.query'
               OR p_result_type <> 'CHAT_LOCAL_V1'
               OR version.contract_document->>'query_template' <> 'chat-v1'
           )
       )
       OR NOT (version.contract_document->'scopes' ? p_requested_scope)
       OR version.contract_document->'response_schema'->>'type' <> 'object'
       OR COALESCE(
           (version.contract_document->'response_schema'
               ->>'additionalProperties')::boolean,
           TRUE
       )
       OR consumer.subject_id IS NULL
       OR consumer_subject.id IS NULL
       OR release_valid IS DISTINCT FROM true
       OR lineage_count <> 1 THEN
        RETURN QUERY SELECT
            'DENIED'::text, NULL::uuid, NULL::text, NULL::integer,
            NULL::uuid, NULL::text, NULL::text, NULL::timestamptz,
            NULL::text, 0::bigint, 0::bigint;
        RETURN;
    END IF;

    current_retention_data_class := CASE p_surface
        WHEN 'CHAT' THEN 'CHAT_CONTENT'
        ELSE 'OBJECT_DATA'
    END;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('datariver:retention:workspace:' || p_workspace_id::text, 0)
    );
    SELECT selected_policy.id, selected_policy.payload_hash
    INTO current_retention_policy_id, current_retention_policy_hash
    FROM retention.policy_versions AS selected_policy
    JOIN retention.policy_class_rules AS selected_rule
      ON selected_rule.workspace_id = selected_policy.workspace_id
     AND selected_rule.policy_id = selected_policy.id
     AND selected_rule.policy_hash = selected_policy.payload_hash
    WHERE selected_policy.workspace_id = p_workspace_id
      AND selected_policy.contract_version = 'POLICY_BOOK_V2'
      AND selected_policy.state = 'ACTIVE'
      AND selected_policy.effective_from <= observed_at
      AND (
          selected_policy.effective_until IS NULL
          OR selected_policy.effective_until > observed_at
      )
      AND selected_rule.data_class = current_retention_data_class
      AND selected_rule.minimum_value >= 1
      AND EXISTS (
          SELECT 1
          FROM retention.policy_class_rules AS audit_rule
          WHERE audit_rule.workspace_id = selected_policy.workspace_id
            AND audit_rule.policy_id = selected_policy.id
            AND audit_rule.policy_hash = selected_policy.payload_hash
            AND audit_rule.data_class = 'AUDIT_EVIDENCE'
            AND audit_rule.minimum_value >= 1
      )
    FOR SHARE OF selected_policy, selected_rule;
    IF current_retention_policy_id IS NULL THEN
        RETURN QUERY SELECT
            'DENIED'::text, NULL::uuid, NULL::text, NULL::integer,
            NULL::uuid, NULL::text, current_retention_data_class, NULL::timestamptz,
            NULL::text, 0::bigint, 0::bigint;
        RETURN;
    END IF;

    SELECT *
    INTO stored
    FROM sharing.api_invocations AS invocation
    WHERE invocation.workspace_id = p_workspace_id
      AND invocation.grant_id = p_grant_id
      AND invocation.invocation_key IN (
          p_invocation_key_hash,
          p_legacy_invocation_key
      )
    LIMIT 1;

    IF FOUND THEN
        IF stored.evidence_kind <> 'ATOMIC_RESULT_V2' THEN
            RETURN QUERY SELECT
                'LEGACY'::text, stored.id, NULL::text, NULL::integer,
                NULL::uuid, NULL::text, NULL::text, NULL::timestamptz,
                NULL::text, 0::bigint, 0::bigint;
            RETURN;
        END IF;
        IF stored.actor_id IS DISTINCT FROM p_subject_id
           OR stored.consumer_issuer IS DISTINCT FROM p_consumer_issuer
           OR stored.consumer_client_id IS DISTINCT FROM p_consumer_client_id
           OR stored.product_id IS DISTINCT FROM p_product_id
           OR stored.product_version_id IS DISTINCT FROM p_product_version_id
           OR stored.graph_id IS DISTINCT FROM p_graph_id
           OR stored.release_id IS DISTINCT FROM p_release_id
           OR stored.release_content_hash IS DISTINCT FROM p_release_content_hash
           OR stored.surface IS DISTINCT FROM p_surface
           OR stored.requested_scope IS DISTINCT FROM p_requested_scope
           OR stored.effective_classification IS DISTINCT FROM p_effective_classification
           OR stored.security_scope_hash IS DISTINCT FROM p_security_scope_hash
           OR stored.request_hash IS DISTINCT FROM p_request_hash
           OR stored.result_type IS DISTINCT FROM p_result_type THEN
            RETURN QUERY SELECT
                'CONFLICT'::text, stored.id, NULL::text, NULL::integer,
                NULL::uuid, NULL::text, NULL::text, NULL::timestamptz,
                NULL::text, 0::bigint, 0::bigint;
            RETURN;
        END IF;
        IF stored.audit_retention_policy_id IS DISTINCT FROM current_retention_policy_id
           OR stored.audit_retention_policy_hash IS DISTINCT FROM current_retention_policy_hash
           OR stored.audit_retention_until IS NULL THEN
            RETURN QUERY SELECT
                'DENIED'::text, stored.id, NULL::text, NULL::integer,
                stored.retention_policy_id, stored.retention_policy_hash::text,
                stored.retention_data_class::text, stored.retention_until,
                NULL::text, 0::bigint, 0::bigint;
            RETURN;
        END IF;
        IF stored.retention_until IS NULL OR observed_at >= stored.retention_until THEN
            RETURN QUERY SELECT
                'EXPIRED'::text, stored.id, NULL::text, NULL::integer,
                stored.retention_policy_id, stored.retention_policy_hash::text,
                stored.retention_data_class::text, stored.retention_until,
                NULL::text, 0::bigint, 0::bigint;
            RETURN;
        END IF;
        SELECT *
        INTO stored_result
        FROM sharing.api_invocation_results AS result
        WHERE result.workspace_id = p_workspace_id
          AND result.invocation_id = stored.id
          AND result.actor_id = p_subject_id
          AND result.consumer_client_id = p_consumer_client_id;
        IF NOT FOUND
           OR stored_result.result_type IS DISTINCT FROM stored.result_type
           OR stored_result.result_hash IS DISTINCT FROM stored.result_hash
           OR stored_result.result_size_bytes IS DISTINCT FROM stored.result_size_bytes
           OR stored_result.retention_policy_id IS DISTINCT FROM stored.retention_policy_id
           OR stored_result.retention_policy_hash IS DISTINCT FROM stored.retention_policy_hash
           OR stored_result.retention_data_class IS DISTINCT FROM stored.retention_data_class
           OR stored_result.retention_until IS DISTINCT FROM stored.retention_until THEN
            RETURN QUERY SELECT
                'CORRUPT'::text, stored.id, NULL::text, NULL::integer,
                stored.retention_policy_id, stored.retention_policy_hash::text,
                stored.retention_data_class::text, stored.retention_until,
                NULL::text, 0::bigint, 0::bigint;
            RETURN;
        END IF;
        IF stored.retention_policy_id IS DISTINCT FROM current_retention_policy_id
           OR stored.retention_policy_hash IS DISTINCT FROM current_retention_policy_hash
           OR stored.retention_data_class IS DISTINCT FROM current_retention_data_class THEN
            RETURN QUERY SELECT
                'DENIED'::text, stored.id, NULL::text, NULL::integer,
                stored.retention_policy_id, stored.retention_policy_hash::text,
                stored.retention_data_class::text, stored.retention_until,
                NULL::text, 0::bigint, 0::bigint;
            RETURN;
        END IF;
        RETURN QUERY SELECT
            'REPLAY'::text,
            stored.id,
            stored_result.result_hash::text,
            stored_result.result_size_bytes,
            stored_result.retention_policy_id,
            stored_result.retention_policy_hash::text,
            stored_result.retention_data_class::text,
            stored_result.retention_until,
            stored_result.result_document,
            0::bigint,
            0::bigint;
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        'NEW'::text,
        NULL::uuid,
        NULL::text,
        NULL::integer,
        current_retention_policy_id,
        current_retention_policy_hash,
        current_retention_data_class,
        NULL::timestamptz,
        NULL::text,
        (
            SELECT count(*)::bigint
            FROM sharing.api_invocations AS recent
            WHERE recent.workspace_id = p_workspace_id
              AND recent.grant_id = p_grant_id
              AND recent.occurred_at >= observed_at - interval '1 minute'
        ),
        COALESCE(
            (
                SELECT monthly.units::bigint
                FROM sharing.api_invocation_monthly_usage AS monthly
                WHERE monthly.workspace_id = p_workspace_id
                  AND monthly.grant_id = p_grant_id
                  AND monthly.month_start = observed_month
            ),
            0::bigint
        );
END
$$;
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION sharing.complete_api_invocation_v2(
    p_workspace_id uuid,
    p_subject_id uuid,
    p_grant_id uuid,
    p_invocation_id uuid,
    p_invocation_key_hash text,
    p_legacy_invocation_key text,
    p_consumer_issuer text,
    p_consumer_client_id text,
    p_product_id uuid,
    p_product_version_id uuid,
    p_graph_id uuid,
    p_release_id uuid,
    p_release_content_hash text,
    p_surface text,
    p_requested_scope text,
    p_request_id text,
    p_effective_classification integer,
    p_security_scope_hash text,
    p_request_hash text,
    p_result_type text,
    p_result_document text,
    p_retention_data_class text,
    p_retention_policy_id uuid,
    p_retention_policy_hash text
)
RETURNS TABLE (
    status text,
    occurred_at timestamptz,
    completed_at timestamptz,
    result_hash text,
    result_size_bytes integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, sharing, iam, knowledge, retention
SET TimeZone = 'UTC'
AS $$
DECLARE
    product sharing.api_products%ROWTYPE;
    version sharing.api_product_versions%ROWTYPE;
    grant_value sharing.consumer_grants%ROWTYPE;
    consumer iam.workspace_memberships%ROWTYPE;
    consumer_subject iam.subjects%ROWTYPE;
    policy retention.policy_versions%ROWTYPE;
    class_rule retention.policy_class_rules%ROWTYPE;
    audit_rule retention.policy_class_rules%ROWTYPE;
    observed_at timestamptz := clock_timestamp();
    observed_month timestamptz :=
        date_trunc('month', observed_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    minute_count bigint;
    month_count bigint;
    canonical_size integer;
    canonical_hash text;
    calculated_retention_until timestamptz;
    calculated_audit_retention_until timestamptz;
    release_valid boolean;
    lineage_count bigint;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
            NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_subject_id IS DISTINCT FROM
            NULLIF(current_setting('app.subject_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Sharing invocation context is absent or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF COALESCE(char_length(p_invocation_key_hash), 0) <> 64
       OR COALESCE(char_length(p_release_content_hash), 0) <> 64
       OR COALESCE(char_length(p_security_scope_hash), 0) <> 64
       OR COALESCE(char_length(p_request_hash), 0) <> 64
       OR COALESCE(char_length(p_retention_policy_hash), 0) <> 64
       OR COALESCE(char_length(p_legacy_invocation_key), 0) NOT BETWEEN 16 AND 200
       OR COALESCE(char_length(p_consumer_issuer), 0) NOT BETWEEN 1 AND 500
       OR COALESCE(char_length(p_consumer_client_id), 0) NOT BETWEEN 3 AND 255
       OR COALESCE(char_length(p_surface), 0) NOT BETWEEN 1 AND 32
       OR COALESCE(char_length(p_requested_scope), 0) NOT BETWEEN 1 AND 100
       OR COALESCE(char_length(p_request_id), 0) NOT BETWEEN 1 AND 100
       OR COALESCE(char_length(p_result_type), 0) NOT BETWEEN 1 AND 32
       OR COALESCE(char_length(p_retention_data_class), 0) NOT BETWEEN 1 AND 32
       OR p_invocation_key_hash !~ '^[0-9a-f]{64}$'
       OR p_security_scope_hash !~ '^[0-9a-f]{64}$'
       OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_release_content_hash !~ '^[0-9a-f]{64}$'
       OR p_retention_policy_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Sharing invocation hashes are invalid'
            USING ERRCODE = '22023';
    END IF;
    canonical_size := octet_length(convert_to(COALESCE(p_result_document, ''), 'UTF8'));
    IF canonical_size < 2 OR canonical_size > 1048576 THEN
        RETURN QUERY SELECT
            'OVERSIZE'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;
    IF jsonb_typeof(p_result_document::jsonb) <> 'object' THEN
        RAISE EXCEPTION 'Sharing result must be a JSON object'
            USING ERRCODE = '22023';
    END IF;
    canonical_hash := encode(sha256(convert_to(p_result_document, 'UTF8')), 'hex');

    SELECT * INTO product
    FROM sharing.api_products AS selected_product
    WHERE selected_product.workspace_id = p_workspace_id
      AND selected_product.id = p_product_id
      AND selected_product.graph_id = p_graph_id
      AND selected_product.state = 'PUBLISHED'
      AND selected_product.current_version_id = p_product_version_id
    FOR SHARE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            'DENIED'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    SELECT * INTO version
    FROM sharing.api_product_versions AS selected_version
    WHERE selected_version.workspace_id = p_workspace_id
      AND selected_version.product_id = p_product_id
      AND selected_version.id = p_product_version_id
      AND selected_version.graph_id = p_graph_id
      AND selected_version.release_id = p_release_id
      AND selected_version.surface = p_surface
      AND selected_version.state = 'PUBLISHED'
    FOR SHARE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            'DENIED'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    SELECT * INTO grant_value
    FROM sharing.consumer_grants AS selected_grant
    WHERE selected_grant.workspace_id = p_workspace_id
      AND selected_grant.id = p_grant_id
      AND selected_grant.product_id = p_product_id
      AND selected_grant.product_version_id = p_product_version_id
      AND selected_grant.contract_version = 'SUBJECT_CLIENT_V2'
      AND selected_grant.consumer_subject_id = p_subject_id
      AND selected_grant.consumer_issuer = p_consumer_issuer
      AND selected_grant.consumer_client_id = p_consumer_client_id
    FOR UPDATE;
    IF NOT FOUND
       OR grant_value.state <> 'ACTIVE'
       OR observed_at < grant_value.valid_from
       OR observed_at >= grant_value.expires_at
       OR NOT (grant_value.scopes ? p_requested_scope)
       OR product.classification > grant_value.maximum_classification
       OR p_effective_classification < product.classification
       OR p_effective_classification > grant_value.maximum_classification
       OR p_surface NOT IN ('SNAPSHOT', 'NEIGHBORS', 'CHAT')
       OR (
           p_surface = 'SNAPSHOT'
           AND (
               p_requested_scope <> 'snapshot.read'
               OR p_result_type <> 'SNAPSHOT_V1'
               OR version.contract_document->>'query_template' <> 'snapshot-v1'
           )
       )
       OR (
           p_surface = 'NEIGHBORS'
           AND (
               p_requested_scope <> 'neighbors.query'
               OR p_result_type <> 'NEIGHBORS_V1'
               OR version.contract_document->>'query_template' <> 'neighbors-v1'
           )
       )
       OR (
           p_surface = 'CHAT'
           AND (
               p_requested_scope <> 'chat.query'
               OR p_result_type <> 'CHAT_LOCAL_V1'
               OR version.contract_document->>'query_template' <> 'chat-v1'
           )
       )
       OR NOT (version.contract_document->'scopes' ? p_requested_scope)
       OR version.contract_document->'response_schema'->>'type' <> 'object'
       OR COALESCE(
           (version.contract_document->'response_schema'
               ->>'additionalProperties')::boolean,
           TRUE
       ) THEN
        RETURN QUERY SELECT
            'DENIED'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    SELECT * INTO consumer
    FROM iam.workspace_memberships AS membership
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = p_subject_id
      AND membership.active
      AND membership.job_function = 'SERVICE_ACCOUNT'
      AND membership.access_expires_at IS NULL
    FOR SHARE;
    SELECT * INTO consumer_subject
    FROM iam.subjects AS subject_value
    WHERE subject_value.id = p_subject_id
      AND subject_value.active
      AND subject_value.issuer = p_consumer_issuer
    FOR SHARE;
    IF consumer.subject_id IS NULL OR consumer_subject.id IS NULL THEN
        RETURN QUERY SELECT
            'DENIED'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    SELECT true INTO release_valid
    FROM knowledge.releases AS release
    WHERE release.workspace_id = p_workspace_id
      AND release.graph_id = p_graph_id
      AND release.id = p_release_id
      AND release.content_hash = p_release_content_hash
    FOR SHARE;
    SELECT count(*) INTO lineage_count
    FROM (
        SELECT changeset.id
        FROM knowledge.changesets AS changeset
        WHERE changeset.workspace_id = p_workspace_id
          AND changeset.graph_id = p_graph_id
          AND changeset.published_release_id = p_release_id
          AND changeset.state = 'PUBLISHED'
          AND changeset.reviewed_by IS NOT NULL
          AND changeset.reviewed_by <> changeset.author_id
          AND changeset.reviewed_at IS NOT NULL
          AND length(btrim(changeset.review_reason)) > 0
        FOR SHARE
    ) AS governed_lineage;
    IF release_valid IS DISTINCT FROM true OR lineage_count <> 1 THEN
        RETURN QUERY SELECT
            'DENIED'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('datariver:retention:workspace:' || p_workspace_id::text, 0)
    );
    SELECT * INTO policy
    FROM retention.policy_versions AS selected_policy
    WHERE selected_policy.workspace_id = p_workspace_id
      AND selected_policy.id = p_retention_policy_id
      AND selected_policy.payload_hash = p_retention_policy_hash
      AND selected_policy.contract_version = 'POLICY_BOOK_V2'
      AND selected_policy.state = 'ACTIVE'
      AND selected_policy.effective_from <= observed_at
      AND (
          selected_policy.effective_until IS NULL
          OR selected_policy.effective_until > observed_at
      )
    FOR SHARE;
    SELECT * INTO class_rule
    FROM retention.policy_class_rules AS selected_rule
    WHERE selected_rule.workspace_id = p_workspace_id
      AND selected_rule.policy_id = p_retention_policy_id
      AND selected_rule.policy_hash = p_retention_policy_hash
      AND selected_rule.data_class = p_retention_data_class
    FOR SHARE;
    SELECT * INTO audit_rule
    FROM retention.policy_class_rules AS selected_rule
    WHERE selected_rule.workspace_id = p_workspace_id
      AND selected_rule.policy_id = p_retention_policy_id
      AND selected_rule.policy_hash = p_retention_policy_hash
      AND selected_rule.data_class = 'AUDIT_EVIDENCE'
    FOR SHARE;
    IF policy.id IS NULL
       OR class_rule.id IS NULL
       OR class_rule.minimum_value < 1
       OR audit_rule.id IS NULL
       OR audit_rule.minimum_value < 1 THEN
        RETURN QUERY SELECT
            'RETENTION_DENIED'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;
    calculated_retention_until := CASE class_rule.unit
        WHEN 'DAYS' THEN
            observed_at + make_interval(days => class_rule.minimum_value)
        WHEN 'MONTHS' THEN
            observed_at + make_interval(months => class_rule.minimum_value)
        WHEN 'YEARS' THEN
            observed_at + make_interval(years => class_rule.minimum_value)
        ELSE NULL
    END;
    calculated_audit_retention_until := CASE audit_rule.unit
        WHEN 'DAYS' THEN
            observed_at + make_interval(days => audit_rule.minimum_value)
        WHEN 'MONTHS' THEN
            observed_at + make_interval(months => audit_rule.minimum_value)
        WHEN 'YEARS' THEN
            observed_at + make_interval(years => audit_rule.minimum_value)
        ELSE NULL
    END;
    IF calculated_retention_until IS NULL
       OR calculated_retention_until <= observed_at
       OR calculated_audit_retention_until IS NULL
       OR calculated_audit_retention_until <= observed_at THEN
        RETURN QUERY SELECT
            'RETENTION_DENIED'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM sharing.api_invocations AS existing
        WHERE existing.workspace_id = p_workspace_id
          AND existing.grant_id = p_grant_id
          AND existing.invocation_key IN (
              p_invocation_key_hash,
              p_legacy_invocation_key
          )
    ) THEN
        RETURN QUERY SELECT
            'CONFLICT'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    SELECT count(*)::bigint INTO minute_count
    FROM sharing.api_invocations AS recent
    WHERE recent.workspace_id = p_workspace_id
      AND recent.grant_id = p_grant_id
      AND recent.occurred_at >= observed_at - interval '1 minute';
    SELECT COALESCE(monthly.units, 0)::bigint INTO month_count
    FROM sharing.api_invocation_monthly_usage AS monthly
    WHERE monthly.workspace_id = p_workspace_id
      AND monthly.grant_id = p_grant_id
      AND monthly.month_start = observed_month;
    month_count := COALESCE(month_count, 0);
    IF minute_count >= grant_value.requests_per_minute THEN
        RETURN QUERY SELECT
            'RATE_MINUTE'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;
    IF month_count >= grant_value.monthly_quota THEN
        RETURN QUERY SELECT
            'RATE_MONTH'::text, NULL::timestamptz, NULL::timestamptz,
            NULL::text, NULL::integer;
        RETURN;
    END IF;

    INSERT INTO sharing.api_invocations (
        id, workspace_id, grant_id, invocation_key, evidence_kind, actor_id,
        consumer_issuer, consumer_client_id, product_id, product_version_id,
        graph_id, release_id, release_content_hash, surface, requested_scope,
        request_id, effective_classification, security_scope_hash, request_hash,
        result_type, result_hash, result_size_bytes, retention_data_class,
        retention_policy_id, retention_policy_hash, retention_until,
        audit_retention_policy_id, audit_retention_policy_hash,
        audit_retention_until,
        occurred_at, completed_at, units
    ) VALUES (
        p_invocation_id, p_workspace_id, p_grant_id, p_invocation_key_hash,
        'ATOMIC_RESULT_V2', p_subject_id, p_consumer_issuer,
        p_consumer_client_id, p_product_id, p_product_version_id, p_graph_id,
        p_release_id, p_release_content_hash, p_surface, p_requested_scope,
        p_request_id, p_effective_classification, p_security_scope_hash,
        p_request_hash, p_result_type, canonical_hash, canonical_size,
        p_retention_data_class, p_retention_policy_id, p_retention_policy_hash,
        calculated_retention_until, p_retention_policy_id,
        p_retention_policy_hash, calculated_audit_retention_until,
        observed_at, observed_at, 1
    );
    INSERT INTO sharing.api_invocation_results (
        workspace_id, invocation_id, actor_id, consumer_client_id, result_type,
        result_document, result_size_bytes, result_hash, classification,
        retention_data_class, retention_policy_id, retention_policy_hash,
        retention_until, created_at
    ) VALUES (
        p_workspace_id, p_invocation_id, p_subject_id, p_consumer_client_id,
        p_result_type, p_result_document, canonical_size, canonical_hash,
        product.classification, p_retention_data_class, p_retention_policy_id,
        p_retention_policy_hash, calculated_retention_until, observed_at
    );
    INSERT INTO sharing.api_invocation_monthly_usage (
        workspace_id, grant_id, month_start, units, updated_at
    ) VALUES (
        p_workspace_id, p_grant_id, observed_month, 1, observed_at
    )
    ON CONFLICT (workspace_id, grant_id, month_start)
    DO UPDATE SET
        units = sharing.api_invocation_monthly_usage.units + 1,
        updated_at = EXCLUDED.updated_at;

    RETURN QUERY SELECT
        'RECORDED'::text, observed_at, observed_at, canonical_hash, canonical_size;
END
$$;
"""


_TRIGGER_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION sharing.reject_invocation_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, sharing
AS $$
BEGIN
    RAISE EXCEPTION 'Sharing invocation evidence is immutable'
        USING ERRCODE = '42501';
END
$$;
-- datariver-statement-boundary
CREATE OR REPLACE FUNCTION sharing.require_atomic_invocation_result()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, sharing
AS $$
BEGIN
    IF NEW.evidence_kind = 'ATOMIC_RESULT_V2'
       AND NOT EXISTS (
           SELECT 1
           FROM sharing.api_invocation_results AS result
           WHERE result.workspace_id = NEW.workspace_id
             AND result.invocation_id = NEW.id
             AND result.actor_id = NEW.actor_id
             AND result.consumer_client_id = NEW.consumer_client_id
             AND result.result_type = NEW.result_type
             AND result.result_hash = NEW.result_hash
             AND result.result_size_bytes = NEW.result_size_bytes
             AND result.retention_data_class = NEW.retention_data_class
             AND result.retention_policy_id = NEW.retention_policy_id
             AND result.retention_policy_hash = NEW.retention_policy_hash
             AND result.retention_until = NEW.retention_until
       ) THEN
        RAISE EXCEPTION 'Atomic Sharing invocation has no exact result';
    END IF;
    RETURN NEW;
END
$$;
"""


_TRIGGER_SQL = r"""
CREATE TRIGGER api_invocations_immutable
BEFORE UPDATE OR DELETE ON sharing.api_invocations
FOR EACH ROW EXECUTE FUNCTION sharing.reject_invocation_evidence_mutation();
-- datariver-statement-boundary
CREATE TRIGGER api_invocation_results_immutable
BEFORE UPDATE OR DELETE ON sharing.api_invocation_results
FOR EACH ROW EXECUTE FUNCTION sharing.reject_invocation_evidence_mutation();
-- datariver-statement-boundary
CREATE CONSTRAINT TRIGGER api_invocation_exact_result
AFTER INSERT ON sharing.api_invocations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION sharing.require_atomic_invocation_result();
"""


_GRANT_SQL = r"""
DO $$
DECLARE
    role_is_safe boolean;
    migration_owner oid := to_regrole(current_user)::oid;
BEGIN
    SELECT
        rolcanlogin
        AND NOT rolsuper
        AND NOT rolcreatedb
        AND NOT rolcreaterole
        AND NOT rolreplication
        AND NOT rolbypassrls
    INTO role_is_safe
    FROM pg_roles
    WHERE rolname = 'datariver_app';
    IF role_is_safe IS DISTINCT FROM true THEN
        RAISE EXCEPTION
            'datariver_app must be an unprivileged direct LOGIN principal';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_app'
          AND pg_has_role('datariver_app', candidate.oid, 'MEMBER')
    ) THEN
        RAISE EXCEPTION
            'datariver_app must not inherit or SET ROLE to another principal';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS candidate
        WHERE candidate.rolname <> 'datariver_app'
          AND NOT candidate.rolsuper
          AND candidate.rolname NOT LIKE 'pg\_%' ESCAPE '\'
          AND pg_has_role(candidate.oid, 'datariver_app', 'MEMBER')
    ) THEN
        RAISE EXCEPTION
            'datariver_app must not be assumable by another non-superuser principal';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_class AS class
        JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
        WHERE namespace.nspname = 'sharing'
          AND class.relname IN (
              'api_invocations',
              'api_invocation_results',
              'api_invocation_monthly_usage'
          )
          AND class.relowner <> migration_owner
    ) OR EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        WHERE procedure.oid IN (
            to_regprocedure(
                'sharing.prepare_api_invocation_v2('
                'uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,text,'
                'text,text,integer,text,text,text)'
            ),
            to_regprocedure(
                'sharing.complete_api_invocation_v2('
                'uuid,uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,'
                'text,text,text,text,integer,text,text,text,text,text,uuid,text)'
            ),
            to_regprocedure('sharing.reject_invocation_evidence_mutation()'),
            to_regprocedure('sharing.require_atomic_invocation_result()')
        )
          AND procedure.proowner <> migration_owner
    ) THEN
        RAISE EXCEPTION
            'Atomic Sharing protected objects must remain migration-owner controlled';
    END IF;
END
$$;
-- datariver-statement-boundary
DO $$
DECLARE
    role_value record;
BEGIN
    FOR role_value IN
        SELECT role_state.rolname
        FROM pg_roles AS role_state
        WHERE role_state.oid <> (
            SELECT class.relowner
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'sharing'
              AND class.relname = 'api_invocations'
        )
    LOOP
        EXECUTE format(
            'REVOKE ALL ON sharing.api_invocations, '
            'sharing.api_invocation_results, '
            'sharing.api_invocation_monthly_usage FROM %I',
            role_value.rolname
        );
    END LOOP;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION sharing.reject_invocation_evidence_mutation()
FROM PUBLIC;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION sharing.require_atomic_invocation_result()
FROM PUBLIC;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION sharing.prepare_api_invocation_v2(
    uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid, text,
    text, text, integer, text, text, text
) FROM PUBLIC;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION sharing.complete_api_invocation_v2(
    uuid, uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid,
    text, text, text, text, integer, text, text, text, text, text, uuid,
    text
) FROM PUBLIC;
-- datariver-statement-boundary
DO $$
DECLARE
    role_value record;
BEGIN
    FOR role_value IN
        SELECT role_state.rolname
        FROM pg_roles AS role_state
        WHERE role_state.rolname <> 'datariver_app'
          AND role_state.oid <> (
              SELECT procedure.proowner
              FROM pg_proc AS procedure
              WHERE procedure.oid = to_regprocedure(
                  'sharing.prepare_api_invocation_v2('
                  'uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,text,'
                  'text,text,integer,text,text,text)'
              )
          )
    LOOP
        EXECUTE format(
            'REVOKE ALL ON FUNCTION '
            'sharing.prepare_api_invocation_v2('
            'uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,text,'
            'text,text,integer,text,text,text) FROM %I',
            role_value.rolname
        );
        EXECUTE format(
            'REVOKE ALL ON FUNCTION '
            'sharing.complete_api_invocation_v2('
            'uuid,uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,'
            'text,text,text,text,integer,text,text,text,text,text,uuid,text) FROM %I',
            role_value.rolname
        );
        EXECUTE format(
            'REVOKE ALL ON FUNCTION '
            'sharing.reject_invocation_evidence_mutation() FROM %I',
            role_value.rolname
        );
        EXECUTE format(
            'REVOKE ALL ON FUNCTION '
            'sharing.require_atomic_invocation_result() FROM %I',
            role_value.rolname
        );
    END LOOP;
END
$$;
-- datariver-statement-boundary
REVOKE ALL ON sharing.api_invocations,
    sharing.api_invocation_results,
    sharing.api_invocation_monthly_usage
FROM datariver_app;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION sharing.prepare_api_invocation_v2(
    uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid, text,
    text, text, integer, text, text, text
) TO datariver_app;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION sharing.complete_api_invocation_v2(
    uuid, uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid,
    text, text, text, text, integer, text, text, text, text, text, uuid,
    text
) TO datariver_app;
"""

_PHASE6B_COLUMN_CONTRACT = {
    ("consumer_grants", "contract_version"): ("character varying(32)", True),
    ("consumer_grants", "consumer_subject_id"): ("uuid", False),
    ("consumer_grants", "consumer_issuer"): ("character varying(500)", False),
    ("api_invocations", "evidence_kind"): ("character varying(32)", True),
    ("api_invocations", "actor_id"): ("uuid", False),
    ("api_invocations", "consumer_issuer"): ("character varying(500)", False),
    ("api_invocations", "consumer_client_id"): ("character varying(255)", False),
    ("api_invocations", "product_id"): ("uuid", False),
    ("api_invocations", "product_version_id"): ("uuid", False),
    ("api_invocations", "graph_id"): ("uuid", False),
    ("api_invocations", "release_id"): ("uuid", False),
    ("api_invocations", "release_content_hash"): ("character varying(64)", False),
    ("api_invocations", "surface"): ("character varying(32)", False),
    ("api_invocations", "effective_classification"): ("integer", False),
    ("api_invocations", "security_scope_hash"): ("character varying(64)", False),
    ("api_invocations", "request_hash"): ("character varying(64)", False),
    ("api_invocations", "result_type"): ("character varying(32)", False),
    ("api_invocations", "result_hash"): ("character varying(64)", False),
    ("api_invocations", "result_size_bytes"): ("integer", False),
    ("api_invocations", "retention_data_class"): ("character varying(32)", False),
    ("api_invocations", "retention_policy_id"): ("uuid", False),
    ("api_invocations", "retention_policy_hash"): ("character varying(64)", False),
    ("api_invocations", "retention_until"): ("timestamp with time zone", False),
    ("api_invocations", "audit_retention_policy_id"): ("uuid", False),
    ("api_invocations", "audit_retention_policy_hash"): ("character varying(64)", False),
    ("api_invocations", "audit_retention_until"): ("timestamp with time zone", False),
    ("api_invocations", "completed_at"): ("timestamp with time zone", False),
    ("api_invocation_results", "workspace_id"): ("uuid", True),
    ("api_invocation_results", "invocation_id"): ("uuid", True),
    ("api_invocation_results", "actor_id"): ("uuid", True),
    ("api_invocation_results", "consumer_client_id"): ("character varying(255)", True),
    ("api_invocation_results", "result_type"): ("character varying(32)", True),
    ("api_invocation_results", "result_document"): ("text", True),
    ("api_invocation_results", "result_size_bytes"): ("integer", True),
    ("api_invocation_results", "result_hash"): ("character varying(64)", True),
    ("api_invocation_results", "classification"): ("integer", True),
    ("api_invocation_results", "retention_data_class"): ("character varying(32)", True),
    ("api_invocation_results", "retention_policy_id"): ("uuid", True),
    ("api_invocation_results", "retention_policy_hash"): ("character varying(64)", True),
    ("api_invocation_results", "retention_until"): ("timestamp with time zone", True),
    ("api_invocation_results", "created_at"): ("timestamp with time zone", True),
    ("api_invocation_monthly_usage", "workspace_id"): ("uuid", True),
    ("api_invocation_monthly_usage", "grant_id"): ("uuid", True),
    ("api_invocation_monthly_usage", "month_start"): ("timestamp with time zone", True),
    ("api_invocation_monthly_usage", "units"): ("integer", True),
    ("api_invocation_monthly_usage", "updated_at"): ("timestamp with time zone", True),
}

_PHASE6B_CONSTRAINT_DEFINITION_MD5 = {
    ("consumer_grants", "ck_consumer_grants_contract_shape"): "66b031978ccc9784a3f6100c5e815752",
    (
        "consumer_grants",
        "fk_consumer_grants_consumer_membership",
    ): "2a9ebffe02f7b4b77e43b6777d213b34",
    (
        "consumer_grants",
        "fk_consumer_grants_workspace_id_product_id_product_vers_3221",
    ): "74ff510fdfa45b0330757dba95a9ea89",
    ("api_invocations", "ck_api_invocations_single_unit"): "2c8b62f5e19f93cdb86ff12925d8342a",
    ("api_invocations", "ck_api_invocations_evidence_shape"): "878cf3345998dd36d3e46a5c1c6dce18",
    ("api_invocations", "ck_api_invocations_surface_result"): "d849c4cd186c7554a86922718ec22eef",
    ("api_invocations", "ck_api_invocations_v2_hashes"): "3897059e3b0e151040d35d24404e6903",
    ("api_invocations", "fk_api_invocations_actor_membership"): "605a13730c7e0625248dd53a91e7405c",
    ("api_invocations", "fk_api_invocations_product_version"): "74ff510fdfa45b0330757dba95a9ea89",
    (
        "api_invocations",
        "fk_api_invocations_workspace_id_grant_id_consumer_grants",
    ): "3288e72f5a0a2774f1d2dcf2f6b8285c",
    ("api_invocations", "uq_api_invocations_workspace_id_id"): ("b45cc43f27c80ddc77c3503eeaeb2729"),
    (
        "api_invocation_results",
        "ck_api_invocation_results_classification",
    ): "784e7eeba21948a75159f7f4edf74ca8",
    (
        "api_invocation_results",
        "ck_api_invocation_results_document_object",
    ): "eafede886efb6346889ca30c6183b827",
    (
        "api_invocation_results",
        "ck_api_invocation_results_policy_hash",
    ): "a89d0242e3c5d23e3a6d8c889ae0dc2f",
    (
        "api_invocation_results",
        "ck_api_invocation_results_result_hash",
    ): "2821f3fb734465c8cfb5905320111398",
    (
        "api_invocation_results",
        "ck_api_invocation_results_retention_data_class",
    ): "b7657c4fe7706e3020f634952afed0f9",
    (
        "api_invocation_results",
        "ck_api_invocation_results_retention_window",
    ): "ead5485d48e6c2b1e149207045efd2c2",
    (
        "api_invocation_results",
        "ck_api_invocation_results_size_bound",
    ): "b82ee540a66e0c1e5545506341660cec",
    (
        "api_invocation_results",
        "fk_api_invocation_results_invocation",
    ): "fe2c34f9128501cc477d3f1163626fb7",
    ("api_invocation_results", "pk_api_invocation_results"): "7de3c042f577dc204fa63f6855e242eb",
    (
        "api_invocation_monthly_usage",
        "ck_api_invocation_monthly_usage_positive_units",
    ): "3ff020e4f14b21fa5212c71bb413d70f",
    (
        "api_invocation_monthly_usage",
        "ck_api_invocation_monthly_usage_utc_month_start",
    ): "9b76f7f33d9a7b2b0b91978f31b820d5",
    (
        "api_invocation_monthly_usage",
        "fk_api_invocation_monthly_usage_workspace_id_grant_id_c_cc44",
    ): "3288e72f5a0a2774f1d2dcf2f6b8285c",
    (
        "api_invocation_monthly_usage",
        "pk_api_invocation_monthly_usage",
    ): "2327f148afd630f4ea50541d2d42c53e",
}

_PHASE6B_INDEX_DEFINITION_MD5 = {
    "ix_api_invocation_monthly_usage_grant_month": "45fc2139b3678108f3e5a4800c426a6d",
    "ix_api_invocation_results_retention": "6c67121c239b2749c9d67bc438485503",
    "ix_api_invocations_grant_time": "c326ee301e880ce6c98b6daff51c31d3",
    "uq_consumer_grants_legacy_client": "f9d02c4a501a4c9042b3151e770c9185",
    "uq_consumer_grants_v2_subject_client": "5005f1cecaa2e5085421349cd263de15",
}

_PHASE6B_TRIGGER_DEFINITION = {
    ("api_invocation_results", "api_invocation_results_immutable"): (
        "O",
        False,
        False,
        "260332db9de5ad50a51e7e47177b217a",
    ),
    ("api_invocations", "api_invocation_exact_result"): (
        "O",
        True,
        True,
        "5fc6acd90b8906b5c91ceba2bdd10078",
    ),
    ("api_invocations", "api_invocations_immutable"): (
        "O",
        False,
        False,
        "072eeb64172dea8ba67c79f1e9bda187",
    ),
}


def _canonical_phase6b_contract_exists() -> bool:
    connection = op.get_bind()
    required_columns = {
        "sharing.consumer_grants": {
            "contract_version",
            "consumer_subject_id",
            "consumer_issuer",
        },
        "sharing.api_invocations": {
            "evidence_kind",
            "actor_id",
            "consumer_issuer",
            "consumer_client_id",
            "product_id",
            "product_version_id",
            "graph_id",
            "release_id",
            "release_content_hash",
            "surface",
            "effective_classification",
            "security_scope_hash",
            "request_hash",
            "result_type",
            "result_hash",
            "result_size_bytes",
            "retention_data_class",
            "retention_policy_id",
            "retention_policy_hash",
            "retention_until",
            "audit_retention_policy_id",
            "audit_retention_policy_hash",
            "audit_retention_until",
            "completed_at",
        },
    }
    presence: list[bool] = []
    for qualified_table, columns in required_columns.items():
        schema, table = qualified_table.split(".", 1)
        stored_columns = set(
            connection.execute(
                sa.text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table
                    """
                ),
                {"schema": schema, "table": table},
            ).scalars()
        )
        presence.extend(column in stored_columns for column in columns)
    for table in (
        "sharing.api_invocation_results",
        "sharing.api_invocation_monthly_usage",
    ):
        presence.append(
            bool(
                connection.scalar(
                    sa.text("SELECT to_regclass(:table_name) IS NOT NULL"),
                    {"table_name": table},
                )
            )
        )
    for index in (
        "sharing.uq_consumer_grants_legacy_client",
        "sharing.uq_consumer_grants_v2_subject_client",
    ):
        presence.append(
            bool(
                connection.scalar(
                    sa.text("SELECT to_regclass(:index_name) IS NOT NULL"),
                    {"index_name": index},
                )
            )
        )
    for signature in (
        "sharing.prepare_api_invocation_v2(uuid,uuid,uuid,text,text,text,text,"
        "uuid,uuid,uuid,uuid,text,text,text,integer,text,text,text)",
        "sharing.complete_api_invocation_v2(uuid,uuid,uuid,uuid,text,text,text,text,"
        "uuid,uuid,uuid,uuid,text,text,text,text,integer,text,text,text,text,text,uuid,text)",
    ):
        presence.append(
            bool(
                connection.scalar(
                    sa.text("SELECT to_regprocedure(:signature) IS NOT NULL"),
                    {"signature": signature},
                )
            )
        )
    for trigger_name, table_name in (
        ("api_invocations_immutable", "api_invocations"),
        ("api_invocation_results_immutable", "api_invocation_results"),
        ("api_invocation_exact_result", "api_invocations"),
    ):
        presence.append(
            bool(
                connection.scalar(
                    sa.text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_trigger AS trigger
                            JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
                            JOIN pg_namespace AS namespace
                              ON namespace.oid = relation.relnamespace
                            WHERE namespace.nspname = 'sharing'
                              AND relation.relname = :table_name
                              AND trigger.tgname = :trigger_name
                              AND NOT trigger.tgisinternal
                        )
                        """
                    ),
                    {"trigger_name": trigger_name, "table_name": table_name},
                )
            )
        )
    if not any(presence):
        return False
    if not all(presence):
        raise RuntimeError("Partial atomic Sharing canonical bridge detected.")
    return True


def _assert_phase6b_privileges() -> None:
    privileges_ok = op.get_bind().scalar(
        sa.text(
            """
            WITH protected_tables AS (
                SELECT class.oid, class.relowner
                FROM pg_class AS class
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'sharing'
                  AND class.relname IN (
                      'api_invocations',
                      'api_invocation_results',
                      'api_invocation_monthly_usage'
                  )
            ),
            protected_functions AS (
                SELECT procedure.oid, procedure.proowner,
                       procedure.oid IN (
                           to_regprocedure(
                               'sharing.prepare_api_invocation_v2('
                               'uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,'
                               'text,text,text,integer,text,text,text)'
                           ),
                           to_regprocedure(
                               'sharing.complete_api_invocation_v2('
                               'uuid,uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,'
                               'text,text,text,text,integer,text,text,text,text,text,uuid,text)'
                           )
                       ) AS app_execute
                FROM pg_proc AS procedure
                WHERE procedure.oid IN (
                    to_regprocedure(
                        'sharing.prepare_api_invocation_v2('
                        'uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,'
                        'text,text,text,integer,text,text,text)'
                    ),
                    to_regprocedure(
                        'sharing.complete_api_invocation_v2('
                        'uuid,uuid,uuid,uuid,text,text,text,text,uuid,uuid,uuid,uuid,'
                        'text,text,text,text,integer,text,text,text,text,text,uuid,text)'
                    ),
                    to_regprocedure('sharing.reject_invocation_evidence_mutation()'),
                    to_regprocedure('sharing.require_atomic_invocation_result()')
                )
            ),
            app_role AS (
                SELECT
                    oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                    rolreplication, rolbypassrls
                FROM pg_roles
                WHERE rolname = 'datariver_app'
            ),
            migration_role AS (
                SELECT to_regrole(current_user)::oid AS oid
            )
            SELECT
                (SELECT count(*) = 3 FROM protected_tables)
                AND (SELECT count(*) = 4 FROM protected_functions)
                AND (
                    SELECT count(*) = 1
                       AND bool_and(
                           rolcanlogin
                           AND NOT rolsuper
                           AND NOT rolcreatedb
                           AND NOT rolcreaterole
                           AND NOT rolreplication
                           AND NOT rolbypassrls
                       )
                    FROM app_role
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM protected_tables AS table_state
                    CROSS JOIN migration_role
                    WHERE table_state.relowner <> migration_role.oid
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM protected_functions AS function_state
                    CROSS JOIN migration_role
                    WHERE function_state.proowner <> migration_role.oid
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM app_role
                    CROSS JOIN pg_roles AS candidate
                    WHERE candidate.oid <> app_role.oid
                      AND pg_has_role(app_role.oid, candidate.oid, 'MEMBER')
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM app_role
                    CROSS JOIN pg_roles AS candidate
                    WHERE candidate.oid <> app_role.oid
                      AND NOT candidate.rolsuper
                      AND candidate.rolname NOT LIKE 'pg\\_%' ESCAPE '\\'
                      AND pg_has_role(candidate.oid, app_role.oid, 'MEMBER')
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM protected_tables AS table_state
                    CROSS JOIN pg_roles AS role_state
                    WHERE NOT role_state.rolsuper
                      AND role_state.rolname NOT LIKE 'pg\\_%' ESCAPE '\\'
                      AND role_state.oid <> table_state.relowner
                      AND has_table_privilege(
                          role_state.oid,
                          table_state.oid,
                          'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                      )
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM protected_functions AS function_state
                    CROSS JOIN pg_roles AS role_state
                    CROSS JOIN app_role
                    WHERE NOT role_state.rolsuper
                      AND role_state.rolname NOT LIKE 'pg\\_%' ESCAPE '\\'
                      AND role_state.oid <> function_state.proowner
                      AND (
                          (
                              function_state.app_execute
                              AND role_state.oid <> app_role.oid
                              AND has_function_privilege(
                                  role_state.oid, function_state.oid, 'EXECUTE'
                              )
                          )
                          OR (
                              NOT function_state.app_execute
                              AND has_function_privilege(
                                  role_state.oid, function_state.oid, 'EXECUTE'
                              )
                          )
                      )
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM protected_functions AS function_state
                    CROSS JOIN app_role
                    WHERE function_state.proowner = app_role.oid
                       OR has_function_privilege(
                           app_role.oid, function_state.oid, 'EXECUTE'
                       ) IS DISTINCT FROM function_state.app_execute
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM protected_functions AS function_state
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(
                            (SELECT procedure.proacl
                             FROM pg_proc AS procedure
                             WHERE procedure.oid = function_state.oid),
                            acldefault('f', function_state.proowner)
                        )
                    ) AS privilege
                    CROSS JOIN app_role
                    WHERE privilege.privilege_type = 'EXECUTE'
                      AND privilege.grantee NOT IN (
                          function_state.proowner,
                          CASE
                              WHEN function_state.app_execute THEN app_role.oid
                              ELSE function_state.proowner
                          END
                      )
                )
            """
        )
    )
    if not bool(privileges_ok):
        raise RuntimeError("Atomic Sharing least-privilege grants are incomplete.")


def _assert_phase6b_contract() -> None:
    connection = op.get_bind()
    tables = sorted({table for table, _column in _PHASE6B_COLUMN_CONTRACT})
    column_rows = list(
        connection.execute(
            sa.text(
                """
            SELECT
                class.relname,
                attribute.attname,
                format_type(attribute.atttypid, attribute.atttypmod),
                attribute.attnotnull,
                pg_get_expr(default_value.adbin, default_value.adrelid)
            FROM pg_attribute AS attribute
            JOIN pg_class AS class ON class.oid = attribute.attrelid
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            LEFT JOIN pg_attrdef AS default_value
              ON default_value.adrelid = attribute.attrelid
             AND default_value.adnum = attribute.attnum
            WHERE namespace.nspname = 'sharing'
              AND class.relname = ANY(CAST(:tables AS text[]))
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """
            ),
            {"tables": tables},
        )
    )
    actual_columns = {
        (str(row[0]), str(row[1])): (str(row[2]), bool(row[3]), row[4])
        for row in column_rows
        if (str(row[0]), str(row[1])) in _PHASE6B_COLUMN_CONTRACT
    }
    expected_columns = {
        key: (data_type, nullable, None)
        for key, (data_type, nullable) in _PHASE6B_COLUMN_CONTRACT.items()
    }
    if actual_columns != expected_columns:
        raise RuntimeError("Malformed atomic Sharing column contract.")
    for table in ("api_invocation_results", "api_invocation_monthly_usage"):
        if {str(row[1]) for row in column_rows if str(row[0]) == table} != {
            column for (table_name, column) in _PHASE6B_COLUMN_CONTRACT if table_name == table
        }:
            raise RuntimeError(f"Malformed atomic Sharing table shape: {table}")

    constraint_rows = connection.execute(
        sa.text(
            """
            SELECT
                class.relname,
                constraint_state.conname,
                md5(
                    regexp_replace(
                        pg_get_constraintdef(constraint_state.oid, true),
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                )
            FROM pg_constraint AS constraint_state
            JOIN pg_class AS class ON class.oid = constraint_state.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'sharing'
              AND class.relname = ANY(CAST(:tables AS text[]))
              AND constraint_state.conname = ANY(CAST(:constraints AS text[]))
            """
        ),
        {
            "tables": tables,
            "constraints": [
                constraint for _table, constraint in _PHASE6B_CONSTRAINT_DEFINITION_MD5
            ],
        },
    )
    actual_constraints = {(str(row[0]), str(row[1])): str(row[2]) for row in constraint_rows}
    if actual_constraints != _PHASE6B_CONSTRAINT_DEFINITION_MD5:
        raise RuntimeError("Malformed atomic Sharing constraint contract.")

    index_rows = connection.execute(
        sa.text(
            """
            SELECT
                indexname,
                md5(regexp_replace(indexdef, '[[:space:]]+', ' ', 'g'))
            FROM pg_indexes
            WHERE schemaname = 'sharing'
              AND indexname = ANY(CAST(:indexes AS text[]))
            """
        ),
        {"indexes": list(_PHASE6B_INDEX_DEFINITION_MD5)},
    )
    actual_indexes = {str(row[0]): str(row[1]) for row in index_rows}
    if actual_indexes != _PHASE6B_INDEX_DEFINITION_MD5:
        raise RuntimeError("Malformed atomic Sharing index contract.")

    rls_rows = connection.execute(
        sa.text(
            """
            SELECT class.relname, class.relrowsecurity, class.relforcerowsecurity
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'sharing'
              AND class.relname = ANY(CAST(:tables AS text[]))
            """
        ),
        {
            "tables": [
                "api_invocations",
                "api_invocation_results",
                "api_invocation_monthly_usage",
            ]
        },
    )
    if {(str(row[0]), bool(row[1]), bool(row[2])) for row in rls_rows} != {
        ("api_invocations", True, True),
        ("api_invocation_results", True, True),
        ("api_invocation_monthly_usage", True, True),
    }:
        raise RuntimeError("Atomic Sharing evidence tables must use FORCE RLS.")
    policy_rows = connection.execute(
        sa.text(
            """
            SELECT
                tablename,
                policyname,
                permissive,
                cmd,
                roles::text,
                md5(COALESCE(qual, '') || '|' || COALESCE(with_check, ''))
            FROM pg_policies
            WHERE schemaname = 'sharing'
              AND tablename = ANY(CAST(:tables AS text[]))
            """
        ),
        {
            "tables": [
                "api_invocations",
                "api_invocation_results",
                "api_invocation_monthly_usage",
            ]
        },
    )
    expected_policy = (
        "workspace_isolation",
        "PERMISSIVE",
        "ALL",
        "{public}",
        "45817745f8a8e0c90f7e7657e41bdd13",
    )
    if {(str(row[0]), *(str(value) for value in row[1:])) for row in policy_rows} != {
        (table, *expected_policy)
        for table in (
            "api_invocations",
            "api_invocation_results",
            "api_invocation_monthly_usage",
        )
    }:
        raise RuntimeError("Malformed atomic Sharing RLS policy contract.")

    trigger_rows = connection.execute(
        sa.text(
            """
            SELECT
                class.relname,
                trigger_state.tgname,
                trigger_state.tgenabled::text,
                trigger_state.tgdeferrable,
                trigger_state.tginitdeferred,
                md5(
                    regexp_replace(
                        pg_get_triggerdef(trigger_state.oid, true),
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                )
            FROM pg_trigger AS trigger_state
            JOIN pg_class AS class ON class.oid = trigger_state.tgrelid
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'sharing'
              AND NOT trigger_state.tgisinternal
              AND trigger_state.tgname = ANY(CAST(:triggers AS text[]))
            """
        ),
        {"triggers": [trigger for _table, trigger in _PHASE6B_TRIGGER_DEFINITION]},
    )
    actual_triggers = {
        (str(row[0]), str(row[1])): (
            str(row[2]),
            bool(row[3]),
            bool(row[4]),
            str(row[5]),
        )
        for row in trigger_rows
    }
    if actual_triggers != _PHASE6B_TRIGGER_DEFINITION:
        raise RuntimeError("Malformed atomic Sharing trigger contract.")

    function_contract = {
        (
            "sharing.prepare_api_invocation_v2(uuid,uuid,uuid,text,text,text,text,"
            "uuid,uuid,uuid,uuid,text,text,text,integer,text,text,text)"
        ): ({"search_path=pg_catalog, sharing", "TimeZone=UTC"}, True),
        (
            "sharing.complete_api_invocation_v2(uuid,uuid,uuid,uuid,text,text,text,text,"
            "uuid,uuid,uuid,uuid,text,text,text,text,integer,text,text,text,text,text,uuid,text)"
        ): (
            {"search_path=pg_catalog, sharing, iam, knowledge, retention", "TimeZone=UTC"},
            True,
        ),
        "sharing.reject_invocation_evidence_mutation()": (
            {"search_path=pg_catalog, sharing"},
            False,
        ),
        "sharing.require_atomic_invocation_result()": (
            {"search_path=pg_catalog, sharing"},
            False,
        ),
    }
    for signature, (expected_settings, app_execute) in function_contract.items():
        function_row = connection.execute(
            sa.text(
                """
                SELECT
                    procedure.prosecdef,
                    procedure.proconfig,
                    has_function_privilege(
                        'datariver_app',
                        procedure.oid,
                        'EXECUTE'
                    ),
                    EXISTS (
                        SELECT 1
                        FROM aclexplode(
                            COALESCE(
                                procedure.proacl,
                                acldefault('f', procedure.proowner)
                            )
                        ) AS privilege
                        WHERE privilege.grantee = 0
                          AND privilege.privilege_type = 'EXECUTE'
                    )
                FROM pg_proc AS procedure
                WHERE procedure.oid = to_regprocedure(:signature)
                """
            ),
            {"signature": signature},
        ).one_or_none()
        if (
            function_row is None
            or not bool(function_row[0])
            or set(function_row[1] or ()) != expected_settings
            or bool(function_row[2]) is not app_execute
            or bool(function_row[3])
        ):
            raise RuntimeError(f"Malformed atomic Sharing function contract: {signature}")


def upgrade() -> None:
    if _canonical_phase6b_contract_exists():
        _execute_blocks(_FUNCTION_SQL)
        _execute_blocks(_TRIGGER_FUNCTION_SQL)
        _execute_blocks(_GRANT_SQL)
        _assert_phase6b_privileges()
        _assert_phase6b_contract()
        return
    op.add_column(
        "consumer_grants",
        sa.Column(
            "contract_version",
            sa.String(length=32),
            server_default="LEGACY_CLIENT_V1",
            nullable=False,
        ),
        schema="sharing",
    )
    op.add_column(
        "consumer_grants",
        sa.Column("consumer_subject_id", sa.Uuid(), nullable=True),
        schema="sharing",
    )
    op.add_column(
        "consumer_grants",
        sa.Column("consumer_issuer", sa.String(length=500), nullable=True),
        schema="sharing",
    )
    op.create_foreign_key(
        "fk_consumer_grants_consumer_membership",
        "consumer_grants",
        "workspace_memberships",
        ["workspace_id", "consumer_subject_id"],
        ["workspace_id", "subject_id"],
        source_schema="sharing",
        referent_schema="iam",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_consumer_grants_contract_shape"),
        "consumer_grants",
        "(contract_version = 'LEGACY_CLIENT_V1' "
        "AND consumer_subject_id IS NULL AND consumer_issuer IS NULL) OR "
        "(contract_version = 'SUBJECT_CLIENT_V2' "
        "AND consumer_subject_id IS NOT NULL AND consumer_issuer IS NOT NULL "
        "AND length(consumer_issuer) BETWEEN 1 AND 500)",
        schema="sharing",
    )
    op.alter_column(
        "consumer_grants",
        "contract_version",
        server_default=None,
        schema="sharing",
    )
    op.drop_constraint(
        op.f("uq_consumer_grants_workspace_id_product_version_id_consumer_client_id"),
        "consumer_grants",
        schema="sharing",
        type_="unique",
    )
    op.create_index(
        "uq_consumer_grants_legacy_client",
        "consumer_grants",
        ["workspace_id", "product_version_id", "consumer_client_id"],
        unique=True,
        schema="sharing",
        postgresql_where=sa.text("contract_version = 'LEGACY_CLIENT_V1'"),
    )
    op.create_index(
        "uq_consumer_grants_v2_subject_client",
        "consumer_grants",
        [
            "workspace_id",
            "product_version_id",
            "consumer_subject_id",
            "consumer_client_id",
        ],
        unique=True,
        schema="sharing",
        postgresql_where=sa.text("contract_version = 'SUBJECT_CLIENT_V2'"),
    )
    op.drop_constraint(
        op.f("fk_consumer_grants_workspace_id_product_id_product_version_id_api_product_versions"),
        "consumer_grants",
        schema="sharing",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_consumer_grants_workspace_id_product_id_product_version_id_api_product_versions"),
        "consumer_grants",
        "api_product_versions",
        ["workspace_id", "product_id", "product_version_id"],
        ["workspace_id", "product_id", "id"],
        source_schema="sharing",
        referent_schema="sharing",
        ondelete="RESTRICT",
    )

    invocation_columns = (
        sa.Column(
            "evidence_kind",
            sa.String(length=32),
            server_default="LEGACY_USAGE_V1",
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("consumer_issuer", sa.String(length=500), nullable=True),
        sa.Column("consumer_client_id", sa.String(length=255), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("product_version_id", sa.Uuid(), nullable=True),
        sa.Column("graph_id", sa.Uuid(), nullable=True),
        sa.Column("release_id", sa.Uuid(), nullable=True),
        sa.Column("release_content_hash", sa.String(length=64), nullable=True),
        sa.Column("surface", sa.String(length=32), nullable=True),
        sa.Column("effective_classification", sa.Integer(), nullable=True),
        sa.Column("security_scope_hash", sa.String(length=64), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("result_type", sa.String(length=32), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("result_size_bytes", sa.Integer(), nullable=True),
        sa.Column("retention_data_class", sa.String(length=32), nullable=True),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=True),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_retention_policy_id", sa.Uuid(), nullable=True),
        sa.Column("audit_retention_policy_hash", sa.String(length=64), nullable=True),
        sa.Column("audit_retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in invocation_columns:
        op.add_column("api_invocations", column, schema="sharing")
    op.alter_column(
        "api_invocations",
        "evidence_kind",
        server_default=None,
        schema="sharing",
    )
    op.create_unique_constraint(
        op.f("uq_api_invocations_workspace_id_id"),
        "api_invocations",
        ["workspace_id", "id"],
        schema="sharing",
    )
    op.drop_constraint(
        op.f("fk_api_invocations_workspace_id_grant_id_consumer_grants"),
        "api_invocations",
        schema="sharing",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_api_invocations_workspace_id_grant_id_consumer_grants"),
        "api_invocations",
        "consumer_grants",
        ["workspace_id", "grant_id"],
        ["workspace_id", "id"],
        source_schema="sharing",
        referent_schema="sharing",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_api_invocations_actor_membership",
        "api_invocations",
        "workspace_memberships",
        ["workspace_id", "actor_id"],
        ["workspace_id", "subject_id"],
        source_schema="sharing",
        referent_schema="iam",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_api_invocations_product_version",
        "api_invocations",
        "api_product_versions",
        ["workspace_id", "product_id", "product_version_id"],
        ["workspace_id", "product_id", "id"],
        source_schema="sharing",
        referent_schema="sharing",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_api_invocations_single_unit"),
        "api_invocations",
        "units = 1",
        schema="sharing",
    )
    op.create_check_constraint(
        op.f("ck_api_invocations_evidence_shape"),
        "api_invocations",
        "(evidence_kind = 'LEGACY_USAGE_V1' "
        "AND actor_id IS NULL AND consumer_issuer IS NULL "
        "AND consumer_client_id IS NULL AND product_id IS NULL "
        "AND product_version_id IS NULL AND graph_id IS NULL AND release_id IS NULL "
        "AND release_content_hash IS NULL AND surface IS NULL "
        "AND effective_classification IS NULL AND security_scope_hash IS NULL "
        "AND request_hash IS NULL AND result_type IS NULL AND result_hash IS NULL "
        "AND result_size_bytes IS NULL AND retention_data_class IS NULL "
        "AND retention_policy_id IS NULL AND retention_policy_hash IS NULL "
        "AND retention_until IS NULL AND audit_retention_policy_id IS NULL "
        "AND audit_retention_policy_hash IS NULL AND audit_retention_until IS NULL "
        "AND completed_at IS NULL) OR "
        "(evidence_kind = 'ATOMIC_RESULT_V2' "
        "AND actor_id IS NOT NULL AND consumer_issuer IS NOT NULL "
        "AND consumer_client_id IS NOT NULL AND product_id IS NOT NULL "
        "AND product_version_id IS NOT NULL AND graph_id IS NOT NULL "
        "AND release_id IS NOT NULL AND release_content_hash IS NOT NULL "
        "AND surface IS NOT NULL AND effective_classification BETWEEN 0 AND 3 "
        "AND security_scope_hash IS NOT NULL AND request_hash IS NOT NULL "
        "AND result_type IS NOT NULL AND result_hash IS NOT NULL "
        "AND result_size_bytes BETWEEN 2 AND 1048576 "
        "AND retention_data_class IS NOT NULL AND retention_policy_id IS NOT NULL "
        "AND retention_policy_hash IS NOT NULL AND retention_until IS NOT NULL "
        "AND audit_retention_policy_id IS NOT NULL "
        "AND audit_retention_policy_hash IS NOT NULL "
        "AND audit_retention_until IS NOT NULL "
        "AND completed_at IS NOT NULL AND completed_at >= occurred_at "
        "AND retention_until > completed_at "
        "AND audit_retention_until > completed_at)",
        schema="sharing",
    )
    op.create_check_constraint(
        op.f("ck_api_invocations_v2_hashes"),
        "api_invocations",
        "evidence_kind = 'LEGACY_USAGE_V1' OR "
        "(invocation_key ~ '^[0-9a-f]{64}$' "
        "AND release_content_hash ~ '^[0-9a-f]{64}$' "
        "AND security_scope_hash ~ '^[0-9a-f]{64}$' "
        "AND request_hash ~ '^[0-9a-f]{64}$' "
        "AND result_hash ~ '^[0-9a-f]{64}$' "
        "AND retention_policy_hash ~ '^[0-9a-f]{64}$' "
        "AND audit_retention_policy_hash ~ '^[0-9a-f]{64}$')",
        schema="sharing",
    )
    op.create_check_constraint(
        op.f("ck_api_invocations_surface_result"),
        "api_invocations",
        "evidence_kind = 'LEGACY_USAGE_V1' OR "
        "((surface = 'SNAPSHOT' AND result_type = 'SNAPSHOT_V1' "
        "AND requested_scope = 'snapshot.read' "
        "AND retention_data_class = 'OBJECT_DATA') OR "
        "(surface = 'NEIGHBORS' AND result_type = 'NEIGHBORS_V1' "
        "AND requested_scope = 'neighbors.query' "
        "AND retention_data_class = 'OBJECT_DATA') OR "
        "(surface = 'CHAT' AND result_type = 'CHAT_LOCAL_V1' "
        "AND requested_scope = 'chat.query' "
        "AND retention_data_class = 'CHAT_CONTENT'))",
        schema="sharing",
    )

    op.create_table(
        "api_invocation_results",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_client_id", sa.String(length=255), nullable=False),
        sa.Column("result_type", sa.String(length=32), nullable=False),
        sa.Column("result_document", sa.Text(), nullable=False),
        sa.Column("result_size_bytes", sa.Integer(), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("retention_data_class", sa.String(length=32), nullable=False),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=False),
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(result_document::jsonb) = 'object'",
            name=op.f("ck_api_invocation_results_document_object"),
        ),
        sa.CheckConstraint(
            "result_size_bytes BETWEEN 2 AND 1048576 "
            "AND octet_length(convert_to(result_document, 'UTF8')) = result_size_bytes",
            name=op.f("ck_api_invocation_results_size_bound"),
        ),
        sa.CheckConstraint(
            "result_hash ~ '^[0-9a-f]{64}$' "
            "AND encode(sha256(convert_to(result_document, 'UTF8')), 'hex') = result_hash",
            name=op.f("ck_api_invocation_results_result_hash"),
        ),
        sa.CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name=op.f("ck_api_invocation_results_classification"),
        ),
        sa.CheckConstraint(
            "retention_data_class IN ('OBJECT_DATA', 'CHAT_CONTENT')",
            name=op.f("ck_api_invocation_results_retention_data_class"),
        ),
        sa.CheckConstraint(
            "retention_policy_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_api_invocation_results_policy_hash"),
        ),
        sa.CheckConstraint(
            "retention_until > created_at",
            name=op.f("ck_api_invocation_results_retention_window"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "invocation_id"],
            ["sharing.api_invocations.workspace_id", "sharing.api_invocations.id"],
            name="fk_api_invocation_results_invocation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "invocation_id",
            name=op.f("pk_api_invocation_results"),
        ),
        schema="sharing",
    )
    op.create_index(
        "ix_api_invocation_results_retention",
        "api_invocation_results",
        ["workspace_id", "retention_until", "invocation_id"],
        schema="sharing",
    )
    op.execute("ALTER TABLE sharing.api_invocation_results ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sharing.api_invocation_results FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON sharing.api_invocation_results "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )

    op.create_table(
        "api_invocation_monthly_usage",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("month_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "units > 0",
            name=op.f("ck_api_invocation_monthly_usage_positive_units"),
        ),
        sa.CheckConstraint(
            "month_start = date_trunc('month', month_start AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",
            name=op.f("ck_api_invocation_monthly_usage_utc_month_start"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "grant_id"],
            ["sharing.consumer_grants.workspace_id", "sharing.consumer_grants.id"],
            name=op.f("fk_api_invocation_monthly_usage_workspace_id_grant_id_consumer_grants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "grant_id",
            "month_start",
            name=op.f("pk_api_invocation_monthly_usage"),
        ),
        schema="sharing",
    )
    op.create_index(
        "ix_api_invocation_monthly_usage_grant_month",
        "api_invocation_monthly_usage",
        ["grant_id", "month_start"],
        schema="sharing",
    )
    op.execute("ALTER TABLE sharing.api_invocation_monthly_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sharing.api_invocation_monthly_usage FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON sharing.api_invocation_monthly_usage "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )
    op.execute(
        """
        INSERT INTO sharing.api_invocation_monthly_usage (
            workspace_id, grant_id, month_start, units, updated_at
        )
        SELECT
            workspace_id,
            grant_id,
            date_trunc('month', occurred_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC',
            sum(units)::integer,
            max(occurred_at)
        FROM sharing.api_invocations
        GROUP BY
            workspace_id,
            grant_id,
            date_trunc('month', occurred_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
        """
    )
    _execute_blocks(_FUNCTION_SQL)
    _execute_blocks(_TRIGGER_FUNCTION_SQL)
    _execute_blocks(_TRIGGER_SQL)
    _execute_blocks(_GRANT_SQL)
    _assert_phase6b_privileges()
    _assert_phase6b_contract()


def downgrade() -> None:
    connection = op.get_bind()
    evidence = connection.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM sharing.api_invocations
                WHERE evidence_kind = 'ATOMIC_RESULT_V2'
            )
            """
        )
    ).scalar_one()
    v2_grants = connection.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM sharing.consumer_grants
                WHERE contract_version = 'SUBJECT_CLIENT_V2'
            )
            """
        )
    ).scalar_one()
    if evidence or v2_grants:
        raise RuntimeError(
            "Downgrade refused while atomic Sharing evidence or subject-bound grants exist."
        )
    op.execute(
        "DROP FUNCTION sharing.complete_api_invocation_v2("
        "uuid, uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid, "
        "text, text, text, text, integer, text, text, text, text, text, uuid, "
        "text)"
    )
    op.execute(
        "DROP FUNCTION sharing.prepare_api_invocation_v2("
        "uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid, text, "
        "text, text, integer, text, text, text)"
    )
    op.execute("DROP FUNCTION sharing.require_atomic_invocation_result() CASCADE")
    op.execute("DROP FUNCTION sharing.reject_invocation_evidence_mutation() CASCADE")
    op.drop_table("api_invocation_monthly_usage", schema="sharing")
    op.drop_table("api_invocation_results", schema="sharing")
    for name in (
        "surface_result",
        "v2_hashes",
        "evidence_shape",
        "single_unit",
    ):
        op.drop_constraint(
            op.f(f"ck_api_invocations_{name}"),
            "api_invocations",
            schema="sharing",
            type_="check",
        )
    op.drop_constraint(
        "fk_api_invocations_product_version",
        "api_invocations",
        schema="sharing",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_api_invocations_actor_membership",
        "api_invocations",
        schema="sharing",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_api_invocations_workspace_id_grant_id_consumer_grants"),
        "api_invocations",
        schema="sharing",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_api_invocations_workspace_id_grant_id_consumer_grants"),
        "api_invocations",
        "consumer_grants",
        ["workspace_id", "grant_id"],
        ["workspace_id", "id"],
        source_schema="sharing",
        referent_schema="sharing",
        ondelete="CASCADE",
    )
    op.execute("GRANT SELECT, INSERT ON sharing.api_invocations TO datariver_app")
    op.drop_constraint(
        op.f("uq_api_invocations_workspace_id_id"),
        "api_invocations",
        schema="sharing",
        type_="unique",
    )
    for column in (
        "completed_at",
        "audit_retention_until",
        "audit_retention_policy_hash",
        "audit_retention_policy_id",
        "retention_until",
        "retention_policy_hash",
        "retention_policy_id",
        "retention_data_class",
        "result_size_bytes",
        "result_hash",
        "result_type",
        "request_hash",
        "security_scope_hash",
        "effective_classification",
        "surface",
        "release_content_hash",
        "release_id",
        "graph_id",
        "product_version_id",
        "product_id",
        "consumer_client_id",
        "consumer_issuer",
        "actor_id",
        "evidence_kind",
    ):
        op.drop_column("api_invocations", column, schema="sharing")
    op.drop_constraint(
        op.f("fk_consumer_grants_workspace_id_product_id_product_version_id_api_product_versions"),
        "consumer_grants",
        schema="sharing",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_consumer_grants_workspace_id_product_id_product_version_id_api_product_versions"),
        "consumer_grants",
        "api_product_versions",
        ["workspace_id", "product_id", "product_version_id"],
        ["workspace_id", "product_id", "id"],
        source_schema="sharing",
        referent_schema="sharing",
        ondelete="CASCADE",
    )
    op.drop_constraint(
        op.f("ck_consumer_grants_contract_shape"),
        "consumer_grants",
        schema="sharing",
        type_="check",
    )
    op.drop_index(
        "uq_consumer_grants_v2_subject_client",
        table_name="consumer_grants",
        schema="sharing",
    )
    op.drop_index(
        "uq_consumer_grants_legacy_client",
        table_name="consumer_grants",
        schema="sharing",
    )
    op.create_unique_constraint(
        op.f("uq_consumer_grants_workspace_id_product_version_id_consumer_client_id"),
        "consumer_grants",
        ["workspace_id", "product_version_id", "consumer_client_id"],
        schema="sharing",
    )
    op.drop_constraint(
        "fk_consumer_grants_consumer_membership",
        "consumer_grants",
        schema="sharing",
        type_="foreignkey",
    )
    op.drop_column("consumer_grants", "consumer_issuer", schema="sharing")
    op.drop_column("consumer_grants", "consumer_subject_id", schema="sharing")
    op.drop_column("consumer_grants", "contract_version", schema="sharing")
