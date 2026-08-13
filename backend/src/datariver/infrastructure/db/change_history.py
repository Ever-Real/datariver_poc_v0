from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.domain.common import ConflictError, ValidationError, utc_now, uuid7
from datariver.infrastructure.db.models.change_history import (
    ChangeHistoryCrLinkEventModel,
    ChangeHistoryLedgerEventModel,
    ChangeHistorySourceModel,
)
from datariver.infrastructure.db.rls import set_security_context

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_DOCUMENT_KEYS = frozenset(
    {"raw", "payload", "aspect", "schemaMetadata", "previousAspectValue"}
)


@dataclass(frozen=True, slots=True)
class CaptureSource:
    workspace_id: UUID
    source_identity_hash: str
    source_generation: int
    provider_name: str
    provider_version: str
    schema_contract_hash: str


@dataclass(frozen=True, slots=True)
class NormalizedLedgerEvent:
    workspace_id: UUID
    source_id: UUID
    event_identity: str
    source_event_identity: str
    normalized_change_transaction_id: str
    deterministic_ordinal: int
    source_kind: str
    topic_contract: str | None
    source_partition: int | None
    source_offset: int | None
    asset_id: UUID | None
    entity_urn: str
    entity_urn_hash: str
    entity_type: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    table_or_view_name: str | None
    field_path: str | None
    normalized_entity_key: str
    system_id: UUID | None
    category: str
    source_aspect: str
    operation: str
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    before_hash: str | None
    after_hash: str | None
    actor_ref: str | None
    source_occurred_at: datetime | None
    detected_at: datetime
    captured_at: datetime
    effective_week_start: date | None
    precision: str
    tombstone: bool
    source_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LedgerAppendResult:
    event_id: UUID
    replayed: bool


@dataclass(frozen=True, slots=True)
class CheckpointLease:
    checkpoint_id: UUID
    version: int
    fence_epoch: int
    next_offset: int


@dataclass(frozen=True, slots=True)
class CrLinkEvent:
    workspace_id: UUID
    ledger_event_id: UUID
    link_version: int
    link_kind: str
    action: str
    change_request_id: UUID
    change_request_round_id: UUID
    active_result: bool
    resulting_primary_change_request_id: UUID | None
    resulting_primary_round_id: UUID | None
    prior_link_hash: str | None
    event_hash: str
    reason: str
    policy_hash: str
    basis_hash: str
    actor_id: UUID
    created_at: datetime


