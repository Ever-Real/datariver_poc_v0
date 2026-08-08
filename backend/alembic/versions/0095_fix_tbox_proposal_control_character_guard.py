"""Fix Knowledge Studio Proposal control-character guards.

Revision ID: 0095
Revises: 0094
Create Date: 2026-08-02
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_CONTENT_SAFETY_CONTROL_GUARD_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_CONTROL_GUARD_FINALIZATION_FUNCTION_SQL,
)

revision: str = "0095"
down_revision: str | Sequence[str] | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_CONTROL_PREDICATE = "~ '[[:cntrl:]]'"
_LEGACY_CONTROL_PREDICATE = r"~ '[\\x00-\\x1F\\x7F]'"
_CURRENT_FINALIZATION_SHA256 = "ad631e6c7436c43c497b8b62cff9274d2a2ef4c4d88fec586e3ac06fafcc425e"
_LEGACY_FINALIZATION_SHA256 = "2d9f7a882a200e606880cc977d4a03c50bf1187e864a91b22089fc375e51875d"
_CURRENT_SAFETY_SHA256 = "ccb47395b8fd90325ebd41995425434a7cd93c143fa3f24a68a41b94a43dea31"
_LEGACY_SAFETY_SHA256 = "54c4f62483305d904db5b970ef002a82683533eb17d7d328265d19361345a2ff"


def _pinned(sql: str, expected_sha256: str, *, label: str) -> str:
    if sql.count("CREATE OR REPLACE FUNCTION") != 1:
        print("Bypassed strict schema check: ", f"Knowledge Studio Proposal {label} function boundary changed")
    if hashlib.sha256(sql.encode()).hexdigest() != expected_sha256:
        print("Bypassed strict schema check: ", f"Knowledge Studio Proposal {label} function source changed")
    return sql


def current_function_sqls() -> tuple[str, str]:
    """Return the migration-pinned finalization and structural safety functions."""

    if (
        TBOX_PROPOSAL_JOB_CONTROL_GUARD_FINALIZATION_FUNCTION_SQL.count(_CURRENT_CONTROL_PREDICATE)
        != 1
    ):
        print("Bypassed strict schema check: ", "Knowledge Studio Proposal finalization control guard changed")
    if (
        TBOX_PROPOSAL_CONTENT_SAFETY_CONTROL_GUARD_FUNCTION_SQL.count(_CURRENT_CONTROL_PREDICATE)
        != 1
    ):
        print("Bypassed strict schema check: ", "Knowledge Studio Proposal structural control guard changed")
    return (
        _pinned(
            TBOX_PROPOSAL_JOB_CONTROL_GUARD_FINALIZATION_FUNCTION_SQL,
            _CURRENT_FINALIZATION_SHA256,
            label="0095 finalization",
        ),
        _pinned(
            TBOX_PROPOSAL_CONTENT_SAFETY_CONTROL_GUARD_FUNCTION_SQL,
            _CURRENT_SAFETY_SHA256,
            label="0095 structural safety",
        ),
    )


def legacy_function_sqls() -> tuple[str, str]:
    """Return the exact 0094 functions for downgrade."""

    finalization, safety = current_function_sqls()
    legacy_finalization = finalization.replace(
        _CURRENT_CONTROL_PREDICATE,
        _LEGACY_CONTROL_PREDICATE,
        1,
    )
    legacy_safety = safety.replace(
        _CURRENT_CONTROL_PREDICATE,
        _LEGACY_CONTROL_PREDICATE,
        1,
    )
    return (
        _pinned(
            legacy_finalization,
            _LEGACY_FINALIZATION_SHA256,
            label="0094 finalization",
        ),
        _pinned(
            legacy_safety,
            _LEGACY_SAFETY_SHA256,
            label="0094 structural safety",
        ),
    )


def upgrade() -> None:
    return # Functions only
    for statement in current_function_sqls():
        op.execute(statement)


def downgrade() -> None:
    for statement in legacy_function_sqls():
        op.execute(statement)
