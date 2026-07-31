from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from datariver.interfaces.http.schemas import CatalogSchemaMetricResponse


class DashboardSummaryResponse(BaseModel):
    """Ordinary home-dashboard facts without operational or audit telemetry."""

    observed_at: datetime
    changes_by_state: dict[str, int]
    catalog_asset_count: int
    catalog_described_asset_count: int
    catalog_glossary_term_count: int
    catalog_schema_metrics: list[CatalogSchemaMetricResponse]
    catalog_schema_metrics_truncated: bool
