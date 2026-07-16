from __future__ import annotations

from datariver.domain.authz import Classification

CLASSIFICATION_ACCESS_FLOOR_VERSION = "classification-access-floor-v1"


def unconfigured_search_ceiling(clearance: Classification) -> Classification:
    """Fail closed until a governed RESTRICTED-search grant can be evaluated."""

    return min(clearance, Classification.CONFIDENTIAL)


def unconfigured_chat_ceiling(clearance: Classification) -> Classification:
    """Fail closed until an approved provider/profile policy can be evaluated."""

    return min(clearance, Classification.INTERNAL)


def unconfigured_chat_evidence_allowed(classification: Classification) -> bool:
    return classification <= Classification.INTERNAL
