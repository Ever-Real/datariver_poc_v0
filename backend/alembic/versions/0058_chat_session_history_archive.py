"""add owner-scoped Chat history archive state

Revision ID: 0058
Revises: 0057
Create Date: 2026-07-28 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | Sequence[str] | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "assistant"
TABLE = "chat_sessions"
COLUMN = "is_archived"


def _column_state() -> tuple[str, str, str] | None:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT data_type, is_nullable, COALESCE(column_default, '')
                FROM information_schema.columns
                WHERE table_schema = 'assistant'
                  AND table_name = 'chat_sessions'
                  AND column_name = 'is_archived'
                """
            )
        )
        .one_or_none()
    )
    if row is None:
        return None
    return str(row[0]), str(row[1]), str(row[2])


def _assert_column_contract() -> None:
    state = _column_state()
    if state is None:
        raise RuntimeError("The Chat history archive column is unavailable.")
    data_type, nullable, default = state
    if data_type != "boolean" or nullable != "NO" or "false" not in default.lower():
        raise RuntimeError("The Chat history archive column is not canonical.")


def _grant_owner_mutation() -> None:
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE UPDATE ON assistant.chat_sessions FROM datariver_app;
                GRANT UPDATE (is_favorite, is_archived, version, updated_at)
                    ON assistant.chat_sessions TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def upgrade() -> None:
    state = _column_state()
    if state is None:
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            schema=SCHEMA,
        )
    _assert_column_contract()
    _grant_owner_mutation()


def downgrade() -> None:
    _assert_column_contract()
    archived_count = int(
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM assistant.chat_sessions WHERE is_archived"))
        .scalar_one()
    )
    if archived_count:
        raise RuntimeError("Archived Chat history exists; downgrade would restore deleted items.")
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE UPDATE ON assistant.chat_sessions FROM datariver_app;
                GRANT UPDATE (is_favorite, version, updated_at)
                    ON assistant.chat_sessions TO datariver_app;
            END IF;
        END
        $grant$
        """
    )
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
