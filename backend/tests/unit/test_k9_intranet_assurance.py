from datetime import datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import pytest

from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, Effect, ForbiddenError, ValidationError


@pytest.fixture
def env() -> EnvironmentAttributes:
    return EnvironmentAttributes(
        requested_at=datetime.now(),
        maximum_clock_skew=timedelta(seconds=5),
        maximum_authentication_age=timedelta(hours=1),
    )


@pytest.fixture
def workspace_id() -> UUID:
    return uuid4()


@pytest.fixture
def system_id() -> UUID:
    return uuid4()


@pytest.fixture
def domain_id() -> UUID:
    return uuid4()


@pytest.fixture
def resource(workspace_id: UUID, system_id: UUID, domain_id: UUID) -> ResourceAttributes:
    return ResourceAttributes(
        resource_id=uuid4(),
        resource_type="knowledge_studio_draft",
        workspace_id=workspace_id,
        classification=Classification.INTERNAL,
        active=True,
        lifecycle="ACTIVE",
        owner_department_id=None,
        system_id=system_id,
        domain_id=domain_id,
    )


def create_subject(
    subject_id: UUID,
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    groups: set[str],
    allowed_actions: set[Action],
    job_function: str = "SERVICE_ACCOUNT",
    active: bool = True,
    clearance: Classification = Classification.INTERNAL,
    authentication_time: datetime | None | object = ...,
    authentication_assurance: AuthenticationAssurance = AuthenticationAssurance.PASSWORD,
) -> SubjectAttributes:
    if authentication_time is ...:
        authentication_time = datetime.now()
    # We cast to avoid mypy complaining about ellipsis.
    auth_time = authentication_time if authentication_time is not ... else datetime.now()
    return SubjectAttributes(
        subject_id=subject_id,
        department_id=None,
        job_function=job_function,
        groups=frozenset(groups),
        allowed_actions=frozenset(allowed_actions),
        denied_actions=frozenset(),
        clearance=clearance,
        workspace_id=workspace_id,
        allowed_system_ids=frozenset({system_id}),
        allowed_domain_ids=frozenset({domain_id}),
        authentication_assurance=authentication_assurance,
        authentication_time=cast(datetime | None, auth_time),
        active=active,
    )


