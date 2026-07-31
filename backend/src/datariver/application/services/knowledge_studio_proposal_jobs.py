from __future__ import annotations

from uuid import UUID

from datariver.application.dto import (
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioTBoxRecord,
)
from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalJobPage,
    KnowledgeStudioProposalJobRecord,
)
from datariver.application.knowledge_studio_proposal_job_ports import (
    KnowledgeStudioProposalJobStore,
)
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash
from datariver.domain.knowledge_studio_proposal_jobs import KnowledgeStudioProposalJobPins

KNOWLEDGE_STUDIO_PROPOSAL_BASE_TBOX_CONTRACT = "KNOWLEDGE_STUDIO_PROPOSAL_BASE_TBOX_V1"


def knowledge_studio_proposal_base_tbox_document(
    record: KnowledgeStudioTBoxRecord,
) -> dict[str, object]:
    """Fold the exact accepted block/schema state into one deterministic document."""

    return {
        "contract": KNOWLEDGE_STUDIO_PROPOSAL_BASE_TBOX_CONTRACT,
        "draft_id": str(record.draft.draft_id),
        "blocks": [
            {
                "block_id": str(block.block_id),
                "kind": block.kind,
                "title": block.title,
                "weight": block.weight,
                "ordinal": block.ordinal,
                "elements": [
                    _element_record_document(element)
                    for element in sorted(
                        block.elements,
                        key=lambda value: (value.ordinal, value.stable_element_id),
                    )
                ],
            }
            for block in sorted(
                record.blocks,
                key=lambda value: (value.ordinal, str(value.block_id)),
            )
        ],
    }


def knowledge_studio_proposal_base_tbox_hash(
    record: KnowledgeStudioTBoxRecord,
) -> str:
    return canonical_json_hash(knowledge_studio_proposal_base_tbox_document(record))


class KnowledgeStudioProposalJobService:
    """Owner-scoped durable command façade.

    Draft authorization, accepted-manifest resolution and Catalog authorization happen
    before pin construction. PostgreSQL repeats the ownership and pin checks in the
    command functions; this service only accepts the typed, server-derived result.
    """

    def __init__(self, *, store: KnowledgeStudioProposalJobStore) -> None:
        self._store = store

    async def enqueue(
        self,
        *,
        pins: KnowledgeStudioProposalJobPins,
        request_hash: str,
        maximum_attempts: int,
        idempotency_key: str,
    ) -> KnowledgeStudioProposalJobRecord:
        pins.validate()
        _require_sha256(request_hash, "request hash")
        _require_idempotency_key(idempotency_key)
        if not 1 <= maximum_attempts <= 20:
            raise ValidationError("The Knowledge Studio Proposal job attempt limit is invalid.")
        record = await self._store.enqueue(
            pins=pins,
            request_hash=request_hash,
            maximum_attempts=maximum_attempts,
            idempotency_key=idempotency_key,
        )
        if (
            record.workspace_id != pins.workspace_id
            or record.draft_id != pins.draft_id
            or record.requested_by != pins.requested_by
            or record.input_kind is not pins.input_kind
            or record.mode is not pins.mode
            or record.target_block_id != pins.target_block_id
        ):
            raise ConflictError(
                "The Knowledge Studio Proposal job does not match the prepared request."
            )
        return record

    async def get_owned(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        job_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeStudioProposalJobRecord | None:
        return await self._store.get_owned(
            workspace_id=workspace_id,
            draft_id=draft_id,
            job_id=job_id,
            actor_id=actor_id,
        )

    async def list_owned(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        actor_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeStudioProposalJobPage:
        if not 1 <= limit <= 100:
            raise ValidationError("The Knowledge Studio Proposal job list limit is invalid.")
        return await self._store.list_owned(
            workspace_id=workspace_id,
            draft_id=draft_id,
            actor_id=actor_id,
            limit=limit,
            cursor=cursor,
        )

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
    ) -> KnowledgeStudioProposalJobRecord:
        normalized_reason = " ".join(reason.split())
        if not normalized_reason or len(normalized_reason) > 1_000:
            raise ValidationError("The Knowledge Studio Proposal cancellation reason is invalid.")
        _require_version(expected_version)
        _require_sha256(request_hash, "request hash")
        _require_idempotency_key(idempotency_key)
        return await self._store.cancel(
            workspace_id=workspace_id,
            draft_id=draft_id,
            job_id=job_id,
            actor_id=actor_id,
            expected_version=expected_version,
            reason=normalized_reason,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
        )

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
    ) -> KnowledgeStudioProposalJobRecord:
        _require_version(expected_version)
        _require_sha256(request_hash, "request hash")
        _require_idempotency_key(idempotency_key)
        retried = await self._store.retry(
            workspace_id=workspace_id,
            draft_id=draft_id,
            job_id=job_id,
            actor_id=actor_id,
            expected_version=expected_version,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
        )
        if (
            retried.job_id == job_id
            or retried.supersedes_job_id != job_id
            or retried.workspace_id != workspace_id
            or retried.draft_id != draft_id
            or retried.requested_by != actor_id
        ):
            raise ConflictError(
                "The Knowledge Studio Proposal retry did not create the expected successor."
            )
        return retried


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError(f"The Knowledge Studio Proposal job {field} is invalid.")


def _require_idempotency_key(value: str) -> None:
    if value != value.strip() or not 1 <= len(value) <= 200:
        raise ValidationError("The Knowledge Studio Proposal job idempotency key is invalid.")


def _require_version(value: int) -> None:
    if value < 1:
        raise ValidationError("The Knowledge Studio Proposal job version is invalid.")


def _element_record_document(
    element: KnowledgeStudioTBoxElementRecord,
) -> dict[str, object]:
    return {
        "stable_element_id": element.stable_element_id,
        "kind": element.kind,
        "canonical_name": element.canonical_name,
        "display_name": element.display_name,
        "parent_stable_element_id": element.parent_stable_element_id,
        "hierarchy_relation": element.hierarchy_relation,
        "source_stable_element_id": element.source_stable_element_id,
        "target_stable_element_id": element.target_stable_element_id,
        "data_type": element.data_type,
        "nullable": element.nullable,
        "definition": element.definition,
        "aliases": list(element.aliases),
        "unit": element.unit,
        "vector_index_enabled": element.vector_index_enabled,
        "metadata_reference_id": (
            str(element.metadata_reference_id)
            if element.metadata_reference_id is not None
            else None
        ),
        "metadata_reference_urn": element.metadata_reference_urn,
        "layout_x": element.layout_x,
        "layout_y": element.layout_y,
        "ordinal": element.ordinal,
    }
