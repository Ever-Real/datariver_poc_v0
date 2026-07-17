from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from datariver.application.assistant_inference import (
    INFERENCE_CONTRACT_VERSION,
    UNVERIFIABLE_INFERENCE_ANSWER,
    AuthorizedEvidenceSnapshot,
    AuthorizedInferencePackage,
    InferenceAttestationSnapshot,
    InferenceBudgetMode,
    InferenceBudgetSnapshot,
    InferenceBudgetState,
    InferenceCitation,
    InferenceExecutionResult,
    InferenceExecutionState,
    InferenceGroundingAssessment,
    InferenceGroundingMetric,
    InferenceGroundingPolicySnapshot,
    InferencePolicySnapshot,
    InferenceProviderSnapshot,
    InferenceRouteReason,
    InferenceRoutingSnapshot,
    InferenceUsageState,
    ProviderInferenceDraft,
    finalize_inference_draft,
    grounding_answer_hash,
    grounding_evidence_bundle_hash,
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
    source_locator: str | None = None,
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
        source_locator=source_locator or f"urn:datariver:test-asset:{resource_id}",
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


def _provider(
    workspace_id: UUID,
    *,
    now: datetime,
    kind: ProviderKind = ProviderKind.INTERNAL,
) -> InferenceProviderSnapshot:
    return InferenceProviderSnapshot(
        workspace_id=workspace_id,
        provider_profile_version_id=uuid4(),
        profile_version=3,
        payload_hash="c" * 64,
        state=InferenceProviderProfileState.APPROVED,
        kind=kind,
        server_route_key=f"{kind.value.lower()}-model-a",
        provider_identity=f"{kind.value.lower()}-provider-a",
        model_identity="governed-model-a",
        deployment_identity="governed-deployment-a",
        jurisdiction="jurisdiction-a",
        region="kr-private-a",
        maximum_classification=(
            Classification.CONFIDENTIAL
            if kind is ProviderKind.INTERNAL
            else Classification.INTERNAL
        ),
        residency_attestation=_attestation(now=now),
        zero_retention_attestation=replace(_attestation(now=now), fingerprint="d" * 64),
    )


def _budget(
    workspace_id: UUID,
    subject_id: UUID,
    *,
    now: datetime,
    mode: InferenceBudgetMode = InferenceBudgetMode.MONITOR_ONLY,
    state: InferenceBudgetState = InferenceBudgetState.OBSERVED,
    workspace_consumed_tokens: int = 120,
    subject_consumed_tokens: int = 30,
) -> InferenceBudgetSnapshot:
    hard_limit = mode is InferenceBudgetMode.HARD_LIMIT
    period_timezone = timezone(timedelta(hours=9))
    return InferenceBudgetSnapshot(
        budget_decision_id=uuid4(),
        workspace_id=workspace_id,
        subject_id=subject_id,
        policy_version=2,
        policy_hash="e" * 64,
        period_start=datetime(2026, 7, 1, tzinfo=period_timezone),
        period_end=datetime(2026, 8, 1, tzinfo=period_timezone),
        period_timezone=str(period_timezone),
        mode=mode,
        state=state,
        estimated_tokens=100,
        workspace_consumed_tokens=workspace_consumed_tokens,
        subject_consumed_tokens=subject_consumed_tokens,
        workspace_limit_tokens=200 if hard_limit else None,
        subject_limit_tokens=100 if hard_limit else None,
        reservation_id=(uuid4() if hard_limit and state is InferenceBudgetState.RESERVED else None),
        decided_at=now,
    )


def _grounding_policy(
    workspace_id: UUID,
    *,
    now: datetime,
    minimum_score_millionths: int = 800_000,
) -> InferenceGroundingPolicySnapshot:
    return InferenceGroundingPolicySnapshot(
        workspace_id=workspace_id,
        policy_id=uuid4(),
        policy_version=3,
        policy_hash="f" * 64,
        metric=InferenceGroundingMetric.COSINE_SIMILARITY,
        minimum_score_millionths=minimum_score_millionths,
        evaluator_version="grounding-evaluator-v1",
        evaluated_at=now,
    )


def _grounding(
    package: AuthorizedInferencePackage,
    draft: ProviderInferenceDraft,
    *,
    score_millionths: int = 900_000,
) -> InferenceGroundingAssessment:
    evidence_by_id = {item.evidence.chunk_id: item.evidence for item in package.evidence}
    return InferenceGroundingAssessment(
        package_id=package.package_id,
        route_decision_id=package.route.route_decision_id,
        policy_id=package.route.grounding_policy.policy_id,
        policy_version=package.route.grounding_policy.policy_version,
        policy_hash=package.route.grounding_policy.policy_hash,
        answer_hash=grounding_answer_hash(draft.answer),
        cited_chunk_ids=draft.cited_chunk_ids,
        canonical_source_urns=tuple(
            evidence_by_id[chunk_id].source_locator for chunk_id in draft.cited_chunk_ids
        ),
        evidence_bundle_hash=grounding_evidence_bundle_hash(
            package=package,
            cited_chunk_ids=draft.cited_chunk_ids,
        ),
        metric=package.route.grounding_policy.metric,
        score_millionths=score_millionths,
        evaluator_version=package.route.grounding_policy.evaluator_version,
        evaluated_at=package.route.routed_at + timedelta(milliseconds=1),
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
    subject_id = uuid4()
    return AuthorizedInferencePackage.create(
        workspace_id=workspace_id,
        subject_id=subject_id,
        request_id="request-assistant-inference-1",
        question="Which governed evidence supports this answer?",
        evidence=tuple(
            _evidence(workspace_id, classification, now=now) for classification in classifications
        ),
        policy=_policy(workspace_id, now=now),
        grounding_policy=_grounding_policy(workspace_id, now=now),
        primary_provider=_provider(workspace_id, now=now),
        budget=_budget(workspace_id, subject_id, now=now),
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
    assert package.route.requested_budget.schema_version == INFERENCE_CONTRACT_VERSION
    assert package.route.execution_budget.schema_version == INFERENCE_CONTRACT_VERSION
    assert package.route.schema_version == INFERENCE_CONTRACT_VERSION
    assert package.route.effective_classification is Classification.CONFIDENTIAL
    with pytest.raises(FrozenInstanceError):
        package.route.effective_classification = Classification.PUBLIC  # type: ignore[misc]


def test_inference_contract_has_no_executable_or_connection_fields() -> None:
    contract_types = (
        InferencePolicySnapshot,
        InferenceAttestationSnapshot,
        InferenceBudgetSnapshot,
        InferenceGroundingPolicySnapshot,
        InferenceProviderSnapshot,
        AuthorizedEvidenceSnapshot,
        InferenceRoutingSnapshot,
        AuthorizedInferencePackage,
        ProviderInferenceDraft,
        InferenceGroundingAssessment,
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
    subject_id = uuid4()

    with pytest.raises(ValidationError, match="not approved"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=subject_id,
            request_id="request-invalid-provider",
            question="Can this route be used?",
            evidence=(_evidence(workspace_id, Classification.INTERNAL, now=now),),
            policy=_policy(workspace_id, now=now),
            grounding_policy=_grounding_policy(workspace_id, now=now),
            primary_provider=provider,
            budget=_budget(workspace_id, subject_id, now=now),
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
    subject_id = uuid4()

    with pytest.raises(ValidationError, match="not current"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=subject_id,
            request_id="request-expired-provider",
            question="Can this expired route be used?",
            evidence=evidence,
            policy=_policy(workspace_id, now=now),
            grounding_policy=_grounding_policy(workspace_id, now=now),
            primary_provider=expired_provider,
            budget=_budget(workspace_id, subject_id, now=now),
            routed_at=now,
        )

    cross_border = replace(_provider(workspace_id, now=now), jurisdiction="jurisdiction-b")
    with pytest.raises(ValidationError, match="crosses"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=subject_id,
            request_id="request-cross-border",
            question="Can this cross-border route be used?",
            evidence=evidence,
            policy=_policy(workspace_id, now=now),
            grounding_policy=_grounding_policy(workspace_id, now=now),
            primary_provider=cross_border,
            budget=_budget(workspace_id, subject_id, now=now),
            routed_at=now,
        )


def test_forged_duplicate_and_empty_citations_fail_closed() -> None:
    package = inference_package()
    first_id = package.evidence[0].evidence.chunk_id
    invalid_citations = ((), (first_id, first_id), (uuid4(),))

    for cited_chunk_ids in invalid_citations:
        draft = ProviderInferenceDraft(
            answer="unsupported answer",
            cited_chunk_ids=cited_chunk_ids,
            input_tokens=10,
            output_tokens=5,
            time_to_first_token_ms=100,
            duration_ms=200,
        )
        result = finalize_inference_draft(
            package=package,
            draft=draft,
            grounding=object(),
        )
        assert result.state is InferenceExecutionState.REFUSED
        assert result.answer == UNVERIFIABLE_INFERENCE_ANSWER
        assert result.citations == ()


def test_valid_provider_result_is_bounded_to_the_exact_authorized_citation_subset() -> None:
    package = inference_package()
    cited = package.evidence[1].evidence

    draft = ProviderInferenceDraft(
        answer="Grounded answer",
        cited_chunk_ids=(cited.chunk_id,),
        input_tokens=120,
        output_tokens=30,
        time_to_first_token_ms=500,
        duration_ms=1_200,
    )
    result = finalize_inference_draft(
        package=package,
        draft=draft,
        grounding=_grounding(package, draft),
    )

    assert result.state is InferenceExecutionState.COMPLETED
    assert result.effective_classification is Classification.INTERNAL
    assert tuple(item.chunk_id for item in result.citations) == (cited.chunk_id,)
    assert result.citations[0].source_version == cited.source_version
    assert result.citations[0].content_hash == cited.content_hash
    assert result.route_reason is InferenceRouteReason.PRIMARY
    assert result.usage_state is InferenceUsageState.OBSERVED
    assert result.generation_tokens_per_second == pytest.approx(30_000 / 700)


def test_low_grounding_score_refuses_with_the_governed_answer() -> None:
    package = inference_package()
    cited = package.evidence[0].evidence
    draft = ProviderInferenceDraft(
        answer="A fluent but weakly grounded answer",
        cited_chunk_ids=(cited.chunk_id,),
        input_tokens=40,
        output_tokens=20,
        time_to_first_token_ms=300,
        duration_ms=900,
    )

    result = finalize_inference_draft(
        package=package,
        draft=draft,
        grounding=_grounding(
            package,
            draft,
            score_millionths=799_999,
        ),
    )

    assert result.state is InferenceExecutionState.REFUSED
    assert result.answer == UNVERIFIABLE_INFERENCE_ANSWER
    assert result.citations == ()
    assert result.usage_state is InferenceUsageState.OBSERVED
    assert result.input_tokens == 40
    assert result.output_tokens == 20


def test_grounding_verdict_is_bound_to_package_policy_and_evidence_bundle() -> None:
    package = inference_package()
    cited = package.evidence[0].evidence
    draft = ProviderInferenceDraft(
        answer="Grounded-looking answer",
        cited_chunk_ids=(cited.chunk_id,),
        input_tokens=40,
        output_tokens=20,
        time_to_first_token_ms=300,
        duration_ms=900,
    )
    assessment = _grounding(package, draft)

    for forged in (
        replace(assessment, package_id=uuid4()),
        replace(assessment, route_decision_id=uuid4()),
        replace(assessment, policy_hash="0" * 64),
        replace(assessment, evidence_bundle_hash="1" * 64),
    ):
        result = finalize_inference_draft(
            package=package,
            draft=draft,
            grounding=forged,
        )
        assert result.state is InferenceExecutionState.REFUSED
        assert result.usage_state is InferenceUsageState.OBSERVED


def test_grounding_policy_rejects_a_zero_threshold() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="threshold"):
        _grounding_policy(uuid4(), now=now, minimum_score_millionths=0)


@pytest.mark.parametrize(
    "source_locator",
    ("urn::missing-nid", "URN:datariver:not-canonical", "urn:datariver:bad%2fescape"),
)
def test_inference_evidence_requires_a_canonical_urn(source_locator: str) -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()

    with pytest.raises(ValidationError, match="canonical URN"):
        AuthorizedEvidenceSnapshot(
            _evidence(
                workspace_id,
                Classification.INTERNAL,
                now=now,
                source_locator=source_locator,
            )
        )


def test_budget_timezone_label_must_match_both_month_boundaries() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()
    budget = _budget(workspace_id, subject_id, now=now)

    with pytest.raises(ValidationError, match="not bound"):
        replace(budget, period_timezone="UTC")


def test_external_route_requires_atomic_budget_reservation() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()
    package = AuthorizedInferencePackage.create(
        workspace_id=workspace_id,
        subject_id=subject_id,
        request_id="request-external-reserved",
        question="Can the approved external route be used?",
        evidence=(_evidence(workspace_id, Classification.INTERNAL, now=now),),
        policy=_policy(workspace_id, now=now),
        grounding_policy=_grounding_policy(workspace_id, now=now),
        primary_provider=_provider(workspace_id, now=now, kind=ProviderKind.EXTERNAL),
        budget=_budget(
            workspace_id,
            subject_id,
            now=now,
            mode=InferenceBudgetMode.HARD_LIMIT,
            state=InferenceBudgetState.RESERVED,
            workspace_consumed_tokens=0,
            subject_consumed_tokens=0,
        ),
        routed_at=now,
    )

    assert package.route.selection_reason is InferenceRouteReason.PRIMARY
    assert package.route.provider.kind is ProviderKind.EXTERNAL
    assert package.route.execution_budget.reservation_id is not None


def test_external_output_cannot_exceed_the_reserved_token_envelope() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()
    package = AuthorizedInferencePackage.create(
        workspace_id=workspace_id,
        subject_id=subject_id,
        request_id="request-external-over-reservation",
        question="Can provider output exceed its reservation?",
        evidence=(_evidence(workspace_id, Classification.INTERNAL, now=now),),
        policy=_policy(workspace_id, now=now),
        grounding_policy=_grounding_policy(workspace_id, now=now),
        primary_provider=_provider(workspace_id, now=now, kind=ProviderKind.EXTERNAL),
        budget=_budget(
            workspace_id,
            subject_id,
            now=now,
            mode=InferenceBudgetMode.HARD_LIMIT,
            state=InferenceBudgetState.RESERVED,
            workspace_consumed_tokens=0,
            subject_consumed_tokens=0,
        ),
        routed_at=now,
    )
    cited = package.evidence[0].evidence
    draft = ProviderInferenceDraft(
        answer="Over-reservation answer",
        cited_chunk_ids=(cited.chunk_id,),
        input_tokens=80,
        output_tokens=21,
        time_to_first_token_ms=100,
        duration_ms=500,
    )

    result = finalize_inference_draft(
        package=package,
        draft=draft,
        grounding=_grounding(package, draft),
    )

    assert result.state is InferenceExecutionState.REFUSED
    assert result.answer == UNVERIFIABLE_INFERENCE_ANSWER
    assert result.usage_state is InferenceUsageState.OBSERVED
    assert result.input_tokens == 80
    assert result.output_tokens == 21


def test_external_budget_exhaustion_preselects_an_approved_internal_route() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()
    external = _provider(workspace_id, now=now, kind=ProviderKind.EXTERNAL)
    internal = _provider(workspace_id, now=now, kind=ProviderKind.INTERNAL)

    package = AuthorizedInferencePackage.create(
        workspace_id=workspace_id,
        subject_id=subject_id,
        request_id="request-budget-fallback",
        question="Can budget fallback change the provider before execution?",
        evidence=(_evidence(workspace_id, Classification.INTERNAL, now=now),),
        policy=_policy(workspace_id, now=now),
        grounding_policy=_grounding_policy(workspace_id, now=now),
        primary_provider=external,
        internal_budget_fallback=internal,
        internal_fallback_budget=_budget(workspace_id, subject_id, now=now),
        budget=_budget(
            workspace_id,
            subject_id,
            now=now,
            mode=InferenceBudgetMode.HARD_LIMIT,
            state=InferenceBudgetState.EXCEEDED,
        ),
        routed_at=now,
    )

    assert package.route.requested_provider == external
    assert package.route.provider == internal
    assert package.route.selection_reason is InferenceRouteReason.BUDGET_LIMIT_FALLBACK
    assert package.route.requested_budget.reservation_id is None
    assert package.route.requested_budget.state is InferenceBudgetState.EXCEEDED
    assert package.route.execution_budget.mode is InferenceBudgetMode.MONITOR_ONLY
    assert package.route.execution_budget.state is InferenceBudgetState.OBSERVED


@pytest.mark.parametrize(
    "invalid_case",
    ("jurisdiction", "state", "classification"),
)
def test_budget_fallback_revalidates_every_selected_provider_predicate(
    invalid_case: str,
) -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()
    internal = _provider(workspace_id, now=now, kind=ProviderKind.INTERNAL)
    if invalid_case == "jurisdiction":
        internal = replace(internal, jurisdiction="jurisdiction-b")
    elif invalid_case == "state":
        internal = replace(internal, state=InferenceProviderProfileState.REVOKED)
    else:
        internal = replace(internal, maximum_classification=Classification.PUBLIC)

    with pytest.raises(ValidationError):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=subject_id,
            request_id="request-invalid-budget-fallback",
            question="Can an ineligible fallback route execute?",
            evidence=(_evidence(workspace_id, Classification.INTERNAL, now=now),),
            policy=_policy(workspace_id, now=now),
            grounding_policy=_grounding_policy(workspace_id, now=now),
            primary_provider=_provider(
                workspace_id,
                now=now,
                kind=ProviderKind.EXTERNAL,
            ),
            budget=_budget(
                workspace_id,
                subject_id,
                now=now,
                mode=InferenceBudgetMode.HARD_LIMIT,
                state=InferenceBudgetState.EXCEEDED,
            ),
            internal_budget_fallback=internal,
            internal_fallback_budget=_budget(workspace_id, subject_id, now=now),
            routed_at=now,
        )


def test_external_budget_exhaustion_without_internal_route_fails_closed() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()

    with pytest.raises(ValidationError, match="requires an internal route"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=subject_id,
            request_id="request-missing-budget-fallback",
            question="Can an exhausted route run without local fallback?",
            evidence=(_evidence(workspace_id, Classification.INTERNAL, now=now),),
            policy=_policy(workspace_id, now=now),
            grounding_policy=_grounding_policy(workspace_id, now=now),
            primary_provider=_provider(
                workspace_id,
                now=now,
                kind=ProviderKind.EXTERNAL,
            ),
            budget=_budget(
                workspace_id,
                subject_id,
                now=now,
                mode=InferenceBudgetMode.HARD_LIMIT,
                state=InferenceBudgetState.EXCEEDED,
            ),
            routed_at=now,
        )


def test_evidence_package_is_bounded_to_ten_unique_chunks() -> None:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()
    evidence = tuple(_evidence(workspace_id, Classification.INTERNAL, now=now) for _ in range(11))

    with pytest.raises(ValidationError, match="count"):
        AuthorizedInferencePackage.create(
            workspace_id=workspace_id,
            subject_id=subject_id,
            request_id="request-too-many-evidence",
            question="Is this evidence package bounded?",
            evidence=evidence,
            policy=_policy(workspace_id, now=now),
            grounding_policy=_grounding_policy(workspace_id, now=now),
            primary_provider=_provider(workspace_id, now=now),
            budget=_budget(workspace_id, subject_id, now=now),
            routed_at=now,
        )
