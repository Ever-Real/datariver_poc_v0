from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.inference_provider import (
    InferenceProviderProfile,
    InferenceProviderProfileState,
    InferenceProviderProfileVersion,
    ProviderAttestation,
    ProviderKind,
)
from datariver.infrastructure.db.inference import (
    SqlInferenceProviderProfileRepository,
    _profile_model,
    _required_profile,
)

NOW = datetime(2035, 1, 1, 12, tzinfo=UTC)


class _ScalarRows:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values

    def one_or_none(self) -> object | None:
        if len(self._values) > 1:
            raise AssertionError("Expected at most one row.")
        return self._values[0] if self._values else None

    def all(self) -> tuple[object, ...]:
        return self._values


class _ExecuteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Session:
    def __init__(
        self,
        *,
        scalar_rows: tuple[object, ...] = (),
        scalar_value: object | None = None,
        rowcount: int = 1,
    ) -> None:
        self.scalar_rows = scalar_rows
        self.scalar_value = scalar_value
        self.rowcount = rowcount
        self.added: list[object] = []
        self.scalar_statements: list[object] = []
        self.scalars_statements: list[object] = []
        self.executions: list[tuple[object, object | None]] = []
        self.calls: list[str] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def scalar(self, statement: object) -> object | None:
        self.calls.append("scalar")
        self.scalar_statements.append(statement)
        return self.scalar_value

    async def scalars(self, statement: object) -> _ScalarRows:
        self.calls.append("scalars")
        self.scalars_statements.append(statement)
        return _ScalarRows(self.scalar_rows)

    async def execute(self, statement: object, parameters: object | None = None) -> _ExecuteResult:
        self.calls.append("execute")
        self.executions.append((statement, parameters))
        return _ExecuteResult(self.rowcount)


def _attestation(marker: str) -> ProviderAttestation:
    return ProviderAttestation(
        fingerprint=marker * 64,
        observed_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )


def _proposal() -> InferenceProviderProfileVersion:
    return InferenceProviderProfileVersion.propose(
        workspace_id=uuid4(),
        profile_version=1,
        profile=InferenceProviderProfile(
            profile_key="profile-a",
            server_route_key="route-a",
            kind=ProviderKind.INTERNAL,
            provider_identity="provider-a",
            model_identity="model-a",
            deployment_identity="deployment-a",
            jurisdiction="JURISDICTION-A",
            region="region-a",
            maximum_classification=Classification.CONFIDENTIAL,
            residency_attestation=_attestation("a"),
            zero_retention_attestation=_attestation("b"),
        ),
        maker_id=uuid4(),
        reason="Governed provider registration",
        policy_decision_id=uuid4(),
        now=NOW,
    )


def _approve(profile: InferenceProviderProfileVersion) -> None:
    profile.approve(
        checker_id=uuid4(),
        reason="Independent approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=NOW,
    )


def test_model_round_trip_maps_every_immutable_runtime_field() -> None:
    proposal = _proposal()
    model = _profile_model(proposal)

    hydrated = _required_profile(model)

    assert hydrated.profile == proposal.profile
    assert hydrated.profile_version == proposal.profile_version
    assert hydrated.payload_hash == proposal.payload_hash
    assert hydrated.maker_id == proposal.maker_id
    assert hydrated.state is InferenceProviderProfileState.PROPOSED
    assert not ({"url", "endpoint", "credential", "secret", "api_key"} & set(vars(model)))


def test_hydration_fails_closed_for_payload_tamper_or_invalid_state_shape() -> None:
    model = _profile_model(_proposal())
    model.region = "region-b"
    with pytest.raises(ConflictError, match="integrity"):
        _required_profile(model)

    model = _profile_model(_proposal())
    model.state = InferenceProviderProfileState.APPROVED.value
    with pytest.raises(ConflictError, match="approval state"):
        _required_profile(model)


