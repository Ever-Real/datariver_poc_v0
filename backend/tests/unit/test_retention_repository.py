from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.retention import (
    ErasureRequest,
    ErasureTargetType,
    GovernanceDecision,
    LegalHold,
    LegalHoldScope,
    RetentionDataClass,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.infrastructure.db.models.assistant import ChatSessionModel
from datariver.infrastructure.db.models.integration import ObjectManifestModel
from datariver.infrastructure.db.models.platform import WorkspaceMembershipModel
from datariver.infrastructure.db.retention import (
    SqlErasureRequestRepository,
    SqlErasureTargetReader,
    SqlLegalHoldRepository,
    SqlRetentionPolicyRepository,
    _classification_or_restricted,
    _decode_retention_list_cursor,
    _encode_retention_list_cursor,
    _erasure_approval_event_model,
    _erasure_created_event_model,
    _erasure_request_model,
    _hold_event_model,
    _hold_model,
    _hydrate_erasure_request,
    _hydrate_hold,
    _policy_cursor_boundary,
    _policy_model,
    _required_policy,
    _temporal_cursor_boundary,
)


class _ScalarRows:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def one_or_none(self) -> object | None:
        return self._value


class _ReaderSession:
    def __init__(self, value: object | None) -> None:
        self._value = value

    async def scalars(self, statement: object) -> _ScalarRows:
        del statement
        return _ScalarRows(self._value)


class _ExistenceSession:
    def __init__(self) -> None:
        self.statement: object | None = None

    async def scalar(self, statement: object) -> object:
        self.statement = statement
        return uuid4()


class _ScriptedSession:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def scalars(self, statement: object) -> tuple[object, ...]:
        self.statements.append(statement)
        return self.rows.pop(0)


def test_policy_hydration_rejects_a_tampered_rules_hash() -> None:
    policy = RetentionPolicyVersion.propose(
        workspace_id=uuid4(),
        policy_number=1,
        rules=RetentionRules(17, 29, 8, 4),
        requester_id=uuid4(),
        reason="Operating policy",
        policy_decision_id=uuid4(),
    )
    model = _policy_model(policy)
    model.completed_operation_days = 18

    with pytest.raises(ConflictError, match="integrity"):
        _required_policy(model)


def test_legal_hold_hydration_requires_complete_hash_bound_history() -> None:
    hold = LegalHold.create(
        workspace_id=uuid4(),
        data_class=RetentionDataClass.AUDIT_EVIDENCE,
        scope=LegalHoldScope.WORKSPACE,
        scope_id=None,
        reason="Investigation",
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
        now=datetime.now(UTC),
    )
    model = _hold_model(hold)
    event = _hold_event_model(hold, hold.actions[0])

    hydrated = _hydrate_hold(model, (event,))
    assert hydrated.payload_hash == hold.payload_hash
    assert hydrated.actions == hold.actions

    event.payload_hash = "0" * 64
    with pytest.raises(ConflictError, match="action failed its integrity"):
        _hydrate_hold(model, (event,))


def test_legal_hold_hydration_rejects_missing_append_only_event() -> None:
    hold = LegalHold.create(
        workspace_id=uuid4(),
        data_class=RetentionDataClass.CHAT_CONTENT,
        scope=LegalHoldScope.SUBJECT,
        scope_id=uuid4(),
        reason="Investigation",
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
        now=datetime.now(UTC),
    )
    model = _hold_model(hold)

    with pytest.raises(ConflictError, match="history is incomplete"):
        _hydrate_hold(model, ())


def test_legal_hold_hydration_accepts_only_a_bounded_contiguous_history_tail() -> None:
    now = datetime.now(UTC)
    maker_id, checker_id = uuid4(), uuid4()
    hold = LegalHold.create(
        workspace_id=uuid4(),
        data_class=RetentionDataClass.AUDIT_EVIDENCE,
        scope=LegalHoldScope.WORKSPACE,
        scope_id=None,
        reason="Long-running investigation",
        actor_id=maker_id,
        policy_decision_id=uuid4(),
        now=now,
    )
    for cycle in range(50):
        hold.request_release(
            actor_id=maker_id,
            reason=f"Release request {cycle}",
            policy_decision_id=uuid4(),
            expected_version=hold.version,
            now=now + timedelta(minutes=cycle * 2 + 1),
        )
        hold.decide_release(
            decision=GovernanceDecision.REJECTED,
            actor_id=checker_id,
            reason=f"Continue hold {cycle}",
            policy_decision_id=uuid4(),
            expected_version=hold.version,
            now=now + timedelta(minutes=cycle * 2 + 2),
        )
    model = _hold_model(hold)
    event_tail = tuple(_hold_event_model(hold, action) for action in hold.actions[-100:])

    hydrated = _hydrate_hold(model, event_tail, history_truncated=True)

    assert hydrated.version == 101
    assert len(hydrated.actions) == 100
    assert hydrated.actions[0].hold_version == 2
    assert hydrated.actions[-1].hold_version == 101
    assert hydrated.action_history_truncated is True


def test_erasure_hydration_requires_hash_bound_append_only_history() -> None:
    now = datetime.now(UTC)
    request = ErasureRequest.create(
        workspace_id=uuid4(),
        target_type=ErasureTargetType.UPLOAD_OBJECT,
        target_id=uuid4(),
        target_version=3,
        target_owner_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        retention_policy_id=uuid4(),
        retention_policy_hash="a" * 64,
        requester_id=uuid4(),
        reason="Retention expired",
        policy_decision_id=uuid4(),
        now=now,
        expires_at=now + timedelta(days=1),
    )
    created = _erasure_created_event_model(request)
    request.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=uuid4(),
        reason="Independent approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now + timedelta(minutes=1),
        active_legal_hold=False,
        current_target_version=3,
        current_target_owner_id=request.target_owner_id,
        current_classification=Classification.CONFIDENTIAL,
        active_retention_policy_id=request.retention_policy_id,
        active_retention_policy_hash=request.retention_policy_hash,
    )
    model = _erasure_request_model(request)
    approved = _erasure_approval_event_model(request, request.approvals[0])

    hydrated = _hydrate_erasure_request(model, (created, approved))
    assert hydrated.state is request.state
    assert hydrated.approvals == request.approvals
    assert hydrated.execution_state == "DISABLED_NOT_READY"

    model.target_version = 4
    with pytest.raises(ConflictError, match="integrity"):
        _hydrate_erasure_request(model, (created, approved))


