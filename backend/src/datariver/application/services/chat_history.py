from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from datariver.application.dto import ChatMessageRecord, ChatSessionRecord
from datariver.application.ports import ChatHistoryStore
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError


class ChatHistoryService:
    """Authorize owner-scoped Chat history operations before using the persistence port."""

    def __init__(
        self,
        *,
        history: ChatHistoryStore,
        authorization: AuthorizationService,
    ) -> None:
        self._history = history
        self._authorization = authorization

    async def list_sessions(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        limit: int,
    ) -> Sequence[ChatSessionRecord]:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return await self._history.list_sessions(
            workspace_id=workspace_id,
            owner_id=subject.subject_id,
            limit=limit,
        )

    async def list_messages(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        limit: int,
    ) -> Sequence[ChatMessageRecord]:
        owner_id = await self._owned_session_id(
            workspace_id=workspace_id,
            session_id=session_id,
            subject=subject,
        )
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=session_id,
            owner_id=owner_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return await self._history.list_messages(
            workspace_id=workspace_id,
            owner_id=owner_id,
            session_id=session_id,
            limit=limit,
        )

    async def set_favorite(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        expected_version: int,
        is_favorite: bool,
    ) -> ChatSessionRecord:
        owner_id = await self._owned_session_id(
            workspace_id=workspace_id,
            session_id=session_id,
            subject=subject,
        )
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=session_id,
            owner_id=owner_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return await self._history.set_favorite(
            workspace_id=workspace_id,
            owner_id=owner_id,
            session_id=session_id,
            expected_version=expected_version,
            is_favorite=is_favorite,
        )

    async def _authorize(
        self,
        *,
        workspace_id: UUID,
        resource_id: UUID,
        owner_id: UUID | None = None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=resource_id,
                workspace_id=workspace_id,
                resource_type="chat_session",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.INTERNAL,
                lifecycle="ACTIVE",
                owner_subject_id=owner_id or subject.subject_id,
            ),
            action=Action.CHAT_QUERY,
            environment=environment,
            request_id=request_id,
        )

    async def _owned_session_id(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
        subject: SubjectAttributes,
    ) -> UUID:
        owner_id = await self._history.get_session_owner(
            workspace_id=workspace_id,
            session_id=session_id,
        )
        if owner_id is None or owner_id != subject.subject_id:
            raise ForbiddenError("The chat session is not available.")
        return owner_id
