from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import datariver.local_admin_catalog_access as local_admin_catalog_access_module
from datariver.domain.authz import Action, Classification
from datariver.infrastructure.db.models.platform import WorkspaceMembershipModel
from datariver.local_admin_catalog_access import (
    _apply_local_catalog_scopes,
    _read_active_catalog_scopes,
    admin_catalog_access_command,
    reconcile_local_admin_catalog_access,
)


@asynccontextmanager
async def _async_context(value: Any) -> AsyncIterator[Any]:
    yield value


def _catalog_read_database(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[object],
    scalar_values: list[int],
) -> SimpleNamespace:
    session = MagicMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    session.scalar = AsyncMock(side_effect=scalar_values)
    session.begin.return_value = _async_context(session)
    database = SimpleNamespace(
        session_factory=lambda: _async_context(session),
        close=AsyncMock(),
    )
    monkeypatch.setattr(local_admin_catalog_access_module, "Database", lambda *_a, **_k: database)
    monkeypatch.setattr(
        local_admin_catalog_access_module,
        "set_security_context",
        AsyncMock(),
    )
    return database


def test_local_admin_catalog_access_adds_exact_scopes_without_broadening_policy() -> None:
    workspace_id = uuid4()
    administrator_id = uuid4()
    existing_system_id = uuid4()
    catalog_system_id = uuid4()
    existing_domain_id = uuid4()
    catalog_domain_id = uuid4()
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=administrator_id,
        department_id=None,
        job_function="LOCAL_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": ["security-administrators"],
            "allowed_actions": [
                Action.ADMIN_MANAGE.value,
                Action.CATALOG_READ.value,
                Action.CATALOG_SEARCH.value,
                Action.CHAT_QUERY.value,
                Action.QUALITY_READ.value,
            ],
            "denied_actions": [Action.CATALOG_EXPORT.value],
            "allowed_system_ids": [str(existing_system_id)],
            "allowed_domain_ids": [str(existing_domain_id)],
        },
        active=True,
        version=9,
    )

    command = admin_catalog_access_command(
        membership=membership,
        system_ids=frozenset({catalog_system_id}),
        domain_ids=frozenset({catalog_domain_id}),
    )

    assert command.expected_membership_version == 9
    assert command.clearance is Classification.RESTRICTED
    assert command.groups == frozenset({"security-administrators"})
    assert command.allowed_actions == {
        Action.ADMIN_MANAGE,
        Action.CATALOG_READ,
        Action.CATALOG_SEARCH,
        Action.CHAT_QUERY,
        Action.QUALITY_READ,
    }
    assert command.denied_actions == {Action.CATALOG_EXPORT}
    assert command.allowed_system_ids == {existing_system_id, catalog_system_id}
    assert command.allowed_domain_ids == {existing_domain_id, catalog_domain_id}


def test_local_admin_catalog_access_replay_is_a_natural_noop() -> None:
    system_id = uuid4()
    domain_id = uuid4()
    membership = WorkspaceMembershipModel(
        workspace_id=uuid4(),
        subject_id=uuid4(),
        department_id=None,
        job_function="LOCAL_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": ["security-administrators"],
            "allowed_actions": [Action.ADMIN_MANAGE.value],
            "denied_actions": [],
            "allowed_system_ids": [str(system_id)],
            "allowed_domain_ids": [str(domain_id)],
        },
        active=True,
        version=10,
    )
    original_attributes = dict(membership.attributes)

    updated = _apply_local_catalog_scopes(
        membership=membership,
        system_ids=frozenset({system_id}),
        domain_ids=frozenset({domain_id}),
    )

    assert updated is False
    assert membership.version == 10
    assert membership.attributes == original_attributes


