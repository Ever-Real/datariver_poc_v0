from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from datariver import gateway_auth_parity_fixture as fixture
from datariver.domain.authz import Classification
from datariver.domain.common import utc_now
from datariver.infrastructure.db.models.platform import (
    SubjectModel,
    WorkspaceMembershipModel,
)


class RecordingRepository:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.absent = True
        self.prepared = False
        self.enabled = False
        self.revoked = False

    async def require_absent(self, identities: tuple[fixture.FixtureIdentity, ...]) -> None:
        self.events.append(("require-absent", identities))
        if not self.absent:
            raise fixture.GatewayAuthParityFixtureError("FIXTURE_NOT_ABSENT")

    async def prepare(self, identities: tuple[fixture.FixtureIdentity, ...]) -> None:
        self.events.append(("prepare", identities))
        self.absent = False
        self.prepared = True

    async def enable(self, identities: tuple[fixture.FixtureIdentity, ...]) -> None:
        self.events.append(("enable", identities))
        self.enabled = True

    async def revoke_allow_membership(
        self,
        identity: fixture.FixtureIdentity,
    ) -> None:
        self.events.append(("revoke", identity))
        self.revoked = True

    async def cleanup(self, identities: tuple[fixture.FixtureIdentity, ...]) -> None:
        self.events.append(("cleanup", identities))
        self.absent = True
        self.prepared = False
        self.enabled = False
        self.revoked = False

    async def require_zero_residual(
        self,
        identities: tuple[fixture.FixtureIdentity, ...],
    ) -> None:
        self.events.append(("require-zero-residual", identities))
        if not self.absent:
            raise fixture.GatewayAuthParityFixtureError("FIXTURE_RESIDUAL")


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class RecordingSqlSession:
    def __init__(
        self,
        *,
        subjects: dict[object, object],
        memberships: dict[object, object],
        privilege_rows: list[list[object]] | None = None,
        simulate_concurrent_membership: bool = False,
    ) -> None:
        self.subjects = subjects
        self.memberships = memberships
        self.privilege_rows = list(privilege_rows or ([], [], []))
        self.subject_query_pending = True
        self.locked_gets: list[bool] = []
        self.execute_calls: list[object] = []
        self.events: list[str] = []
        self.simulate_concurrent_membership = simulate_concurrent_membership
        self.concurrent_membership_retained = False

    async def get(
        self,
        model: object,
        key: object,
        *,
        with_for_update: bool = False,
    ) -> object | None:
        self.locked_gets.append(with_for_update)
        if model is SubjectModel:
            self.events.append("lock-subject")
            return self.subjects.get(key)
        if model is WorkspaceMembershipModel:
            assert isinstance(key, dict)
            self.events.append("lock-local-membership")
            return self.memberships.get(key["subject_id"])
        return None

    async def scalars(self, _statement: object) -> _ScalarRows:
        if self.subject_query_pending:
            self.subject_query_pending = False
            self.events.append("read-exact-alias-set")
            return _ScalarRows(list(self.subjects.values()))
        assert self.privilege_rows
        self.events.append("read-privilege-residual")
        return _ScalarRows(self.privilege_rows.pop(0))

    async def scalar(self, _statement: object) -> int:
        self.events.append("read-all-workspace-memberships")
        if self.simulate_concurrent_membership:
            assert self.locked_gets == [True, True, True, True]
            self.concurrent_membership_retained = True
            return len(self.memberships) + 1
        return len(self.memberships)

    async def execute(self, statement: object) -> None:
        self.events.append(
            "delete-local-memberships" if not self.execute_calls else "delete-exact-subjects"
        )
        self.execute_calls.append(statement)

    async def flush(self) -> None:
        return None


class ResidualSqlSession:
    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = rows

    async def scalars(self, _statement: object) -> _ScalarRows:
        assert self._rows
        return _ScalarRows(self._rows.pop(0))


