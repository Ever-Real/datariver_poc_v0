from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from datariver.interfaces.http.retention_schemas import RetentionExecutionEvidenceResponse
from datariver.interfaces.http.routes.retention import get_erasure_execution_evidence


def _document() -> dict[str, object]:
    now = datetime.now(UTC)
    request_id = uuid4()
    receipt_id = uuid4()
    return {
        "erasure_request_id": request_id,
        "availability": "AVAILABLE",
        "archive_only": True,
        "deletion_automation_state": "DISABLED_NOT_READY",
        "job": {
            "job_id": uuid4(),
            "erasure_request_version": 2,
            "erasure_request_payload_hash": "a" * 64,
            "target_type": "CHAT_SESSION",
            "target_id": uuid4(),
            "target_version": 7,
            "classification": "RESTRICTED",
            "retention_policy_id": uuid4(),
            "retention_policy_hash": "b" * 64,
            "policy_number": 3,
            "execution_authorization_valid_until": now,
            "archive_disposition": "EVIDENCE_ONLY",
            "command_hash": "c" * 64,
            "archive_retain_until": now,
            "state": "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED",
            "next_attempt_at": now,
            "attempt_count": 1,
            "maximum_attempts": 3,
            "archive_manifest_hash": "f" * 64,
            "destructive_state": "DISABLED_NOT_READY",
            "separation_of_duties_verified": True,
            "version": 4,
            "created_at": now,
            "updated_at": now,
            "attempts": [
                {
                    "attempt_no": 1,
                    "state": "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED",
                    "stage": "COMPLETE",
                    "evidence_hash": "d" * 64,
                    "destructive_effect_count": 0,
                    "started_at": now,
                    "finished_at": now,
                }
            ],
            "attempts_truncated": False,
            "events": [
                {
                    "sequence": 1,
                    "event_type": "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED",
                    "attempt_no": 1,
                    "evidence_hash": "e" * 64,
                    "occurred_at": now,
                }
            ],
            "events_truncated": False,
            "receipt": {
                "receipt_id": receipt_id,
                "manifest_hash": "f" * 64,
                "content_sha256": "0" * 64,
                "row_count": 1,
                "byte_count": 128,
                "retention_until": now,
                "legal_hold": False,
                "content_verified_at": now,
                "retention_verified_at": now,
                "verified_at": now,
                "payload_hash": "1" * 64,
            },
        },
    }


def test_retention_execution_evidence_contract_is_sanitized_and_zero_delete() -> None:
    response = RetentionExecutionEvidenceResponse.model_validate(_document())
    serialized = response.model_dump(mode="json")
    encoded = str(serialized)

    assert serialized["availability"] == "AVAILABLE"
    assert serialized["job"]["destructive_state"] == "DISABLED_NOT_READY"
    assert serialized["job"]["attempts"][0]["destructive_effect_count"] == 0
    for forbidden in (
        "object_bucket",
        "object_key",
        "object_version_id",
        "provider_checksum",
        "lease_token",
        "lease_owner",
        "principal_fingerprint",
        "archive_configuration",
    ):
        assert forbidden not in encoded

    document = _document()
    job = document["job"]
    assert isinstance(job, dict)
    job["object_key"] = "must-not-be-accepted"
    with pytest.raises(ValidationError):
        RetentionExecutionEvidenceResponse.model_validate(document)


def test_retention_execution_evidence_contract_rejects_any_destructive_effect() -> None:
    document = _document()
    job = document["job"]
    assert isinstance(job, dict)
    attempts = job["attempts"]
    assert isinstance(attempts, list)
    attempt = attempts[0]
    assert isinstance(attempt, dict)
    attempt["destructive_effect_count"] = 1

    with pytest.raises(ValidationError):
        RetentionExecutionEvidenceResponse.model_validate(document)


def test_retention_execution_evidence_route_disables_browser_storage() -> None:
    source = inspect.getsource(get_erasure_execution_evidence)

    assert 'response.headers["Cache-Control"] = "private, no-store"' in source
