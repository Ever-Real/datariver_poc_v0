"""Atomically retain registration worker run-call results.

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPECTED_OBJECT_COUNT = 2
RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
SUBJECT_SETTING = "NULLIF(current_setting('app.subject_id', true), '')::uuid"


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.tables
                     WHERE table_schema = 'integration'
                       AND table_name = 'registration_worker_call_receipts')
                  + (SELECT count(*) FROM pg_constraint
                     WHERE conrelid =
                         to_regclass('integration.registration_worker_call_receipts')
                       AND conname =
                         'ck_registration_worker_call_receipts_state_shape')
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
            IF NOT EXISTS (
                SELECT 1
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'integration'
                  AND relation.relname = 'registration_worker_call_receipts'
                  AND relation.relkind = 'r'
                  AND relation.relpersistence = 'p'
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt table is not a canonical plain table';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('workspace_id', 'uuid', 'NO', -1),
                        ('operation', 'character varying', 'NO', 100),
                        ('key_hash', 'character varying', 'NO', 64),
                        ('request_hash', 'character varying', 'NO', 64),
                        ('worker_subject_id', 'uuid', 'NO', -1),
                        ('state', 'character varying', 'NO', 32),
                        ('work_kind', 'character varying', 'YES', 16),
                        ('work_id', 'uuid', 'YES', -1),
                        ('claim_attempt', 'integer', 'YES', -1),
                        ('claim_token_hash', 'character varying', 'YES', 64),
                        ('lease_expires_at', 'timestamp with time zone', 'YES', -1),
                        ('processed', 'boolean', 'YES', -1),
                        ('result', 'jsonb', 'YES', -1),
                        ('created_at', 'timestamp with time zone', 'NO', -1),
                        ('updated_at', 'timestamp with time zone', 'NO', -1)
                ) AS expected(
                    column_name,
                    data_type,
                    is_nullable,
                    character_maximum_length
                )
                LEFT JOIN information_schema.columns AS actual
                  ON actual.table_schema = 'integration'
                 AND actual.table_name = 'registration_worker_call_receipts'
                 AND actual.column_name = expected.column_name
                WHERE actual.column_name IS NULL
                   OR actual.data_type <> expected.data_type
                   OR actual.is_nullable <> expected.is_nullable
                   OR actual.column_default IS NOT NULL
                   OR actual.is_identity <> 'NO'
                   OR actual.is_generated <> 'NEVER'
                   OR (
                       expected.character_maximum_length >= 0
                       AND actual.character_maximum_length <>
                           expected.character_maximum_length
                   )
            ) OR (
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'integration'
                  AND table_name = 'registration_worker_call_receipts'
            ) <> 15 THEN
                RAISE EXCEPTION
                    'registration worker receipt columns do not match the canonical contract';
            END IF;

            IF (
                SELECT count(*)
                FROM pg_constraint
                WHERE conrelid =
                    'integration.registration_worker_call_receipts'::regclass
            ) <> 7 OR EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('pk_registration_worker_call_receipts', 'p', 'PRIMARY KEY'),
                        (
                            'ck_registration_worker_call_receipts_operation_allowlist',
                            'c',
                            'registration.manual-metadata.apply-run.v1'
                        ),
                        (
                            'ck_registration_worker_call_receipts_state_allowlist',
                            'c',
                            'COMPLETED'
                        ),
                        (
                            'ck_registration_worker_call_receipts_identity_hashes_valid',
                            'c',
                            'request_hash'
                        ),
                        (
                            'ck_registration_worker_call_receipts_claim_token_hash_valid',
                            'c',
                            'claim_token_hash'
                        ),
                        (
                            'ck_registration_worker_call_receipts_state_shape',
                            'c',
                            'lease_expires_at'
                        ),
                        (
                            'fk_registration_worker_call_receipts_subject',
                            'f',
                            'iam.workspace_memberships'
                        )
                ) AS expected(constraint_name, constraint_type, definition_fragment)
                LEFT JOIN pg_constraint AS actual
                  ON actual.conrelid =
                        'integration.registration_worker_call_receipts'::regclass
                 AND actual.conname = expected.constraint_name
                WHERE actual.oid IS NULL
                   OR actual.contype::text <> expected.constraint_type
                   OR actual.convalidated IS NOT TRUE
                   OR position(
                       expected.definition_fragment
                       IN pg_get_constraintdef(actual.oid)
                   ) = 0
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt constraints are missing, unvalidated, or drifted';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint AS constraint_contract
                WHERE constraint_contract.conrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND constraint_contract.conname =
                    'pk_registration_worker_call_receipts'
                  AND (
                      constraint_contract.condeferrable
                      OR constraint_contract.condeferred
                      OR (
                          SELECT array_agg(attribute.attname::text ORDER BY key.ordinality)
                          FROM unnest(constraint_contract.conkey)
                              WITH ORDINALITY AS key(attnum, ordinality)
                          JOIN pg_attribute AS attribute
                            ON attribute.attrelid = constraint_contract.conrelid
                           AND attribute.attnum = key.attnum
                      ) IS DISTINCT FROM
                          ARRAY['workspace_id', 'operation', 'key_hash']::text[]
                  )
            ) OR EXISTS (
                SELECT 1
                FROM pg_constraint AS constraint_contract
                WHERE constraint_contract.conrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND constraint_contract.conname =
                    'fk_registration_worker_call_receipts_subject'
                  AND (
                      constraint_contract.confrelid <>
                          'iam.workspace_memberships'::regclass
                      OR constraint_contract.confdeltype <> 'r'
                      OR constraint_contract.confupdtype <> 'a'
                      OR constraint_contract.confmatchtype <> 's'
                      OR constraint_contract.condeferrable
                      OR constraint_contract.condeferred
                      OR (
                          SELECT array_agg(attribute.attname::text ORDER BY key.ordinality)
                          FROM unnest(constraint_contract.conkey)
                              WITH ORDINALITY AS key(attnum, ordinality)
                          JOIN pg_attribute AS attribute
                            ON attribute.attrelid = constraint_contract.conrelid
                           AND attribute.attnum = key.attnum
                      ) IS DISTINCT FROM
                          ARRAY['workspace_id', 'worker_subject_id']::text[]
                      OR (
                          SELECT array_agg(attribute.attname::text ORDER BY key.ordinality)
                          FROM unnest(constraint_contract.confkey)
                              WITH ORDINALITY AS key(attnum, ordinality)
                          JOIN pg_attribute AS attribute
                            ON attribute.attrelid = constraint_contract.confrelid
                           AND attribute.attnum = key.attnum
                      ) IS DISTINCT FROM
                          ARRAY['workspace_id', 'subject_id']::text[]
                  )
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt primary/foreign key semantics are drifted';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND conname =
                    'ck_registration_worker_call_receipts_operation_allowlist'
                  AND position(
                      'registration.bulk-preparation.execute-run.v1'
                      IN pg_get_constraintdef(oid)
                  ) > 0
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND conname =
                    'ck_registration_worker_call_receipts_identity_hashes_valid'
                  AND position('key_hash' IN pg_get_constraintdef(oid)) > 0
                  AND position(
                      '^[0-9a-f]{64}$'
                      IN pg_get_constraintdef(oid)
                  ) > 0
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND conname =
                    'ck_registration_worker_call_receipts_state_shape'
                  AND position('claim_token_hash' IN pg_get_constraintdef(oid)) > 0
                  AND position('processed' IN pg_get_constraintdef(oid)) > 0
                  AND position('result' IN pg_get_constraintdef(oid)) > 0
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt check semantics are drifted';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        (
                            'ck_registration_worker_call_receipts_operation_allowlist',
                            concat(
                                'CHECK (operation::text = ANY (ARRAY[',
                                '''registration.manual-metadata.apply-run.v1''',
                                '::character varying, ',
                                '''registration.bulk-preparation.execute-run.v1''',
                                '::character varying]::text[]))'
                            )
                        ),
                        (
                            'ck_registration_worker_call_receipts_state_allowlist',
                            concat(
                                'CHECK (state::text = ANY (ARRAY[',
                                '''RUNNING''::character varying, ',
                                '''COMPLETED''::character varying]::text[]))'
                            )
                        ),
                        (
                            'ck_registration_worker_call_receipts_identity_hashes_valid',
                            concat(
                                'CHECK (request_hash::text ~ ',
                                '''^[0-9a-f]{64}$''::text AND key_hash::text ~ ',
                                '''^[0-9a-f]{64}$''::text)'
                            )
                        ),
                        (
                            'ck_registration_worker_call_receipts_claim_token_hash_valid',
                            concat(
                                'CHECK (claim_token_hash IS NULL OR ',
                                'claim_token_hash::text ~ ',
                                '''^[0-9a-f]{64}$''::text)'
                            )
                        ),
                        (
                            'ck_registration_worker_call_receipts_state_shape',
                            concat(
                                'CHECK (state::text = ''RUNNING''::text AND ',
                                'processed IS NULL AND result IS NULL AND ',
                                '(work_kind::text = ANY (ARRAY[',
                                '''MANUAL''::character varying, ',
                                '''BULK''::character varying]::text[])) AND ',
                                'work_id IS NOT NULL AND claim_attempt IS NOT NULL ',
                                'AND claim_attempt > 0 AND claim_token_hash IS NOT NULL ',
                                'AND lease_expires_at IS NOT NULL OR state::text = ',
                                '''COMPLETED''::text AND processed IS NOT NULL AND ',
                                'result IS NOT NULL AND claim_token_hash IS NULL AND ',
                                'lease_expires_at IS NULL)'
                            )
                        )
                ) AS expected(constraint_name, exact_definition)
                LEFT JOIN pg_constraint AS actual
                  ON actual.conrelid =
                        'integration.registration_worker_call_receipts'::regclass
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
                    'registration worker receipt check definitions are not canonical';
            END IF;

            IF (
                SELECT count(*)
                FROM pg_index
                WHERE indrelid =
                    'integration.registration_worker_call_receipts'::regclass
            ) <> 2 OR NOT EXISTS (
                SELECT 1
                FROM pg_index AS index_contract
                JOIN pg_class AS index_relation
                  ON index_relation.oid = index_contract.indexrelid
                JOIN pg_am AS access_method
                  ON access_method.oid = index_relation.relam
                WHERE index_contract.indrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND index_relation.relname =
                    'ix_registration_worker_call_receipts_running_lease'
                  AND access_method.amname = 'btree'
                  AND index_contract.indisvalid
                  AND index_contract.indisready
                  AND index_contract.indislive
                  AND NOT index_contract.indisunique
                  AND NOT index_contract.indisprimary
                  AND NOT index_contract.indisexclusion
                  AND index_contract.indnkeyatts = 1
                  AND index_contract.indnatts = 1
                  AND index_contract.indexprs IS NULL
                  AND position(
                      '(lease_expires_at)'
                      IN pg_get_indexdef(index_contract.indexrelid)
                  ) > 0
                  AND pg_get_expr(
                      index_contract.indpred,
                      index_contract.indrelid,
                      true
                  ) = 'state::text = ''RUNNING''::text'
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt indexes are incomplete or drifted';
            END IF;
        END
        $datariver$;
        """
    )