@pytest.mark.asyncio
async def test_get_and_list_are_workspace_scoped_and_hydrate_domain_aggregates() -> None:
    proposal = _proposal()
    model = _profile_model(proposal)
    get_session = _Session(scalar_rows=(model,))
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, get_session))

    value = await repository.get(
        workspace_id=proposal.workspace_id,
        profile_version_id=proposal.provider_profile_version_id,
    )

    assert value is not None and value.payload_hash == proposal.payload_hash
    get_sql = str(cast(ClauseElement, get_session.scalars_statements[0]).compile())
    assert "workspace_id" in get_sql and "inference_provider_profile_versions.id" in get_sql

    list_session = _Session(scalar_rows=(model,))
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, list_session))
    page = await repository.list(
        workspace_id=proposal.workspace_id,
        profile_key=proposal.profile.profile_key,
        state=InferenceProviderProfileState.PROPOSED,
        limit=20,
    )
    assert len(page.items) == 1
    assert page.items[0].payload_hash == proposal.payload_hash
    assert page.next_cursor is None
    list_statement = cast(ClauseElement, list_session.scalars_statements[0])
    parameter_values = set(list_statement.compile().params.values())
    assert proposal.workspace_id in parameter_values
    assert proposal.profile.profile_key in parameter_values
    assert InferenceProviderProfileState.PROPOSED.value in parameter_values


@pytest.mark.asyncio
async def test_list_uses_limit_plus_one_and_filter_bound_composite_cursor() -> None:
    proposal = _proposal()
    model = _profile_model(proposal)
    first_session = _Session(scalar_rows=(model, model))
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, first_session))

    page = await repository.list(
        workspace_id=proposal.workspace_id,
        profile_key=None,
        state=None,
        limit=1,
    )

    assert len(page.items) == 1
    assert page.next_cursor is not None
    first_statement = cast(ClauseElement, first_session.scalars_statements[0])
    assert first_statement.compile().params["param_1"] == 2

    next_session = _Session()
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, next_session))
    empty = await repository.list(
        workspace_id=proposal.workspace_id,
        profile_key=None,
        state=None,
        limit=1,
        cursor=page.next_cursor,
    )
    assert empty.items == ()
    sql = str(cast(ClauseElement, next_session.scalars_statements[0]).compile())
    assert "profile_key >" in sql
    assert "profile_version <" in sql
    assert "id >" in sql

    with pytest.raises(ValidationError, match="stale"):
        await repository.list(
            workspace_id=uuid4(),
            profile_key=None,
            state=None,
            limit=1,
            cursor=page.next_cursor,
        )
    with pytest.raises(ValidationError, match="stale"):
        await repository.list(
            workspace_id=proposal.workspace_id,
            profile_key=proposal.profile.profile_key,
            state=None,
            limit=1,
            cursor=page.next_cursor,
        )


@pytest.mark.asyncio
async def test_list_rejects_pages_larger_than_one_hundred() -> None:
    proposal = _proposal()
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, _Session()))
    with pytest.raises(ValidationError, match="limit"):
        await repository.list(
            workspace_id=proposal.workspace_id,
            limit=101,
        )


@pytest.mark.asyncio
async def test_next_version_takes_workspace_advisory_lock_before_maximum() -> None:
    workspace_id = uuid4()
    session = _Session(scalar_value=4)
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, session))

    value = await repository.next_profile_version(
        workspace_id=workspace_id, profile_key="profile-a"
    )

    assert value == 5
    assert session.calls == ["execute", "scalar"]
    lock_statement, lock_parameters = session.executions[0]
    assert "pg_advisory_xact_lock" in str(lock_statement)
    assert lock_parameters == {
        "lock_key": f"datariver:integration:inference-provider:{workspace_id}"
    }
    maximum = cast(ClauseElement, session.scalar_statements[0]).compile()
    assert workspace_id in maximum.params.values()
    assert "profile-a" in maximum.params.values()


@pytest.mark.asyncio
async def test_add_accepts_only_an_intact_pristine_proposal_without_committing() -> None:
    proposal = _proposal()
    session = _Session()
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, session))

    await repository.add(proposal)

    assert len(session.added) == 1
    _approve(proposal)
    with pytest.raises(ValidationError, match="pristine"):
        await repository.add(proposal)


