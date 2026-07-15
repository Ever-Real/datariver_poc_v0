"""Bridge pre-hardening development databases to the regenerated initial schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-15
"""

from typing import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A clean clone receives these objects from the regenerated 0001 migration. The IF NOT EXISTS
    # bridge upgrades the already-verified local 0001 database without requiring destructive reset.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "ALTER TABLE authz.policy_decisions "
        "ADD COLUMN IF NOT EXISTS evaluation_context jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE authz.policy_decisions ALTER COLUMN evaluation_context DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE catalog.assets_projection ADD COLUMN IF NOT EXISTS search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, "
        "coalesce(name, '') || ' ' || coalesce(description, ''))) STORED"
    )
    op.execute("DROP INDEX IF EXISTS catalog.ix_assets_projection_name")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assets_projection_active_scope_order "
        "ON catalog.assets_projection (workspace_id, classification, name, id) "
        "WHERE deleted_at IS NULL AND lifecycle = 'ACTIVE'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assets_projection_search_fts_active "
        "ON catalog.assets_projection USING gin (search_vector) "
        "WHERE deleted_at IS NULL AND lifecycle = 'ACTIVE'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assets_projection_name_trgm_active "
        "ON catalog.assets_projection USING gin (name gin_trgm_ops) "
        "WHERE deleted_at IS NULL AND lifecycle = 'ACTIVE'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assets_projection_workspace_watermark "
        "ON catalog.assets_projection (workspace_id, updated_at)"
    )


def downgrade() -> None:
    # Compatibility marker only: these objects are part of the regenerated 0001 clean-clone
    # baseline, so removing them at revision 0001 would make clean and upgraded databases diverge.
    pass
