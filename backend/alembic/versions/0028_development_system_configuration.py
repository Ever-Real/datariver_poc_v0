"""Add development-scoped YAML system configuration persistence.

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Compatibility bridge: regenerated 0001 already owns this complete
    # canonical shape.  Only databases at the earlier head require DDL.
    op.execute(
        """
DO $datariver$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'platform'
          AND table_name = 'external_service_profiles'
          AND column_name = 'configuration_yaml'
    ) THEN
        ALTER TABLE platform.external_service_profiles
            DROP CONSTRAINT IF EXISTS ck_external_service_profiles_service_key_vocabulary;
        ALTER TABLE platform.external_service_profiles
            DROP CONSTRAINT IF EXISTS service_key_vocabulary;
        ALTER TABLE platform.external_service_profiles
            ADD CONSTRAINT ck_external_service_profiles_service_key_vocabulary
            CHECK (service_key IN (
                'DATAHUB', 'DATAHUB_FRONTEND', 'AIRFLOW', 'S3_STORAGE',
                'LLM_CHAT_MODEL', 'LLM_EMBEDDING', 'LLM_RERANKER', 'NEO4J',
                'PROMETHEUS', 'GRAFANA_DASHBOARD'
            ));
        ALTER TABLE platform.external_service_profiles
            ALTER COLUMN endpoint_url DROP NOT NULL;
        ALTER TABLE platform.external_service_profiles
            ADD COLUMN configuration_yaml text NOT NULL DEFAULT '';
        ALTER TABLE platform.external_service_profiles
            ALTER COLUMN configuration_yaml DROP DEFAULT;
    END IF;
END
$datariver$;
"""
    )


def downgrade() -> None:
    # Configuration rows are operator input.  A downgrade must not discard it.
    pass
