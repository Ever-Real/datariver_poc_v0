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
from datariver.application.knowledge_studio_ingestion_ports import (
    KnowledgeStudioIngestionWorkerStore,
)
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio_ingestion import (
    StudioIngestionBindingClaim,
    StudioIngestionClaim,
    StudioIngestionMaterialization,
    StudioIngestionRule,
    StudioSourceProfilePin,
    StudioVectorReceipt,
)
from datariver.infrastructure.db.rls import set_security_context

_REQUEST = text(
    """
    SELECT knowledge.request_studio_ingestion_v1(
        :workspace_id, :draft_id, :expected_version, :request_hash,
        :manifest_id, :manifest_version, :manifest_hash,
        :source_profile_pins, :embedding_binding, :maximum_attempts
    )
    """
).bindparams(
    bindparam("source_profile_pins", type_=JSONB),
    bindparam("embedding_binding", type_=JSONB),
)
_CANCEL = text(
    """
    SELECT knowledge.cancel_studio_ingestion_v1(
        :workspace_id, :job_id, :expected_version, :reason
    )
    """
)
_RETRY = text(
    """
    SELECT knowledge.retry_studio_ingestion_v1(
        :workspace_id, :job_id, :expected_version
    )
    """
)
_CLAIM = text(
    """
    SELECT knowledge.claim_studio_ingestion_v1(
        :workspace_id, :worker_fingerprint, :lease_token, :lease_seconds
    )
    """
)
_FREEZE = text(
    """
    SELECT knowledge.freeze_studio_ingestion_source_access_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint,
        :hard_timeout_seconds, :completion_margin_seconds
    )
    """
)
_FENCE = text(
    """
    SELECT knowledge.assert_studio_ingestion_source_statement_fence_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint
    )
    """
)
_RENEW = text(
    """
    SELECT knowledge.renew_studio_ingestion_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :lease_seconds, :stage, :progress_percent
    )
    """
)
_ENSURE_CURRENT = text(
    """
    SELECT knowledge.ensure_studio_ingestion_current_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :manifest_id, :manifest_version, :manifest_hash,
        :embedding_binding
    )
    """
).bindparams(bindparam("embedding_binding", type_=JSONB))
_BEGIN_COMPLETION = text(
    """
    SELECT knowledge.begin_studio_ingestion_completion_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint
    )
    """
)
_APPEND_COMPLETION = text(
    """
    SELECT knowledge.append_studio_ingestion_result_batch_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :changeset_id, :operations, :vectors
    )
    """
).bindparams(
    bindparam("operations", type_=JSONB),
    bindparam("vectors", type_=JSONB),
)
_COMPLETE = text(
    """
    SELECT knowledge.complete_studio_ingestion_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :changeset_id, :source_read_receipt_hash, :result_hash,
        :operation_count, :vector_receipt_count, :call_id
    )
    """
)
_FAIL = text(
    """
    SELECT knowledge.fail_studio_ingestion_v1(
        :workspace_id, :job_id, :attempt_id, :lease_epoch, :lease_token,
        :worker_fingerprint, :call_id, :failure_code, :retryable, :stale
    )
    """
)


