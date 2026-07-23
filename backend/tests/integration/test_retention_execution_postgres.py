from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from datariver.application.dto import ArchiveCapabilityEvidence
from datariver.application.services.retention_execution import (
    RetentionArchiveOutcome,
    RetentionArchiveWorker,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import canonical_json_hash
from datariver.domain.retention import (
    ArchiveCapability,
    ErasureRequest,
    ErasureTargetType,
    GovernanceDecision,
    RetentionArchiveDisposition,
    RetentionClassRule,
    RetentionDataClass,
    RetentionPeriodUnit,
    RetentionPolicyContract,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentModel,
    AccessRoleModel,
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
from datariver.infrastructure.db.models.retention import (
    ArchiveCapabilityAttestationModel,
    ErasureRequestModel,
    ImmutableArchiveReceiptModel,
    LegalHoldModel,
    RetentionExecutionAttemptModel,
    RetentionExecutionJobModel,
)
from datariver.infrastructure.db.retention import (
    _erasure_approval_event_model,
    _erasure_created_event_model,
    _erasure_request_model,
    _policy_class_rule_models,
    _policy_model,
)
from datariver.infrastructure.db.retention_execution import SqlRetentionExecutionStore
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.object_store.archive_s3 import S3ImmutableArchiveStore
from datariver.infrastructure.secrets import SecretResolver

_SCHEDULER_URL = "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_URL"
_ARCHIVE_URL = "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_URL"
_ADMIN_URL = "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_URL"
_CONFIRM_ISOLATED = "DATARIVER_RETENTION_TEST_CONFIRM_ISOLATED"


class _Body:
    def __init__(self, content: bytes) -> None:
        self._stream = BytesIO(content)

    def read(self, size: int) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()


class _LockedS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.put_calls = 0

    def get_bucket_versioning(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"Status": "Enabled"}

    def get_object_lock_configuration(self, **kwargs: Any) -> dict[str, object]:
        del kwargs
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.put_calls += 1
        assert kwargs["IfNoneMatch"] == "*"
        if any(key == str(kwargs["Key"]) for key, _version in self.objects):
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        content = bytes(kwargs["Body"])
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
        assert kwargs["ChecksumSHA256"] == checksum
        key = (str(kwargs["Key"]), "version-1")
        self.objects[key] = {
            "content": content,
            "retain_until": kwargs["ObjectLockRetainUntilDate"],
            "metadata": kwargs["Metadata"],
            "last_modified": datetime.now(UTC).replace(microsecond=0),
        }
        return {"VersionId": "version-1", "ChecksumSHA256": checksum}

    def get_object(self, **kwargs: Any) -> dict[str, object]:
        value = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {"Body": _Body(value["content"])}

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        matches = [
            (version, value)
            for (key, version), value in self.objects.items()
            if key == str(kwargs["Key"])
        ]
        if not matches:
            raise ClientError({"Error": {"Code": "404", "Message": "missing"}}, "HeadObject")
        version, value = matches[-1]
        content = bytes(value["content"])
        return {
            "VersionId": version,
            "ContentLength": len(content),
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(content).digest()).decode("ascii"),
            "Metadata": value["metadata"],
            "LastModified": value["last_modified"],
        }

    def get_object_retention(self, **kwargs: Any) -> dict[str, object]:
        value = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {"Retention": {"Mode": "COMPLIANCE", "RetainUntilDate": value["retain_until"]}}

    def get_object_legal_hold(self, **kwargs: Any) -> dict[str, object]:
        del kwargs
        return {"LegalHold": {"Status": "OFF"}}

    def put_object_retention(self, **kwargs: Any) -> None:
        del kwargs
        raise _access_denied("PutObjectRetention")

    def delete_object(self, **kwargs: Any) -> None:
        del kwargs
        raise _access_denied("DeleteObject")


def _access_denied(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, operation)


class _SimulatedWorkerCrash(BaseException):
    pass


@dataclass(frozen=True, slots=True)
class _Fixture:
    workspace_id: UUID
    requester_id: UUID
    checker_id: UUID
    owner_id: UUID
    executor_id: UUID
    role_id: UUID
    chat_id: UUID
    request_decision_id: UUID
    approval_decision_id: UUID

    @classmethod
    def create(cls) -> _Fixture:
        values = [uuid4() for _ in range(8)]
        return cls(
            workspace_id=values[0],
            requester_id=values[1],
            checker_id=values[2],
            owner_id=values[3],
            executor_id=UUID("00000000-0000-7000-8000-000000000003"),
            role_id=values[4],
            chat_id=values[5],
            request_decision_id=values[6],
            approval_decision_id=values[7],
        )


def _engine(url_env: str, secret_env: str, default_secret: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[url_env],
        connect_args={"password": SecretResolver().resolve(os.getenv(secret_env, default_secret))},
        pool_size=1,
        max_overflow=0,
    )


def _contract(now: datetime) -> RetentionPolicyContract:
    return RetentionPolicyContract(
        effective_from=now - timedelta(days=1),
        effective_until=now + timedelta(days=365),
        execution_authorization_hours=24,
        class_rules=tuple(
            RetentionClassRule(
                data_class=data_class,
                unit=RetentionPeriodUnit.DAYS,
                minimum=minimum,
                maximum=maximum,
                archive_disposition=disposition,
            )
            for data_class, minimum, maximum, disposition in (
                (
                    RetentionDataClass.COMPLETED_OPERATIONS,
                    0,
                    30,
                    RetentionArchiveDisposition.NO_ARCHIVE,
                ),
                (
                    RetentionDataClass.CHAT_CONTENT,
                    0,
                    30,
                    RetentionArchiveDisposition.EVIDENCE_ONLY,
                ),
                (
                    RetentionDataClass.AUDIT_EVIDENCE,
                    1,
                    365,
                    RetentionArchiveDisposition.EVIDENCE_ONLY,
                ),
                (
                    RetentionDataClass.OBJECT_DATA,
                    1,
                    30,
                    RetentionArchiveDisposition.NO_ARCHIVE,
                ),
            )
        ),
    )


async def _prepare(admin_engine: AsyncEngine, fixture: _Fixture) -> None:
    # Keep the approval evidence in the past. A future-dated governance decision is
    # not a valid execution fixture and changes the archive evidence basis.
    now = datetime.now(UTC) - timedelta(minutes=2)
    admin_attributes = {
        "groups": sorted(["datariver-role-retention-security-admin", "security-administrators"]),
        "allowed_actions": sorted([Action.ERASURE_APPROVE.value, Action.ERASURE_REQUEST.value]),
        "denied_actions": [],
        "allowed_system_ids": [],
        "allowed_domain_ids": [],
    }
    admin_access_hash = canonical_json_hash(
        {
            "active": True,
            "clearance": Classification.RESTRICTED.name,
            **admin_attributes,
        }
    )
    policy = RetentionPolicyVersion.propose(
        workspace_id=fixture.workspace_id,
        policy_number=1,
        rules=RetentionRules(30, 30, 12, 1),
        contract=_contract(now),
        requester_id=fixture.requester_id,
        reason="PostgreSQL retention execution test",
        policy_decision_id=uuid4(),
    )
    policy.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=fixture.checker_id,
        reason="Independent policy approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
    )
    request = ErasureRequest.create(
        workspace_id=fixture.workspace_id,
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=fixture.chat_id,
        target_version=1,
        target_owner_id=fixture.owner_id,
        classification=Classification.RESTRICTED,
        retention_policy_id=policy.policy_id,
        retention_policy_hash=policy.payload_hash,
        requester_id=fixture.requester_id,
        reason="Minimum Chat retention elapsed",
        policy_decision_id=fixture.request_decision_id,
        now=now,
        expires_at=now + timedelta(days=1),
    )
    created_event = _erasure_created_event_model(request)
    request.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=fixture.checker_id,
        reason="Independent erasure approval",
        policy_decision_id=fixture.approval_decision_id,
        expected_version=1,
        now=now + timedelta(minutes=1),
        active_legal_hold=False,
        current_target_version=1,
        current_target_owner_id=fixture.owner_id,
        current_classification=Classification.RESTRICTED,
        active_retention_policy_id=policy.policy_id,
        active_retention_policy_hash=policy.payload_hash,
    )
    async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
        async with session.begin():
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            session.add(
                WorkspaceModel(
                    id=fixture.workspace_id,
                    slug=f"retention-test-{fixture.workspace_id.hex[:12]}",
                    name="Retention integration test",
                    status="ACTIVE",
                    settings={},
                    version=1,
                )
            )
            session.add_all(
                SubjectModel(
                    id=subject_id,
                    issuer="retention-integration-test",
                    external_subject=f"{label}-{fixture.workspace_id}",
                    display_name=label,
                    active=True,
                )
                for subject_id, label in (
                    (fixture.requester_id, "requester"),
                    (fixture.checker_id, "checker"),
                    (fixture.owner_id, "owner"),
                )
            )
            await session.flush()
            session.add_all(
                WorkspaceMembershipModel(
                    workspace_id=fixture.workspace_id,
                    subject_id=subject_id,
                    job_function=(
                        "SECURITY_ADMINISTRATOR" if subject_id != fixture.owner_id else "DATA_OWNER"
                    ),
                    clearance=int(Classification.RESTRICTED),
                    attributes=(admin_attributes if subject_id != fixture.owner_id else {}),
                    active=True,
                    access_expires_at=now + timedelta(days=30),
                    version=1,
                )
                for subject_id in (
                    fixture.requester_id,
                    fixture.checker_id,
                    fixture.owner_id,
                )
            )
            await session.flush()
            session.add(
                AccessRoleModel(
                    id=fixture.role_id,
                    workspace_id=fixture.workspace_id,
                    role_key="retention-security-admin",
                    name="Retention security administrator",
                    description="Integration fixture",
                    clearance=int(Classification.RESTRICTED),
                    groups=["security-administrators"],
                    allowed_actions=[Action.ERASURE_REQUEST.value, Action.ERASURE_APPROVE.value],
                    denied_actions=[],
                    allowed_system_ids=[],
                    allowed_domain_ids=[],
                    active=True,
                    updated_by=fixture.requester_id,
                    version=1,
                )
            )
            await session.flush()
            session.add_all(
                AccessRoleAssignmentModel(
                    workspace_id=fixture.workspace_id,
                    subject_id=subject_id,
                    role_id=fixture.role_id,
                    role_version=1,
                    membership_version=1,
                    access_payload_hash=admin_access_hash,
                    assigned_by=fixture.requester_id,
                    active=True,
                    version=1,
                )
                for subject_id in (fixture.requester_id, fixture.checker_id)
            )
            session.add_all(
                PolicyDecisionModel(
                    id=decision_id,
                    workspace_id=fixture.workspace_id,
                    subject_id=subject_id,
                    resource_id=fixture.chat_id,
                    action=action.value,
                    effect="ALLOW",
                    reason_codes=["POLICY_ALLOW"],
                    policy_versions=["builtin-abac-v2"],
                    evaluation_context={
                        "authentication_assurance": "HARDWARE_WEBAUTHN",
                        "authentication_time": now.isoformat(),
                    },
                    request_id=f"retention-{action.value}",
                    decided_at=decision_time,
                )
                for decision_id, subject_id, action, decision_time in (
                    (
                        fixture.request_decision_id,
                        fixture.requester_id,
                        Action.ERASURE_REQUEST,
                        now,
                    ),
                    (
                        fixture.approval_decision_id,
                        fixture.checker_id,
                        Action.ERASURE_APPROVE,
                        now + timedelta(seconds=30),
                    ),
                )
            )
            session.add(_policy_model(policy))
            await session.flush()
            session.add_all(_policy_class_rule_models(policy))
            await session.execute(
                text(
                    """
                    INSERT INTO assistant.chat_sessions (
                        id, workspace_id, owner_id, title, scope,
                        retention_policy_id, retention_policy_hash,
                        retention_basis_at, retention_until,
                        retention_binding_version, version, created_at, updated_at
                    ) VALUES (
                        :id, :workspace_id, :owner_id, 'Retention test Chat', '{}'::jsonb,
                        :policy_id, :policy_hash,
                        transaction_timestamp(), transaction_timestamp() + INTERVAL '30 days',
                        'ACTIVE_POLICY_V1', 1,
                        transaction_timestamp(), transaction_timestamp()
                    )
                    """
                ),
                {
                    "id": fixture.chat_id,
                    "workspace_id": fixture.workspace_id,
                    "owner_id": fixture.owner_id,
                    "policy_id": policy.policy_id,
                    "policy_hash": policy.payload_hash,
                },
            )
            request_model = _erasure_request_model(request)
            request_model.created_at = now
            assert request.decided_at is not None
            request_model.updated_at = request.decided_at
            session.add(request_model)
            await session.flush()
            session.add(created_event)
            session.add(_erasure_approval_event_model(request, request.approvals[0]))


