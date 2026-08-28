"""Fence governed DataHub change application at the database boundary.

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'integration'
                  AND table_name = 'jobs'
                  AND column_name IN (
                      'attempt_cycle',
                      'cycle_attempts',
                      'lease_token_hash',
                      'lease_owner_id'
                  )
                """
            )
        )
        .scalar_one()
    )


def _add_columns() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM integration.jobs
                WHERE job_type = 'DATAHUB_CHANGE_APPLY'
                  AND state = 'RUNNING'
            ) OR EXISTS (
                SELECT 1
                FROM governance.change_requests
                WHERE state = 'APPLYING'
            ) THEN
                RAISE EXCEPTION
                    'stop and resolve active governance apply work before revision 0048';
            END IF;
        END
        $datariver$;
        """
    )
    op.add_column(
        "jobs",
        sa.Column(
            "attempt_cycle",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        schema="integration",
    )
    op.add_column(
        "jobs",
        sa.Column(
            "cycle_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema="integration",
    )
    op.add_column(
        "jobs",
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        schema="integration",
    )
    op.add_column(
        "jobs",
        sa.Column("lease_owner_id", sa.Uuid(), nullable=True),
        schema="integration",
    )
    op.execute(
        """
        UPDATE integration.jobs
        SET cycle_attempts = attempts
        WHERE attempts > 0;
        """
    )
    op.create_check_constraint(
        op.f("ck_jobs_lease_token_hash_valid"),
        "jobs",
        "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
        schema="integration",
    )
    op.create_check_constraint(
        op.f("ck_jobs_attempt_counters_valid"),
        "jobs",
        "attempt_cycle > 0 AND cycle_attempts >= 0 AND attempts >= cycle_attempts",
        schema="integration",
    )
    op.create_check_constraint(
        op.f("ck_jobs_governance_apply_lease_shape"),
        "jobs",
        "job_type <> 'DATAHUB_CHANGE_APPLY' OR "
        "((state = 'RUNNING' AND lease_token_hash IS NOT NULL "
        "AND lease_owner_id IS NOT NULL AND lease_until IS NOT NULL) "
        "OR (state <> 'RUNNING' AND lease_token_hash IS NULL "
        "AND lease_owner_id IS NULL))",
        schema="integration",
    )
    op.create_foreign_key(
        "fk_jobs_workspace_lease_owner",
        "jobs",
        "workspace_memberships",
        ["workspace_id", "lease_owner_id"],
        ["workspace_id", "subject_id"],
        source_schema="integration",
        referent_schema="iam",
        ondelete="RESTRICT",
    )


def _assert_columns_and_constraints() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('attempt_cycle', 'integer', 'NO', '1', -1),
                        ('cycle_attempts', 'integer', 'NO', '0', -1),
                        ('lease_token_hash', 'character varying', 'YES', NULL, 64),
                        ('lease_owner_id', 'uuid', 'YES', NULL, -1)
                ) AS expected(
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length
                )
                LEFT JOIN information_schema.columns AS actual
                  ON actual.table_schema = 'integration'
                 AND actual.table_name = 'jobs'
                 AND actual.column_name = expected.column_name
                WHERE actual.column_name IS NULL
                   OR actual.data_type <> expected.data_type
                   OR actual.is_nullable <> expected.is_nullable
                   OR actual.column_default IS DISTINCT FROM expected.column_default
                   OR actual.is_identity <> 'NO'
                   OR actual.is_generated <> 'NEVER'
                   OR (
                       expected.character_maximum_length >= 0
                       AND actual.character_maximum_length <>
                           expected.character_maximum_length
                   )
            ) THEN
                RAISE EXCEPTION 'governance apply job lease columns drifted';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        (
                            'ck_jobs_lease_token_hash_valid',
                            'c',
                            'lease_token_hash'
                        ),
                        (
                            'ck_jobs_attempt_counters_valid',
                            'c',
                            'attempt_cycle'
                        ),
                        (
                            'ck_jobs_governance_apply_lease_shape',
                            'c',
                            'DATAHUB_CHANGE_APPLY'
                        ),
                        (
                            'fk_jobs_workspace_lease_owner',
                            'f',
                            'iam.workspace_memberships'
                        )
                ) AS expected(constraint_name, constraint_type, definition_fragment)
                LEFT JOIN pg_constraint AS actual
                  ON actual.conrelid = 'integration.jobs'::regclass
                 AND actual.conname = expected.constraint_name
                WHERE actual.oid IS NULL
                   OR actual.contype::text <> expected.constraint_type
                   OR actual.convalidated IS NOT TRUE
                   OR position(
                       expected.definition_fragment
                       IN pg_get_constraintdef(actual.oid)
                   ) = 0
            ) OR EXISTS (
                SELECT 1
                FROM pg_constraint AS contract
                WHERE contract.conrelid = 'integration.jobs'::regclass
                  AND contract.conname = 'fk_jobs_workspace_lease_owner'
                  AND (
                      contract.confrelid <> 'iam.workspace_memberships'::regclass
                      OR contract.confdeltype <> 'r'
                      OR contract.confupdtype <> 'a'
                      OR contract.condeferrable
                      OR contract.condeferred
                      OR (
                          SELECT array_agg(attribute.attname::text ORDER BY key.ordinality)
                          FROM unnest(contract.conkey)
                              WITH ORDINALITY AS key(attnum, ordinality)
                          JOIN pg_attribute AS attribute
                            ON attribute.attrelid = contract.conrelid
                           AND attribute.attnum = key.attnum
                      ) IS DISTINCT FROM
                          ARRAY['workspace_id', 'lease_owner_id']::text[]
                      OR (
                          SELECT array_agg(attribute.attname::text ORDER BY key.ordinality)
                          FROM unnest(contract.confkey)
                              WITH ORDINALITY AS key(attnum, ordinality)
                          JOIN pg_attribute AS attribute
                            ON attribute.attrelid = contract.confrelid
                           AND attribute.attnum = key.attnum
                      ) IS DISTINCT FROM
                          ARRAY['workspace_id', 'subject_id']::text[]
                  )
            ) THEN
                RAISE EXCEPTION 'governance apply job lease constraints drifted';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        (
                            'ck_jobs_lease_token_hash_valid',
                            concat(
                                'CHECK (lease_token_hash IS NULL OR ',
                                'lease_token_hash::text ~ ',
                                '''^[0-9a-f]{64}$''::text)'
                            )
                        ),
                        (
                            'ck_jobs_attempt_counters_valid',
                            'CHECK (attempt_cycle > 0 AND cycle_attempts >= 0 '
                            || 'AND attempts >= cycle_attempts)'
                        ),
                        (
                            'ck_jobs_governance_apply_lease_shape',
                            concat(
                                'CHECK (job_type::text <> ',
                                '''DATAHUB_CHANGE_APPLY''::text OR ',
                                'state::text = ''RUNNING''::text AND ',
                                'lease_token_hash IS NOT NULL AND ',
                                'lease_owner_id IS NOT NULL AND ',
                                'lease_until IS NOT NULL OR state::text <> ',
                                '''RUNNING''::text AND lease_token_hash IS NULL ',
                                'AND lease_owner_id IS NULL)'
                            )
                        )
                ) AS expected(constraint_name, exact_definition)
                LEFT JOIN pg_constraint AS actual
                  ON actual.conrelid = 'integration.jobs'::regclass
                 AND actual.conname = expected.constraint_name
                WHERE actual.oid IS NULL
                   OR regexp_replace(
                       pg_get_constraintdef(actual.oid, true),
                       '[[:space:]]+',
                       ' ',
                       'g'
                   ) IS DISTINCT FROM expected.exact_definition
            ) THEN
                RAISE EXCEPTION
                    'governance apply job check definitions are not canonical';
            END IF;
        END
        $datariver$;
        """
    )


