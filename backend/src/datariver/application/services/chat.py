from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from datariver.application.dto import ChatDraft, ChatEvidence, ChatExchange
from datariver.application.evidence import build_evidence_chunk, evidence_chunk_is_valid
from datariver.application.ports import (
    CatalogIndexReader,
    ChatAnswerComposer,
    ChatStore,
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
        store: ChatStore,
        authorization: AuthorizationService,
        composer: ChatAnswerComposer | None = None,
    ) -> None:
        self._catalog_index = catalog_index
        self._knowledge_evidence = knowledge_evidence
        self._store = store
        self._authorization = authorization
        self._composer = composer or DeterministicChatAnswerComposer()

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
        page = await self._catalog_index.search(
            subject=subject,
            query=self._search_term(question),
            filters={},
            cursor=None,
            limit=maximum_evidence,
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
            for asset in page.items
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
        for asset in page.items:
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
                maximum_classification=int(subject.clearance),
                limit=maximum_evidence - len(evidence),
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
        return await self._store.save_exchange(
            workspace_id=workspace_id,
            owner_id=subject.subject_id,
            session_id=session_id,
            question=question,
            answer=answer,
            evidence=cited_evidence,
            policy_decision_id=chat_decision.decision_id,
        )

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
