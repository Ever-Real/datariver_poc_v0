# ruff: noqa: S608 -- fixed table names render compatibility DDL only.

"""Persist governed erasure requests without an execution path.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_retention_policy_versions_workspace_id_hash'
                  AND conrelid = 'retention.policy_versions'::regclass
            ) THEN
                ALTER TABLE retention.policy_versions
                ADD CONSTRAINT uq_retention_policy_versions_workspace_id_hash
                UNIQUE (workspace_id, id, payload_hash);
            END IF;
        END
        $datariver$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention.erasure_requests (
            workspace_id uuid NOT NULL,
            target_type varchar(32) NOT NULL,
            target_id uuid NOT NULL,
            target_version integer NOT NULL,
            target_owner_id uuid,
            classification integer NOT NULL,
            retention_policy_id uuid NOT NULL,
            retention_policy_hash varchar(64) NOT NULL,
            requester_id uuid NOT NULL,
            request_reason varchar(4000) NOT NULL,
            request_policy_decision_id uuid NOT NULL,
            payload_hash varchar(64) NOT NULL,
            expires_at timestamptz NOT NULL,
            state varchar(20) NOT NULL,
            checker_id uuid,
            decision_reason varchar(4000),
            decision_policy_decision_id uuid,
            decided_at timestamptz,
            id uuid CONSTRAINT pk_erasure_requests PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version integer NOT NULL,
            CONSTRAINT uq_erasure_requests_workspace_id_id
                UNIQUE (workspace_id, id),
            CONSTRAINT uq_erasure_requests_idempotent_payload
                UNIQUE (workspace_id, requester_id, payload_hash),
            CONSTRAINT fk_erasure_requests_workspace_id_workspaces
                FOREIGN KEY (workspace_id) REFERENCES platform.workspaces(id),
            CONSTRAINT fk_erasure_requests_retention_policy
                FOREIGN KEY (
                    workspace_id, retention_policy_id, retention_policy_hash
                ) REFERENCES retention.policy_versions(workspace_id, id, payload_hash),
            CONSTRAINT fk_erasure_requests_requester_membership
                FOREIGN KEY (workspace_id, requester_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_erasure_requests_checker_membership
                FOREIGN KEY (workspace_id, checker_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_erasure_requests_target_owner_membership
                FOREIGN KEY (workspace_id, target_owner_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT ck_erasure_requests_target_type CHECK (
                target_type IN ('SUBJECT_DATA', 'CHAT_SESSION', 'UPLOAD_OBJECT')
            ),
            CONSTRAINT ck_erasure_requests_target_version_positive
                CHECK (target_version > 0),
            CONSTRAINT ck_erasure_requests_classification_range
                CHECK (classification BETWEEN 0 AND 3),
            CONSTRAINT ck_erasure_requests_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_erasure_requests_retention_policy_hash_sha256
                CHECK (retention_policy_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_erasure_requests_state
                CHECK (state IN ('PENDING', 'APPROVED', 'REJECTED')),
            CONSTRAINT ck_erasure_requests_version_positive CHECK (version > 0),
            CONSTRAINT ck_erasure_requests_reasons_nonempty CHECK (
                length(btrim(request_reason)) > 0
                AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0)
            ),
            CONSTRAINT ck_erasure_requests_review_window CHECK (
                expires_at > created_at
                AND expires_at <= created_at + INTERVAL '7 days'
                AND (decided_at IS NULL OR decided_at >= created_at)
                AND (state <> 'APPROVED' OR decided_at < expires_at)
            ),
            CONSTRAINT ck_erasure_requests_independent_checker
                CHECK (checker_id IS NULL OR checker_id <> requester_id),
            CONSTRAINT ck_erasure_requests_target_owner_cannot_check CHECK (
                checker_id IS NULL OR target_owner_id IS NULL
                OR checker_id <> target_owner_id
            ),
            CONSTRAINT ck_erasure_requests_subject_cannot_check_own_erasure CHECK (
                target_type <> 'SUBJECT_DATA' OR checker_id IS NULL
                OR checker_id <> target_id
            ),
            CONSTRAINT ck_erasure_requests_state_shape CHECK (
                (state = 'PENDING' AND version = 1 AND checker_id IS NULL
                    AND decision_reason IS NULL
                    AND decision_policy_decision_id IS NULL
                    AND decided_at IS NULL) OR
                (state IN ('APPROVED', 'REJECTED') AND version = 2
                    AND checker_id IS NOT NULL AND decision_reason IS NOT NULL
                    AND decision_policy_decision_id IS NOT NULL
                    AND decided_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_erasure_requests_workspace_state_expiry
        ON retention.erasure_requests (workspace_id, state, expires_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_erasure_requests_workspace_target
        ON retention.erasure_requests (workspace_id, target_type, target_id, created_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention.erasure_request_events (
            workspace_id uuid NOT NULL,
            erasure_request_id uuid NOT NULL,
            action varchar(20) NOT NULL,
            actor_id uuid NOT NULL,
            reason varchar(4000) NOT NULL,
            policy_decision_id uuid NOT NULL,
            occurred_at timestamptz NOT NULL,
            request_version integer NOT NULL,
            payload_hash varchar(64) NOT NULL,
            id uuid CONSTRAINT pk_erasure_request_events PRIMARY KEY,
            CONSTRAINT fk_erasure_request_events_workspace_id_workspaces
                FOREIGN KEY (workspace_id) REFERENCES platform.workspaces(id),
            CONSTRAINT fk_erasure_request_events_request
                FOREIGN KEY (workspace_id, erasure_request_id)
                REFERENCES retention.erasure_requests(workspace_id, id),
            CONSTRAINT fk_erasure_request_events_actor_membership
                FOREIGN KEY (workspace_id, actor_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT uq_erasure_request_events_request_version
                UNIQUE (workspace_id, erasure_request_id, request_version),
            CONSTRAINT ck_erasure_request_events_action
                CHECK (action IN ('CREATED', 'APPROVED', 'REJECTED')),
            CONSTRAINT ck_erasure_request_events_action_version_shape CHECK (
                (action = 'CREATED' AND request_version = 1) OR
                (action IN ('APPROVED', 'REJECTED') AND request_version = 2)
            ),
            CONSTRAINT ck_erasure_request_events_reason_nonempty
                CHECK (length(btrim(reason)) > 0),
            CONSTRAINT ck_erasure_request_events_request_version_positive
                CHECK (request_version > 0),
            CONSTRAINT ck_erasure_request_events_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_erasure_request_events_workspace_request_time
        ON retention.erasure_request_events (
            workspace_id, erasure_request_id, occurred_at
        )
        """
    )
    for table in ("erasure_requests", "erasure_request_events"):
        op.execute(f"ALTER TABLE retention.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE retention.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            DO $datariver$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'retention'
                      AND tablename = '{table}'
                      AND policyname = 'workspace_isolation'
                ) THEN
                    CREATE POLICY workspace_isolation ON retention.{table}
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
    _assert_erasure_schema_contract()
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT ON retention.erasure_requests TO datariver_app;
                GRANT UPDATE (state, checker_id, decision_reason,
                    decision_policy_decision_id, decided_at, version, updated_at)
                    ON retention.erasure_requests TO datariver_app;
                GRANT SELECT, INSERT ON retention.erasure_request_events TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Compatibility bridge: the regenerated 0001 owns this canonical governance schema.
    pass


