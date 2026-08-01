from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from datariver.application.dto import CatalogAssetDetail, CatalogAssetIndex, CatalogPage
from datariver.application.services.catalog import CatalogService
from datariver.application.services.knowledge_studio_catalog import (
    CatalogKnowledgeStudioSourceReader,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog import DATASET_ASSET_TYPES
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_studio_proposal_jobs import (
    KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
    KnowledgeStudioCatalogFieldMetadataPin,
    KnowledgeStudioCatalogSourcePin,
)
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2")
ASSET_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b4")
NOW = datetime(2026, 7, 28, 1, 2, 3, tzinfo=UTC)


def subject() -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.RESTRICTED,
        allowed_domain_ids=frozenset(),
        allowed_actions=frozenset({Action.KG_EDIT}),
    )


def asset() -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=ASSET_ID,
        workspace_id=WORKSPACE_ID,
        external_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,hr.employee,PROD)",
        asset_type="DATASET",
        name="hr_employee",
        description=None,
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="projection-v1",
        observed_at=NOW,
        database_name="hr",
        schema_name="public",
        domain="Finance",
        tags=("PII",),
        glossary_terms=("Employee",),
        column_names=("fallback_id",),
    )


@pytest.mark.asyncio
async def test_studio_source_search_uses_the_authorized_dataset_projection_only() -> None:
    catalog = SimpleNamespace(
        search=AsyncMock(
            return_value=CatalogPage(
                items=(asset(),),
                next_cursor="next",
                observed_at=NOW,
            )
        )
    )
    reader = CatalogKnowledgeStudioSourceReader(cast(CatalogService, catalog))
    environment = EnvironmentAttributes(requested_at=NOW)

    page = await reader.search_datasets(
        subject=subject(),
        maximum_classification=Classification.INTERNAL,
        query="employee",
        cursor=None,
        limit=25,
        environment=environment,
        request_id="request",
    )

    assert page.items[0].field_paths == ()
    assert page.items[0].fields_truncated is True
    assert page.items[0].source_version == "projection-v1"
    assert page.items[0].projection_source_version == "projection-v1"
    assert page.items[0].domain == "Finance"
    assert page.items[0].tags == ("PII",)
    catalog.search.assert_awaited_once_with(
        subject=subject(),
        query="employee",
        filters={
            "asset_types": sorted(DATASET_ASSET_TYPES),
            "classification_ceiling": int(Classification.INTERNAL),
        },
        cursor=None,
        limit=25,
        environment=environment,
        request_id="request",
    )


@pytest.mark.asyncio
async def test_studio_source_search_forwards_catalog_domain_and_search_fields() -> None:
    catalog = SimpleNamespace(
        search=AsyncMock(
            return_value=CatalogPage(items=(asset(),), next_cursor=None, observed_at=NOW)
        )
    )
    reader = CatalogKnowledgeStudioSourceReader(cast(CatalogService, catalog))
    environment = EnvironmentAttributes(requested_at=NOW)

    await reader.search_datasets(
        subject=subject(),
        maximum_classification=Classification.INTERNAL,
        query="PII employee",
        cursor=None,
        limit=25,
        environment=environment,
        request_id="request",
        domain="Finance",
        search_fields="TABLE,COLUMN,TAG,TERM",
    )

    catalog.search.assert_awaited_once_with(
        subject=subject(),
        query="PII employee",
        filters={
            "asset_types": sorted(DATASET_ASSET_TYPES),
            "classification_ceiling": int(Classification.INTERNAL),
            "domain": "Finance",
            "search_fields": "TABLE,COLUMN,TAG,TERM",
        },
        cursor=None,
        limit=25,
        environment=environment,
        request_id="request",
    )


