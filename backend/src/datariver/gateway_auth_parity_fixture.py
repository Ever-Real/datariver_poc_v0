from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import stat
import sys
from dataclasses import asdict, dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
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
MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES = 256
MAXIMUM_FIXTURE_SOURCE_BYTES = 512 * 1024
LOCAL_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000100")
ALLOW_SUBJECT_ID = UUID("00000000-0000-4000-8000-00000000010a")
DENY_SUBJECT_ID = UUID("00000000-0000-4000-8000-00000000010b")
_EXACT_REQUEST_KEYS = frozenset(
    {
        "contract",
        "operation",
        "allow_external_subject",
        "deny_external_subject",
        "source_sha256",
    }
)


class FixtureDiagnosticOperation(StrEnum):
    """Closed read-only operation vocabulary for the fixture diagnostic."""

    REQUIRE_ABSENT = "REQUIRE_ABSENT"


class FixtureDiagnosticPredicate(StrEnum):
    """Value-free first-predicate evidence from the require-absent boundary."""

    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a password.
    FIXED_INPUT_PROTOCOL = "FIXED_INPUT_PROTOCOL"
    ENVIRONMENT_DEPENDENCY = "ENVIRONMENT_DEPENDENCY"
    REPOSITORY_NOT_ABSENT = "REPOSITORY_NOT_ABSENT"
    REPOSITORY_QUERY_DEPENDENCY = "REPOSITORY_QUERY_DEPENDENCY"
    IMAGE_PROVENANCE = "IMAGE_PROVENANCE"
    PROCESS_SPAWN = "PROCESS_SPAWN"
    PROCESS_TIMEOUT = "PROCESS_TIMEOUT"
    PROCESS_NONZERO = "PROCESS_NONZERO"
    OUTPUT_SIZE = "OUTPUT_SIZE"
    OUTPUT_LINE = "OUTPUT_LINE"
    OUTPUT_JSON = "OUTPUT_JSON"
    OUTPUT_SHAPE = "OUTPUT_SHAPE"
    OUTPUT_TUPLE = "OUTPUT_TUPLE"
    UNKNOWN = "UNKNOWN"


class GatewayAuthParityFixtureError(RuntimeError):
    """Sanitized fixed failure from the development-only parity fixture."""

    def __init__(
        self,
        classification: str,
        *,
        diagnostic_predicate: FixtureDiagnosticPredicate | None = None,
    ) -> None:
        self.diagnostic_predicate = diagnostic_predicate
        super().__init__(classification)


class FixtureDiagnosticProtocolError(GatewayAuthParityFixtureError):
    """Fixed parser failure carrying only a closed predicate."""

    def __init__(self, predicate: FixtureDiagnosticPredicate) -> None:
        self.predicate = predicate
        super().__init__(
            "GATEWAY_AUTH_PARITY_FIXTURE_DIAGNOSTIC_INVALID",
            diagnostic_predicate=predicate,
        )


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
    source_sha256: str


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


@dataclass(frozen=True, slots=True)
class FixtureDiagnosticEnvelope:
    operation: FixtureDiagnosticOperation
    predicate: FixtureDiagnosticPredicate


@dataclass(frozen=True, slots=True)
class _FixtureDiagnosticJsonObject:
    pairs: tuple[tuple[str, object], ...]


def _capture_fixture_diagnostic_object(
    pairs: list[tuple[str, object]],
) -> _FixtureDiagnosticJsonObject:
    return _FixtureDiagnosticJsonObject(tuple(pairs))


def format_fixture_diagnostic_line(evidence: FixtureDiagnosticEnvelope) -> str:
    """Render the exact bounded value-free child/parent protocol line."""

    line = json.dumps(
        {
            "operation": evidence.operation.value,
            "predicate": evidence.predicate.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(line.encode("utf-8")) > MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES:
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_SIZE)
    return line


def parse_fixture_diagnostic_line(raw: str) -> FixtureDiagnosticEnvelope:
    """Accept only one exact closed line and never retain its rejected input."""

    if len(raw.encode("utf-8")) > MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES:
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_SIZE)
    if not raw or "\n" in raw or "\r" in raw:
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_LINE)
    try:
        parsed = json.loads(raw, object_pairs_hook=_capture_fixture_diagnostic_object)
    except (json.JSONDecodeError, UnicodeError):
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_JSON) from None
    if not isinstance(parsed, _FixtureDiagnosticJsonObject):
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_SHAPE)
    keys = tuple(key for key, _value in parsed.pairs)
    if len(keys) != len(set(keys)):
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
    document = dict(parsed.pairs)
    if set(document) != {"operation", "predicate"}:
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_SHAPE)
    try:
        operation_value = document["operation"]
        predicate_value = document["predicate"]
        if not isinstance(operation_value, str) or not isinstance(predicate_value, str):
            raise ValueError
        operation = FixtureDiagnosticOperation(operation_value)
        predicate = FixtureDiagnosticPredicate(predicate_value)
    except (TypeError, ValueError):
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE) from None
    if operation is not FixtureDiagnosticOperation.REQUIRE_ABSENT:
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
    return FixtureDiagnosticEnvelope(operation=operation, predicate=predicate)


