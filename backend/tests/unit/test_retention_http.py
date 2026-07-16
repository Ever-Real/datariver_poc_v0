from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI

from datariver.domain.retention import (
    AUTOMATION_DISABLED,
    LegalHold,
    LegalHoldScope,
    RetentionDataClass,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.interfaces.http.retention_presenters import (
    legal_hold_response,
    retention_policy_response,
)
from datariver.interfaces.http.router import api_router
from datariver.interfaces.http.routes.retention import _expected_version


def test_retention_openapi_exposes_only_governed_commands() -> None:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    schema = app.openapi()
    paths = schema["paths"]

    expected = {
        "/api/v1/admin/retention/policies",
        "/api/v1/admin/retention/policies/current",
        "/api/v1/admin/retention/policies/{policy_id}/decisions",
        "/api/v1/admin/retention/legal-holds",
        "/api/v1/admin/retention/legal-holds/{hold_id}/release-requests",
        "/api/v1/admin/retention/legal-holds/{hold_id}/release-decisions",
    }
    assert expected <= set(paths)
    assert not any("execute" in path or "delete" in path for path in paths if "retention" in path)

    proposal = schema["components"]["schemas"]["RetentionRulesRequest"]["properties"]
    assert set(proposal) == {
        "completed_operation_days",
        "chat_content_days",
        "audit_online_months",
        "immutable_archive_years",
    }


def test_retention_presenters_keep_every_destructive_effect_disabled() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    policy = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=1,
        rules=RetentionRules(30, 90, 13, 7),
        requester_id=uuid4(),
        reason="Operating policy",
        policy_decision_id=uuid4(),
    )
    hold = LegalHold.create(
        workspace_id=workspace_id,
        data_class=RetentionDataClass.AUDIT_EVIDENCE,
        scope=LegalHoldScope.WORKSPACE,
        scope_id=None,
        reason="Investigation",
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
        now=now,
    )

    policy_document = retention_policy_response(policy)
    hold_document = legal_hold_response(hold)

    assert policy_document.partition_automation_state == AUTOMATION_DISABLED
    assert policy_document.deletion_automation_state == AUTOMATION_DISABLED
    assert hold_document.deletion_effect == "BLOCKED_BY_LEGAL_HOLD"


def test_retention_if_match_is_positive_and_quoted_compatible() -> None:
    assert _expected_version('"12"') == 12
