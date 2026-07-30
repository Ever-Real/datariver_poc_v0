from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric

from datariver.infrastructure.db import models as _models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0068_catalog_profile_projection.py"
PHASE1_MIGRATION = ROOT / "backend/alembic/versions/0067_quality_control_plane.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_metadata_is_tenant_bound_and_immutable_by_shape() -> None:
    assert REQUIRED_DATABASE_REVISION == "0072"
    snapshots = Base.metadata.tables["catalog.asset_profile_snapshots"]
    metrics = Base.metadata.tables["catalog.column_profile_metrics"]
    for table in (snapshots, metrics):
        assert "workspace_id" in table.c
        assert all(
            (element.ondelete or "").upper() != "CASCADE"
            for constraint in table.foreign_key_constraints
            for element in constraint.elements
        )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_column_profile_metrics_snapshot_binding"
        and "workspace_id" in constraint.column_keys
        and "profile_hold_hash" in constraint.column_keys
        for constraint in metrics.constraints
    )
    assert isinstance(metrics.c.null_proportion.type, Numeric)
    assert isinstance(metrics.c.unique_proportion.type, Numeric)
    snapshot_checks = "\n".join(
        str(constraint.sqltext)
        for constraint in snapshots.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "QUALITY_PROFILE" in snapshot_checks
    assert "PARTITION" in snapshot_checks
    assert "provenance_fingerprint" in snapshot_checks


def test_0068_pins_profile_security_and_retention_v4() -> None:
    migration = _load(MIGRATION, "catalog_profile_0068_unit")
    assert migration.revision == "0068"
    assert migration.down_revision == "0067"
    assert migration._schema_contract_hash() == migration._PROFILE_SCHEMA_CONTRACT_HASH
    combined = "\n".join(
        (
            migration._RETENTION_V4_SQL,
            migration._RESOLVER_V4_SQL,
            migration._PROFILE_ROLE_ASSERTION_SQL,
            migration._PROFILE_FUNCTION_SQL,
            migration._PROFILE_RLS_AND_GRANTS_SQL,
        )
    )
    assert "POLICY_BOOK_V4" in combined
    assert "QUALITY_PROFILE" in combined
    assert "PROFILE_SNAPSHOT" in combined
    assert "session_user = 'datariver_catalog_profile'" in combined
    assert "FORCE ROW LEVEL SECURITY" in combined
    assert "GRANT EXECUTE ON FUNCTION catalog.read_profile_target_v1" in combined
    assert "GRANT EXECUTE ON FUNCTION catalog.project_asset_profile_v1" in combined
    assert "GRANT INSERT" not in migration._PROFILE_RLS_AND_GRANTS_SQL
    assert "sampleValues" not in combined
    assert "raw_partition" not in combined


def test_0068_downgrade_and_canonical_generator_are_ordered() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    generator = GENERATOR.read_text(encoding="utf-8")
    assert "0068 downgrade refuses non-empty immutable Profile evidence" in source
    assert "0068 downgrade refuses governed Profile retention evidence" in source
    assert source.index("DROP FUNCTION catalog.project_asset_profile_v1") < source.index(
        "table.drop(bind=bind"
    )
    assert "_load_catalog_profile_phase2_revision" in generator
    assert generator.index("_PROFILE_FUNCTION_SQL") < generator.index("return ops.UpgradeOps")
    assert generator.index("DROP FUNCTION catalog.project_asset_profile_v1") < generator.index(
        "for table in reversed(Base.metadata.sorted_tables)"
    )


def test_phase1_historical_schema_contract_stays_frozen() -> None:
    phase1 = _load(PHASE1_MIGRATION, "quality_0067_frozen_unit")
    assert phase1._schema_contract_hash() == phase1._QUALITY_SCHEMA_CONTRACT_HASH
