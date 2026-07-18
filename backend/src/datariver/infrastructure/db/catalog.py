from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import String, and_, cast, false, func, literal, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import (
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogFacetBucket,
    CatalogFacets,
    CatalogMatchFragment,
    CatalogPage,
    CatalogSuggestion,
    CatalogSuggestions,
    CatalogTreeNode,
    CatalogTreePage,
    DataHubScanAsset,
)
from datariver.application.ports import CatalogIndexReader, CatalogProjectionWriter
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.classification_access import SearchMode
from datariver.domain.common import ConflictError, ValidationError, utc_now, uuid7
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogProjectionWatermarkModel,
    CatalogSyncRunModel,
)
from datariver.infrastructure.db.models.platform import WorkspaceModel

CATALOG_SEARCH_FIELDS = frozenset({"SCHEMA", "TABLE", "COLUMN", "TAG", "TERM", "DESCRIPTION"})


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
        database_name=model.database_name,
        schema_name=model.schema_name,
        owner=model.owner_ref,
        domain=model.domain_ref,
        tags=tuple(model.tags),
        glossary_terms=tuple(model.glossary_terms),
        created_at=model.source_created_at,
        domain_id=model.domain_id,
        system_id=model.system_id,
        owner_department_id=model.owner_department_id,
        classification=Classification(model.classification),
        lifecycle=model.lifecycle,
        source_version=model.source_version,
        observed_at=model.observed_at,
    )


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(term for term in query.split() if term))


def _search_fields(filters: dict[str, Any]) -> tuple[str, ...]:
    raw_value = filters.get("search_fields")
    if raw_value in (None, ""):
        return tuple(sorted(CATALOG_SEARCH_FIELDS))
    if not isinstance(raw_value, str):
        raise ValidationError("Catalog search fields must be a comma-separated string.")
    fields = tuple(
        dict.fromkeys(value.strip().upper() for value in raw_value.split(",") if value.strip())
    )
    if not fields or any(field not in CATALOG_SEARCH_FIELDS for field in fields):
        raise ValidationError("Catalog search fields are invalid.")
    return fields


def _catalog_query_condition(query: str, *, search_fields: tuple[str, ...]) -> Any:
    terms = _query_terms(query)
    per_term: list[Any] = []
    for term in terms:
        pattern = _literal_contains_pattern(term)
        fields: list[Any] = []
        if "TABLE" in search_fields:
            fields.append(AssetProjectionModel.name.ilike(pattern, escape="\\"))
        if "DESCRIPTION" in search_fields:
            fields.append(AssetProjectionModel.description.ilike(pattern, escape="\\"))
        if "SCHEMA" in search_fields:
            fields.append(AssetProjectionModel.schema_name.ilike(pattern, escape="\\"))
        if "COLUMN" in search_fields:
            fields.append(
                cast(AssetProjectionModel.column_names, String).ilike(pattern, escape="\\")
            )
        if "TAG" in search_fields:
            fields.append(cast(AssetProjectionModel.tags, String).ilike(pattern, escape="\\"))
        if "TERM" in search_fields:
            fields.append(
                cast(AssetProjectionModel.glossary_terms, String).ilike(pattern, escape="\\")
            )
        per_term.append(or_(*fields))
    # Each query token must match one enabled field.  This preserves the v0.3
    # ALL-keyword behavior while keeping every condition typed and locally
    # authorization-pruned; no browser-side provider query is constructed.
    return and_(*per_term)


def _match_fragments(
    *, name: str, description: str | None, query: str
) -> tuple[CatalogMatchFragment, ...]:
    terms = _query_terms(query)
    if not terms:
        return ()
    fragments: list[CatalogMatchFragment] = []
    for field, value in (("NAME", name), ("DESCRIPTION", description)):
        if not value:
            continue
        folded = value.casefold()
        matched = tuple(term for term in terms if term.casefold() in folded)
        if not matched:
            continue
        if len(value) <= 240:
            context = value
        else:
            positions = [folded.find(term.casefold()) for term in matched]
            first = min(position for position in positions if position >= 0)
            start = max(0, first - 80)
            end = min(len(value), start + 240)
            context = ("…" if start else "") + value[start:end] + ("…" if end < len(value) else "")
        fragments.append(CatalogMatchFragment(field=field, text=context, matched_terms=matched))
    return tuple(fragments)


