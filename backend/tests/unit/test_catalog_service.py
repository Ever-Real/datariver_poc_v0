from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, Table

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
    CatalogVocabulary,
    DataHubAssetEnrichment,
    DataHubLineageNode,
    DataHubLineagePage,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    Cache,
    CatalogCandidateTargetReader,
    CatalogDiscoveryReader,
    CatalogIndexReader,
    CatalogWatermarkReader,
    DataHubGateway,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.domain.authz import (
    Action,
    BuiltinPolicyEngine,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ValidationError
from datariver.infrastructure.db.catalog import (
    _literal_contains_pattern,
    _literal_prefix_pattern,
    _match_fragments,
    _query_terms,
)
from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogSyncRunModel,
)
from datariver.infrastructure.observability.metrics import HttpMetrics


class FakeIndex:
    def __init__(self, detail: CatalogAssetDetail) -> None:
        self.detail = detail
        self.search_calls = 0
        self.facet_calls = 0
        self.suggestion_calls = 0
        self.vocabulary_calls = 0
        self.tree_calls = 0
        self.last_search_access: ClassificationAccessSnapshot | None = None
        self.projection_version = 1
        self.lineage_assets: tuple[CatalogAssetIndex, ...] = (detail.index,)

    async def get_search_watermark(self, *, workspace_id: object) -> int:
        return self.projection_version

    async def search(self, **kwargs: object) -> CatalogPage:
        self.search_calls += 1
        self.last_search_access = cast(ClassificationAccessSnapshot | None, kwargs.get("access"))
        return CatalogPage(
            items=(self.detail.index,),
            next_cursor=None,
            observed_at=self.detail.observed_at,
            total=1,
        )

    async def get_authorized_asset(
        self, *, subject: SubjectAttributes, access: object, asset_id: object
    ) -> CatalogAssetDetail | None:
        del access
        return self.detail

    async def facets(self, **_: object) -> CatalogFacets:
        self.facet_calls += 1
        return CatalogFacets(
            asset_types=(CatalogFacetBucket("DATASET", 1),),
            platforms=(CatalogFacetBucket("snowflake", 1),),
            classifications=(CatalogFacetBucket("PUBLIC", 1),),
            observed_at=self.detail.observed_at,
            databases=(CatalogFacetBucket("manufacturing", 1),),
            schemas=(CatalogFacetBucket("yield", 1),),
            domains=(CatalogFacetBucket("urn:li:domain:semiconductor", 1),),
            lifecycles=(CatalogFacetBucket("ACTIVE", 1),),
        )

    async def suggestions(self, **_: object) -> CatalogSuggestions:
        self.suggestion_calls += 1
        return CatalogSuggestions(
            items=(
                CatalogSuggestion(
                    asset_id=self.detail.index.asset_id,
                    name=self.detail.index.name,
                    asset_type=self.detail.index.asset_type,
                    platform=self.detail.index.platform,
                    database_name=self.detail.index.database_name,
                    schema_name=self.detail.index.schema_name,
                    matches=(
                        CatalogMatchFragment(
                            field="NAME",
                            text=self.detail.index.name,
                            matched_terms=("wafer",),
                        ),
                    ),
                ),
            ),
            observed_at=self.detail.observed_at,
        )

    async def vocabulary(self, **_: object) -> CatalogVocabulary:
        self.vocabulary_calls += 1
        return CatalogVocabulary(items=("Calibration",), observed_at=self.detail.observed_at)

    async def tree_nodes(self, **_: object) -> CatalogTreePage:
        self.tree_calls += 1
        return CatalogTreePage(
            items=(
                CatalogTreeNode(
                    node_id=uuid4(),
                    kind="PLATFORM",
                    label="snowflake",
                    asset_count=1,
                    has_children=True,
                    platform="snowflake",
                ),
            ),
            next_cursor=None,
            observed_at=self.detail.observed_at,
        )

    async def get_authorized_assets_by_external_urns(
        self, *, external_urns: object, **_: object
    ) -> tuple[CatalogAssetIndex, ...]:
        del external_urns
        return self.lineage_assets

    async def get_authorized_assets_by_ids(
        self, *, asset_ids: object, **_: object
    ) -> tuple[CatalogAssetIndex, ...]:
        requested = set(cast(tuple[object, ...], asset_ids))
        return tuple(item for item in self.lineage_assets if item.asset_id in requested)


