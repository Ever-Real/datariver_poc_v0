"""Add expiring human memberships and governed six-month renewal requests.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from datariver.infrastructure.db.migration_definition_fingerprint import (
    RelationDefinitionFingerprintV1,
    read_relation_definition_fingerprint_v1,
)

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
EXPECTED_OBJECT_COUNT = 5

_CANONICAL_COLUMNS = (
    "workspace_id|uuid|uuid||NO",
    "target_subject_id|uuid|uuid||NO",
    "requester_id|uuid|uuid||NO",
    "reason|character varying|varchar|4000|NO",
    "current_expires_at|timestamp with time zone|timestamptz||NO",
    "requested_expires_at|timestamp with time zone|timestamptz||NO",
    "state|character varying|varchar|20|NO",
    "checker_id|uuid|uuid||YES",
    "decision_reason|character varying|varchar|4000|YES",
    "decision_policy_decision_id|uuid|uuid||YES",
    "decided_at|timestamp with time zone|timestamptz||YES",
    "id|uuid|uuid||NO",
    "created_at|timestamp with time zone|timestamptz||NO",
    "updated_at|timestamp with time zone|timestamptz||NO",
    "version|integer|int4||NO",
)
_CANONICAL_CONSTRAINTS = (
    "ck_membership_renewal_requests_extension_positive",
    "ck_membership_renewal_requests_independent_checker",
    "ck_membership_renewal_requests_self_request",
    "ck_membership_renewal_requests_state",
    "ck_membership_renewal_requests_state_shape",
    "fk_membership_renewal_requests_workspace_id_workspaces",
    "fk_membership_renewals_checker_membership",
    "fk_membership_renewals_requester_membership",
    "fk_membership_renewals_target_membership",
    "pk_membership_renewal_requests",
    "uq_membership_renewal_requests_workspace_id_id",
)
_CANONICAL_INDEXES = (
    "ix_membership_renewals_workspace_state_created",
    "uq_membership_renewals_pending_subject",
)
_CANONICAL_DEFINITION_FINGERPRINT = RelationDefinitionFingerprintV1(
    "d07b78ea13dd261a98b24e7fedb9d7242abf775d8b31e44654ed5b341ec2a603",
    "6a745700c8eec3c71e97782e4a7e0d88bd3a3e76e0799c7dd5df8f26fd7d712d",
    "9b5ca7ec5c37c60f1f4bbebc96a32edc1a47b8ee5f15c5cadceb73f291aedb86",
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "true|true",
)
_CANONICAL_MEMBERSHIP_FINGERPRINT = RelationDefinitionFingerprintV1(
    "9c3d0b8dad566bedb30d78e6d0e7f0a9e4b1d516f0bd9e911bf40e27710e2354",
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "c0854f58f2fd197a0297390551c355ad5a78ef5e8c32d1f7886697e90767dd47",
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "true|true",
)


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'iam' AND table_name = 'workspace_memberships'
                       AND column_name = 'access_expires_at')
                    + (to_regclass('iam.membership_renewal_requests') IS NOT NULL)::int
                    + (to_regclass('iam.ix_membership_renewals_workspace_state_created')
                       IS NOT NULL)::int
                    + (to_regclass('iam.uq_membership_renewals_pending_subject')
                       IS NOT NULL)::int
                    + (SELECT count(*) FROM pg_policies
                       WHERE schemaname = 'iam' AND tablename = 'membership_renewal_requests'
                         AND policyname = 'workspace_isolation')
                """
            )
        )
        .scalar_one()
    )


def _is_canonical_schema() -> bool:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    ARRAY(
                        SELECT column_name || '|' || data_type || '|' || udt_name
                            || '|' || COALESCE(character_maximum_length::text, '')
                            || '|' || is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'iam'
                          AND table_name = 'membership_renewal_requests'
                        ORDER BY ordinal_position
                    ) AS columns,
                    ARRAY(
                        SELECT conname FROM pg_constraint
                        WHERE conrelid = to_regclass('iam.membership_renewal_requests')
                        ORDER BY conname
                    ) AS constraints,
                    ARRAY(
                        SELECT index_class.relname
                        FROM pg_index AS index_state
                        JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
                        WHERE index_state.indrelid =
                            to_regclass('iam.membership_renewal_requests')
                          AND NOT EXISTS (
                              SELECT 1 FROM pg_constraint
                              WHERE conindid = index_state.indexrelid
                          )
                        ORDER BY index_class.relname
                    ) AS indexes,
                    ARRAY(
                        SELECT polname FROM pg_policy
                        WHERE polrelid = to_regclass('iam.membership_renewal_requests')
                        ORDER BY polname
                    ) AS policies,
                    ARRAY(
                        SELECT column_name || '|' || data_type || '|' || udt_name
                            || '|' || COALESCE(character_maximum_length::text, '')
                            || '|' || is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'iam'
                          AND table_name = 'workspace_memberships'
                          AND column_name = 'access_expires_at'
                    ) AS membership_column,
                    COALESCE((
                        SELECT relrowsecurity AND relforcerowsecurity
                        FROM pg_class
                        WHERE oid = to_regclass('iam.membership_renewal_requests')
                    ), FALSE) AS force_rls
                """
            )
        )
        .mappings()
        .one()
    )
    return (
        tuple(sorted(row["columns"])) == tuple(sorted(_CANONICAL_COLUMNS))
        and tuple(row["constraints"]) == _CANONICAL_CONSTRAINTS
        and tuple(row["indexes"]) == _CANONICAL_INDEXES
        and tuple(row["policies"]) == ("workspace_isolation",)
        and tuple(row["membership_column"])
        == ("access_expires_at|timestamp with time zone|timestamptz||YES",)
        and bool(row["force_rls"])
        and read_relation_definition_fingerprint_v1(
            op.get_bind(), "iam.membership_renewal_requests"
        )
        == _CANONICAL_DEFINITION_FINGERPRINT
        and read_relation_definition_fingerprint_v1(op.get_bind(), "iam.workspace_memberships")
        == _CANONICAL_MEMBERSHIP_FINGERPRINT
    )


def _install_security_contract() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT, UPDATE ON iam.membership_renewal_requests
                    TO datariver_app;
                GRANT UPDATE (access_expires_at, version, updated_at)
                    ON iam.workspace_memberships TO datariver_app;
            END IF;
        END
        $datariver$;
        """
    )
    _install_default_workspace_resolver()