def _assert_erasure_schema_contract() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            request_constraint_count integer;
            event_constraint_count integer;
        BEGIN
            IF (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'retention' AND table_name = 'erasure_requests'
            ) <> 22 OR (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'retention'
                  AND table_name = 'erasure_request_events'
            ) <> 10 THEN
                RAISE EXCEPTION 'erasure table column count contract is invalid';
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'retention'
                  AND table_name = 'erasure_requests'
                  AND column_name = 'version' AND column_default IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'erasure request version cannot have a server default';
            END IF;

            SELECT count(*) INTO request_constraint_count
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'retention'
              AND table_row.relname = 'erasure_requests'
              AND constraint_row.convalidated
              AND constraint_row.conname = ANY (ARRAY[
                'pk_erasure_requests', 'uq_erasure_requests_workspace_id_id',
                'uq_erasure_requests_idempotent_payload',
                'fk_erasure_requests_workspace_id_workspaces',
                'fk_erasure_requests_retention_policy',
                'fk_erasure_requests_requester_membership',
                'fk_erasure_requests_checker_membership',
                'fk_erasure_requests_target_owner_membership',
                'ck_erasure_requests_target_type',
                'ck_erasure_requests_target_version_positive',
                'ck_erasure_requests_classification_range',
                'ck_erasure_requests_payload_hash_sha256',
                'ck_erasure_requests_retention_policy_hash_sha256',
                'ck_erasure_requests_state', 'ck_erasure_requests_version_positive',
                'ck_erasure_requests_reasons_nonempty',
                'ck_erasure_requests_review_window',
                'ck_erasure_requests_independent_checker',
                'ck_erasure_requests_target_owner_cannot_check',
                'ck_erasure_requests_subject_cannot_check_own_erasure',
                'ck_erasure_requests_state_shape'
              ]);
            IF request_constraint_count <> 21 THEN
                RAISE EXCEPTION 'erasure request constraints are incomplete';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_retention_policy_versions_workspace_id_hash'
                  AND conrelid = 'retention.policy_versions'::regclass
                  AND convalidated
            ) THEN
                RAISE EXCEPTION 'retention policy hash binding is unavailable';
            END IF;

            SELECT count(*) INTO event_constraint_count
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'retention'
              AND table_row.relname = 'erasure_request_events'
              AND constraint_row.convalidated
              AND constraint_row.conname = ANY (ARRAY[
                'pk_erasure_request_events',
                'uq_erasure_request_events_request_version',
                'fk_erasure_request_events_workspace_id_workspaces',
                'fk_erasure_request_events_request',
                'fk_erasure_request_events_actor_membership',
                'ck_erasure_request_events_action',
                'ck_erasure_request_events_action_version_shape',
                'ck_erasure_request_events_reason_nonempty',
                'ck_erasure_request_events_request_version_positive',
                'ck_erasure_request_events_payload_hash_sha256'
              ]);
            IF event_constraint_count <> 10 THEN
                RAISE EXCEPTION 'erasure request event constraints are incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_class table_row
                JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
                WHERE namespace_row.nspname = 'retention'
                  AND table_row.relname IN (
                      'erasure_requests', 'erasure_request_events'
                  )
                  AND (NOT table_row.relrowsecurity OR NOT table_row.relforcerowsecurity)
            ) OR (
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'retention'
                  AND tablename IN ('erasure_requests', 'erasure_request_events')
                  AND policyname = 'workspace_isolation'
                  AND permissive = 'PERMISSIVE' AND cmd = 'ALL'
                  AND roles = ARRAY['public']::name[]
                  AND qual LIKE '%app.workspace_id%'
                  AND with_check LIKE '%app.workspace_id%'
            ) <> 2 THEN
                RAISE EXCEPTION 'erasure RLS contract is invalid';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'retention'
                  AND indexname = 'ix_erasure_requests_workspace_state_expiry'
                  AND indexdef LIKE '%(workspace_id, state, expires_at)%'
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'retention'
                  AND indexname = 'ix_erasure_requests_workspace_target'
                  AND indexdef LIKE '%(workspace_id, target_type, target_id, created_at)%'
            ) THEN
                RAISE EXCEPTION 'erasure request index contract is invalid';
            END IF;
        END
        $datariver$
        """
    )