def _sql_rows(
    identities: tuple[fixture.FixtureIdentity, ...],
) -> tuple[dict[object, object], dict[object, object]]:
    subjects: dict[object, object] = {}
    memberships: dict[object, object] = {}
    for identity in identities:
        subjects[identity.subject_id] = SubjectModel(
            id=identity.subject_id,
            issuer="http://keycloak:8080/realms/datariver",
            external_subject=identity.external_subject,
            display_name=identity.display_name,
            email=None,
            active=True,
        )
        memberships[identity.subject_id] = WorkspaceMembershipModel(
            workspace_id=fixture.LOCAL_WORKSPACE_ID,
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
                "bootstrap": fixture.FIXTURE_CONTRACT,
            },
            active=True,
            access_expires_at=utc_now() + timedelta(minutes=30),
            version=2,
        )
    return subjects, memberships


def _request(operation: fixture.FixtureOperation) -> fixture.FixtureRequest:
    return fixture.FixtureRequest(
        contract=fixture.FIXTURE_CONTRACT,
        operation=operation,
        allow_external_subject="10000000-0000-4000-8000-000000000001",
        deny_external_subject="10000000-0000-4000-8000-000000000002",
        source_sha256=fixture.current_fixture_source_sha256(),
    )


def test_fixture_contract_is_exact_human_least_scope_and_not_a_service_identity() -> None:
    allow, deny = fixture.fixture_identities(_request(fixture.FixtureOperation.PREPARE))

    assert allow.kind is fixture.FixtureIdentityKind.ALLOW
    assert allow.allowed_actions == ("change.read", "kg.read")
    assert allow.denied_actions == ()
    assert deny.kind is fixture.FixtureIdentityKind.DENY
    assert deny.allowed_actions == ()
    assert deny.denied_actions == ("change.read", "kg.read")
    assert allow.job_function == deny.job_function == "GATEWAY_AUTH_PARITY_PROBE"
    assert "service-accounts" not in allow.groups
    assert "admin.manage" not in (*allow.allowed_actions, *deny.allowed_actions)
    assert allow.subject_id != deny.subject_id


def test_require_absent_diagnostic_envelope_is_closed_bounded_and_value_free() -> None:
    assert tuple(fixture.FixtureDiagnosticOperation) == (
        fixture.FixtureDiagnosticOperation.REQUIRE_ABSENT,
    )
    assert tuple(fixture.FixtureDiagnosticPredicate) == (
        fixture.FixtureDiagnosticPredicate.PASS,
        fixture.FixtureDiagnosticPredicate.FIXED_INPUT_PROTOCOL,
        fixture.FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY,
        fixture.FixtureDiagnosticPredicate.REPOSITORY_NOT_ABSENT,
        fixture.FixtureDiagnosticPredicate.REPOSITORY_QUERY_DEPENDENCY,
        fixture.FixtureDiagnosticPredicate.IMAGE_PROVENANCE,
        fixture.FixtureDiagnosticPredicate.PROCESS_SPAWN,
        fixture.FixtureDiagnosticPredicate.PROCESS_TIMEOUT,
        fixture.FixtureDiagnosticPredicate.PROCESS_NONZERO,
        fixture.FixtureDiagnosticPredicate.OUTPUT_SIZE,
        fixture.FixtureDiagnosticPredicate.OUTPUT_LINE,
        fixture.FixtureDiagnosticPredicate.OUTPUT_JSON,
        fixture.FixtureDiagnosticPredicate.OUTPUT_SHAPE,
        fixture.FixtureDiagnosticPredicate.OUTPUT_TUPLE,
        fixture.FixtureDiagnosticPredicate.UNKNOWN,
    )
    for predicate in fixture.FixtureDiagnosticPredicate:
        evidence = fixture.FixtureDiagnosticEnvelope(
            operation=fixture.FixtureDiagnosticOperation.REQUIRE_ABSENT,
            predicate=predicate,
        )
        line = fixture.format_fixture_diagnostic_line(evidence)
        assert fixture.parse_fixture_diagnostic_line(line) == evidence
        assert len(line.encode("utf-8")) <= fixture.MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES
        for forbidden in ("provider-secret-sentinel", "sql", "count", "identifier"):
            assert forbidden not in line.casefold()


