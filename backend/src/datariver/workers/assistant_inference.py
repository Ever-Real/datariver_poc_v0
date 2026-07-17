from __future__ import annotations

from datariver.application.assistant_inference import (
    AuthorizedInferencePackage,
    InferenceExecutionResult,
    InferenceGroundingAssessment,
    InferenceRefusalCode,
    ProviderInferenceDraft,
    finalize_inference_draft,
    provider_draft_is_valid,
    provider_draft_within_budget,
    refused_inference_result,
)
from datariver.application.ports import AssistantGroundingVerifier, AssistantInferenceAdapter


class ExternalInferenceDisabledError(RuntimeError):
    pass


class DisabledAssistantInferenceAdapter(AssistantInferenceAdapter):
    """Safe baseline with no SDK, connection, secret, egress, or provider request."""

    provider_call_count = 0

    async def infer(
        self,
        *,
        package: AuthorizedInferencePackage,
    ) -> ProviderInferenceDraft:
        del package
        raise ExternalInferenceDisabledError("External assistant inference is disabled.")


class GroundingVerifierDisabledError(RuntimeError):
    pass


class DisabledGroundingVerifier(AssistantGroundingVerifier):
    """Fail-closed baseline until a separately measured server-side verifier is supplied."""

    async def assess(
        self,
        *,
        package: AuthorizedInferencePackage,
        draft: ProviderInferenceDraft,
    ) -> InferenceGroundingAssessment:
        del package, draft
        raise GroundingVerifierDisabledError("Assistant grounding verification is disabled.")


class AssistantInferenceWorker:
    """Execute one pre-authorized route and verify its evidence without runtime fallback."""

    def __init__(
        self,
        adapter: AssistantInferenceAdapter | None = None,
        grounding_verifier: AssistantGroundingVerifier | None = None,
    ) -> None:
        self._adapter = adapter or DisabledAssistantInferenceAdapter()
        self._grounding_verifier = grounding_verifier or DisabledGroundingVerifier()

    async def execute(
        self,
        *,
        package: AuthorizedInferencePackage,
    ) -> InferenceExecutionResult:
        try:
            draft = await self._adapter.infer(package=package)
        except Exception:
            return refused_inference_result(
                package=package,
                code=InferenceRefusalCode.PROVIDER_UNAVAILABLE,
            )
        try:
            draft_is_valid = provider_draft_is_valid(draft, package=package)
        except Exception:
            draft_is_valid = False
        if not draft_is_valid:
            return refused_inference_result(
                package=package,
                code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
            )
        try:
            draft_within_budget = provider_draft_within_budget(package=package, draft=draft)
        except Exception:
            draft_within_budget = False
        if not draft_within_budget:
            return refused_inference_result(
                package=package,
                code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
                draft=draft,
            )
        try:
            grounding = await self._grounding_verifier.assess(package=package, draft=draft)
        except Exception:
            return refused_inference_result(
                package=package,
                code=InferenceRefusalCode.GROUNDING_UNAVAILABLE,
                draft=draft,
            )
        try:
            return finalize_inference_draft(package=package, draft=draft, grounding=grounding)
        except Exception:
            return refused_inference_result(
                package=package,
                code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
                draft=draft,
            )
