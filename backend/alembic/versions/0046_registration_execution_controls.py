"""Fence registration workers and retain bounded Manual read-back evidence.

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
EXPECTED_OBJECT_COUNT = 10


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'governance'
                       AND table_name = 'manual_metadata_submissions'
                       AND column_name IN (
                           'next_attempt_at', 'lease_epoch', 'lease_token_hash',
                           'lease_owner_id', 'lease_started_at',
                           'provider_source_version'
                       ))
                  + (SELECT count(*) FROM information_schema.tables
                     WHERE table_schema = 'governance'
                       AND table_name IN (
                           'manual_metadata_apply_attempts',
                           'manual_metadata_aspect_reports'
                       ))
                  + (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'integration'
                       AND table_name = 'upload_preparation_jobs'
                       AND column_name = 'next_attempt_at')
                  + (SELECT count(*) FROM pg_constraint
                     WHERE conname = 'ck_manual_metadata_submissions_lease_shape')
                """
            )
        )
        .scalar_one()
    )


def _assert_existing_contract() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('governance', 'manual_metadata_submissions',
                         'next_attempt_at', 'timestamp with time zone', 'YES', -1),
                        ('governance', 'manual_metadata_submissions',
                         'lease_epoch', 'integer', 'NO', -1),
                        ('governance', 'manual_metadata_submissions',
                         'lease_token_hash', 'character varying', 'YES', 64),
                        ('governance', 'manual_metadata_submissions',
                         'lease_owner_id', 'uuid', 'YES', -1),
                        ('governance', 'manual_metadata_submissions',
                         'lease_started_at', 'timestamp with time zone', 'YES', -1),
                        ('governance', 'manual_metadata_submissions',
                         'provider_source_version', 'character varying', 'NO', 64),
                        ('integration', 'upload_preparation_jobs',
                         'next_attempt_at', 'timestamp with time zone', 'YES', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'workspace_id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'submission_id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'attempt_no', 'integer', 'NO', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'lease_epoch', 'integer', 'NO', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'lease_token_hash', 'character varying', 'NO', 64),
                        ('governance', 'manual_metadata_apply_attempts',
                         'worker_subject_id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'state', 'character varying', 'NO', 32),
                        ('governance', 'manual_metadata_apply_attempts',
                         'failure_code', 'character varying', 'YES', 100),
                        ('governance', 'manual_metadata_apply_attempts',
                         'report_root_hash', 'character varying', 'YES', 64),
                        ('governance', 'manual_metadata_apply_attempts',
                         'started_at', 'timestamp with time zone', 'NO', -1),
                        ('governance', 'manual_metadata_apply_attempts',
                         'finished_at', 'timestamp with time zone', 'YES', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'workspace_id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'submission_id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'attempt_id', 'uuid', 'NO', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'aspect_name', 'character varying', 'NO', 64),
                        ('governance', 'manual_metadata_aspect_reports',
                         'aspect_ordinal', 'integer', 'NO', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'outcome', 'character varying', 'NO', 32),
                        ('governance', 'manual_metadata_aspect_reports',
                         'before_hash', 'character varying', 'YES', 64),
                        ('governance', 'manual_metadata_aspect_reports',
                         'expected_hash', 'character varying', 'YES', 64),
                        ('governance', 'manual_metadata_aspect_reports',
                         'observed_hash', 'character varying', 'YES', 64),
                        ('governance', 'manual_metadata_aspect_reports',
                         'write_attempted', 'boolean', 'NO', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'failure_code', 'character varying', 'YES', 100),
                        ('governance', 'manual_metadata_aspect_reports',
                         'provider_operation_id_hash', 'character varying', 'YES', 64),
                        ('governance', 'manual_metadata_aspect_reports',
                         'provider_version', 'character varying', 'YES', 255),
                        ('governance', 'manual_metadata_aspect_reports',
                         'provider_response_hash', 'character varying', 'YES', 64),
                        ('governance', 'manual_metadata_aspect_reports',
                         'observed_at', 'timestamp with time zone', 'NO', -1),
                        ('governance', 'manual_metadata_aspect_reports',
                         'created_at', 'timestamp with time zone', 'NO', -1)
                ) AS expected(
                    table_schema,
                    table_name,
                    column_name,
                    data_type,
                    is_nullable,
                    character_maximum_length
                )
                LEFT JOIN information_schema.columns AS actual
                  ON actual.table_schema = expected.table_schema
                 AND actual.table_name = expected.table_name
                 AND actual.column_name = expected.column_name
                WHERE actual.column_name IS NULL
                   OR actual.data_type <> expected.data_type
                   OR actual.is_nullable <> expected.is_nullable
                   OR (
                       expected.character_maximum_length >= 0
                       AND actual.character_maximum_length <>
                           expected.character_maximum_length
                   )
            ) THEN
                RAISE EXCEPTION
                    'registration execution columns do not match the canonical contract';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'governance.manual_metadata_submissions'::regclass
                  AND conname = 'ck_manual_metadata_submissions_lease_shape'
                  AND pg_get_constraintdef(oid) LIKE
                      '%lease_expires_at > lease_started_at%'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'governance.manual_metadata_submissions'::regclass
                  AND conname =
                      'fk_manual_metadata_submissions_lease_owner'
                  AND pg_get_constraintdef(oid) LIKE
                      '%FOREIGN KEY (workspace_id, lease_owner_id)%'
                  AND pg_get_constraintdef(oid) LIKE
                      '%REFERENCES iam.workspace_memberships(workspace_id, subject_id)%'
                  AND pg_get_constraintdef(oid) LIKE '%ON DELETE RESTRICT%'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'governance.manual_metadata_apply_attempts'::regclass
                  AND conname =
                      'ck_manual_metadata_apply_attempts_terminal_shape'
                  AND pg_get_constraintdef(oid) LIKE
                      '%report_root_hash%'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'governance.manual_metadata_aspect_reports'::regclass
                  AND conname =
                      'ck_manual_metadata_aspect_reports_verified_outcome_shape'
                  AND pg_get_constraintdef(oid) LIKE
                      '%expected_hash%observed_hash%APPLIED_VERIFIED%'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'governance.manual_metadata_submissions'::regclass
                  AND conname =
                      'ck_manual_metadata_submissions_provider_source_version_valid'
                  AND convalidated IS TRUE
                  AND pg_get_constraintdef(oid) LIKE
                      '%provider_source_version%^[0-9a-f]{64}$%'
            ) THEN
                RAISE EXCEPTION
                    'registration execution constraints do not match the canonical contract';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('manual_metadata_apply_attempts',
                         'uq_manual_metadata_apply_attempts_workspace_id_id', 'u',
                         'UNIQUE (workspace_id, id)'),
                        ('manual_metadata_apply_attempts',
                         'uq_manual_metadata_apply_attempts_workspace_id_submission_id_id', 'u',
                         'UNIQUE (workspace_id, submission_id, id)'),
                        ('manual_metadata_apply_attempts',
                         'uq_manual_metadata_apply_attempts_workspace_id_submissi_d35a',
                         'u', 'UNIQUE (workspace_id, submission_id, attempt_no)'),
                        ('manual_metadata_apply_attempts',
                         'uq_manual_metadata_apply_attempts_workspace_id_submissi_3bb7',
                         'u', 'UNIQUE (workspace_id, submission_id, lease_epoch)'),
                        ('manual_metadata_apply_attempts',
                         'fk_manual_apply_attempts_submission', 'f',
                         concat(
                             'FOREIGN KEY (workspace_id, submission_id) REFERENCES ',
                             'governance.manual_metadata_submissions(workspace_id, id) ',
                             'ON DELETE RESTRICT'
                         )),
                        ('manual_metadata_apply_attempts',
                         'fk_manual_apply_attempts_worker', 'f',
                         concat(
                             'FOREIGN KEY (workspace_id, worker_subject_id) REFERENCES ',
                             'iam.workspace_memberships(workspace_id, subject_id) ',
                             'ON DELETE RESTRICT'
                         )),
                        ('manual_metadata_apply_attempts',
                         'ck_manual_metadata_apply_attempts_attempt_fence_positive', 'c',
                         'attempt_no > 0'),
                        ('manual_metadata_apply_attempts',
                         'ck_manual_metadata_apply_attempts_lease_token_hash_valid', 'c',
                         'lease_token_hash'),
                        ('manual_metadata_apply_attempts',
                         'ck_manual_metadata_apply_attempts_state_vocabulary', 'c',
                         'SUPERSEDED'),
                        ('manual_metadata_apply_attempts',
                         'ck_manual_metadata_apply_attempts_terminal_shape', 'c',
                         'report_root_hash'),
                        ('manual_metadata_aspect_reports',
                         'uq_manual_metadata_aspect_reports_workspace_id_id', 'u',
                         'UNIQUE (workspace_id, id)'),
                        ('manual_metadata_aspect_reports',
                         'uq_manual_metadata_aspect_reports_workspace_id_attempt__e222',
                         'u', 'UNIQUE (workspace_id, attempt_id, aspect_name)'),
                        ('manual_metadata_aspect_reports',
                         'fk_manual_aspect_reports_submission', 'f',
                         concat(
                             'FOREIGN KEY (workspace_id, submission_id) REFERENCES ',
                             'governance.manual_metadata_submissions(workspace_id, id) ',
                             'ON DELETE RESTRICT'
                         )),
                        ('manual_metadata_aspect_reports',
                         'fk_manual_aspect_reports_attempt', 'f',
                         concat(
                             'FOREIGN KEY (workspace_id, submission_id, attempt_id) ',
                             'REFERENCES governance.manual_metadata_apply_attempts',
                             '(workspace_id, submission_id, id) ON DELETE RESTRICT'
                         )),
                        ('manual_metadata_aspect_reports',
                         'ck_manual_metadata_aspect_reports_aspect_ordinal_contract', 'c',
                         'schemaMetadata'),
                        ('manual_metadata_aspect_reports',
                         'ck_manual_metadata_aspect_reports_outcome_vocabulary', 'c',
                         'READBACK_MISMATCH'),
                        ('manual_metadata_aspect_reports',
                         'ck_manual_metadata_aspect_reports_content_hashes_valid', 'c',
                         'failure_code'),
                        ('manual_metadata_aspect_reports',
                         'ck_manual_metadata_aspect_reports_verified_outcome_shape', 'c',
                         'WRITE_REJECTED')
                ) AS expected(table_name, constraint_name, constraint_type, fragment)
                LEFT JOIN pg_constraint AS actual
                  ON actual.conrelid =
                        format('governance.%I', expected.table_name)::regclass
                 AND actual.conname = expected.constraint_name
                WHERE actual.oid IS NULL
                   OR actual.contype::text <> expected.constraint_type
                   OR actual.convalidated IS NOT TRUE
                   OR position(
                       expected.fragment IN pg_get_constraintdef(actual.oid)
                   ) = 0
            ) THEN
                RAISE EXCEPTION
                    'registration evidence constraints are missing, unvalidated, or drifted';
            END IF;
        END
        $datariver$
        """
    )


def _assert_runtime_contract() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            expected_workspace_policy text :=
                '(workspace_id = (NULLIF(current_setting(''app.workspace_id''::text, '
                || 'true), ''''::text))::uuid)';
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('governance', 'manual_metadata_apply_attempts'),
                        ('governance', 'manual_metadata_aspect_reports')
                ) AS expected(schema_name, table_name)
                LEFT JOIN pg_namespace AS namespace
                  ON namespace.nspname = expected.schema_name
                LEFT JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = expected.table_name
                WHERE relation.oid IS NULL
                   OR relation.relrowsecurity IS NOT TRUE
                   OR relation.relforcerowsecurity IS NOT TRUE
            ) THEN
                RAISE EXCEPTION 'registration execution RLS is not forced';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('manual_metadata_apply_attempts', 'workspace_isolation',
                         'PERMISSIVE', 'ALL'),
                        ('manual_metadata_apply_attempts',
                         'manual_metadata_attempt_reader_scope',
                         'RESTRICTIVE', 'SELECT'),
                        ('manual_metadata_aspect_reports', 'workspace_isolation',
                         'PERMISSIVE', 'ALL'),
                        ('manual_metadata_aspect_reports',
                         'manual_metadata_aspect_reader_scope',
                         'RESTRICTIVE', 'SELECT')
                ) AS expected(table_name, policy_name, permissive, command)
                LEFT JOIN pg_policies AS policy
                  ON policy.schemaname = 'governance'
                 AND policy.tablename = expected.table_name
                 AND policy.policyname = expected.policy_name
                WHERE policy.policyname IS NULL
                   OR policy.permissive <> expected.permissive
                   OR policy.cmd <> expected.command
                   OR (
                       expected.policy_name = 'workspace_isolation'
                       AND (
                           policy.qual IS DISTINCT FROM
                               expected_workspace_policy
                           OR policy.with_check IS DISTINCT FROM
                               expected_workspace_policy
                       )
                   )
            ) THEN
                RAISE EXCEPTION 'registration execution RLS policies are invalid';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgrelid =
                    'governance.manual_metadata_apply_attempts'::regclass
                  AND tgname = 'reject_manual_apply_attempt_mutation'
                  AND tgenabled <> 'D'
                  AND tgtype = 31
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgrelid =
                    'governance.manual_metadata_aspect_reports'::regclass
                  AND tgname = 'reject_manual_aspect_report_mutation'
                  AND tgenabled <> 'D'
                  AND tgtype = 31
            ) OR position(
                'provider_source_version' IN pg_get_functiondef(
                    'governance.reject_manual_metadata_payload_mutation()'::regprocedure
                )
            ) = 0
            OR position(
                'app.manual_metadata_lease_token' IN pg_get_functiondef(
                    'governance.manual_metadata_raw_token_matches(text)'::regprocedure
                )
            ) = 0
            OR position(
                'manual_metadata_raw_token_matches' IN pg_get_functiondef(
                    'governance.reject_manual_metadata_payload_mutation()'::regprocedure
                )
            ) = 0
            OR position(
                'manual_metadata_raw_token_matches' IN pg_get_functiondef(
                    'governance.reject_manual_apply_attempt_mutation()'::regprocedure
                )
            ) = 0
            THEN
                RAISE EXCEPTION 'registration execution evidence triggers are invalid';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('governance', 'manual_metadata_submissions',
                         'ix_manual_metadata_submissions_claim', false,
                         '(workspace_id, next_attempt_at, created_at, id)',
                         'state::text = ''QUEUED''::text'),
                        ('governance', 'manual_metadata_submissions',
                         'ix_manual_metadata_submissions_requester', false,
                         '(workspace_id, requester_id, created_at, id)', NULL),
                        ('governance', 'manual_metadata_submissions',
                         'uq_manual_metadata_submissions_active_asset', true,
                         '(workspace_id, asset_id)',
                         'state::text = ''APPLYING''::text'),
                        ('governance', 'manual_metadata_apply_attempts',
                         'ix_manual_apply_attempts_submission', false,
                         '(workspace_id, submission_id, attempt_no)', NULL),
                        ('governance', 'manual_metadata_aspect_reports',
                         'ix_manual_aspect_reports_attempt', false,
                         '(workspace_id, attempt_id, aspect_ordinal)', NULL),
                        ('governance', 'change_requests',
                         'ix_change_requests_workspace_created_id', false,
                         '(workspace_id, created_at, id)', NULL),
                        ('governance', 'change_requests',
                         'ix_change_requests_workspace_state_created_id', false,
                         '(workspace_id, state, created_at, id)', NULL),
                        ('integration', 'upload_preparation_jobs',
                         'ix_upload_preparation_jobs_claim', false,
                         '(state, next_attempt_at, lease_until, created_at)', NULL)
                ) AS expected(
                    schema_name,
                    table_name,
                    index_name,
                    is_unique,
                    column_fragment,
                    expected_predicate
                )
                LEFT JOIN pg_namespace AS namespace
                  ON namespace.nspname = expected.schema_name
                LEFT JOIN pg_class AS table_relation
                  ON table_relation.relnamespace = namespace.oid
                 AND table_relation.relname = expected.table_name
                LEFT JOIN pg_class AS index_relation
                  ON index_relation.relnamespace = namespace.oid
                 AND index_relation.relname = expected.index_name
                LEFT JOIN pg_index AS index_contract
                  ON index_contract.indrelid = table_relation.oid
                 AND index_contract.indexrelid = index_relation.oid
                WHERE index_contract.indexrelid IS NULL
                   OR index_contract.indisvalid IS NOT TRUE
                   OR index_contract.indisready IS NOT TRUE
                   OR index_contract.indisunique <> expected.is_unique
                   OR position(
                       expected.column_fragment IN
                       pg_get_indexdef(index_contract.indexrelid)
                   ) = 0
                   OR pg_get_expr(
                       index_contract.indpred,
                       index_contract.indrelid,
                       true
                   ) IS DISTINCT FROM expected.expected_predicate
            ) THEN
                RAISE EXCEPTION
                    'registration execution indexes are incomplete or drifted';
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app')
               AND (
                   has_table_privilege(
                       'datariver_app',
                       'governance.manual_metadata_submissions',
                       'UPDATE'
                   )
                   OR has_table_privilege(
                       'datariver_app',
                       'governance.manual_metadata_submissions',
                       'DELETE'
                   )
                   OR has_table_privilege(
                       'datariver_app',
                       'governance.manual_metadata_apply_attempts',
                       'UPDATE'
                   )
                   OR has_table_privilege(
                       'datariver_app',
                       'governance.manual_metadata_apply_attempts',
                       'DELETE'
                   )
                   OR has_table_privilege(
                       'datariver_app',
                       'governance.manual_metadata_aspect_reports',
                       'UPDATE'
                   )
                   OR has_table_privilege(
                       'datariver_app',
                       'governance.manual_metadata_aspect_reports',
                       'DELETE'
                   )
               ) THEN
                RAISE EXCEPTION
                    'datariver_app has broad mutation privileges over immutable evidence';
            END IF;
        END
        $datariver$
        """
    )


