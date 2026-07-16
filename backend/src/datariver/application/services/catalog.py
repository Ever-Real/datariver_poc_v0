from __future__ import annotations

import base64
import binascii
import hashlib
import json
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from datariver.application.classification_access import (
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogFacetBucket,
    CatalogFacets,
    CatalogPage,
    CatalogSuggestion,
    CatalogSuggestions,
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
                cached_page = self._cached_page(cached)
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
                cached_facets = self._cached_facets(cached)
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
                    self._facets_document(facets),
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
                cached_suggestions = self._cached_suggestions(cached)
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
                    self._suggestions_document(suggestions),
                    ttl_seconds=cache_ttl,
                )
            except Exception:
                self._cache_access(cache="suggestions_write", outcome="error")
            else:
                self._cache_access(cache="suggestions_write", outcome="success")
        return suggestions

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
        )
        authorized = await self._index.get_authorized_asset(
            subject=subject,
            access=access,
            asset_id=asset_id,
        )
        if authorized is None:
            return None
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

    def _cache_access(self, *, cache: str, outcome: str) -> None:
        if self._telemetry is not None:
            self._telemetry.catalog_cache_access(cache=cache, outcome=outcome)

    def _detail_source(self, *, source: str) -> None:
        if self._telemetry is not None:
            self._telemetry.catalog_detail_source(source=source)

    def _permission_scope_hash(self, subject: SubjectAttributes) -> str:
        permission_scope = {
            "clearance": int(subject.clearance),
            "systems": sorted(str(value) for value in subject.allowed_system_ids),
            "domains": sorted(str(value) for value in subject.allowed_domain_ids),
            "actions": sorted(value.value for value in subject.allowed_actions),
            "denies": sorted(value.value for value in subject.denied_actions),
        }
        return hashlib.sha256(json.dumps(permission_scope, sort_keys=True).encode()).hexdigest()

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
    ) -> tuple[str, ClassificationAccessSnapshot, int]:
        normalized_query = unicodedata.normalize("NFKC", query).strip()
        if require_query and not normalized_query:
            raise ValidationError("The catalog query is required.")
        if normalized_query and len(normalized_query) < self._minimum_query_length:
            raise ValidationError(
                "The catalog query is shorter than the configured minimum.",
                details={"minimum_query_length": self._minimum_query_length},
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
        )
        watermark = await self._watermark.get_search_watermark(workspace_id=subject.workspace_id)
        return normalized_query, access, watermark

    async def _resolve_classification_access(
        self,
        *,
        subject: SubjectAttributes,
        now: datetime,
    ) -> ClassificationAccessSnapshot:
        if self._classification_access is None:
            return static_classification_access_floor()
        return await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=now,
        )

    @staticmethod
    def _classification_access_document(
        access: ClassificationAccessSnapshot,
    ) -> dict[str, Any]:
        return {
            "posture": access.posture.value,
            "policy_id": str(access.policy_id) if access.policy_id else None,
            "policy_hash": access.policy_hash,
            "policy_version": access.policy_version,
            "authorization_generation": access.authorization_generation,
            "rules": [
                {
                    "classification": int(rule.classification),
                    "search_mode": rule.search_mode.value,
                }
                for rule in access.rules
            ],
            "restricted_resources": sorted(str(value) for value in access.restricted_resource_ids),
            "restricted_systems": sorted(str(value) for value in access.restricted_system_ids),
            "restricted_domains": sorted(str(value) for value in access.restricted_domain_ids),
        }

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
            "schema": 2,
            "items": [
                {
                    "asset_id": str(item.asset_id),
                    "workspace_id": str(item.workspace_id),
                    "external_urn": item.external_urn,
                    "asset_type": item.asset_type,
                    "name": item.name,
                    "description": item.description,
                    "platform": item.platform,
                    "domain_id": str(item.domain_id) if item.domain_id else None,
                    "system_id": str(item.system_id) if item.system_id else None,
                    "owner_department_id": (
                        str(item.owner_department_id) if item.owner_department_id else None
                    ),
                    "classification": int(item.classification),
                    "lifecycle": item.lifecycle,
                    "source_version": item.source_version,
                    "observed_at": item.observed_at.isoformat(),
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
            "observed_at": page.observed_at.isoformat(),
            "stale_at": page.stale_at.isoformat() if page.stale_at else None,
            "projection_version": page.projection_version,
            "policy_version": page.policy_version,
            "classification_policy_version": page.classification_policy_version,
            "authorization_generation": page.authorization_generation,
        }

    @staticmethod
    def _cached_page(value: object) -> CatalogPage | None:
        if not isinstance(value, dict) or value.get("schema") != 2:
            return None
        try:
            items = tuple(
                CatalogAssetIndex(
                    asset_id=UUID(str(item["asset_id"])),
                    workspace_id=UUID(str(item["workspace_id"])),
                    external_urn=str(item["external_urn"]),
                    asset_type=str(item["asset_type"]),
                    name=str(item["name"]),
                    description=(
                        str(item["description"]) if item.get("description") is not None else None
                    ),
                    platform=str(item["platform"]) if item.get("platform") is not None else None,
                    domain_id=UUID(str(item["domain_id"])) if item.get("domain_id") else None,
                    system_id=UUID(str(item["system_id"])) if item.get("system_id") else None,
                    owner_department_id=(
                        UUID(str(item["owner_department_id"]))
                        if item.get("owner_department_id")
                        else None
                    ),
                    classification=Classification(int(item["classification"])),
                    lifecycle=str(item["lifecycle"]),
                    source_version=str(item["source_version"]),
                    observed_at=datetime.fromisoformat(str(item["observed_at"])),
                )
                for item in value["items"]
            )
            stale_raw = value.get("stale_at")
            return CatalogPage(
                items=items,
                next_cursor=str(value["next_cursor"]) if value.get("next_cursor") else None,
                observed_at=datetime.fromisoformat(str(value["observed_at"])),
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
    def _facets_document(facets: CatalogFacets) -> dict[str, Any]:
        return {
            "schema": 1,
            "asset_types": [
                {"value": item.value, "count": item.count} for item in facets.asset_types
            ],
            "platforms": [{"value": item.value, "count": item.count} for item in facets.platforms],
            "classifications": [
                {"value": item.value, "count": item.count} for item in facets.classifications
            ],
            "observed_at": facets.observed_at.isoformat() if facets.observed_at else None,
            "projection_version": facets.projection_version,
            "policy_version": facets.policy_version,
            "classification_policy_version": facets.classification_policy_version,
            "authorization_generation": facets.authorization_generation,
        }

    @staticmethod
    def _cached_facets(value: object) -> CatalogFacets | None:
        if not isinstance(value, dict) or value.get("schema") != 1:
            return None
        try:
            return CatalogFacets(
                asset_types=tuple(
                    CatalogFacetBucket(
                        value=str(item["value"]) if item.get("value") is not None else None,
                        count=int(item["count"]),
                    )
                    for item in value["asset_types"]
                ),
                platforms=tuple(
                    CatalogFacetBucket(
                        value=str(item["value"]) if item.get("value") is not None else None,
                        count=int(item["count"]),
                    )
                    for item in value["platforms"]
                ),
                classifications=tuple(
                    CatalogFacetBucket(
                        value=str(item["value"]) if item.get("value") is not None else None,
                        count=int(item["count"]),
                    )
                    for item in value["classifications"]
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
    def _suggestions_document(suggestions: CatalogSuggestions) -> dict[str, Any]:
        return {
            "schema": 1,
            "items": [
                {
                    "asset_id": str(item.asset_id),
                    "name": item.name,
                    "asset_type": item.asset_type,
                    "platform": item.platform,
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
    def _cached_suggestions(value: object) -> CatalogSuggestions | None:
        if not isinstance(value, dict) or value.get("schema") != 1:
            return None
        try:
            return CatalogSuggestions(
                items=tuple(
                    CatalogSuggestion(
                        asset_id=UUID(str(item["asset_id"])),
                        name=str(item["name"]),
                        asset_type=str(item["asset_type"]),
                        platform=(
                            str(item["platform"]) if item.get("platform") is not None else None
                        ),
                    )
                    for item in value["items"]
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
        return CatalogAssetDetail(
            index=authorized.index,
            ownership=enrichment.ownership,
            glossary_terms=enrichment.glossary_terms,
            tags=enrichment.tags,
            schema_fields=enrichment.schema_fields,
            quality=enrichment.quality,
            raw_version=enrichment.raw_version,
            observed_at=enrichment.observed_at,
            stale_at=stale_at,
        )

    @staticmethod
    def _enrichment_document(
        enrichment: DataHubAssetEnrichment, *, fresh_until: datetime
    ) -> dict[str, Any]:
        return {
            "schema": 1,
            "ownership": list(enrichment.ownership),
            "glossary_terms": list(enrichment.glossary_terms),
            "tags": list(enrichment.tags),
            "schema_fields": list(enrichment.schema_fields),
            "quality": enrichment.quality,
            "raw_version": enrichment.raw_version,
            "observed_at": enrichment.observed_at.isoformat(),
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
        if not isinstance(value, dict) or value.get("schema") != 1:
            return None
        try:
            ownership = tuple(dict(item) for item in value["ownership"])
            glossary_terms = tuple(dict(item) for item in value["glossary_terms"])
            tags = tuple(str(item) for item in value["tags"])
            schema_fields = tuple(dict(item) for item in value["schema_fields"])
            quality = dict(value["quality"])
            raw_version = str(value["raw_version"])
            observed_at = datetime.fromisoformat(str(value["observed_at"]))
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
        )
