from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from datariver.application.dto import (
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioIngestionJobRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioSourcePage,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioTBoxProposalRecord,
    KnowledgeStudioTBoxRecord,
)
from datariver.application.ports import (
    KnowledgeStudioSchemaAssistant,
    KnowledgeStudioSourceReader,
    KnowledgeStudioStore,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio import (
    ABoxMappingMethod,
    ABoxMappingRuleInput,
    TBoxBlockKind,
    TBoxElementInput,
    TBoxElementKind,
    TBoxMergeResolution,
    TBoxMergeStrategy,
    TBoxOperationInput,
    TBoxOperationKind,
    TBoxProposalMode,
    require_studio_version,
    validate_abox_mapping_rules,
    validate_endpoint_alias,
    validate_stable_element_id,
    validate_studio_name,
    validate_tbox_element_set,
)


class KnowledgeStudioService:
    def __init__(
        self,
        *,
        store: KnowledgeStudioStore,
        authorization: AuthorizationService,
        sources: KnowledgeStudioSourceReader | None = None,
        schema_assistant: KnowledgeStudioSchemaAssistant | None = None,
        schema_binding: ModelBinding | None = None,
        embedding_binding: ModelBinding | None = None,
    ) -> None:
        self._store = store
        self._authorization = authorization
        self._sources = sources
        self._schema_assistant = schema_assistant
        self._schema_binding = schema_binding
        self._embedding_binding = embedding_binding

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

    async def get_resumable_draft(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        endpoint_alias: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioDraftRecord:
        validate_endpoint_alias(endpoint_alias)
        draft = await self._store.get_owned_live_draft_by_endpoint_alias(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            endpoint_alias=endpoint_alias,
        )
        if draft is None:
            raise NotFoundError("A resumable Knowledge Studio draft does not exist.")
        await self._authorize_draft(
            draft=draft,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return draft

    async def create_edit_draft(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        graph_id: UUID,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioDraftRecord:
        graph = await self._store.get_edit_graph(
            workspace_id=workspace_id,
            graph_id=graph_id,
            clearance=int(subject.clearance),
        )
        if graph is None:
            raise NotFoundError("The Knowledge asset does not exist.")
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                resource_id=graph.graph_id,
                workspace_id=workspace_id,
                owner_subject_id=None,
                domain_id=graph.domain_id,
                classification=graph.classification,
                lifecycle=graph.status,
            ),
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.create_edit_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            graph_id=graph_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def get_tbox(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioTBoxRecord:
        record = await self._store.get_tbox(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
        )
        if record is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        if record.draft.current_step not in {"TBOX", "ABOX"}:
            raise ConflictError("Open Graph Builder before reading the T-Box Draft.")
        await self._authorize_visible_draft(
            draft=record.draft,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return record

    async def create_tbox_block(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        kind: str,
        title: str,
        weight: int,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioTBoxRecord:
        try:
            typed_kind = TBoxBlockKind(kind)
        except ValueError as error:
            raise ValidationError("The T-Box block kind is invalid.") from error
        if title != title.strip() or not 1 <= len(title) <= 120:
            raise ValidationError("A T-Box block title must contain between 1 and 120 characters.")
        if not 0 <= weight <= 100:
            raise ValidationError("A T-Box block weight must be between 0 and 100.")
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
        return await self._store.create_tbox_block(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            kind=typed_kind.value,
            title=title,
            weight=weight,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def update_tbox_block(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        block_id: UUID,
        title: str,
        weight: int,
        collapsed: bool,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioTBoxRecord:
        if title != title.strip() or not 1 <= len(title) <= 120:
            raise ValidationError("A T-Box block title must contain between 1 and 120 characters.")
        if not 0 <= weight <= 100:
            raise ValidationError("A T-Box block weight must be between 0 and 100.")
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
        return await self._store.update_tbox_block(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            block_id=block_id,
            title=title,
            weight=weight,
            collapsed=collapsed,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def apply_tbox_operations(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        block_id: UUID,
        operations: tuple[TBoxOperationInput, ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioTBoxRecord:
        if not 1 <= len(operations) <= 500:
            raise ValidationError("A typed T-Box request requires between 1 and 500 operations.")
        record = await self.get_tbox(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=draft_id,
            environment=environment,
            request_id=request_id,
        )
        await self._authorize_draft(
            draft=record.draft,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        if record.draft.current_step != "TBOX" or record.draft.state != "DRAFT":
            raise ConflictError("Typed T-Box operations require a mutable Graph Builder Draft.")
        elements_by_block: dict[UUID, dict[str, TBoxElementInput]] = {
            block.block_id: {
                item.stable_element_id: self._tbox_input(item) for item in block.elements
            }
            for block in record.blocks
        }
        target = elements_by_block.get(block_id)
        if target is None:
            raise NotFoundError("The T-Box block does not exist.")
        ownership = {
            stable_id: owner_id
            for owner_id, elements in elements_by_block.items()
            for stable_id in elements
        }
        for operation in operations:
            operation.validate()
            owner_id = ownership.get(operation.stable_element_id)
            if operation.operation is TBoxOperationKind.UPSERT_ELEMENT:
                if owner_id is not None and owner_id != block_id:
                    raise ConflictError(
                        "A typed operation cannot overwrite an element owned by another block."
                    )
                assert operation.element is not None
                target[operation.stable_element_id] = operation.element
                ownership[operation.stable_element_id] = block_id
            elif operation.operation is TBoxOperationKind.DELETE_ELEMENT:
                if owner_id != block_id:
                    raise ConflictError(
                        "A typed operation can delete only an element owned by its block."
                    )
                del target[operation.stable_element_id]
                ownership.pop(operation.stable_element_id, None)
            else:
                if owner_id != block_id:
                    raise ConflictError(
                        "A typed operation can move only an element owned by its block."
                    )
                target[operation.stable_element_id] = replace(
                    target[operation.stable_element_id],
                    layout_x=operation.layout_x,
                    layout_y=operation.layout_y,
                )
        ordered_blocks = tuple(
            (
                block.block_id,
                tuple(elements_by_block[block.block_id].values()),
            )
            for block in record.blocks
        )
        validate_tbox_element_set(
            tuple(element for _owner, elements in ordered_blocks for element in elements)
        )
        return await self._store.save_tbox_block_elements(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            block_id=block_id,
            elements_by_block=ordered_blocks,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def create_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        target_block_id: UUID | None,
        mode: TBoxProposalMode,
        prompt: str,
        expected_version: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioTBoxProposalRecord:
        if prompt != prompt.strip() or not 1 <= len(prompt) <= 4_000:
            raise ValidationError(
                "A schema-assistant prompt must contain between 1 and 4,000 characters."
            )
        record = await self.get_tbox(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=draft_id,
            environment=environment,
            request_id=request_id,
        )
        await self._authorize_draft(
            draft=record.draft,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        if record.draft.state != "DRAFT" or record.draft.current_step != "TBOX":
            raise ConflictError("LLM schema proposals require a mutable Graph Builder Draft.")
        require_studio_version(record.draft.version, expected_version)
        if mode is TBoxProposalMode.MERGE_INTO_CURRENT and target_block_id is None:
            raise ValidationError("MERGE_INTO_CURRENT requires a target block.")
        if mode is TBoxProposalMode.APPEND_LAYER and target_block_id is not None:
            raise ValidationError("APPEND_LAYER cannot target an existing block.")
        assistant, binding = self._schema_runtime()
        current = tuple(
            self._tbox_input(item) for block in record.blocks for item in block.elements
        )
        proposed = await assistant.propose(
            prompt=prompt,
            current_elements=current,
            binding=binding,
        )
        if not proposed:
            raise ConflictError("The LLM returned no typed T-Box elements.")
        conflicts = self._proposal_conflicts(current=current, proposed=proposed)
        return await self._store.save_tbox_proposal(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            base_draft_version=expected_version,
            target_block_id=target_block_id,
            mode=mode.value,
            prompt=prompt,
            elements=proposed,
            conflicts=conflicts,
            model_binding=binding.to_document(),
        )

    async def get_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        proposal_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioTBoxProposalRecord:
        proposal = await self._store.get_tbox_proposal(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
            proposal_id=proposal_id,
        )
        if proposal is None:
            raise NotFoundError("The T-Box proposal does not exist.")
        draft = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        await self._authorize_visible_draft(
            draft=draft,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return proposal

    async def apply_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        proposal_id: UUID,
        merge_strategy: TBoxMergeStrategy,
        resolutions: tuple[dict[str, str], ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioTBoxRecord:
        record = await self.get_tbox(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=draft_id,
            environment=environment,
            request_id=request_id,
        )
        await self._authorize_draft(
            draft=record.draft,
            subject=subject,
            action=Action.KG_EDIT,
            environment=environment,
            request_id=request_id,
        )
        proposal = await self.get_tbox_proposal(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=draft_id,
            proposal_id=proposal_id,
            environment=environment,
            request_id=request_id,
        )
        if proposal.state != "READY":
            raise ConflictError("Only a READY T-Box proposal can be applied.")
        proposed = tuple(self._tbox_input(item) for item in proposal.elements)
        grouped: dict[UUID, dict[str, TBoxElementInput]] = {
            block.block_id: {
                item.stable_element_id: self._tbox_input(item) for item in block.elements
            }
            for block in record.blocks
        }
        current = tuple(item for values in grouped.values() for item in values.values())
        conflicts = self._proposal_conflicts(current=current, proposed=proposed)
        resolution_by_conflict = {item.get("conflict_id", ""): item for item in resolutions}
        if len(resolution_by_conflict) != len(resolutions):
            raise ValidationError("A proposal conflict resolution can appear only once.")
        if merge_strategy is TBoxMergeStrategy.RESOLVE and any(
            str(item["conflict_id"]) not in resolution_by_conflict for item in conflicts
        ):
            raise ValidationError("Every proposal conflict requires an explicit resolution.")
        appended_elements: tuple[TBoxElementInput, ...] = ()
        if proposal.mode == TBoxProposalMode.APPEND_LAYER.value:
            appended_elements = self._resolve_proposal_elements(
                current=current,
                proposed=proposed,
                conflicts=conflicts,
                merge_strategy=merge_strategy,
                resolution_by_conflict=resolution_by_conflict,
            )
            validate_tbox_element_set((*current, *appended_elements))
        else:
            if proposal.target_block_id is None or proposal.target_block_id not in grouped:
                raise ConflictError("The proposal target block is unavailable.")
            accepted = self._resolve_proposal_elements(
                current=current,
                proposed=proposed,
                conflicts=conflicts,
                merge_strategy=merge_strategy,
                resolution_by_conflict=resolution_by_conflict,
            )
            target = grouped[proposal.target_block_id]
            identity_by_name = {
                (item.kind, item.canonical_name.casefold()): item.stable_element_id
                for item in current
            }
            for item in accepted:
                existing_id = identity_by_name.get((item.kind, item.canonical_name.casefold()))
                if existing_id is not None and existing_id != item.stable_element_id:
                    for elements in grouped.values():
                        elements.pop(existing_id, None)
                for elements in grouped.values():
                    if item.stable_element_id in elements:
                        elements[item.stable_element_id] = item
                        break
                else:
                    target[item.stable_element_id] = item
            validate_tbox_element_set(
                tuple(item for values in grouped.values() for item in values.values())
            )
        ordered = tuple(
            (block.block_id, tuple(grouped[block.block_id].values())) for block in record.blocks
        )
        return await self._store.apply_tbox_proposal(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            proposal_id=proposal_id,
            target_block_id=proposal.target_block_id,
            elements_by_block=ordered,
            appended_elements=appended_elements,
            conflicts=conflicts,
            merge_strategy=merge_strategy.value,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

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

    async def create_ingestion_job(
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
    ) -> KnowledgeStudioIngestionJobRecord:
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
        tbox = await self._store.get_tbox(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
        )
        if tbox is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        has_vector_targets = any(
            item.vector_index_enabled for block in tbox.blocks for item in block.elements
        )
        if has_vector_targets and self._embedding_binding is None:
            raise ConflictError("A Vector Index target requires the governed embedding runtime.")
        if self._embedding_binding is not None:
            self._embedding_binding.validate()
        return await self._store.create_ingestion_job(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
            expected_version=expected_version,
            embedding_binding=(
                self._embedding_binding.to_document()
                if has_vector_targets and self._embedding_binding is not None
                else None
            ),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def get_ingestion_job(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        job_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioIngestionJobRecord:
        current = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        await self._authorize_visible_draft(
            draft=current,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        job = await self._store.get_ingestion_job(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
            job_id=job_id,
        )
        if job is None:
            raise NotFoundError("The A-Box ingestion job does not exist.")
        return job

    async def list_ingestion_jobs(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        draft_id: UUID,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioIngestionJobRecord, ...]:
        current = await self._require_draft(
            workspace_id=workspace_id,
            author_id=subject.subject_id,
            draft_id=draft_id,
        )
        await self._authorize_visible_draft(
            draft=current,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.list_ingestion_jobs(
            workspace_id=workspace_id,
            actor_id=subject.subject_id,
            draft_id=draft_id,
            limit=limit,
        )

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

    def _schema_runtime(self) -> tuple[KnowledgeStudioSchemaAssistant, ModelBinding]:
        if self._schema_assistant is None or self._schema_binding is None:
            raise ConflictError("The governed LLM schema assistant is unavailable.")
        self._schema_binding.validate()
        return self._schema_assistant, self._schema_binding

    @classmethod
    def _proposal_conflicts(
        cls,
        *,
        current: tuple[TBoxElementInput, ...],
        proposed: tuple[TBoxElementInput, ...],
    ) -> tuple[dict[str, object], ...]:
        current_by_id = {item.stable_element_id: item for item in current}
        current_by_name = {(item.kind, item.canonical_name.casefold()): item for item in current}
        conflicts: list[dict[str, object]] = []
        for item in proposed:
            original = current_by_id.get(item.stable_element_id)
            kind = "IDENTITY"
            if original is not None and original.kind is not item.kind:
                kind = "KIND"
            if original is None:
                original = current_by_name.get((item.kind, item.canonical_name.casefold()))
                kind = "IDENTITY"
            if original is None:
                continue
            original_document = cls._tbox_document(original)
            proposed_document = cls._tbox_document(item)
            if original_document == proposed_document:
                continue
            if original.kind is TBoxElementKind.RELATION and (
                original.source_stable_element_id != item.source_stable_element_id
                or original.target_stable_element_id != item.target_stable_element_id
            ):
                kind = "ENDPOINT"
            elif original.kind is TBoxElementKind.PROPERTY:
                kind = "PROPERTY"
            conflict_id = canonical_json_hash(
                {
                    "contract": "KNOWLEDGE_STUDIO_TBOX_CONFLICT_V1",
                    "original": original_document,
                    "proposed": proposed_document,
                }
            )
            conflicts.append(
                {
                    "conflict_id": conflict_id,
                    "kind": kind,
                    "stable_element_id": item.stable_element_id,
                    "field": "element",
                    "original_value": original_document,
                    "proposed_value": proposed_document,
                }
            )
        return tuple(conflicts)

    @classmethod
    def _resolve_proposal_elements(
        cls,
        *,
        current: tuple[TBoxElementInput, ...],
        proposed: tuple[TBoxElementInput, ...],
        conflicts: tuple[dict[str, object], ...],
        merge_strategy: TBoxMergeStrategy,
        resolution_by_conflict: dict[str, dict[str, str]],
    ) -> tuple[TBoxElementInput, ...]:
        conflict_by_stable_id = {str(item["stable_element_id"]): item for item in conflicts}
        current_by_id = {item.stable_element_id: item for item in current}
        current_by_name = {(item.kind, item.canonical_name.casefold()): item for item in current}
        accepted: list[TBoxElementInput] = []
        reference_rewrites: dict[str, str] = {}
        for item in proposed:
            conflict = conflict_by_stable_id.get(item.stable_element_id)
            if conflict is None:
                accepted.append(item)
                continue
            action = (
                TBoxMergeResolution.KEEP_ORIGINAL
                if merge_strategy is TBoxMergeStrategy.KEEP_ORIGINAL
                else TBoxMergeResolution.ACCEPT_PROPOSAL
                if merge_strategy is TBoxMergeStrategy.ACCEPT_PROPOSAL
                else TBoxMergeResolution(
                    resolution_by_conflict[str(conflict["conflict_id"])]["action"]
                )
            )
            if action is TBoxMergeResolution.KEEP_ORIGINAL:
                original = current_by_id.get(item.stable_element_id) or current_by_name.get(
                    (item.kind, item.canonical_name.casefold())
                )
                if original is not None:
                    reference_rewrites[item.stable_element_id] = original.stable_element_id
                continue
            if action is TBoxMergeResolution.ACCEPT_PROPOSAL:
                accepted.append(item)
                continue
            resolution = resolution_by_conflict[str(conflict["conflict_id"])]
            renamed_id = resolution.get("renamed_stable_element_id", "")
            renamed_name = resolution.get("renamed_canonical_name", "")
            renamed_display = resolution.get("renamed_display_name", renamed_name)
            renamed = replace(
                item,
                stable_element_id=renamed_id,
                canonical_name=renamed_name,
                display_name=renamed_display,
            )
            renamed.validate()
            reference_rewrites[item.stable_element_id] = renamed.stable_element_id
            accepted.append(renamed)

        def rewrite_reference(value: str | None) -> str | None:
            return reference_rewrites.get(value, value) if value is not None else None

        return tuple(
            replace(
                item,
                parent_stable_element_id=rewrite_reference(item.parent_stable_element_id),
                source_stable_element_id=rewrite_reference(item.source_stable_element_id),
                target_stable_element_id=rewrite_reference(item.target_stable_element_id),
            )
            for item in accepted
        )

    @staticmethod
    def _tbox_document(item: TBoxElementInput) -> dict[str, object]:
        return {
            "stable_element_id": item.stable_element_id,
            "kind": item.kind.value,
            "canonical_name": item.canonical_name,
            "display_name": item.display_name,
            "parent_stable_element_id": item.parent_stable_element_id,
            "source_stable_element_id": item.source_stable_element_id,
            "target_stable_element_id": item.target_stable_element_id,
            "data_type": item.data_type,
            "nullable": item.nullable,
            "definition": item.definition,
            "aliases": list(item.aliases),
            "unit": item.unit,
            "vector_index_enabled": item.vector_index_enabled,
        }

    @staticmethod
    def _tbox_input(item: KnowledgeStudioTBoxElementRecord) -> TBoxElementInput:
        try:
            return TBoxElementInput(
                stable_element_id=item.stable_element_id,
                kind=TBoxElementKind(item.kind),
                canonical_name=item.canonical_name,
                display_name=item.display_name,
                parent_stable_element_id=item.parent_stable_element_id,
                source_stable_element_id=item.source_stable_element_id,
                target_stable_element_id=item.target_stable_element_id,
                data_type=item.data_type,
                nullable=item.nullable,
                definition=item.definition,
                aliases=item.aliases,
                unit=item.unit,
                vector_index_enabled=item.vector_index_enabled,
                layout_x=item.layout_x,
                layout_y=item.layout_y,
            )
        except ValueError as error:
            raise ConflictError("The accepted T-Box element is invalid.") from error

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
