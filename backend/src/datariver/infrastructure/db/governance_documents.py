from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from datariver.application.catalog_security import catalog_permission_scope_hash
from datariver.application.governance_document_attachments import (
    GovernanceDocumentAttachmentSource,
)
from datariver.application.governance_document_ports import (
    GovernanceDocumentProjectionRepository,
    GovernanceDocumentRepository,
)
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    PreconditionFailedError,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.governance_documents import (
    MAXIMUM_ATTACHMENTS_PER_VERSION,
    GovernanceDocumentArtifactState,
    GovernanceDocumentAttachment,
    GovernanceDocumentCategory,
    GovernanceDocumentDetail,
    GovernanceDocumentKind,
    GovernanceDocumentKnowledgeState,
    GovernanceDocumentPage,
    GovernanceDocumentProjectionClaim,
    GovernanceDocumentReview,
    GovernanceDocumentReviewDecision,
    GovernanceDocumentSourceFormat,
    GovernanceDocumentState,
    GovernanceDocumentSummary,
    GovernanceDocumentVersion,
    GovernanceDocumentVersionState,
    GovernanceKnowledgeEvidence,
    version_tag,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.governance_documents import (
    GovernanceDocumentArtifactReceiptModel,
    GovernanceDocumentAttachmentModel,
    GovernanceDocumentEventModel,
    GovernanceDocumentKnowledgeChunkModel,
    GovernanceDocumentModel,
    GovernanceDocumentProjectionReceiptModel,
    GovernanceDocumentReviewModel,
    GovernanceDocumentVersionModel,
)
from datariver.infrastructure.db.models.integration import OutboxEventModel
from datariver.infrastructure.db.models.platform import SubjectModel, WorkspaceMembershipModel
from datariver.infrastructure.db.rls import set_security_context

_CREATE_OPERATION = "governance.document.create.v1"
_VERSION_OPERATION = "governance.document.version.create.v1"
_SUBMIT_OPERATION = "governance.document.version.submit.v1"
_REVIEW_OPERATION = "governance.document.version.review.v1"
_ARCHIVE_OPERATION = "governance.document.archive.v1"
_ATTACHMENT_OPERATION = "governance.document.attachment.add.v1"
_MAXIMUM_CURSOR_BYTES = 2_000


class SqlGovernanceDocumentRepository(
    GovernanceDocumentRepository,
    GovernanceDocumentProjectionRepository,
):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._idempotency = SqlIdempotencyStore(session)

    async def database_now(self) -> datetime:
        value = await self._session.scalar(select(func.transaction_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("The database did not return a Governance Document clock.")
        return value

    async def list_documents(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        kind: GovernanceDocumentKind | None,
        category: GovernanceDocumentCategory | None,
        state: GovernanceDocumentState | None,
        include_archived: bool,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> GovernanceDocumentPage:
        if not 1 <= limit <= 100:
            raise ValidationError("The Governance Document page size is invalid.")
        normalized_query = (query or "").strip()
        if len(normalized_query) > 200:
            raise ValidationError("The Governance Document query is too long.")
        cursor_values = _decode_cursor(
            cursor,
            workspace_id=workspace_id,
            permission_scope=catalog_permission_scope_hash(subject),
            kind=kind,
            category=category,
            state=state,
            include_archived=include_archived,
            query=normalized_query,
            limit=limit,
        )
        conditions: list[ColumnElement[bool]] = [
            GovernanceDocumentModel.workspace_id == workspace_id,
            GovernanceDocumentModel.classification <= int(subject.clearance),
            *_subject_scope_conditions(subject),
        ]
        if kind is not None:
            conditions.append(GovernanceDocumentModel.kind == kind.value)
        if category is not None:
            conditions.append(GovernanceDocumentModel.category == category.value)
        if state is not None:
            conditions.append(GovernanceDocumentModel.state == state.value)
        if not include_archived:
            conditions.append(
                GovernanceDocumentModel.state != GovernanceDocumentState.ARCHIVED.value
            )
        if normalized_query:
            escaped = (
                normalized_query.casefold()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            conditions.append(
                or_(
                    func.lower(GovernanceDocumentModel.title).like(
                        f"%{escaped}%",
                        escape="\\",
                    ),
                    func.lower(GovernanceDocumentModel.summary).like(
                        f"%{escaped}%",
                        escape="\\",
                    ),
                )
            )
        if cursor_values is not None:
            cursor_time, cursor_id = cursor_values
            conditions.append(
                or_(
                    GovernanceDocumentModel.updated_at < cursor_time,
                    and_(
                        GovernanceDocumentModel.updated_at == cursor_time,
                        GovernanceDocumentModel.id < cursor_id,
                    ),
                )
            )
        rows = list(
            (
                await self._session.scalars(
                    select(GovernanceDocumentModel)
                    .where(*conditions)
                    .order_by(
                        desc(GovernanceDocumentModel.updated_at),
                        desc(GovernanceDocumentModel.id),
                    )
                    .limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        selected = rows[:limit]
        version_numbers = await self._current_version_numbers(
            workspace_id=workspace_id,
            documents=selected,
        )
        next_cursor = None
        if has_more and selected:
            last = selected[-1]
            next_cursor = _encode_cursor(
                workspace_id=workspace_id,
                permission_scope=catalog_permission_scope_hash(subject),
                kind=kind,
                category=category,
                state=state,
                include_archived=include_archived,
                query=normalized_query,
                limit=limit,
                updated_at=last.updated_at,
                document_id=last.id,
            )
        return GovernanceDocumentPage(
            items=tuple(
                _summary(row, current_version_number=version_numbers.get(row.id))
                for row in selected
            ),
            next_cursor=next_cursor,
        )

    async def get_document(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        subject: SubjectAttributes,
    ) -> GovernanceDocumentDetail | None:
        document = (
            await self._session.scalars(
                select(GovernanceDocumentModel).where(
                    GovernanceDocumentModel.workspace_id == workspace_id,
                    GovernanceDocumentModel.id == document_id,
                    GovernanceDocumentModel.classification <= int(subject.clearance),
                    *_subject_scope_conditions(subject),
                )
            )
        ).one_or_none()
        if document is None:
            return None
        return await self._detail(document, subject=subject)

    async def get_published_template_version(
        self,
        *,
        workspace_id: UUID,
        version_id: UUID,
        subject: SubjectAttributes,
    ) -> GovernanceDocumentVersion | None:
        value = (
            await self._session.scalars(
                select(GovernanceDocumentVersionModel)
                .join(
                    GovernanceDocumentModel,
                    and_(
                        GovernanceDocumentModel.workspace_id
                        == GovernanceDocumentVersionModel.workspace_id,
                        GovernanceDocumentModel.id == GovernanceDocumentVersionModel.document_id,
                    ),
                )
                .where(
                    GovernanceDocumentVersionModel.workspace_id == workspace_id,
                    GovernanceDocumentVersionModel.id == version_id,
                    GovernanceDocumentVersionModel.state
                    == GovernanceDocumentVersionState.PUBLISHED.value,
                    GovernanceDocumentModel.kind == GovernanceDocumentKind.TEMPLATE.value,
                    GovernanceDocumentModel.state == GovernanceDocumentState.ACTIVE.value,
                    GovernanceDocumentModel.current_published_version_id == version_id,
                    GovernanceDocumentModel.classification <= int(subject.clearance),
                    *_subject_scope_conditions(subject),
                )
            )
        ).one_or_none()
        return _document_version(value) if value is not None else None

    async def validate_parent_document(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID | None,
        parent_document_id: UUID | None,
        subject: SubjectAttributes,
    ) -> None:
        if parent_document_id is None:
            return
        if parent_document_id == document_id:
            raise ValidationError("A Governance Document cannot be its own parent.")
        parent = (
            await self._session.scalars(
                select(GovernanceDocumentModel).where(
                    GovernanceDocumentModel.workspace_id == workspace_id,
                    GovernanceDocumentModel.id == parent_document_id,
                    GovernanceDocumentModel.kind == GovernanceDocumentKind.DOCUMENT.value,
                    GovernanceDocumentModel.state != GovernanceDocumentState.ARCHIVED.value,
                    GovernanceDocumentModel.classification <= int(subject.clearance),
                    *_subject_scope_conditions(subject),
                )
            )
        ).one_or_none()
        if parent is None:
            raise NotFoundError("The Governance Document parent is unavailable.")
        if document_id is None:
            return
        rows = (
            await self._session.scalars(
                select(GovernanceDocumentVersionModel)
                .where(
                    GovernanceDocumentVersionModel.workspace_id == workspace_id,
                    GovernanceDocumentVersionModel.state.in_(
                        (
                            GovernanceDocumentVersionState.DRAFT.value,
                            GovernanceDocumentVersionState.IN_REVIEW.value,
                            GovernanceDocumentVersionState.PUBLISHED.value,
                        )
                    ),
                )
                .order_by(
                    GovernanceDocumentVersionModel.document_id,
                    desc(GovernanceDocumentVersionModel.version_number),
                )
            )
        ).all()
        effective_parent: dict[UUID, UUID | None] = {}
        for row in rows:
            effective_parent.setdefault(row.document_id, row.parent_document_id)
        visited: set[UUID] = set()
        current: UUID | None = parent_document_id
        while current is not None:
            if current == document_id:
                raise ConflictError("The Governance Document parent would create a cycle.")
            if current in visited:
                raise ConflictError("The Governance Document hierarchy already contains a cycle.")
            visited.add(current)
            current = effective_parent.get(current)

    async def create_document(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
        kind: GovernanceDocumentKind,
        category: GovernanceDocumentCategory,
        title: str,
        summary: str,
        classification: int,
        applicability_scope: str,
        sanitized_html: str,
        plain_text: str,
        content_sha256: str,
        sanitizer_policy_version: str,
        sanitizer_policy_sha256: str,
        source_format: GovernanceDocumentSourceFormat,
        source_template_version_id: UUID | None,
        parent_document_id: UUID | None,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail:
        await self._acquire(workspace_id, idempotency_key, _CREATE_OPERATION)
        replay = await self._replay(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_CREATE_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
        )
        if replay is not None:
            return await self._replayed_detail(
                workspace_id=workspace_id,
                document_id=replay,
            )
        now = await self.database_now()
        document_id = uuid7()
        version_id = uuid7()
        document = GovernanceDocumentModel(
            id=document_id,
            workspace_id=workspace_id,
            kind=kind.value,
            category=category.value,
            title=title,
            summary=summary,
            classification=classification,
            owner_subject_id=actor_id,
            state=GovernanceDocumentState.DRAFT.value,
            version=1,
            created_at=now,
            updated_at=now,
        )
        document_version = GovernanceDocumentVersionModel(
            id=version_id,
            workspace_id=workspace_id,
            document_id=document_id,
            version_number=1,
            version_tag=version_tag(1),
            state=GovernanceDocumentVersionState.DRAFT.value,
            title=title,
            summary=summary,
            applicability_scope=applicability_scope,
            sanitized_html=sanitized_html,
            plain_text=plain_text,
            content_sha256=content_sha256,
            size_bytes=len(sanitized_html.encode("utf-8")),
            sanitizer_policy_version=sanitizer_policy_version,
            sanitizer_policy_sha256=sanitizer_policy_sha256,
            source_format=source_format.value,
            source_template_version_id=source_template_version_id,
            parent_document_id=parent_document_id,
            author_id=actor_id,
            artifact_state=GovernanceDocumentArtifactState.PENDING.value,
            knowledge_state=GovernanceDocumentKnowledgeState.PENDING.value,
            projection_attempts=0,
            next_attempt_at=now,
            version=1,
            created_at=now,
        )
        self._session.add_all((document, document_version))
        await self._session.flush()
        self._append_event(
            workspace_id=workspace_id,
            document_id=document_id,
            document_version_id=version_id,
            sequence=1,
            event_type="CREATED",
            actor_id=actor_id,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            details={
                "kind": kind.value,
                "category": category.value,
                "version_number": 1,
                "parent_document_id": (
                    str(parent_document_id) if parent_document_id is not None else None
                ),
            },
            created_at=now,
        )
        self._append_outbox(
            workspace_id=workspace_id,
            document_id=document_id,
            version_id=version_id,
            event_type="governance.document-version.created.v1",
            content_sha256=content_sha256,
            occurred_at=now,
        )
        await self._save_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_CREATE_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
            document_id=document_id,
        )
        detail = await self._detail(document)
        await self._session.commit()
        return detail

    async def create_version(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        title: str,
        summary: str,
        applicability_scope: str,
        sanitized_html: str,
        plain_text: str,
        content_sha256: str,
        sanitizer_policy_version: str,
        sanitizer_policy_sha256: str,
        source_format: GovernanceDocumentSourceFormat,
        source_template_version_id: UUID | None,
        parent_document_id: UUID | None,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail:
        await self._acquire(workspace_id, idempotency_key, _VERSION_OPERATION)
        replay = await self._replay(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_VERSION_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
        )
        if replay is not None:
            return await self._replayed_detail(
                workspace_id=workspace_id,
                document_id=replay,
            )
        document = await self._locked_document(workspace_id, document_id)
        _require_version(document, expected_version)
        if document.state == GovernanceDocumentState.ARCHIVED.value:
            raise ConflictError("An archived Governance Document cannot receive a new version.")
        live_draft = await self._session.scalar(
            select(func.count())
            .select_from(GovernanceDocumentVersionModel)
            .where(
                GovernanceDocumentVersionModel.workspace_id == workspace_id,
                GovernanceDocumentVersionModel.document_id == document_id,
                GovernanceDocumentVersionModel.state.in_(
                    (
                        GovernanceDocumentVersionState.DRAFT.value,
                        GovernanceDocumentVersionState.IN_REVIEW.value,
                    )
                ),
            )
        )
        if int(live_draft or 0) != 0:
            raise ConflictError("The Governance Document already has a mutable version.")
        latest_number = int(
            await self._session.scalar(
                select(func.max(GovernanceDocumentVersionModel.version_number)).where(
                    GovernanceDocumentVersionModel.workspace_id == workspace_id,
                    GovernanceDocumentVersionModel.document_id == document_id,
                )
            )
            or 0
        )
        now = await self.database_now()
        version_number = latest_number + 1
        document_version = GovernanceDocumentVersionModel(
            id=uuid7(),
            workspace_id=workspace_id,
            document_id=document_id,
            version_number=version_number,
            version_tag=version_tag(version_number),
            state=GovernanceDocumentVersionState.DRAFT.value,
            title=title,
            summary=summary,
            applicability_scope=applicability_scope,
            sanitized_html=sanitized_html,
            plain_text=plain_text,
            content_sha256=content_sha256,
            size_bytes=len(sanitized_html.encode("utf-8")),
            sanitizer_policy_version=sanitizer_policy_version,
            sanitizer_policy_sha256=sanitizer_policy_sha256,
            source_format=source_format.value,
            source_template_version_id=source_template_version_id,
            parent_document_id=parent_document_id,
            author_id=actor_id,
            artifact_state=GovernanceDocumentArtifactState.PENDING.value,
            knowledge_state=GovernanceDocumentKnowledgeState.PENDING.value,
            projection_attempts=0,
            next_attempt_at=now,
            version=1,
            created_at=now,
        )
        document.updated_at = now
        document.version += 1
        self._session.add(document_version)
        await self._session.flush()
        await self._append_next_event(
            document=document,
            document_version_id=document_version.id,
            event_type="VERSION_CREATED",
            actor_id=actor_id,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            details={
                "version_number": version_number,
                "parent_document_id": (
                    str(parent_document_id) if parent_document_id is not None else None
                ),
            },
            created_at=now,
        )
        self._append_outbox(
            workspace_id=workspace_id,
            document_id=document_id,
            version_id=document_version.id,
            event_type="governance.document-version.created.v1",
            content_sha256=content_sha256,
            occurred_at=now,
        )
        await self._save_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_VERSION_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
            document_id=document_id,
        )
        detail = await self._detail(document)
        await self._session.commit()
        return detail

    async def submit_version(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail:
        await self._acquire(workspace_id, idempotency_key, _SUBMIT_OPERATION)
        replay = await self._replay(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_SUBMIT_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
        )
        if replay is not None:
            return await self._replayed_detail(
                workspace_id=workspace_id,
                document_id=replay,
            )
        document = await self._locked_document(workspace_id, document_id)
        _require_version(document, expected_version)
        candidate = await self._locked_document_version(
            workspace_id,
            document_id,
            document_version_id,
        )
        if (
            candidate.state != GovernanceDocumentVersionState.DRAFT.value
            or candidate.author_id != actor_id
        ):
            raise ConflictError("Only the author can submit the current Draft version.")
        if candidate.artifact_state != GovernanceDocumentArtifactState.STORED.value:
            raise ConflictError(
                "The immutable Governance Document artifact is not verified yet.",
                details={"code": "DOCUMENT_ARTIFACT_NOT_READY"},
            )
        now = await self.database_now()
        candidate.state = GovernanceDocumentVersionState.IN_REVIEW.value
        candidate.submitted_at = now
        candidate.version += 1
        document.version += 1
        document.updated_at = now
        await self._append_next_event(
            document=document,
            document_version_id=candidate.id,
            event_type="SUBMITTED",
            actor_id=actor_id,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            details={"version_number": candidate.version_number},
            created_at=now,
        )
        await self._save_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_SUBMIT_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
            document_id=document_id,
        )
        detail = await self._detail(document)
        await self._session.commit()
        return detail

    async def review_version(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        reviewer_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        decision: GovernanceDocumentReviewDecision,
        reason: str,
        policy_decision_id: UUID,
        authentication_assurance: str,
        request_id: str,
    ) -> GovernanceDocumentDetail:
        await self._acquire(workspace_id, idempotency_key, _REVIEW_OPERATION)
        replay = await self._replay(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_REVIEW_OPERATION,
            request_hash=request_hash,
            actor_id=reviewer_id,
        )
        if replay is not None:
            return await self._replayed_detail(
                workspace_id=workspace_id,
                document_id=replay,
            )
        document = await self._locked_document(workspace_id, document_id)
        _require_version(document, expected_version)
        candidate = await self._locked_document_version(
            workspace_id,
            document_id,
            document_version_id,
        )
        if candidate.state != GovernanceDocumentVersionState.IN_REVIEW.value:
            raise ConflictError("The Governance Document version is not awaiting review.")
        if candidate.author_id == reviewer_id:
            raise ConflictError("The Governance Document author cannot approve their own version.")
        now = await self.database_now()
        candidate.reviewed_by = reviewer_id
        candidate.reviewed_at = now
        candidate.version += 1
        review = GovernanceDocumentReviewModel(
            id=uuid7(),
            workspace_id=workspace_id,
            document_id=document_id,
            document_version_id=document_version_id,
            decision=decision.value,
            reviewer_id=reviewer_id,
            reason=reason,
            policy_decision_id=policy_decision_id,
            authentication_assurance=authentication_assurance,
            created_at=now,
        )
        self._session.add(review)
        event_type: str
        if decision is GovernanceDocumentReviewDecision.REJECT:
            candidate.state = GovernanceDocumentVersionState.REJECTED.value
            event_type = "REJECTED"
        else:
            if candidate.artifact_state != GovernanceDocumentArtifactState.STORED.value:
                raise ConflictError(
                    "The Governance Document artifact must be verified before publication."
                )
            if document.current_published_version_id is not None:
                current = await self._locked_document_version(
                    workspace_id,
                    document_id,
                    document.current_published_version_id,
                )
                if current.state != GovernanceDocumentVersionState.PUBLISHED.value:
                    raise ConflictError("The current Governance Document version is inconsistent.")
                current.state = GovernanceDocumentVersionState.SUPERSEDED.value
                current.version += 1
            candidate.state = GovernanceDocumentVersionState.PUBLISHED.value
            candidate.published_at = now
            document.current_published_version_id = candidate.id
            document.state = GovernanceDocumentState.ACTIVE.value
            document.title = candidate.title
            document.summary = candidate.summary
            event_type = "PUBLISHED"
            self._append_outbox(
                workspace_id=workspace_id,
                document_id=document_id,
                version_id=candidate.id,
                event_type="governance.document-version.published.v1",
                content_sha256=candidate.content_sha256,
                occurred_at=now,
            )
        document.version += 1
        document.updated_at = now
        await self._append_next_event(
            document=document,
            document_version_id=candidate.id,
            event_type=event_type,
            actor_id=reviewer_id,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            details={"decision": decision.value, "version_number": candidate.version_number},
            created_at=now,
        )
        await self._save_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_REVIEW_OPERATION,
            request_hash=request_hash,
            actor_id=reviewer_id,
            document_id=document_id,
        )
        detail = await self._detail(document)
        await self._session.commit()
        return detail

    async def archive_document(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentDetail:
        await self._acquire(workspace_id, idempotency_key, _ARCHIVE_OPERATION)
        replay = await self._replay(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_ARCHIVE_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
        )
        if replay is not None:
            return await self._replayed_detail(
                workspace_id=workspace_id,
                document_id=replay,
            )
        document = await self._locked_document(workspace_id, document_id)
        _require_version(document, expected_version)
        if document.state == GovernanceDocumentState.ARCHIVED.value:
            raise ConflictError("The Governance Document is already archived.")
        now = await self.database_now()
        document.state = GovernanceDocumentState.ARCHIVED.value
        document.archived_at = now
        document.archived_by = actor_id
        document.archived_reason = reason
        document.updated_at = now
        document.version += 1
        await self._append_next_event(
            document=document,
            document_version_id=document.current_published_version_id,
            event_type="ARCHIVED",
            actor_id=actor_id,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            details={"reason_hash": hashlib.sha256(reason.encode()).hexdigest()},
            created_at=now,
        )
        await self._save_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation=_ARCHIVE_OPERATION,
            request_hash=request_hash,
            actor_id=actor_id,
            document_id=document_id,
        )
        detail = await self._detail(document)
        await self._session.commit()
        return detail

    async def add_attachment(
        self,
        *,
        attachment_id: UUID,
        workspace_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        serial_number: int,
        storage_filename: str,
        original_name: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        bucket: str,
        object_key: str,
        provider_version_id: str,
        etag: str,
        policy_decision_id: UUID,
        request_id: str,
    ) -> GovernanceDocumentAttachment:
        await self._acquire(workspace_id, idempotency_key, _ATTACHMENT_OPERATION)
        existing = await self._idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_ATTACHMENT_OPERATION,
        )
        if existing is not None:
            _require_replay(existing.request_hash, existing.result, request_hash, actor_id)
            attachment_id = UUID(str(existing.result["attachment_id"]))
            attachment = await self._session.get(
                GovernanceDocumentAttachmentModel,
                attachment_id,
            )
            if attachment is None or attachment.workspace_id != workspace_id:
                raise ConflictError("The attachment idempotency evidence is unavailable.")
            await self._session.commit()
            return _attachment(attachment)
        document = await self._locked_document(workspace_id, document_id)
        _require_version(document, expected_version)
        candidate = await self._locked_document_version(
            workspace_id,
            document_id,
            document_version_id,
        )
        if candidate.state != GovernanceDocumentVersionState.DRAFT.value:
            raise ConflictError("Attachments may be added only to a Draft document version.")
        count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(GovernanceDocumentAttachmentModel)
                .where(
                    GovernanceDocumentAttachmentModel.workspace_id == workspace_id,
                    GovernanceDocumentAttachmentModel.document_version_id == document_version_id,
                )
            )
            or 0
        )
        if count >= MAXIMUM_ATTACHMENTS_PER_VERSION:
            raise ConflictError("The Governance Document attachment limit has been reached.")
        if serial_number != count + 1:
            raise ConflictError("The Governance Document attachment serial is stale.")
        now = await self.database_now()
        attachment = GovernanceDocumentAttachmentModel(
            id=attachment_id,
            workspace_id=workspace_id,
            document_id=document_id,
            document_version_id=document_version_id,
            serial_number=serial_number,
            storage_filename=storage_filename,
            original_name=original_name,
            content_type=content_type,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
            bucket=bucket,
            object_key=object_key,
            provider_version_id=provider_version_id,
            etag=etag,
            uploaded_by=actor_id,
            created_at=now,
        )
        document.updated_at = now
        document.version += 1
        self._session.add(attachment)
        await self._session.flush()
        await self._append_next_event(
            document=document,
            document_version_id=document_version_id,
            event_type="ATTACHMENT_ADDED",
            actor_id=actor_id,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            details={
                "attachment_id": str(attachment.id),
                "serial_number": serial_number,
                "storage_filename": storage_filename,
                "content_sha256": content_sha256,
                "size_bytes": size_bytes,
            },
            created_at=now,
        )
        await self._idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_ATTACHMENT_OPERATION,
            request_hash=request_hash,
            result={
                "actor_id": str(actor_id),
                "attachment_id": str(attachment.id),
                "document_id": str(document_id),
            },
        )
        value = _attachment(attachment)
        await self._session.commit()
        return value

    async def get_attachment_source(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        attachment_id: UUID,
        subject: SubjectAttributes,
    ) -> GovernanceDocumentAttachmentSource | None:
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
        )
        row = (
            await self._session.execute(
                select(
                    GovernanceDocumentAttachmentModel,
                    GovernanceDocumentModel,
                )
                .join(
                    GovernanceDocumentModel,
                    and_(
                        GovernanceDocumentModel.workspace_id
                        == GovernanceDocumentAttachmentModel.workspace_id,
                        GovernanceDocumentModel.id == GovernanceDocumentAttachmentModel.document_id,
                    ),
                )
                .where(
                    GovernanceDocumentAttachmentModel.workspace_id == workspace_id,
                    GovernanceDocumentAttachmentModel.document_id == document_id,
                    GovernanceDocumentAttachmentModel.id == attachment_id,
                    GovernanceDocumentModel.classification <= int(subject.clearance),
                    *_subject_scope_conditions(subject),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        attachment, _document = row
        return GovernanceDocumentAttachmentSource(
            attachment=_attachment(attachment),
            bucket=attachment.bucket,
            object_key=attachment.object_key,
            provider_version_id=attachment.provider_version_id,
        )

    async def search_knowledge(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        query: str,
        query_vector: Sequence[float] | None,
        provider: str | None,
        model: str | None,
        limit: int,
    ) -> tuple[GovernanceKnowledgeEvidence, ...]:
        normalized = query.strip()
        if not 2 <= len(normalized) <= 500 or not 1 <= limit <= 20:
            raise ValidationError("The Governance knowledge query is outside its bounded contract.")
        conditions: list[ColumnElement[bool]] = [
            GovernanceDocumentKnowledgeChunkModel.workspace_id == workspace_id,
            GovernanceDocumentModel.state == GovernanceDocumentState.ACTIVE.value,
            GovernanceDocumentModel.classification <= int(subject.clearance),
            *_subject_scope_conditions(subject),
            GovernanceDocumentModel.current_published_version_id
            == GovernanceDocumentKnowledgeChunkModel.document_version_id,
        ]
        if provider is not None:
            conditions.append(GovernanceDocumentKnowledgeChunkModel.provider == provider)
        if model is not None:
            conditions.append(GovernanceDocumentKnowledgeChunkModel.model_identity == model)
        statement = (
            select(
                GovernanceDocumentKnowledgeChunkModel,
                GovernanceDocumentModel,
                GovernanceDocumentVersionModel,
            )
            .join(
                GovernanceDocumentModel,
                and_(
                    GovernanceDocumentModel.workspace_id
                    == GovernanceDocumentKnowledgeChunkModel.workspace_id,
                    GovernanceDocumentModel.id == GovernanceDocumentKnowledgeChunkModel.document_id,
                ),
            )
            .join(
                GovernanceDocumentVersionModel,
                and_(
                    GovernanceDocumentVersionModel.workspace_id
                    == GovernanceDocumentKnowledgeChunkModel.workspace_id,
                    GovernanceDocumentVersionModel.id
                    == GovernanceDocumentKnowledgeChunkModel.document_version_id,
                ),
            )
            .where(*conditions)
        )
        scored: list[
            tuple[
                float,
                GovernanceDocumentKnowledgeChunkModel,
                GovernanceDocumentModel,
                GovernanceDocumentVersionModel,
            ]
        ]
        if query_vector is not None:
            query_values = [float(value) for value in query_vector]
            distance = GovernanceDocumentKnowledgeChunkModel.embedding_vector.cosine_distance(
                query_values
            )
            vector_rows = (
                await self._session.execute(
                    statement.add_columns(distance.label("distance"))
                    .where(
                        GovernanceDocumentKnowledgeChunkModel.embedding_dimension
                        == len(query_values)
                    )
                    .order_by(distance, GovernanceDocumentKnowledgeChunkModel.id)
                    .limit(limit)
                )
            ).all()
            scored = [
                (
                    max(-1.0, min(1.0, 1.0 - float(distance_value))),
                    chunk,
                    document,
                    document_version,
                )
                for chunk, document, document_version, distance_value in vector_rows
                if distance_value is not None
            ]
        else:
            rows = (await self._session.execute(statement.limit(2_000))).all()
            tokens = frozenset(part.casefold() for part in normalized.split() if part)
            scored = []
            for chunk, document, document_version in rows:
                candidate_tokens = frozenset(
                    part.casefold() for part in chunk.content.split() if part
                )
                score = (
                    len(tokens & candidate_tokens) / len(tokens)
                    if tokens and candidate_tokens
                    else 0.0
                )
                if score > 0:
                    scored.append((score, chunk, document, document_version))
            scored.sort(key=lambda item: (-item[0], item[1].id.int))
        return tuple(
            _knowledge_evidence(
                chunk=chunk,
                document=document,
                document_version=document_version,
                score_basis_points=max(0, min(10_000, round(score * 10_000))),
            )
            for score, chunk, document, document_version in scored[:limit]
        )

    async def get_current_knowledge(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        chunk_ids: Sequence[UUID],
    ) -> tuple[GovernanceKnowledgeEvidence, ...]:
        ordered_ids = tuple(dict.fromkeys(chunk_ids))
        if not ordered_ids or len(ordered_ids) > 20:
            raise ValidationError("Governance knowledge citation ids are outside their contract.")
        rows = (
            await self._session.execute(
                select(
                    GovernanceDocumentKnowledgeChunkModel,
                    GovernanceDocumentModel,
                    GovernanceDocumentVersionModel,
                )
                .join(
                    GovernanceDocumentModel,
                    and_(
                        GovernanceDocumentModel.workspace_id
                        == GovernanceDocumentKnowledgeChunkModel.workspace_id,
                        GovernanceDocumentModel.id
                        == GovernanceDocumentKnowledgeChunkModel.document_id,
                    ),
                )
                .join(
                    GovernanceDocumentVersionModel,
                    and_(
                        GovernanceDocumentVersionModel.workspace_id
                        == GovernanceDocumentKnowledgeChunkModel.workspace_id,
                        GovernanceDocumentVersionModel.id
                        == GovernanceDocumentKnowledgeChunkModel.document_version_id,
                    ),
                )
                .where(
                    GovernanceDocumentKnowledgeChunkModel.workspace_id == workspace_id,
                    GovernanceDocumentKnowledgeChunkModel.id.in_(ordered_ids),
                    GovernanceDocumentModel.state == GovernanceDocumentState.ACTIVE.value,
                    GovernanceDocumentModel.classification <= int(subject.clearance),
                    *_subject_scope_conditions(subject),
                    GovernanceDocumentModel.current_published_version_id
                    == GovernanceDocumentKnowledgeChunkModel.document_version_id,
                )
            )
        ).all()
        values = {
            chunk.id: _knowledge_evidence(
                chunk=chunk,
                document=document,
                document_version=document_version,
                score_basis_points=10_000,
            )
            for chunk, document, document_version in rows
        }
        return tuple(values[value] for value in ordered_ids if value in values)

    async def claim_next_projection(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> GovernanceDocumentProjectionClaim | None:
        now = await self.database_now()
        row = (
            await self._session.execute(
                select(GovernanceDocumentVersionModel, GovernanceDocumentModel)
                .join(
                    GovernanceDocumentModel,
                    and_(
                        GovernanceDocumentModel.workspace_id
                        == GovernanceDocumentVersionModel.workspace_id,
                        GovernanceDocumentModel.id == GovernanceDocumentVersionModel.document_id,
                    ),
                )
                .where(
                    or_(
                        GovernanceDocumentVersionModel.artifact_state.in_(("PENDING", "FAILED")),
                        and_(
                            GovernanceDocumentVersionModel.state == "PUBLISHED",
                            GovernanceDocumentVersionModel.artifact_state == "STORED",
                            GovernanceDocumentVersionModel.knowledge_state.in_(
                                ("PENDING", "FAILED")
                            ),
                        ),
                    ),
                    or_(
                        GovernanceDocumentVersionModel.next_attempt_at.is_(None),
                        GovernanceDocumentVersionModel.next_attempt_at <= now,
                    ),
                    or_(
                        GovernanceDocumentVersionModel.lease_until.is_(None),
                        GovernanceDocumentVersionModel.lease_until <= now,
                    ),
                    GovernanceDocumentVersionModel.projection_attempts < 8,
                )
                .order_by(
                    GovernanceDocumentVersionModel.next_attempt_at,
                    GovernanceDocumentVersionModel.created_at,
                    GovernanceDocumentVersionModel.id,
                )
                .with_for_update(
                    of=GovernanceDocumentVersionModel,
                    skip_locked=True,
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            await self._session.rollback()
            return None
        candidate, document = row
        candidate.lease_owner = worker_id
        candidate.lease_until = now + timedelta(seconds=lease_seconds)
        candidate.projection_attempts += 1
        if candidate.artifact_state == "STORED":
            candidate.knowledge_state = GovernanceDocumentKnowledgeState.PROJECTING.value
        candidate.version += 1
        value = GovernanceDocumentProjectionClaim(
            version=_document_version(candidate),
            kind=GovernanceDocumentKind(document.kind),
            category=GovernanceDocumentCategory(document.category),
            classification=Classification(document.classification),
        )
        await self._session.commit()
        return value

    async def store_artifact_receipt(
        self,
        *,
        version: GovernanceDocumentVersion,
        bucket: str,
        content_key: str,
        content_version_id: str,
        content_etag: str,
        manifest_key: str,
        manifest_version_id: str,
        manifest_etag: str,
        manifest_sha256: str,
    ) -> None:
        await set_security_context(
            self._session,
            workspace_id=version.workspace_id,
            subject_id=None,
        )
        candidate = await self._locked_document_version(
            version.workspace_id,
            version.document_id,
            version.version_id,
        )
        if candidate.content_sha256 != version.content_sha256:
            raise ConflictError("The Governance Document content changed before artifact receipt.")
        existing = (
            await self._session.scalars(
                select(GovernanceDocumentArtifactReceiptModel).where(
                    GovernanceDocumentArtifactReceiptModel.workspace_id == version.workspace_id,
                    GovernanceDocumentArtifactReceiptModel.document_version_id
                    == version.version_id,
                )
            )
        ).one_or_none()
        if existing is None:
            self._session.add(
                GovernanceDocumentArtifactReceiptModel(
                    id=uuid7(),
                    workspace_id=version.workspace_id,
                    document_id=version.document_id,
                    document_version_id=version.version_id,
                    bucket=bucket,
                    content_object_key=content_key,
                    content_provider_version_id=content_version_id,
                    content_etag=content_etag,
                    content_sha256=version.content_sha256,
                    manifest_object_key=manifest_key,
                    manifest_provider_version_id=manifest_version_id,
                    manifest_etag=manifest_etag,
                    manifest_sha256=manifest_sha256,
                )
            )
        else:
            expected = (
                existing.bucket,
                existing.content_object_key,
                existing.content_provider_version_id,
                existing.content_sha256,
                existing.manifest_object_key,
                existing.manifest_provider_version_id,
                existing.manifest_sha256,
            )
            observed = (
                bucket,
                content_key,
                content_version_id,
                version.content_sha256,
                manifest_key,
                manifest_version_id,
                manifest_sha256,
            )
            if expected != observed:
                raise ConflictError("The Governance Document artifact receipt has drifted.")
        candidate.artifact_state = GovernanceDocumentArtifactState.STORED.value
        candidate.failure_code = None
        candidate.lease_owner = None
        candidate.lease_until = None
        candidate.next_attempt_at = None
        candidate.version += 1
        await self._session.commit()

    async def store_projection(
        self,
        *,
        version: GovernanceDocumentVersion,
        chunks: Sequence[tuple[int, str, str, Sequence[float]]],
        provider: str,
        model: str,
        graph_projection_hash: str | None,
    ) -> None:
        await set_security_context(
            self._session,
            workspace_id=version.workspace_id,
            subject_id=None,
        )
        candidate = await self._locked_document_version(
            version.workspace_id,
            version.document_id,
            version.version_id,
        )
        if (
            candidate.state != GovernanceDocumentVersionState.PUBLISHED.value
            or candidate.content_sha256 != version.content_sha256
        ):
            raise ConflictError("The Governance Document publication changed before projection.")
        existing_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(GovernanceDocumentKnowledgeChunkModel)
                .where(
                    GovernanceDocumentKnowledgeChunkModel.workspace_id == version.workspace_id,
                    GovernanceDocumentKnowledgeChunkModel.document_version_id == version.version_id,
                )
            )
            or 0
        )
        projection_hash = canonical_json_hash(
            {
                "contract": "GOVERNANCE_DOCUMENT_KNOWLEDGE_PROJECTION_V1",
                "workspace_id": str(version.workspace_id),
                "document_id": str(version.document_id),
                "version_id": str(version.version_id),
                "content_sha256": version.content_sha256,
                "provider": provider,
                "model": model,
                "chunks": [
                    {
                        "ordinal": ordinal,
                        "content_sha256": content_sha256,
                        "dimension": len(embedding),
                    }
                    for ordinal, _content, content_sha256, embedding in chunks
                ],
                "graph_projection_hash": graph_projection_hash,
            }
        )
        if existing_count == 0:
            self._session.add_all(
                [
                    GovernanceDocumentKnowledgeChunkModel(
                        id=uuid7(),
                        workspace_id=version.workspace_id,
                        document_id=version.document_id,
                        document_version_id=version.version_id,
                        ordinal=ordinal,
                        content=content,
                        content_sha256=content_sha256,
                        embedding=[float(value) for value in embedding],
                        embedding_vector=[float(value) for value in embedding],
                        embedding_dimension=len(embedding),
                        provider=provider,
                        model_identity=model,
                        graph_node_id=_graph_node_id(version.version_id, ordinal),
                    )
                    for ordinal, content, content_sha256, embedding in chunks
                ]
            )
            self._session.add(
                GovernanceDocumentProjectionReceiptModel(
                    id=uuid7(),
                    workspace_id=version.workspace_id,
                    document_id=version.document_id,
                    document_version_id=version.version_id,
                    chunk_count=len(chunks),
                    provider=provider,
                    model_identity=model,
                    projection_hash=projection_hash,
                    graph_projection_hash=graph_projection_hash,
                )
            )
        else:
            receipt = (
                await self._session.scalars(
                    select(GovernanceDocumentProjectionReceiptModel).where(
                        GovernanceDocumentProjectionReceiptModel.workspace_id
                        == version.workspace_id,
                        GovernanceDocumentProjectionReceiptModel.document_version_id
                        == version.version_id,
                    )
                )
            ).one_or_none()
            if receipt is None or receipt.projection_hash != projection_hash:
                raise ConflictError("The Governance Document projection receipt has drifted.")
        candidate.knowledge_state = GovernanceDocumentKnowledgeState.READY.value
        candidate.failure_code = None
        candidate.lease_owner = None
        candidate.lease_until = None
        candidate.next_attempt_at = None
        candidate.version += 1
        await self._session.commit()

    async def fail_projection(
        self,
        *,
        version: GovernanceDocumentVersion,
        failure_code: str,
        retryable: bool,
    ) -> None:
        await set_security_context(
            self._session,
            workspace_id=version.workspace_id,
            subject_id=None,
        )
        candidate = await self._locked_document_version(
            version.workspace_id,
            version.document_id,
            version.version_id,
        )
        if candidate.artifact_state != GovernanceDocumentArtifactState.STORED.value:
            candidate.artifact_state = GovernanceDocumentArtifactState.FAILED.value
        else:
            candidate.knowledge_state = GovernanceDocumentKnowledgeState.FAILED.value
        candidate.failure_code = failure_code[:100]
        candidate.lease_owner = None
        candidate.lease_until = None
        candidate.next_attempt_at = (
            utc_now() + timedelta(seconds=min(300, 2**candidate.projection_attempts))
            if retryable and candidate.projection_attempts < 8
            else None
        )
        candidate.version += 1
        await self._session.commit()

    async def _current_version_numbers(
        self,
        *,
        workspace_id: UUID,
        documents: Sequence[GovernanceDocumentModel],
    ) -> dict[UUID, int]:
        version_ids = [
            row.current_published_version_id
            for row in documents
            if row.current_published_version_id is not None
        ]
        if not version_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    GovernanceDocumentVersionModel.document_id,
                    GovernanceDocumentVersionModel.version_number,
                ).where(
                    GovernanceDocumentVersionModel.workspace_id == workspace_id,
                    GovernanceDocumentVersionModel.id.in_(version_ids),
                )
            )
        ).all()
        return {document_id: version_number for document_id, version_number in rows}

    async def _detail(
        self,
        document: GovernanceDocumentModel,
        *,
        subject: SubjectAttributes | None = None,
    ) -> GovernanceDocumentDetail:
        versions = tuple(
            _document_version(row)
            for row in (
                await self._session.scalars(
                    select(GovernanceDocumentVersionModel)
                    .where(
                        GovernanceDocumentVersionModel.workspace_id == document.workspace_id,
                        GovernanceDocumentVersionModel.document_id == document.id,
                    )
                    .order_by(
                        desc(GovernanceDocumentVersionModel.version_number),
                        desc(GovernanceDocumentVersionModel.id),
                    )
                    .limit(100)
                )
            ).all()
        )
        reviews = tuple(
            _review(row)
            for row in (
                await self._session.scalars(
                    select(GovernanceDocumentReviewModel)
                    .where(
                        GovernanceDocumentReviewModel.workspace_id == document.workspace_id,
                        GovernanceDocumentReviewModel.document_id == document.id,
                    )
                    .order_by(
                        desc(GovernanceDocumentReviewModel.created_at),
                        desc(GovernanceDocumentReviewModel.id),
                    )
                    .limit(100)
                )
            ).all()
        )
        attachments = tuple(
            _attachment(row)
            for row in (
                await self._session.scalars(
                    select(GovernanceDocumentAttachmentModel)
                    .where(
                        GovernanceDocumentAttachmentModel.workspace_id == document.workspace_id,
                        GovernanceDocumentAttachmentModel.document_id == document.id,
                    )
                    .order_by(
                        GovernanceDocumentAttachmentModel.created_at,
                        GovernanceDocumentAttachmentModel.id,
                    )
                    .limit(2_500)
                )
            ).all()
        )
        current_number = next(
            (
                value.version_number
                for value in versions
                if value.version_id == document.current_published_version_id
            ),
            None,
        )
        parent_document: GovernanceDocumentSummary | None = None
        child_documents: tuple[GovernanceDocumentSummary, ...] = ()
        relationship_version = next(
            (
                value
                for value in versions
                if value.version_id == document.current_published_version_id
            ),
            versions[0] if versions else None,
        )
        if subject is not None and relationship_version is not None:
            parent_document, child_documents = await self._relationships(
                document=document,
                version=relationship_version,
                subject=subject,
            )
        subject_ids = {
            document.owner_subject_id,
            *(value.author_id for value in versions),
            *(value.reviewed_by for value in versions if value.reviewed_by is not None),
            *(value.reviewer_id for value in reviews),
            *(value.uploaded_by for value in attachments),
        }
        subject_rows = (
            await self._session.execute(
                select(SubjectModel.id, SubjectModel.display_name)
                .join(
                    WorkspaceMembershipModel,
                    and_(
                        WorkspaceMembershipModel.subject_id == SubjectModel.id,
                        WorkspaceMembershipModel.workspace_id == document.workspace_id,
                    ),
                )
                .where(SubjectModel.id.in_(subject_ids))
                .order_by(SubjectModel.id)
            )
        ).all()
        return GovernanceDocumentDetail(
            document=_summary(document, current_version_number=current_number),
            versions=versions,
            reviews=reviews,
            attachments=attachments,
            parent_document=parent_document,
            child_documents=child_documents,
            subject_display_names=tuple(
                (subject_id, display_name) for subject_id, display_name in subject_rows
            ),
        )

    async def _relationships(
        self,
        *,
        document: GovernanceDocumentModel,
        version: GovernanceDocumentVersion,
        subject: SubjectAttributes,
    ) -> tuple[GovernanceDocumentSummary | None, tuple[GovernanceDocumentSummary, ...]]:
        parent_document: GovernanceDocumentSummary | None = None
        if version.parent_document_id is not None:
            parent_row = (
                await self._session.execute(
                    select(
                        GovernanceDocumentModel,
                        GovernanceDocumentVersionModel.version_number,
                    )
                    .join(
                        GovernanceDocumentVersionModel,
                        and_(
                            GovernanceDocumentVersionModel.workspace_id
                            == GovernanceDocumentModel.workspace_id,
                            GovernanceDocumentVersionModel.id
                            == GovernanceDocumentModel.current_published_version_id,
                        ),
                    )
                    .where(
                        GovernanceDocumentModel.workspace_id == document.workspace_id,
                        GovernanceDocumentModel.id == version.parent_document_id,
                        GovernanceDocumentModel.state == GovernanceDocumentState.ACTIVE.value,
                        GovernanceDocumentModel.classification <= int(subject.clearance),
                        *_subject_scope_conditions(subject),
                    )
                )
            ).one_or_none()
            if parent_row is not None:
                parent, version_number = parent_row
                parent_document = _summary(
                    parent,
                    current_version_number=version_number,
                )
        child_rows = (
            await self._session.execute(
                select(
                    GovernanceDocumentModel,
                    GovernanceDocumentVersionModel.version_number,
                )
                .join(
                    GovernanceDocumentVersionModel,
                    and_(
                        GovernanceDocumentVersionModel.workspace_id
                        == GovernanceDocumentModel.workspace_id,
                        GovernanceDocumentVersionModel.id
                        == GovernanceDocumentModel.current_published_version_id,
                    ),
                )
                .where(
                    GovernanceDocumentModel.workspace_id == document.workspace_id,
                    GovernanceDocumentModel.state == GovernanceDocumentState.ACTIVE.value,
                    GovernanceDocumentModel.classification <= int(subject.clearance),
                    GovernanceDocumentVersionModel.parent_document_id == document.id,
                    *_subject_scope_conditions(subject),
                )
                .order_by(
                    func.lower(GovernanceDocumentModel.title),
                    GovernanceDocumentModel.id,
                )
            )
        ).all()
        return (
            parent_document,
            tuple(
                _summary(child, current_version_number=version_number)
                for child, version_number in child_rows
            ),
        )

    async def _locked_document(
        self,
        workspace_id: UUID,
        document_id: UUID,
    ) -> GovernanceDocumentModel:
        value = (
            await self._session.scalars(
                select(GovernanceDocumentModel)
                .where(
                    GovernanceDocumentModel.workspace_id == workspace_id,
                    GovernanceDocumentModel.id == document_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if value is None:
            raise NotFoundError("The Governance Document does not exist.")
        return value

    async def _locked_document_version(
        self,
        workspace_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> GovernanceDocumentVersionModel:
        value = (
            await self._session.scalars(
                select(GovernanceDocumentVersionModel)
                .where(
                    GovernanceDocumentVersionModel.workspace_id == workspace_id,
                    GovernanceDocumentVersionModel.document_id == document_id,
                    GovernanceDocumentVersionModel.id == version_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if value is None:
            raise NotFoundError("The Governance Document version does not exist.")
        return value

    async def _append_next_event(
        self,
        *,
        document: GovernanceDocumentModel,
        document_version_id: UUID | None,
        event_type: str,
        actor_id: UUID,
        policy_decision_id: UUID,
        request_id: str,
        details: dict[str, object],
        created_at: datetime,
    ) -> None:
        sequence = int(
            await self._session.scalar(
                select(func.max(GovernanceDocumentEventModel.sequence)).where(
                    GovernanceDocumentEventModel.workspace_id == document.workspace_id,
                    GovernanceDocumentEventModel.document_id == document.id,
                )
            )
            or 0
        )
        self._append_event(
            workspace_id=document.workspace_id,
            document_id=document.id,
            document_version_id=document_version_id,
            sequence=sequence + 1,
            event_type=event_type,
            actor_id=actor_id,
            policy_decision_id=policy_decision_id,
            request_id=request_id,
            details=details,
            created_at=created_at,
        )

    def _append_event(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        document_version_id: UUID | None,
        sequence: int,
        event_type: str,
        actor_id: UUID,
        policy_decision_id: UUID | None,
        request_id: str,
        details: dict[str, object],
        created_at: datetime,
    ) -> None:
        self._session.add(
            GovernanceDocumentEventModel(
                id=uuid7(),
                workspace_id=workspace_id,
                document_id=document_id,
                document_version_id=document_version_id,
                sequence=sequence,
                event_type=event_type,
                actor_id=actor_id,
                policy_decision_id=policy_decision_id,
                request_id=request_id,
                details=details,
                created_at=created_at,
            )
        )

    def _append_outbox(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        version_id: UUID,
        event_type: str,
        content_sha256: str,
        occurred_at: datetime,
    ) -> None:
        self._session.add(
            OutboxEventModel(
                id=uuid7(),
                workspace_id=workspace_id,
                aggregate_type="GOVERNANCE_DOCUMENT",
                aggregate_id=document_id,
                event_type=event_type,
                schema_version=1,
                payload={
                    "document_id": str(document_id),
                    "document_version_id": str(version_id),
                    "content_sha256": content_sha256,
                },
                created_at=occurred_at,
                attempts=0,
            )
        )

    async def _acquire(self, workspace_id: UUID, key: str, operation: str) -> None:
        await self._idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=key,
            operation=operation,
        )

    async def _replay(
        self,
        *,
        workspace_id: UUID,
        idempotency_key: str,
        operation: str,
        request_hash: str,
        actor_id: UUID,
    ) -> UUID | None:
        existing = await self._idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if existing is None:
            return None
        _require_replay(existing.request_hash, existing.result, request_hash, actor_id)
        return UUID(str(existing.result["document_id"]))

    async def _save_idempotency(
        self,
        *,
        workspace_id: UUID,
        idempotency_key: str,
        operation: str,
        request_hash: str,
        actor_id: UUID,
        document_id: UUID,
    ) -> None:
        await self._idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={"actor_id": str(actor_id), "document_id": str(document_id)},
        )

    async def _replayed_detail(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
    ) -> GovernanceDocumentDetail:
        document = (
            await self._session.scalars(
                select(GovernanceDocumentModel).where(
                    GovernanceDocumentModel.workspace_id == workspace_id,
                    GovernanceDocumentModel.id == document_id,
                )
            )
        ).one_or_none()
        if document is None:
            raise ConflictError("The Governance Document idempotency evidence is unavailable.")
        detail = await self._detail(document)
        await self._session.commit()
        return detail


def _summary(
    model: GovernanceDocumentModel,
    *,
    current_version_number: int | None,
) -> GovernanceDocumentSummary:
    return GovernanceDocumentSummary(
        document_id=model.id,
        workspace_id=model.workspace_id,
        kind=GovernanceDocumentKind(model.kind),
        category=GovernanceDocumentCategory(model.category),
        title=model.title,
        summary=model.summary,
        classification=Classification(model.classification),
        state=GovernanceDocumentState(model.state),
        owner_subject_id=model.owner_subject_id,
        current_published_version_id=model.current_published_version_id,
        current_version_number=current_version_number,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
        allowed_actions=(),
    )


def _document_version(model: GovernanceDocumentVersionModel) -> GovernanceDocumentVersion:
    return GovernanceDocumentVersion(
        version_id=model.id,
        workspace_id=model.workspace_id,
        document_id=model.document_id,
        version_number=model.version_number,
        version_tag=model.version_tag,
        state=GovernanceDocumentVersionState(model.state),
        title=model.title,
        summary=model.summary,
        applicability_scope=model.applicability_scope,
        sanitized_html=model.sanitized_html,
        plain_text=model.plain_text,
        content_sha256=model.content_sha256,
        size_bytes=model.size_bytes,
        sanitizer_policy_version=model.sanitizer_policy_version,
        sanitizer_policy_sha256=model.sanitizer_policy_sha256,
        source_format=GovernanceDocumentSourceFormat(model.source_format),
        source_template_version_id=model.source_template_version_id,
        parent_document_id=model.parent_document_id,
        author_id=model.author_id,
        submitted_at=model.submitted_at,
        reviewed_by=model.reviewed_by,
        reviewed_at=model.reviewed_at,
        published_at=model.published_at,
        artifact_state=GovernanceDocumentArtifactState(model.artifact_state),
        knowledge_state=GovernanceDocumentKnowledgeState(model.knowledge_state),
        created_at=model.created_at,
        version=model.version,
    )


def _review(model: GovernanceDocumentReviewModel) -> GovernanceDocumentReview:
    return GovernanceDocumentReview(
        review_id=model.id,
        workspace_id=model.workspace_id,
        document_id=model.document_id,
        document_version_id=model.document_version_id,
        decision=GovernanceDocumentReviewDecision(model.decision),
        reviewer_id=model.reviewer_id,
        reason=model.reason,
        policy_decision_id=model.policy_decision_id,
        authentication_assurance=model.authentication_assurance,
        created_at=model.created_at,
    )


def _attachment(model: GovernanceDocumentAttachmentModel) -> GovernanceDocumentAttachment:
    return GovernanceDocumentAttachment(
        attachment_id=model.id,
        workspace_id=model.workspace_id,
        document_id=model.document_id,
        document_version_id=model.document_version_id,
        serial_number=model.serial_number,
        storage_filename=model.storage_filename,
        original_name=model.original_name,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        content_sha256=model.content_sha256,
        uploaded_by=model.uploaded_by,
        created_at=model.created_at,
    )


def _knowledge_evidence(
    *,
    chunk: GovernanceDocumentKnowledgeChunkModel,
    document: GovernanceDocumentModel,
    document_version: GovernanceDocumentVersionModel,
    score_basis_points: int,
) -> GovernanceKnowledgeEvidence:
    return GovernanceKnowledgeEvidence(
        chunk_id=chunk.id,
        document_id=document.id,
        document_version_id=document_version.id,
        document_title=document.title,
        version_tag=document_version.version_tag,
        ordinal=chunk.ordinal,
        excerpt=chunk.content[:1_000],
        content_sha256=chunk.content_sha256,
        score_basis_points=score_basis_points,
        classification=Classification(document.classification),
        published_at=document_version.published_at
        or document_version.reviewed_at
        or document_version.created_at,
    )


def _require_version(document: GovernanceDocumentModel, expected_version: int) -> None:
    if document.version != expected_version:
        raise PreconditionFailedError("The Governance Document version has changed.")


def _require_replay(
    stored_request_hash: str,
    result: dict[str, object],
    request_hash: str,
    actor_id: UUID,
) -> None:
    if (
        stored_request_hash != request_hash
        or result.get("actor_id") != str(actor_id)
        or not isinstance(result.get("document_id"), str)
    ):
        raise ConflictError("The Governance Document idempotency key was reused.")


def _encode_cursor(
    *,
    workspace_id: UUID,
    permission_scope: str,
    kind: GovernanceDocumentKind | None,
    category: GovernanceDocumentCategory | None,
    state: GovernanceDocumentState | None,
    include_archived: bool,
    query: str,
    limit: int,
    updated_at: datetime,
    document_id: UUID,
) -> str:
    scope = _cursor_scope(
        workspace_id=workspace_id,
        permission_scope=permission_scope,
        kind=kind,
        category=category,
        state=state,
        include_archived=include_archived,
        query=query,
        limit=limit,
    )
    payload = json.dumps(
        {
            "scope": scope,
            "updated_at": updated_at.isoformat(),
            "id": str(document_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    workspace_id: UUID,
    permission_scope: str,
    kind: GovernanceDocumentKind | None,
    category: GovernanceDocumentCategory | None,
    state: GovernanceDocumentState | None,
    include_archived: bool,
    query: str,
    limit: int,
) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    if not cursor or len(cursor) > _MAXIMUM_CURSOR_BYTES:
        raise ValidationError("The Governance Document cursor is invalid.")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        observed_scope = payload["scope"]
        updated_at = datetime.fromisoformat(payload["updated_at"])
        document_id = UUID(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValidationError("The Governance Document cursor is invalid.") from error
    expected_scope = _cursor_scope(
        workspace_id=workspace_id,
        permission_scope=permission_scope,
        kind=kind,
        category=category,
        state=state,
        include_archived=include_archived,
        query=query,
        limit=limit,
    )
    if observed_scope != expected_scope or updated_at.tzinfo is None:
        raise ValidationError("The Governance Document cursor scope is stale.")
    return updated_at, document_id


def _cursor_scope(
    *,
    workspace_id: UUID,
    permission_scope: str,
    kind: GovernanceDocumentKind | None,
    category: GovernanceDocumentCategory | None,
    state: GovernanceDocumentState | None,
    include_archived: bool,
    query: str,
    limit: int,
) -> str:
    return canonical_json_hash(
        {
            "contract": "GOVERNANCE_DOCUMENT_CURSOR_V2",
            "workspace_id": str(workspace_id),
            "permission_scope": permission_scope,
            "kind": kind.value if kind is not None else None,
            "category": category.value if category is not None else None,
            "state": state.value if state is not None else None,
            "include_archived": include_archived,
            "query": query,
            "limit": limit,
        }
    )


def _subject_scope_conditions(
    subject: SubjectAttributes,
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (
        or_(
            GovernanceDocumentModel.classification == int(Classification.PUBLIC),
            GovernanceDocumentModel.system_id.is_(None),
            GovernanceDocumentModel.system_id.in_(tuple(subject.allowed_system_ids)),
        ),
        or_(
            GovernanceDocumentModel.classification == int(Classification.PUBLIC),
            GovernanceDocumentModel.domain_id.is_(None),
            GovernanceDocumentModel.domain_id.in_(tuple(subject.allowed_domain_ids)),
        ),
    )


def _graph_node_id(version_id: UUID, ordinal: int) -> UUID:
    digest = hashlib.sha256(f"{version_id}:{ordinal}".encode()).digest()
    value = bytearray(digest[:16])
    value[6] = (value[6] & 0x0F) | 0x50
    value[8] = (value[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(value))
