# ruff: noqa: S608 -- fixed table names render compatibility DDL only.

"""Add governed retention policy versions and Legal Hold evidence.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS retention")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention.policy_versions (
            workspace_id uuid NOT NULL,
            policy_number integer NOT NULL,
            completed_operation_days integer NOT NULL,
            chat_content_days integer NOT NULL,
            audit_online_months integer NOT NULL,
            immutable_archive_years integer NOT NULL,
            payload_hash varchar(64) NOT NULL,
            requester_id uuid NOT NULL,
            request_reason varchar(4000) NOT NULL,
            request_policy_decision_id uuid NOT NULL,
            state varchar(20) NOT NULL,
            checker_id uuid,
            decision_reason varchar(4000),
            decision_policy_decision_id uuid,
            decided_at timestamptz,
            superseded_by uuid,
            supersede_reason varchar(4000),
            supersede_policy_decision_id uuid,
            superseded_at timestamptz,
            id uuid CONSTRAINT pk_policy_versions PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version integer NOT NULL,
            CONSTRAINT uq_retention_policy_versions_workspace_id_id
                UNIQUE (workspace_id, id),
            CONSTRAINT uq_retention_policy_versions_workspace_number
                UNIQUE (workspace_id, policy_number),
            CONSTRAINT fk_policy_versions_workspace_id_workspaces
                FOREIGN KEY (workspace_id)
                REFERENCES platform.workspaces(id),
            CONSTRAINT fk_retention_policy_versions_requester_membership
                FOREIGN KEY (workspace_id, requester_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_retention_policy_versions_checker_membership
                FOREIGN KEY (workspace_id, checker_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_retention_policy_versions_superseder_membership
                FOREIGN KEY (workspace_id, superseded_by)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT ck_policy_versions_policy_number_positive
                CHECK (policy_number > 0),
            CONSTRAINT ck_policy_versions_rules_supported_bounds CHECK (
                completed_operation_days BETWEEN 1 AND 3650
                AND chat_content_days BETWEEN 1 AND 3650
                AND audit_online_months BETWEEN 1 AND 120
                AND immutable_archive_years BETWEEN 1 AND 100
            ),
            CONSTRAINT ck_policy_versions_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_policy_versions_state
                CHECK (state IN ('DRAFT', 'ACTIVE', 'REJECTED', 'SUPERSEDED')),
            CONSTRAINT ck_policy_versions_version_positive CHECK (version > 0),
            CONSTRAINT ck_policy_versions_independent_checker
                CHECK (checker_id IS NULL OR checker_id <> requester_id),
            CONSTRAINT ck_policy_versions_reasons_nonempty CHECK (
                length(btrim(request_reason)) > 0
                AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0)
                AND (supersede_reason IS NULL OR length(btrim(supersede_reason)) > 0)
            ),
            CONSTRAINT ck_policy_versions_state_shape CHECK (
                (state = 'DRAFT' AND checker_id IS NULL AND decision_reason IS NULL
                    AND decision_policy_decision_id IS NULL AND decided_at IS NULL
                    AND superseded_by IS NULL AND supersede_reason IS NULL
                    AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR
                (state IN ('ACTIVE', 'REJECTED') AND checker_id IS NOT NULL
                    AND decision_reason IS NOT NULL
                    AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL
                    AND superseded_by IS NULL AND supersede_reason IS NULL
                    AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR
                (state = 'SUPERSEDED' AND checker_id IS NOT NULL
                    AND decision_reason IS NOT NULL
                    AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL
                    AND superseded_by IS NOT NULL AND supersede_reason IS NOT NULL
                    AND supersede_policy_decision_id IS NOT NULL
                    AND superseded_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_retention_policy_versions_workspace_active
        ON retention.policy_versions (workspace_id) WHERE state = 'ACTIVE'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_retention_policy_versions_workspace_number
        ON retention.policy_versions (workspace_id, policy_number)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention.legal_holds (
            workspace_id uuid NOT NULL,
            data_class varchar(32) NOT NULL,
            scope varchar(20) NOT NULL,
            scope_id uuid,
            reason varchar(4000) NOT NULL,
            payload_hash varchar(64) NOT NULL,
            created_by uuid NOT NULL,
            create_policy_decision_id uuid NOT NULL,
            state varchar(24) NOT NULL,
            release_requested_by uuid,
            release_request_reason varchar(4000),
            release_request_policy_decision_id uuid,
            release_checker_id uuid,
            release_decision_reason varchar(4000),
            release_decision_policy_decision_id uuid,
            released_at timestamptz,
            id uuid CONSTRAINT pk_legal_holds PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version integer NOT NULL,
            CONSTRAINT uq_legal_holds_workspace_id_id UNIQUE (workspace_id, id),
            CONSTRAINT fk_legal_holds_workspace_id_workspaces
                FOREIGN KEY (workspace_id)
                REFERENCES platform.workspaces(id),
            CONSTRAINT fk_legal_holds_creator_membership
                FOREIGN KEY (workspace_id, created_by)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_legal_holds_release_requester_membership
                FOREIGN KEY (workspace_id, release_requested_by)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT fk_legal_holds_release_checker_membership
                FOREIGN KEY (workspace_id, release_checker_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT ck_legal_holds_data_class CHECK (
                data_class IN (
                    'COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA'
                )
            ),
            CONSTRAINT ck_legal_holds_scope
                CHECK (scope IN ('WORKSPACE', 'SUBJECT', 'RESOURCE')),
            CONSTRAINT ck_legal_holds_scope_shape CHECK (
                (scope = 'WORKSPACE' AND scope_id IS NULL) OR
                (scope IN ('SUBJECT', 'RESOURCE') AND scope_id IS NOT NULL)
            ),
            CONSTRAINT ck_legal_holds_state CHECK (
                state IN ('ACTIVE', 'RELEASE_REQUESTED', 'RELEASE_REJECTED', 'RELEASED')
            ),
            CONSTRAINT ck_legal_holds_version_positive CHECK (version > 0),
            CONSTRAINT ck_legal_holds_reason_nonempty CHECK (length(btrim(reason)) > 0),
            CONSTRAINT ck_legal_holds_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_legal_holds_independent_release_checker CHECK (
                release_checker_id IS NULL OR release_checker_id <> release_requested_by
            ),
            CONSTRAINT ck_legal_holds_subject_cannot_release_own_hold CHECK (
                scope <> 'SUBJECT' OR release_checker_id IS NULL OR release_checker_id <> scope_id
            ),
            CONSTRAINT ck_legal_holds_state_shape CHECK (
                (state = 'ACTIVE' AND release_requested_by IS NULL
                    AND release_request_reason IS NULL
                    AND release_request_policy_decision_id IS NULL
                    AND release_checker_id IS NULL AND release_decision_reason IS NULL
                    AND release_decision_policy_decision_id IS NULL
                    AND released_at IS NULL) OR
                (state = 'RELEASE_REQUESTED' AND release_requested_by IS NOT NULL
                    AND release_request_reason IS NOT NULL
                    AND release_request_policy_decision_id IS NOT NULL
                    AND release_checker_id IS NULL AND release_decision_reason IS NULL
                    AND release_decision_policy_decision_id IS NULL
                    AND released_at IS NULL) OR
                (state = 'RELEASE_REJECTED' AND release_requested_by IS NOT NULL
                    AND release_request_reason IS NOT NULL
                    AND release_request_policy_decision_id IS NOT NULL
                    AND release_checker_id IS NOT NULL
                    AND release_decision_reason IS NOT NULL
                    AND release_decision_policy_decision_id IS NOT NULL
                    AND released_at IS NULL) OR
                (state = 'RELEASED' AND release_requested_by IS NOT NULL
                    AND release_request_reason IS NOT NULL
                    AND release_request_policy_decision_id IS NOT NULL
                    AND release_checker_id IS NOT NULL
                    AND release_decision_reason IS NOT NULL
                    AND release_decision_policy_decision_id IS NOT NULL
                    AND released_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_legal_holds_workspace_blocking_scope
        ON retention.legal_holds (workspace_id, data_class, scope, scope_id)
        WHERE state <> 'RELEASED'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_legal_holds_workspace_state
        ON retention.legal_holds (workspace_id, state, updated_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention.legal_hold_events (
            workspace_id uuid NOT NULL,
            hold_id uuid NOT NULL,
            action varchar(32) NOT NULL,
            actor_id uuid NOT NULL,
            reason varchar(4000) NOT NULL,
            policy_decision_id uuid NOT NULL,
            occurred_at timestamptz NOT NULL,
            hold_version integer NOT NULL,
            payload_hash varchar(64) NOT NULL,
            id uuid CONSTRAINT pk_legal_hold_events PRIMARY KEY,
            CONSTRAINT fk_legal_hold_events_workspace_id_workspaces
                FOREIGN KEY (workspace_id)
                REFERENCES platform.workspaces(id),
            CONSTRAINT fk_legal_hold_events_hold
                FOREIGN KEY (workspace_id, hold_id)
                REFERENCES retention.legal_holds(workspace_id, id),
            CONSTRAINT fk_legal_hold_events_actor_membership
                FOREIGN KEY (workspace_id, actor_id)
                REFERENCES iam.workspace_memberships(workspace_id, subject_id),
            CONSTRAINT uq_legal_hold_events_hold_version
                UNIQUE (workspace_id, hold_id, hold_version),
            CONSTRAINT ck_legal_hold_events_action CHECK (
                action IN ('PLACED', 'RELEASE_REQUESTED',
                    'RELEASE_APPROVED', 'RELEASE_REJECTED')
            ),
            CONSTRAINT ck_legal_hold_events_action_version_shape CHECK (
                (action = 'PLACED' AND hold_version = 1) OR
                (action <> 'PLACED' AND hold_version > 1)
            ),
            CONSTRAINT ck_legal_hold_events_reason_nonempty
                CHECK (length(btrim(reason)) > 0),
            CONSTRAINT ck_legal_hold_events_hold_version_positive CHECK (hold_version > 0),
            CONSTRAINT ck_legal_hold_events_payload_hash_sha256
                CHECK (payload_hash ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_legal_hold_events_workspace_hold_time
        ON retention.legal_hold_events (workspace_id, hold_id, occurred_at)
        """
    )
    for table in ("policy_versions", "legal_holds", "legal_hold_events"):
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
    _assert_retention_schema_contract()
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT USAGE ON SCHEMA retention TO datariver_app;
                GRANT SELECT, INSERT ON retention.policy_versions TO datariver_app;
                GRANT UPDATE (state, checker_id, decision_reason,
                    decision_policy_decision_id, decided_at, superseded_by, supersede_reason,
                    supersede_policy_decision_id, superseded_at, version, updated_at)
                    ON retention.policy_versions TO datariver_app;
                GRANT SELECT, INSERT ON retention.legal_holds TO datariver_app;
                GRANT UPDATE (state, release_requested_by, release_request_reason,
                    release_request_policy_decision_id, release_checker_id,
                    release_decision_reason, release_decision_policy_decision_id,
                    released_at, version, updated_at)
                    ON retention.legal_holds TO datariver_app;
                GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Compatibility bridge: the regenerated 0001 owns this canonical governance schema.
    pass