def test_local_admin_catalog_scope_update_preserves_non_scope_authority() -> None:
    existing_system_id = uuid4()
    catalog_system_id = uuid4()
    existing_domain_id = uuid4()
    catalog_domain_id = uuid4()
    membership = WorkspaceMembershipModel(
        workspace_id=uuid4(),
        subject_id=uuid4(),
        department_id=None,
        job_function="LOCAL_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": ["security-administrators"],
            "allowed_actions": [Action.ADMIN_MANAGE.value, Action.CATALOG_READ.value],
            "denied_actions": [Action.CATALOG_EXPORT.value],
            "allowed_system_ids": [str(existing_system_id)],
            "allowed_domain_ids": [str(existing_domain_id)],
            "bootstrap": "local-identity-v1",
        },
        active=True,
        version=10,
    )

    updated = _apply_local_catalog_scopes(
        membership=membership,
        system_ids=frozenset({catalog_system_id}),
        domain_ids=frozenset({catalog_domain_id}),
    )

    assert updated is True
    assert membership.version == 11
    assert membership.clearance == int(Classification.RESTRICTED)
    assert membership.attributes == {
        "groups": ["security-administrators"],
        "allowed_actions": [Action.ADMIN_MANAGE.value, Action.CATALOG_READ.value],
        "denied_actions": [Action.CATALOG_EXPORT.value],
        "allowed_system_ids": sorted((str(existing_system_id), str(catalog_system_id))),
        "allowed_domain_ids": sorted((str(existing_domain_id), str(catalog_domain_id))),
        "bootstrap": "local-identity-v1",
    }


def test_operator_workflows_reconcile_admin_scope_after_catalog_sync() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for workflow in (
        root / "scripts" / "workflow_fresh_setup.py",
        root / "scripts" / "workflow_update_restart.py",
    ):
        source = workflow.read_text(encoding="utf-8")
        reconciliation = source.split("def _reconcile_local_admin_catalog_access(", maxsplit=1)[
            1
        ].split("\ndef ", maxsplit=1)[0]

        assert "datariver.local_admin_catalog_access" in source
        assert source.index("_sync_catalog(runner") < source.rindex(
            "_reconcile_local_admin_catalog_access("
        )
        assert all(
            token in reconciliation
            for token in (
                '"--profile"',
                '"tools"',
                '"run"',
                '"--rm"',
                '"--no-deps"',
                '"--build"',
                '"local-bootstrap"',
                '"datariver.local_admin_catalog_access"',
            )
        )
        assert '"exec"' not in reconciliation
        assert '"api"' not in reconciliation

    compose_source = (root / "compose.yaml").read_text(encoding="utf-8")
    local_bootstrap = compose_source.split("  local-bootstrap:", maxsplit=1)[1].split(
        "\n  api:", maxsplit=1
    )[0]
    assert "postgres_app_password" in local_bootstrap
    assert "postgres_bootstrap_password" in local_bootstrap


@pytest.mark.asyncio
async def test_local_catalog_reconciliation_rejects_non_development_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_admin_catalog_access_module,
        "get_settings",
        lambda: SimpleNamespace(app_env="production"),
    )

    with pytest.raises(RuntimeError, match="development-only"):
        await reconcile_local_admin_catalog_access()


@pytest.mark.asyncio
async def test_catalog_read_failure_prevents_bootstrap_database_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(app_env="development")
    bootstrap_database_opened = False

    async def fail_catalog_read(**_: object) -> object:
        raise RuntimeError("catalog read failed")

    class UnexpectedBootstrapDatabase:
        def __init__(self, *_: object, **__: object) -> None:
            nonlocal bootstrap_database_opened
            bootstrap_database_opened = True

    monkeypatch.setattr(local_admin_catalog_access_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        local_admin_catalog_access_module,
        "_read_active_catalog_scopes",
        fail_catalog_read,
    )
    monkeypatch.setattr(
        local_admin_catalog_access_module,
        "Database",
        UnexpectedBootstrapDatabase,
    )

    with pytest.raises(RuntimeError, match="catalog read failed"):
        await reconcile_local_admin_catalog_access()

    assert bootstrap_database_opened is False