class FakeGateway:
    def __init__(self, enrichment: DataHubAssetEnrichment) -> None:
        self.enrichment = enrichment
        self.calls = 0
        self.fail = False
        self.lineage_page = DataHubLineagePage(items=(), total=0, partial=False)
        self.vocabulary_items: tuple[str, ...] = ()
        self.vocabulary_failure = False
        self.vocabulary_queries: list[dict[str, object]] = []

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

    async def get_lineage(self, **_: object) -> DataHubLineagePage:
        return self.lineage_page

    async def search_vocabulary(self, **values: object) -> tuple[str, ...]:
        self.vocabulary_queries.append(values)
        if self.vocabulary_failure:
            raise ExternalDependencyError(
                "DataHub unavailable.",
                dependency="datahub",
                retryable=True,
                provider_code="NETWORK",
            )
        return self.vocabulary_items


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

    async def can_review_quarantined_catalog(self, **_: object) -> bool:
        return False

    async def filter_authorized(self, **values: object) -> tuple[object, ...]:
        return cast(tuple[object, ...], values["resources"])


class AdminReviewAuthorization(AllowAuthorization):
    async def can_review_quarantined_catalog(self, **_: object) -> bool:
        return True


class ReviewOnlyAuthorization(AdminReviewAuthorization):
    async def authorize(self, **_: object) -> None:
        raise AssertionError("The separate audited review scope must not re-enter generic ABAC.")


@pytest.mark.asyncio
async def test_catalog_asset_access_revalidation_is_set_based_and_skips_datahub_detail() -> None:
    now = datetime.now(UTC)
    workspace_id, asset_id = uuid4(), uuid4()
    asset = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:employee",
        asset_type="DATASET",
        name="employee",
        description=None,
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="projection-v3",
        observed_at=now,
    )
    detail = CatalogAssetDetail(asset, (), (), (), (), {}, "datahub-v4", now)
    index_reader = FakeIndex(detail)
    gateway = FakeGateway(DataHubAssetEnrichment((), (), (), (), {}, "datahub-v4", now))
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(DataHubGateway, gateway),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, AllowAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
        candidate_targets=cast(CatalogCandidateTargetReader, index_reader),
    )
    current_subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="USER",
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CATALOG_READ}),
    )

    values = await service.get_asset_indexes(
        subject=current_subject,
        asset_ids=(asset_id,),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="preflight",
    )

    assert values == (asset,)
    assert gateway.calls == 0


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
async def test_catalog_vocabulary_allows_a_single_character_query() -> None:
    now = datetime.now(UTC)
    workspace_id, asset_id = uuid4(), uuid4()
    asset = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:vocabulary",
        asset_type="DATASET",
        name="vocabulary_source",
        description=None,
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="projection-v1",
        observed_at=now,
    )
    index_reader = FakeIndex(CatalogAssetDetail(asset, (), (), (), (), {}, "projection-v1", now))
    gateway = FakeGateway(DataHubAssetEnrichment((), (), (), (), {}, "v1", now))
    gateway.vocabulary_items = ("Calibration policy", "Capacity")
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(DataHubGateway, gateway),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, AllowAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="USER",
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CATALOG_SEARCH}),
    )

    vocabulary = await service.vocabulary(
        subject=subject,
        kind="TERM",
        query="c",
        limit=12,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="single-character-vocabulary",
    )

    assert vocabulary.items == ("Calibration",)
    assert index_reader.vocabulary_calls == 1
    assert gateway.vocabulary_queries == []


