from __future__ import annotations

from uuid import uuid4

from datariver.domain.authz import Action, Classification
from datariver.infrastructure.db.models.platform import WorkspaceMembershipModel
from datariver.local_admin_catalog_access import admin_catalog_access_command


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

        assert "datariver.local_admin_catalog_access" in source
        assert source.index("_sync_catalog(runner") < source.rindex(
            "_reconcile_local_admin_catalog_access("
        )
