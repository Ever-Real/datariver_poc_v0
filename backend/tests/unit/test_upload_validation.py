from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import ObjectMetadata
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import ObjectStore, UploadValidationStore
from datariver.application.services.upload_validation import Inspection, UploadValidationWorker
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError
from datariver.domain.registration import UploadContentProfile, UploadManifest, UploadState


class MemoryValidationStore:
    def __init__(
        self,
        manifest: UploadManifest,
        *,
        accept_result: bool = True,
        accept_error: Exception | None = None,
    ) -> None:
        self.manifest: UploadManifest | None = manifest
        self.accept_result = accept_result
        self.accept_error = accept_error
        self.accepted: dict[str, object] | None = None
        self.accepted_object_key: str | None = None
        self.failed: tuple[str, bool] | None = None

    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None:
        del lease_seconds, maximum_attempts
        value, self.manifest = self.manifest, None
        return value

    async def mark_accepted(
        self,
        *,
        manifest: UploadManifest,
        accepted_bucket: str,
        accepted_object_key: str,
        validated_sha256: str,
        validation_summary: dict[str, object],
    ) -> bool:
        del manifest, accepted_bucket
        assert validated_sha256 == validation_summary["sha256"]
        self.accepted_object_key = accepted_object_key
        if self.accept_error is not None:
            raise self.accept_error
        if self.accept_result:
            self.accepted = validation_summary
        return self.accept_result

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        del manifest, maximum_attempts
        self.failed = (error_code, retryable)


