from __future__ import annotations

import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import TextClause

from datariver.application.errors import ExternalDependencyError
from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalCompletion,
    KnowledgeStudioProposalJobClaim,
    KnowledgeStudioProposalJobPage,
    KnowledgeStudioProposalJobRecord,
    KnowledgeStudioProposalJobResult,
    KnowledgeStudioProposalSourceLocator,
)
from datariver.application.knowledge_studio_proposal_job_ports import (
    KnowledgeStudioProposalJobStore,
    KnowledgeStudioProposalJobWorkerStore,
)
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio import (
    TBoxElementInput,
    TBoxElementKind,
    TBoxProposalMode,
)
from datariver.domain.knowledge_studio_proposal_jobs import (
    KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V1,
    KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
    KnowledgeStudioAcceptedUploadPin,
    KnowledgeStudioCatalogFieldMetadataPin,
    KnowledgeStudioCatalogSourcePin,
    KnowledgeStudioProposalInputKind,
    KnowledgeStudioProposalJobPins,
    KnowledgeStudioProposalJobStage,
    KnowledgeStudioProposalJobState,
)
from datariver.infrastructure.db.rls import set_security_context

KNOWLEDGE_STUDIO_PROPOSAL_JOB_COMMAND_FUNCTION_SIGNATURES = (
    "knowledge.request_tbox_proposal_job_v1("
    "uuid,uuid,uuid,uuid,text,text,integer,text,text,text,jsonb,text,text,jsonb,text,text,integer,text"
    ")",
    "knowledge.get_owned_tbox_proposal_job_v1(uuid,uuid,uuid,uuid)",
    "knowledge.list_owned_tbox_proposal_jobs_v1(uuid,uuid,uuid,integer,text)",
    "knowledge.cancel_tbox_proposal_job_v1(uuid,uuid,uuid,uuid,integer,text,text,text)",
    "knowledge.retry_tbox_proposal_job_v1(uuid,uuid,uuid,uuid,integer,text,text)",
)
KNOWLEDGE_STUDIO_PROPOSAL_JOB_WORKER_FUNCTION_SIGNATURES = (
    "knowledge.claim_tbox_proposal_job_v1(uuid,text,text,integer)",
    "knowledge.renew_tbox_proposal_job_v1(uuid,uuid,uuid,bigint,text,text,integer,text,integer)",
    "knowledge.ensure_tbox_proposal_job_current_v1(uuid,uuid,uuid,bigint,text,text,jsonb)",
    "knowledge.complete_tbox_proposal_job_v1("
    "uuid,uuid,uuid,bigint,text,text,text,jsonb,jsonb,text,jsonb,jsonb,text"
    ")",
    "knowledge.fail_tbox_proposal_job_v1("
    "uuid,uuid,uuid,bigint,text,text,text,text,boolean,boolean"
    ")",
)

_REQUEST = text(
    """
    SELECT knowledge.request_tbox_proposal_job_v1(
        :workspace_id, :draft_id, :requested_by, :target_block_id,
        :input_kind, :mode, :base_draft_version, :base_tbox_hash,
        :request_hash, :requester_authorization_hash, :source_pin,
        :source_pin_hash, :parser_configuration_hash, :schema_binding,
        :schema_binding_hash, :pin_hash, :maximum_attempts, :idempotency_key
    )
    """
).bindparams(
    bindparam("source_pin", type_=JSONB),
    bindparam("schema_binding", type_=JSONB),
)
_GET = text(
    """
    SELECT knowledge.get_owned_tbox_proposal_job_v1(
        :workspace_id, :draft_id, :job_id, :actor_id
    )
    """
)
_LIST = text(
    """
    SELECT knowledge.list_owned_tbox_proposal_jobs_v1(
        :workspace_id, :draft_id, :actor_id, :limit, :cursor
    )
    """
)
_CANCEL = text(
    """
    SELECT knowledge.cancel_tbox_proposal_job_v1(
        :workspace_id, :draft_id, :job_id, :actor_id, :expected_version,
        :reason, :request_hash, :idempotency_key
    )
    """
)
_RETRY = text(
    """
    SELECT knowledge.retry_tbox_proposal_job_v1(
        :workspace_id, :draft_id, :job_id, :actor_id, :expected_version,
        :request_hash, :idempotency_key
    )
    """
)
_CLAIM = text(
    """
    SELECT knowledge.claim_tbox_proposal_job_v1(
        :workspace_id, :worker_fingerprint, :lease_token, :lease_seconds
    )
    """
)
_RENEW = text(
    """
    SELECT knowledge.renew_tbox_proposal_job_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :lease_seconds, :stage, :progress_percent
    )
    """
)
_ENSURE_CURRENT = text(
    """
    SELECT knowledge.ensure_tbox_proposal_job_current_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :schema_binding
    )
    """
).bindparams(bindparam("schema_binding", type_=JSONB))
_COMPLETE = text(
    """
    SELECT knowledge.complete_tbox_proposal_job_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :call_id, :elements, :conflicts, :prompt_label,
        :model_binding, :source_reference, :result_hash
    )
    """
).bindparams(
    bindparam("elements", type_=JSONB),
    bindparam("conflicts", type_=JSONB),
    bindparam("model_binding", type_=JSONB),
    bindparam("source_reference", type_=JSONB),
)
_FAIL = text(
    """
    SELECT knowledge.fail_tbox_proposal_job_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :call_id, :failure_code, :retryable, :stale
    )
    """
)


