from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from datariver.infrastructure.db.models.catalog import CatalogVocabularyEntryModel
from datariver.infrastructure.db.models.governance import (
    ChangeItemModel,
    RegistrationMetadataContentBindingModel,
)
from datariver.infrastructure.db.models.integration import (
    CatalogMetadataCandidateModel,
    CatalogMetadataCandidateRowModel,
    CatalogMetadataRowModel,
    ObjectManifestModel,
    UploadPreparationJobModel,
    UploadPreparationReceiptModel,
    UploadRegistrationCandidateModel,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


def _load_migration() -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    path = root / "backend/alembic/versions/0051_typed_catalog_metadata_evidence.py"
    spec = spec_from_file_location("test_0051_typed_catalog_metadata_evidence", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load migration: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_sql(table: Table) -> str:
    return "\n".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def _foreign_keys(table: Table) -> dict[str, set[tuple[str, str]]]:
    return {
        cast(str, constraint.name): {
            (element.parent.name, element.column.name) for element in constraint.elements
        }
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _unique_columns(table: Table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_new_profiles_extend_allowlists_without_changing_v2_candidate_shape() -> None:
    manifest = cast(Table, ObjectManifestModel.__table__)
    jobs = cast(Table, UploadPreparationJobModel.__table__)
    receipts = cast(Table, UploadPreparationReceiptModel.__table__)
    legacy_candidates = cast(Table, UploadRegistrationCandidateModel.__table__)

    for table in (manifest, jobs, receipts):
        sql = _check_sql(table)
        assert "CATALOG_METADATA_ROWS_CSV_V1" in sql
        assert "CATALOG_METADATA_ROWS_XLSX_V1" in sql
    assert "DATASET_DESCRIPTION_CSV_V1" in _check_sql(receipts)
    assert "DATASET_DESCRIPTION_XLSX_V1" in _check_sql(receipts)
    assert {
        "id",
        "workspace_id",
        "receipt_id",
        "ordinal",
        "target_asset_id",
        "candidate_kind",
        "proposed_description",
        "evidence_version",
        "submitted_platform",
        "submitted_database_name",
        "submitted_schema_name",
        "submitted_table_name",
        "submitted_identity_hash",
        "candidate_hash",
        "created_at",
    } == set(legacy_candidates.c.keys())


def test_catalog_metadata_rows_are_typed_and_never_store_provider_payloads() -> None:
    rows = cast(Table, CatalogMetadataRowModel.__table__)
    assert {
        "id",
        "workspace_id",
        "receipt_id",
        "ordinal",
        "content_profile",
        "evidence_version",
        "record_kind",
        "aspect_name",
        "target_asset_id",
        "submitted_platform",
        "submitted_database_name",
        "submitted_schema_name",
        "submitted_table_name",
        "field_path",
        "operation",
        "value_text",
        "controlled_ref_id",
        "controlled_kind",
        "submitted_identity_hash",
        "semantic_target_hash",
        "row_hash",
        "created_at",
    } == set(rows.c.keys())
    assert {
        "provider_ref",
        "target_ref",
        "after_document",
        "bucket",
        "object_key",
        "credential",
    }.isdisjoint(rows.c.keys())
    check_sql = _check_sql(rows)
    for value in (
        "TABLE_DESCRIPTION",
        "COLUMN_DESCRIPTION",
        "DATASET_DOMAIN",
        "DATASET_TERM",
        "DATASET_TAG",
        "CATALOG_METADATA_CANDIDATE_V3",
        "TABLE_DESCRIPTION' AND aspect_name = 'datasetProperties",
        "COLUMN_DESCRIPTION' AND aspect_name = 'schemaMetadata",
        "DATASET_DOMAIN' AND aspect_name = 'domains",
        "DATASET_TERM' AND aspect_name = 'glossaryTerms",
        "DATASET_TAG' AND aspect_name = 'globalTags",
        "controlled_ref_id IS NULL",
        "controlled_ref_id IS NOT NULL",
    ):
        assert value in check_sql
    assert (
        "workspace_id",
        "receipt_id",
        "semantic_target_hash",
    ) in _unique_columns(rows)


def test_vocabulary_and_rows_bind_workspace_kind_and_server_only_provider_ref() -> None:
    vocabulary = cast(Table, CatalogVocabularyEntryModel.__table__)
    rows = cast(Table, CatalogMetadataRowModel.__table__)

    assert "provider_ref" in vocabulary.c
    assert "last_seen_sync_id" in vocabulary.c
    assert "provider_ref" not in rows.c
    assert ("workspace_id", "id", "kind") in _unique_columns(vocabulary)
    assert (
        "workspace_id",
        "kind",
        "provider_ref",
    ) in _unique_columns(vocabulary)
    assert _foreign_keys(rows)["fk_catalog_metadata_rows_vocabulary"] == {
        ("workspace_id", "workspace_id"),
        ("controlled_ref_id", "id"),
        ("controlled_kind", "kind"),
    }
    for constraint in rows.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            assert constraint.ondelete == "RESTRICT"


def test_candidate_membership_pins_same_receipt_profile_and_ordered_hashes() -> None:
    candidates = cast(Table, CatalogMetadataCandidateModel.__table__)
    membership = cast(Table, CatalogMetadataCandidateRowModel.__table__)

    candidate_sql = _check_sql(candidates)
    assert "record_kind" in candidates.c
    assert "CATALOG_METADATA_CANDIDATE_V3" in candidate_sql
    for record_kind, candidate_kind, aspect_name in (
        ("TABLE_DESCRIPTION", "TABLE_DESCRIPTION_UPDATE", "datasetProperties"),
        ("COLUMN_DESCRIPTION", "COLUMN_DESCRIPTION_UPDATE", "schemaMetadata"),
        ("DATASET_DOMAIN", "DATASET_DOMAIN_UPDATE", "domains"),
        ("DATASET_TERM", "DATASET_TERM_ADD", "glossaryTerms"),
        ("DATASET_TAG", "DATASET_TAG_ADD", "globalTags"),
    ):
        assert record_kind in candidate_sql
        assert candidate_kind in candidate_sql
        assert aspect_name in candidate_sql
    assert "last_row_ordinal BETWEEN first_row_ordinal AND 10000" in candidate_sql
    assert "last_row_ordinal - first_row_ordinal + 1 = row_count" not in candidate_sql
    assert (
        "workspace_id",
        "receipt_id",
        "target_asset_id",
        "aspect_name",
    ) in _unique_columns(candidates)
    assert _foreign_keys(membership)["fk_catalog_metadata_candidate_rows_candidate"] == {
        ("workspace_id", "workspace_id"),
        ("receipt_id", "receipt_id"),
        ("candidate_id", "id"),
        ("content_profile", "content_profile"),
        ("candidate_hash", "candidate_hash"),
    }
    assert _foreign_keys(membership)["fk_catalog_metadata_candidate_rows_row"] == {
        ("workspace_id", "workspace_id"),
        ("receipt_id", "receipt_id"),
        ("row_id", "id"),
        ("content_profile", "content_profile"),
        ("row_hash", "row_hash"),
    }


def test_metadata_binding_pins_candidate_and_exact_change_item_contract() -> None:
    items = cast(Table, ChangeItemModel.__table__)
    bindings = cast(Table, RegistrationMetadataContentBindingModel.__table__)

    assert "item_contract_hash" in items.c
    assert (
        "workspace_id",
        "change_request_id",
        "id",
        "aspect_name",
        "before_hash",
        "after_hash",
        "item_contract_hash",
    ) in _unique_columns(items)
    assert _foreign_keys(bindings)["fk_registration_metadata_bindings_candidate_content"] == {
        ("workspace_id", "workspace_id"),
        ("candidate_id", "id"),
        ("content_profile", "content_profile"),
        ("candidate_kind", "candidate_kind"),
        ("aspect_name", "aspect_name"),
        ("candidate_hash", "candidate_hash"),
    }
    assert _foreign_keys(bindings)["fk_registration_metadata_bindings_request_item"] == {
        ("workspace_id", "workspace_id"),
        ("change_request_id", "change_request_id"),
        ("change_item_id", "id"),
        ("aspect_name", "aspect_name"),
        ("before_hash", "before_hash"),
        ("after_hash", "after_hash"),
        ("item_contract_hash", "item_contract_hash"),
    }
    assert {
        ("workspace_id", "candidate_id"),
        ("workspace_id", "change_request_id"),
        ("workspace_id", "change_item_id"),
    } <= _unique_columns(bindings)
    binding_sql = _check_sql(bindings)
    for candidate_kind, aspect_name in (
        ("TABLE_DESCRIPTION_UPDATE", "datasetProperties"),
        ("COLUMN_DESCRIPTION_UPDATE", "schemaMetadata"),
        ("DATASET_DOMAIN_UPDATE", "domains"),
        ("DATASET_TERM_ADD", "glossaryTerms"),
        ("DATASET_TAG_ADD", "globalTags"),
    ):
        assert candidate_kind in binding_sql
        assert aspect_name in binding_sql


def test_persistence_hash_contract_is_server_authored_and_membership_ordered() -> None:
    root = Path(__file__).resolve().parents[3]
    parser = (
        root / "backend/src/datariver/application/catalog_metadata_upload_parser.py"
    ).read_text(encoding="utf-8")
    rows = cast(Table, CatalogMetadataRowModel.__table__)
    candidates = cast(Table, CatalogMetadataCandidateModel.__table__)
    membership = cast(Table, CatalogMetadataCandidateRowModel.__table__)

    assert '_ROW_HASH_CONTRACT = "catalog-metadata-row-v3"' in parser
    assert '"ordered_row_hashes": list(row_hashes)' in parser
    assert "semantic_key=semantic_key" in parser
    assert "catalog_metadata_submitted_identity_hash(" in parser
    assert {"semantic_target_hash", "submitted_identity_hash", "row_hash"} <= set(rows.c.keys())
    assert {"submitted_identity_hash", "row_root_hash", "candidate_hash"} <= set(
        candidates.c.keys()
    )
    assert {"member_ordinal", "source_ordinal", "row_hash"} <= set(membership.c.keys())


@pytest.mark.parametrize("existing", (0, 7))
def test_0051_upgrade_creates_or_reasserts_complete_contract(
    monkeypatch: pytest.MonkeyPatch,
    existing: int,
) -> None:
    migration = _load_migration()
    monkeypatch.setattr(migration, "_artifact_count", lambda: existing)
    calls: list[str] = []
    names = (
        "_create_schema",
        "_replace_profile_allowlists",
        "_install_rls",
        "_install_immutability",
        "_install_grants",
        "_assert_contract",
    )
    for name in names:
        monkeypatch.setattr(migration, name, lambda name=name: calls.append(name))

    migration.upgrade()

    assert calls == list(names if existing == 0 else names[1:])


def test_0051_upgrade_and_downgrade_fail_closed_on_partial_or_durable_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration()
    monkeypatch.setattr(migration, "_artifact_count", lambda: 3)
    with pytest.raises(RuntimeError, match="partially present"):
        migration.upgrade()

    monkeypatch.setattr(migration, "_artifact_count", lambda: 7)
    monkeypatch.setattr(migration, "_new_evidence_count", lambda: 1)
    with pytest.raises(RuntimeError, match="cannot be downgraded"):
        migration.downgrade()


def test_0051_migration_is_forced_rls_append_only_and_least_privilege() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0051_typed_catalog_metadata_evidence.py"
    ).read_text(encoding="utf-8")

    assert REQUIRED_DATABASE_REVISION == "0052"
    assert 'down_revision: str | Sequence[str] | None = "0050"' in migration
    for schema, table in (
        ("catalog", "vocabulary_entries"),
        ("catalog", "vocabulary_sync_runs"),
        ("integration", "catalog_metadata_rows"),
        ("integration", "catalog_metadata_candidates"),
        ("integration", "catalog_metadata_candidate_rows"),
        ("governance", "registration_metadata_content_bindings"),
    ):
        assert f'("{schema}", "{table}")' in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY workspace_isolation" in migration
    assert "reject_catalog_metadata_evidence_mutation" in migration
    assert "reject_registration_metadata_binding_mutation" in migration
    assert "guard_vocabulary_entry_mutation" in migration
    assert "REVOKE ALL PRIVILEGES" in migration
    assert "FROM datariver_upload" in migration
    assert "application role has overbroad evidence mutation privileges" in migration
    assert "typed catalog metadata V3 evidence contract is invalid" in migration
    assert "ck_catalog_metadata_rows_record_kind_aspect_contract" in migration
    assert "ck_catalog_metadata_candidates_record_candidate_aspect_contract" in migration
    assert "ck_registration_metadata_content_bindings_candidate_aspect" in migration
    assert "CATALOG_METADATA_ASPECT_GROUP" not in migration
    assert "CATALOG_METADATA_ROW_V1" not in migration
    assert "CATALOG_METADATA_CANDIDATE_V1" not in migration
    assert "Revision 0051 cannot be downgraded" in migration