def fixture_diagnostic_failure_classification(
    predicate: FixtureDiagnosticPredicate,
) -> str:
    """Map one non-PASS predicate to an allowlisted outer failure."""

    if predicate is FixtureDiagnosticPredicate.PASS:
        raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
    return f"GATEWAY_AUTH_PARITY_FIXTURE_REQUIRE_ABSENT_{predicate.value}"


def _fixture_source_invalid() -> NoReturn:
    raise GatewayAuthParityFixtureError(
        "GATEWAY_AUTH_PARITY_FIXTURE_IMAGE_PROVENANCE_INVALID",
        diagnostic_predicate=FixtureDiagnosticPredicate.IMAGE_PROVENANCE,
    )


def current_fixture_source_sha256() -> str:
    """Fingerprint only this exact regular linked source file without following links."""

    path = Path(__file__)
    descriptor = -1
    content = bytearray()
    try:
        linked = path.lstat()
        if (
            not stat.S_ISREG(linked.st_mode)
            or linked.st_nlink != 1
            or linked.st_size <= 0
            or linked.st_size > MAXIMUM_FIXTURE_SOURCE_BYTES
        ):
            _fixture_source_invalid()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink, opened.st_size) != (
            linked.st_dev,
            linked.st_ino,
            linked.st_mode,
            linked.st_nlink,
            linked.st_size,
        ):
            _fixture_source_invalid()
        while True:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAXIMUM_FIXTURE_SOURCE_BYTES - len(content) + 1),
            )
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAXIMUM_FIXTURE_SOURCE_BYTES:
                _fixture_source_invalid()
        rechecked = os.fstat(descriptor)
        if (
            rechecked.st_dev,
            rechecked.st_ino,
            rechecked.st_mode,
            rechecked.st_nlink,
            rechecked.st_size,
        ) != (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink, opened.st_size):
            _fixture_source_invalid()
    except GatewayAuthParityFixtureError:
        raise
    except Exception:
        _fixture_source_invalid()
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                _fixture_source_invalid()
    return hashlib.sha256(content).hexdigest()


def require_current_fixture_source(expected_sha256: str) -> None:
    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or not hmac.compare_digest(current_fixture_source_sha256(), expected_sha256)
    ):
        _fixture_source_invalid()