class SqlKnowledgeStudioProposalJobStore(KnowledgeStudioProposalJobStore):
    """Human command wrapper; PostgreSQL owns pinning and idempotent transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        pins: KnowledgeStudioProposalJobPins,
        request_hash: str,
        maximum_attempts: int,
        idempotency_key: str,
    ) -> KnowledgeStudioProposalJobRecord:
        pins.validate()
        await set_security_context(
            self._session,
            workspace_id=pins.workspace_id,
            subject_id=pins.requested_by,
        )
        try:
            document = await self._session.scalar(
                _REQUEST,
                {
                    "workspace_id": pins.workspace_id,
                    "draft_id": pins.draft_id,
                    "requested_by": pins.requested_by,
                    "target_block_id": pins.target_block_id,
                    "input_kind": pins.input_kind.value,
                    "mode": pins.mode.value,
                    "base_draft_version": pins.base_draft_version,
                    "base_tbox_hash": pins.base_tbox_hash,
                    "request_hash": request_hash,
                    "requester_authorization_hash": pins.requester_authorization_hash,
                    "source_pin": pins.source.to_document(),
                    "source_pin_hash": canonical_json_hash(pins.source.to_document()),
                    "parser_configuration_hash": pins.parser_configuration_hash,
                    "schema_binding": pins.schema_binding.to_document(),
                    "schema_binding_hash": canonical_json_hash(pins.schema_binding.to_document()),
                    "pin_hash": pins.evidence_hash(),
                    "maximum_attempts": maximum_attempts,
                    "idempotency_key": idempotency_key,
                },
            )
        except DBAPIError as error:
            _raise_database_contract(error, operation="request")
            raise
        return _job_record(_mapping(document, "T-Box Proposal job"))

    async def get_owned(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        job_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeStudioProposalJobRecord | None:
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=actor_id,
        )
        try:
            document = await self._session.scalar(
                _GET,
                {
                    "workspace_id": workspace_id,
                    "draft_id": draft_id,
                    "job_id": job_id,
                    "actor_id": actor_id,
                },
            )
        except DBAPIError as error:
            _raise_database_contract(error, operation="read")
            raise
        if document is None:
            return None
        return _job_record(_mapping(document, "T-Box Proposal job"))

    async def list_owned(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        actor_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeStudioProposalJobPage:
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=actor_id,
        )
        try:
            document = await self._session.scalar(
                _LIST,
                {
                    "workspace_id": workspace_id,
                    "draft_id": draft_id,
                    "actor_id": actor_id,
                    "limit": limit,
                    "cursor": cursor,
                },
            )
        except DBAPIError as error:
            _raise_database_contract(error, operation="list")
            raise
        value = _mapping(document, "T-Box Proposal job page")
        _exact_keys(value, {"items", "next_cursor"}, "T-Box Proposal job page")
        raw_items = value["items"]
        if not isinstance(raw_items, list) or len(raw_items) > limit:
            raise ValidationError("The T-Box Proposal job page items are invalid.")
        raw_cursor = value["next_cursor"]
        if raw_cursor is not None and (
            not isinstance(raw_cursor, str) or not 1 <= len(raw_cursor) <= 2_000
        ):
            raise ValidationError("The T-Box Proposal job page cursor is invalid.")
        return KnowledgeStudioProposalJobPage(
            items=tuple(_job_record(_mapping(item, "T-Box Proposal job")) for item in raw_items),
            next_cursor=raw_cursor,
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
        return await self._owner_transition(
            statement=_CANCEL,
            workspace_id=workspace_id,
            draft_id=draft_id,
            job_id=job_id,
            actor_id=actor_id,
            parameters={
                "expected_version": expected_version,
                "reason": reason,
                "request_hash": request_hash,
                "idempotency_key": idempotency_key,
            },
            operation="cancel",
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
        return await self._owner_transition(
            statement=_RETRY,
            workspace_id=workspace_id,
            draft_id=draft_id,
            job_id=job_id,
            actor_id=actor_id,
            parameters={
                "expected_version": expected_version,
                "request_hash": request_hash,
                "idempotency_key": idempotency_key,
            },
            operation="retry",
        )

    async def _owner_transition(
        self,
        *,
        statement: TextClause,
        workspace_id: UUID,
        draft_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        parameters: Mapping[str, object],
        operation: str,
    ) -> KnowledgeStudioProposalJobRecord:
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=actor_id,
        )
        try:
            document = await self._session.scalar(
                statement,
                {
                    "workspace_id": workspace_id,
                    "draft_id": draft_id,
                    "job_id": job_id,
                    "actor_id": actor_id,
                    **parameters,
                },
            )
        except DBAPIError as error:
            _raise_database_contract(error, operation=operation)
            raise
        return _job_record(_mapping(document, f"T-Box Proposal job {operation}"))


class SqlKnowledgeStudioProposalJobWorkerStore(KnowledgeStudioProposalJobWorkerStore):
    """Function-only adapter for the dedicated LOGIN/NOBYPASSRLS Proposal worker.

    Every SECURITY DEFINER worker function must independently require an active
    SERVICE_ACCOUNT membership whose action set is exactly ``kg.proposal.execute``
    and whose groups contain ``knowledge-proposal-workers``.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> KnowledgeStudioProposalJobClaim | None:
        lease_token = secrets.token_urlsafe(32)
        try:
            async with self._session_factory() as session, session.begin():
                await set_security_context(
                    session,
                    workspace_id=workspace_id,
                    subject_id=worker_subject_id,
                )
                document = await session.scalar(
                    _CLAIM,
                    {
                        "workspace_id": workspace_id,
                        "worker_fingerprint": worker_fingerprint,
                        "lease_token": lease_token,
                        "lease_seconds": lease_seconds,
                    },
                )
        except DBAPIError as error:
            _raise_database_contract(error, operation="claim")
            raise
        if document is None:
            return None
        return _claim_from_document(
            _mapping(document, "T-Box Proposal job claim"),
            lease_token=lease_token,
        )

    async def renew(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        lease_seconds: int,
        stage: str,
        progress_percent: int,
    ) -> datetime:
        value = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_RENEW,
            extra={
                "lease_seconds": lease_seconds,
                "stage": stage,
                "progress_percent": progress_percent,
            },
        )
        return _datetime(value, "T-Box Proposal job lease")

    async def ensure_current(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        current_schema_binding: ModelBinding,
    ) -> str | None:
        current_schema_binding.validate()
        value = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_ENSURE_CURRENT,
            extra={"schema_binding": current_schema_binding.to_document()},
        )
        if value is None:
            return None
        result = _text(value, "T-Box Proposal drift result", 100)
        if result != "CANCELLED" and not result.startswith("STALE_"):
            raise ConflictError("The database returned an invalid T-Box Proposal drift result.")
        return result

    async def complete(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        call_id: str,
        completion: KnowledgeStudioProposalCompletion,
    ) -> KnowledgeStudioProposalJobRecord:
        completion.validate()
        document = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_COMPLETE,
            extra={
                "call_id": call_id,
                "elements": [_element_document(item) for item in completion.elements],
                "conflicts": list(completion.conflicts),
                "prompt_label": completion.prompt_label,
                "model_binding": completion.model_binding,
                "source_reference": completion.source_reference,
                "result_hash": completion.result_hash,
            },
        )
        return _job_record(_mapping(document, "completed T-Box Proposal job"))

    async def fail(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        call_id: str,
        failure_code: str,
        retryable: bool,
        stale: bool,
    ) -> None:
        await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_FAIL,
            extra={
                "call_id": call_id,
                "failure_code": failure_code,
                "retryable": retryable,
                "stale": stale,
            },
        )

    async def _claim_scalar(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
        worker_subject_id: UUID,
        statement: TextClause,
        extra: Mapping[str, object] | None = None,
    ) -> object:
        parameters = _claim_parameters(claim)
        parameters.update(extra or {})
        try:
            async with self._session_factory() as session, session.begin():
                await set_security_context(
                    session,
                    workspace_id=claim.job.workspace_id,
                    subject_id=worker_subject_id,
                )
                return await session.scalar(statement, parameters)
        except DBAPIError as error:
            _raise_database_contract(error, operation="worker transition")
            raise


