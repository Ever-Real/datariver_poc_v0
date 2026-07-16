from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from datariver.application.assistant_inference import (
    INFERENCE_CONTRACT_VERSION,
    UNVERIFIABLE_INFERENCE_ANSWER,
    AuthorizedEvidenceSnapshot,
    AuthorizedInferencePackage,
    InferenceAttestationSnapshot,
    InferenceCitation,
    InferenceExecutionResult,
    InferenceExecutionState,
    InferencePolicySnapshot,
    InferenceProviderSnapshot,
    InferenceRoutingSnapshot,
    ProviderInferenceDraft,
    finalize_inference_draft,
)
from datariver.application.dto import ChatEvidence
from datariver.application.evidence import build_evidence_chunk
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError
from datariver.domain.inference_provider import (
    InferenceProviderProfileState,
    ProviderKind,
)


def _evidence(
    workspace_id: UUID,
    classification: Classification,
    *,
    now: datetime,
) -> ChatEvidence:
    resource_id = uuid4()
    return build_evidence_chunk(
        workspace_id=workspace_id,
        resource_id=resource_id,
        classification=classification,
        system_id=uuid4(),
        domain_id=uuid4(),
        owner_department_id=uuid4(),
        name=f"evidence-{resource_id}",
        description="bounded authorized evidence",
        source_locator=f"catalog://assets/{resource_id}",
        source_version="source-version-7",
        effective_from=now - timedelta(minutes=5),
        effective_until=now + timedelta(minutes=30),
        extraction_method="CATALOG_PROJECTION_V1",
    )


def _policy(workspace_id: UUID, *, now: datetime) -> InferencePolicySnapshot:
    return InferencePolicySnapshot(
        workspace_id=workspace_id,
        policy_id=uuid4(),
        policy_version=4,
        policy_hash="a" * 64,
        authorization_generation=9,
        required_jurisdiction="jurisdiction-a",
        evaluated_at=now,
    )


def _attestation(*, now: datetime) -> InferenceAttestationSnapshot:
    return InferenceAttestationSnapshot(
        fingerprint="b" * 64,
        observed_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
    )


def _provider(workspace_id: UUID, *, now: datetime) -> InferenceProviderSnapshot:
    return InferenceProviderSnapshot(
        workspace_id=workspace_id,
        provider_profile_version_id=uuid4(),
        profile_version=3,
        payload_hash="c" * 64,
        state=InferenceProviderProfileState.APPROVED,
        kind=ProviderKind.INTERNAL,
        server_route_key="internal-model-a",
        jurisdiction="jurisdiction-a",
        maximum_classification=Classification.CONFIDENTIAL,
        residency_attestation=_attestation(now=now),
        zero_retention_attestation=replace(_attestation(now=now), fingerprint="d" * 64),
    )


def inference_package(
    *,
    classifications: tuple[Classification, ...] = (
        Classification.PUBLIC,
        Classification.INTERNAL,
    ),
) -> AuthorizedInferencePackage:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    return AuthorizedInferencePackage.create(
        workspace_id=workspace_id,
        subject_id=uuid4(),
        request_id="request-assistant-inference-1",
        question="Which governed evidence supports this answer?",
        evidence=tuple(
            _evidence(workspace_id, classification, now=now) for classification in classifications
        ),
        policy=_policy(workspace_id, now=now),
        provider=_provider(workspace_id, now=now),
        routed_at=now,
    )


def test_package_is_versioned_immutable_and_routes_the_highest_evidence_classification() -> None:
    package = inference_package(
        classifications=(Classification.PUBLIC, Classification.CONFIDENTIAL)
    )

    assert package.schema_version == INFERENCE_CONTRACT_VERSION
    assert all(item.schema_version == INFERENCE_CONTRACT_VERSION for item in package.evidence)
    assert package.route.policy.schema_version == INFERENCE_CONTRACT_VERSION
    assert package.route.provider.schema_version == INFERENCE_CONTRACT_VERSION
    assert package.route.schema_version == INFERENCE_CONTRACT_VERSION
    assert package.route.effective_classification is Classification.CONFIDENTIAL
    with pytest.raises(FrozenInstanceError):
        package.route.effective_classification = Classification.PUBLIC  # type: ignore[misc]