def test_erasure_hydration_rejects_missing_or_tampered_decision_event() -> None:
    now = datetime.now(UTC)
    request = ErasureRequest.create(
        workspace_id=uuid4(),
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=uuid4(),
        target_version=1,
        target_owner_id=uuid4(),
        classification=Classification.RESTRICTED,
        retention_policy_id=uuid4(),
        retention_policy_hash="b" * 64,
        requester_id=uuid4(),
        reason="Retention expired",
        policy_decision_id=uuid4(),
        now=now,
        expires_at=now + timedelta(days=1),
    )
    created = _erasure_created_event_model(request)
    request.decide(
        decision=GovernanceDecision.REJECTED,
        actor_id=uuid4(),
        reason="Target must be retained",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now + timedelta(minutes=1),
        active_legal_hold=False,
        current_target_version=1,
        current_target_owner_id=request.target_owner_id,
        current_classification=Classification.RESTRICTED,
        active_retention_policy_id=request.retention_policy_id,
        active_retention_policy_hash=request.retention_policy_hash,
    )
    model = _erasure_request_model(request)
    rejected = _erasure_approval_event_model(request, request.approvals[0])

    with pytest.raises(ConflictError, match="history is incomplete"):
        _hydrate_erasure_request(model, (created,))
    rejected.reason = "Tampered"
    with pytest.raises(ConflictError, match="does not match"):
        _hydrate_erasure_request(model, (created, rejected))


def test_missing_or_invalid_target_classification_fails_closed() -> None:
    assert _classification_or_restricted(None) is Classification.RESTRICTED
    assert _classification_or_restricted(999) is Classification.RESTRICTED
    assert _classification_or_restricted(1) is Classification.INTERNAL