@pytest.mark.asyncio
async def test_active_catalog_scope_read_accepts_provider_asset_without_canonical_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_system_id = uuid4()
    provider_domain_id = uuid4()
    canonical_domain_id = uuid4()
    database = _catalog_read_database(
        monkeypatch,
        rows=[
            SimpleNamespace(system_id=None, domain_id=provider_domain_id),
            SimpleNamespace(
                system_id=canonical_system_id,
                domain_id=canonical_domain_id,
            ),
        ],
        scalar_values=[2, 0, 0],
    )

    system_ids, domain_ids, active_count, quarantined_count = await _read_active_catalog_scopes(
        settings=SimpleNamespace(  # type: ignore[arg-type]
            database_url="postgresql+asyncpg://app@postgres/datariver",
            database_secret_ref="secret://postgres_app_password",
        ),
        resolver=SimpleNamespace(resolve=lambda _: "test-only-password"),  # type: ignore[arg-type]
    )

    assert system_ids == {canonical_system_id}
    assert domain_ids == {provider_domain_id, canonical_domain_id}
    assert active_count == 2
    assert quarantined_count == 0
    database.close.assert_awaited_once()
    invalid_predicate = (
        inspect.getsource(_read_active_catalog_scopes)
        .split(
            "invalid_active_count =",
            maxsplit=1,
        )[1]
        .split("if invalid_active_count", maxsplit=1)[0]
    )
    assert "AssetProjectionModel.domain_id.is_(None)" in invalid_predicate
    assert "AssetProjectionModel.system_id.is_(None)" not in invalid_predicate


@pytest.mark.asyncio
async def test_active_catalog_scope_read_rejects_missing_non_public_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _catalog_read_database(
        monkeypatch,
        rows=[SimpleNamespace(system_id=None, domain_id=None)],
        scalar_values=[1, 0, 1],
    )

    with pytest.raises(RuntimeError, match="missing its governed Domain scope"):
        await _read_active_catalog_scopes(
            settings=SimpleNamespace(  # type: ignore[arg-type]
                database_url="postgresql+asyncpg://app@postgres/datariver",
                database_secret_ref="secret://postgres_app_password",
            ),
            resolver=SimpleNamespace(  # type: ignore[arg-type]
                resolve=lambda _: "test-only-password"
            ),
        )

    database.close.assert_awaited_once()


def test_local_catalog_reconciliation_is_fixed_atomic_and_binding_current() -> None:
    source = inspect.getsource(reconcile_local_admin_catalog_access)
    catalog_source = inspect.getsource(_read_active_catalog_scopes)
    bootstrap_transaction = source.split(
        "async with bootstrap_database.session_factory() as session, session.begin():",
        maxsplit=1,
    )[1].split("\n    finally:", maxsplit=1)[0]

    assert source.index('settings.app_env != "development"') < source.index(
        "resolver = SecretResolver()"
    )
    assert source.index("_read_active_catalog_scopes(") < source.index(
        "settings.bootstrap_database_url"
    )
    assert "settings.database_url" in catalog_source
    assert "settings.database_secret_ref" in catalog_source
    assert "settings.bootstrap_database_url" not in catalog_source
    assert "settings.bootstrap_database_secret_ref" not in catalog_source
    assert "AssetProjectionModel" in catalog_source
    assert "WorkspaceMembershipModel" not in catalog_source
    assert "CanonicalAdminBindingModel" not in catalog_source
    assert "settings.bootstrap_database_url" in source
    assert "settings.bootstrap_database_secret_ref" in source
    assert "AssetProjectionModel" not in source
    assert "session.begin()" in source
    assert ".with_for_update()" in source
    assert "_apply_local_catalog_scopes(" in source
    assert "_reconcile_local_canonical_admin_binding(session=session)" in source
    assert "_canonical_admin_binding_is_current(" in source
    assert "integration." not in source
    assert "SqlOutboxWriter" not in source
    assert "SqlIdempotencyStore" not in source
    assert "PolicyDecisionModel" not in source
    assert "except " not in bootstrap_transaction
    assert bootstrap_transaction.index("_apply_local_catalog_scopes(") < (
        bootstrap_transaction.index("_reconcile_local_canonical_admin_binding(session=session)")
    )
    assert "ProfileRoleAssignmentModel" not in source
    assert "update_membership_with_hardware_key" not in source
    assert "assert_manual_access_update_allowed" not in source