@pytest.mark.asyncio
async def test_authorization_assurance(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    authz = AuthorizationService(
        decision_writer=AsyncMock(),
        knowledge_studio_intranet_publication_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        knowledge_studio_intranet_publisher_checker_subject_id=checker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
        authentication_assurance=AuthenticationAssurance.UNKNOWN,
        authentication_time=None,
    )

    decision = await authz.authorize(
        subject=subject,
        resource=resource,
        action=Action.KG_PUBLISH,
        environment=env,
        request_id="req1",
    )
    assert decision.allowed
    assert "INTRANET_DISTINCT_PRINCIPAL" in decision.reason_codes


@pytest.mark.asyncio
async def test_authorization_assurance_fails_on_maker_group(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    authz = AuthorizationService(
        decision_writer=AsyncMock(),
        knowledge_studio_intranet_publication_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        knowledge_studio_intranet_publisher_checker_subject_id=checker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers", "k9-publisher-makers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
    )

    with pytest.raises(ForbiddenError):
        await authz.authorize(
            subject=subject,
            resource=resource,
            action=Action.KG_PUBLISH,
            environment=env,
            request_id="req1",
        )


@pytest.mark.asyncio
async def test_authorization_assurance_fails_on_extra_actions(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    authz = AuthorizationService(
        decision_writer=AsyncMock(),
        knowledge_studio_intranet_publication_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        knowledge_studio_intranet_publisher_checker_subject_id=checker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_EDIT},
    )

    with pytest.raises(ForbiddenError):
        await authz.authorize(
            subject=subject,
            resource=resource,
            action=Action.KG_PUBLISH,
            environment=env,
            request_id="req1",
        )


@pytest.mark.asyncio
async def test_authorization_assurance_fails_on_inactive(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    authz = AuthorizationService(
        decision_writer=AsyncMock(),
        knowledge_studio_intranet_publication_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        knowledge_studio_intranet_publisher_checker_subject_id=checker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
        active=False,
    )

    with pytest.raises(ForbiddenError):
        await authz.authorize(
            subject=subject,
            resource=resource,
            action=Action.KG_PUBLISH,
            environment=env,
            request_id="req1",
        )


@pytest.mark.asyncio
async def test_authorization_assurance_fails_on_future_auth(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    authz = AuthorizationService(
        decision_writer=AsyncMock(),
        knowledge_studio_intranet_publication_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        knowledge_studio_intranet_publisher_checker_subject_id=checker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
        authentication_time=datetime.now() + timedelta(days=1),
    )

    with pytest.raises(ForbiddenError):
        await authz.authorize(
            subject=subject,
            resource=resource,
            action=Action.KG_PUBLISH,
            environment=env,
            request_id="req1",
        )


@pytest.mark.asyncio
async def test_authorization_assurance_fails_on_stale_auth(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    authz = AuthorizationService(
        decision_writer=AsyncMock(),
        knowledge_studio_intranet_publication_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        knowledge_studio_intranet_publisher_checker_subject_id=checker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
        authentication_time=datetime.now() - timedelta(days=1),
    )

    with pytest.raises(ForbiddenError):
        await authz.authorize(
            subject=subject,
            resource=resource,
            action=Action.KG_PUBLISH,
            environment=env,
            request_id="req1",
        )


@pytest.mark.asyncio
async def test_publish_draft_rejects_wrong_author(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    maker_id = uuid4()
    other_maker_id = uuid4()

    store_mock = AsyncMock()
    mock_draft = AsyncMock()
    mock_draft.state = "REVIEW"
    mock_draft.author_id = other_maker_id
    mock_draft.draft_id = uuid4()
    mock_draft.workspace_id = workspace_id
    store_mock.get_draft.return_value = mock_draft

    service = KnowledgeStudioService(
        store=store_mock,
        authorization=AsyncMock(),
        intranet_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        intranet_publisher_checker_subject_id=checker_id,
        intranet_publisher_maker_subject_id=maker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
    )

    with pytest.raises(
        ValidationError, match="The intranet assurance exception requires the fixed maker principal"
    ):
        await service.publish_draft(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=mock_draft.draft_id,
            review_reason="Looks good",
            expected_version=1,
            idempotency_key="key1",
            request_hash="hash1",
            environment=env,
            request_id="req1",
        )


@pytest.mark.asyncio
async def test_publish_draft_accepts_maker_author(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    maker_id = uuid4()

    store_mock = AsyncMock()
    mock_draft = Mock()
    mock_draft.state = "REVIEW"
    mock_draft.author_id = maker_id
    mock_draft.draft_id = uuid4()
    mock_draft.workspace_id = workspace_id
    store_mock.get_draft.return_value = mock_draft
    store_mock._materialization_target = AsyncMock(
        return_value=(Mock(graph_type="CATALOG_MIRROR", version=1), None)
    )
    store_mock._load_contract = AsyncMock(return_value=Mock())

    authz_mock = AsyncMock()
    authz_mock.authorize = AsyncMock(
        return_value=Decision(
            decision_id=uuid4(),
            effect=Effect.ALLOW,
            reason_codes=("INTRANET_DISTINCT_PRINCIPAL",),
            policy_versions=(),
        )
    )

    service = KnowledgeStudioService(
        store=store_mock,
        authorization=authz_mock,
        intranet_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        intranet_publisher_checker_subject_id=checker_id,
        intranet_publisher_maker_subject_id=maker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
    )

    # Mock _resource method by patching it
    with patch.object(service, "_resource", return_value=resource):
        # We don't swallow exceptions here, proving success
        result = await service.publish_draft(
            workspace_id=workspace_id,
            subject=subject,
            draft_id=mock_draft.draft_id,
            review_reason="Looks good",
            expected_version=1,
            idempotency_key="key1",
            request_hash="hash1",
            environment=env,
            request_id="req1",
        )
        assert result == store_mock.publish_draft.return_value

        # Exact interactions
        authz_mock.authorize.assert_any_call(
            subject=subject,
            resource=resource,
            action=Action.KG_PUBLISH,
            environment=env,
            request_id="req1",
        )
        store_mock.get_draft.assert_called_once_with(
            workspace_id=workspace_id,
            actor_id=checker_id,
            draft_id=mock_draft.draft_id,
        )
        store_mock.publish_draft.assert_called_once_with(
            workspace_id=workspace_id,
            actor_id=checker_id,
            draft_id=mock_draft.draft_id,
            review_reason="Looks good",
            expected_version=1,
            idempotency_key="key1",
            request_hash="hash1",
        )


@pytest.mark.asyncio
async def test_publish_draft_rejects_self_approval(
    workspace_id: UUID,
    system_id: UUID,
    domain_id: UUID,
    env: EnvironmentAttributes,
    resource: ResourceAttributes,
) -> None:
    checker_id = uuid4()
    maker_id = checker_id  # Maker is checker

    store_mock = AsyncMock()
    mock_draft = Mock()
    mock_draft.state = "REVIEW"
    mock_draft.author_id = maker_id
    mock_draft.draft_id = uuid4()
    mock_draft.workspace_id = workspace_id
    store_mock.get_draft.return_value = mock_draft

    service = KnowledgeStudioService(
        store=store_mock,
        authorization=AsyncMock(),
        intranet_assurance_mode="INTRANET_DISTINCT_PRINCIPAL",
        intranet_publisher_checker_subject_id=checker_id,
        intranet_publisher_maker_subject_id=maker_id,
    )

    subject = create_subject(
        checker_id,
        workspace_id,
        system_id,
        domain_id,
        groups={"service-accounts", "k9-publisher-checkers"},
        allowed_actions={Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ},
    )

    with patch.object(service, "_resource", return_value=resource):
        with pytest.raises(
            ConflictError, match=r"A Studio author cannot review or publish their own Draft."
        ):
            await service.publish_draft(
                workspace_id=workspace_id,
                subject=subject,
                draft_id=mock_draft.draft_id,
                review_reason="Looks good",
                expected_version=1,
                idempotency_key="key1",
                request_hash="hash1",
                environment=env,
                request_id="req1",
            )