def _claim_parameters(claim: KnowledgeStudioProposalJobClaim) -> dict[str, object]:
    return {
        "workspace_id": claim.job.workspace_id,
        "job_id": claim.job.job_id,
        "attempt_id": claim.attempt_id,
        "lease_epoch": claim.lease_epoch,
        "lease_token": claim.lease_token,
        "worker_fingerprint": claim.worker_fingerprint,
    }


def _claim_from_document(
    document: Mapping[str, object],
    *,
    lease_token: str,
) -> KnowledgeStudioProposalJobClaim:
    _exact_keys(
        document,
        {
            "job",
            "pins",
            "current_elements",
            "attempt_id",
            "attempt_no",
            "lease_epoch",
            "worker_fingerprint",
            "source_locator",
        },
        "T-Box Proposal job claim",
    )
    raw_elements = document["current_elements"]
    if not isinstance(raw_elements, list) or len(raw_elements) > 500:
        raise ValidationError("The T-Box Proposal claim element set is invalid.")
    raw_locator = document["source_locator"]
    source_locator = (
        _source_locator(_mapping(raw_locator, "T-Box Proposal source locator"))
        if raw_locator is not None
        else None
    )
    claim = KnowledgeStudioProposalJobClaim(
        job=_job_record(_mapping(document["job"], "T-Box Proposal job")),
        pins=_pins(_mapping(document["pins"], "T-Box Proposal job pins")),
        current_elements=tuple(_element(_mapping(item, "T-Box element")) for item in raw_elements),
        attempt_id=_uuid(document["attempt_id"], "attempt"),
        attempt_no=_integer(document["attempt_no"], "attempt number", 1, 20),
        lease_epoch=_integer(document["lease_epoch"], "lease epoch", 1, 2**63 - 1),
        worker_fingerprint=_text(
            document["worker_fingerprint"],
            "worker fingerprint",
            255,
        ),
        lease_token=lease_token,
        source_locator=source_locator,
    )
    if (
        claim.job.workspace_id != claim.pins.workspace_id
        or claim.job.draft_id != claim.pins.draft_id
        or claim.job.requested_by != claim.pins.requested_by
        or claim.job.input_kind is not claim.pins.input_kind
        or claim.job.mode is not claim.pins.mode
        or claim.job.target_block_id != claim.pins.target_block_id
        or claim.job.attempt_count != claim.attempt_no
        or claim.job.state is not KnowledgeStudioProposalJobState.RUNNING
        or claim.job.stage is not KnowledgeStudioProposalJobStage.SOURCE_VALIDATION
        or (claim.pins.input_kind is KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA)
        != (claim.source_locator is not None)
    ):
        raise ConflictError("The T-Box Proposal job claim does not match its immutable pins.")
    claim.pins.validate()
    return claim


