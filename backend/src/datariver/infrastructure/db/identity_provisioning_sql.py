from __future__ import annotations

IDENTITY_PROVISIONING_SIGNATURE = (
    "iam.provision_workspace_identity(uuid, uuid, text, text, text, text, "
    "uuid, text, uuid, timestamptz)"
)

IDENTITY_PROVISIONING_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION iam.provision_workspace_identity(
    p_subject_id uuid, p_workspace_id uuid, p_issuer text, p_external_subject text,
    p_display_name text, p_email text, p_department_id uuid, p_job_function text,
    p_role_id uuid, p_access_expires_at timestamptz
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, iam, platform
AS $datariver$
DECLARE
    actor_id uuid;
    existing_subject_id uuid;
    access_clearance integer := 0;
    access_attributes jsonb := jsonb_build_object(
        'groups', jsonb_build_array(), 'allowed_actions', jsonb_build_array(),
        'denied_actions', jsonb_build_array(), 'allowed_system_ids', jsonb_build_array(),
        'allowed_domain_ids', jsonb_build_array(), 'default_workspace', true,
        'managed_by', 'IDENTITY_PROVISIONING_V1'
    );
    selected_role iam.access_roles%ROWTYPE;
BEGIN
    actor_id := NULLIF(current_setting('app.subject_id', true), '')::uuid;
    IF actor_id IS NULL OR NULLIF(current_setting('app.workspace_id', true), '')::uuid
       IS DISTINCT FROM p_workspace_id THEN
        RAISE EXCEPTION 'A matching DataRiver security context is required'
            USING ERRCODE = '42501';
    END IF;
    IF p_access_expires_at <= transaction_timestamp()
       OR p_access_expires_at > transaction_timestamp() + INTERVAL '7 months' THEN
        RAISE EXCEPTION 'The initial access expiration is outside the governed bound'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1
    FROM iam.workspace_memberships AS membership
    JOIN iam.subjects AS subject ON subject.id = membership.subject_id
    JOIN platform.workspaces AS workspace ON workspace.id = membership.workspace_id
    WHERE membership.workspace_id = p_workspace_id
      AND membership.subject_id = actor_id
      AND subject.active IS TRUE AND membership.active IS TRUE
      AND workspace.status = 'ACTIVE'
      AND (membership.access_expires_at IS NULL
           OR membership.access_expires_at > transaction_timestamp())
      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
      AND membership.clearance >= 3
      AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'security-administrators'
      AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
          ? 'service-accounts')
      AND COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)
          ? 'admin.manage'
      AND NOT (COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb)
          ? 'admin.manage')
    FOR KEY SHARE OF membership, subject, workspace;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'An eligible human security administrator is required'
            USING ERRCODE = '42501';
    END IF;
    IF p_role_id IS NOT NULL THEN
        SELECT * INTO selected_role FROM iam.access_roles
        WHERE workspace_id = p_workspace_id AND id = p_role_id AND active IS TRUE
          AND role_kind = 'HUMAN_ROLE'
        FOR KEY SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The selected workspace role is not an assignable human role'
                USING ERRCODE = '23514';
        END IF;
        access_clearance := selected_role.clearance;
        access_attributes := jsonb_build_object(
            'groups', selected_role.groups
                || jsonb_build_array('datariver-role-' || selected_role.role_key),
            'allowed_actions', selected_role.allowed_actions,
            'denied_actions', selected_role.denied_actions,
            'allowed_system_ids', selected_role.allowed_system_ids,
            'allowed_domain_ids', selected_role.allowed_domain_ids,
            'default_workspace', true, 'role_id', selected_role.id::text,
            'managed_by', 'IDENTITY_PROVISIONING_V1'
        );
    END IF;
    SELECT id INTO existing_subject_id FROM iam.subjects
    WHERE issuer = p_issuer AND external_subject = p_external_subject FOR KEY SHARE;
    IF FOUND THEN
        IF existing_subject_id IS DISTINCT FROM p_subject_id THEN
            RAISE EXCEPTION 'The external identity is already bound to another subject'
                USING ERRCODE = '23505';
        END IF;
        RETURN existing_subject_id;
    END IF;
    INSERT INTO iam.subjects (
        id, issuer, external_subject, display_name, email, active, created_at, updated_at
    ) VALUES (
        p_subject_id, p_issuer, p_external_subject, p_display_name, p_email, TRUE,
        transaction_timestamp(), transaction_timestamp()
    );
    INSERT INTO iam.workspace_memberships (
        workspace_id, subject_id, department_id, job_function, clearance, attributes,
        active, access_expires_at, version, created_at, updated_at
    ) VALUES (
        p_workspace_id, p_subject_id, p_department_id, p_job_function,
        access_clearance, access_attributes, TRUE, p_access_expires_at,
        1, transaction_timestamp(), transaction_timestamp()
    );
    RETURN p_subject_id;
END
$datariver$
""".strip()

# The 0089 downgrade restores the exact pre-canonical-role function. Keeping the
# legacy body derived beside the current function avoids a second drifting copy
# of the otherwise identical security-definer contract.
IDENTITY_PROVISIONING_FUNCTION_SQL_V1 = (
    IDENTITY_PROVISIONING_FUNCTION_SQL.replace(
        " AND active IS TRUE\n          AND role_kind = 'HUMAN_ROLE'",
        " AND active IS TRUE",
    )
    .replace(
        "The selected workspace role is not an assignable human role",
        "The selected workspace role is not active",
    )
    .replace(
        "ERRCODE = '23514';\n        END IF;\n        access_clearance := selected_role.clearance;",
        "ERRCODE = '23503';\n        END IF;\n        access_clearance := selected_role.clearance;",
    )
)
