from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest

import datariver.local_admin_catalog_access as local_admin_catalog_access_module
from datariver.domain.authz import Action, Classification
from datariver.infrastructure.db.models.platform import WorkspaceMembershipModel
from datariver.local_admin_catalog_access import (
    admin_catalog_access_command,
    reconcile_local_admin_catalog_access,
)


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


def test_local_catalog_reconciliation_is_fixed_atomic_and_binding_current() -> None:
    source = inspect.getsource(reconcile_local_admin_catalog_access)

    assert source.index('settings.app_env != "development"') < source.index(
        "resolver = SecretResolver()"
    )
    assert "settings.bootstrap_database_url" in source
    assert "settings.bootstrap_database_secret_ref" in source
    assert "session.begin()" in source
    assert ".with_for_update()" in source
    assert "SqlMembershipAccessRepository(session).apply(command)" in source
    assert "_reconcile_local_canonical_admin_binding(session=session)" in source
    assert "_canonical_admin_binding_is_current(" in source
    assert "SqlOutboxWriter(session).add_events" in source
    assert "SqlIdempotencyStore(session)" in source
    assert "idempotency.save_result" in source
    assert "update_membership_with_hardware_key" not in source
    assert "assert_manual_access_update_allowed" not in source
