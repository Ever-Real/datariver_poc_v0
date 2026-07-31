from datetime import timedelta
from uuid import uuid4

import pytest

from datariver.application.typed_upload_profiles import (
    DATASET_DESCRIPTION_CSV_V1,
    KNOWLEDGE_STUDIO_DOCUMENT_V1,
    validate_upload_profile,
)
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError, utc_now
from datariver.domain.registration import (
    CompletedUploadPart,
    UploadContentProfile,
    UploadManifest,
    UploadPreparation,
    UploadState,
)


def manifest() -> UploadManifest:
    upload_id = uuid4()
    workspace_id = uuid4()
    return UploadManifest(
        upload_id=upload_id,
        workspace_id=workspace_id,
        owner_id=uuid4(),
        bucket="quarantine",
        object_key=f"quarantine/{workspace_id}/{upload_id}",
        display_name="catalog.csv",
        declared_size_bytes=100,
        declared_mime="text/csv",
        declared_sha256="a" * 64,
        classification=Classification.INTERNAL,
        multipart_upload_id="multipart-1",
        expires_at=utc_now() + timedelta(hours=1),
    )


def test_completion_requires_contiguous_parts() -> None:
    upload = manifest()

    with pytest.raises(ValidationError):
        upload.queue_completion(
            parts=[
                CompletedUploadPart(part_number=1, etag="one"),
                CompletedUploadPart(part_number=3, etag="three"),
            ],
            expected_version=1,
        )


def test_completion_event_contains_identifier_not_part_payload() -> None:
    upload = manifest()

    upload.queue_completion(
        parts=[CompletedUploadPart(part_number=1, etag="one")], expected_version=1
    )

    assert upload.state is UploadState.COMPLETION_QUEUED
    assert upload.events[0].payload == {"upload_id": str(upload.upload_id), "version": 2}


def test_quarantine_rejects_declared_size_mismatch() -> None:
    upload = manifest()
    upload.queue_completion(
        parts=[CompletedUploadPart(part_number=1, etag="one")], expected_version=1
    )

    with pytest.raises(ValidationError):
        upload.mark_quarantined(
            actual_size_bytes=101,
            actual_mime="text/csv",
            checksum_sha256=None,
            expected_version=2,
        )


def test_stale_upload_version_is_rejected() -> None:
    upload = manifest()

    with pytest.raises(ConflictError):
        upload.queue_completion(
            parts=[CompletedUploadPart(part_number=1, etag="one")], expected_version=99
        )


def test_completion_claim_and_retry_are_explicit_states() -> None:
    upload = manifest()
    upload.queue_completion(
        parts=[CompletedUploadPart(part_number=1, etag="one")], expected_version=1
    )

    upload.begin_completion(expected_version=2)
    upload.mark_completion_failed(retryable=True, expected_version=3)

    assert upload.state is UploadState.COMPLETION_QUEUED
    assert upload.processing_attempts == 1
    assert upload.version == 4


def test_quarantine_rejects_available_checksum_mismatch() -> None:
    upload = manifest()
    upload.queue_completion(
        parts=[CompletedUploadPart(part_number=1, etag="one")], expected_version=1
    )
    upload.begin_completion(expected_version=2)

    with pytest.raises(ValidationError):
        upload.mark_quarantined(
            actual_size_bytes=100,
            actual_mime="text/csv",
            checksum_sha256="b" * 64,
            expected_version=3,
        )


def test_validation_acceptance_promotes_location_and_records_summary() -> None:
    upload = manifest()
    upload.state = UploadState.QUARANTINED
    upload.begin_validation(expected_version=upload.version)
    upload.mark_accepted(
        accepted_bucket="accepted",
        accepted_object_key=f"accepted/{upload.upload_id}",
        validated_sha256=upload.declared_sha256,
        validation_summary={"coverage": "FULL", "sha256": upload.declared_sha256},
        expected_version=upload.version,
    )

    assert upload.state is UploadState.ACCEPTED
    assert upload.bucket == "accepted"
    assert upload.actual_sha256 == upload.declared_sha256
    assert upload.validation_summary["coverage"] == "FULL"


