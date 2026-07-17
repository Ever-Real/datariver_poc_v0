from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import Action, Classification, ResourceAttributes
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.schemas import (
    CapabilitiesResponse,
    CapabilityResponse,
    ExternalSystemLinkResponse,
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

    database, cache, datahub_status = await asyncio.gather(
        database_status(),
        valkey_status("valkey-cache", container.cache.ping()),
        container.datahub.capability(),
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
                ("grafana", "Grafana", container.settings.ui_grafana_url),
                ("prometheus", "Prometheus", container.settings.ui_prometheus_url),
                ("graph", "Knowledge Graph", container.settings.ui_graph_url),
            )
            if url is not None
        ],
        deployment_tier=container.settings.deployment_tier,
    )
