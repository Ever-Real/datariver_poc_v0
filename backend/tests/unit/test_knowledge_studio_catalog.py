from __future__ import annotations

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
async def test_studio_source_detail_pins_datahub_schema_version_and_typed_field_paths() -> None:
    detail = CatalogAssetDetail(
        index=asset(),
        ownership=(),
        glossary_terms=(),
        tags=(),
        schema_fields=(
            {"fieldPath": "emp_id", "nativeDataType": "uuid"},
            {"fieldPath": "emp_nm", "nativeDataType": "varchar"},
            {"fieldPath": "emp_nm"},
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
    assert not hasattr(result.dataset, "external_urn")


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