async def _cleanup(admin_engine: AsyncEngine, fixture: _Fixture) -> None:
    async with admin_engine.begin() as connection:
        await connection.execute(
            text(
                "SELECT set_config('app.workspace_id', :workspace_id, true), "
                "set_config('app.subject_id', :subject_id, true)"
            ),
            {
                "workspace_id": str(fixture.workspace_id),
                "subject_id": str(fixture.requester_id),
            },
        )
        for table in (
            "retention.execution_events",
            "retention.execution_attempts",
            "retention.execution_jobs",
            "retention.immutable_archive_receipts",
            "retention.archive_capability_attestations",
            "retention.legal_hold_events",
            "retention.legal_holds",
            "retention.erasure_request_events",
            "retention.erasure_requests",
            "assistant.chat_sessions",
            "retention.policy_class_rules",
            "retention.policy_versions",
            "authz.policy_decisions",
            "iam.access_role_assignments",
            "iam.access_roles",
            "iam.workspace_memberships",
            "iam.subjects",
            "platform.workspaces",
        ):
            if table == "iam.subjects":
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE id = ANY(:subject_ids)"),  # noqa: S608
                    {
                        "subject_ids": [
                            fixture.requester_id,
                            fixture.checker_id,
                            fixture.owner_id,
                        ]
                    },
                )
            elif table == "platform.workspaces":
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE id = :workspace_id"),  # noqa: S608
                    {"workspace_id": fixture.workspace_id},
                )
            else:
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE workspace_id = :workspace_id"),  # noqa: S608
                    {"workspace_id": fixture.workspace_id},
                )


