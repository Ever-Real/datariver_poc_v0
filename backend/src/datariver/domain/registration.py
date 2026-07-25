from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, DomainEvent, ValidationError, utc_now, uuid7


class UploadState(StrEnum):
    INITIATED = "INITIATED"
    COMPLETION_QUEUED = "COMPLETION_QUEUED"
    COMPLETING = "COMPLETING"
    QUARANTINED = "QUARANTINED"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ABORTED = "ABORTED"
    EXPIRED = "EXPIRED"


class UploadContentProfile(StrEnum):
    FORMAT_ONLY_V1 = "FORMAT_ONLY_V1"
    CATALOG_METADATA_ROWS_CSV_V1 = "CATALOG_METADATA_ROWS_CSV_V1"
    CATALOG_METADATA_ROWS_XLSX_V1 = "CATALOG_METADATA_ROWS_XLSX_V1"


class UploadPreparationState(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class CompletedUploadPart:
    part_number: int
    etag: str
    checksum_sha256: str | None = None


@dataclass(slots=True)
class UploadManifest:
    upload_id: UUID
    workspace_id: UUID
    owner_id: UUID
    bucket: str
    object_key: str
    display_name: str
    declared_size_bytes: int
    declared_mime: str
    declared_sha256: str
    classification: Classification
    multipart_upload_id: str
    expires_at: datetime
    content_profile: UploadContentProfile = UploadContentProfile.FORMAT_ONLY_V1
    state: UploadState = UploadState.INITIATED
    version: int = 1
    completion_parts: list[CompletedUploadPart] = field(default_factory=list)
    actual_size_bytes: int | None = None
    actual_mime: str | None = None
    actual_sha256: str | None = None
    processing_attempts: int = 0
    validation_attempts: int = 0
    validation_summary: dict[str, object] = field(default_factory=dict)
    last_error_code: str | None = None
    events: list[DomainEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if (
            self.content_profile
            in {
                UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
            }
            and self.declared_mime != "text/csv"
        ):
            raise ValidationError("The selected content profile requires a CSV upload.")
        if (
            self.content_profile
            in {
                UploadContentProfile.CATALOG_METADATA_ROWS_XLSX_V1,
            }
            and self.declared_mime
            != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            raise ValidationError("The selected content profile requires an XLSX upload.")

    def queue_completion(self, *, parts: list[CompletedUploadPart], expected_version: int) -> None:
        self._check_version(expected_version)
        if self.state is not UploadState.INITIATED:
            raise ValidationError("Only an initiated upload can be queued for completion.")
        if not parts or len(parts) > 10_000:
            raise ValidationError("Upload completion requires between 1 and 10000 parts.")
        ordered = sorted(parts, key=lambda item: item.part_number)
        numbers = [item.part_number for item in ordered]
        if len(set(numbers)) != len(numbers) or numbers != list(range(1, len(numbers) + 1)):
            raise ValidationError("Upload parts must be unique and contiguous from part 1.")
        self.completion_parts = ordered
        self.state = UploadState.COMPLETION_QUEUED
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="registration.upload.completion_queued.v1",
                aggregate_type="upload_manifest",
                aggregate_id=self.upload_id,
                workspace_id=self.workspace_id,
                payload={"upload_id": str(self.upload_id), "version": self.version},
            )
        )

    def begin_completion(self, *, expected_version: int) -> None:
        self._check_version(expected_version)
        if self.state not in {UploadState.COMPLETION_QUEUED, UploadState.COMPLETING}:
            raise ValidationError("The upload is not available for completion processing.")
        self.state = UploadState.COMPLETING
        self.processing_attempts += 1
        self.version += 1

    def mark_quarantined(
        self,
        *,
        actual_size_bytes: int,
        actual_mime: str,
        checksum_sha256: str | None,
        expected_version: int,
    ) -> None:
        self._check_version(expected_version)
        if self.state not in {UploadState.COMPLETION_QUEUED, UploadState.COMPLETING}:
            raise ValidationError("The upload is not awaiting completion.")
        if actual_size_bytes != self.declared_size_bytes:
            raise ValidationError("Uploaded object size does not match the declaration.")
        if actual_mime != self.declared_mime:
            raise ValidationError("Uploaded object content type does not match the declaration.")
        if checksum_sha256 is not None and checksum_sha256 != self.declared_sha256:
            raise ValidationError("Uploaded object checksum does not match the declaration.")
        self.actual_size_bytes = actual_size_bytes
        self.actual_mime = actual_mime
        self.actual_sha256 = checksum_sha256
        self.state = UploadState.QUARANTINED
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="registration.upload.quarantined.v1",
                aggregate_type="upload_manifest",
                aggregate_id=self.upload_id,
                workspace_id=self.workspace_id,
                payload={"upload_id": str(self.upload_id), "version": self.version},
            )
        )

    def mark_completion_failed(self, *, retryable: bool, expected_version: int) -> None:
        self._check_version(expected_version)
        if self.state is not UploadState.COMPLETING:
            raise ValidationError("Only an active completion can fail.")
        self.state = UploadState.COMPLETION_QUEUED if retryable else UploadState.REJECTED
        self.version += 1
        if not retryable:
            self.events.append(
                DomainEvent.create(
                    event_type="registration.upload.rejected.v1",
                    aggregate_type="upload_manifest",
                    aggregate_id=self.upload_id,
                    workspace_id=self.workspace_id,
                    payload={"upload_id": str(self.upload_id), "version": self.version},
                )
            )

    def begin_validation(self, *, expected_version: int) -> None:
        self._check_version(expected_version)
        if self.state not in {UploadState.QUARANTINED, UploadState.VALIDATING}:
            raise ValidationError("The upload is not available for validation.")
        self.state = UploadState.VALIDATING
        self.validation_attempts += 1
        self.version += 1

    def mark_accepted(
        self,
        *,
        accepted_bucket: str,
        accepted_object_key: str,
        validated_sha256: str,
        validation_summary: dict[str, object],
        expected_version: int,
    ) -> None:
        self._check_version(expected_version)
        if self.state is not UploadState.VALIDATING:
            raise ValidationError("Only a validated upload can be accepted.")
        if not accepted_bucket or not accepted_object_key:
            raise ValidationError("Accepted object location is required.")
        if validated_sha256 != self.declared_sha256:
            raise ValidationError("Validated object checksum does not match the declaration.")
        self.bucket = accepted_bucket
        self.object_key = accepted_object_key
        self.actual_sha256 = validated_sha256
        self.validation_summary = dict(validation_summary)
        self.state = UploadState.ACCEPTED
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="registration.upload.accepted.v1",
                aggregate_type="upload_manifest",
                aggregate_id=self.upload_id,
                workspace_id=self.workspace_id,
                payload={
                    "upload_id": str(self.upload_id),
                    "validation": self.validation_summary,
                    "version": self.version,
                },
            )
        )

    def mark_validation_failed(self, *, retryable: bool, expected_version: int) -> None:
        self._check_version(expected_version)
        if self.state is not UploadState.VALIDATING:
            raise ValidationError("Only an active validation can fail.")
        self.state = UploadState.QUARANTINED if retryable else UploadState.REJECTED
        self.version += 1
        if not retryable:
            self.events.append(
                DomainEvent.create(
                    event_type="registration.upload.rejected.v1",
                    aggregate_type="upload_manifest",
                    aggregate_id=self.upload_id,
                    workspace_id=self.workspace_id,
                    payload={"upload_id": str(self.upload_id), "version": self.version},
                )
            )

    def abort(self, *, expected_version: int) -> None:
        self._check_version(expected_version)
        if self.state not in {UploadState.INITIATED, UploadState.COMPLETION_QUEUED}:
            raise ValidationError("The upload can no longer be aborted.")
        self.state = UploadState.ABORTED
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="registration.upload.aborted.v1",
                aggregate_type="upload_manifest",
                aggregate_id=self.upload_id,
                workspace_id=self.workspace_id,
                payload={"upload_id": str(self.upload_id), "version": self.version},
            )
        )

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The upload was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )

    @property
    def expired(self) -> bool:
        return self.expires_at <= utc_now()


