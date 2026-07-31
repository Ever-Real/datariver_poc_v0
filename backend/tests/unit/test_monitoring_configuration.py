from __future__ import annotations

from uuid import uuid4

import pytest

from datariver.domain.common import ValidationError
from datariver.domain.monitoring import (
    MAX_MONITORING_DASHBOARDS,
    MonitoringDashboardDraft,
    normalize_monitoring_dashboards,
)

APPROVED_ORIGIN = frozenset({"https://grafana.example.com"})


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


def test_monitoring_dashboard_normalization_preserves_bounded_exact_origin_tabs() -> None:
    dashboards = normalize_monitoring_dashboards(
        (
            draft(),
            draft(
                label="DataHub",
                url="https://grafana.example.com/d/datahub",
                height_px=1200,
            ),
        ),
        approved_origins=APPROVED_ORIGIN,
    )

    assert [item.label for item in dashboards] == ["Platform", "DataHub"]
    assert dashboards[1].height_px == 1200
    assert dashboards[0].document()["url"] == ("https://grafana.example.com/d/platform?orgId=1")


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        ("https://other.example.com/d/platform", "deployment-approved Grafana origin"),
        ("https://user:password@grafana.example.com/d/platform", "credential-free"),
        ("javascript:alert(1)", "credential-free"),
    ],
)
def test_monitoring_dashboard_normalization_rejects_unapproved_or_unsafe_urls(
    candidate: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        normalize_monitoring_dashboards(
            (draft(url=candidate),),
            approved_origins=APPROVED_ORIGIN,
        )


def test_monitoring_dashboard_normalization_rejects_duplicates_and_unbounded_input() -> None:
    with pytest.raises(ValidationError, match="labels must be unique"):
        normalize_monitoring_dashboards(
            (draft(label="Platform"), draft(label=" platform ")),
            approved_origins=APPROVED_ORIGIN,
        )

    with pytest.raises(ValidationError, match=f"at most {MAX_MONITORING_DASHBOARDS}"):
        normalize_monitoring_dashboards(
            tuple(draft(label=f"Dashboard {index}") for index in range(9)),
            approved_origins=APPROVED_ORIGIN,
        )


@pytest.mark.parametrize("height_px", [479, 2001])
def test_monitoring_dashboard_normalization_rejects_unbounded_height(height_px: int) -> None:
    with pytest.raises(ValidationError, match="height must be between"):
        normalize_monitoring_dashboards(
            (draft(height_px=height_px),),
            approved_origins=APPROVED_ORIGIN,
        )
