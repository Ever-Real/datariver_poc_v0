from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from datariver.application.dto import ManualMetadataApplyAttemptEvidence
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    DataHubGateway,
    GovernanceUnitOfWork,
    ObjectStore,
    ProviderMutationLock,
)
from datariver.domain.common import ConflictError, DomainError, canonical_json_hash
from datariver.domain.manual_metadata import (
    ManualMetadataApplyClaim,
    ManualMetadataAspectOutcome,
    ManualMetadataAspectReport,
    ManualMetadataSubmission,
)
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)

MAXIMUM_MANUAL_RECEIPT_BYTES = 5 * 1024 * 1024
_MANUAL_PROVIDER_CHECKPOINT_PREFIX = "datariver-source-sha256:"
_MANUAL_PROVIDER_CHECKPOINT_SEPARATOR = ";provider:"
MANUAL_METADATA_CSV_HEADERS = (
    "record_kind",
    "external_urn",
    "source_version",
    "platform",
    "database_name",
    "schema_name",
    "table_name",
    "column_name",
    "data_type",
    "description",
    "domain",
    "tags",
    "terms",
)


def _encode_manual_provider_checkpoint(*, source_version: str, provider_version: str) -> str:
    if len(source_version) != 64 or any(
        character not in "0123456789abcdef" for character in source_version
    ):
        raise ValueError("The manual provider source checkpoint must be a SHA-256 hash.")
    normalized_provider_version = provider_version.strip()
    if not normalized_provider_version:
        raise ValueError("The manual provider version evidence is empty.")
    prefix = (
        f"{_MANUAL_PROVIDER_CHECKPOINT_PREFIX}{source_version}"
        f"{_MANUAL_PROVIDER_CHECKPOINT_SEPARATOR}"
    )
    return prefix + normalized_provider_version[: 255 - len(prefix)]


def _decode_manual_provider_checkpoint(provider_version: str | None) -> str | None:
    if provider_version is None or not provider_version.startswith(
        _MANUAL_PROVIDER_CHECKPOINT_PREFIX
    ):
        return None
    source_version, separator, provider_evidence = provider_version[
        len(_MANUAL_PROVIDER_CHECKPOINT_PREFIX) :
    ].partition(_MANUAL_PROVIDER_CHECKPOINT_SEPARATOR)
    if (
        not separator
        or not provider_evidence
        or len(source_version) != 64
        or any(character not in "0123456789abcdef" for character in source_version)
    ):
        return None
    return source_version


class ManualMetadataApplyUowFactory(Protocol):
    def __call__(self) -> GovernanceUnitOfWork: ...


