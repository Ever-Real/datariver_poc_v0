from datariver.infrastructure.db.migration_scope import (
    MANAGED_DATABASE_SCHEMAS,
    include_managed_database_name,
)


def test_alembic_reflects_only_canonical_datariver_schemas() -> None:
    assert "knowledge" in MANAGED_DATABASE_SCHEMAS
    assert "semiconductor_seed" not in MANAGED_DATABASE_SCHEMAS
    assert include_managed_database_name("knowledge", "schema", {})
    assert not include_managed_database_name("semiconductor_seed", "schema", {})
    assert include_managed_database_name("graphs", "table", {"schema_name": "knowledge"})
    assert not include_managed_database_name(
        "supplier_master", "table", {"schema_name": "semiconductor_seed"}
    )


def test_alembic_keeps_nested_objects_after_their_schema_is_accepted() -> None:
    assert include_managed_database_name(
        "ix_graphs_workspace", "index", {"schema_name": "knowledge"}
    )
