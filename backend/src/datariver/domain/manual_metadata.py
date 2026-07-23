from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import (
    DomainEvent,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.registration_worker import RegistrationWorkerCallIdentity


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


class ManualMetadataAspectOutcome(StrEnum):
    ALREADY_MATCHED = "ALREADY_MATCHED"
    APPLIED_VERIFIED = "APPLIED_VERIFIED"
    FAILED_BEFORE_WRITE = "FAILED_BEFORE_WRITE"
    WRITE_REJECTED = "WRITE_REJECTED"
    READBACK_FAILED = "READBACK_FAILED"
    READBACK_MISMATCH = "READBACK_MISMATCH"


@dataclass(frozen=True, slots=True)
class ManualMetadataApplyClaim:
    submission: ManualMetadataSubmission
    attempt_id: UUID
    attempt_no: int
    lease_epoch: int
    lease_token: str
    worker_subject_id: UUID
    run_call: RegistrationWorkerCallIdentity | None = None


@dataclass(frozen=True, slots=True)
class ManualMetadataAspectReport:
    aspect_name: str
    aspect_ordinal: int
    outcome: ManualMetadataAspectOutcome
    before_hash: str | None
    expected_hash: str | None
    observed_hash: str | None
    write_attempted: bool
    failure_code: str | None
    provider_operation_id_hash: str | None
    provider_version: str | None
    provider_response_hash: str | None
    observed_at: datetime

    def content_hash(self) -> str:
        return canonical_json_hash(
            {
                "aspect_name": self.aspect_name,
                "aspect_ordinal": self.aspect_ordinal,
                "before_hash": self.before_hash,
                "expected_hash": self.expected_hash,
                "failure_code": self.failure_code,
                "observed_hash": self.observed_hash,
                "outcome": self.outcome.value,
                "provider_operation_id_hash": self.provider_operation_id_hash,
                "provider_response_hash": self.provider_response_hash,
                "provider_version": self.provider_version,
                "write_attempted": self.write_attempted,
            }
        )


@dataclass(slots=True)
class ManualMetadataSubmission:
    submission_id: UUID
    workspace_id: UUID
    asset_id: UUID
    external_urn: str
    requester_id: UUID
    source_version: str
    provider_source_version: str
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
    next_attempt_at: datetime | None = None
    lease_epoch: int = 0
    lease_token_hash: str | None = None
    lease_owner_id: UUID | None = None
    lease_started_at: datetime | None = None
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
        provider_source_version: str,
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
            provider_source_version=provider_source_version,
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
            provider_source_version=provider_source_version,
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
            next_attempt_at=now,
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
                    "provider_source_version": provider_source_version,
                },
            )
        )
        return submission

    def claim_for_apply(
        self,
        *,
        now: datetime,
        lease_seconds: int,
        lease_token_hash: str,
        lease_owner_id: UUID,
    ) -> None:
        if lease_seconds < 1:
            raise ValidationError("The manual metadata apply lease is invalid.")
        if self.state is ManualMetadataSubmissionState.APPLIED:
            raise ValidationError("The manual metadata submission is already applied.")
        if self.state is ManualMetadataSubmissionState.FAILED:
            raise ValidationError("The manual metadata submission is terminally failed.")
        if (
            self.state is ManualMetadataSubmissionState.QUEUED
            and self.next_attempt_at is not None
            and self.next_attempt_at > now
        ):
            raise ValidationError("The manual metadata submission retry is not due.")
        if (
            self.state is ManualMetadataSubmissionState.APPLYING
            and self.lease_expires_at is not None
            and self.lease_expires_at > now
        ):
            raise ValidationError("The manual metadata submission is already being applied.")
        self.state = ManualMetadataSubmissionState.APPLYING
        self.attempts += 1
        self.lease_epoch += 1
        self.lease_token_hash = self._validate_lease_token_hash(lease_token_hash)
        self.lease_owner_id = lease_owner_id
        self.lease_started_at = now
        self.lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.next_attempt_at = None
        self.last_error_code = None
        self.updated_at = now
        self.version += 1

    def mark_applied(self, *, now: datetime) -> None:
        if self.state is not ManualMetadataSubmissionState.APPLYING:
            raise ValidationError("Only an applying manual metadata submission may complete.")
        self.state = ManualMetadataSubmissionState.APPLIED
        self.applied_at = now
        self._clear_lease()
        self.next_attempt_at = None
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
        self._clear_lease()
        self.next_attempt_at = (
            now + timedelta(seconds=min(2 ** min(self.attempts, 6), 60)) if retryable else None
        )
        self.last_error_code = error_code
        self.updated_at = now
        self.version += 1

    def fence_matches(
        self,
        *,
        now: datetime,
        lease_epoch: int,
        lease_token_hash: str,
        lease_owner_id: UUID,
    ) -> bool:
        return (
            self.state is ManualMetadataSubmissionState.APPLYING
            and self.lease_epoch == lease_epoch
            and self.lease_token_hash == lease_token_hash
            and self.lease_owner_id == lease_owner_id
            and self.lease_expires_at is not None
            and self.lease_expires_at > now
        )

    def _clear_lease(self) -> None:
        self.lease_token_hash = None
        self.lease_owner_id = None
        self.lease_started_at = None
        self.lease_expires_at = None

    @staticmethod
    def _validate_lease_token_hash(value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValidationError("The manual metadata apply lease token is invalid.")
        return value

    @staticmethod
    def _validate(
        *,
        external_urn: str,
        source_version: str,
        provider_source_version: str,
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
        if len(provider_source_version) != 64 or any(
            value not in "0123456789abcdef" for value in provider_source_version
        ):
            raise ValidationError("The provider source version is invalid.")
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
            if len(set(column.tags)) != len(column.tags) or len(set(column.terms)) != len(
                column.terms
            ):
                raise ValidationError("Column controlled metadata values must be unique.")
            for value in (*column.tags, *column.terms):
                if not value or len(value) > 1_000 or "\x00" in value:
                    raise ValidationError("A column controlled metadata reference is invalid.")