def _source_locator(document: Mapping[str, object]) -> KnowledgeStudioProposalSourceLocator:
    _exact_keys(document, {"bucket", "object_key"}, "T-Box Proposal source locator")
    bucket = _text(document["bucket"], "source bucket", 255)
    object_key = _text(document["object_key"], "source object key", 2_000)
    if bucket in {".", ".."} or object_key in {".", ".."}:
        raise ValidationError("The T-Box Proposal source locator is invalid.")
    return KnowledgeStudioProposalSourceLocator(bucket=bucket, object_key=object_key)


def _pins(document: Mapping[str, object]) -> KnowledgeStudioProposalJobPins:
    _exact_keys(
        document,
        {
            "contract",
            "workspace_id",
            "draft_id",
            "requested_by",
            "input_kind",
            "mode",
            "target_block_id",
            "base_draft_version",
            "base_tbox_hash",
            "source",
            "parser_configuration_hash",
            "schema_binding",
            "requester_authorization_hash",
            "prepared_at",
        },
        "T-Box Proposal job pins",
    )
    if document["contract"] != "KNOWLEDGE_STUDIO_TBOX_PROPOSAL_JOB_PINS_V1":
        raise ValidationError("The T-Box Proposal job pin contract is unsupported.")
    input_kind = KnowledgeStudioProposalInputKind(
        _text(document["input_kind"], "Proposal input kind", 32)
    )
    raw_source = _mapping(document["source"], "T-Box Proposal source pin")
    source = (
        _accepted_upload_pin(raw_source)
        if input_kind is KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA
        else _catalog_source_pin(raw_source)
    )
    target = document["target_block_id"]
    result = KnowledgeStudioProposalJobPins(
        workspace_id=_uuid(document["workspace_id"], "workspace"),
        draft_id=_uuid(document["draft_id"], "Draft"),
        requested_by=_uuid(document["requested_by"], "requester"),
        input_kind=input_kind,
        mode=TBoxProposalMode(_text(document["mode"], "Proposal mode", 32)),
        target_block_id=_uuid(target, "target block") if target is not None else None,
        base_draft_version=_integer(
            document["base_draft_version"],
            "base Draft version",
            1,
            2**31 - 1,
        ),
        base_tbox_hash=_sha256(document["base_tbox_hash"], "base T-Box hash"),
        source=source,
        parser_configuration_hash=_sha256(
            document["parser_configuration_hash"],
            "parser configuration hash",
        ),
        schema_binding=_model_binding(_mapping(document["schema_binding"], "schema binding")),
        requester_authorization_hash=_sha256(
            document["requester_authorization_hash"],
            "requester authorization hash",
        ),
        prepared_at=_datetime(document["prepared_at"], "preparation time"),
    )
    result.validate()
    return result


