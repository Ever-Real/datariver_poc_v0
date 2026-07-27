"""bind interactive inference stages to separate governed profiles

Revision ID: 0057
Revises: 0056
Create Date: 2026-07-26 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "authz"
TABLE = "classification_access_policy_rules"
EMBEDDING_COLUMN = "embedding_provider_profile_version_id"
RERANKER_COLUMN = "reranker_provider_profile_version_id"
PROVIDER_BINDING_CHECK = "ck_classification_access_policy_rules_provider_binding"
EMBEDDING_FK = "fk_classification_policy_rules_embedding_profile"
RERANKER_FK = "fk_classification_policy_rules_reranker_profile"
LEGACY_CHECK_DEFINITION = (
    "CHECK (((((chat_mode)::text = 'DENY'::text) AND "
    "(provider_profile_version_id IS NULL)) OR (((chat_mode)::text <> "
    "'DENY'::text) AND (provider_profile_version_id IS NOT NULL))))"
)
STAGED_CHECK_DEFINITION = (
    "CHECK (((((chat_mode)::text = 'DENY'::text) AND "
    "(provider_profile_version_id IS NULL) AND "
    "(embedding_provider_profile_version_id IS NULL) AND "
    "(reranker_provider_profile_version_id IS NULL)) OR "
    "(((chat_mode)::text <> 'DENY'::text) AND "
    "(provider_profile_version_id IS NOT NULL))))"
)
EXPECTED_CONSTRAINTS = {
    PROVIDER_BINDING_CHECK: STAGED_CHECK_DEFINITION,
    EMBEDDING_FK: (
        "FOREIGN KEY (workspace_id, embedding_provider_profile_version_id) "
        "REFERENCES integration.inference_provider_profile_versions(workspace_id, id)"
    ),
    RERANKER_FK: (
        "FOREIGN KEY (workspace_id, reranker_provider_profile_version_id) "
        "REFERENCES integration.inference_provider_profile_versions(workspace_id, id)"
    ),
}


def _normalize_sql(value: str) -> str:
    return " ".join(value.split())


def _staged_schema_state() -> tuple[
    dict[str, tuple[str, str]],
    dict[str, str],
]:
    column_rows = op.get_bind().execute(
        sa.text(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'authz'
              AND table_name = 'classification_access_policy_rules'
              AND column_name IN (
                  'embedding_provider_profile_version_id',
                  'reranker_provider_profile_version_id'
              )
            ORDER BY column_name
            """
        )
    )
    constraint_rows = op.get_bind().execute(
        sa.text(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid =
                'authz.classification_access_policy_rules'::regclass
              AND conname IN (
                  'ck_classification_access_policy_rules_provider_binding',
                  'fk_classification_policy_rules_embedding_profile',
                  'fk_classification_policy_rules_reranker_profile'
              )
            ORDER BY conname
            """
        )
    )
    return (
        {str(row[0]): (str(row[1]), str(row[2])) for row in column_rows},
        {str(row[0]): _normalize_sql(str(row[1])) for row in constraint_rows},
    )


def _is_legacy_schema(
    columns: dict[str, tuple[str, str]],
    constraints: dict[str, str],
) -> bool:
    return not columns and constraints == {
        PROVIDER_BINDING_CHECK: _normalize_sql(LEGACY_CHECK_DEFINITION)
    }


def _is_canonical_schema(
    columns: dict[str, tuple[str, str]],
    constraints: dict[str, str],
) -> bool:
    return columns == {
        EMBEDDING_COLUMN: ("uuid", "YES"),
        RERANKER_COLUMN: ("uuid", "YES"),
    } and constraints == {
        name: _normalize_sql(definition) for name, definition in EXPECTED_CONSTRAINTS.items()
    }


def _assert_staged_schema_contract() -> None:
    columns, constraints = _staged_schema_state()
    if not _is_canonical_schema(columns, constraints):
        raise RuntimeError("The staged inference profile binding schema is not canonical.")


def _install_staged_policy_activation() -> None:
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
            CROSS JOIN LATERAL unnest(
                ARRAY[
                    rule.provider_profile_version_id,
                    rule.embedding_provider_profile_version_id,
                    rule.reranker_provider_profile_version_id
                ]
            ) AS referenced(profile_id)
            LEFT JOIN integration.inference_provider_profile_versions profile
              ON profile.workspace_id = rule.workspace_id
             AND profile.id = referenced.profile_id
            WHERE rule.workspace_id = NEW.workspace_id
              AND rule.policy_id = NEW.id
              AND rule.policy_hash = NEW.payload_hash
              AND rule.chat_mode <> 'DENY'
              AND referenced.profile_id IS NOT NULL
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


def _restore_single_profile_policy_activation() -> None:
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


def _assert_staged_binding_columns_empty() -> None:
    staged_binding_count = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM authz.classification_access_policy_rules
                WHERE embedding_provider_profile_version_id IS NOT NULL
                   OR reranker_provider_profile_version_id IS NOT NULL
                """
            )
        )
        .scalar_one()
    )
    if staged_binding_count:
        raise RuntimeError(
            "Staged inference profile bindings exist; downgrade would discard "
            "immutable policy evidence."
        )