def _install_security_contract() -> None:
    op.execute(
        """
        ALTER TABLE integration.registration_worker_call_receipts
            ENABLE ROW LEVEL SECURITY;
        """
    )
    op.execute(
        """
        ALTER TABLE integration.registration_worker_call_receipts
            FORCE ROW LEVEL SECURITY;
        """
    )
    op.execute(
        """
        DROP POLICY IF EXISTS workspace_isolation
            ON integration.registration_worker_call_receipts;
        """
    )
    op.execute(
        """
        DO $datariver$
        DECLARE
            policy_record record;
        BEGIN
            FOR policy_record IN
                SELECT policyname
                FROM pg_policies
                WHERE schemaname = 'integration'
                  AND tablename = 'registration_worker_call_receipts'
            LOOP
                EXECUTE format(
                    'DROP POLICY %I ON integration.registration_worker_call_receipts',
                    policy_record.policyname
                );
            END LOOP;
        END
        $datariver$;
        """
    )
    op.execute(
        """
        DROP POLICY IF EXISTS registration_worker_call_scope
            ON integration.registration_worker_call_receipts;
        """
    )
    op.execute(
        """
        CREATE POLICY registration_worker_call_scope
            ON integration.registration_worker_call_receipts
            FOR ALL
            USING (
                workspace_id =
                    NULLIF(current_setting('app.workspace_id', true), '')::uuid
                AND worker_subject_id =
                    NULLIF(current_setting('app.subject_id', true), '')::uuid
            )
            WITH CHECK (
                workspace_id =
                    NULLIF(current_setting('app.workspace_id', true), '')::uuid
                AND worker_subject_id =
                    NULLIF(current_setting('app.subject_id', true), '')::uuid
            );
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            integration.guard_registration_worker_call_receipt()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SECURITY INVOKER
        SET search_path = pg_catalog
        AS $datariver$
        DECLARE
            raw_token text :=
                NULLIF(current_setting('app.registration_worker_claim_token', true), '');
            raw_token_hash text;
            canonical_claim boolean := false;
            canonical_completion boolean := false;
            fixed_recovery_completion boolean := false;
            fixed_superseded_completion boolean := false;
        BEGIN
            IF current_user <> 'datariver_app' THEN
                RAISE EXCEPTION
                    'only datariver_app may mutate registration worker call receipts'
                    USING ERRCODE = '42501';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'registration worker call receipts are immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF TG_OP = 'UPDATE' AND (
                OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
                OR OLD.operation IS DISTINCT FROM NEW.operation
                OR OLD.key_hash IS DISTINCT FROM NEW.key_hash
                OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
                OR OLD.worker_subject_id IS DISTINCT FROM NEW.worker_subject_id
                OR OLD.created_at IS DISTINCT FROM NEW.created_at
                OR OLD.state = 'COMPLETED'
            ) THEN
                RAISE EXCEPTION
                    'registration worker call receipt identity is immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.state = 'RUNNING' THEN
                IF (
                    NEW.operation =
                        'registration.manual-metadata.apply-run.v1'
                    AND NEW.work_kind IS DISTINCT FROM 'MANUAL'
                ) OR (
                    NEW.operation =
                        'registration.bulk-preparation.execute-run.v1'
                    AND NEW.work_kind IS DISTINCT FROM 'BULK'
                ) THEN
                    RAISE EXCEPTION
                        'registration worker call operation/work kind is invalid'
                        USING ERRCODE = '23514';
                END IF;
                IF raw_token IS NULL THEN
                    RAISE EXCEPTION
                        'registration worker call claim token is required'
                        USING ERRCODE = '23514';
                END IF;
                raw_token_hash :=
                    encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
                IF raw_token_hash <> NEW.claim_token_hash THEN
                    RAISE EXCEPTION
                        'registration worker call claim token does not match'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.work_kind = 'MANUAL' THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM governance.manual_metadata_submissions AS submission
                        WHERE submission.workspace_id = NEW.workspace_id
                          AND submission.id = NEW.work_id
                          AND submission.state = 'APPLYING'
                          AND submission.lease_epoch = NEW.claim_attempt
                          AND submission.lease_token_hash = NEW.claim_token_hash
                          AND submission.lease_owner_id = NEW.worker_subject_id
                          AND submission.lease_expires_at = NEW.lease_expires_at
                    ) INTO canonical_claim;
                ELSIF NEW.work_kind = 'BULK' THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM integration.upload_preparation_jobs AS preparation
                        WHERE preparation.workspace_id = NEW.workspace_id
                          AND preparation.id = NEW.work_id
                          AND preparation.state = 'PREPARING'
                          AND preparation.attempts = NEW.claim_attempt
                          AND encode(
                              sha256(convert_to(preparation.lease_token::text, 'UTF8')),
                              'hex'
                          ) = NEW.claim_token_hash
                          AND preparation.lease_until = NEW.lease_expires_at
                    ) INTO canonical_claim;
                END IF;
                IF canonical_claim IS NOT TRUE THEN
                    RAISE EXCEPTION
                        'registration worker call receipt lacks a current canonical claim'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_OP = 'INSERT' THEN
                IF NEW.state IS DISTINCT FROM 'COMPLETED'
                   OR NEW.processed IS DISTINCT FROM false
                   OR NEW.work_kind IS NOT NULL
                   OR NEW.work_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'only a bounded no-work result may be inserted as completed'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.claim_attempt IS NOT NULL
                   OR NEW.claim_token_hash IS NOT NULL
                   OR NEW.lease_expires_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'a no-work result cannot retain claim evidence'
                        USING ERRCODE = '23514';
                END IF;
                IF (
                    NEW.operation =
                        'registration.manual-metadata.apply-run.v1'
                    AND NEW.result IS DISTINCT FROM jsonb_build_object(
                        'processed', false,
                        'submission_id', NULL,
                        'serial_number', NULL,
                        'state', NULL
                    )
                    AND NEW.result IS DISTINCT FROM jsonb_build_object(
                        'processed', false,
                        'submission_id', NULL,
                        'serial_number', NULL,
                        'state', 'RECOVERY_LIMIT_REACHED'
                    )
                ) OR (
                    NEW.operation =
                        'registration.bulk-preparation.execute-run.v1'
                    AND NEW.result IS DISTINCT FROM jsonb_build_object(
                        'processed', false,
                        'preparation_id', NULL,
                        'state', NULL,
                        'item_count', NULL
                    )
                    AND NEW.result IS DISTINCT FROM jsonb_build_object(
                        'processed', false,
                        'preparation_id', NULL,
                        'state', 'RECOVERY_LIMIT_REACHED',
                        'item_count', NULL
                    )
                ) THEN
                    RAISE EXCEPTION
                        'registration worker call no-work result is not canonical'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                IF OLD.state IS DISTINCT FROM 'RUNNING'
                   OR NEW.state IS DISTINCT FROM 'COMPLETED'
                   OR OLD.work_kind IS DISTINCT FROM NEW.work_kind
                   OR OLD.work_id IS DISTINCT FROM NEW.work_id
                   OR OLD.claim_attempt IS DISTINCT FROM NEW.claim_attempt
                   OR NEW.processed IS DISTINCT FROM true
                   OR NEW.claim_token_hash IS NOT NULL
                   OR NEW.lease_expires_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'registration worker call terminal transition is invalid'
                        USING ERRCODE = '23514';
                END IF;

                IF raw_token IS NOT NULL THEN
                    raw_token_hash :=
                        encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');
                END IF;

                IF OLD.work_kind = 'MANUAL'
                   AND raw_token_hash = OLD.claim_token_hash THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM governance.manual_metadata_submissions AS submission
                        JOIN governance.manual_metadata_apply_attempts AS attempt
                          ON attempt.workspace_id = submission.workspace_id
                         AND attempt.submission_id = submission.id
                         AND attempt.attempt_no = OLD.claim_attempt
                         AND attempt.lease_epoch = OLD.claim_attempt
                         AND attempt.lease_token_hash = OLD.claim_token_hash
                         AND attempt.worker_subject_id = OLD.worker_subject_id
                        WHERE submission.workspace_id = OLD.workspace_id
                          AND submission.id = OLD.work_id
                          AND (
                              (
                                  submission.attempts = OLD.claim_attempt
                                  AND submission.state = 'APPLIED'
                                  AND attempt.state = 'APPLIED'
                                  AND NEW.result = jsonb_build_object(
                                      'processed', true,
                                      'submission_id', submission.id::text,
                                      'serial_number', submission.serial_number,
                                      'state', 'APPLIED'
                                  )
                              )
                              OR (
                                  submission.attempts = OLD.claim_attempt
                                  AND submission.state = 'QUEUED'
                                  AND attempt.state = 'RETRY_WAIT'
                                  AND NEW.result = jsonb_build_object(
                                      'processed', true,
                                      'submission_id', submission.id::text,
                                      'serial_number', submission.serial_number,
                                      'state', 'QUEUED'
                                  )
                              )
                              OR (
                                  submission.attempts = OLD.claim_attempt
                                  AND submission.state = 'FAILED'
                                  AND attempt.state = 'FAILED'
                                  AND NEW.result = jsonb_build_object(
                                      'processed', true,
                                      'submission_id', submission.id::text,
                                      'serial_number', submission.serial_number,
                                      'state', 'FAILED'
                                  )
                              )
                              OR (
                                  attempt.state = 'SUPERSEDED'
                                  AND submission.attempts > OLD.claim_attempt
                                  AND submission.lease_epoch > OLD.claim_attempt
                                  AND EXISTS (
                                      SELECT 1
                                      FROM governance.manual_metadata_apply_attempts
                                          AS newer_attempt
                                      WHERE newer_attempt.workspace_id =
                                          submission.workspace_id
                                        AND newer_attempt.submission_id =
                                            submission.id
                                        AND newer_attempt.attempt_no >
                                            OLD.claim_attempt
                                        AND newer_attempt.lease_epoch >
                                            OLD.claim_attempt
                                  )
                                  AND NEW.result = jsonb_build_object(
                                      'processed', true,
                                      'submission_id', submission.id::text,
                                      'serial_number', submission.serial_number,
                                      'state', 'SUPERSEDED'
                                  )
                              )
                          )
                    ) INTO canonical_completion;
                ELSIF OLD.work_kind = 'BULK'
                      AND raw_token_hash = OLD.claim_token_hash THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM integration.upload_preparation_jobs AS preparation
                        WHERE preparation.workspace_id = OLD.workspace_id
                          AND preparation.id = OLD.work_id
                          AND (
                              (
                                  preparation.attempts = OLD.claim_attempt
                                  AND preparation.state = 'READY'
                                  AND preparation.rows_processed =
                                      preparation.total_rows
                                  AND preparation.total_rows > 0
                                  AND EXISTS (
                                      SELECT 1
                                      FROM integration.upload_preparation_receipts
                                          AS preparation_receipt
                                      WHERE preparation_receipt.workspace_id =
                                          preparation.workspace_id
                                        AND preparation_receipt.preparation_job_id =
                                            preparation.id
                                        AND preparation_receipt.item_count =
                                            preparation.total_rows
                                  )
                                  AND NEW.result = jsonb_build_object(
                                      'processed', true,
                                      'preparation_id', preparation.id::text,
                                      'state', 'READY',
                                      'item_count', preparation.total_rows
                                  )
                              )
                              OR (
                                  preparation.attempts = OLD.claim_attempt
                                  AND preparation.state IN ('QUEUED', 'FAILED')
                                  AND NEW.result = jsonb_build_object(
                                      'processed', true,
                                      'preparation_id', preparation.id::text,
                                      'state', preparation.state,
                                      'item_count', NULL
                                  )
                              )
                              OR (
                                  preparation.attempts > OLD.claim_attempt
                                  AND EXISTS (
                                      SELECT 1
                                      FROM integration.registration_worker_call_receipts
                                          AS newer_receipt
                                      WHERE newer_receipt.workspace_id =
                                          OLD.workspace_id
                                        AND newer_receipt.worker_subject_id =
                                            OLD.worker_subject_id
                                        AND newer_receipt.work_kind = 'BULK'
                                        AND newer_receipt.work_id = OLD.work_id
                                        AND newer_receipt.claim_attempt >
                                            OLD.claim_attempt
                                        AND newer_receipt.key_hash <> OLD.key_hash
                                  )
                                  AND NEW.result = jsonb_build_object(
                                      'processed', true,
                                      'preparation_id', preparation.id::text,
                                      'state', 'SUPERSEDED',
                                      'item_count', NULL
                                  )
                              )
                          )
                    ) INTO canonical_completion;
                END IF;

                IF raw_token IS NULL AND OLD.work_kind = 'MANUAL' THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM governance.manual_metadata_submissions AS submission
                        JOIN governance.manual_metadata_apply_attempts AS attempt
                          ON attempt.workspace_id = submission.workspace_id
                         AND attempt.submission_id = submission.id
                         AND attempt.lease_epoch = OLD.claim_attempt
                        WHERE submission.workspace_id = OLD.workspace_id
                          AND submission.id = OLD.work_id
                          AND OLD.lease_expires_at <= clock_timestamp()
                          AND submission.state = 'FAILED'
                          AND submission.last_error_code = 'WORKER_LEASE_EXHAUSTED'
                          AND submission.attempts = OLD.claim_attempt
                          AND submission.lease_token_hash IS NULL
                          AND submission.lease_owner_id IS NULL
                          AND submission.lease_expires_at IS NULL
                          AND attempt.attempt_no = OLD.claim_attempt
                          AND attempt.lease_epoch = OLD.claim_attempt
                          AND attempt.lease_token_hash = OLD.claim_token_hash
                          AND attempt.worker_subject_id = OLD.worker_subject_id
                          AND attempt.state = 'FAILED'
                          AND attempt.failure_code = 'WORKER_LEASE_EXHAUSTED'
                          AND NEW.state = 'COMPLETED'
                          AND NEW.processed IS TRUE
                          AND NEW.claim_token_hash IS NULL
                          AND NEW.lease_expires_at IS NULL
                          AND NEW.result = jsonb_build_object(
                              'processed', true,
                              'submission_id', submission.id::text,
                              'serial_number', submission.serial_number,
                              'state', 'FAILED'
                          )
                    ) INTO fixed_recovery_completion;
                ELSIF raw_token IS NULL AND OLD.work_kind = 'BULK' THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM integration.upload_preparation_jobs AS preparation
                        WHERE preparation.workspace_id = OLD.workspace_id
                          AND preparation.id = OLD.work_id
                          AND OLD.lease_expires_at <= clock_timestamp()
                          AND preparation.state = 'FAILED'
                          AND preparation.last_error_code = 'WORKER_LEASE_EXHAUSTED'
                          AND preparation.attempts = OLD.claim_attempt
                          AND preparation.lease_token IS NULL
                          AND preparation.lease_until IS NULL
                          AND NEW.state = 'COMPLETED'
                          AND NEW.processed IS TRUE
                          AND NEW.claim_token_hash IS NULL
                          AND NEW.lease_expires_at IS NULL
                          AND NEW.result = jsonb_build_object(
                              'processed', true,
                              'preparation_id', preparation.id::text,
                              'state', 'FAILED',
                              'item_count', NULL
                          )
                    ) INTO fixed_recovery_completion;
                END IF;

                IF raw_token IS NULL AND OLD.work_kind = 'MANUAL' THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM governance.manual_metadata_submissions AS submission
                        JOIN governance.manual_metadata_apply_attempts AS old_attempt
                          ON old_attempt.workspace_id = submission.workspace_id
                         AND old_attempt.submission_id = submission.id
                         AND old_attempt.attempt_no = OLD.claim_attempt
                         AND old_attempt.lease_epoch = OLD.claim_attempt
                         AND old_attempt.lease_token_hash = OLD.claim_token_hash
                         AND old_attempt.worker_subject_id = OLD.worker_subject_id
                        WHERE submission.workspace_id = OLD.workspace_id
                          AND submission.id = OLD.work_id
                          AND OLD.lease_expires_at <= clock_timestamp()
                          AND submission.attempts > OLD.claim_attempt
                          AND submission.lease_epoch > OLD.claim_attempt
                          AND old_attempt.state = 'SUPERSEDED'
                          AND old_attempt.failure_code = 'LEASE_EXPIRED'
                          AND EXISTS (
                              SELECT 1
                              FROM governance.manual_metadata_apply_attempts
                                  AS newer_attempt
                              WHERE newer_attempt.workspace_id =
                                  submission.workspace_id
                                AND newer_attempt.submission_id = submission.id
                                AND newer_attempt.attempt_no > OLD.claim_attempt
                                AND newer_attempt.lease_epoch > OLD.claim_attempt
                          )
                          AND NEW.result = jsonb_build_object(
                              'processed', true,
                              'submission_id', submission.id::text,
                              'serial_number', submission.serial_number,
                              'state', 'SUPERSEDED'
                          )
                    ) INTO fixed_superseded_completion;
                ELSIF raw_token IS NULL AND OLD.work_kind = 'BULK' THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM integration.upload_preparation_jobs AS preparation
                        WHERE preparation.workspace_id = OLD.workspace_id
                          AND preparation.id = OLD.work_id
                          AND OLD.lease_expires_at <= clock_timestamp()
                          AND preparation.attempts > OLD.claim_attempt
                          AND EXISTS (
                              SELECT 1
                              FROM integration.registration_worker_call_receipts
                                  AS newer_receipt
                              WHERE newer_receipt.workspace_id = OLD.workspace_id
                                AND newer_receipt.worker_subject_id =
                                    OLD.worker_subject_id
                                AND newer_receipt.work_kind = 'BULK'
                                AND newer_receipt.work_id = OLD.work_id
                                AND newer_receipt.claim_attempt > OLD.claim_attempt
                                AND newer_receipt.key_hash <> OLD.key_hash
                          )
                          AND NEW.result = jsonb_build_object(
                              'processed', true,
                              'preparation_id', preparation.id::text,
                              'state', 'SUPERSEDED',
                              'item_count', NULL
                          )
                    ) INTO fixed_superseded_completion;
                END IF;

                IF canonical_completion IS NOT TRUE
                   AND fixed_recovery_completion IS NOT TRUE
                   AND fixed_superseded_completion IS NOT TRUE THEN
                    RAISE EXCEPTION
                        'registration worker call terminal result is not canonical'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $datariver$;
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION
            integration.guard_registration_worker_call_receipt()
            FROM PUBLIC;
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION
            integration.guard_registration_worker_call_receipt()
            FROM datariver_app;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS guard_registration_worker_call_receipt
            ON integration.registration_worker_call_receipts;
        """
    )
    op.execute(
        """
        CREATE TRIGGER guard_registration_worker_call_receipt
            BEFORE INSERT OR UPDATE OR DELETE
            ON integration.registration_worker_call_receipts
            FOR EACH ROW
            EXECUTE FUNCTION
                integration.guard_registration_worker_call_receipt();
        """
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app'
            ) THEN
                RAISE EXCEPTION
                    'datariver_app must exist before registration receipt installation';
            END IF;

            REVOKE ALL
                ON integration.registration_worker_call_receipts
                FROM PUBLIC;
            REVOKE ALL
                ON integration.registration_worker_call_receipts
                FROM datariver_app;
            GRANT SELECT, INSERT
                ON integration.registration_worker_call_receipts
                TO datariver_app;
            GRANT UPDATE (
                state,
                work_kind,
                work_id,
                claim_attempt,
                claim_token_hash,
                lease_expires_at,
                processed,
                result,
                updated_at
            )
                ON integration.registration_worker_call_receipts
                TO datariver_app;
        END
        $datariver$;
        """
    )


def _assert_runtime_contract() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            expected_scope text :=
                '((workspace_id = (NULLIF(current_setting('
                || '''app.workspace_id''::text, true), ''''::text))::uuid) '
                || 'AND (worker_subject_id = (NULLIF(current_setting('
                || '''app.subject_id''::text, true), ''''::text))::uuid))';
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_class
                WHERE oid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND relrowsecurity IS TRUE
                  AND relforcerowsecurity IS TRUE
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt RLS is not forced';
            END IF;

            IF (
                SELECT count(*)
                FROM pg_policies
                WHERE schemaname = 'integration'
                  AND tablename = 'registration_worker_call_receipts'
            ) <> 1 OR NOT EXISTS (
                SELECT 1
                FROM pg_policies AS policy
                WHERE policy.schemaname = 'integration'
                  AND policy.tablename =
                      'registration_worker_call_receipts'
                  AND policy.policyname =
                      'registration_worker_call_scope'
                  AND policy.permissive = 'PERMISSIVE'
                  AND policy.roles::text = '{public}'
                  AND policy.cmd = 'ALL'
                  AND policy.qual = expected_scope
                  AND policy.with_check = expected_scope
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt RLS policy is incomplete or drifted';
            END IF;

            IF (
                SELECT count(*)
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'integration'
                  AND procedure.proname =
                      'guard_registration_worker_call_receipt'
            ) <> 1 OR NOT EXISTS (
                SELECT 1
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                JOIN pg_language AS language
                  ON language.oid = procedure.prolang
                WHERE namespace.nspname = 'integration'
                  AND procedure.proname =
                      'guard_registration_worker_call_receipt'
                  AND procedure.pronargs = 0
                  AND procedure.prorettype = 'trigger'::regtype
                  AND procedure.prokind = 'f'
                  AND procedure.provolatile = 'v'
                  AND procedure.prosecdef IS FALSE
                  AND procedure.proconfig IS NOT DISTINCT FROM
                      ARRAY['search_path=pg_catalog']::text[]
                  AND language.lanname = 'plpgsql'
                  AND position(
                      'governance.manual_metadata_apply_attempts'
                      IN pg_get_functiondef(procedure.oid)
                  ) > 0
                  AND position(
                      'integration.upload_preparation_receipts'
                      IN pg_get_functiondef(procedure.oid)
                  ) > 0
                  AND position(
                      'WORKER_LEASE_EXHAUSTED'
                      IN pg_get_functiondef(procedure.oid)
                  ) > 0
                  AND position(
                      'SUPERSEDED'
                      IN pg_get_functiondef(procedure.oid)
                  ) > 0
                  AND position(
                      'registration worker call no-work result is not canonical'
                      IN pg_get_functiondef(procedure.oid)
                  ) > 0
                  AND position(
                      'registration worker call terminal result is not canonical'
                      IN pg_get_functiondef(procedure.oid)
                  ) > 0
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt trigger function is incomplete or drifted';
            END IF;

            IF (
                SELECT count(*)
                FROM pg_trigger
                WHERE tgrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND tgisinternal IS FALSE
            ) <> 1 OR NOT EXISTS (
                SELECT 1
                FROM pg_trigger AS trigger_contract
                WHERE tgrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND tgname = 'guard_registration_worker_call_receipt'
                  AND tgenabled = 'O'
                  AND tgtype = 31
                  AND tgisinternal IS FALSE
                  AND tgfoid =
                      'integration.guard_registration_worker_call_receipt()'
                          ::regprocedure
                  AND tgqual IS NULL
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt runtime controls are incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM integration.registration_worker_call_receipts AS receipt
                WHERE (
                    receipt.state = 'RUNNING'
                    AND (
                        (
                            receipt.operation =
                                'registration.manual-metadata.apply-run.v1'
                            AND receipt.work_kind IS DISTINCT FROM 'MANUAL'
                        )
                        OR (
                            receipt.operation =
                                'registration.bulk-preparation.execute-run.v1'
                            AND receipt.work_kind IS DISTINCT FROM 'BULK'
                        )
                    )
                ) OR (
                    receipt.state = 'COMPLETED'
                    AND receipt.processed IS FALSE
                    AND (
                        receipt.work_kind IS NOT NULL
                        OR receipt.work_id IS NOT NULL
                        OR receipt.claim_attempt IS NOT NULL
                        OR (
                            receipt.operation =
                                'registration.manual-metadata.apply-run.v1'
                            AND receipt.result IS DISTINCT FROM jsonb_build_object(
                                'processed', false,
                                'submission_id', NULL,
                                'serial_number', NULL,
                                'state', NULL
                            )
                            AND receipt.result IS DISTINCT FROM jsonb_build_object(
                                'processed', false,
                                'submission_id', NULL,
                                'serial_number', NULL,
                                'state', 'RECOVERY_LIMIT_REACHED'
                            )
                        )
                        OR (
                            receipt.operation =
                                'registration.bulk-preparation.execute-run.v1'
                            AND receipt.result IS DISTINCT FROM jsonb_build_object(
                                'processed', false,
                                'preparation_id', NULL,
                                'state', NULL,
                                'item_count', NULL
                            )
                            AND receipt.result IS DISTINCT FROM jsonb_build_object(
                                'processed', false,
                                'preparation_id', NULL,
                                'state', 'RECOVERY_LIMIT_REACHED',
                                'item_count', NULL
                            )
                        )
                    )
                ) OR (
                    receipt.state = 'COMPLETED'
                    AND receipt.processed IS TRUE
                    AND (
                        receipt.work_kind IS NULL
                        OR receipt.work_id IS NULL
                        OR receipt.claim_attempt IS NULL
                        OR jsonb_typeof(receipt.result) IS DISTINCT FROM 'object'
                        OR receipt.result -> 'processed' IS DISTINCT FROM
                            'true'::jsonb
                        OR (
                            receipt.operation =
                                'registration.manual-metadata.apply-run.v1'
                            AND (
                                receipt.work_kind <> 'MANUAL'
                                OR CASE
                                    WHEN jsonb_typeof(receipt.result) = 'object'
                                    THEN (
                                        SELECT count(*)
                                        FROM jsonb_object_keys(receipt.result)
                                    )
                                    ELSE 0
                                END <> 4
                                OR receipt.result ->> 'submission_id' IS DISTINCT FROM
                                    receipt.work_id::text
                                OR jsonb_typeof(
                                    receipt.result -> 'serial_number'
                                ) IS DISTINCT FROM 'number'
                                OR receipt.result ->> 'serial_number'
                                    !~ '^[1-9][0-9]*$'
                                OR (
                                    receipt.result ->> 'state' = ANY (
                                        ARRAY[
                                            'QUEUED',
                                            'FAILED',
                                            'APPLIED',
                                            'SUPERSEDED'
                                        ]
                                    )
                                ) IS DISTINCT FROM TRUE
                            )
                        )
                        OR (
                            receipt.operation =
                                'registration.bulk-preparation.execute-run.v1'
                            AND (
                                receipt.work_kind <> 'BULK'
                                OR CASE
                                    WHEN jsonb_typeof(receipt.result) = 'object'
                                    THEN (
                                        SELECT count(*)
                                        FROM jsonb_object_keys(receipt.result)
                                    )
                                    ELSE 0
                                END <> 4
                                OR receipt.result ->> 'preparation_id'
                                    IS DISTINCT FROM
                                    receipt.work_id::text
                                OR (
                                    receipt.result ->> 'state' = ANY (
                                        ARRAY[
                                            'READY',
                                            'QUEUED',
                                            'FAILED',
                                            'SUPERSEDED'
                                        ]
                                    )
                                ) IS DISTINCT FROM TRUE
                                OR (
                                    receipt.result ->> 'state' = 'READY'
                                    AND (
                                        jsonb_typeof(
                                            receipt.result -> 'item_count'
                                        ) IS DISTINCT FROM 'number'
                                        OR receipt.result ->> 'item_count'
                                            !~ '^[1-9][0-9]*$'
                                    )
                                )
                                OR (
                                    receipt.result ->> 'state'
                                        IS DISTINCT FROM 'READY'
                                    AND receipt.result -> 'item_count'
                                        IS DISTINCT FROM
                                        'null'::jsonb
                                )
                            )
                        )
                    )
                )
            ) THEN
                RAISE EXCEPTION
                    'existing registration worker receipt rows violate the result contract';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM integration.registration_worker_call_receipts AS receipt
                WHERE receipt.state = 'RUNNING'
                  AND receipt.work_kind = 'MANUAL'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM governance.manual_metadata_submissions AS submission
                      LEFT JOIN governance.manual_metadata_apply_attempts AS old_attempt
                        ON old_attempt.workspace_id = submission.workspace_id
                       AND old_attempt.submission_id = submission.id
                       AND old_attempt.attempt_no = receipt.claim_attempt
                       AND old_attempt.lease_epoch = receipt.claim_attempt
                      WHERE submission.workspace_id = receipt.workspace_id
                        AND submission.id = receipt.work_id
                        AND (
                            (
                                submission.state = 'APPLYING'
                                AND submission.lease_epoch = receipt.claim_attempt
                                AND submission.lease_token_hash =
                                    receipt.claim_token_hash
                                AND submission.lease_owner_id =
                                    receipt.worker_subject_id
                                AND submission.lease_expires_at =
                                    receipt.lease_expires_at
                                AND old_attempt.state = 'RUNNING'
                                AND old_attempt.lease_token_hash =
                                    receipt.claim_token_hash
                                AND old_attempt.worker_subject_id =
                                    receipt.worker_subject_id
                            )
                            OR (
                                submission.attempts > receipt.claim_attempt
                                AND submission.lease_epoch > receipt.claim_attempt
                                AND old_attempt.state = 'SUPERSEDED'
                                AND old_attempt.failure_code = 'LEASE_EXPIRED'
                                AND EXISTS (
                                    SELECT 1
                                    FROM governance.manual_metadata_apply_attempts
                                        AS newer_attempt
                                    WHERE newer_attempt.workspace_id =
                                        submission.workspace_id
                                      AND newer_attempt.submission_id =
                                        submission.id
                                      AND newer_attempt.attempt_no >
                                          receipt.claim_attempt
                                      AND newer_attempt.lease_epoch >
                                          receipt.claim_attempt
                                )
                            )
                        )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM integration.registration_worker_call_receipts AS receipt
                WHERE receipt.state = 'RUNNING'
                  AND receipt.work_kind = 'BULK'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM integration.upload_preparation_jobs AS preparation
                      WHERE preparation.workspace_id = receipt.workspace_id
                        AND preparation.id = receipt.work_id
                        AND (
                            (
                                preparation.state = 'PREPARING'
                                AND preparation.attempts = receipt.claim_attempt
                                AND encode(
                                    sha256(
                                        convert_to(
                                            preparation.lease_token::text,
                                            'UTF8'
                                        )
                                    ),
                                    'hex'
                                ) = receipt.claim_token_hash
                                AND preparation.lease_until =
                                    receipt.lease_expires_at
                            )
                            OR (
                                preparation.attempts > receipt.claim_attempt
                                AND EXISTS (
                                    SELECT 1
                                    FROM integration.registration_worker_call_receipts
                                        AS newer_receipt
                                    WHERE newer_receipt.workspace_id =
                                        receipt.workspace_id
                                      AND newer_receipt.worker_subject_id =
                                          receipt.worker_subject_id
                                      AND newer_receipt.work_kind = 'BULK'
                                      AND newer_receipt.work_id = receipt.work_id
                                      AND newer_receipt.claim_attempt >
                                          receipt.claim_attempt
                                      AND newer_receipt.key_hash <>
                                          receipt.key_hash
                                )
                            )
                        )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM integration.registration_worker_call_receipts AS receipt
                WHERE receipt.state = 'COMPLETED'
                  AND receipt.processed IS TRUE
                  AND receipt.work_kind = 'MANUAL'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM governance.manual_metadata_submissions AS submission
                      JOIN governance.manual_metadata_apply_attempts AS attempt
                        ON attempt.workspace_id = submission.workspace_id
                       AND attempt.submission_id = submission.id
                       AND attempt.attempt_no = receipt.claim_attempt
                       AND attempt.lease_epoch = receipt.claim_attempt
                      WHERE submission.workspace_id = receipt.workspace_id
                        AND submission.id = receipt.work_id
                        AND receipt.result ->> 'serial_number' =
                            submission.serial_number::text
                        AND (
                            (
                                receipt.result ->> 'state' = 'APPLIED'
                                AND submission.state = 'APPLIED'
                                AND submission.attempts = receipt.claim_attempt
                                AND attempt.state = 'APPLIED'
                            )
                            OR (
                                receipt.result ->> 'state' = 'QUEUED'
                                AND attempt.state = 'RETRY_WAIT'
                                AND (
                                    (
                                        submission.state = 'QUEUED'
                                        AND submission.attempts =
                                            receipt.claim_attempt
                                    )
                                    OR (
                                        submission.attempts >
                                            receipt.claim_attempt
                                        AND EXISTS (
                                            SELECT 1
                                            FROM governance.manual_metadata_apply_attempts
                                                AS newer_attempt
                                            WHERE newer_attempt.workspace_id =
                                                submission.workspace_id
                                              AND newer_attempt.submission_id =
                                                  submission.id
                                              AND newer_attempt.attempt_no >
                                                  receipt.claim_attempt
                                              AND newer_attempt.lease_epoch >
                                                  receipt.claim_attempt
                                        )
                                    )
                                )
                            )
                            OR (
                                receipt.result ->> 'state' = 'FAILED'
                                AND submission.state = 'FAILED'
                                AND submission.attempts = receipt.claim_attempt
                                AND attempt.state = 'FAILED'
                            )
                            OR (
                                receipt.result ->> 'state' = 'SUPERSEDED'
                                AND attempt.state = 'SUPERSEDED'
                                AND submission.attempts > receipt.claim_attempt
                                AND EXISTS (
                                    SELECT 1
                                    FROM governance.manual_metadata_apply_attempts
                                        AS newer_attempt
                                    WHERE newer_attempt.workspace_id =
                                        submission.workspace_id
                                      AND newer_attempt.submission_id =
                                        submission.id
                                      AND newer_attempt.attempt_no >
                                          receipt.claim_attempt
                                )
                            )
                        )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM integration.registration_worker_call_receipts AS receipt
                WHERE receipt.state = 'COMPLETED'
                  AND receipt.processed IS TRUE
                  AND receipt.work_kind = 'BULK'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM integration.upload_preparation_jobs AS preparation
                      WHERE preparation.workspace_id = receipt.workspace_id
                        AND preparation.id = receipt.work_id
                        AND preparation.attempts >= receipt.claim_attempt
                        AND (
                            (
                                receipt.result ->> 'state' = 'READY'
                                AND preparation.state = 'READY'
                                AND preparation.attempts = receipt.claim_attempt
                                AND preparation.rows_processed =
                                    preparation.total_rows
                                AND preparation.total_rows =
                                    (receipt.result ->> 'item_count')::integer
                                AND EXISTS (
                                    SELECT 1
                                    FROM integration.upload_preparation_receipts
                                        AS preparation_receipt
                                    WHERE preparation_receipt.workspace_id =
                                        preparation.workspace_id
                                      AND preparation_receipt.preparation_job_id =
                                          preparation.id
                                      AND preparation_receipt.item_count =
                                          preparation.total_rows
                                )
                            )
                            OR (
                                receipt.result ->> 'state' = 'QUEUED'
                                AND (
                                    (
                                        preparation.attempts =
                                            receipt.claim_attempt
                                        AND preparation.state = 'QUEUED'
                                    )
                                    OR (
                                        preparation.attempts >
                                            receipt.claim_attempt
                                        AND EXISTS (
                                            SELECT 1
                                            FROM integration.registration_worker_call_receipts
                                                AS newer_receipt
                                            WHERE newer_receipt.workspace_id =
                                                receipt.workspace_id
                                              AND newer_receipt.worker_subject_id =
                                                  receipt.worker_subject_id
                                              AND newer_receipt.work_kind = 'BULK'
                                              AND newer_receipt.work_id =
                                                  receipt.work_id
                                              AND newer_receipt.claim_attempt >
                                                  receipt.claim_attempt
                                              AND newer_receipt.key_hash <>
                                                  receipt.key_hash
                                        )
                                    )
                                )
                            )
                            OR (
                                receipt.result ->> 'state' = 'FAILED'
                                AND preparation.attempts =
                                    receipt.claim_attempt
                                AND preparation.state = 'FAILED'
                            )
                            OR (
                                receipt.result ->> 'state' = 'SUPERSEDED'
                                AND preparation.attempts > receipt.claim_attempt
                                AND EXISTS (
                                    SELECT 1
                                    FROM integration.registration_worker_call_receipts
                                        AS newer_receipt
                                    WHERE newer_receipt.workspace_id =
                                        receipt.workspace_id
                                      AND newer_receipt.worker_subject_id =
                                          receipt.worker_subject_id
                                      AND newer_receipt.work_kind = 'BULK'
                                      AND newer_receipt.work_id = receipt.work_id
                                      AND newer_receipt.claim_attempt >
                                          receipt.claim_attempt
                                      AND newer_receipt.key_hash <>
                                          receipt.key_hash
                                )
                            )
                        )
                  )
            ) THEN
                RAISE EXCEPTION
                    'existing registration worker receipts lack canonical work evidence';
            END IF;

            IF NOT has_table_privilege(
                'datariver_app',
                'integration.registration_worker_call_receipts',
                'SELECT'
            ) OR NOT has_table_privilege(
                'datariver_app',
                'integration.registration_worker_call_receipts',
                'INSERT'
            ) OR has_table_privilege(
                'datariver_app',
                'integration.registration_worker_call_receipts',
                'UPDATE'
            ) OR has_table_privilege(
                'datariver_app',
                'integration.registration_worker_call_receipts',
                'DELETE'
            ) OR has_table_privilege(
                'datariver_app',
                'integration.registration_worker_call_receipts',
                'TRUNCATE'
            ) OR has_table_privilege(
                'datariver_app',
                'integration.registration_worker_call_receipts',
                'REFERENCES'
            ) OR has_table_privilege(
                'datariver_app',
                'integration.registration_worker_call_receipts',
                'TRIGGER'
            ) THEN
                RAISE EXCEPTION
                    'datariver_app receipt table privileges are overbroad or incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('state'),
                        ('work_kind'),
                        ('work_id'),
                        ('claim_attempt'),
                        ('claim_token_hash'),
                        ('lease_expires_at'),
                        ('processed'),
                        ('result'),
                        ('updated_at')
                ) AS allowed(column_name)
                WHERE NOT has_column_privilege(
                    'datariver_app',
                    'integration.registration_worker_call_receipts',
                    allowed.column_name,
                    'UPDATE'
                )
            ) OR EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('workspace_id'),
                        ('operation'),
                        ('key_hash'),
                        ('request_hash'),
                        ('worker_subject_id'),
                        ('created_at')
                ) AS immutable(column_name)
                WHERE has_column_privilege(
                    'datariver_app',
                    'integration.registration_worker_call_receipts',
                    immutable.column_name,
                    'UPDATE'
                )
            ) THEN
                RAISE EXCEPTION
                    'datariver_app receipt column privileges are incomplete or overbroad';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_class AS relation
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(
                        relation.relacl,
                        acldefault('r', relation.relowner)
                    )
                ) AS privilege
                WHERE relation.oid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND privilege.grantee NOT IN (
                      relation.relowner,
                      (
                          SELECT oid
                          FROM pg_roles
                          WHERE rolname = 'datariver_app'
                      )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM pg_attribute AS attribute
                JOIN pg_class AS relation
                  ON relation.oid = attribute.attrelid
                CROSS JOIN LATERAL aclexplode(attribute.attacl) AS privilege
                WHERE attribute.attrelid =
                    'integration.registration_worker_call_receipts'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND privilege.grantee NOT IN (
                      relation.relowner,
                      (
                          SELECT oid
                          FROM pg_roles
                          WHERE rolname = 'datariver_app'
                      )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM pg_proc AS procedure
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(
                        procedure.proacl,
                        acldefault('f', procedure.proowner)
                    )
                ) AS privilege
                WHERE procedure.oid =
                    'integration.guard_registration_worker_call_receipt()'
                        ::regprocedure
                  AND privilege.grantee <> procedure.proowner
            ) OR has_function_privilege(
                'datariver_app',
                'integration.guard_registration_worker_call_receipt()',
                'EXECUTE'
            ) THEN
                RAISE EXCEPTION
                    'registration worker receipt PUBLIC/function grants are overbroad';
            END IF;
        END
        $datariver$;
        """
    )


