"""Restore the composed Knowledge Studio Proposal request and safety contracts.

Revision ID: 0088
Revises: 0087
Create Date: 2026-08-01
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_CONTENT_SAFETY_STRUCTURAL_FUNCTION_SQL,
    TBOX_PROPOSAL_CONTENT_SAFETY_TEXT_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_IDEMPOTENT_V1_REQUEST_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_PIN_V2_IDEMPOTENT_REQUEST_FUNCTION_SQL,
)

revision: str = "0088"
down_revision: str | Sequence[str] | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST_FUNCTION_SHA256 = "499b73cbc2dd55bd3faa3843184b4c7625fff84f5d8996b7ce5424ecef9a0438"
_STRUCTURAL_SAFETY_FUNCTION_SHA256 = (
    "54c4f62483305d904db5b970ef002a82683533eb17d7d328265d19361345a2ff"
)
_DOWNGRADE_REQUEST_FUNCTION_SHA256 = (
    "b24971aabec7f349a796581d99e3f1b6b36adf842aaff8b0f78710dbae990db4"
)
_DOWNGRADE_SAFETY_FUNCTION_SHA256 = (
    "95561cf960c35a8c5ac7dd8ecfb2822f5b0b2e8b8d965bdeffdeee82bbe7e97a"
)

_DOWNGRADE_PREFLIGHT_SQL = r"""
DO $datariver$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM knowledge.tbox_proposals
        WHERE source_reference_document IS NOT NULL
          AND source_reference_document::text ~*
              '"(bucket|object_key|excerpt|prompt|provider_body|content)"\s*:'
    ) THEN
        RAISE EXCEPTION
            '0088 downgrade requires reconciliation of structurally safe Proposal evidence';
    END IF;
END
$datariver$;
""".strip()


def _pinned(sql: str, expected_sha256: str, *, label: str) -> str:
    if sql.count("CREATE OR REPLACE FUNCTION") != 1:
        raise RuntimeError(f"The Knowledge Studio {label} function boundary changed")
    if hashlib.sha256(sql.encode()).hexdigest() != expected_sha256:
        raise RuntimeError(f"The Knowledge Studio {label} function changed after revision 0088")
    return sql


def upgrade() -> None:
    op.execute(
        _pinned(
            TBOX_PROPOSAL_JOB_PIN_V2_IDEMPOTENT_REQUEST_FUNCTION_SQL,
            _REQUEST_FUNCTION_SHA256,
            label="composed Proposal request",
        )
    )
    op.execute(
        _pinned(
            TBOX_PROPOSAL_CONTENT_SAFETY_STRUCTURAL_FUNCTION_SQL,
            _STRUCTURAL_SAFETY_FUNCTION_SHA256,
            label="structural content-safety",
        )
    )


def downgrade() -> None:
    op.execute(_DOWNGRADE_PREFLIGHT_SQL)
    op.execute(
        _pinned(
            TBOX_PROPOSAL_JOB_IDEMPOTENT_V1_REQUEST_FUNCTION_SQL,
            _DOWNGRADE_REQUEST_FUNCTION_SHA256,
            label="0087 Proposal request",
        )
    )
    op.execute(
        _pinned(
            TBOX_PROPOSAL_CONTENT_SAFETY_TEXT_FUNCTION_SQL,
            _DOWNGRADE_SAFETY_FUNCTION_SHA256,
            label="legacy content-safety",
        )
    )