def _accepted_upload_pin(
    document: Mapping[str, object],
) -> KnowledgeStudioAcceptedUploadPin:
    _exact_keys(
        document,
        {
            "kind",
            "manifest_id",
            "manifest_version",
            "content_sha256",
            "media_type",
            "size_bytes",
            "classification",
            "content_profile",
            "validation_evidence_hash",
            "filename",
        },
        "accepted upload pin",
    )
    if document["kind"] != KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA.value:
        raise ValidationError("The accepted upload pin kind is invalid.")
    result = KnowledgeStudioAcceptedUploadPin(
        manifest_id=_uuid(document["manifest_id"], "manifest"),
        manifest_version=_integer(
            document["manifest_version"],
            "manifest version",
            1,
            2**31 - 1,
        ),
        content_sha256=_sha256(document["content_sha256"], "source content hash"),
        media_type=_text(document["media_type"], "source media type", 255),
        size_bytes=_integer(document["size_bytes"], "source size", 1, 10 * 1024 * 1024),
        classification=_integer(document["classification"], "classification", 0, 1),
        content_profile=_text(document["content_profile"], "content profile", 100),
        validation_evidence_hash=_sha256(
            document["validation_evidence_hash"],
            "validation evidence hash",
        ),
        filename=_text(document["filename"], "source filename", 255),
    )
    result.validate()
    return result


