from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from datariver.config import Settings
from datariver.infrastructure.db.models.platform import MonitoringConfigurationModel
from datariver.interfaces.http.schemas import (
    MonitoringConfigurationResponse,
    MonitoringDashboardResponse,
)


def monitoring_configuration_response(
    *,
    settings: Settings,
    workspace_id: UUID,
    configuration: MonitoringConfigurationModel | None,
) -> MonitoringConfigurationResponse:
    if configuration is None:
        documents = _deployment_default_documents(settings=settings, workspace_id=workspace_id)
        version = 0
        administrator_approved = False
    else:
        documents = configuration.dashboards
        version = configuration.version
        administrator_approved = True
    items = [
        _dashboard_response(
            settings=settings,
            document=document,
            administrator_approved=administrator_approved,
        )
        for document in documents
    ]
    return MonitoringConfigurationResponse(items=items, version=version)


def _deployment_default_documents(
    *,
    settings: Settings,
    workspace_id: UUID,
) -> list[dict[str, Any]]:
    if settings.ui_grafana_url is None:
        return []
    url = str(settings.ui_grafana_url)
    return [
        {
            "id": str(uuid5(NAMESPACE_URL, f"datariver:{workspace_id}:monitoring:{url}")),
            "label": "Infrastructure",
            "url": url,
            "height_px": 900,
        }
    ]


def _dashboard_response(
    *,
    settings: Settings,
    document: dict[str, Any],
    administrator_approved: bool,
) -> MonitoringDashboardResponse:
    url = str(document["url"])
    embed_url = url if administrator_approved else settings.grafana_embed_url(url)
    return MonitoringDashboardResponse(
        id=UUID(str(document["id"])),
        label=str(document["label"]),
        url=url,
        height_px=int(document["height_px"]),
        embed_state="AVAILABLE" if embed_url is not None else "DISABLED",
        embed_url=embed_url,
    )