@pytest.mark.asyncio
async def test_erasure_target_snapshots_use_canonical_versions_and_fail_closed() -> None:
    workspace_id = uuid4()
    subject_id = uuid4()
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        clearance=3,
        attributes={},
        active=True,
        access_expires_at=None,
        version=7,
    )
    subject_reader = SqlErasureTargetReader(cast(AsyncSession, _ReaderSession(membership)))
    subject = await subject_reader.get_erasure_target_snapshot(
        workspace_id=workspace_id,
        target_type=ErasureTargetType.SUBJECT_DATA,
        target_id=subject_id,
    )
    assert subject is not None
    assert subject.version == 7
    assert subject.owner_id == subject_id
    assert subject.classification is Classification.RESTRICTED

    chat_id = uuid4()
    chat = ChatSessionModel(
        id=chat_id,
        workspace_id=workspace_id,
        owner_id=subject_id,
        title="Governed chat",
        scope={},
        version=4,
    )
    chat_reader = SqlErasureTargetReader(cast(AsyncSession, _ReaderSession(chat)))
    chat_snapshot = await chat_reader.get_erasure_target_snapshot(
        workspace_id=workspace_id,
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=chat_id,
    )
    assert chat_snapshot is not None
    assert chat_snapshot.version == 4
    assert chat_snapshot.owner_id == subject_id
    assert chat_snapshot.classification is Classification.RESTRICTED

    manifest_id = uuid4()
    manifest = ObjectManifestModel(
        id=manifest_id,
        workspace_id=workspace_id,
        bucket="governed",
        object_key="object.csv",
        display_name="object.csv",
        size_bytes=1,
        mime="text/csv",
        sha256="a" * 64,
        processing_attempts=0,
        validation_attempts=0,
        validation_summary={},
        completion_parts=[],
        state="VALIDATED",
        classification=999,
        owner_id=subject_id,
        version=3,
    )
    manifest_reader = SqlErasureTargetReader(cast(AsyncSession, _ReaderSession(manifest)))
    manifest_snapshot = await manifest_reader.get_erasure_target_snapshot(
        workspace_id=workspace_id,
        target_type=ErasureTargetType.UPLOAD_OBJECT,
        target_id=manifest_id,
    )
    assert manifest_snapshot is not None
    assert manifest_snapshot.version == 3
    assert manifest_snapshot.owner_id == subject_id
    assert manifest_snapshot.classification is Classification.RESTRICTED


@pytest.mark.asyncio
async def test_nonreleased_target_legal_hold_is_treated_as_active() -> None:
    session = _ExistenceSession()
    repository = SqlLegalHoldRepository(cast(AsyncSession, session))
    assert await repository.has_active_for_erasure_target(
        workspace_id=uuid4(),
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=uuid4(),
        target_owner_id=uuid4(),
    )
    assert session.statement is not None
    compiled = cast(ClauseElement, session.statement).compile()
    sql = str(compiled)
    parameter_values = repr(compiled.params)
    assert "legal_holds.state !=" in sql
    assert "legal_holds.data_class =" in sql
    assert "legal_holds.scope =" in sql
    for expected in ("RELEASED", "CHAT_CONTENT", "WORKSPACE", "RESOURCE", "SUBJECT"):
        assert expected in parameter_values


def test_retention_cursor_is_canonical_and_bound_to_workspace_scope_and_state() -> None:
    workspace_id = uuid4()
    cursor = _encode_retention_list_cursor(
        scope="retention-policies",
        workspace_id=workspace_id,
        state="ACTIVE",
        boundary={"policy_number": 17},
    )

    assert (
        _policy_cursor_boundary(
            cursor,
            workspace_id=workspace_id,
            state="ACTIVE",
        )
        == 17
    )
    assert _decode_retention_list_cursor(
        cursor,
        scope="retention-policies",
        workspace_id=workspace_id,
        state="ACTIVE",
    ) == {"policy_number": 17}

    mismatched_requests: tuple[tuple[str, UUID, str | None], ...] = (
        ("legal-holds", workspace_id, "ACTIVE"),
        ("retention-policies", uuid4(), "ACTIVE"),
        ("retention-policies", workspace_id, "DRAFT"),
    )
    for scope, mismatched_workspace_id, state in mismatched_requests:
        with pytest.raises(ValidationError, match="stale or does not match"):
            _decode_retention_list_cursor(
                cursor,
                scope=scope,
                workspace_id=mismatched_workspace_id,
                state=state,
            )

    with pytest.raises(ValidationError, match="stale or does not match"):
        _decode_retention_list_cursor(
            "a" * 2_001,
            scope="retention-policies",
            workspace_id=workspace_id,
            state="ACTIVE",
        )


