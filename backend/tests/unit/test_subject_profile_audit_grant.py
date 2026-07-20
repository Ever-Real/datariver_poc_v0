from __future__ import annotations

from pathlib import Path


def test_subject_profile_audit_update_grant_covers_timestamp_mixin() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    bridge = (
        root / "backend/alembic/versions/0030_subject_profile_audit_updated_at_grant.py"
    ).read_text(encoding="utf-8")

    expected_grant = "GRANT UPDATE (email, last_login_at, last_login_ip, updated_at)"
    assert expected_grant in generator
    assert expected_grant in bridge