def _group_cursor(value: str) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps([value], separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _decode_group_cursor(cursor: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        values = json.loads(payload)
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
            raise ValueError
        return values[0]
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValidationError("The catalog tree cursor is invalid.") from error


def _tree_group_cursor(kind: str, label: str) -> str:
    payload = json.dumps([kind, label], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_tree_group_cursor(cursor: str) -> tuple[str, str]:
    try:
        payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        kind, label = json.loads(payload)
        if kind not in {"DATABASE", "SCHEMA"} or not isinstance(label, str):
            raise ValueError
        return kind, label
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValidationError("The catalog tree cursor is invalid.") from error


def _tree_node_id(
    *,
    workspace_id: UUID,
    kind: str,
    platform: str | None,
    database_name: str | None,
    schema_name: str | None,
    asset_id: UUID | None = None,
) -> UUID:
    document = json.dumps(
        [str(workspace_id), kind, platform, database_name, schema_name, str(asset_id or "")],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return uuid5(NAMESPACE_URL, f"urn:datariver:catalog-tree:{document}")


def _literal_contains_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _literal_prefix_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


class SqlCatalogIndexReader(CatalogIndexReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _scope_conditions(
        self,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot | None = None,
    ) -> list[Any]:
        resolved_access = access or static_classification_access_floor()
        if resolved_access.admin_quarantine_review:
            # The service has independently recorded a human security-administrator
            # decision. This read-only review path never reaches export, Chat or mutation
            # services, but lets the administrator classify DataHub projections before
            # their normal ACTIVE/classification policy becomes available to users.
            return [
                AssetProjectionModel.workspace_id == subject.workspace_id,
                AssetProjectionModel.deleted_at.is_(None),
            ]
        standard_classifications = tuple(
            int(classification)
            for classification in Classification
            if classification is not Classification.RESTRICTED
            and classification <= subject.clearance
            and resolved_access.rule_for(classification).search_mode is SearchMode.ABAC
        )
        restricted_scope: Any = false()
        restricted_rule = resolved_access.rule_for(Classification.RESTRICTED)
        if (
            subject.clearance >= Classification.RESTRICTED
            and restricted_rule.search_mode is SearchMode.EXPLICIT_GRANT_ONLY
        ):
            scoped_conditions: list[Any] = []
            if resolved_access.restricted_resource_ids:
                scoped_conditions.append(
                    AssetProjectionModel.id.in_(resolved_access.restricted_resource_ids)
                )
            if resolved_access.restricted_system_ids:
                scoped_conditions.append(
                    AssetProjectionModel.system_id.in_(resolved_access.restricted_system_ids)
                )
            if resolved_access.restricted_domain_ids:
                scoped_conditions.append(
                    AssetProjectionModel.domain_id.in_(resolved_access.restricted_domain_ids)
                )
            restricted_scope = or_(*scoped_conditions) if scoped_conditions else false()
        conditions: list[Any] = [
            AssetProjectionModel.workspace_id == subject.workspace_id,
            AssetProjectionModel.deleted_at.is_(None),
            AssetProjectionModel.lifecycle == "ACTIVE",
            or_(
                AssetProjectionModel.classification.in_(standard_classifications),
                and_(
                    AssetProjectionModel.classification == int(Classification.RESTRICTED),
                    restricted_scope,
                ),
            ),
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
        access: ClassificationAccessSnapshot,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
    ) -> CatalogPage:
        conditions = self._scope_conditions(subject, access)
        if query:
            conditions.append(
                _catalog_query_condition(query, search_fields=_search_fields(filters))
            )
        conditions.extend(self._filter_conditions(filters))
        total = await self._session.scalar(
            select(func.count(AssetProjectionModel.id)).where(and_(*conditions))
        )
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
            items=tuple(
                replace(
                    _to_index(row),
                    matches=_match_fragments(
                        name=row.name, description=row.description, query=query
                    ),
                )
                for row in visible_rows
            ),
            next_cursor=next_cursor,
            observed_at=observed_at,
            total=int(total or 0),
        )

    async def export_page(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
    ) -> CatalogPage:
        """Read one stable export page while unconditionally excluding RESTRICTED rows."""

        conditions = self._scope_conditions(subject, access)
        conditions.append(AssetProjectionModel.classification < int(Classification.RESTRICTED))
        if query:
            conditions.append(
                _catalog_query_condition(query, search_fields=_search_fields(filters))
            )
        conditions.extend(self._filter_conditions(filters))
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
        rows = list(
            (
                await self._session.scalars(
                    select(AssetProjectionModel)
                    .where(and_(*conditions))
                    .order_by(AssetProjectionModel.name, AssetProjectionModel.id)
                    .limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        return CatalogPage(
            items=tuple(_to_index(row) for row in visible_rows),
            next_cursor=(
                _encode_cursor(visible_rows[-1].name, visible_rows[-1].id)
                if has_more and visible_rows
                else None
            ),
            observed_at=max(
                (row.observed_at for row in visible_rows),
                default=datetime.now(UTC),
            ),
        )

    async def facets(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        filters: dict[str, Any],
        limit: int,
    ) -> CatalogFacets:
        if not 1 <= limit <= 100:
            raise ValueError("Catalog facet limit must be between 1 and 100.")
        conditions = self._scope_conditions(subject, access)
        if query:
            conditions.append(
                _catalog_query_condition(query, search_fields=tuple(sorted(CATALOG_SEARCH_FIELDS)))
            )
        conditions.extend(self._filter_conditions(filters))
        facet_columns = {
            "asset_type": AssetProjectionModel.asset_type,
            "platform": AssetProjectionModel.platform,
            "classification": AssetProjectionModel.classification,
        }
        statements = []
        for facet, column in facet_columns.items():
            statements.append(
                select(
                    literal(facet).label("facet"),
                    # PostgreSQL requires a common type for every UNION column.  The
                    # public facet DTO is textual (classification is rendered as its
                    # enum name below), so normalize every grouped value at the SQL
                    # boundary instead of allowing an integer classification branch
                    # to be unioned with asset/platform strings.
                    cast(column, String).label("value"),
                    func.count(AssetProjectionModel.id).label("count"),
                    func.max(AssetProjectionModel.observed_at).label("observed_at"),
                )
                .where(and_(*conditions))
                .group_by(column)
            )
        rows = (await self._session.execute(union_all(*statements))).mappings().all()
        buckets: dict[str, list[CatalogFacetBucket]] = {name: [] for name in facet_columns}
        observed_values: list[datetime] = []
        for row in rows:
            facet = str(row["facet"])
            raw_value = row["value"]
            value = (
                Classification(int(raw_value)).name
                if facet == "classification" and raw_value is not None
                else str(raw_value)
                if raw_value is not None
                else None
            )
            buckets[facet].append(CatalogFacetBucket(value=value, count=int(row["count"])))
            if isinstance(row["observed_at"], datetime):
                observed_values.append(row["observed_at"])
        for values in buckets.values():
            values.sort(key=lambda item: (-item.count, item.value.casefold() if item.value else ""))
            del values[limit:]
        return CatalogFacets(
            asset_types=tuple(buckets["asset_type"]),
            platforms=tuple(buckets["platform"]),
            classifications=tuple(buckets["classification"]),
            observed_at=max(observed_values) if observed_values else None,
        )

    async def suggestions(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        limit: int,
    ) -> CatalogSuggestions:
        if not 1 <= limit <= 20:
            raise ValueError("Catalog suggestion limit must be between 1 and 20.")
        conditions = self._scope_conditions(subject, access)
        if len(query) < 3:
            conditions.append(
                func.lower(AssetProjectionModel.name).like(
                    _literal_prefix_pattern(query.lower()), escape="\\"
                )
            )
            ordering: tuple[Any, ...] = (
                func.lower(AssetProjectionModel.name),
                AssetProjectionModel.id,
            )
        else:
            conditions.append(
                AssetProjectionModel.name.ilike(_literal_contains_pattern(query), escape="\\")
            )
            ordering = (
                func.similarity(AssetProjectionModel.name, query).desc(),
                AssetProjectionModel.name,
                AssetProjectionModel.id,
            )
        statement = (
            select(AssetProjectionModel).where(and_(*conditions)).order_by(*ordering).limit(limit)
        )
        rows = list((await self._session.scalars(statement)).all())
        return CatalogSuggestions(
            items=tuple(
                CatalogSuggestion(
                    asset_id=row.id,
                    name=row.name,
                    asset_type=row.asset_type,
                    platform=row.platform,
                )
                for row in rows
            ),
            observed_at=max((row.observed_at for row in rows), default=None),
        )

    async def tree_nodes(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        parent_kind: str,
        platform: str | None,
        database_name: str | None,
        schema_name: str | None,
        cursor: str | None,
        limit: int,
    ) -> CatalogTreePage:
        if not 1 <= limit <= 100:
            raise ValueError("Catalog tree page limit must be between 1 and 100.")
        if parent_kind not in {"ROOT", "PLATFORM", "DATABASE", "SCHEMA"}:
            raise ValidationError("Unsupported catalog tree parent kind.")
        required = {
            "ROOT": (),
            "PLATFORM": (platform,),
            "DATABASE": (platform, database_name),
            # Some providers expose an authoritative schema browse segment
            # without materializing a database container.  Its schema remains
            # navigable, but a database label is never invented.
            "SCHEMA": (platform, schema_name),
        }[parent_kind]
        if any(value is None or not value.strip() for value in required):
            raise ValidationError("The catalog tree parent path is incomplete.")
        conditions = self._scope_conditions(subject, access)
        if query:
            conditions.append(
                _catalog_query_condition(query, search_fields=tuple(sorted(CATALOG_SEARCH_FIELDS)))
            )
        if parent_kind in {"PLATFORM", "DATABASE", "SCHEMA"}:
            conditions.append(AssetProjectionModel.platform == platform)
        if parent_kind == "DATABASE" or (parent_kind == "SCHEMA" and database_name is not None):
            conditions.append(AssetProjectionModel.database_name == database_name)
        if parent_kind == "SCHEMA":
            conditions.append(AssetProjectionModel.schema_name == schema_name)
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
            asset_statement = (
                select(AssetProjectionModel)
                .where(and_(*conditions))
                .order_by(AssetProjectionModel.name, AssetProjectionModel.id)
                .limit(limit + 1)
            )
            asset_rows = list((await self._session.scalars(asset_statement)).all())
            visible = asset_rows[:limit]
            return CatalogTreePage(
                items=tuple(
                    CatalogTreeNode(
                        node_id=_tree_node_id(
                            workspace_id=subject.workspace_id,
                            kind="ASSET",
                            platform=row.platform,
                            database_name=row.database_name,
                            schema_name=row.schema_name,
                            asset_id=row.id,
                        ),
                        kind="ASSET",
                        label=row.name,
                        asset_count=1,
                        has_children=False,
                        platform=row.platform,
                        database_name=row.database_name,
                        schema_name=row.schema_name,
                        asset=_to_index(row),
                    )
                    for row in visible
                ),
                next_cursor=(
                    _encode_cursor(visible[-1].name, visible[-1].id)
                    if len(asset_rows) > limit and visible
                    else None
                ),
                observed_at=max((row.observed_at for row in visible), default=None),
            )

        if parent_kind == "PLATFORM":
            database_groups = (
                select(
                    AssetProjectionModel.database_name.label("label"),
                    literal("DATABASE").label("kind"),
                    func.count(AssetProjectionModel.id).label("asset_count"),
                    func.max(AssetProjectionModel.observed_at).label("observed_at"),
                )
                .where(
                    and_(
                        *conditions,
                        AssetProjectionModel.database_name.is_not(None),
                    )
                )
                .group_by(AssetProjectionModel.database_name)
            )
            schema_without_database_groups = (
                select(
                    AssetProjectionModel.schema_name.label("label"),
                    literal("SCHEMA").label("kind"),
                    func.count(AssetProjectionModel.id).label("asset_count"),
                    func.max(AssetProjectionModel.observed_at).label("observed_at"),
                )
                .where(
                    and_(
                        *conditions,
                        AssetProjectionModel.database_name.is_(None),
                        AssetProjectionModel.schema_name.is_not(None),
                    )
                )
                .group_by(AssetProjectionModel.schema_name)
            )
            grouped = union_all(database_groups, schema_without_database_groups).subquery()
            group_conditions: list[Any] = []
            if cursor:
                cursor_kind, cursor_label = _decode_tree_group_cursor(cursor)
                group_conditions.append(
                    or_(
                        grouped.c.kind > cursor_kind,
                        and_(grouped.c.kind == cursor_kind, grouped.c.label > cursor_label),
                    )
                )
            group_statement = (
                select(grouped)
                .where(*group_conditions)
                .order_by(grouped.c.kind, grouped.c.label)
                .limit(limit + 1)
            )
            group_rows = list((await self._session.execute(group_statement)).mappings().all())
            visible_rows = group_rows[:limit]
            platform_nodes: list[CatalogTreeNode] = []
            for row in visible_rows:
                kind = str(row["kind"])
                label = str(row["label"])
                child_database = label if kind == "DATABASE" else None
                child_schema = label if kind == "SCHEMA" else None
                platform_nodes.append(
                    CatalogTreeNode(
                        node_id=_tree_node_id(
                            workspace_id=subject.workspace_id,
                            kind=kind,
                            platform=platform,
                            database_name=child_database,
                            schema_name=child_schema,
                        ),
                        kind=kind,
                        label=label,
                        asset_count=int(row["asset_count"]),
                        has_children=True,
                        platform=platform,
                        database_name=child_database,
                        schema_name=child_schema,
                    )
                )
            return CatalogTreePage(
                items=tuple(platform_nodes),
                next_cursor=(
                    _tree_group_cursor(
                        str(visible_rows[-1]["kind"]), str(visible_rows[-1]["label"])
                    )
                    if len(group_rows) > limit and visible_rows
                    else None
                ),
                observed_at=max(
                    (row["observed_at"] for row in visible_rows if row["observed_at"]),
                    default=None,
                ),
            )

        column, child_kind = {
            "ROOT": (AssetProjectionModel.platform, "PLATFORM"),
            "DATABASE": (AssetProjectionModel.schema_name, "SCHEMA"),
        }[parent_kind]
        conditions.append(column.is_not(None))
        if cursor:
            conditions.append(column > _decode_group_cursor(cursor))
        group_statement = (
            select(
                column.label("label"),
                func.count(AssetProjectionModel.id).label("asset_count"),
                func.max(AssetProjectionModel.observed_at).label("observed_at"),
            )
            .where(and_(*conditions))
            .group_by(column)
            .order_by(column)
            .limit(limit + 1)
        )
        group_rows = list((await self._session.execute(group_statement)).mappings().all())
        visible_rows = group_rows[:limit]
        nodes: list[CatalogTreeNode] = []
        for row in visible_rows:
            label = str(row["label"])
            child_platform = label if child_kind == "PLATFORM" else platform
            child_database = label if child_kind == "DATABASE" else database_name
            child_schema = label if child_kind == "SCHEMA" else schema_name
            nodes.append(
                CatalogTreeNode(
                    node_id=_tree_node_id(
                        workspace_id=subject.workspace_id,
                        kind=child_kind,
                        platform=child_platform,
                        database_name=child_database,
                        schema_name=child_schema,
                    ),
                    kind=child_kind,
                    label=label,
                    asset_count=int(row["asset_count"]),
                    has_children=True,
                    platform=child_platform,
                    database_name=child_database,
                    schema_name=child_schema,
                )
            )
        return CatalogTreePage(
            items=tuple(nodes),
            next_cursor=(
                _group_cursor(str(visible_rows[-1]["label"]))
                if len(group_rows) > limit and visible_rows
                else None
            ),
            observed_at=max(
                (row["observed_at"] for row in visible_rows if row["observed_at"]),
                default=None,
            ),
        )

    @staticmethod
    def _filter_conditions(filters: dict[str, Any]) -> list[Any]:
        allowed_filters = {
            "asset_type": AssetProjectionModel.asset_type,
            "platform": AssetProjectionModel.platform,
            "lifecycle": AssetProjectionModel.lifecycle,
            "database_name": AssetProjectionModel.database_name,
            "schema_name": AssetProjectionModel.schema_name,
            "domain": AssetProjectionModel.domain_ref,
        }
        unknown_filters = set(filters) - {*allowed_filters, "classification", "search_fields"}
        if unknown_filters:
            raise ValidationError(
                "Unsupported catalog filters.", details={"filters": sorted(unknown_filters)}
            )
        conditions = [
            allowed_filters[name] == value
            for name, value in filters.items()
            if name in allowed_filters and value not in (None, "")
        ]
        raw_classification = filters.get("classification")
        if raw_classification not in (None, ""):
            try:
                classification = Classification[str(raw_classification).upper()]
            except KeyError as error:
                raise ValidationError("Unsupported catalog classification filter.") from error
            conditions.append(AssetProjectionModel.classification == int(classification))
        return conditions

    async def get_authorized_asset(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        asset_id: UUID,
    ) -> CatalogAssetDetail | None:
        statement = select(AssetProjectionModel).where(
            AssetProjectionModel.id == asset_id,
            and_(*self._scope_conditions(subject, access)),
        )
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None:
            return None
        index = _to_index(model)
        return CatalogAssetDetail(
            index=index,
            ownership=(),
            glossary_terms=(),
            tags=index.tags,
            schema_fields=(),
            quality={},
            raw_version=model.source_version,
            observed_at=model.observed_at,
        )

    async def get_authorized_assets_by_external_urns(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        external_urns: Sequence[str],
        lock_for_share: bool = False,
    ) -> Sequence[CatalogAssetIndex]:
        unique_urns = tuple(dict.fromkeys(external_urns))
        if len(unique_urns) > 1_000:
            raise ValueError("The lineage candidate set exceeds the configured bound.")
        if not unique_urns:
            return ()
        statement = select(AssetProjectionModel).where(
            AssetProjectionModel.external_urn.in_(unique_urns),
            and_(*self._scope_conditions(subject, access)),
        )
        if lock_for_share:
            statement = statement.with_for_update(read=True, of=AssetProjectionModel)
        return tuple(_to_index(model) for model in (await self._session.scalars(statement)).all())

    async def get_authorized_assets_by_ids(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        asset_ids: Sequence[UUID],
    ) -> Sequence[CatalogAssetIndex]:
        unique_ids = tuple(dict.fromkeys(asset_ids))
        if len(unique_ids) > 1_000:
            raise ValueError("The catalog candidate target set exceeds the configured bound.")
        if not unique_ids:
            return ()
        statement = select(AssetProjectionModel).where(
            AssetProjectionModel.id.in_(unique_ids),
            AssetProjectionModel.asset_type == "DATASET",
            and_(*self._scope_conditions(subject, access)),
        )
        return tuple(_to_index(model) for model in (await self._session.scalars(statement)).all())


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
        workspace_lock_key = int.from_bytes(
            hashlib.sha256(f"catalog-sync:{workspace_id}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await self._session.execute(select(func.pg_advisory_xact_lock(workspace_lock_key)))
        workspace = await self._session.scalar(
            select(WorkspaceModel).where(WorkspaceModel.id == workspace_id)
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
                database_name=item.database_name,
                schema_name=item.schema_name,
                owner_ref=item.owner_ref,
                domain_ref=item.domain_ref,
                tags=list(item.tags),
                glossary_terms=list(item.glossary_terms),
                column_names=list(item.column_names),
                source_created_at=item.created_at,
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
                    "database_name": item.database_name,
                    "schema_name": item.schema_name,
                    "owner_ref": item.owner_ref,
                    "domain_ref": item.domain_ref,
                    "tags": list(item.tags),
                    "glossary_terms": list(item.glossary_terms),
                    "column_names": list(item.column_names),
                    "source_created_at": item.created_at,
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