@pytest.mark.asyncio
async def test_studio_source_detail_pins_datahub_schema_version_and_typed_field_paths() -> None:
    indexed_asset = replace(
        asset(),
        tags=("PII", "urn:li:tag:restricted"),
        glossary_terms=("Employee", "urn:li:glossaryTerm:restricted"),
    )
    detail = CatalogAssetDetail(
        index=indexed_asset,
        ownership=(),
        glossary_terms=(),
        tags=(),
        schema_fields=(
            {
                "fieldPath": "emp_id",
                "type": "KEY",
                "nativeDataType": "uuid",
                "description": "Employee identifier",
                "description_truncated": False,
                "globalTags": {
                    "tags": [
                        {"tag": {"name": "PII"}},
                        {"tag": {"urn": "urn:li:tag:restricted"}},
                        {"tag": {"name": "urn:li:tag:name-form-restricted"}},
                    ]
                },
                "tags_truncated": False,
                "glossaryTerms": {
                    "terms": [
                        {"term": {"name": "Employee"}},
                        {"term": {"name": "urn:li:glossaryTerm:restricted"}},
                    ]
                },
                "terms_truncated": False,
            },
            {
                "fieldPath": "emp_nm",
                "nativeDataType": "varchar",
                "description": "N" * 1_001,
                "globalTags": {
                    "tags": [{"tag": {"name": f"tag-{index}"}} for index in range(20)]
                    + [{"tag": {"name": "x" * 241}}]
                },
                "glossaryTerms": {"terms": []},
            },
            {"fieldPath": "emp_nm"},
            {"fieldPath": "x" * 2_001},
            {"fieldPath": " surrounding "},
            {"providerExpression": "DROP"},
        ),
        quality={},
        raw_version="datahub-v7",
        observed_at=NOW,
    )
    catalog = SimpleNamespace(get_asset=AsyncMock(return_value=detail))
    reader = CatalogKnowledgeStudioSourceReader(cast(CatalogService, catalog))

    result = await reader.get_dataset(
        subject=subject(),
        asset_id=ASSET_ID,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result is not None
    assert result.dataset.source_version == "datahub-v7"
    assert result.dataset.projection_source_version == "projection-v1"
    assert result.dataset.field_paths == ("emp_id", "emp_nm")
    assert result.dataset.fields_truncated is True
    assert result.dataset.field_metadata[0].field_type == "KEY"
    assert result.dataset.field_metadata[0].tags == ("PII",)
    assert result.dataset.field_metadata[0].tags_truncated is True
    assert result.dataset.field_metadata[0].glossary_terms == ("Employee",)
    assert result.dataset.field_metadata[0].terms_truncated is True
    assert result.dataset.tags == ("PII",)
    assert result.dataset.glossary_terms == ("Employee",)
    assert "urn:" not in repr(result.dataset)
    assert result.dataset.field_metadata[1].description == "N" * 1_000
    assert result.dataset.field_metadata[1].description_truncated is True
    assert len(result.dataset.field_metadata[1].tags) == 20
    assert result.dataset.field_metadata[1].tags_truncated is True
    assert result.dataset.selection_fingerprint is not None
    assert len(result.dataset.selection_fingerprint) == 64
    assert not hasattr(result.dataset, "external_urn")

    source_pin = KnowledgeStudioCatalogSourcePin(
        asset_id=result.dataset.asset_id,
        name=result.dataset.name,
        asset_type=result.dataset.asset_type,
        classification=int(result.dataset.classification),
        source_version=result.dataset.source_version,
        projection_source_version=result.dataset.projection_source_version,
        selected_field_paths=result.dataset.field_paths,
        platform=result.dataset.platform,
        database_name=result.dataset.database_name,
        schema_name=result.dataset.schema_name,
        domain=result.dataset.domain,
        tags=result.dataset.tags,
        glossary_terms=result.dataset.glossary_terms,
        contract_version=KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
        description=result.dataset.description,
        description_truncated=result.dataset.description_truncated,
        field_metadata=tuple(
            KnowledgeStudioCatalogFieldMetadataPin(
                field_path=field.field_path,
                field_type=field.field_type,
                native_data_type=field.native_data_type,
                description=field.description,
                description_truncated=field.description_truncated,
                tags=field.tags,
                tags_truncated=field.tags_truncated,
                glossary_terms=field.glossary_terms,
                terms_truncated=field.terms_truncated,
            )
            for field in result.dataset.field_metadata
        ),
    ).with_computed_metadata_fingerprint()
    assert "urn:" not in repr(source_pin.to_document())

    sanitized_detail = replace(
        detail,
        index=replace(
            indexed_asset,
            tags=("PII",),
            glossary_terms=("Employee",),
        ),
    )
    catalog.get_asset.return_value = sanitized_detail
    sanitized = await reader.get_dataset(
        subject=subject(),
        asset_id=ASSET_ID,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request-sanitized",
    )
    assert sanitized is not None
    assert sanitized.dataset.selection_fingerprint == result.dataset.selection_fingerprint

    changed_detail = replace(
        sanitized_detail,
        schema_fields=(
            {**detail.schema_fields[0], "description": "Changed identifier"},
            *detail.schema_fields[1:],
        ),
    )
    catalog.get_asset.return_value = changed_detail
    changed = await reader.get_dataset(
        subject=subject(),
        asset_id=ASSET_ID,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request-changed",
    )
    assert changed is not None
    assert changed.dataset.selection_fingerprint != result.dataset.selection_fingerprint


@pytest.mark.asyncio
async def test_studio_source_access_revalidation_uses_one_authorized_catalog_set() -> None:
    catalog = SimpleNamespace(get_asset_indexes=AsyncMock(return_value=(asset(),)))
    reader = CatalogKnowledgeStudioSourceReader(cast(CatalogService, catalog))

    result = await reader.validate_dataset_access(
        subject=subject(),
        asset_ids=(ASSET_ID,),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result[0].asset_id == ASSET_ID
    assert result[0].projection_source_version == "projection-v1"
    catalog.get_asset_indexes.assert_awaited_once_with(
        subject=subject(),
        asset_ids=(ASSET_ID,),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )


def test_internal_dataset_search_filter_enforces_a_typed_classification_ceiling() -> None:
    conditions = SqlCatalogIndexReader._filter_conditions(
        {
            "asset_types": sorted(DATASET_ASSET_TYPES),
            "classification_ceiling": int(Classification.INTERNAL),
        }
    )

    assert any("assets_projection.classification <=" in str(condition) for condition in conditions)
    with pytest.raises(ValidationError, match="classification ceiling"):
        SqlCatalogIndexReader._filter_conditions({"classification_ceiling": True})