def _install_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION iam.is_governance_apply_worker_eligible(
            p_workspace_id uuid,
            p_subject_id uuid
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, iam, platform
        AS $datariver$
        BEGIN
            IF p_workspace_id IS NULL OR p_subject_id IS NULL THEN
                RETURN false;
            END IF;
            PERFORM 1
            FROM iam.workspace_memberships AS membership
            JOIN iam.subjects AS subject
              ON subject.id = membership.subject_id
            JOIN platform.workspaces AS workspace
              ON workspace.id = membership.workspace_id
            WHERE membership.workspace_id = p_workspace_id
              AND membership.subject_id = p_subject_id
              AND workspace.status = 'ACTIVE'
              AND subject.active IS TRUE
              AND membership.active IS TRUE
              AND (
                  membership.access_expires_at IS NULL
                  OR membership.access_expires_at > transaction_timestamp()
              )
              AND membership.job_function = 'SERVICE_ACCOUNT'
              AND COALESCE(
                  membership.attributes -> 'groups',
                  '[]'::jsonb
              ) ? 'service-accounts'
              AND COALESCE(
                  membership.attributes -> 'groups',
                  '[]'::jsonb
              ) ? 'registration-workers'
              AND COALESCE(
                  membership.attributes -> 'allowed_actions',
                  '[]'::jsonb
              ) ? 'catalog.sync'
              AND NOT (
                  COALESCE(
                      membership.attributes -> 'denied_actions',
                      '[]'::jsonb
                  ) ? 'catalog.sync'
              )
            FOR UPDATE OF membership, subject, workspace;
            RETURN FOUND;
        END
        $datariver$;
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION
            iam.is_governance_apply_worker_eligible(uuid, uuid)
            FROM PUBLIC
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION integration.guard_governance_apply_job()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, integration, governance
        AS $datariver$
        DECLARE
            raw_token text :=
                NULLIF(current_setting('app.governance_apply_lease_token', true), '');
            actor_id uuid :=
                NULLIF(current_setting('app.subject_id', true), '')::uuid;
            raw_hash text;
            token_matches_old boolean := false;
            token_matches_new boolean := false;
            eligible_request boolean := false;
            eligible_worker boolean := false;
            canonical_requester uuid;
            canonical_request_state text;
            table_owner name;
        BEGIN
            SELECT pg_get_userbyid(relowner)
            INTO table_owner
            FROM pg_class
            WHERE oid = TG_RELID;
            IF current_user = table_owner THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            IF (
                TG_OP = 'INSERT'
                AND NEW.job_type = 'DATAHUB_CHANGE_APPLY'
            ) OR (
                TG_OP = 'UPDATE'
                AND (
                    OLD.job_type = 'DATAHUB_CHANGE_APPLY'
                    OR NEW.job_type = 'DATAHUB_CHANGE_APPLY'
                )
            ) OR (
                TG_OP = 'DELETE'
                AND OLD.job_type = 'DATAHUB_CHANGE_APPLY'
            ) THEN
                IF current_user <> 'datariver_governance' THEN
                    RAISE EXCEPTION
                        'only the governance worker may mutate governance apply jobs';
                END IF;
            ELSIF current_user = 'datariver_governance' THEN
                RAISE EXCEPTION
                    'the governance worker cannot mutate another worker job';
            ELSE
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'governance apply jobs are not directly deletable';
            END IF;
            IF raw_token IS NOT NULL THEN
                raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
                token_matches_new := raw_hash = NEW.lease_token_hash;
                IF TG_OP = 'UPDATE' THEN
                    token_matches_old := raw_hash = OLD.lease_token_hash;
                END IF;
            END IF;
            SELECT request.requester_id, request.state
            INTO canonical_requester, canonical_request_state
            FROM governance.change_requests AS request
            WHERE request.workspace_id = NEW.workspace_id
              AND request.id = NEW.causation_id
              AND request.state IN ('APPLY_QUEUED', 'APPLYING');
            eligible_request := FOUND;

            eligible_worker := iam.is_governance_apply_worker_eligible(
                NEW.workspace_id,
                actor_id
            );

            IF TG_OP = 'UPDATE' AND (
                OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
                OR OLD.id IS DISTINCT FROM NEW.id
                OR OLD.job_type IS DISTINCT FROM NEW.job_type
                OR OLD.causation_id IS DISTINCT FROM NEW.causation_id
                OR OLD.requested_by IS DISTINCT FROM NEW.requested_by
                OR OLD.created_at IS DISTINCT FROM NEW.created_at
            ) THEN
                RAISE EXCEPTION 'governance apply job identity is immutable';
            END IF;

            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'RUNNING'
                   OR NEW.requested_by IS DISTINCT FROM canonical_requester
                   OR NEW.progress IS DISTINCT FROM jsonb_build_object()
                   OR NEW.result_ref IS NOT NULL
                   OR NEW.last_error_code IS NOT NULL
                   OR NEW.version <> 1
                   OR NEW.attempts <> 1
                   OR NEW.attempt_cycle <> 1
                   OR NEW.cycle_attempts <> 1
                   OR NEW.lease_until <= clock_timestamp()
                   OR NEW.lease_until >
                       clock_timestamp() + interval '15 minutes'
                   OR NEW.lease_owner_id IS DISTINCT FROM actor_id
                   OR token_matches_new IS NOT TRUE
                   OR eligible_request IS NOT TRUE
                   OR eligible_worker IS NOT TRUE THEN
                    RAISE EXCEPTION 'invalid governance apply initial claim';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.state = 'RUNNING' AND NEW.state = 'RUNNING' THEN
                IF OLD.lease_until <= clock_timestamp() THEN
                    IF NEW.attempts <> OLD.attempts + 1
                       OR NEW.attempt_cycle <> OLD.attempt_cycle
                       OR NEW.cycle_attempts <> OLD.cycle_attempts + 1
                       OR NEW.progress IS DISTINCT FROM jsonb_build_object()
                       OR NEW.result_ref IS NOT NULL
                       OR NEW.last_error_code IS NOT NULL
                       OR NEW.version <> OLD.version + 1
                       OR NEW.lease_until <= clock_timestamp()
                       OR NEW.lease_until >
                           clock_timestamp() + interval '15 minutes'
                       OR NEW.lease_owner_id IS DISTINCT FROM actor_id
                       OR token_matches_new IS NOT TRUE
                       OR eligible_request IS NOT TRUE
                       OR eligible_worker IS NOT TRUE THEN
                        RAISE EXCEPTION 'invalid governance apply reclaim';
                    END IF;
                ELSIF NEW.attempts <> OLD.attempts
                   OR NEW.attempt_cycle <> OLD.attempt_cycle
                   OR NEW.cycle_attempts <> OLD.cycle_attempts
                   OR NEW.progress IS DISTINCT FROM OLD.progress
                   OR NEW.result_ref IS DISTINCT FROM OLD.result_ref
                   OR NEW.last_error_code IS DISTINCT FROM OLD.last_error_code
                   OR NEW.version <> OLD.version
                   OR NEW.lease_token_hash IS DISTINCT FROM OLD.lease_token_hash
                   OR NEW.lease_owner_id IS DISTINCT FROM OLD.lease_owner_id
                   OR NEW.lease_until <= OLD.lease_until
                   OR NEW.lease_until >
                       clock_timestamp() + interval '15 minutes'
                   OR token_matches_old IS NOT TRUE
                   OR eligible_worker IS NOT TRUE THEN
                    RAISE EXCEPTION 'invalid governance apply lease renewal';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.state <> 'RUNNING' AND NEW.state = 'RUNNING' THEN
                IF OLD.state NOT IN ('RETRY_WAIT', 'FAILED')
                   OR (
                       OLD.state = 'RETRY_WAIT'
                       AND canonical_request_state <> 'APPLYING'
                   )
                   OR (
                       OLD.state = 'FAILED'
                       AND canonical_request_state <> 'APPLY_QUEUED'
                   )
                   OR NEW.attempts <> OLD.attempts + 1
                   OR NEW.progress IS DISTINCT FROM jsonb_build_object()
                   OR NEW.result_ref IS NOT NULL
                   OR NEW.last_error_code IS NOT NULL
                   OR NEW.version <> OLD.version + 1
                   OR NEW.lease_until <= clock_timestamp()
                   OR NEW.lease_until >
                       clock_timestamp() + interval '15 minutes'
                   OR NEW.lease_owner_id IS DISTINCT FROM actor_id
                   OR token_matches_new IS NOT TRUE
                   OR eligible_request IS NOT TRUE
                   OR eligible_worker IS NOT TRUE
                   OR NOT (
                       (
                           OLD.state = 'FAILED'
                           AND NEW.attempt_cycle = OLD.attempt_cycle + 1
                           AND NEW.cycle_attempts = 1
                       )
                       OR (
                           OLD.state <> 'FAILED'
                           AND NEW.attempt_cycle = OLD.attempt_cycle
                           AND NEW.cycle_attempts = OLD.cycle_attempts + 1
                       )
                   ) THEN
                    RAISE EXCEPTION 'invalid governance apply next claim';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.state = 'RUNNING' AND NEW.state <> 'RUNNING' THEN
                IF NEW.lease_token_hash IS NOT NULL
                   OR NEW.lease_owner_id IS NOT NULL
                   OR NEW.attempts <> OLD.attempts
                   OR NEW.attempt_cycle <> OLD.attempt_cycle
                   OR NEW.cycle_attempts <> OLD.cycle_attempts
                   OR NEW.version <> OLD.version + 1
                   OR NEW.updated_at <= OLD.updated_at THEN
                    RAISE EXCEPTION 'invalid governance apply terminal shape';
                END IF;
                IF token_matches_old IS TRUE
                   AND OLD.lease_until > clock_timestamp()
                   AND eligible_worker IS TRUE
                   AND (
                       (
                           NEW.state = 'COMPLETED'
                           AND NEW.lease_until IS NULL
                           AND NEW.last_error_code IS NULL
                           AND NEW.result_ref =
                               'change-request:' || NEW.causation_id::text
                           AND jsonb_typeof(NEW.progress -> 'items') = 'array'
                           AND NEW.progress ->> 'content_hash'
                               ~ '^[0-9a-f]{64}$'
                           AND EXISTS (
                               SELECT 1
                               FROM integration.job_attempts AS attempt
                               WHERE attempt.workspace_id = NEW.workspace_id
                                 AND attempt.job_id = NEW.id
                                 AND attempt.attempt_no = NEW.attempts
                                 AND attempt.state = 'COMPLETED'
                                 AND attempt.error_class IS NULL
                                 AND attempt.external_response_hash =
                                     NEW.progress ->> 'content_hash'
                           )
                       )
                       OR (
                           NEW.state = 'FAILED'
                           AND NEW.lease_until IS NULL
                           AND NEW.result_ref IS NULL
                           AND NEW.last_error_code IS NOT NULL
                           AND EXISTS (
                               SELECT 1
                               FROM integration.job_attempts AS attempt
                               WHERE attempt.workspace_id = NEW.workspace_id
                                 AND attempt.job_id = NEW.id
                                 AND attempt.attempt_no = NEW.attempts
                                 AND attempt.state = 'FAILED'
                                 AND attempt.error_class = NEW.last_error_code
                           )
                       )
                       OR (
                           NEW.state = 'RETRY_WAIT'
                           AND NEW.lease_until > clock_timestamp()
                           AND NEW.lease_until <=
                               clock_timestamp() + interval '15 minutes'
                           AND NEW.result_ref IS NULL
                           AND NEW.last_error_code IS NOT NULL
                           AND EXISTS (
                               SELECT 1
                               FROM integration.job_attempts AS attempt
                               WHERE attempt.workspace_id = NEW.workspace_id
                                 AND attempt.job_id = NEW.id
                                 AND attempt.attempt_no = NEW.attempts
                                 AND attempt.state = 'FAILED'
                                 AND attempt.error_class = NEW.last_error_code
                           )
                       )
                   ) THEN
                    RETURN NEW;
                END IF;
                IF raw_token IS NULL
                   AND OLD.lease_until <= clock_timestamp()
                   AND NEW.state = 'FAILED'
                   AND NEW.last_error_code = 'WORKER_LEASE_EXHAUSTED'
                   AND NEW.result_ref IS NULL
                   AND NEW.lease_until IS NULL
                   AND EXISTS (
                       SELECT 1
                       FROM integration.job_attempts AS attempt
                       WHERE attempt.workspace_id = NEW.workspace_id
                         AND attempt.job_id = NEW.id
                         AND attempt.attempt_no = NEW.attempts
                         AND attempt.state = 'FAILED'
                         AND attempt.error_class = 'WORKER_LEASE_EXHAUSTED'
                   ) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'governance apply terminal lease is not current';
            END IF;
            RAISE EXCEPTION 'unsupported governance apply job transition';
        END
        $datariver$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION integration.guard_governance_apply_attempt()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, integration
        AS $datariver$
        DECLARE
            raw_token text :=
                NULLIF(current_setting('app.governance_apply_lease_token', true), '');
            raw_hash text;
            parent integration.jobs%ROWTYPE;
            table_owner name;
        BEGIN
            SELECT pg_get_userbyid(relowner)
            INTO table_owner
            FROM pg_class
            WHERE oid = TG_RELID;
            IF current_user = table_owner THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            SELECT * INTO parent
            FROM integration.jobs
            WHERE id = COALESCE(NEW.job_id, OLD.job_id)
              AND workspace_id = COALESCE(NEW.workspace_id, OLD.workspace_id);
            IF FOUND AND parent.job_type = 'DATAHUB_CHANGE_APPLY' THEN
                IF current_user <> 'datariver_governance' THEN
                    RAISE EXCEPTION
                        'only the governance worker may mutate governance apply attempts';
                END IF;
            ELSIF current_user = 'datariver_governance' THEN
                RAISE EXCEPTION
                    'the governance worker cannot mutate another worker attempt';
            ELSE
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'governance apply attempts are append-only';
            END IF;
            IF raw_token IS NOT NULL THEN
                raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'RUNNING'
                   OR NEW.attempt_no <> parent.attempts
                   OR parent.state <> 'RUNNING'
                   OR parent.lease_until <= clock_timestamp()
                   OR raw_hash IS DISTINCT FROM parent.lease_token_hash THEN
                    RAISE EXCEPTION 'invalid governance apply attempt claim';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.workspace_id <> NEW.workspace_id
               OR OLD.id <> NEW.id
               OR OLD.job_id <> NEW.job_id
                   OR OLD.attempt_no <> NEW.attempt_no
                   OR OLD.worker_id <> NEW.worker_id
                   OR OLD.started_at <> NEW.started_at
                   OR OLD.state <> 'RUNNING' THEN
                RAISE EXCEPTION 'governance apply attempt identity is immutable';
            END IF;
            IF parent.state = 'RUNNING'
               AND parent.attempts = OLD.attempt_no
               AND parent.lease_until > clock_timestamp()
               AND raw_hash = parent.lease_token_hash
               AND (
                   (
                       NEW.state = 'COMPLETED'
                       AND NEW.error_class IS NULL
                       AND NEW.external_response_hash ~ '^[0-9a-f]{64}$'
                       AND NEW.finished_at >= OLD.started_at
                   )
                   OR (
                       NEW.state = 'FAILED'
                       AND NEW.error_class IS NOT NULL
                       AND NEW.external_response_hash IS NULL
                       AND NEW.finished_at >= OLD.started_at
                   )
               ) THEN
                RETURN NEW;
            END IF;
            IF parent.state = 'RUNNING'
               AND parent.attempts = OLD.attempt_no
               AND parent.lease_until <= clock_timestamp()
               AND raw_token IS NULL
               AND (
                   (
                       NEW.state = 'SUPERSEDED'
                       AND NEW.error_class = 'LEASE_EXPIRED'
                       AND NEW.external_response_hash IS NULL
                       AND NEW.finished_at >= OLD.started_at
                   )
                   OR (
                       NEW.state = 'FAILED'
                       AND NEW.error_class = 'WORKER_LEASE_EXHAUSTED'
                       AND NEW.external_response_hash IS NULL
                       AND NEW.finished_at >= OLD.started_at
                   )
               ) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'governance apply attempt lease is not current';
        END
        $datariver$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.guard_governance_apply_request()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, governance, integration
        AS $datariver$
        DECLARE
            raw_token text :=
                NULLIF(current_setting('app.governance_apply_lease_token', true), '');
            raw_hash text;
            apply_job integration.jobs%ROWTYPE;
            eligible_worker boolean := false;
            table_owner name;
        BEGIN
            SELECT pg_get_userbyid(relowner)
            INTO table_owner
            FROM pg_class
            WHERE oid = TG_RELID;
            IF current_user = table_owner THEN
                RETURN NEW;
            END IF;
            IF current_user <> 'datariver_governance' THEN
                IF OLD.state IS DISTINCT FROM NEW.state
                   AND (
                       NEW.state IN ('APPLYING', 'APPLIED', 'APPLY_FAILED')
                       OR OLD.state IN ('APPLYING', 'APPLIED', 'APPLY_FAILED')
                   ) THEN
                    RAISE EXCEPTION
                        'only the governance worker may record apply execution states';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.state = NEW.state
               OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
               OR OLD.id IS DISTINCT FROM NEW.id
               OR OLD.number IS DISTINCT FROM NEW.number
               OR OLD.request_type IS DISTINCT FROM NEW.request_type
               OR OLD.title IS DISTINCT FROM NEW.title
               OR OLD.description IS DISTINCT FROM NEW.description
               OR OLD.requester_id IS DISTINCT FROM NEW.requester_id
               OR OLD.requester_department_id IS DISTINCT FROM
                   NEW.requester_department_id
               OR OLD.current_round_id IS DISTINCT FROM NEW.current_round_id
               OR OLD.current_round_number IS DISTINCT FROM NEW.current_round_number
               OR OLD.classification IS DISTINCT FROM NEW.classification
               OR OLD.requested_due_date IS DISTINCT FROM NEW.requested_due_date
               OR OLD.priority IS DISTINCT FROM NEW.priority
               OR OLD.urgency IS DISTINCT FROM NEW.urgency
               OR OLD.created_at IS DISTINCT FROM NEW.created_at
               OR NEW.version <> OLD.version + 1
               OR NEW.updated_at <= OLD.updated_at THEN
                RAISE EXCEPTION 'invalid governance apply request update shape';
            END IF;
            IF raw_token IS NOT NULL THEN
                raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
            END IF;
            SELECT * INTO apply_job
            FROM integration.jobs
            WHERE workspace_id = NEW.workspace_id
              AND causation_id = NEW.id
              AND job_type = 'DATAHUB_CHANGE_APPLY';
            IF NOT FOUND
               OR apply_job.state <> 'RUNNING'
               OR apply_job.lease_until IS NULL THEN
                RAISE EXCEPTION 'governance apply request has no active claim';
            END IF;
            eligible_worker := iam.is_governance_apply_worker_eligible(
                apply_job.workspace_id,
                apply_job.lease_owner_id
            );
            IF raw_hash = apply_job.lease_token_hash
               AND apply_job.lease_until > clock_timestamp()
               AND eligible_worker IS TRUE
               AND (
                   (OLD.state = 'APPLY_QUEUED' AND NEW.state = 'APPLYING')
                   OR (
                       OLD.state = 'APPLYING'
                       AND NEW.state IN ('APPLIED', 'APPLY_FAILED')
                   )
               ) THEN
                RETURN NEW;
            END IF;
            IF raw_token IS NULL
               AND apply_job.lease_until <= clock_timestamp()
               AND OLD.state = 'APPLYING'
               AND NEW.state = 'APPLY_FAILED' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'governance apply request lease is not current';
        END
        $datariver$;
        """
    )
    for table, trigger, function, events in (
        (
            "integration.jobs",
            "guard_governance_apply_job",
            "integration.guard_governance_apply_job",
            "INSERT OR UPDATE OR DELETE",
        ),
        (
            "integration.job_attempts",
            "guard_governance_apply_attempt",
            "integration.guard_governance_apply_attempt",
            "INSERT OR UPDATE OR DELETE",
        ),
        (
            "governance.change_requests",
            "guard_governance_apply_request",
            "governance.guard_governance_apply_request",
            "UPDATE",
        ),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE {events} ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}()
            """
        )


