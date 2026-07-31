from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.knowledge_pipeline import ModelBinding


class KnowledgeSourceJobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {
            self.SUCCEEDED,
            self.FAILED,
            self.STALE,
            self.CANCELLED,
        }


class KnowledgeSourceJobStage(StrEnum):
    QUEUED = "QUEUED"
    SOURCE_READ = "SOURCE_READ"
    PARSED = "PARSED"
    EMBEDDED = "EMBEDDED"
    EXTRACTED = "EXTRACTED"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"


_TRANSITIONS: dict[KnowledgeSourceJobState, frozenset[KnowledgeSourceJobState]] = {
    KnowledgeSourceJobState.QUEUED: frozenset(
        {
            KnowledgeSourceJobState.RUNNING,
            KnowledgeSourceJobState.CANCELLED,
        }
    ),
    KnowledgeSourceJobState.RUNNING: frozenset(
        {
            KnowledgeSourceJobState.RETRY_WAIT,
            KnowledgeSourceJobState.CANCEL_REQUESTED,
            KnowledgeSourceJobState.SUCCEEDED,
            KnowledgeSourceJobState.FAILED,
            KnowledgeSourceJobState.STALE,
            KnowledgeSourceJobState.CANCELLED,
        }
    ),
    KnowledgeSourceJobState.RETRY_WAIT: frozenset(
        {
            KnowledgeSourceJobState.RUNNING,
            KnowledgeSourceJobState.CANCELLED,
        }
    ),
    KnowledgeSourceJobState.CANCEL_REQUESTED: frozenset(
        {
            KnowledgeSourceJobState.CANCELLED,
            KnowledgeSourceJobState.FAILED,
            KnowledgeSourceJobState.STALE,
        }
    ),
    KnowledgeSourceJobState.SUCCEEDED: frozenset(),
    KnowledgeSourceJobState.FAILED: frozenset(),
    KnowledgeSourceJobState.STALE: frozenset(),
    KnowledgeSourceJobState.CANCELLED: frozenset(),
}


def require_knowledge_source_transition(
    *,
    current: KnowledgeSourceJobState,
    target: KnowledgeSourceJobState,
) -> None:
    if target not in _TRANSITIONS[current]:
        raise ValidationError(
            f"Knowledge source job transition {current.value} -> {target.value} is invalid."
        )


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError(f"The Knowledge source job {field} is invalid.")


@dataclass(frozen=True, slots=True)
class KnowledgeSourceJobPins:
    workspace_id: UUID
    graph_id: UUID
    source_snapshot_id: UUID
    upload_id: UUID
    source_storage_version: str
    source_content_sha256: str
    source_classification: int
    source_content_profile: str
    source_validation_evidence_hash: str
    graph_version: int
    base_release_id: UUID | None
    base_release_hash: str | None
    ontology_version_id: UUID
    ontology_checksum: str
    parser_configuration_hash: str
    embedding_binding: ModelBinding
    extraction_binding: ModelBinding
    prepared_at: datetime

    def validate(self) -> None:
        if (
            not self.source_storage_version
            or len(self.source_storage_version) > 255
            or self.source_classification not in {0, 1}
            or self.graph_version < 1
        ):
            raise ValidationError("The Knowledge source job source or graph binding is invalid.")
        _require_sha256(self.source_content_sha256, "source content hash")
        if not self.source_content_profile or len(self.source_content_profile) > 100:
            raise ValidationError("The Knowledge source job content profile is invalid.")
        _require_sha256(
            self.source_validation_evidence_hash,
            "source validation evidence hash",
        )
        _require_sha256(self.ontology_checksum, "ontology checksum")
        _require_sha256(self.parser_configuration_hash, "parser configuration hash")
        if (self.base_release_id is None) != (self.base_release_hash is None):
            raise ValidationError("The Knowledge source job base release binding is invalid.")
        if self.base_release_hash is not None:
            _require_sha256(self.base_release_hash, "base release hash")
        if self.prepared_at.tzinfo is None or self.prepared_at.utcoffset() is None:
            raise ValidationError(
                "The Knowledge source job preparation time must be timezone-aware."
            )
        self.embedding_binding.validate()
        self.extraction_binding.validate()

    def to_document(self) -> dict[str, object]:
        self.validate()
        base: dict[str, object]
        if self.base_release_id is None:
            base = {"kind": "EMPTY"}
        else:
            base = {
                "kind": "RELEASE",
                "release_id": str(self.base_release_id),
                "content_hash": self.base_release_hash,
            }
        document: dict[str, object] = {
            "contract": "KNOWLEDGE_SOURCE_JOB_PINS_V1",
            "workspace_id": str(self.workspace_id),
            "graph_id": str(self.graph_id),
            "source": {
                "snapshot_id": str(self.source_snapshot_id),
                "upload_id": str(self.upload_id),
                "storage_version": self.source_storage_version,
                "content_sha256": self.source_content_sha256,
                "classification": self.source_classification,
            },
            "graph_version": self.graph_version,
            "base": base,
            "ontology": {
                "version_id": str(self.ontology_version_id),
                "checksum": self.ontology_checksum,
            },
            "parser_configuration_hash": self.parser_configuration_hash,
            "embedding_binding": self.embedding_binding.to_document(),
            "extraction_binding": self.extraction_binding.to_document(),
            "prepared_at": self.prepared_at.isoformat(),
        }
        if self.source_content_profile == "KNOWLEDGE_SOURCE_DOCUMENT_V1":
            document["contract"] = "KNOWLEDGE_SOURCE_JOB_PINS_V2"
            source = document["source"]
            assert isinstance(source, dict)
            source["content_profile"] = self.source_content_profile
            source["validation_evidence_hash"] = self.source_validation_evidence_hash
        return document

    def evidence_hash(self) -> str:
        return canonical_json_hash(self.to_document())