def test_temporal_retention_cursor_requires_an_aware_timestamp_and_exact_boundary() -> None:
    workspace_id = uuid4()
    boundary_id = uuid4()
    created_at = datetime.now(UTC)
    cursor = _encode_retention_list_cursor(
        scope="legal-holds",
        workspace_id=workspace_id,
        state=None,
        boundary={"created_at": created_at.isoformat(), "id": str(boundary_id)},
    )
    assert _temporal_cursor_boundary(
        cursor,
        scope="legal-holds",
        workspace_id=workspace_id,
        state=None,
    ) == (created_at, boundary_id)

    naive = _encode_retention_list_cursor(
        scope="legal-holds",
        workspace_id=workspace_id,
        state=None,
        boundary={
            "created_at": created_at.replace(tzinfo=None).isoformat(),
            "id": str(boundary_id),
        },
    )
    with pytest.raises(ValidationError, match="invalid boundary"):
        _temporal_cursor_boundary(
            naive,
            scope="legal-holds",
            workspace_id=workspace_id,
            state=None,
        )


@pytest.mark.asyncio
async def test_policy_list_fetches_limit_plus_one_and_continues_after_policy_number() -> None:
    workspace_id = uuid4()
    policies = [
        RetentionPolicyVersion.propose(
            workspace_id=workspace_id,
            policy_number=number,
            rules=RetentionRules(17, 29, 8, 4),
            requester_id=uuid4(),
            reason=f"Policy {number}",
            policy_decision_id=uuid4(),
        )
        for number in (3, 2, 1)
    ]
    models = tuple(_policy_model(policy) for policy in policies)
    first_session = _ScriptedSession([models, ()])
    first_repository = SqlRetentionPolicyRepository(cast(AsyncSession, first_session))

    first = await first_repository.list(
        workspace_id=workspace_id,
        state=None,
        limit=2,
    )

    assert [item.policy_number for item in first.items] == [3, 2]
    assert first.next_cursor is not None
    assert (
        _policy_cursor_boundary(
            first.next_cursor,
            workspace_id=workspace_id,
            state=None,
        )
        == 2
    )

    second_session = _ScriptedSession([(models[2],), ()])
    second_repository = SqlRetentionPolicyRepository(cast(AsyncSession, second_session))
    second = await second_repository.list(
        workspace_id=workspace_id,
        state=None,
        limit=2,
        cursor=first.next_cursor,
    )

    assert [item.policy_number for item in second.items] == [1]
    assert second.next_cursor is None
    compiled = cast(ClauseElement, second_session.statements[0]).compile()
    assert "policy_versions.policy_number <" in str(compiled)
    assert 2 in compiled.params.values()