def upgrade() -> None:
    existing = _existing_object_count()
    if existing == EXPECTED_OBJECT_COUNT:
        _assert_existing_contract()
        _install_security_contract()
        _assert_runtime_contract()
        return
    if existing != 0:
        raise RuntimeError(
            "0047 registration worker receipt objects are partially present; "
            "refusing an ambiguous migration"
        )

    op.create_table(
        "registration_worker_call_receipts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("worker_subject_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("work_kind", sa.String(length=16), nullable=True),
        sa.Column("work_id", sa.Uuid(), nullable=True),
        sa.Column("claim_attempt", sa.Integer(), nullable=True),
        sa.Column("claim_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "operation", "key_hash"),
        sa.CheckConstraint(
            "operation IN ("
            "'registration.manual-metadata.apply-run.v1', "
            "'registration.bulk-preparation.execute-run.v1'"
            ")",
            name=op.f("ck_registration_worker_call_receipts_operation_allowlist"),
        ),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'COMPLETED')",
            name=op.f("ck_registration_worker_call_receipts_state_allowlist"),
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$' AND key_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_registration_worker_call_receipts_identity_hashes_valid"),
        ),
        sa.CheckConstraint(
            "claim_token_hash IS NULL OR claim_token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_registration_worker_call_receipts_claim_token_hash_valid"),
        ),
        sa.CheckConstraint(
            "(state = 'RUNNING' AND processed IS NULL AND result IS NULL "
            "AND work_kind IN ('MANUAL', 'BULK') AND work_id IS NOT NULL "
            "AND claim_attempt IS NOT NULL AND claim_attempt > 0 "
            "AND claim_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state = 'COMPLETED' AND processed IS NOT NULL AND result IS NOT NULL "
            "AND claim_token_hash IS NULL AND lease_expires_at IS NULL)",
            name=op.f("ck_registration_worker_call_receipts_state_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "worker_subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_registration_worker_call_receipts_subject",
            ondelete="RESTRICT",
        ),
        schema="integration",
    )
    op.create_index(
        "ix_registration_worker_call_receipts_running_lease",
        "registration_worker_call_receipts",
        ["lease_expires_at"],
        schema="integration",
        postgresql_where=sa.text("state = 'RUNNING'"),
    )
    _assert_existing_contract()
    _install_security_contract()
    _assert_runtime_contract()


def downgrade() -> None:
    # Worker execution receipts are compliance evidence and intentionally forward-only.
    pass
