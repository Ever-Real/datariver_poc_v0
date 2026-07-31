from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from datariver.application.dto import ChatEvidence
from datariver.application.evidence import build_evidence_chunk
from datariver.application.ports import GovernanceChatEvidenceReader
from datariver.application.services.governance_documents import GovernanceDocumentService
from datariver.domain.authz import EnvironmentAttributes, SubjectAttributes
from datariver.domain.governance_documents import GovernanceKnowledgeEvidence


class GovernanceDocumentChatEvidenceReader(GovernanceChatEvidenceReader):
    """Expose only current, authorized Governance Document chunks to Chat."""

    def __init__(self, service: GovernanceDocumentService) -> None:
        self._service = service

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        question: str,
        limit: int,
    ) -> tuple[ChatEvidence, ...]:
        values, _context = await self._service.search_knowledge(
            subject=subject,
            environment=environment,
            request_id=request_id,
            query=question,
            limit=limit,
        )
        return tuple(_chat_evidence(subject.workspace_id, value) for value in values)

    async def get_current(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        resource_ids: Sequence[UUID],
    ) -> tuple[ChatEvidence, ...]:
        values = await self._service.get_current_knowledge(
            subject=subject,
            environment=environment,
            request_id=request_id,
            chunk_ids=tuple(resource_ids),
        )
        return tuple(_chat_evidence(subject.workspace_id, value) for value in values)


def _chat_evidence(
    workspace_id: UUID,
    value: GovernanceKnowledgeEvidence,
) -> ChatEvidence:
    return build_evidence_chunk(
        workspace_id=workspace_id,
        resource_id=value.chunk_id,
        classification=value.classification,
        system_id=None,
        domain_id=None,
        owner_department_id=None,
        name=f"{value.document_title} ({value.version_tag})",
        description=value.excerpt,
        source_locator=(
            f"governance://documents/{value.document_id}/"
            f"versions/{value.document_version_id}#chunk={value.ordinal}"
        ),
        source_version=f"{value.document_version_id}:{value.content_sha256}",
        effective_from=value.published_at,
        extraction_method="GOVERNANCE_DOCUMENT_PGVECTOR_V1",
        source_type="GOVERNANCE_DOCUMENT",
    )
