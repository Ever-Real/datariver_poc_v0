from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from datariver.application.ports import AdminAccessUnitOfWork
from datariver.application.services.admin_access import AdminAccessService
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.admin_access import MembershipAccessUpdate
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.infrastructure.db.admin_access import SqlAdminAccessUnitOfWork
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.secrets import SecretResolver

_DATABASE_URL_ENV = "DATARIVER_POLICY_TEST_DATABASE_URL"
_ADMIN_DATABASE_URL_ENV = "DATARIVER_POLICY_TEST_ADMIN_DATABASE_URL"
_CONFIRM_ISOLATED_ENV = "DATARIVER_POLICY_TEST_CONFIRM_ISOLATED"
_FORCED_SQLSTATE = "P0001"
_FORCED_CONSTRAINT = "ck_policy_test_forced_evidence_failure"
_SnapshotRow = tuple[object, ...]
_Snapshot = tuple[
    _SnapshotRow,
    _SnapshotRow | None,
    tuple[_SnapshotRow, ...],
    tuple[_SnapshotRow, ...],
    tuple[_SnapshotRow, ...],
]


@dataclass(frozen=True, slots=True)
class PolicyFixture:
    workspace_id: UUID
    actor_id: UUID
    checker_id: UUID
    target_id: UUID
    first_role_id: UUID
    second_role_id: UUID
    failure_role_id: UUID

    @classmethod
    def create(cls) -> PolicyFixture:
        return cls(*(uuid4() for _ in range(7)))

    @property
    def suffix(self) -> str:
        return self.workspace_id.hex[:12]

    @property
    def sequence_name(self) -> str:
        return f"datariver_policy_test_failure_{self.suffix}"

    @property
    def function_name(self) -> str:
        return f"datariver_policy_test_reject_event_{self.suffix}"

    @property
    def trigger_name(self) -> str:
        return f"datariver_policy_test_reject_event_{self.suffix}"


class MemoryDecisionWriter:
    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del decision, subject_id, workspace_id, resource_id, action, request_id


def _command(
    *, workspace_id: UUID, subject_id: UUID, expected_version: int, role_key: str | None
) -> MembershipAccessUpdate:
    groups = {"engineers"}
    if role_key is not None:
        groups.add(f"datariver-role-{role_key}")
    return MembershipAccessUpdate(
        workspace_id=workspace_id,
        target_subject_id=subject_id,
        expected_membership_version=expected_version,
        active=True,
        clearance=Classification.CONFIDENTIAL,
        groups=frozenset(groups),
        allowed_actions=frozenset({Action.CATALOG_READ, Action.CATALOG_SEARCH}),
        denied_actions=frozenset(),
    )


def _database_engine(*, url_env: str, secret_ref_env: str, default_secret_ref: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[url_env],
        connect_args={
            "password": SecretResolver().resolve(os.getenv(secret_ref_env, default_secret_ref))
        },
    )


async def _set_fixture_security_context(
    connection: AsyncConnection, fixture: PolicyFixture
) -> None:
    await connection.execute(
        text(
            """
            SELECT set_config('app.workspace_id', :workspace_id, true),
                   set_config('app.subject_id', :subject_id, true)
            """
        ),
        {
            "workspace_id": str(fixture.workspace_id),
            "subject_id": str(fixture.actor_id),
        },
    )


