from __future__ import annotations

from uuid import uuid4

import pytest

from datariver.config import Settings
from datariver.domain.common import ValidationError
from datariver.domain.monitoring import (
    MAX_MONITORING_DASHBOARDS,
    MonitoringDashboardDraft,
    normalize_monitoring_dashboards,
)
from datariver.infrastructure.db.models.platform import MonitoringConfigurationModel
from datariver.interfaces.http.monitoring_configuration import monitoring_configuration_response


def draft(
    *,
    label: str = "Platform",
    url: str = "https://grafana.example.com/d/platform?orgId=1",
    height_px: int = 900,
) -> MonitoringDashboardDraft:
    return MonitoringDashboardDraft(
        dashboard_id=uuid4(),
        label=label,
        url=url,
        height_px=height_px,
    )


def test_monitoring_dashboard_normalization_accepts_bounded_http_dashboard_links() -> None:
    dashboards = normalize_monitoring_dashboards(
        (
            draft(),
            draft(
                label="Prometheus",
                url="https://prometheus.example.com/graph?g0.expr=up",
                height_px=1200,
            ),
        )
    )

    assert [item.label for item in dashboards] == ["Platform", "Prometheus"]
    assert dashboards[1].height_px == 1200
    assert dashboards[0].document()["url"] == ("https://grafana.example.com/d/platform?orgId=1")


def test_persisted_administrator_dashboard_link_is_an_embed_descriptor() -> None:
    workspace_id = uuid4()
    configuration = MonitoringConfigurationModel(
        workspace_id=workspace_id,
        dashboards=[
            {
                "id": str(uuid4()),
                "label": "Vendor status",
                "url": "https://status.example.com/platform",
                "height_px": 900,
            }
        ],
        payload_hash="0" * 64,
        updated_by=uuid4(),
        version=1,
    )

    result = monitoring_configuration_response(
        settings=Settings.model_construct(),
        workspace_id=workspace_id,
        configuration=configuration,
    )

    assert result.items[0].embed_state == "AVAILABLE"
    assert str(result.items[0].embed_url) == "https://status.example.com/platform"


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        ("https://user:password@grafana.example.com/d/platform", "credential-free"),
        ("javascript:alert(1)", "credential-free"),
    ],
)
def test_monitoring_dashboard_normalization_rejects_unsafe_urls(
    candidate: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        normalize_monitoring_dashboards((draft(url=candidate),))


def test_monitoring_dashboard_normalization_rejects_duplicates_and_unbounded_input() -> None:
    with pytest.raises(ValidationError, match="labels must be unique"):
        normalize_monitoring_dashboards(
            (draft(label="Platform"), draft(label=" platform ")),
        )

    with pytest.raises(ValidationError, match=f"at most {MAX_MONITORING_DASHBOARDS}"):
        normalize_monitoring_dashboards(
            tuple(draft(label=f"Dashboard {index}") for index in range(9)),
        )


@pytest.mark.parametrize("height_px", [479, 2001])
def test_monitoring_dashboard_normalization_rejects_unbounded_height(height_px: int) -> None:
    with pytest.raises(ValidationError, match="height must be between"):
        normalize_monitoring_dashboards((draft(height_px=height_px),))
