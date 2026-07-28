from __future__ import annotations

from uuid import UUID

from datariver.application.dto import KnowledgeStudioDomainOption, KnowledgeStudioDraftRecord
from datariver.application.ports import KnowledgeStudioStore
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import NotFoundError
from datariver.domain.knowledge_studio import validate_endpoint_alias, validate_studio_name


class KnowledgeStudioService:
    def __init__(
        self,
        *,
        store: KnowledgeStudioStore,
        authorization: AuthorizationService,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def list_domains(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        classification: Classification,
        query: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioDomainOption, ...]:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                owner_subject_id=subject.subject_id,
                domain_id=None,
                classification=classification,
                lifecycle="DRAFT",
            ),
            action=Action.KG_CREATE,
            environment=environment,
            request_id=request_id,
        )
        allowed_domains = (
            None if classification is Classification.PUBLIC else subject.allowed_domain_ids
        )
        return await self._store.list_domains(
            workspace_id=workspace_id,
            allowed_domain_ids=allowed_domains,
            query=query,
            limit=limit,
        )

    async def get_draft(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioDraftRecord:
        draft = await self._store.get_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        if draft is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        await self._authorize_draft(
            draft=draft,
            subject=subject,
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return draft

    async def create_draft(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        name: str,
        endpoint_alias: str,
        domain_id: UUID,
        domain_source_version: str,
        classification: Classification,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioDraftRecord:
        validate_studio_name(name)
        validate_endpoint_alias(endpoint_alias)
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                owner_subject_id=subject.subject_id,
                domain_id=domain_id,
                classification=classification,
                lifecycle="DRAFT",
            ),
            action=Action.KG_CREATE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.create_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            name=name,
            endpoint_alias=endpoint_alias,
            domain_id=domain_id,
            domain_source_version=domain_source_version,
            classification=int(classification),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def autosave_draft(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        name: str,
        endpoint_alias: str,
        domain_id: UUID,
        domain_source_version: str,
        classification: Classification,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioDraftRecord:
        validate_studio_name(name)
        validate_endpoint_alias(endpoint_alias)
        current = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                resource_id=draft_id,
                workspace_id=workspace_id,
                owner_subject_id=current.author_id,
                domain_id=domain_id,
                classification=classification,
                lifecycle=current.state,
            ),
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.autosave_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            name=name,
            endpoint_alias=endpoint_alias,
            domain_id=domain_id,
            domain_source_version=domain_source_version,
            classification=int(classification),
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def advance_to_tbox(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioDraftRecord:
        current = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        await self._authorize_draft(
            draft=current,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.advance_to_tbox(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def _require_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioDraftRecord:
        draft = await self._store.get_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        if draft is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        return draft

    async def _authorize_draft(
        self,
        *,
        draft: KnowledgeStudioDraftRecord,
        subject: SubjectAttributes,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                resource_id=draft.draft_id,
                workspace_id=draft.workspace_id,
                owner_subject_id=draft.author_id,
                domain_id=draft.domain_id,
                classification=draft.classification,
                lifecycle=draft.state,
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    def _resource(
        *,
        resource_id: UUID,
        workspace_id: UUID,
        owner_subject_id: UUID,
        domain_id: UUID | None,
        classification: Classification,
        lifecycle: str,
    ) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=resource_id,
            workspace_id=workspace_id,
            resource_type="knowledge_studio_draft",
            owner_department_id=None,
            system_id=None,
            domain_id=domain_id,
            classification=classification,
            lifecycle=lifecycle,
            owner_subject_id=owner_subject_id,
        )
