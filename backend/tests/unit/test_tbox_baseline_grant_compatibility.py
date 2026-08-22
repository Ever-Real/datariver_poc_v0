from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = ROOT / "scripts/generate_initial_migration.py"
MIGRATION_0001_PATH = ROOT / "backend/alembic/versions/0001_initial_schema.py"
MIGRATION_0063_PATH = ROOT / "backend/alembic/versions/0063_ontology_builder_and_ingestion_jobs.py"
MIGRATION_0098_PATH = ROOT / "backend/alembic/versions/0098_tbox_baseline_grant_compatibility.py"
MIGRATION_0099_PATH = ROOT / "backend/alembic/versions/0099_tbox_lifecycle_grant_compatibility.py"


def _load_module(path: Path) -> ModuleType:
    spec = spec_from_file_location(f"test_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load module: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_is_contiguous() -> None:
    migration_0098 = _load_module(MIGRATION_0098_PATH)
    assert migration_0098.revision == "0098"
    assert migration_0098.down_revision == "0097"

    migration_0099 = _load_module(MIGRATION_0099_PATH)
    assert migration_0099.revision == "0099"
    assert migration_0099.down_revision == "0098"


def test_generator_baseline_parity() -> None:
    generator_content = GENERATOR_PATH.read_text()
    baseline_content = MIGRATION_0001_PATH.read_text()

    required_grants = [
        "GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge.tbox_draft_blocks",
        "knowledge.tbox_draft_elements TO datariver_app",
        "GRANT SELECT, INSERT, DELETE ON knowledge.tbox_classes,",
        "knowledge.tbox_properties,",
        "knowledge.tbox_relationships TO datariver_app;",
        "GRANT SELECT, INSERT, UPDATE ON knowledge.tbox_proposals TO datariver_app",
        "GRANT SELECT, INSERT ON knowledge.studio_ingestion_jobs TO datariver_app",
    ]

    for grant in required_grants:
        assert grant in generator_content, f"Missing grant in generator: {grant}"
        assert grant in baseline_content, f"Missing grant in baseline 0001: {grant}"


def test_exact_grant_surface_and_no_broader_privileges() -> None:
    migration_0063 = _load_module(MIGRATION_0063_PATH)
    migration_0098 = _load_module(MIGRATION_0098_PATH)

    # We want to make sure 0098 applies EXACTLY the same grants as 0063.
    import inspect
    import re

    source_0063 = inspect.getsource(migration_0063._install_rls_and_grants)
    source_0098 = inspect.getsource(migration_0098.upgrade)

    # Extract the grant block string
    grant_block_63 = re.search(r"DO \$grant\$(.*?)END\s*\$grant\$", source_0063, re.DOTALL)
    assert grant_block_63 is not None

    grant_block_98 = re.search(r"DO \$grant\$(.*?)END\s*\$grant\$", source_0098, re.DOTALL)
    assert grant_block_98 is not None

    assert grant_block_63.group(1).strip() == grant_block_98.group(1).strip()


def test_migration_0099_scope() -> None:
    migration_0099 = _load_module(MIGRATION_0099_PATH)
    import inspect
    import re

    source_up = inspect.getsource(migration_0099.upgrade)
    source_down = inspect.getsource(migration_0099.downgrade)

    expected_tables = {
        "knowledge.tbox_classes",
        "knowledge.tbox_properties",
        "knowledge.tbox_relationships",
    }

    # Assert upgrade scope
    assert "GRANT SELECT, INSERT, DELETE" in source_up
    assert "UPDATE" not in source_up
    assert "REVOKE" not in source_up
    for table in expected_tables:
        assert table in source_up

    # Ensure no other knowledge tables are granted
    found_tables_up = set(re.findall(r"knowledge\.[a-z0-9_]+", source_up))
    assert found_tables_up == expected_tables

    # Assert downgrade scope is no-op to preserve canonical grants
    assert "REVOKE" not in source_down
    assert "GRANT" not in source_down
    assert "pass" in source_down
