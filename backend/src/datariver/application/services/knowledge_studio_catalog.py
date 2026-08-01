from __future__ import annotations

from uuid import UUID

from datariver.application.dto import (
    CatalogAssetIndex,
    KnowledgeStudioCatalogFieldMetadata,
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
from datariver.domain.common import canonical_json_hash
from datariver.domain.knowledge_studio_proposal_jobs import (
    KNOWLEDGE_STUDIO_CATALOG_MAX_DESCRIPTION_CHARACTERS,
    KNOWLEDGE_STUDIO_CATALOG_MAX_FIELD_PATH_CHARACTERS,
    KNOWLEDGE_STUDIO_CATALOG_MAX_FIELD_REFERENCE_CHARACTERS,
    KNOWLEDGE_STUDIO_CATALOG_MAX_FIELD_REFERENCES,
)


def _dataset(
    asset: CatalogAssetIndex,
    *,
    field_paths: tuple[str, ...] | None = None,
    fields_truncated: bool | None = None,
    source_version: str | None = None,
    description: str | None = None,
    description_truncated: bool = False,
    field_metadata: tuple[KnowledgeStudioCatalogFieldMetadata, ...] = (),
    selection_fingerprint: str | None = None,
) -> KnowledgeStudioSourceDataset:
    tags = _human_reference_values(asset.tags, maximum_items=100, maximum_characters=255)
    glossary_terms = _human_reference_values(
        asset.glossary_terms,
        maximum_items=100,
        maximum_characters=255,
    )
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
        tags=tags,
        glossary_terms=glossary_terms,
        description=description,
        description_truncated=description_truncated,
        field_metadata=field_metadata,
        selection_fingerprint=selection_fingerprint,
    )


def _human_reference_values(
    values: tuple[str, ...],
    *,
    maximum_items: int,
    maximum_characters: int,
) -> tuple[str, ...]:
    """Return bounded display names without exposing provider identifiers."""
    names = {
        value.strip()
        for value in values
        if value == value.strip()
        and 1 <= len(value) <= maximum_characters
        and not value.casefold().startswith("urn:")
    }
    return tuple(sorted(names))[:maximum_items]


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


def _reference_names(
    value: object,
    *,
    wrapper: str,
    entity: str,
) -> tuple[tuple[str, ...], bool]:
    document = value if isinstance(value, dict) else {}
    raw_items = document.get(wrapper)
    items = raw_items if isinstance(raw_items, list) else []
    names: set[str] = set()
    clipped = False
    for item in items:
        reference = item.get(entity) if isinstance(item, dict) else None
        if not isinstance(reference, dict):
            clipped = True
            continue
        raw_name = reference.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if (
            1 <= len(name) <= KNOWLEDGE_STUDIO_CATALOG_MAX_FIELD_REFERENCE_CHARACTERS
            and not name.casefold().startswith("urn:")
        ):
            names.add(name)
        else:
            clipped = True
    ordered = tuple(sorted(names))
    return (
        ordered[:KNOWLEDGE_STUDIO_CATALOG_MAX_FIELD_REFERENCES],
        clipped or len(ordered) > KNOWLEDGE_STUDIO_CATALOG_MAX_FIELD_REFERENCES,
    )


