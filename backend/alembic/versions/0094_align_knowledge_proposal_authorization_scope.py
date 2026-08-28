"""Align Knowledge Studio Proposal authorization system scope.

Revision ID: 0094
Revises: 0093
Create Date: 2026-08-02
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_JOB_SUPPORT_FUNCTION_SQL,
)

revision: str = "0094"
down_revision: str | Sequence[str] | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION_START = (
    "CREATE OR REPLACE FUNCTION knowledge.current_tbox_proposal_authorization_hash_v1("
)
_FUNCTION_END = "\n\nCREATE OR REPLACE FUNCTION knowledge.current_tbox_proposal_human_can_v1("
_MANAGED_ALLOWED_SYSTEM_SCOPE = """        'allowed_system_ids', CASE
            WHEN EXISTS (
                SELECT 1
                FROM iam.canonical_admin_bindings AS admin_binding
                WHERE admin_binding.workspace_id = membership.workspace_id
                  AND admin_binding.subject_id = membership.subject_id
            ) OR EXISTS (
                SELECT 1
                FROM iam.profile_role_assignments AS profile_assignment
                WHERE profile_assignment.workspace_id = membership.workspace_id
                  AND profile_assignment.subject_id = membership.subject_id
            ) THEN COALESCE((
                SELECT jsonb_agg(active_scope.system_id ORDER BY active_scope.system_id)
                FROM (
                    SELECT DISTINCT assignee.system_id::text AS system_id
                    FROM platform.system_assignees AS assignee
                    JOIN platform.data_systems AS data_system
                      ON data_system.workspace_id = assignee.workspace_id
                     AND data_system.id = assignee.system_id
                    WHERE assignee.workspace_id = membership.workspace_id
                      AND assignee.subject_id = membership.subject_id
                      AND assignee.active IS TRUE
                      AND data_system.active IS TRUE
                ) AS active_scope
            ), '[]'::jsonb)
            ELSE COALESCE((
                SELECT jsonb_agg(value ORDER BY value)
                FROM jsonb_array_elements_text(
                    COALESCE(membership.attributes -> 'allowed_system_ids', '[]'::jsonb)
                ) AS item(value)
            ), '[]'::jsonb)
        END,"""
_LEGACY_ALLOWED_SYSTEM_SCOPE = """        'allowed_system_ids', COALESCE((
            SELECT jsonb_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(
                COALESCE(membership.attributes -> 'allowed_system_ids', '[]'::jsonb)
            ) AS item(value)
        ), '[]'::jsonb),"""
_CURRENT_SHA256 = "c70b173f64fab6233b59b6f509318e9ce58b91a33bcff5e176fef61ad115e622"
_LEGACY_SHA256 = "9c89eaa41c1b4b5b60d358ac6416336a568f605a5f397d4a216485acd7e823f9"


def _pinned(sql: str, expected_sha256: str, *, label: str) -> str:
    if sql.count("CREATE OR REPLACE FUNCTION") != 1:
        raise RuntimeError(f"Knowledge Studio Proposal {label} function boundary changed")
    if hashlib.sha256(sql.encode()).hexdigest() != expected_sha256:
        raise RuntimeError(f"Knowledge Studio Proposal {label} function source changed")
    return sql


def current_authorization_function_sql() -> str:
    """Return the migration-pinned effective authorization hash function."""

    if (
        TBOX_PROPOSAL_JOB_SUPPORT_FUNCTION_SQL.count(_FUNCTION_START) != 1
        or TBOX_PROPOSAL_JOB_SUPPORT_FUNCTION_SQL.count(_FUNCTION_END) != 1
    ):
        raise RuntimeError("Knowledge Studio Proposal authorization function boundary changed")
    _prefix, _separator, remainder = TBOX_PROPOSAL_JOB_SUPPORT_FUNCTION_SQL.partition(
        _FUNCTION_START
    )
    body, _separator, _remainder = remainder.partition(_FUNCTION_END)
    function_sql = f"{_FUNCTION_START}{body}".strip()
    if function_sql.count(_MANAGED_ALLOWED_SYSTEM_SCOPE) != 1:
        raise RuntimeError("Knowledge Studio Proposal managed system scope boundary changed")
    return _pinned(function_sql, _CURRENT_SHA256, label="0094 authorization")


def legacy_authorization_function_sql() -> str:
    """Return the exact 0093 authorization hash function for downgrade."""

    current = current_authorization_function_sql()
    legacy = current.replace(
        _MANAGED_ALLOWED_SYSTEM_SCOPE,
        _LEGACY_ALLOWED_SYSTEM_SCOPE,
        1,
    )
    return _pinned(legacy, _LEGACY_SHA256, label="0093 authorization")


def upgrade() -> None:
    return # Functions only
    op.execute(current_authorization_function_sql())


def downgrade() -> None:
    op.execute(legacy_authorization_function_sql())
