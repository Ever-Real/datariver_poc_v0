from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.inference_provider import (
    InferenceProviderProfile,
    InferenceProviderProfileState,
    InferenceProviderProfileVersion,
    ProviderAttestation,
    ProviderKind,
)

NOW = datetime(2035, 1, 1, 12, tzinfo=UTC)


def _attestation(
    marker: str,
    *,
    observed_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime = NOW + timedelta(days=1),
) -> ProviderAttestation:
    return ProviderAttestation(
        fingerprint=marker * 64,
        observed_at=observed_at,
        expires_at=expires_at,
    )


def _profile(
    *,
    kind: ProviderKind = ProviderKind.INTERNAL,
    maximum_classification: Classification = Classification.CONFIDENTIAL,
    server_route_key: str = "route-a",
    jurisdiction: str = "JURISDICTION-A",
    residency_attestation: ProviderAttestation | None = None,
    zero_retention_attestation: ProviderAttestation | None = None,
) -> InferenceProviderProfile:
    return InferenceProviderProfile(
        profile_key="profile-a",
        server_route_key=server_route_key,
        kind=kind,
        provider_identity="provider-a",
        model_identity="model-a",
        deployment_identity="deployment-a",
        jurisdiction=jurisdiction,
        region="region-a",
        maximum_classification=maximum_classification,
        residency_attestation=residency_attestation or _attestation("a"),
        zero_retention_attestation=zero_retention_attestation or _attestation("b"),
    )


def _proposal(
    *,
    profile: InferenceProviderProfile | None = None,
    workspace_id: UUID | None = None,
    maker_id: UUID | None = None,
) -> InferenceProviderProfileVersion:
    return InferenceProviderProfileVersion.propose(
        workspace_id=workspace_id or uuid4(),
        profile_version=1,
        profile=profile or _profile(),
        maker_id=maker_id or uuid4(),
        reason="Governed provider registration",
        policy_decision_id=uuid4(),
        now=NOW,
    )


def _approve(proposal: InferenceProviderProfileVersion, *, checker_id: UUID | None = None) -> UUID:
    checker = checker_id or uuid4()
    proposal.approve(
        checker_id=checker,
        reason="Independent capability review",
        policy_decision_id=uuid4(),
        expected_version=proposal.version,
        now=NOW,
    )
    return checker


def test_internal_confidential_profile_requires_independent_approval() -> None:
    proposal = _proposal()

    assert proposal.state is InferenceProviderProfileState.PROPOSED
    assert not proposal.eligible(
        now=NOW,
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=True,
    )

    checker_id = _approve(proposal)

    assert proposal.state is InferenceProviderProfileState.APPROVED
    assert proposal.checker_id == checker_id
    assert proposal.version == 2
    assert proposal.eligible(
        now=NOW,
        effective_classification=Classification.CONFIDENTIAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=True,
    )
    assert [event.event_type for event in proposal.events] == [
        "governance.inference_provider_profile.proposed.v1",
        "governance.inference_provider_profile.approved.v1",
    ]
    assert proposal.events[-1].payload["payload_hash"] == proposal.payload_hash


def test_external_profile_is_bounded_to_internal_and_cannot_satisfy_internal_only() -> None:
    proposal = _proposal(
        profile=_profile(
            kind=ProviderKind.EXTERNAL,
            maximum_classification=Classification.INTERNAL,
        )
    )
    _approve(proposal)

    assert proposal.eligible(
        now=NOW,
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=False,
    )
    assert not proposal.eligible(
        now=NOW,
        effective_classification=Classification.CONFIDENTIAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=False,
    )
    assert not proposal.eligible(
        now=NOW,
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=True,
    )

    with pytest.raises(ValidationError):
        _profile(
            kind=ProviderKind.EXTERNAL,
            maximum_classification=Classification.CONFIDENTIAL,
        )


@pytest.mark.parametrize("kind", [ProviderKind.INTERNAL, ProviderKind.EXTERNAL])
def test_no_provider_can_process_restricted(kind: ProviderKind) -> None:
    with pytest.raises(ValidationError):
        _profile(kind=kind, maximum_classification=Classification.RESTRICTED)


