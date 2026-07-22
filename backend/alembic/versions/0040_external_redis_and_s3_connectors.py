"""Add external Redis connector profiles and Redis probe evidence.

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_TABLE = "external_service_profiles"
_PROFILE_SCHEMA = "platform"
_SERVICE_CONSTRAINT = "ck_external_service_profiles_service_key_vocabulary"
_ENDPOINT_CONSTRAINT = "ck_external_service_profiles_endpoint_url_scheme"
_SCOPE_CONSTRAINT = "ck_external_service_profile_versions_test_scope_vocabulary"
_SERVICE_KEYS = (
    "service_key IN ('DATAHUB', 'DATAHUB_FRONTEND', 'AIRFLOW', 'REDIS_CACHE', "
    "'REDIS_DELIVERY', 'S3_STORAGE', 'LLM_CHAT_MODEL', 'LLM_EMBEDDING', "
    "'LLM_RERANKER', 'NEO4J', 'PROMETHEUS', 'GRAFANA_DASHBOARD')"
)
_ENDPOINT_SCHEMES = "endpoint_url ~ '^(https?|redis|rediss)://'"
_SCOPES = (
    "test_scope IS NULL OR test_scope IN ('HTTP_HEALTH', 'MODEL_DISCOVERY', "
    "'MODEL_INFERENCE', 'EMBEDDING_INFERENCE', 'AUTHENTICATED_QUERY', 'REDIS_PING')"
)


def _definition(name: str, table: str) -> str | None:
    value = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT pg_get_constraintdef(c.oid)
                FROM pg_constraint AS c
                WHERE c.conrelid = to_regclass(:table_name)
                  AND c.conname = :constraint_name
                """
            ),
            {"table_name": f"{_PROFILE_SCHEMA}.{table}", "constraint_name": name},
        )
        .scalar_one_or_none()
    )
    return value if isinstance(value, str) else None


def _replace(name: str, table: str, expression: str, required_markers: tuple[str, ...]) -> None:
    definition = _definition(name, table)
    if definition is not None and all(marker in definition for marker in required_markers):
        return
    if definition is not None:
        op.drop_constraint(op.f(name), table, schema=_PROFILE_SCHEMA, type_="check")
    op.create_check_constraint(op.f(name), table, expression, schema=_PROFILE_SCHEMA)


def upgrade() -> None:
    _replace(
        _SERVICE_CONSTRAINT,
        _PROFILE_TABLE,
        _SERVICE_KEYS,
        ("REDIS_CACHE", "REDIS_DELIVERY"),
    )
    _replace(
        _ENDPOINT_CONSTRAINT,
        _PROFILE_TABLE,
        _ENDPOINT_SCHEMES,
        ("redis", "rediss"),
    )
    _replace(
        _SCOPE_CONSTRAINT,
        "external_service_profile_versions",
        _SCOPES,
        ("REDIS_PING",),
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') THEN
                GRANT USAGE ON SCHEMA platform TO datariver_relay;
                GRANT SELECT ON platform.external_service_profiles,
                    platform.external_service_profile_versions TO datariver_relay;
            END IF;
        END
        $datariver$;
        """
    )


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical connector vocabulary.
    pass
