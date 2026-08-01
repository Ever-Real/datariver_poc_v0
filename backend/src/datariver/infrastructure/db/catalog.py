from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    tuple_,
    union_all,
    update,
)
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
    CatalogSyncProgress,
    CatalogSyncReservation,
    CatalogSyncResult,
    CatalogTreeNode,
    CatalogTreePage,
    CatalogVocabulary,
    DataHubScanAsset,
)
from datariver.application.ports import (
    CatalogIndexReader,
    CatalogProjectionWriter,
    CatalogReaderMode,
)
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.catalog import DATASET_ASSET_TYPES
from datariver.domain.common import ConflictError, ValidationError, utc_now, uuid7
from datariver.infrastructure.db.catalog_visibility import (
    catalog_asset_scope_conditions,
    catalog_asset_workspace_discovery_conditions,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogProjectionWatermarkModel,
    CatalogSyncRunModel,
)
from datariver.infrastructure.db.models.platform import WorkspaceModel

CATALOG_SEARCH_FIELDS = frozenset({"SCHEMA", "TABLE", "COLUMN", "TAG", "TERM", "DESCRIPTION"})
MAX_CATALOG_QUERY_TERMS = 12
MAX_CATALOG_QUERY_TERM_LENGTH = 120
MAX_CATALOG_EXTERNAL_URN_CHARACTERS = 4_096
MAX_CATALOG_PROJECTION_DESCRIPTION_CHARACTERS = 10_000
MAX_CATALOG_PROJECTION_METADATA_ITEMS = 100
MAX_CATALOG_PROJECTION_METADATA_CHARACTERS = 1_000
MAX_CATALOG_PROJECTION_COLUMN_ITEMS = 1_000
MAX_CATALOG_PROJECTION_COLUMN_CHARACTERS = 500


def _bounded_scan_asset(item: DataHubScanAsset) -> DataHubScanAsset:
    if not item.external_urn or len(item.external_urn) > MAX_CATALOG_EXTERNAL_URN_CHARACTERS:
        raise ValidationError(
            "Catalog asset URNs must contain between 1 and "
            f"{MAX_CATALOG_EXTERNAL_URN_CHARACTERS} characters."
        )
    return replace(
        item,
        description=(
            item.description[:MAX_CATALOG_PROJECTION_DESCRIPTION_CHARACTERS]
            if item.description is not None
            else None
        ),
        tags=tuple(
            value[:MAX_CATALOG_PROJECTION_METADATA_CHARACTERS]
            for value in item.tags[:MAX_CATALOG_PROJECTION_METADATA_ITEMS]
        ),
        glossary_terms=tuple(
            value[:MAX_CATALOG_PROJECTION_METADATA_CHARACTERS]
            for value in item.glossary_terms[:MAX_CATALOG_PROJECTION_METADATA_ITEMS]
        ),
        column_names=tuple(
            value[:MAX_CATALOG_PROJECTION_COLUMN_CHARACTERS]
            for value in item.column_names[:MAX_CATALOG_PROJECTION_COLUMN_ITEMS]
        ),
        description_truncated=(
            item.description_truncated
            or (
                item.description is not None
                and len(item.description) > MAX_CATALOG_PROJECTION_DESCRIPTION_CHARACTERS
            )
        ),
        tags_truncated=(
            item.tags_truncated
            or len(item.tags) > MAX_CATALOG_PROJECTION_METADATA_ITEMS
            or any(
                len(value) > MAX_CATALOG_PROJECTION_METADATA_CHARACTERS
                for value in item.tags[:MAX_CATALOG_PROJECTION_METADATA_ITEMS]
            )
        ),
        glossary_terms_truncated=(
            item.glossary_terms_truncated
            or len(item.glossary_terms) > MAX_CATALOG_PROJECTION_METADATA_ITEMS
            or any(
                len(value) > MAX_CATALOG_PROJECTION_METADATA_CHARACTERS
                for value in item.glossary_terms[:MAX_CATALOG_PROJECTION_METADATA_ITEMS]
            )
        ),
        column_names_truncated=(
            item.column_names_truncated
            or len(item.column_names) > MAX_CATALOG_PROJECTION_COLUMN_ITEMS
            or any(
                len(value) > MAX_CATALOG_PROJECTION_COLUMN_CHARACTERS
                for value in item.column_names[:MAX_CATALOG_PROJECTION_COLUMN_ITEMS]
            )
        ),
    )


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
        column_names=tuple(model.column_names),
        description_truncated=model.description_truncated,
        tags_truncated=model.tags_truncated,
        glossary_terms_truncated=model.glossary_terms_truncated,
        column_names_truncated=model.column_names_truncated,
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
    terms = tuple(dict.fromkeys(term for term in query.split() if term))
    if len(terms) > MAX_CATALOG_QUERY_TERMS:
        raise ValidationError(
            f"Catalog search accepts at most {MAX_CATALOG_QUERY_TERMS} unique terms."
        )
    if any(len(term) > MAX_CATALOG_QUERY_TERM_LENGTH for term in terms):
        raise ValidationError(
            f"Each catalog search term must be at most {MAX_CATALOG_QUERY_TERM_LENGTH} characters."
        )
    return terms


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


