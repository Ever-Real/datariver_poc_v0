from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest

from datariver.application.classification_access import static_classification_access_floor
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
    CatalogWatermarkReader,
    DataHubGateway,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.domain.authz import (
    BuiltinPolicyEngine,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ValidationError
from datariver.infrastructure.db.catalog import _literal_contains_pattern
from datariver.infrastructure.observability.metrics import HttpMetrics


class FakeIndex:
    def __init__(self, detail: CatalogAssetDetail) -> None:
        self.detail = detail
        self.search_calls = 0
        self.projection_version = 1

    async def get_search_watermark(self, *, workspace_id: object) -> int:
        return self.projection_version

    async def search(self, **_: object) -> CatalogPage:
        self.search_calls += 1
        return CatalogPage(
            items=(self.detail.index,),
            next_cursor=None,
            observed_at=self.detail.observed_at,
        )

    async def get_authorized_asset(
        self, *, subject: SubjectAttributes, access: object, asset_id: object
    ) -> CatalogAssetDetail | None:
        del access
        return self.detail


class FakeGateway:
    def __init__(self, enrichment: DataHubAssetEnrichment) -> None:
        self.enrichment = enrichment
        self.calls = 0
        self.fail = False

    async def get_asset(self, external_urn: str) -> DataHubAssetEnrichment:
        self.calls += 1
        if self.fail:
            raise ExternalDependencyError(
                "DataHub unavailable.",
                dependency="datahub",
                retryable=True,
                provider_code="NETWORK",
            )
        return self.enrichment


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any] | list[Any]] = {}

    async def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        return self.values.get(key)

    async def set_json(
        self, key: str, value: dict[str, Any] | list[Any], *, ttl_seconds: int
    ) -> None:
        self.values[key] = value

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                del self.values[key]
        return deleted


class AllowAuthorization:
    async def authorize(self, **_: object) -> None:
        return None


def test_search_cache_ttl_never_crosses_policy_or_grant_boundary() -> None:
    now = datetime.now(UTC)
    access = replace(
        static_classification_access_floor(),
        nearest_validity_boundary=now + timedelta(seconds=3, microseconds=900_000),
    )
    assert (
        CatalogService._bounded_cache_ttl(
            configured_ttl=30,
            access=access,
            now=now,
        )
        == 3
    )
    assert (
        CatalogService._bounded_cache_ttl(
            configured_ttl=30,
            access=access,
            now=now + timedelta(seconds=4),
        )
        == 0
    )


@pytest.mark.asyncio
async def test_authorized_detail_enrichment_uses_scope_versioned_cache() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    asset_id = uuid4()
    index = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:test",
        asset_type="DATASET",
        name="wafer_events",
        description="events",
        platform="snowflake",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.PUBLIC,
        lifecycle="ACTIVE",
        source_version="projection-v1",
        observed_at=now,
    )
    local = CatalogAssetDetail(index, (), (), (), (), {}, "projection-v1", now)
    gateway = FakeGateway(
        DataHubAssetEnrichment(
            ownership=({"owner": "yield"},),
            glossary_terms=(),
            tags=("trusted",),
            schema_fields=({"fieldPath": "wafer_id"},),
            quality={"score": 0.99},
            raw_version="datahub-v2",
            observed_at=now,
        )
    )
    cache = FakeCache()
    metrics = HttpMetrics()
    index_reader = FakeIndex(local)
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(DataHubGateway, gateway),
        cache=cast(Cache, cache),
        authorization=cast(AuthorizationService, AllowAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
        telemetry=metrics,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.PUBLIC,
    )
    environment = EnvironmentAttributes(requested_at=now)

    first = await service.get_asset(
        subject=subject, asset_id=asset_id, environment=environment, request_id="one"
    )
    second = await service.get_asset(
        subject=subject, asset_id=asset_id, environment=environment, request_id="two"
    )

    assert first is not None and second is not None
    assert second.raw_version == "datahub-v2"
    assert gateway.calls == 1
    assert len(cache.values) == 2

    fresh_key = next(key for key in cache.values if ":fresh:" in key)
    await cache.delete(fresh_key)
    gateway.fail = True
    stale = await service.get_asset(
        subject=subject, asset_id=asset_id, environment=environment, request_id="three"
    )
    assert stale is not None and stale.stale_at is not None

    first_page = await service.search(
        subject=subject,
        query="wafer",
        filters={},
        cursor=None,
        limit=25,
        environment=environment,
        request_id="search-one",
    )
    second_page = await service.search(
        subject=subject,
        query="wafer",
        filters={},
        cursor=None,
        limit=25,
        environment=environment,
        request_id="search-two",
    )
    assert first_page == second_page
    assert index_reader.search_calls == 1
    index_reader.projection_version += 1
    third_page = await service.search(
        subject=subject,
        query="wafer",
        filters={},
        cursor=None,
        limit=25,
        environment=environment,
        request_id="search-after-projection-change",
    )
    assert third_page == first_page
    assert index_reader.search_calls == 2
    rendered_metrics = metrics.render().decode()
    assert 'datariver_catalog_cache_access_total{cache="search",outcome="miss"} 2.0' in (
        rendered_metrics
    )
    assert 'datariver_catalog_cache_access_total{cache="search",outcome="hit"} 1.0' in (
        rendered_metrics
    )
    assert 'datariver_catalog_detail_source_total{source="datahub"} 1.0' in rendered_metrics
    assert 'datariver_catalog_detail_source_total{source="fresh_cache"} 1.0' in (rendered_metrics)
    assert 'datariver_catalog_detail_source_total{source="stale_cache"} 1.0' in (rendered_metrics)

    with pytest.raises(ValidationError):
        await service.search(
            subject=subject,
            query="x",
            filters={},
            cursor=None,
            limit=25,
            environment=environment,
            request_id="too-short",
        )


def test_catalog_literal_pattern_escapes_wildcards() -> None:
    assert _literal_contains_pattern(r"100%_yield\path") == r"%100\%\_yield\\path%"
