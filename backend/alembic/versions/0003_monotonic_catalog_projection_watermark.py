"""Add a monotonic per-workspace catalog projection generation.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The regenerated 0001 contains the current clean-clone schema. These conditional statements
    # also bridge development databases that reached 0002 through the older 0001 definition.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog.projection_watermarks (
            workspace_id uuid NOT NULL,
            projection_version bigint DEFAULT 0 NOT NULL,
            CONSTRAINT pk_projection_watermarks PRIMARY KEY (workspace_id),
            CONSTRAINT ck_projection_watermarks_projection_version_nonnegative
                CHECK (projection_version >= 0),
            CONSTRAINT fk_projection_watermarks_workspace_id_workspaces
                FOREIGN KEY(workspace_id) REFERENCES platform.workspaces (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("ALTER TABLE catalog.projection_watermarks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog.projection_watermarks FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_policies
                WHERE schemaname = 'catalog'
                  AND tablename = 'projection_watermarks'
                  AND policyname = 'workspace_isolation'
            ) THEN
                CREATE POLICY workspace_isolation ON catalog.projection_watermarks
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
        INSERT INTO catalog.projection_watermarks (workspace_id, projection_version)
        SELECT id, 1
        FROM platform.workspaces
        ON CONFLICT (workspace_id) DO NOTHING
        """
    )
    op.execute("DROP INDEX IF EXISTS catalog.ix_assets_projection_workspace_watermark")
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT, UPDATE ON catalog.projection_watermarks TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Compatibility marker only. The regenerated 0001 includes the watermark table and excludes
    # the obsolete timestamp index, so removing either here would make clean and upgraded paths
    # diverge at revision 0002.
    pass