@pytest.mark.parametrize(
    ("raw", "predicate"),
    (
        ("", "OUTPUT_LINE"),
        ("{}\n{}", "OUTPUT_LINE"),
        ("not-json", "OUTPUT_JSON"),
        ("[]", "OUTPUT_SHAPE"),
        ('{"operation":"REQUIRE_ABSENT"}', "OUTPUT_SHAPE"),
        (
            '{"operation":"REQUIRE_ABSENT","predicate":"NOT_REVIEWED"}',
            "OUTPUT_TUPLE",
        ),
        (
            '{"operation":"REQUIRE_ABSENT","predicate":null}',
            "OUTPUT_TUPLE",
        ),
        (
            '{"operation":"PREPARE","predicate":"PASS"}',
            "OUTPUT_TUPLE",
        ),
        (
            '{"operation":"REQUIRE_ABSENT","operation":"REQUIRE_ABSENT","predicate":"PASS"}',
            "OUTPUT_TUPLE",
        ),
    ),
)
def test_require_absent_diagnostic_parser_classifies_protocol_defects_without_raw(
    raw: str,
    predicate: str,
) -> None:
    with pytest.raises(fixture.FixtureDiagnosticProtocolError) as captured:
        fixture.parse_fixture_diagnostic_line(raw)

    assert captured.value.predicate.value == predicate
    if raw:
        assert raw not in str(captured.value)


def test_require_absent_diagnostic_parser_rejects_oversized_output_before_json() -> None:
    raw = "provider-secret-sentinel" * fixture.MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES

    with pytest.raises(fixture.FixtureDiagnosticProtocolError) as captured:
        fixture.parse_fixture_diagnostic_line(raw)

    assert captured.value.predicate is fixture.FixtureDiagnosticPredicate.OUTPUT_SIZE
    assert "provider" not in str(captured.value)


