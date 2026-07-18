from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint

from datariver.infrastructure.db.models.governance import ManualMetadataSubmissionModel
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


def test_manual_metadata_submission_is_workspace_scoped_immutable_receipt_metadata() -> None:
    table = ManualMetadataSubmissionModel.__table__
    assert {
        "workspace_id",
        "asset_id",
        "requester_id",
        "source_version",
        "serial_number",
        "payload",
        "bucket",
        "object_key",
        "csv_sha256",
        "csv_size_bytes",
        "row_count",
        "state",
        "version",
    } <= set(table.c.keys())
    assert "secret" not in set(table.c.keys())
    names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_manual_metadata_submissions_serial_number_positive",
        "ck_manual_metadata_submissions_csv_sha256_valid",
        "ck_manual_metadata_submissions_state_vocabulary",
        "ck_manual_metadata_submissions_payload_object",
    } <= names


def test_manual_metadata_migration_has_rls_immutable_evidence_and_private_storage_boundary() -> (
    None
):
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0023_manual_metadata_submissions.py").read_text(
        encoding="utf-8"
    )
    assert REQUIRED_DATABASE_REVISION == "0027"
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "reject_manual_metadata_payload_mutation" in migration
    assert "GRANT SELECT, INSERT, UPDATE ON governance.manual_metadata_submissions" in migration
    assert "DROP TABLE" not in migration