def _require_sha256(value: str | None, *, field: str, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if value is None or _SHA256.fullmatch(value) is None:
        raise ValidationError(f"{field} must be a lowercase SHA-256 value.")


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(_FORBIDDEN_DOCUMENT_KEYS.intersection(value)) or any(
            _contains_forbidden_key(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def _validate_document(
    value: dict[str, Any] | None,
    *,
    field: str,
    maximum_bytes: int,
) -> None:
    if value is None:
        return
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{field} must be JSON serializable.") from error
    if len(encoded) > maximum_bytes:
        raise ValidationError(f"{field} exceeds the normalized persistence bound.")
    if _contains_forbidden_key(value):
        raise ValidationError(f"{field} contains a raw provider-document key.")


def _validate_source(source: CaptureSource) -> None:
    _require_sha256(source.source_identity_hash, field="source_identity_hash")
    _require_sha256(source.schema_contract_hash, field="schema_contract_hash")
    if source.source_generation < 1:
        raise ValidationError("source_generation must be positive.")


def _validate_event(event: NormalizedLedgerEvent) -> None:
    for field, value in (
        ("event_identity", event.event_identity),
        ("source_event_identity", event.source_event_identity),
        ("normalized_change_transaction_id", event.normalized_change_transaction_id),
        ("entity_urn_hash", event.entity_urn_hash),
    ):
        _require_sha256(value, field=field)
    _require_sha256(event.before_hash, field="before_hash", nullable=True)
    _require_sha256(event.after_hash, field="after_hash", nullable=True)
    if event.deterministic_ordinal < 0:
        raise ValidationError("deterministic_ordinal must be non-negative.")
    if not 1 <= len(event.entity_urn) <= 4096:
        raise ValidationError("entity_urn is outside the normalized persistence bound.")
    _validate_document(event.before_data, field="before_data", maximum_bytes=16_384)
    _validate_document(event.after_data, field="after_data", maximum_bytes=16_384)
    _validate_document(event.source_metadata, field="source_metadata", maximum_bytes=4_096)


def _validate_link(event: CrLinkEvent) -> None:
    for field, value in (
        ("event_hash", event.event_hash),
        ("policy_hash", event.policy_hash),
        ("basis_hash", event.basis_hash),
    ):
        _require_sha256(value, field=field)
    _require_sha256(event.prior_link_hash, field="prior_link_hash", nullable=True)
    if event.link_version < 1:
        raise ValidationError("link_version must be positive.")


class SqlChangeHistoryStore:
    """PostgreSQL persistence only; capture, decode, API and UI orchestration live elsewhere."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_source(self, source: CaptureSource) -> UUID:
        _validate_source(source)
        now = utc_now()
        source_id = uuid7()
        async with self._session_factory() as session, session.begin():
            await set_security_context(session, workspace_id=source.workspace_id, subject_id=None)
            inserted_id = await session.scalar(
                insert(ChangeHistorySourceModel)
                .values(
                    id=source_id,
                    workspace_id=source.workspace_id,
                    source_identity_hash=source.source_identity_hash,
                    source_generation=source.source_generation,
                    source_kind="DATAHUB",
                    provider_name=source.provider_name,
                    provider_version=source.provider_version,
                    schema_contract_hash=source.schema_contract_hash,
                    capture_state="DISABLED",
                    first_mcl_offsets=None,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing()
                .returning(ChangeHistorySourceModel.id)
            )
            if inserted_id is not None:
                return inserted_id
            existing = await session.scalar(
                select(ChangeHistorySourceModel).where(
                    ChangeHistorySourceModel.workspace_id == source.workspace_id,
                    ChangeHistorySourceModel.source_identity_hash == source.source_identity_hash,
                )
            )
            if existing is None:
                raise ConflictError("Capture source identity conflicts with existing evidence.")
            if (
                existing.source_generation != source.source_generation
                or existing.provider_name != source.provider_name
                or existing.provider_version != source.provider_version
                or existing.schema_contract_hash != source.schema_contract_hash
            ):
                raise ConflictError("Capture source replay does not match stored source evidence.")
            return existing.id

    async def append_ledger_event(self, event: NormalizedLedgerEvent) -> LedgerAppendResult:
        _validate_event(event)
        event_id = uuid7()
        async with self._session_factory() as session, session.begin():
            await set_security_context(session, workspace_id=event.workspace_id, subject_id=None)
            inserted_id = await session.scalar(
                insert(ChangeHistoryLedgerEventModel)
                .values(id=event_id, **asdict(event))
                .on_conflict_do_nothing()
                .returning(ChangeHistoryLedgerEventModel.id)
            )
            if inserted_id is not None:
                return LedgerAppendResult(event_id=inserted_id, replayed=False)
            existing = await session.scalar(
                select(ChangeHistoryLedgerEventModel).where(
                    ChangeHistoryLedgerEventModel.workspace_id == event.workspace_id,
                    ChangeHistoryLedgerEventModel.source_id == event.source_id,
                    ChangeHistoryLedgerEventModel.source_event_identity
                    == event.source_event_identity,
                    ChangeHistoryLedgerEventModel.deterministic_ordinal
                    == event.deterministic_ordinal,
                )
            )
            if existing is None or existing.event_identity != event.event_identity:
                raise ConflictError("Source-event replay conflicts with stored ledger identity.")
            return LedgerAppendResult(event_id=existing.id, replayed=True)

    async def acquire_checkpoint_lease(
        self,
        *,
        workspace_id: UUID,
        source_id: UUID,
        topic_contract: str,
        source_partition: int,
        initial_next_offset: int,
        owner_fingerprint: str,
        lease_token_hash: str,
        lease_duration_seconds: int,
    ) -> CheckpointLease:
        _require_sha256(owner_fingerprint, field="owner_fingerprint")
        _require_sha256(lease_token_hash, field="lease_token_hash")
        if source_partition < 0 or initial_next_offset < 0 or lease_duration_seconds <= 0:
            raise ValidationError("Checkpoint lease position or interval is invalid.")
        async with self._session_factory() as session, session.begin():
            await set_security_context(session, workspace_id=workspace_id, subject_id=None)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM change_history.claim_checkpoint_v1("
                            ":workspace_id, :source_id, :topic_contract, :source_partition, "
                            ":initial_next_offset, :owner_fingerprint, :lease_token_hash, "
                            ":lease_duration_seconds)"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "source_id": source_id,
                            "topic_contract": topic_contract,
                            "source_partition": source_partition,
                            "initial_next_offset": initial_next_offset,
                            "owner_fingerprint": owner_fingerprint,
                            "lease_token_hash": lease_token_hash,
                            "lease_duration_seconds": lease_duration_seconds,
                        },
                    )
                )
                .mappings()
                .one()
            )
            return CheckpointLease(
                checkpoint_id=row["checkpoint_id"],
                version=row["checkpoint_version"],
                fence_epoch=row["checkpoint_fence"],
                next_offset=row["checkpoint_next_offset"],
            )

    async def advance_checkpoint(
        self,
        *,
        workspace_id: UUID,
        checkpoint_id: UUID,
        expected_version: int,
        expected_fence_epoch: int,
        expected_next_offset: int,
        next_offset: int,
        owner_fingerprint: str,
        lease_token_hash: str,
        last_event_identity: str,
        source_occurred_at: datetime | None,
        captured_at: datetime,
        establish_first_exact: bool = False,
    ) -> CheckpointLease:
        _require_sha256(owner_fingerprint, field="owner_fingerprint")
        _require_sha256(lease_token_hash, field="lease_token_hash")
        _require_sha256(last_event_identity, field="last_event_identity")
        if next_offset <= expected_next_offset:
            raise ValidationError("Checkpoint advancement must increase next_offset.")
        async with self._session_factory() as session, session.begin():
            await set_security_context(session, workspace_id=workspace_id, subject_id=None)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM change_history.advance_checkpoint_v1("
                            ":workspace_id, :checkpoint_id, :expected_version, "
                            ":expected_fence_epoch, :expected_next_offset, :next_offset, "
                            ":owner_fingerprint, :lease_token_hash, :last_event_identity, "
                            ":source_occurred_at, :captured_at, :establish_first_exact)"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "checkpoint_id": checkpoint_id,
                            "expected_version": expected_version,
                            "expected_fence_epoch": expected_fence_epoch,
                            "expected_next_offset": expected_next_offset,
                            "next_offset": next_offset,
                            "owner_fingerprint": owner_fingerprint,
                            "lease_token_hash": lease_token_hash,
                            "last_event_identity": last_event_identity,
                            "source_occurred_at": source_occurred_at,
                            "captured_at": captured_at,
                            "establish_first_exact": establish_first_exact,
                        },
                    )
                )
                .mappings()
                .one()
            )
            return CheckpointLease(
                checkpoint_id=row["checkpoint_id"],
                version=row["checkpoint_version"],
                fence_epoch=row["checkpoint_fence"],
                next_offset=row["checkpoint_next_offset"],
            )

    async def append_cr_link_event(self, event: CrLinkEvent) -> LedgerAppendResult:
        _validate_link(event)
        link_event_id = uuid7()
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=event.workspace_id,
                subject_id=event.actor_id,
            )
            inserted_id = await session.scalar(
                insert(ChangeHistoryCrLinkEventModel)
                .values(id=link_event_id, **asdict(event))
                .on_conflict_do_nothing()
                .returning(ChangeHistoryCrLinkEventModel.id)
            )
            if inserted_id is not None:
                return LedgerAppendResult(event_id=inserted_id, replayed=False)
            existing = await session.scalar(
                select(ChangeHistoryCrLinkEventModel).where(
                    ChangeHistoryCrLinkEventModel.workspace_id == event.workspace_id,
                    ChangeHistoryCrLinkEventModel.ledger_event_id == event.ledger_event_id,
                    ChangeHistoryCrLinkEventModel.event_hash == event.event_hash,
                )
            )
            if existing is None or existing.link_version != event.link_version:
                raise ConflictError("CR link replay conflicts with stored link history.")
            return LedgerAppendResult(event_id=existing.id, replayed=True)