class SqlKnowledgeStudioIngestionCommandStore:
    """Human command wrapper; PostgreSQL owns release pinning and the queue transition."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        expected_version: int,
        request_hash: str,
        manifest_id: str,
        manifest_version: int,
        manifest_hash: str,
        source_profile_pins: tuple[StudioSourceProfilePin, ...],
        embedding_binding: dict[str, object] | None,
        maximum_attempts: int,
    ) -> UUID:
        for pin in source_profile_pins:
            pin.validate()
        try:
            document = await self._session.scalar(
                _REQUEST,
                {
                    "workspace_id": workspace_id,
                    "draft_id": draft_id,
                    "expected_version": expected_version,
                    "request_hash": request_hash,
                    "manifest_id": manifest_id,
                    "manifest_version": manifest_version,
                    "manifest_hash": manifest_hash,
                    "source_profile_pins": [
                        {
                            "asset_id": str(pin.asset_id),
                            "source_version": pin.source_version,
                            "projection_source_version": pin.projection_source_version,
                            "connection_profile_id": pin.connection_profile_id,
                            "connection_profile_version": pin.connection_profile_version,
                            "connection_profile_hash": pin.connection_profile_hash,
                        }
                        for pin in source_profile_pins
                    ],
                    "embedding_binding": embedding_binding,
                    "maximum_attempts": maximum_attempts,
                },
            )
        except DBAPIError as error:
            _raise_database_contract(error, operation="request")
            raise
        value = _mapping(document, "Studio ingestion request")
        _exact_keys(value, {"job_id"}, "Studio ingestion request")
        return _uuid(value["job_id"], "Studio ingestion job")

    async def cancel(
        self,
        *,
        workspace_id: UUID,
        job_id: UUID,
        expected_version: int,
        reason: str,
    ) -> None:
        await self._transition(
            statement=_CANCEL,
            parameters={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "expected_version": expected_version,
                "reason": reason,
            },
            operation="cancel",
        )

    async def retry(
        self,
        *,
        workspace_id: UUID,
        job_id: UUID,
        expected_version: int,
    ) -> None:
        await self._transition(
            statement=_RETRY,
            parameters={
                "workspace_id": workspace_id,
                "job_id": job_id,
                "expected_version": expected_version,
            },
            operation="retry",
        )

    async def _transition(
        self,
        *,
        statement: TextClause,
        parameters: Mapping[str, object],
        operation: str,
    ) -> None:
        try:
            document = await self._session.scalar(statement, parameters)
        except DBAPIError as error:
            _raise_database_contract(error, operation=operation)
            raise
        value = _mapping(document, f"Studio ingestion {operation}")
        _exact_keys(
            value,
            {"job_id", "state", "version"},
            f"Studio ingestion {operation}",
        )
        _uuid(value["job_id"], "Studio ingestion job")
        _text(value["state"], "Studio ingestion state", 24)
        _integer(value["version"], "Studio ingestion version", 1, 2**31 - 1)


class SqlKnowledgeStudioIngestionWorkerStore(KnowledgeStudioIngestionWorkerStore):
    """Function-only worker store for the dedicated NOBYPASSRLS DB principal."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> StudioIngestionClaim | None:
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
            _mapping(document, "Studio ingestion claim"),
            lease_token=lease_token,
        )

    async def freeze_source_access(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        hard_timeout_seconds: int,
        completion_margin_seconds: int,
    ) -> datetime:
        value = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_FREEZE,
            extra={
                "hard_timeout_seconds": hard_timeout_seconds,
                "completion_margin_seconds": completion_margin_seconds,
            },
        )
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ConflictError("The database returned an invalid source-access deadline.")
        return value

    async def assert_source_statement_fence(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
    ) -> None:
        value = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_FENCE,
        )
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ConflictError("The Studio source-access fence is no longer valid.")

    async def renew(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        lease_seconds: int,
        stage: str,
        progress_percent: int,
    ) -> None:
        await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_RENEW,
            extra={
                "lease_seconds": lease_seconds,
                "stage": stage,
                "progress_percent": progress_percent,
            },
        )

    async def ensure_current(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        manifest_id: str,
        manifest_version: int,
        manifest_hash: str,
        current_embedding_binding: ModelBinding | None,
    ) -> str | None:
        value = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_ENSURE_CURRENT,
            extra={
                "manifest_id": manifest_id,
                "manifest_version": manifest_version,
                "manifest_hash": manifest_hash,
                "embedding_binding": (
                    current_embedding_binding.to_document()
                    if current_embedding_binding is not None
                    else None
                ),
            },
        )
        if value is None:
            return None
        if not isinstance(value, str) or not 1 <= len(value) <= 100:
            raise ConflictError("The database returned an invalid Studio drift result.")
        return value

    async def complete(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        call_id: str,
        materialization: StudioIngestionMaterialization,
        vector_receipts: tuple[StudioVectorReceipt, ...],
        result_hash: str,
    ) -> UUID:
        materialization.validate()
        for receipt in vector_receipts:
            receipt.validate()
        try:
            async with self._session_factory() as session, session.begin():
                await set_security_context(
                    session,
                    workspace_id=claim.workspace_id,
                    subject_id=worker_subject_id,
                )
                parameters = _claim_parameters(claim)
                raw_changeset_id = await session.scalar(_BEGIN_COMPLETION, parameters)
                changeset_id = _uuid(raw_changeset_id, "Studio ingestion Changeset")
                operations = [_operation_document(item) for item in materialization.operations]
                vectors = [_vector_document(item) for item in vector_receipts]
                maximum_batches = max(
                    (len(operations) + 499) // 500,
                    (len(vectors) + 499) // 500,
                )
                for batch_index in range(maximum_batches):
                    start = batch_index * 500
                    await session.scalar(
                        _APPEND_COMPLETION,
                        {
                            **parameters,
                            "changeset_id": changeset_id,
                            "operations": operations[start : start + 500],
                            "vectors": vectors[start : start + 500],
                        },
                    )
                await session.scalar(
                    _COMPLETE,
                    {
                        **parameters,
                        "changeset_id": changeset_id,
                        "source_read_receipt_hash": (materialization.source_read_receipt_hash),
                        "result_hash": result_hash,
                        "operation_count": len(operations),
                        "vector_receipt_count": len(vectors),
                        "call_id": call_id,
                    },
                )
        except DBAPIError as error:
            _raise_database_contract(error, operation="complete")
            raise
        return changeset_id

    async def fail(
        self,
        *,
        claim: StudioIngestionClaim,
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
        claim: StudioIngestionClaim,
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
                    workspace_id=claim.workspace_id,
                    subject_id=worker_subject_id,
                )
                return await session.scalar(statement, parameters)
        except DBAPIError as error:
            _raise_database_contract(error, operation="worker transition")
            raise