def _assert_retention_schema_contract() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            policy_constraint_count integer;
            hold_constraint_count integer;
            event_constraint_count integer;
        BEGIN
            IF (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'retention' AND table_name = 'policy_versions'
            ) <> 23 OR (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'retention' AND table_name = 'legal_holds'
            ) <> 20 OR (
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'retention' AND table_name = 'legal_hold_events'
            ) <> 10 THEN
                RAISE EXCEPTION 'retention table column count contract is invalid';
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'retention'
                  AND table_name IN ('policy_versions', 'legal_holds')
                  AND column_name = 'version' AND column_default IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'retention aggregate versions cannot have a server default';
            END IF;

            SELECT count(*) INTO policy_constraint_count
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'retention'
              AND table_row.relname = 'policy_versions'
              AND constraint_row.convalidated
              AND constraint_row.conname = ANY (ARRAY[
                'pk_policy_versions',
                'uq_retention_policy_versions_workspace_id_id',
                'uq_retention_policy_versions_workspace_number',
                'fk_policy_versions_workspace_id_workspaces',
                'fk_retention_policy_versions_requester_membership',
                'fk_retention_policy_versions_checker_membership',
                'fk_retention_policy_versions_superseder_membership',
                'ck_policy_versions_policy_number_positive',
                'ck_policy_versions_rules_supported_bounds',
                'ck_policy_versions_payload_hash_sha256',
                'ck_policy_versions_state',
                'ck_policy_versions_version_positive',
                'ck_policy_versions_independent_checker',
                'ck_policy_versions_reasons_nonempty',
                'ck_policy_versions_state_shape'
              ]);
            IF policy_constraint_count <> 15 THEN
                RAISE EXCEPTION 'retention policy constraints are incomplete';
            END IF;

            SELECT count(*) INTO hold_constraint_count
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'retention'
              AND table_row.relname = 'legal_holds'
              AND constraint_row.convalidated
              AND constraint_row.conname = ANY (ARRAY[
                'pk_legal_holds', 'uq_legal_holds_workspace_id_id',
                'fk_legal_holds_workspace_id_workspaces',
                'fk_legal_holds_creator_membership',
                'fk_legal_holds_release_requester_membership',
                'fk_legal_holds_release_checker_membership',
                'ck_legal_holds_data_class', 'ck_legal_holds_scope',
                'ck_legal_holds_scope_shape', 'ck_legal_holds_state',
                'ck_legal_holds_version_positive', 'ck_legal_holds_reason_nonempty',
                'ck_legal_holds_payload_hash_sha256',
                'ck_legal_holds_independent_release_checker',
                'ck_legal_holds_subject_cannot_release_own_hold',
                'ck_legal_holds_state_shape'
              ]);
            IF hold_constraint_count <> 16 THEN
                RAISE EXCEPTION 'Legal Hold constraints are incomplete';
            END IF;

            SELECT count(*) INTO event_constraint_count
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'retention'
              AND table_row.relname = 'legal_hold_events'
              AND constraint_row.convalidated
              AND constraint_row.conname = ANY (ARRAY[
                'pk_legal_hold_events', 'uq_legal_hold_events_hold_version',
                'fk_legal_hold_events_workspace_id_workspaces',
                'fk_legal_hold_events_hold', 'fk_legal_hold_events_actor_membership',
                'ck_legal_hold_events_action',
                'ck_legal_hold_events_action_version_shape',
                'ck_legal_hold_events_reason_nonempty',
                'ck_legal_hold_events_hold_version_positive',
                'ck_legal_hold_events_payload_hash_sha256'
              ]);
            IF event_constraint_count <> 10 THEN
                RAISE EXCEPTION 'Legal Hold event constraints are incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_class table_row
                JOIN pg_namespace namespace_row ON namespace_row.oid = table_row.relnamespace
                WHERE namespace_row.nspname = 'retention'
                  AND table_row.relname IN (
                      'policy_versions', 'legal_holds', 'legal_hold_events'
                  )
                  AND (NOT table_row.relrowsecurity OR NOT table_row.relforcerowsecurity)
            ) OR (
                SELECT count(*) FROM pg_policies
                WHERE schemaname = 'retention'
                  AND tablename IN ('policy_versions', 'legal_holds', 'legal_hold_events')
                  AND policyname = 'workspace_isolation'
                  AND permissive = 'PERMISSIVE' AND cmd = 'ALL'
                  AND roles = ARRAY['public']::name[]
                  AND qual LIKE '%app.workspace_id%'
                  AND with_check LIKE '%app.workspace_id%'
            ) <> 3 THEN
                RAISE EXCEPTION 'retention RLS contract is invalid';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'retention'
                  AND indexname = 'uq_retention_policy_versions_workspace_active'
                  AND indexdef LIKE 'CREATE UNIQUE INDEX%'
                  AND indexdef LIKE '%(workspace_id)%'
                  AND indexdef LIKE '%ACTIVE%'
            ) OR NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'retention'
                  AND indexname = 'ix_legal_holds_workspace_blocking_scope'
                  AND indexdef LIKE '%(workspace_id, data_class, scope, scope_id)%'
                  AND indexdef LIKE '%RELEASED%'
            ) THEN
                RAISE EXCEPTION 'retention partial index contract is invalid';
            END IF;
        END
        $datariver$
        """
    )
