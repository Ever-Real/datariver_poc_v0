from __future__ import annotations

import hashlib
import json
from typing import Any

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.domain.authz import SubjectAttributes


def catalog_permission_scope_document(subject: SubjectAttributes) -> dict[str, Any]:
    """Return the canonical security scope used by catalog cursors, caches and exports."""

    return {
        "active": subject.active,
        "clearance": int(subject.clearance),
        "systems": sorted(str(value) for value in subject.allowed_system_ids),
        "domains": sorted(str(value) for value in subject.allowed_domain_ids),
        "actions": sorted(value.value for value in subject.allowed_actions),
        "denies": sorted(value.value for value in subject.denied_actions),
    }


def catalog_permission_scope_hash(subject: SubjectAttributes) -> str:
    return _document_hash(catalog_permission_scope_document(subject))


def catalog_classification_access_document(
    access: ClassificationAccessSnapshot,
) -> dict[str, Any]:
    return {
        "posture": access.posture.value,
        "policy_id": str(access.policy_id) if access.policy_id else None,
        "policy_hash": access.policy_hash,
        "policy_version": access.policy_version,
        "authorization_generation": access.authorization_generation,
        "rules": [
            {
                "classification": int(rule.classification),
                "search_mode": rule.search_mode.value,
            }
            for rule in access.rules
        ],
        "restricted_resources": sorted(str(value) for value in access.restricted_resource_ids),
        "restricted_systems": sorted(str(value) for value in access.restricted_system_ids),
        "restricted_domains": sorted(str(value) for value in access.restricted_domain_ids),
        "admin_quarantine_review": access.admin_quarantine_review,
    }


def catalog_classification_access_hash(access: ClassificationAccessSnapshot) -> str:
    return _document_hash(catalog_classification_access_document(access))


def _document_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
