from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogPage,
    DataHubAssetEnrichment,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    Cache,
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
from datariver.domain.common import ValidationError


class CatalogService:
    def __init__(
        self,
        *,
        index: CatalogIndexReader,
        watermark: CatalogWatermarkReader,
        datahub: DataHubGateway,
        cache: Cache,
        authorization: AuthorizationService,
        detail_cache_ttl_seconds: int,
        stale_detail_ttl_seconds: int,
        search_cache_ttl_seconds: int,
        minimum_query_length: int,
        policy_version: str,
        telemetry: CatalogTelemetry | None = None,
    ) -> None:
        self._index = index
        self._watermark = watermark
        self._datahub = datahub
        self._cache = cache
        self._authorization = authorization
        self._detail_cache_ttl_seconds = detail_cache_ttl_seconds
        self._stale_detail_ttl_seconds = stale_detail_ttl_seconds
        self._search_cache_ttl_seconds = search_cache_ttl_seconds
        self._minimum_query_length = minimum_query_length
        self._policy_version = policy_version
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
        normalized_query = unicodedata.normalize("NFKC", query).strip()
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
        watermark = await self._watermark.get_search_watermark(workspace_id=subject.workspace_id)
        cache_key = self._search_cache_key(
            subject=subject,
            query=normalized_query,
            filters=filters,
            cursor=cursor,
            limit=limit,
            watermark=watermark,
        )
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
            query=normalized_query,
            filters=filters,
            cursor=cursor,
            limit=limit,
        )
        try:
            await self._cache.set_json(
                cache_key,
                self._page_document(page),
                ttl_seconds=self._search_cache_ttl_seconds,
            )
        except Exception:
            self._cache_access(cache="search_write", outcome="error")
            return page
        self._cache_access(cache="search_write", outcome="success")
        return page

    async def get_asset(
        self,
        *,
        subject: SubjectAttributes,
        asset_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogAssetDetail | None:
        authorized = await self._index.get_authorized_asset(subject=subject, asset_id=asset_id)
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
        watermark: datetime,
    ) -> str:
        key_document = {
            "workspace": str(subject.workspace_id),
            "scope": self._permission_scope_hash(subject),
            "policy": self._policy_version,
            "source_watermark": watermark.isoformat(),
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

    @staticmethod
    def _page_document(page: CatalogPage) -> dict[str, Any]:
        return {
            "schema": 1,
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
        }

    @staticmethod
    def _cached_page(value: object) -> CatalogPage | None:
        if not isinstance(value, dict) or value.get("schema") != 1:
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