@pytest.mark.asyncio
async def test_catalog_vocabulary_initial_browse_is_workspace_projection_scoped() -> None:
    now = datetime.now(UTC)
    workspace_id, asset_id = uuid4(), uuid4()
    asset = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:vocabulary-browse",
        asset_type="DATASET",
        name="vocabulary_source",
        description=None,
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="projection-v1",
        observed_at=now,
    )
    index_reader = FakeIndex(CatalogAssetDetail(asset, (), (), (), (), {}, "projection-v1", now))
    gateway = FakeGateway(DataHubAssetEnrichment((), (), (), (), {}, "v1", now))
    gateway.vocabulary_items = ("Business Critical", "Customer")
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(DataHubGateway, gateway),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, AllowAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="USER",
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CATALOG_SEARCH}),
    )

    vocabulary = await service.vocabulary(
        subject=subject,
        kind="TAG",
        query="",
        limit=12,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="initial-vocabulary-browse",
    )

    assert vocabulary.items == ("Calibration",)
    assert gateway.vocabulary_queries == []


@pytest.mark.asyncio
async def test_catalog_vocabulary_keeps_projection_when_datahub_unavailable() -> None:
    now = datetime.now(UTC)
    workspace_id, asset_id = uuid4(), uuid4()
    asset = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:vocabulary-fallback",
        asset_type="DATASET",
        name="vocabulary_source",
        description=None,
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="projection-v1",
        observed_at=now,
    )
    index_reader = FakeIndex(CatalogAssetDetail(asset, (), (), (), (), {}, "projection-v1", now))
    gateway = FakeGateway(DataHubAssetEnrichment((), (), (), (), {}, "v1", now))
    gateway.vocabulary_failure = True
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(DataHubGateway, gateway),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, AllowAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="USER",
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CATALOG_SEARCH}),
    )

    vocabulary = await service.vocabulary(
        subject=subject,
        kind="TAG",
        query="c",
        limit=12,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="vocabulary-datahub-fallback",
    )

    assert vocabulary.items == ("Calibration",)
    assert gateway.vocabulary_queries == []


@pytest.mark.asyncio
async def test_catalog_search_marks_authorized_admin_quarantine_review_scope() -> None:
    now = datetime.now(UTC)
    workspace_id, asset_id = uuid4(), uuid4()
    asset = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:quarantined",
        asset_type="DATASET",
        name="unclassified_source",
        description="Awaiting DataHub classification.",
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.RESTRICTED,
        lifecycle="QUARANTINED",
        source_version="projection-v1",
        observed_at=now,
    )
    detail = CatalogAssetDetail(asset, (), (), (), (), {}, "projection-v1", now)
    index_reader = FakeIndex(detail)
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(
            DataHubGateway, FakeGateway(DataHubAssetEnrichment((), (), (), (), {}, "v1", now))
        ),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, AdminReviewAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset(
            {Action.CATALOG_SEARCH, Action.CATALOG_READ, Action.ADMIN_MANAGE}
        ),
    )

    page = await service.search(
        subject=subject,
        query="unclassified",
        filters={},
        cursor=None,
        limit=25,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="admin-quarantine-search",
    )

    assert page.items == (asset,)
    assert index_reader.last_search_access is not None
    assert index_reader.last_search_access.admin_quarantine_review is True


