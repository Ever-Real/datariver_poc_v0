# ruff: noqa: S608 -- SQL is rendered only from fixed server-owned policy constants.

from __future__ import annotations

import json

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

PROFILE_ROLE_ASSIGNMENT_SIGNATURE = (
    "iam.assign_profile_role(uuid, uuid, text, integer, text, text, text, uuid)"
)
CANONICAL_ADMIN_PROFILE_TRANSITION_SIGNATURE = (
    "iam.transition_canonical_admin_profile(uuid, uuid, text, integer, integer, text, text, text, "
    "uuid)"
)


def _json_actions(tier: ProfileRoleTier) -> str:
    return json.dumps(
        sorted(action.value for action in PROFILE_ROLE_BY_TIER[tier].allowed_actions),
        separators=(",", ":"),
    ).replace("'", "''")


_VIEWER_ACTIONS = _json_actions(ProfileRoleTier.VIEWER)
_ENGINEER_STEWARD_ACTIONS = _json_actions(ProfileRoleTier.ENGINEER_STEWARD)
_MANAGER_ACTIONS = _json_actions(ProfileRoleTier.MANAGER)
_ADMIN_ACTIONS = json.dumps(
    sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS),
    separators=(",", ":"),
).replace("'", "''")
_VIEWER_HASH = PROFILE_ROLE_BY_TIER[ProfileRoleTier.VIEWER].materialized_actions_hash
_ENGINEER_STEWARD_HASH = PROFILE_ROLE_BY_TIER[
    ProfileRoleTier.ENGINEER_STEWARD
].materialized_actions_hash
_MANAGER_HASH = PROFILE_ROLE_BY_TIER[ProfileRoleTier.MANAGER].materialized_actions_hash


def _profile_action_case(variable: str) -> str:
    return f"""CASE {variable}
        WHEN 'VIEWER' THEN '{_VIEWER_ACTIONS}'::jsonb
        WHEN 'ENGINEER_STEWARD' THEN '{_ENGINEER_STEWARD_ACTIONS}'::jsonb
        WHEN 'MANAGER' THEN '{_MANAGER_ACTIONS}'::jsonb
    END"""


def _profile_hash_case(variable: str) -> str:
    return f"""CASE {variable}
        WHEN 'VIEWER' THEN '{_VIEWER_HASH}'
        WHEN 'ENGINEER_STEWARD' THEN '{_ENGINEER_STEWARD_HASH}'
        WHEN 'MANAGER' THEN '{_MANAGER_HASH}'
    END"""


