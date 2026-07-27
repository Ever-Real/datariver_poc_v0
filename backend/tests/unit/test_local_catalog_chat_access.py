from __future__ import annotations

from uuid import uuid4

from datariver.domain.authz import Action, Classification
from datariver.infrastructure.db.models.platform import WorkspaceMembershipModel
from datariver.local_catalog_chat_access import _chat_access_command


def test_local_catalog_chat_access_preserves_existing_rights_and_adds_dynamic_scopes() -> None:
    workspace_id = uuid4()
    subject_id = uuid4()
    existing_system_id = uuid4()
    oracle_system_id = uuid4()
    oracle_domain_id = uuid4()
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        department_id=None,
        job_function="DATA_ANALYST",
        clearance=int(Classification.INTERNAL),
        attributes={
            "groups": ["data-analysts"],
            "allowed_actions": [Action.CHANGE_READ.value],
            "denied_actions": [Action.CHAT_QUERY.value],
            "allowed_system_ids": [str(existing_system_id)],
            "allowed_domain_ids": [],
        },
        active=True,
        version=7,
    )

    command = _chat_access_command(
        membership=membership,
        system_ids=frozenset({oracle_system_id}),
        domain_ids=frozenset({oracle_domain_id}),
        minimum_classification=Classification.CONFIDENTIAL,
    )

    assert command.clearance is Classification.CONFIDENTIAL
    assert command.allowed_actions >= {
        Action.CATALOG_READ,
        Action.CATALOG_SEARCH,
        Action.CHAT_QUERY,
        Action.KG_READ,
        Action.CHANGE_READ,
    }
    assert Action.CHAT_QUERY not in command.denied_actions
    assert command.allowed_system_ids == frozenset({existing_system_id, oracle_system_id})
    assert command.allowed_domain_ids == frozenset({oracle_domain_id})
    assert command.expected_membership_version == 7
