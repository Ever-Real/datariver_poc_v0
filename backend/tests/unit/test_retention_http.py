from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI

from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError
from datariver.domain.retention import (
    AUTOMATION_DISABLED,
    ErasureRequest,
    ErasureTargetType,
    LegalHold,
    LegalHoldScope,
    RetentionDataClass,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.interfaces.http.retention_presenters import (
    erasure_request_response,
    legal_hold_response,
    retention_policy_response,
)
from datariver.interfaces.http.retention_schemas import RetentionPolicyProposalRequest
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
        "/api/v1/admin/retention/legal-holds/{hold_id}",
        "/api/v1/admin/retention/legal-holds/{hold_id}/release-requests",
        "/api/v1/admin/retention/legal-holds/{hold_id}/release-decisions",
        "/api/v1/admin/retention/erasure-requests",
        "/api/v1/admin/retention/erasure-requests/{erasure_request_id}",
        "/api/v1/admin/retention/erasure-requests/{erasure_request_id}/decisions",
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
    for path in (
        "/api/v1/admin/retention/policies",
        "/api/v1/admin/retention/legal-holds",
        "/api/v1/admin/retention/erasure-requests",
    ):
        parameters = {
            parameter["name"]: parameter["schema"] for parameter in paths[path]["get"]["parameters"]
        }
        assert parameters["limit"]["maximum"] == 100
        assert parameters["cursor"]["anyOf"][0]["maxLength"] == 2000

    for response_schema in (
        "RetentionPolicyListResponse",
        "LegalHoldListResponse",
        "ErasureRequestListResponse",
    ):
        assert {"items", "page"} <= set(
            schema["components"]["schemas"][response_schema]["properties"]
        )


def test_policy_book_v2_admin_wire_contract_accepts_canonical_archive_dispositions() -> None:
    request = RetentionPolicyProposalRequest.model_validate(
        {
            "rules": {
                "completed_operation_days": 30,
                "chat_content_days": 30,
                "audit_online_months": 12,
                "immutable_archive_years": 7,
            },
            "contract": {
                "effective_from": "2026-07-23T00:00:00Z",
                "effective_until": None,
                "execution_authorization_hours": 24,
                "class_rules": [
                    {
                        "data_class": "COMPLETED_OPERATIONS",
                        "unit": "DAYS",
                        "minimum": 30,
                        "maximum": 365,
                        "archive_disposition": "NO_ARCHIVE",
                    },
                    {
                        "data_class": "CHAT_CONTENT",
                        "unit": "DAYS",
                        "minimum": 7,
                        "maximum": 365,
                        "archive_disposition": "NO_ARCHIVE",
                    },
                    {
                        "data_class": "AUDIT_EVIDENCE",
                        "unit": "MONTHS",
                        "minimum": 12,
                        "maximum": 84,
                        "archive_disposition": "CONTENT_WORM",
                    },
                    {
                        "data_class": "OBJECT_DATA",
                        "unit": "DAYS",
                        "minimum": 30,
                        "maximum": 3650,
                        "archive_disposition": "CONTENT_WORM",
                    },
                ],
            },
            "reason": "Reviewed enterprise policy",
        }
    )

    assert request.contract is not None
    assert [rule.archive_disposition.value for rule in request.contract.class_rules] == [
        "NO_ARCHIVE",
        "NO_ARCHIVE",
        "CONTENT_WORM",
        "CONTENT_WORM",
    ]


def test_retention_presenters_keep_every_destructive_effect_disabled() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    policy = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=1,
        rules=RetentionRules(17, 29, 8, 4),
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
    erasure = ErasureRequest.create(
        workspace_id=workspace_id,
        target_type=ErasureTargetType.UPLOAD_OBJECT,
        target_id=uuid4(),
        target_version=1,
        target_owner_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        retention_policy_id=policy.policy_id,
        retention_policy_hash=policy.payload_hash,
        requester_id=uuid4(),
        reason="Governed destruction",
        policy_decision_id=uuid4(),
        now=now,
        expires_at=now + timedelta(hours=1),
    )

    policy_document = retention_policy_response(policy)
    hold_document = legal_hold_response(hold)
    erasure_document = erasure_request_response(erasure)

    assert policy_document.partition_automation_state == AUTOMATION_DISABLED
    assert policy_document.deletion_automation_state == AUTOMATION_DISABLED
    assert hold_document.deletion_effect == "BLOCKED_BY_LEGAL_HOLD"
    assert erasure_document.execution_state == AUTOMATION_DISABLED


def test_retention_if_match_is_positive_and_quoted_compatible() -> None:
    assert _expected_version('"12"') == 12


@pytest.mark.parametrize("value", ["12", '"12', '12"', '"0"', '"01"', 'W/"12"'])
def test_retention_if_match_rejects_noncanonical_etags(value: str) -> None:
    with pytest.raises(ValidationError):
        _expected_version(value)
