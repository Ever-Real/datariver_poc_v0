from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table

from datariver.infrastructure.db.models.governance import RegistrationContentBindingModel
from datariver.infrastructure.db.models.integration import (
    ObjectManifestModel,
    UploadPreparationJobModel,
    UploadPreparationReceiptModel,
    UploadRegistrationCandidateModel,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


def _check_names(table: Table) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and isinstance(constraint.name, str)
    }


def test_typed_bulk_models_keep_profile_rows_and_provider_coordinates_server_owned() -> None:
    manifest = cast(Table, ObjectManifestModel.__table__)
    jobs = cast(Table, UploadPreparationJobModel.__table__)
    receipts = cast(Table, UploadPreparationReceiptModel.__table__)
    candidates = cast(Table, UploadRegistrationCandidateModel.__table__)
    bindings = cast(Table, RegistrationContentBindingModel.__table__)

    assert "content_profile" in manifest.c
    assert "ck_object_manifests_content_profile_allowlist" in _check_names(manifest)
    assert "ck_upload_preparation_jobs_lease_shape" in _check_names(jobs)
    assert "ck_upload_preparation_receipts_accepted_source_sha256_equal" in _check_names(receipts)
    assert "ck_upload_registration_candidates_candidate_kind_allowlist" in _check_names(candidates)
    assert "ck_upload_registration_candidates_submitted_identity_evidence_shape" in _check_names(
        candidates
    )
    assert "ck_registration_content_bindings_candidate_hash_valid" in _check_names(bindings)

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
    } == set(candidates.c.keys())
    assert {
        "target_ref",
        "aspect_name",
        "classification",
        "after_document",
        "bucket",
        "object_key",
    }.isdisjoint(candidates.c.keys())


def test_typed_bulk_relationships_carry_workspace_and_do_not_cascade() -> None:
    tables = (
        cast(Table, UploadPreparationJobModel.__table__),
        cast(Table, UploadPreparationReceiptModel.__table__),
        cast(Table, UploadRegistrationCandidateModel.__table__),
        cast(Table, RegistrationContentBindingModel.__table__),
    )
    for table in tables:
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            mappings = {
                (element.parent.name, element.column.name) for element in constraint.elements
            }
            assert ("workspace_id", "workspace_id") in mappings
            assert constraint.ondelete == "RESTRICT"


def test_typed_bulk_bindings_pin_exact_source_candidate_and_change_item() -> None:
    receipts = cast(Table, UploadPreparationReceiptModel.__table__)
    bindings = cast(Table, RegistrationContentBindingModel.__table__)

    receipt_foreign_keys = {
        constraint.name: {
            (element.parent.name, element.column.name) for element in constraint.elements
        }
        for constraint in receipts.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert receipt_foreign_keys["fk_upload_prep_receipts_source_evidence"] == {
        ("workspace_id", "workspace_id"),
        ("preparation_job_id", "id"),
        ("upload_id", "upload_id"),
        ("manifest_version", "source_manifest_version"),
        ("source_sha256", "source_sha256"),
        ("content_profile", "content_profile"),
        ("configuration_hash", "configuration_hash"),
    }

    binding_foreign_keys = {
        constraint.name: {
            (element.parent.name, element.column.name) for element in constraint.elements
        }
        for constraint in bindings.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert binding_foreign_keys["fk_reg_content_bindings_candidate_content"] == {
        ("workspace_id", "workspace_id"),
        ("candidate_id", "id"),
        ("candidate_hash", "candidate_hash"),
    }
    assert binding_foreign_keys["fk_reg_content_bindings_request_item"] == {
        ("workspace_id", "workspace_id"),
        ("change_request_id", "change_request_id"),
        ("change_item_id", "id"),
    }


def test_typed_bulk_migration_forces_rls_and_limits_mutation_grants() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0016_typed_bulk_registration_foundation.py"
    ).read_text(encoding="utf-8")

    assert REQUIRED_DATABASE_REVISION == "0024"
    assert "_enable_workspace_rls(schema, table)" in migration
    for schema, table in (
        ("integration", "upload_preparation_jobs"),
        ("integration", "upload_preparation_receipts"),
        ("integration", "upload_registration_candidates"),
        ("governance", "registration_content_bindings"),
    ):
        assert f'("{schema}", "{table}")' in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY workspace_isolation" in migration
    assert (
        "GRANT SELECT, INSERT ON integration.upload_preparation_jobs TO datariver_app" in migration
    )
    assert "GRANT SELECT ON integration.upload_preparation_receipts" in migration
    assert "GRANT SELECT, INSERT ON governance.registration_content_bindings" in migration
    assert "reject_object_manifest_content_profile_change" in migration
    assert (
        "Compatibility bridge: regenerated 0001 owns the canonical typed BULK schema" in migration
    )
    assert "TO datariver_upload" not in migration
    assert "GRANT UPDATE ON integration.upload_preparation_receipts" not in migration
    assert "GRANT UPDATE ON integration.upload_registration_candidates" not in migration
    assert "GRANT DELETE ON integration.upload_" not in migration
    assert "BYPASSRLS" not in migration


def test_candidate_identity_evidence_migration_preserves_legacy_and_requires_v2() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0017_candidate_submitted_identity_evidence.py"
    ).read_text(encoding="utf-8")

    assert 'server_default="LEGACY_V1"' in migration
    assert "server_default=V2" in migration
    assert "submitted_identity_hash ~ '^[0-9a-f]{64}$'" in migration
    assert "new upload registration candidates require V2 evidence" in migration
    assert "upload registration candidate evidence is immutable" in migration
    assert (
        "Compatibility bridge: regenerated 0001 owns the canonical candidate evidence schema"
        in migration
    )
    assert "GRANT" not in migration


def test_initial_schema_generator_preserves_typed_bulk_role_boundary() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")
    for source in (generator, initial):
        assert "integration.upload_preparation_receipts" in source
        assert "integration.upload_registration_candidates" in source
        assert "governance.registration_content_bindings" in source
        assert "reject_object_manifest_content_profile_change" in source
        assert "upload_preparation_jobs TO datariver_upload" not in source
        assert "GRANT DELETE ON integration.upload_" not in source