class GatewayAuthParityFixtureRepository(Protocol):
    async def require_absent(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def prepare(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def enable(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def revoke_allow_membership(self, identity: FixtureIdentity) -> None: ...

    async def cleanup(self, identities: tuple[FixtureIdentity, ...]) -> None: ...

    async def require_zero_residual(self, identities: tuple[FixtureIdentity, ...]) -> None: ...


def _invalid() -> NoReturn:
    raise GatewayAuthParityFixtureError(
        "GATEWAY_AUTH_PARITY_FIXTURE_INPUT_INVALID",
        diagnostic_predicate=FixtureDiagnosticPredicate.FIXED_INPUT_PROTOCOL,
    )


def parse_fixture_request(document: object) -> FixtureRequest:
    if not isinstance(document, dict) or set(document) != _EXACT_REQUEST_KEYS:
        _invalid()
    try:
        contract = document["contract"]
        operation = FixtureOperation(document["operation"])
        allow_external_subject = str(UUID(document["allow_external_subject"]))
        deny_external_subject = str(UUID(document["deny_external_subject"]))
        source_sha256 = document["source_sha256"]
    except (KeyError, TypeError, ValueError):
        _invalid()
    if (
        contract != FIXTURE_CONTRACT
        or allow_external_subject == deny_external_subject
        or len(allow_external_subject) != 36
        or len(deny_external_subject) != 36
        or not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256)
    ):
        _invalid()
    return FixtureRequest(
        contract=contract,
        operation=operation,
        allow_external_subject=allow_external_subject,
        deny_external_subject=deny_external_subject,
        source_sha256=source_sha256,
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
        try:
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
        except GatewayAuthParityFixtureError:
            raise
        except BaseException:
            raise GatewayAuthParityFixtureError(
                "GATEWAY_AUTH_PARITY_FIXTURE_QUERY_FAILED",
                diagnostic_predicate=FixtureDiagnosticPredicate.REPOSITORY_QUERY_DEPENDENCY,
            ) from None
        if subjects or membership_count != 0 or any(privilege_residual_counts):
            raise GatewayAuthParityFixtureError(
                "GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT",
                diagnostic_predicate=FixtureDiagnosticPredicate.REPOSITORY_NOT_ABSENT,
            )

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
    try:
        settings = get_settings()
        if settings.app_env != "development":
            raise GatewayAuthParityFixtureError(
                "GATEWAY_AUTH_PARITY_FIXTURE_ENVIRONMENT_INVALID",
                diagnostic_predicate=FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY,
            )
        resolver = SecretResolver()
        database = Database(
            settings.bootstrap_database_url,
            password=resolver.resolve(settings.bootstrap_database_secret_ref),
            pool_size=1,
            max_overflow=0,
            application_name="datariver-gateway-auth-parity-fixture",
        )
    except GatewayAuthParityFixtureError:
        raise
    except BaseException:
        raise GatewayAuthParityFixtureError(
            "GATEWAY_AUTH_PARITY_FIXTURE_ENVIRONMENT_INVALID",
            diagnostic_predicate=FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY,
        ) from None

    evidence: FixtureEvidence | None = None
    failure: GatewayAuthParityFixtureError | None = None
    try:
        async with database.session_factory() as session, session.begin():
            repository = SqlGatewayAuthParityFixtureRepository(session, issuer=settings.oidc_issuer)
            evidence = await GatewayAuthParityFixtureService(repository).execute(request)
    except GatewayAuthParityFixtureError as error:
        failure = error
    except BaseException:
        failure = GatewayAuthParityFixtureError(
            "GATEWAY_AUTH_PARITY_FIXTURE_ENVIRONMENT_INVALID",
            diagnostic_predicate=FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY,
        )
    try:
        await database.close()
    except BaseException:
        if failure is None:
            failure = GatewayAuthParityFixtureError(
                "GATEWAY_AUTH_PARITY_FIXTURE_ENVIRONMENT_INVALID",
                diagnostic_predicate=FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY,
            )
    if failure is not None:
        raise failure from None
    assert evidence is not None
    return evidence


def main() -> int:
    diagnostic_requested = (
        len(sys.argv) == 2 and sys.argv[1] == FixtureOperation.REQUIRE_ABSENT.value
    )
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {value.value for value in FixtureOperation}:
            _invalid()
        raw = sys.stdin.buffer.read(4_097)
        if not raw or len(raw) > 4_096:
            _invalid()
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            _invalid()
        request = parse_fixture_request(document)
        if request.operation.value != sys.argv[1]:
            _invalid()
        require_current_fixture_source(request.source_sha256)
        evidence = asyncio.run(execute_fixture_request(request))
    except BaseException as error:
        if diagnostic_requested:
            predicate = (
                error.diagnostic_predicate
                if isinstance(error, GatewayAuthParityFixtureError)
                and error.diagnostic_predicate is not None
                else FixtureDiagnosticPredicate.UNKNOWN
            )
            print(
                format_fixture_diagnostic_line(
                    FixtureDiagnosticEnvelope(
                        operation=FixtureDiagnosticOperation.REQUIRE_ABSENT,
                        predicate=predicate,
                    )
                ),
                file=sys.stderr,
            )
            return 2
        print("GATEWAY_AUTH_PARITY_FIXTURE_FAILED", file=sys.stderr)
        return 2
    if request.operation is FixtureOperation.REQUIRE_ABSENT:
        print(
            format_fixture_diagnostic_line(
                FixtureDiagnosticEnvelope(
                    operation=FixtureDiagnosticOperation.REQUIRE_ABSENT,
                    predicate=FixtureDiagnosticPredicate.PASS,
                )
            )
        )
        return 0
    print(json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
