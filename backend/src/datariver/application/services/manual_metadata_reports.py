from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.application.dto import ManualMetadataApplyAttemptEvidence
from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.manual_metadata import ManualMetadataSubmission


class ManualMetadataReportUowFactory(Protocol):
    def __call__(self) -> GovernanceUnitOfWork: ...


@dataclass(frozen=True, slots=True)
class ManualMetadataSubmissionPage:
    items: tuple[ManualMetadataSubmission, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ManualMetadataSubmissionReport:
    submission: ManualMetadataSubmission
    attempts: tuple[ManualMetadataApplyAttemptEvidence, ...]


class ManualMetadataReportService:
    def __init__(
        self,
        *,
        authorization: AuthorizationService,
        uow_factory: ManualMetadataReportUowFactory,
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory

    async def list(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        scope: str,
        state: str | None,
        cursor: str | None,
        limit: int,
    ) -> ManualMetadataSubmissionPage:
        self._validate_scope(scope=scope, subject=subject)
        await self._authorize_collection(
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        context = canonical_json_hash(
            {
                "contract": "manual-metadata-submission-cursor-v1",
                "scope": scope,
                "state": state,
                "subject_id": str(subject.subject_id),
                "workspace_id": str(workspace_id),
            }
        )
        before_created_at, before_id = _unwrap_cursor(cursor, expected_context=context)
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            values = tuple(
                await uow.manual_metadata_submissions.list(
                    workspace_id=workspace_id,
                    requester_id=subject.subject_id if scope == "mine" else None,
                    state=state,
                    before_created_at=before_created_at,
                    before_id=before_id,
                    limit=limit + 1,
                )
            )
            await uow.commit()
        visible = values[:limit]
        next_cursor = (
            _wrap_cursor(
                created_at=visible[-1].created_at,
                submission_id=visible[-1].submission_id,
                context=context,
            )
            if len(values) > limit and visible
            else None
        )
        return ManualMetadataSubmissionPage(items=visible, next_cursor=next_cursor)

    async def get(
        self,
        *,
        workspace_id: UUID,
        submission_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ManualMetadataSubmissionReport:
        await self._authorize_collection(
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            submission = await uow.manual_metadata_submissions.get(
                workspace_id=workspace_id,
                submission_id=submission_id,
            )
            if submission is None or (
                submission.requester_id != subject.subject_id
                and "security-administrators" not in subject.groups
            ):
                raise NotFoundError("The manual metadata submission does not exist.")
            attempts = tuple(
                await uow.manual_metadata_submissions.list_attempts(
                    workspace_id=workspace_id,
                    submission_id=submission_id,
                    limit=20,
                )
            )
            await uow.commit()
        return ManualMetadataSubmissionReport(submission=submission, attempts=attempts)

    async def _authorize_collection(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="manual_metadata_submission_collection",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.REGISTRATION_READ,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    def _validate_scope(*, scope: str, subject: SubjectAttributes) -> None:
        if scope not in {"mine", "workspace"}:
            raise ValidationError("The manual metadata submission scope is invalid.")
        if scope == "workspace" and "security-administrators" not in subject.groups:
            raise ForbiddenError("Workspace-wide registration history requires an administrator.")


def _wrap_cursor(*, created_at: datetime, submission_id: UUID, context: str) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "context": context,
            "created_at": created_at.isoformat(),
            "submission_id": str(submission_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _unwrap_cursor(
    cursor: str | None,
    *,
    expected_context: str,
) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        document = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (
            not isinstance(document, dict)
            or set(document) != {"v", "context", "created_at", "submission_id"}
            or document.get("v") != 1
            or document.get("context") != expected_context
        ):
            raise ValueError
        created_at = datetime.fromisoformat(str(document["created_at"]))
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(str(document["submission_id"]))
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as error:
        raise ValidationError(
            "The manual metadata submission cursor is stale or invalid."
        ) from error
