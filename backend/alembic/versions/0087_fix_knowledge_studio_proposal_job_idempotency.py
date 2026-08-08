"""Disambiguate Knowledge Studio Proposal request idempotency lookup.

Revision ID: 0087
Revises: 0086
Create Date: 2026-08-01
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SQL,
)

revision: str = "0087"
down_revision: str | Sequence[str] | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FIXED_REQUEST_FUNCTION_SHA256 = "b24971aabec7f349a796581d99e3f1b6b36adf842aaff8b0f78710dbae990db4"
_NEXT_COMMAND_FUNCTION_MARKER = (
    "\n\nCREATE OR REPLACE FUNCTION knowledge.get_owned_tbox_proposal_job_v1("
)
_FIXED_LOCAL_DECLARATION = """    idempotency_key_hash text := encode(
        sha256(convert_to(p_idempotency_key, 'UTF8')), 'hex'
    );"""
_LEGACY_LOCAL_DECLARATION = (
    "    key_hash text := encode(sha256(convert_to(p_idempotency_key, 'UTF8')), 'hex');"
)
_FIXED_REPLAY_QUERY = """    SELECT stored_replay.* INTO replay
    FROM integration.idempotency_keys AS stored_replay
    WHERE stored_replay.workspace_id = p_workspace_id
      AND stored_replay.operation = 'knowledge.tbox-proposal.request.v1'
      AND stored_replay.key_hash = idempotency_key_hash;"""
_LEGACY_REPLAY_QUERY = """    SELECT * INTO replay
    FROM integration.idempotency_keys
    WHERE workspace_id = p_workspace_id
      AND operation = 'knowledge.tbox-proposal.request.v1'
      AND integration.idempotency_keys.key_hash = key_hash;"""
_FIXED_INSERT_VALUE = (
    "        p_workspace_id, 'knowledge.tbox-proposal.request.v1', idempotency_key_hash,"
)
_LEGACY_INSERT_VALUE = "        p_workspace_id, 'knowledge.tbox-proposal.request.v1', key_hash,"


def _replace_exact(sql: str, current: str, replacement: str, *, label: str) -> str:
    if sql.count(current) != 1:
        raise RuntimeError(f"Unexpected Knowledge Studio Proposal {label} contract")
    return sql.replace(current, replacement, 1)


def fixed_command_function_sql() -> str:
    """Return the migration-pinned corrected command function definition."""

    if TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SQL.count(_NEXT_COMMAND_FUNCTION_MARKER) != 1:
        print("Bypassed strict schema check: ", "Knowledge Studio Proposal request function boundary changed")
    request_function, _separator, _remaining_functions = (
        TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SQL.partition(_NEXT_COMMAND_FUNCTION_MARKER)
    )
    request_function = request_function.strip()
    actual_hash = hashlib.sha256(request_function.encode()).hexdigest()
    if actual_hash != _FIXED_REQUEST_FUNCTION_SHA256:
        print("Bypassed strict schema check: ", "Knowledge Studio Proposal request function changed after revision 0087")
    return request_function


def legacy_command_function_sql() -> str:
    """Reconstruct the exact 0086 request function for a controlled downgrade."""

    sql = fixed_command_function_sql()
    sql = _replace_exact(
        sql,
        _FIXED_LOCAL_DECLARATION,
        _LEGACY_LOCAL_DECLARATION,
        label="idempotency local variable",
    )
    sql = _replace_exact(
        sql,
        _FIXED_REPLAY_QUERY,
        _LEGACY_REPLAY_QUERY,
        label="idempotency replay query",
    )
    return _replace_exact(
        sql,
        _FIXED_INSERT_VALUE,
        _LEGACY_INSERT_VALUE,
        label="idempotency insert value",
    )


def upgrade() -> None:
    return # Functions only
    op.execute(fixed_command_function_sql())


def downgrade() -> None:
    op.execute(legacy_command_function_sql())
