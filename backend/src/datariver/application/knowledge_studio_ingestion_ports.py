from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio_ingestion import (
    StudioIngestionClaim,
    StudioIngestionMaterialization,
    StudioSourceProfilePin,
    StudioSourceRead,
    StudioVectorReceipt,
)


class KnowledgeStudioBatchSourceReader(Protocol):
    @property
    def manifest_id(self) -> str: ...

    @property
    def manifest_version(self) -> int: ...

    @property
    def manifest_hash(self) -> str: ...

    async def read(
        self,
        *,
        claim: StudioIngestionClaim,
        statement_fence: Callable[[], Awaitable[None]],
    ) -> tuple[StudioSourceRead, ...]: ...


class KnowledgeStudioIngestionSourceResolver(Protocol):
    @property
    def manifest_id(self) -> str: ...

    @property
    def manifest_version(self) -> int: ...

    @property
    def manifest_hash(self) -> str: ...

    def resolve_pin(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        source_version: str,
        projection_source_version: str,
    ) -> StudioSourceProfilePin | None: ...


class KnowledgeStudioIngestionWorkerStore(Protocol):
    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> StudioIngestionClaim | None: ...

    async def freeze_source_access(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        hard_timeout_seconds: int,
        completion_margin_seconds: int,
    ) -> datetime: ...

    async def assert_source_statement_fence(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
    ) -> None: ...

    async def renew(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        lease_seconds: int,
        stage: str,
        progress_percent: int,
    ) -> None: ...

    async def ensure_current(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        manifest_id: str,
        manifest_version: int,
        manifest_hash: str,
        current_embedding_binding: ModelBinding | None,
    ) -> str | None: ...

    async def complete(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        call_id: str,
        materialization: StudioIngestionMaterialization,
        vector_receipts: tuple[StudioVectorReceipt, ...],
        result_hash: str,
    ) -> UUID: ...

    async def fail(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        call_id: str,
        failure_code: str,
        retryable: bool,
        stale: bool,
    ) -> None: ...
