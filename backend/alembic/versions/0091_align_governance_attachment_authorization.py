"""Align CR attachment finalization with current profile and target authority.

Revision ID: 0091
Revises: 0090
Create Date: 2026-08-02
"""

# ruff: noqa: S608 -- SQL is rendered only from fixed server-owned policy constants.

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

from datariver.domain.capability_catalog import (
    CANONICAL_ADMIN_CAPABILITY_HASH,
    CAPABILITY_CATALOG_VERSION,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
)
from datariver.domain.profile_roles import (
    PROFILE_ROLE_BY_TIER,
    PROFILE_ROLE_POLICY_VERSION,
    ProfileRoleTier,
)

revision: str = "0091"
down_revision: str | Sequence[str] | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _actions(tier: ProfileRoleTier) -> str:
    return json.dumps(
        sorted(action.value for action in PROFILE_ROLE_BY_TIER[tier].allowed_actions),
        separators=(",", ":"),
    ).replace("'", "''")


_VIEWER_ACTIONS = _actions(ProfileRoleTier.VIEWER)
_ENGINEER_STEWARD_ACTIONS = _actions(ProfileRoleTier.ENGINEER_STEWARD)
_MANAGER_ACTIONS = _actions(ProfileRoleTier.MANAGER)
_ADMIN_ACTIONS = json.dumps(
    sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS),
    separators=(",", ":"),
).replace("'", "''")
_VIEWER_HASH = PROFILE_ROLE_BY_TIER[ProfileRoleTier.VIEWER].materialized_actions_hash
_ENGINEER_STEWARD_HASH = PROFILE_ROLE_BY_TIER[
    ProfileRoleTier.ENGINEER_STEWARD
].materialized_actions_hash
_MANAGER_HASH = PROFILE_ROLE_BY_TIER[ProfileRoleTier.MANAGER].materialized_actions_hash


FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION governance.finalize_attachment_upload_intent(
    p_workspace_id uuid,
    p_attachment_id uuid,
    p_expected_change_request_version integer
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, governance, iam, platform, catalog, authz
AS $function$
DECLARE
    intent governance.change_request_attachment_upload_intents%ROWTYPE;
    request governance.change_requests%ROWTYPE;
    current_membership iam.workspace_memberships%ROWTYPE;
    current_profile iam.profile_role_assignments%ROWTYPE;
    current_binding iam.canonical_admin_bindings%ROWTYPE;
    canonical_role iam.access_roles%ROWTYPE;
    current_mapping platform.system_schema_scopes%ROWTYPE;
    actor_id uuid := NULLIF(pg_catalog.current_setting('app.subject_id', true), '')::uuid;
    contextual_workspace_id uuid :=
        NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid;
    action_name text;
    finalized_time timestamptz := clock_timestamp();
    target record;
    expected_system_id uuid;
    effective_system_id uuid;
    profile_present boolean := false;
    binding_present boolean := false;
    mapping_present boolean := false;
    profile_current boolean := false;
    canonical_admin_current boolean := false;
    legacy_current boolean := false;
BEGIN
    IF contextual_workspace_id IS DISTINCT FROM p_workspace_id OR actor_id IS NULL THEN
        RAISE EXCEPTION 'attachment finalization context is invalid';
    END IF;

    SELECT membership.*
    INTO current_membership
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject
      ON subject.id = membership.subject_id
    JOIN platform.workspaces AS workspace
      ON workspace.id = membership.workspace_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = actor_id
      AND workspace.status = 'ACTIVE'
      AND subject.active IS TRUE
      AND membership.active IS TRUE
      AND (
          membership.access_expires_at IS NULL
          OR membership.access_expires_at > finalized_time
      )
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND NOT (
          COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'service-accounts'
      )
    FOR UPDATE OF membership, subject, workspace;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'attachment current actor authorization is invalid';
    END IF;

    SELECT *
    INTO intent
    FROM governance.change_request_attachment_upload_intents
    WHERE workspace_id = p_workspace_id
      AND id = p_attachment_id
      AND uploaded_by = actor_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'attachment upload intent does not exist';
    END IF;
    IF intent.state = 'FINALIZED' THEN
        IF EXISTS (
            SELECT 1
            FROM governance.change_request_attachments AS attachment
            WHERE attachment.workspace_id = intent.workspace_id
              AND attachment.id = intent.id
              AND attachment.object_key = intent.object_key
              AND attachment.content_sha256 = intent.content_sha256
        ) THEN
            RETURN intent.id;
        END IF;
        RAISE EXCEPTION 'finalized attachment evidence is inconsistent';
    END IF;
    IF intent.state <> 'STORED'
       OR intent.created_at > intent.stored_at
       OR intent.stored_at > finalized_time THEN
        RAISE EXCEPTION 'attachment upload intent is not ready to finalize';
    END IF;

    SELECT *
    INTO request
    FROM governance.change_requests
    WHERE workspace_id = p_workspace_id
      AND id = intent.change_request_id
    FOR UPDATE;
    IF NOT FOUND
       OR request.version IS DISTINCT FROM p_expected_change_request_version
       OR request.current_round_id IS DISTINCT FROM intent.round_id
       OR request.updated_at > finalized_time THEN
        RAISE EXCEPTION 'attachment change-request authorization is stale';
    END IF;
    PERFORM 1
    FROM governance.change_request_rounds AS round
    WHERE round.workspace_id = p_workspace_id
      AND round.change_request_id = request.id
      AND round.id = request.current_round_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'attachment change-request authorization is stale';
    END IF;

    action_name := CASE intent.kind
        WHEN 'TEST' THEN 'change.review'
        ELSE 'change.edit'
    END;
    IF (intent.kind = 'TEST' AND request.state <> 'TESTING')
       OR (
           intent.kind = 'REQUEST'
           AND request.state NOT IN ('REGISTERED', 'CHANGES_REQUESTED')
       ) THEN
        RAISE EXCEPTION 'attachment change-request state is not authorized';
    END IF;
    IF current_membership.clearance < GREATEST(
        request.classification,
        COALESCE(
            (
                SELECT max(item.target_classification)
                FROM governance.change_request_items AS item
                WHERE item.workspace_id = p_workspace_id
                  AND item.change_request_id = request.id
            ),
            0
        )
    ) THEN
        RAISE EXCEPTION 'attachment current actor authorization is invalid';
    END IF;

    PERFORM system.id
    FROM platform.data_systems AS system
    WHERE system.workspace_id = p_workspace_id
      AND system.id IN (
          SELECT COALESCE(item.routing_system_id, item.target_system_id)
          FROM governance.change_request_items AS item
          WHERE item.workspace_id = p_workspace_id
            AND item.change_request_id = request.id
            AND COALESCE(item.routing_system_id, item.target_system_id) IS NOT NULL
          UNION
          SELECT asset.system_id
          FROM governance.change_request_items AS item
          JOIN catalog.assets_projection AS asset
            ON asset.workspace_id = item.workspace_id
           AND asset.id = item.target_asset_id
          WHERE item.workspace_id = p_workspace_id
            AND item.change_request_id = request.id
            AND asset.system_id IS NOT NULL
          UNION
          SELECT scope.system_id
          FROM governance.change_request_items AS item
          JOIN catalog.assets_projection AS asset
            ON asset.workspace_id = item.workspace_id
           AND asset.id = item.target_asset_id
          JOIN platform.system_schema_scopes AS scope
            ON scope.workspace_id = asset.workspace_id
           AND scope.platform = asset.platform
           AND scope.database_name = asset.database_name
           AND scope.schema_name = asset.schema_name
          WHERE item.workspace_id = p_workspace_id
            AND item.change_request_id = request.id
      )
    ORDER BY system.id
    FOR UPDATE OF system;
    PERFORM assignee.id
    FROM platform.system_assignees AS assignee
    WHERE assignee.workspace_id = p_workspace_id
      AND assignee.subject_id = actor_id
      AND assignee.system_id IN (
          SELECT COALESCE(item.routing_system_id, item.target_system_id)
          FROM governance.change_request_items AS item
          WHERE item.workspace_id = p_workspace_id
            AND item.change_request_id = request.id
            AND COALESCE(item.routing_system_id, item.target_system_id) IS NOT NULL
      )
    ORDER BY assignee.system_id, assignee.id
    FOR UPDATE OF assignee;
    PERFORM asset.id
    FROM catalog.assets_projection AS asset
    JOIN governance.change_request_items AS item
      ON item.workspace_id = asset.workspace_id
     AND item.target_asset_id = asset.id
    WHERE item.workspace_id = p_workspace_id
      AND item.change_request_id = request.id
    ORDER BY asset.id
    FOR UPDATE OF asset;
    PERFORM scope.id
    FROM platform.system_schema_scopes AS scope
    JOIN catalog.assets_projection AS asset
      ON asset.workspace_id = scope.workspace_id
     AND asset.platform = scope.platform
     AND asset.database_name = scope.database_name
     AND asset.schema_name = scope.schema_name
    JOIN governance.change_request_items AS item
      ON item.workspace_id = asset.workspace_id
     AND item.target_asset_id = asset.id
    WHERE item.workspace_id = p_workspace_id
      AND item.change_request_id = request.id
    ORDER BY scope.id
    FOR UPDATE OF scope;

    SELECT *
    INTO current_profile
    FROM iam.profile_role_assignments AS assignment
    WHERE assignment.workspace_id = p_workspace_id
      AND assignment.subject_id = actor_id
    FOR UPDATE;
    profile_present := FOUND;
    SELECT *
    INTO current_binding
    FROM iam.canonical_admin_bindings AS binding
    WHERE binding.workspace_id = p_workspace_id
      AND binding.subject_id = actor_id
    FOR UPDATE;
    binding_present := FOUND;
    IF binding_present THEN
        SELECT *
        INTO canonical_role
        FROM iam.access_roles AS role
        WHERE role.workspace_id = current_binding.workspace_id
          AND role.id = current_binding.canonical_role_id
        FOR UPDATE;
    END IF;

    profile_current := profile_present
        AND current_profile.state = 'ACTIVE'
        AND current_profile.tier IN ('VIEWER', 'ENGINEER_STEWARD', 'MANAGER')
        AND current_profile.policy_version = '{PROFILE_ROLE_POLICY_VERSION}'
        AND current_profile.membership_version = current_membership.version
        AND current_profile.materialized_actions_hash = CASE current_profile.tier
            WHEN 'VIEWER' THEN '{_VIEWER_HASH}'
            WHEN 'ENGINEER_STEWARD' THEN '{_ENGINEER_STEWARD_HASH}'
            WHEN 'MANAGER' THEN '{_MANAGER_HASH}'
        END
        AND COALESCE(
            current_membership.attributes -> 'allowed_actions',
            '[]'::jsonb
        ) = CASE current_profile.tier
            WHEN 'VIEWER' THEN '{_VIEWER_ACTIONS}'::jsonb
            WHEN 'ENGINEER_STEWARD' THEN '{_ENGINEER_STEWARD_ACTIONS}'::jsonb
            WHEN 'MANAGER' THEN '{_MANAGER_ACTIONS}'::jsonb
        END
        AND COALESCE(
            current_membership.attributes -> 'allowed_system_ids',
            '[]'::jsonb
        ) = '[]'::jsonb
        AND NOT (
            COALESCE(current_membership.attributes -> 'groups', '[]'::jsonb)
            ? 'security-administrators'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(
                COALESCE(current_membership.attributes -> 'groups', '[]'::jsonb)
            ) AS membership_group(value)
            WHERE membership_group.value LIKE 'datariver-role-%'
        )
        AND COALESCE(
            current_membership.attributes -> 'allowed_actions',
            '[]'::jsonb
        ) ? action_name
        AND NOT (
            COALESCE(
                current_membership.attributes -> 'denied_actions',
                '[]'::jsonb
            ) ? action_name
        );

    canonical_admin_current := binding_present
        AND current_binding.state = 'ACTIVE'
        AND current_binding.role_kind = 'CANONICAL_ADMIN'
        AND current_binding.canonical_role_version = canonical_role.version
        AND current_binding.capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}'
        AND current_binding.capability_hash = '{CANONICAL_ADMIN_CAPABILITY_HASH}'
        AND current_binding.membership_version = current_membership.version
        AND canonical_role.role_key = 'canonical-admin'
        AND canonical_role.role_kind = 'CANONICAL_ADMIN'
        AND canonical_role.management_source = 'SERVER_CANONICAL'
        AND canonical_role.capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}'
        AND canonical_role.active IS TRUE
        AND canonical_role.clearance = 3
        AND canonical_role.groups = '["security-administrators"]'::jsonb
        AND canonical_role.allowed_actions = '{_ADMIN_ACTIONS}'::jsonb
        AND canonical_role.denied_actions = '[]'::jsonb
        AND canonical_role.allowed_system_ids = '[]'::jsonb
        AND canonical_role.allowed_domain_ids = '[]'::jsonb
        AND current_membership.clearance = 3
        AND COALESCE(current_membership.attributes -> 'groups', '[]'::jsonb)
            ? 'security-administrators'
        AND NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(
                COALESCE(current_membership.attributes -> 'groups', '[]'::jsonb)
            ) AS membership_group(value)
            WHERE membership_group.value = 'service-accounts'
               OR membership_group.value LIKE 'datariver-role-%'
        )
        AND COALESCE(
            current_membership.attributes -> 'allowed_actions',
            '[]'::jsonb
        ) = '{_ADMIN_ACTIONS}'::jsonb
        AND COALESCE(
            current_membership.attributes -> 'denied_actions',
            '[]'::jsonb
        ) = '[]'::jsonb
        AND COALESCE(
            current_membership.attributes -> 'allowed_system_ids',
            '[]'::jsonb
        ) = '[]'::jsonb
        AND current_binding.membership_access_hash = pg_catalog.encode(
            pg_catalog.sha256(
                pg_catalog.convert_to(
                    '{{"active":'
                    || CASE WHEN current_membership.active THEN 'true' ELSE 'false' END
                    || ',"allowed_actions":'
                    || COALESCE(
                        (
                            SELECT '[' || pg_catalog.string_agg(
                                pg_catalog.to_json(allowed_action.value)::text,
                                ',' ORDER BY allowed_action.value
                            ) || ']'
                            FROM pg_catalog.jsonb_array_elements_text(
                                COALESCE(
                                    current_membership.attributes -> 'allowed_actions',
                                    '[]'::jsonb
                                )
                            ) AS allowed_action(value)
                        ),
                        '[]'
                    )
                    || ',"allowed_domain_ids":'
                    || COALESCE(
                        (
                            SELECT '[' || pg_catalog.string_agg(
                                pg_catalog.to_json(domain_id.value)::text,
                                ',' ORDER BY domain_id.value
                            ) || ']'
                            FROM pg_catalog.jsonb_array_elements_text(
                                COALESCE(
                                    current_membership.attributes -> 'allowed_domain_ids',
                                    '[]'::jsonb
                                )
                            ) AS domain_id(value)
                        ),
                        '[]'
                    )
                    || ',"allowed_system_ids":'
                    || COALESCE(
                        (
                            SELECT '[' || pg_catalog.string_agg(
                                pg_catalog.to_json(system_id.value)::text,
                                ',' ORDER BY system_id.value
                            ) || ']'
                            FROM pg_catalog.jsonb_array_elements_text(
                                COALESCE(
                                    current_membership.attributes -> 'allowed_system_ids',
                                    '[]'::jsonb
                                )
                            ) AS system_id(value)
                        ),
                        '[]'
                    )
                    || ',"clearance":'
                    || pg_catalog.to_json(
                        CASE current_membership.clearance
                            WHEN 0 THEN 'PUBLIC'
                            WHEN 1 THEN 'INTERNAL'
                            WHEN 2 THEN 'CONFIDENTIAL'
                            WHEN 3 THEN 'RESTRICTED'
                        END
                    )::text
                    || ',"denied_actions":'
                    || COALESCE(
                        (
                            SELECT '[' || pg_catalog.string_agg(
                                pg_catalog.to_json(denied_action.value)::text,
                                ',' ORDER BY denied_action.value
                            ) || ']'
                            FROM pg_catalog.jsonb_array_elements_text(
                                COALESCE(
                                    current_membership.attributes -> 'denied_actions',
                                    '[]'::jsonb
                                )
                            ) AS denied_action(value)
                        ),
                        '[]'
                    )
                    || ',"groups":'
                    || COALESCE(
                        (
                            SELECT '[' || pg_catalog.string_agg(
                                pg_catalog.to_json(membership_group.value)::text,
                                ',' ORDER BY membership_group.value
                            ) || ']'
                            FROM pg_catalog.jsonb_array_elements_text(
                                COALESCE(
                                    current_membership.attributes -> 'groups',
                                    '[]'::jsonb
                                )
                            ) AS membership_group(value)
                        ),
                        '[]'
                    )
                    || '}}',
                    'UTF8'
                )
            ),
            'hex'
        )
        AND COALESCE(
            current_membership.attributes -> 'allowed_actions',
            '[]'::jsonb
        ) ? action_name;

    legacy_current := NOT profile_present
        AND NOT binding_present
        AND COALESCE(
            current_membership.attributes -> 'allowed_actions',
            '[]'::jsonb
        ) ? action_name
        AND NOT (
            COALESCE(
                current_membership.attributes -> 'denied_actions',
                '[]'::jsonb
            ) ? action_name
        );
    IF NOT (profile_current OR canonical_admin_current OR legacy_current) THEN
        RAISE EXCEPTION 'attachment current actor authorization is invalid';
    END IF;

    PERFORM policy.id
    FROM authz.classification_access_policy_versions AS policy
    WHERE policy.workspace_id = p_workspace_id
      AND policy.state = 'ACTIVE'
    ORDER BY policy.id
    FOR SHARE OF policy;
    PERFORM rule.id
    FROM authz.classification_access_policy_rules AS rule
    JOIN authz.classification_access_policy_versions AS policy
      ON policy.workspace_id = rule.workspace_id
     AND policy.id = rule.policy_id
     AND policy.payload_hash = rule.policy_hash
    WHERE policy.workspace_id = p_workspace_id
      AND policy.state = 'ACTIVE'
    ORDER BY rule.id
    FOR SHARE OF rule;
    PERFORM grant_row.id
    FROM authz.restricted_search_grants AS grant_row
    WHERE grant_row.workspace_id = p_workspace_id
      AND grant_row.subject_id = actor_id
    ORDER BY grant_row.id
    FOR SHARE OF grant_row;

    FOR target IN
        SELECT
            item.id AS item_id,
            item.target_ref,
            item.target_asset_id,
            item.target_asset_type,
            item.target_system_id,
            item.routing_system_id,
            item.target_domain_id,
            item.target_owner_department_id,
            item.target_classification,
            item.target_lifecycle,
            asset.id AS current_asset_id,
            asset.external_urn AS current_external_urn,
            asset.asset_type AS current_asset_type,
            asset.platform AS current_platform,
            asset.database_name AS current_database_name,
            asset.schema_name AS current_schema_name,
            asset.system_id AS current_native_system_id,
            asset.domain_id AS current_domain_id,
            asset.owner_department_id AS current_owner_department_id,
            asset.classification AS current_classification,
            asset.lifecycle AS current_lifecycle,
            asset.deleted_at AS current_deleted_at
        FROM governance.change_request_items AS item
        LEFT JOIN catalog.assets_projection AS asset
          ON asset.workspace_id = item.workspace_id
         AND asset.id = item.target_asset_id
        WHERE item.workspace_id = p_workspace_id
          AND item.change_request_id = request.id
        ORDER BY item.id
    LOOP
        expected_system_id := COALESCE(target.routing_system_id, target.target_system_id);
        IF expected_system_id IS NULL
           OR (
               target.routing_system_id IS NOT NULL
               AND target.target_system_id IS NOT NULL
               AND target.routing_system_id IS DISTINCT FROM target.target_system_id
           )
           OR NOT EXISTS (
               SELECT 1
               FROM platform.data_systems AS system
               WHERE system.workspace_id = p_workspace_id
                 AND system.id = expected_system_id
                 AND system.active IS TRUE
           ) THEN
            RAISE EXCEPTION 'attachment catalog target binding is stale';
        END IF;
        IF (profile_current OR canonical_admin_current)
           AND NOT EXISTS (
               SELECT 1
               FROM platform.system_assignees AS assignee
               WHERE assignee.workspace_id = p_workspace_id
                 AND assignee.system_id = expected_system_id
                 AND assignee.subject_id = actor_id
                 AND assignee.active IS TRUE
           ) THEN
            RAISE EXCEPTION 'attachment current actor authorization is invalid';
        END IF;
        IF legacy_current AND NOT (
            COALESCE(
                current_membership.attributes -> 'allowed_system_ids',
                '[]'::jsonb
            ) ? expected_system_id::text
        ) THEN
            RAISE EXCEPTION 'attachment current actor authorization is invalid';
        END IF;
        IF intent.kind = 'TEST' AND NOT EXISTS (
            SELECT 1
            FROM platform.system_assignees AS assignee
            WHERE assignee.workspace_id = p_workspace_id
              AND assignee.system_id = expected_system_id
              AND assignee.subject_id = actor_id
              AND assignee.responsibility = 'DEVELOPER'
              AND assignee.active IS TRUE
        ) THEN
            RAISE EXCEPTION 'attachment developer assignment is not current';
        END IF;

        IF target.target_asset_id IS NULL THEN
            CONTINUE;
        END IF;
        IF target.current_asset_id IS NULL
           OR target.current_external_urn IS DISTINCT FROM target.target_ref
           OR target.current_asset_type IS DISTINCT FROM target.target_asset_type
           OR target.current_asset_type NOT IN ('TABLE', 'VIEW', 'DATASET')
           OR target.current_platform IS NULL
           OR target.current_database_name IS NULL
           OR target.current_schema_name IS NULL
           OR target.current_domain_id IS DISTINCT FROM target.target_domain_id
           OR target.current_owner_department_id
                IS DISTINCT FROM target.target_owner_department_id
           OR target.current_classification IS DISTINCT FROM target.target_classification
           OR target.current_lifecycle IS DISTINCT FROM target.target_lifecycle
           OR target.current_lifecycle <> 'ACTIVE'
           OR target.current_deleted_at IS NOT NULL THEN
            RAISE EXCEPTION 'attachment catalog target binding is stale';
        END IF;

        SELECT *
        INTO current_mapping
        FROM platform.system_schema_scopes AS scope
        WHERE scope.workspace_id = p_workspace_id
          AND scope.platform = target.current_platform
          AND scope.database_name = target.current_database_name
          AND scope.schema_name = target.current_schema_name;
        mapping_present := FOUND;
        IF mapping_present THEN
            IF current_mapping.active IS NOT TRUE
               OR (
                   target.current_native_system_id IS NOT NULL
                   AND target.current_native_system_id
                       IS DISTINCT FROM current_mapping.system_id
               )
               OR NOT EXISTS (
                   SELECT 1
                   FROM platform.data_systems AS system
                   WHERE system.workspace_id = p_workspace_id
                     AND system.id = current_mapping.system_id
                     AND system.active IS TRUE
               ) THEN
                RAISE EXCEPTION 'attachment catalog target binding is stale';
            END IF;
            effective_system_id := current_mapping.system_id;
        ELSE
            IF target.current_native_system_id IS NULL
               OR NOT EXISTS (
                   SELECT 1
                   FROM platform.data_systems AS system
                   WHERE system.workspace_id = p_workspace_id
                     AND system.id = target.current_native_system_id
                     AND system.active IS TRUE
               ) THEN
                RAISE EXCEPTION 'attachment catalog target binding is stale';
            END IF;
            effective_system_id := target.current_native_system_id;
        END IF;
        IF effective_system_id IS DISTINCT FROM expected_system_id THEN
            RAISE EXCEPTION 'attachment catalog target binding is stale';
        END IF;

        IF target.current_classification = 3 THEN
            IF target.current_domain_id IS NULL
               OR NOT (
                   COALESCE(
                       current_membership.attributes -> 'allowed_domain_ids',
                       '[]'::jsonb
                   ) ? target.current_domain_id::text
               )
               OR NOT EXISTS (
                   SELECT 1
                   FROM authz.classification_access_policy_versions AS policy
                   JOIN authz.classification_access_policy_rules AS rule
                     ON rule.workspace_id = policy.workspace_id
                    AND rule.policy_id = policy.id
                    AND rule.policy_hash = policy.payload_hash
                    AND rule.classification = 3
                    AND rule.search_mode = 'EXPLICIT_GRANT_ONLY'
                   JOIN authz.restricted_search_grants AS grant_row
                     ON grant_row.workspace_id = policy.workspace_id
                    AND grant_row.classification_policy_id = policy.id
                    AND grant_row.classification_policy_hash = policy.payload_hash
                    AND grant_row.subject_id = actor_id
                    AND grant_row.state = 'ACTIVE'
                    AND grant_row.valid_from <= finalized_time
                    AND grant_row.expires_at > finalized_time
                   WHERE policy.workspace_id = p_workspace_id
                     AND policy.state = 'ACTIVE'
                     AND (
                         (grant_row.scope = 'RESOURCE'
                          AND grant_row.scope_id = target.current_asset_id)
                         OR (grant_row.scope = 'SYSTEM'
                             AND grant_row.scope_id = effective_system_id)
                         OR (grant_row.scope = 'DOMAIN'
                             AND grant_row.scope_id = target.current_domain_id)
                     )
               ) THEN
                RAISE EXCEPTION 'attachment current actor authorization is invalid';
            END IF;
        ELSIF EXISTS (
            SELECT 1
            FROM authz.classification_access_policy_versions AS policy
            WHERE policy.workspace_id = p_workspace_id
              AND policy.state = 'ACTIVE'
        ) AND NOT EXISTS (
            SELECT 1
            FROM authz.classification_access_policy_versions AS policy
            JOIN authz.classification_access_policy_rules AS rule
              ON rule.workspace_id = policy.workspace_id
             AND rule.policy_id = policy.id
             AND rule.policy_hash = policy.payload_hash
             AND rule.classification = target.current_classification
             AND rule.search_mode = 'ABAC'
            WHERE policy.workspace_id = p_workspace_id
              AND policy.state = 'ACTIVE'
        ) THEN
            RAISE EXCEPTION 'attachment current actor authorization is invalid';
        END IF;

        IF legacy_current
           AND target.current_domain_id IS NOT NULL
           AND NOT (
               COALESCE(
                   current_membership.attributes -> 'allowed_domain_ids',
                   '[]'::jsonb
               ) ? target.current_domain_id::text
           ) THEN
            RAISE EXCEPTION 'attachment current actor authorization is invalid';
        END IF;
    END LOOP;

    INSERT INTO governance.change_request_attachments (
        id,
        workspace_id,
        change_request_id,
        round_id,
        kind,
        original_name,
        serial_number,
        bucket,
        object_key,
        content_type,
        size_bytes,
        content_sha256,
        uploaded_by,
        created_at,
        updated_at
    ) VALUES (
        intent.id,
        intent.workspace_id,
        intent.change_request_id,
        intent.round_id,
        intent.kind,
        intent.original_name,
        intent.serial_number,
        intent.bucket,
        intent.object_key,
        intent.content_type,
        intent.size_bytes,
        intent.content_sha256,
        intent.uploaded_by,
        finalized_time,
        finalized_time
    );
    UPDATE governance.change_request_attachment_upload_intents
    SET state = 'FINALIZED',
        finalized_at = finalized_time,
        updated_at = finalized_time,
        version = version + 1
    WHERE workspace_id = p_workspace_id
      AND id = p_attachment_id;
    RETURN p_attachment_id;