def _field_metadata(
    schema_fields: tuple[dict[str, object], ...],
) -> tuple[tuple[KnowledgeStudioCatalogFieldMetadata, ...], bool]:
    values: list[KnowledgeStudioCatalogFieldMetadata] = []
    seen: set[str] = set()
    clipped = False
    for field in schema_fields:
        raw_path = field.get("fieldPath")
        field_path = raw_path.strip() if isinstance(raw_path, str) else ""
        if (
            not field_path
            or raw_path != field_path
            or len(field_path) > KNOWLEDGE_STUDIO_CATALOG_MAX_FIELD_PATH_CHARACTERS
        ):
            clipped = True
            continue
        if field_path in seen:
            continue
        seen.add(field_path)
        raw_description = field.get("description")
        description = raw_description.strip() if isinstance(raw_description, str) else None
        if description == "":
            description = None
        description_was_truncated = bool(field.get("description_truncated", False))
        if (
            description is not None
            and len(description) > KNOWLEDGE_STUDIO_CATALOG_MAX_DESCRIPTION_CHARACTERS
        ):
            description = description[:KNOWLEDGE_STUDIO_CATALOG_MAX_DESCRIPTION_CHARACTERS]
            description_was_truncated = True
        tags, tags_clipped = _reference_names(field.get("globalTags"), wrapper="tags", entity="tag")
        terms, terms_clipped = _reference_names(
            field.get("glossaryTerms"),
            wrapper="terms",
            entity="term",
        )
        values.append(
            KnowledgeStudioCatalogFieldMetadata(
                field_path=field_path,
                field_type=(
                    str(field["type"]).strip()
                    if isinstance(field.get("type"), str) and str(field["type"]).strip()
                    else None
                ),
                native_data_type=(
                    str(field["nativeDataType"]).strip()
                    if isinstance(field.get("nativeDataType"), str)
                    and str(field["nativeDataType"]).strip()
                    else None
                ),
                description=description,
                description_truncated=description_was_truncated,
                tags=tags,
                tags_truncated=(bool(field.get("tags_truncated", False)) or tags_clipped),
                glossary_terms=terms,
                terms_truncated=(bool(field.get("terms_truncated", False)) or terms_clipped),
            )
        )
    return tuple(values), clipped


def _selection_fingerprint(
    *,
    asset: CatalogAssetIndex,
    source_version: str,
    description: str | None,
    description_truncated: bool,
    fields: tuple[KnowledgeStudioCatalogFieldMetadata, ...],
) -> str:
    tags = _human_reference_values(asset.tags, maximum_items=100, maximum_characters=255)
    glossary_terms = _human_reference_values(
        asset.glossary_terms,
        maximum_items=100,
        maximum_characters=255,
    )
    return canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_CATALOG_SELECTION_SNAPSHOT_V1",
            "asset_id": str(asset.asset_id),
            "classification": int(asset.classification),
            "source_version": source_version,
            "projection_source_version": asset.source_version,
            "description": description,
            "description_truncated": description_truncated,
            "tags": list(tags),
            "glossary_terms": list(glossary_terms),
            "field_metadata": [
                {
                    "field_path": field.field_path,
                    "field_type": field.field_type,
                    "native_data_type": field.native_data_type,
                    "description": field.description,
                    "description_truncated": field.description_truncated,
                    "tags": list(field.tags),
                    "tags_truncated": field.tags_truncated,
                    "glossary_terms": list(field.glossary_terms),
                    "terms_truncated": field.terms_truncated,
                }
                for field in fields
            ],
        }
    )


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
        field_metadata, metadata_clipped = _field_metadata(detail.schema_fields)
        field_paths = tuple(item.field_path for item in field_metadata)
        if not field_paths:
            field_paths = detail.index.column_names
            field_metadata = tuple(
                KnowledgeStudioCatalogFieldMetadata(
                    field_path=value,
                    field_type=None,
                    native_data_type=None,
                    description=None,
                    description_truncated=False,
                    tags=(),
                    tags_truncated=False,
                    glossary_terms=(),
                    terms_truncated=False,
                )
                for value in field_paths
            )
        description = detail.index.description
        description_truncated = detail.description_truncated
        if (
            description is not None
            and len(description) > KNOWLEDGE_STUDIO_CATALOG_MAX_DESCRIPTION_CHARACTERS
        ):
            description = description[:KNOWLEDGE_STUDIO_CATALOG_MAX_DESCRIPTION_CHARACTERS]
            description_truncated = True
        return KnowledgeStudioSourceDetail(
            dataset=_dataset(
                detail.index,
                field_paths=field_paths,
                fields_truncated=(
                    detail.schema_fields_truncated
                    or detail.index.column_names_truncated
                    or metadata_clipped
                ),
                source_version=detail.raw_version,
                description=description,
                description_truncated=description_truncated,
                field_metadata=field_metadata,
                selection_fingerprint=_selection_fingerprint(
                    asset=detail.index,
                    source_version=detail.raw_version,
                    description=description,
                    description_truncated=description_truncated,
                    fields=field_metadata,
                ),
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