def _catalog_source_pin(document: Mapping[str, object]) -> KnowledgeStudioCatalogSourcePin:
    contract_version = document.get(
        "contract_version",
        KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V1,
    )
    if not isinstance(contract_version, str) or contract_version not in {
        KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V1,
        KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
    }:
        raise ValidationError("The Catalog source pin contract is unsupported.")
    v1_keys = {
        "kind",
        "asset_id",
        "name",
        "asset_type",
        "classification",
        "source_version",
        "projection_source_version",
        "selected_field_paths",
        "platform",
        "database_name",
        "schema_name",
        "domain",
        "tags",
        "glossary_terms",
    }
    _exact_keys(
        document,
        v1_keys
        if contract_version == KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V1
        else v1_keys
        | {
            "contract_version",
            "description",
            "description_truncated",
            "field_metadata",
            "metadata_fingerprint",
        },
        "Catalog source pin",
    )
    if document["kind"] != KnowledgeStudioProposalInputKind.CATALOG_SCHEMA.value:
        raise ValidationError("The Catalog source pin kind is invalid.")
    raw_field_metadata = document.get("field_metadata", [])
    if not isinstance(raw_field_metadata, list):
        raise ValidationError("The Catalog source field metadata is invalid.")
    field_metadata: list[KnowledgeStudioCatalogFieldMetadataPin] = []
    for raw_item in raw_field_metadata:
        item = _mapping(raw_item, "Catalog field metadata")
        _exact_keys(
            item,
            {
                "field_path",
                "field_type",
                "native_data_type",
                "description",
                "description_truncated",
                "tags",
                "tags_truncated",
                "glossary_terms",
                "terms_truncated",
            },
            "Catalog field metadata",
        )
        field_metadata.append(
            KnowledgeStudioCatalogFieldMetadataPin(
                field_path=_text(item["field_path"], "Catalog field path", 2_000),
                field_type=_optional_text(item["field_type"], 500),
                native_data_type=_optional_text(item["native_data_type"], 500),
                description=_optional_text(item["description"], 1_000),
                description_truncated=_boolean(
                    item["description_truncated"],
                    "Catalog field description truncation",
                ),
                tags=_string_tuple(
                    item["tags"],
                    "Catalog field tags",
                    maximum_items=20,
                    maximum_length=240,
                    allow_empty=True,
                ),
                tags_truncated=_boolean(
                    item["tags_truncated"],
                    "Catalog field tag truncation",
                ),
                glossary_terms=_string_tuple(
                    item["glossary_terms"],
                    "Catalog field glossary terms",
                    maximum_items=20,
                    maximum_length=240,
                    allow_empty=True,
                ),
                terms_truncated=_boolean(
                    item["terms_truncated"],
                    "Catalog field term truncation",
                ),
            )
        )
    result = KnowledgeStudioCatalogSourcePin(
        asset_id=_uuid(document["asset_id"], "Catalog asset"),
        name=_text(document["name"], "Catalog source name", 255),
        asset_type=_text(document["asset_type"], "Catalog asset type", 100),
        classification=_integer(document["classification"], "classification", 0, 1),
        source_version=_text(document["source_version"], "source version", 255),
        projection_source_version=_text(
            document["projection_source_version"],
            "projection source version",
            255,
        ),
        selected_field_paths=_string_tuple(
            document["selected_field_paths"],
            "selected field paths",
            maximum_items=100,
            maximum_length=2_000,
        ),
        platform=_optional_text(document["platform"], 255),
        database_name=_optional_text(document["database_name"], 255),
        schema_name=_optional_text(document["schema_name"], 255),
        domain=_optional_text(document["domain"], 255),
        tags=_string_tuple(
            document["tags"],
            "Catalog tags",
            maximum_items=100,
            maximum_length=255,
            allow_empty=True,
        ),
        glossary_terms=_string_tuple(
            document["glossary_terms"],
            "Catalog glossary terms",
            maximum_items=100,
            maximum_length=255,
            allow_empty=True,
        ),
        contract_version=str(contract_version),
        description=_optional_text(document.get("description"), 1_000),
        description_truncated=_boolean(
            document.get("description_truncated", False),
            "Catalog description truncation",
        ),
        field_metadata=tuple(field_metadata),
        metadata_fingerprint=(
            _sha256(document["metadata_fingerprint"], "Catalog metadata fingerprint")
            if contract_version == KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2
            else None
        ),
    )
    result.validate()
    return result


