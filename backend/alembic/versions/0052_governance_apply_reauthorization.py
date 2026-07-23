"""Add a claim-bound database reauthorization boundary for DataHub apply.

Revision ID: 0052
Revises: 0051
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# ruff: noqa: S608

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPLY_FUNCTION_SIGNATURE = (
    "governance.reauthorize_datahub_apply("
    "uuid,uuid,integer,text,uuid,integer,uuid,text,text,text,text,text,text,text,"
    "uuid,text,uuid,uuid,uuid,integer,text,text,text,uuid,uuid,integer,uuid,text)"
)
_PREPARATION_FUNCTION_SIGNATURE = (
    "integration.reauthorize_catalog_metadata_preparation("
    "uuid,uuid,uuid,uuid,integer,text,uuid[],boolean)"
)
_LEGACY_PREPARATION_FUNCTION_SIGNATURE = (
    "integration.reauthorize_catalog_metadata_preparation(uuid,uuid,uuid,uuid,integer,text,uuid[])"
)

_SENSITIVE_REAUTHORIZATION_TABLES = (
    "platform.workspaces",
    "platform.data_systems",
    "iam.subjects",
    "iam.workspace_memberships",
    "catalog.assets_projection",
    "catalog.vocabulary_entries",
    "authz.classification_access_policy_versions",
    "authz.classification_access_policy_rules",
    "authz.classification_access_generations",
    "authz.restricted_search_grants",
    "governance.registration_content_bindings",
    "governance.registration_metadata_content_bindings",
    "integration.object_manifests",
    "integration.upload_preparation_jobs",
    "integration.upload_preparation_receipts",
    "integration.upload_registration_candidates",
    "integration.catalog_metadata_rows",
    "integration.catalog_metadata_candidates",
    "integration.catalog_metadata_candidate_rows",
)


def _install_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.reauthorize_datahub_apply(
            p_workspace_id uuid,
            p_change_request_id uuid,
            p_change_request_version integer,
            p_request_type text,
            p_requester_id uuid,
            p_request_classification integer,
            p_item_id uuid,
            p_action text,
            p_target_type text,
            p_target_ref text,
            p_operation text,
            p_aspect_name text,
            p_before_hash text,
            p_after_hash text,
            p_target_asset_id uuid,
            p_target_asset_type text,
            p_target_system_id uuid,
            p_target_domain_id uuid,
            p_target_owner_department_id uuid,
            p_target_classification integer,
            p_target_lifecycle text,
            p_target_source_version text,
            p_target_binding_hash text,
            p_job_id uuid,
            p_attempt_id uuid,
            p_attempt_no integer,
            p_worker_subject_id uuid,
            p_lease_token_hash text
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            evaluated_at timestamptz := pg_catalog.clock_timestamp();
            allowed boolean := false;
            reason_code text := 'REAUTHORIZATION_INTERNAL_ERROR';
            membership_attributes jsonb;
            membership_job_function text;
            membership_clearance integer;
            current_request_type text;
            operator_required boolean := false;
            current_after_document jsonb;
            current_item_contract_hash text;
            current_routing_system_id uuid;
            current_asset_platform text;
            current_asset_database text;
            current_asset_schema text;
            current_asset_name text;
            active_policy_id uuid;
            active_policy_hash text;
            active_policy_version integer;
            authorization_generation bigint;
            target_search_mode text;
            policy_versions jsonb :=
                pg_catalog.jsonb_build_array('governance-apply-reauthorization-v1');
            evaluation_context jsonb;
        BEGIN
            <<evaluation>>
            BEGIN
                IF p_workspace_id IS NULL
                   OR p_change_request_id IS NULL
                   OR p_change_request_version IS NULL
                   OR p_request_type IS NULL
                   OR p_requester_id IS NULL
                   OR p_request_classification IS NULL
                   OR p_item_id IS NULL
                   OR p_action IS NULL
                   OR p_target_type IS NULL
                   OR p_target_ref IS NULL
                   OR p_operation IS NULL
                   OR p_aspect_name IS NULL
                   OR p_before_hash IS NULL
                   OR p_after_hash IS NULL
                   OR p_target_asset_id IS NULL
                   OR p_target_asset_type IS NULL
                   OR p_target_system_id IS NULL
                   OR p_target_classification IS NULL
                   OR p_target_lifecycle IS NULL
                   OR p_target_source_version IS NULL
                   OR p_target_binding_hash IS NULL
                   OR p_job_id IS NULL
                   OR p_attempt_id IS NULL
                   OR p_attempt_no IS NULL
                   OR p_worker_subject_id IS NULL
                   OR p_lease_token_hash IS NULL
                   OR p_change_request_version < 1
                   OR p_attempt_no < 1
                   OR p_request_classification NOT BETWEEN 0 AND 3
                   OR p_target_classification NOT BETWEEN 0 AND 3
                   OR p_action <> 'change.create'
                   OR p_target_type <> 'DATAHUB_ASPECT'
                   OR p_operation <> 'UPSERT'
                   OR p_aspect_name NOT IN (
                       'datasetProperties',
                       'schemaMetadata',
                       'domains',
                       'globalTags',
                       'glossaryTerms',
                       'ownership'
                   )
                   OR p_target_ref NOT LIKE 'urn:li:dataset:%'
                   OR p_target_asset_type NOT IN ('DATASET', 'TABLE', 'VIEW')
                   OR p_before_hash !~ '^[0-9a-f]{64}$'
                   OR p_after_hash !~ '^[0-9a-f]{64}$'
                   OR p_target_binding_hash !~ '^[0-9a-f]{64}$'
                   OR p_lease_token_hash !~ '^[0-9a-f]{64}$' THEN
                    reason_code := 'REAUTHORIZATION_ARGUMENT_INVALID';
                    EXIT evaluation;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM integration.jobs AS job
                    JOIN integration.job_attempts AS attempt
                      ON attempt.workspace_id = job.workspace_id
                     AND attempt.job_id = job.id
                    JOIN iam.workspace_memberships AS worker_membership
                      ON worker_membership.workspace_id = job.workspace_id
                     AND worker_membership.subject_id = job.lease_owner_id
                    JOIN iam.subjects AS worker_subject
                      ON worker_subject.id = worker_membership.subject_id
                    WHERE job.workspace_id = p_workspace_id
                      AND job.id = p_job_id
                      AND job.job_type = 'DATAHUB_CHANGE_APPLY'
                      AND job.causation_id = p_change_request_id
                      AND job.requested_by = p_requester_id
                      AND job.state = 'RUNNING'
                      AND job.attempts = p_attempt_no
                      AND job.lease_token_hash = p_lease_token_hash
                      AND job.lease_owner_id = p_worker_subject_id
                      AND job.lease_until > evaluated_at
                      AND attempt.id = p_attempt_id
                      AND attempt.attempt_no = p_attempt_no
                      AND attempt.state = 'RUNNING'
                      AND attempt.finished_at IS NULL
                      AND worker_membership.active IS TRUE
                      AND worker_membership.job_function = 'SERVICE_ACCOUNT'
                      AND (
                          worker_membership.access_expires_at IS NULL
                          OR worker_membership.access_expires_at > evaluated_at
                      )
                      AND pg_catalog.jsonb_typeof(
                          worker_membership.attributes -> 'groups'
                      ) = 'array'
                      AND (worker_membership.attributes -> 'groups')
                            ? 'service-accounts'
                      AND (worker_membership.attributes -> 'groups')
                            ? 'registration-workers'
                      AND worker_subject.active IS TRUE
                ) THEN
                    reason_code := 'CURRENT_WORKER_LEASE_INVALID';
                    EXIT evaluation;
                END IF;

                SELECT request.request_type,
                       item.after_document,
                       item.item_contract_hash,
                       item.routing_system_id
                INTO current_request_type,
                     current_after_document,
                     current_item_contract_hash,
                     current_routing_system_id
                FROM governance.change_requests AS request
                JOIN governance.change_request_items AS item
                  ON item.workspace_id = request.workspace_id
                 AND item.change_request_id = request.id
                WHERE request.workspace_id = p_workspace_id
                  AND request.id = p_change_request_id
                  AND request.version = p_change_request_version
                  AND request.state = 'APPLYING'
                  AND request.request_type = p_request_type
                  AND request.requester_id = p_requester_id
                  AND request.classification = p_request_classification
                  AND request.classification >= p_target_classification
                  AND item.id = p_item_id
                  AND item.target_type = p_target_type
                  AND item.target_ref = p_target_ref
                  AND item.operation = p_operation
                  AND item.aspect_name = p_aspect_name
                  AND item.before_hash = p_before_hash
                  AND item.after_hash = p_after_hash
                  AND item.target_asset_id = p_target_asset_id
                  AND item.target_asset_type = p_target_asset_type
                  AND item.target_system_id = p_target_system_id
                  AND item.target_domain_id IS NOT DISTINCT FROM p_target_domain_id
                  AND item.target_owner_department_id
                        IS NOT DISTINCT FROM p_target_owner_department_id
                  AND item.target_classification = p_target_classification
                  AND item.target_lifecycle = p_target_lifecycle
                  AND item.target_source_version = p_target_source_version
                  AND item.target_binding_hash = p_target_binding_hash
                  AND item.routing_system_id = p_target_system_id
                  AND (
                      SELECT pg_catalog.count(*)
                      FROM governance.change_request_items AS item_count
                      WHERE item_count.workspace_id = request.workspace_id
                        AND item_count.change_request_id = request.id
                  ) = 1;
                IF NOT FOUND THEN
                    reason_code := 'CURRENT_CLAIM_ITEM_MISMATCH';
                    EXIT evaluation;
                END IF;
                operator_required :=
                    current_request_type LIKE 'BULK\\_%' ESCAPE '\\';

                IF NOT EXISTS (
                    SELECT 1
                    FROM platform.workspaces AS workspace
                    WHERE workspace.id = p_workspace_id
                      AND workspace.status = 'ACTIVE'
                ) THEN
                    reason_code := 'WORKSPACE_INACTIVE';
                    EXIT evaluation;
                END IF;

                SELECT asset.platform,
                       asset.database_name,
                       asset.schema_name,
                       asset.name
                INTO current_asset_platform,
                     current_asset_database,
                     current_asset_schema,
                     current_asset_name
                FROM catalog.assets_projection AS asset
                WHERE asset.workspace_id = p_workspace_id
                  AND asset.id = p_target_asset_id
                  AND asset.deleted_at IS NULL
                  AND asset.lifecycle = 'ACTIVE'
                  AND asset.lifecycle = p_target_lifecycle
                  AND asset.external_urn = p_target_ref
                  AND asset.asset_type = p_target_asset_type
                  AND asset.asset_type IN ('DATASET', 'TABLE', 'VIEW')
                  AND asset.system_id = p_target_system_id
                  AND asset.domain_id IS NOT DISTINCT FROM p_target_domain_id
                  AND asset.owner_department_id
                        IS NOT DISTINCT FROM p_target_owner_department_id
                  AND asset.classification = p_target_classification
                  AND asset.source_version = p_target_source_version;
                IF NOT FOUND THEN
                    reason_code := 'CURRENT_TARGET_MISMATCH';
                    EXIT evaluation;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM platform.data_systems AS data_system
                    WHERE data_system.workspace_id = p_workspace_id
                      AND data_system.id = p_target_system_id
                      AND data_system.active IS TRUE
                ) THEN
                    reason_code := 'DATA_SYSTEM_INACTIVE';
                    EXIT evaluation;
                END IF;

                SELECT membership.attributes,
                       membership.job_function,
                       membership.clearance
                INTO membership_attributes,
                     membership_job_function,
                     membership_clearance
                FROM iam.workspace_memberships AS membership
                JOIN iam.subjects AS subject
                  ON subject.id = membership.subject_id
                WHERE membership.workspace_id = p_workspace_id
                  AND membership.subject_id = p_requester_id
                  AND membership.active IS TRUE
                  AND subject.active IS TRUE
                  AND (
                      membership.access_expires_at IS NULL
                      OR membership.access_expires_at > evaluated_at
                  );
                IF NOT FOUND
                   OR pg_catalog.jsonb_typeof(
                       membership_attributes -> 'groups'
                   ) <> 'array'
                   OR pg_catalog.jsonb_typeof(
                       membership_attributes -> 'allowed_actions'
                   ) <> 'array'
                   OR (
                       membership_attributes ? 'denied_actions'
                       AND pg_catalog.jsonb_typeof(
                           membership_attributes -> 'denied_actions'
                       ) <> 'array'
                   )
                   OR pg_catalog.jsonb_typeof(
                       membership_attributes -> 'allowed_system_ids'
                   ) <> 'array'
                   OR pg_catalog.jsonb_typeof(
                       membership_attributes -> 'allowed_domain_ids'
                   ) <> 'array' THEN
                    reason_code := 'CURRENT_MEMBERSHIP_INVALID';
                    EXIT evaluation;
                END IF;

                IF membership_job_function = 'SERVICE_ACCOUNT'
                   OR (membership_attributes -> 'groups') ? 'service-accounts' THEN
                    reason_code := 'HUMAN_ACTOR_REQUIRED';
                    EXIT evaluation;
                END IF;
                IF operator_required
                   AND NOT (
                       (membership_attributes -> 'groups') ? 'security-administrators'
                       OR (
                           membership_job_function = 'DATA_STEWARD'
                           AND (membership_attributes -> 'groups') ? 'data-stewards'
                       )
                   ) THEN
                    reason_code := 'REGISTRATION_OPERATOR_INELIGIBLE';
                    EXIT evaluation;
                END IF;

                IF NOT (membership_attributes -> 'allowed_actions') ? 'change.create'
                   OR (COALESCE(
                       membership_attributes -> 'denied_actions',
                       '[]'::jsonb
                   )) ? 'change.create'
                   OR membership_clearance < p_target_classification
                   OR NOT (membership_attributes -> 'allowed_system_ids')
                        ? p_target_system_id::text
                   OR (
                       p_target_domain_id IS NOT NULL
                       AND NOT (membership_attributes -> 'allowed_domain_ids')
                            ? p_target_domain_id::text
                   ) THEN
                    reason_code := 'CURRENT_ACTION_SCOPE_DENIED';
                    EXIT evaluation;
                END IF;

                SELECT policy.id,
                       policy.payload_hash,
                       policy.version,
                       generation.generation,
                       rule.search_mode
                INTO active_policy_id,
                     active_policy_hash,
                     active_policy_version,
                     authorization_generation,
                     target_search_mode
                FROM authz.classification_access_policy_versions AS policy
                JOIN authz.classification_access_generations AS generation
                  ON generation.workspace_id = policy.workspace_id
                JOIN authz.classification_access_policy_rules AS rule
                  ON rule.workspace_id = policy.workspace_id
                 AND rule.policy_id = policy.id
                 AND rule.policy_hash = policy.payload_hash
                 AND rule.classification = p_target_classification
                WHERE policy.workspace_id = p_workspace_id
                  AND policy.state = 'ACTIVE'
                  AND (
                      SELECT pg_catalog.count(DISTINCT all_rules.classification)
                      FROM authz.classification_access_policy_rules AS all_rules
                      WHERE all_rules.workspace_id = policy.workspace_id
                        AND all_rules.policy_id = policy.id
                        AND all_rules.policy_hash = policy.payload_hash
                  ) = 4;
                IF NOT FOUND THEN
                    reason_code := 'CLASSIFICATION_POLICY_UNAVAILABLE';
                    EXIT evaluation;
                END IF;

                policy_versions := policy_versions || pg_catalog.jsonb_build_array(
                    'classification-access:'
                    || active_policy_id::text
                    || ':'
                    || active_policy_version::text
                    || ':'
                    || active_policy_hash
                );

                IF p_target_classification < 3 AND target_search_mode <> 'ABAC' THEN
                    reason_code := 'CLASSIFICATION_POLICY_DENIED';
                    EXIT evaluation;
                END IF;
                IF p_target_classification = 3 THEN
                    IF target_search_mode <> 'EXPLICIT_GRANT_ONLY' THEN
                        reason_code := 'CLASSIFICATION_POLICY_DENIED';
                        EXIT evaluation;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1
                        FROM authz.restricted_search_grants AS restricted_grant
                        WHERE restricted_grant.workspace_id = p_workspace_id
                          AND restricted_grant.subject_id = p_requester_id
                          AND restricted_grant.classification_policy_id =
                                active_policy_id
                          AND restricted_grant.classification_policy_hash =
                                active_policy_hash
                          AND restricted_grant.state = 'ACTIVE'
                          AND restricted_grant.valid_from <= evaluated_at
                          AND restricted_grant.expires_at > evaluated_at
                          AND (
                              (
                                  restricted_grant.scope = 'RESOURCE'
                                  AND restricted_grant.scope_id = p_target_asset_id
                              )
                              OR (
                                  restricted_grant.scope = 'SYSTEM'
                                  AND restricted_grant.scope_id =
                                        p_target_system_id
                              )
                              OR (
                                  restricted_grant.scope = 'DOMAIN'
                                  AND p_target_domain_id IS NOT NULL
                                  AND restricted_grant.scope_id =
                                        p_target_domain_id
                              )
                          )
                    ) THEN
                        reason_code := 'RESTRICTED_GRANT_REQUIRED';
                        EXIT evaluation;
                    END IF;
                END IF;

                IF current_request_type = 'BULK_DATASET_DESCRIPTION' THEN
                    IF p_aspect_name <> 'datasetProperties'
                       OR NOT EXISTS (
                           SELECT 1
                           FROM governance.registration_content_bindings AS binding
                           JOIN integration.upload_registration_candidates AS candidate
                             ON candidate.workspace_id = binding.workspace_id
                            AND candidate.id = binding.candidate_id
                            AND candidate.candidate_hash = binding.candidate_hash
                           JOIN integration.upload_preparation_receipts AS receipt
                             ON receipt.workspace_id = candidate.workspace_id
                            AND receipt.id = candidate.receipt_id
                           JOIN integration.upload_preparation_jobs AS preparation
                             ON preparation.workspace_id = receipt.workspace_id
                            AND preparation.id = receipt.preparation_job_id
                            AND preparation.upload_id = receipt.upload_id
                            AND preparation.source_manifest_version =
                                receipt.manifest_version
                            AND preparation.source_sha256 = receipt.source_sha256
                            AND preparation.content_profile = receipt.content_profile
                            AND preparation.configuration_hash =
                                receipt.configuration_hash
                           JOIN integration.object_manifests AS manifest
                             ON manifest.workspace_id = preparation.workspace_id
                            AND manifest.id = preparation.upload_id
                           WHERE binding.workspace_id = p_workspace_id
                             AND binding.change_request_id = p_change_request_id
                             AND binding.change_item_id = p_item_id
                             AND binding.created_by = p_requester_id
                             AND candidate.target_asset_id = p_target_asset_id
                             AND candidate.candidate_kind =
                                'DATASET_DESCRIPTION_UPDATE'
                             AND candidate.evidence_version =
                                'DATASET_DESCRIPTION_CANDIDATE_V2'
                             AND candidate.proposed_description
                                IS NOT DISTINCT FROM
                                    current_after_document ->> 'description'
                             AND candidate.submitted_platform
                                IS NOT DISTINCT FROM current_asset_platform
                             AND candidate.submitted_database_name
                                IS NOT DISTINCT FROM current_asset_database
                             AND candidate.submitted_schema_name
                                IS NOT DISTINCT FROM current_asset_schema
                             AND candidate.submitted_table_name
                                IS NOT DISTINCT FROM current_asset_name
                             AND receipt.content_profile IN (
                                 'DATASET_DESCRIPTION_CSV_V1',
                                 'DATASET_DESCRIPTION_XLSX_V1'
                             )
                             AND receipt.rejected_count = 0
                             AND receipt.item_count > 0
                             AND preparation.state = 'READY'
                             AND manifest.state = 'ACCEPTED'
                             AND manifest.version = receipt.manifest_version
                             AND manifest.content_profile = receipt.content_profile
                             AND manifest.actual_sha256 = receipt.source_sha256
                       ) THEN
                        reason_code := 'TYPED_V2_BINDING_INVALID';
                        EXIT evaluation;
                    END IF;
                ELSIF current_request_type = 'BULK_CATALOG_METADATA' THEN
                    IF current_item_contract_hash IS NULL
                       OR NOT EXISTS (
                           SELECT 1
                           FROM governance.registration_metadata_content_bindings AS binding
                           JOIN integration.catalog_metadata_candidates AS candidate
                             ON candidate.workspace_id = binding.workspace_id
                            AND candidate.id = binding.candidate_id
                            AND candidate.content_profile = binding.content_profile
                            AND candidate.candidate_kind = binding.candidate_kind
                            AND candidate.aspect_name = binding.aspect_name
                            AND candidate.candidate_hash = binding.candidate_hash
                           JOIN integration.upload_preparation_receipts AS receipt
                             ON receipt.workspace_id = candidate.workspace_id
                            AND receipt.id = candidate.receipt_id
                            AND receipt.content_profile = candidate.content_profile
                           JOIN integration.upload_preparation_jobs AS preparation
                             ON preparation.workspace_id = receipt.workspace_id
                            AND preparation.id = receipt.preparation_job_id
                            AND preparation.upload_id = receipt.upload_id
                            AND preparation.source_manifest_version =
                                receipt.manifest_version
                            AND preparation.source_sha256 = receipt.source_sha256
                            AND preparation.content_profile = receipt.content_profile
                            AND preparation.configuration_hash =
                                receipt.configuration_hash
                           JOIN integration.object_manifests AS manifest
                             ON manifest.workspace_id = preparation.workspace_id
                            AND manifest.id = preparation.upload_id
                           WHERE binding.workspace_id = p_workspace_id
                             AND binding.change_request_id = p_change_request_id
                             AND binding.change_item_id = p_item_id
                             AND binding.created_by = p_requester_id
                             AND binding.aspect_name = p_aspect_name
                             AND binding.before_hash = p_before_hash
                             AND binding.after_hash = p_after_hash
                             AND binding.item_contract_hash =
                                current_item_contract_hash
                             AND candidate.evidence_version =
                                'CATALOG_METADATA_CANDIDATE_V3'
                             AND candidate.target_asset_id = p_target_asset_id
                             AND candidate.aspect_name = p_aspect_name
                             AND receipt.content_profile IN (
                                 'CATALOG_METADATA_ROWS_CSV_V1',
                                 'CATALOG_METADATA_ROWS_XLSX_V1'
                             )
                             AND receipt.rejected_count = 0
                             AND receipt.item_count > 0
                             AND preparation.state = 'READY'
                             AND manifest.state = 'ACCEPTED'
                             AND manifest.version = receipt.manifest_version
                             AND manifest.content_profile = receipt.content_profile
                             AND manifest.actual_sha256 = receipt.source_sha256
                             AND candidate.row_count = (
                                 SELECT pg_catalog.count(*)
                                 FROM integration.catalog_metadata_candidate_rows
                                    AS membership
                                 WHERE membership.workspace_id = candidate.workspace_id
                                   AND membership.receipt_id = candidate.receipt_id
                                   AND membership.candidate_id = candidate.id
                                   AND membership.candidate_hash =
                                        candidate.candidate_hash
                             )
                             AND NOT EXISTS (
                                 SELECT 1
                                 FROM integration.catalog_metadata_candidate_rows
                                    AS membership
                                 JOIN integration.catalog_metadata_rows AS source_row
                                   ON source_row.workspace_id =
                                        membership.workspace_id
                                  AND source_row.receipt_id = membership.receipt_id
                                  AND source_row.id = membership.row_id
                                  AND source_row.content_profile =
                                        membership.content_profile
                                  AND source_row.row_hash = membership.row_hash
                                 LEFT JOIN catalog.vocabulary_entries AS vocabulary
                                   ON vocabulary.workspace_id =
                                        source_row.workspace_id
                                  AND vocabulary.id =
                                        source_row.controlled_ref_id
                                  AND vocabulary.kind =
                                        source_row.controlled_kind
                                 WHERE membership.workspace_id =
                                        candidate.workspace_id
                                   AND membership.receipt_id =
                                        candidate.receipt_id
                                   AND membership.candidate_id = candidate.id
                                   AND (
                                       source_row.target_asset_id
                                            <> candidate.target_asset_id
                                       OR source_row.aspect_name
                                            <> candidate.aspect_name
                                       OR (
                                           source_row.controlled_ref_id IS NOT NULL
                                           AND (
                                               vocabulary.id IS NULL
                                               OR vocabulary.lifecycle <> 'ACTIVE'
                                           )
                                       )
                                   )
                             )
                       ) THEN
                        reason_code := 'TYPED_V3_BINDING_INVALID';
                        EXIT evaluation;
                    END IF;
                ELSIF current_request_type LIKE 'BULK\\_%' ESCAPE '\\' THEN
                    reason_code := 'UNKNOWN_BULK_CONTRACT';
                    EXIT evaluation;
                END IF;

                allowed := true;
                reason_code := 'POLICY_ALLOW';
            EXCEPTION
                WHEN OTHERS THEN
                    allowed := false;
                    reason_code := 'REAUTHORIZATION_INTERNAL_ERROR';
            END evaluation;

            evaluation_context := pg_catalog.jsonb_strip_nulls(
                pg_catalog.jsonb_build_object(
                    'kind', 'governance_apply_reauthorization',
                    'request_type', p_request_type,
                    'aspect_name', p_aspect_name,
                    'target_asset_id', p_target_asset_id,
                    'target_classification', p_target_classification,
                    'job_id', p_job_id,
                    'attempt_id', p_attempt_id,
                    'attempt_no', p_attempt_no,
                    'worker_subject_id', p_worker_subject_id,
                    'authorization_generation', authorization_generation,
                    'classification_policy_id', active_policy_id,
                    'classification_policy_hash', active_policy_hash
                )
            );
            INSERT INTO authz.policy_decisions (
                id,
                workspace_id,
                subject_id,
                resource_id,
                action,
                effect,
                reason_codes,
                policy_versions,
                evaluation_context,
                request_id,
                decided_at
            )
            VALUES (
                pg_catalog.gen_random_uuid(),
                p_workspace_id,
                p_requester_id,
                p_change_request_id,
                'change.create',
                CASE WHEN allowed THEN 'ALLOW' ELSE 'DENY' END,
                pg_catalog.jsonb_build_array(reason_code),
                policy_versions,
                evaluation_context,
                pg_catalog.left(
                    'apply-reauth:'
                    || p_change_request_id::text
                    || ':'
                    || p_item_id::text,
                    100
                ),
                evaluated_at
            );
            RETURN allowed;
        END
        $function$
        """
    )


