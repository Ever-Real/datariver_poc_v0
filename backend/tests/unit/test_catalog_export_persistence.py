from __future__ import annotations

from pathlib import Path

from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


def test_catalog_export_migration_is_owner_scoped_and_fail_closed() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0014_catalog_exports.py").read_text(
        encoding="utf-8"
    )

    assert REQUIRED_DATABASE_REVISION == "0039"
    assert "ALTER TABLE catalog.export_requests FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY workspace_isolation ON catalog.export_requests" in migration
    assert "CREATE POLICY catalog_export_owner_select" in migration
    assert "AS RESTRICTIVE FOR SELECT" in migration
    assert "current_setting('app.subject_id', true)" in migration
    assert "classification_ceiling BETWEEN 0 AND 2" in migration
    assert "source_projection_version >= 0" in migration
    assert "request_hash ~ '^[0-9a-f]{64}$'" in migration
    assert "ck_export_requests_artifact_shape" in migration
    assert "ck_export_requests_classification_policy_binding_shape" in migration
    assert "ON DELETE CASCADE" not in migration
    assert "BYPASSRLS" not in migration
    assert "GRANT SELECT, INSERT ON catalog.export_requests TO datariver_app" in migration
    assert "GRANT UPDATE ON catalog.export_requests" not in migration
    assert "GRANT DELETE ON catalog.export_requests" not in migration


def test_initial_schema_generator_preserves_catalog_export_security_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    for source in (generator, initial):
        assert "CREATE POLICY catalog_export_owner_select" in source
        assert "AS RESTRICTIVE FOR SELECT" in source
        assert "GRANT SELECT, INSERT ON catalog.export_requests TO datariver_app" in source
        assert "GRANT UPDATE ON catalog.export_requests" not in source
        assert "GRANT DELETE ON catalog.export_requests" not in source
