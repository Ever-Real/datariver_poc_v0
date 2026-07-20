from datetime import UTC, datetime
from uuid import uuid4

from datariver.application.dto import CatalogAssetDetail, CatalogAssetIndex
from datariver.domain.authz import Classification
from datariver.interfaces.http.presenters import catalog_detail, catalog_summary


def test_catalog_summary_preserves_projected_term_and_tag_arrays() -> None:
    observed_at = datetime.now(UTC)
    asset = CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=uuid4(),
        external_urn="urn:li:dataset:semiconductor",
        asset_type="TABLE",
        name="wafer_events",
        description="Wafer event evidence",
        platform="postgres",
        database_name="semiconductor",
        schema_name="manufacturing",
        owner="urn:li:corpGroup:data-stewards",
        domain="urn:li:domain:manufacturing",
        tags=("datariver_semiconductor", "tier:gold"),
        glossary_terms=("semiconductor_scenario", "wafer"),
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.CONFIDENTIAL,
        lifecycle="ACTIVE",
        source_version="projection-v1",
        observed_at=observed_at,
    )

    response = catalog_summary(asset)

    assert response.tags == ["datariver_semiconductor", "tier:gold"]
    assert response.terms == ["semiconductor_scenario", "wafer"]
    assert response.model_dump(mode="json")["tags"] == [
        "datariver_semiconductor",
        "tier:gold",
    ]
    assert response.model_dump(mode="json")["terms"] == [
        "semiconductor_scenario",
        "wafer",
    ]


def test_catalog_detail_distinguishes_projection_and_provider_versions() -> None:
    observed_at = datetime.now(UTC)
    index = CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=uuid4(),
        external_urn="urn:li:dataset:semiconductor",
        asset_type="VIEW",
        name="supplier_qualification",
        description=None,
        platform="postgres",
        database_name="datariver",
        schema_name="semiconductor_seed",
        owner=None,
        domain=None,
        tags=(),
        glossary_terms=(),
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.CONFIDENTIAL,
        lifecycle="ACTIVE",
        source_version="projection-v1",
        observed_at=observed_at,
    )
    detail = CatalogAssetDetail(
        index=index,
        ownership=(),
        glossary_terms=(),
        tags=(),
        schema_fields=(),
        quality={},
        raw_version="datahub-v3",
        observed_at=observed_at,
    )

    response = catalog_detail(detail)

    assert response.projection_source_version == "projection-v1"
    assert response.source_version == "datahub-v3"
