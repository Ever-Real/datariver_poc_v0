import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0097_managed_studio_intents.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_managed_studio_0097", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0097_targets_canonical_tables() -> None:
    from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

    assert REQUIRED_DATABASE_REVISION == "0101", (
        "Packaged runtime readiness constant must match migration head"
    )

    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0097"' in source
    assert 'down_revision: str | Sequence[str] | None = "0096"' in source

    # Must target canonical tables, not the old SQLAlchemy class names
    assert "knowledge_studio_draft" not in source
    assert "knowledge_studio_release" not in source

    # Should use correct target schemas and tables
    assert '"studio_drafts"' in source
    assert '"studio_releases"' in source
    assert 'schema="knowledge"' in source
