from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.knowledge import GraphChangeOperation
from datariver.domain.knowledge_pipeline import ModelBinding

StudioSourceScalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class StudioSourceProfilePin:
    workspace_id: UUID
    asset_id: UUID
    source_version: str
    projection_source_version: str
    connection_profile_id: str
    connection_profile_version: int
    connection_profile_hash: str

    def validate(self) -> None:
        if (
            not self.source_version
            or not self.projection_source_version
            or not self.connection_profile_id
            or self.connection_profile_version < 1
        ):
            raise ValidationError("The Studio source profile pin is invalid.")
        _require_sha256(self.connection_profile_hash, "connection profile hash")


class StudioIngestionState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {
            self.SUCCESS,
            self.FAILED,
            self.STALE,
            self.CANCELLED,
        }


class StudioIngestionStage(StrEnum):
    QUEUED = "QUEUED"
    SOURCE_READ = "SOURCE_READ"
    MAPPING = "MAPPING"
    EMBEDDING = "EMBEDDING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class StudioIngestionRule:
    method: str
    source_field_path: str
    target_stable_element_id: str
    target_canonical_name: str
    target_data_type: str | None
    target_nullable: bool | None
    vector_index_enabled: bool
    transform_id: str
    transform_version: str

    def validate(self) -> None:
        if self.method not in {"SUBJECT_ID", "PROPERTY"}:
            raise ValidationError("The Studio ingestion Mapping method is unsupported.")
        if (
            not self.source_field_path
            or len(self.source_field_path) > 2_000
            or not self.target_stable_element_id
            or not self.target_canonical_name
            or self.transform_id != "IDENTITY"
            or self.transform_version != "1"
        ):
            raise ValidationError("The Studio ingestion Mapping rule is invalid.")
        if self.method == "SUBJECT_ID":
            if (
                self.target_data_type is not None
                or self.target_nullable is not None
                or self.vector_index_enabled
            ):
                raise ValidationError("A SUBJECT_ID rule must target its owning Class.")
        elif self.target_data_type is None or self.target_nullable is None:
            raise ValidationError("A PROPERTY rule requires released Property metadata.")
        target_data_type = self.target_data_type
        if (
            self.vector_index_enabled
            and target_data_type is not None
            and target_data_type.upper() not in {"STRING", "TEXT"}
        ):
            raise ValidationError("A Vector Index Mapping must target a text Property.")


@dataclass(frozen=True, slots=True)
class StudioIngestionBindingClaim:
    pin_id: UUID
    binding_version_id: UUID
    source_reference_id: UUID
    source_asset_id: UUID
    source_version: str
    projection_source_version: str
    source_classification: int
    target_class_stable_id: str
    target_class_canonical_name: str
    mapping_hash: str
    connection_profile_id: str
    connection_profile_version: int
    connection_profile_hash: str
    rules: tuple[StudioIngestionRule, ...]

    def validate(self) -> None:
        if (
            not self.source_version
            or not self.projection_source_version
            or self.source_classification not in range(4)
            or not self.target_class_stable_id
            or not self.target_class_canonical_name
            or self.connection_profile_version < 1
        ):
            raise ValidationError("The Studio ingestion Binding pin is invalid.")
        _require_sha256(self.mapping_hash, "Mapping hash")
        _require_sha256(self.connection_profile_hash, "connection profile hash")
        for rule in self.rules:
            rule.validate()
        subject_rules = tuple(rule for rule in self.rules if rule.method == "SUBJECT_ID")
        if len(subject_rules) != 1:
            raise ValidationError("A Class Binding requires exactly one SUBJECT_ID rule.")
        if subject_rules[0].target_stable_element_id != self.target_class_stable_id:
            raise ValidationError("The SUBJECT_ID rule does not target its released Class.")
        property_targets = [
            rule.target_stable_element_id for rule in self.rules if rule.method == "PROPERTY"
        ]
        if len(property_targets) != len(set(property_targets)):
            raise ValidationError("A Class Binding repeats a Property Mapping.")


