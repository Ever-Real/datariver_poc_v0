# ruff: noqa: E501, S608 -- generated constraint SQL and fixed compatibility DDL.

"""Persist governed classification access and inference routing metadata.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-16 12:53:57.769198+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CANONICAL_TABLES = {
    "authz.classification_access_generations": (
        (
            "workspace_id|uuid|uuid||NO",
            "generation|bigint|int8||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
        ),
        (
            "ck_classification_access_generations_generation_nonnegative",
            "fk_classification_access_generations_workspace_id_workspaces",
            "pk_classification_access_generations",
        ),
        (),
    ),
    "integration.inference_provider_generations": (
        (
            "workspace_id|uuid|uuid||NO",
            "generation|bigint|int8||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
        ),
        (
            "ck_inference_provider_generations_generation_nonnegative",
            "fk_inference_provider_generations_workspace_id_workspaces",
            "pk_inference_provider_generations",
        ),
        (),
    ),
    "authz.classification_access_policy_versions": (
        (
            "workspace_id|uuid|uuid||NO",
            "policy_number|integer|int4||NO",
            "required_jurisdiction|character varying|varchar|64|NO",
            "restricted_search_grant_maximum_days|integer|int4||NO",
            "payload_hash|character varying|varchar|64|NO",
            "requester_id|uuid|uuid||NO",
            "request_reason|character varying|varchar|4000|NO",
            "request_policy_decision_id|uuid|uuid||NO",
            "state|character varying|varchar|20|NO",
            "checker_id|uuid|uuid||YES",
            "decision_reason|character varying|varchar|4000|YES",
            "decision_policy_decision_id|uuid|uuid||YES",
            "decided_at|timestamp with time zone|timestamptz||YES",
            "superseded_by|uuid|uuid||YES",
            "supersede_reason|character varying|varchar|4000|YES",
            "supersede_policy_decision_id|uuid|uuid||YES",
            "superseded_at|timestamp with time zone|timestamptz||YES",
            "id|uuid|uuid||NO",
            "created_at|timestamp with time zone|timestamptz||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
            "version|integer|int4||NO",
        ),
        (
            "ck_classification_access_policy_versions_grant_maximum_days",
            "ck_classification_access_policy_versions_independent_checker",
            "ck_classification_access_policy_versions_jurisdiction",
            "ck_classification_access_policy_versions_payload_hash_sha256",
            "ck_classification_access_policy_versions_policy_number_positive",
            "ck_classification_access_policy_versions_reasons_nonempty",
            "ck_classification_access_policy_versions_state",
            "ck_classification_access_policy_versions_state_shape",
            "ck_classification_access_policy_versions_version_positive",
            "fk_classification_access_policy_versions_workspace_id_w_8bf9",
            "fk_classification_policy_versions_checker_membership",
            "fk_classification_policy_versions_requester_membership",
            "fk_classification_policy_versions_superseder_membership",
            "pk_classification_access_policy_versions",
            "uq_classification_policy_versions_exact",
            "uq_classification_policy_versions_number",
            "uq_classification_policy_versions_workspace_id",
        ),
        (
            "ix_classification_policy_versions_workspace_number",
            "uq_classification_policy_versions_workspace_active",
        ),
    ),
    "integration.inference_provider_profile_versions": (
        (
            "workspace_id|uuid|uuid||NO",
            "profile_key|character varying|varchar|128|NO",
            "profile_version|integer|int4||NO",
            "server_route_key|character varying|varchar|128|NO",
            "kind|character varying|varchar|20|NO",
            "provider_identity|character varying|varchar|256|NO",
            "model_identity|character varying|varchar|256|NO",
            "deployment_identity|character varying|varchar|256|NO",
            "jurisdiction|character varying|varchar|64|NO",
            "region|character varying|varchar|64|NO",
            "maximum_classification|integer|int4||NO",
            "residency_attestation_fingerprint|character varying|varchar|64|NO",
            "residency_attestation_observed_at|timestamp with time zone|timestamptz||NO",
            "residency_attestation_expires_at|timestamp with time zone|timestamptz||NO",
            "zero_retention_attestation_fingerprint|character varying|varchar|64|NO",
            "zero_retention_attestation_observed_at|timestamp with time zone|timestamptz||NO",
            "zero_retention_attestation_expires_at|timestamp with time zone|timestamptz||NO",
            "payload_hash|character varying|varchar|64|NO",
            "maker_id|uuid|uuid||NO",
            "proposal_reason|character varying|varchar|1000|NO",
            "proposal_policy_decision_id|uuid|uuid||NO",
            "proposed_at|timestamp with time zone|timestamptz||NO",
            "state|character varying|varchar|20|NO",
            "checker_id|uuid|uuid||YES",
            "decision_reason|character varying|varchar|1000|YES",
            "decision_policy_decision_id|uuid|uuid||YES",
            "decided_at|timestamp with time zone|timestamptz||YES",
            "revoked_by|uuid|uuid||YES",
            "revocation_reason|character varying|varchar|1000|YES",
            "revocation_policy_decision_id|uuid|uuid||YES",
            "revoked_at|timestamp with time zone|timestamptz||YES",
            "id|uuid|uuid||NO",
            "created_at|timestamp with time zone|timestamptz||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
            "version|integer|int4||NO",
        ),
        (
            "ck_inference_provider_profile_versions_attestation_hashes",
            "ck_inference_provider_profile_versions_attestation_windows",
            "ck_inference_provider_profile_versions_classification",
            "ck_inference_provider_profile_versions_external_classif_71fd",
            "ck_inference_provider_profile_versions_independent_checker",
            "ck_inference_provider_profile_versions_kind",
            "ck_inference_provider_profile_versions_no_endpoint_values",
            "ck_inference_provider_profile_versions_payload_hash_sha256",
            "ck_inference_provider_profile_versions_profile_version_positive",
            "ck_inference_provider_profile_versions_reasons_nonempty",
            "ck_inference_provider_profile_versions_state",
            "ck_inference_provider_profile_versions_state_shape",
            "ck_inference_provider_profile_versions_version_positive",
            "fk_inference_profile_versions_checker_membership",
            "fk_inference_profile_versions_maker_membership",
            "fk_inference_profile_versions_revoker_membership",
            "fk_inference_provider_profile_versions_workspace_id_workspaces",
            "pk_inference_provider_profile_versions",
            "uq_inference_profile_versions_key_version",
            "uq_inference_profile_versions_workspace_id",
        ),
        (
            "ix_inference_profile_versions_workspace_order",
            "ix_inference_profile_versions_workspace_state",
        ),
    ),
    "authz.classification_access_policy_rules": (
        (
            "workspace_id|uuid|uuid||NO",
            "policy_id|uuid|uuid||NO",
            "policy_hash|character varying|varchar|64|NO",
            "classification|integer|int4||NO",
            "search_mode|character varying|varchar|30|NO",
            "chat_mode|character varying|varchar|30|NO",
            "provider_profile_version_id|uuid|uuid||YES",
            "embedding_provider_profile_version_id|uuid|uuid||YES",
            "reranker_provider_profile_version_id|uuid|uuid||YES",
            "id|uuid|uuid||NO",
        ),
        (
            "ck_classification_access_policy_rules_chat_mode",
            "ck_classification_access_policy_rules_classification",
            "ck_classification_access_policy_rules_confidential_chat_floor",
            "ck_classification_access_policy_rules_provider_binding",
            "ck_classification_access_policy_rules_restricted_floor",
            "ck_classification_access_policy_rules_search_mode",
            "fk_classification_access_policy_rules_workspace_id_workspaces",
            "fk_classification_policy_rules_embedding_profile",
            "fk_classification_policy_rules_policy",
            "fk_classification_policy_rules_provider_profile",
            "fk_classification_policy_rules_reranker_profile",
            "pk_classification_access_policy_rules",
            "uq_classification_policy_rules_classification",
        ),
        ("ix_classification_policy_rules_policy",),
    ),
    "authz.restricted_search_grants": (
        (
            "workspace_id|uuid|uuid||NO",
            "classification_policy_id|uuid|uuid||NO",
            "classification_policy_hash|character varying|varchar|64|NO",
            "subject_id|uuid|uuid||NO",
            "scope|character varying|varchar|20|NO",
            "scope_id|uuid|uuid||NO",
            "purpose|character varying|varchar|4000|NO",
            "valid_from|timestamp with time zone|timestamptz||NO",
            "expires_at|timestamp with time zone|timestamptz||NO",
            "payload_hash|character varying|varchar|64|NO",
            "requester_id|uuid|uuid||NO",
            "request_reason|character varying|varchar|4000|NO",
            "request_policy_decision_id|uuid|uuid||NO",
            "state|character varying|varchar|20|NO",
            "checker_id|uuid|uuid||YES",
            "decision_reason|character varying|varchar|4000|YES",
            "decision_policy_decision_id|uuid|uuid||YES",
            "decided_at|timestamp with time zone|timestamptz||YES",
            "revoked_by|uuid|uuid||YES",
            "revocation_reason|character varying|varchar|4000|YES",
            "revocation_policy_decision_id|uuid|uuid||YES",
            "revoked_at|timestamp with time zone|timestamptz||YES",
            "id|uuid|uuid||NO",
            "created_at|timestamp with time zone|timestamptz||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
            "version|integer|int4||NO",
        ),
        (
            "ck_restricted_search_grants_independent_checker",
            "ck_restricted_search_grants_payload_hash_sha256",
            "ck_restricted_search_grants_policy_hash_sha256",
            "ck_restricted_search_grants_reasons_nonempty",
            "ck_restricted_search_grants_scope",
            "ck_restricted_search_grants_state",
            "ck_restricted_search_grants_state_shape",
            "ck_restricted_search_grants_subject_cannot_check",
            "ck_restricted_search_grants_validity_window",
            "ck_restricted_search_grants_version_positive",
            "fk_restricted_search_grants_checker_membership",
            "fk_restricted_search_grants_policy",
            "fk_restricted_search_grants_requester_membership",
            "fk_restricted_search_grants_revoker_membership",
            "fk_restricted_search_grants_subject_membership",
            "fk_restricted_search_grants_workspace_id_workspaces",
            "pk_restricted_search_grants",
            "uq_restricted_search_grants_workspace_id",
        ),
        (
            "ix_restricted_search_grants_scope_active",
            "ix_restricted_search_grants_subject_active",
            "ix_restricted_search_grants_workspace_created_id",
        ),
    ),
    "authz.restricted_search_grant_events": (
        (
            "workspace_id|uuid|uuid||NO",
            "grant_id|uuid|uuid||NO",
            "action|character varying|varchar|20|NO",
            "actor_id|uuid|uuid||NO",
            "reason|character varying|varchar|4000|NO",
            "policy_decision_id|uuid|uuid||NO",
            "occurred_at|timestamp with time zone|timestamptz||NO",
            "grant_version|integer|int4||NO",
            "payload_hash|character varying|varchar|64|NO",
            "id|uuid|uuid||NO",
        ),
        (
            "ck_restricted_search_grant_events_action",
            "ck_restricted_search_grant_events_grant_version",
            "ck_restricted_search_grant_events_payload_hash_sha256",
            "ck_restricted_search_grant_events_reason_nonempty",
            "fk_restricted_search_grant_events_actor_membership",
            "fk_restricted_search_grant_events_grant",
            "fk_restricted_search_grant_events_workspace_id_workspaces",
            "pk_restricted_search_grant_events",
            "uq_grant_events_version",
        ),
        ("ix_restricted_search_grant_events_grant",),
    ),
}


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM (VALUES
                    ('authz', 'classification_access_generations'),
                    ('authz', 'classification_access_policy_versions'),
                    ('authz', 'classification_access_policy_rules'),
                    ('authz', 'restricted_search_grants'),
                    ('authz', 'restricted_search_grant_events'),
                    ('integration', 'inference_provider_generations'),
                    ('integration', 'inference_provider_profile_versions')
                ) AS expected(schema_name, table_name)
                WHERE to_regclass(format('%I.%I', schema_name, table_name)) IS NOT NULL
                """
            )
        )
        .scalar_one()
    )