def upgrade() -> None:
    columns, constraints = _staged_schema_state()
    if _is_canonical_schema(columns, constraints):
        # Compatibility bridge: regenerated canonical 0001 already owns the
        # stage-specific columns, FKs and CHECK. Reinstall the trigger because
        # its function body remains a migration-owned security contract.
        _install_staged_policy_activation()
        _assert_staged_schema_contract()
        return
    if not _is_legacy_schema(columns, constraints):
        raise RuntimeError("The staged inference profile binding schema is only partially present.")
    op.add_column(
        TABLE,
        sa.Column(
            EMBEDDING_COLUMN,
            sa.Uuid(),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            RERANKER_COLUMN,
            sa.Uuid(),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        EMBEDDING_FK,
        TABLE,
        "inference_provider_profile_versions",
        ["workspace_id", "embedding_provider_profile_version_id"],
        ["workspace_id", "id"],
        source_schema=SCHEMA,
        referent_schema="integration",
    )
    op.create_foreign_key(
        RERANKER_FK,
        TABLE,
        "inference_provider_profile_versions",
        ["workspace_id", "reranker_provider_profile_version_id"],
        ["workspace_id", "id"],
        source_schema=SCHEMA,
        referent_schema="integration",
    )
    op.drop_constraint(
        op.f(PROVIDER_BINDING_CHECK),
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        op.f(PROVIDER_BINDING_CHECK),
        TABLE,
        "(chat_mode = 'DENY' AND provider_profile_version_id IS NULL "
        "AND embedding_provider_profile_version_id IS NULL "
        "AND reranker_provider_profile_version_id IS NULL) OR "
        "(chat_mode <> 'DENY' AND provider_profile_version_id IS NOT NULL)",
        schema=SCHEMA,
    )
    _install_staged_policy_activation()
    _assert_staged_schema_contract()


def downgrade() -> None:
    _assert_staged_binding_columns_empty()
    _restore_single_profile_policy_activation()
    op.drop_constraint(
        op.f(PROVIDER_BINDING_CHECK),
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        op.f(PROVIDER_BINDING_CHECK),
        TABLE,
        "(chat_mode = 'DENY' AND provider_profile_version_id IS NULL) OR "
        "(chat_mode <> 'DENY' AND provider_profile_version_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.drop_constraint(
        RERANKER_FK,
        TABLE,
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        EMBEDDING_FK,
        TABLE,
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column(
        TABLE,
        RERANKER_COLUMN,
        schema=SCHEMA,
    )
    op.drop_column(
        TABLE,
        EMBEDDING_COLUMN,
        schema=SCHEMA,
    )
