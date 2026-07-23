from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID

from datariver.application.catalog_security import (
    catalog_classification_access_document,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import (
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.application.dto import (
    MAX_CATALOG_SCHEMA_FIELDS,
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogFacetBucket,
    CatalogFacets,
    CatalogLineage,
    CatalogLineageEdge,
    CatalogMatchFragment,
    CatalogPage,
    CatalogSuggestion,
    CatalogSuggestions,
    CatalogTreeNode,
    CatalogTreePage,
    CatalogVocabulary,
    DataHubAssetEnrichment,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    Cache,
    CatalogDiscoveryReader,
    CatalogIndexReader,
    CatalogTelemetry,
    CatalogWatermarkReader,
    DataHubGateway,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.classification_policy import CLASSIFICATION_ACCESS_FLOOR_VERSION
from datariver.domain.common import ValidationError

MAX_CATALOG_MATCH_FRAGMENTS = 72
MAX_CATALOG_CACHE_EXTERNAL_URN_CHARACTERS = 4_096
MAX_CATALOG_CACHE_DESCRIPTION_CHARACTERS = 10_000
MAX_CATALOG_CACHE_METADATA_ITEMS = 100
MAX_CATALOG_CACHE_METADATA_CHARACTERS = 1_000
MAX_CATALOG_CACHE_SCHEMA_FIELD_REFERENCES = 20
MAX_CATALOG_CACHE_SCHEMA_FIELD_REFERENCE_CHARACTERS = 240


def _cached_reference_items(
    value: object,
    *,
    entity: str,
    maximum_items: int,
    maximum_characters: int,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ValueError("Invalid cached catalog references.")
    references: list[dict[str, Any]] = []
    for item in value:
        reference = item.get(entity) if isinstance(item, dict) else None
        if not isinstance(reference, dict):
            raise ValueError("Invalid cached catalog reference.")
        normalized: dict[str, str] = {}
        for key in ("urn", "name"):
            candidate = reference.get(key)
            if candidate is not None:
                if not isinstance(candidate, str) or not 1 <= len(candidate) <= maximum_characters:
                    raise ValueError("Invalid cached catalog reference identity.")
                normalized[key] = candidate
        if not normalized:
            raise ValueError("Invalid cached catalog reference identity.")
        references.append({entity: normalized})
    return tuple(references)


def _cached_schema_field(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Invalid cached schema field.")
    field_path = value.get("fieldPath")
    if not isinstance(field_path, str) or not 1 <= len(field_path) <= 4_096:
        raise ValueError("Invalid cached schema field path.")
    field: dict[str, Any] = {"fieldPath": field_path}
    limits = {
        "type": 500,
        "nativeDataType": 500,
        "label": 500,
        "description": 10_000,
    }
    for key, maximum in limits.items():
        candidate = value.get(key)
        if candidate is not None:
            if not isinstance(candidate, str) or len(candidate) > maximum:
                raise ValueError("Invalid cached schema field value.")
            field[key] = candidate
            flag = value.get(f"{key}_truncated", False)
            if not isinstance(flag, bool):
                raise ValueError("Invalid cached schema field truncation evidence.")
            field[f"{key}_truncated"] = flag
    for key, wrapper, entity, flag in (
        ("globalTags", "tags", "tag", "tags_truncated"),
        ("glossaryTerms", "terms", "term", "terms_truncated"),
    ):
        document = value.get(key)
        items = document.get(wrapper) if isinstance(document, dict) else None
        field[key] = {
            wrapper: list(
                _cached_reference_items(
                    items if items is not None else [],
                    entity=entity,
                    maximum_items=MAX_CATALOG_CACHE_SCHEMA_FIELD_REFERENCES,
                    maximum_characters=MAX_CATALOG_CACHE_SCHEMA_FIELD_REFERENCE_CHARACTERS,
                )
            )
        }
        raw_flag = value.get(flag, False)
        if not isinstance(raw_flag, bool):
            raise ValueError("Invalid cached schema field truncation evidence.")
        field[flag] = raw_flag
    return field


class CatalogService:
    def __init__(
        self,
        *,
        index: CatalogIndexReader,
        discovery: CatalogDiscoveryReader,
        watermark: CatalogWatermarkReader,
        datahub: DataHubGateway,
        cache: Cache,
        authorization: AuthorizationService,
        detail_cache_ttl_seconds: int,
        stale_detail_ttl_seconds: int,
        search_cache_ttl_seconds: int,
        minimum_query_length: int,
        policy_version: str,
        classification_access: ClassificationAccessResolver | None = None,
        telemetry: CatalogTelemetry | None = None,
    ) -> None:
        self._index = index
        self._discovery = discovery
        self._watermark = watermark
        self._datahub = datahub
        self._cache = cache
        self._authorization = authorization
        self._detail_cache_ttl_seconds = detail_cache_ttl_seconds
        self._stale_detail_ttl_seconds = stale_detail_ttl_seconds
        self._search_cache_ttl_seconds = search_cache_ttl_seconds
        self._minimum_query_length = minimum_query_length
        self._policy_version = policy_version
        self._classification_access = classification_access
        self._telemetry = telemetry

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogPage:
        if not 1 <= limit <= 100:
            raise ValueError("Catalog page limit must be between 1 and 100.")
        normalized_query, access, watermark = await self._prepare_discovery(
            subject=subject,
            query=query,
            environment=environment,
            request_id=request_id,
        )
        cursor_context = self._search_cursor_context(
            subject=subject,
            query=normalized_query,
            filters=filters,
            limit=limit,
            watermark=watermark,
            access=access,
        )
        repository_cursor = self._unwrap_search_cursor(cursor, expected_context=cursor_context)
        cache_key = self._search_cache_key(
            subject=subject,
            query=normalized_query,
            filters=filters,
            cursor=repository_cursor,
            limit=limit,
            watermark=watermark,
            access=access,
        )
        cache_ttl = self._bounded_cache_ttl(
            configured_ttl=self._search_cache_ttl_seconds,
            access=access,
            now=environment.requested_at,
        )
        if cache_ttl > 0:
            try:
                cached = await self._cache.get_json(cache_key)
            except Exception:
                self._cache_access(cache="search", outcome="error")
            else:
                cached_page = self._cached_page(
                    cached,
                    workspace_id=subject.workspace_id,
                    limit=limit,
                )
                if cached_page is not None:
                    self._cache_access(cache="search", outcome="hit")
                    return cached_page
                self._cache_access(cache="search", outcome="miss")
        page = await self._index.search(
            subject=subject,
            access=access,
            query=normalized_query,
            filters=filters,
            cursor=repository_cursor,
            limit=limit,
        )
        page = replace(
            page,
            next_cursor=(
                self._wrap_search_cursor(page.next_cursor, context=cursor_context)
                if page.next_cursor
                else None
            ),
            projection_version=watermark,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )
        if cache_ttl > 0:
            try:
                await self._cache.set_json(
                    cache_key,
                    self._page_document(page),
                    ttl_seconds=cache_ttl,
                )
            except Exception:
                self._cache_access(cache="search_write", outcome="error")
                return page
            self._cache_access(cache="search_write", outcome="success")
        return page

    async def facets(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        filters: dict[str, Any],
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogFacets:
        if not 1 <= limit <= 100:
            raise ValueError("Catalog facet limit must be between 1 and 100.")
        normalized_query, access, watermark = await self._prepare_discovery(
            subject=subject,
            query=query,
            environment=environment,
            request_id=request_id,
        )
        cache_key = self._discovery_cache_key(
            surface="facets",
            subject=subject,
            query=normalized_query,
            filters=filters,
            limit=limit,
            watermark=watermark,
            access=access,
        )
        cache_ttl = self._bounded_cache_ttl(
            configured_ttl=self._search_cache_ttl_seconds,
            access=access,
            now=environment.requested_at,
        )
        if cache_ttl > 0:
            try:
                cached = await self._cache.get_json(cache_key)
            except Exception:
                self._cache_access(cache="facets", outcome="error")
            else:
                cached_facets = self._cached_facets(
                    cached,
                    workspace_id=subject.workspace_id,
                    limit=limit,
                )
                if cached_facets is not None:
                    self._cache_access(cache="facets", outcome="hit")
                    return cached_facets
                self._cache_access(cache="facets", outcome="miss")
        facets = await self._discovery.facets(
            subject=subject,
            access=access,
            query=normalized_query,
            filters=filters,
            limit=limit,
        )
        facets = replace(
            facets,
            projection_version=watermark,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )
        if cache_ttl > 0:
            try:
                await self._cache.set_json(
                    cache_key,
                    self._facets_document(facets, workspace_id=subject.workspace_id),
                    ttl_seconds=cache_ttl,
                )
            except Exception:
                self._cache_access(cache="facets_write", outcome="error")
            else:
                self._cache_access(cache="facets_write", outcome="success")
        return facets

    async def suggestions(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogSuggestions:
        if not 1 <= limit <= 20:
            raise ValueError("Catalog suggestion limit must be between 1 and 20.")
        normalized_query, access, watermark = await self._prepare_discovery(
            subject=subject,
            query=query,
            environment=environment,
            request_id=request_id,
            require_query=True,
        )
        cache_key = self._discovery_cache_key(
            surface="suggestions",
            subject=subject,
            query=normalized_query,
            filters={},
            limit=limit,
            watermark=watermark,
            access=access,
        )
        cache_ttl = self._bounded_cache_ttl(
            configured_ttl=self._search_cache_ttl_seconds,
            access=access,
            now=environment.requested_at,
        )
        if cache_ttl > 0:
            try:
                cached = await self._cache.get_json(cache_key)
            except Exception:
                self._cache_access(cache="suggestions", outcome="error")
            else:
                cached_suggestions = self._cached_suggestions(
                    cached,
                    workspace_id=subject.workspace_id,
                    limit=limit,
                )
                if cached_suggestions is not None:
                    self._cache_access(cache="suggestions", outcome="hit")
                    return cached_suggestions
                self._cache_access(cache="suggestions", outcome="miss")
        suggestions = await self._discovery.suggestions(
            subject=subject,
            access=access,
            query=normalized_query,
            limit=limit,
        )
        suggestions = replace(
            suggestions,
            projection_version=watermark,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )
        if cache_ttl > 0:
            try:
                await self._cache.set_json(
                    cache_key,
                    self._suggestions_document(
                        suggestions,
                        workspace_id=subject.workspace_id,
                    ),
                    ttl_seconds=cache_ttl,
                )
            except Exception:
                self._cache_access(cache="suggestions_write", outcome="error")
            else:
                self._cache_access(cache="suggestions_write", outcome="success")
        return suggestions

    async def tree_nodes(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        parent_kind: str,
        platform: str | None,
        database_name: str | None,
        schema_name: str | None,
        cursor: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogTreePage:
        if not 1 <= limit <= 100:
            raise ValueError("Catalog tree page limit must be between 1 and 100.")
        normalized_query, access, watermark = await self._prepare_discovery(
            subject=subject,
            query=query,
            environment=environment,
            request_id=request_id,
        )
        tree_context = {
            "parent_kind": parent_kind,
            "platform": platform,
            "database_name": database_name,
            "schema_name": schema_name,
        }
        cursor_context = self._search_cursor_context(
            subject=subject,
            query=normalized_query,
            filters=tree_context,
            limit=limit,
            watermark=watermark,
            access=access,
        )
        repository_cursor = self._unwrap_search_cursor(cursor, expected_context=cursor_context)
        cache_key = self._discovery_cache_key(
            surface="tree",
            subject=subject,
            query=normalized_query,
            filters={**tree_context, "cursor": repository_cursor},
            limit=limit,
            watermark=watermark,
            access=access,
        )
        cache_ttl = self._bounded_cache_ttl(
            configured_ttl=self._search_cache_ttl_seconds,
            access=access,
            now=environment.requested_at,
        )
        if cache_ttl > 0:
            try:
                cached = await self._cache.get_json(cache_key)
            except Exception:
                self._cache_access(cache="tree", outcome="error")
            else:
                cached_page = self._cached_tree_page(
                    cached,
                    workspace_id=subject.workspace_id,
                    limit=limit,
                )
                if cached_page is not None:
                    self._cache_access(cache="tree", outcome="hit")
                    return cached_page
                self._cache_access(cache="tree", outcome="miss")
        page = await self._discovery.tree_nodes(
            subject=subject,
            access=access,
            query=normalized_query,
            parent_kind=parent_kind,
            platform=platform,
            database_name=database_name,
            schema_name=schema_name,
            cursor=repository_cursor,
            limit=limit,
        )
        page = replace(
            page,
            next_cursor=(
                self._wrap_search_cursor(page.next_cursor, context=cursor_context)
                if page.next_cursor
                else None
            ),
            projection_version=watermark,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )
        if cache_ttl > 0:
            try:
                await self._cache.set_json(
                    cache_key,
                    self._tree_page_document(page, workspace_id=subject.workspace_id),
                    ttl_seconds=cache_ttl,
                )
            except Exception:
                self._cache_access(cache="tree_write", outcome="error")
            else:
                self._cache_access(cache="tree_write", outcome="success")
        return page

    async def vocabulary(
        self,
        *,
        subject: SubjectAttributes,
        kind: str,
        query: str,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogVocabulary:
        if kind not in {"TAG", "TERM", "DOMAIN"} or not 1 <= limit <= 50:
            raise ValueError("Catalog vocabulary request is invalid.")
        normalized_query, access, watermark = await self._prepare_discovery(
            subject=subject,
            query=query,
            environment=environment,
            request_id=request_id,
            minimum_query_length=1,
        )
        vocabulary = await self._discovery.vocabulary(
            subject=subject,
            access=access,
            kind=kind,
            query=normalized_query,
            limit=limit,
        )
        # Discovery values must stay inside the authorization-pruned workspace
        # projection. DataHub tags and terms are globally addressable and its
        # provider search contract has no workspace/classification predicate,
        # so unioning provider-only names here could disclose cross-tenant
        # vocabulary. Provider refs are resolved only in governed server-side
        # mutation workflows.
        return replace(
            vocabulary,
            projection_version=watermark,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )

    async def get_asset(
        self,
        *,
        subject: SubjectAttributes,
        asset_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogAssetDetail | None:
        access = await self._resolve_classification_access(
            subject=subject,
            now=environment.requested_at,
            request_id=request_id,
        )
        authorized = await self._index.get_authorized_asset(
            subject=subject,
            access=access,
            asset_id=asset_id,
        )
        if authorized is None:
            return None
        if not access.admin_quarantine_review:
            await self._authorization.authorize(
                subject=subject,
                resource=ResourceAttributes(
                    resource_id=authorized.index.asset_id,
                    workspace_id=authorized.index.workspace_id,
                    resource_type="catalog_asset",
                    owner_department_id=authorized.index.owner_department_id,
                    system_id=authorized.index.system_id,
                    domain_id=authorized.index.domain_id,
                    classification=authorized.index.classification,
                    lifecycle=authorized.index.lifecycle,
                ),
                action=Action.CATALOG_READ,
                environment=environment,
                request_id=request_id,
            )
        permission_scope_hash = self._permission_scope_hash(subject)
        key_document = {
            "workspace": str(subject.workspace_id),
            "asset": str(asset_id),
            "scope": permission_scope_hash,
            "policy": self._policy_version,
            "classification_policy_floor": CLASSIFICATION_ACCESS_FLOOR_VERSION,
            "classification_access": self._classification_access_document(access),
            "source": authorized.index.source_version,
        }
        key_hash = hashlib.sha256(json.dumps(key_document, sort_keys=True).encode()).hexdigest()
        fresh_cache_key = "catalog:asset:fresh:" + key_hash
        stale_cache_key = "catalog:asset:stale:" + key_hash
        try:
            cached = await self._cache.get_json(fresh_cache_key)
        except Exception:
            self._cache_access(cache="detail_fresh", outcome="error")
        else:
            cached_enrichment = self._cached_enrichment(cached)
            if cached_enrichment is not None:
                self._cache_access(cache="detail_fresh", outcome="hit")
                self._detail_source(source="fresh_cache")
                return self._detail(authorized, cached_enrichment)
            self._cache_access(cache="detail_fresh", outcome="miss")
        try:
            remote_enrichment = await self._datahub.get_asset(authorized.index.external_urn)
        except ExternalDependencyError as error:
            if not error.details.get("retryable"):
                raise
            try:
                stale_cached = await self._cache.get_json(stale_cache_key)
            except Exception:
                self._cache_access(cache="detail_stale", outcome="error")
            else:
                stale_enrichment = self._cached_enrichment(stale_cached)
                if stale_enrichment is not None:
                    self._cache_access(cache="detail_stale", outcome="hit")
                    self._detail_source(source="stale_cache")
                    fresh_until = self._cached_fresh_until(stale_cached)
                    stale_at = (
                        min(fresh_until, datetime.now(UTC))
                        if fresh_until is not None
                        else stale_enrichment.observed_at
                    )
                    return self._detail(authorized, stale_enrichment, stale_at=stale_at)
                self._cache_access(cache="detail_stale", outcome="miss")
            if datetime.now(UTC) - authorized.index.observed_at <= timedelta(
                seconds=self._stale_detail_ttl_seconds
            ):
                self._detail_source(source="local_projection")
                return CatalogAssetDetail(
                    index=authorized.index,
                    ownership=authorized.ownership,
                    glossary_terms=authorized.glossary_terms,
                    tags=authorized.tags,
                    schema_fields=authorized.schema_fields,
                    quality=authorized.quality,
                    raw_version=authorized.raw_version,
                    observed_at=authorized.observed_at,
                    stale_at=authorized.index.observed_at,
                    schema_fields_total=authorized.schema_fields_total,
                    schema_fields_truncated=authorized.schema_fields_truncated,
                    schema_fields_total_exact=authorized.schema_fields_total_exact,
                    glossary_terms_truncated=authorized.index.glossary_terms_truncated,
                    tags_truncated=authorized.index.tags_truncated,
                    description_truncated=authorized.index.description_truncated,
                )
            raise
        self._detail_source(source="datahub")
        detail = self._detail(authorized, remote_enrichment)
        fresh_until = datetime.now(UTC) + timedelta(seconds=self._detail_cache_ttl_seconds)
        cache_document = self._enrichment_document(remote_enrichment, fresh_until=fresh_until)
        try:
            await self._cache.set_json(
                fresh_cache_key,
                cache_document,
                ttl_seconds=self._detail_cache_ttl_seconds,
            )
            await self._cache.set_json(
                stale_cache_key,
                cache_document,
                ttl_seconds=self._stale_detail_ttl_seconds,
            )
        except Exception:
            self._cache_access(cache="detail_write", outcome="error")
            return detail
        self._cache_access(cache="detail_write", outcome="success")
        return detail

    async def lineage(
        self,
        *,
        subject: SubjectAttributes,
        asset_id: UUID,
        direction: str,
        depth: int,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogLineage | None:
        if direction not in {"UPSTREAM", "DOWNSTREAM", "BOTH"}:
            raise ValidationError("Unsupported lineage direction.")
        if not 1 <= depth <= 3:
            raise ValidationError("Lineage depth must be between one and three.")
        access = await self._resolve_classification_access(
            subject=subject,
            now=environment.requested_at,
            request_id=request_id,
        )
        center = await self._index.get_authorized_asset(
            subject=subject, access=access, asset_id=asset_id
        )
        if center is None:
            return None
        # The audited, read-only quarantine-review scope already allows this
        # administrator to retrieve the selected catalog detail.  Lineage must
        # use that same server-side scope; otherwise its extra generic policy
        # check produces a local 403 before DataHub is contacted.  All normal
        # user requests remain subject to the catalog-read authorization check.
        if not access.admin_quarantine_review:
            await self._authorization.authorize(
                subject=subject,
                resource=ResourceAttributes(
                    resource_id=center.index.asset_id,
                    workspace_id=center.index.workspace_id,
                    resource_type="catalog_lineage",
                    owner_department_id=center.index.owner_department_id,
                    system_id=center.index.system_id,
                    domain_id=center.index.domain_id,
                    classification=center.index.classification,
                    lifecycle=center.index.lifecycle,
                ),
                action=Action.CATALOG_READ,
                environment=environment,
                request_id=request_id,
            )
        directions = ("UPSTREAM", "DOWNSTREAM") if direction == "BOTH" else (direction,)
        remote_pages = await asyncio.gather(
            *(
                self._datahub.get_lineage(
                    external_urn=center.index.external_urn,
                    direction=item,
                    depth=depth,
                )
                for item in directions
            )
        )
        candidate_urns = {center.index.external_urn}
        for page in remote_pages:
            for item in page.items:
                candidate_urns.add(item.external_urn)
                candidate_urns.update(urn for path in item.paths for urn in path)
        authorized = await self._index.get_authorized_assets_by_external_urns(
            subject=subject,
            access=access,
            external_urns=tuple(candidate_urns),
        )
        by_urn = {item.external_urn: item for item in authorized}
        by_urn[center.index.external_urn] = center.index
        visible_urns = {center.index.external_urn}
        edge_ids: set[tuple[UUID, UUID]] = set()
        truncated = any(page.partial or page.total > len(page.items) for page in remote_pages)
        for remote_direction, page in zip(directions, remote_pages, strict=True):
            for item in page.items:
                truncated = truncated or item.truncated_children
                if item.external_urn in by_urn:
                    visible_urns.add(item.external_urn)
                paths = item.paths
                if not paths and item.degree == 1:
                    paths = ((center.index.external_urn, item.external_urn),)
                for path in paths:
                    oriented = self._oriented_lineage_path(
                        path=path,
                        center_urn=center.index.external_urn,
                        direction=remote_direction,
                    )
                    if oriented is None:
                        truncated = True
                        continue
                    for source_urn, target_urn in pairwise(oriented):
                        source = by_urn.get(source_urn)
                        target = by_urn.get(target_urn)
                        if source is None or target is None:
                            truncated = True
                            continue
                        if source.asset_id == target.asset_id:
                            continue
                        visible_urns.update((source_urn, target_urn))
                        edge_ids.add((source.asset_id, target.asset_id))
        nodes = tuple(
            sorted(
                (by_urn[urn] for urn in visible_urns if urn in by_urn),
                key=lambda item: (
                    item.asset_id != center.index.asset_id,
                    item.name.casefold(),
                    str(item.asset_id),
                ),
            )
        )
        watermark = await self._watermark.get_search_watermark(workspace_id=subject.workspace_id)
        return CatalogLineage(
            center_asset_id=center.index.asset_id,
            nodes=nodes,
            edges=tuple(
                CatalogLineageEdge(source_asset_id=source, target_asset_id=target)
                for source, target in sorted(
                    edge_ids, key=lambda edge: (str(edge[0]), str(edge[1]))
                )
            ),
            direction=direction,
            depth=depth,
            truncated=truncated,
            observed_at=datetime.now(UTC),
            projection_version=watermark,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )

    @staticmethod
    def _oriented_lineage_path(
        *, path: tuple[str, ...], center_urn: str, direction: str
    ) -> tuple[str, ...] | None:
        if len(path) < 2 or center_urn not in path:
            return None
        if path[0] == center_urn:
            return path if direction == "DOWNSTREAM" else tuple(reversed(path))
        if path[-1] == center_urn:
            return tuple(reversed(path)) if direction == "DOWNSTREAM" else path
        return None

    def _cache_access(self, *, cache: str, outcome: str) -> None:
        if self._telemetry is not None:
            self._telemetry.catalog_cache_access(cache=cache, outcome=outcome)

    def _detail_source(self, *, source: str) -> None:
        if self._telemetry is not None:
            self._telemetry.catalog_detail_source(source=source)

    def _permission_scope_hash(self, subject: SubjectAttributes) -> str:
        return catalog_permission_scope_hash(subject)

    def _search_cache_key(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
        watermark: int,
        access: ClassificationAccessSnapshot,
    ) -> str:
        key_document = {
            "workspace": str(subject.workspace_id),
            "scope": self._permission_scope_hash(subject),
            "policy": self._policy_version,
            "classification_policy_floor": CLASSIFICATION_ACCESS_FLOOR_VERSION,
            "classification_access": self._classification_access_document(access),
            "projection_version": watermark,
            "query": query,
            "filters": filters,
            "cursor": cursor,
            "limit": limit,
        }
        return (
            "catalog:search:"
            + hashlib.sha256(
                json.dumps(key_document, sort_keys=True, default=str).encode()
            ).hexdigest()
        )

    def _discovery_cache_key(
        self,
        *,
        surface: str,
        subject: SubjectAttributes,
        query: str,
        filters: dict[str, Any],
        limit: int,
        watermark: int,
        access: ClassificationAccessSnapshot,
    ) -> str:
        key_document = {
            "workspace": str(subject.workspace_id),
            "scope": self._permission_scope_hash(subject),
            "policy": self._policy_version,
            "classification_policy_floor": CLASSIFICATION_ACCESS_FLOOR_VERSION,
            "classification_access": self._classification_access_document(access),
            "projection_version": watermark,
            "query": query,
            "filters": filters,
            "limit": limit,
        }
        return (
            f"catalog:{surface}:"
            + hashlib.sha256(
                json.dumps(key_document, sort_keys=True, default=str).encode()
            ).hexdigest()
        )

    def _search_cursor_context(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        filters: dict[str, Any],
        limit: int,
        watermark: int,
        access: ClassificationAccessSnapshot,
    ) -> str:
        document = {
            "workspace": str(subject.workspace_id),
            "scope": self._permission_scope_hash(subject),
            "policy": self._policy_version,
            "classification_policy_floor": CLASSIFICATION_ACCESS_FLOOR_VERSION,
            "classification_access": self._classification_access_document(access),
            "projection_version": watermark,
            "query": query,
            "filters": filters,
            "limit": limit,
        }
        return hashlib.sha256(
            json.dumps(document, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _wrap_search_cursor(cursor: str, *, context: str) -> str:
        payload = json.dumps(
            {"v": 1, "context": context, "cursor": cursor},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _unwrap_search_cursor(cursor: str | None, *, expected_context: str) -> str | None:
        if cursor is None:
            return None
        try:
            payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            document = json.loads(payload)
            if (
                not isinstance(document, dict)
                or document.get("v") != 1
                or document.get("context") != expected_context
                or not isinstance(document.get("cursor"), str)
                or not document["cursor"]
            ):
                raise ValueError
            return str(document["cursor"])
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as error:
            raise ValidationError(
                "The catalog cursor is stale or does not match this request."
            ) from error

    async def _prepare_discovery(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        environment: EnvironmentAttributes,
        request_id: str,
        require_query: bool = False,
        minimum_query_length: int | None = None,
    ) -> tuple[str, ClassificationAccessSnapshot, int]:
        normalized_query = unicodedata.normalize("NFKC", query).strip()
        if require_query and not normalized_query:
            raise ValidationError("The catalog query is required.")
        required_length = (
            self._minimum_query_length if minimum_query_length is None else minimum_query_length
        )
        if required_length < 1:
            raise ValueError("The catalog query minimum must be positive.")
        if normalized_query and len(normalized_query) < required_length:
            raise ValidationError(
                "The catalog query is shorter than the configured minimum.",
                details={"minimum_query_length": required_length},
            )
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=subject.workspace_id,
                workspace_id=subject.workspace_id,
                resource_type="catalog",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.CATALOG_SEARCH,
            environment=environment,
            request_id=request_id,
        )
        access = await self._resolve_classification_access(
            subject=subject,
            now=environment.requested_at,
            request_id=request_id,
        )
        watermark = await self._watermark.get_search_watermark(workspace_id=subject.workspace_id)
        return normalized_query, access, watermark

    async def _resolve_classification_access(
        self,
        *,
        subject: SubjectAttributes,
        now: datetime,
        request_id: str,
    ) -> ClassificationAccessSnapshot:
        if self._classification_access is None:
            access = static_classification_access_floor()
        else:
            access = await self._classification_access.resolve(
                workspace_id=subject.workspace_id,
                subject_id=subject.subject_id,
                now=now,
            )
        if "security-administrators" not in subject.groups:
            return access
        if await self._authorization.can_review_quarantined_catalog(
            subject=subject,
            environment=EnvironmentAttributes(requested_at=now),
            request_id=request_id,
        ):
            return replace(access, admin_quarantine_review=True)
        return access

    @staticmethod
    def _classification_access_document(
        access: ClassificationAccessSnapshot,
    ) -> dict[str, Any]:
        return catalog_classification_access_document(access)

    @staticmethod
    def _bounded_cache_ttl(
        *,
        configured_ttl: int,
        access: ClassificationAccessSnapshot,
        now: datetime,
    ) -> int:
        boundary = access.nearest_validity_boundary
        if boundary is None:
            return configured_ttl
        remaining_seconds = int((boundary - now).total_seconds())
        return max(0, min(configured_ttl, remaining_seconds))

    @staticmethod
    def _page_document(page: CatalogPage) -> dict[str, Any]:
        return {
            "schema": 8,
            "items": [CatalogService._asset_index_document(item) for item in page.items],
            "next_cursor": page.next_cursor,
            "observed_at": page.observed_at.isoformat(),
            "total": page.total,
            "total_exact": page.total_exact,
            "stale_at": page.stale_at.isoformat() if page.stale_at else None,
            "projection_version": page.projection_version,
            "policy_version": page.policy_version,
            "classification_policy_version": page.classification_policy_version,
            "authorization_generation": page.authorization_generation,
        }

    @staticmethod
    def _cached_page(
        value: object,
        *,
        workspace_id: UUID,
        limit: int,
    ) -> CatalogPage | None:
        if not isinstance(value, dict) or value.get("schema") != 8:
            return None
        try:
            raw_items = value["items"]
            if not isinstance(raw_items, list) or len(raw_items) > limit:
                return None
            items = tuple(CatalogService._asset_index_from_document(item) for item in raw_items)
            if any(item.workspace_id != workspace_id for item in items):
                return None
            total = int(value["total"])
            if total < len(items):
                return None
            total_exact = value.get("total_exact")
            if not isinstance(total_exact, bool):
                return None
            raw_cursor = value.get("next_cursor")
            if raw_cursor is not None and (
                not isinstance(raw_cursor, str) or not 1 <= len(raw_cursor) <= 4_096
            ):
                return None
            if total_exact and raw_cursor is not None:
                return None
            stale_raw = value.get("stale_at")
            return CatalogPage(
                items=items,
                next_cursor=raw_cursor,
                observed_at=datetime.fromisoformat(str(value["observed_at"])),
                total=total,
                total_exact=total_exact,
                stale_at=datetime.fromisoformat(str(stale_raw)) if stale_raw else None,
                projection_version=int(value["projection_version"]),
                policy_version=str(value["policy_version"]),
                classification_policy_version=(
                    int(value["classification_policy_version"])
                    if value.get("classification_policy_version") is not None
                    else None
                ),
                authorization_generation=(
                    int(value["authorization_generation"])
                    if value.get("authorization_generation") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _tree_page_document(
        page: CatalogTreePage,
        *,
        workspace_id: UUID,
    ) -> dict[str, Any]:
        return {
            "schema": 3,
            "workspace_id": str(workspace_id),
            "items": [
                {
                    "node_id": str(item.node_id),
                    "kind": item.kind,
                    "label": item.label,
                    "asset_count": item.asset_count,
                    "has_children": item.has_children,
                    "platform": item.platform,
                    "database_name": item.database_name,
                    "schema_name": item.schema_name,
                    "asset": (
                        CatalogService._asset_index_document(item.asset)
                        if item.asset is not None
                        else None
                    ),
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
            "observed_at": page.observed_at.isoformat() if page.observed_at else None,
            "projection_version": page.projection_version,
            "policy_version": page.policy_version,
            "classification_policy_version": page.classification_policy_version,
            "authorization_generation": page.authorization_generation,
        }

    @staticmethod
    def _cached_tree_page(
        value: object,
        *,
        workspace_id: UUID,
        limit: int,
    ) -> CatalogTreePage | None:
        if (
            not isinstance(value, dict)
            or value.get("schema") != 3
            or value.get("workspace_id") != str(workspace_id)
            or not 1 <= limit <= 100
        ):
            return None
        try:
            raw_items = value.get("items")
            if not isinstance(raw_items, list) or len(raw_items) > limit:
                return None
            nodes: list[CatalogTreeNode] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    return None
                kind = item.get("kind")
                label = item.get("label")
                node_id = item.get("node_id")
                asset_count = item.get("asset_count")
                has_children = item.get("has_children")
                optional_fields = (
                    ("platform", 100),
                    ("database_name", 255),
                    ("schema_name", 255),
                )
                if (
                    kind not in {"PLATFORM", "DATABASE", "SCHEMA", "ASSET"}
                    or not isinstance(node_id, str)
                    or not isinstance(label, str)
                    or not 1 <= len(label) <= 500
                    or isinstance(asset_count, bool)
                    or not isinstance(asset_count, int)
                    or asset_count < 0
                    or not isinstance(has_children, bool)
                ):
                    return None
                for key, maximum_characters in optional_fields:
                    candidate = item.get(key)
                    if candidate is not None and (
                        not isinstance(candidate, str)
                        or not 1 <= len(candidate) <= maximum_characters
                    ):
                        return None
                asset = (
                    CatalogService._asset_index_from_document(item["asset"])
                    if item.get("asset") is not None
                    else None
                )
                if (
                    (kind == "ASSET" and asset is None)
                    or (kind != "ASSET" and asset is not None)
                    or (asset is not None and asset.workspace_id != workspace_id)
                ):
                    return None
                nodes.append(
                    CatalogTreeNode(
                        node_id=UUID(node_id),
                        kind=kind,
                        label=label,
                        asset_count=asset_count,
                        has_children=has_children,
                        platform=item.get("platform"),
                        database_name=item.get("database_name"),
                        schema_name=item.get("schema_name"),
                        asset=asset,
                    )
                )
            raw_cursor = value.get("next_cursor")
            if raw_cursor is not None and (
                not isinstance(raw_cursor, str) or not 1 <= len(raw_cursor) <= 4_096
            ):
                return None
            return CatalogTreePage(
                items=tuple(nodes),
                next_cursor=raw_cursor,
                observed_at=(
                    datetime.fromisoformat(str(value["observed_at"]))
                    if value.get("observed_at")
                    else None
                ),
                projection_version=int(value["projection_version"]),
                policy_version=str(value["policy_version"]),
                classification_policy_version=(
                    int(value["classification_policy_version"])
                    if value.get("classification_policy_version") is not None
                    else None
                ),
                authorization_generation=(
                    int(value["authorization_generation"])
                    if value.get("authorization_generation") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _asset_index_document(item: CatalogAssetIndex) -> dict[str, Any]:
        return {
            "asset_id": str(item.asset_id),
            "workspace_id": str(item.workspace_id),
            "external_urn": item.external_urn,
            "asset_type": item.asset_type,
            "name": item.name,
            "description": item.description,
            "platform": item.platform,
            "database_name": item.database_name,
            "schema_name": item.schema_name,
            "domain_id": str(item.domain_id) if item.domain_id else None,
            "system_id": str(item.system_id) if item.system_id else None,
            "owner_department_id": (
                str(item.owner_department_id) if item.owner_department_id else None
            ),
            "classification": int(item.classification),
            "lifecycle": item.lifecycle,
            "source_version": item.source_version,
            "observed_at": item.observed_at.isoformat(),
            "owner": item.owner,
            "domain": item.domain,
            "tags": list(item.tags),
            "glossary_terms": list(item.glossary_terms),
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "matches": [
                {
                    "field": fragment.field,
                    "text": fragment.text,
                    "matched_terms": list(fragment.matched_terms),
                }
                for fragment in item.matches
            ],
            "description_truncated": item.description_truncated,
            "tags_truncated": item.tags_truncated,
            "glossary_terms_truncated": item.glossary_terms_truncated,
            "column_names_truncated": item.column_names_truncated,
        }

    @staticmethod
    def _match_fragment_from_document(item: object) -> CatalogMatchFragment:
        if not isinstance(item, dict):
            raise ValueError("Invalid cached catalog match.")
        field = item.get("field")
        text = item.get("text")
        matched_terms = item.get("matched_terms")
        if (
            field not in {"NAME", "DESCRIPTION", "SCHEMA", "COLUMN", "TAG", "TERM"}
            or not isinstance(text, str)
            or not 1 <= len(text) <= 240
            or not isinstance(matched_terms, list)
            or not 1 <= len(matched_terms) <= 12
            or any(
                not isinstance(term, str)
                or not 1 <= len(term) <= 120
                or term.casefold() not in text.casefold()
                for term in matched_terms
            )
        ):
            raise ValueError("Invalid cached catalog match.")
        return CatalogMatchFragment(
            field=field,
            text=text,
            matched_terms=tuple(matched_terms),
        )

    @staticmethod
    def _asset_index_from_document(item: object) -> CatalogAssetIndex:
        if not isinstance(item, dict):
            raise ValueError("Invalid cached catalog asset.")
        raw_matches = item.get("matches", [])
        if not isinstance(raw_matches, list) or len(raw_matches) > MAX_CATALOG_MATCH_FRAGMENTS:
            raise ValueError("Invalid cached catalog matches.")
        external_urn = item.get("external_urn")
        description = item.get("description")
        raw_tags = item.get("tags", [])
        raw_terms = item.get("glossary_terms", [])
        truncation_values = tuple(
            item.get(key)
            for key in (
                "description_truncated",
                "tags_truncated",
                "glossary_terms_truncated",
                "column_names_truncated",
            )
        )
        bounded_fields = (
            ("asset_type", 100, False),
            ("name", 500, False),
            ("platform", 100, True),
            ("database_name", 255, True),
            ("schema_name", 255, True),
            ("owner", 1_000, True),
            ("domain", 1_000, True),
            ("lifecycle", 50, False),
            ("source_version", 255, False),
        )
        for key, maximum_characters, nullable in bounded_fields:
            candidate = item.get(key)
            if candidate is None and nullable:
                continue
            if not isinstance(candidate, str) or not 1 <= len(candidate) <= maximum_characters:
                raise ValueError("Invalid cached catalog asset scalar.")
        for key in ("asset_id", "workspace_id"):
            if not isinstance(item.get(key), str):
                raise ValueError("Invalid cached catalog asset identity.")
        for key in ("domain_id", "system_id", "owner_department_id"):
            if item.get(key) is not None and not isinstance(item.get(key), str):
                raise ValueError("Invalid cached catalog scope identity.")
        classification = item.get("classification")
        observed_at = item.get("observed_at")
        created_at = item.get("created_at")
        if (
            not isinstance(external_urn, str)
            or not 1 <= len(external_urn) <= MAX_CATALOG_CACHE_EXTERNAL_URN_CHARACTERS
            or (
                description is not None
                and (
                    not isinstance(description, str)
                    or len(description) > MAX_CATALOG_CACHE_DESCRIPTION_CHARACTERS
                )
            )
            or not isinstance(raw_tags, list)
            or len(raw_tags) > MAX_CATALOG_CACHE_METADATA_ITEMS
            or any(
                not isinstance(value, str) or len(value) > MAX_CATALOG_CACHE_METADATA_CHARACTERS
                for value in raw_tags
            )
            or not isinstance(raw_terms, list)
            or len(raw_terms) > MAX_CATALOG_CACHE_METADATA_ITEMS
            or any(
                not isinstance(value, str) or len(value) > MAX_CATALOG_CACHE_METADATA_CHARACTERS
                for value in raw_terms
            )
            or not all(isinstance(value, bool) for value in truncation_values)
            or isinstance(classification, bool)
            or not isinstance(classification, int)
            or not isinstance(observed_at, str)
            or not 1 <= len(observed_at) <= 64
            or (
                created_at is not None
                and (not isinstance(created_at, str) or not 1 <= len(created_at) <= 64)
            )
        ):
            raise ValueError("Invalid cached catalog asset bounds.")
        return CatalogAssetIndex(
            asset_id=UUID(item["asset_id"]),
            workspace_id=UUID(item["workspace_id"]),
            external_urn=external_urn,
            asset_type=item["asset_type"],
            name=item["name"],
            description=description,
            platform=item.get("platform"),
            database_name=item.get("database_name"),
            schema_name=item.get("schema_name"),
            domain_id=UUID(item["domain_id"]) if item.get("domain_id") else None,
            system_id=UUID(item["system_id"]) if item.get("system_id") else None,
            owner_department_id=(
                UUID(item["owner_department_id"]) if item.get("owner_department_id") else None
            ),
            classification=Classification(classification),
            lifecycle=item["lifecycle"],
            source_version=item["source_version"],
            observed_at=datetime.fromisoformat(observed_at),
            owner=item.get("owner"),
            domain=item.get("domain"),
            tags=tuple(raw_tags),
            glossary_terms=tuple(raw_terms),
            created_at=(datetime.fromisoformat(created_at) if created_at is not None else None),
            matches=tuple(
                CatalogService._match_fragment_from_document(fragment) for fragment in raw_matches
            ),
            description_truncated=bool(truncation_values[0]),
            tags_truncated=bool(truncation_values[1]),
            glossary_terms_truncated=bool(truncation_values[2]),
            column_names_truncated=bool(truncation_values[3]),
        )

    @staticmethod
    def _facets_document(
        facets: CatalogFacets,
        *,
        workspace_id: UUID,
    ) -> dict[str, Any]:
        return {
            "schema": 3,
            "workspace_id": str(workspace_id),
            "asset_types": [
                {"value": item.value, "count": item.count} for item in facets.asset_types
            ],
            "platforms": [{"value": item.value, "count": item.count} for item in facets.platforms],
            "classifications": [
                {"value": item.value, "count": item.count} for item in facets.classifications
            ],
            "databases": [{"value": item.value, "count": item.count} for item in facets.databases],
            "schemas": [{"value": item.value, "count": item.count} for item in facets.schemas],
            "domains": [{"value": item.value, "count": item.count} for item in facets.domains],
            "lifecycles": [
                {"value": item.value, "count": item.count} for item in facets.lifecycles
            ],
            "observed_at": facets.observed_at.isoformat() if facets.observed_at else None,
            "projection_version": facets.projection_version,
            "policy_version": facets.policy_version,
            "classification_policy_version": facets.classification_policy_version,
            "authorization_generation": facets.authorization_generation,
        }

    @staticmethod
    def _cached_facets(
        value: object,
        *,
        workspace_id: UUID,
        limit: int,
    ) -> CatalogFacets | None:
        if (
            not isinstance(value, dict)
            or value.get("schema") != 3
            or value.get("workspace_id") != str(workspace_id)
            or not 1 <= limit <= 100
        ):
            return None

        def buckets(key: str, *, maximum_characters: int) -> tuple[CatalogFacetBucket, ...]:
            raw_buckets = value.get(key)
            if not isinstance(raw_buckets, list) or len(raw_buckets) > limit:
                raise ValueError("Invalid cached catalog facet collection.")
            normalized: list[CatalogFacetBucket] = []
            for item in raw_buckets:
                if not isinstance(item, dict):
                    raise ValueError("Invalid cached catalog facet bucket.")
                raw_value = item.get("value")
                if raw_value is not None and (
                    not isinstance(raw_value, str) or not 1 <= len(raw_value) <= maximum_characters
                ):
                    raise ValueError("Invalid cached catalog facet value.")
                raw_count = item.get("count")
                if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
                    raise ValueError("Invalid cached catalog facet count.")
                normalized.append(CatalogFacetBucket(value=raw_value, count=raw_count))
            return tuple(normalized)

        try:
            return CatalogFacets(
                asset_types=buckets("asset_types", maximum_characters=100),
                platforms=buckets("platforms", maximum_characters=100),
                classifications=buckets("classifications", maximum_characters=100),
                databases=buckets("databases", maximum_characters=255),
                schemas=buckets("schemas", maximum_characters=255),
                domains=buckets("domains", maximum_characters=1_000),
                lifecycles=buckets("lifecycles", maximum_characters=50),
                observed_at=(
                    datetime.fromisoformat(str(value["observed_at"]))
                    if value.get("observed_at") is not None
                    else None
                ),
                projection_version=int(value["projection_version"]),
                policy_version=str(value["policy_version"]),
                classification_policy_version=(
                    int(value["classification_policy_version"])
                    if value.get("classification_policy_version") is not None
                    else None
                ),
                authorization_generation=(
                    int(value["authorization_generation"])
                    if value.get("authorization_generation") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _suggestions_document(
        suggestions: CatalogSuggestions,
        *,
        workspace_id: UUID,
    ) -> dict[str, Any]:
        return {
            "schema": 3,
            "workspace_id": str(workspace_id),
            "items": [
                {
                    "asset_id": str(item.asset_id),
                    "name": item.name,
                    "asset_type": item.asset_type,
                    "platform": item.platform,
                    "database_name": item.database_name,
                    "schema_name": item.schema_name,
                    "matches": [
                        {
                            "field": fragment.field,
                            "text": fragment.text,
                            "matched_terms": list(fragment.matched_terms),
                        }
                        for fragment in item.matches
                    ],
                }
                for item in suggestions.items
            ],
            "observed_at": (
                suggestions.observed_at.isoformat() if suggestions.observed_at else None
            ),
            "projection_version": suggestions.projection_version,
            "policy_version": suggestions.policy_version,
            "classification_policy_version": suggestions.classification_policy_version,
            "authorization_generation": suggestions.authorization_generation,
        }

    @staticmethod
    def _cached_suggestions(
        value: object,
        *,
        workspace_id: UUID,
        limit: int,
    ) -> CatalogSuggestions | None:
        if (
            not isinstance(value, dict)
            or value.get("schema") != 3
            or value.get("workspace_id") != str(workspace_id)
            or not 1 <= limit <= 20
        ):
            return None
        try:
            raw_items = value["items"]
            if not isinstance(raw_items, list) or len(raw_items) > limit:
                return None
            for item in raw_items:
                if not isinstance(item, dict):
                    return None
                bounded_fields = (
                    ("name", 500, False),
                    ("asset_type", 100, False),
                    ("platform", 100, True),
                    ("database_name", 255, True),
                    ("schema_name", 255, True),
                )
                for key, maximum_characters, nullable in bounded_fields:
                    candidate = item.get(key)
                    if candidate is None and nullable:
                        continue
                    if (
                        not isinstance(candidate, str)
                        or not 1 <= len(candidate) <= maximum_characters
                    ):
                        return None
                raw_matches = item.get("matches", [])
                if (
                    not isinstance(raw_matches, list)
                    or len(raw_matches) > MAX_CATALOG_MATCH_FRAGMENTS
                ):
                    return None
            return CatalogSuggestions(
                items=tuple(
                    CatalogSuggestion(
                        asset_id=UUID(str(item["asset_id"])),
                        name=item["name"],
                        asset_type=item["asset_type"],
                        platform=item.get("platform"),
                        database_name=item.get("database_name"),
                        schema_name=item.get("schema_name"),
                        matches=tuple(
                            CatalogService._match_fragment_from_document(fragment)
                            for fragment in item.get("matches", [])
                        ),
                    )
                    for item in raw_items
                ),
                observed_at=(
                    datetime.fromisoformat(str(value["observed_at"]))
                    if value.get("observed_at") is not None
                    else None
                ),
                projection_version=int(value["projection_version"]),
                policy_version=str(value["policy_version"]),
                classification_policy_version=(
                    int(value["classification_policy_version"])
                    if value.get("classification_policy_version") is not None
                    else None
                ),
                authorization_generation=(
                    int(value["authorization_generation"])
                    if value.get("authorization_generation") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _detail(
        authorized: CatalogAssetDetail,
        enrichment: DataHubAssetEnrichment,
        *,
        stale_at: datetime | None = None,
    ) -> CatalogAssetDetail:
        index = authorized.index
        glossary_terms = tuple(
            str(reference.get("name") or reference.get("urn"))[:1_000]
            for item in enrichment.glossary_terms
            if isinstance(item, dict)
            and isinstance((reference := item.get("term")), dict)
            and (reference.get("name") or reference.get("urn"))
        )[:100]
        if (
            enrichment.created_at is not None
            or enrichment.description is not None
            or enrichment.tags
            or glossary_terms
        ):
            index = replace(
                index,
                created_at=(
                    enrichment.created_at if enrichment.created_at is not None else index.created_at
                ),
                description=(
                    enrichment.description
                    if enrichment.description is not None
                    else index.description
                ),
                tags=enrichment.tags,
                glossary_terms=glossary_terms,
                description_truncated=enrichment.description_truncated,
                tags_truncated=enrichment.tags_truncated,
                glossary_terms_truncated=enrichment.glossary_terms_truncated,
            )
        return CatalogAssetDetail(
            index=index,
            ownership=enrichment.ownership,
            glossary_terms=enrichment.glossary_terms,
            tags=enrichment.tags,
            schema_fields=enrichment.schema_fields,
            quality=enrichment.quality,
            raw_version=enrichment.raw_version,
            observed_at=enrichment.observed_at,
            stale_at=stale_at,
            schema_fields_total=enrichment.schema_fields_total,
            schema_fields_truncated=enrichment.schema_fields_truncated,
            schema_fields_total_exact=enrichment.schema_fields_total_exact,
            ownership_truncated=enrichment.ownership_truncated,
            glossary_terms_truncated=enrichment.glossary_terms_truncated,
            tags_truncated=enrichment.tags_truncated,
            description_truncated=enrichment.description_truncated,
        )

    @staticmethod
    def _enrichment_document(
        enrichment: DataHubAssetEnrichment, *, fresh_until: datetime
    ) -> dict[str, Any]:
        return {
            "schema": 7,
            "ownership": list(enrichment.ownership),
            "glossary_terms": list(enrichment.glossary_terms),
            "tags": list(enrichment.tags),
            "schema_fields": list(enrichment.schema_fields),
            "schema_fields_total": enrichment.schema_fields_total,
            "schema_fields_truncated": enrichment.schema_fields_truncated,
            "schema_fields_total_exact": enrichment.schema_fields_total_exact,
            "quality": enrichment.quality,
            "raw_version": enrichment.raw_version,
            "observed_at": enrichment.observed_at.isoformat(),
            "created_at": (
                enrichment.created_at.isoformat() if enrichment.created_at is not None else None
            ),
            "description": enrichment.description,
            "ownership_truncated": enrichment.ownership_truncated,
            "glossary_terms_truncated": enrichment.glossary_terms_truncated,
            "tags_truncated": enrichment.tags_truncated,
            "description_truncated": enrichment.description_truncated,
            "fresh_until": fresh_until.isoformat(),
        }

    @staticmethod
    def _cached_fresh_until(value: object) -> datetime | None:
        if not isinstance(value, dict):
            return None
        try:
            return datetime.fromisoformat(str(value["fresh_until"]))
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _cached_enrichment(value: object) -> DataHubAssetEnrichment | None:
        if not isinstance(value, dict) or value.get("schema") != 7:
            return None
        try:
            ownership = _cached_reference_items(
                value["ownership"],
                entity="owner",
                maximum_items=100,
                maximum_characters=1_000,
            )
            glossary_terms = _cached_reference_items(
                value["glossary_terms"],
                entity="term",
                maximum_items=100,
                maximum_characters=1_000,
            )
            raw_tags = value["tags"]
            if (
                not isinstance(raw_tags, list)
                or len(raw_tags) > 100
                or any(not isinstance(item, str) or len(item) > 1_000 for item in raw_tags)
            ):
                return None
            tags = tuple(raw_tags)
            raw_schema_fields = value["schema_fields"]
            if (
                not isinstance(raw_schema_fields, list)
                or len(raw_schema_fields) > MAX_CATALOG_SCHEMA_FIELDS
            ):
                return None
            schema_fields = tuple(_cached_schema_field(item) for item in raw_schema_fields)
            schema_fields_total = (
                int(value["schema_fields_total"])
                if value.get("schema_fields_total") is not None
                else len(raw_schema_fields)
            )
            raw_truncated = value.get("schema_fields_truncated", False)
            raw_total_exact = value.get("schema_fields_total_exact", True)
            if not isinstance(raw_truncated, bool) or not isinstance(raw_total_exact, bool):
                return None
            schema_fields_truncated = raw_truncated
            schema_fields_total_exact = raw_total_exact
            if (
                schema_fields_total < len(schema_fields)
                or (schema_fields_truncated and schema_fields_total <= len(schema_fields))
                or (schema_fields_truncated and len(schema_fields) != MAX_CATALOG_SCHEMA_FIELDS)
                or (not schema_fields_truncated and schema_fields_total != len(schema_fields))
                or (not schema_fields_total_exact and not schema_fields_truncated)
            ):
                return None
            raw_quality = value["quality"]
            if not isinstance(raw_quality, dict):
                return None
            quality: dict[str, Any] = {}
            for key in ("rowCount", "columnCount", "sizeInBytes"):
                candidate = raw_quality.get(key)
                if candidate is not None:
                    if (
                        isinstance(candidate, bool)
                        or not isinstance(candidate, int)
                        or candidate < 0
                    ):
                        return None
                    quality[key] = candidate
            profiled_at = raw_quality.get("profiledAt")
            if profiled_at is not None:
                if not isinstance(profiled_at, str) or len(profiled_at) > 100:
                    return None
                quality["profiledAt"] = profiled_at
            raw_version = str(value["raw_version"])
            if not 1 <= len(raw_version) <= 255:
                return None
            observed_at = datetime.fromisoformat(str(value["observed_at"]))
            created_at = (
                datetime.fromisoformat(str(value["created_at"]))
                if value.get("created_at") is not None
                else None
            )
            description = (
                str(value["description"])
                if isinstance(value.get("description"), str) and value["description"].strip()
                else None
            )
            if description is not None and len(description) > 10_000:
                return None
            truncation_values = tuple(
                value.get(key)
                for key in (
                    "ownership_truncated",
                    "glossary_terms_truncated",
                    "tags_truncated",
                    "description_truncated",
                )
            )
            if not all(isinstance(item, bool) for item in truncation_values):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        return DataHubAssetEnrichment(
            ownership=ownership,
            glossary_terms=glossary_terms,
            tags=tags,
            schema_fields=schema_fields,
            quality=quality,
            raw_version=raw_version,
            observed_at=observed_at,
            created_at=created_at,
            description=description,
            schema_fields_total=schema_fields_total,
            schema_fields_truncated=schema_fields_truncated,
            schema_fields_total_exact=schema_fields_total_exact,
            ownership_truncated=bool(truncation_values[0]),
            glossary_terms_truncated=bool(truncation_values[1]),
            tags_truncated=bool(truncation_values[2]),
            description_truncated=bool(truncation_values[3]),
        )