@pytest.mark.asyncio
async def test_catalog_detail_allows_typed_datahub_enrichment_for_review_scope() -> None:
    now = datetime.now(UTC)
    workspace_id, asset_id = uuid4(), uuid4()
    asset = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:quarantined-detail",
        asset_type="DATASET",
        name="unclassified_source",
        description="Awaiting DataHub classification.",
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.RESTRICTED,
        lifecycle="QUARANTINED",
        source_version="projection-v1",
        observed_at=now,
    )
    local_detail = CatalogAssetDetail(asset, (), (), (), (), {}, "projection-v1", now)
    index_reader = FakeIndex(local_detail)
    gateway = FakeGateway(
        DataHubAssetEnrichment(
            ownership=({"owner": {"urn": "urn:li:corpUser:security-admin"}},),
            glossary_terms=(),
            tags=(),
            schema_fields=(),
            quality={},
            raw_version="datahub-v1",
            observed_at=now,
        )
    )
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(DataHubGateway, gateway),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, ReviewOnlyAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset(
            {Action.CATALOG_SEARCH, Action.CATALOG_READ, Action.ADMIN_MANAGE}
        ),
    )

    detail = await service.get_asset(
        subject=subject,
        asset_id=asset_id,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="admin-quarantine-detail",
    )

    assert detail is not None
    assert detail.ownership == ({"owner": {"urn": "urn:li:corpUser:security-admin"}},)
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_catalog_lineage_allows_the_same_audited_review_scope_as_detail() -> None:
    now = datetime.now(UTC)
    workspace_id, asset_id = uuid4(), uuid4()
    asset = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:quarantined-lineage",
        asset_type="DATASET",
        name="unclassified_lineage_source",
        description="Awaiting DataHub classification.",
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.RESTRICTED,
        lifecycle="QUARANTINED",
        source_version="projection-v1",
        observed_at=now,
    )
    detail = CatalogAssetDetail(asset, (), (), (), (), {}, "projection-v1", now)
    service = CatalogService(
        index=cast(CatalogIndexReader, FakeIndex(detail)),
        discovery=cast(CatalogDiscoveryReader, FakeIndex(detail)),
        watermark=cast(CatalogWatermarkReader, FakeIndex(detail)),
        datahub=cast(
            DataHubGateway, FakeGateway(DataHubAssetEnrichment((), (), (), (), {}, "v1", now))
        ),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, ReviewOnlyAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset(
            {Action.CATALOG_SEARCH, Action.CATALOG_READ, Action.ADMIN_MANAGE}
        ),
    )

    lineage = await service.lineage(
        subject=subject,
        asset_id=asset_id,
        direction="BOTH",
        depth=2,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="admin-quarantine-lineage",
    )

    assert lineage is not None
    assert lineage.center_asset_id == asset_id


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
        owner="urn:li:corpGroup:yield",
        domain="urn:li:domain:manufacturing",
        tags=("trusted",),
        glossary_terms=("Wafer",),
        created_at=now - timedelta(days=1),
    )
    local = CatalogAssetDetail(index, (), (), (), (), {}, "projection-v1", now)
    gateway = FakeGateway(
        DataHubAssetEnrichment(
            ownership=({"owner": {"urn": "urn:li:corpGroup:yield"}},),
            glossary_terms=(),
            tags=("trusted",),
            schema_fields=({"fieldPath": "wafer_id"},),
            quality={"score": 0.99},
            raw_version="datahub-v2",
            observed_at=now,
            created_at=now,
            description="governed events",
        )
    )
    cache = FakeCache()
    metrics = HttpMetrics()
    index_reader = FakeIndex(local)
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
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
    assert second.index.created_at == now
    assert first.index.description == "governed events"
    assert second.index.description == "governed events"
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
    assert second_page.items[0].owner == "urn:li:corpGroup:yield"
    assert second_page.items[0].domain == "urn:li:domain:manufacturing"
    assert second_page.items[0].tags == ("trusted",)
    assert second_page.items[0].glossary_terms == ("Wafer",)
    assert second_page.items[0].created_at == now - timedelta(days=1)
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
    assert third_page.items == first_page.items
    assert third_page.projection_version == 2
    assert index_reader.search_calls == 2

    first_facets = await service.facets(
        subject=subject,
        query="wafer",
        filters={},
        limit=30,
        environment=environment,
        request_id="facets-one",
    )
    second_facets = await service.facets(
        subject=subject,
        query="wafer",
        filters={},
        limit=30,
        environment=environment,
        request_id="facets-two",
    )
    assert first_facets == second_facets
    assert first_facets.projection_version == 2
    assert first_facets.authorization_generation is None
    assert first_facets.databases == (CatalogFacetBucket("manufacturing", 1),)
    assert first_facets.schemas == (CatalogFacetBucket("yield", 1),)
    assert first_facets.domains == (CatalogFacetBucket("urn:li:domain:semiconductor", 1),)
    assert first_facets.lifecycles == (CatalogFacetBucket("ACTIVE", 1),)
    assert index_reader.facet_calls == 1

    first_suggestions = await service.suggestions(
        subject=subject,
        query="wafer",
        limit=8,
        environment=environment,
        request_id="suggestions-one",
    )
    second_suggestions = await service.suggestions(
        subject=subject,
        query="wafer",
        limit=8,
        environment=environment,
        request_id="suggestions-two",
    )
    assert first_suggestions == second_suggestions
    assert first_suggestions.projection_version == 2
    assert first_suggestions.items[0].matches[0].matched_terms == ("wafer",)
    assert index_reader.suggestion_calls == 1

    first_tree = await service.tree_nodes(
        subject=subject,
        query="wafer",
        parent_kind="ROOT",
        platform=None,
        database_name=None,
        schema_name=None,
        cursor=None,
        limit=50,
        environment=environment,
        request_id="tree-one",
    )
    second_tree = await service.tree_nodes(
        subject=subject,
        query="wafer",
        parent_kind="ROOT",
        platform=None,
        database_name=None,
        schema_name=None,
        cursor=None,
        limit=50,
        environment=environment,
        request_id="tree-two",
    )
    assert first_tree == second_tree
    assert first_tree.projection_version == 2
    assert index_reader.tree_calls == 1
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

    assert 'datariver_catalog_cache_access_total{cache="facets",outcome="hit"} 1.0' in (
        rendered_metrics
    )
    assert (
        'datariver_catalog_cache_access_total{cache="suggestions",outcome="hit"} 1.0'
        in rendered_metrics
    )

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

    with pytest.raises(ValidationError):
        await service.suggestions(
            subject=subject,
            query="",
            limit=8,
            environment=environment,
            request_id="empty-suggestion",
        )


