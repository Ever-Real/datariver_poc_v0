from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.db.models.platform import AccessRoleModel
from datariver.interfaces.http.routes.admin import (
    _data_rule_models,
    _effective_role_data_rules,
    _role_mutation_event,
    _stored_data_rule_document,
)
from datariver.interfaces.http.schemas import (
    AccessRoleDataRuleRequest,
    AccessRoleWriteRequest,
    MembershipAccessDocumentRequest,
)


def _rule(classification: str, level: str = "FULL_ACCESS") -> dict[str, object]:
    return {
        "classification": classification,
        "access_level": level,
        "partial_treatment": "MASK" if level == "PARTIAL_ACCESS" else None,
        "allowed_residency_regions": ["KR"],
        "allowed_processing_purposes": ["METADATA_READ", "DATA_READ"],
    }


def test_access_role_accepts_one_typed_rule_per_classification() -> None:
    value = AccessRoleWriteRequest.model_validate(
        {
            "role_key": "data-steward",
            "name": "Data steward",
            "clearance": "RESTRICTED",
            "groups": ["data-stewards"],
            "allowed_actions": ["catalog.search", "catalog.read"],
            "data_access_rules": [
                _rule("PUBLIC"),
                _rule("INTERNAL"),
                _rule("CONFIDENTIAL", "PARTIAL_ACCESS"),
                _rule("RESTRICTED", "NO_ACCESS")
                | {
                    "allowed_residency_regions": [],
                    "allowed_processing_purposes": [],
                },
            ],
        }
    )

    assert value.data_access_rules is not None
    assert len(value.data_access_rules) == 4
    assert isinstance(value.data_access_rules[0], AccessRoleDataRuleRequest)


def test_legacy_update_omission_preserves_rules_but_explicit_empty_clears_them() -> None:
    base = {
        "role_key": "legacy-editor",
        "name": "Legacy editor",
        "clearance": "INTERNAL",
        "allowed_actions": ["catalog.read"],
    }
    legacy_update = AccessRoleWriteRequest.model_validate(base)
    explicit_clear = AccessRoleWriteRequest.model_validate(base | {"data_access_rules": []})
    current = (AccessRoleDataRuleRequest.model_validate(_rule("PUBLIC")),)

    assert legacy_update.data_access_rules == []
    assert "data_access_rules" not in legacy_update.model_fields_set
    assert "data_access_rules" in explicit_clear.model_fields_set
    assert _effective_role_data_rules(legacy_update, current=current) == current
    assert _effective_role_data_rules(explicit_clear, current=current) == ()
    with pytest.raises(ValidationError, match="omitted or supplied as an array"):
        AccessRoleWriteRequest.model_validate(base | {"data_access_rules": None})

    property_schema = AccessRoleWriteRequest.model_json_schema()["properties"]["data_access_rules"]
    assert property_schema["type"] == "array"
    assert "anyOf" not in property_schema


def test_stored_rule_hash_matches_the_canonical_persisted_document() -> None:
    rule = AccessRoleDataRuleRequest.model_validate(
        _rule("CONFIDENTIAL")
        | {
            "allowed_residency_regions": [" us-east-1 ", "kr"],
            "allowed_processing_purposes": ["DATA_READ", "METADATA_READ"],
        }
    )
    role = AccessRoleModel(
        id=uuid4(),
        workspace_id=uuid4(),
        role_key="canonical-rule",
        name="Canonical rule",
        description="",
        clearance=2,
        groups=[],
        allowed_actions=[],
        denied_actions=[],
        allowed_system_ids=[],
        allowed_domain_ids=[],
        active=True,
        updated_by=uuid4(),
        version=3,
    )

    stored = _data_rule_models(role=role, rules=(rule,), created_by=uuid4())[0]
    permutation = AccessRoleDataRuleRequest.model_validate(
        _rule("CONFIDENTIAL")
        | {
            "allowed_residency_regions": ["KR", "US-EAST-1"],
            "allowed_processing_purposes": ["METADATA_READ", "DATA_READ"],
        }
    )
    permuted = _data_rule_models(role=role, rules=(permutation,), created_by=uuid4())[0]

    assert stored.payload_hash == canonical_json_hash(_stored_data_rule_document(stored))
    assert stored.allowed_residency_regions == ["KR", "US-EAST-1"]
    assert permuted.payload_hash == stored.payload_hash


def test_manual_membership_access_rejects_reserved_role_markers() -> None:
    with pytest.raises(ValidationError, match="reserved role marker"):
        MembershipAccessDocumentRequest.model_validate(
            {
                "active": True,
                "clearance": "INTERNAL",
                "groups": ["engineers", "datariver-role-catalog-reader"],
                "allowed_actions": ["catalog.read"],
                "denied_actions": [],
            }
        )


def test_role_mutation_event_binds_high_risk_decision_and_assurance() -> None:
    workspace_id, role_id, actor_id, decision_id = (uuid4() for _ in range(4))
    role = AccessRoleModel(
        id=role_id,
        workspace_id=workspace_id,
        role_key="audited-role",
        name="Audited role",
        description="",
        clearance=3,
        groups=[],
        allowed_actions=[],
        denied_actions=[],
        allowed_system_ids=[],
        allowed_domain_ids=[],
        active=True,
        updated_by=actor_id,
        version=4,
    )

    event = _role_mutation_event(
        event_type="iam.access_role.updated.v1",
        role=role,
        actor_id=actor_id,
        assurance="HARDWARE_WEBAUTHN",
        policy_decision_id=decision_id,
        payload_hash="a" * 64,
    )

    assert event.aggregate_id == role_id
    assert event.workspace_id == workspace_id
    assert event.payload["policy_decision_id"] == str(decision_id)
    assert event.payload["assurance"] == "HARDWARE_WEBAUTHN"
    assert event.payload["payload_hash"] == "a" * 64


def test_access_role_rejects_duplicate_classification_rules() -> None:
    with pytest.raises(ValidationError, match="classification"):
        AccessRoleWriteRequest.model_validate(
            {
                "role_key": "duplicate-role",
                "name": "Duplicate role",
                "clearance": "INTERNAL",
                "allowed_actions": ["catalog.read"],
                "data_access_rules": [_rule("PUBLIC"), _rule("PUBLIC")],
            }
        )


def test_partial_rule_requires_treatment_and_no_access_has_no_scope() -> None:
    with pytest.raises(ValidationError):
        AccessRoleDataRuleRequest.model_validate(
            _rule("CONFIDENTIAL", "PARTIAL_ACCESS") | {"partial_treatment": None}
        )
    with pytest.raises(ValidationError):
        AccessRoleDataRuleRequest.model_validate(_rule("RESTRICTED", "NO_ACCESS"))


def test_rule_rejects_unbounded_residency_identifier() -> None:
    with pytest.raises(ValidationError, match="uppercase identifiers"):
        AccessRoleDataRuleRequest.model_validate(
            _rule("INTERNAL") | {"allowed_residency_regions": ["KR/../../../secret"]}
        )