class MemoryObjectStore:
    def __init__(
        self,
        *,
        source_bucket: str,
        source_key: str,
        content: bytes,
        content_type: str,
        corrupt_copy: bytes | None = None,
        cleanup_failures: set[tuple[str, str]] | None = None,
    ) -> None:
        self.content_type = content_type
        self.corrupt_copy = corrupt_copy
        self.cleanup_failures = cleanup_failures or set()
        self.objects: dict[tuple[str, str], bytes] = {(source_bucket, source_key): content}
        self.copy_destinations: list[tuple[str, str]] = []
        self.read_paths: list[tuple[str, str]] = []
        self.delete_attempts: list[tuple[str, str]] = []

    async def iter_object_chunks(
        self, *, bucket: str, object_key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        del chunk_size
        path = (bucket, object_key)
        self.read_paths.append(path)
        content = self.objects[path]
        midpoint = max(len(content) // 2, 1)
        yield content[:midpoint]
        if content[midpoint:]:
            yield content[midpoint:]

    async def copy_object(
        self,
        *,
        source_bucket: str,
        source_key: str,
        destination_bucket: str,
        destination_key: str,
    ) -> ObjectMetadata:
        source = self.objects[(source_bucket, source_key)]
        copied = self.corrupt_copy if self.corrupt_copy is not None else source
        destination = (destination_bucket, destination_key)
        self.objects[destination] = copied
        self.copy_destinations.append(destination)
        return ObjectMetadata(
            destination_bucket,
            destination_key,
            len(copied),
            self.content_type,
            "etag",
            hashlib.sha256(copied).hexdigest(),
            {},
        )

    async def delete_object(self, *, bucket: str, object_key: str) -> None:
        path = (bucket, object_key)
        self.delete_attempts.append(path)
        if path in self.cleanup_failures:
            raise ExternalDependencyError(
                "cleanup failed",
                dependency="object_store",
                retryable=True,
                provider_code="DELETE_FAILED",
            )
        self.objects.pop(path, None)


def manifest(
    content: bytes,
    *,
    declared_hash: str | None = None,
    upload_id: UUID | None = None,
    workspace_id: UUID | None = None,
    version: int = 7,
    validation_attempts: int = 2,
) -> UploadManifest:
    return UploadManifest(
        upload_id=upload_id or uuid4(),
        workspace_id=workspace_id or uuid4(),
        owner_id=uuid4(),
        bucket="quarantine",
        object_key="object",
        display_name="assets.csv",
        declared_size_bytes=len(content),
        declared_mime="text/csv",
        declared_sha256=declared_hash or hashlib.sha256(content).hexdigest(),
        classification=Classification.INTERNAL,
        multipart_upload_id="multipart",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        state=UploadState.VALIDATING,
        version=version,
        validation_attempts=validation_attempts,
    )


def worker(*, store: MemoryValidationStore, objects: MemoryObjectStore) -> UploadValidationWorker:
    return UploadValidationWorker(
        store=cast(UploadValidationStore, store),
        object_store=cast(ObjectStore, objects),
        accepted_bucket="accepted",
    )


@pytest.mark.asyncio
async def test_streaming_csv_integrity_validation_promotes_then_cleans_quarantine() -> None:
    content = b"asset_id,name\n1,wafer\n2,die\n"
    upload = manifest(content)
    store = MemoryValidationStore(upload)
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="text/csv",
    )

    assert await worker(store=store, objects=objects).run_once() is True

    destination_key = (
        f"accepted/{upload.workspace_id}/{upload.upload_id}/"
        f"validation-v{upload.version}-attempt-{upload.validation_attempts}"
    )
    assert store.failed is None
    assert store.accepted is not None
    assert store.accepted["column_count"] == 2
    assert store.accepted_object_key == destination_key
    assert objects.read_paths == [
        (upload.bucket, upload.object_key),
        ("accepted", destination_key),
    ]
    assert (upload.bucket, upload.object_key) not in objects.objects
    assert ("accepted", destination_key) in objects.objects


@pytest.mark.parametrize(
    ("classification", "expected_namespace"),
    (
        (Classification.PUBLIC, "knowledge-eligible"),
        (Classification.INTERNAL, "knowledge-eligible"),
        (Classification.CONFIDENTIAL, "accepted"),
        (Classification.RESTRICTED, "accepted"),
    ),
)
@pytest.mark.asyncio
async def test_only_low_classification_pdfs_use_the_knowledge_read_prefix(
    classification: Classification,
    expected_namespace: str,
) -> None:
    content = b"%PDF-1.7\nclassification boundary\n%%EOF"
    upload = manifest(content)
    upload.display_name = "source.pdf"
    upload.declared_mime = "application/pdf"
    upload.classification = classification
    store = MemoryValidationStore(upload)
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="application/pdf",
    )

    assert await worker(store=store, objects=objects).run_once() is True

    destination_key = (
        f"{expected_namespace}/{upload.workspace_id}/{upload.upload_id}/"
        f"validation-v{upload.version}-attempt-{upload.validation_attempts}"
    )
    assert store.accepted_object_key == destination_key
    assert objects.copy_destinations == [("accepted", destination_key)]


def test_xlsx_validation_emits_the_registered_profile_validator_version() -> None:
    content = b"PK\x03\x04safe-xlsx-package"
    upload = manifest(content)
    upload.display_name = "assets.xlsx"
    upload.declared_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    upload.content_profile = UploadContentProfile.DATASET_DESCRIPTION_XLSX_V1
    summary = UploadValidationWorker._validate_format(
        upload,
        Inspection(
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            prefix=content,
            tail=content[-8:],
            contains_vba=False,
        ),
    )

    assert summary["validator_version"] == "integrity-xlsx-v2-low-resource"


@pytest.mark.parametrize(
    ("display_name", "mime", "content"),
    (
        ("source.txt", "text/plain", "고객 데이터".encode()),
        ("source.json", "application/json", b'{"customer":"one"}'),
        ("source.xml", "application/xml", "<customer>하나</customer>".encode()),
        ("source.html", "text/html", b"<p>customer</p>"),
        (
            "source.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04safe-docx-package",
        ),
        (
            "source.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            b"PK\x03\x04safe-pptx-package",
        ),
    ),
)
def test_format_only_knowledge_documents_are_allowlisted(
    display_name: str,
    mime: str,
    content: bytes,
) -> None:
    upload = manifest(content)
    upload.display_name = display_name
    upload.declared_mime = mime

    summary = UploadValidationWorker._validate_format(
        upload,
        Inspection(
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            prefix=content,
            tail=content[-8:],
            contains_vba=False,
        ),
    )

    assert summary["validator_version"] in {"integrity-format-v1", "integrity-openxml-v1"}