PROFILE_ROLE_ASSIGNMENT_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION iam.assign_profile_role(
    p_workspace_id uuid,
    p_target_subject_id uuid,
    p_tier text,
    p_expected_membership_version integer,
    p_reason text,
    p_assurance text,
    p_access_payload_hash text,
    p_policy_decision_id uuid
)
RETURNS TABLE(membership_version integer, assignment_version integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, iam, platform
AS $datariver$
DECLARE
    actor_id uuid;
    target_membership iam.workspace_memberships%ROWTYPE;
    previous_profile iam.profile_role_assignments%ROWTYPE;
    previous_role iam.access_role_assignments%ROWTYPE;
    next_actions jsonb;
    next_actions_hash text;
    next_attributes jsonb;
    filtered_groups jsonb;
    next_membership_version integer;
    next_assignment_version integer;
BEGIN
    actor_id := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    IF actor_id IS NULL OR NULLIF(current_setting('app.workspace_id', true), '')::uuid
       IS DISTINCT FROM p_workspace_id THEN
        RAISE EXCEPTION 'A matching DataRiver security context is required'
            USING ERRCODE = '42501';
    END IF;
    IF actor_id = p_target_subject_id THEN
        RAISE EXCEPTION 'An administrator cannot change their own profile Role'
            USING ERRCODE = '23514';
    END IF;
    IF p_tier NOT IN ('VIEWER', 'ENGINEER_STEWARD', 'MANAGER') THEN
        RAISE EXCEPTION 'The profile Role tier is invalid' USING ERRCODE = '23514';
    END IF;
    IF char_length(trim(p_reason)) NOT BETWEEN 1 AND 4000
       OR p_assurance NOT IN ('PASSWORD_REAUTH', 'HARDWARE_WEBAUTHN')
       OR p_access_payload_hash !~ '^[0-9a-f]{{64}}$'
       OR p_policy_decision_id IS NULL THEN
        RAISE EXCEPTION 'The governed profile Role evidence is invalid'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = actor_id
      AND subject.active IS TRUE AND membership.active IS TRUE
      AND (membership.access_expires_at IS NULL
           OR membership.access_expires_at > transaction_timestamp())
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND membership.clearance >= 3
      AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'security-administrators'
      AND COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)
          ? 'admin.manage'
      AND NOT (COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb)
          ? 'admin.manage')
    FOR KEY SHARE OF membership, subject;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'An eligible human security administrator is required'
            USING ERRCODE = '42501';
    END IF;

    SELECT membership.* INTO target_membership
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = p_target_subject_id
      AND subject.active IS TRUE AND membership.active IS TRUE
      AND (membership.access_expires_at IS NULL
           OR membership.access_expires_at > transaction_timestamp())
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'service-accounts')
    FOR UPDATE OF membership;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Only an active human membership can receive a profile Role'
            USING ERRCODE = '23514';
    END IF;
    IF target_membership.version <> p_expected_membership_version THEN
        RAISE EXCEPTION 'The target membership version changed' USING ERRCODE = '40001';
    END IF;
    IF EXISTS (
        SELECT 1 FROM iam.canonical_admin_bindings AS binding
        WHERE binding.workspace_id = p_workspace_id
          AND binding.subject_id = p_target_subject_id
          AND binding.state = 'ACTIVE'
    ) THEN
        RAISE EXCEPTION 'Canonical Admin demotion requires the protected transition'
            USING ERRCODE = '23514';
    END IF;

    next_actions := {_profile_action_case("p_tier")};
    next_actions_hash := {_profile_hash_case("p_tier")};
    SELECT COALESCE(jsonb_agg(value ORDER BY ordinal), '[]'::jsonb)
      INTO filtered_groups
    FROM jsonb_array_elements_text(
        COALESCE(target_membership.attributes -> 'groups', '[]'::jsonb)
    ) WITH ORDINALITY AS item(value, ordinal)
    WHERE value <> 'security-administrators'
      AND value NOT LIKE 'datariver-role-%';
    next_attributes := target_membership.attributes - 'role_id' - 'managed_by';
    next_attributes := jsonb_set(next_attributes, '{{groups}}', filtered_groups, true);
    next_attributes := jsonb_set(next_attributes, '{{allowed_actions}}', next_actions, true);
    next_attributes := jsonb_set(next_attributes, '{{allowed_system_ids}}', '[]'::jsonb, true);

    SELECT * INTO previous_role FROM iam.access_role_assignments
    WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id AND active IS TRUE
    FOR UPDATE;
    IF FOUND THEN
        UPDATE iam.access_role_assignments
        SET active = FALSE, version = version + 1, updated_at = transaction_timestamp()
        WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id;
    END IF;
    SELECT * INTO previous_profile FROM iam.profile_role_assignments
    WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id
    FOR UPDATE;

    UPDATE iam.workspace_memberships
    SET clearance = GREATEST(clearance, 2), attributes = next_attributes,
        version = version + 1, updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id
    RETURNING version INTO next_membership_version;

    IF previous_role.id IS NOT NULL THEN
        INSERT INTO iam.access_role_assignment_events (
            id, workspace_id, subject_id, event_type, previous_role_id,
            previous_role_version, role_id, role_version, membership_version,
            access_payload_hash, actor_id, occurred_at
        ) VALUES (
            gen_random_uuid(), p_workspace_id, p_target_subject_id, 'REMOVED',
            previous_role.role_id, previous_role.role_version, NULL, NULL,
            next_membership_version, p_access_payload_hash, actor_id,
            transaction_timestamp()
        );
    END IF;

    IF previous_profile.workspace_id IS NULL THEN
        next_assignment_version := 1;
        INSERT INTO iam.profile_role_assignments (
            workspace_id, subject_id, tier, policy_version, materialized_actions_hash,
            membership_version, state, assigned_by, reason, assurance, version,
            created_at, updated_at
        ) VALUES (
            p_workspace_id, p_target_subject_id, p_tier, '{PROFILE_ROLE_POLICY_VERSION}',
            next_actions_hash, next_membership_version, 'ACTIVE', actor_id, trim(p_reason),
            p_assurance, next_assignment_version, transaction_timestamp(),
            transaction_timestamp()
        );
    ELSE
        next_assignment_version := previous_profile.version + 1;
        UPDATE iam.profile_role_assignments
        SET tier = p_tier, policy_version = '{PROFILE_ROLE_POLICY_VERSION}',
            materialized_actions_hash = next_actions_hash,
            membership_version = next_membership_version, state = 'ACTIVE',
            assigned_by = actor_id, reason = trim(p_reason), assurance = p_assurance,
            version = next_assignment_version, updated_at = transaction_timestamp()
        WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id;
    END IF;
    INSERT INTO iam.profile_role_assignment_events (
        id, workspace_id, subject_id, event_type, previous_tier, next_tier,
        policy_version, membership_version, assignment_version, actor_id,
        policy_decision_id,
        reason, assurance, occurred_at
    ) VALUES (
        gen_random_uuid(), p_workspace_id, p_target_subject_id,
        CASE WHEN previous_profile.workspace_id IS NULL THEN 'ASSIGNED' ELSE 'CHANGED' END,
        CASE WHEN previous_profile.workspace_id IS NULL THEN NULL ELSE previous_profile.tier END,
        p_tier, '{PROFILE_ROLE_POLICY_VERSION}', next_membership_version,
        next_assignment_version, actor_id, p_policy_decision_id, trim(p_reason), p_assurance,
        transaction_timestamp()
    );
    RETURN QUERY SELECT next_membership_version, next_assignment_version;