def _install_default_workspace_resolver() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION iam.resolve_default_workspace(
            p_issuer text,
            p_external_subject text
        )
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, iam, platform
        AS $datariver$
            SELECT membership.workspace_id
            FROM iam.subjects AS subject
            JOIN iam.workspace_memberships AS membership
              ON membership.subject_id = subject.id
            JOIN platform.workspaces AS workspace
              ON workspace.id = membership.workspace_id
            WHERE subject.issuer = p_issuer
              AND subject.external_subject = p_external_subject
              AND subject.active IS TRUE
              AND membership.active IS TRUE
              AND (
                  membership.access_expires_at IS NULL
                  OR membership.access_expires_at > CURRENT_TIMESTAMP
              )
              AND workspace.status = 'ACTIVE'
            ORDER BY
              CASE WHEN membership.attributes ->> 'default_workspace' = 'true'
                THEN 0 ELSE 1 END,
              workspace.slug ASC,
              membership.workspace_id ASC
            LIMIT 1
        $datariver$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION iam.resolve_default_workspace(text, text) FROM PUBLIC")
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT EXECUTE ON FUNCTION iam.resolve_default_workspace(text, text)
                    TO datariver_app;
            END IF;
        END
        $datariver$;
        """
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT or not _is_canonical_schema():
            raise RuntimeError("The membership renewal schema is only partially present.")
        _install_security_contract()
        return
    op.add_column(
        "workspace_memberships",
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="iam",
    )
    op.execute(
        """
        UPDATE iam.workspace_memberships
        SET access_expires_at = GREATEST(
            created_at + INTERVAL '6 months',
            CURRENT_TIMESTAMP + INTERVAL '30 days'
        )
        WHERE COALESCE(job_function, '') <> 'SERVICE_ACCOUNT'
          AND NOT (COALESCE(attributes -> 'groups', '[]'::jsonb) ? 'service-accounts')
        """
    )
    op.create_table(
        "membership_renewal_requests",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("target_subject_id", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=4000), nullable=False),
        sa.Column("current_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("checker_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(length=4000), nullable=True),
        sa.Column("decision_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("requester_id = target_subject_id", name="self_request"),
        sa.CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED')", name="state"),
        sa.CheckConstraint("requested_expires_at > current_expires_at", name="extension_positive"),
        sa.CheckConstraint(
            "checker_id IS NULL OR checker_id <> target_subject_id",
            name="independent_checker",
        ),
        sa.CheckConstraint(
            "(state = 'PENDING' AND checker_id IS NULL AND decision_reason IS NULL "
            "AND decision_policy_decision_id IS NULL AND decided_at IS NULL) OR "
            "(state IN ('APPROVED', 'REJECTED') AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name="state_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "target_subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_membership_renewals_target_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_membership_renewals_requester_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_membership_renewals_checker_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        schema="iam",
    )
    op.create_index(
        "ix_membership_renewals_workspace_state_created",
        "membership_renewal_requests",
        ["workspace_id", "state", "created_at"],
        schema="iam",
    )
    op.create_index(
        "uq_membership_renewals_pending_subject",
        "membership_renewal_requests",
        ["workspace_id", "target_subject_id"],
        unique=True,
        postgresql_where=sa.text("state = 'PENDING'"),
        schema="iam",
    )
    op.execute("ALTER TABLE iam.membership_renewal_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.membership_renewal_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON iam.membership_renewal_requests "
        f"USING (workspace_id = {RLS_SETTING}) "
        f"WITH CHECK (workspace_id = {RLS_SETTING})"
    )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical renewal shape.
    pass