@dataclass(frozen=True, slots=True)
class StudioIngestionClaim:
    workspace_id: UUID
    job_id: UUID
    graph_id: UUID
    draft_id: UUID
    studio_release_id: UUID
    ontology_version_id: UUID
    requested_by: UUID
    graph_classification: int
    manifest_id: str
    manifest_version: int
    manifest_hash: str
    pin_hash: str
    embedding_binding: ModelBinding | None
    bindings: tuple[StudioIngestionBindingClaim, ...]
    attempt_id: UUID
    attempt_no: int
    lease_epoch: int
    worker_fingerprint: str
    source_access_deadline: datetime | None = None
    lease_token: str = field(repr=False, default="")

    def validate(self) -> None:
        if (
            self.graph_classification not in range(4)
            or not self.manifest_id
            or self.manifest_version < 1
            or not self.bindings
            or self.attempt_no < 1
            or self.lease_epoch < 1
            or not self.worker_fingerprint
            or not self.lease_token
        ):
            raise ValidationError("The Studio ingestion claim is invalid.")
        _require_sha256(self.manifest_hash, "manifest hash")
        _require_sha256(self.pin_hash, "pin hash")
        if self.embedding_binding is not None:
            self.embedding_binding.validate()
        for binding in self.bindings:
            binding.validate()


@dataclass(frozen=True, slots=True)
class StudioSourceRead:
    binding_pin_id: UUID
    rows: tuple[Mapping[str, StudioSourceScalar], ...]
    source_read_receipt_hash: str

    def validate(self) -> None:
        _require_sha256(self.source_read_receipt_hash, "source-read receipt hash")


@dataclass(frozen=True, slots=True)
class StudioVectorInput:
    entity_id: UUID
    property_stable_id: str
    text: str
    content_hash: str

    def validate(self) -> None:
        if (
            not self.property_stable_id
            or not self.text
            or len(self.text) > 8_000
            or self.text != self.text.strip()
        ):
            raise ValidationError("The Studio vector input is invalid.")
        _require_sha256(self.content_hash, "vector content hash")


@dataclass(frozen=True, slots=True)
class StudioVectorReceipt:
    entity_id: UUID
    property_stable_id: str
    content_hash: str
    dimension: int
    vector: tuple[float, ...]
    vector_hash: str

    def validate(self) -> None:
        _require_sha256(self.content_hash, "vector content hash")
        _require_sha256(self.vector_hash, "vector hash")
        if (
            not 1 <= self.dimension <= 16_384
            or self.dimension != len(self.vector)
            or any(not math.isfinite(value) for value in self.vector)
        ):
            raise ValidationError("The Studio vector dimension is invalid.")


@dataclass(frozen=True, slots=True)
class StudioIngestionMaterialization:
    operations: tuple[GraphChangeOperation, ...]
    vector_inputs: tuple[StudioVectorInput, ...]
    source_read_receipt_hash: str

    def validate(self) -> None:
        if not self.operations or len(self.operations) > 100_000:
            raise ValidationError("The Studio ingestion operation count is outside its bound.")
        _require_sha256(self.source_read_receipt_hash, "source-read receipt hash")
        for operation in self.operations:
            operation.validate()
        for vector_input in self.vector_inputs:
            vector_input.validate()

    def result_hash(self, *, vector_receipts: tuple[StudioVectorReceipt, ...]) -> str:
        self.validate()
        for receipt in vector_receipts:
            receipt.validate()
        return canonical_json_hash(
            {
                "contract": "STUDIO_DB_INGESTION_RESULT_V1",
                "source_read_receipt_hash": self.source_read_receipt_hash,
                "operations": [
                    {
                        "sequence": operation.sequence,
                        "operation": operation.operation.value,
                        "entity_kind": operation.entity_kind.value,
                        "stable_entity_id": str(operation.stable_entity_id),
                        "document": operation.document,
                        "provenance": [
                            provenance.to_document() for provenance in operation.provenance
                        ],
                        "confidence": operation.confidence,
                    }
                    for operation in self.operations
                ],
                "vectors": [
                    {
                        "entity_id": str(receipt.entity_id),
                        "property_stable_id": receipt.property_stable_id,
                        "content_hash": receipt.content_hash,
                        "dimension": receipt.dimension,
                        "vector_hash": receipt.vector_hash,
                    }
                    for receipt in vector_receipts
                ],
            }
        )


def _require_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError(f"The Studio ingestion {label} is invalid.")
