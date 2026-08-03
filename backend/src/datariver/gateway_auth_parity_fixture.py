from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import timedelta
from enum import StrEnum
from typing import NoReturn, Protocol
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.config import get_settings
from datariver.domain.authz import Classification
from datariver.domain.common import utc_now
from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentModel,
    CanonicalAdminBindingModel,
    ProfileRoleAssignmentModel,
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.secrets import SecretResolver

FIXTURE_CONTRACT = "SEC-GATEWAY-AUTH-PARITY-001-A-V1"
LOCAL_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000100")
ALLOW_SUBJECT_ID = UUID("00000000-0000-4000-8000-00000000010a")
DENY_SUBJECT_ID = UUID("00000000-0000-4000-8000-00000000010b")
_EXACT_REQUEST_KEYS = frozenset(
    {
        "contract",
        "operation",
        "allow_external_subject",
        "deny_external_subject",
    }
)


class GatewayAuthParityFixtureError(RuntimeError):
    """Sanitized fixed failure from the development-only parity fixture."""


class FixtureOperation(StrEnum):
    REQUIRE_ABSENT = "require-absent"
    PREPARE = "prepare"
    ENABLE = "enable"
    REVOKE_ALLOW_MEMBERSHIP = "revoke-allow-membership"
    CLEANUP = "cleanup"
    REQUIRE_ZERO_RESIDUAL = "require-zero-residual"


