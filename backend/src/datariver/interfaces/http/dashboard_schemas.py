from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from datariver.application.change_request_read import ChangeRequestStateGroup
from datariver.interfaces.http.schemas import CatalogSchemaMetricResponse


class ChangeRequestProgressResponse(BaseModel):
    total: int | None
    groups: dict[ChangeRequestStateGroup, int | None]
    complete: bool


class DashboardSummaryResponse(BaseModel):
    """Ordinary home-dashboard facts without operational or audit telemetry."""

    observed_at: datetime
    changes_by_state: dict[str, int] | None
    change_request_progress: ChangeRequestProgressResponse
    catalog_asset_count: int
    catalog_described_asset_count: int
    catalog_glossary_term_count: int
    catalog_schema_metrics: list[CatalogSchemaMetricResponse]
    catalog_schema_metrics_truncated: bool