def _table_contract_is_exact(
    relation: str,
    expected_columns: tuple[str, ...],
    expected_constraints: tuple[str, ...],
    expected_indexes: tuple[str, ...],
) -> bool:
    schema_name, table_name = relation.split(".", maxsplit=1)
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
                        WHERE table_schema = :schema_name AND table_name = :table_name
                        ORDER BY ordinal_position
                    ) AS columns,
                    ARRAY(
                        SELECT conname FROM pg_constraint
                        WHERE conrelid = to_regclass(:relation)
                        ORDER BY conname
                    ) AS constraints,
                    ARRAY(
                        SELECT index_class.relname
                        FROM pg_index AS index_state
                        JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
                        WHERE index_state.indrelid = to_regclass(:relation)
                          AND NOT EXISTS (
                              SELECT 1 FROM pg_constraint
                              WHERE conindid = index_state.indexrelid
                          )
                        ORDER BY index_class.relname
                    ) AS indexes,
                    ARRAY(
                        SELECT polname FROM pg_policy
                        WHERE polrelid = to_regclass(:relation)
                        ORDER BY polname
                    ) AS policies,
                    COALESCE((
                        SELECT relrowsecurity AND relforcerowsecurity
                        FROM pg_class WHERE oid = to_regclass(:relation)
                    ), FALSE) AS force_rls
                """
            ),
            {
                "relation": relation,
                "schema_name": schema_name,
                "table_name": table_name,
            },
        )
        .mappings()
        .one()
    )
    return (
        tuple(sorted(row["columns"])) == tuple(sorted(expected_columns))
        and tuple(row["constraints"]) == expected_constraints
        and tuple(row["indexes"]) == expected_indexes
        and tuple(row["policies"]) == ("workspace_isolation",)
        and bool(row["force_rls"])
    )


def _is_canonical_schema() -> bool:
    return all(
        _table_contract_is_exact(relation, *expected)
        for relation, expected in _CANONICAL_TABLES.items()
    )


def upgrade() -> None:
    existing_tables = _existing_object_count()
    if existing_tables:
        if existing_tables != 7 or not _is_canonical_schema():
            raise RuntimeError("The governed classification schema is only partially present.")
        _install_security_contract()
        return
    op.create_table(
        "classification_access_generations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generation >= 0",
            name=op.f("ck_classification_access_generations_generation_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_classification_access_generations_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_classification_access_generations")),
        schema="authz",
    )
    op.create_table(
        "inference_provider_generations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generation >= 0", name=op.f("ck_inference_provider_generations_generation_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_inference_provider_generations_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_inference_provider_generations")),
        schema="integration",
    )
    op.create_table(
        "classification_access_policy_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("policy_number", sa.Integer(), nullable=False),
        sa.Column("required_jurisdiction", sa.String(length=64), nullable=False),
        sa.Column("restricted_search_grant_maximum_days", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.String(length=4000), nullable=False),
        sa.Column("request_policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("checker_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(length=4000), nullable=True),
        sa.Column("decision_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.Column("supersede_reason", sa.String(length=4000), nullable=True),
        sa.Column("supersede_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "(state = 'PROPOSED' AND version = 1 AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL AND superseded_by IS NULL AND supersede_reason IS NULL AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR (state IN ('ACTIVE', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND superseded_by IS NULL AND supersede_reason IS NULL AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR (state = 'SUPERSEDED' AND version = 3 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND superseded_by IS NOT NULL AND supersede_reason IS NOT NULL AND supersede_policy_decision_id IS NOT NULL AND superseded_at IS NOT NULL)",
            name=op.f("ck_classification_access_policy_versions_state_shape"),
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_classification_access_policy_versions_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "state IN ('PROPOSED', 'ACTIVE', 'REJECTED', 'SUPERSEDED')",
            name=op.f("ck_classification_access_policy_versions_state"),
        ),
        sa.CheckConstraint(
            "checker_id IS NULL OR checker_id <> requester_id",
            name=op.f("ck_classification_access_policy_versions_independent_checker"),
        ),
        sa.CheckConstraint(
            "length(btrim(request_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND (supersede_reason IS NULL OR length(btrim(supersede_reason)) > 0)",
            name=op.f("ck_classification_access_policy_versions_reasons_nonempty"),
        ),
        sa.CheckConstraint(
            "length(btrim(required_jurisdiction)) BETWEEN 1 AND 64",
            name=op.f("ck_classification_access_policy_versions_jurisdiction"),
        ),
        sa.CheckConstraint(
            "policy_number > 0",
            name=op.f("ck_classification_access_policy_versions_policy_number_positive"),
        ),
        sa.CheckConstraint(
            "restricted_search_grant_maximum_days BETWEEN 1 AND 365",
            name=op.f("ck_classification_access_policy_versions_grant_maximum_days"),
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_classification_access_policy_versions_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_classification_policy_versions_checker_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_classification_policy_versions_requester_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "superseded_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_classification_policy_versions_superseder_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_classification_access_policy_versions_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classification_access_policy_versions")),
        sa.UniqueConstraint(
            "workspace_id", "id", "payload_hash", name="uq_classification_policy_versions_exact"
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_classification_policy_versions_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id", "policy_number", name="uq_classification_policy_versions_number"
        ),
        schema="authz",
    )
    op.create_index(
        "ix_classification_policy_versions_workspace_number",
        "classification_access_policy_versions",
        ["workspace_id", "policy_number"],
        unique=False,
        schema="authz",
    )
    op.create_index(
        "uq_classification_policy_versions_workspace_active",
        "classification_access_policy_versions",
        ["workspace_id"],
        unique=True,
        schema="authz",
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_table(
        "inference_provider_profile_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("profile_key", sa.String(length=128), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("server_route_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("provider_identity", sa.String(length=256), nullable=False),
        sa.Column("model_identity", sa.String(length=256), nullable=False),
        sa.Column("deployment_identity", sa.String(length=256), nullable=False),
        sa.Column("jurisdiction", sa.String(length=64), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("maximum_classification", sa.Integer(), nullable=False),
        sa.Column("residency_attestation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("residency_attestation_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("residency_attestation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("zero_retention_attestation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "zero_retention_attestation_observed_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "zero_retention_attestation_expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("maker_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_reason", sa.String(length=1000), nullable=False),
        sa.Column("proposal_policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("checker_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(length=1000), nullable=True),
        sa.Column("decision_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=1000), nullable=True),
        sa.Column("revocation_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "(state = 'PROPOSED' AND version = 1 AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state IN ('APPROVED', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state = 'REVOKED' AND version = 3 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL AND revocation_policy_decision_id IS NOT NULL AND revoked_at IS NOT NULL)",
            name=op.f("ck_inference_provider_profile_versions_state_shape"),
        ),
        sa.CheckConstraint(
            "kind <> 'EXTERNAL' OR maximum_classification <= 1",
            name=op.f("ck_inference_provider_profile_versions_external_classification_floor"),
        ),
        sa.CheckConstraint(
            "kind IN ('INTERNAL', 'EXTERNAL')",
            name=op.f("ck_inference_provider_profile_versions_kind"),
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_inference_provider_profile_versions_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "profile_key !~ '://' AND server_route_key !~ '://' AND provider_identity !~ '://' AND model_identity !~ '://' AND deployment_identity !~ '://'",
            name=op.f("ck_inference_provider_profile_versions_no_endpoint_values"),
        ),
        sa.CheckConstraint(
            "residency_attestation_fingerprint ~ '^[0-9a-f]{64}$' AND zero_retention_attestation_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_inference_provider_profile_versions_attestation_hashes"),
        ),
        sa.CheckConstraint(
            "state IN ('PROPOSED', 'APPROVED', 'REJECTED', 'REVOKED')",
            name=op.f("ck_inference_provider_profile_versions_state"),
        ),
        sa.CheckConstraint(
            "checker_id IS NULL OR checker_id <> maker_id",
            name=op.f("ck_inference_provider_profile_versions_independent_checker"),
        ),
        sa.CheckConstraint(
            "length(btrim(proposal_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND (revocation_reason IS NULL OR length(btrim(revocation_reason)) > 0)",
            name=op.f("ck_inference_provider_profile_versions_reasons_nonempty"),
        ),
        sa.CheckConstraint(
            "maximum_classification BETWEEN 0 AND 2",
            name=op.f("ck_inference_provider_profile_versions_classification"),
        ),
        sa.CheckConstraint(
            "profile_version > 0",
            name=op.f("ck_inference_provider_profile_versions_profile_version_positive"),
        ),
        sa.CheckConstraint(
            "residency_attestation_expires_at > residency_attestation_observed_at AND zero_retention_attestation_expires_at > zero_retention_attestation_observed_at",
            name=op.f("ck_inference_provider_profile_versions_attestation_windows"),
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_inference_provider_profile_versions_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_inference_profile_versions_checker_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "maker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_inference_profile_versions_maker_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "revoked_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_inference_profile_versions_revoker_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_inference_provider_profile_versions_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inference_provider_profile_versions")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_inference_profile_versions_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "profile_key",
            "profile_version",
            name="uq_inference_profile_versions_key_version",
        ),
        schema="integration",
    )
    op.create_index(
        "ix_inference_profile_versions_workspace_state",
        "inference_provider_profile_versions",
        ["workspace_id", "state", "profile_key"],
        unique=False,
        schema="integration",
    )
    op.create_table(
        "classification_access_policy_rules",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("search_mode", sa.String(length=30), nullable=False),
        sa.Column("chat_mode", sa.String(length=30), nullable=False),
        sa.Column("provider_profile_version_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(chat_mode = 'DENY' AND provider_profile_version_id IS NULL) OR (chat_mode <> 'DENY' AND provider_profile_version_id IS NOT NULL)",
            name=op.f("ck_classification_access_policy_rules_provider_binding"),
        ),
        sa.CheckConstraint(
            "(classification = 3 AND search_mode IN ('DENY', 'EXPLICIT_GRANT_ONLY') AND chat_mode = 'DENY') OR (classification <> 3 AND search_mode <> 'EXPLICIT_GRANT_ONLY')",
            name=op.f("ck_classification_access_policy_rules_restricted_floor"),
        ),
        sa.CheckConstraint(
            "chat_mode IN ('DENY', 'INTERNAL_APPROVED_ONLY', 'APPROVED_PROVIDER_ONLY')",
            name=op.f("ck_classification_access_policy_rules_chat_mode"),
        ),
        sa.CheckConstraint(
            "classification <> 2 OR chat_mode IN ('DENY', 'INTERNAL_APPROVED_ONLY')",
            name=op.f("ck_classification_access_policy_rules_confidential_chat_floor"),
        ),
        sa.CheckConstraint(
            "search_mode IN ('ABAC', 'DENY', 'EXPLICIT_GRANT_ONLY')",
            name=op.f("ck_classification_access_policy_rules_search_mode"),
        ),
        sa.CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name=op.f("ck_classification_access_policy_rules_classification"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "policy_id", "policy_hash"],
            [
                "authz.classification_access_policy_versions.workspace_id",
                "authz.classification_access_policy_versions.id",
                "authz.classification_access_policy_versions.payload_hash",
            ],
            name="fk_classification_policy_rules_policy",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "provider_profile_version_id"],
            [
                "integration.inference_provider_profile_versions.workspace_id",
                "integration.inference_provider_profile_versions.id",
            ],
            name="fk_classification_policy_rules_provider_profile",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_classification_access_policy_rules_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classification_access_policy_rules")),
        sa.UniqueConstraint(
            "workspace_id",
            "policy_id",
            "classification",
            name="uq_classification_policy_rules_classification",
        ),
        schema="authz",
    )
    op.create_index(
        "ix_classification_policy_rules_policy",
        "classification_access_policy_rules",
        ["workspace_id", "policy_id"],
        unique=False,
        schema="authz",
    )
    op.create_table(
        "restricted_search_grants",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("classification_policy_id", sa.Uuid(), nullable=False),
        sa.Column("classification_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=4000), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("request_reason", sa.String(length=4000), nullable=False),
        sa.Column("request_policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("checker_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(length=4000), nullable=True),
        sa.Column("decision_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=4000), nullable=True),
        sa.Column("revocation_policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "(state = 'PENDING' AND version = 1 AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state IN ('ACTIVE', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state = 'REVOKED' AND version = 3 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL AND revocation_policy_decision_id IS NOT NULL AND revoked_at IS NOT NULL)",
            name=op.f("ck_restricted_search_grants_state_shape"),
        ),
        sa.CheckConstraint(
            "classification_policy_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_restricted_search_grants_policy_hash_sha256"),
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_restricted_search_grants_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "scope IN ('RESOURCE', 'SYSTEM', 'DOMAIN')",
            name=op.f("ck_restricted_search_grants_scope"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'REJECTED', 'REVOKED')",
            name=op.f("ck_restricted_search_grants_state"),
        ),
        sa.CheckConstraint(
            "checker_id IS NULL OR checker_id <> requester_id",
            name=op.f("ck_restricted_search_grants_independent_checker"),
        ),
        sa.CheckConstraint(
            "checker_id IS NULL OR checker_id <> subject_id",
            name=op.f("ck_restricted_search_grants_subject_cannot_check"),
        ),
        sa.CheckConstraint(
            "expires_at > valid_from", name=op.f("ck_restricted_search_grants_validity_window")
        ),
        sa.CheckConstraint(
            "length(btrim(purpose)) > 0 AND length(btrim(request_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND (revocation_reason IS NULL OR length(btrim(revocation_reason)) > 0)",
            name=op.f("ck_restricted_search_grants_reasons_nonempty"),
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_restricted_search_grants_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_checker_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "classification_policy_id", "classification_policy_hash"],
            [
                "authz.classification_access_policy_versions.workspace_id",
                "authz.classification_access_policy_versions.id",
                "authz.classification_access_policy_versions.payload_hash",
            ],
            name="fk_restricted_search_grants_policy",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_requester_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "revoked_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_revoker_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_subject_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_restricted_search_grants_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restricted_search_grants")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_restricted_search_grants_workspace_id"),
        schema="authz",
    )
    op.create_index(
        "ix_restricted_search_grants_scope_active",
        "restricted_search_grants",
        ["workspace_id", "scope", "scope_id", "state", "expires_at"],
        unique=False,
        schema="authz",
    )
    op.create_index(
        "ix_restricted_search_grants_subject_active",
        "restricted_search_grants",
        ["workspace_id", "subject_id", "state", "expires_at"],
        unique=False,
        schema="authz",
    )
    op.create_table(
        "restricted_search_grant_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=4000), nullable=False),
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grant_version", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "action IN ('PROPOSED', 'APPROVED', 'REJECTED', 'REVOKED')",
            name=op.f("ck_restricted_search_grant_events_action"),
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_restricted_search_grant_events_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "grant_version BETWEEN 1 AND 3",
            name=op.f("ck_restricted_search_grant_events_grant_version"),
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0",
            name=op.f("ck_restricted_search_grant_events_reason_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grant_events_actor_membership",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "grant_id"],
            ["authz.restricted_search_grants.workspace_id", "authz.restricted_search_grants.id"],
            name="fk_restricted_search_grant_events_grant",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_restricted_search_grant_events_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restricted_search_grant_events")),
        sa.UniqueConstraint(
            "workspace_id", "grant_id", "grant_version", name="uq_grant_events_version"
        ),
        schema="authz",
    )
    op.create_index(
        "ix_restricted_search_grant_events_grant",
        "restricted_search_grant_events",
        ["workspace_id", "grant_id", "occurred_at"],
        unique=False,
        schema="authz",
    )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical schema.
    pass


def _install_security_contract() -> None:
    workspace_tables = {
        "authz": (
            "classification_access_generations",
            "classification_access_policy_versions",
            "classification_access_policy_rules",
            "restricted_search_grants",
            "restricted_search_grant_events",
        ),
        "integration": (
            "inference_provider_generations",
            "inference_provider_profile_versions",
        ),
    }
    for schema, tables in workspace_tables.items():
        for table in tables:
            op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"""
                DO $datariver$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE schemaname = '{schema}'
                          AND tablename = '{table}'
                          AND policyname = 'workspace_isolation'
                    ) THEN
                        CREATE POLICY workspace_isolation ON {schema}.{table}
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

    op.execute(
        """
        CREATE OR REPLACE FUNCTION authz.validate_classification_policy_activation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $datariver$
        DECLARE
            rule_count integer;
            invalid_provider_count integer;
        BEGIN
            IF NEW.state <> 'ACTIVE' OR OLD.state = 'ACTIVE' THEN
                RETURN NEW;
            END IF;

            SELECT count(*) INTO rule_count
            FROM authz.classification_access_policy_rules
            WHERE workspace_id = NEW.workspace_id
              AND policy_id = NEW.id
              AND policy_hash = NEW.payload_hash;
            IF rule_count <> 4 THEN
                RAISE EXCEPTION 'classification policy requires exactly four bound rules';
            END IF;

            SELECT count(*) INTO invalid_provider_count
            FROM authz.classification_access_policy_rules rule
            LEFT JOIN integration.inference_provider_profile_versions profile
              ON profile.workspace_id = rule.workspace_id
             AND profile.id = rule.provider_profile_version_id
            WHERE rule.workspace_id = NEW.workspace_id
              AND rule.policy_id = NEW.id
              AND rule.policy_hash = NEW.payload_hash
              AND rule.chat_mode <> 'DENY'
              AND (
                    profile.id IS NULL
                 OR profile.state <> 'APPROVED'
                 OR profile.jurisdiction <> NEW.required_jurisdiction
                 OR profile.maximum_classification < rule.classification
                 OR profile.residency_attestation_observed_at > CURRENT_TIMESTAMP
                 OR profile.residency_attestation_expires_at <= CURRENT_TIMESTAMP
                 OR profile.zero_retention_attestation_observed_at > CURRENT_TIMESTAMP
                 OR profile.zero_retention_attestation_expires_at <= CURRENT_TIMESTAMP
                 OR (
                        rule.chat_mode = 'INTERNAL_APPROVED_ONLY'
                    AND profile.kind <> 'INTERNAL'
                 )
                 OR (rule.classification = 2 AND profile.kind <> 'INTERNAL')
              );
            IF invalid_provider_count <> 0 THEN
                RAISE EXCEPTION 'classification policy references an ineligible provider profile';
            END IF;
            RETURN NEW;
        END
        $datariver$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS validate_classification_policy_activation "
        "ON authz.classification_access_policy_versions"
    )
    op.execute(
        """
        CREATE TRIGGER validate_classification_policy_activation
        BEFORE UPDATE OF state
        ON authz.classification_access_policy_versions
        FOR EACH ROW
        EXECUTE FUNCTION authz.validate_classification_policy_activation()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION authz.validate_restricted_search_grant()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $datariver$
        DECLARE
            maximum_days integer;
        BEGIN
            SELECT policy.restricted_search_grant_maximum_days
              INTO maximum_days
            FROM authz.classification_access_policy_versions policy
            JOIN authz.classification_access_policy_rules rule
              ON rule.workspace_id = policy.workspace_id
             AND rule.policy_id = policy.id
             AND rule.policy_hash = policy.payload_hash
             AND rule.classification = 3
             AND rule.search_mode = 'EXPLICIT_GRANT_ONLY'
             AND rule.chat_mode = 'DENY'
            WHERE policy.workspace_id = NEW.workspace_id
              AND policy.id = NEW.classification_policy_id
              AND policy.payload_hash = NEW.classification_policy_hash
              AND policy.state = 'ACTIVE';
            IF maximum_days IS NULL THEN
                RAISE EXCEPTION 'RESTRICTED Search grant requires the bound active policy';
            END IF;
            IF NEW.expires_at > NEW.valid_from + make_interval(days => maximum_days) THEN
                RAISE EXCEPTION 'RESTRICTED Search grant exceeds the active policy maximum';
            END IF;
            RETURN NEW;
        END
        $datariver$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS validate_restricted_search_grant ON authz.restricted_search_grants"
    )
    op.execute(
        """
        CREATE TRIGGER validate_restricted_search_grant
        BEFORE INSERT OR UPDATE OF state, valid_from, expires_at,
            classification_policy_id, classification_policy_hash
        ON authz.restricted_search_grants
        FOR EACH ROW
        EXECUTE FUNCTION authz.validate_restricted_search_grant()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION integration.validate_inference_provider_approval()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $datariver$
        BEGIN
            IF NEW.state = 'APPROVED' AND OLD.state <> 'APPROVED' AND (
                   NEW.residency_attestation_observed_at > CURRENT_TIMESTAMP
                OR NEW.residency_attestation_expires_at <= CURRENT_TIMESTAMP
                OR NEW.zero_retention_attestation_observed_at > CURRENT_TIMESTAMP
                OR NEW.zero_retention_attestation_expires_at <= CURRENT_TIMESTAMP
            ) THEN
                RAISE EXCEPTION 'provider approval requires current attestations';
            END IF;
            RETURN NEW;
        END
        $datariver$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS validate_inference_provider_approval "
        "ON integration.inference_provider_profile_versions"
    )
    op.execute(
        """
        CREATE TRIGGER validate_inference_provider_approval
        BEFORE UPDATE OF state
        ON integration.inference_provider_profile_versions
        FOR EACH ROW
        EXECUTE FUNCTION integration.validate_inference_provider_approval()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION authz.bump_classification_access_generation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $datariver$
        BEGIN
            IF NEW.state IN ('ACTIVE', 'SUPERSEDED', 'REVOKED')
               AND NEW.state IS DISTINCT FROM OLD.state THEN
                INSERT INTO authz.classification_access_generations (
                    workspace_id, generation, updated_at
                ) VALUES (NEW.workspace_id, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (workspace_id) DO UPDATE
                SET generation = authz.classification_access_generations.generation + 1,
                    updated_at = CURRENT_TIMESTAMP;
            END IF;
            RETURN NEW;
        END
        $datariver$
        """
    )
    for table in ("classification_access_policy_versions", "restricted_search_grants"):
        op.execute(f"DROP TRIGGER IF EXISTS bump_classification_access_generation ON authz.{table}")
        op.execute(
            f"""
            CREATE TRIGGER bump_classification_access_generation
            AFTER UPDATE OF state ON authz.{table}
            FOR EACH ROW
            EXECUTE FUNCTION authz.bump_classification_access_generation()
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION integration.bump_inference_provider_generation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $datariver$
        BEGIN
            IF NEW.state IN ('APPROVED', 'REVOKED')
               AND NEW.state IS DISTINCT FROM OLD.state THEN
                INSERT INTO integration.inference_provider_generations (
                    workspace_id, generation, updated_at
                ) VALUES (NEW.workspace_id, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (workspace_id) DO UPDATE
                SET generation = integration.inference_provider_generations.generation + 1,
                    updated_at = CURRENT_TIMESTAMP;
            END IF;
            RETURN NEW;
        END
        $datariver$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS bump_inference_provider_generation "
        "ON integration.inference_provider_profile_versions"
    )
    op.execute(
        """
        CREATE TRIGGER bump_inference_provider_generation
        AFTER UPDATE OF state
        ON integration.inference_provider_profile_versions
        FOR EACH ROW
        EXECUTE FUNCTION integration.bump_inference_provider_generation()
        """
    )
    _grant_application_permissions()


def _grant_application_permissions() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT ON
                    authz.classification_access_policy_versions,
                    authz.restricted_search_grants,
                    integration.inference_provider_profile_versions
                TO datariver_app;
                GRANT SELECT, INSERT ON
                    authz.classification_access_policy_rules,
                    authz.restricted_search_grant_events
                TO datariver_app;
                GRANT SELECT, INSERT, UPDATE ON
                    authz.classification_access_generations,
                    integration.inference_provider_generations
                TO datariver_app;

                GRANT UPDATE (
                    state, checker_id, decision_reason,
                    decision_policy_decision_id, decided_at,
                    superseded_by, supersede_reason,
                    supersede_policy_decision_id, superseded_at,
                    updated_at, version
                ) ON authz.classification_access_policy_versions TO datariver_app;
                GRANT UPDATE (
                    state, checker_id, decision_reason,
                    decision_policy_decision_id, decided_at,
                    revoked_by, revocation_reason,
                    revocation_policy_decision_id, revoked_at,
                    updated_at, version
                ) ON authz.restricted_search_grants TO datariver_app;
                GRANT UPDATE (
                    state, checker_id, decision_reason,
                    decision_policy_decision_id, decided_at,
                    revoked_by, revocation_reason,
                    revocation_policy_decision_id, revoked_at,
                    updated_at, version
                ) ON integration.inference_provider_profile_versions TO datariver_app;

                REVOKE DELETE ON
                    authz.classification_access_policy_versions,
                    authz.classification_access_policy_rules,
                    authz.restricted_search_grants,
                    authz.restricted_search_grant_events,
                    authz.classification_access_generations,
                    integration.inference_provider_profile_versions,
                    integration.inference_provider_generations
                FROM datariver_app;
                REVOKE UPDATE ON
                    authz.classification_access_policy_rules,
                    authz.restricted_search_grant_events
                FROM datariver_app;
            END IF;
        END
        $datariver$
        """
    )
