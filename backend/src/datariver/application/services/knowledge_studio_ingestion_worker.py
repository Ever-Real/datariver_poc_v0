from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID, uuid4, uuid5

from datariver.application.errors import ExternalDependencyError
from datariver.application.knowledge_pipeline_ports import KnowledgeEmbeddingProvider
from datariver.application.knowledge_studio_ingestion_ports import (
    KnowledgeStudioBatchSourceReader,
    KnowledgeStudioIngestionWorkerStore,
)
from datariver.domain.common import ConflictError, DomainError, ValidationError, canonical_json_hash
from datariver.domain.knowledge import (
    ChangeOperationType,
    GraphChangeOperation,
    GraphEntityKind,
    Provenance,
)
from datariver.domain.knowledge_pipeline import ModelBinding, PdfPage
from datariver.domain.knowledge_studio_ingestion import (
    StudioIngestionClaim,
    StudioIngestionMaterialization,
    StudioIngestionRule,
    StudioSourceRead,
    StudioVectorInput,
    StudioVectorReceipt,
)


class KnowledgeStudioIngestionMapper:
    """Convert exact released Mapping rules and bounded source rows to typed node operations."""

    @staticmethod
    def materialize(
        *,
        claim: StudioIngestionClaim,
        reads: tuple[StudioSourceRead, ...],
    ) -> StudioIngestionMaterialization:
        claim.validate()
        by_pin = {read.binding_pin_id: read for read in reads}
        if len(by_pin) != len(reads) or set(by_pin) != {
            binding.pin_id for binding in claim.bindings
        }:
            raise ValidationError("The Studio source reader returned an incomplete Binding set.")
        operations: list[GraphChangeOperation] = []
        vector_inputs: list[StudioVectorInput] = []
        seen_entities: set[UUID] = set()
        receipt_hashes: list[str] = []
        for binding in claim.bindings:
            binding.validate()
            read = by_pin[binding.pin_id]
            read.validate()
            receipt_hashes.append(read.source_read_receipt_hash)
            subject_rule = next(rule for rule in binding.rules if rule.method == "SUBJECT_ID")
            property_rules = tuple(rule for rule in binding.rules if rule.method == "PROPERTY")
            allowed_fields = {rule.source_field_path for rule in binding.rules}
            for row in read.rows:
                if not set(row).issubset(allowed_fields):
                    raise ValidationError("The Studio source reader returned an unrequested field.")
                subject_value = row.get(subject_rule.source_field_path)
                if subject_value is None:
                    raise ValidationError("A Studio source row has no SUBJECT_ID value.")
                identity_hash = canonical_json_hash(
                    {
                        "contract": "STUDIO_DB_ENTITY_IDENTITY_V1",
                        "binding_version_id": str(binding.binding_version_id),
                        "target_class_stable_id": binding.target_class_stable_id,
                        "subject": _typed_scalar_document(subject_value),
                    }
                )
                entity_id = uuid5(claim.graph_id, identity_hash)
                if entity_id in seen_entities:
                    raise ValidationError("The Studio source repeats an entity identity.")
                seen_entities.add(entity_id)
                properties: dict[str, object] = {}
                for rule in property_rules:
                    value = row.get(rule.source_field_path)
                    if value is None:
                        if rule.target_nullable is False:
                            raise ValidationError(
                                "A required Studio Property Mapping produced a null value."
                            )
                        continue
                    properties[rule.target_canonical_name] = value
                    if rule.vector_index_enabled:
                        vector_inputs.append(
                            _vector_input(
                                entity_id=entity_id,
                                rule=rule,
                                value=value,
                            )
                        )
                provenance = Provenance(
                    source_ref=f"knowledge-studio-binding:{binding.binding_version_id}",
                    source_locator=(
                        f"catalog-asset:{binding.source_asset_id}#identity-sha256={identity_hash}"
                    ),
                    source_version=(
                        f"{binding.source_version}@{binding.projection_source_version}"
                    ),
                    method="DB_MAPPING_IDENTITY_V1",
                    confidence=1.0,
                )
                operation = GraphChangeOperation(
                    sequence=len(operations) + 1,
                    operation=ChangeOperationType.UPSERT,
                    entity_kind=GraphEntityKind.NODE,
                    stable_entity_id=entity_id,
                    document={
                        "entity_type": binding.target_class_canonical_name,
                        "properties": properties,
                        "classification": binding.source_classification,
                    },
                    provenance=(provenance,),
                    confidence=1.0,
                )
                operation.require_classification_ceiling(
                    maximum_classification=claim.graph_classification
                )
                operations.append(operation)
                if len(operations) > 100_000:
                    raise ValidationError(
                        "The Studio ingestion operation count exceeds its hard limit."
                    )
        materialization = StudioIngestionMaterialization(
            operations=tuple(operations),
            vector_inputs=tuple(vector_inputs),
            source_read_receipt_hash=canonical_json_hash(
                {
                    "contract": "STUDIO_DB_SOURCE_READ_SET_V1",
                    "job_id": str(claim.job_id),
                    "receipts": sorted(receipt_hashes),
                }
            ),
        )
        materialization.validate()
        return materialization


