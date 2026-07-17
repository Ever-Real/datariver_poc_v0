from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

SYSTEM_SLUG = re.compile(r"[^A-Z0-9]+")


def change_request_number(
    system_name: str | None,
    *,
    occurred_at: datetime | None = None,
    random4: str | None = None,
) -> str:
    """Create a display identifier; the workspace unique constraint remains authoritative."""
    slug = SYSTEM_SLUG.sub("-", (system_name or "DATARIVER").upper()).strip("-")[:32]
    timestamp = occurred_at or datetime.now(UTC)
    suffix = (random4 or secrets.token_hex(2).upper()).upper()
    if not slug:
        slug = "DATARIVER"
    if re.fullmatch(r"[A-Z0-9]{4}", suffix) is None:
        raise ValueError("random4 must contain exactly four uppercase letters or digits")
    return f"CR-{slug}-{timestamp:%y%m%d}-{suffix}"