def _job_record(document: Mapping[str, object]) -> KnowledgeStudioProposalJobRecord:
    _exact_keys(
        document,
        {
            "job_id",
            "workspace_id",
            "draft_id",
            "requested_by",
            "input_kind",
            "mode",
            "target_block_id",
            "state",
            "stage",
            "progress_percent",
            "attempt_count",
            "maximum_attempts",
            "next_attempt_at",
            "last_failure_code",
            "version",
            "created_at",
            "updated_at",
            "completed_at",
            "result",
            "supersedes_job_id",
        },
        "T-Box Proposal job",
    )
    raw_target = document["target_block_id"]
    raw_completed = document["completed_at"]
    raw_supersedes = document["supersedes_job_id"]
    raw_result = document["result"]
    result = (
        _job_result(_mapping(raw_result, "T-Box Proposal job result"))
        if raw_result is not None
        else None
    )
    record = KnowledgeStudioProposalJobRecord(
        job_id=_uuid(document["job_id"], "job"),
        workspace_id=_uuid(document["workspace_id"], "workspace"),
        draft_id=_uuid(document["draft_id"], "Draft"),
        requested_by=_uuid(document["requested_by"], "requester"),
        input_kind=KnowledgeStudioProposalInputKind(
            _text(document["input_kind"], "input kind", 32)
        ),
        mode=TBoxProposalMode(_text(document["mode"], "Proposal mode", 32)),
        target_block_id=(_uuid(raw_target, "target block") if raw_target is not None else None),
        state=KnowledgeStudioProposalJobState(_text(document["state"], "job state", 24)),
        stage=KnowledgeStudioProposalJobStage(_text(document["stage"], "job stage", 32)),
        progress_percent=_integer(document["progress_percent"], "progress", 0, 100),
        attempt_count=_integer(document["attempt_count"], "attempt count", 0, 20),
        maximum_attempts=_integer(document["maximum_attempts"], "attempt limit", 1, 20),
        next_attempt_at=_datetime(document["next_attempt_at"], "next attempt time"),
        last_failure_code=_optional_text(document["last_failure_code"], 100),
        version=_integer(document["version"], "job version", 1, 2**31 - 1),
        created_at=_datetime(document["created_at"], "creation time"),
        updated_at=_datetime(document["updated_at"], "update time"),
        completed_at=(
            _datetime(raw_completed, "completion time") if raw_completed is not None else None
        ),
        result=result,
        supersedes_job_id=(
            _uuid(raw_supersedes, "superseded job") if raw_supersedes is not None else None
        ),
    )
    terminal = record.state.terminal
    if (
        record.attempt_count > record.maximum_attempts
        or terminal != (record.completed_at is not None)
        or terminal != (record.stage is KnowledgeStudioProposalJobStage.COMPLETED)
        or (record.state is KnowledgeStudioProposalJobState.SUCCEEDED) != (result is not None)
    ):
        raise ConflictError("The T-Box Proposal job lifecycle evidence is inconsistent.")
    if (
        (
            record.state
            in {
                KnowledgeStudioProposalJobState.QUEUED,
                KnowledgeStudioProposalJobState.RETRY_WAIT,
            }
            and record.progress_percent != 0
        )
        or (
            record.state
            in {
                KnowledgeStudioProposalJobState.RUNNING,
                KnowledgeStudioProposalJobState.CANCEL_REQUESTED,
            }
            and not 1 <= record.progress_percent <= 99
        )
        or (
            record.state is KnowledgeStudioProposalJobState.SUCCEEDED
            and record.progress_percent != 100
        )
        or (
            record.state
            in {
                KnowledgeStudioProposalJobState.FAILED,
                KnowledgeStudioProposalJobState.STALE,
                KnowledgeStudioProposalJobState.CANCELLED,
            }
            and not 0 <= record.progress_percent <= 99
        )
    ):
        raise ConflictError("The T-Box Proposal job progress does not match its state.")
    requires_failure = record.state in {
        KnowledgeStudioProposalJobState.RETRY_WAIT,
        KnowledgeStudioProposalJobState.FAILED,
        KnowledgeStudioProposalJobState.STALE,
    }
    if requires_failure != (record.last_failure_code is not None):
        raise ConflictError("The T-Box Proposal job failure evidence does not match its state.")
    return record


def _job_result(document: Mapping[str, object]) -> KnowledgeStudioProposalJobResult:
    _exact_keys(document, {"proposal_id", "evidence_hash"}, "T-Box Proposal job result")
    return KnowledgeStudioProposalJobResult(
        proposal_id=_uuid(document["proposal_id"], "Proposal"),
        evidence_hash=_sha256(document["evidence_hash"], "result evidence hash"),
    )


def _element(document: Mapping[str, object]) -> TBoxElementInput:
    _exact_keys(
        document,
        {
            "stable_element_id",
            "kind",
            "canonical_name",
            "display_name",
            "parent_stable_element_id",
            "hierarchy_relation",
            "source_stable_element_id",
            "target_stable_element_id",
            "data_type",
            "nullable",
            "definition",
            "aliases",
            "unit",
            "vector_index_enabled",
            "metadata_reference_id",
            "metadata_reference_urn",
            "layout_x",
            "layout_y",
        },
        "T-Box element",
    )
    metadata_reference_id = document["metadata_reference_id"]
    nullable = document["nullable"]
    vector = document["vector_index_enabled"]
    layout_x = document["layout_x"]
    layout_y = document["layout_y"]
    if nullable is not None and not isinstance(nullable, bool):
        raise ValidationError("The T-Box element nullable value is invalid.")
    if not isinstance(vector, bool):
        raise ValidationError("The T-Box element Vector Index value is invalid.")
    result = TBoxElementInput(
        stable_element_id=_text(document["stable_element_id"], "stable element ID", 128),
        kind=TBoxElementKind(_text(document["kind"], "element kind", 16)),
        canonical_name=_text(document["canonical_name"], "canonical name", 255),
        display_name=_text(document["display_name"], "display name", 255),
        parent_stable_element_id=_optional_text(
            document["parent_stable_element_id"],
            128,
        ),
        hierarchy_relation=_optional_text(document["hierarchy_relation"], 255),
        source_stable_element_id=_optional_text(
            document["source_stable_element_id"],
            128,
        ),
        target_stable_element_id=_optional_text(
            document["target_stable_element_id"],
            128,
        ),
        data_type=_optional_text(document["data_type"], 255),
        nullable=nullable,
        definition=_optional_text(document["definition"], 4_000),
        aliases=_string_tuple(
            document["aliases"],
            "aliases",
            maximum_items=50,
            maximum_length=255,
            allow_empty=True,
        ),
        unit=_optional_text(document["unit"], 100),
        vector_index_enabled=vector,
        metadata_reference_id=(
            _uuid(metadata_reference_id, "metadata reference")
            if metadata_reference_id is not None
            else None
        ),
        metadata_reference_urn=_optional_text(
            document["metadata_reference_urn"],
            2_000,
        ),
        layout_x=_optional_number(layout_x, "layout x"),
        layout_y=_optional_number(layout_y, "layout y"),
    )
    result.validate()
    return result


