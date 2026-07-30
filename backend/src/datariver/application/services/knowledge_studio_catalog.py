from __future__ import annotations

from uuid import UUID

from datariver.application.dto import (
    CatalogAssetIndex,
    KnowledgeStudioSourceAccess,
    KnowledgeStudioSourceDataset,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioSourcePage,
)
from datariver.application.services.catalog import CatalogService
from datariver.domain.authz import (
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog import DATASET_ASSET_TYPES


def _dataset(
    asset: CatalogAssetIndex,
    *,
    field_paths: tuple[str, ...] | None = None,
    fields_truncated: bool | None = None,
    source_version: str | None = None,
) -> KnowledgeStudioSourceDataset:
    return KnowledgeStudioSourceDataset(
        asset_id=asset.asset_id,
        name=asset.name,
        asset_type=asset.asset_type,
        platform=asset.platform,
        database_name=asset.database_name,
        schema_name=asset.schema_name,
        classification=asset.classification,
        source_version=source_version or asset.source_version,
        projection_source_version=asset.source_version,
        field_paths=field_paths if field_paths is not None else asset.column_names,
        fields_truncated=(
            fields_truncated if fields_truncated is not None else asset.column_names_truncated
        ),
        domain=asset.domain,
        tags=asset.tags,
        glossary_terms=asset.glossary_terms,
    )


def _field_paths(schema_fields: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for field in schema_fields:
        value = field.get("fieldPath")
        if (
            isinstance(value, str)
            and 1 <= len(value) <= 2_000
            and value == value.strip()
            and value not in seen
        ):
            seen.add(value)
            values.append(value)
    return tuple(values)


class CatalogKnowledgeStudioSourceReader:
    """Adapts the governed Catalog service to the bounded Studio source contract."""

    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    async def search_datasets(
        self,
        *,
        subject: SubjectAttributes,
        maximum_classification: Classification,
        query: str,
        cursor: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
        domain: str | None = None,
        search_fields: str | None = None,
    ) -> KnowledgeStudioSourcePage:
        filters: dict[str, object] = {
            "asset_types": sorted(DATASET_ASSET_TYPES),
            "classification_ceiling": int(maximum_classification),
        }
        if domain:
            filters["domain"] = domain
        if search_fields:
            filters["search_fields"] = search_fields
        page = await self._catalog.search(
            subject=subject,
            query=query,
            filters=filters,
            cursor=cursor,
            limit=limit,
            environment=environment,
            request_id=request_id,
        )
        return KnowledgeStudioSourcePage(
            items=tuple(
                _dataset(
                    item,
                    field_paths=(),
                    fields_truncated=(bool(item.column_names) or item.column_names_truncated),
                )
                for item in page.items
            ),
            next_cursor=page.next_cursor,
        )

    async def get_dataset(
        self,
        *,
        subject: SubjectAttributes,
        asset_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioSourceDetail | None:
        detail = await self._catalog.get_asset(
            subject=subject,
            asset_id=asset_id,
            environment=environment,
            request_id=request_id,
        )
        if detail is None or detail.index.asset_type not in DATASET_ASSET_TYPES:
            return None
        field_paths = _field_paths(detail.schema_fields)
        if not field_paths:
            field_paths = detail.index.column_names
        return KnowledgeStudioSourceDetail(
            dataset=_dataset(
                detail.index,
                field_paths=field_paths,
                fields_truncated=(
                    detail.schema_fields_truncated or detail.index.column_names_truncated
                ),
                source_version=detail.raw_version,
            ),
            observed_at=detail.observed_at,
            stale_at=detail.stale_at,
        )

    async def validate_dataset_access(
        self,
        *,
        subject: SubjectAttributes,
        asset_ids: tuple[UUID, ...],
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioSourceAccess, ...]:
        values = await self._catalog.get_asset_indexes(
            subject=subject,
            asset_ids=asset_ids,
            environment=environment,
            request_id=request_id,
        )
        return tuple(
            KnowledgeStudioSourceAccess(
                asset_id=item.asset_id,
                classification=item.classification,
                projection_source_version=item.source_version,
            )
            for item in values
        )
