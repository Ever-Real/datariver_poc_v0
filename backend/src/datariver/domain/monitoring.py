from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from datariver.domain.common import ValidationError, uuid7

MAX_MONITORING_DASHBOARDS = 8
MIN_DASHBOARD_HEIGHT_PX = 480
MAX_DASHBOARD_HEIGHT_PX = 2000


@dataclass(frozen=True, slots=True)
class MonitoringDashboardDraft:
    dashboard_id: UUID | None
    label: str
    url: str
    height_px: int


@dataclass(frozen=True, slots=True)
class MonitoringDashboard:
    dashboard_id: UUID
    label: str
    url: str
    height_px: int

    def document(self) -> dict[str, str | int]:
        return {
            "id": str(self.dashboard_id),
            "label": self.label,
            "url": self.url,
            "height_px": self.height_px,
        }


def monitoring_origin(url: str) -> str | None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_monitoring_dashboards(
    drafts: tuple[MonitoringDashboardDraft, ...],
) -> tuple[MonitoringDashboard, ...]:
    if len(drafts) > MAX_MONITORING_DASHBOARDS:
        raise ValidationError(
            f"Monitoring configuration supports at most {MAX_MONITORING_DASHBOARDS} dashboards."
        )
    normalized: list[MonitoringDashboard] = []
    labels: set[str] = set()
    dashboard_ids: set[UUID] = set()
    for draft in drafts:
        label = draft.label.strip()
        if not label or len(label) > 80:
            raise ValidationError("Monitoring dashboard labels must contain 1 to 80 characters.")
        folded_label = label.casefold()
        if folded_label in labels:
            raise ValidationError("Monitoring dashboard labels must be unique.")
        labels.add(folded_label)

        url = draft.url.strip()
        if len(url) > 2000:
            raise ValidationError("Monitoring dashboard URLs cannot exceed 2000 characters.")
        origin = monitoring_origin(url)
        if origin is None:
            raise ValidationError(
                "Monitoring dashboard URLs must be credential-free HTTP or HTTPS URLs."
            )
        if not MIN_DASHBOARD_HEIGHT_PX <= draft.height_px <= MAX_DASHBOARD_HEIGHT_PX:
            raise ValidationError(
                "Monitoring dashboard height must be between "
                f"{MIN_DASHBOARD_HEIGHT_PX} and {MAX_DASHBOARD_HEIGHT_PX} pixels."
            )

        dashboard_id = draft.dashboard_id or uuid7()
        if dashboard_id in dashboard_ids:
            raise ValidationError("Monitoring dashboard identifiers must be unique.")
        dashboard_ids.add(dashboard_id)
        normalized.append(
            MonitoringDashboard(
                dashboard_id=dashboard_id,
                label=label,
                url=url,
                height_px=draft.height_px,
            )
        )
    return tuple(normalized)
