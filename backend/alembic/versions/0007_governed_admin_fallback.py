# ruff: noqa: S608 -- fixed table names render compatibility DDL only.

"""Add typed, governed administrator password-fallback requests.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE iam.workspace_memberships "
        "ADD COLUMN IF NOT EXISTS version integer DEFAULT 1 NOT NULL"
    )
    op.execute("ALTER TABLE iam.workspace_memberships ALTER COLUMN version DROP DEFAULT")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS iam.admin_access_requests (
            id uuid CONSTRAINT pk_admin_access_requests PRIMARY KEY,
            workspace_id uuid NOT NULL,
            requester_id uuid NOT NULL,
            request_reason varchar(4000) NOT NULL,
            request_policy_decision_id uuid NOT NULL,
            target_subject_id uuid NOT NULL,
            command_type varchar(100) NOT NULL,
            command_document jsonb NOT NULL,
            payload_hash varchar(64) NOT NULL,
            state varchar(20) NOT NULL,
            expires_at timestamptz NOT NULL,
            checker_id uuid,
            consumed_by uuid,
            consumed_at timestamptz,
            consume_policy_decision_id uuid,
            version integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_admin_access_requests_workspace_id_id UNIQUE (workspace_id, id),
            CONSTRAINT fk_admin_access_requests_workspace_id_workspaces
                FOREIGN KEY (workspace_id)
                REFERENCES platform.workspaces(id) ON DELETE CASCADE,
            CONSTRAINT fk_admin_access_requests_target_membership
                FOREIGN KEY (workspace_id, target_subject_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_admin_access_requests_requester_membership
                FOREIGN KEY (workspace_id, requester_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_admin_access_requests_checker_membership
                FOREIGN KEY (workspace_id, checker_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT ck_admin_access_requests_typed_command
                CHECK (command_type = 'WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1'),
            CONSTRAINT ck_admin_access_requests_state
                CHECK (state IN ('PENDING', 'APPROVED', 'REJECTED', 'CONSUMED')),
            CONSTRAINT ck_admin_access_requests_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_admin_access_requests_version_positive CHECK (version > 0),
            CONSTRAINT ck_admin_access_requests_expiry_after_create
                CHECK (expires_at > created_at),
            CONSTRAINT ck_admin_access_requests_no_self_benefit
                CHECK (requester_id <> target_subject_id),
            CONSTRAINT ck_admin_access_requests_independent_checker
                CHECK (
                    checker_id IS NULL OR
                    (checker_id <> requester_id AND checker_id <> target_subject_id)
                ),
            CONSTRAINT ck_admin_access_requests_maker_consumes
                CHECK (consumed_by IS NULL OR consumed_by = requester_id),
            CONSTRAINT ck_admin_access_requests_state_shape CHECK (
                (state = 'PENDING' AND checker_id IS NULL AND consumed_by IS NULL
                    AND consumed_at IS NULL AND consume_policy_decision_id IS NULL) OR
                (state IN ('APPROVED', 'REJECTED') AND checker_id IS NOT NULL
                    AND consumed_by IS NULL AND consumed_at IS NULL
                    AND consume_policy_decision_id IS NULL) OR
                (state = 'CONSUMED' AND checker_id IS NOT NULL
                    AND consumed_by = requester_id AND consumed_at IS NOT NULL
                    AND consume_policy_decision_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_admin_access_requests_workspace_state
        ON iam.admin_access_requests (workspace_id, state, expires_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS iam.admin_access_approvals (
            id uuid CONSTRAINT pk_admin_access_approvals PRIMARY KEY,
            workspace_id uuid NOT NULL,
            access_request_id uuid NOT NULL,
            actor_id uuid NOT NULL,
            decision varchar(20) NOT NULL,
            reason varchar(4000) NOT NULL,
            policy_decision_id uuid NOT NULL,
            payload_hash varchar(64) NOT NULL,
            request_version integer NOT NULL,
            occurred_at timestamptz NOT NULL,
            CONSTRAINT fk_admin_access_approvals_workspace_id_workspaces
                FOREIGN KEY (workspace_id)
                REFERENCES platform.workspaces(id) ON DELETE CASCADE,
            CONSTRAINT fk_admin_access_approvals_request
                FOREIGN KEY (workspace_id, access_request_id)
                REFERENCES iam.admin_access_requests(workspace_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_admin_access_approvals_actor_membership
                FOREIGN KEY (workspace_id, actor_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT uq_admin_access_approvals_request_actor
                UNIQUE (workspace_id, access_request_id, actor_id),
            CONSTRAINT ck_admin_access_approvals_decision
                CHECK (decision IN ('APPROVED', 'REJECTED')),
            CONSTRAINT ck_admin_access_approvals_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_admin_access_approvals_version_positive
                CHECK (request_version > 0)
        )
        """
    )
    op.execute("ALTER TABLE iam.admin_access_requests ALTER COLUMN version DROP DEFAULT")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_admin_access_approvals_workspace_request
        ON iam.admin_access_approvals (workspace_id, access_request_id)
        """
    )
    for table in ("admin_access_requests", "admin_access_approvals"):
        op.execute(f"ALTER TABLE iam.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE iam.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            DO $datariver$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'iam'
                      AND tablename = '{table}'
                      AND policyname = 'workspace_isolation'
                ) THEN
                    CREATE POLICY workspace_isolation ON iam.{table}
                    USING (
                        workspace_id = NULLIF(
                            current_setting('app.workspace_id', true), ''
                        )::uuid
                    )
                    WITH CHECK (
                        workspace_id = NULLIF(
                            current_setting('app.workspace_id', true), ''
                        )::uuid
                    );
                END IF;
            END
            $datariver$
            """
        )
    _assert_admin_schema_contract()
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT ON iam.workspace_memberships TO datariver_app;
                GRANT UPDATE (active, clearance, attributes, version, updated_at)
                    ON iam.workspace_memberships TO datariver_app;
                GRANT SELECT, INSERT ON iam.admin_access_requests TO datariver_app;
                GRANT UPDATE (state, checker_id, consumed_by, consumed_at,
                    consume_policy_decision_id, version, updated_at)
                    ON iam.admin_access_requests TO datariver_app;
                GRANT SELECT, INSERT ON iam.admin_access_approvals TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Compatibility bridge: the regenerated 0001 owns this canonical security schema.
    pass


