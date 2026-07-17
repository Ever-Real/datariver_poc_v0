from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from uuid import UUID, uuid4

from datariver.application.assistant_inference import (
    UNVERIFIABLE_INFERENCE_ANSWER,
    AuthorizedInferencePackage,
    InferenceAttestationSnapshot,
    InferenceBudgetMode,
    InferenceBudgetSnapshot,
    InferenceBudgetState,
    InferenceExecutionState,
    InferenceGroundingAssessment,
    InferenceGroundingMetric,
    InferenceGroundingPolicySnapshot,
    InferencePolicySnapshot,
    InferenceProviderSnapshot,
    InferenceUsageState,
    ProviderInferenceDraft,
    grounding_answer_hash,
    grounding_evidence_bundle_hash,
)
from datariver.application.evidence import build_evidence_chunk
from datariver.domain.authz import Classification
from datariver.domain.inference_provider import (
    InferenceProviderProfileState,
    ProviderKind,
)
from datariver.workers.assistant_inference import (
    AssistantInferenceWorker,
    DisabledAssistantInferenceAdapter,
    DisabledGroundingVerifier,
)


def inference_package() -> AuthorizedInferencePackage:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    subject_id = uuid4()
    period_timezone = timezone(timedelta(hours=9))
    attestation = InferenceAttestationSnapshot(
        fingerprint="a" * 64,
        observed_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
    )
    return AuthorizedInferencePackage.create(
        workspace_id=workspace_id,
        subject_id=subject_id,
        request_id="request-worker",
        question="Which evidence supports this answer?",
        evidence=(
            build_evidence_chunk(
                workspace_id=workspace_id,
                resource_id=uuid4(),
                classification=Classification.INTERNAL,
                system_id=None,
                domain_id=None,
                owner_department_id=None,
                name="worker evidence",
                description="authorized",
                source_locator="urn:datariver:worker-evidence:1",
                source_version="version-1",
                effective_from=now - timedelta(minutes=1),
                extraction_method="CATALOG_PROJECTION_V1",
            ),
        ),
        policy=InferencePolicySnapshot(
            workspace_id=workspace_id,
            policy_id=uuid4(),
            policy_version=1,
            policy_hash="b" * 64,
            authorization_generation=1,
            required_jurisdiction="jurisdiction-a",
            evaluated_at=now,
        ),
        grounding_policy=InferenceGroundingPolicySnapshot(
            workspace_id=workspace_id,
            policy_id=uuid4(),
            policy_version=1,
            policy_hash="e" * 64,
            metric=InferenceGroundingMetric.COSINE_SIMILARITY,
            minimum_score_millionths=800_000,
            evaluator_version="evaluator-v1",
            evaluated_at=now,
        ),
        primary_provider=InferenceProviderSnapshot(
            workspace_id=workspace_id,
            provider_profile_version_id=uuid4(),
            profile_version=1,
            payload_hash="c" * 64,
            state=InferenceProviderProfileState.APPROVED,
            kind=ProviderKind.INTERNAL,
            server_route_key="internal-route",
            provider_identity="internal-provider",
            model_identity="internal-model",
            deployment_identity="internal-deployment",
            jurisdiction="jurisdiction-a",
            region="kr-private-a",
            maximum_classification=Classification.INTERNAL,
            residency_attestation=attestation,
            zero_retention_attestation=attestation,
        ),
        budget=InferenceBudgetSnapshot(
            budget_decision_id=uuid4(),
            workspace_id=workspace_id,
            subject_id=subject_id,
            policy_version=1,
            policy_hash="d" * 64,
            period_start=datetime(2026, 7, 1, tzinfo=period_timezone),
            period_end=datetime(2026, 8, 1, tzinfo=period_timezone),
            period_timezone=str(period_timezone),
            mode=InferenceBudgetMode.MONITOR_ONLY,
            state=InferenceBudgetState.OBSERVED,
            estimated_tokens=100,
            workspace_consumed_tokens=0,
            subject_consumed_tokens=0,
            workspace_limit_tokens=None,
            subject_limit_tokens=None,
            reservation_id=None,
            decided_at=now,
        ),
        routed_at=now,
    )


class FailingAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self.profile_ids: list[UUID] = []

    async def infer(self, *, package: AuthorizedInferencePackage) -> ProviderInferenceDraft:
        self.calls += 1
        self.profile_ids.append(package.route.provider.provider_profile_version_id)
        raise RuntimeError("provider unavailable")


class FixedAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def infer(self, *, package: AuthorizedInferencePackage) -> ProviderInferenceDraft:
        self.calls += 1
        return ProviderInferenceDraft(
            answer="Grounded worker answer",
            cited_chunk_ids=(package.evidence[0].evidence.chunk_id,),
            input_tokens=20,
            output_tokens=10,
            time_to_first_token_ms=50,
            duration_ms=100,
        )


class FixedGroundingVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def assess(
        self,
        *,
        package: AuthorizedInferencePackage,
        draft: ProviderInferenceDraft,
    ) -> InferenceGroundingAssessment:
        self.calls += 1
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
            score_millionths=900_000,
            evaluator_version=package.route.grounding_policy.evaluator_version,
            evaluated_at=package.route.routed_at + timedelta(milliseconds=1),
        )


class MalformedAdapter:
    async def infer(self, *, package: AuthorizedInferencePackage) -> ProviderInferenceDraft:
        del package
        return cast(ProviderInferenceDraft, object())


class MalformedGroundingVerifier:
    async def assess(
        self,
        *,
        package: AuthorizedInferencePackage,
        draft: ProviderInferenceDraft,
    ) -> InferenceGroundingAssessment:
        del package, draft
        return cast(InferenceGroundingAssessment, object())


async def test_default_worker_is_disabled_and_has_no_state_mutation_dependency() -> None:
    package = inference_package()
    worker = AssistantInferenceWorker()

    result = await worker.execute(package=package)

    assert result.state is InferenceExecutionState.REFUSED
    assert result.answer == UNVERIFIABLE_INFERENCE_ANSWER
    assert result.citations == ()
    assert result.usage_state is InferenceUsageState.UNAVAILABLE
    assert set(vars(worker)) == {"_adapter", "_grounding_verifier"}
    assert isinstance(worker._adapter, DisabledAssistantInferenceAdapter)
    assert isinstance(worker._grounding_verifier, DisabledGroundingVerifier)
    assert worker._adapter.provider_call_count == 0


async def test_provider_failure_is_attempted_once_without_fallback_or_route_downgrade() -> None:
    package = inference_package()
    adapter = FailingAdapter()
    worker = AssistantInferenceWorker(adapter)

    result = await worker.execute(package=package)

    assert adapter.calls == 1
    assert adapter.profile_ids == [package.route.provider.provider_profile_version_id]
    assert result.state is InferenceExecutionState.REFUSED
    assert result.answer == UNVERIFIABLE_INFERENCE_ANSWER
    assert result.provider_profile_version_id == package.route.provider.provider_profile_version_id
    assert result.effective_classification is package.route.effective_classification
    assert result.usage_state is InferenceUsageState.UNAVAILABLE


async def test_worker_calls_only_the_preselected_adapter_once() -> None:
    package = inference_package()
    adapter = FixedAdapter()
    grounding_verifier = FixedGroundingVerifier()

    result = await AssistantInferenceWorker(adapter, grounding_verifier).execute(package=package)

    assert adapter.calls == 1
    assert grounding_verifier.calls == 1
    assert result.state is InferenceExecutionState.COMPLETED
    assert result.provider_profile_version_id == package.route.provider.provider_profile_version_id


async def test_malformed_adapter_return_fails_closed_before_grounding() -> None:
    package = inference_package()
    grounding_verifier = FixedGroundingVerifier()

    result = await AssistantInferenceWorker(
        MalformedAdapter(),
        grounding_verifier,
    ).execute(package=package)

    assert grounding_verifier.calls == 0
    assert result.state is InferenceExecutionState.REFUSED
    assert result.usage_state is InferenceUsageState.UNAVAILABLE


async def test_malformed_grounding_return_fails_closed_and_preserves_usage() -> None:
    package = inference_package()

    result = await AssistantInferenceWorker(
        FixedAdapter(),
        MalformedGroundingVerifier(),
    ).execute(package=package)

    assert result.state is InferenceExecutionState.REFUSED
    assert result.usage_state is InferenceUsageState.OBSERVED
    assert result.input_tokens == 20
    assert result.output_tokens == 10