class FixtureIdentityKind(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class FixtureRequest:
    contract: str
    operation: FixtureOperation
    allow_external_subject: str
    deny_external_subject: str


@dataclass(frozen=True, slots=True)
class FixtureIdentity:
    kind: FixtureIdentityKind
    subject_id: UUID
    external_subject: str
    display_name: str
    job_function: str
    groups: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    denied_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixtureEvidence:
    state: str
    subject_count: int
    membership_count: int
    privilege_residual_count: int


class GatewayAuthParityFixtureRepository(Protocol):
    async def require_absent(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def prepare(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def enable(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def revoke_allow_membership(self, identity: FixtureIdentity) -> None: ...

    async def cleanup(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def require_zero_residual(self, identities: tuple[FixtureIdentity, ...]) -> None: ...


def _invalid() -> NoReturn:
    raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_INPUT_INVALID")


def parse_fixture_request(document: object) -> FixtureRequest:
    if not isinstance(document, dict) or set(document) != _EXACT_REQUEST_KEYS:
        _invalid()
    try:
        contract = document["contract"]
        operation = FixtureOperation(document["operation"])
        allow_external_subject = str(UUID(document["allow_external_subject"]))
        deny_external_subject = str(UUID(document["deny_external_subject"]))
    except (KeyError, TypeError, ValueError):
        _invalid()
    if (
        contract != FIXTURE_CONTRACT
        or allow_external_subject == deny_external_subject
        or len(allow_external_subject) != 36
        or len(deny_external_subject) != 36
    ):
        _invalid()
    return FixtureRequest(
        contract=contract,
        operation=operation,
        allow_external_subject=allow_external_subject,
        deny_external_subject=deny_external_subject,
    )


def fixture_identities(request: FixtureRequest) -> tuple[FixtureIdentity, ...]:
    if request.contract != FIXTURE_CONTRACT:
        _invalid()
    try:
        allow_external_subject = str(UUID(request.allow_external_subject))
        deny_external_subject = str(UUID(request.deny_external_subject))
    except ValueError:
        _invalid()
    if allow_external_subject == deny_external_subject:
        _invalid()
    actions = ("change.read", "kg.read")
    return (
        FixtureIdentity(
            kind=FixtureIdentityKind.ALLOW,
            subject_id=ALLOW_SUBJECT_ID,
            external_subject=allow_external_subject,
            display_name="DataRiver Gateway Parity Allow",
            job_function="GATEWAY_AUTH_PARITY_PROBE",
            groups=("gateway-auth-parity-probe",),
            allowed_actions=actions,
            denied_actions=(),
        ),
        FixtureIdentity(
            kind=FixtureIdentityKind.DENY,
            subject_id=DENY_SUBJECT_ID,
            external_subject=deny_external_subject,
            display_name="DataRiver Gateway Parity Deny",
            job_function="GATEWAY_AUTH_PARITY_PROBE",
            groups=("gateway-auth-parity-probe",),
            allowed_actions=(),
            denied_actions=actions,
        ),
    )


class GatewayAuthParityFixtureService:
    def __init__(self, repository: GatewayAuthParityFixtureRepository) -> None:
        self._repository = repository

    async def execute(self, request: FixtureRequest) -> FixtureEvidence:
        identities = fixture_identities(request)
        operation = request.operation
        if operation is FixtureOperation.REQUIRE_ABSENT:
            await self._repository.require_absent(identities)
            return FixtureEvidence("absent", 0, 0, 0)
        if operation is FixtureOperation.PREPARE:
            await self._repository.require_absent(identities)
            await self._repository.prepare(identities)
            return FixtureEvidence("prepared", 2, 2, 0)
        if operation is FixtureOperation.ENABLE:
            await self._repository.enable(identities)
            return FixtureEvidence("enabled", 2, 2, 0)
        if operation is FixtureOperation.REVOKE_ALLOW_MEMBERSHIP:
            await self._repository.revoke_allow_membership(identities[0])
            return FixtureEvidence("membership-revoked", 2, 2, 0)
        if operation is FixtureOperation.CLEANUP:
            await self._repository.cleanup(identities)
            await self._repository.require_zero_residual(identities)
            return FixtureEvidence("clean", 0, 0, 0)
        if operation is FixtureOperation.REQUIRE_ZERO_RESIDUAL:
            await self._repository.require_zero_residual(identities)
            return FixtureEvidence("zero-residual", 0, 0, 0)
        _invalid()


class SqlGatewayAuthParityFixtureRepository:
    def __init__(self, session: AsyncSession, *, issuer: str) -> None:
        self._session = session
        self._issuer = issuer

    async def _subjects(self, identities: tuple[FixtureIdentity, ...]) -> list[SubjectModel]:
        subject_ids = tuple(identity.subject_id for identity in identities)
        external_subjects = tuple(identity.external_subject for identity in identities)
        return list(
            (
                await self._session.scalars(
                    select(SubjectModel).where(
                        or_(
                            SubjectModel.id.in_(subject_ids),
                            (
                                (SubjectModel.issuer == self._issuer)
                                & SubjectModel.external_subject.in_(external_subjects)
                            ),
                        )
                    )
                )
            ).all()
        )

    async def _privilege_residual_counts(self, subject_ids: tuple[UUID, ...]) -> tuple[int, ...]:
        return (
            len(
                (
                    await self._session.scalars(
                        select(AccessRoleAssignmentModel.subject_id).where(
                            AccessRoleAssignmentModel.subject_id.in_(subject_ids)
                        )
                    )
                ).all()
            ),
            len(
                (
                    await self._session.scalars(
                        select(ProfileRoleAssignmentModel.subject_id).where(
                            ProfileRoleAssignmentModel.subject_id.in_(subject_ids)
                        )
                    )
                ).all()
            ),
            len(
                (
                    await self._session.scalars(
                        select(CanonicalAdminBindingModel.subject_id).where(
                            CanonicalAdminBindingModel.subject_id.in_(subject_ids)
                        )
                    )
                ).all()
            ),
        )

    async def require_absent(self, identities: tuple[FixtureIdentity, ...]) -> None:
        subject_ids = tuple(identity.subject_id for identity in identities)
        subjects = await self._subjects(identities)
        membership_count = await self._session.scalar(
            select(func.count())
            .select_from(WorkspaceMembershipModel)
            .where(
                WorkspaceMembershipModel.workspace_id == LOCAL_WORKSPACE_ID,
                WorkspaceMembershipModel.subject_id.in_(subject_ids),
            )
        )
        privilege_residual_counts = await self._privilege_residual_counts(subject_ids)
        if subjects or membership_count != 0 or any(privilege_residual_counts):
            raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT")

    async def prepare(self, identities: tuple[FixtureIdentity, ...]) -> None:
        workspace = await self._session.get(WorkspaceModel, LOCAL_WORKSPACE_ID)
        if workspace is None or workspace.status != "ACTIVE":
            raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_WORKSPACE_INVALID")
        expires_at = utc_now() + timedelta(hours=1)
        for identity in identities:
            self._session.add(
                SubjectModel(
                    id=identity.subject_id,
                    issuer=self._issuer,
                    external_subject=identity.external_subject,
                    display_name=identity.display_name,
                    email=None,
                    active=False,
                )
            )
            self._session.add(
                WorkspaceMembershipModel(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    subject_id=identity.subject_id,
                    department_id=None,
                    job_function=identity.job_function,
                    clearance=int(Classification.PUBLIC),
                    attributes={
                        "groups": list(identity.groups),
                        "allowed_actions": list(identity.allowed_actions),
                        "denied_actions": list(identity.denied_actions),
                        "allowed_system_ids": [],
                        "allowed_domain_ids": [],
                        "default_workspace": True,
                        "bootstrap": FIXTURE_CONTRACT,
                    },
                    active=False,
                    access_expires_at=expires_at,
                )
            )
        await self._session.flush()

    async def _exact_rows(
        self,
        identities: tuple[FixtureIdentity, ...],
        *,
        cleanup: bool = False,
        allow_absent: bool = False,
    ) -> tuple[tuple[SubjectModel, WorkspaceMembershipModel], ...]:
        locked: list[
            tuple[FixtureIdentity, SubjectModel | None, WorkspaceMembershipModel | None]
        ] = []
        for identity in identities:
            subject = await self._session.get(
                SubjectModel,
                identity.subject_id,
                with_for_update=True,
            )
            membership = await self._session.get(
                WorkspaceMembershipModel,
                {"workspace_id": LOCAL_WORKSPACE_ID, "subject_id": identity.subject_id},
                with_for_update=True,
            )
            locked.append((identity, subject, membership))
        if allow_absent and all(
            subject is None and membership is None for _identity, subject, membership in locked
        ):
            return ()
        if any(subject is None or membership is None for _identity, subject, membership in locked):
            raise GatewayAuthParityFixtureError(
                "GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED"
                if cleanup
                else "GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID"
            )
        rows: list[tuple[SubjectModel, WorkspaceMembershipModel]] = []
        for identity, nullable_subject, nullable_membership in locked:
            if nullable_subject is None or nullable_membership is None:
                raise GatewayAuthParityFixtureError(
                    "GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED"
                    if cleanup
                    else "GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID"
                )
            subject = nullable_subject
            membership = nullable_membership
            allowed_states = {(False, False), (True, True)}
            if cleanup and identity.kind is FixtureIdentityKind.ALLOW:
                allowed_states.add((True, False))
            lifecycle = (subject.active, membership.active)
            expected_version = {
                (False, False): 1,
                (True, True): 2,
                (True, False): 3,
            }.get(lifecycle)
            if (
                subject.issuer != self._issuer
                or subject.external_subject != identity.external_subject
                or subject.display_name != identity.display_name
                or subject.email is not None
                or membership.job_function != identity.job_function
                or membership.department_id is not None
                or membership.clearance != int(Classification.PUBLIC)
                or membership.attributes
                != {
                    "groups": list(identity.groups),
                    "allowed_actions": list(identity.allowed_actions),
                    "denied_actions": list(identity.denied_actions),
                    "allowed_system_ids": [],
                    "allowed_domain_ids": [],
                    "default_workspace": True,
                    "bootstrap": FIXTURE_CONTRACT,
                }
                or membership.access_expires_at is None
                or membership.access_expires_at <= utc_now()
                or lifecycle not in allowed_states
                or membership.version != expected_version
            ):
                raise GatewayAuthParityFixtureError(
                    "GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED"
                    if cleanup
                    else "GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID"
                )
            rows.append((subject, membership))
        return tuple(rows)

    async def enable(self, identities: tuple[FixtureIdentity, ...]) -> None:
        rows = await self._exact_rows(identities)
        if any(subject.active or membership.active for subject, membership in rows):
            raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        for subject, membership in rows:
            subject.active = True
            membership.active = True
            membership.version += 1
        await self._session.flush()

    async def revoke_allow_membership(self, identity: FixtureIdentity) -> None:
        rows = await self._exact_rows((identity,))
        _subject, membership = rows[0]
        if not membership.active:
            raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        membership.active = False
        membership.version += 1
        await self._session.flush()

    async def cleanup(self, identities: tuple[FixtureIdentity, ...]) -> None:
        subject_ids = tuple(identity.subject_id for identity in identities)
        rows = await self._exact_rows(identities, cleanup=True, allow_absent=True)
        existing = await self._subjects(identities)
        membership_count = await self._session.scalar(
            select(func.count())
            .select_from(WorkspaceMembershipModel)
            .where(WorkspaceMembershipModel.subject_id.in_(subject_ids))
        )
        privilege_residual_counts = await self._privilege_residual_counts(subject_ids)
        if (
            not rows
            and not existing
            and membership_count == 0
            and not any(privilege_residual_counts)
        ):
            return
        if not rows or any(privilege_residual_counts):
            raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED")
        exact_subjects = {subject.id: subject for subject, _membership in rows}
        if (
            len(existing) != len(identities)
            or membership_count != len(identities)
            or set(exact_subjects) != set(subject_ids)
            or any(exact_subjects.get(subject.id) is not subject for subject in existing)
        ):
            raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED")
        await self._session.execute(
            delete(WorkspaceMembershipModel).where(
                WorkspaceMembershipModel.workspace_id == LOCAL_WORKSPACE_ID,
                WorkspaceMembershipModel.subject_id.in_(subject_ids),
            )
        )
        await self._session.execute(delete(SubjectModel).where(SubjectModel.id.in_(subject_ids)))
        await self._session.flush()

    async def require_zero_residual(self, identities: tuple[FixtureIdentity, ...]) -> None:
        subject_ids = tuple(identity.subject_id for identity in identities)
        external_subjects = tuple(identity.external_subject for identity in identities)
        residual_subject_rows = list(
            (
                await self._session.scalars(
                    select(SubjectModel.id).where(
                        or_(
                            SubjectModel.id.in_(subject_ids),
                            (
                                (SubjectModel.issuer == self._issuer)
                                & SubjectModel.external_subject.in_(external_subjects)
                            ),
                        )
                    )
                )
            ).all()
        )
        residual_subject_ids = tuple(dict.fromkeys((*subject_ids, *residual_subject_rows)))
        privilege_residual_counts = await self._privilege_residual_counts(residual_subject_ids)
        counts = (
            len(residual_subject_rows),
            len(
                (
                    await self._session.scalars(
                        select(WorkspaceMembershipModel.subject_id).where(
                            WorkspaceMembershipModel.subject_id.in_(residual_subject_ids)
                        )
                    )
                ).all()
            ),
            *privilege_residual_counts,
        )
        if any(counts):
            raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_RESIDUAL")


async def execute_fixture_request(request: FixtureRequest) -> FixtureEvidence:
    settings = get_settings()
    if settings.app_env != "development":
        raise GatewayAuthParityFixtureError("GATEWAY_AUTH_PARITY_FIXTURE_ENVIRONMENT_INVALID")
    resolver = SecretResolver()
    database = Database(
        settings.bootstrap_database_url,
        password=resolver.resolve(settings.bootstrap_database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-gateway-auth-parity-fixture",
    )
    try:
        async with database.session_factory() as session, session.begin():
            repository = SqlGatewayAuthParityFixtureRepository(session, issuer=settings.oidc_issuer)
            return await GatewayAuthParityFixtureService(repository).execute(request)
    finally:
        await database.close()


def main() -> int:
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {value.value for value in FixtureOperation}:
            _invalid()
        raw = sys.stdin.buffer.read(4_097)
        if not raw or len(raw) > 4_096:
            _invalid()
        document = json.loads(raw)
        request = parse_fixture_request(document)
        if request.operation.value != sys.argv[1]:
            _invalid()
        evidence = asyncio.run(execute_fixture_request(request))
    except BaseException:
        print("GATEWAY_AUTH_PARITY_FIXTURE_FAILED", file=sys.stderr)
        return 2
    print(json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