def test_eligibility_requires_exact_jurisdiction_and_current_attestations() -> None:
    proposal = _proposal()
    _approve(proposal)

    assert not proposal.eligible(
        now=NOW,
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="jurisdiction-a",
        require_internal=False,
    )
    assert not proposal.eligible(
        now=NOW + timedelta(days=1),
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=False,
    )
    assert not proposal.eligible(
        now=NOW.replace(tzinfo=None),
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=False,
    )


def test_expired_attestation_blocks_approval() -> None:
    expired = _attestation(
        "c",
        observed_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(seconds=1),
    )
    proposal = _proposal(profile=_profile(zero_retention_attestation=expired))

    with pytest.raises(ConflictError, match="attestations"):
        _approve(proposal)

    assert proposal.state is InferenceProviderProfileState.PROPOSED


def test_maker_cannot_approve_or_reject_own_proposal() -> None:
    maker_id = uuid4()
    proposal = _proposal(maker_id=maker_id)

    with pytest.raises(ValidationError, match="maker"):
        proposal.approve(
            checker_id=maker_id,
            reason="Self approval",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=NOW,
        )

    with pytest.raises(ValidationError, match="maker"):
        proposal.reject(
            checker_id=maker_id,
            reason="Self rejection",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=NOW,
        )

    assert proposal.state is InferenceProviderProfileState.PROPOSED


def test_independent_rejection_is_terminal_and_ineligible() -> None:
    proposal = _proposal()
    proposal.reject(
        checker_id=uuid4(),
        reason="Evidence was insufficient",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=NOW,
    )

    assert proposal.state is InferenceProviderProfileState.REJECTED
    assert proposal.version == 2
    assert not proposal.eligible(
        now=NOW,
        effective_classification=Classification.PUBLIC,
        required_jurisdiction="JURISDICTION-A",
        require_internal=False,
    )
    assert proposal.events[-1].event_type.endswith(".rejected.v1")


def test_canonical_hash_tamper_blocks_approval_and_runtime_eligibility() -> None:
    proposal = _proposal()
    proposal.profile = replace(proposal.profile, model_identity="model-b")

    with pytest.raises(ConflictError, match="integrity"):
        _approve(proposal)

    clean = _proposal()
    _approve(clean)
    clean.profile = replace(clean.profile, region="region-b")

    assert not clean.integrity_valid()
    assert not clean.eligible(
        now=NOW,
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=False,
    )


def test_revocation_is_immediate_and_records_deny_evidence_without_checker() -> None:
    maker_id = uuid4()
    proposal = _proposal(maker_id=maker_id)
    _approve(proposal)
    revocation_decision_id = uuid4()

    proposal.revoke(
        actor_id=maker_id,
        reason="Provider assurance withdrawn",
        policy_decision_id=revocation_decision_id,
        expected_version=2,
        now=NOW + timedelta(minutes=1),
    )

    assert proposal.state is InferenceProviderProfileState.REVOKED
    assert proposal.revoked_by == maker_id
    assert proposal.revocation_reason == "Provider assurance withdrawn"
    assert proposal.revocation_policy_decision_id == revocation_decision_id
    assert proposal.revoked_at == NOW + timedelta(minutes=1)
    assert proposal.version == 3
    assert proposal.events[-1].event_type.endswith(".revoked.v1")
    assert not proposal.eligible(
        now=NOW + timedelta(minutes=1),
        effective_classification=Classification.INTERNAL,
        required_jurisdiction="JURISDICTION-A",
        require_internal=False,
    )


def test_route_is_registry_key_not_url_or_credential_bearing_contract() -> None:
    with pytest.raises(ValidationError, match="route"):
        _profile(server_route_key="https://inference.invalid/v1")

    profile_fields = {item.name for item in fields(InferenceProviderProfile)}
    forbidden_fields = {
        "url",
        "endpoint",
        "endpoint_url",
        "credential",
        "credentials",
        "secret",
        "api_key",
        "headers",
        "http_request",
    }
    assert profile_fields.isdisjoint(forbidden_fields)