class ManualMetadataApplyEligibility(Protocol):
    async def authorize(
        self,
        *,
        submission: ManualMetadataSubmission,
        request_id: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ManualMetadataApplyResult:
    processed: bool
    submission_id: UUID | None = None
    serial_number: int | None = None
    state: str | None = None


class ManualMetadataApplyService:
    """Apply one immutable MANUAL CSV receipt through a service-account-only worker boundary.

    The worker re-reads the private CSV from object storage, verifies its retained hash and shape,
    then read-merges only the typed five DataHub aspect families.  Each aspect has a stable
    idempotency key and a post-write read-back; partial external success can therefore resume
    without treating a provider acceptance as completion.
    """

    def __init__(
        self,
        *,
        datahub: DataHubGateway,
        object_store: ObjectStore,
        uow_factory: ManualMetadataApplyUowFactory,
        eligibility: ManualMetadataApplyEligibility,
        provider_mutation_lock: ProviderMutationLock,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> None:
        self._datahub = datahub
        self._object_store = object_store
        self._uow_factory = uow_factory
        self._eligibility = eligibility
        self._provider_mutation_lock = provider_mutation_lock
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts

    async def run_once(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        request_id: str,
        run_call: RegistrationWorkerCallIdentity | None = None,
    ) -> ManualMetadataApplyResult:
        claim = await self._claim_next(
            workspace_id=workspace_id,
            worker_subject_id=worker_subject_id,
            run_call=run_call,
        )
        if claim is None:
            return ManualMetadataApplyResult(processed=False)
        if isinstance(claim, RegistrationWorkerCallReplay):
            return ManualMetadataApplyResult(
                processed=bool(claim.result["processed"]),
                submission_id=(
                    UUID(str(claim.result["submission_id"]))
                    if claim.result.get("submission_id") is not None
                    else None
                ),
                serial_number=(
                    int(claim.result["serial_number"])
                    if claim.result.get("serial_number") is not None
                    else None
                ),
                state=(
                    str(claim.result["state"]) if claim.result.get("state") is not None else None
                ),
            )
        submission = claim.submission
        try:
            await self._renew_lease(claim)
            await self._eligibility.authorize(
                submission=submission,
                request_id=f"{request_id}:claim",
            )
            await self._verify_csv_receipt(submission)
            await self._renew_lease(claim)
            await self._apply_submission(claim, request_id=request_id)
            await self._renew_lease(claim)
            await self._eligibility.authorize(
                submission=submission,
                request_id=f"{request_id}:complete",
            )
        except DomainError as error:
            state = await self._mark_failed(
                claim=claim,
                error_code=self._error_code(error),
                retryable=self._retryable(error),
            )
            return ManualMetadataApplyResult(
                processed=True,
                submission_id=submission.submission_id,
                serial_number=submission.serial_number,
                state=state,
            )
        except Exception as error:
            state = await self._mark_failed(
                claim=claim,
                error_code=f"UNEXPECTED_{type(error).__name__}"[:100],
                retryable=True,
            )
            return ManualMetadataApplyResult(
                processed=True,
                submission_id=submission.submission_id,
                serial_number=submission.serial_number,
                state=state,
            )
        applied = await self._mark_applied(claim=claim)
        if not applied:
            return ManualMetadataApplyResult(
                processed=True,
                submission_id=submission.submission_id,
                serial_number=submission.serial_number,
                state="SUPERSEDED",
            )
        return ManualMetadataApplyResult(
            processed=True,
            submission_id=submission.submission_id,
            serial_number=submission.serial_number,
            state="APPLIED",
        )

    async def _claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        run_call: RegistrationWorkerCallIdentity | None,
    ) -> ManualMetadataApplyClaim | RegistrationWorkerCallReplay | None:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=worker_subject_id)
            if run_call is None:
                claim = await uow.manual_metadata_submissions.claim_next(
                    workspace_id=workspace_id,
                    worker_subject_id=worker_subject_id,
                    now=self._now(),
                    lease_seconds=self._lease_seconds,
                    maximum_attempts=self._maximum_attempts,
                )
            else:
                claim = await uow.manual_metadata_submissions.claim_next(
                    workspace_id=workspace_id,
                    worker_subject_id=worker_subject_id,
                    now=self._now(),
                    lease_seconds=self._lease_seconds,
                    maximum_attempts=self._maximum_attempts,
                    run_call=run_call,
                )
            await uow.commit()
            return claim

    async def _mark_applied(self, *, claim: ManualMetadataApplyClaim) -> bool:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=claim.submission.workspace_id,
                subject_id=claim.worker_subject_id,
            )
            current = await uow.manual_metadata_submissions.complete(claim=claim, now=self._now())
            if current is None:
                await uow.commit()
                return False
            await uow.outbox.add_events(current.events)
            await uow.commit()
            return True

    async def _mark_failed(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        error_code: str,
        retryable: bool,
    ) -> str:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=claim.submission.workspace_id,
                subject_id=claim.worker_subject_id,
            )
            state = await uow.manual_metadata_submissions.fail(
                claim=claim,
                now=self._now(),
                error_code=error_code,
                retryable=retryable,
                maximum_attempts=self._maximum_attempts,
            )
            await uow.commit()
            return state or "SUPERSEDED"

    async def _verify_csv_receipt(self, submission: ManualMetadataSubmission) -> None:
        payload = await self._read_limited_object(
            bucket=submission.bucket,
            object_key=submission.object_key,
        )
        if len(payload) != submission.csv_size_bytes:
            raise ConflictError(
                "The manual metadata CSV receipt size does not reconcile.",
                details={"code": "CSV_RECEIPT_SIZE_MISMATCH"},
            )
        if hashlib.sha256(payload).hexdigest() != submission.csv_sha256:
            raise ConflictError(
                "The manual metadata CSV receipt hash does not reconcile.",
                details={"code": "CSV_RECEIPT_HASH_MISMATCH"},
            )
        try:
            reader = csv.DictReader(io.StringIO(payload.decode("utf-8")))
            if tuple(reader.fieldnames or ()) != MANUAL_METADATA_CSV_HEADERS:
                raise csv.Error("unexpected header")
            rows = list(reader)
        except (UnicodeDecodeError, csv.Error) as error:
            raise ConflictError(
                "The manual metadata CSV receipt is invalid.",
                details={"code": "CSV_RECEIPT_INVALID"},
            ) from error
        if len(rows) != submission.row_count or not rows:
            raise ConflictError(
                "The manual metadata CSV receipt row count does not reconcile.",
                details={"code": "CSV_RECEIPT_ROW_COUNT_MISMATCH"},
            )
        table_rows = [row for row in rows if row.get("record_kind") == "TABLE"]
        column_rows = [row for row in rows if row.get("record_kind") == "COLUMN"]
        if (
            len(table_rows) != 1
            or len(column_rows) != len(submission.columns)
            or len(table_rows) + len(column_rows) != len(rows)
        ):
            raise ConflictError(
                "The manual metadata CSV receipt shape is invalid.",
                details={"code": "CSV_RECEIPT_SHAPE_MISMATCH"},
            )
        table = table_rows[0]
        if (
            table.get("external_urn") != submission.external_urn
            or table.get("source_version") != submission.source_version
            or table.get("description") != submission.description
            or table.get("domain", "") != (submission.domain or "")
            or tuple(self._csv_refs(table.get("tags"))) != submission.tags
            or tuple(self._csv_refs(table.get("terms"))) != submission.terms
        ):
            raise ConflictError(
                "The manual metadata CSV receipt does not match its immutable submission.",
                details={"code": "CSV_RECEIPT_PAYLOAD_MISMATCH"},
            )
        expected_columns = {
            column.field_path: (column.description, column.tags, column.terms)
            for column in submission.columns
        }
        actual_columns = {
            str(row.get("column_name", "")): (
                str(row.get("description", "")),
                tuple(self._csv_refs(row.get("tags"))),
                tuple(self._csv_refs(row.get("terms"))),
            )
            for row in column_rows
        }
        if actual_columns != expected_columns:
            raise ConflictError(
                "The manual metadata CSV column rows do not match their immutable submission.",
                details={"code": "CSV_RECEIPT_COLUMNS_MISMATCH"},
            )

    async def _read_limited_object(self, *, bucket: str, object_key: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in self._object_store.iter_object_chunks(
            bucket=bucket, object_key=object_key
        ):
            if not isinstance(chunk, bytes):
                raise ExternalDependencyError(
                    "Object storage returned an invalid manual metadata receipt.",
                    dependency="object_store",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            total += len(chunk)
            if total > MAXIMUM_MANUAL_RECEIPT_BYTES:
                raise ConflictError(
                    "The manual metadata CSV receipt exceeds the worker safety bound.",
                    details={"code": "CSV_RECEIPT_TOO_LARGE"},
                )
            chunks.append(chunk)
        if not chunks:
            raise ConflictError(
                "The manual metadata CSV receipt is missing.",
                details={"code": "CSV_RECEIPT_MISSING"},
            )
        return b"".join(chunks)

    async def _apply_submission(self, claim: ManualMetadataApplyClaim, *, request_id: str) -> None:
        submission = claim.submission
        await self._renew_lease(claim)
        async with self._provider_mutation_lock.hold(
            workspace_id=submission.workspace_id,
            provider="DATAHUB",
            target_ref=submission.external_urn,
            aspect_name="*",
            on_wait=lambda: self._renew_lease(claim),
        ):
            await self._renew_lease(claim)
            provider_asset = await self._datahub.get_asset(submission.external_urn)
            if (
                provider_asset.raw_version != submission.provider_source_version
                and provider_asset.raw_version != await self._resume_provider_checkpoint(claim)
            ):
                raise ConflictError(
                    "The DataHub asset changed after the Manual submission was accepted.",
                    details={"code": "PROVIDER_SOURCE_VERSION_MISMATCH"},
                )
            aspect_operations: tuple[tuple[int, str, Callable[[dict[str, Any]], None]], ...] = (
                (
                    1,
                    "datasetProperties",
                    lambda document: self._set_description(document, submission.description),
                ),
                (
                    2,
                    "domains",
                    lambda document: self._set_controlled_refs(
                        document,
                        field="domains",
                        nested=None,
                        refs=(() if submission.domain is None else (submission.domain,)),
                    ),
                ),
                (
                    3,
                    "globalTags",
                    lambda document: self._set_controlled_refs(
                        document,
                        field="tags",
                        nested="tag",
                        refs=submission.tags,
                    ),
                ),
                (
                    4,
                    "glossaryTerms",
                    lambda document: self._set_controlled_refs(
                        document,
                        field="terms",
                        nested="urn",
                        refs=submission.terms,
                    ),
                ),
                (
                    5,
                    "schemaMetadata",
                    lambda document: self._set_schema_metadata(document, submission),
                ),
            )
            for aspect_ordinal, aspect_name, mutate in aspect_operations:
                await self._apply_aspect_locked(
                    claim=claim,
                    submission=submission,
                    request_id=request_id,
                    aspect_ordinal=aspect_ordinal,
                    aspect_name=aspect_name,
                    mutate=mutate,
                )

    async def _apply_aspect_locked(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        submission: ManualMetadataSubmission,
        request_id: str,
        aspect_ordinal: int,
        aspect_name: str,
        mutate: Callable[[dict[str, Any]], None],
    ) -> None:
        await self._eligibility.authorize(
            submission=submission,
            request_id=f"{request_id}:{aspect_name}",
        )
        await self._renew_lease(claim)
        try:
            current = await self._datahub.read_aspect(
                external_urn=submission.external_urn,
                aspect_name=aspect_name,
            )
        except ExternalDependencyError as error:
            failure_code = self._aspect_provider_code(aspect_name, error)
            await self._record_aspect_report(
                claim=claim,
                report=ManualMetadataAspectReport(
                    aspect_name=aspect_name,
                    aspect_ordinal=aspect_ordinal,
                    outcome=ManualMetadataAspectOutcome.FAILED_BEFORE_WRITE,
                    before_hash=None,
                    expected_hash=None,
                    observed_hash=None,
                    write_attempted=False,
                    failure_code=failure_code,
                    provider_operation_id_hash=None,
                    provider_version=None,
                    provider_response_hash=None,
                    observed_at=self._now(),
                ),
            )
            raise ExternalDependencyError(
                "DataHub could not read a typed manual metadata aspect.",
                dependency="datahub",
                retryable=bool(error.details.get("retryable")),
                provider_code=failure_code,
            ) from error
        document = self._mutable_document(current.document)
        mutate(document)
        expected_hash = canonical_json_hash(document)
        if current.content_hash == expected_hash:
            await self._record_aspect_report(
                claim=claim,
                report=ManualMetadataAspectReport(
                    aspect_name=aspect_name,
                    aspect_ordinal=aspect_ordinal,
                    outcome=ManualMetadataAspectOutcome.ALREADY_MATCHED,
                    before_hash=current.content_hash,
                    expected_hash=expected_hash,
                    observed_hash=current.content_hash,
                    write_attempted=False,
                    failure_code=None,
                    provider_operation_id_hash=None,
                    provider_version=None,
                    provider_response_hash=None,
                    observed_at=current.observed_at,
                ),
            )
            return
        await self._renew_lease(claim)
        try:
            receipt = await self._datahub.apply_change(
                external_urn=submission.external_urn,
                aspect_name=aspect_name,
                document=document,
                idempotency_key=(
                    f"manual-metadata:{submission.submission_id}:{aspect_name}:{expected_hash}"[
                        :200
                    ]
                ),
            )
        except ExternalDependencyError as error:
            provider_code = self._aspect_provider_code(aspect_name, error)
            await self._record_aspect_report(
                claim=claim,
                report=ManualMetadataAspectReport(
                    aspect_name=aspect_name,
                    aspect_ordinal=aspect_ordinal,
                    outcome=ManualMetadataAspectOutcome.WRITE_REJECTED,
                    before_hash=current.content_hash,
                    expected_hash=expected_hash,
                    observed_hash=None,
                    write_attempted=True,
                    failure_code=provider_code,
                    provider_operation_id_hash=None,
                    provider_version=None,
                    provider_response_hash=None,
                    observed_at=self._now(),
                ),
            )
            raise ExternalDependencyError(
                "DataHub rejected a typed manual metadata aspect.",
                dependency="datahub",
                retryable=bool(error.details.get("retryable")),
                provider_code=provider_code,
            ) from error
        await self._renew_lease(claim)
        try:
            observed = await self._datahub.read_aspect(
                external_urn=submission.external_urn,
                aspect_name=aspect_name,
            )
        except ExternalDependencyError as error:
            failure_code = self._aspect_provider_code(aspect_name, error)
            await self._record_aspect_report(
                claim=claim,
                report=ManualMetadataAspectReport(
                    aspect_name=aspect_name,
                    aspect_ordinal=aspect_ordinal,
                    outcome=ManualMetadataAspectOutcome.READBACK_FAILED,
                    before_hash=current.content_hash,
                    expected_hash=expected_hash,
                    observed_hash=None,
                    write_attempted=True,
                    failure_code=failure_code,
                    provider_operation_id_hash=hashlib.sha256(
                        receipt.operation_id.encode()
                    ).hexdigest(),
                    provider_version=receipt.provider_version,
                    provider_response_hash=receipt.response_hash,
                    observed_at=self._now(),
                ),
            )
            raise ExternalDependencyError(
                "DataHub could not read back a typed manual metadata aspect.",
                dependency="datahub",
                retryable=bool(error.details.get("retryable")),
                provider_code=failure_code,
            ) from error
        if observed.content_hash != expected_hash:
            failure_code = f"{aspect_name.upper()}_READBACK_MISMATCH"[:100]
            await self._record_aspect_report(
                claim=claim,
                report=ManualMetadataAspectReport(
                    aspect_name=aspect_name,
                    aspect_ordinal=aspect_ordinal,
                    outcome=ManualMetadataAspectOutcome.READBACK_MISMATCH,
                    before_hash=current.content_hash,
                    expected_hash=expected_hash,
                    observed_hash=observed.content_hash,
                    write_attempted=True,
                    failure_code=failure_code,
                    provider_operation_id_hash=hashlib.sha256(
                        receipt.operation_id.encode()
                    ).hexdigest(),
                    provider_version=receipt.provider_version,
                    provider_response_hash=receipt.response_hash,
                    observed_at=observed.observed_at,
                ),
            )
            raise ExternalDependencyError(
                "DataHub did not reconcile to the manual metadata receipt.",
                dependency="datahub",
                retryable=True,
                provider_code=failure_code,
            )
        try:
            provider_asset = await self._datahub.get_asset(submission.external_urn)
            provider_checkpoint = _encode_manual_provider_checkpoint(
                source_version=provider_asset.raw_version,
                provider_version=receipt.provider_version,
            )
        except (ExternalDependencyError, ValueError) as error:
            if isinstance(error, ExternalDependencyError):
                retryable = bool(error.details.get("retryable"))
                provider_code = self._aspect_provider_code(aspect_name, error)
            else:
                retryable = False
                provider_code = f"{aspect_name.upper()}_INVALID_SOURCE_CHECKPOINT"[:100]
            await self._record_aspect_report(
                claim=claim,
                report=ManualMetadataAspectReport(
                    aspect_name=aspect_name,
                    aspect_ordinal=aspect_ordinal,
                    outcome=ManualMetadataAspectOutcome.READBACK_FAILED,
                    before_hash=current.content_hash,
                    expected_hash=expected_hash,
                    observed_hash=None,
                    write_attempted=True,
                    failure_code=provider_code,
                    provider_operation_id_hash=hashlib.sha256(
                        receipt.operation_id.encode()
                    ).hexdigest(),
                    provider_version=receipt.provider_version,
                    provider_response_hash=receipt.response_hash,
                    observed_at=self._now(),
                ),
            )
            raise ExternalDependencyError(
                "DataHub could not establish the aggregate Manual retry checkpoint.",
                dependency="datahub",
                retryable=retryable,
                provider_code=provider_code,
            ) from error
        await self._record_aspect_report(
            claim=claim,
            report=ManualMetadataAspectReport(
                aspect_name=aspect_name,
                aspect_ordinal=aspect_ordinal,
                outcome=ManualMetadataAspectOutcome.APPLIED_VERIFIED,
                before_hash=current.content_hash,
                expected_hash=expected_hash,
                observed_hash=observed.content_hash,
                write_attempted=True,
                failure_code=None,
                provider_operation_id_hash=hashlib.sha256(
                    receipt.operation_id.encode()
                ).hexdigest(),
                provider_version=provider_checkpoint,
                provider_response_hash=receipt.response_hash,
                observed_at=observed.observed_at,
            ),
        )

    async def _resume_provider_checkpoint(self, claim: ManualMetadataApplyClaim) -> str | None:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=claim.submission.workspace_id,
                subject_id=claim.worker_subject_id,
            )
            attempts = await uow.manual_metadata_submissions.list_attempts(
                workspace_id=claim.submission.workspace_id,
                submission_id=claim.submission.submission_id,
                limit=self._maximum_attempts,
            )
        return self._latest_verified_provider_checkpoint(
            attempts=attempts,
            current_attempt_no=claim.attempt_no,
        )

    @staticmethod
    def _latest_verified_provider_checkpoint(
        *,
        attempts: Sequence[ManualMetadataApplyAttemptEvidence],
        current_attempt_no: int,
    ) -> str | None:
        for attempt in attempts:
            if attempt.attempt_no >= current_attempt_no:
                continue
            checkpoint: str | None = None
            expected_ordinal = 1
            for index, report in enumerate(attempt.aspects):
                if report.aspect_ordinal != expected_ordinal:
                    return None
                if (
                    report.outcome not in {"ALREADY_MATCHED", "APPLIED_VERIFIED"}
                    or report.expected_hash is None
                    or report.expected_hash != report.observed_hash
                ):
                    if index != len(attempt.aspects) - 1:
                        return None
                    break
                if report.outcome == "APPLIED_VERIFIED":
                    checkpoint = _decode_manual_provider_checkpoint(report.provider_version)
                expected_ordinal += 1
            if checkpoint is not None:
                return checkpoint
        return None

    @staticmethod
    def _aspect_provider_code(aspect_name: str, error: ExternalDependencyError) -> str:
        provider_code = str(error.details.get("provider_code") or "UNKNOWN")
        return f"{aspect_name.upper()}_{provider_code}"[:100]

    async def _record_aspect_report(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        report: ManualMetadataAspectReport,
    ) -> None:
        await self._renew_lease(claim)
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=claim.submission.workspace_id,
                subject_id=claim.worker_subject_id,
            )
            recorded = await uow.manual_metadata_submissions.record_aspect_report(
                claim=claim,
                report=report,
            )
            await uow.commit()
        if not recorded:
            raise ConflictError(
                "The manual metadata apply lease was superseded.",
                details={"code": "LEASE_SUPERSEDED"},
            )

    async def _renew_lease(self, claim: ManualMetadataApplyClaim) -> None:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=claim.submission.workspace_id,
                subject_id=claim.worker_subject_id,
            )
            renewed = await uow.manual_metadata_submissions.renew_lease(
                claim=claim,
                lease_seconds=self._lease_seconds,
            )
            await uow.commit()
        if not renewed:
            raise ConflictError(
                "The manual metadata apply lease was superseded.",
                details={"code": "LEASE_SUPERSEDED"},
            )

    @staticmethod
    def _set_description(document: dict[str, Any], description: str) -> None:
        if description:
            document["description"] = description
        else:
            document.pop("description", None)

    @staticmethod
    def _set_controlled_refs(
        document: dict[str, Any], *, field: str, nested: str | None, refs: tuple[str, ...]
    ) -> None:
        if not refs:
            if field in document:
                document[field] = []
            return
        document[field] = list(refs) if nested is None else [{nested: ref} for ref in refs]

    @staticmethod
    def _set_schema_metadata(
        document: dict[str, Any], submission: ManualMetadataSubmission
    ) -> None:
        fields = document.get("fields")
        if not isinstance(fields, list):
            raise ExternalDependencyError(
                "DataHub returned an invalid schemaMetadata fields document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        by_path = {
            field.get("fieldPath"): field
            for field in fields
            if isinstance(field, dict) and isinstance(field.get("fieldPath"), str)
        }
        if len(by_path) != len(fields) or set(by_path) != {
            column.field_path for column in submission.columns
        }:
            raise ConflictError(
                "The DataHub schema changed after the manual submission was staged.",
                details={"code": "SCHEMA_FIELD_DRIFT"},
            )
        for column in submission.columns:
            field = by_path[column.field_path]
            if column.description:
                field["description"] = column.description
            else:
                field.pop("description", None)
            ManualMetadataApplyService._set_nested_controlled_refs(
                field,
                container="globalTags",
                field="tags",
                nested="tag",
                refs=column.tags,
            )
            ManualMetadataApplyService._set_nested_controlled_refs(
                field,
                container="glossaryTerms",
                field="terms",
                nested="urn",
                refs=column.terms,
            )

    @staticmethod
    def _set_nested_controlled_refs(
        document: dict[str, Any],
        *,
        container: str,
        field: str,
        nested: str,
        refs: tuple[str, ...],
    ) -> None:
        existing = document.get(container)
        if existing is None and not refs:
            return
        value = existing if isinstance(existing, dict) else {}
        value[field] = [{nested: ref} for ref in refs]
        document[container] = value

    @staticmethod
    def _mutable_document(value: Mapping[str, Any]) -> dict[str, Any]:
        def copy(item: Any) -> Any:
            if isinstance(item, Mapping):
                if any(not isinstance(key, str) for key in item):
                    raise ExternalDependencyError(
                        "DataHub returned an invalid metadata document.",
                        dependency="datahub",
                        retryable=False,
                        provider_code="INVALID_RESPONSE",
                    )
                return {key: copy(nested) for key, nested in item.items()}
            if isinstance(item, tuple | list):
                return [copy(nested) for nested in item]
            if item is None or isinstance(item, str | bool | int | float):
                return item
            raise ExternalDependencyError(
                "DataHub returned an invalid metadata document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )

        copied = copy(value)
        if not isinstance(copied, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid metadata document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        return copied

    @staticmethod
    def _csv_refs(value: str | None) -> tuple[str, ...]:
        return tuple(item for item in (value or "").split(",") if item)

    @staticmethod
    def _retryable(error: DomainError) -> bool:
        return isinstance(error, ExternalDependencyError) and bool(error.details.get("retryable"))

    @staticmethod
    def _error_code(error: DomainError) -> str:
        return str(error.details.get("code") or error.details.get("provider_code") or error.code)[
            :100
        ]

    @staticmethod
    def _now() -> datetime:
        from datariver.domain.common import utc_now

        return utc_now()