def _claim_parameters(claim: StudioIngestionClaim) -> dict[str, object]:
    return {
        "workspace_id": claim.workspace_id,
        "job_id": claim.job_id,
        "attempt_id": claim.attempt_id,
        "lease_epoch": claim.lease_epoch,
        "lease_token": claim.lease_token,
        "worker_fingerprint": claim.worker_fingerprint,
    }


def _claim_from_document(
    document: Mapping[str, object],
    *,
    lease_token: str,
) -> StudioIngestionClaim:
    _exact_keys(
        document,
        {
            "workspace_id",
            "job_id",
            "graph_id",
            "draft_id",
            "studio_release_id",
            "ontology_version_id",
            "requested_by",
            "graph_classification",
            "manifest_id",
            "manifest_version",
            "manifest_hash",
            "pin_hash",
            "embedding_binding",
            "bindings",
            "attempt_id",
            "attempt_no",
            "lease_epoch",
            "worker_fingerprint",
        },
        "Studio ingestion claim",
    )
    raw_bindings = document["bindings"]
    if not isinstance(raw_bindings, list) or not 1 <= len(raw_bindings) <= 500:
        raise ValidationError("The Studio ingestion claim has an invalid Binding set.")
    raw_embedding = document["embedding_binding"]
    claim = StudioIngestionClaim(
        workspace_id=_uuid(document["workspace_id"], "workspace"),
        job_id=_uuid(document["job_id"], "job"),
        graph_id=_uuid(document["graph_id"], "graph"),
        draft_id=_uuid(document["draft_id"], "draft"),
        studio_release_id=_uuid(document["studio_release_id"], "Studio Release"),
        ontology_version_id=_uuid(document["ontology_version_id"], "ontology version"),
        requested_by=_uuid(document["requested_by"], "requester"),
        graph_classification=_integer(document["graph_classification"], "classification", 0, 3),
        manifest_id=_text(document["manifest_id"], "manifest ID", 255),
        manifest_version=_integer(document["manifest_version"], "manifest version", 1, 2**31 - 1),
        manifest_hash=_sha256(document["manifest_hash"], "manifest hash"),
        pin_hash=_sha256(document["pin_hash"], "pin hash"),
        embedding_binding=(
            _model_binding(_mapping(raw_embedding, "embedding binding"))
            if raw_embedding is not None
            else None
        ),
        bindings=tuple(
            _binding_claim(_mapping(value, "Studio ingestion Binding")) for value in raw_bindings
        ),
        attempt_id=_uuid(document["attempt_id"], "attempt"),
        attempt_no=_integer(document["attempt_no"], "attempt number", 1, 20),
        lease_epoch=_integer(document["lease_epoch"], "lease epoch", 1, 2**63 - 1),
        worker_fingerprint=_text(
            document["worker_fingerprint"],
            "worker fingerprint",
            255,
        ),
        lease_token=lease_token,
    )
    claim.validate()
    return claim


def _binding_claim(document: Mapping[str, object]) -> StudioIngestionBindingClaim:
    _exact_keys(
        document,
        {
            "pin_id",
            "binding_version_id",
            "source_reference_id",
            "source_asset_id",
            "source_version",
            "projection_source_version",
            "source_classification",
            "target_class_stable_id",
            "target_class_canonical_name",
            "mapping_hash",
            "connection_profile_id",
            "connection_profile_version",
            "connection_profile_hash",
            "rules",
        },
        "Studio ingestion Binding",
    )
    raw_rules = document["rules"]
    if not isinstance(raw_rules, list) or not 1 <= len(raw_rules) <= 1_000:
        raise ValidationError("The Studio ingestion Mapping rule set is invalid.")
    result = StudioIngestionBindingClaim(
        pin_id=_uuid(document["pin_id"], "Binding pin"),
        binding_version_id=_uuid(document["binding_version_id"], "Binding version"),
        source_reference_id=_uuid(document["source_reference_id"], "source reference"),
        source_asset_id=_uuid(document["source_asset_id"], "source asset"),
        source_version=_text(document["source_version"], "source version", 255),
        projection_source_version=_text(
            document["projection_source_version"],
            "projection source version",
            255,
        ),
        source_classification=_integer(
            document["source_classification"],
            "source classification",
            0,
            3,
        ),
        target_class_stable_id=_text(
            document["target_class_stable_id"],
            "target Class stable ID",
            128,
        ),
        target_class_canonical_name=_text(
            document["target_class_canonical_name"],
            "target Class canonical name",
            255,
        ),
        mapping_hash=_sha256(document["mapping_hash"], "Mapping hash"),
        connection_profile_id=_text(
            document["connection_profile_id"],
            "connection profile ID",
            255,
        ),
        connection_profile_version=_integer(
            document["connection_profile_version"],
            "connection profile version",
            1,
            2**31 - 1,
        ),
        connection_profile_hash=_sha256(
            document["connection_profile_hash"],
            "connection profile hash",
        ),
        rules=tuple(_rule(_mapping(value, "Studio ingestion Mapping rule")) for value in raw_rules),
    )
    result.validate()
    return result