@dataclass(slots=True)
class UploadPreparation:
    preparation_id: UUID
    workspace_id: UUID
    upload_id: UUID
    requested_by: UUID
    content_profile: UploadContentProfile
    source_manifest_version: int
    source_sha256: str
    configuration_hash: str
    state: UploadPreparationState
    attempts: int
    rows_processed: int
    total_rows: int | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def queue(
        cls,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        requested_by: UUID,
        content_profile: UploadContentProfile,
        source_manifest_version: int,
        source_sha256: str,
        configuration_hash: str,
    ) -> UploadPreparation:
        if content_profile not in {
            UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
            UploadContentProfile.DATASET_DESCRIPTION_XLSX_V1,
        }:
            raise ValidationError("The upload profile has no typed preparation workflow.")
        if source_manifest_version < 1:
            raise ValidationError("The source manifest version is invalid.")
        for field_name, digest_value in (
            ("source_sha256", source_sha256),
            ("configuration_hash", configuration_hash),
        ):
            if len(digest_value) != 64 or any(
                character not in "0123456789abcdef" for character in digest_value
            ):
                raise ValidationError(f"The {field_name} value is invalid.")
        preparation_id = uuid7()
        now = utc_now()
        preparation = cls(
            preparation_id=preparation_id,
            workspace_id=workspace_id,
            upload_id=upload_id,
            requested_by=requested_by,
            content_profile=content_profile,
            source_manifest_version=source_manifest_version,
            source_sha256=source_sha256,
            configuration_hash=configuration_hash,
            state=UploadPreparationState.QUEUED,
            attempts=0,
            rows_processed=0,
            total_rows=None,
            last_error_code=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        preparation.events.append(
            DomainEvent.create(
                event_type="registration.upload.preparation_queued.v1",
                aggregate_type="upload_preparation",
                aggregate_id=preparation_id,
                workspace_id=workspace_id,
                payload={
                    "preparation_id": str(preparation_id),
                    "upload_id": str(upload_id),
                    "source_manifest_version": source_manifest_version,
                    "content_profile": content_profile.value,
                },
            )
        )
        return preparation
