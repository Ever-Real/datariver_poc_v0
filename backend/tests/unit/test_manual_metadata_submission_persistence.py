from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import CheckConstraint, Table

from datariver.infrastructure.db.models.governance import (
    ManualMetadataApplyAttemptModel,
    ManualMetadataAspectReportModel,
    ManualMetadataSubmissionModel,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.interfaces.http.schemas import ManualMetadataSubmissionRequest


def test_manual_metadata_submission_is_workspace_scoped_immutable_receipt_metadata() -> None:
    table = cast(Table, ManualMetadataSubmissionModel.__table__)
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
        "next_attempt_at",
        "lease_epoch",
        "lease_token_hash",
        "lease_owner_id",
        "lease_started_at",
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
        "ck_manual_metadata_submissions_retry_schedule_shape",
        "ck_manual_metadata_submissions_lease_shape",
    } <= names


def test_manual_apply_attempts_and_aspect_reports_are_typed_fenced_evidence() -> None:
    attempts = cast(Table, ManualMetadataApplyAttemptModel.__table__)
    reports = cast(Table, ManualMetadataAspectReportModel.__table__)
    assert {
        "submission_id",
        "attempt_no",
        "lease_epoch",
        "lease_token_hash",
        "worker_subject_id",
        "state",
        "report_root_hash",
    } <= set(attempts.c.keys())
    assert {
        "attempt_id",
        "aspect_name",
        "aspect_ordinal",
        "outcome",
        "before_hash",
        "expected_hash",
        "observed_hash",
        "write_attempted",
    } <= set(reports.c.keys())
    attempt_checks = {
        constraint.name
        for constraint in attempts.constraints
        if isinstance(constraint, CheckConstraint)
    }
    report_checks = {
        constraint.name
        for constraint in reports.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_manual_metadata_apply_attempts_terminal_shape" in attempt_checks
    assert "ck_manual_metadata_aspect_reports_verified_outcome_shape" in report_checks


def test_manual_metadata_migration_has_rls_immutable_evidence_and_private_storage_boundary() -> (
    None
):
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0023_manual_metadata_submissions.py").read_text(
        encoding="utf-8"
    )
    assert REQUIRED_DATABASE_REVISION == "0072"
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "reject_manual_metadata_payload_mutation" in migration
    assert "GRANT SELECT, INSERT, UPDATE ON governance.manual_metadata_submissions" in migration
    assert "DROP TABLE" not in migration

    controls = (
        root / "backend/alembic/versions/0046_registration_execution_controls.py"
    ).read_text(encoding="utf-8")
    assert "reject_manual_apply_attempt_mutation" in controls
    assert "reject_manual_aspect_report_mutation" in controls
    assert "BEFORE INSERT OR UPDATE OR DELETE ON governance.manual_metadata_apply_attempts" in (
        controls
    )
    assert "manual apply attempts must start as RUNNING" in controls
    assert "OLD.provider_source_version <> NEW.provider_source_version" in controls
    assert "pg_get_expr(" in controls
    assert "state::text = ''APPLYING''::text" in controls
    assert "'governance.manual_metadata_submissions'," in controls
    assert "FORCE ROW LEVEL SECURITY" in controls
    assert "next_attempt_at" in controls


def test_manual_metadata_http_schema_bounds_each_controlled_reference() -> None:
    with pytest.raises(PydanticValidationError):
        ManualMetadataSubmissionRequest.model_validate(
            {
                "asset_id": str(uuid4()),
                "source_version": "source-v1",
                "provider_source_version": "a" * 64,
                "tags": ["x" * 1_001],
                "column_edits": [],
            }
        )


def test_manual_metadata_v1_request_accepts_legacy_columns_and_sparse_edits() -> None:
    base = {
        "asset_id": str(uuid4()),
        "source_version": "source-v1",
        "description": "compatible",
    }
    legacy = ManualMetadataSubmissionRequest.model_validate(
        base
        | {
            "columns": [
                {
                    "field_path": "id",
                    "description": "identifier",
                    "tags": [],
                    "terms": [],
                }
            ]
        }
    )
    sparse = ManualMetadataSubmissionRequest.model_validate(
        base
        | {
            "provider_source_version": "a" * 64,
            "column_edits": [],
        }
    )

    assert legacy.provider_source_version is None
    assert legacy.columns is not None
    assert sparse.column_edits == []

    with pytest.raises(PydanticValidationError):
        ManualMetadataSubmissionRequest.model_validate(
            {
                "asset_id": str(uuid4()),
                "source_version": "source-v1",
                "provider_source_version": "a" * 64,
                "column_edits": [
                    {
                        "field_path": "id",
                        "terms": ["x" * 1_001],
                    }
                ],
            }
        )
