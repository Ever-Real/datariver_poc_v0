from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    GovernanceApplyAttemptEvidence,
    GovernanceApplyItemEvidence,
    GovernanceApplyReport,
)
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.domain.governance import ChangeRequest
from datariver.infrastructure.db.governance_apply import SqlGovernanceApplyStore
from datariver.infrastructure.db.models.integration import JobAttemptModel, JobModel


class SqlGovernanceApplyReportReader:
    """Return bounded, redacted apply/read-back evidence for one authorized CR."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        *,
        workspace_id: UUID,
        change_request: ChangeRequest,
    ) -> GovernanceApplyReport:
        job = await self._session.scalar(
            select(JobModel).where(
                JobModel.workspace_id == workspace_id,
                JobModel.job_type == SqlGovernanceApplyStore.job_type,
                JobModel.causation_id == change_request.change_request_id,
            )
        )
        if job is None:
            return GovernanceApplyReport(
                change_request_id=change_request.change_request_id,
                job_id=None,
                state="NOT_STARTED",
                attempt_count=0,
                last_error_code=None,
                expected_hash=None,
                observed_hash=None,
                reconciled=False,
                created_at=None,
                updated_at=None,
                items=(),
                attempts=(),
            )
        attempt_models = list(
            (
                await self._session.scalars(
                    select(JobAttemptModel)
                    .where(
                        JobAttemptModel.workspace_id == workspace_id,
                        JobAttemptModel.job_id == job.id,
                    )
                    .order_by(JobAttemptModel.attempt_no.desc())
                    .limit(20)
                )
            ).all()
        )
        expected_items = tuple(
            {
                "item_id": str(item.item_id),
                "content_hash": item.after_hash or canonical_json_hash(item.after_document),
            }
            for item in change_request.items
        )
        expected_hash = canonical_json_hash(expected_items)
        progress_items = job.progress.get("items")
        observed_hash = job.progress.get("content_hash")
        if progress_items is None:
            progress_items = []
        if not isinstance(progress_items, list) or (
            observed_hash is not None and not _is_sha256(observed_hash)
        ):
            raise ConflictError("The stored governance apply report is invalid.")
        progress_by_item: dict[UUID, Mapping[str, object]] = {}
        for raw in progress_items:
            if not isinstance(raw, Mapping):
                raise ConflictError("The stored governance apply report is invalid.")
            try:
                item_id = UUID(str(raw.get("item_id")))
            except ValueError as error:
                raise ConflictError("The stored governance apply report is invalid.") from error
            content_hash = raw.get("content_hash")
            source_version = raw.get("source_version")
            provider_version = raw.get("provider_version")
            if (
                item_id in progress_by_item
                or not _is_sha256(content_hash)
                or not _optional_bounded_text(source_version, maximum=255)
                or not _optional_bounded_text(provider_version, maximum=255)
            ):
                raise ConflictError("The stored governance apply report is invalid.")
            progress_by_item[item_id] = raw
        expected_ids = {item.item_id for item in change_request.items}
        if not set(progress_by_item) <= expected_ids:
            raise ConflictError("The stored governance apply report is invalid.")
        item_evidence = tuple(
            GovernanceApplyItemEvidence(
                item_id=item.item_id,
                expected_hash=item.after_hash or canonical_json_hash(item.after_document),
                observed_hash=(
                    str(progress_by_item[item.item_id]["content_hash"])
                    if item.item_id in progress_by_item
                    else None
                ),
                source_version=(
                    _optional_text(progress_by_item[item.item_id].get("source_version"))
                    if item.item_id in progress_by_item
                    else None
                ),
                provider_version=(
                    _optional_text(progress_by_item[item.item_id].get("provider_version"))
                    if item.item_id in progress_by_item
                    else None
                ),
            )
            for item in change_request.items
        )
        attempts = tuple(
            GovernanceApplyAttemptEvidence(
                attempt_id=attempt.id,
                attempt_no=attempt.attempt_no,
                state=attempt.state,
                failure_code=attempt.error_class,
                external_response_hash=attempt.external_response_hash,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
            )
            for attempt in attempt_models
        )
        fully_reconciled = (
            job.state == "COMPLETED"
            and observed_hash == expected_hash
            and len(progress_by_item) == len(expected_ids)
            and all(item.observed_hash == item.expected_hash for item in item_evidence)
        )
        return GovernanceApplyReport(
            change_request_id=change_request.change_request_id,
            job_id=job.id,
            state=job.state,
            attempt_count=job.attempts,
            last_error_code=job.last_error_code,
            expected_hash=expected_hash,
            observed_hash=str(observed_hash) if observed_hash is not None else None,
            reconciled=fully_reconciled,
            created_at=job.created_at,
            updated_at=job.updated_at,
            items=item_evidence,
            attempts=attempts,
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _optional_bounded_text(value: object, *, maximum: int) -> bool:
    return value is None or (isinstance(value, str) and 1 <= len(value) <= maximum)


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None