def _install_grants() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN
                GRANT USAGE ON SCHEMA iam TO datariver_governance;
                REVOKE SELECT ON platform.workspaces, iam.subjects,
                    iam.workspace_memberships FROM datariver_governance;
                GRANT EXECUTE ON FUNCTION
                    iam.is_governance_apply_worker_eligible(uuid, uuid)
                    TO datariver_governance;
                GRANT SELECT ON governance.change_request_rounds,
                    governance.change_test_runs
                    TO datariver_governance;

                REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
                    ON governance.change_requests FROM datariver_governance;
                GRANT UPDATE (state, version, updated_at)
                    ON governance.change_requests TO datariver_governance;

                REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
                    ON integration.jobs, integration.job_attempts
                    FROM datariver_governance;
                GRANT INSERT ON integration.jobs, integration.job_attempts
                    TO datariver_governance;
                GRANT UPDATE (
                    state, progress, result_ref, lease_until, attempts,
                    attempt_cycle, cycle_attempts, lease_token_hash, lease_owner_id,
                    last_error_code, version, updated_at
                ) ON integration.jobs TO datariver_governance;
                GRANT UPDATE (
                    state, error_class, external_response_hash, finished_at
                ) ON integration.job_attempts TO datariver_governance;
            END IF;
        END
        $datariver$;
        """
    )


def _assert_runtime_contract() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF (
                SELECT count(*)
                FROM (
                    VALUES
                    (
                        'integration.jobs'::regclass,
                        'guard_governance_apply_job'::text,
                        31::smallint
                    ),
                    (
                        'integration.job_attempts'::regclass,
                        'guard_governance_apply_attempt'::text,
                        31::smallint
                    ),
                    (
                        'governance.change_requests'::regclass,
                        'guard_governance_apply_request'::text,
                        19::smallint
                    )
                ) AS expected(relation_id, trigger_name, trigger_type)
                JOIN pg_trigger AS actual
                  ON actual.tgrelid = expected.relation_id
                 AND actual.tgname = expected.trigger_name
                 AND actual.tgtype = expected.trigger_type
                 AND actual.tgenabled = 'O'
                 AND actual.tgisinternal IS FALSE
            ) <> 3 THEN
                RAISE EXCEPTION 'governance apply database triggers are incomplete';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        (
                            'integration'::text,
                            'guard_governance_apply_job'::text,
                            ARRAY[
                                'search_path=pg_catalog, integration, governance'
                            ]::text[]
                        ),
                        (
                            'integration'::text,
                            'guard_governance_apply_attempt'::text,
                            ARRAY['search_path=pg_catalog, integration']::text[]
                        ),
                        (
                            'governance'::text,
                            'guard_governance_apply_request'::text,
                            ARRAY[
                                'search_path=pg_catalog, governance, integration'
                            ]::text[]
                        )
                ) AS expected(schema_name, function_name, function_config)
                LEFT JOIN pg_namespace AS namespace
                  ON namespace.nspname = expected.schema_name
                LEFT JOIN pg_proc AS procedure
                  ON procedure.pronamespace = namespace.oid
                 AND procedure.proname = expected.function_name
                 AND procedure.pronargs = 0
                WHERE procedure.oid IS NULL
                   OR procedure.prorettype <> 'trigger'::regtype
                   OR procedure.prokind <> 'f'
                   OR procedure.provolatile <> 'v'
                   OR procedure.prosecdef IS TRUE
                   OR procedure.proconfig IS DISTINCT FROM expected.function_config
                   OR position(
                       'app.governance_apply_lease_token'
                       IN pg_get_functiondef(procedure.oid)
                   ) = 0
            ) THEN
                RAISE EXCEPTION 'governance apply trigger functions drifted';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'iam'
                  AND procedure.proname =
                      'is_governance_apply_worker_eligible'
                  AND procedure.proargtypes = '2950 2950'::oidvector
                  AND procedure.prorettype = 'boolean'::regtype
                  AND procedure.prokind = 'f'
                  AND procedure.provolatile = 'v'
                  AND procedure.prosecdef IS TRUE
                  AND procedure.proconfig = ARRAY[
                      'search_path=pg_catalog, iam, platform'
                  ]::text[]
                  AND position(
                      'FOR UPDATE OF membership, subject, workspace'
                      IN pg_get_functiondef(procedure.oid)
                  ) > 0
            ) THEN
                RAISE EXCEPTION
                    'governance apply worker eligibility function drifted';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM pg_proc AS procedure
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(
                        procedure.proacl,
                        acldefault('f', procedure.proowner)
                    )
                ) AS privilege
                WHERE procedure.oid =
                    'iam.is_governance_apply_worker_eligible(uuid, uuid)'
                        ::regprocedure
                  AND privilege.grantee NOT IN (
                      procedure.proowner,
                      (
                          SELECT oid
                          FROM pg_roles
                          WHERE rolname = 'datariver_governance'
                      )
                  )
            ) THEN
                RAISE EXCEPTION
                    'governance apply worker eligibility grants are overbroad';
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance')
               AND (
                   NOT (
                       SELECT rolbypassrls
                       FROM pg_roles
                       WHERE rolname = 'datariver_governance'
                   )
                   OR NOT has_table_privilege(
                       'datariver_governance',
                       'integration.jobs',
                       'SELECT'
                   )
                   OR NOT has_table_privilege(
                       'datariver_governance',
                       'integration.jobs',
                       'INSERT'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.jobs',
                       'DELETE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.jobs',
                       'TRUNCATE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.jobs',
                       'REFERENCES'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.jobs',
                       'TRIGGER'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.jobs',
                       'UPDATE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.job_attempts',
                       'DELETE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.job_attempts',
                       'TRUNCATE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.job_attempts',
                       'REFERENCES'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.job_attempts',
                       'TRIGGER'
                   )
                   OR NOT has_table_privilege(
                       'datariver_governance',
                       'integration.job_attempts',
                       'SELECT'
                   )
                   OR NOT has_table_privilege(
                       'datariver_governance',
                       'integration.job_attempts',
                       'INSERT'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'integration.job_attempts',
                       'UPDATE'
                   )
                   OR NOT has_table_privilege(
                       'datariver_governance',
                       'governance.change_request_rounds',
                       'SELECT'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'platform.workspaces',
                       'SELECT'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'iam.subjects',
                       'SELECT'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'iam.workspace_memberships',
                       'SELECT'
                   )
                   OR NOT has_function_privilege(
                       'datariver_governance',
                       'iam.is_governance_apply_worker_eligible(uuid, uuid)',
                       'EXECUTE'
                   )
                   OR NOT has_table_privilege(
                       'datariver_governance',
                       'governance.change_test_runs',
                       'SELECT'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'governance.change_requests',
                       'UPDATE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'governance.change_requests',
                       'INSERT'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'governance.change_requests',
                       'DELETE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'governance.change_requests',
                       'TRUNCATE'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'governance.change_requests',
                       'REFERENCES'
                   )
                   OR has_table_privilege(
                       'datariver_governance',
                       'governance.change_requests',
                       'TRIGGER'
                   )
                   OR EXISTS (
                       SELECT 1
                       FROM information_schema.columns AS column_contract
                       WHERE column_contract.table_schema = 'integration'
                         AND column_contract.table_name = 'jobs'
                         AND has_column_privilege(
                             'datariver_governance',
                             'integration.jobs',
                             column_contract.column_name,
                             'UPDATE'
                         ) IS DISTINCT FROM (
                             column_contract.column_name = ANY (ARRAY[
                                 'state', 'progress', 'result_ref', 'lease_until',
                                 'attempts', 'attempt_cycle', 'cycle_attempts',
                                 'lease_token_hash', 'lease_owner_id',
                                 'last_error_code', 'version', 'updated_at'
                             ])
                         )
                   )
                   OR EXISTS (
                       SELECT 1
                       FROM information_schema.columns AS column_contract
                       WHERE column_contract.table_schema = 'integration'
                         AND column_contract.table_name = 'job_attempts'
                         AND has_column_privilege(
                             'datariver_governance',
                             'integration.job_attempts',
                             column_contract.column_name,
                             'UPDATE'
                         ) IS DISTINCT FROM (
                             column_contract.column_name = ANY (ARRAY[
                                 'state', 'error_class',
                                 'external_response_hash', 'finished_at'
                             ])
                         )
                   )
                   OR EXISTS (
                       SELECT 1
                       FROM information_schema.columns AS column_contract
                       WHERE column_contract.table_schema = 'governance'
                         AND column_contract.table_name = 'change_requests'
                         AND has_column_privilege(
                             'datariver_governance',
                             'governance.change_requests',
                             column_contract.column_name,
                             'UPDATE'
                         ) IS DISTINCT FROM (
                             column_contract.column_name = ANY (ARRAY[
                                 'state', 'version', 'updated_at'
                             ])
                         )
                   )
               ) THEN
                RAISE EXCEPTION 'governance apply worker privilege contract drifted';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM integration.jobs AS apply_job
                JOIN governance.change_requests AS request
                  ON request.workspace_id = apply_job.workspace_id
                 AND request.id = apply_job.causation_id
                WHERE apply_job.job_type = 'DATAHUB_CHANGE_APPLY'
                  AND apply_job.state = 'COMPLETED'
                  AND request.state <> 'APPLIED'
            ) THEN
                RAISE EXCEPTION
                    'completed governance apply job is not bound to an applied request';
            END IF;
        END
        $datariver$;
        """
    )


def upgrade() -> None:
    existing = _column_count()
    if existing == 0:
        _add_columns()
    elif existing != 4:
        raise RuntimeError(
            "0048 governance apply lease columns are partially present; refusing migration"
        )
    _assert_columns_and_constraints()
    _install_triggers()
    _install_grants()
    _assert_runtime_contract()


def downgrade() -> None:
    # Claim evidence and the narrowed worker boundary are forward-only security controls.
    pass
