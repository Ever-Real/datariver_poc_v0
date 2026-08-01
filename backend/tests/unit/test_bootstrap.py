import inspect
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import datariver.bootstrap as bootstrap_module
from datariver.bootstrap import (
    LOCAL_DEMO_IDENTITIES,
    LOCAL_SUBJECT_ID,
    LOCAL_WORKSPACE_ID,
    _local_human_membership_attributes,
    _reconcile_local_canonical_admin_binding,
    _resolve_local_subject,
    bootstrap_local_identity,
)
from datariver.domain.authz import SERVICE_ONLY_ACTIONS, Action, Classification
from datariver.domain.capability_catalog import DEFAULT_HUMAN_ADMIN_ACTIONS
from datariver.infrastructure.db.models.platform import (
    AccessRoleModel,
    CanonicalAdminBindingModel,
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)


def subject(issuer: str, external_subject: str) -> SubjectModel:
    return SubjectModel(
        id=uuid4(),
        issuer=issuer,
        external_subject=external_subject,
        display_name="Local subject",
        active=True,
    )


def test_local_subject_reuses_fixed_id_when_issuer_changes() -> None:
    existing = subject(
        "http://localhost:8081/realms/datariver",
        "00000000-0000-4000-8000-000000000001",
    )

    resolved = _resolve_local_subject(existing, None, label="administrator")

    assert resolved is existing


def test_local_subject_rejects_conflicting_identity() -> None:
    fixed = subject("http://localhost:8081/realms/datariver", "fixed")
    identity = subject("http://localhost:18081/realms/datariver", "identity")

    with pytest.raises(RuntimeError, match="belongs to another subject"):
        _resolve_local_subject(fixed, identity, label="administrator")


def test_local_human_memberships_always_receive_dashboard_read_actions() -> None:
    attributes = _local_human_membership_attributes(
        groups=("data-analysts",),
        allowed_actions=(Action.CATALOG_READ,),
        bootstrap="test",
    )

    assert attributes["allowed_actions"] == [
        "catalog.read",
        "dashboard.read",
        "quality.read",
        "quality.profile.read",
    ]


def test_default_human_admin_actions_come_from_the_exhaustive_catalog() -> None:
    assert len(DEFAULT_HUMAN_ADMIN_ACTIONS) == 64
    assert Action.CHANGE_RAW_CREATE in DEFAULT_HUMAN_ADMIN_ACTIONS
    assert DEFAULT_HUMAN_ADMIN_ACTIONS.isdisjoint(SERVICE_ONLY_ACTIONS)


def test_local_secondary_security_administrator_uses_the_same_default_catalog() -> None:
    secondary = next(
        identity for identity in LOCAL_DEMO_IDENTITIES if identity.username == "sua.han"
    )

    assert set(secondary.allowed_actions) == DEFAULT_HUMAN_ADMIN_ACTIONS
    assert set(secondary.allowed_actions).isdisjoint(SERVICE_ONLY_ACTIONS)


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ["production", "test", "staging", "demo", "seed"])
async def test_local_identity_bootstrap_requires_exact_development_environment(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    monkeypatch.setattr(
        bootstrap_module,
        "get_settings",
        lambda: SimpleNamespace(app_env=app_env),
    )

    with pytest.raises(RuntimeError, match="APP_ENV=development exactly"):
        await bootstrap_local_identity()


def test_local_binding_call_boundary_checks_environment_before_database_access() -> None:
    source = inspect.getsource(bootstrap_local_identity)

    assert source.index('settings.app_env != "development"') < source.index(
        "resolver = SecretResolver()"
    )
    assert source.count("_reconcile_local_canonical_admin_binding(") == 1
    assert "workspace=" not in inspect.getsource(_reconcile_local_canonical_admin_binding)
    assert "subject=" not in inspect.getsource(_reconcile_local_canonical_admin_binding)
    assert "membership=" not in inspect.getsource(_reconcile_local_canonical_admin_binding)


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def one_or_none(self) -> object | None:
        return self._value


class _CanonicalBindingSession:
    def __init__(
        self,
        *,
        workspace: WorkspaceModel,
        subject: SubjectModel,
        membership: WorkspaceMembershipModel,
    ) -> None:
        self.workspace = workspace
        self.subject = subject
        self.membership = membership
        self.role: AccessRoleModel | None = None
        self.binding: CanonicalAdminBindingModel | None = None
        self.flush_count = 0

    async def scalars(self, statement: Any) -> _ScalarResult:
        assert statement.column_descriptions[0].get("entity") is AccessRoleModel
        return _ScalarResult(self.role)

    async def get(self, model: type[object], key: object) -> object | None:
        if model is WorkspaceModel:
            assert key == LOCAL_WORKSPACE_ID
            return self.workspace
        if model is SubjectModel:
            assert key == LOCAL_SUBJECT_ID
            return self.subject
        if model is WorkspaceMembershipModel:
            assert key == {
                "workspace_id": LOCAL_WORKSPACE_ID,
                "subject_id": LOCAL_SUBJECT_ID,
            }
            return self.membership
        if model is CanonicalAdminBindingModel:
            assert key == {
                "workspace_id": LOCAL_WORKSPACE_ID,
                "subject_id": LOCAL_SUBJECT_ID,
            }
            return self.binding
        raise AssertionError(f"Unexpected bootstrap lookup: {model}")

    def add(self, value: object) -> None:
        if isinstance(value, AccessRoleModel):
            value.id = UUID("00000000-0000-4000-8000-0000000001a0")
            value.version = 1
            self.role = value
            return
        if isinstance(value, CanonicalAdminBindingModel):
            value.version = 1
            self.binding = value
            return
        raise AssertionError(f"Unexpected bootstrap model: {type(value)}")

    async def flush(self) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
async def test_local_canonical_binding_is_fixed_parameter_free_and_idempotent() -> None:
    workspace = WorkspaceModel(
        id=LOCAL_WORKSPACE_ID,
        slug="local-development",
        name="Local Development",
        status="ACTIVE",
        settings={},
        version=1,
    )
    administrator = SubjectModel(
        id=LOCAL_SUBJECT_ID,
        issuer="http://localhost/realms/datariver",
        external_subject="local-admin",
        display_name="Local Administrator",
        active=True,
    )
    membership = WorkspaceMembershipModel(
        workspace_id=LOCAL_WORKSPACE_ID,
        subject_id=LOCAL_SUBJECT_ID,
        job_function="LOCAL_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes=_local_human_membership_attributes(
            groups=("security-administrators",),
            allowed_actions=tuple(DEFAULT_HUMAN_ADMIN_ACTIONS),
            bootstrap="test-only",
            allowed_domain_ids=(UUID("00000000-0000-4000-8000-0000000001d0"),),
        ),
        active=True,
        access_expires_at=None,
        version=7,
    )
    session = _CanonicalBindingSession(
        workspace=workspace,
        subject=administrator,
        membership=membership,
    )

    for _ in range(2):
        await _reconcile_local_canonical_admin_binding(
            session=cast(AsyncSession, session),
        )

    assert session.role is not None
    assert session.binding is not None
    assert session.role.allowed_actions == sorted(
        action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS
    )
    assert session.role.denied_actions == []
    assert session.binding.workspace_id == LOCAL_WORKSPACE_ID
    assert session.binding.subject_id == LOCAL_SUBJECT_ID
    assert session.binding.membership_version == membership.version
    assert session.binding.state == "ACTIVE"
    assert session.binding.version == 1