async def _add_stale_requests_before_eligible(
    admin_engine: AsyncEngine, fixture: _Fixture, *, count: int
) -> None:
    async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
        async with session.begin():
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            reference = (
                await session.scalars(
                    select(ErasureRequestModel).where(
                        ErasureRequestModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            base = datetime.now(UTC) - timedelta(minutes=20)
            for index in range(count):
                created_at = base + timedelta(seconds=index * 2)
                request = ErasureRequest.create(
                    workspace_id=fixture.workspace_id,
                    target_type=ErasureTargetType.CHAT_SESSION,
                    target_id=uuid4(),
                    target_version=1,
                    target_owner_id=fixture.owner_id,
                    classification=Classification.RESTRICTED,
                    retention_policy_id=reference.retention_policy_id,
                    retention_policy_hash=reference.retention_policy_hash,
                    requester_id=fixture.requester_id,
                    reason=f"Stale request without a canonical target {index}",
                    policy_decision_id=uuid4(),
                    now=created_at,
                    expires_at=created_at + timedelta(days=1),
                )
                created_event = _erasure_created_event_model(request)
                request.decide(
                    decision=GovernanceDecision.APPROVED,
                    actor_id=fixture.checker_id,
                    reason="Independent stale-request approval",
                    policy_decision_id=uuid4(),
                    expected_version=1,
                    now=created_at + timedelta(seconds=1),
                    active_legal_hold=False,
                    current_target_version=1,
                    current_target_owner_id=fixture.owner_id,
                    current_classification=Classification.RESTRICTED,
                    active_retention_policy_id=reference.retention_policy_id,
                    active_retention_policy_hash=reference.retention_policy_hash,
                )
                model = _erasure_request_model(request)
                model.created_at = created_at
                assert request.decided_at is not None
                model.updated_at = request.decided_at
                session.add(model)
                await session.flush()
                session.add(created_event)
                session.add(_erasure_approval_event_model(request, request.approvals[0]))


async def _mutate_current_eligibility(
    admin_engine: AsyncEngine, fixture: _Fixture, mutation: str
) -> None:
    async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
        async with session.begin():
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            if mutation == "subject_inactive":
                await session.execute(
                    update(SubjectModel)
                    .where(SubjectModel.id == fixture.requester_id)
                    .values(active=False)
                )
            elif mutation == "workspace_suspended":
                await session.execute(
                    update(WorkspaceModel)
                    .where(WorkspaceModel.id == fixture.workspace_id)
                    .values(status="SUSPENDED")
                )
            elif mutation == "membership_inactive":
                await session.execute(
                    update(WorkspaceMembershipModel)
                    .where(
                        WorkspaceMembershipModel.workspace_id == fixture.workspace_id,
                        WorkspaceMembershipModel.subject_id == fixture.requester_id,
                    )
                    .values(active=False)
                )
            elif mutation == "membership_expired":
                await session.execute(
                    update(WorkspaceMembershipModel)
                    .where(
                        WorkspaceMembershipModel.workspace_id == fixture.workspace_id,
                        WorkspaceMembershipModel.subject_id == fixture.requester_id,
                    )
                    .values(access_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            elif mutation == "service_account_job":
                await session.execute(
                    update(WorkspaceMembershipModel)
                    .where(
                        WorkspaceMembershipModel.workspace_id == fixture.workspace_id,
                        WorkspaceMembershipModel.subject_id == fixture.requester_id,
                    )
                    .values(job_function="SERVICE_ACCOUNT")
                )
            elif mutation == "service_account_group":
                await session.execute(
                    update(WorkspaceMembershipModel)
                    .where(
                        WorkspaceMembershipModel.workspace_id == fixture.workspace_id,
                        WorkspaceMembershipModel.subject_id == fixture.requester_id,
                    )
                    .values(
                        attributes={
                            "groups": sorted(
                                [
                                    "datariver-role-retention-security-admin",
                                    "security-administrators",
                                    "service-accounts",
                                ]
                            ),
                            "allowed_actions": sorted(
                                [Action.ERASURE_APPROVE.value, Action.ERASURE_REQUEST.value]
                            ),
                            "denied_actions": [],
                            "allowed_system_ids": [],
                            "allowed_domain_ids": [],
                        }
                    )
                )
            elif mutation == "group_drift":
                await session.execute(
                    update(WorkspaceMembershipModel)
                    .where(
                        WorkspaceMembershipModel.workspace_id == fixture.workspace_id,
                        WorkspaceMembershipModel.subject_id == fixture.requester_id,
                    )
                    .values(
                        attributes={
                            "groups": ["datariver-role-retention-security-admin"],
                            "allowed_actions": sorted(
                                [Action.ERASURE_APPROVE.value, Action.ERASURE_REQUEST.value]
                            ),
                            "denied_actions": [],
                            "allowed_system_ids": [],
                            "allowed_domain_ids": [],
                        }
                    )
                )
            elif mutation == "allowed_action_removed":
                await session.execute(
                    update(AccessRoleModel)
                    .where(
                        AccessRoleModel.workspace_id == fixture.workspace_id,
                        AccessRoleModel.id == fixture.role_id,
                    )
                    .values(allowed_actions=[Action.ERASURE_REQUEST.value], version=2)
                )
            elif mutation == "denied_action_added":
                await session.execute(
                    update(AccessRoleModel)
                    .where(
                        AccessRoleModel.workspace_id == fixture.workspace_id,
                        AccessRoleModel.id == fixture.role_id,
                    )
                    .values(denied_actions=[Action.ERASURE_REQUEST.value])
                )
            elif mutation == "role_version_drift":
                await session.execute(
                    update(AccessRoleModel)
                    .where(
                        AccessRoleModel.workspace_id == fixture.workspace_id,
                        AccessRoleModel.id == fixture.role_id,
                    )
                    .values(version=2)
                )
            elif mutation == "access_hash_drift":
                await session.execute(
                    update(AccessRoleAssignmentModel)
                    .where(
                        AccessRoleAssignmentModel.workspace_id == fixture.workspace_id,
                        AccessRoleAssignmentModel.subject_id == fixture.requester_id,
                    )
                    .values(access_payload_hash="d" * 64)
                )
            else:  # pragma: no cover - test parameter invariant
                raise AssertionError(f"Unknown eligibility mutation: {mutation}")


_POSTGRES_ENABLED = (
    all(os.getenv(name) for name in (_SCHEDULER_URL, _ARCHIVE_URL, _ADMIN_URL))
    and os.getenv(_CONFIRM_ISOLATED) == "1"
)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_fenced_planning_claim_and_revocation_revalidation_on_postgres() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        planned = await asyncio.gather(
            *(
                scheduler_store.plan_next(
                    workspace_id=fixture.workspace_id,
                    executor_id=fixture.executor_id,
                    archive_configuration_hash="a" * 64,
                    maximum_attempts=4,
                )
                for _ in range(2)
            )
        )
        assert sorted(planned) == [False, True]

        claims = await asyncio.gather(
            *(
                archive_store.claim_next(
                    workspace_id=fixture.workspace_id,
                    worker_id=f"archive-{index}",
                    worker_principal_fingerprint="c" * 64,
                    lease_seconds=300,
                )
                for index in range(2)
            )
        )
        claim = next(value for value in claims if value is not None)
        assert sum(value is not None for value in claims) == 1
        assert claim.lease_epoch == 1
        assert await archive_store.revalidate_before_archive(claim=claim)

        # Simulate a worker crash after claim. Only an expired lease may be reclaimed and the old
        # fence must lose all completion authority.
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(
                        RetentionExecutionJobModel.workspace_id == fixture.workspace_id,
                        RetentionExecutionJobModel.id == claim.job_id,
                    )
                    .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
                )
        reclaimed = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-restarted",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )
        assert reclaimed is not None
        assert reclaimed.recovery_only
        assert reclaimed.attempt_count == 1
        assert reclaimed.lease_epoch == 2
        assert not await archive_store.revalidate_before_archive(claim=claim)
        assert (
            await archive_store.mark_failed(
                claim=reclaimed,
                error_code="ARCHIVE_RECOVERY_OBJECT_NOT_FOUND",
                retryable=True,
            )
            == "RETRY_WAIT"
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == claim.job_id)
                    .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                )
        retry_claim = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-retry-after-recovery",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )
        assert retry_claim is not None and not retry_claim.recovery_only
        assert retry_claim.attempt_count == 2
        assert retry_claim.lease_epoch == 3
        assert not await archive_store.revalidate_before_archive(claim=reclaimed)
        assert await archive_store.revalidate_before_archive(claim=retry_claim)
        claim = retry_claim

        # A hold placed after claim must block the final archive gate. Releasing that exact hold
        # restores eligibility but does not reuse or weaken any lease evidence.
        hold_id = uuid4()
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                session.add(
                    LegalHoldModel(
                        id=hold_id,
                        workspace_id=fixture.workspace_id,
                        data_class=RetentionDataClass.CHAT_CONTENT.value,
                        scope="RESOURCE",
                        scope_id=fixture.chat_id,
                        reason="Race-test hold",
                        payload_hash="d" * 64,
                        created_by=fixture.requester_id,
                        create_policy_decision_id=uuid4(),
                        state="ACTIVE",
                        release_requested_by=None,
                        release_request_reason=None,
                        release_request_policy_decision_id=None,
                        release_checker_id=None,
                        release_decision_reason=None,
                        release_decision_policy_decision_id=None,
                        released_at=None,
                        version=1,
                    )
                )
        assert not await archive_store.revalidate_before_archive(claim=claim)
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(LegalHoldModel)
                    .where(
                        LegalHoldModel.workspace_id == fixture.workspace_id,
                        LegalHoldModel.id == hold_id,
                    )
                    .values(
                        state="RELEASED",
                        release_requested_by=fixture.requester_id,
                        release_request_reason="Race-test release request",
                        release_request_policy_decision_id=uuid4(),
                        release_checker_id=fixture.checker_id,
                        release_decision_reason="Race-test release approval",
                        release_decision_policy_decision_id=uuid4(),
                        released_at=datetime.now(UTC),
                        version=2,
                    )
                )
        assert await archive_store.revalidate_before_archive(claim=claim)

        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(AccessRoleAssignmentModel)
                    .where(
                        AccessRoleAssignmentModel.workspace_id == fixture.workspace_id,
                        AccessRoleAssignmentModel.subject_id == fixture.checker_id,
                    )
                    .values(active=False, version=2)
                )
        assert not await archive_store.revalidate_before_archive(claim=claim)
        await archive_store.mark_failed(
            claim=claim,
            error_code="PRE_ARCHIVE_REVALIDATION_FAILED",
            retryable=False,
        )

        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            job = (
                await session.scalars(
                    select(RetentionExecutionJobModel).where(
                        RetentionExecutionJobModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            assert job.state == "BLOCKED"
            assert job.destructive_state == "DISABLED_NOT_READY"
            assert job.attempt_count == 2
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_cached_capability_observation_is_idempotent_on_postgres() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=1,
        )
        claim = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-cached-capability",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )
        assert claim is not None
        observed_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
        capability = ArchiveCapability(
            configuration_fingerprint="a" * 64,
            challenge_hash="d" * 64,
            observed_at=observed_at,
            expires_at=observed_at + timedelta(minutes=10),
            versioning_enabled=True,
            object_lock_enabled=True,
            compliance_retention_supported=True,
            checksum_sha256_supported=True,
            full_readback_verified=True,
            retention_shorten_denied=True,
            retained_version_delete_denied=True,
        )
        evidence = ArchiveCapabilityEvidence(
            encryption_profile_fingerprint="b" * 64,
            runtime_principal_fingerprint="c" * 64,
            probe_contract_version="archive-probe-v1",
            challenge_hash="d" * 64,
            object_bucket="immutable-audit",
        )

        first = await archive_store.record_archive_capability(
            claim=claim, capability=capability, evidence=evidence
        )
        second = await archive_store.record_archive_capability(
            claim=claim, capability=capability, evidence=evidence
        )
        assert first.attestation_id == second.attestation_id
        assert (
            await archive_store.mark_failed(
                claim=claim,
                error_code="TEST_CAPABILITY_REUSE_COMPLETE",
                retryable=False,
            )
            == "BLOCKED"
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            count = await session.scalar(
                select(func.count(ArchiveCapabilityAttestationModel.id)).where(
                    ArchiveCapabilityAttestationModel.workspace_id == fixture.workspace_id
                )
            )
            assert count == 1
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_s3_adapter_worker_and_postgres_complete_base64_receipt_contract() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive = S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="test-only",
        encryption_profile_fingerprint="b" * 64,
        client=_LockedS3Client(),
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash=archive.configuration_fingerprint,
            maximum_attempts=1,
        )
        worker = RetentionArchiveWorker(
            store=archive_store,
            archive=archive,
            execution_enabled=True,
            worker_id="archive-postgres-contract",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )

        outcome = await worker.run_once(workspace_id=fixture.workspace_id)
        if outcome is not RetentionArchiveOutcome.ARCHIVED:
            async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
                attempt = (
                    await session.scalars(
                        select(RetentionExecutionAttemptModel)
                        .where(RetentionExecutionAttemptModel.workspace_id == fixture.workspace_id)
                        .order_by(RetentionExecutionAttemptModel.attempt_no.desc())
                    )
                ).first()
            pytest.fail(
                "archive worker did not complete the real database contract: "
                f"outcome={outcome!s}, error_code="
                f"{attempt.failure_code if attempt is not None else 'missing-attempt'}"
            )

        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            job = (
                await session.scalars(
                    select(RetentionExecutionJobModel).where(
                        RetentionExecutionJobModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            receipt = (
                await session.scalars(
                    select(ImmutableArchiveReceiptModel).where(
                        ImmutableArchiveReceiptModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            attestation = (
                await session.scalars(
                    select(ArchiveCapabilityAttestationModel).where(
                        ArchiveCapabilityAttestationModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            assert job.state == "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED"
            assert job.destructive_state == "DISABLED_NOT_READY"
            assert receipt.source == "ERASURE_EXECUTION_EVIDENCE"
            assert receipt.provider_checksum_encoding == "BASE64"
            assert receipt.provider_checksum_normalized_sha256 == receipt.content_sha256
            assert attestation.challenge_hash != canonical_json_hash(
                {"job_id": str(job.id), "lease_epoch": 1}
            )
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_cold_restart_recovers_exact_attestation_without_provider_write() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    client = _LockedS3Client()
    first_process_archive = S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="test-only",
        encryption_profile_fingerprint="b" * 64,
        client=client,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash=first_process_archive.configuration_fingerprint,
            maximum_attempts=1,
        )
        write = first_process_archive.write_archive

        async def crash_after_evidence_put(**kwargs: Any) -> Any:
            receipt = await write(**kwargs)
            if "_capability-probes/" not in str(kwargs["object_key"]):
                raise _SimulatedWorkerCrash
            return receipt

        first_process_archive.write_archive = crash_after_evidence_put  # type: ignore[method-assign]
        first_worker = RetentionArchiveWorker(
            store=archive_store,
            archive=first_process_archive,
            execution_enabled=True,
            worker_id="archive-before-crash",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        with pytest.raises(_SimulatedWorkerCrash):
            await first_worker.run_once(workspace_id=fixture.workspace_id)
        assert client.put_calls == 2

        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                job_id = (
                    await session.scalars(
                        select(RetentionExecutionJobModel.id).where(
                            RetentionExecutionJobModel.workspace_id == fixture.workspace_id
                        )
                    )
                ).one()
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == job_id)
                    .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
                )

        cold_archive = S3ImmutableArchiveStore(
            endpoint_url="https://archive.internal.example",
            region="us-east-1",
            bucket="immutable-audit",
            prefix="evidence",
            access_key="archive-only",
            secret_key="test-only",
            encryption_profile_fingerprint="b" * 64,
            client=client,
        )
        recovery_worker = RetentionArchiveWorker(
            store=archive_store,
            archive=cold_archive,
            execution_enabled=True,
            worker_id="archive-after-cold-restart",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        assert (
            await recovery_worker.run_once(workspace_id=fixture.workspace_id)
            is RetentionArchiveOutcome.BLOCKED
        )
        assert client.put_calls == 2

        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            job = await session.get(RetentionExecutionJobModel, job_id)
            receipt = (
                await session.scalars(
                    select(ImmutableArchiveReceiptModel).where(
                        ImmutableArchiveReceiptModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            attestation = (
                await session.scalars(
                    select(ArchiveCapabilityAttestationModel).where(
                        ArchiveCapabilityAttestationModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            assert job is not None and job.state == "BLOCKED"
            assert job.archive_receipt_id == receipt.id
            assert receipt.capability_attestation_id == attestation.id
            assert job.last_failure_code == "POST_WRITE_RECEIPT_RECOVERED"
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_post_write_kill_switch_records_reconcilable_orphan_receipt() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive = S3ImmutableArchiveStore(
        endpoint_url="https://archive.internal.example",
        region="us-east-1",
        bucket="immutable-audit",
        prefix="evidence",
        access_key="archive-only",
        secret_key="test-only",
        encryption_profile_fingerprint="b" * 64,
        client=_LockedS3Client(),
    )
    switch_observations = iter((True, True, True, False))
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash=archive.configuration_fingerprint,
            maximum_attempts=2,
        )
        worker = RetentionArchiveWorker(
            store=archive_store,
            archive=archive,
            execution_enabled=lambda: next(switch_observations),
            worker_id="archive-post-write-switch",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )

        assert (
            await worker.run_once(workspace_id=fixture.workspace_id)
            is RetentionArchiveOutcome.BLOCKED
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            job = (
                await session.scalars(
                    select(RetentionExecutionJobModel).where(
                        RetentionExecutionJobModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            receipt = (
                await session.scalars(
                    select(ImmutableArchiveReceiptModel).where(
                        ImmutableArchiveReceiptModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            attempt = (
                await session.scalars(
                    select(RetentionExecutionAttemptModel).where(
                        RetentionExecutionAttemptModel.workspace_id == fixture.workspace_id
                    )
                )
            ).one()
            assert job.state == "BLOCKED"
            assert job.last_failure_code == "KILL_SWITCH_DISABLED_AFTER_WRITE"
            assert job.archive_receipt_id == receipt.id
            assert job.archive_manifest_hash == receipt.manifest_hash
            assert receipt.object_version_id == "version-1"
            assert receipt.content_sha256 == receipt.readback_sha256
            assert attempt.external_response_hash is not None
            assert attempt.finished_at is not None
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_expired_final_lease_issues_read_only_recovery_fence_then_blocks() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=1,
        )
        claim = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-final-attempt",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        assert claim is not None
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == claim.job_id)
                    .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
                )

        recovery = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-read-only-recovery",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        assert recovery is not None and recovery.recovery_only
        assert recovery.attempt_count == recovery.maximum_attempts == 1
        assert recovery.lease_epoch == claim.lease_epoch + 1
        assert (
            await archive_store.mark_failed(
                claim=recovery,
                error_code="ARCHIVE_RECOVERY_OBJECT_NOT_FOUND",
                retryable=True,
            )
            == "BLOCKED"
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            job = await session.get(RetentionExecutionJobModel, claim.job_id)
            attempt = await session.get(RetentionExecutionAttemptModel, claim.attempt_id)
            recovery_attempt = await session.get(
                RetentionExecutionAttemptModel, recovery.attempt_id
            )
            assert job is not None and job.state == "BLOCKED"
            assert job.last_failure_code == "ARCHIVE_RECOVERY_OBJECT_NOT_FOUND"
            assert attempt is not None and attempt.state == "SUPERSEDED"
            assert attempt.stage == "LEASE_EXPIRED_RECOVERY"
            assert attempt.finished_at is not None
            assert recovery_attempt is not None and recovery_attempt.state == "BLOCKED"
            assert recovery_attempt.stage == "FAILED"
            assert recovery_attempt.finished_at is not None
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_recovery_budget_is_persistent_and_bounded_on_postgres() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
        write_claim = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-write-before-recovery",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        assert write_claim is not None
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == write_claim.job_id)
                    .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
                )

        first_recovery_epochs: list[int] = []
        for recovery_no in range(1, 4):
            recovery = await archive_store.claim_next(
                workspace_id=fixture.workspace_id,
                worker_id=f"archive-recovery-{recovery_no}",
                worker_principal_fingerprint="c" * 64,
                lease_seconds=60,
            )
            assert recovery is not None and recovery.recovery_only
            assert recovery.attempt_count == 1
            first_recovery_epochs.append(recovery.lease_epoch)
            failure_code = (
                "ARCHIVE_RECOVERY_TRANSIENT_ServiceUnavailable"
                if recovery_no < 3
                else "ARCHIVE_RECOVERY_OBJECT_NOT_FOUND"
            )
            assert (
                await archive_store.mark_failed(
                    claim=recovery,
                    error_code=failure_code,
                    retryable=True,
                )
                == "RETRY_WAIT"
            )
            async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
                async with session.begin():
                    await set_security_context(
                        session,
                        workspace_id=fixture.workspace_id,
                        subject_id=fixture.requester_id,
                    )
                    await session.execute(
                        update(RetentionExecutionJobModel)
                        .where(RetentionExecutionJobModel.id == write_claim.job_id)
                        .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                    )

        assert first_recovery_epochs == [2, 3, 4]
        second_write = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-second-write-after-recovery-budget",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        assert second_write is not None and not second_write.recovery_only
        assert second_write.attempt_count == 2
        assert second_write.lease_epoch == 5
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == write_claim.job_id)
                    .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
                )

        second_recovery_epochs: list[int] = []
        for recovery_no in range(1, 4):
            recovery = await archive_store.claim_next(
                workspace_id=fixture.workspace_id,
                worker_id=f"archive-second-write-recovery-{recovery_no}",
                worker_principal_fingerprint="c" * 64,
                lease_seconds=60,
            )
            assert recovery is not None and recovery.recovery_only
            assert recovery.attempt_count == 2
            second_recovery_epochs.append(recovery.lease_epoch)
            expected_state = "RETRY_WAIT" if recovery_no < 3 else "BLOCKED"
            assert (
                await archive_store.mark_failed(
                    claim=recovery,
                    error_code="ARCHIVE_RECOVERY_TRANSIENT_ServiceUnavailable",
                    retryable=True,
                )
                == expected_state
            )
            if recovery_no < 3:
                async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
                    async with session.begin():
                        await set_security_context(
                            session,
                            workspace_id=fixture.workspace_id,
                            subject_id=fixture.requester_id,
                        )
                        await session.execute(
                            update(RetentionExecutionJobModel)
                            .where(RetentionExecutionJobModel.id == write_claim.job_id)
                            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                        )

        assert second_recovery_epochs == [6, 7, 8]
        assert (
            await archive_store.claim_next(
                workspace_id=fixture.workspace_id,
                worker_id="archive-recovery-exhausted",
                worker_principal_fingerprint="c" * 64,
                lease_seconds=60,
            )
            is None
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            job = await session.get(RetentionExecutionJobModel, write_claim.job_id)
            attempts = tuple(
                await session.scalars(
                    select(RetentionExecutionAttemptModel).where(
                        RetentionExecutionAttemptModel.workspace_id == fixture.workspace_id
                    )
                )
            )
            assert job is not None
            assert job.state == "BLOCKED"
            assert job.attempt_count == 2
            assert job.lease_epoch == 8
            assert len(attempts) == 8
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_expired_lease_recovery_precedes_governance_drift_on_postgres() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
        write_claim = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-before-drift",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        assert write_claim is not None
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(AccessRoleAssignmentModel)
                    .where(
                        AccessRoleAssignmentModel.workspace_id == fixture.workspace_id,
                        AccessRoleAssignmentModel.subject_id == fixture.checker_id,
                    )
                    .values(active=False, version=2)
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == write_claim.job_id)
                    .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
                )

        recovery = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-recovery-before-drift-block",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=60,
        )
        assert recovery is not None and recovery.recovery_only
        assert recovery.attempt_count == 1
        assert (
            await archive_store.mark_failed(
                claim=recovery,
                error_code="ARCHIVE_RECOVERY_OBJECT_NOT_FOUND",
                retryable=True,
            )
            == "RETRY_WAIT"
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == write_claim.job_id)
                    .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                )
        assert (
            await archive_store.claim_next(
                workspace_id=fixture.workspace_id,
                worker_id="archive-normal-claim-after-drift",
                worker_principal_fingerprint="c" * 64,
                lease_seconds=60,
            )
            is None
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.requester_id
            )
            job = await session.get(RetentionExecutionJobModel, write_claim.job_id)
            receipt_count = await session.scalar(
                select(func.count(ImmutableArchiveReceiptModel.id)).where(
                    ImmutableArchiveReceiptModel.workspace_id == fixture.workspace_id
                )
            )
            assert job is not None
            assert job.state == "BLOCKED"
            assert job.last_failure_code == "CLAIM_REVALIDATION_FAILED"
            assert job.attempt_count == 1
            assert job.lease_epoch == 2
            assert receipt_count == 0
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    (
        "subject_inactive",
        "workspace_suspended",
        "membership_inactive",
        "membership_expired",
        "service_account_job",
        "service_account_group",
        "group_drift",
        "allowed_action_removed",
        "denied_action_added",
        "role_version_drift",
        "access_hash_drift",
    ),
)
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_planning_rejects_current_identity_and_access_drift(mutation: str) -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        await _mutate_current_eligibility(admin_engine, fixture, mutation)

        assert not await store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            job_count = await session.scalar(
                select(func.count(RetentionExecutionJobModel.id)).where(
                    RetentionExecutionJobModel.workspace_id == fixture.workspace_id
                )
            )
            assert job_count == 0
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    (
        "subject_inactive",
        "workspace_suspended",
        "group_drift",
        "allowed_action_removed",
        "access_hash_drift",
    ),
)
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_archive_revalidation_rejects_identity_drift_without_receipt(
    mutation: str,
) -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
        claim = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-revalidation-negative",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )
        assert claim is not None
        await _mutate_current_eligibility(admin_engine, fixture, mutation)

        assert not await archive_store.revalidate_before_archive(claim=claim)
        assert (
            await archive_store.mark_failed(
                claim=claim,
                error_code="PRE_ARCHIVE_REVALIDATION_FAILED",
                retryable=False,
            )
            == "BLOCKED"
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            receipt_count = await session.scalar(
                select(func.count(ImmutableArchiveReceiptModel.id)).where(
                    ImmutableArchiveReceiptModel.workspace_id == fixture.workspace_id
                )
            )
            assert receipt_count == 0
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_planner_cursor_reaches_eligible_request_after_twenty_five_stale_rows() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        await _add_stale_requests_before_eligible(admin_engine, fixture, count=25)

        assert not await store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
        assert await store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_database_rejects_executor_collapsing_into_requester_role() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            with pytest.raises(IntegrityError, match="separation_of_duties"):
                async with session.begin():
                    await set_security_context(
                        session,
                        workspace_id=fixture.workspace_id,
                        subject_id=fixture.requester_id,
                    )
                    await session.execute(
                        update(RetentionExecutionJobModel)
                        .where(RetentionExecutionJobModel.workspace_id == fixture.workspace_id)
                        .values(executor_id=fixture.requester_id)
                    )
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await admin_engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated scheduler/archive/admin PostgreSQL URLs are required",
)
async def test_stored_retry_budget_is_authoritative_on_postgres() -> None:
    fixture = _Fixture.create()
    scheduler_engine = _engine(
        _SCHEDULER_URL,
        "DATARIVER_RETENTION_TEST_SCHEDULER_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_retention_scheduler_password",
    )
    archive_engine = _engine(
        _ARCHIVE_URL,
        "DATARIVER_RETENTION_TEST_ARCHIVE_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_archive_password",
    )
    admin_engine = _engine(
        _ADMIN_URL,
        "DATARIVER_RETENTION_TEST_ADMIN_DATABASE_SECRET_REF",
        "file:/run/secrets/postgres_password",
    )
    scheduler_store = SqlRetentionExecutionStore(
        async_sessionmaker(scheduler_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    archive_store = SqlRetentionExecutionStore(
        async_sessionmaker(archive_engine, expire_on_commit=False),
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        encryption_profile_fingerprint="b" * 64,
    )
    try:
        await _prepare(admin_engine, fixture)
        assert await scheduler_store.plan_next(
            workspace_id=fixture.workspace_id,
            executor_id=fixture.executor_id,
            archive_configuration_hash="a" * 64,
            maximum_attempts=2,
        )
        first = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-retry-one",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )
        assert first is not None and first.maximum_attempts == 2
        assert (
            await archive_store.mark_failed(
                claim=first,
                error_code="TRANSIENT_ARCHIVE_FAILURE",
                retryable=True,
            )
            == "RETRY_WAIT"
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=fixture.workspace_id,
                    subject_id=fixture.requester_id,
                )
                await session.execute(
                    update(RetentionExecutionJobModel)
                    .where(RetentionExecutionJobModel.id == first.job_id)
                    .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                )
        second = await archive_store.claim_next(
            workspace_id=fixture.workspace_id,
            worker_id="archive-retry-two",
            worker_principal_fingerprint="c" * 64,
            lease_seconds=300,
        )
        assert second is not None and second.attempt_count == 2
        assert (
            await archive_store.mark_failed(
                claim=second,
                error_code="TRANSIENT_ARCHIVE_FAILURE",
                retryable=True,
            )
            == "BLOCKED"
        )
        assert (
            await archive_store.claim_next(
                workspace_id=fixture.workspace_id,
                worker_id="archive-retry-three",
                worker_principal_fingerprint="c" * 64,
                lease_seconds=300,
            )
            is None
        )
        async with async_sessionmaker(admin_engine, expire_on_commit=False)() as session:
            attempts = tuple(
                await session.scalars(
                    select(RetentionExecutionAttemptModel).where(
                        RetentionExecutionAttemptModel.workspace_id == fixture.workspace_id
                    )
                )
            )
            assert len(attempts) == 2
            assert all(attempt.finished_at is not None for attempt in attempts)
    finally:
        try:
            await _cleanup(admin_engine, fixture)
        finally:
            await scheduler_engine.dispose()
            await archive_engine.dispose()
            await admin_engine.dispose()
