from __future__ import annotations

from typing import Any

from sqlalchemy import and_, false, or_

from datariver.application.classification_access import (
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.classification_access import SearchMode
from datariver.infrastructure.db.models.catalog import AssetProjectionModel


def catalog_asset_scope_conditions(
    subject: SubjectAttributes,
    access: ClassificationAccessSnapshot | None = None,
    *,
    include_quarantine_review: bool = False,
) -> list[Any]:
    """Return the canonical authorization-pruned Catalog asset predicate.

    Read models must use this predicate before aggregating so rows hidden from a
    caller cannot influence cards, trends, facets, issue counts, or cursors.
    """

    resolved_access = access or static_classification_access_floor()
    if include_quarantine_review and resolved_access.admin_quarantine_review:
        return [
            AssetProjectionModel.workspace_id == subject.workspace_id,
            AssetProjectionModel.deleted_at.is_(None),
        ]
    standard_classifications = tuple(
        int(classification)
        for classification in Classification
        if classification is not Classification.RESTRICTED
        and classification <= subject.clearance
        and resolved_access.rule_for(classification).search_mode is SearchMode.ABAC
    )
    restricted_scope: Any = false()
    restricted_rule = resolved_access.rule_for(Classification.RESTRICTED)
    if (
        subject.clearance >= Classification.RESTRICTED
        and restricted_rule.search_mode is SearchMode.EXPLICIT_GRANT_ONLY
    ):
        scoped_conditions: list[Any] = []
        if resolved_access.restricted_resource_ids:
            scoped_conditions.append(
                AssetProjectionModel.id.in_(resolved_access.restricted_resource_ids)
            )
        if resolved_access.restricted_system_ids:
            scoped_conditions.append(
                AssetProjectionModel.system_id.in_(resolved_access.restricted_system_ids)
            )
        if resolved_access.restricted_domain_ids:
            scoped_conditions.append(
                AssetProjectionModel.domain_id.in_(resolved_access.restricted_domain_ids)
            )
        restricted_scope = or_(*scoped_conditions) if scoped_conditions else false()
    return [
        AssetProjectionModel.workspace_id == subject.workspace_id,
        AssetProjectionModel.deleted_at.is_(None),
        AssetProjectionModel.lifecycle == "ACTIVE",
        or_(
            AssetProjectionModel.classification.in_(standard_classifications),
            and_(
                AssetProjectionModel.classification == int(Classification.RESTRICTED),
                restricted_scope,
            ),
        ),
        or_(
            AssetProjectionModel.classification == int(Classification.PUBLIC),
            and_(
                AssetProjectionModel.system_id.is_not(None),
                AssetProjectionModel.system_id.in_(subject.allowed_system_ids),
            ),
        ),
        or_(
            AssetProjectionModel.classification == int(Classification.PUBLIC),
            and_(
                AssetProjectionModel.domain_id.is_not(None),
                AssetProjectionModel.domain_id.in_(subject.allowed_domain_ids),
            ),
        ),
    ]