def _rule(document: Mapping[str, object]) -> StudioIngestionRule:
    _exact_keys(
        document,
        {
            "method",
            "source_field_path",
            "target_stable_element_id",
            "target_canonical_name",
            "target_data_type",
            "target_nullable",
            "vector_index_enabled",
            "transform_id",
            "transform_version",
        },
        "Studio ingestion Mapping rule",
    )
    raw_data_type = document["target_data_type"]
    raw_nullable = document["target_nullable"]
    raw_vector = document["vector_index_enabled"]
    if raw_data_type is not None and not isinstance(raw_data_type, str):
        raise ValidationError("The Studio Mapping target data type is invalid.")
    if raw_nullable is not None and not isinstance(raw_nullable, bool):
        raise ValidationError("The Studio Mapping target nullable value is invalid.")
    if not isinstance(raw_vector, bool):
        raise ValidationError("The Studio Mapping Vector Index value is invalid.")
    result = StudioIngestionRule(
        method=_text(document["method"], "Mapping method", 32),
        source_field_path=_text(document["source_field_path"], "source field path", 2_000),
        target_stable_element_id=_text(
            document["target_stable_element_id"],
            "target stable element ID",
            128,
        ),
        target_canonical_name=_text(
            document["target_canonical_name"],
            "target canonical name",
            255,
        ),
        target_data_type=raw_data_type,
        target_nullable=raw_nullable,
        vector_index_enabled=raw_vector,
        transform_id=_text(document["transform_id"], "transform ID", 64),
        transform_version=_text(document["transform_version"], "transform version", 32),
    )
    result.validate()
    return result


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
        "embedding binding",
    )
    configuration_source = _optional_text(document["configuration_source"], 64)
    configuration_version = document["configuration_version"]
    if configuration_version is not None:
        configuration_version = _integer(
            configuration_version,
            "embedding configuration version",
            1,
            2**31 - 1,
        )
    configuration_hash = _optional_sha256(
        document["configuration_hash"],
        "embedding configuration hash",
    )
    result = ModelBinding(
        provider=_text(document["provider"], "embedding provider", 200),
        model=_text(document["model"], "embedding model", 200),
        prompt_version=_text(document["prompt_version"], "embedding prompt version", 200),
        tool_schema_version=_text(
            document["tool_schema_version"],
            "embedding schema version",
            200,
        ),
        configuration_source=configuration_source,
        configuration_version=configuration_version,
        configuration_hash=configuration_hash,
    )
    result.validate()
    return result


def _operation_document(operation: object) -> dict[str, object]:
    from datariver.domain.knowledge import GraphChangeOperation

    if not isinstance(operation, GraphChangeOperation):
        raise ValidationError("The Studio ingestion operation is invalid.")
    return {
        "sequence": operation.sequence,
        "operation": operation.operation.value,
        "entity_kind": operation.entity_kind.value,
        "stable_entity_id": str(operation.stable_entity_id),
        "document": operation.document,
        "provenance": [item.to_document() for item in operation.provenance],
        "confidence": operation.confidence,
    }


def _vector_document(receipt: StudioVectorReceipt) -> dict[str, object]:
    return {
        "entity_id": str(receipt.entity_id),
        "property_stable_id": receipt.property_stable_id,
        "content_hash": receipt.content_hash,
        "dimension": receipt.dimension,
        "vector": list(receipt.vector),
        "vector_hash": receipt.vector_hash,
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValidationError(f"The {label} is invalid.")
    return cast(Mapping[str, object], value)


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


def _raise_database_contract(error: DBAPIError, *, operation: str) -> None:
    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate == "42501":
        raise ForbiddenError(f"The Studio ingestion {operation} is not permitted.") from error
    if sqlstate in {"23503", "23505", "40001", "55000"}:
        raise ConflictError(f"The Studio ingestion {operation} changed concurrently.") from error
    if sqlstate in {"57014", "57P01", "08000", "08003", "08006"}:
        raise ExternalDependencyError(
            f"The Studio ingestion {operation} dependency is unavailable.",
            dependency="postgresql",
            retryable=True,
            provider_code="STUDIO_INGESTION_DATABASE_UNAVAILABLE",
        ) from error
