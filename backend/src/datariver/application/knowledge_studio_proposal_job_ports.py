from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalCompletion,
    KnowledgeStudioProposalDocument,
    KnowledgeStudioProposalJobClaim,
    KnowledgeStudioProposalJobPage,
    KnowledgeStudioProposalJobRecord,
)
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio_proposal_jobs import KnowledgeStudioProposalJobPins


class KnowledgeStudioProposalJobStore(Protocol):
    async def enqueue(
        self,
        *,
        pins: KnowledgeStudioProposalJobPins,
        request_hash: str,
        maximum_attempts: int,
        idempotency_key: str,
    ) -> KnowledgeStudioProposalJobRecord: ...

    async def get_owned(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        job_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeStudioProposalJobRecord | None: ...

    async def list_owned(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        actor_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeStudioProposalJobPage: ...

    async def cancel(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        expected_version: int,
        reason: str,
        request_hash: str,
        idempotency_key: str,
    ) -> KnowledgeStudioProposalJobRecord: ...

    async def retry(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        expected_version: int,
        request_hash: str,
        idempotency_key: str,
    ) -> KnowledgeStudioProposalJobRecord: ...


class KnowledgeStudioProposalDocumentReader(Protocol):
    async def read_document(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalDocument: ...


class KnowledgeStudioProposalJobWorkerStore(Protocol):
    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> KnowledgeStudioProposalJobClaim | None: ...

    async def renew(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        lease_seconds: int,
        stage: str,
        progress_percent: int,
    ) -> datetime: ...

    async def ensure_current(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        current_schema_binding: ModelBinding,
    ) -> str | None: ...

    async def complete(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        call_id: str,
        completion: KnowledgeStudioProposalCompletion,
    ) -> KnowledgeStudioProposalJobRecord: ...

    async def fail(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        call_id: str,
        failure_code: str,
        retryable: bool,
        stale: bool,
    ) -> None: ...
