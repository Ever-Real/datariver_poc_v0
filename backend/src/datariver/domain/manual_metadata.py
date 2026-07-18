from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import DomainEvent, ValidationError, utc_now, uuid7


class ManualMetadataSubmissionState(StrEnum):
    QUEUED = "QUEUED"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ManualColumnMetadata:
    field_path: str
    description: str
    tags: tuple[str, ...]
    terms: tuple[str, ...]


@dataclass(slots=True)
class ManualMetadataSubmission:
    submission_id: UUID
    workspace_id: UUID
    asset_id: UUID
    external_urn: str
    requester_id: UUID
    source_version: str
    serial_number: int
    description: str
    domain: str | None
    tags: tuple[str, ...]
    terms: tuple[str, ...]
    columns: tuple[ManualColumnMetadata, ...]
    bucket: str
    object_key: str
    csv_sha256: str
    csv_size_bytes: int
    row_count: int
    state: ManualMetadataSubmissionState
    created_at: datetime
    updated_at: datetime
    version: int = 1
    applied_at: datetime | None = None
    last_error_code: str | None = None
    attempts: int = 0
    lease_expires_at: datetime | None = None
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def queue(
        cls,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        external_urn: str,
        requester_id: UUID,
        source_version: str,
        serial_number: int,
        description: str,
        domain: str | None,
        tags: tuple[str, ...],
        terms: tuple[str, ...],
        columns: tuple[ManualColumnMetadata, ...],
        bucket: str,
        object_key: str,
        csv_sha256: str,
        csv_size_bytes: int,
        row_count: int,
    ) -> ManualMetadataSubmission:
        cls._validate(
            external_urn=external_urn,
            source_version=source_version,
            serial_number=serial_number,
            description=description,
            domain=domain,
            tags=tags,
            terms=terms,
            columns=columns,
            bucket=bucket,
            object_key=object_key,
            csv_sha256=csv_sha256,
            csv_size_bytes=csv_size_bytes,
            row_count=row_count,
        )
        now = utc_now()
        submission = cls(
            submission_id=uuid7(),
            workspace_id=workspace_id,
            asset_id=asset_id,
            external_urn=external_urn,
            requester_id=requester_id,
            source_version=source_version,
            serial_number=serial_number,
            description=description,
            domain=domain,
            tags=tags,
            terms=terms,
            columns=columns,
            bucket=bucket,
            object_key=object_key,
            csv_sha256=csv_sha256,
            csv_size_bytes=csv_size_bytes,
            row_count=row_count,
            state=ManualMetadataSubmissionState.QUEUED,
            created_at=now,
            updated_at=now,
        )
        submission.events.append(
            DomainEvent.create(
                event_type="registration.manual_metadata.queued.v1",
                aggregate_type="manual_metadata_submission",
                aggregate_id=submission.submission_id,
                workspace_id=workspace_id,
                payload={
                    "submission_id": str(submission.submission_id),
                    "asset_id": str(asset_id),
                    "serial_number": serial_number,
                    "source_version": source_version,
                },
            )
        )
        return submission

    def claim_for_apply(self, *, now: datetime, lease_seconds: int) -> None:
        if lease_seconds < 1:
            raise ValidationError("The manual metadata apply lease is invalid.")
        if self.state is ManualMetadataSubmissionState.APPLIED:
            raise ValidationError("The manual metadata submission is already applied.")
        if self.state is ManualMetadataSubmissionState.FAILED:
            raise ValidationError("The manual metadata submission is terminally failed.")
        if (
            self.state is ManualMetadataSubmissionState.APPLYING
            and self.lease_expires_at is not None
            and self.lease_expires_at > now
        ):
            raise ValidationError("The manual metadata submission is already being applied.")
        self.state = ManualMetadataSubmissionState.APPLYING
        self.attempts += 1
        self.lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.last_error_code = None
        self.updated_at = now
        self.version += 1

    def mark_applied(self, *, now: datetime) -> None:
        if self.state is not ManualMetadataSubmissionState.APPLYING:
            raise ValidationError("Only an applying manual metadata submission may complete.")
        self.state = ManualMetadataSubmissionState.APPLIED
        self.applied_at = now
        self.lease_expires_at = None
        self.last_error_code = None
        self.updated_at = now
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="registration.manual_metadata.applied.v1",
                aggregate_type="manual_metadata_submission",
                aggregate_id=self.submission_id,
                workspace_id=self.workspace_id,
                payload={
                    "submission_id": str(self.submission_id),
                    "asset_id": str(self.asset_id),
                    "serial_number": self.serial_number,
                    "attempts": self.attempts,
                },
            )
        )

    def mark_apply_failed(self, *, now: datetime, error_code: str, retryable: bool) -> None:
        if self.state is not ManualMetadataSubmissionState.APPLYING:
            raise ValidationError("Only an applying manual metadata submission may fail.")
        if not error_code or len(error_code) > 100 or "\x00" in error_code:
            raise ValidationError("The manual metadata apply error is invalid.")
        self.state = (
            ManualMetadataSubmissionState.QUEUED
            if retryable
            else ManualMetadataSubmissionState.FAILED
        )
        self.lease_expires_at = None
        self.last_error_code = error_code
        self.updated_at = now
        self.version += 1

    @staticmethod
    def _validate(
        *,
        external_urn: str,
        source_version: str,
        serial_number: int,
        description: str,
        domain: str | None,
        tags: tuple[str, ...],
        terms: tuple[str, ...],
        columns: tuple[ManualColumnMetadata, ...],
        bucket: str,
        object_key: str,
        csv_sha256: str,
        csv_size_bytes: int,
        row_count: int,
    ) -> None:
        if not external_urn.startswith("urn:li:dataset:"):
            raise ValidationError("Manual metadata submissions require a DataHub dataset target.")
        if not source_version.strip() or "\x00" in source_version:
            raise ValidationError("The source version is invalid.")
        if serial_number < 1 or csv_size_bytes < 1 or row_count < 1:
            raise ValidationError("The manual metadata receipt is invalid.")
        if len(csv_sha256) != 64 or any(value not in "0123456789abcdef" for value in csv_sha256):
            raise ValidationError("The manual metadata CSV hash is invalid.")
        text_values = (description, bucket, object_key, *(() if domain is None else (domain,)))
        for value in text_values:
            if "\x00" in value:
                raise ValidationError("Manual metadata text must not contain NUL characters.")
        if len(description) > 10_000 or (domain is not None and len(domain) > 1_000):
            raise ValidationError("Manual metadata text exceeds the allowed length.")
        if len(tags) > 100 or len(terms) > 100 or len(columns) > 2_000:
            raise ValidationError("Manual metadata contains too many values.")
        if len(set(tags)) != len(tags) or len(set(terms)) != len(terms):
            raise ValidationError("Manual metadata values must be unique.")
        if len({column.field_path for column in columns}) != len(columns):
            raise ValidationError("Manual metadata column paths must be unique.")
        for value in (*tags, *terms):
            if not value or len(value) > 1_000 or "\x00" in value:
                raise ValidationError("A controlled metadata reference is invalid.")
        for column in columns:
            if (
                not column.field_path
                or len(column.field_path) > 2_000
                or "\x00" in column.field_path
            ):
                raise ValidationError("A column field path is invalid.")
            if len(column.description) > 10_000 or "\x00" in column.description:
                raise ValidationError("A column description is invalid.")
            if len(column.tags) > 100 or len(column.terms) > 100:
                raise ValidationError("A column contains too many controlled metadata values.")
