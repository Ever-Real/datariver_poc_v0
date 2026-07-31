from uuid import uuid4

import pytest

from datariver.bootstrap import _local_human_membership_attributes, _resolve_local_subject
from datariver.domain.authz import Action
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