async def _prepare_fixture(admin_engine: AsyncEngine, fixture: PolicyFixture) -> None:
    administrator_attributes = json.dumps(
        {
            "groups": ["security-administrators"],
            "allowed_actions": ["admin.manage"],
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [],
        }
    )
    target_attributes = json.dumps(
        {
            "groups": ["engineers"],
            "allowed_actions": ["catalog.read", "catalog.search"],
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [],
        }
    )
    expires_at = datetime.now(UTC) + timedelta(days=30)
    async with admin_engine.begin() as connection:
        await _set_fixture_security_context(connection, fixture)
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version)
                VALUES
                    (:workspace_id, :slug, 'Policy test workspace', 'ACTIVE', '{}'::jsonb, 1)
                """
            ),
            {
                "workspace_id": fixture.workspace_id,
                "slug": f"policy-test-{fixture.suffix}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.subjects
                    (id, issuer, external_subject, display_name, email, active)
                VALUES
                    (:actor_id, 'policy-test', :actor_external, 'Policy actor', NULL, true),
                    (:checker_id, 'policy-test', :checker_external, 'Policy checker', NULL, true),
                    (:target_id, 'policy-test', :target_external, 'Policy target', NULL, true)
                """
            ),
            {
                "actor_id": fixture.actor_id,
                "actor_external": f"actor-{fixture.suffix}",
                "checker_id": fixture.checker_id,
                "checker_external": f"checker-{fixture.suffix}",
                "target_id": fixture.target_id,
                "target_external": f"target-{fixture.suffix}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.workspace_memberships
                    (workspace_id, subject_id, department_id, job_function, clearance,
                     attributes, active, access_expires_at, version)
                VALUES
                    (:workspace_id, :actor_id, NULL, 'SECURITY_ADMINISTRATOR', 3,
                     CAST(:administrator_attributes AS jsonb), true, :expires_at, 1),
                    (:workspace_id, :checker_id, NULL, 'SECURITY_ADMINISTRATOR', 3,
                     CAST(:administrator_attributes AS jsonb), true, :expires_at, 1),
                    (:workspace_id, :target_id, NULL, 'DATA_ENGINEER', 2,
                     CAST(:target_attributes AS jsonb), true, :expires_at, 1)
                """
            ),
            {
                "workspace_id": fixture.workspace_id,
                "actor_id": fixture.actor_id,
                "checker_id": fixture.checker_id,
                "target_id": fixture.target_id,
                "administrator_attributes": administrator_attributes,
                "target_attributes": target_attributes,
                "expires_at": expires_at,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.access_roles
                    (workspace_id, id, role_key, name, description, clearance, groups,
                     allowed_actions, denied_actions, allowed_system_ids, allowed_domain_ids,
                     active, updated_by, version)
                VALUES
                    (:workspace_id, :first_role_id, 'reader', 'Reader', '', 2,
                     '["engineers", "datariver-role-reader"]'::jsonb,
                     '["catalog.read", "catalog.search"]'::jsonb, '[]'::jsonb,
                     '[]'::jsonb, '[]'::jsonb, true, :actor_id, 1),
                    (:workspace_id, :second_role_id, 'steward', 'Steward', '', 2,
                     '["engineers", "datariver-role-steward"]'::jsonb,
                     '["catalog.read", "catalog.search"]'::jsonb, '[]'::jsonb,
                     '[]'::jsonb, '[]'::jsonb, true, :actor_id, 1),
                    (:workspace_id, :failure_role_id, 'failure', 'Failure role', '', 2,
                     '["engineers", "datariver-role-failure"]'::jsonb,
                     '["catalog.read", "catalog.search"]'::jsonb, '[]'::jsonb,
                     '[]'::jsonb, '[]'::jsonb, true, :actor_id, 1)
                """
            ),
            {
                "workspace_id": fixture.workspace_id,
                "actor_id": fixture.actor_id,
                "first_role_id": fixture.first_role_id,
                "second_role_id": fixture.second_role_id,
                "failure_role_id": fixture.failure_role_id,
            },
        )
        await connection.execute(text(f"CREATE SEQUENCE iam.{fixture.sequence_name} START WITH 1"))
        await connection.execute(
            text(
                f"""
                CREATE FUNCTION iam.{fixture.function_name}() RETURNS trigger
                LANGUAGE plpgsql
                SECURITY DEFINER
                SET search_path = pg_catalog, iam
                AS $function$
                BEGIN
                    IF NEW.role_id = '{fixture.failure_role_id}'::uuid THEN
                        PERFORM nextval('iam.{fixture.sequence_name}'::regclass);
                        RAISE EXCEPTION USING
                            ERRCODE = '{_FORCED_SQLSTATE}',
                            CONSTRAINT = '{_FORCED_CONSTRAINT}',
                            MESSAGE = 'forced policy-book assignment evidence failure';
                    END IF;
                    RETURN NEW;
                END;
                $function$
                """
            )
        )
        await connection.execute(
            text(
                f"""
                CREATE TRIGGER {fixture.trigger_name}
                BEFORE INSERT ON iam.access_role_assignment_events
                FOR EACH ROW EXECUTE FUNCTION iam.{fixture.function_name}()
                """
            )
        )


