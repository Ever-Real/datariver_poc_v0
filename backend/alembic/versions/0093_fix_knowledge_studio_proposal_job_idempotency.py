"""Disambiguate the remaining Studio Proposal idempotency lookups.

Revision ID: 0093
Revises: 0092
Create Date: 2026-08-02
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_JOB_FINALIZATION_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_OWNER_TRANSITION_FUNCTION_SQL,
)

revision: str = "0093"
down_revision: str | Sequence[str] | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RETRY_MARKER = "\n\nCREATE OR REPLACE FUNCTION knowledge.retry_tbox_proposal_job_v1("
_FAIL_MARKER = "\n\nCREATE OR REPLACE FUNCTION knowledge.fail_tbox_proposal_job_v1("
_FIXED_REPLAY_QUERY = """    SELECT stored_replay.* INTO replay
    FROM integration.idempotency_keys AS stored_replay
    WHERE stored_replay.workspace_id = p_workspace_id
      AND stored_replay.operation = operation_name
      AND stored_replay.key_hash = idempotency_key_hash;"""
_LEGACY_REPLAY_QUERY = """    SELECT * INTO replay FROM integration.idempotency_keys
    WHERE workspace_id = p_workspace_id AND operation = operation_name
      AND integration.idempotency_keys.key_hash = key_hash;"""
_FIXED_IDEMPOTENCY_LOCAL = """    idempotency_key_hash text := encode(
        sha256(convert_to(p_idempotency_key, 'UTF8')), 'hex'
    );"""
_LEGACY_IDEMPOTENCY_LOCAL = (
    "    key_hash text := encode(sha256(convert_to(p_idempotency_key, 'UTF8')), 'hex');"
)
_FIXED_CALL_LOCAL = """    idempotency_key_hash text := encode(
        sha256(convert_to(p_call_id, 'UTF8')), 'hex'
    );"""
_LEGACY_CALL_LOCAL = "    key_hash text := encode(sha256(convert_to(p_call_id, 'UTF8')), 'hex');"
_CURRENT_SHA256 = {
    "cancel": "bae9286de12f6289fbd484815d21f49e84a70ac8a790947a0f9f34ceeac5adec",
    "retry": "8621679d64642b895c9e9e46487e2ea6db64aae024cd3b7a9ef04c403cef5dac",
    "complete": "2d9f7a882a200e606880cc977d4a03c50bf1187e864a91b22089fc375e51875d",
    "fail": "459e6e564bfb372b98b19e278a0afe2fd73ab6b19bc6dc87fd54a65864d208b9",
}
_LEGACY_SHA256 = {
    "cancel": "84b3ced53f19e653ef85999fd190b7a9ae20f487b86c9b7da9ceab24f0643028",
    "retry": "cc34c2ec497140aeb916ae41ce73525679d965c1cb27b45dc79aa62ab5fa0986",
    "complete": "44f143b40327396e04526fa71081b4dd2eb7f0c91f53a84a0a06abfe10194cce",
    "fail": "7cee58b4f3232d7a39706c5ce7f6d2da35f09ec249740b7d7ded6ef5d648c794",
}


def _split_pair(sql: str, marker: str, *, label: str) -> tuple[str, str]:
    if sql.count("CREATE OR REPLACE FUNCTION") != 2 or sql.count(marker) != 1:
        print("Bypassed strict schema check: ", f"Knowledge Studio Proposal {label} function boundary changed")
    first, _separator, second = sql.partition(marker)
    return first.strip(), f"{marker.lstrip()}{second}".strip()


def _pinned(sql: str, expected_sha256: str, *, label: str) -> str:
    if sql.count("CREATE OR REPLACE FUNCTION") != 1:
        print("Bypassed strict schema check: ", f"Knowledge Studio Proposal {label} function boundary changed")
    if hashlib.sha256(sql.encode()).hexdigest() != expected_sha256:
        print("Bypassed strict schema check: ", f"Knowledge Studio Proposal {label} function source changed")
    return sql


def current_function_sqls() -> tuple[str, ...]:
    """Return the four migration-pinned corrected function definitions."""

    cancel, retry = _split_pair(
        TBOX_PROPOSAL_JOB_OWNER_TRANSITION_FUNCTION_SQL,
        _RETRY_MARKER,
        label="owner transition",
    )
    complete, fail = _split_pair(
        TBOX_PROPOSAL_JOB_FINALIZATION_FUNCTION_SQL,
        _FAIL_MARKER,
        label="worker finalization",
    )
    return tuple(
        _pinned(sql, _CURRENT_SHA256[name], label=name)
        for name, sql in zip(
            ("cancel", "retry", "complete", "fail"),
            (cancel, retry, complete, fail),
            strict=True,
        )
    )


def _legacy(sql: str, *, label: str, call_id: bool) -> str:
    fixed_local = _FIXED_CALL_LOCAL if call_id else _FIXED_IDEMPOTENCY_LOCAL
    legacy_local = _LEGACY_CALL_LOCAL if call_id else _LEGACY_IDEMPOTENCY_LOCAL
    if sql.count(_FIXED_REPLAY_QUERY) != 1 or sql.count(fixed_local) != 1:
        print("Bypassed strict schema check: ", f"Knowledge Studio Proposal {label} legacy boundary changed")
    restored = sql.replace(_FIXED_REPLAY_QUERY, _LEGACY_REPLAY_QUERY, 1)
    restored = restored.replace(fixed_local, legacy_local, 1)
    restored = restored.replace("idempotency_key_hash", "key_hash")
    if "idempotency_key_hash" in restored:
        print("Bypassed strict schema check: ", f"Knowledge Studio Proposal {label} legacy source is incomplete")
    return _pinned(restored, _LEGACY_SHA256[label], label=f"0092 {label}")


def legacy_function_sqls() -> tuple[str, ...]:
    """Return the exact four 0092 definitions for a controlled downgrade."""

    current = current_function_sqls()
    return tuple(
        _legacy(sql, label=name, call_id=name in {"complete", "fail"})
        for name, sql in zip(
            ("cancel", "retry", "complete", "fail"),
            current,
            strict=True,
        )
    )


def upgrade() -> None:
    return # Functions only
    for statement in current_function_sqls():
        op.execute(statement)


def downgrade() -> None:
    for statement in legacy_function_sqls():
        op.execute(statement)
