from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import PurePath

from datariver.domain.common import ValidationError

_UNSAFE_COMPONENT = re.compile(r"[^\w가-힣-]+", flags=re.UNICODE)
_REPEATED_SEPARATOR = re.compile(r"[_-]{2,}")
_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,12}$")


def governance_document_storage_stem(
    *,
    prefix: str,
    title: str,
    registered_at: datetime,
    serial_number: int,
) -> str:
    if prefix not in {"doc_governance", "ref_governance"}:
        raise ValueError("Governance document storage prefix is invalid.")
    if registered_at.tzinfo is None:
        raise ValueError("Governance document registration time must be timezone-aware.")
    if not 1 <= serial_number <= 999_999_999:
        raise ValidationError("Governance document storage serial is outside the safe range.")
    normalized = unicodedata.normalize("NFKC", title).strip()
    component = _UNSAFE_COMPONENT.sub("_", normalized)
    component = _REPEATED_SEPARATOR.sub("_", component).strip("._-")[:80].rstrip("._-")
    if not component:
        component = "document"
    return f"{prefix}_{component}_{registered_at.date().strftime('%Y%m%d')}_{serial_number:03d}"


def governance_document_attachment_filename(
    *,
    title: str,
    registered_at: datetime,
    serial_number: int,
    original_name: str,
) -> str:
    suffix = PurePath(original_name).suffix.casefold()
    safe_suffix = suffix if _SAFE_EXTENSION.fullmatch(suffix) is not None else ""
    return (
        governance_document_storage_stem(
            prefix="ref_governance",
            title=title,
            registered_at=registered_at,
            serial_number=serial_number,
        )
        + safe_suffix
    )