async def _cleanup_fixture(admin_engine: AsyncEngine, fixture: PolicyFixture) -> None:
    async with admin_engine.begin() as connection:
        await _set_fixture_security_context(connection, fixture)
        await connection.execute(
            text(
                f"DROP TRIGGER IF EXISTS {fixture.trigger_name} "
                "ON iam.access_role_assignment_events"
            )
        )
        await connection.execute(text(f"DROP FUNCTION IF EXISTS iam.{fixture.function_name}()"))
        await connection.execute(text(f"DROP SEQUENCE IF EXISTS iam.{fixture.sequence_name}"))
        await connection.execute(
            text("DELETE FROM integration.idempotency_keys WHERE workspace_id = :workspace_id"),
            {"workspace_id": fixture.workspace_id},
        )
        await connection.execute(
            text("DELETE FROM integration.outbox_events WHERE workspace_id = :workspace_id"),
            {"workspace_id": fixture.workspace_id},
        )
        await connection.execute(
            text(
                "DELETE FROM iam.access_role_assignment_events WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": fixture.workspace_id},
        )
        await connection.execute(
            text("DELETE FROM iam.access_role_assignments WHERE workspace_id = :workspace_id"),
            {"workspace_id": fixture.workspace_id},
        )
        await connection.execute(
            text("DELETE FROM iam.access_roles WHERE workspace_id = :workspace_id"),
            {"workspace_id": fixture.workspace_id},
        )
        await connection.execute(
            text("DELETE FROM iam.workspace_memberships WHERE workspace_id = :workspace_id"),
            {"workspace_id": fixture.workspace_id},
        )
        await connection.execute(
            text("DELETE FROM platform.workspaces WHERE id = :workspace_id"),
            {"workspace_id": fixture.workspace_id},
        )
        await connection.execute(
            text("DELETE FROM iam.subjects WHERE id IN (:actor_id, :checker_id, :target_id)"),
            {
                "actor_id": fixture.actor_id,
                "checker_id": fixture.checker_id,
                "target_id": fixture.target_id,
            },
        )


async def _snapshot(
    session_factory: async_sessionmaker[AsyncSession], fixture: PolicyFixture
) -> _Snapshot:
    async with session_factory() as session:
        await set_security_context(
            session, workspace_id=fixture.workspace_id, subject_id=fixture.actor_id
        )
        membership = (
            await session.execute(
                text(
                    """
                    SELECT version, active, clearance, attributes::text
                    FROM iam.workspace_memberships
                    WHERE workspace_id = :workspace_id AND subject_id = :subject_id
                    """
                ),
                {"workspace_id": fixture.workspace_id, "subject_id": fixture.target_id},
            )
        ).one()
        assignment = (
            await session.execute(
                text(
                    """
                    SELECT id::text, role_id::text, role_version, membership_version,
                           access_payload_hash, assigned_by::text, active, version,
                           created_at, updated_at
                    FROM iam.access_role_assignments
                    WHERE workspace_id = :workspace_id AND subject_id = :subject_id
                    """
                ),
                {"workspace_id": fixture.workspace_id, "subject_id": fixture.target_id},
            )
        ).one_or_none()
        events = (
            await session.execute(
                text(
                    """
                    SELECT id::text, event_type, previous_role_id::text, previous_role_version,
                           role_id::text, role_version, membership_version, access_payload_hash,
                           actor_id::text, occurred_at
                    FROM iam.access_role_assignment_events
                    WHERE workspace_id = :workspace_id AND subject_id = :subject_id
                    ORDER BY occurred_at, id
                    """
                ),
                {"workspace_id": fixture.workspace_id, "subject_id": fixture.target_id},
            )
        ).all()
        outbox = (
            await session.execute(
                text(
                    """
                    SELECT id::text, event_type, payload::text, created_at
                    FROM integration.outbox_events
                    WHERE workspace_id = :workspace_id
                      AND aggregate_type = 'workspace_membership'
                      AND aggregate_id = :subject_id
                    ORDER BY created_at, id
                    """
                ),
                {"workspace_id": fixture.workspace_id, "subject_id": fixture.target_id},
            )
        ).all()
        idempotency = (
            await session.execute(
                text(
                    """
                    SELECT operation, key_hash, request_hash, result::text, created_at, expires_at
                    FROM integration.idempotency_keys
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                    ORDER BY key_hash
                    """
                ),
                {
                    "workspace_id": fixture.workspace_id,
                    "operation": f"admin.membership.update:{fixture.target_id}",
                },
            )
        ).all()
    return (
        tuple(membership),
        tuple(assignment) if assignment is not None else None,
        tuple(tuple(row) for row in events),
        tuple(tuple(row) for row in outbox),
        tuple(tuple(row) for row in idempotency),
    )


