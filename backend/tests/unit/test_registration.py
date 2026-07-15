from datetime import timedelta
from uuid import uuid4

import pytest

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError, utc_now
from datariver.domain.registration import CompletedUploadPart, UploadManifest, UploadState


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
        validation_summary={"coverage": "FULL", "sha256": upload.declared_sha256},
        expected_version=upload.version,
    )

    assert upload.state is UploadState.ACCEPTED
    assert upload.bucket == "accepted"
    assert upload.validation_summary["coverage"] == "FULL"