def test_inference_contract_has_no_executable_or_connection_fields() -> None:
    contract_types = (
        InferencePolicySnapshot,
        InferenceAttestationSnapshot,
        InferenceProviderSnapshot,
        AuthorizedEvidenceSnapshot,
        InferenceRoutingSnapshot,
        AuthorizedInferencePackage,
        ProviderInferenceDraft,
        InferenceCitation,
        InferenceExecutionResult,
    )
    prohibited = {
        "endpoint",
        "credential",
        "secret",
        "api_key",
        "sql",
        "cypher",
        "http",
        "tool",
        "mutation",
    }

    field_names = {field.name.lower() for value in contract_types for field in fields(value)}

    assert not {name for name in field_names if any(token in name for token in prohibited)}


def test_restricted_evidence_is_denied_before_route_creation() -> None:
    with pytest.raises(ValidationError, match="RESTRICTED"):
        inference_package(classifications=(Classification.RESTRICTED,))


@pytest.mark.parametrize(
    "invalid_state",
    [
        InferenceProviderProfileState.PROPOSED,
        InferenceProviderProfileState.REJECTED,
        InferenceProviderProfileState.REVOKED,
    ],
)
def test_unapproved_or_revoked_provider_is_denied(
    invalid_state: InferenceProviderProfileState,
) -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    provider = replace(_provider(workspace_id, now=now), state=invalid_state)

    with pytest.raises(ValidationError, match="not approved"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=uuid4(),
            request_id="request-invalid-provider",
            question="Can this route be used?",
            evidence=(_evidence(workspace_id, Classification.INTERNAL, now=now),),
            policy=_policy(workspace_id, now=now),
            provider=provider,
            routed_at=now,
        )


def test_expired_attestation_and_cross_jurisdiction_route_are_denied() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    evidence = (_evidence(workspace_id, Classification.INTERNAL, now=now),)
    expired = InferenceAttestationSnapshot(
        fingerprint="e" * 64,
        observed_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    expired_provider = replace(_provider(workspace_id, now=now), residency_attestation=expired)

    with pytest.raises(ValidationError, match="not current"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=uuid4(),
            request_id="request-expired-provider",
            question="Can this expired route be used?",
            evidence=evidence,
            policy=_policy(workspace_id, now=now),
            provider=expired_provider,
            routed_at=now,
        )

    cross_border = replace(_provider(workspace_id, now=now), jurisdiction="jurisdiction-b")
    with pytest.raises(ValidationError, match="crosses"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=uuid4(),
            request_id="request-cross-border",
            question="Can this cross-border route be used?",
            evidence=evidence,
            policy=_policy(workspace_id, now=now),
            provider=cross_border,
            routed_at=now,
        )


def test_forged_duplicate_and_empty_citations_fail_closed() -> None:
    package = inference_package()
    first_id = package.evidence[0].evidence.chunk_id
    invalid_citations = ((), (first_id, first_id), (uuid4(),))

    for cited_chunk_ids in invalid_citations:
        result = finalize_inference_draft(
            package=package,
            draft=ProviderInferenceDraft(
                answer="unsupported answer",
                cited_chunk_ids=cited_chunk_ids,
                input_tokens=10,
                output_tokens=5,
                time_to_first_token_ms=100,
                duration_ms=200,
            ),
        )
        assert result.state is InferenceExecutionState.REFUSED
        assert result.answer == UNVERIFIABLE_INFERENCE_ANSWER
        assert result.citations == ()


def test_valid_provider_result_is_bounded_to_the_exact_authorized_citation_subset() -> None:
    package = inference_package()
    cited = package.evidence[1].evidence

    result = finalize_inference_draft(
        package=package,
        draft=ProviderInferenceDraft(
            answer="Grounded answer",
            cited_chunk_ids=(cited.chunk_id,),
            input_tokens=120,
            output_tokens=30,
            time_to_first_token_ms=500,
            duration_ms=1_200,
        ),
    )

    assert result.state is InferenceExecutionState.COMPLETED
    assert result.effective_classification is Classification.INTERNAL
    assert tuple(item.chunk_id for item in result.citations) == (cited.chunk_id,)
    assert result.citations[0].source_version == cited.source_version
    assert result.citations[0].content_hash == cited.content_hash


def test_evidence_package_is_bounded_to_ten_unique_chunks() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    evidence = tuple(_evidence(workspace_id, Classification.INTERNAL, now=now) for _ in range(11))

    with pytest.raises(ValidationError, match="count"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=uuid4(),
            request_id="request-too-many-evidence",
            question="Is this evidence package bounded?",
            evidence=evidence,
            policy=_policy(workspace_id, now=now),
            provider=_provider(workspace_id, now=now),
            routed_at=now,
        )
