from __future__ import annotations

from uuid import UUID

from datariver.application.dto import ChatEvidence, ChatExchange
from datariver.application.ports import CatalogIndexReader, ChatStore, KnowledgeEvidenceReader
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)


class ChatService:
    def __init__(
        self,
        *,
        catalog_index: CatalogIndexReader,
        knowledge_evidence: KnowledgeEvidenceReader | None = None,
        store: ChatStore,
        authorization: AuthorizationService,
    ) -> None:
        self._catalog_index = catalog_index
        self._knowledge_evidence = knowledge_evidence
        self._store = store
        self._authorization = authorization

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
                ChatEvidence(
                    resource_id=asset.asset_id,
                    name=asset.name,
                    description=asset.description,
                    source_locator=asset.external_urn,
                    source_version=asset.source_version,
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
                evidence.append(candidate.evidence)
                if len(evidence) >= maximum_evidence:
                    break
        answer = self._compose_answer(evidence)
        return await self._store.save_exchange(
            workspace_id=workspace_id,
            owner_id=subject.subject_id,
            session_id=session_id,
            question=question,
            answer=answer,
            evidence=evidence,
            policy_decision_id=chat_decision.decision_id,
        )

    @staticmethod
    def _search_term(question: str) -> str:
        tokens = [token.strip(".,?!:;()[]{}") for token in question.split()]
        candidates = [token for token in tokens if len(token) >= 2]
        return max(candidates, key=len)[:100] if candidates else question.strip()[:100]

    @staticmethod
    def _compose_answer(evidence: list[ChatEvidence]) -> str:
        if not evidence:
            return (
                "현재 접근 권한 범위에서 질문과 관련된 검증 가능한 카탈로그 근거를 찾지 못했습니다."
            )
        lines = ["접근 권한이 확인된 카탈로그·지식그래프 근거는 다음과 같습니다."]
        for index, item in enumerate(evidence, start=1):
            description = (item.description or "설명이 등록되지 않았습니다.").strip()
            lines.append(f"[{index}] {item.name}: {description[:500]}")
        return "\n".join(lines)