def _jsonb_array_contains(column: Any, pattern: str) -> Any:
    values = func.jsonb_array_elements_text(column).table_valued(
        "value",
        joins_implicitly=True,
    )
    return (
        select(literal(1))
        .select_from(values)
        .where(values.c.value.ilike(pattern, escape="\\"))
        .exists()
    )


def _catalog_query_condition(query: str, *, search_fields: tuple[str, ...]) -> Any:
    terms = _query_terms(query)
    per_term: list[Any] = []
    for term in terms:
        pattern = _literal_contains_pattern(term)
        fields: list[Any] = []
        array_fields: list[Any] = []
        if "TABLE" in search_fields:
            fields.append(AssetProjectionModel.name.ilike(pattern, escape="\\"))
        if "DESCRIPTION" in search_fields:
            fields.append(AssetProjectionModel.description.ilike(pattern, escape="\\"))
        if "SCHEMA" in search_fields:
            fields.append(AssetProjectionModel.schema_name.ilike(pattern, escape="\\"))
        if "COLUMN" in search_fields:
            array_fields.append(AssetProjectionModel.column_names)
        if "TAG" in search_fields:
            array_fields.append(AssetProjectionModel.tags)
        if "TERM" in search_fields:
            array_fields.append(AssetProjectionModel.glossary_terms)
        if array_fields:
            combined_array = array_fields[0]
            for array_field in array_fields[1:]:
                combined_array = combined_array.op("||")(array_field)
            fields.append(_jsonb_array_contains(combined_array, pattern))
        per_term.append(or_(*fields))
    # Each query token must match one enabled field.  This preserves the v0.3
    # ALL-keyword behavior while keeping every condition typed and locally
    # authorization-pruned; no browser-side provider query is constructed.
    return and_(*per_term)


def _source_index_for_folded_offset(value: str, folded_offset: int) -> int:
    current_offset = 0
    for source_index, character in enumerate(value):
        next_offset = current_offset + len(character.casefold())
        if current_offset <= folded_offset < next_offset:
            return source_index
        current_offset = next_offset
    return len(value)


