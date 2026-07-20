"""Record authenticated connector probes and inference binding evidence.

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_external_service_profile_versions_test_scope_vocabulary"
_SCOPES = (
    "test_scope IS NULL OR test_scope IN ('HTTP_HEALTH', 'MODEL_DISCOVERY', "
    "'MODEL_INFERENCE', 'EMBEDDING_INFERENCE', 'AUTHENTICATED_QUERY')"
)


def _is_current() -> bool:
    definition = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint AS c
            WHERE c.conrelid =
                  to_regclass('platform.external_service_profile_versions')
              AND c.conname = :constraint_name
            """
            ),
            {"constraint_name": _CONSTRAINT},
        )
        .scalar_one_or_none()
    )
    scope_is_current = isinstance(definition, str) and all(
        value in definition
        for value in ("MODEL_INFERENCE", "EMBEDDING_INFERENCE", "AUTHENTICATED_QUERY")
    )
    binding_columns = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'knowledge'
                  AND table_name = 'graphrag_audits'
                  AND column_name IN (
                    'configuration_source', 'configuration_version', 'configuration_hash')
                """
            )
        )
        .scalar_one()
    )
    binding_constraint = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = to_regclass('knowledge.graphrag_audits')
                  AND conname = 'ck_graphrag_audits_configuration_evidence_shape'
                """
            )
        )
        .scalar_one_or_none()
    )
    return scope_is_current and binding_columns == 3 and binding_constraint == 1


def upgrade() -> None:
    if _is_current():
        return
    current_scope = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint AS c
            WHERE c.conrelid =
                  to_regclass('platform.external_service_profile_versions')
              AND c.conname = :constraint_name
            """
            ),
            {"constraint_name": _CONSTRAINT},
        )
        .scalar_one_or_none()
    )
    current_scope_is_complete = isinstance(current_scope, str) and all(
        value in current_scope
        for value in ("MODEL_INFERENCE", "EMBEDDING_INFERENCE", "AUTHENTICATED_QUERY")
    )
    if not current_scope_is_complete:
        if isinstance(current_scope, str):
            op.drop_constraint(
                op.f(_CONSTRAINT),
                "external_service_profile_versions",
                schema="platform",
                type_="check",
            )
        op.create_check_constraint(
            op.f(_CONSTRAINT),
            "external_service_profile_versions",
            _SCOPES,
            schema="platform",
        )
    existing_columns = set(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'knowledge'
                  AND table_name = 'graphrag_audits'
                """
            )
        )
        .scalars()
    )
    for name, column_type in (
        ("configuration_source", sa.String(length=32)),
        ("configuration_version", sa.Integer()),
        ("configuration_hash", sa.String(length=64)),
    ):
        if name not in existing_columns:
            op.add_column(
                "graphrag_audits",
                sa.Column(name, column_type, nullable=True),
                schema="knowledge",
            )
    binding_constraint = "ck_graphrag_audits_configuration_evidence_shape"
    binding_exists = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT 1 FROM pg_constraint
            WHERE conrelid = to_regclass('knowledge.graphrag_audits')
              AND conname = :constraint_name
            """
            ),
            {"constraint_name": binding_constraint},
        )
        .scalar_one_or_none()
    )
    if binding_exists is None:
        op.create_check_constraint(
            op.f(binding_constraint),
            "graphrag_audits",
            "(configuration_source IS NULL AND configuration_version IS NULL "
            "AND configuration_hash IS NULL) OR "
            "(configuration_source = 'SYSTEM_CONFIGURATION' "
            "AND configuration_version > 0 "
            "AND configuration_hash ~ '^[0-9a-f]{64}$') OR "
            "(configuration_source = 'DEPLOYMENT' "
            "AND configuration_version IS NULL "
            "AND configuration_hash ~ '^[0-9a-f]{64}$')",
            schema="knowledge",
        )


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical probe vocabulary.
    pass