def test_xml_entity_and_legacy_document_profiles_fail_closed() -> None:
    content = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'
    upload = manifest(content)
    upload.display_name = "source.xml"
    upload.declared_mime = "application/xml"

    with pytest.raises(ValidationError, match="DTD and entity"):
        UploadValidationWorker._validate_format(
            upload,
            Inspection(
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                prefix=content,
                tail=content[-8:],
                contains_vba=False,
            ),
        )

    upload.display_name = "legacy.doc"
    upload.declared_mime = "application/msword"
    with pytest.raises(ValidationError, match="extension"):
        UploadValidationWorker._validate_format(
            upload,
            Inspection(
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                prefix=content,
                tail=content[-8:],
                contains_vba=False,
            ),
        )

    openxml = b"PK\x03\x04xl/externalLinks/externalLink1.xml"
    upload.display_name = "unsafe.xlsx"
    upload.declared_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    with pytest.raises(ValidationError, match="OpenXML"):
        UploadValidationWorker._validate_format(
            upload,
            Inspection(
                size_bytes=len(openxml),
                sha256=hashlib.sha256(openxml).hexdigest(),
                prefix=openxml,
                tail=openxml[-8:],
                contains_vba=False,
                contains_openxml_external_link=True,
            ),
        )


def test_typed_csv_validation_emits_the_registered_profile_validator_version() -> None:
    content = b"asset_id,platform,database_name,schema_name,table_name,description\n"
    upload = manifest(content)
    upload.content_profile = UploadContentProfile.DATASET_DESCRIPTION_CSV_V1
    summary = UploadValidationWorker._validate_format(
        upload,
        Inspection(
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            prefix=content,
            tail=content[-8:],
            contains_vba=False,
        ),
    )

    assert summary["validator_version"] == "integrity-format-v2-low-resource"


@pytest.mark.asyncio
async def test_checksum_mismatch_is_terminal_and_never_promoted() -> None:
    content = b"asset_id,name\n1,wafer\n"
    upload = manifest(content, declared_hash="0" * 64)
    store = MemoryValidationStore(upload)
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="text/csv",
    )

    assert await worker(store=store, objects=objects).run_once() is True

    assert store.accepted is None
    assert store.failed == ("CHECKSUM_MISMATCH", False)
    assert objects.copy_destinations == []
    assert (upload.bucket, upload.object_key) in objects.objects


@pytest.mark.asyncio
async def test_stale_claim_uses_a_unique_destination_and_removes_only_its_orphan() -> None:
    content = b"asset_id,name\n1,wafer\n"
    upload_id = uuid4()
    workspace_id = uuid4()
    stale = manifest(
        content,
        upload_id=upload_id,
        workspace_id=workspace_id,
        version=7,
        validation_attempts=2,
    )
    current = manifest(
        content,
        upload_id=upload_id,
        workspace_id=workspace_id,
        version=9,
        validation_attempts=3,
    )
    objects = MemoryObjectStore(
        source_bucket=stale.bucket,
        source_key=stale.object_key,
        content=content,
        content_type="text/csv",
    )

    stale_store = MemoryValidationStore(stale, accept_result=False)
    assert await worker(store=stale_store, objects=objects).run_once() is True
    stale_destination = objects.copy_destinations[-1]
    assert stale_store.failed is None
    assert stale_destination not in objects.objects
    assert (stale.bucket, stale.object_key) in objects.objects

    current_store = MemoryValidationStore(current)
    assert await worker(store=current_store, objects=objects).run_once() is True
    current_destination = objects.copy_destinations[-1]
    assert current_destination != stale_destination
    assert current_destination in objects.objects
    assert (current.bucket, current.object_key) not in objects.objects


