from __future__ import annotations

from pathlib import Path

from datariver.infrastructure.db.identity_profile_sql import (
    IDENTITY_PROFILE_UPDATE_FUNCTION_SQL,
)


def test_identity_profile_function_is_fixed_and_rechecks_both_human_boundaries() -> None:
    sql = IDENTITY_PROFILE_UPDATE_FUNCTION_SQL

    assert "SECURITY DEFINER" in sql
    assert "current_setting('app.subject_id'" in sql
    assert "current_setting('app.workspace_id'" in sql
    assert "security-administrators" in sql
    assert "admin.manage" in sql
    assert "p_expected_membership_version" in sql
    assert "FOR UPDATE OF membership, subject" in sql
    assert "%ROWTYPE" not in sql
    assert "access_expires_at <= transaction_timestamp()" in sql
    assert "SERVICE_ACCOUNT" in sql
    assert "EXECUTE " not in sql
    assert "password" not in sql.lower()


def test_identity_profile_migration_and_initial_baseline_have_execute_only_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0083_governed_identity_profile_administration.py"
    ).read_text(encoding="utf-8")
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "0082"' in migration
    assert "IDENTITY_PROFILE_UPDATE_FUNCTION_SQL" in migration
    assert "IDENTITY_PROFILE_UPDATE_SIGNATURE" in migration
    assert "update_workspace_identity_profile" in initial
    for source in (migration, initial):
        assert "REVOKE ALL ON FUNCTION" in source
        assert "GRANT EXECUTE ON FUNCTION" in source
    assert "GRANT INSERT ON iam.subjects" not in initial
    assert "GRANT INSERT ON iam.workspace_memberships" not in initial