END
$function$;
""".strip()


LEGACY_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION governance.finalize_attachment_upload_intent(
    p_workspace_id uuid,
    p_attachment_id uuid,
    p_expected_change_request_version integer
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, governance, iam, platform, catalog
AS $function$
DECLARE
    intent governance.change_request_attachment_upload_intents%ROWTYPE;
    request governance.change_requests%ROWTYPE;
    actor_id uuid := NULLIF(pg_catalog.current_setting('app.subject_id', true), '')::uuid;
    contextual_workspace_id uuid :=
        NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid;
    action_name text;
    finalized_time timestamptz := clock_timestamp();
BEGIN
    IF contextual_workspace_id IS DISTINCT FROM p_workspace_id OR actor_id IS NULL THEN
        RAISE EXCEPTION 'attachment finalization context is invalid';
    END IF;
    SELECT *
    INTO intent
    FROM governance.change_request_attachment_upload_intents
    WHERE workspace_id = p_workspace_id
      AND id = p_attachment_id
      AND uploaded_by = actor_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'attachment upload intent does not exist';
    END IF;
    IF intent.state = 'FINALIZED' THEN
        IF EXISTS (
            SELECT 1
            FROM governance.change_request_attachments AS attachment
            WHERE attachment.workspace_id = intent.workspace_id
              AND attachment.id = intent.id
              AND attachment.object_key = intent.object_key
              AND attachment.content_sha256 = intent.content_sha256
        ) THEN
            RETURN intent.id;
        END IF;
        RAISE EXCEPTION 'finalized attachment evidence is inconsistent';
    END IF;
    IF intent.state <> 'STORED'
       OR intent.created_at > intent.stored_at
       OR intent.stored_at > finalized_time THEN
        RAISE EXCEPTION 'attachment upload intent is not ready to finalize';
    END IF;
    SELECT *
    INTO request
    FROM governance.change_requests
    WHERE workspace_id = p_workspace_id
      AND id = intent.change_request_id
    FOR UPDATE;
    IF NOT FOUND
       OR request.version IS DISTINCT FROM p_expected_change_request_version
       OR request.current_round_id IS DISTINCT FROM intent.round_id
       OR request.updated_at > finalized_time THEN
        RAISE EXCEPTION 'attachment change-request authorization is stale';
    END IF;
    action_name := CASE intent.kind
        WHEN 'TEST' THEN 'change.review'
        ELSE 'change.edit'
    END;
    IF (intent.kind = 'TEST' AND request.state <> 'TESTING')
       OR (
           intent.kind = 'REQUEST'
           AND request.state NOT IN ('REGISTERED', 'CHANGES_REQUESTED')
       ) THEN
        RAISE EXCEPTION 'attachment change-request state is not authorized';
    END IF;
    PERFORM 1
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject
      ON subject.id = membership.subject_id
    JOIN platform.workspaces AS workspace
      ON workspace.id = membership.workspace_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = actor_id
      AND workspace.status = 'ACTIVE'
      AND subject.active IS TRUE
      AND membership.active IS TRUE
      AND (
          membership.access_expires_at IS NULL
          OR membership.access_expires_at > finalized_time
      )
      AND membership.clearance >= GREATEST(
          request.classification,
          COALESCE(
              (
                  SELECT max(item.target_classification)
                  FROM governance.change_request_items AS item
                  WHERE item.workspace_id = p_workspace_id
                    AND item.change_request_id = request.id
              ),
              0
          )
      )
      AND COALESCE(
          membership.attributes -> 'allowed_actions',
          '[]'::jsonb
      ) ? action_name
      AND NOT (
          COALESCE(
              membership.attributes -> 'denied_actions',
              '[]'::jsonb
          ) ? action_name
      )
      AND NOT EXISTS (
          SELECT 1
          FROM governance.change_request_items AS item
          WHERE item.workspace_id = p_workspace_id
            AND item.change_request_id = request.id
            AND COALESCE(item.routing_system_id, item.target_system_id) IS NOT NULL
            AND NOT (
                COALESCE(
                    membership.attributes -> 'allowed_system_ids',
                    '[]'::jsonb
                ) ? COALESCE(
                    item.routing_system_id,
                    item.target_system_id
                )::text
            )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM governance.change_request_items AS item
          WHERE item.workspace_id = p_workspace_id
            AND item.change_request_id = request.id
            AND item.target_domain_id IS NOT NULL
            AND NOT (
                COALESCE(
                    membership.attributes -> 'allowed_domain_ids',
                    '[]'::jsonb
                ) ? item.target_domain_id::text
            )
      )
    FOR UPDATE OF membership, subject, workspace;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'attachment current actor authorization is invalid';
    END IF;
    IF intent.kind = 'TEST' AND NOT EXISTS (
        SELECT 1
        FROM platform.system_assignees AS assignee
        JOIN governance.change_request_items AS item
          ON item.workspace_id = assignee.workspace_id
         AND COALESCE(item.routing_system_id, item.target_system_id) =
             assignee.system_id
        WHERE item.workspace_id = p_workspace_id
          AND item.change_request_id = request.id
          AND assignee.subject_id = actor_id
          AND assignee.responsibility = 'DEVELOPER'
          AND assignee.active IS TRUE
    ) THEN
        RAISE EXCEPTION 'attachment developer assignment is not current';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM governance.change_request_items AS item
        LEFT JOIN catalog.assets_projection AS asset
          ON asset.workspace_id = item.workspace_id
         AND asset.id = item.target_asset_id
        WHERE item.workspace_id = p_workspace_id
          AND item.change_request_id = request.id
          AND item.target_asset_id IS NOT NULL
          AND (
              asset.id IS NULL
              OR asset.external_urn IS DISTINCT FROM item.target_ref
              OR asset.asset_type IS DISTINCT FROM item.target_asset_type
              OR asset.system_id IS DISTINCT FROM item.target_system_id
              OR asset.domain_id IS DISTINCT FROM item.target_domain_id
              OR asset.owner_department_id
                  IS DISTINCT FROM item.target_owner_department_id
              OR asset.classification IS DISTINCT FROM item.target_classification
              OR asset.lifecycle IS DISTINCT FROM item.target_lifecycle
          )
    ) THEN
        RAISE EXCEPTION 'attachment catalog target binding is stale';
    END IF;
    INSERT INTO governance.change_request_attachments (
        id,
        workspace_id,
        change_request_id,
        round_id,
        kind,
        original_name,
        serial_number,
        bucket,
        object_key,
        content_type,
        size_bytes,
        content_sha256,
        uploaded_by,
        created_at,
        updated_at
    ) VALUES (
        intent.id,
        intent.workspace_id,
        intent.change_request_id,
        intent.round_id,
        intent.kind,
        intent.original_name,
        intent.serial_number,
        intent.bucket,
        intent.object_key,
        intent.content_type,
        intent.size_bytes,
        intent.content_sha256,
        intent.uploaded_by,
        finalized_time,
        finalized_time
    );
    UPDATE governance.change_request_attachment_upload_intents
    SET state = 'FINALIZED',
        finalized_at = finalized_time,
        updated_at = finalized_time,
        version = version + 1
    WHERE workspace_id = p_workspace_id
      AND id = p_attachment_id;
    RETURN p_attachment_id;
END
$function$;
""".strip()


def upgrade() -> None:
    return # Functions only
    op.execute(FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL)


def downgrade() -> None:
    op.execute(LEGACY_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL)
