from __future__ import annotations

from uuid import UUID

from datariver.application.dto import (
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioSourcePage,
)
from datariver.application.ports import KnowledgeStudioSourceReader, KnowledgeStudioStore
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, NotFoundError, ValidationError
from datariver.domain.knowledge_studio import (
    ABoxMappingMethod,
    ABoxMappingRuleInput,
    TBoxElementKind,
    validate_abox_mapping_rules,
    validate_endpoint_alias,
    validate_stable_element_id,
    validate_studio_name,
)


class KnowledgeStudioService:
    def __init__(
        self,
        *,
        store: KnowledgeStudioStore,
        authorization: AuthorizationService,
        sources: KnowledgeStudioSourceReader | None = None,
    ) -> None:
        self._store = store
        self._authorization = authorization
        self._sources = sources

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
            actor_id=subject.subject_id,
            draft_id=draft_id,
        )
        if draft is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        await self._authorize_visible_draft(
            draft=draft,
            subject=subject,
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

    async def advance_to_abox(
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
        return await self._store.advance_to_abox(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def get_abox(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioABoxRecord:
        record = await self._store.get_abox(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
        )
        if record is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        self._require_abox_step(record.draft)
        await self._authorize_visible_draft(
            draft=record.draft,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return record

    async def search_abox_sources(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        query: str,
        cursor: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioSourcePage:
        current = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        self._require_abox_step(current)
        await self._authorize_draft(
            draft=current,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return await self._source_reader().search_datasets(
            subject=subject,
            maximum_classification=current.classification,
            query=query,
            cursor=cursor,
            limit=limit,
            environment=environment,
            request_id=request_id,
        )

    async def get_abox_source(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        asset_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioSourceDetail:
        current = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        self._require_abox_step(current)
        await self._authorize_draft(
            draft=current,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return await self._require_source(
            draft=current,
            subject=subject,
            asset_id=asset_id,
            environment=environment,
            request_id=request_id,
        )

    async def _require_source(
        self,
        *,
        draft: KnowledgeStudioDraftRecord,
        subject: SubjectAttributes,
        asset_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioSourceDetail:
        source = await self._source_reader().get_dataset(
            subject=subject,
            asset_id=asset_id,
            environment=environment,
            request_id=request_id,
        )
        if source is None:
            raise NotFoundError("The Dataset is unavailable in the authorized catalog scope.")
        if source.dataset.classification > draft.classification:
            raise ConflictError(
                "The Dataset classification exceeds the Knowledge graph classification envelope."
            )
        return source

    async def save_abox_binding(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        target_stable_element_id: str,
        source_asset_id: UUID,
        source_version: str,
        projection_source_version: str,
        rules: tuple[tuple[str, str, str], ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioBindingRecord]:
        validate_stable_element_id(target_stable_element_id)
        current = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        self._require_abox_step(current)
        await self._authorize_draft(
            draft=current,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        source = await self._require_source(
            draft=current,
            subject=subject,
            asset_id=source_asset_id,
            environment=environment,
            request_id=request_id,
        )
        if source.stale_at is not None:
            raise ConflictError("A stale Dataset schema cannot be used for a new binding.")
        if source.dataset.source_version != source_version:
            raise ConflictError("The Dataset schema changed before the binding was saved.")
        if source.dataset.projection_source_version != projection_source_version:
            raise ConflictError(
                "The Dataset catalog projection changed before the binding was saved."
            )
        abox = await self._store.get_abox(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
        )
        if abox is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        elements = {item.stable_element_id: item for item in abox.tbox_elements}
        target = elements.get(target_stable_element_id)
        if target is None:
            raise ConflictError("The selected T-Box target is no longer accepted.")
        try:
            target_kind = TBoxElementKind(target.kind)
            typed_rules = tuple(
                ABoxMappingRuleInput(
                    method=ABoxMappingMethod(method),
                    source_field_path=source_field_path,
                    target_stable_element_id=target_element_id,
                )
                for method, source_field_path, target_element_id in rules
            )
        except ValueError as error:
            raise ConflictError("The A-Box mapping rule vocabulary is invalid.") from error
        validate_abox_mapping_rules(
            target_kind=target_kind,
            target_stable_element_id=target_stable_element_id,
            property_parent_by_id={
                item.stable_element_id: item.parent_stable_element_id
                for item in abox.tbox_elements
                if item.kind == TBoxElementKind.PROPERTY
                and item.parent_stable_element_id is not None
            },
            allowed_source_field_paths=frozenset(source.dataset.field_paths),
            rules=typed_rules,
        )
        return await self._store.save_abox_binding(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            target_stable_element_id=target_stable_element_id,
            source_asset_id=source_asset_id,
            source_version=source.dataset.source_version,
            projection_source_version=source.dataset.projection_source_version,
            source_classification=int(source.dataset.classification),
            source_name=source.dataset.name,
            rules=rules,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def submit_review(
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
        draft = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        await self._authorize_draft(
            draft=draft,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.submit_review(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def discard_draft(
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
        draft = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        await self._authorize_draft(
            draft=draft,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.discard_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def publish_draft(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        review_reason: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioReleaseRecord]:
        if subject.job_function == "SERVICE_ACCOUNT" or "service-accounts" in subject.groups:
            raise ValidationError("Studio publication requires an independent human reviewer.")
        draft = await self._store.get_draft(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
        )
        if draft is None or draft.state != "REVIEW":
            raise NotFoundError("The Knowledge Studio review Draft does not exist.")
        if draft.author_id == subject.subject_id:
            raise ConflictError("A Studio author cannot review or publish their own Draft.")
        review_resource = self._resource(
            resource_id=draft.draft_id,
            workspace_id=draft.workspace_id,
            owner_subject_id=None,
            domain_id=draft.domain_id,
            classification=draft.classification,
            lifecycle=draft.state,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=review_resource,
            action=Action.KG_REVIEW,
            environment=environment,
            request_id=request_id,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=review_resource,
            action=Action.KG_PUBLISH,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.publish_draft(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
            review_reason=review_reason,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    def _source_reader(self) -> KnowledgeStudioSourceReader:
        if self._sources is None:
            raise ConflictError("Knowledge Studio Dataset selection is unavailable.")
        return self._sources

    @staticmethod
    def _require_abox_step(draft: KnowledgeStudioDraftRecord) -> None:
        if draft.current_step != "ABOX":
            raise ConflictError("Open Data Enricher before reading or editing A-Box mappings.")

    async def _require_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioDraftRecord:
        draft = await self._store.get_draft(
            workspace_id=workspace_id,
            actor_id=author_id,
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

    async def _authorize_visible_draft(
        self,
        *,
        draft: KnowledgeStudioDraftRecord,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        if draft.author_id == subject.subject_id:
            await self._authorize_draft(
                draft=draft,
                subject=subject,
                action=Action.KG_READ,
                environment=environment,
                request_id=request_id,
            )
            return
        if draft.state not in {"REVIEW", "PUBLISHED"}:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                resource_id=draft.draft_id,
                workspace_id=draft.workspace_id,
                owner_subject_id=None,
                domain_id=draft.domain_id,
                classification=draft.classification,
                lifecycle=draft.state,
            ),
            action=Action.KG_REVIEW,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    def _resource(
        *,
        resource_id: UUID,
        workspace_id: UUID,
        owner_subject_id: UUID | None,
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
