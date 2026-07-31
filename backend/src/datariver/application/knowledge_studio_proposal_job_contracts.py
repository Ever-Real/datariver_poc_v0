from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from datariver.application.ports import KnowledgeStudioSchemaAssistant
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio import TBoxElementInput, TBoxProposalMode
from datariver.domain.knowledge_studio_proposal_jobs import (
    KnowledgeStudioProposalInputKind,
    KnowledgeStudioProposalJobPins,
    KnowledgeStudioProposalJobStage,
    KnowledgeStudioProposalJobState,
)


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalJobResult:
    proposal_id: UUID
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalJobRecord:
    job_id: UUID
    workspace_id: UUID
    draft_id: UUID
    requested_by: UUID
    input_kind: KnowledgeStudioProposalInputKind
    mode: TBoxProposalMode
    target_block_id: UUID | None
    state: KnowledgeStudioProposalJobState
    stage: KnowledgeStudioProposalJobStage
    progress_percent: int
    attempt_count: int
    maximum_attempts: int
    next_attempt_at: datetime
    last_failure_code: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    result: KnowledgeStudioProposalJobResult | None
    supersedes_job_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalJobPage:
    items: tuple[KnowledgeStudioProposalJobRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalJobClaim:
    job: KnowledgeStudioProposalJobRecord
    pins: KnowledgeStudioProposalJobPins
    current_elements: tuple[TBoxElementInput, ...]
    attempt_id: UUID
    attempt_no: int
    lease_epoch: int
    worker_fingerprint: str
    lease_token: str = field(repr=False)
    source_locator: KnowledgeStudioProposalSourceLocator | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalDocument:
    filename: str
    media_type: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalSourceLocator:
    """Ephemeral claim-only coordinates; never persisted in a job, event or API."""

    bucket: str = field(repr=False)
    object_key: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalRuntime:
    assistant: KnowledgeStudioSchemaAssistant
    binding: ModelBinding


@dataclass(frozen=True, slots=True)
class KnowledgeStudioProposalCompletion:
    elements: tuple[TBoxElementInput, ...]
    conflicts: tuple[dict[str, object], ...]
    prompt_label: str
    model_binding: dict[str, object]
    source_reference: dict[str, object]
    result_hash: str

    def validate(self) -> None:
        if not 1 <= len(self.elements) <= 500:
            raise ValidationError("A durable T-Box Proposal requires between 1 and 500 elements.")
        for element in self.elements:
            element.validate()
        if len(self.conflicts) > 500:
            raise ValidationError("The durable T-Box Proposal conflict set is too large.")
        if (
            self.prompt_label != self.prompt_label.strip()
            or not 1 <= len(self.prompt_label) <= 4_000
        ):
            raise ValidationError("The durable T-Box Proposal label is invalid.")
        if len(self.result_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.result_hash
        ):
            raise ValidationError("The durable T-Box Proposal result hash is invalid.")
        _reject_sensitive_source_keys(self.source_reference)
        if (
            len(
                json.dumps(
                    self.source_reference,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            > 65_536
        ):
            raise ValidationError("The durable T-Box Proposal source evidence is too large.")


def _reject_sensitive_source_keys(value: object) -> None:
    if isinstance(value, dict):
        forbidden = {
            "bucket",
            "object_key",
            "excerpt",
            "prompt",
            "provider_body",
            "content",
        }
        if any(str(key).casefold() in forbidden for key in value):
            raise ValidationError(
                "The durable T-Box Proposal source evidence contains sensitive payload data."
            )
        for nested in value.values():
            _reject_sensitive_source_keys(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            _reject_sensitive_source_keys(nested)