def _enable_workspace_rls(table: str) -> None:
    op.execute(f"ALTER TABLE governance.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE governance.{table} FORCE ROW LEVEL SECURITY")
    policy_statement = f"""
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'governance'
                  AND tablename = '{table}'
                  AND policyname = 'workspace_isolation'
            ) THEN
                CREATE POLICY workspace_isolation ON governance.{table}
                USING (workspace_id = {RLS_SETTING})
                WITH CHECK (workspace_id = {RLS_SETTING});
            END IF;
        END
        $datariver$
        """  # noqa: S608 -- table is selected only from migration-owned constants.
    op.execute(policy_statement)


def _install_security_contract() -> None:
    _enable_workspace_rls("manual_metadata_apply_attempts")
    _enable_workspace_rls("manual_metadata_aspect_reports")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.can_read_manual_metadata_submission(
            p_workspace_id uuid,
            p_requester_id uuid
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, iam
        AS $function$
            SELECT EXISTS (
                SELECT 1
                FROM iam.workspace_memberships AS membership
                JOIN iam.subjects AS subject
                  ON subject.id = membership.subject_id
                WHERE membership.workspace_id = p_workspace_id
                  AND membership.subject_id =
                      NULLIF(current_setting('app.subject_id', true), '')::uuid
                  AND membership.active IS TRUE
                  AND subject.active IS TRUE
                  AND (
                      membership.access_expires_at IS NULL
                      OR membership.access_expires_at > transaction_timestamp()
                  )
                  AND (
                      (
                          COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
                          AND NOT (
                              COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                              ? 'service-accounts'
                          )
                          AND (
                              (
                                  COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                                  ? 'security-administrators'
                              )
                              OR (
                                  membership.job_function = 'DATA_STEWARD'
                                  AND (
                                      COALESCE(
                                          membership.attributes -> 'groups',
                                          '[]'::jsonb
                                      ) ? 'data-stewards'
                                  )
                                  AND membership.subject_id = p_requester_id
                              )
                          )
                          AND (
                              COALESCE(
                                  membership.attributes -> 'allowed_actions',
                                  '[]'::jsonb
                              ) ? 'registration.read'
                          )
                          AND NOT (
                              COALESCE(
                                  membership.attributes -> 'denied_actions',
                                  '[]'::jsonb
                              ) ? 'registration.read'
                          )
                      )
                      OR (
                          membership.job_function = 'SERVICE_ACCOUNT'
                          AND (
                              COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                              ? 'service-accounts'
                          )
                          AND (
                              COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                              ? 'registration-workers'
                          )
                          AND (
                              COALESCE(
                                  membership.attributes -> 'allowed_actions',
                                  '[]'::jsonb
                              ) ? 'catalog.sync'
                          )
                          AND NOT (
                              COALESCE(
                                  membership.attributes -> 'denied_actions',
                                  '[]'::jsonb
                              ) ? 'catalog.sync'
                          )
                      )
                  )
            )
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "governance.can_read_manual_metadata_submission(uuid, uuid) FROM PUBLIC"
    )
    op.execute(
        "DROP POLICY IF EXISTS manual_metadata_reader_scope "
        "ON governance.manual_metadata_submissions"
    )
    op.execute(
        """
        CREATE POLICY manual_metadata_reader_scope
        ON governance.manual_metadata_submissions
        AS RESTRICTIVE
        FOR SELECT
        USING (
            current_user <> 'datariver_app'
            OR governance.can_read_manual_metadata_submission(
                workspace_id,
                requester_id
            )
        )
        """
    )
    op.execute(
        "DROP POLICY IF EXISTS manual_metadata_attempt_reader_scope "
        "ON governance.manual_metadata_apply_attempts"
    )
    op.execute(
        """
        CREATE POLICY manual_metadata_attempt_reader_scope
        ON governance.manual_metadata_apply_attempts
        AS RESTRICTIVE
        FOR SELECT
        USING (
            current_user <> 'datariver_app'
            OR EXISTS (
                SELECT 1
                FROM governance.manual_metadata_submissions AS submission
                WHERE submission.workspace_id =
                    manual_metadata_apply_attempts.workspace_id
                  AND submission.id =
                    manual_metadata_apply_attempts.submission_id
                  AND governance.can_read_manual_metadata_submission(
                      submission.workspace_id,
                      submission.requester_id
                  )
            )
        )
        """
    )
    op.execute(
        "DROP POLICY IF EXISTS manual_metadata_aspect_reader_scope "
        "ON governance.manual_metadata_aspect_reports"
    )
    op.execute(
        """
        CREATE POLICY manual_metadata_aspect_reader_scope
        ON governance.manual_metadata_aspect_reports
        AS RESTRICTIVE
        FOR SELECT
        USING (
            current_user <> 'datariver_app'
            OR EXISTS (
                SELECT 1
                FROM governance.manual_metadata_submissions AS submission
                WHERE submission.workspace_id =
                    manual_metadata_aspect_reports.workspace_id
                  AND submission.id =
                    manual_metadata_aspect_reports.submission_id
                  AND governance.can_read_manual_metadata_submission(
                      submission.workspace_id,
                      submission.requester_id
                  )
            )
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.manual_metadata_raw_token_matches(
            p_lease_token_hash text
        )
        RETURNS boolean
        LANGUAGE sql
        VOLATILE
        SECURITY INVOKER
        SET search_path = pg_catalog
        AS $function$
            SELECT
                NULLIF(
                    current_setting('app.manual_metadata_lease_token', true),
                    ''
                ) IS NOT NULL
                AND encode(
                    sha256(
                        convert_to(
                            current_setting(
                                'app.manual_metadata_lease_token',
                                true
                            ),
                            'UTF8'
                        )
                    ),
                    'hex'
                ) = p_lease_token_hash
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION governance.manual_metadata_raw_token_matches(text) FROM PUBLIC"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.reject_manual_metadata_payload_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, governance
        AS $function$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'manual metadata submission history is append-only'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.workspace_id <> NEW.workspace_id
               OR OLD.asset_id <> NEW.asset_id
               OR OLD.requester_id <> NEW.requester_id
               OR OLD.external_urn <> NEW.external_urn
               OR OLD.source_version <> NEW.source_version
               OR OLD.provider_source_version <> NEW.provider_source_version
               OR OLD.serial_number <> NEW.serial_number
               OR OLD.payload <> NEW.payload
               OR OLD.bucket <> NEW.bucket
               OR OLD.object_key <> NEW.object_key
               OR OLD.csv_sha256 <> NEW.csv_sha256
               OR OLD.csv_size_bytes <> NEW.csv_size_bytes
               OR OLD.row_count <> NEW.row_count
               OR OLD.created_at <> NEW.created_at THEN
                RAISE EXCEPTION 'manual metadata submission evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF current_user = 'datariver_app'
               AND (
                   OLD.state = 'APPLYING'
                   OR NEW.state = 'APPLYING'
               ) THEN
                -- An expired lease may only be closed with the fixed recovery
                -- outcome.  This deliberately cannot produce a successful
                -- business result and remains available to the bounded
                -- database-time recovery scan.
                IF OLD.state = 'APPLYING'
                   AND OLD.lease_expires_at <= transaction_timestamp()
                   AND NEW.state = 'FAILED'
                   AND NEW.last_error_code = 'WORKER_LEASE_EXHAUSTED'
                   AND NEW.applied_at IS NULL
                   AND NEW.attempts = OLD.attempts
                   AND NEW.lease_epoch = OLD.lease_epoch
                   AND NEW.next_attempt_at IS NULL
                   AND NEW.lease_token_hash IS NULL
                   AND NEW.lease_owner_id IS NULL
                   AND NEW.lease_started_at IS NULL
                   AND NEW.lease_expires_at IS NULL THEN
                    RETURN NEW;
                END IF;

                -- A new worker may reclaim an expired row, but the newly
                -- generated raw token must be present only in this transaction
                -- and must bind the complete new lease identity.
                IF OLD.state = 'APPLYING'
                   AND OLD.lease_expires_at <= transaction_timestamp()
                   AND NEW.state = 'APPLYING'
                   AND NEW.attempts = OLD.attempts + 1
                   AND NEW.lease_epoch = OLD.lease_epoch + 1
                   AND NEW.lease_owner_id =
                       NULLIF(current_setting('app.subject_id', true), '')::uuid
                   AND NEW.lease_started_at >= OLD.lease_expires_at
                   AND NEW.lease_expires_at > NEW.lease_started_at
                   AND governance.manual_metadata_raw_token_matches(
                       NEW.lease_token_hash
                   ) THEN
                    RETURN NEW;
                END IF;

                IF OLD.state = 'QUEUED'
                   AND NEW.state = 'APPLYING'
                   AND NEW.attempts = OLD.attempts + 1
                   AND NEW.lease_epoch = OLD.lease_epoch + 1
                   AND NEW.lease_owner_id =
                       NULLIF(current_setting('app.subject_id', true), '')::uuid
                   AND NEW.lease_started_at >= transaction_timestamp()
                   AND NEW.lease_expires_at > NEW.lease_started_at
                   AND governance.manual_metadata_raw_token_matches(
                       NEW.lease_token_hash
                   ) THEN
                    RETURN NEW;
                END IF;

                -- Every renewal or terminal transition under a live lease is
                -- fenced by the unguessable raw token, owner, epoch and
                -- database clock.  Lease identity is immutable until the
                -- terminal transition clears it.
                IF OLD.state = 'APPLYING'
                   AND OLD.lease_expires_at > transaction_timestamp()
                   AND OLD.lease_owner_id =
                       NULLIF(current_setting('app.subject_id', true), '')::uuid
                   AND governance.manual_metadata_raw_token_matches(
                       OLD.lease_token_hash
                   )
                   AND NEW.attempts = OLD.attempts
                   AND NEW.lease_epoch = OLD.lease_epoch
                   AND (
                       (
                           NEW.state = 'APPLYING'
                           AND NEW.lease_token_hash = OLD.lease_token_hash
                           AND NEW.lease_owner_id = OLD.lease_owner_id
                           AND NEW.lease_started_at = OLD.lease_started_at
                           AND NEW.lease_expires_at >= OLD.lease_expires_at
                       )
                       OR (
                           NEW.state IN ('QUEUED', 'APPLIED', 'FAILED')
                           AND NEW.lease_token_hash IS NULL
                           AND NEW.lease_owner_id IS NULL
                           AND NEW.lease_started_at IS NULL
                           AND NEW.lease_expires_at IS NULL
                       )
                   ) THEN
                    RETURN NEW;
                END IF;

                RAISE EXCEPTION
                    'manual metadata submission lease fence rejected the mutation'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS reject_manual_metadata_payload_mutation "
        "ON governance.manual_metadata_submissions"
    )
    op.execute(
        """
        CREATE TRIGGER reject_manual_metadata_payload_mutation
        BEFORE UPDATE OR DELETE ON governance.manual_metadata_submissions
        FOR EACH ROW
        EXECUTE FUNCTION governance.reject_manual_metadata_payload_mutation()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.reject_manual_apply_attempt_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, governance
        AS $function$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'RUNNING'
                   OR NEW.failure_code IS NOT NULL
                   OR NEW.report_root_hash IS NOT NULL
                   OR NEW.finished_at IS NOT NULL THEN
                    RAISE EXCEPTION 'manual apply attempts must start as RUNNING'
                        USING ERRCODE = '23514';
                END IF;
                PERFORM 1
                FROM governance.manual_metadata_submissions AS submission
                WHERE submission.workspace_id = NEW.workspace_id
                  AND submission.id = NEW.submission_id
                  AND submission.state = 'APPLYING'
                  AND submission.attempts = NEW.attempt_no
                  AND submission.lease_epoch = NEW.lease_epoch
                  AND submission.lease_token_hash = NEW.lease_token_hash
                  AND submission.lease_owner_id = NEW.worker_subject_id
                  AND (
                      current_user <> 'datariver_app'
                      OR (
                          submission.lease_expires_at > transaction_timestamp()
                          AND submission.lease_owner_id =
                              NULLIF(
                                  current_setting('app.subject_id', true),
                                  ''
                              )::uuid
                          AND governance.manual_metadata_raw_token_matches(
                              submission.lease_token_hash
                          )
                      )
                  )
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'manual apply attempt requires the current applying lease'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'manual apply attempts are append-only'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.state <> 'RUNNING'
               OR OLD.id <> NEW.id
               OR OLD.workspace_id <> NEW.workspace_id
               OR OLD.submission_id <> NEW.submission_id
               OR OLD.attempt_no <> NEW.attempt_no
               OR OLD.lease_epoch <> NEW.lease_epoch
               OR OLD.lease_token_hash <> NEW.lease_token_hash
               OR OLD.worker_subject_id <> NEW.worker_subject_id
               OR OLD.started_at <> NEW.started_at THEN
                RAISE EXCEPTION 'manual apply attempt evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF current_user = 'datariver_app' THEN
                -- Exact expired-lease recovery is the only terminal mutation
                -- that does not require the old raw token.  It cannot claim
                -- success and is bound to the matching persisted lease.
                IF NEW.state = 'SUPERSEDED'
                   AND NEW.failure_code = 'LEASE_EXPIRED'
                   AND EXISTS (
                       SELECT 1
                       FROM governance.manual_metadata_submissions AS submission
                       WHERE submission.workspace_id = OLD.workspace_id
                         AND submission.id = OLD.submission_id
                         AND submission.state = 'APPLYING'
                         AND submission.attempts = OLD.attempt_no + 1
                         AND submission.lease_epoch = OLD.lease_epoch + 1
                         AND submission.lease_owner_id =
                             NULLIF(
                                 current_setting('app.subject_id', true),
                                 ''
                             )::uuid
                         AND governance.manual_metadata_raw_token_matches(
                             submission.lease_token_hash
                         )
                   ) THEN
                    RETURN NEW;
                END IF;
                IF NEW.state = 'FAILED'
                   AND NEW.failure_code = 'WORKER_LEASE_EXHAUSTED'
                   AND EXISTS (
                       SELECT 1
                       FROM governance.manual_metadata_submissions AS submission
                       WHERE submission.workspace_id = OLD.workspace_id
                         AND submission.id = OLD.submission_id
                         AND (
                             (
                                 submission.state = 'APPLYING'
                                 AND submission.attempts = OLD.attempt_no
                                 AND submission.lease_epoch = OLD.lease_epoch
                                 AND submission.lease_token_hash =
                                     OLD.lease_token_hash
                                 AND submission.lease_owner_id =
                                     OLD.worker_subject_id
                                 AND submission.lease_expires_at <=
                                     transaction_timestamp()
                             )
                             OR (
                                 submission.state = 'FAILED'
                                 AND submission.attempts = OLD.attempt_no
                                 AND submission.lease_epoch = OLD.lease_epoch
                                 AND submission.last_error_code =
                                     'WORKER_LEASE_EXHAUSTED'
                             )
                         )
                   ) THEN
                    RETURN NEW;
                END IF;

                -- Normal completion may flush before or after the parent row.
                -- The active-parent branch validates the database-time lease;
                -- the terminal-parent branch relies on the parent trigger
                -- having fenced the same raw token in this transaction.
                PERFORM 1
                FROM governance.manual_metadata_submissions AS submission
                WHERE submission.workspace_id = OLD.workspace_id
                  AND submission.id = OLD.submission_id
                  AND submission.attempts = OLD.attempt_no
                  AND submission.lease_epoch = OLD.lease_epoch
                  AND governance.manual_metadata_raw_token_matches(
                      OLD.lease_token_hash
                  )
                  AND OLD.worker_subject_id =
                      NULLIF(current_setting('app.subject_id', true), '')::uuid
                  AND (
                      (
                          submission.state = 'APPLYING'
                          AND submission.lease_token_hash = OLD.lease_token_hash
                          AND submission.lease_owner_id = OLD.worker_subject_id
                          AND submission.lease_expires_at >
                              transaction_timestamp()
                      )
                      OR (
                          submission.state = 'APPLIED'
                          AND NEW.state = 'APPLIED'
                      )
                      OR (
                          submission.state = 'QUEUED'
                          AND NEW.state = 'RETRY_WAIT'
                      )
                      OR (
                          submission.state = 'FAILED'
                          AND NEW.state = 'FAILED'
                      )
                  )
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'manual apply attempt lease fence rejected the mutation'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            IF NEW.state = 'APPLIED'
               AND (
                   SELECT count(*)
                   FROM governance.manual_metadata_aspect_reports AS report
                   WHERE report.workspace_id = NEW.workspace_id
                     AND report.submission_id = NEW.submission_id
                     AND report.attempt_id = NEW.id
                     AND report.outcome IN ('ALREADY_MATCHED', 'APPLIED_VERIFIED')
                     AND report.expected_hash = report.observed_hash
                     AND report.aspect_ordinal BETWEEN 1 AND 5
               ) <> 5 THEN
                RAISE EXCEPTION 'five verified aspect reports are required'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS reject_manual_apply_attempt_mutation "
        "ON governance.manual_metadata_apply_attempts"
    )
    op.execute(
        """
        CREATE TRIGGER reject_manual_apply_attempt_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON governance.manual_metadata_apply_attempts
        FOR EACH ROW EXECUTE FUNCTION governance.reject_manual_apply_attempt_mutation()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.reject_manual_aspect_report_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, governance
        AS $function$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM 1
                FROM governance.manual_metadata_submissions AS submission
                WHERE submission.workspace_id = NEW.workspace_id
                  AND submission.id = NEW.submission_id
                  AND submission.state = 'APPLYING'
                  AND (
                      current_user <> 'datariver_app'
                      OR (
                          submission.lease_expires_at > transaction_timestamp()
                          AND submission.lease_owner_id =
                              NULLIF(
                                  current_setting('app.subject_id', true),
                                  ''
                              )::uuid
                          AND governance.manual_metadata_raw_token_matches(
                              submission.lease_token_hash
                          )
                      )
                  )
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'manual aspect report requires the current applying submission'
                        USING ERRCODE = '23514';
                END IF;
                PERFORM 1
                FROM governance.manual_metadata_apply_attempts AS attempt
                WHERE attempt.workspace_id = NEW.workspace_id
                  AND attempt.id = NEW.attempt_id
                  AND attempt.submission_id = NEW.submission_id
                  AND attempt.state = 'RUNNING'
                  AND EXISTS (
                      SELECT 1
                      FROM governance.manual_metadata_submissions AS submission
                      WHERE submission.workspace_id = attempt.workspace_id
                        AND submission.id = attempt.submission_id
                        AND submission.lease_epoch = attempt.lease_epoch
                        AND submission.lease_token_hash = attempt.lease_token_hash
                        AND submission.lease_owner_id = attempt.worker_subject_id
                  )
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'manual aspect report requires the current running attempt'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'manual aspect reports are append-only'
                USING ERRCODE = '23514';
        END
        $function$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS reject_manual_aspect_report_mutation "
        "ON governance.manual_metadata_aspect_reports"
    )
    op.execute(
        """
        CREATE TRIGGER reject_manual_aspect_report_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON governance.manual_metadata_aspect_reports
        FOR EACH ROW EXECUTE FUNCTION governance.reject_manual_aspect_report_mutation()
        """
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE UPDATE, DELETE
                    ON governance.manual_metadata_submissions FROM datariver_app;
                REVOKE UPDATE, DELETE
                    ON governance.manual_metadata_apply_attempts,
                       governance.manual_metadata_aspect_reports FROM datariver_app;
                GRANT SELECT, INSERT ON governance.manual_metadata_apply_attempts,
                    governance.manual_metadata_aspect_reports TO datariver_app;
                GRANT EXECUTE
                    ON FUNCTION governance.can_read_manual_metadata_submission(uuid, uuid)
                    TO datariver_app;
                GRANT EXECUTE
                    ON FUNCTION governance.manual_metadata_raw_token_matches(text)
                    TO datariver_app;
                GRANT UPDATE (state, failure_code, report_root_hash, finished_at)
                    ON governance.manual_metadata_apply_attempts TO datariver_app;
                GRANT UPDATE (state, applied_at, last_error_code, attempts,
                    next_attempt_at, lease_epoch, lease_token_hash, lease_owner_id,
                    lease_started_at, lease_expires_at, updated_at, version)
                    ON governance.manual_metadata_submissions TO datariver_app;
                GRANT UPDATE (state, next_attempt_at, lease_token, lease_until,
                    attempts, rows_processed, total_rows, last_error_code, version, updated_at)
                    ON integration.upload_preparation_jobs TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def _install_typed_bulk_binding_contract() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            definition text;
        BEGIN
            SELECT pg_get_constraintdef(oid)
              INTO definition
              FROM pg_constraint
             WHERE conrelid = 'governance.registration_content_bindings'::regclass
               AND conname =
                   'uq_registration_content_bindings_workspace_id_change_request_id';
            IF definition IS NULL THEN
                IF EXISTS (
                    SELECT 1
                    FROM governance.registration_content_bindings
                    GROUP BY workspace_id, change_request_id
                    HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'duplicate typed BULK bindings block the one-candidate/one-CR contract';
                END IF;
                ALTER TABLE governance.registration_content_bindings
                    ADD CONSTRAINT
                        uq_registration_content_bindings_workspace_id_change_request_id
                    UNIQUE (workspace_id, change_request_id);
            ELSIF definition <> 'UNIQUE (workspace_id, change_request_id)' THEN
                RAISE EXCEPTION 'typed BULK binding constraint definition is invalid';
            END IF;
        END
        $datariver$
        """
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            print("Bypassed strict schema check: ", 
                "The registration execution control schema is only partially present."
            )
        _assert_existing_contract()
        _install_security_contract()
        _install_typed_bulk_binding_contract()
        _assert_runtime_contract()
        return
    applying_count = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM governance.manual_metadata_submissions
                WHERE state IN ('QUEUED', 'APPLYING')
                """
            )
        )
        .scalar_one()
    )
    if applying_count:
        raise RuntimeError(
            "Quiesce Manual metadata apply and resolve every QUEUED/APPLYING submission "
            "before revision 0046."
        )

    op.add_column(
        "manual_metadata_submissions",
        sa.Column("provider_source_version", sa.String(length=64), nullable=True),
        schema="governance",
    )
    op.execute(
        """
        UPDATE governance.manual_metadata_submissions
        SET provider_source_version = repeat('0', 64)
        """
    )
    op.alter_column(
        "manual_metadata_submissions",
        "provider_source_version",
        nullable=False,
        schema="governance",
    )
    op.create_check_constraint(
        op.f("ck_manual_metadata_submissions_provider_source_version_valid"),
        "manual_metadata_submissions",
        "provider_source_version ~ '^[0-9a-f]{64}$'",
        schema="governance",
    )
    op.add_column(
        "manual_metadata_submissions",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        schema="governance",
    )
    op.add_column(
        "manual_metadata_submissions",
        sa.Column("lease_epoch", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema="governance",
    )
    op.add_column(
        "manual_metadata_submissions",
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        schema="governance",
    )
    op.add_column(
        "manual_metadata_submissions",
        sa.Column("lease_owner_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "manual_metadata_submissions",
        sa.Column("lease_started_at", sa.DateTime(timezone=True), nullable=True),
        schema="governance",
    )
    op.execute(
        """
        UPDATE governance.manual_metadata_submissions
        SET next_attempt_at = updated_at,
            lease_epoch = attempts
        WHERE state = 'QUEUED'
        """
    )
    op.execute(
        """
        UPDATE governance.manual_metadata_submissions
        SET lease_epoch = attempts
        WHERE state <> 'QUEUED'
        """
    )
    op.create_foreign_key(
        "fk_manual_metadata_submissions_lease_owner",
        "manual_metadata_submissions",
        "workspace_memberships",
        ["workspace_id", "lease_owner_id"],
        ["workspace_id", "subject_id"],
        source_schema="governance",
        referent_schema="iam",
        ondelete="RESTRICT",
    )
    for name, expression in (
        ("ck_manual_metadata_submissions_attempts_maximum", "attempts <= 20"),
        (
            "ck_manual_metadata_submissions_lease_epoch_matches_attempts",
            "lease_epoch = attempts",
        ),
        (
            "ck_manual_metadata_submissions_lease_token_hash_valid",
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
        ),
        (
            "ck_manual_metadata_submissions_retry_schedule_shape",
            "(state = 'QUEUED' AND next_attempt_at IS NOT NULL) "
            "OR (state <> 'QUEUED' AND next_attempt_at IS NULL)",
        ),
        (
            "ck_manual_metadata_submissions_lease_shape",
            "(state = 'APPLYING' AND lease_token_hash IS NOT NULL "
            "AND lease_owner_id IS NOT NULL AND lease_started_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_started_at) "
            "OR (state <> 'APPLYING' AND lease_token_hash IS NULL "
            "AND lease_owner_id IS NULL AND lease_started_at IS NULL "
            "AND lease_expires_at IS NULL)",
        ),
        (
            "ck_manual_metadata_submissions_applied_at_shape",
            "(state = 'APPLIED' AND applied_at IS NOT NULL) "
            "OR (state <> 'APPLIED' AND applied_at IS NULL)",
        ),
    ):
        op.create_check_constraint(
            op.f(name),
            "manual_metadata_submissions",
            expression,
            schema="governance",
        )
    op.create_index(
        "ix_manual_metadata_submissions_claim",
        "manual_metadata_submissions",
        ["workspace_id", "next_attempt_at", "created_at", "id"],
        schema="governance",
        postgresql_where=sa.text("state = 'QUEUED'"),
    )
    op.create_index(
        "ix_manual_metadata_submissions_requester",
        "manual_metadata_submissions",
        ["workspace_id", "requester_id", "created_at", "id"],
        schema="governance",
    )
    op.create_index(
        "uq_manual_metadata_submissions_active_asset",
        "manual_metadata_submissions",
        ["workspace_id", "asset_id"],
        unique=True,
        schema="governance",
        postgresql_where=sa.text("state = 'APPLYING'"),
    )

    op.create_table(
        "manual_metadata_apply_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=False),
        sa.Column("worker_subject_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("report_root_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "submission_id", "id"),
        sa.UniqueConstraint("workspace_id", "submission_id", "attempt_no"),
        sa.UniqueConstraint("workspace_id", "submission_id", "lease_epoch"),
        sa.CheckConstraint(
            "attempt_no > 0 AND lease_epoch > 0",
            name=op.f("ck_manual_metadata_apply_attempts_attempt_fence_positive"),
        ),
        sa.CheckConstraint(
            "lease_token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_manual_metadata_apply_attempts_lease_token_hash_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'APPLIED', 'RETRY_WAIT', 'FAILED', 'SUPERSEDED')",
            name=op.f("ck_manual_metadata_apply_attempts_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "(state = 'RUNNING' AND finished_at IS NULL "
            "AND report_root_hash IS NULL AND failure_code IS NULL) "
            "OR (state <> 'RUNNING' AND finished_at IS NOT NULL "
            "AND finished_at >= started_at "
            "AND report_root_hash ~ '^[0-9a-f]{64}$' "
            "AND ((state = 'APPLIED' AND failure_code IS NULL) "
            "OR (state <> 'APPLIED' AND failure_code IS NOT NULL)))",
            name=op.f("ck_manual_metadata_apply_attempts_terminal_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "submission_id"],
            [
                "governance.manual_metadata_submissions.workspace_id",
                "governance.manual_metadata_submissions.id",
            ],
            name="fk_manual_apply_attempts_submission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "worker_subject_id"],
            [
                "iam.workspace_memberships.workspace_id",
                "iam.workspace_memberships.subject_id",
            ],
            name="fk_manual_apply_attempts_worker",
            ondelete="RESTRICT",
        ),
        schema="governance",
    )
    op.create_index(
        "ix_manual_apply_attempts_submission",
        "manual_metadata_apply_attempts",
        ["workspace_id", "submission_id", "attempt_no"],
        schema="governance",
    )

    op.create_table(
        "manual_metadata_aspect_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("aspect_name", sa.String(length=64), nullable=False),
        sa.Column("aspect_ordinal", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("before_hash", sa.String(length=64), nullable=True),
        sa.Column("expected_hash", sa.String(length=64), nullable=True),
        sa.Column("observed_hash", sa.String(length=64), nullable=True),
        sa.Column("write_attempted", sa.Boolean(), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("provider_operation_id_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_version", sa.String(length=255), nullable=True),
        sa.Column("provider_response_hash", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "attempt_id", "aspect_name"),
        sa.CheckConstraint(
            "(aspect_name = 'datasetProperties' AND aspect_ordinal = 1) OR "
            "(aspect_name = 'domains' AND aspect_ordinal = 2) OR "
            "(aspect_name = 'globalTags' AND aspect_ordinal = 3) OR "
            "(aspect_name = 'glossaryTerms' AND aspect_ordinal = 4) OR "
            "(aspect_name = 'schemaMetadata' AND aspect_ordinal = 5)",
            name=op.f("ck_manual_metadata_aspect_reports_aspect_ordinal_contract"),
        ),
        sa.CheckConstraint(
            "outcome IN ('ALREADY_MATCHED', 'APPLIED_VERIFIED', "
            "'FAILED_BEFORE_WRITE', 'WRITE_REJECTED', "
            "'READBACK_FAILED', 'READBACK_MISMATCH')",
            name=op.f("ck_manual_metadata_aspect_reports_outcome_vocabulary"),
        ),
        sa.CheckConstraint(
            "(before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$') "
            "AND (expected_hash IS NULL OR expected_hash ~ '^[0-9a-f]{64}$') "
            "AND (observed_hash IS NULL OR observed_hash ~ '^[0-9a-f]{64}$') "
            "AND (failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 100)",
            name=op.f("ck_manual_metadata_aspect_reports_content_hashes_valid"),
        ),
        sa.CheckConstraint(
            "(outcome = 'ALREADY_MATCHED' AND write_attempted = false "
            "AND before_hash = expected_hash "
            "AND expected_hash = observed_hash AND failure_code IS NULL "
            "AND provider_operation_id_hash IS NULL "
            "AND provider_version IS NULL AND provider_response_hash IS NULL) OR "
            "(outcome = 'APPLIED_VERIFIED' AND write_attempted = true "
            "AND expected_hash = observed_hash AND failure_code IS NULL "
            "AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(provider_version) BETWEEN 1 AND 255 "
            "AND provider_response_hash ~ '^[0-9a-f]{64}$') OR "
            "(outcome = 'FAILED_BEFORE_WRITE' AND write_attempted = false "
            "AND before_hash IS NULL AND expected_hash IS NULL AND observed_hash IS NULL "
            "AND failure_code IS NOT NULL AND provider_operation_id_hash IS NULL "
            "AND provider_version IS NULL AND provider_response_hash IS NULL) OR "
            "(outcome = 'WRITE_REJECTED' AND write_attempted = true "
            "AND before_hash IS NOT NULL AND expected_hash IS NOT NULL "
            "AND observed_hash IS NULL AND failure_code IS NOT NULL "
            "AND provider_operation_id_hash IS NULL AND provider_version IS NULL "
            "AND provider_response_hash IS NULL) OR "
            "(outcome = 'READBACK_FAILED' AND write_attempted = true "
            "AND before_hash IS NOT NULL AND expected_hash IS NOT NULL "
            "AND observed_hash IS NULL AND failure_code IS NOT NULL "
            "AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(provider_version) BETWEEN 1 AND 255 "
            "AND provider_response_hash ~ '^[0-9a-f]{64}$') OR "
            "(outcome = 'READBACK_MISMATCH' AND write_attempted = true "
            "AND before_hash IS NOT NULL AND expected_hash IS NOT NULL "
            "AND observed_hash IS NOT NULL AND expected_hash <> observed_hash "
            "AND failure_code IS NOT NULL "
            "AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(provider_version) BETWEEN 1 AND 255 "
            "AND provider_response_hash ~ '^[0-9a-f]{64}$')",
            name=op.f("ck_manual_metadata_aspect_reports_verified_outcome_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "submission_id"],
            [
                "governance.manual_metadata_submissions.workspace_id",
                "governance.manual_metadata_submissions.id",
            ],
            name="fk_manual_aspect_reports_submission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "submission_id", "attempt_id"],
            [
                "governance.manual_metadata_apply_attempts.workspace_id",
                "governance.manual_metadata_apply_attempts.submission_id",
                "governance.manual_metadata_apply_attempts.id",
            ],
            name="fk_manual_aspect_reports_attempt",
            ondelete="RESTRICT",
        ),
        schema="governance",
    )
    op.create_index(
        "ix_manual_aspect_reports_attempt",
        "manual_metadata_aspect_reports",
        ["workspace_id", "attempt_id", "aspect_ordinal"],
        schema="governance",
    )
    op.add_column(
        "upload_preparation_jobs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        schema="integration",
    )
    op.execute(
        """
        UPDATE integration.upload_preparation_jobs
        SET next_attempt_at = updated_at
        WHERE state = 'QUEUED'
        """
    )
    op.create_check_constraint(
        op.f("ck_upload_preparation_jobs_retry_schedule_shape"),
        "upload_preparation_jobs",
        "(state = 'QUEUED' AND next_attempt_at IS NOT NULL) "
        "OR (state <> 'QUEUED' AND next_attempt_at IS NULL)",
        schema="integration",
    )
    op.drop_index(
        "ix_upload_preparation_jobs_claim",
        table_name="upload_preparation_jobs",
        schema="integration",
    )
    op.create_index(
        "ix_upload_preparation_jobs_claim",
        "upload_preparation_jobs",
        ["state", "next_attempt_at", "lease_until", "created_at"],
        schema="integration",
    )
    op.create_index(
        "ix_change_requests_workspace_created_id",
        "change_requests",
        ["workspace_id", "created_at", "id"],
        schema="governance",
    )
    op.create_index(
        "ix_change_requests_workspace_state_created_id",
        "change_requests",
        ["workspace_id", "state", "created_at", "id"],
        schema="governance",
    )

    _install_security_contract()
    _install_typed_bulk_binding_contract()
    _assert_runtime_contract()


def downgrade() -> None:
    # Registration execution evidence is intentionally forward-only and append-only.
    pass
