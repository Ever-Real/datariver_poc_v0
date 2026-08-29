from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import Action, Classification, ResourceAttributes
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogVocabularyEntryModel,
)
from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.integration import (
    JobModel,
    ObjectManifestModel,
    OutboxEventModel,
)
from datariver.interfaces.http.dashboard_schemas import DashboardSummaryResponse
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    CatalogSchemaMetricResponse,
    OperationsSummaryResponse,
)

router = APIRouter(prefix="/operations", tags=["operations"])


async def _authorize_operations(request: Request, context: ContextDep) -> None:
    container = get_container(request)
    await AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    ).authorize(
        subject=context.subject,
        resource=ResourceAttributes(
            resource_id=context.workspace_id,
            workspace_id=context.workspace_id,
            resource_type="operations",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.INTERNAL,
            lifecycle="ACTIVE",
        ),
        action=Action.OPERATIONS_READ,
        environment=context.environment,
        request_id=context.request_id,
    )


async def _authorize_dashboard(request: Request, context: ContextDep) -> None:
    container = get_container(request)
    await AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    ).authorize(
        subject=context.subject,
        resource=ResourceAttributes(
            resource_id=context.workspace_id,
            workspace_id=context.workspace_id,
            resource_type="dashboard",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.PUBLIC,
            lifecycle="ACTIVE",
        ),
        action=Action.DASHBOARD_READ,
        environment=context.environment,
        request_id=context.request_id,
    )


async def _state_counts(
    session: AsyncSession,
    state: InstrumentedAttribute[str],
    workspace: InstrumentedAttribute[UUID],
    workspace_id: UUID,
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(state, func.count()).where(workspace == workspace_id).group_by(state)
        )
    ).all()
    return {str(name): int(count) for name, count in rows}


