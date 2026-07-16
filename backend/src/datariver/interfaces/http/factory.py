from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.routing import Match

from datariver.application.errors import AuthenticationError, ExternalDependencyError
from datariver.config import Settings
from datariver.domain.common import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    uuid7,
)
from datariver.interfaces.http.container import AppContainer, build_container
from datariver.interfaces.http.router import api_router

logger = structlog.get_logger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
PUBLIC_REMEDIATION_KINDS = frozenset({"FIDO2_REQUIRED", "REAUTH_REQUIRED", "FALLBACK_UNAVAILABLE"})


def _route_template(app: FastAPI, request: Request) -> str:
    fastapi_scope = request.scope.get("fastapi")
    if isinstance(fastapi_scope, dict):
        effective_route = fastapi_scope.get("effective_route_context")
        effective_path = getattr(effective_route, "path", None)
        if isinstance(effective_path, str):
            return effective_path
    matched_route = request.scope.get("route")
    dependant = getattr(matched_route, "dependant", None)
    dependant_path = getattr(dependant, "path", None)
    if isinstance(dependant_path, str):
        return dependant_path
    matched_path = getattr(matched_route, "path", None)
    if isinstance(matched_path, str):
        return matched_path
    partial: str | None = None
    for route in app.router.routes:
        match, _ = route.matches(request.scope)
        path = getattr(route, "path", None)
        if match is Match.FULL and isinstance(path, str):
            return path
        if match is Match.PARTIAL and partial is None and isinstance(path, str):
            partial = path
    return partial or "unmatched"


def create_app(
    settings: Settings,
    *,
    container_factory: Callable[[Settings], AppContainer] = build_container,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = container_factory(settings)
        app.state.container = container
        yield
        await container.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.app_cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Purpose",
            "X-Request-Id",
            "X-Workspace-Id",
        ],
        expose_headers=["ETag", "Retry-After", "X-Request-Id"],
        max_age=600,
    )
    public_host = settings.app_public_origin.host
    if public_host is None:
        raise ValueError("The public origin must contain a host.")
    allowed_hosts = sorted({public_host, *settings.app_trusted_hosts})
    if settings.app_env == "test":
        allowed_hosts.append("testserver")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def request_security(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get("X-Request-Id", "")
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid7())
        request.state.request_id = request_id
        metrics = request.app.state.container.metrics
        metrics.request_started()
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except BaseException:
            metrics.request_finished(
                method=request.method,
                route="unmatched",
                status=500,
                duration_seconds=time.perf_counter() - started,
            )
            raise
        else:
            metrics.request_finished(
                method=request.method,
                route=_route_template(app, request),
                status=response.status_code,
                duration_seconds=time.perf_counter() - started,
            )
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
        if isinstance(error, AuthenticationError):
            status = 401
        elif isinstance(error, ForbiddenError):
            status = 403
        elif isinstance(error, NotFoundError):
            status = 404
        elif isinstance(error, ConflictError):
            status = 409
        elif isinstance(error, ValidationError):
            status = 422
        elif isinstance(error, RateLimitError):
            status = 429
        elif isinstance(error, ExternalDependencyError):
            status = 503 if error.details.get("retryable") else 502
        else:
            status = 400
        content = {
            "type": f"urn:datariver:problem:{error.code}",
            "title": error.code.replace("_", " ").title(),
            "status": status,
            "detail": error.message,
            "instance": request.url.path,
            "code": error.code,
            "request_id": getattr(request.state, "request_id", "unknown"),
        }
        if error.details.get("violations"):
            content["violations"] = error.details["violations"]
        remediation = error.details.get("remediation")
        if isinstance(error, ForbiddenError) and isinstance(remediation, dict):
            kind = remediation.get("kind")
            if isinstance(kind, str) and kind in PUBLIC_REMEDIATION_KINDS:
                content["remediation"] = {"kind": kind}
        response = JSONResponse(
            status_code=status, content=content, media_type="application/problem+json"
        )
        retry_after = error.details.get("retry_after_seconds")
        if isinstance(error, RateLimitError) and isinstance(retry_after, int):
            response.headers["Retry-After"] = str(retry_after)
        return response

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
        await logger.aerror(
            "unhandled_request_error",
            request_id=getattr(request.state, "request_id", "unknown"),
            path=request.url.path,
            error_type=type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            media_type="application/problem+json",
            content={
                "type": "urn:datariver:problem:internal_error",
                "title": "Internal error",
                "status": 500,
                "detail": "The request could not be completed.",
                "instance": request.url.path,
                "code": "internal_error",
                "request_id": getattr(request.state, "request_id", "unknown"),
            },
        )

    app.include_router(api_router, prefix="/api/v1")
    return app