@pytest.mark.asyncio
async def test_approval_update_is_optimistic_and_never_updates_payload_fields() -> None:
    proposal = _proposal()
    _approve(proposal)
    session = _Session()
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, session))

    await repository.approve(proposal)

    statement = cast(ClauseElement, session.executions[0][0])
    sql = str(statement.compile())
    set_clause = sql.split(" SET ", maxsplit=1)[1].split(" WHERE ", maxsplit=1)[0]
    for immutable_column in (
        "profile_key",
        "profile_version",
        "server_route_key",
        "provider_identity",
        "model_identity",
        "deployment_identity",
        "jurisdiction",
        "region",
        "maximum_classification",
        "attestation_fingerprint",
        "payload_hash",
        "maker_id",
    ):
        assert immutable_column not in set_clause
    parameters = set(statement.compile().params.values())
    assert InferenceProviderProfileState.PROPOSED.value in parameters
    assert InferenceProviderProfileState.APPROVED.value in parameters
    assert 1 in parameters and 2 in parameters


@pytest.mark.asyncio
async def test_rejection_and_revocation_use_explicit_optimistic_transitions() -> None:
    rejected = _proposal()
    rejected.reject(
        checker_id=uuid4(),
        reason="Rejected evidence",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=NOW,
    )
    reject_session = _Session()
    await SqlInferenceProviderProfileRepository(cast(AsyncSession, reject_session)).reject(rejected)
    reject_parameters = set(
        cast(ClauseElement, reject_session.executions[0][0]).compile().params.values()
    )
    assert InferenceProviderProfileState.REJECTED.value in reject_parameters

    revoked = _proposal()
    _approve(revoked)
    revoked.revoke(
        actor_id=revoked.maker_id,
        reason="Assurance withdrawn",
        policy_decision_id=uuid4(),
        expected_version=2,
        now=NOW + timedelta(minutes=1),
    )
    revoke_session = _Session()
    await SqlInferenceProviderProfileRepository(cast(AsyncSession, revoke_session)).revoke(revoked)
    revoke_statement = cast(ClauseElement, revoke_session.executions[0][0])
    revoke_sql = str(revoke_statement.compile())
    assert "revoked_by" in revoke_sql
    revoke_parameters = set(revoke_statement.compile().params.values())
    assert InferenceProviderProfileState.APPROVED.value in revoke_parameters
    assert InferenceProviderProfileState.REVOKED.value in revoke_parameters
    assert 2 in revoke_parameters and 3 in revoke_parameters


@pytest.mark.asyncio
async def test_optimistic_conflict_is_reported_without_commit() -> None:
    proposal = _proposal()
    _approve(proposal)
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, _Session(rowcount=0)))

    with pytest.raises(ConflictError, match="decision conflicted"):
        await repository.approve(proposal)


@pytest.mark.asyncio
async def test_exact_approved_resolver_requires_current_attestations_in_sql_and_domain() -> None:
    approved = _proposal()
    _approve(approved)
    model = _profile_model(approved)
    session = _Session(scalar_rows=(model,))
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, session))

    value = await repository.get_approved_exact(
        workspace_id=approved.workspace_id,
        profile_version_id=approved.provider_profile_version_id,
        now=NOW,
    )

    assert value is not None and value.state is InferenceProviderProfileState.APPROVED
    statement = cast(ClauseElement, session.scalars_statements[0])
    sql = str(statement.compile())
    assert "residency_attestation_observed_at" in sql
    assert "residency_attestation_expires_at" in sql
    assert "zero_retention_attestation_observed_at" in sql
    assert "zero_retention_attestation_expires_at" in sql
    assert InferenceProviderProfileState.APPROVED.value in statement.compile().params.values()

    expired_session = _Session(scalar_rows=(model,))
    expired_repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, expired_session))
    assert (
        await expired_repository.get_approved_exact(
            workspace_id=approved.workspace_id,
            profile_version_id=approved.provider_profile_version_id,
            now=NOW + timedelta(days=1),
        )
        is None
    )


@pytest.mark.asyncio
async def test_exact_resolver_rejects_naive_time_before_query() -> None:
    session = _Session()
    repository = SqlInferenceProviderProfileRepository(cast(AsyncSession, session))

    with pytest.raises(ValidationError, match="timezone"):
        await repository.get_approved_exact(
            workspace_id=uuid4(),
            profile_version_id=uuid4(),
            now=NOW.replace(tzinfo=None),
        )

    assert session.scalars_statements == []
