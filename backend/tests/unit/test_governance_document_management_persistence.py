from __future__ import annotations

import json
import runpy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from datariver.domain.authz import Classification
from datariver.domain.governance_documents import (
    GovernanceDocumentCategory,
    GovernanceDocumentDetail,
    GovernanceDocumentKind,
    GovernanceDocumentState,
    GovernanceDocumentSummary,
)
from datariver.interfaces.http.governance_document_presenters import (
    governance_document_detail_response,
)
from datariver.interfaces.http.governance_document_schemas import (
    GovernanceDocumentDetailItemResponse,
    GovernanceDocumentExportResponse,
)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0079_governance_document_management.py"
CANONICAL = ROOT / "backend/alembic/versions/0001_initial_schema.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"
REPOSITORY = ROOT / "backend/src/datariver/infrastructure/db/governance_documents.py"


def test_additive_management_migration_has_bounded_backfill_and_immutable_parent() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    namespace = runpy.run_path(str(MIGRATION))

    assert namespace["revision"] == "0079"
    assert namespace["down_revision"] == "0078"
    assert "row_number() OVER (" in source
    assert "PARTITION BY workspace_id, document_version_id" in source
    assert "ORDER BY created_at, id" in source
    drop_trigger = source.index("DROP TRIGGER reject_document_attachment_mutation")
    backfill = source.index("UPDATE governance.document_attachments AS attachment")
    restore_trigger = source.index("op.execute(_ATTACHMENT_MUTATION_TRIGGER_SQL)")
    assert drop_trigger < backfill < restore_trigger
    assert "EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1()" in source
    assert "serial_number BETWEEN 1 AND 25" in source
    assert "uq_governance_document_attachments_serial" in source
    assert "parent_document_id IS NULL OR parent_document_id <> document_id" in source
    assert "reject_document_parent_mutation_v1" in source
    assert "NEW.parent_document_id IS DISTINCT FROM OLD.parent_document_id" in source
    assert "storage_filename IS NOT NULL" in source


def test_canonical_and_generator_include_the_same_management_contract() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")
    generator = GENERATOR.read_text(encoding="utf-8")

    assert "parent_document_id" in canonical
    assert "ck_document_versions_parent_document_distinct" in canonical
    assert "ix_governance_document_versions_parent" in canonical
    assert "storage_filename" in canonical
    assert "ck_document_attachments_serial_number_range" in canonical
    assert "uq_governance_document_attachments_serial" in canonical
    assert "reject_document_parent_mutation_v1" in canonical
    assert "NEW.parent_document_id IS DISTINCT FROM OLD.parent_document_id" in canonical
    assert "_load_governance_document_management_revision" in generator
    assert "_PARENT_MUTATION_FUNCTION_SQL" in generator
    assert "_PARENT_MUTATION_TRIGGER_SQL" in generator


def test_export_schema_has_no_object_store_coordinates_or_signing_fields() -> None:
    schema = json.dumps(
        GovernanceDocumentExportResponse.model_json_schema(),
        sort_keys=True,
    )

    for prohibited in (
        '"bucket"',
        '"object_key"',
        '"provider_version_id"',
        '"etag"',
        '"url"',
        '"expires_at"',
        '"credential"',
        '"endpoint"',
    ):
        assert prohibited not in schema


def test_detail_schema_and_presenter_expose_only_canonical_subject_display_names() -> None:
    subject_id = uuid4()
    now = datetime.now(UTC)
    summary = GovernanceDocumentSummary(
        document_id=uuid4(),
        workspace_id=uuid4(),
        kind=GovernanceDocumentKind.DOCUMENT,
        category=GovernanceDocumentCategory.POLICY,
        title="Policy",
        summary="Managed policy",
        classification=Classification.INTERNAL,
        state=GovernanceDocumentState.ACTIVE,
        owner_subject_id=subject_id,
        current_published_version_id=None,
        current_version_number=None,
        created_at=now,
        updated_at=now,
        version=1,
        allowed_actions=("read",),
    )

    response = governance_document_detail_response(
        GovernanceDocumentDetail(
            document=summary,
            versions=(),
            reviews=(),
            attachments=(),
            parent_document=None,
            child_documents=(),
            subject_display_names=((subject_id, "Data Steward"),),
        )
    )

    assert response.subject_display_names == {subject_id: "Data Steward"}
    assert (
        "subject_display_names"
        in GovernanceDocumentDetailItemResponse.model_json_schema()["required"]
    )


def test_detail_repository_resolves_names_through_workspace_scoped_iam_membership() -> None:
    source = REPOSITORY.read_text(encoding="utf-8")

    assert "select(SubjectModel.id, SubjectModel.display_name)" in source
    assert "WorkspaceMembershipModel.subject_id == SubjectModel.id" in source
    assert "WorkspaceMembershipModel.workspace_id == document.workspace_id" in source
