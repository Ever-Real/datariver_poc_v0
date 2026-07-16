from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError
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
    SqlErasureTargetReader,
    SqlLegalHoldRepository,
    _classification_or_restricted,
    _erasure_approval_event_model,
    _erasure_created_event_model,
    _erasure_request_model,
    _hold_event_model,
    _hold_model,
    _hydrate_erasure_request,
    _hydrate_hold,
    _policy_model,
    _required_policy,
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
