from __future__ import annotations

from uuid import uuid4

import pytest

from datariver.domain.admin_access import AdminOperation
from datariver.domain.authz import AuthenticationAssurance
from datariver.interfaces.http.schemas import AdminReadContextResponse


@pytest.mark.parametrize("assurance", list(AuthenticationAssurance))
def test_admin_read_context_reports_every_verified_assurance_without_step_up(
    assurance: AuthenticationAssurance,
) -> None:
    response = AdminReadContextResponse(
        subject_id=uuid4(),
        workspace_id=uuid4(),
        display_name="Administrator",
        authentication_assurance=assurance.value,
        fallback_enabled=False,
        allowed_operations=[],
        action_vocabulary=[],
    )

    assert response.authentication_assurance == assurance.value


def test_admin_read_context_serializes_every_domain_operation() -> None:
    response = AdminReadContextResponse(
        subject_id=uuid4(),
        workspace_id=uuid4(),
        display_name="Administrator",
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN.value,
        fallback_enabled=False,
        allowed_operations=list(AdminOperation),
        action_vocabulary=[],
    )

    assert response.allowed_operations == list(AdminOperation)
    assert AdminOperation.IDENTITY_USER_PROVISION in response.allowed_operations
