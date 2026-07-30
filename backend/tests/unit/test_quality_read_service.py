from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.quality_read_ports import QualityReadRepository
from datariver.application.services.authorization import (
    AuthorizationService,
    NullDecisionWriter,
)
from datariver.application.services.quality_read import QualityReadService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError

NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)


class _NoClassificationPolicy:
    async def read_candidate(self, **_: Any) -> None:
        return None


class _Repository:
    def __init__(self) -> None:
        self.overview_called = False

    async def database_now(self) -> datetime:
        return NOW

    async def overview(self, **_: Any) -> Any:
        self.overview_called = True
        raise AssertionError("The overview repository must not be called after denial.")


def _subject(
    workspace_id: UUID,
    *,
    actions: frozenset[Action],
    service: bool = False,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"service-accounts"}) if service else frozenset(),
        job_function="SERVICE_ACCOUNT" if service else "DATA_STEWARD",
        clearance=Classification.RESTRICTED,
        allowed_actions=actions,
    )


def _service(repository: _Repository) -> QualityReadService:
    return QualityReadService(
        repository=cast(QualityReadRepository, repository),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        classification_access=ClassificationAccessResolver(cast(Any, _NoClassificationPolicy())),
    )


@pytest.mark.asyncio
async def test_capability_has_bounded_lease_and_keeps_dependencies_fail_closed() -> None:
    workspace_id = uuid4()
    subject = _subject(
        workspace_id,
        actions=frozenset(
            {
                Action.QUALITY_READ,
                Action.QUALITY_PROFILE_READ,
                Action.QUALITY_RULE_PROPOSE,
                Action.QUALITY_RULE_ACTIVATE,
                Action.QUALITY_RUN_REQUEST,
            }
        ),
    )

    capability = await _service(_Repository()).capability(
        subject=subject,
        environment=EnvironmentAttributes(requested_at=NOW),
    )

    assert capability.valid_until == NOW.replace(second=30)
    assert len(capability.cache_scope) == 64
    axes = {value.id: value for value in capability.axes}
    assert axes["read_access"].state == "AVAILABLE"
    assert axes["profile_readiness"].state == "AVAILABLE"
    assert axes["rule_authoring"].state == "UNAVAILABLE"
    assert axes["rule_authoring"].reason_code == "FIELD_IDENTITY_MAPPING_UNAVAILABLE"
    assert axes["manual_execution"].reason_code == ("SOURCE_READINESS_ATTESTATION_UNAVAILABLE")
    assert axes["operations"].state == "DENIED"


@pytest.mark.asyncio
async def test_public_quality_capability_rejects_service_identity() -> None:
    workspace_id = uuid4()
    subject = _subject(
        workspace_id,
        actions=frozenset({Action.QUALITY_READ}),
        service=True,
    )

    with pytest.raises(ForbiddenError):
        await _service(_Repository()).capability(
            subject=subject,
            environment=EnvironmentAttributes(requested_at=NOW),
        )


@pytest.mark.asyncio
async def test_read_denial_happens_before_read_model_query() -> None:
    workspace_id = uuid4()
    repository = _Repository()
    subject = _subject(workspace_id, actions=frozenset())

    with pytest.raises(ForbiddenError):
        await _service(repository).overview(
            days=30,
            subject=subject,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="quality-read-denied",
        )

    assert not repository.overview_called