def _element_document(item: TBoxElementInput) -> dict[str, object]:
    item.validate()
    return {
        "stable_element_id": item.stable_element_id,
        "kind": item.kind.value,
        "canonical_name": item.canonical_name,
        "display_name": item.display_name,
        "parent_stable_element_id": item.parent_stable_element_id,
        "hierarchy_relation": item.hierarchy_relation,
        "source_stable_element_id": item.source_stable_element_id,
        "target_stable_element_id": item.target_stable_element_id,
        "data_type": item.data_type,
        "nullable": item.nullable,
        "definition": item.definition,
        "aliases": list(item.aliases),
        "unit": item.unit,
        "vector_index_enabled": item.vector_index_enabled,
        "metadata_reference_id": (
            str(item.metadata_reference_id) if item.metadata_reference_id is not None else None
        ),
        "metadata_reference_urn": item.metadata_reference_urn,
        "layout_x": item.layout_x,
        "layout_y": item.layout_y,
    }


def _model_binding(document: Mapping[str, object]) -> ModelBinding:
    _exact_keys(
        document,
        {
            "provider",
            "model",
            "prompt_version",
            "tool_schema_version",
            "configuration_source",
            "configuration_version",
            "configuration_hash",
        },
        "schema binding",
    )
    configuration_version = document["configuration_version"]
    if configuration_version is not None:
        configuration_version = _integer(
            configuration_version,
            "schema binding configuration version",
            1,
            2**31 - 1,
        )
    result = ModelBinding(
        provider=_text(document["provider"], "schema provider", 200),
        model=_text(document["model"], "schema model", 200),
        prompt_version=_text(document["prompt_version"], "prompt version", 200),
        tool_schema_version=_text(
            document["tool_schema_version"],
            "tool schema version",
            200,
        ),
        configuration_source=_optional_text(document["configuration_source"], 64),
        configuration_version=configuration_version,
        configuration_hash=_optional_sha256(
            document["configuration_hash"],
            "schema configuration hash",
        ),
    )
    result.validate()
    return result


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValidationError(f"The {label} is invalid.")
    return cast(Mapping[str, object], value)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"The {label} is invalid.")
    return value


def _exact_keys(document: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(document) != expected:
        raise ValidationError(f"The {label} fields do not match the contract.")


def _uuid(value: object, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ValidationError(f"The {label} ID is invalid.") from error


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip():
        raise ValidationError(f"The {label} is invalid.")
    return value


def _optional_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, "optional text", maximum)


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValidationError(f"The {label} is invalid.")
    return value


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationError(f"The {label} is invalid.")
    return value


def _optional_sha256(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, label)


def _datetime(value: object, label: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValidationError(f"The {label} is invalid.") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"The {label} is invalid.")
    return value


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValidationError(f"The {label} is invalid.")
    return float(value)


def _string_tuple(
    value: object,
    label: str,
    *,
    maximum_items: int,
    maximum_length: int,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items or (not allow_empty and not value):
        raise ValidationError(f"The {label} are invalid.")
    result = tuple(_text(item, label, maximum_length) for item in value)
    if len(set(result)) != len(result):
        raise ValidationError(f"The {label} must be unique.")
    return result


def _raise_database_contract(error: DBAPIError, *, operation: str) -> None:
    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate == "42501":
        raise ForbiddenError(f"The T-Box Proposal job {operation} is not permitted.") from error
    if sqlstate in {"23503", "23505", "40001", "55000"}:
        raise ConflictError(f"The T-Box Proposal job {operation} changed concurrently.") from error
    if sqlstate in {"57014", "57P01", "08000", "08003", "08006"}:
        raise ExternalDependencyError(
            f"The T-Box Proposal job {operation} dependency is unavailable.",
            dependency="postgresql",
            retryable=True,
            provider_code="TBOX_PROPOSAL_DATABASE_UNAVAILABLE",
        ) from error