async def _sequence_value(admin_engine: AsyncEngine, fixture: PolicyFixture) -> int | None:
    async with admin_engine.connect() as connection:
        value = await connection.scalar(
            text(
                """
                SELECT last_value
                FROM pg_catalog.pg_sequences
                WHERE schemaname = 'iam' AND sequencename = :sequence_name
                """
            ),
            {"sequence_name": fixture.sequence_name},
        )
    return cast(int | None, value)


def _dbapi_attribute(error: DBAPIError, name: str) -> object | None:
    original = error.orig
    value = getattr(original, name, None)
    if value is not None:
        return cast(object, value)
    cause = getattr(original, "__cause__", None)
    return cast(object | None, getattr(cause, name, None))


_POSTGRES_ENABLED = (
    bool(os.getenv(_DATABASE_URL_ENV))
    and bool(os.getenv(_ADMIN_DATABASE_URL_ENV))
    and os.getenv(_CONFIRM_ISOLATED_ENV) == "1"
)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated PostgreSQL app/admin URLs are required",
)
async def test_role_assignment_transition_and_failure_rollback_on_postgres() -> None:
    fixture = PolicyFixture.create()
    app_engine = _database_engine(
        url_env=_DATABASE_URL_ENV,
        secret_ref_env="DATARIVER_POLICY_TEST_DATABASE_SECRET_REF",
        default_secret_ref="file:/run/secrets/postgres_app_password",
    )
    admin_engine = _database_engine(
        url_env=_ADMIN_DATABASE_URL_ENV,
        secret_ref_env="DATARIVER_POLICY_TEST_ADMIN_DATABASE_SECRET_REF",
        default_secret_ref="file:/run/secrets/postgres_password",
    )
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    service = AdminAccessService(
        cast(
            Callable[[], AdminAccessUnitOfWork],
            lambda: SqlAdminAccessUnitOfWork(session_factory),
        ),
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        fallback_enabled=False,
        fallback_ttl_seconds=300,
    )
    now = datetime.now(UTC)
    subject = SubjectAttributes(
        subject_id=fixture.actor_id,
        workspace_id=fixture.workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.ADMIN_MANAGE}),
        denied_actions=frozenset(),
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
        authentication_time=now,
    )
    environment = EnvironmentAttributes(requested_at=now)

    async with admin_engine.connect() as connection:
        access_roles_rls = (
            await connection.execute(
                text(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE oid = 'iam.access_roles'::regclass
                    """
                )
            )
        ).one()
    assert tuple(access_roles_rls) == (True, True)

    async def apply(
        *,
        role_id: UUID | None,
        role_version: int | None,
        role_key: str | None,
        expected_version: int,
        suffix: str,
    ) -> int:
        return await service.update_membership_with_hardware_key(
            command=_command(
                workspace_id=fixture.workspace_id,
                subject_id=fixture.target_id,
                expected_version=expected_version,
                role_key=role_key,
            ),
            subject=subject,
            environment=environment,
            request_id=f"postgres-role-{suffix}",
            idempotency_key=f"postgres-policy-book-{suffix}-0001",
            request_hash=canonical_json_hash({"suffix": suffix}),
            role_id=role_id,
            role_version=role_version,
            role_transition=True,
        )

    try:
        await _prepare_fixture(admin_engine, fixture)
        assert await _sequence_value(admin_engine, fixture) is None

        async with app_engine.begin() as connection:
            await _set_fixture_security_context(connection, fixture)
            canonical_role_id = await connection.scalar(
                text(
                    """
                    SELECT id
                    FROM iam.access_roles
                    WHERE workspace_id = :workspace_id
                      AND role_kind = 'CANONICAL_ADMIN'
                    """
                ),
                {"workspace_id": fixture.workspace_id},
            )
        assert isinstance(canonical_role_id, UUID)

        with pytest.raises(DBAPIError) as assignment_rejection:
            async with app_engine.begin() as connection:
                await _set_fixture_security_context(connection, fixture)
                await connection.execute(
                    text(
                        """
                        INSERT INTO iam.access_role_assignments (
                            id, workspace_id, subject_id, role_id, role_kind, role_version,
                            membership_version, access_payload_hash, assigned_by, active, version
                        ) VALUES (
                            :id, :workspace_id, :target_id, :role_id, 'CANONICAL_ADMIN', 1,
                            1, :access_hash, :actor_id, true, 1
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": fixture.workspace_id,
                        "target_id": fixture.target_id,
                        "role_id": canonical_role_id,
                        "access_hash": "a" * 64,
                        "actor_id": fixture.actor_id,
                    },
                )
        assert _dbapi_attribute(assignment_rejection.value, "sqlstate") == "23514"

        rejected_subject_id = uuid4()
        rejected_external_subject = f"canonical-provision-{fixture.suffix}"
        with pytest.raises(DBAPIError) as provisioning_rejection:
            async with app_engine.begin() as connection:
                await _set_fixture_security_context(connection, fixture)
                await connection.execute(
                    text(
                        """
                        SELECT iam.provision_workspace_identity(
                            :subject_id, :workspace_id, 'policy-test', :external_subject,
                            'Rejected canonical assignment', 'rejected@example.test', NULL,
                            'DATA_ENGINEER', :role_id, :expires_at
                        )
                        """
                    ),
                    {
                        "subject_id": rejected_subject_id,
                        "workspace_id": fixture.workspace_id,
                        "external_subject": rejected_external_subject,
                        "role_id": canonical_role_id,
                        "expires_at": datetime.now(UTC) + timedelta(days=30),
                    },
                )
        assert _dbapi_attribute(provisioning_rejection.value, "sqlstate") == "23514"
        async with admin_engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM iam.subjects WHERE id = :subject_id"),
                    {"subject_id": rejected_subject_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM iam.access_role_assignments
                        WHERE workspace_id = :workspace_id AND subject_id = :subject_id
                        """
                    ),
                    {"workspace_id": fixture.workspace_id, "subject_id": fixture.target_id},
                )
                == 0
            )

        assert (
            await apply(
                role_id=fixture.first_role_id,
                role_version=1,
                role_key="reader",
                expected_version=1,
                suffix="assigned",
            )
            == 2
        )
        assigned_snapshot = await _snapshot(session_factory, fixture)
        with pytest.raises(ConflictError, match="already has this exact access role"):
            await apply(
                role_id=fixture.first_role_id,
                role_version=1,
                role_key="reader",
                expected_version=2,
                suffix="reaffirmed",
            )
        assert await _snapshot(session_factory, fixture) == assigned_snapshot

        assert (
            await apply(
                role_id=fixture.second_role_id,
                role_version=1,
                role_key="steward",
                expected_version=2,
                suffix="reassigned",
            )
            == 3
        )
        assert (
            await apply(
                role_id=None,
                role_version=None,
                role_key=None,
                expected_version=3,
                suffix="removed",
            )
            == 4
        )

        completed_snapshot = await _snapshot(session_factory, fixture)
        with pytest.raises(ConflictError, match="changed before assignment"):
            await apply(
                role_id=fixture.first_role_id,
                role_version=999,
                role_key="reader",
                expected_version=4,
                suffix="stale",
            )
        assert await _snapshot(session_factory, fixture) == completed_snapshot

        with pytest.raises(DBAPIError) as forced_failure:
            await apply(
                role_id=fixture.failure_role_id,
                role_version=1,
                role_key="failure",
                expected_version=4,
                suffix="failure",
            )
        assert _dbapi_attribute(forced_failure.value, "sqlstate") == _FORCED_SQLSTATE
        assert _dbapi_attribute(forced_failure.value, "constraint_name") == _FORCED_CONSTRAINT
        assert "forced policy-book assignment evidence failure" in str(forced_failure.value)
        assert await _sequence_value(admin_engine, fixture) == 1
        assert await _snapshot(session_factory, fixture) == completed_snapshot

        async with session_factory() as session:
            await set_security_context(
                session, workspace_id=fixture.workspace_id, subject_id=fixture.actor_id
            )
            transition_rows = (
                await session.execute(
                    text(
                        """
                        SELECT event_type, previous_role_id, previous_role_version,
                               role_id, role_version, membership_version,
                               access_payload_hash, actor_id
                        FROM iam.access_role_assignment_events
                        WHERE workspace_id = :workspace_id AND subject_id = :subject_id
                        ORDER BY occurred_at, id
                        """
                    ),
                    {"workspace_id": fixture.workspace_id, "subject_id": fixture.target_id},
                )
            ).all()
            outbox_versions = (
                await session.scalars(
                    text(
                        """
                        SELECT payload ->> 'membership_version'
                        FROM integration.outbox_events
                        WHERE workspace_id = :workspace_id
                          AND aggregate_type = 'workspace_membership'
                          AND aggregate_id = :subject_id
                        ORDER BY created_at, id
                        """
                    ),
                    {"workspace_id": fixture.workspace_id, "subject_id": fixture.target_id},
                )
            ).all()
            idempotency_count = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM integration.idempotency_keys
                    WHERE workspace_id = :workspace_id AND operation = :operation
                    """
                ),
                {
                    "workspace_id": fixture.workspace_id,
                    "operation": f"admin.membership.update:{fixture.target_id}",
                },
            )

        first_hash = canonical_json_hash(
            _command(
                workspace_id=fixture.workspace_id,
                subject_id=fixture.target_id,
                expected_version=1,
                role_key="reader",
            ).access_document()
        )
        second_hash = canonical_json_hash(
            _command(
                workspace_id=fixture.workspace_id,
                subject_id=fixture.target_id,
                expected_version=2,
                role_key="steward",
            ).access_document()
        )
        removed_hash = canonical_json_hash(
            _command(
                workspace_id=fixture.workspace_id,
                subject_id=fixture.target_id,
                expected_version=3,
                role_key=None,
            ).access_document()
        )
        assert [tuple(row) for row in transition_rows] == [
            (
                "ASSIGNED",
                None,
                None,
                fixture.first_role_id,
                1,
                2,
                first_hash,
                fixture.actor_id,
            ),
            (
                "REASSIGNED",
                fixture.first_role_id,
                1,
                fixture.second_role_id,
                1,
                3,
                second_hash,
                fixture.actor_id,
            ),
            (
                "REMOVED",
                fixture.second_role_id,
                1,
                None,
                None,
                4,
                removed_hash,
                fixture.actor_id,
            ),
        ]
        assert outbox_versions == ["2", "3", "4"]
        assert idempotency_count == 3
        membership, assignment, events, outbox, idempotency = completed_snapshot
        assert membership[:3] == (4, True, 2)
        assert assignment is not None
        assert assignment[1:8] == (
            str(fixture.second_role_id),
            1,
            4,
            removed_hash,
            str(fixture.actor_id),
            False,
            3,
        )
        assert len(events) == len(outbox) == len(idempotency) == 3
    finally:
        try:
            await _cleanup_fixture(admin_engine, fixture)
        finally:
            await app_engine.dispose()
            await admin_engine.dispose()