def _install_preparation_function() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {_LEGACY_PREPARATION_FUNCTION_SIGNATURE}")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION integration.reauthorize_catalog_metadata_preparation(
            p_workspace_id uuid,
            p_preparation_id uuid,
            p_requested_by uuid,
            p_worker_subject_id uuid,
            p_attempt integer,
            p_lease_token_hash text,
            p_target_asset_ids uuid[],
            p_lock_for_publication boolean
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            evaluated_at timestamptz := pg_catalog.clock_timestamp();
            allowed boolean := false;
            reason_code text := 'REAUTHORIZATION_INTERNAL_ERROR';
            requester_attributes jsonb;
            requester_job_function text;
            requester_clearance integer;
            claim_started_at timestamptz;
            active_policy_id uuid;
            active_policy_hash text;
            active_policy_version integer;
            authorization_generation bigint;
            generation_updated_at timestamptz;
            locked_count integer;
            target_system_count integer;
            lock_denial_code text;
            target_count integer := COALESCE(
                pg_catalog.cardinality(p_target_asset_ids),
                0
            );
            policy_versions jsonb := pg_catalog.jsonb_build_array(
                'catalog-metadata-preparation-reauthorization-v1'
            );
            evaluation_context jsonb;
        BEGIN
            <<evaluation>>
            BEGIN
                IF p_workspace_id IS NULL
                   OR p_preparation_id IS NULL
                   OR p_requested_by IS NULL
                   OR p_worker_subject_id IS NULL
                   OR p_attempt IS NULL
                   OR p_lease_token_hash IS NULL
                   OR p_target_asset_ids IS NULL
                   OR p_lock_for_publication IS NULL
                   OR p_attempt < 1
                   OR p_lease_token_hash !~ '^[0-9a-f]{64}$'
                   OR target_count NOT BETWEEN 1 AND 10000
                   OR EXISTS (
                       SELECT 1
                       FROM pg_catalog.unnest(p_target_asset_ids) AS target(asset_id)
                       WHERE target.asset_id IS NULL
                   )
                   OR (
                       SELECT pg_catalog.count(DISTINCT target.asset_id)
                       FROM pg_catalog.unnest(p_target_asset_ids)
                            AS target(asset_id)
                   ) <> target_count THEN
                    reason_code := 'REAUTHORIZATION_ARGUMENT_INVALID';
                    EXIT evaluation;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM platform.workspaces AS workspace
                    WHERE workspace.id = p_workspace_id
                      AND workspace.status = 'ACTIVE'
                ) THEN
                    reason_code := 'WORKSPACE_INACTIVE';
                    EXIT evaluation;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM integration.upload_preparation_jobs AS preparation
                    JOIN integration.object_manifests AS manifest
                      ON manifest.workspace_id = preparation.workspace_id
                     AND manifest.id = preparation.upload_id
                    JOIN integration.registration_worker_call_receipts
                         AS call_receipt
                      ON call_receipt.workspace_id = preparation.workspace_id
                     AND call_receipt.work_id = preparation.id
                    JOIN iam.workspace_memberships AS worker_membership
                      ON worker_membership.workspace_id = preparation.workspace_id
                     AND worker_membership.subject_id = p_worker_subject_id
                    JOIN iam.subjects AS worker_subject
                      ON worker_subject.id = worker_membership.subject_id
                    WHERE preparation.workspace_id = p_workspace_id
                      AND preparation.id = p_preparation_id
                      AND preparation.requested_by = p_requested_by
                      AND preparation.content_profile IN (
                          'CATALOG_METADATA_ROWS_CSV_V1',
                          'CATALOG_METADATA_ROWS_XLSX_V1'
                      )
                      AND preparation.state = 'PREPARING'
                      AND preparation.attempts = p_attempt
                      AND preparation.lease_token IS NOT NULL
                      AND preparation.lease_until > evaluated_at
                      AND pg_catalog.encode(
                          pg_catalog.sha256(
                              pg_catalog.convert_to(
                                  preparation.lease_token::text,
                                  'UTF8'
                              )
                          ),
                          'hex'
                      ) = p_lease_token_hash
                      AND manifest.state = 'ACCEPTED'
                      AND manifest.version = preparation.source_manifest_version
                      AND manifest.content_profile = preparation.content_profile
                      AND manifest.actual_sha256 = preparation.source_sha256
                      AND manifest.owner_id = p_requested_by
                      AND call_receipt.operation =
                            'registration.bulk-preparation.execute-run.v1'
                      AND call_receipt.worker_subject_id = p_worker_subject_id
                      AND call_receipt.state = 'RUNNING'
                      AND call_receipt.work_kind = 'BULK'
                      AND call_receipt.claim_attempt = p_attempt
                      AND call_receipt.claim_token_hash = p_lease_token_hash
                      AND call_receipt.lease_expires_at > evaluated_at
                      AND call_receipt.processed IS NULL
                      AND call_receipt.result IS NULL
                      AND worker_membership.active IS TRUE
                      AND worker_membership.job_function = 'SERVICE_ACCOUNT'
                      AND (
                          worker_membership.access_expires_at IS NULL
                          OR worker_membership.access_expires_at > evaluated_at
                      )
                      AND pg_catalog.jsonb_typeof(
                          worker_membership.attributes -> 'groups'
                      ) = 'array'
                      AND (worker_membership.attributes -> 'groups')
                            ? 'service-accounts'
                      AND (worker_membership.attributes -> 'groups')
                            ? 'registration-workers'
                      AND worker_subject.active IS TRUE
                      AND NOT EXISTS (
                          SELECT 1
                          FROM integration.upload_preparation_receipts AS receipt
                          WHERE receipt.workspace_id = preparation.workspace_id
                            AND receipt.preparation_job_id = preparation.id
                      )
                ) THEN
                    reason_code := 'CURRENT_PREPARATION_LEASE_INVALID';
                    EXIT evaluation;
                END IF;

                SELECT call_receipt.updated_at
                INTO claim_started_at
                FROM integration.registration_worker_call_receipts AS call_receipt
                WHERE call_receipt.workspace_id = p_workspace_id
                  AND call_receipt.operation =
                        'registration.bulk-preparation.execute-run.v1'
                  AND call_receipt.worker_subject_id = p_worker_subject_id
                  AND call_receipt.state = 'RUNNING'
                  AND call_receipt.work_kind = 'BULK'
                  AND call_receipt.work_id = p_preparation_id
                  AND call_receipt.claim_attempt = p_attempt
                  AND call_receipt.claim_token_hash = p_lease_token_hash
                  AND call_receipt.lease_expires_at > evaluated_at
                  AND call_receipt.processed IS NULL
                  AND call_receipt.result IS NULL;
                IF NOT FOUND THEN
                    reason_code := 'CURRENT_PREPARATION_LEASE_INVALID';
                    EXIT evaluation;
                END IF;

                SELECT membership.attributes,
                       membership.job_function,
                       membership.clearance
                INTO requester_attributes,
                     requester_job_function,
                     requester_clearance
                FROM iam.workspace_memberships AS membership
                JOIN iam.subjects AS subject
                  ON subject.id = membership.subject_id
                WHERE membership.workspace_id = p_workspace_id
                  AND membership.subject_id = p_requested_by
                  AND membership.active IS TRUE
                  AND subject.active IS TRUE
                  AND (
                      membership.access_expires_at IS NULL
                      OR membership.access_expires_at > evaluated_at
                  );
                IF NOT FOUND
                   OR pg_catalog.jsonb_typeof(
                       requester_attributes -> 'groups'
                   ) <> 'array'
                   OR pg_catalog.jsonb_typeof(
                       requester_attributes -> 'allowed_actions'
                   ) <> 'array'
                   OR (
                       requester_attributes ? 'denied_actions'
                       AND pg_catalog.jsonb_typeof(
                           requester_attributes -> 'denied_actions'
                       ) <> 'array'
                   )
                   OR pg_catalog.jsonb_typeof(
                       requester_attributes -> 'allowed_system_ids'
                   ) <> 'array'
                   OR pg_catalog.jsonb_typeof(
                       requester_attributes -> 'allowed_domain_ids'
                   ) <> 'array' THEN
                    reason_code := 'CURRENT_REQUESTER_INVALID';
                    EXIT evaluation;
                END IF;

                IF requester_job_function = 'SERVICE_ACCOUNT'
                   OR (requester_attributes -> 'groups') ? 'service-accounts'
                   OR NOT (
                       (requester_attributes -> 'groups')
                            ? 'security-administrators'
                       OR (
                           requester_job_function = 'DATA_STEWARD'
                           AND (requester_attributes -> 'groups') ? 'data-stewards'
                       )
                   ) THEN
                    reason_code := 'REGISTRATION_OPERATOR_INELIGIBLE';
                    EXIT evaluation;
                END IF;

                IF NOT (requester_attributes -> 'allowed_actions')
                        ? 'change.create'
                   OR (
                       COALESCE(
                           requester_attributes -> 'denied_actions',
                           '[]'::jsonb
                       )
                   ) ? 'change.create' THEN
                    reason_code := 'CURRENT_ACTION_DENIED';
                    EXIT evaluation;
                END IF;

                IF (
                    SELECT pg_catalog.count(*)
                    FROM catalog.assets_projection AS asset
                    JOIN platform.data_systems AS data_system
                      ON data_system.workspace_id = asset.workspace_id
                     AND data_system.id = asset.system_id
                     AND data_system.active IS TRUE
                    WHERE asset.workspace_id = p_workspace_id
                      AND asset.id = ANY(p_target_asset_ids)
                      AND asset.deleted_at IS NULL
                      AND asset.lifecycle = 'ACTIVE'
                      AND asset.projection_source = 'DATAHUB'
                      AND asset.asset_type IN ('DATASET', 'TABLE', 'VIEW')
                      AND asset.external_urn LIKE 'urn:li:dataset:%'
                      AND asset.system_id IS NOT NULL
                ) <> target_count THEN
                    reason_code := 'CURRENT_TARGET_SET_INVALID';
                    EXIT evaluation;
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM catalog.assets_projection AS asset
                    WHERE asset.workspace_id = p_workspace_id
                      AND asset.id = ANY(p_target_asset_ids)
                      AND (
                          asset.classification > requester_clearance
                          OR NOT (
                              requester_attributes -> 'allowed_system_ids'
                          ) ? asset.system_id::text
                          OR (
                              asset.domain_id IS NOT NULL
                              AND NOT (
                                  requester_attributes -> 'allowed_domain_ids'
                              ) ? asset.domain_id::text
                          )
                      )
                ) THEN
                    reason_code := 'CURRENT_TARGET_SCOPE_DENIED';
                    EXIT evaluation;
                END IF;

                SELECT policy.id,
                       policy.payload_hash,
                       policy.version,
                       generation.generation,
                       generation.updated_at
                INTO active_policy_id,
                     active_policy_hash,
                     active_policy_version,
                     authorization_generation,
                     generation_updated_at
                FROM authz.classification_access_policy_versions AS policy
                JOIN authz.classification_access_generations AS generation
                  ON generation.workspace_id = policy.workspace_id
                WHERE policy.workspace_id = p_workspace_id
                  AND policy.state = 'ACTIVE'
                  AND (
                      SELECT pg_catalog.count(DISTINCT rule.classification)
                      FROM authz.classification_access_policy_rules AS rule
                      WHERE rule.workspace_id = policy.workspace_id
                        AND rule.policy_id = policy.id
                        AND rule.policy_hash = policy.payload_hash
                  ) = 4;
                IF NOT FOUND THEN
                    reason_code := 'CLASSIFICATION_POLICY_UNAVAILABLE';
                    EXIT evaluation;
                END IF;

                policy_versions := policy_versions || pg_catalog.jsonb_build_array(
                    'classification-access:'
                    || active_policy_id::text
                    || ':'
                    || active_policy_version::text
                    || ':'
                    || active_policy_hash
                );

                IF authorization_generation < 1
                   OR generation_updated_at > claim_started_at THEN
                    reason_code := 'AUTHORIZATION_GENERATION_DRIFT';
                    EXIT evaluation;
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM catalog.assets_projection AS asset
                    LEFT JOIN authz.classification_access_policy_rules AS rule
                      ON rule.workspace_id = asset.workspace_id
                     AND rule.policy_id = active_policy_id
                     AND rule.policy_hash = active_policy_hash
                     AND rule.classification = asset.classification
                    WHERE asset.workspace_id = p_workspace_id
                      AND asset.id = ANY(p_target_asset_ids)
                      AND (
                          rule.id IS NULL
                          OR (
                              asset.classification < 3
                              AND rule.search_mode <> 'ABAC'
                          )
                          OR (
                              asset.classification = 3
                              AND rule.search_mode <> 'EXPLICIT_GRANT_ONLY'
                          )
                      )
                ) THEN
                    reason_code := 'CLASSIFICATION_POLICY_DENIED';
                    EXIT evaluation;
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM catalog.assets_projection AS asset
                    WHERE asset.workspace_id = p_workspace_id
                      AND asset.id = ANY(p_target_asset_ids)
                      AND asset.classification = 3
                      AND NOT EXISTS (
                          SELECT 1
                          FROM authz.restricted_search_grants AS restricted_grant
                          WHERE restricted_grant.workspace_id = p_workspace_id
                            AND restricted_grant.subject_id = p_requested_by
                            AND restricted_grant.classification_policy_id =
                                  active_policy_id
                            AND restricted_grant.classification_policy_hash =
                                  active_policy_hash
                            AND restricted_grant.state = 'ACTIVE'
                            AND restricted_grant.valid_from <= evaluated_at
                            AND restricted_grant.expires_at > evaluated_at
                            AND (
                                (
                                    restricted_grant.scope = 'RESOURCE'
                                    AND restricted_grant.scope_id = asset.id
                                )
                                OR (
                                    restricted_grant.scope = 'SYSTEM'
                                    AND restricted_grant.scope_id = asset.system_id
                                )
                                OR (
                                    restricted_grant.scope = 'DOMAIN'
                                    AND asset.domain_id IS NOT NULL
                                    AND restricted_grant.scope_id = asset.domain_id
                                )
                            )
                      )
                ) THEN
                    reason_code := 'RESTRICTED_GRANT_REQUIRED';
                    EXIT evaluation;
                END IF;

                IF p_lock_for_publication THEN
                    lock_denial_code := NULL;
                    BEGIN
                        /*
                         * Publication callers acquire their bounded target
                         * locks before this final check. Keep the same order
                         * here: targets -> systems -> workspace -> subjects ->
                         * memberships -> policy -> generation -> rules ->
                         * applicable grants. FOR SHARE is sufficient to fence
                         * revocation/mutation and avoids upgrading the caller's
                         * existing target locks.
                         */
                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT asset.id
                            FROM catalog.assets_projection AS asset
                            WHERE asset.workspace_id = p_workspace_id
                              AND asset.id = ANY(p_target_asset_ids)
                            ORDER BY asset.id
                            FOR SHARE
                        ) AS locked_assets;
                        IF locked_count <> target_count OR (
                            SELECT pg_catalog.count(*)
                            FROM catalog.assets_projection AS asset
                            WHERE asset.workspace_id = p_workspace_id
                              AND asset.id = ANY(p_target_asset_ids)
                              AND asset.deleted_at IS NULL
                              AND asset.lifecycle = 'ACTIVE'
                              AND asset.projection_source = 'DATAHUB'
                              AND asset.asset_type IN (
                                  'DATASET',
                                  'TABLE',
                                  'VIEW'
                              )
                              AND asset.external_urn LIKE 'urn:li:dataset:%'
                              AND asset.system_id IS NOT NULL
                        ) <> target_count THEN
                            lock_denial_code := 'CURRENT_TARGET_SET_INVALID';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT pg_catalog.count(DISTINCT asset.system_id)
                        INTO target_system_count
                        FROM catalog.assets_projection AS asset
                        WHERE asset.workspace_id = p_workspace_id
                          AND asset.id = ANY(p_target_asset_ids);
                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT data_system.id
                            FROM platform.data_systems AS data_system
                            WHERE data_system.workspace_id = p_workspace_id
                              AND data_system.id IN (
                                  SELECT asset.system_id
                                  FROM catalog.assets_projection AS asset
                                  WHERE asset.workspace_id = p_workspace_id
                                    AND asset.id = ANY(p_target_asset_ids)
                              )
                            ORDER BY data_system.id
                            FOR SHARE
                        ) AS locked_systems;
                        IF locked_count <> target_system_count OR (
                            SELECT pg_catalog.count(*)
                            FROM platform.data_systems AS data_system
                            WHERE data_system.workspace_id = p_workspace_id
                              AND data_system.active IS TRUE
                              AND data_system.id IN (
                                  SELECT asset.system_id
                                  FROM catalog.assets_projection AS asset
                                  WHERE asset.workspace_id = p_workspace_id
                                    AND asset.id = ANY(p_target_asset_ids)
                              )
                        ) <> target_system_count THEN
                            lock_denial_code := 'CURRENT_TARGET_SET_INVALID';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT workspace.id
                            FROM platform.workspaces AS workspace
                            WHERE workspace.id = p_workspace_id
                            FOR SHARE
                        ) AS locked_workspace;
                        IF locked_count <> 1 OR NOT EXISTS (
                            SELECT 1
                            FROM platform.workspaces AS workspace
                            WHERE workspace.id = p_workspace_id
                              AND workspace.status = 'ACTIVE'
                        ) THEN
                            lock_denial_code := 'WORKSPACE_INACTIVE';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT subject.id
                            FROM iam.subjects AS subject
                            WHERE subject.id IN (
                                p_requested_by,
                                p_worker_subject_id
                            )
                            ORDER BY subject.id
                            FOR SHARE
                        ) AS locked_subjects;
                        IF locked_count <> 2 OR NOT EXISTS (
                            SELECT 1
                            FROM iam.subjects AS subject
                            WHERE subject.id = p_requested_by
                              AND subject.active IS TRUE
                        ) OR NOT EXISTS (
                            SELECT 1
                            FROM iam.subjects AS subject
                            WHERE subject.id = p_worker_subject_id
                              AND subject.active IS TRUE
                        ) THEN
                            lock_denial_code := 'CURRENT_REQUESTER_INVALID';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT membership.subject_id
                            FROM iam.workspace_memberships AS membership
                            WHERE membership.workspace_id = p_workspace_id
                              AND membership.subject_id IN (
                                  p_requested_by,
                                  p_worker_subject_id
                              )
                            ORDER BY membership.subject_id
                            FOR SHARE
                        ) AS locked_memberships;
                        IF locked_count <> 2 THEN
                            lock_denial_code := 'CURRENT_REQUESTER_INVALID';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT membership.attributes,
                               membership.job_function,
                               membership.clearance
                        INTO requester_attributes,
                             requester_job_function,
                             requester_clearance
                        FROM iam.workspace_memberships AS membership
                        WHERE membership.workspace_id = p_workspace_id
                          AND membership.subject_id = p_requested_by
                          AND membership.active IS TRUE
                          AND (
                              membership.access_expires_at IS NULL
                              OR membership.access_expires_at > evaluated_at
                          );
                        IF NOT FOUND
                           OR pg_catalog.jsonb_typeof(
                               requester_attributes -> 'groups'
                           ) <> 'array'
                           OR pg_catalog.jsonb_typeof(
                               requester_attributes -> 'allowed_actions'
                           ) <> 'array'
                           OR (
                               requester_attributes ? 'denied_actions'
                               AND pg_catalog.jsonb_typeof(
                                   requester_attributes -> 'denied_actions'
                               ) <> 'array'
                           )
                           OR pg_catalog.jsonb_typeof(
                               requester_attributes -> 'allowed_system_ids'
                           ) <> 'array'
                           OR pg_catalog.jsonb_typeof(
                               requester_attributes -> 'allowed_domain_ids'
                           ) <> 'array'
                           OR requester_job_function = 'SERVICE_ACCOUNT'
                           OR (requester_attributes -> 'groups')
                                ? 'service-accounts'
                           OR NOT (
                               (requester_attributes -> 'groups')
                                    ? 'security-administrators'
                               OR (
                                   requester_job_function = 'DATA_STEWARD'
                                   AND (requester_attributes -> 'groups')
                                        ? 'data-stewards'
                               )
                           ) THEN
                            lock_denial_code := 'CURRENT_REQUESTER_INVALID';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;
                        IF NOT (requester_attributes -> 'allowed_actions')
                                ? 'change.create'
                           OR (
                               COALESCE(
                                   requester_attributes -> 'denied_actions',
                                   '[]'::jsonb
                               )
                           ) ? 'change.create' THEN
                            lock_denial_code := 'CURRENT_ACTION_DENIED';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1
                            FROM iam.workspace_memberships AS membership
                            WHERE membership.workspace_id = p_workspace_id
                              AND membership.subject_id = p_worker_subject_id
                              AND membership.active IS TRUE
                              AND membership.job_function = 'SERVICE_ACCOUNT'
                              AND (
                                  membership.access_expires_at IS NULL
                                  OR membership.access_expires_at > evaluated_at
                              )
                              AND pg_catalog.jsonb_typeof(
                                  membership.attributes -> 'groups'
                              ) = 'array'
                              AND (membership.attributes -> 'groups')
                                    ? 'service-accounts'
                              AND (membership.attributes -> 'groups')
                                    ? 'registration-workers'
                        ) THEN
                            lock_denial_code :=
                                'CURRENT_PREPARATION_LEASE_INVALID';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT policy.id
                            FROM authz.classification_access_policy_versions
                                AS policy
                            WHERE policy.workspace_id = p_workspace_id
                              AND policy.id = active_policy_id
                            FOR SHARE
                        ) AS locked_policy;
                        IF locked_count <> 1 OR NOT EXISTS (
                            SELECT 1
                            FROM authz.classification_access_policy_versions
                                AS policy
                            WHERE policy.workspace_id = p_workspace_id
                              AND policy.id = active_policy_id
                              AND policy.payload_hash = active_policy_hash
                              AND policy.version = active_policy_version
                              AND policy.state = 'ACTIVE'
                        ) THEN
                            lock_denial_code :=
                                'CLASSIFICATION_POLICY_UNAVAILABLE';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT generation.workspace_id
                            FROM authz.classification_access_generations
                                AS generation
                            WHERE generation.workspace_id = p_workspace_id
                            FOR SHARE
                        ) AS locked_generation;
                        SELECT generation.generation,
                               generation.updated_at
                        INTO authorization_generation,
                             generation_updated_at
                        FROM authz.classification_access_generations
                            AS generation
                        WHERE generation.workspace_id = p_workspace_id;
                        IF locked_count <> 1
                           OR NOT FOUND
                           OR authorization_generation < 1
                           OR generation_updated_at > claim_started_at THEN
                            lock_denial_code :=
                                'AUTHORIZATION_GENERATION_DRIFT';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        SELECT pg_catalog.count(*)
                        INTO locked_count
                        FROM (
                            SELECT rule.classification, rule.id
                            FROM authz.classification_access_policy_rules
                                AS rule
                            WHERE rule.workspace_id = p_workspace_id
                              AND rule.policy_id = active_policy_id
                              AND rule.policy_hash = active_policy_hash
                            ORDER BY rule.classification, rule.id
                            FOR SHARE
                        ) AS locked_rules;
                        IF locked_count <> 4 OR (
                            SELECT pg_catalog.count(
                                DISTINCT rule.classification
                            )
                            FROM authz.classification_access_policy_rules
                                AS rule
                            WHERE rule.workspace_id = p_workspace_id
                              AND rule.policy_id = active_policy_id
                              AND rule.policy_hash = active_policy_hash
                              AND rule.classification BETWEEN 0 AND 3
                        ) <> 4 OR EXISTS (
                            SELECT 1
                            FROM catalog.assets_projection AS asset
                            LEFT JOIN
                                authz.classification_access_policy_rules AS rule
                              ON rule.workspace_id = asset.workspace_id
                             AND rule.policy_id = active_policy_id
                             AND rule.policy_hash = active_policy_hash
                             AND rule.classification = asset.classification
                            WHERE asset.workspace_id = p_workspace_id
                              AND asset.id = ANY(p_target_asset_ids)
                              AND (
                                  rule.id IS NULL
                                  OR (
                                      asset.classification < 3
                                      AND rule.search_mode <> 'ABAC'
                                  )
                                  OR (
                                      asset.classification = 3
                                      AND rule.search_mode <>
                                            'EXPLICIT_GRANT_ONLY'
                                  )
                              )
                        ) THEN
                            lock_denial_code :=
                                'CLASSIFICATION_POLICY_DENIED';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        IF EXISTS (
                            SELECT 1
                            FROM catalog.assets_projection AS asset
                            WHERE asset.workspace_id = p_workspace_id
                              AND asset.id = ANY(p_target_asset_ids)
                              AND (
                                  asset.classification > requester_clearance
                                  OR NOT (
                                      requester_attributes ->
                                        'allowed_system_ids'
                                  ) ? asset.system_id::text
                                  OR (
                                      asset.domain_id IS NOT NULL
                                      AND NOT (
                                          requester_attributes ->
                                            'allowed_domain_ids'
                                      ) ? asset.domain_id::text
                                  )
                              )
                        ) THEN
                            lock_denial_code := 'CURRENT_TARGET_SCOPE_DENIED';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;

                        PERFORM restricted_grant.id
                        FROM authz.restricted_search_grants
                            AS restricted_grant
                        WHERE restricted_grant.workspace_id = p_workspace_id
                          AND restricted_grant.subject_id = p_requested_by
                          AND restricted_grant.classification_policy_id =
                                active_policy_id
                          AND restricted_grant.classification_policy_hash =
                                active_policy_hash
                          AND restricted_grant.state = 'ACTIVE'
                          AND restricted_grant.valid_from <= evaluated_at
                          AND restricted_grant.expires_at > evaluated_at
                          AND EXISTS (
                              SELECT 1
                              FROM catalog.assets_projection AS asset
                              WHERE asset.workspace_id = p_workspace_id
                                AND asset.id = ANY(p_target_asset_ids)
                                AND asset.classification = 3
                                AND (
                                    (
                                        restricted_grant.scope = 'RESOURCE'
                                        AND restricted_grant.scope_id = asset.id
                                    )
                                    OR (
                                        restricted_grant.scope = 'SYSTEM'
                                        AND restricted_grant.scope_id =
                                            asset.system_id
                                    )
                                    OR (
                                        restricted_grant.scope = 'DOMAIN'
                                        AND asset.domain_id IS NOT NULL
                                        AND restricted_grant.scope_id =
                                            asset.domain_id
                                    )
                                )
                          )
                        ORDER BY restricted_grant.id
                        FOR SHARE;
                        IF EXISTS (
                            SELECT 1
                            FROM catalog.assets_projection AS asset
                            WHERE asset.workspace_id = p_workspace_id
                              AND asset.id = ANY(p_target_asset_ids)
                              AND asset.classification = 3
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM authz.restricted_search_grants
                                      AS restricted_grant
                                  WHERE restricted_grant.workspace_id =
                                        p_workspace_id
                                    AND restricted_grant.subject_id =
                                        p_requested_by
                                    AND
                                        restricted_grant
                                            .classification_policy_id =
                                        active_policy_id
                                    AND
                                        restricted_grant
                                            .classification_policy_hash =
                                        active_policy_hash
                                    AND restricted_grant.state = 'ACTIVE'
                                    AND restricted_grant.valid_from <=
                                        evaluated_at
                                    AND restricted_grant.expires_at >
                                        evaluated_at
                                    AND (
                                        (
                                            restricted_grant.scope =
                                                'RESOURCE'
                                            AND restricted_grant.scope_id =
                                                asset.id
                                        )
                                        OR (
                                            restricted_grant.scope = 'SYSTEM'
                                            AND restricted_grant.scope_id =
                                                asset.system_id
                                        )
                                        OR (
                                            restricted_grant.scope = 'DOMAIN'
                                            AND asset.domain_id IS NOT NULL
                                            AND restricted_grant.scope_id =
                                                asset.domain_id
                                        )
                                    )
                              )
                        ) THEN
                            lock_denial_code := 'RESTRICTED_GRANT_REQUIRED';
                            RAISE EXCEPTION USING
                                ERRCODE = 'DR001',
                                MESSAGE = lock_denial_code;
                        END IF;
                    EXCEPTION
                        WHEN SQLSTATE 'DR001' THEN
                            NULL;
                    END;
                    IF lock_denial_code IS NOT NULL THEN
                        reason_code := lock_denial_code;
                        EXIT evaluation;
                    END IF;
                END IF;

                allowed := true;
                reason_code := 'POLICY_ALLOW';
            EXCEPTION
                WHEN OTHERS THEN
                    allowed := false;
                    reason_code := 'REAUTHORIZATION_INTERNAL_ERROR';
            END evaluation;

            evaluation_context := pg_catalog.jsonb_build_object(
                'kind', 'catalog_metadata_preparation_reauthorization',
                'preparation_id', p_preparation_id,
                'attempt', p_attempt,
                'worker_subject_id', p_worker_subject_id,
                'target_count', target_count,
                'lock_for_publication', p_lock_for_publication,
                'authorization_generation', authorization_generation,
                'classification_policy_id', active_policy_id,
                'classification_policy_hash', active_policy_hash
            );
            INSERT INTO authz.policy_decisions (
                id,
                workspace_id,
                subject_id,
                resource_id,
                action,
                effect,
                reason_codes,
                policy_versions,
                evaluation_context,
                request_id,
                decided_at
            )
            VALUES (
                pg_catalog.gen_random_uuid(),
                p_workspace_id,
                p_requested_by,
                p_preparation_id,
                'registration.bulk.prepare.publish',
                CASE WHEN allowed THEN 'ALLOW' ELSE 'DENY' END,
                pg_catalog.jsonb_build_array(reason_code),
                policy_versions,
                evaluation_context,
                pg_catalog.left(
                    'catalog-prep-reauth:' || p_preparation_id::text,
                    100
                ),
                evaluated_at
            );
            RETURN allowed;
        END
        $function$
        """
    )


def _install_privileges() -> None:
    op.execute(f"REVOKE ALL ON FUNCTION {_APPLY_FUNCTION_SIGNATURE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {_PREPARATION_FUNCTION_SIGNATURE} FROM PUBLIC")
    for table in _SENSITIVE_REAUTHORIZATION_TABLES:
        op.execute(
            f"""
            DO $datariver$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_roles
                    WHERE rolname = 'datariver_governance'
                ) THEN
                    REVOKE SELECT ON {table} FROM datariver_governance;
                END IF;
            END
            $datariver$
            """
        )
    op.execute(
        f"""
        DO $datariver$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY[
                'datariver_app',
                'datariver_upload',
                'datariver_relay',
                'datariver_export',
                'datariver_retention_scheduler',
                'datariver_archive',
                'datariver_bootstrap'
            ]
            LOOP
                IF EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_roles
                    WHERE rolname = role_name
                ) THEN
                    EXECUTE pg_catalog.format(
                        'REVOKE ALL ON FUNCTION {_APPLY_FUNCTION_SIGNATURE} FROM %I',
                        role_name
                    );
                END IF;
            END LOOP;
            IF EXISTS (
                SELECT 1
                FROM pg_catalog.pg_roles
                WHERE rolname = 'datariver_governance'
            ) THEN
                GRANT EXECUTE ON FUNCTION {_APPLY_FUNCTION_SIGNATURE}
                    TO datariver_governance;
            END IF;
        END
        $datariver$
        """
    )
    op.execute(
        f"""
        DO $datariver$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY[
                'datariver_governance',
                'datariver_upload',
                'datariver_relay',
                'datariver_export',
                'datariver_retention_scheduler',
                'datariver_archive',
                'datariver_bootstrap'
            ]
            LOOP
                IF EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_roles
                    WHERE rolname = role_name
                ) THEN
                    EXECUTE pg_catalog.format(
                        'REVOKE ALL ON FUNCTION {_PREPARATION_FUNCTION_SIGNATURE} FROM %I',
                        role_name
                    );
                END IF;
            END LOOP;
            IF EXISTS (
                SELECT 1
                FROM pg_catalog.pg_roles
                WHERE rolname = 'datariver_app'
            ) THEN
                GRANT EXECUTE ON FUNCTION {_PREPARATION_FUNCTION_SIGNATURE}
                    TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def _assert_contract() -> None:
    tables = ", ".join(f"'{table}'" for table in _SENSITIVE_REAUTHORIZATION_TABLES)
    op.execute(
        f"""
        DO $datariver$
        DECLARE
            function_oid oid := '{_APPLY_FUNCTION_SIGNATURE}'::regprocedure;
            function_owner oid;
            governance_role_oid oid;
        BEGIN
            SELECT procedure.proowner
            INTO function_owner
            FROM pg_catalog.pg_proc AS procedure
            WHERE procedure.oid = function_oid
              AND procedure.prosecdef IS TRUE
              AND procedure.proconfig @> ARRAY['search_path=pg_catalog']::text[];
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'governance apply reauthorization function is not security hardened';
            END IF;

            SELECT role.oid
            INTO governance_role_oid
            FROM pg_catalog.pg_roles AS role
            WHERE role.rolname = 'datariver_governance';

            IF governance_role_oid IS NOT NULL
               AND (
                   function_owner = governance_role_oid
                   OR NOT pg_catalog.has_function_privilege(
                       'datariver_governance',
                       '{_APPLY_FUNCTION_SIGNATURE}',
                       'EXECUTE'
                   )
               ) THEN
                RAISE EXCEPTION
                    'governance apply reauthorization execute contract is invalid';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_catalog.aclexplode(
                    COALESCE(
                        (
                            SELECT procedure.proacl
                            FROM pg_catalog.pg_proc AS procedure
                            WHERE procedure.oid = function_oid
                        ),
                        pg_catalog.acldefault('f', function_owner)
                    )
                ) AS privilege
                WHERE privilege.privilege_type = 'EXECUTE'
                  AND (
                      privilege.grantee = 0
                      OR privilege.grantee NOT IN (
                          function_owner,
                          COALESCE(governance_role_oid, function_owner)
                      )
                  )
            ) THEN
                RAISE EXCEPTION
                    'governance apply reauthorization execute grant is overbroad';
            END IF;

            IF governance_role_oid IS NOT NULL AND EXISTS (
                SELECT 1
                FROM pg_catalog.unnest(ARRAY[{tables}]) AS relation_name
                WHERE pg_catalog.has_table_privilege(
                    'datariver_governance',
                    relation_name,
                    'SELECT'
                )
            ) THEN
                RAISE EXCEPTION
                    'governance worker has broad reauthorization table access';
            END IF;
        END
        $datariver$
        """
    )
    op.execute(
        f"""
        DO $datariver$
        DECLARE
            function_oid oid :=
                '{_PREPARATION_FUNCTION_SIGNATURE}'::regprocedure;
            function_owner oid;
            app_role_oid oid;
        BEGIN
            SELECT procedure.proowner
            INTO function_owner
            FROM pg_catalog.pg_proc AS procedure
            WHERE procedure.oid = function_oid
              AND procedure.prosecdef IS TRUE
              AND procedure.proconfig @> ARRAY['search_path=pg_catalog']::text[];
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'catalog metadata preparation reauthorization is not hardened';
            END IF;

            SELECT role.oid
            INTO app_role_oid
            FROM pg_catalog.pg_roles AS role
            WHERE role.rolname = 'datariver_app';

            IF app_role_oid IS NOT NULL
               AND (
                   function_owner = app_role_oid
                   OR NOT pg_catalog.has_function_privilege(
                       'datariver_app',
                       '{_PREPARATION_FUNCTION_SIGNATURE}',
                       'EXECUTE'
                   )
               ) THEN
                RAISE EXCEPTION
                    'catalog metadata preparation execute contract is invalid';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_catalog.aclexplode(
                    COALESCE(
                        (
                            SELECT procedure.proacl
                            FROM pg_catalog.pg_proc AS procedure
                            WHERE procedure.oid = function_oid
                        ),
                        pg_catalog.acldefault('f', function_owner)
                    )
                ) AS privilege
                WHERE privilege.privilege_type = 'EXECUTE'
                  AND (
                      privilege.grantee = 0
                      OR privilege.grantee NOT IN (
                          function_owner,
                          COALESCE(app_role_oid, function_owner)
                      )
                  )
            ) THEN
                RAISE EXCEPTION
                    'catalog metadata preparation execute grant is overbroad';
            END IF;
        END
        $datariver$
        """
    )


def upgrade() -> None:
    _install_function()
    _install_preparation_function()
    _install_privileges()
    _assert_contract()


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {_PREPARATION_FUNCTION_SIGNATURE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_LEGACY_PREPARATION_FUNCTION_SIGNATURE}")
    op.execute(f"REVOKE ALL ON FUNCTION {_APPLY_FUNCTION_SIGNATURE} FROM PUBLIC")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPLY_FUNCTION_SIGNATURE}")
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_catalog.pg_roles
                WHERE rolname = 'datariver_governance'
            ) THEN
                GRANT SELECT ON
                    catalog.vocabulary_entries,
                    integration.catalog_metadata_rows,
                    integration.catalog_metadata_candidates,
                    integration.catalog_metadata_candidate_rows,
                    governance.registration_metadata_content_bindings
                    TO datariver_governance;
            END IF;
        END
        $datariver$
        """
    )
