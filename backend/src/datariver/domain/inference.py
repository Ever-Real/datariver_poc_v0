from __future__ import annotations

import re

_MODEL_ID_PATTERN = re.compile(r"/?[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_API_PATH_PATTERN = re.compile(r"/[A-Za-z0-9._~/-]{0,511}")


def is_valid_inference_model_identity(value: str) -> bool:
    """Accept opaque provider model IDs without accepting URL/query syntax."""

    normalized = value.strip()
    if (
        normalized != value
        or len(normalized) > 128
        or _MODEL_ID_PATTERN.fullmatch(normalized) is None
    ):
        return False
    segments = normalized.lstrip("/").split("/")
    return all(segment not in {"", ".", ".."} for segment in segments)


def is_safe_inference_api_base_path(
    path: str,
    *,
    terminal_segment: str | None = None,
) -> bool:
    """Validate a deployment-owned API prefix before fixed server routes are appended."""

    normalized = path.rstrip("/")
    if _API_PATH_PATTERN.fullmatch(normalized) is None or "//" in normalized:
        return False
    segments = normalized.lstrip("/").split("/")
    if not segments or any(segment in {"", ".", ".."} for segment in segments):
        return False
    return terminal_segment is None or segments[-1] == terminal_segment
