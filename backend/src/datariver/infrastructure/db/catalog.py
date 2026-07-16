from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogPage,
    DataHubScanAsset,
)
from datariver.application.ports import CatalogIndexReader, CatalogProjectionWriter
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.classification_policy import unconfigured_search_ceiling
from datariver.domain.common import ConflictError, ValidationError, utc_now, uuid7
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogProjectionWatermarkModel,
    CatalogSyncRunModel,
)
from datariver.infrastructure.db.models.platform import WorkspaceModel


def _encode_cursor(name: str, asset_id: UUID) -> str:
    payload = json.dumps([name, str(asset_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, UUID]:
    try:
        payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        name, asset_id = json.loads(payload)
        return str(name), UUID(str(asset_id))
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValidationError("The catalog cursor is invalid.") from error


def _to_index(model: AssetProjectionModel) -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=model.id,
        workspace_id=model.workspace_id,
        external_urn=model.external_urn,
        asset_type=model.asset_type,
        name=model.name,
        description=model.description,
        platform=model.platform,
        domain_id=model.domain_id,
        system_id=model.system_id,
        owner_department_id=model.owner_department_id,
        classification=Classification(model.classification),
        lifecycle=model.lifecycle,
        source_version=model.source_version,
        observed_at=model.observed_at,
    )


def _literal_contains_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SqlCatalogIndexReader(CatalogIndexReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _scope_conditions(self, subject: SubjectAttributes) -> list[Any]:
        conditions: list[Any] = [
            AssetProjectionModel.workspace_id == subject.workspace_id,
            AssetProjectionModel.deleted_at.is_(None),
            AssetProjectionModel.lifecycle == "ACTIVE",
            AssetProjectionModel.classification
            <= int(unconfigured_search_ceiling(subject.clearance)),
        ]
        conditions.append(
            or_(
                AssetProjectionModel.classification == int(Classification.PUBLIC),
                and_(
                    AssetProjectionModel.system_id.is_not(None),
                    AssetProjectionModel.system_id.in_(subject.allowed_system_ids),
                ),
            )
        )
        conditions.append(
            or_(
                AssetProjectionModel.classification == int(Classification.PUBLIC),
                and_(
                    AssetProjectionModel.domain_id.is_not(None),
                    AssetProjectionModel.domain_id.in_(subject.allowed_domain_ids),
                ),
            )
        )
        return conditions

    async def get_search_watermark(self, *, workspace_id: UUID) -> int:
        projection_version = await self._session.scalar(
            select(CatalogProjectionWatermarkModel.projection_version).where(
                CatalogProjectionWatermarkModel.workspace_id == workspace_id
            )
        )
        return int(projection_version or 0)

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
    ) -> CatalogPage:
        conditions = self._scope_conditions(subject)
        if query:
            pattern = _literal_contains_pattern(query)
            conditions.append(
                or_(
                    AssetProjectionModel.search_vector.op("@@")(
                        func.plainto_tsquery("simple", query)
                    ),
                    AssetProjectionModel.name.ilike(pattern, escape="\\"),
                    AssetProjectionModel.description.ilike(pattern, escape="\\"),
                )
            )
        allowed_filters = {
            "asset_type": AssetProjectionModel.asset_type,
            "platform": AssetProjectionModel.platform,
            "lifecycle": AssetProjectionModel.lifecycle,
        }
        unknown_filters = set(filters) - set(allowed_filters)
        if unknown_filters:
            raise ValidationError(
                "Unsupported catalog filters.", details={"filters": sorted(unknown_filters)}
            )
        for name, value in filters.items():
            if value not in (None, ""):
                conditions.append(allowed_filters[name] == value)
        if cursor:
            cursor_name, cursor_id = _decode_cursor(cursor)
            conditions.append(
                or_(
                    AssetProjectionModel.name > cursor_name,
                    and_(
                        AssetProjectionModel.name == cursor_name,
                        AssetProjectionModel.id > cursor_id,
                    ),
                )
            )
        statement = (
            select(AssetProjectionModel)
            .where(and_(*conditions))
            .order_by(AssetProjectionModel.name, AssetProjectionModel.id)
            .limit(limit + 1)
        )
        rows = list((await self._session.scalars(statement)).all())
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        next_cursor = (
            _encode_cursor(visible_rows[-1].name, visible_rows[-1].id)
            if has_more and visible_rows
            else None
        )
        observed_at = max((row.observed_at for row in visible_rows), default=datetime.now(UTC))
        return CatalogPage(
            items=tuple(_to_index(row) for row in visible_rows),
            next_cursor=next_cursor,
            observed_at=observed_at,
        )

    async def get_authorized_asset(
        self, *, subject: SubjectAttributes, asset_id: UUID
    ) -> CatalogAssetDetail | None:
        statement = select(AssetProjectionModel).where(
            AssetProjectionModel.id == asset_id,
            and_(*self._scope_conditions(subject)),
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        index = _to_index(model)
        return CatalogAssetDetail(
            index=index,
            ownership=(),
            glossary_terms=(),
            tags=(),
            schema_fields=(),
            quality={},
            raw_version=model.source_version,
            observed_at=model.observed_at,
        )


class SqlCatalogProjectionWriter(CatalogProjectionWriter):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
        next_offset: int | None,
        items: Sequence[DataHubScanAsset],
        observed_at: datetime,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> tuple[int, int]:
        idempotency = SqlIdempotencyStore(self._session)
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            return int(existing.result["upserted"]), int(existing.result["tombstoned"])
        workspace = await self._session.scalar(
            select(WorkspaceModel).where(WorkspaceModel.id == workspace_id).with_for_update()
        )
        if workspace is None:
            raise ValidationError("The catalog sync workspace does not exist.")
        now = utc_now()
        active = await self._session.scalar(
            select(CatalogSyncRunModel)
            .where(
                CatalogSyncRunModel.workspace_id == workspace_id,
                CatalogSyncRunModel.state == "ACTIVE",
            )
            .with_for_update()
        )
        if active is not None and active.sync_id != sync_id:
            if active.heartbeat_at >= now - timedelta(hours=1):
                raise ConflictError("Another catalog full reconciliation is active.")
            active.state = "ABANDONED"
            active.completed_at = now
            active = None
        if active is None:
            if offset != 0:
                raise ConflictError("A catalog reconciliation must begin at offset zero.")
            active = CatalogSyncRunModel(
                workspace_id=workspace_id,
                sync_id=sync_id,
                state="ACTIVE",
                next_offset=0,
                started_at=now,
                heartbeat_at=now,
            )
            self._session.add(active)
        elif active.next_offset != offset:
            raise ConflictError("The catalog reconciliation page is out of sequence.")
        for item in items:
            urn_hash = hashlib.sha256(item.external_urn.encode()).hexdigest()
            mapped = item.classification is not None and (
                item.classification is Classification.PUBLIC
                or (item.domain_ref is not None and item.system_ref is not None)
            )
            classification = int(item.classification or Classification.RESTRICTED)
            domain_id = _scope_id("domain", item.domain_ref)
            system_id = _scope_id("system", item.system_ref)
            owner_department_id = _scope_id("owner", item.owner_ref)
            lifecycle = "ACTIVE" if mapped else "QUARANTINED"
            statement = insert(AssetProjectionModel).values(
                id=uuid7(),
                workspace_id=workspace_id,
                external_urn=item.external_urn,
                urn_hash=urn_hash,
                asset_type=item.asset_type,
                name=item.name,
                description=item.description,
                platform=item.platform,
                domain_id=domain_id,
                system_id=system_id,
                owner_department_id=owner_department_id,
                classification=classification,
                lifecycle=lifecycle,
                source_version=item.source_version,
                observed_at=observed_at,
                deleted_at=None,
                last_seen_sync_id=sync_id,
                projection_source="DATAHUB",
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    AssetProjectionModel.workspace_id,
                    AssetProjectionModel.urn_hash,
                ],
                set_={
                    "external_urn": item.external_urn,
                    "asset_type": item.asset_type,
                    "name": item.name,
                    "description": item.description,
                    "platform": item.platform,
                    "domain_id": domain_id,
                    "system_id": system_id,
                    "owner_department_id": owner_department_id,
                    "classification": classification,
                    "lifecycle": lifecycle,
                    "source_version": item.source_version,
                    "observed_at": observed_at,
                    "deleted_at": None,
                    "last_seen_sync_id": sync_id,
                    "projection_source": "DATAHUB",
                    "updated_at": observed_at,
                },
            )
            await self._session.execute(statement)
        tombstoned = 0
        if next_offset is None:
            tombstoned_ids = (
                await self._session.scalars(
                    update(AssetProjectionModel)
                    .where(
                        AssetProjectionModel.workspace_id == workspace_id,
                        AssetProjectionModel.projection_source == "DATAHUB",
                        AssetProjectionModel.deleted_at.is_(None),
                        AssetProjectionModel.last_seen_sync_id.is_distinct_from(sync_id),
                    )
                    .values(
                        lifecycle="DELETED",
                        deleted_at=observed_at,
                        updated_at=observed_at,
                    )
                    .returning(AssetProjectionModel.id)
                )
            ).all()
            tombstoned = len(tombstoned_ids)
            active.state = "COMPLETED"
            active.completed_at = now
        else:
            active.next_offset = next_offset
        active.heartbeat_at = now
        await advance_catalog_projection_version(
            self._session,
            workspace_id=workspace_id,
        )
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={"upserted": len(items), "tombstoned": tombstoned},
        )
        await self._session.commit()
        return len(items), tombstoned


async def advance_catalog_projection_version(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> int:
    """Advance a workspace projection generation inside the caller's transaction."""
    statement = insert(CatalogProjectionWatermarkModel).values(
        workspace_id=workspace_id,
        projection_version=1,
    )
    upsert_statement = statement.on_conflict_do_update(
        index_elements=[CatalogProjectionWatermarkModel.workspace_id],
        set_={
            "projection_version": CatalogProjectionWatermarkModel.projection_version + 1,
        },
    ).returning(CatalogProjectionWatermarkModel.projection_version)
    projection_version = await session.scalar(upsert_statement)
    if projection_version is None:
        raise RuntimeError("Catalog projection version did not advance.")
    return int(projection_version)


def _scope_id(scope_type: str, external_ref: str | None) -> UUID | None:
    if external_ref is None:
        return None
    return uuid5(NAMESPACE_URL, f"urn:datariver:scope:{scope_type}:{external_ref}")
