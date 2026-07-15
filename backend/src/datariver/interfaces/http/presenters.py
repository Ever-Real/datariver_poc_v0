from __future__ import annotations

from datariver.application.dto import CatalogAssetDetail, CatalogAssetIndex
from datariver.domain.governance import ChangeRequest
from datariver.interfaces.http.schemas import (
    ApprovalResponse,
    CatalogAssetResponse,
    CatalogAssetSummary,
    ChangeItemResponse,
    ChangeRequestResponse,
    TransitionResponse,
)


def catalog_summary(asset: CatalogAssetIndex) -> CatalogAssetSummary:
    return CatalogAssetSummary(
        id=asset.asset_id,
        external_urn=asset.external_urn,
        asset_type=asset.asset_type,
        name=asset.name,
        description=asset.description,
        platform=asset.platform,
        classification=asset.classification.name,
        lifecycle=asset.lifecycle,
        observed_at=asset.observed_at,
    )


def catalog_detail(asset: CatalogAssetDetail) -> CatalogAssetResponse:
    summary = catalog_summary(asset.index)
    return CatalogAssetResponse(
        **summary.model_dump(),
        ownership=list(asset.ownership),
        glossary_terms=list(asset.glossary_terms),
        tags=list(asset.tags),
        schema_fields=list(asset.schema_fields),
        quality=asset.quality,
        source_version=asset.raw_version,
        stale_at=asset.stale_at,
    )


def change_request_response(change_request: ChangeRequest) -> ChangeRequestResponse:
    return ChangeRequestResponse(
        id=change_request.change_request_id,
        number=change_request.number,
        request_type=change_request.request_type,
        title=change_request.title,
        description=change_request.description,
        state=change_request.state.value,
        requester_id=change_request.requester_id,
        classification=change_request.classification.name,
        version=change_request.version,
        items=[
            ChangeItemResponse(
                id=item.item_id,
                target_type=item.target_type,
                target_ref=item.target_ref,
                aspect_name=item.aspect_name,
                operation=item.operation,
                before_hash=item.before_hash,
                after_hash=item.after_hash,
            )
            for item in change_request.items
        ],
        approvals=[
            ApprovalResponse(
                id=approval.approval_id,
                stage=approval.stage,
                decision=approval.decision.value,
                actor_id=approval.actor_id,
                reason=approval.reason,
                occurred_at=approval.occurred_at,
            )
            for approval in change_request.approvals
        ],
        transitions=[
            TransitionResponse(
                id=transition.transition_id,
                from_state=transition.from_state.value,
                to_state=transition.to_state.value,
                actor_id=transition.actor_id,
                reason=transition.reason,
                occurred_at=transition.occurred_at,
            )
            for transition in change_request.transitions
        ],
    )
