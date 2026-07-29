from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    CatalogMetadataVocabularyListItem,
    CatalogMetadataVocabularyPage,
    CatalogVocabularySyncReservation,
    CatalogVocabularySyncResult,
    DataHubVocabularyScanPage,
)
from datariver.application.services.catalog_metadata_compiler import (
    CatalogMetadataVocabularyReference,
)
from datariver.domain.common import ConflictError, ValidationError, utc_now, uuid7
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import (
    CatalogVocabularyEntryModel,
    CatalogVocabularySyncRunModel,
)
from datariver.infrastructure.db.models.platform import WorkspaceModel

_KINDS = frozenset({"DOMAIN", "TAG", "TERM"})
_CURSOR_KEYS = frozenset({"v", "scope", "workspace_id", "kind", "query", "name", "id"})


def _encode_vocabulary_cursor(
    *,
    workspace_id: UUID,
    kind: str,
    query: str | None,
    sort_name: str,
    vocabulary_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "scope": "catalog-metadata-vocabulary",
            "workspace_id": str(workspace_id),
            "kind": kind,
            "query": query,
            "name": sort_name,
            "id": str(vocabulary_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_vocabulary_cursor(
    cursor: str,
    *,
    workspace_id: UUID,
    kind: str,
    query: str | None,
) -> tuple[str, UUID]:
    try:
        if not cursor or len(cursor) > 2_000:
            raise ValueError
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(raw)
        if (
            not isinstance(document, dict)
            or frozenset(document) != _CURSOR_KEYS
            or document.get("v") != 1
            or document.get("scope") != "catalog-metadata-vocabulary"
            or document.get("workspace_id") != str(workspace_id)
            or document.get("kind") != kind
            or document.get("query") != query
            or not isinstance(document.get("name"), str)
        ):
            raise ValueError
        display_name = str(document["name"])
        vocabulary_id = UUID(str(document["id"]))
        if cursor != _encode_vocabulary_cursor(
            workspace_id=workspace_id,
            kind=kind,
            query=query,
            sort_name=display_name,
            vocabulary_id=vocabulary_id,
        ):
            raise ValueError
        return display_name, vocabulary_id
    except (
        UnicodeDecodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        raise ValidationError("The catalog vocabulary cursor is invalid.") from error


def _validate_snapshot(page: DataHubVocabularyScanPage) -> None:
    if page.snapshot_consistent:
        if (
            page.snapshot_evidence_reference is None
            or not 1 <= len(page.snapshot_evidence_reference) <= 500
            or page.snapshot_contract_hash is None
            or re.fullmatch(r"[0-9a-f]{64}", page.snapshot_contract_hash) is None
            or page.snapshot_provider_version is None
            or not 1 <= len(page.snapshot_provider_version) <= 128
        ):
            raise ValidationError(
                "A verified vocabulary snapshot requires bounded immutable evidence."
            )
    elif any(
        value is not None
        for value in (
            page.snapshot_evidence_reference,
            page.snapshot_contract_hash,
            page.snapshot_provider_version,
        )
    ):
        raise ValidationError(
            "An unverified vocabulary snapshot cannot persist verification evidence."
        )


class SqlCatalogMetadataVocabularyResolver:
    """Resolve local typed IDs under the caller's already-installed workspace RLS context."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        vocabulary_ids: tuple[UUID, ...],
        expected_kind: str,
    ) -> Mapping[UUID, CatalogMetadataVocabularyReference]:
        if expected_kind not in {"DOMAIN", "TAG", "TERM"}:
            raise ValueError("The catalog vocabulary kind is invalid.")
        unique_ids = tuple(dict.fromkeys(vocabulary_ids))
        if len(unique_ids) != len(vocabulary_ids) or len(unique_ids) > 100:
            raise ConflictError(
                "The controlled vocabulary candidate is invalid.",
                details={"code": "CATALOG_VOCABULARY_DRIFT"},
            )
        if not unique_ids:
            return {}
        models = tuple(
            (
                await self._session.scalars(
                    select(CatalogVocabularyEntryModel).where(
                        CatalogVocabularyEntryModel.workspace_id == workspace_id,
                        CatalogVocabularyEntryModel.id.in_(unique_ids),
                        CatalogVocabularyEntryModel.kind == expected_kind,
                        CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
                    )
                )
            ).all()
        )
        if len(models) != len(unique_ids):
            raise ConflictError(
                "The controlled vocabulary evidence is unavailable.",
                details={"code": "CATALOG_VOCABULARY_DRIFT"},
            )
        values = {
            model.id: CatalogMetadataVocabularyReference(
                vocabulary_id=model.id,
                kind=model.kind,
                provider_ref=model.provider_ref,
                source_version=model.source_version,
            )
            for model in models
        }
        if set(values) != set(unique_ids):
            raise ConflictError(
                "The controlled vocabulary evidence is ambiguous.",
                details={"code": "CATALOG_VOCABULARY_DRIFT"},
            )
        return values


class SqlCatalogMetadataVocabularyProjection:
    """Workspace-isolated durable vocabulary reconciliation and safe local-ID listing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock_kind(self, *, workspace_id: UUID, kind: str) -> None:
        digest = hashlib.sha256(f"{workspace_id}:{kind}".encode()).digest()[:8]
        lock_key = int.from_bytes(digest, byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def _replay(
        self,
        *,
        workspace_id: UUID,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogVocabularySyncResult | None:
        existing = await SqlIdempotencyStore(self._session).get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ConflictError("The idempotency key was used with a different request.")
        try:
            result = existing.result
            status = str(result["inactivation_status"])
            if status not in {
                "NOT_FINAL",
                "APPLIED",
                "SUPPRESSED_UNVERIFIED_SNAPSHOT",
            }:
                raise ValueError
            next_offset_raw = result["next_offset"]
            return CatalogVocabularySyncResult(
                upserted=int(result["upserted"]),
                inactivated=int(result["inactivated"]),
                next_offset=(int(next_offset_raw) if next_offset_raw is not None else None),
                total=int(result["total"]),
                observed_at=datetime.fromisoformat(str(result["observed_at"])),
                inactivation_status=status,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ConflictError(
                "The stored vocabulary synchronization replay is invalid."
            ) from error

    async def reserve_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        kind: str,
        offset: int,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogVocabularySyncReservation:
        if kind not in _KINDS or offset < 0:
            raise ValueError("The catalog vocabulary reservation is invalid.")
        await self._lock_kind(workspace_id=workspace_id, kind=kind)
        replayed = await self._replay(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation,
        )
        if replayed is not None:
            await self._session.rollback()
            return CatalogVocabularySyncReservation(cursor=None, replayed=replayed)
        workspace = await self._session.scalar(
            select(WorkspaceModel.id).where(WorkspaceModel.id == workspace_id)
        )
        if workspace is None:
            await self._session.rollback()
            raise ValidationError("The vocabulary workspace does not exist.")
        now = utc_now()
        active = await self._session.scalar(
            select(CatalogVocabularySyncRunModel)
            .where(
                CatalogVocabularySyncRunModel.workspace_id == workspace_id,
                CatalogVocabularySyncRunModel.kind == kind,
                CatalogVocabularySyncRunModel.state == "ACTIVE",
            )
            .with_for_update()
        )
        if active is not None and active.sync_id != sync_id:
            if active.heartbeat_at >= now - timedelta(hours=1):
                await self._session.rollback()
                raise ConflictError("Another vocabulary reconciliation is active for this kind.")
            active.state = "ABANDONED"
            active.completed_at = now
            active.heartbeat_at = now
            active = None
        if active is None:
            if offset != 0:
                await self._session.rollback()
                raise ConflictError("A vocabulary reconciliation must begin at page zero.")
            active = CatalogVocabularySyncRunModel(
                workspace_id=workspace_id,
                sync_id=sync_id,
                kind=kind,
                state="ACTIVE",
                next_offset=0,
                next_cursor=None,
                expected_total=None,
                seen_count=0,
                snapshot_consistent=False,
                snapshot_evidence_reference=None,
                snapshot_contract_hash=None,
                snapshot_provider_version=None,
                started_at=now,
                heartbeat_at=now,
                completed_at=None,
            )
            self._session.add(active)
            await self._session.flush()
        elif active.next_offset != offset:
            await self._session.rollback()
            raise ConflictError("The vocabulary reconciliation page is out of sequence.")
        return CatalogVocabularySyncReservation(cursor=active.next_cursor)

    async def release_scan(self) -> None:
        await self._session.rollback()

    async def abandon_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        kind: str,
    ) -> None:
        if kind not in _KINDS:
            raise ValueError("The catalog vocabulary kind is invalid.")
        now = utc_now()
        await self._session.execute(
            update(CatalogVocabularySyncRunModel)
            .where(
                CatalogVocabularySyncRunModel.workspace_id == workspace_id,
                CatalogVocabularySyncRunModel.sync_id == sync_id,
                CatalogVocabularySyncRunModel.kind == kind,
                CatalogVocabularySyncRunModel.state == "ACTIVE",
            )
            .values(state="ABANDONED", completed_at=now, heartbeat_at=now)
        )
        await self._session.commit()

    async def upsert_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        kind: str,
        offset: int,
        cursor: str | None,
        next_offset: int | None,
        page: DataHubVocabularyScanPage,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogVocabularySyncResult:
        if (
            kind not in _KINDS
            or offset < 0
            or any(
                value is not None and not 1 <= len(value) <= 4_096
                for value in (cursor, page.next_cursor)
            )
        ):
            raise ValueError("The catalog vocabulary page is invalid.")
        _validate_snapshot(page)
        await self._lock_kind(workspace_id=workspace_id, kind=kind)
        replayed = await self._replay(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation,
        )
        if replayed is not None:
            await self._session.rollback()
            return replayed
        active = await self._session.scalar(
            select(CatalogVocabularySyncRunModel)
            .where(
                CatalogVocabularySyncRunModel.workspace_id == workspace_id,
                CatalogVocabularySyncRunModel.sync_id == sync_id,
                CatalogVocabularySyncRunModel.kind == kind,
                CatalogVocabularySyncRunModel.state == "ACTIVE",
            )
            .with_for_update()
        )
        if active is None:
            raise ConflictError("The vocabulary reconciliation reservation is unavailable.")
        if active.next_offset != offset or active.next_cursor != cursor:
            raise ConflictError("The vocabulary reconciliation page is out of sequence.")
        if page.observed_at < active.started_at:
            raise ConflictError("The vocabulary observation predates its reconciliation.")
        if active.expected_total is None:
            if offset != 0 or cursor is not None or active.seen_count != 0:
                raise ConflictError("The vocabulary reconciliation reservation is invalid.")
            active.expected_total = page.total
            active.snapshot_consistent = page.snapshot_consistent
            active.snapshot_evidence_reference = page.snapshot_evidence_reference
            active.snapshot_contract_hash = page.snapshot_contract_hash
            active.snapshot_provider_version = page.snapshot_provider_version
        elif (
            active.expected_total != page.total
            or active.snapshot_consistent != page.snapshot_consistent
            or active.snapshot_evidence_reference != page.snapshot_evidence_reference
            or active.snapshot_contract_hash != page.snapshot_contract_hash
            or active.snapshot_provider_version != page.snapshot_provider_version
        ):
            raise ConflictError("The vocabulary reconciliation snapshot changed between pages.")
        if page.next_cursor is not None and page.next_cursor == cursor:
            raise ConflictError("The vocabulary reconciliation cursor did not advance.")
        refs: list[str] = []
        for item in page.items:
            expected_prefix = {
                "DOMAIN": "urn:li:domain:",
                "TAG": "urn:li:tag:",
                "TERM": "urn:li:glossaryTerm:",
            }[kind]
            if (
                item.kind != kind
                or not item.provider_ref.startswith(expected_prefix)
                or not 1 <= len(item.provider_ref) <= 1_000
                or not item.display_name
                or item.display_name != item.display_name.strip()
                or len(item.display_name) > 500
                or re.fullmatch(r"[0-9a-f]{64}", item.source_version) is None
            ):
                raise ValidationError("The vocabulary entry is invalid.")
            refs.append(item.provider_ref)
        if len(set(refs)) != len(refs):
            raise ConflictError("The vocabulary page contains duplicate provider identities.")
        if refs:
            repeated = await self._session.scalar(
                select(CatalogVocabularyEntryModel.id)
                .where(
                    CatalogVocabularyEntryModel.workspace_id == workspace_id,
                    CatalogVocabularyEntryModel.kind == kind,
                    CatalogVocabularyEntryModel.last_seen_sync_id == sync_id,
                    CatalogVocabularyEntryModel.provider_ref.in_(refs),
                )
                .limit(1)
            )
            if repeated is not None:
                raise ConflictError(
                    "The vocabulary reconciliation repeated an earlier provider identity."
                )
        for item in page.items:
            statement = insert(CatalogVocabularyEntryModel).values(
                id=uuid7(),
                workspace_id=workspace_id,
                kind=kind,
                provider_ref=item.provider_ref,
                display_name=item.display_name,
                lifecycle="ACTIVE",
                source_version=item.source_version,
                observed_at=page.observed_at,
                last_seen_sync_id=sync_id,
                updated_at=page.observed_at,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    CatalogVocabularyEntryModel.workspace_id,
                    CatalogVocabularyEntryModel.kind,
                    CatalogVocabularyEntryModel.provider_ref,
                ],
                set_={
                    "display_name": item.display_name,
                    "lifecycle": "ACTIVE",
                    "source_version": item.source_version,
                    "observed_at": page.observed_at,
                    "last_seen_sync_id": sync_id,
                    "updated_at": page.observed_at,
                },
            )
            await self._session.execute(statement)
        seen_count = active.seen_count + len(page.items)
        expected_total = active.expected_total
        if expected_total is None or seen_count > expected_total:
            raise ConflictError(
                "The vocabulary reconciliation exceeded its declared snapshot total."
            )
        inactivated = 0
        if page.next_cursor is None:
            if next_offset is not None or seen_count != expected_total:
                raise ConflictError("The vocabulary reconciliation snapshot is incomplete.")
            if active.snapshot_consistent:
                inactivated_ids = (
                    await self._session.scalars(
                        update(CatalogVocabularyEntryModel)
                        .where(
                            CatalogVocabularyEntryModel.workspace_id == workspace_id,
                            CatalogVocabularyEntryModel.kind == kind,
                            CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
                            CatalogVocabularyEntryModel.last_seen_sync_id.is_distinct_from(sync_id),
                            ~CatalogVocabularyEntryModel.provider_ref.startswith(
                                "urn:li:domain:datariver-"
                            ),
                        )
                        .values(
                            lifecycle="INACTIVE",
                            updated_at=page.observed_at,
                        )
                        .returning(CatalogVocabularyEntryModel.id)
                    )
                ).all()
                inactivated = len(inactivated_ids)
            active.state = "COMPLETED"
            active.completed_at = utc_now()
        else:
            if next_offset != offset + 1:
                raise ConflictError("The vocabulary reconciliation page number did not advance.")
            active.next_offset = next_offset
            active.next_cursor = page.next_cursor
        active.seen_count = seen_count
        active.heartbeat_at = utc_now()
        status = (
            "NOT_FINAL"
            if page.next_cursor is not None
            else "APPLIED"
            if active.snapshot_consistent
            else "SUPPRESSED_UNVERIFIED_SNAPSHOT"
        )
        result = CatalogVocabularySyncResult(
            upserted=len(page.items),
            inactivated=inactivated,
            next_offset=next_offset,
            total=page.total,
            observed_at=page.observed_at,
            inactivation_status=status,
        )
        await SqlIdempotencyStore(self._session).save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={
                "upserted": result.upserted,
                "inactivated": result.inactivated,
                "next_offset": result.next_offset,
                "total": result.total,
                "observed_at": result.observed_at.isoformat(),
                "inactivation_status": result.inactivation_status,
            },
        )
        await self._session.commit()
        return result

    async def list_active(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        query: str | None,
        cursor: str | None,
        limit: int,
    ) -> CatalogMetadataVocabularyPage:
        if kind not in _KINDS or not 1 <= limit <= 50:
            raise ValueError("The catalog vocabulary query is invalid.")
        normalized_query = query.strip() if query is not None else None
        if normalized_query is not None and not 1 <= len(normalized_query) <= 200:
            raise ValueError("The catalog vocabulary query is invalid.")
        boundary = (
            _decode_vocabulary_cursor(
                cursor,
                workspace_id=workspace_id,
                kind=kind,
                query=normalized_query,
            )
            if cursor is not None
            else None
        )
        sort_name = func.lower(CatalogVocabularyEntryModel.display_name)
        statement = (
            select(CatalogVocabularyEntryModel, sort_name.label("sort_name"))
            .where(
                CatalogVocabularyEntryModel.workspace_id == workspace_id,
                CatalogVocabularyEntryModel.kind == kind,
                CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
            )
            .order_by(sort_name, CatalogVocabularyEntryModel.id)
            .limit(limit + 1)
        )
        if normalized_query is not None:
            escaped_query = (
                normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            statement = statement.where(
                CatalogVocabularyEntryModel.display_name.ilike(
                    f"%{escaped_query}%",
                    escape="\\",
                )
            )
        if boundary is not None:
            statement = statement.where(
                tuple_(sort_name, CatalogVocabularyEntryModel.id) > boundary
            )
        rows = tuple((await self._session.execute(statement)).all())
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            last_model, last_sort_name = visible[-1]
            next_cursor = _encode_vocabulary_cursor(
                workspace_id=workspace_id,
                kind=kind,
                query=normalized_query,
                sort_name=str(last_sort_name),
                vocabulary_id=last_model.id,
            )
        return CatalogMetadataVocabularyPage(
            items=tuple(
                CatalogMetadataVocabularyListItem(
                    vocabulary_id=model.id,
                    kind=model.kind,
                    display_name=model.display_name,
                    source_version=model.source_version,
                )
                for model, _ in visible
            ),
            next_cursor=next_cursor,
        )
