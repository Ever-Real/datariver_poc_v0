import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_0100 = ROOT / "backend/alembic/versions/0100_k9_intranet_distinct_principal.py"
MIGRATION_0001 = ROOT / "backend/alembic/versions/0001_initial_schema.py"


def _load_migration(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0100_upgrade_downgrade_parity() -> None:
    mod = _load_migration(MIGRATION_0100)
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")

    source_0100 = MIGRATION_0100.read_text(encoding="utf-8")

    # EXACT K9 pass assertions (no partial relaxations, extras/duplicates)
    assert "OR (membership.subject_id = {K9_CHECKER}" in source_0100

    upgrade_sql = mod._reviewer_sql("test_draft", upgrade=True)
    downgrade_sql = mod._reviewer_sql("test_draft", upgrade=False)

    # Normalize whitespace for exact SQL string matching
    normalized_sql = " ".join(upgrade_sql.split())

    # Exact JSONB cardinality checks
    assert (
        "jsonb_array_length(COALESCE(membership.attributes -> 'groups', '[]'::jsonb)) = 2"
        in normalized_sql
    )
    assert (
        "jsonb_array_length(COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)) = 3"
        in normalized_sql
    )
    assert (
        "jsonb_array_length(COALESCE(membership.attributes -> 'allowed_domain_ids', "
        "'[]'::jsonb)) = 1" in normalized_sql
    )
    assert "f14fa2ce-e5f2-beee-5eea-5e77be5754ff" in normalized_sql

    # upgrade includes the K9 override predicate
    assert "00000000-0000-4000-8000-000000000111" in upgrade_sql
    assert "jsonb_array_length" in upgrade_sql

    # downgrade restores 0099 human-only semantics
    assert "00000000-0000-4000-8000-000000000111" not in downgrade_sql
    assert "SERVICE_ACCOUNT" in downgrade_sql

    # self-approval reject
    assert "membership.subject_id <> test_draft.author_id" in upgrade_sql

    # legacy human pass
    assert "COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'" in upgrade_sql


def test_0001_baseline_parity() -> None:
    source_0001 = MIGRATION_0001.read_text(encoding="utf-8")

    # Check that 0001 has the exact same K9 override string
    normalized_0001 = " ".join(source_0001.replace("\\'", "'").replace('\\"', '"').split())
    assert "00000000-0000-4000-8000-000000000111" in normalized_0001
    assert (
        "jsonb_array_length(COALESCE(membership.attributes -> 'groups', '[]'::jsonb)) = 2"
        in normalized_0001
    )
    assert (
        "jsonb_array_length(COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)) = 3"
        in normalized_0001
    )
    assert (
        "jsonb_array_length(COALESCE(membership.attributes -> 'allowed_domain_ids', "
        "'[]'::jsonb)) = 1" in normalized_0001
    )
    assert "f14fa2ce-e5f2-beee-5eea-5e77be5754ff" in normalized_0001
