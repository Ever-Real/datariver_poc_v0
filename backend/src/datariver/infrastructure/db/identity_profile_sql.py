from __future__ import annotations

IDENTITY_PROFILE_UPDATE_SIGNATURE = (
    "iam.update_workspace_identity_profile(uuid, uuid, integer, text, text, uuid, text)"
)

IDENTITY_PROFILE_UPDATE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION iam.update_workspace_identity_profile(
    p_workspace_id uuid,
    p_subject_id uuid,
    p_expected_membership_version integer,
    p_display_name text,
    p_email text,
    p_department_id uuid,
    p_job_function text
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, iam, platform
AS $datariver$
DECLARE
    actor_id uuid;
    target_membership_version integer;
    target_membership_active boolean;
    target_subject_active boolean;
    target_access_expires_at timestamptz;
    target_job_function text;
    target_attributes jsonb;
    next_version integer;
BEGIN
    actor_id := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    IF actor_id IS NULL OR NULLIF(current_setting('app.workspace_id', true), '')::uuid
       IS DISTINCT FROM p_workspace_id THEN
        RAISE EXCEPTION 'A matching DataRiver security context is required'
            USING ERRCODE = '42501';
    END IF;
    IF p_expected_membership_version < 1
       OR char_length(COALESCE(p_display_name, '')) NOT BETWEEN 1 AND 255
       OR char_length(COALESCE(p_email, '')) NOT BETWEEN 3 AND 320
       OR (
           p_job_function IS NOT NULL
           AND char_length(p_job_function) NOT BETWEEN 1 AND 100
       )
       OR COALESCE(p_job_function, '') = 'SERVICE_ACCOUNT' THEN
        RAISE EXCEPTION 'The identity profile document is outside the governed bound'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    JOIN platform.workspaces AS workspace ON workspace.id = membership.workspace_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = actor_id
      AND subject.active IS TRUE
      AND membership.active IS TRUE
      AND workspace.status = 'ACTIVE'
      AND (
          membership.access_expires_at IS NULL
          OR membership.access_expires_at > transaction_timestamp()
      )
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND membership.clearance >= 3
      AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'security-administrators'
      AND NOT (
          COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'service-accounts'
      )
      AND COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)
          ? 'admin.manage'
      AND NOT (
          COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb)
          ? 'admin.manage'
      )
    FOR KEY SHARE OF membership, subject, workspace;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'An eligible human security administrator is required'
            USING ERRCODE = '42501';
    END IF;
    SELECT
        membership.version,
        membership.active,
        subject.active,
        membership.access_expires_at,
        membership.job_function,
        membership.attributes
    INTO
        target_membership_version,
        target_membership_active,
        target_subject_active,
        target_access_expires_at,
        target_job_function,
        target_attributes
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = p_subject_id
    FOR UPDATE OF membership, subject;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The target workspace identity does not exist'
            USING ERRCODE = 'P0002';
    END IF;
    IF target_membership_version <> p_expected_membership_version THEN
        RAISE EXCEPTION 'The target workspace identity changed'
            USING ERRCODE = '40001';
    END IF;
    IF NOT target_membership_active
       OR NOT target_subject_active
       OR (
           target_access_expires_at IS NOT NULL
           AND target_access_expires_at <= transaction_timestamp()
       )
       OR COALESCE(target_job_function, '') = 'SERVICE_ACCOUNT'
       OR COALESCE(target_attributes -> 'groups', '[]'::jsonb)
          ? 'service-accounts' THEN
        RAISE EXCEPTION 'Only an active human identity can be updated'
            USING ERRCODE = '23514';
    END IF;
    UPDATE iam.subjects
    SET display_name = p_display_name,
        email = p_email,
        updated_at = transaction_timestamp()
    WHERE id = p_subject_id;
    UPDATE iam.workspace_memberships
    SET department_id = p_department_id,
        job_function = p_job_function,
        version = version + 1,
        updated_at = transaction_timestamp()
    WHERE workspace_id = p_workspace_id
      AND subject_id = p_subject_id
    RETURNING version INTO next_version;
    RETURN next_version;
END
$datariver$
""".strip()