def test_format_only_is_the_safe_default_and_typed_profile_requires_csv() -> None:
    upload = manifest()

    assert upload.content_profile is UploadContentProfile.FORMAT_ONLY_V1
    with pytest.raises(ValidationError, match="requires a CSV"):
        UploadManifest(
            upload_id=uuid4(),
            workspace_id=uuid4(),
            owner_id=uuid4(),
            bucket="quarantine",
            object_key="quarantine/object",
            display_name="metadata.json",
            declared_size_bytes=100,
            declared_mime="application/json",
            declared_sha256="a" * 64,
            classification=Classification.INTERNAL,
            multipart_upload_id="multipart-1",
            expires_at=utc_now() + timedelta(hours=1),
            content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
        )


def test_typed_profile_definition_is_bounded_and_hashes_exact_schema() -> None:
    definition = DATASET_DESCRIPTION_CSV_V1

    assert definition.headers == (
        "asset_id",
        "platform",
        "database_name",
        "schema_name",
        "table_name",
        "description",
    )
    assert definition.maximum_file_bytes == 16 * 1024 * 1024
    assert definition.maximum_rows == 10_000
    assert (
        definition.maximum_platform_characters,
        definition.maximum_database_name_characters,
        definition.maximum_schema_name_characters,
        definition.maximum_table_name_characters,
    ) == (100, 255, 255, 500)
    assert (
        definition.configuration_hash
        == "e840ab65b7c3c1fc89e5b4fc68bafedc2426ac8be2f57b381c07c4569e602ad5"
    )
    validate_upload_profile(
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
        display_name="dataset-description.csv",
        content_type="text/csv",
        size_bytes=1024,
    )
    with pytest.raises(ValidationError, match="bounded file-size"):
        validate_upload_profile(
            content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
            display_name="dataset-description.csv",
            content_type="text/csv",
            size_bytes=definition.maximum_file_bytes + 1,
        )


@pytest.mark.parametrize(
    ("display_name", "content_type"),
    (
        ("source.pdf", "application/pdf"),
        ("source.csv", "text/csv"),
        ("source.txt", "text/plain"),
        ("source.json", "application/json"),
        ("source.xml", "application/xml"),
        ("source.html", "text/html"),
        (
            "source.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "source.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "source.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ),
)
def test_knowledge_studio_document_profile_accepts_only_its_bounded_media_contract(
    display_name: str,
    content_type: str,
) -> None:
    validate_upload_profile(
        content_profile=UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1,
        display_name=display_name,
        content_type=content_type,
        size_bytes=KNOWLEDGE_STUDIO_DOCUMENT_V1.maximum_file_bytes,
    )


def test_knowledge_studio_document_profile_rejects_unlisted_media_and_oversize() -> None:
    with pytest.raises(ValidationError, match="content type or filename"):
        validate_upload_profile(
            content_profile=UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1,
            display_name="source.yaml",
            content_type="application/yaml",
            size_bytes=100,
        )
    with pytest.raises(ValidationError, match="content type or filename"):
        validate_upload_profile(
            content_profile=UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1,
            display_name="source.txt",
            content_type="application/pdf",
            size_bytes=100,
        )
    with pytest.raises(ValidationError, match="bounded file-size"):
        validate_upload_profile(
            content_profile=UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1,
            display_name="source.pdf",
            content_type="application/pdf",
            size_bytes=KNOWLEDGE_STUDIO_DOCUMENT_V1.maximum_file_bytes + 1,
        )
    assert KNOWLEDGE_STUDIO_DOCUMENT_V1.maximum_file_bytes == 10 * 1024 * 1024
    assert (
        KNOWLEDGE_STUDIO_DOCUMENT_V1.configuration_hash
        == "c70a2750dd6f089d79ef3e4d1e2eb59bb34b885c85db88d0426d59ee65a513e8"
    )


def test_preparation_queue_is_server_owned_and_emits_bounded_event() -> None:
    upload = manifest()
    preparation = UploadPreparation.queue(
        workspace_id=upload.workspace_id,
        upload_id=upload.upload_id,
        requested_by=upload.owner_id,
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
        source_manifest_version=7,
        source_sha256="a" * 64,
        configuration_hash="b" * 64,
    )

    assert preparation.state.value == "QUEUED"
    assert preparation.rows_processed == 0
    assert preparation.attempts == 0
    assert preparation.events[0].payload == {
        "preparation_id": str(preparation.preparation_id),
        "upload_id": str(upload.upload_id),
        "source_manifest_version": 7,
        "content_profile": "DATASET_DESCRIPTION_CSV_V1",
    }
