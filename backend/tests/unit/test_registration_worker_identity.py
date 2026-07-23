from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from datariver.application.services.bulk_registration import BulkPreparationRunResult
from datariver.application.services.manual_metadata_apply import ManualMetadataApplyResult
from datariver.application.services.registration_worker import (
    require_registration_operator_identity,
    require_registration_worker_identity,
)
from datariver.domain.authz import Action, Classification, SubjectAttributes
from datariver.domain.common import ForbiddenError
from datariver.domain.registration_worker import RegistrationWorkerCallIdentity
from datariver.interfaces.http.dependencies import RequestContext, get_request_context
from datariver.interfaces.http.routes import manual_registration, registration


class _AllowAuthorization:
    def __init__(self, **_: object) -> None:
        pass

    async def authorize(self, **_: object) -> None:
        return None


def _subject(
    *,
    active: bool = True,
    groups: frozenset[str] = frozenset({"service-accounts", "registration-workers"}),
    job_function: str | None = "SERVICE_ACCOUNT",
) -> SubjectAttributes:
    workspace_id = uuid4()
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=active,
        department_id=None,
        groups=groups,
        job_function=job_function,
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.CATALOG_SYNC}),
    )


def test_registration_worker_identity_requires_every_purpose_bound_attribute() -> None:
    accepted = _subject()

    assert require_registration_worker_identity(accepted) is accepted

    rejected = (
        _subject(active=False),
        _subject(job_function="DATA_STEWARD"),
        _subject(groups=frozenset({"registration-workers"})),
        _subject(groups=frozenset({"service-accounts"})),
        _subject(
            groups=frozenset(
                {
                    "security-administrators",
                    "service-accounts",
                    "registration-workers",
                }
            ),
            job_function="LOCAL_ADMINISTRATOR",
        ),
    )
    for subject in rejected:
        with pytest.raises(ForbiddenError):
            require_registration_worker_identity(subject)


def test_registration_operator_requires_a_human_admin_or_canonical_data_steward() -> None:
    admin = _subject(
        groups=frozenset({"security-administrators"}),
        job_function="LOCAL_ADMINISTRATOR",
    )
    steward = _subject(
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
    )
    assert require_registration_operator_identity(admin) is admin
    assert require_registration_operator_identity(steward) is steward

    for subject in (
        _subject(groups=frozenset(), job_function="ANALYST"),
        _subject(groups=frozenset(), job_function="DATA_STEWARD"),
        _subject(groups=frozenset({"data-stewards"}), job_function="ANALYST"),
        _subject(),
        _subject(
            groups=frozenset({"security-administrators", "service-accounts"}),
            job_function="LOCAL_ADMINISTRATOR",
        ),
        _subject(
            active=False,
            groups=frozenset({"security-administrators"}),
            job_function="LOCAL_ADMINISTRATOR",
        ),
    ):
        with pytest.raises(ForbiddenError):
            require_registration_operator_identity(subject)


@pytest.mark.parametrize(
    ("subject", "eligible", "reason_code"),
    [
        (
            _subject(
                groups=frozenset({"security-administrators"}),
                job_function="LOCAL_ADMINISTRATOR",
            ),
            True,
            "ELIGIBLE",
        ),
        (
            _subject(
                groups=frozenset({"data-stewards"}),
                job_function="DATA_STEWARD",
            ),
            True,
            "ELIGIBLE",
        ),
        (
            _subject(groups=frozenset(), job_function="ANALYST"),
            False,
            "ACTIVE_HUMAN_ADMIN_OR_DATA_STEWARD_REQUIRED",
        ),
        (
            _subject(),
            False,
            "ACTIVE_HUMAN_ADMIN_OR_DATA_STEWARD_REQUIRED",
        ),
    ],
)
def test_registration_operator_capability_is_server_owned_and_never_resolves_io(
    monkeypatch: pytest.MonkeyPatch,
    subject: SubjectAttributes,
    eligible: bool,
    reason_code: str,
) -> None:
    app = FastAPI()
    app.include_router(registration.router)
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id=subject.workspace_id,
        subject=subject,
        environment=object(),
        request_id="registration-operator-capability",
    )

    def fail_if_container_is_resolved(_: Request) -> object:
        raise AssertionError("Capability checks must not resolve infrastructure.")

    monkeypatch.setattr(registration, "get_container", fail_if_container_is_resolved)

    with TestClient(app) as client:
        response = client.get("/uploads/operator-capability")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "eligible": eligible,
        "can_view_workspace_history": (eligible and "security-administrators" in subject.groups),
        "reason_code": reason_code,
        "allowed_roles": ["ADMIN", "DATA_STEWARD"],
    }