async def _catalog_coverage(
    session: AsyncSession,
    workspace_id: UUID,
) -> tuple[int, int, list[CatalogSchemaMetricResponse], bool]:
    """Return bounded, source-derived dashboard coverage without provider calls.

    The operations dashboard is authorized independently from catalog discovery.
    It therefore reports workspace-level projection aggregates only, never asset
    names, URNs, classifications, tags, glossary terms, or DataHub documents.
    """

    description_present = func.nullif(func.btrim(AssetProjectionModel.description), "").is_not(None)
    tags_present = func.jsonb_array_length(AssetProjectionModel.tags) > 0
    terms_present = func.jsonb_array_length(AssetProjectionModel.glossary_terms) > 0
    scope = (
        AssetProjectionModel.workspace_id == workspace_id,
        AssetProjectionModel.deleted_at.is_(None),
        AssetProjectionModel.lifecycle == "ACTIVE",
    )
    asset_count, described_asset_count = (
        await session.execute(
            select(
                func.count(AssetProjectionModel.id),
                func.coalesce(
                    func.sum(case((description_present, 1), else_=0)),
                    0,
                ),
            ).where(*scope)
        )
    ).one()
    # A dashboard is not an unbounded hierarchy browser.  The extra row makes
    # truncation explicit instead of silently presenting a partial result.
    metric_rows = (
        await session.execute(
            select(
                AssetProjectionModel.platform,
                AssetProjectionModel.database_name,
                AssetProjectionModel.schema_name,
                func.count(AssetProjectionModel.id),
                func.coalesce(
                    func.sum(case((description_present, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((tags_present, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((terms_present, 1), else_=0)),
                    0,
                ),
            )
            .where(*scope)
            .group_by(
                AssetProjectionModel.platform,
                AssetProjectionModel.database_name,
                AssetProjectionModel.schema_name,
            )
            .order_by(
                func.count(AssetProjectionModel.id).desc(),
                AssetProjectionModel.platform.asc().nulls_last(),
                AssetProjectionModel.database_name.asc().nulls_last(),
                AssetProjectionModel.schema_name.asc().nulls_last(),
            )
            .limit(201)
        )
    ).all()
    truncated = len(metric_rows) > 200
    return (
        int(asset_count),
        int(described_asset_count),
        [
            CatalogSchemaMetricResponse(
                platform=platform,
                database_name=database_name,
                schema_name=schema_name,
                asset_count=int(count),
                described_asset_count=int(descriptions),
                tagged_asset_count=int(tagged),
                term_asset_count=int(terms),
            )
            for (
                platform,
                database_name,
                schema_name,
                count,
                descriptions,
                tagged,
                terms,
            ) in metric_rows[:200]
        ],
        truncated,
    )


async def _catalog_glossary_term_count(
    session: AsyncSession,
    workspace_id: UUID,
) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(CatalogVocabularyEntryModel)
        .where(
            CatalogVocabularyEntryModel.workspace_id == workspace_id,
            CatalogVocabularyEntryModel.kind == "TERM",
            CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
        )
    )
    return int(value or 0)


@router.get("/dashboard", response_model=DashboardSummaryResponse)
async def dashboard(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> DashboardSummaryResponse:
    """Return bounded home-dashboard facts without operator-only telemetry."""

    await _authorize_dashboard(request, context)
    (
        catalog_asset_count,
        catalog_described_asset_count,
        catalog_schema_metrics,
        catalog_schema_metrics_truncated,
    ) = await _catalog_coverage(session, context.workspace_id)
    return DashboardSummaryResponse(
        observed_at=datetime.now(UTC),
        changes_by_state=await _state_counts(
            session,
            ChangeRequestModel.state,
            ChangeRequestModel.workspace_id,
            context.workspace_id,
        ),
        catalog_asset_count=catalog_asset_count,
        catalog_described_asset_count=catalog_described_asset_count,
        catalog_glossary_term_count=await _catalog_glossary_term_count(
            session,
            context.workspace_id,
        ),
        catalog_schema_metrics=catalog_schema_metrics,
        catalog_schema_metrics_truncated=catalog_schema_metrics_truncated,
    )


@router.get("/summary", response_model=OperationsSummaryResponse)
async def summary(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> OperationsSummaryResponse:
    await _authorize_operations(request, context)
    observed_at = datetime.now(UTC)
    outbox_count, oldest = (
        await session.execute(
            select(func.count(), func.min(OutboxEventModel.created_at)).where(
                OutboxEventModel.workspace_id == context.workspace_id,
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.dead_lettered_at.is_(None),
            )
        )
    ).one()
    dead_letter_count = await session.scalar(
        select(func.count()).where(
            OutboxEventModel.workspace_id == context.workspace_id,
            OutboxEventModel.dead_lettered_at.is_not(None),
        )
    )
    (
        catalog_asset_count,
        catalog_described_asset_count,
        catalog_schema_metrics,
        catalog_schema_metrics_truncated,
    ) = await _catalog_coverage(session, context.workspace_id)
    return OperationsSummaryResponse(
        observed_at=observed_at,
        jobs_by_state=await _state_counts(
            session, JobModel.state, JobModel.workspace_id, context.workspace_id
        ),
        uploads_by_state=await _state_counts(
            session,
            ObjectManifestModel.state,
            ObjectManifestModel.workspace_id,
            context.workspace_id,
        ),
        changes_by_state=await _state_counts(
            session,
            ChangeRequestModel.state,
            ChangeRequestModel.workspace_id,
            context.workspace_id,
        ),
        catalog_asset_count=catalog_asset_count,
        catalog_described_asset_count=catalog_described_asset_count,
        catalog_schema_metrics=catalog_schema_metrics,
        catalog_schema_metrics_truncated=catalog_schema_metrics_truncated,
        unpublished_outbox_events=int(outbox_count),
        dead_lettered_outbox_events=int(dead_letter_count or 0),
        oldest_unpublished_age_seconds=(
            max(0, int((observed_at - oldest).total_seconds())) if oldest is not None else None
        ),
        retention_automation_state="DISABLED_NOT_READY",
    )


@router.get("/metrics", response_class=Response)
async def metrics(request: Request, context: ContextDep) -> Response:
    await _authorize_operations(request, context)
    container = get_container(request)
    telemetry = container.metrics
    pool = container.database.pool_snapshot()
    telemetry.database_pool_observed(
        configured_size=pool.configured_size,
        configured_max_overflow=pool.configured_max_overflow,
        checked_in=pool.checked_in,
        checked_out=pool.checked_out,
        overflow=pool.overflow,
    )
    return Response(content=telemetry.render(), headers={"Content-Type": telemetry.content_type})