def _match_context(value: str, folded: str, matched_term: str) -> str:
    if len(value) <= 240:
        return value
    term_folded = matched_term.casefold()
    first = folded.find(term_folded)
    source_start = _source_index_for_folded_offset(value, first)
    source_end = _source_index_for_folded_offset(value, first + len(term_folded) - 1) + 1
    padding = max(0, (238 - (source_end - source_start)) // 2)
    start = max(0, source_start - padding)
    end = min(len(value), start + 238)
    start = max(0, end - 238)
    return ("…" if start else "") + value[start:end] + ("…" if end < len(value) else "")


def _match_fragments(
    *,
    name: str,
    description: str | None,
    schema_name: str | None = None,
    column_names: Sequence[str] = (),
    tags: Sequence[str] = (),
    glossary_terms: Sequence[str] = (),
    query: str,
    search_fields: tuple[str, ...] | None = None,
) -> tuple[CatalogMatchFragment, ...]:
    terms = _query_terms(query)
    if not terms:
        return ()
    enabled = frozenset(search_fields or CATALOG_SEARCH_FIELDS)
    fragments: list[CatalogMatchFragment] = []
    values: tuple[tuple[str, str | None], ...] = (
        ("NAME", name if "TABLE" in enabled else None),
        ("DESCRIPTION", description if "DESCRIPTION" in enabled else None),
        ("SCHEMA", schema_name if "SCHEMA" in enabled else None),
        ("COLUMN", " · ".join(column_names) if "COLUMN" in enabled else None),
        ("TAG", " · ".join(tags) if "TAG" in enabled else None),
        ("TERM", " · ".join(glossary_terms) if "TERM" in enabled else None),
    )
    for field, value in values:
        if not value:
            continue
        folded = value.casefold()
        matched = tuple(term for term in terms if term.casefold() in folded)
        if not matched:
            continue
        if len(value) <= 240:
            fragments.append(CatalogMatchFragment(field=field, text=value, matched_terms=matched))
            continue
        for term in matched:
            fragments.append(
                CatalogMatchFragment(
                    field=field,
                    text=_match_context(value, folded, term),
                    matched_terms=(term,),
                )
            )
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
    def __init__(
        self,
        session: AsyncSession,
        *,
        reader_mode: CatalogReaderMode = CatalogReaderMode.SCOPED,
    ) -> None:
        self._session = session
        self._reader_mode = reader_mode

    def _scope_conditions(
        self,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot | None = None,
        reader_mode: CatalogReaderMode | None = None,
    ) -> list[Any]:
        if (reader_mode or self._reader_mode) is CatalogReaderMode.WORKSPACE_DISCOVERY:
            return catalog_asset_workspace_discovery_conditions(
                subject,
                access or static_classification_access_floor(),
            )
        return catalog_asset_scope_conditions(
            subject,
            access,
            include_quarantine_review=True,
        )

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
        first_page = cursor is None
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
                        name=row.name,
                        description=row.description,
                        schema_name=row.schema_name,
                        column_names=row.column_names,
                        tags=row.tags,
                        glossary_terms=row.glossary_terms,
                        query=query,
                        search_fields=_search_fields(filters),
                    ),
                )
                for row in visible_rows
            ),
            next_cursor=next_cursor,
            observed_at=observed_at,
            total=len(rows),
            total_exact=first_page and not has_more,
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
                _catalog_query_condition(query, search_fields=_search_fields(filters))
            )
        conditions.extend(self._filter_conditions(filters))
        facet_columns = {
            "asset_type": AssetProjectionModel.asset_type,
            "platform": AssetProjectionModel.platform,
            "database": AssetProjectionModel.database_name,
            "schema": AssetProjectionModel.schema_name,
            "domain": AssetProjectionModel.domain_ref,
            "classification": AssetProjectionModel.classification,
            "lifecycle": AssetProjectionModel.lifecycle,
        }
        facet_expression = case(
            *[
                (func.grouping(column) == 0, literal(facet))
                for facet, column in facet_columns.items()
            ]
        ).label("facet")
        value_expression = case(
            *[
                (func.grouping(column) == 0, cast(column, String))
                for column in facet_columns.values()
            ]
        ).label("value")
        aggregated = (
            select(
                facet_expression,
                value_expression,
                func.count(AssetProjectionModel.id).label("count"),
                func.max(AssetProjectionModel.observed_at).label("observed_at"),
            )
            .where(and_(*conditions))
            .group_by(func.grouping_sets(*(tuple_(column) for column in facet_columns.values())))
            .subquery()
        )
        ranked = select(
            aggregated,
            func.row_number()
            .over(
                partition_by=aggregated.c.facet,
                order_by=(
                    aggregated.c.count.desc(),
                    aggregated.c.value.asc().nulls_first(),
                ),
            )
            .label("facet_rank"),
        ).subquery()
        rows = (
            (
                await self._session.execute(
                    select(
                        ranked.c.facet,
                        ranked.c.value,
                        ranked.c.count,
                        ranked.c.observed_at,
                    ).where(ranked.c.facet_rank <= limit)
                )
            )
            .mappings()
            .all()
        )
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
            databases=tuple(buckets["database"]),
            schemas=tuple(buckets["schema"]),
            domains=tuple(buckets["domain"]),
            lifecycles=tuple(buckets["lifecycle"]),
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
        conditions.append(
            _catalog_query_condition(
                query,
                search_fields=tuple(sorted(CATALOG_SEARCH_FIELDS)),
            )
        )
        ordering: tuple[Any, ...] = (
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
                    database_name=row.database_name,
                    schema_name=row.schema_name,
                    matches=_match_fragments(
                        name=row.name,
                        description=row.description,
                        schema_name=row.schema_name,
                        column_names=row.column_names,
                        tags=row.tags,
                        glossary_terms=row.glossary_terms,
                        query=query,
                    ),
                )
                for row in rows
            ),
            observed_at=max((row.observed_at for row in rows), default=None),
        )

    async def vocabulary(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        kind: str,
        query: str,
        limit: int,
    ) -> CatalogVocabulary:
        if kind not in {"TAG", "TERM", "DOMAIN"} or not 1 <= limit <= 50:
            raise ValueError("Catalog vocabulary request is invalid.")
        rows = list(
            (
                await self._session.execute(
                    select(
                        AssetProjectionModel.tags,
                        AssetProjectionModel.glossary_terms,
                        AssetProjectionModel.domain_ref,
                        AssetProjectionModel.observed_at,
                    )
                    .where(and_(*self._scope_conditions(subject, access)))
                    .order_by(AssetProjectionModel.observed_at.desc(), AssetProjectionModel.id)
                    .limit(5_000)
                )
            ).all()
        )
        query_key = query.casefold().strip()
        values: set[str] = set()
        observed_at: datetime | None = None
        for tags, terms, domain, observed in rows:
            candidates: Sequence[object]
            if kind == "TAG":
                candidates = tags if isinstance(tags, list) else ()
            elif kind == "TERM":
                candidates = terms if isinstance(terms, list) else ()
            else:
                candidates = (domain,) if isinstance(domain, str) else ()
            for candidate in candidates:
                if (
                    isinstance(candidate, str)
                    and candidate
                    and (not query_key or query_key in candidate.casefold())
                ):
                    values.add(candidate)
            if isinstance(observed, datetime):
                observed_at = max(observed_at, observed) if observed_at else observed
        return CatalogVocabulary(
            items=tuple(sorted(values, key=str.casefold)[:limit]),
            observed_at=observed_at,
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
        unknown_filters = set(filters) - {
            *allowed_filters,
            "asset_types",
            "classification",
            "classification_ceiling",
            "search_fields",
        }
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
        raw_classification_ceiling = filters.get("classification_ceiling")
        if raw_classification_ceiling is not None:
            if (
                not isinstance(raw_classification_ceiling, int)
                or isinstance(raw_classification_ceiling, bool)
                or not 0 <= raw_classification_ceiling <= 3
            ):
                raise ValidationError("Unsupported catalog classification ceiling.")
            conditions.append(AssetProjectionModel.classification <= raw_classification_ceiling)
        raw_asset_types = filters.get("asset_types")
        if raw_asset_types is not None:
            if (
                not isinstance(raw_asset_types, list | tuple)
                or not raw_asset_types
                or len(raw_asset_types) > len(DATASET_ASSET_TYPES)
                or any(
                    not isinstance(value, str) or value not in DATASET_ASSET_TYPES
                    for value in raw_asset_types
                )
            ):
                raise ValidationError("Unsupported catalog asset type set.")
            conditions.append(AssetProjectionModel.asset_type.in_(tuple(raw_asset_types)))
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
            AssetProjectionModel.asset_type.in_(tuple(sorted(DATASET_ASSET_TYPES))),
            and_(*self._scope_conditions(subject, access)),
        )
        return tuple(_to_index(model) for model in (await self._session.scalars(statement)).all())


