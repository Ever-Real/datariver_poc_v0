from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from datariver.application.assistant_inference import (
    UNVERIFIABLE_INFERENCE_ANSWER,
    AuthorizedInferencePackage,
    InferenceAttestationSnapshot,
    InferenceExecutionState,
    InferencePolicySnapshot,
    InferenceProviderSnapshot,
    ProviderInferenceDraft,
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
)


def inference_package() -> AuthorizedInferencePackage:
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    workspace_id = uuid4()
    attestation = InferenceAttestationSnapshot(
        fingerprint="a" * 64,
        observed_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
    )
    return AuthorizedInferencePackage.create(
        workspace_id=workspace_id,
        subject_id=uuid4(),
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
                source_locator="catalog://worker-evidence",
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
        provider=InferenceProviderSnapshot(
            workspace_id=workspace_id,
            provider_profile_version_id=uuid4(),
            profile_version=1,
            payload_hash="c" * 64,
            state=InferenceProviderProfileState.APPROVED,
            kind=ProviderKind.INTERNAL,
            server_route_key="internal-route",
            jurisdiction="jurisdiction-a",
            maximum_classification=Classification.INTERNAL,
            residency_attestation=attestation,
            zero_retention_attestation=attestation,
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


async def test_default_worker_is_disabled_and_has_no_state_mutation_dependency() -> None:
    package = inference_package()
    worker = AssistantInferenceWorker()

    result = await worker.execute(package=package)

    assert result.state is InferenceExecutionState.REFUSED
    assert result.answer == UNVERIFIABLE_INFERENCE_ANSWER
    assert result.citations == ()
    assert set(vars(worker)) == {"_adapter"}
    assert isinstance(worker._adapter, DisabledAssistantInferenceAdapter)
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


async def test_worker_calls_only_the_preselected_adapter_once() -> None:
    package = inference_package()
    adapter = FixedAdapter()

    result = await AssistantInferenceWorker(adapter).execute(package=package)

    assert adapter.calls == 1
    assert result.state is InferenceExecutionState.COMPLETED
    assert result.provider_profile_version_id == package.route.provider.provider_profile_version_id
