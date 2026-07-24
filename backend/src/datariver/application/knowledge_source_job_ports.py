from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.application.knowledge_source_job_contracts import (
    KnowledgeSourceJobClaim,
    KnowledgeSourceJobPage,
    KnowledgeSourceJobRecord,
)
from datariver.domain.knowledge_pipeline import KnowledgeSourceAnalysis, ModelBinding


class KnowledgeSourceJobStore(Protocol):
    async def enqueue(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        upload_id: UUID,
        actor_id: UUID,
        title: str,
        request_hash: str,
        requester_authorization_hash: str,
        embedding_binding: ModelBinding,
        extraction_binding: ModelBinding,
        maximum_attempts: int,
        idempotency_key: str,
    ) -> KnowledgeSourceJobRecord: ...

    async def get_owned(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        job_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeSourceJobRecord | None: ...

    async def list_owned(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        actor_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceJobPage: ...

    async def cancel(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        expected_version: int,
        reason: str,
        request_hash: str,
        idempotency_key: str,
    ) -> KnowledgeSourceJobRecord: ...


class KnowledgeSourceJobWorkerStore(Protocol):
    async def claim_next(
        self,
        *,
        worker_fingerprint: str,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> KnowledgeSourceJobClaim | None: ...

    async def renew(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        lease_seconds: int,
        stage: str,
        progress: dict[str, int],
    ) -> datetime: ...

    async def ensure_current(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        current_embedding_binding: ModelBinding,
        current_extraction_binding: ModelBinding,
    ) -> str | None: ...

    async def mark_cancelled(self, *, claim: KnowledgeSourceJobClaim) -> None: ...

    async def mark_failed(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        failure_code: str,
        retryable: bool,
    ) -> None: ...

    async def mark_stale(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        failure_code: str,
    ) -> None: ...

    async def finalize(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        analysis: KnowledgeSourceAnalysis,
        current_embedding_binding: ModelBinding,
        current_extraction_binding: ModelBinding,
    ) -> KnowledgeSourceJobRecord: ...
