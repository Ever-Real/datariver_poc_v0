from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from datariver.application.classification_access import (
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    ClassificationRuleRecord,
    static_classification_access_floor,
)
from datariver.application.dto import (
    ChatDraft,
    ChatEvidence,
    ChatExchange,
    ChatRetentionBinding,
)
from datariver.application.evidence import build_evidence_chunk, evidence_chunk_is_valid
from datariver.application.ports import (
    CatalogIndexReader,
    ChatAnswerComposer,
    ChatPersistenceUnitOfWork,
    KnowledgeEvidenceReader,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.classification_access import ChatMode, SearchMode
from datariver.domain.common import ConflictError, uuid7
from datariver.domain.retention import RetentionPolicyState

UNVERIFIABLE_ANSWER = "검증 불가"


class DeterministicChatAnswerComposer:
    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> ChatDraft:
        del question
        if not evidence:
            return ChatDraft(answer=UNVERIFIABLE_ANSWER, cited_chunk_ids=())
        lines = ["접근 권한이 확인된 카탈로그·지식그래프 근거는 다음과 같습니다."]
        for index, item in enumerate(evidence, start=1):
            description = (item.description or "설명이 등록되지 않았습니다.").strip()
            lines.append(f"[{index}] {item.name}: {description[:500]}")
        return ChatDraft(
            answer="\n".join(lines),
            cited_chunk_ids=tuple(item.chunk_id for item in evidence),
        )


class ChatService:
    def __init__(
        self,
        *,
        catalog_index: CatalogIndexReader,
        knowledge_evidence: KnowledgeEvidenceReader | None = None,
        uow_factory: Callable[[], ChatPersistenceUnitOfWork],
        authorization: AuthorizationService,
        classification_access: ClassificationAccessResolver | None = None,
        composer: ChatAnswerComposer | None = None,
        allow_ephemeral_without_retention: bool = False,
    ) -> None:
        self._catalog_index = catalog_index
        self._knowledge_evidence = knowledge_evidence
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._classification_access = classification_access
        self._composer = composer or DeterministicChatAnswerComposer()
        self._allow_ephemeral_without_retention = allow_ephemeral_without_retention

    async def query(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        session_id: UUID | None,
        question: str,
        maximum_evidence: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ChatExchange:
        chat_decision = await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=session_id or workspace_id,
                workspace_id=workspace_id,
                resource_type="chat_session",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.INTERNAL,
                lifecycle="ACTIVE",
                owner_subject_id=subject.subject_id,
            ),
            action=Action.CHAT_QUERY,
            environment=environment,
            request_id=request_id,
        )
        access = await self._resolve_classification_access(
            subject=subject,
            now=environment.requested_at,
        )
        chat_access = self._chat_retrieval_access(access, subject=subject)
        allowed_chat_classifications = {
            rule.classification for rule in chat_access.rules if rule.search_mode is SearchMode.ABAC
        }
        page = await self._catalog_index.search(
            subject=replace(
                subject,
                clearance=self._chat_ceiling(
                    allowed_chat_classifications,
                    subject=subject,
                ),
            ),
            access=chat_access,
            query=self._search_term(question),
            filters={},
            cursor=None,
            limit=maximum_evidence,
        )
        catalog_items = tuple(
            item for item in page.items if item.classification in allowed_chat_classifications
        )
        catalog_resources = tuple(
            ResourceAttributes(
                resource_id=asset.asset_id,
                workspace_id=asset.workspace_id,
                resource_type="catalog_asset",
                owner_department_id=asset.owner_department_id,
                system_id=asset.system_id,
                domain_id=asset.domain_id,
                classification=asset.classification,
                lifecycle=asset.lifecycle,
            )
            for asset in catalog_items
        )
        authorized_catalog_ids = {
            resource.resource_id
            for resource in await self._authorization.filter_authorized(
                subject=subject,
                resources=catalog_resources,
                action=Action.CATALOG_READ,
                environment=environment,
                request_id=request_id,
                parent_resource_id=session_id or workspace_id,
            )
        }
        evidence: list[ChatEvidence] = []
        for asset in catalog_items:
            if asset.asset_id not in authorized_catalog_ids:
                continue
            evidence.append(
                build_evidence_chunk(
                    workspace_id=asset.workspace_id,
                    resource_id=asset.asset_id,
                    classification=asset.classification,
                    system_id=asset.system_id,
                    domain_id=asset.domain_id,
                    owner_department_id=asset.owner_department_id,
                    name=asset.name,
                    description=asset.description,
                    source_locator=asset.external_urn,
                    source_version=asset.source_version,
                    effective_from=asset.observed_at,
                    extraction_method="CATALOG_PROJECTION_V1",
                )
            )
        if self._knowledge_evidence is not None and len(evidence) < maximum_evidence:
            candidates = await self._knowledge_evidence.search_active_nodes(
                workspace_id=workspace_id,
                query=self._search_term(question),
                maximum_classification=int(
                    self._chat_ceiling(allowed_chat_classifications, subject=subject)
                ),
                limit=maximum_evidence - len(evidence),
            )
            candidates = tuple(
                candidate
                for candidate in candidates
                if candidate.classification in allowed_chat_classifications
            )
            knowledge_resources = tuple(
                ResourceAttributes(
                    resource_id=candidate.evidence.resource_id,
                    workspace_id=workspace_id,
                    resource_type="knowledge_node",
                    owner_department_id=None,
                    system_id=None,
                    domain_id=None,
                    classification=candidate.classification,
                    lifecycle="PUBLISHED",
                )
                for candidate in candidates
            )
            authorized_knowledge_ids = {
                resource.resource_id
                for resource in await self._authorization.filter_authorized(
                    subject=subject,
                    resources=knowledge_resources,
                    action=Action.KG_READ,
                    environment=environment,
                    request_id=request_id,
                    parent_resource_id=session_id or workspace_id,
                )
            }
            for candidate in candidates:
                if candidate.evidence.resource_id not in authorized_knowledge_ids:
                    continue
                if (
                    candidate.evidence.workspace_id != workspace_id
                    or candidate.evidence.classification != candidate.classification
                ):
                    continue
                evidence.append(candidate.evidence)
                if len(evidence) >= maximum_evidence:
                    break
        try:
            draft = await self._composer.compose(question=question, evidence=tuple(evidence))
        except Exception:
            draft = ChatDraft(answer=UNVERIFIABLE_ANSWER, cited_chunk_ids=())
        answer, cited_evidence = self._validate_draft(
            draft=draft,
            authorized_evidence=evidence,
            workspace_id=workspace_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            await uow.lock_retention_workspace(workspace_id=workspace_id)
            policy = await uow.retention_policies.get_active_for_update(workspace_id=workspace_id)
            if policy is None or policy.state is not RetentionPolicyState.ACTIVE:
                if self._allow_ephemeral_without_retention:
                    # This path deliberately returns before the unit of work
                    # commits. It preserves ABAC/evidence validation but does
                    # not create a Chat session, message, citation, or policy
                    # binding when the development workspace has no policy.
                    return ChatExchange(
                        session_id=session_id or uuid7(),
                        request_message_id=uuid7(),
                        response_message_id=uuid7(),
                        answer=answer,
                        evidence=cited_evidence,
                        persistence="EPHEMERAL_NO_STORE",
                    )
                raise ConflictError(
                    "An active retention policy is required to persist Chat content."
                )
            binding = ChatRetentionBinding(
                policy_id=policy.policy_id,
                policy_hash=policy.payload_hash,
                binding_basis_at=await uow.transaction_time(),
                chat_content_days=policy.rules.chat_content_days,
            )
            exchange = await uow.chats.save_exchange(
                workspace_id=workspace_id,
                owner_id=subject.subject_id,
                session_id=session_id,
                question=question,
                answer=answer,
                evidence=cited_evidence,
                policy_decision_id=chat_decision.decision_id,
                retention=binding,
            )
            await uow.commit()
            return exchange

    async def _resolve_classification_access(
        self,
        *,
        subject: SubjectAttributes,
        now: datetime,
    ) -> ClassificationAccessSnapshot:
        if self._classification_access is None:
            return static_classification_access_floor()
        return await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=now,
        )

    @staticmethod
    def _chat_retrieval_access(
        access: ClassificationAccessSnapshot,
        *,
        subject: SubjectAttributes,
    ) -> ClassificationAccessSnapshot:
        rules = tuple(
            ClassificationRuleRecord(
                classification=rule.classification,
                search_mode=(
                    SearchMode.ABAC
                    if rule.chat_mode is not ChatMode.DENY
                    and rule.classification <= subject.clearance
                    and rule.classification is not Classification.RESTRICTED
                    else SearchMode.DENY
                ),
                chat_mode=rule.chat_mode,
                provider_profile_version_id=rule.provider_profile_version_id,
            )
            for rule in access.rules
        )
        return replace(
            access,
            rules=rules,
            restricted_resource_ids=frozenset(),
            restricted_system_ids=frozenset(),
            restricted_domain_ids=frozenset(),
        )

    @staticmethod
    def _chat_ceiling(
        allowed: set[Classification],
        *,
        subject: SubjectAttributes,
    ) -> Classification:
        visible = tuple(
            classification
            for classification in allowed
            if classification <= subject.clearance
            and classification is not Classification.RESTRICTED
        )
        if not visible:
            return Classification.PUBLIC
        return max(visible)

    @staticmethod
    def _search_term(question: str) -> str:
        tokens = [token.strip(".,?!:;()[]{}") for token in question.split()]
        candidates = [token for token in tokens if len(token) >= 2]
        return max(candidates, key=len)[:100] if candidates else question.strip()[:100]

    @staticmethod
    def _validate_draft(
        *,
        draft: ChatDraft,
        authorized_evidence: Sequence[ChatEvidence],
        workspace_id: UUID,
    ) -> tuple[str, tuple[ChatEvidence, ...]]:
        authorized_by_id = {item.chunk_id: item for item in authorized_evidence}
        cited_ids = draft.cited_chunk_ids
        invalid = (
            not draft.answer.strip()
            or not cited_ids
            or len(cited_ids) != len(set(cited_ids))
            or len(authorized_by_id) != len(authorized_evidence)
            or any(chunk_id not in authorized_by_id for chunk_id in cited_ids)
        )
        if invalid:
            return UNVERIFIABLE_ANSWER, ()
        cited = tuple(authorized_by_id[chunk_id] for chunk_id in cited_ids)
        if any(
            item.workspace_id != workspace_id or not evidence_chunk_is_valid(item) for item in cited
        ):
            return UNVERIFIABLE_ANSWER, ()
        return draft.answer.strip(), cited
