from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import NotFoundError
from datariver.domain.knowledge_property_profiles import (
    KnowledgePropertyProfile,
    KnowledgePropertyTarget,
    validate_property_profile_values,
)


@dataclass(frozen=True, slots=True)
class KnowledgePropertyProfileItem:
    target: KnowledgePropertyTarget
    profile: KnowledgePropertyProfile | None


class KnowledgePropertyProfileRepository(Protocol):
    async def list_items(
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        query: str,
        limit: int,
    ) -> tuple[KnowledgePropertyProfileItem, ...]: ...

    async def get_target(
        self,
        *,
        workspace_id: UUID,
        ontology_element_id: UUID,
    ) -> KnowledgePropertyTarget | None: ...

    async def get_target_for_profile(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
    ) -> KnowledgePropertyTarget | None: ...

    async def create_profile(
        self,
        *,
        target: KnowledgePropertyTarget,
        actor_id: UUID,
        description: str | None,
        unit: str | None,
        synonyms: tuple[str, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgePropertyProfile: ...

    async def update_profile(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
        actor_id: UUID,
        description: str | None,
        unit: str | None,
        synonyms: tuple[str, ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgePropertyTarget, KnowledgePropertyProfile]: ...

    async def archive_profile(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgePropertyTarget, KnowledgePropertyProfile]: ...


class KnowledgePropertyProfileService:
    def __init__(
        self,
        *,
        repository: KnowledgePropertyProfileRepository,
        authorization: AuthorizationService,
    ) -> None:
        self._repository = repository
        self._authorization = authorization

    async def list_items(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        query: str,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgePropertyProfileItem, ...]:
        await self._authorization.authorize(
            subject=subject,
            resource=_resource(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                domain_id=None,
                classification=Classification.PUBLIC,
            ),
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return await self._repository.list_items(
            workspace_id=workspace_id,
            clearance=int(subject.clearance),
            allowed_domain_ids=subject.allowed_domain_ids,
            query=query.strip(),
            limit=limit,
        )

    async def create_profile(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        ontology_element_id: UUID,
        description: str | None,
        unit: str | None,
        synonyms: tuple[str, ...],
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgePropertyProfile:
        target = await self._repository.get_target(
            workspace_id=workspace_id,
            ontology_element_id=ontology_element_id,
        )
        if target is None:
            raise NotFoundError("The active released Property does not exist.")
        await self._authorize_target(
            target=target,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        normalized = validate_property_profile_values(
            description=description,
            unit=unit,
            synonyms=synonyms,
        )
        return await self._repository.create_profile(
            target=target,
            actor_id=subject.subject_id,
            description=normalized[0],
            unit=normalized[1],
            synonyms=normalized[2],
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def update_profile(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        profile_id: UUID,
        description: str | None,
        unit: str | None,
        synonyms: tuple[str, ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgePropertyProfile:
        normalized = validate_property_profile_values(
            description=description,
            unit=unit,
            synonyms=synonyms,
        )
        target = await self._repository.get_target_for_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
        )
        if target is None:
            raise NotFoundError("The Property profile does not exist.")
        await self._authorize_target(
            target=target,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        _, profile = await self._repository.update_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
            actor_id=subject.subject_id,
            description=normalized[0],
            unit=normalized[1],
            synonyms=normalized[2],
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        return profile

    async def archive_profile(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        profile_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgePropertyProfile:
        target = await self._repository.get_target_for_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
        )
        if target is None:
            raise NotFoundError("The Property profile does not exist.")
        await self._authorize_target(
            target=target,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        _, profile = await self._repository.archive_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        return profile

    async def _authorize_target(
        self,
        *,
        target: KnowledgePropertyTarget,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=_resource(
                resource_id=target.graph_id,
                workspace_id=target.workspace_id,
                domain_id=target.domain_id,
                classification=Classification(target.classification),
            ),
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )


def _resource(
    *,
    resource_id: UUID,
    workspace_id: UUID,
    domain_id: UUID | None,
    classification: Classification,
) -> ResourceAttributes:
    return ResourceAttributes(
        resource_id=resource_id,
        workspace_id=workspace_id,
        resource_type="knowledge_property_profile",
        owner_department_id=None,
        system_id=None,
        domain_id=domain_id,
        classification=classification,
        lifecycle="ACTIVE",
    )