@pytest.mark.asyncio
async def test_same_size_corrupt_copy_is_detected_by_full_readback_and_cleaned() -> None:
    content = b"asset_id,name\n1,wafer\n"
    corrupt = b"asset_id,name\n1,XXXXX\n"
    assert len(corrupt) == len(content)
    upload = manifest(content)
    store = MemoryValidationStore(upload)
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="text/csv",
        corrupt_copy=corrupt,
    )

    assert await worker(store=store, objects=objects).run_once() is True

    destination = objects.copy_destinations[0]
    assert store.accepted is None
    assert store.failed == ("CHECKSUM_MISMATCH", False)
    assert destination in objects.read_paths
    assert destination not in objects.objects
    assert (upload.bucket, upload.object_key) in objects.objects


@pytest.mark.asyncio
async def test_stale_orphan_cleanup_failure_preserves_source_and_does_not_fail_claim() -> None:
    content = b"asset_id,name\n1,wafer\n"
    upload = manifest(content)
    destination_key = (
        f"accepted/{upload.workspace_id}/{upload.upload_id}/"
        f"validation-v{upload.version}-attempt-{upload.validation_attempts}"
    )
    destination = ("accepted", destination_key)
    store = MemoryValidationStore(upload, accept_result=False)
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="text/csv",
        cleanup_failures={destination},
    )

    assert await worker(store=store, objects=objects).run_once() is True

    assert store.failed is None
    assert destination in objects.delete_attempts
    assert destination in objects.objects
    assert (upload.bucket, upload.object_key) in objects.objects


@pytest.mark.asyncio
async def test_ambiguous_accept_commit_never_deletes_destination_or_source() -> None:
    content = b"asset_id,name\n1,wafer\n"
    upload = manifest(content)
    store = MemoryValidationStore(
        upload,
        accept_error=ExternalDependencyError(
            "commit result is unknown",
            dependency="postgresql",
            retryable=True,
            provider_code="AMBIGUOUS_COMMIT",
        ),
    )
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="text/csv",
    )

    assert await worker(store=store, objects=objects).run_once() is True

    destination = objects.copy_destinations[0]
    assert store.failed == ("AMBIGUOUS_COMMIT", True)
    assert destination in objects.objects
    assert (upload.bucket, upload.object_key) in objects.objects
    assert objects.delete_attempts == []


@pytest.mark.asyncio
async def test_domain_cleanup_errors_are_best_effort_after_acceptance() -> None:
    content = b"asset_id,name\n1,wafer\n"
    upload = manifest(content)
    source = (upload.bucket, upload.object_key)
    store = MemoryValidationStore(upload)
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="text/csv",
        cleanup_failures={source},
    )

    assert await worker(store=store, objects=objects).run_once() is True

    assert store.accepted is not None
    assert store.failed is None
    assert source in objects.objects


@pytest.mark.parametrize("error_type", [RuntimeError])
@pytest.mark.asyncio
async def test_unexpected_accept_error_is_ambiguous_and_keeps_both_objects(
    error_type: type[Exception],
) -> None:
    content = b"asset_id,name\n1,wafer\n"
    upload = manifest(content)
    store = MemoryValidationStore(upload, accept_error=error_type("unknown"))
    objects = MemoryObjectStore(
        source_bucket=upload.bucket,
        source_key=upload.object_key,
        content=content,
        content_type="text/csv",
    )

    assert await worker(store=store, objects=objects).run_once() is True

    assert store.failed == ("UNEXPECTED_RuntimeError", True)
    assert objects.copy_destinations[0] in objects.objects
    assert (upload.bucket, upload.object_key) in objects.objects