@pytest.mark.parametrize("failure", ("missing", "symlink", "hardlink"))
def test_fixture_source_provenance_rejects_missing_or_ambiguous_identity_before_query(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "fixture.py"
    original.write_bytes(b"current-fixture-source")
    selected = original
    if failure == "missing":
        selected = tmp_path / "missing.py"
    elif failure == "symlink":
        selected = tmp_path / "symlink.py"
        selected.symlink_to(original)
    else:
        selected = tmp_path / "hardlink.py"
        os.link(original, selected)
    monkeypatch.setattr(fixture, "__file__", os.fspath(selected))

    with pytest.raises(fixture.GatewayAuthParityFixtureError) as captured:
        fixture.current_fixture_source_sha256()

    assert captured.value.diagnostic_predicate is (
        fixture.FixtureDiagnosticPredicate.IMAGE_PROVENANCE
    )


def test_fixture_source_provenance_matches_exact_current_bytes_and_rejects_stale_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "fixture.py"
    selected.write_bytes(b"current-fixture-source")
    monkeypatch.setattr(fixture, "__file__", os.fspath(selected))
    digest = fixture.current_fixture_source_sha256()

    fixture.require_current_fixture_source(digest)
    with pytest.raises(fixture.GatewayAuthParityFixtureError) as captured:
        fixture.require_current_fixture_source("0" * 64)

    assert captured.value.diagnostic_predicate is (
        fixture.FixtureDiagnosticPredicate.IMAGE_PROVENANCE
    )


def test_stale_fixture_source_provenance_stops_before_repository_query(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _request(fixture.FixtureOperation.REQUIRE_ABSENT)
    raw = json.dumps(
        {
            "contract": request.contract,
            "operation": request.operation.value,
            "allow_external_subject": request.allow_external_subject,
            "deny_external_subject": request.deny_external_subject,
            "source_sha256": "0" * 64,
        }
    ).encode()
    queries: list[str] = []

    async def query(_request: fixture.FixtureRequest) -> fixture.FixtureEvidence:
        queries.append("query")
        return fixture.FixtureEvidence("absent", 0, 0, 0)

    monkeypatch.setattr(fixture, "execute_fixture_request", query)
    monkeypatch.setattr(sys, "argv", ["fixture", "require-absent"])
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": io.BytesIO(raw)})())

    assert fixture.main() == 2

    output = capsys.readouterr()
    evidence = fixture.parse_fixture_diagnostic_line(output.err.rstrip("\n"))
    assert evidence.predicate is fixture.FixtureDiagnosticPredicate.IMAGE_PROVENANCE
    assert output.out == ""
    assert queries == []


@pytest.mark.asyncio
async def test_fixture_operations_are_fixed_and_membership_revocation_advances_version() -> None:
    repository = RecordingRepository()
    service = fixture.GatewayAuthParityFixtureService(repository)

    prepare = await service.execute(_request(fixture.FixtureOperation.PREPARE))
    enable = await service.execute(_request(fixture.FixtureOperation.ENABLE))
    revoke = await service.execute(_request(fixture.FixtureOperation.REVOKE_ALLOW_MEMBERSHIP))
    cleanup = await service.execute(_request(fixture.FixtureOperation.CLEANUP))

    assert [event[0] for event in repository.events] == [
        "require-absent",
        "prepare",
        "enable",
        "revoke",
        "cleanup",
        "require-zero-residual",
    ]
    assert prepare == fixture.FixtureEvidence("prepared", 2, 2, 0)
    assert enable == fixture.FixtureEvidence("enabled", 2, 2, 0)
    assert revoke == fixture.FixtureEvidence("membership-revoked", 2, 2, 0)
    assert cleanup == fixture.FixtureEvidence("clean", 0, 0, 0)


@pytest.mark.asyncio
async def test_fixture_absence_and_cleanup_are_the_only_idempotent_boundaries() -> None:
    repository = RecordingRepository()
    service = fixture.GatewayAuthParityFixtureService(repository)

    assert await service.execute(_request(fixture.FixtureOperation.REQUIRE_ABSENT)) == (
        fixture.FixtureEvidence("absent", 0, 0, 0)
    )
    assert await service.execute(_request(fixture.FixtureOperation.CLEANUP)) == (
        fixture.FixtureEvidence("clean", 0, 0, 0)
    )
    assert [event[0] for event in repository.events] == [
        "require-absent",
        "cleanup",
        "require-zero-residual",
    ]


@pytest.mark.parametrize(
    "document",
    (
        {},
        {
            "contract": fixture.FIXTURE_CONTRACT,
            "operation": "prepare",
            "allow_external_subject": "not-a-uuid",
            "deny_external_subject": "10000000-0000-4000-8000-000000000002",
        },
        {
            "contract": fixture.FIXTURE_CONTRACT,
            "operation": "prepare",
            "allow_external_subject": "10000000-0000-4000-8000-000000000001",
            "deny_external_subject": "10000000-0000-4000-8000-000000000001",
        },
        {
            "contract": fixture.FIXTURE_CONTRACT,
            "operation": "prepare",
            "allow_external_subject": "10000000-0000-4000-8000-000000000001",
            "deny_external_subject": "10000000-0000-4000-8000-000000000002",
            "sql": "secret-sentinel",
        },
    ),
)
def test_fixture_request_rejects_missing_extra_colliding_or_provider_passthrough(
    document: object,
) -> None:
    with pytest.raises(
        fixture.GatewayAuthParityFixtureError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_INPUT_INVALID",
    ):
        fixture.parse_fixture_request(document)


def test_fixture_request_never_retains_raw_provider_or_secret_values() -> None:
    request = _request(fixture.FixtureOperation.PREPARE)
    parsed = fixture.parse_fixture_request(
        {
            "contract": request.contract,
            "operation": request.operation.value,
            "allow_external_subject": request.allow_external_subject,
            "deny_external_subject": request.deny_external_subject,
            "source_sha256": request.source_sha256,
        }
    )

    assert parsed == request
    with pytest.raises(fixture.GatewayAuthParityFixtureError) as captured:
        fixture.fixture_identities(
            replace(parsed, deny_external_subject=parsed.allow_external_subject)
        )
    assert "10000000" not in str(captured.value)
    assert "secret" not in str(captured.value).casefold()
    assert parsed.operation.value in {value.value for value in fixture.FixtureOperation}


@pytest.mark.asyncio
async def test_sql_cleanup_rejects_swapped_external_subjects_before_any_delete() -> None:
    identities = fixture.fixture_identities(_request(fixture.FixtureOperation.CLEANUP))
    subjects, memberships = _sql_rows(identities)
    cast_allow = subjects[identities[0].subject_id]
    cast_deny = subjects[identities[1].subject_id]
    cast(Any, cast_allow).external_subject = identities[1].external_subject
    cast(Any, cast_deny).external_subject = identities[0].external_subject
    session = RecordingSqlSession(subjects=subjects, memberships=memberships)
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    with pytest.raises(
        fixture.GatewayAuthParityFixtureError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED",
    ):
        await repository.cleanup(identities)

    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_sql_membership_revocation_advances_only_the_allow_version() -> None:
    identities = fixture.fixture_identities(
        _request(fixture.FixtureOperation.REVOKE_ALLOW_MEMBERSHIP)
    )
    subjects, memberships = _sql_rows(identities)
    session = RecordingSqlSession(subjects=subjects, memberships=memberships)
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    await repository.revoke_allow_membership(identities[0])

    allow = cast(Any, memberships[identities[0].subject_id])
    deny = cast(Any, memberships[identities[1].subject_id])
    assert (allow.active, allow.version) == (False, 3)
    assert (deny.active, deny.version) == (True, 2)
    assert session.locked_gets == [True, True]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    (
        "issuer",
        "display",
        "email",
        "job",
        "clearance",
        "groups",
        "allowed-actions",
        "denied-actions",
        "bootstrap",
        "expired",
        "lifecycle",
        "version",
    ),
)
async def test_sql_cleanup_rejects_membership_envelope_drift_before_any_delete(
    drift: str,
) -> None:
    identities = fixture.fixture_identities(_request(fixture.FixtureOperation.CLEANUP))
    subjects, memberships = _sql_rows(identities)
    subject = cast(Any, subjects[identities[0].subject_id])
    membership = cast(Any, memberships[identities[0].subject_id])
    if drift == "issuer":
        subject.issuer = "http://unreviewed.invalid/realms/datariver"
    elif drift == "display":
        subject.display_name = "Not the fixture"
    elif drift == "email":
        subject.email = "unexpected@localhost.invalid"
    elif drift == "job":
        membership.job_function = "ADMIN"
    elif drift == "clearance":
        membership.clearance = int(Classification.CONFIDENTIAL)
    elif drift == "groups":
        membership.attributes["groups"] = ["administrators"]
    elif drift == "allowed-actions":
        membership.attributes["allowed_actions"] = ["admin.manage"]
    elif drift == "denied-actions":
        membership.attributes["denied_actions"] = ["kg.read"]
    elif drift == "bootstrap":
        membership.attributes["bootstrap"] = "unreviewed-fixture"
    elif drift == "expired":
        membership.access_expires_at = utc_now() - timedelta(seconds=1)
    elif drift == "lifecycle":
        subject.active = False
        membership.active = True
    elif drift == "version":
        membership.version = 999
    session = RecordingSqlSession(subjects=subjects, memberships=memberships)
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    with pytest.raises(
        fixture.GatewayAuthParityFixtureError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED",
    ):
        await repository.cleanup(identities)

    assert session.execute_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("privilege_index", (0, 1, 2))
async def test_sql_cleanup_rejects_any_privilege_assignment_before_any_delete(
    privilege_index: int,
) -> None:
    identities = fixture.fixture_identities(_request(fixture.FixtureOperation.CLEANUP))
    subjects, memberships = _sql_rows(identities)
    privilege_rows: list[list[object]] = [[], [], []]
    privilege_rows[privilege_index] = [identities[0].subject_id]
    session = RecordingSqlSession(
        subjects=subjects,
        memberships=memberships,
        privilege_rows=privilege_rows,
    )
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    with pytest.raises(
        fixture.GatewayAuthParityFixtureError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED",
    ):
        await repository.cleanup(identities)

    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_sql_absence_rejects_orphaned_privilege_residual_before_prepare() -> None:
    identities = fixture.fixture_identities(_request(fixture.FixtureOperation.REQUIRE_ABSENT))
    session = RecordingSqlSession(
        subjects={},
        memberships={},
        privilege_rows=[[identities[0].subject_id], [], []],
    )
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    with pytest.raises(
        fixture.GatewayAuthParityFixtureError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT",
    ) as captured:
        await repository.require_absent(identities)

    assert (
        captured.value.diagnostic_predicate
        is fixture.FixtureDiagnosticPredicate.REPOSITORY_NOT_ABSENT
    )
    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_sql_absence_query_failure_is_fixed_select_only_and_nonleaking() -> None:
    identities = fixture.fixture_identities(_request(fixture.FixtureOperation.REQUIRE_ABSENT))
    session = RecordingSqlSession(subjects={}, memberships={})

    async def fail_query(_statement: object) -> _ScalarRows:
        raise RuntimeError("sql-provider-secret-sentinel")

    cast(Any, session).scalars = fail_query
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    with pytest.raises(fixture.GatewayAuthParityFixtureError) as captured:
        await repository.require_absent(identities)

    assert captured.value.diagnostic_predicate is (
        fixture.FixtureDiagnosticPredicate.REPOSITORY_QUERY_DEPENDENCY
    )
    assert "sql-provider" not in str(captured.value)
    assert session.execute_calls == []


def test_require_absent_child_emits_one_fixed_line_and_never_raw_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _request(fixture.FixtureOperation.REQUIRE_ABSENT)
    raw = json.dumps(
        {
            "contract": request.contract,
            "operation": request.operation.value,
            "allow_external_subject": request.allow_external_subject,
            "deny_external_subject": request.deny_external_subject,
            "source_sha256": request.source_sha256,
        }
    ).encode()

    async def fail(_request: fixture.FixtureRequest) -> fixture.FixtureEvidence:
        raise fixture.GatewayAuthParityFixtureError(
            "raw-provider-secret-sentinel",
            diagnostic_predicate=fixture.FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY,
        )

    monkeypatch.setattr(fixture, "execute_fixture_request", fail)
    monkeypatch.setattr(sys, "argv", ["fixture", "require-absent"])
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": io.BytesIO(raw)})())

    assert fixture.main() == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.count("\n") == 1
    evidence = fixture.parse_fixture_diagnostic_line(output.err.rstrip("\n"))
    assert evidence.predicate is fixture.FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY
    assert "provider" not in output.err


def test_require_absent_child_success_emits_only_the_pass_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = _request(fixture.FixtureOperation.REQUIRE_ABSENT)
    raw = json.dumps(
        {
            "contract": request.contract,
            "operation": request.operation.value,
            "allow_external_subject": request.allow_external_subject,
            "deny_external_subject": request.deny_external_subject,
            "source_sha256": request.source_sha256,
        }
    ).encode()

    async def succeed(_request: fixture.FixtureRequest) -> fixture.FixtureEvidence:
        return fixture.FixtureEvidence("absent", 0, 0, 0)

    monkeypatch.setattr(fixture, "execute_fixture_request", succeed)
    monkeypatch.setattr(sys, "argv", ["fixture", "require-absent"])
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": io.BytesIO(raw)})())

    assert fixture.main() == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.count("\n") == 1
    evidence = fixture.parse_fixture_diagnostic_line(output.out.rstrip("\n"))
    assert evidence == fixture.FixtureDiagnosticEnvelope(
        fixture.FixtureDiagnosticOperation.REQUIRE_ABSENT,
        fixture.FixtureDiagnosticPredicate.PASS,
    )


def test_require_absent_child_rejects_invalid_private_request_as_fixed_input_protocol(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["fixture", "require-absent"])
    monkeypatch.setattr(
        sys,
        "stdin",
        type("Input", (), {"buffer": io.BytesIO(b"provider-secret-sentinel")})(),
    )

    assert fixture.main() == 2

    output = capsys.readouterr()
    assert output.out == ""
    evidence = fixture.parse_fixture_diagnostic_line(output.err.rstrip("\n"))
    assert evidence.predicate is fixture.FixtureDiagnosticPredicate.FIXED_INPUT_PROTOCOL
    assert "provider" not in output.err


@pytest.mark.asyncio
async def test_sql_cleanup_deletes_only_exact_rows_after_zero_privilege_proof() -> None:
    identities = fixture.fixture_identities(_request(fixture.FixtureOperation.CLEANUP))
    subjects, memberships = _sql_rows(identities)
    session = RecordingSqlSession(subjects=subjects, memberships=memberships)
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    await repository.cleanup(identities)

    assert len(session.execute_calls) == 2
    assert session.locked_gets == [True, True, True, True]
    assert session.events == [
        "lock-subject",
        "lock-local-membership",
        "lock-subject",
        "lock-local-membership",
        "read-exact-alias-set",
        "read-all-workspace-memberships",
        "read-privilege-residual",
        "read-privilege-residual",
        "read-privilege-residual",
        "delete-local-memberships",
        "delete-exact-subjects",
    ]


@pytest.mark.asyncio
async def test_sql_cleanup_rechecks_concurrent_cross_workspace_membership_under_subject_locks() -> (
    None
):
    identities = fixture.fixture_identities(_request(fixture.FixtureOperation.CLEANUP))
    subjects, memberships = _sql_rows(identities)
    session = RecordingSqlSession(
        subjects=subjects,
        memberships=memberships,
        simulate_concurrent_membership=True,
    )
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    with pytest.raises(
        fixture.GatewayAuthParityFixtureError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_CLEANUP_REQUIRED",
    ):
        await repository.cleanup(identities)

    assert session.concurrent_membership_retained is True
    assert session.execute_calls == []
    assert session.events[:4] == [
        "lock-subject",
        "lock-local-membership",
        "lock-subject",
        "lock-local-membership",
    ]
    assert session.events[4:] == [
        "read-exact-alias-set",
        "read-all-workspace-memberships",
        "read-privilege-residual",
        "read-privilege-residual",
        "read-privilege-residual",
    ]


@pytest.mark.asyncio
async def test_zero_residual_rejects_external_subject_alias_under_another_id() -> None:
    identities = fixture.fixture_identities(
        _request(fixture.FixtureOperation.REQUIRE_ZERO_RESIDUAL)
    )
    alias_id = UUID("10000000-0000-4000-8000-000000000099")
    session = ResidualSqlSession([[alias_id], [], [], [], []])
    repository = fixture.SqlGatewayAuthParityFixtureRepository(
        cast(Any, session),
        issuer="http://keycloak:8080/realms/datariver",
    )

    with pytest.raises(
        fixture.GatewayAuthParityFixtureError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_RESIDUAL",
    ):
        await repository.require_zero_residual(identities)
