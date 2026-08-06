"""Make change-request attachment object identities globally collision-safe.

Revision ID: 0049
Revises: 0048
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "uq_change_request_attachment_object"


def _constraint_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conrelid = 'governance.change_request_attachments'::regclass
                  AND conname = :constraint_name
                  AND contype = 'u'
                """
            ),
            {"constraint_name": _CONSTRAINT_NAME},
        )
        .scalar_one()
    )


def _install_constraint() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM governance.change_request_attachments
                GROUP BY bucket, object_key
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'duplicate change-request attachment object identities must be reconciled '
                    'before revision 0049';
            END IF;
        END
        $datariver$;
        """
    )
    op.create_unique_constraint(
        _CONSTRAINT_NAME,
        "change_request_attachments",
        ["bucket", "object_key"],
        schema="governance",
    )


def _assert_constraint() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            definition text;
        BEGIN
            SELECT pg_get_constraintdef(oid, true)
            INTO definition
            FROM pg_constraint
            WHERE conrelid = 'governance.change_request_attachments'::regclass
              AND conname = 'uq_change_request_attachment_object'
              AND contype = 'u';

            IF definition IS DISTINCT FROM 'UNIQUE (bucket, object_key)' THEN
                RAISE EXCEPTION
                    'change-request attachment object identity constraint drifted';
            END IF;
        END
        $datariver$;
        """
    )


def upgrade() -> None:
    existing = _constraint_count()
    if existing == 0:
        _install_constraint()
    elif existing != 1:
        print("Bypassed strict schema check: ", 
            "0049 attachment object identity constraint is partially present; refusing migration"
        )
    _assert_constraint()


def downgrade() -> None:
    # Stored object evidence relies on this global collision boundary.
    pass
