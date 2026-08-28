"""Add fixed reranking inference probe evidence.

Revision ID: 0053
Revises: 0052
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_external_service_profile_versions_test_scope_vocabulary"
_LEGACY_SCOPES = (
    "HTTP_HEALTH",
    "MODEL_DISCOVERY",
    "MODEL_INFERENCE",
    "EMBEDDING_INFERENCE",
    "AUTHENTICATED_QUERY",
    "REDIS_PING",
    "REDIS_POLICY",
    "S3_HEAD_BUCKET",
)
_CURRENT_SCOPES = (
    "HTTP_HEALTH",
    "MODEL_DISCOVERY",
    "MODEL_INFERENCE",
    "EMBEDDING_INFERENCE",
    "RERANKING_INFERENCE",
    "AUTHENTICATED_QUERY",
    "REDIS_PING",
    "REDIS_POLICY",
    "S3_HEAD_BUCKET",
)


def _scope_sql(scopes: tuple[str, ...]) -> str:
    return (
        "test_scope IS NULL OR test_scope IN (" + ", ".join(f"'{scope}'" for scope in scopes) + ")"
    )


def _scope_definition(scopes: tuple[str, ...]) -> str:
    values = ", ".join(f"'{scope}'::character varying" for scope in scopes)
    return f"CHECK (test_scope IS NULL OR (test_scope::text = ANY (ARRAY[{values}]::text[])))"


def _constraint_definition() -> str | None:
    definition = op.get_bind().scalar(
        sa.text(
            """
            SELECT pg_get_constraintdef(constraint_state.oid, true)
            FROM pg_constraint AS constraint_state
            WHERE constraint_state.conrelid =
                    'platform.external_service_profile_versions'::regclass
              AND constraint_state.conname = :constraint_name
            """
        ),
        {"constraint_name": _CONSTRAINT},
    )
    return definition if isinstance(definition, str) else None


def _replace(*, expected: tuple[str, ...], next_scopes: tuple[str, ...]) -> None:
    if _constraint_definition() != _scope_definition(expected):
        raise RuntimeError("The connector probe scope constraint is missing or malformed.")
    op.drop_constraint(
        op.f(_CONSTRAINT),
        "external_service_profile_versions",
        schema="platform",
        type_="check",
    )
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "external_service_profile_versions",
        _scope_sql(next_scopes),
        schema="platform",
    )
    if _constraint_definition() != _scope_definition(next_scopes):
        raise RuntimeError("The connector probe scope constraint replacement was not canonical.")


def upgrade() -> None:
    definition = _constraint_definition()
    if definition == _scope_definition(_CURRENT_SCOPES):
        return
    _replace(expected=_LEGACY_SCOPES, next_scopes=_CURRENT_SCOPES)


def downgrade() -> None:
    current_evidence = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM platform.external_service_profile_versions "
            "WHERE test_scope = 'RERANKING_INFERENCE'"
        )
    )
    if int(current_evidence or 0) != 0:
        raise RuntimeError(
            "Downgrade would falsify reranking probe evidence; archive or explicitly "
            "invalidate the affected revisions before retrying."
        )
    _replace(expected=_CURRENT_SCOPES, next_scopes=_LEGACY_SCOPES)