def test_legacy_detail_cache_is_invalidated_after_logical_name_contract_change() -> None:
    now = datetime.now(UTC)
    cached = CatalogService._cached_enrichment(
        {
            "schema": 3,
            "ownership": [],
            "glossary_terms": [],
            "tags": [],
            "schema_fields": [{"fieldPath": f"field_{index}"} for index in range(1_005)],
            "quality": {},
            "raw_version": "legacy-wide-v1",
            "observed_at": now.isoformat(),
            "created_at": None,
            "description": None,
        }
    )

    assert cached is None


@pytest.mark.parametrize(
    ("total", "truncated", "total_exact"),
    [(1_001, False, True), (1_000, True, False), (1_000, False, False)],
)
def test_current_detail_cache_rejects_inconsistent_schema_field_metadata(
    total: int, truncated: bool, total_exact: bool
) -> None:
    now = datetime.now(UTC)

    cached = CatalogService._cached_enrichment(
        {
            "schema": 7,
            "ownership": [],
            "glossary_terms": [],
            "tags": [],
            "schema_fields": [{"fieldPath": "field_0"}],
            "schema_fields_total": total,
            "schema_fields_truncated": truncated,
            "schema_fields_total_exact": total_exact,
            "quality": {},
            "raw_version": "malformed-v1",
            "observed_at": now.isoformat(),
            "created_at": None,
            "description": None,
            "ownership_truncated": False,
            "glossary_terms_truncated": False,
            "tags_truncated": False,
            "description_truncated": False,
        }
    )

    assert cached is None


def test_pre_logical_name_detail_cache_is_invalidated() -> None:
    now = datetime.now(UTC)

    assert (
        CatalogService._cached_enrichment(
            {
                "schema": 4,
                "ownership": [],
                "glossary_terms": [],
                "tags": [],
                "schema_fields": [{"fieldPath": "field_0", "description": "legacy"}],
                "schema_fields_total": 1,
                "schema_fields_truncated": False,
                "schema_fields_total_exact": True,
                "quality": {},
                "raw_version": "pre-label-v1",
                "observed_at": now.isoformat(),
                "created_at": None,
                "description": None,
            }
        )
        is None
    )