class SqlCatalogProjectionWriter(CatalogProjectionWriter):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock_workspace(self, workspace_id: UUID) -> None:
        workspace_lock_key = int.from_bytes(
            hashlib.sha256(f"catalog-sync:{workspace_id}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await self._session.execute(select(func.pg_advisory_xact_lock(workspace_lock_key)))

    async def reserve_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogSyncReservation:
        await self._lock_workspace(workspace_id)
        replayed = await self.replay_scan(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation,
        )
        if replayed is not None:
            await self._session.rollback()
            return CatalogSyncReservation(cursor=None, replayed=replayed)
        workspace = await self._session.scalar(
            select(WorkspaceModel).where(WorkspaceModel.id == workspace_id)
        )
        if workspace is None:
            await self._session.rollback()
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
                await self._session.rollback()
                raise ConflictError("Another catalog full reconciliation is active.")
            active.state = "ABANDONED"
            active.completed_at = now
            active.heartbeat_at = now
            active = None
        if active is None:
            if offset != 0:
                await self._session.rollback()
                raise ConflictError("A catalog reconciliation must begin at page zero.")
            active = CatalogSyncRunModel(
                workspace_id=workspace_id,
                sync_id=sync_id,
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
            )
            self._session.add(active)
            await self._session.flush()
        elif active.next_offset != offset:
            await self._session.rollback()
            raise ConflictError("The catalog reconciliation page is out of sequence.")
        return CatalogSyncReservation(cursor=active.next_cursor)

    async def release_scan(self) -> None:
        await self._session.rollback()

    async def abandon_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
    ) -> None:
        now = utc_now()
        await self._session.execute(
            update(CatalogSyncRunModel)
            .where(
                CatalogSyncRunModel.workspace_id == workspace_id,
                CatalogSyncRunModel.sync_id == sync_id,
                CatalogSyncRunModel.state == "ACTIVE",
            )
            .values(
                state="ABANDONED",
                completed_at=now,
                heartbeat_at=now,
            )
        )
        await self._session.commit()

    async def replay_scan(
        self,
        *,
        workspace_id: UUID,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogSyncResult | None:
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
            next_offset_raw = result["next_offset"]
            next_offset = int(next_offset_raw) if next_offset_raw is not None else None
            tombstone_status = str(result["tombstone_status"])
            if tombstone_status not in {
                "NOT_FINAL",
                "APPLIED",
                "SUPPRESSED_UNVERIFIED_SNAPSHOT",
            }:
                raise ValueError
            return CatalogSyncResult(
                upserted=int(result["upserted"]),
                tombstoned=int(result["tombstoned"]),
                next_offset=next_offset,
                total=int(result["total"]),
                observed_at=datetime.fromisoformat(str(result["observed_at"])),
                tombstone_status=tombstone_status,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ConflictError("The stored catalog sync replay result is invalid.") from error

    async def expected_cursor(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
    ) -> str | None:
        active = await self._session.scalar(
            select(CatalogSyncRunModel).where(
                CatalogSyncRunModel.workspace_id == workspace_id,
                CatalogSyncRunModel.state == "ACTIVE",
            )
        )
        if active is None:
            if offset != 0:
                raise ConflictError("A catalog reconciliation must begin at page zero.")
            return None
        if active.sync_id != sync_id:
            if offset == 0 and active.heartbeat_at < utc_now() - timedelta(hours=1):
                return None
            raise ConflictError("Another catalog full reconciliation is active.")
        if active.next_offset != offset:
            raise ConflictError("The catalog reconciliation page is out of sequence.")
        return active.next_cursor

    async def scan_progress(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
    ) -> CatalogSyncProgress:
        run = await self._session.scalar(
            select(CatalogSyncRunModel).where(
                CatalogSyncRunModel.workspace_id == workspace_id,
                CatalogSyncRunModel.sync_id == sync_id,
            )
        )
        if run is None:
            return CatalogSyncProgress(
                state="NOT_STARTED",
                next_offset=0,
                seen_count=0,
                expected_total=None,
                snapshot_consistent=False,
            )
        return CatalogSyncProgress(
            state=run.state,
            next_offset=run.next_offset if run.state == "ACTIVE" else None,
            seen_count=run.seen_count,
            expected_total=run.expected_total,
            snapshot_consistent=run.snapshot_consistent,
        )

    async def upsert_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
        cursor: str | None,
        next_offset: int | None,
        next_cursor: str | None,
        total: int,
        snapshot_consistent: bool,
        snapshot_evidence_reference: str | None,
        snapshot_contract_hash: str | None,
        snapshot_provider_version: str | None,
        items: Sequence[DataHubScanAsset],
        observed_at: datetime,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogSyncResult:
        for candidate in (cursor, next_cursor):
            if candidate is not None and not 1 <= len(candidate) <= 4_096:
                raise ValidationError("The catalog sync cursor is outside the configured bound.")
        if snapshot_consistent:
            if (
                not isinstance(snapshot_evidence_reference, str)
                or not 1 <= len(snapshot_evidence_reference) <= 500
                or not isinstance(snapshot_contract_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", snapshot_contract_hash) is None
                or not isinstance(snapshot_provider_version, str)
                or not 1 <= len(snapshot_provider_version) <= 128
            ):
                raise ValidationError(
                    "A verified catalog snapshot requires bounded immutable evidence."
                )
        elif any(
            value is not None
            for value in (
                snapshot_evidence_reference,
                snapshot_contract_hash,
                snapshot_provider_version,
            )
        ):
            raise ValidationError(
                "An unverified catalog snapshot cannot persist verification evidence."
            )
        idempotency = SqlIdempotencyStore(self._session)
        await self._lock_workspace(workspace_id)
        existing = await self.replay_scan(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation,
        )
        if existing is not None:
            await self._session.rollback()
            return existing
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
            if offset != 0 or cursor is not None:
                raise ConflictError("A catalog reconciliation must begin at offset zero.")
            active = CatalogSyncRunModel(
                workspace_id=workspace_id,
                sync_id=sync_id,
                state="ACTIVE",
                next_offset=0,
                next_cursor=None,
                expected_total=total,
                seen_count=0,
                snapshot_consistent=snapshot_consistent,
                snapshot_evidence_reference=snapshot_evidence_reference,
                snapshot_contract_hash=snapshot_contract_hash,
                snapshot_provider_version=snapshot_provider_version,
                started_at=now,
                heartbeat_at=now,
            )
            self._session.add(active)
        elif active.next_offset != offset or active.next_cursor != cursor:
            raise ConflictError("The catalog reconciliation page is out of sequence.")
        elif active.expected_total is None:
            if offset != 0 or cursor is not None or active.seen_count != 0:
                raise ConflictError("The catalog reconciliation reservation is invalid.")
            active.expected_total = total
            active.snapshot_consistent = snapshot_consistent
            active.snapshot_evidence_reference = snapshot_evidence_reference
            active.snapshot_contract_hash = snapshot_contract_hash
            active.snapshot_provider_version = snapshot_provider_version
        elif (
            active.expected_total != total
            or active.snapshot_consistent != snapshot_consistent
            or active.snapshot_evidence_reference != snapshot_evidence_reference
            or active.snapshot_contract_hash != snapshot_contract_hash
            or active.snapshot_provider_version != snapshot_provider_version
        ):
            raise ConflictError("The catalog reconciliation snapshot changed between pages.")
        if next_cursor is not None and (not next_cursor or next_cursor == cursor):
            raise ConflictError("The catalog reconciliation cursor did not advance.")
        bounded_items = tuple(_bounded_scan_asset(item) for item in items)
        urn_hashes = tuple(
            hashlib.sha256(item.external_urn.encode()).hexdigest() for item in bounded_items
        )
        if len(set(urn_hashes)) != len(urn_hashes):
            raise ConflictError("The catalog reconciliation page contains duplicate assets.")
        if urn_hashes:
            previously_seen = await self._session.scalar(
                select(AssetProjectionModel.id)
                .where(
                    AssetProjectionModel.workspace_id == workspace_id,
                    AssetProjectionModel.last_seen_sync_id == sync_id,
                    AssetProjectionModel.urn_hash.in_(urn_hashes),
                )
                .limit(1)
            )
            if previously_seen is not None:
                raise ConflictError(
                    "The catalog reconciliation repeated an asset from an earlier page."
                )
        for item, urn_hash in zip(bounded_items, urn_hashes, strict=True):
            mapped = item.classification is not None and (
                item.classification is Classification.PUBLIC
                or (item.domain_ref is not None and item.system_ref is not None)
            )
            classification = int(
                item.classification
                if item.classification is not None
                else Classification.RESTRICTED
            )
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
                description_truncated=item.description_truncated,
                platform=item.platform,
                database_name=item.database_name,
                schema_name=item.schema_name,
                owner_ref=item.owner_ref,
                domain_ref=item.domain_ref,
                tags=list(item.tags),
                tags_truncated=item.tags_truncated,
                glossary_terms=list(item.glossary_terms),
                glossary_terms_truncated=item.glossary_terms_truncated,
                column_names=list(item.column_names),
                column_names_truncated=item.column_names_truncated,
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
                    "description_truncated": item.description_truncated,
                    "platform": item.platform,
                    "database_name": item.database_name,
                    "schema_name": item.schema_name,
                    "owner_ref": item.owner_ref,
                    "domain_ref": item.domain_ref,
                    "tags": list(item.tags),
                    "tags_truncated": item.tags_truncated,
                    "glossary_terms": list(item.glossary_terms),
                    "glossary_terms_truncated": item.glossary_terms_truncated,
                    "column_names": list(item.column_names),
                    "column_names_truncated": item.column_names_truncated,
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
        seen_count = active.seen_count + len(bounded_items)
        expected_total = active.expected_total
        if expected_total is None or seen_count > expected_total:
            raise ConflictError("The catalog reconciliation exceeded its declared snapshot total.")
        tombstoned = 0
        if next_cursor is None:
            if next_offset is not None or seen_count != expected_total:
                raise ConflictError("The catalog reconciliation snapshot is incomplete.")
            if active.snapshot_consistent:
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
            if next_offset != offset + 1:
                raise ConflictError("The catalog reconciliation page number did not advance.")
            active.next_offset = next_offset
            active.next_cursor = next_cursor
        active.seen_count = seen_count
        active.heartbeat_at = now
        await advance_catalog_projection_version(
            self._session,
            workspace_id=workspace_id,
        )
        tombstone_status = (
            "NOT_FINAL"
            if next_cursor is not None
            else "APPLIED"
            if active.snapshot_consistent
            else "SUPPRESSED_UNVERIFIED_SNAPSHOT"
        )
        result = CatalogSyncResult(
            upserted=len(items),
            tombstoned=tombstoned,
            next_offset=next_offset,
            total=total,
            observed_at=observed_at,
            tombstone_status=tombstone_status,
        )
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={
                "upserted": result.upserted,
                "tombstoned": result.tombstoned,
                "next_offset": result.next_offset,
                "total": result.total,
                "observed_at": result.observed_at.isoformat(),
                "tombstone_status": result.tombstone_status,
            },
        )
        await self._session.commit()
        return result


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