def _assert_admin_schema_contract() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            request_constraint_count integer;
            approval_constraint_count integer;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'iam' AND table_name = 'workspace_memberships'
                  AND column_name = 'version' AND udt_name = 'int4'
                  AND is_nullable = 'NO' AND column_default IS NULL
            ) THEN
                RAISE EXCEPTION 'workspace membership version contract is invalid';
            END IF;

            IF (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'iam' AND table_name = 'admin_access_requests'
            ) <> 18 OR EXISTS (
                SELECT 1
                FROM (VALUES
                    ('id', 'uuid', 'NO'), ('workspace_id', 'uuid', 'NO'),
                    ('requester_id', 'uuid', 'NO'), ('request_reason', 'varchar', 'NO'),
                    ('request_policy_decision_id', 'uuid', 'NO'),
                    ('target_subject_id', 'uuid', 'NO'), ('command_type', 'varchar', 'NO'),
                    ('command_document', 'jsonb', 'NO'), ('payload_hash', 'varchar', 'NO'),
                    ('state', 'varchar', 'NO'), ('expires_at', 'timestamptz', 'NO'),
                    ('checker_id', 'uuid', 'YES'), ('consumed_by', 'uuid', 'YES'),
                    ('consumed_at', 'timestamptz', 'YES'),
                    ('consume_policy_decision_id', 'uuid', 'YES'),
                    ('created_at', 'timestamptz', 'NO'),
                    ('updated_at', 'timestamptz', 'NO'), ('version', 'int4', 'NO')
                ) AS expected(column_name, udt_name, is_nullable)
                LEFT JOIN information_schema.columns actual
                  ON actual.table_schema = 'iam'
                 AND actual.table_name = 'admin_access_requests'
                 AND actual.column_name = expected.column_name
                 AND actual.udt_name = expected.udt_name
                 AND actual.is_nullable = expected.is_nullable
                WHERE actual.column_name IS NULL
            ) OR EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'iam' AND table_name = 'admin_access_requests'
                  AND column_name = 'version' AND column_default IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'administrator access request column contract is invalid';
            END IF;

            IF (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'iam' AND table_name = 'admin_access_approvals'
            ) <> 10 OR EXISTS (
                SELECT 1
                FROM (VALUES
                    ('id', 'uuid', 'NO'), ('workspace_id', 'uuid', 'NO'),
                    ('access_request_id', 'uuid', 'NO'), ('actor_id', 'uuid', 'NO'),
                    ('decision', 'varchar', 'NO'), ('reason', 'varchar', 'NO'),
                    ('policy_decision_id', 'uuid', 'NO'),
                    ('payload_hash', 'varchar', 'NO'), ('request_version', 'int4', 'NO'),
                    ('occurred_at', 'timestamptz', 'NO')
                ) AS expected(column_name, udt_name, is_nullable)
                LEFT JOIN information_schema.columns actual
                  ON actual.table_schema = 'iam'
                 AND actual.table_name = 'admin_access_approvals'
                 AND actual.column_name = expected.column_name
                 AND actual.udt_name = expected.udt_name
                 AND actual.is_nullable = expected.is_nullable
                WHERE actual.column_name IS NULL
            ) THEN
                RAISE EXCEPTION 'administrator access approval column contract is invalid';
            END IF;

            SELECT count(*) INTO request_constraint_count
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'iam'
              AND table_row.relname = 'admin_access_requests'
              AND constraint_row.convalidated
              AND constraint_row.conname = ANY (ARRAY[
                'pk_admin_access_requests',
                'uq_admin_access_requests_workspace_id_id',
                'fk_admin_access_requests_workspace_id_workspaces',
                'fk_admin_access_requests_target_membership',
                'fk_admin_access_requests_requester_membership',
                'fk_admin_access_requests_checker_membership',
                'ck_admin_access_requests_typed_command',
                'ck_admin_access_requests_state',
                'ck_admin_access_requests_payload_hash_sha256',
                'ck_admin_access_requests_version_positive',
                'ck_admin_access_requests_expiry_after_create',
                'ck_admin_access_requests_no_self_benefit',
                'ck_admin_access_requests_independent_checker',
                'ck_admin_access_requests_maker_consumes',
                'ck_admin_access_requests_state_shape'
              ]);
            IF request_constraint_count <> 15 THEN
                RAISE EXCEPTION 'administrator access request constraints are incomplete';
            END IF;

            SELECT count(*) INTO approval_constraint_count
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'iam'
              AND table_row.relname = 'admin_access_approvals'
              AND constraint_row.convalidated
              AND constraint_row.conname = ANY (ARRAY[
                'pk_admin_access_approvals',
                'uq_admin_access_approvals_request_actor',
                'fk_admin_access_approvals_workspace_id_workspaces',
                'fk_admin_access_approvals_request',
                'fk_admin_access_approvals_actor_membership',
                'ck_admin_access_approvals_decision',
                'ck_admin_access_approvals_payload_hash_sha256',
                'ck_admin_access_approvals_version_positive'
              ]);
            IF approval_constraint_count <> 8 THEN
                RAISE EXCEPTION 'administrator access approval constraints are incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_class table_row
                JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
                WHERE namespace_row.nspname = 'iam'
                  AND table_row.relname IN ('admin_access_requests', 'admin_access_approvals')
                  AND (NOT table_row.relrowsecurity OR NOT table_row.relforcerowsecurity)
            ) OR (
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'iam'
                  AND tablename IN ('admin_access_requests', 'admin_access_approvals')
                  AND policyname = 'workspace_isolation'
                  AND permissive = 'PERMISSIVE' AND cmd = 'ALL'
                  AND roles = ARRAY['public']::name[]
                  AND qual LIKE '%app.workspace_id%'
                  AND with_check LIKE '%app.workspace_id%'
            ) <> 2 THEN
                RAISE EXCEPTION 'administrator access RLS contract is invalid';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'iam'
                  AND indexname = 'ix_admin_access_requests_workspace_state'
                  AND indexdef LIKE '%(workspace_id, state, expires_at)'
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'iam'
                  AND indexname = 'ix_admin_access_approvals_workspace_request'
                  AND indexdef LIKE '%(workspace_id, access_request_id)'
            ) THEN
                RAISE EXCEPTION 'administrator access index contract is invalid';
            END IF;
        END
        $datariver$
        """
    )