@pytest.mark.parametrize(
    ("subject", "path"),
    [
        (
            _subject(
                groups=frozenset({"security-administrators"}),
                job_function="LOCAL_ADMINISTRATOR",
            ),
            "/registration/manual-submissions/apply",
        ),
        (
            _subject(
                groups=frozenset({"security-administrators"}),
                job_function="DATA_STEWARD",
            ),
            "/registration/bulk-preparations/execute",
        ),
        (
            _subject(groups=frozenset({"service-accounts"})),
            "/registration/manual-submissions/apply",
        ),
        (
            _subject(groups=frozenset({"service-accounts", "catalog-sync-workers"})),
            "/registration/bulk-preparations/execute",
        ),
    ],
)
def test_registration_execution_routes_deny_humans_and_unrelated_service_accounts_before_io(
    monkeypatch: pytest.MonkeyPatch,
    subject: SubjectAttributes,
    path: str,
) -> None:
    app = FastAPI()
    app.include_router(manual_registration.router)
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id=subject.workspace_id,
        subject=subject,
        environment=object(),
        request_id="registration-worker-boundary",
    )

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(_: Request, error: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": error.message})

    def fail_if_container_is_resolved(_: Request) -> object:
        raise AssertionError("Denied identities must not reach infrastructure.")

    monkeypatch.setattr(
        manual_registration,
        "get_container",
        fail_if_container_is_resolved,
    )

    with TestClient(app) as client:
        response = client.post(
            path,
            headers={"X-Run-Id": "registration-worker-boundary", "X-Run-Call": "1"},
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": (
            "The registration execution boundary requires an active purpose-bound service identity."
        )
    }


@pytest.mark.asyncio
async def test_manual_worker_hashes_and_forwards_the_run_call_to_atomic_service_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    submission_id = uuid4()
    calls = 0
    observed: RegistrationWorkerCallIdentity | None = None

    class ApplyService:
        async def run_once(self, **kwargs: object) -> ManualMetadataApplyResult:
            nonlocal calls, observed
            calls += 1
            observed = cast(RegistrationWorkerCallIdentity, kwargs["run_call"])
            return ManualMetadataApplyResult(
                processed=True,
                submission_id=submission_id,
                serial_number=41,
                state="APPLIED",
            )

    container = SimpleNamespace(database=SimpleNamespace(session_factory=object()))
    monkeypatch.setattr(manual_registration, "get_container", lambda _: container)
    monkeypatch.setattr(manual_registration, "AuthorizationService", _AllowAuthorization)
    monkeypatch.setattr(manual_registration, "_apply_service", lambda _: ApplyService())
    context = cast(
        RequestContext,
        SimpleNamespace(
            workspace_id=subject.workspace_id,
            subject=subject,
            environment=object(),
            request_id="manual-run-response-loss",
        ),
    )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})

    first = await manual_registration.apply_one_manual_metadata_submission(
        request=request,
        response=Response(),
        context=context,
        run_id="airflow-manual-run",
        run_call=1,
    )
    assert first.submission_id == submission_id
    assert calls == 1
    assert observed is not None
    assert observed.operation == "registration.manual-metadata.apply-run.v1"
    assert observed.worker_subject_id == subject.subject_id
    assert observed.key_hash != "airflow-manual-run:1"
    assert len(observed.key_hash) == 64


@pytest.mark.asyncio
async def test_bulk_worker_hashes_and_forwards_the_run_call_to_atomic_service_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    preparation_id = uuid4()
    calls = 0
    observed: RegistrationWorkerCallIdentity | None = None

    class PreparationService:
        async def run_once(self, **kwargs: object) -> BulkPreparationRunResult:
            nonlocal calls, observed
            calls += 1
            observed = cast(RegistrationWorkerCallIdentity, kwargs["run_call"])
            return BulkPreparationRunResult(
                processed=True,
                preparation_id=preparation_id,
                state="READY",
                item_count=7,
            )

    container = SimpleNamespace(database=SimpleNamespace(session_factory=object()))
    monkeypatch.setattr(manual_registration, "get_container", lambda _: container)
    monkeypatch.setattr(manual_registration, "AuthorizationService", _AllowAuthorization)
    monkeypatch.setattr(
        manual_registration,
        "_bulk_preparation_service",
        lambda _: PreparationService(),
    )
    context = cast(
        RequestContext,
        SimpleNamespace(
            workspace_id=subject.workspace_id,
            subject=subject,
            environment=object(),
            request_id="bulk-run-response-loss",
        ),
    )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})

    first = await manual_registration.execute_one_bulk_preparation(
        request=request,
        response=Response(),
        context=context,
        run_id="airflow-bulk-run",
        run_call=1,
    )
    assert first.preparation_id == preparation_id
    assert calls == 1
    assert observed is not None
    assert observed.operation == "registration.bulk-preparation.execute-run.v1"
    assert observed.worker_subject_id == subject.subject_id
    assert observed.key_hash != "airflow-bulk-run:1"
    assert len(observed.key_hash) == 64