@pytest.mark.asyncio
async def test_legal_hold_list_uses_immutable_created_at_keyset_boundary() -> None:
    workspace_id = uuid4()
    created_at = datetime.now(UTC)
    holds = [
        LegalHold.create(
            workspace_id=workspace_id,
            data_class=RetentionDataClass.AUDIT_EVIDENCE,
            scope=LegalHoldScope.WORKSPACE,
            scope_id=None,
            reason=f"Hold {index}",
            actor_id=uuid4(),
            policy_decision_id=uuid4(),
            now=created_at - timedelta(minutes=index),
        )
        for index in range(3)
    ]
    models = tuple(_hold_model(hold) for hold in holds)
    for index, model in enumerate(models):
        model.created_at = created_at - timedelta(minutes=index)
        model.updated_at = created_at + timedelta(minutes=index)
    first_session = _ScriptedSession(
        [
            models,
            (_hold_event_model(holds[0], holds[0].actions[0]),),
            (_hold_event_model(holds[1], holds[1].actions[0]),),
        ]
    )
    first_repository = SqlLegalHoldRepository(cast(AsyncSession, first_session))

    first = await first_repository.list(
        workspace_id=workspace_id,
        state=None,
        limit=2,
    )

    assert [item.hold_id for item in first.items] == [holds[0].hold_id, holds[1].hold_id]
    assert all(item.actions == [] for item in first.items)
    assert all(item.action_history_truncated for item in first.items)
    assert len(first_session.statements) == 1
    assert first.next_cursor is not None
    assert _temporal_cursor_boundary(
        first.next_cursor,
        scope="legal-holds",
        workspace_id=workspace_id,
        state=None,
    ) == (models[1].created_at, models[1].id)
    compiled_first = cast(ClauseElement, first_session.statements[0]).compile()
    assert "legal_holds.created_at DESC" in str(compiled_first)
    assert "legal_holds.updated_at DESC" not in str(compiled_first)

    second_session = _ScriptedSession(
        [
            (models[2],),
            (_hold_event_model(holds[2], holds[2].actions[0]),),
        ]
    )
    second_repository = SqlLegalHoldRepository(cast(AsyncSession, second_session))
    second = await second_repository.list(
        workspace_id=workspace_id,
        state=None,
        limit=2,
        cursor=first.next_cursor,
    )
    assert [item.hold_id for item in second.items] == [holds[2].hold_id]
    assert second.items[0].action_history_truncated is True
    assert len(second_session.statements) == 1
    assert second.next_cursor is None
    compiled_second = cast(ClauseElement, second_session.statements[0]).compile()
    assert "legal_holds.created_at <" in str(compiled_second)
    assert "legal_holds.id >" in str(compiled_second)


@pytest.mark.asyncio
async def test_erasure_request_list_returns_a_created_at_keyset_cursor() -> None:
    workspace_id = uuid4()
    created_at = datetime.now(UTC)
    requests = [
        ErasureRequest.create(
            workspace_id=workspace_id,
            target_type=ErasureTargetType.UPLOAD_OBJECT,
            target_id=uuid4(),
            target_version=1,
            target_owner_id=uuid4(),
            classification=Classification.CONFIDENTIAL,
            retention_policy_id=uuid4(),
            retention_policy_hash="a" * 64,
            requester_id=uuid4(),
            reason=f"Request {index}",
            policy_decision_id=uuid4(),
            now=created_at - timedelta(minutes=index),
            expires_at=created_at + timedelta(hours=1),
        )
        for index in range(2)
    ]
    models = tuple(_erasure_request_model(request) for request in requests)
    for index, model in enumerate(models):
        model.created_at = created_at - timedelta(minutes=index)
    session = _ScriptedSession(
        [
            models,
            (_erasure_created_event_model(requests[0]),),
        ]
    )
    repository = SqlErasureRequestRepository(cast(AsyncSession, session))

    page = await repository.list(
        workspace_id=workspace_id,
        state=None,
        limit=1,
    )
    assert page.items[0].approvals == []
    assert page.items[0].approval_history_truncated is True
    assert len(session.statements) == 1

    assert [item.erasure_request_id for item in page.items] == [requests[0].erasure_request_id]
    assert page.next_cursor is not None
    assert _temporal_cursor_boundary(
        page.next_cursor,
        scope="erasure-requests",
        workspace_id=workspace_id,
        state=None,
    ) == (models[0].created_at, models[0].id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repository_type",
    [SqlRetentionPolicyRepository, SqlLegalHoldRepository, SqlErasureRequestRepository],
)
@pytest.mark.parametrize("limit", [0, 101])
async def test_retention_repositories_enforce_the_maximum_page_size(
    repository_type: type[
        SqlRetentionPolicyRepository | SqlLegalHoldRepository | SqlErasureRequestRepository
    ],
    limit: int,
) -> None:
    repository = repository_type(cast(AsyncSession, _ScriptedSession([])))
    with pytest.raises(ValidationError, match="between 1 and 100"):
        await repository.list(
            workspace_id=uuid4(),
            state=None,
            limit=limit,
        )