END
$datariver$
""".strip()


CANONICAL_ADMIN_PROFILE_TRANSITION_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION iam.transition_canonical_admin_profile(
    p_workspace_id uuid,
    p_target_subject_id uuid,
    p_next_tier text,
    p_expected_membership_version integer,
    p_expected_binding_version integer,
    p_reason text,
    p_assurance text,
    p_access_payload_hash text,
    p_policy_decision_id uuid
)
RETURNS TABLE(membership_version integer, assignment_version integer, binding_version integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, iam, platform
AS $datariver$
DECLARE
    actor_id uuid;
    target_membership iam.workspace_memberships%ROWTYPE;
    canonical_role iam.access_roles%ROWTYPE;
    current_binding iam.canonical_admin_bindings%ROWTYPE;
    previous_profile iam.profile_role_assignments%ROWTYPE;
    previous_role iam.access_role_assignments%ROWTYPE;
    next_actions jsonb;
    next_actions_hash text;
    next_attributes jsonb;
    filtered_groups jsonb;
    next_membership_version integer;
    next_assignment_version integer;
    next_binding_version integer;
    active_binding_count integer;
BEGIN
    actor_id := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    IF actor_id IS NULL OR NULLIF(current_setting('app.workspace_id', true), '')::uuid
       IS DISTINCT FROM p_workspace_id OR actor_id = p_target_subject_id THEN
        RAISE EXCEPTION 'A separate Canonical Admin actor is required' USING ERRCODE = '42501';
    END IF;
    IF p_assurance <> 'HARDWARE_WEBAUTHN' THEN
        RAISE EXCEPTION 'Canonical Admin transitions require hardware WebAuthn'
            USING ERRCODE = '42501';
    END IF;
    IF p_next_tier NOT IN ('VIEWER', 'ENGINEER_STEWARD', 'MANAGER', 'ADMIN')
       OR char_length(trim(p_reason)) NOT BETWEEN 1 AND 4000
       OR p_access_payload_hash !~ '^[0-9a-f]{{64}}$'
       OR p_policy_decision_id IS NULL THEN
        RAISE EXCEPTION 'The protected profile transition evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM platform.workspaces
    WHERE id = p_workspace_id AND status = 'ACTIVE' FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The workspace is not active' USING ERRCODE = '23514';
    END IF;
    PERFORM 1
    FROM iam.canonical_admin_bindings AS binding
    JOIN iam.workspace_memberships AS membership
      ON membership.workspace_id = binding.workspace_id
     AND membership.subject_id = binding.subject_id
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    JOIN iam.access_roles AS actor_role
      ON actor_role.workspace_id = binding.workspace_id
     AND actor_role.id = binding.canonical_role_id
     AND actor_role.role_kind = binding.role_kind
    WHERE binding.workspace_id = p_workspace_id AND binding.subject_id = actor_id
      AND binding.state = 'ACTIVE'
      AND binding.role_kind = 'CANONICAL_ADMIN'
      AND binding.canonical_role_version = actor_role.version
      AND binding.capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}'
      AND binding.capability_hash = '{CANONICAL_ADMIN_CAPABILITY_HASH}'
      AND binding.membership_version = membership.version
      AND actor_role.role_key = 'canonical-admin'
      AND actor_role.management_source = 'SERVER_CANONICAL'
      AND actor_role.capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}'
      AND actor_role.active IS TRUE AND actor_role.clearance = 3
      AND actor_role.groups = '["security-administrators"]'::jsonb
      AND actor_role.allowed_actions = '{_ADMIN_ACTIONS}'::jsonb
      AND actor_role.denied_actions = '[]'::jsonb
      AND actor_role.allowed_system_ids = '[]'::jsonb
      AND actor_role.allowed_domain_ids = '[]'::jsonb
      AND subject.active IS TRUE AND membership.active IS TRUE
      AND (membership.access_expires_at IS NULL
           OR membership.access_expires_at > transaction_timestamp())
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND membership.clearance = 3
      AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'security-administrators'
      AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'service-accounts')
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements_text(
              COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ) AS membership_group(value)
          WHERE membership_group.value LIKE 'datariver-role-%'
      )
      AND COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)
          = '{_ADMIN_ACTIONS}'::jsonb
      AND COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb) = '[]'::jsonb
      AND COALESCE(membership.attributes -> 'allowed_system_ids', '[]'::jsonb) = '[]'::jsonb
    FOR KEY SHARE OF binding, membership, subject, actor_role;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The actor Canonical Admin binding is not current'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO canonical_role FROM iam.access_roles
    WHERE workspace_id = p_workspace_id AND role_key = 'canonical-admin'
      AND role_kind = 'CANONICAL_ADMIN'
      AND management_source = 'SERVER_CANONICAL' AND active IS TRUE
      AND capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}'
      AND clearance = 3
      AND groups = '["security-administrators"]'::jsonb
      AND allowed_actions = '{_ADMIN_ACTIONS}'::jsonb
      AND denied_actions = '[]'::jsonb
      AND allowed_system_ids = '[]'::jsonb
      AND allowed_domain_ids = '[]'::jsonb
    FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The Canonical Admin definition is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT membership.* INTO target_membership
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = p_target_subject_id
      AND subject.active IS TRUE AND membership.active IS TRUE
      AND (membership.access_expires_at IS NULL
           OR membership.access_expires_at > transaction_timestamp())
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'service-accounts')
    FOR UPDATE OF membership;
    IF NOT FOUND OR target_membership.version <> p_expected_membership_version THEN
        RAISE EXCEPTION 'The target active human membership changed'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO current_binding FROM iam.canonical_admin_bindings
    WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id FOR UPDATE;
    SELECT * INTO previous_profile FROM iam.profile_role_assignments
    WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id FOR UPDATE;
    SELECT * INTO previous_role FROM iam.access_role_assignments
    WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id AND active IS TRUE
    FOR UPDATE;

    IF p_next_tier = 'ADMIN' THEN
        IF current_binding.workspace_id IS NOT NULL AND current_binding.state = 'ACTIVE' THEN
            RAISE EXCEPTION 'The target is already a Canonical Admin' USING ERRCODE = '23514';
        END IF;
        IF current_binding.workspace_id IS NULL THEN
            IF p_expected_binding_version <> 0 THEN
                RAISE EXCEPTION 'A new Canonical Admin binding expects version zero'
                    USING ERRCODE = '40001';
            END IF;
        ELSIF current_binding.state = 'REVOKED' THEN
            IF p_expected_binding_version <> current_binding.version THEN
                RAISE EXCEPTION 'The revoked Canonical Admin binding changed'
                    USING ERRCODE = '40001';
            END IF;
        ELSE
            RAISE EXCEPTION 'The Canonical Admin binding state is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF jsonb_array_length(
            COALESCE(target_membership.attributes -> 'denied_actions', '[]'::jsonb)
        ) <> 0 THEN
            RAISE EXCEPTION 'Explicit denies must be resolved before Admin promotion'
                USING ERRCODE = '23514';
        END IF;
        SELECT COALESCE(jsonb_agg(value ORDER BY ordinal), '[]'::jsonb)
          INTO filtered_groups
        FROM jsonb_array_elements_text(
            COALESCE(target_membership.attributes -> 'groups', '[]'::jsonb)
        ) WITH ORDINALITY AS item(value, ordinal)
        WHERE value NOT LIKE 'datariver-role-%' AND value <> 'security-administrators';
        filtered_groups := filtered_groups || '["security-administrators"]'::jsonb;
        next_attributes := target_membership.attributes - 'role_id' - 'managed_by';
        next_attributes := jsonb_set(next_attributes, '{{groups}}', filtered_groups, true);
        next_attributes := jsonb_set(
            next_attributes, '{{allowed_actions}}', '{_ADMIN_ACTIONS}'::jsonb, true
        );
        next_attributes := jsonb_set(next_attributes, '{{allowed_system_ids}}', '[]'::jsonb, true);
        UPDATE iam.workspace_memberships
        SET clearance = 3, attributes = next_attributes, version = version + 1,
            updated_at = transaction_timestamp()
        WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id
        RETURNING version INTO next_membership_version;
        IF previous_role.id IS NOT NULL THEN
            UPDATE iam.access_role_assignments
            SET active = FALSE, version = version + 1, updated_at = transaction_timestamp()
            WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id;
            INSERT INTO iam.access_role_assignment_events (
                id, workspace_id, subject_id, event_type, previous_role_id,
                previous_role_version, role_id, role_version, membership_version,
                access_payload_hash, actor_id, occurred_at
            ) VALUES (
                gen_random_uuid(), p_workspace_id, p_target_subject_id, 'REMOVED',
                previous_role.role_id, previous_role.role_version, NULL, NULL,
                next_membership_version, p_access_payload_hash, actor_id,
                transaction_timestamp()
            );
        END IF;
        IF previous_profile.workspace_id IS NOT NULL THEN
            UPDATE iam.profile_role_assignments
            SET state = 'REVOKED', membership_version = next_membership_version,
                assigned_by = actor_id, reason = trim(p_reason), assurance = p_assurance,
                version = version + 1, updated_at = transaction_timestamp()
            WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id
            RETURNING version INTO next_assignment_version;
        ELSE
            next_assignment_version := 1;
        END IF;
        IF current_binding.workspace_id IS NULL THEN
            next_binding_version := 1;
            INSERT INTO iam.canonical_admin_bindings (
                workspace_id, subject_id, canonical_role_id, role_kind,
                canonical_role_version, capability_catalog_version, capability_hash,
                membership_version, membership_access_hash, state, binding_source,
                version, created_at, updated_at
            ) VALUES (
                p_workspace_id, p_target_subject_id, canonical_role.id, 'CANONICAL_ADMIN',
                canonical_role.version, '{CAPABILITY_CATALOG_VERSION}',
                '{CANONICAL_ADMIN_CAPABILITY_HASH}', next_membership_version,
                p_access_payload_hash, 'ACTIVE', 'GOVERNED_ADMIN_ASSIGNMENT', 1,
                transaction_timestamp(), transaction_timestamp()
            );
        ELSE
            next_binding_version := current_binding.version + 1;
            UPDATE iam.canonical_admin_bindings
            SET canonical_role_id = canonical_role.id,
                canonical_role_version = canonical_role.version,
                capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}',
                capability_hash = '{CANONICAL_ADMIN_CAPABILITY_HASH}',
                membership_version = next_membership_version,
                membership_access_hash = p_access_payload_hash, state = 'ACTIVE',
                binding_source = 'GOVERNED_ADMIN_ASSIGNMENT',
                version = next_binding_version, updated_at = transaction_timestamp()
            WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id;
        END IF;
        INSERT INTO iam.profile_role_assignment_events (
            id, workspace_id, subject_id, event_type, previous_tier, next_tier,
            policy_version, membership_version, assignment_version, actor_id,
            policy_decision_id,
            reason, assurance, occurred_at
        ) VALUES (
            gen_random_uuid(), p_workspace_id, p_target_subject_id, 'PROMOTED_TO_ADMIN',
            CASE WHEN previous_profile.workspace_id IS NULL
                THEN NULL ELSE previous_profile.tier END,
            'ADMIN', '{PROFILE_ROLE_POLICY_VERSION}', next_membership_version,
            next_assignment_version, actor_id, p_policy_decision_id, trim(p_reason), p_assurance,
            transaction_timestamp()
        );
    ELSE
        IF current_binding.workspace_id IS NULL OR current_binding.state <> 'ACTIVE'
           OR current_binding.version <> p_expected_binding_version THEN
            RAISE EXCEPTION 'The target Canonical Admin binding changed'
                USING ERRCODE = '40001';
        END IF;
        SELECT count(*) INTO active_binding_count
        FROM iam.canonical_admin_bindings AS binding
        JOIN iam.workspace_memberships AS membership
          ON membership.workspace_id = binding.workspace_id
         AND membership.subject_id = binding.subject_id
        JOIN iam.subjects AS subject ON subject.id = membership.subject_id
        JOIN iam.access_roles AS role
          ON role.workspace_id = binding.workspace_id
         AND role.id = binding.canonical_role_id
         AND role.role_kind = binding.role_kind
        WHERE binding.workspace_id = p_workspace_id
          AND binding.state = 'ACTIVE'
          AND binding.role_kind = 'CANONICAL_ADMIN'
          AND binding.canonical_role_version = role.version
          AND binding.capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}'
          AND binding.capability_hash = '{CANONICAL_ADMIN_CAPABILITY_HASH}'
          AND binding.membership_version = membership.version
          AND role.role_key = 'canonical-admin'
          AND role.management_source = 'SERVER_CANONICAL'
          AND role.capability_catalog_version = '{CAPABILITY_CATALOG_VERSION}'
          AND role.active IS TRUE AND role.clearance = 3
          AND role.groups = '["security-administrators"]'::jsonb
          AND role.allowed_actions = '{_ADMIN_ACTIONS}'::jsonb
          AND role.denied_actions = '[]'::jsonb
          AND role.allowed_system_ids = '[]'::jsonb
          AND role.allowed_domain_ids = '[]'::jsonb
          AND subject.active IS TRUE AND membership.active IS TRUE
          AND (membership.access_expires_at IS NULL
               OR membership.access_expires_at > transaction_timestamp())
          AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
          AND membership.clearance = 3
          AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
              ? 'security-administrators'
          AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
              ? 'service-accounts')
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(
                  COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
              ) AS membership_group(value)
              WHERE membership_group.value LIKE 'datariver-role-%'
          )
          AND COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)
              = '{_ADMIN_ACTIONS}'::jsonb
          AND COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb) = '[]'::jsonb
          AND COALESCE(membership.attributes -> 'allowed_system_ids', '[]'::jsonb) = '[]'::jsonb;
        IF active_binding_count <= 1 THEN
            RAISE EXCEPTION 'The last Canonical Admin cannot be demoted'
                USING ERRCODE = '23514';
        END IF;
        next_actions := {_profile_action_case("p_next_tier")};
        next_actions_hash := {_profile_hash_case("p_next_tier")};
        SELECT COALESCE(jsonb_agg(value ORDER BY ordinal), '[]'::jsonb)
          INTO filtered_groups
        FROM jsonb_array_elements_text(
            COALESCE(target_membership.attributes -> 'groups', '[]'::jsonb)
        ) WITH ORDINALITY AS item(value, ordinal)
        WHERE value <> 'security-administrators' AND value NOT LIKE 'datariver-role-%';
        next_attributes := target_membership.attributes - 'role_id' - 'managed_by';
        next_attributes := jsonb_set(next_attributes, '{{groups}}', filtered_groups, true);
        next_attributes := jsonb_set(next_attributes, '{{allowed_actions}}', next_actions, true);
        next_attributes := jsonb_set(next_attributes, '{{allowed_system_ids}}', '[]'::jsonb, true);
        UPDATE iam.workspace_memberships
        SET clearance = GREATEST(clearance, 2), attributes = next_attributes,
            version = version + 1, updated_at = transaction_timestamp()
        WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id
        RETURNING version INTO next_membership_version;
        next_binding_version := current_binding.version + 1;
        UPDATE iam.canonical_admin_bindings
        SET state = 'REVOKED', membership_version = next_membership_version,
            membership_access_hash = p_access_payload_hash,
            version = next_binding_version, updated_at = transaction_timestamp()
        WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id;
        IF previous_profile.workspace_id IS NULL THEN
            next_assignment_version := 1;
            INSERT INTO iam.profile_role_assignments (
                workspace_id, subject_id, tier, policy_version,
                materialized_actions_hash, membership_version, state, assigned_by,
                reason, assurance, version, created_at, updated_at
            ) VALUES (
                p_workspace_id, p_target_subject_id, p_next_tier,
                '{PROFILE_ROLE_POLICY_VERSION}', next_actions_hash,
                next_membership_version, 'ACTIVE', actor_id, trim(p_reason), p_assurance,
                1, transaction_timestamp(), transaction_timestamp()
            );
        ELSE
            next_assignment_version := previous_profile.version + 1;
            UPDATE iam.profile_role_assignments
            SET tier = p_next_tier, policy_version = '{PROFILE_ROLE_POLICY_VERSION}',
                materialized_actions_hash = next_actions_hash,
                membership_version = next_membership_version, state = 'ACTIVE',
                assigned_by = actor_id, reason = trim(p_reason), assurance = p_assurance,
                version = next_assignment_version, updated_at = transaction_timestamp()
            WHERE workspace_id = p_workspace_id AND subject_id = p_target_subject_id;
        END IF;
        INSERT INTO iam.profile_role_assignment_events (
            id, workspace_id, subject_id, event_type, previous_tier, next_tier,
            policy_version, membership_version, assignment_version, actor_id,
            policy_decision_id,
            reason, assurance, occurred_at
        ) VALUES (
            gen_random_uuid(), p_workspace_id, p_target_subject_id,
            'DEMOTED_FROM_ADMIN', 'ADMIN', p_next_tier,
            '{PROFILE_ROLE_POLICY_VERSION}', next_membership_version,
            next_assignment_version, actor_id, p_policy_decision_id, trim(p_reason), p_assurance,
            transaction_timestamp()
        );
    END IF;
    RETURN QUERY SELECT next_membership_version, next_assignment_version, next_binding_version;
END
$datariver$
""".strip()


