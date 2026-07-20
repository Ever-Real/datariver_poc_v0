from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import Action, Classification, ResourceAttributes
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.models.platform import ExternalServiceProfileModel
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.rls import set_security_context
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.schemas import (
    CapabilitiesResponse,
    CapabilityResponse,
    ExternalSystemLinkResponse,
    GrafanaEmbedResponse,
)

router = APIRouter(tags=["platform"])


@router.get("/health/live", include_in_schema=True)
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", response_model=None)
async def ready(request: Request) -> dict[str, str] | JSONResponse:
    container = get_container(request)
    result = await container.database.readiness(
        required_revision=REQUIRED_DATABASE_REVISION,
        timeout_seconds=container.settings.database_readiness_timeout_seconds,
    )
    if not result.ready:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "code": result.code},
        )
    return {"status": "ready"}


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities(request: Request, context: ContextDep) -> CapabilitiesResponse:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    await authorization.authorize(
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

    async def database_status() -> CapabilityResponse:
        started = asyncio.get_running_loop().time()
        state = "healthy"
        detail = None
        try:
            async with container.database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            state = "unavailable"
            detail = "CONNECTION"
        return CapabilityResponse(
            name="postgresql",
            state=state,
            observed_at=datetime.now(UTC),
            latency_ms=round((asyncio.get_running_loop().time() - started) * 1000),
            detail_code=detail,
        )

    async def valkey_status(name: str, ping: object) -> CapabilityResponse:
        started = asyncio.get_running_loop().time()
        state = "healthy"
        detail = None
        try:
            await ping  # type: ignore[misc]
        except Exception:
            state = "unavailable"
            detail = "CONNECTION"
        return CapabilityResponse(
            name=name,
            state=state,
            observed_at=datetime.now(UTC),
            latency_ms=round((asyncio.get_running_loop().time() - started) * 1000),
            detail_code=detail,
        )

    async def development_grafana_url() -> str | None:
        if container.settings.app_env != "development":
            return None
        async with container.database.session_factory() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=context.workspace_id,
                    subject_id=context.subject.subject_id,
                )
                profile = (
                    await session.scalars(
                        select(ExternalServiceProfileModel).where(
                            ExternalServiceProfileModel.workspace_id == context.workspace_id,
                            ExternalServiceProfileModel.service_key == "GRAFANA_DASHBOARD",
                            ExternalServiceProfileModel.active.is_(True),
                        )
                    )
                ).one_or_none()
                return profile.endpoint_url if profile is not None else None

    database, cache, datahub_status, configured_grafana_url = await asyncio.gather(
        database_status(),
        valkey_status("valkey-cache", container.cache.ping()),
        container.datahub.capability(),
        development_grafana_url(),
    )
    grafana_url = configured_grafana_url or (
        str(container.settings.ui_grafana_url)
        if container.settings.ui_grafana_url is not None
        else None
    )
    grafana_embed_url = (
        configured_grafana_url
        if container.settings.app_env == "development"
        else container.settings.grafana_embed_url()
    )
    grafana_embed_state = (
        "AVAILABLE"
        if grafana_embed_url is not None
        else "NOT_CONFIGURED"
        if grafana_url is None
        else "DISABLED"
    )
    return CapabilitiesResponse(
        items=[
            database,
            cache,
            CapabilityResponse(
                name=datahub_status.name,
                state=datahub_status.state,
                observed_at=datahub_status.observed_at,
                latency_ms=datahub_status.latency_ms,
                detail_code=datahub_status.detail_code,
            ),
        ],
        external_system_links=[
            ExternalSystemLinkResponse(system_id=system_id, label=label, url=url)
            for system_id, label, url in (
                ("datahub", "DataHub", container.settings.ui_datahub_url),
                ("airflow", "Airflow", container.settings.ui_airflow_url),
                ("grafana", "Grafana", grafana_url),
                ("prometheus", "Prometheus", container.settings.ui_prometheus_url),
                ("graph", "Knowledge Graph", container.settings.ui_graph_url),
            )
            if url is not None
        ],
        grafana_embed=GrafanaEmbedResponse(
            state=grafana_embed_state,
            url=grafana_embed_url,
        ),
        deployment_tier=container.settings.deployment_tier,
    )
