from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from datariver.domain.knowledge_pipeline import KnowledgeSourceSnapshot
from datariver.domain.knowledge_source_jobs import (
    KnowledgeSourceJobPins,
    KnowledgeSourceJobStage,
    KnowledgeSourceJobState,
)


@dataclass(frozen=True, slots=True)
class KnowledgeSourceJobResult:
    changeset_id: UUID
    page_count: int
    proposed_node_count: int
    proposed_edge_count: int
    evidence_hash: str
    embedding_model: str
    extraction_model: str


@dataclass(frozen=True, slots=True)
class KnowledgeSourceJobRecord:
    job_id: UUID
    workspace_id: UUID
    graph_id: UUID
    source_snapshot_id: UUID
    upload_id: UUID
    requested_by: UUID
    title: str
    state: KnowledgeSourceJobState
    stage: KnowledgeSourceJobStage
    progress: dict[str, int]
    attempt_count: int
    maximum_attempts: int
    next_attempt_at: datetime
    last_failure_code: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    result: KnowledgeSourceJobResult | None


@dataclass(frozen=True, slots=True)
class KnowledgeSourceJobPage:
    items: tuple[KnowledgeSourceJobRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeSourceJobClaim:
    job: KnowledgeSourceJobRecord
    pins: KnowledgeSourceJobPins
    source: KnowledgeSourceSnapshot
    entity_types: frozenset[str]
    edge_types: frozenset[str]
    attempt_id: UUID
    attempt_no: int
    lease_epoch: int
    worker_fingerprint: str
    lease_token: str = field(repr=False)