PROFILE_ROLE_SECURITY_SQL = (
    "ALTER TABLE iam.profile_role_assignments ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE iam.profile_role_assignments FORCE ROW LEVEL SECURITY",
    "ALTER TABLE iam.profile_role_assignment_events ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE iam.profile_role_assignment_events FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS profile_role_assignments_workspace ON iam.profile_role_assignments",
    "DROP POLICY IF EXISTS profile_role_assignment_events_workspace "
    "ON iam.profile_role_assignment_events",
    """
CREATE POLICY profile_role_assignments_workspace ON iam.profile_role_assignments
    USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
""".strip(),
    """
CREATE POLICY profile_role_assignment_events_workspace
    ON iam.profile_role_assignment_events
    USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
""".strip(),
    "DROP POLICY IF EXISTS canonical_admin_bindings_governed_insert "
    "ON iam.canonical_admin_bindings",
    "DROP POLICY IF EXISTS canonical_admin_bindings_governed_update "
    "ON iam.canonical_admin_bindings",
    """
CREATE POLICY canonical_admin_bindings_governed_insert
    ON iam.canonical_admin_bindings FOR INSERT WITH CHECK (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
        AND subject_id <> NULLIF(current_setting('app.subject_id', true), '')::uuid
        AND binding_source = 'GOVERNED_ADMIN_ASSIGNMENT'
    )
""".strip(),
    """
CREATE POLICY canonical_admin_bindings_governed_update
    ON iam.canonical_admin_bindings FOR UPDATE USING (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
        AND subject_id <> NULLIF(current_setting('app.subject_id', true), '')::uuid
    ) WITH CHECK (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
        AND subject_id <> NULLIF(current_setting('app.subject_id', true), '')::uuid
        AND binding_source IN ('LOCAL_DEVELOPMENT_BOOTSTRAP', 'GOVERNED_ADMIN_ASSIGNMENT')
    )
""".strip(),
    "REVOKE ALL ON iam.profile_role_assignments FROM PUBLIC",
    "REVOKE ALL ON iam.profile_role_assignment_events FROM PUBLIC",
    f"REVOKE ALL ON FUNCTION {PROFILE_ROLE_ASSIGNMENT_SIGNATURE} FROM PUBLIC",
    f"REVOKE ALL ON FUNCTION {CANONICAL_ADMIN_PROFILE_TRANSITION_SIGNATURE} FROM PUBLIC",
    f"""
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT SELECT ON iam.profile_role_assignments,
            iam.profile_role_assignment_events TO datariver_app;
        REVOKE INSERT, UPDATE, DELETE ON iam.profile_role_assignments,
            iam.profile_role_assignment_events FROM datariver_app;
        GRANT EXECUTE ON FUNCTION {PROFILE_ROLE_ASSIGNMENT_SIGNATURE} TO datariver_app;
        GRANT EXECUTE ON FUNCTION {CANONICAL_ADMIN_PROFILE_TRANSITION_SIGNATURE}
            TO datariver_app;
    END IF;
END
$datariver$;
""".strip(),
)