class KnowledgeStudioIngestionWorker:
    def __init__(
        self,
        *,
        store: KnowledgeStudioIngestionWorkerStore,
        source_reader: KnowledgeStudioBatchSourceReader,
        embedding_provider: KnowledgeEmbeddingProvider | None,
        current_embedding_binding: Callable[[], ModelBinding | None],
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
        source_hard_timeout_seconds: int,
        completion_margin_seconds: int,
    ) -> None:
        self._store = store
        self._source_reader = source_reader
        self._embedding_provider = embedding_provider
        self._current_embedding_binding = current_embedding_binding
        self._workspace_id = workspace_id
        self._worker_subject_id = worker_subject_id
        self._worker_fingerprint = worker_fingerprint
        self._lease_seconds = lease_seconds
        self._source_hard_timeout_seconds = source_hard_timeout_seconds
        self._completion_margin_seconds = completion_margin_seconds

    async def run_once(self) -> bool:
        claim = await self._store.claim_next(
            workspace_id=self._workspace_id,
            worker_subject_id=self._worker_subject_id,
            worker_fingerprint=self._worker_fingerprint,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return False
        claim.validate()
        try:
            drift = await self._ensure_current(claim)
            if drift is not None:
                await self._fail(
                    claim=claim,
                    failure_code=drift,
                    retryable=False,
                    stale=True,
                )
                return True
            deadline = await self._store.freeze_source_access(
                claim=claim,
                worker_subject_id=self._worker_subject_id,
                hard_timeout_seconds=self._source_hard_timeout_seconds,
                completion_margin_seconds=self._completion_margin_seconds,
            )
            claim = replace(claim, source_access_deadline=deadline)

            async def statement_fence() -> None:
                await self._store.assert_source_statement_fence(
                    claim=claim,
                    worker_subject_id=self._worker_subject_id,
                )

            reads = await self._source_reader.read(
                claim=claim,
                statement_fence=statement_fence,
            )
            await self._store.renew(
                claim=claim,
                worker_subject_id=self._worker_subject_id,
                lease_seconds=self._lease_seconds,
                stage="MAPPING",
                progress_percent=65,
            )
            materialization = KnowledgeStudioIngestionMapper.materialize(
                claim=claim,
                reads=reads,
            )
            vector_receipts = await self._embed(
                claim=claim,
                materialization=materialization,
            )
            await self._store.renew(
                claim=claim,
                worker_subject_id=self._worker_subject_id,
                lease_seconds=self._lease_seconds,
                stage="FINALIZING",
                progress_percent=95,
            )
            drift = await self._ensure_current(claim)
            if drift is not None:
                await self._fail(
                    claim=claim,
                    failure_code=drift,
                    retryable=False,
                    stale=True,
                )
                return True
            result_hash = materialization.result_hash(vector_receipts=vector_receipts)
            await self._store.complete(
                claim=claim,
                worker_subject_id=self._worker_subject_id,
                call_id=str(uuid4()),
                materialization=materialization,
                vector_receipts=vector_receipts,
                result_hash=result_hash,
            )
        except ConflictError as error:
            await self._fail(
                claim=claim,
                failure_code=_failure_code(error),
                retryable=False,
                stale=bool(error.details.get("stale", False)),
            )
        except DomainError as error:
            await self._fail(
                claim=claim,
                failure_code=_failure_code(error),
                retryable=(
                    isinstance(error, ExternalDependencyError)
                    and bool(error.details.get("retryable", False))
                ),
                stale=False,
            )
        except Exception as error:
            await self._fail(
                claim=claim,
                failure_code=f"UNEXPECTED_{type(error).__name__}".upper()[:100],
                retryable=True,
                stale=False,
            )
        return True

    async def _ensure_current(self, claim: StudioIngestionClaim) -> str | None:
        return await self._store.ensure_current(
            claim=claim,
            worker_subject_id=self._worker_subject_id,
            manifest_id=self._source_reader.manifest_id,
            manifest_version=self._source_reader.manifest_version,
            manifest_hash=self._source_reader.manifest_hash,
            current_embedding_binding=self._current_embedding_binding(),
        )

    async def _embed(
        self,
        *,
        claim: StudioIngestionClaim,
        materialization: StudioIngestionMaterialization,
    ) -> tuple[StudioVectorReceipt, ...]:
        if not materialization.vector_inputs:
            return ()
        if claim.embedding_binding is None or self._embedding_provider is None:
            raise ConflictError(
                "The pinned Studio embedding runtime is unavailable.",
                details={"stale": True, "code": "STALE_EMBEDDING_BINDING"},
            )
        await self._store.renew(
            claim=claim,
            worker_subject_id=self._worker_subject_id,
            lease_seconds=self._lease_seconds,
            stage="EMBEDDING",
            progress_percent=80,
        )
        pages = tuple(
            PdfPage(
                page_number=index,
                text=value.text,
                content_sha256=value.content_hash,
            )
            for index, value in enumerate(materialization.vector_inputs, start=1)
        )
        batch = await self._embedding_provider.embed_pages(
            pages=pages,
            binding=claim.embedding_binding,
        )
        if batch.binding.to_document() != claim.embedding_binding.to_document():
            raise ConflictError(
                "The Studio embedding provider returned a different binding.",
                details={"stale": True, "code": "STALE_EMBEDDING_BINDING"},
            )
        vectors = {value.page_number: value.vector for value in batch.embeddings}
        if set(vectors) != set(range(1, len(pages) + 1)):
            raise ValidationError("The Studio embedding provider returned incomplete vectors.")
        dimensions = {len(vector) for vector in vectors.values()}
        if len(dimensions) != 1:
            raise ValidationError("The Studio embedding dimensions are inconsistent.")
        receipts: list[StudioVectorReceipt] = []
        for index, vector_input in enumerate(materialization.vector_inputs, start=1):
            vector = tuple(float(value) for value in vectors[index])
            if (
                not vector
                or len(vector) > 16_384
                or any(not math.isfinite(value) for value in vector)
            ):
                raise ValidationError("The Studio embedding vector is invalid.")
            receipt = StudioVectorReceipt(
                entity_id=vector_input.entity_id,
                property_stable_id=vector_input.property_stable_id,
                content_hash=vector_input.content_hash,
                dimension=len(vector),
                vector=vector,
                vector_hash=canonical_json_hash(list(vector)),
            )
            receipt.validate()
            receipts.append(receipt)
        return tuple(receipts)

    async def _fail(
        self,
        *,
        claim: StudioIngestionClaim,
        failure_code: str,
        retryable: bool,
        stale: bool,
    ) -> None:
        await self._store.fail(
            claim=claim,
            worker_subject_id=self._worker_subject_id,
            call_id=str(uuid4()),
            failure_code=failure_code,
            retryable=retryable,
            stale=stale,
        )


def _typed_scalar_document(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"type": "BOOLEAN", "value": value}
    if isinstance(value, int):
        return {"type": "INTEGER", "value": value}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("The Studio source identity is not finite.")
        return {"type": "NUMBER", "value": value}
    if isinstance(value, str):
        if not value or len(value) > 8_000:
            raise ValidationError("The Studio source identity is outside its text bound.")
        return {"type": "STRING", "value": value}
    raise ValidationError("The Studio source identity type is unsupported.")


def _vector_input(
    *,
    entity_id: UUID,
    rule: StudioIngestionRule,
    value: object,
) -> StudioVectorInput:
    if not isinstance(value, str):
        raise ValidationError("A Vector Index Mapping produced a non-text value.")
    text = " ".join(value.split())
    if not text or len(text) > 8_000:
        raise ValidationError("A Vector Index Mapping produced invalid bounded text.")
    result = StudioVectorInput(
        entity_id=entity_id,
        property_stable_id=rule.target_stable_element_id,
        text=text,
        content_hash=canonical_json_hash(
            {
                "contract": "STUDIO_VECTOR_INPUT_V1",
                "entity_id": str(entity_id),
                "property_stable_id": rule.target_stable_element_id,
                "text": text,
            }
        ),
    )
    result.validate()
    return result


def _failure_code(error: DomainError) -> str:
    raw = str(error.details.get("code") or error.details.get("provider_code") or error.code)
    normalized = "".join(
        character if character.isascii() and character.isalnum() else "_" for character in raw
    ).strip("_")
    return (normalized or type(error).__name__).upper()[:100]
