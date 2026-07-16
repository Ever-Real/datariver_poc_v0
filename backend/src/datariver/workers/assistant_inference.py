from __future__ import annotations

from datariver.application.assistant_inference import (
    AuthorizedInferencePackage,
    InferenceExecutionResult,
    InferenceRefusalCode,
    ProviderInferenceDraft,
    finalize_inference_draft,
    refused_inference_result,
)
from datariver.application.ports import AssistantInferenceAdapter


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


class AssistantInferenceWorker:
    """Execute exactly one pre-authorized route without fallback or state mutation."""

    def __init__(self, adapter: AssistantInferenceAdapter | None = None) -> None:
        self._adapter = adapter or DisabledAssistantInferenceAdapter()

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
        return finalize_inference_draft(package=package, draft=draft)
