from __future__ import annotations

import inspect
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Table

from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogSyncRunModel,
)


def _migration() -> dict[str, object]:
    return runpy.run_path(
        str(
            Path(__file__).parents[2]
            / "alembic"
            / "versions"
            / "0045_bounded_catalog_projection.py"
        )
    )


def _check_names(table: Table) -> set[str | None]:
    return {
        str(constraint.name) if constraint.name is not None else None
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_0045_declares_the_same_projection_and_sync_checks_as_metadata() -> None:
    migration = _migration()
    projection_checks = cast(dict[str, str], migration["_CONSTRAINTS"])
    sync_checks = cast(dict[str, str], migration["_SYNC_CONSTRAINTS"])

    assert set(projection_checks) <= _check_names(cast(Table, AssetProjectionModel.__table__))
    assert set(sync_checks) <= _check_names(cast(Table, CatalogSyncRunModel.__table__))
    assert set(cast(tuple[str, ...], migration["_PROVENANCE_COLUMNS"])) <= {
        column.name for column in AssetProjectionModel.__table__.columns
    }


def test_0045_preserves_identity_and_abandons_unprovable_active_syncs() -> None:
    migration = _migration()
    upgrade_source = inspect.getsource(cast(Callable[[], None], migration["upgrade"]))

    assert "Invalid external URNs must be corrected in DataHub" in upgrade_source
    assert "SET state = 'ABANDONED'" in upgrade_source
    assert "expected_total IS NULL" in upgrade_source
    assert "left(external_urn" not in upgrade_source


def test_0045_array_normalization_is_string_only_bounded_and_provenance_bearing() -> None:
    migration = _migration()
    statements = cast(dict[str, object], migration["_ARRAY_TRUNCATION_STATEMENTS"])

    assert set(statements) == {"tags", "glossary_terms", "column_names"}
    for statement in statements.values():
        sql = str(statement)
        assert "jsonb_typeof(entry.value) = 'string'" in sql
        assert "entry.ordinality <= :maximum_items" in sql
        assert "_truncated = true" in sql
