from uuid import uuid4

import pytest

from datariver.bootstrap import (
    LOCAL_DEMO_IDENTITIES,
    _local_human_membership_attributes,
    _resolve_local_subject,
)
from datariver.domain.authz import SERVICE_ONLY_ACTIONS, Action
from datariver.domain.capability_catalog import DEFAULT_HUMAN_ADMIN_ACTIONS
from datariver.infrastructure.db.models.platform import SubjectModel


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