@pytest.mark.asyncio
async def test_lineage_does_not_bridge_across_an_unauthorized_intermediate_node() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    center = CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:center",
        asset_type="DATASET",
        name="center",
        description=None,
        platform="snowflake",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.PUBLIC,
        lifecycle="ACTIVE",
        source_version="v1",
        observed_at=now,
    )
    visible = replace(
        center,
        asset_id=uuid4(),
        external_urn="urn:li:dataset:visible",
        name="visible",
    )
    detail = CatalogAssetDetail(center, (), (), (), (), {}, "v1", now)
    index_reader = FakeIndex(detail)
    index_reader.lineage_assets = (center, visible)
    gateway = FakeGateway(DataHubAssetEnrichment((), (), (), (), {}, "v1", now))
    gateway.lineage_page = DataHubLineagePage(
        items=(
            DataHubLineageNode(
                external_urn=visible.external_urn,
                degree=2,
                paths=(
                    (
                        center.external_urn,
                        "urn:li:dataset:hidden",
                        visible.external_urn,
                    ),
                ),
                truncated_children=False,
            ),
        ),
        total=1,
        partial=False,
    )
    service = CatalogService(
        index=cast(CatalogIndexReader, index_reader),
        discovery=cast(CatalogDiscoveryReader, index_reader),
        watermark=cast(CatalogWatermarkReader, index_reader),
        datahub=cast(DataHubGateway, gateway),
        cache=cast(Cache, FakeCache()),
        authorization=cast(AuthorizationService, AllowAuthorization()),
        detail_cache_ttl_seconds=60,
        stale_detail_ttl_seconds=900,
        search_cache_ttl_seconds=30,
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
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

    lineage = await service.lineage(
        subject=subject,
        asset_id=center.asset_id,
        direction="UPSTREAM",
        depth=2,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="lineage",
    )

    assert lineage is not None
    assert {node.asset_id for node in lineage.nodes} == {center.asset_id, visible.asset_id}
    assert lineage.edges == ()
    assert lineage.truncated is True


def test_catalog_literal_pattern_escapes_wildcards() -> None:
    assert _literal_contains_pattern(r"100%_yield\path") == r"%100\%\_yield\\path%"
    assert _literal_prefix_pattern(r"100%_yield\path") == r"100\%\_yield\\path%"


def test_catalog_match_fragments_use_all_normalized_terms_without_html() -> None:
    assert _query_terms("wafer  yield wafer") == ("wafer", "yield")
    fragments = _match_fragments(
        name="wafer_events",
        description="Yield evidence without <mark> injection.",
        query="wafer yield",
    )

    assert [fragment.field for fragment in fragments] == ["NAME", "DESCRIPTION"]
    assert fragments[0].matched_terms == ("wafer",)
    assert fragments[1].matched_terms == ("yield",)
    assert "<mark>" in fragments[1].text


def test_catalog_cache_match_fragments_fail_closed_on_unbounded_or_unexplained_evidence() -> None:
    valid = CatalogService._match_fragment_from_document(
        {"field": "TAG", "text": "tier:gold", "matched_terms": ["gold"]}
    )
    assert valid == CatalogMatchFragment(
        field="TAG",
        text="tier:gold",
        matched_terms=("gold",),
    )

    with pytest.raises(ValueError):
        CatalogService._match_fragment_from_document(
            {"field": "RAW", "text": "secret", "matched_terms": ["secret"]}
        )
    with pytest.raises(ValueError):
        CatalogService._match_fragment_from_document(
            {"field": "TAG", "text": "x" * 241, "matched_terms": ["gold"]}
        )
    with pytest.raises(ValueError):
        CatalogService._match_fragment_from_document(
            {"field": "TAG", "text": "tier:silver", "matched_terms": ["gold"]}
        )


def test_catalog_asset_cache_rejects_an_unbounded_match_collection() -> None:
    now = datetime.now(UTC)
    item = CatalogService._asset_index_document(
        CatalogAssetIndex(
            asset_id=uuid4(),
            workspace_id=uuid4(),
            external_urn="urn:li:dataset:cache-bound",
            asset_type="TABLE",
            name="cache_bound",
            description=None,
            platform="postgres",
            domain_id=None,
            system_id=None,
            owner_department_id=None,
            classification=Classification.PUBLIC,
            lifecycle="ACTIVE",
            source_version="v1",
            observed_at=now,
        )
    )
    item["matches"] = [
        {"field": "NAME", "text": "cache", "matched_terms": ["cache"]} for _ in range(73)
    ]

    with pytest.raises(ValueError, match="Invalid cached catalog matches"):
        CatalogService._asset_index_from_document(item)
    item["matches"] = []
    item["name"] = {"not": "a scalar"}
    with pytest.raises(ValueError, match="Invalid cached catalog asset scalar"):
        CatalogService._asset_index_from_document(item)


def test_catalog_page_cache_rejects_cross_workspace_and_over_limit_documents() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    index = CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:cache-scope",
        asset_type="TABLE",
        name="cache_scope",
        description=None,
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.PUBLIC,
        lifecycle="ACTIVE",
        source_version="v1",
        observed_at=now,
    )
    document = CatalogService._page_document(
        CatalogPage(items=(index,), next_cursor=None, observed_at=now, total=1)
    )

    assert CatalogService._cached_page(document, workspace_id=workspace_id, limit=1) is not None
    foreign_document = dict(document)
    foreign_item = dict(cast(list[dict[str, object]], document["items"])[0])
    foreign_item["workspace_id"] = str(uuid4())
    foreign_document["items"] = [foreign_item]
    assert (
        CatalogService._cached_page(
            foreign_document,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )
    oversized_document = dict(document)
    oversized_document["items"] = [
        cast(list[dict[str, object]], document["items"])[0],
        cast(list[dict[str, object]], document["items"])[0],
    ]
    oversized_document["total"] = 2
    assert (
        CatalogService._cached_page(
            oversized_document,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )
    inconsistent_exact = dict(document)
    inconsistent_exact["total_exact"] = True
    inconsistent_exact["next_cursor"] = "next"
    assert (
        CatalogService._cached_page(
            inconsistent_exact,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )


def test_catalog_tree_cache_is_versioned_scoped_and_response_bounded() -> None:
    workspace_id = uuid4()
    page = CatalogTreePage(
        items=(
            CatalogTreeNode(
                node_id=uuid4(),
                kind="PLATFORM",
                label="postgres",
                asset_count=3,
                has_children=True,
                platform="postgres",
            ),
        ),
        next_cursor=None,
        observed_at=None,
    )
    document = CatalogService._tree_page_document(page, workspace_id=workspace_id)

    assert (
        CatalogService._cached_tree_page(
            document,
            workspace_id=workspace_id,
            limit=1,
        )
        == page
    )
    assert (
        CatalogService._cached_tree_page(
            document,
            workspace_id=uuid4(),
            limit=1,
        )
        is None
    )
    legacy_document = dict(document)
    legacy_document["schema"] = 2
    assert (
        CatalogService._cached_tree_page(
            legacy_document,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )
    invalid_count = dict(document)
    invalid_count["items"] = [
        {**cast(list[dict[str, object]], document["items"])[0], "asset_count": True}
    ]
    assert (
        CatalogService._cached_tree_page(
            invalid_count,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )
    oversized_cursor = dict(document)
    oversized_cursor["next_cursor"] = "x" * 4_097
    assert (
        CatalogService._cached_tree_page(
            oversized_cursor,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )


def test_catalog_facet_cache_is_versioned_scoped_and_response_bounded() -> None:
    workspace_id = uuid4()
    facets = CatalogFacets(
        asset_types=(CatalogFacetBucket("DATASET", 1),),
        platforms=(),
        classifications=(),
        databases=(),
        schemas=(),
        domains=(),
        lifecycles=(),
        observed_at=None,
    )
    document = CatalogService._facets_document(facets, workspace_id=workspace_id)

    assert CatalogService._cached_facets(document, workspace_id=workspace_id, limit=1) == facets
    legacy_document = dict(document)
    legacy_document["schema"] = 2
    assert (
        CatalogService._cached_facets(
            legacy_document,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )
    assert (
        CatalogService._cached_facets(
            document,
            workspace_id=uuid4(),
            limit=1,
        )
        is None
    )

    over_limit = dict(document)
    over_limit["asset_types"] = [
        {"value": "DATASET", "count": 1},
        {"value": "CHART", "count": 1},
    ]
    assert (
        CatalogService._cached_facets(
            over_limit,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )
    invalid_count = dict(document)
    invalid_count["asset_types"] = [{"value": "DATASET", "count": True}]
    assert (
        CatalogService._cached_facets(
            invalid_count,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )


def test_catalog_suggestion_cache_is_scoped_and_response_bounded() -> None:
    workspace_id = uuid4()
    suggestions = CatalogSuggestions(
        items=(
            CatalogSuggestion(
                asset_id=uuid4(),
                name="orders",
                asset_type="DATASET",
                platform="postgres",
                database_name="warehouse",
                schema_name="public",
            ),
        ),
        observed_at=None,
    )
    document = CatalogService._suggestions_document(
        suggestions,
        workspace_id=workspace_id,
    )

    assert (
        CatalogService._cached_suggestions(
            document,
            workspace_id=workspace_id,
            limit=1,
        )
        == suggestions
    )
    assert (
        CatalogService._cached_suggestions(
            document,
            workspace_id=uuid4(),
            limit=1,
        )
        is None
    )
    legacy_document = dict(document)
    legacy_document["schema"] = 2
    assert (
        CatalogService._cached_suggestions(
            legacy_document,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )
    oversized_name = dict(document)
    oversized_name["items"] = [{**document["items"][0], "name": "x" * 501}]
    assert (
        CatalogService._cached_suggestions(
            oversized_name,
            workspace_id=workspace_id,
            limit=1,
        )
        is None
    )


def test_catalog_projection_declares_canonical_hierarchy_and_active_tree_index() -> None:
    table = cast(Table, AssetProjectionModel.__table__)

    assert {
        "database_name",
        "schema_name",
        "owner_ref",
        "domain_ref",
        "tags",
        "glossary_terms",
        "source_created_at",
    } <= set(table.columns.keys())
    tree_index = next(
        index for index in table.indexes if index.name == "ix_assets_projection_tree_active"
    )
    assert [column.name for column in tree_index.columns] == [
        "workspace_id",
        "platform",
        "database_name",
        "schema_name",
        "name",
        "id",
    ]
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_assets_projection_description_bounded",
        "ck_assets_projection_tags_bounded",
        "ck_assets_projection_glossary_terms_bounded",
        "ck_assets_projection_column_names_bounded",
        "ck_assets_projection_tags_string_items",
        "ck_assets_projection_glossary_terms_string_items",
        "ck_assets_projection_column_names_string_items",
        "ck_assets_projection_external_urn_bounded",
    } <= check_names
    assert {
        "description_truncated",
        "tags_truncated",
        "glossary_terms_truncated",
        "column_names_truncated",
    } <= set(table.columns.keys())


def test_catalog_sync_cursor_persistence_is_bounded() -> None:
    table = cast(Table, CatalogSyncRunModel.__table__)
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_sync_runs_next_cursor_bounded" in check_names
    assert "ck_sync_runs_snapshot_evidence_bounded" in check_names
    assert {
        "snapshot_evidence_reference",
        "snapshot_contract_hash",
        "snapshot_provider_version",
    } <= set(table.columns.keys())


def test_catalog_cursor_is_bound_to_the_authorized_request_snapshot() -> None:
    wrapped = CatalogService._wrap_search_cursor("inner-cursor", context="snapshot-a")

    assert (
        CatalogService._unwrap_search_cursor(wrapped, expected_context="snapshot-a")
        == "inner-cursor"
    )
    with pytest.raises(ValidationError, match="stale or does not match"):
        CatalogService._unwrap_search_cursor(wrapped, expected_context="snapshot-b")
    with pytest.raises(ValidationError, match="stale or does not match"):
        CatalogService._unwrap_search_cursor("not-a-cursor", expected_context="snapshot-a")
