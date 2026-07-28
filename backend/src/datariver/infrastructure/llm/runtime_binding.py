from __future__ import annotations

from uuid import UUID

from datariver.application.classification_access import (
    InferenceRuntimeBinding,
    InferenceStage,
)
from datariver.config import Settings
from datariver.domain.common import ConflictError, canonical_json_hash

LOCAL_CHAT_ROUTE_KEY = "local-ollama-native-chat-v1"
LOCAL_EMBEDDING_ROUTE_KEY = "local-ollama-embeddings-v1"
LOCAL_RERANKER_ROUTE_KEY = "local-llama-cpp-rerank-v1"
INTRANET_CHAT_ROUTE_KEY = "intranet-openai-chat-v1"
INTRANET_EMBEDDING_ROUTE_KEY = "intranet-openai-embeddings-v1"
INTRANET_RERANKER_ROUTE_KEY = "intranet-rerank-v1"


def resolve_composition_runtime_binding(settings: Settings) -> InferenceRuntimeBinding | None:
    if settings.local_ollama_chat_enabled:
        if settings.local_ollama_chat_base_url is None or settings.local_ollama_chat_model is None:
            raise ConflictError("The local Chat runtime binding is incomplete.")
        return _binding(
            stage=InferenceStage.COMPOSITION,
            profile_id=settings.chat_composition_provider_profile_version_id,
            server_route_key=LOCAL_CHAT_ROUTE_KEY,
            provider_identity="ollama-native-chat",
            model_identity=settings.local_ollama_chat_model,
            deployment_document={
                "adapter_contract": "ollama-native-chat-v1",
                "base_url": str(settings.local_ollama_chat_base_url),
                "context_tokens": settings.local_ollama_chat_context_tokens,
                "timeout_seconds": settings.local_ollama_chat_timeout_seconds,
            },
        )
    if settings.intranet_openai_compatible_chat_enabled:
        if (
            settings.intranet_openai_compatible_chat_base_url is None
            or settings.intranet_openai_compatible_chat_model is None
            or settings.intranet_openai_compatible_chat_api_key_secret_ref is None
        ):
            raise ConflictError("The intranet Chat runtime binding is incomplete.")
        return _binding(
            stage=InferenceStage.COMPOSITION,
            profile_id=settings.chat_composition_provider_profile_version_id,
            server_route_key=INTRANET_CHAT_ROUTE_KEY,
            provider_identity="intranet-openai-compatible",
            model_identity=settings.intranet_openai_compatible_chat_model,
            deployment_document={
                "adapter_contract": "openai-compatible-grounded-chat-v1",
                "allowed_hosts": sorted(settings.intranet_openai_compatible_allowed_hosts),
                "approved_public_hosts": sorted(
                    settings.intranet_openai_compatible_approved_public_hosts
                ),
                "base_url": str(settings.intranet_openai_compatible_chat_base_url),
                "context_tokens": settings.intranet_openai_compatible_chat_context_tokens,
                "enable_thinking": (settings.intranet_openai_compatible_chat_enable_thinking),
                "repetition_penalty": (settings.intranet_openai_compatible_chat_repetition_penalty),
                "secret_ref_identity": (
                    settings.intranet_openai_compatible_chat_api_key_secret_ref
                ),
                "stream": False,
                "temperature": settings.intranet_openai_compatible_chat_temperature,
                "timeout_seconds": (settings.intranet_openai_compatible_chat_timeout_seconds),
                "top_p": settings.intranet_openai_compatible_chat_top_p,
            },
        )
    return None


def resolve_embedding_runtime_binding(settings: Settings) -> InferenceRuntimeBinding | None:
    if settings.local_ollama_embedding_enabled:
        if (
            settings.local_ollama_embedding_base_url is None
            or settings.local_ollama_embedding_model is None
        ):
            raise ConflictError("The local embedding runtime binding is incomplete.")
        return _binding(
            stage=InferenceStage.EMBEDDING,
            profile_id=settings.chat_embedding_provider_profile_version_id,
            server_route_key=LOCAL_EMBEDDING_ROUTE_KEY,
            provider_identity="ollama-openai-compatible",
            model_identity=settings.local_ollama_embedding_model,
            deployment_document={
                "adapter_contract": "openai-compatible-embeddings-v1",
                "base_url": str(settings.local_ollama_embedding_base_url),
                "timeout_seconds": settings.local_ollama_embedding_timeout_seconds,
            },
        )
    if settings.intranet_openai_compatible_embedding_enabled:
        if (
            settings.intranet_openai_compatible_embedding_base_url is None
            or settings.intranet_openai_compatible_embedding_model is None
            or settings.intranet_openai_compatible_embedding_api_key_secret_ref is None
        ):
            raise ConflictError("The intranet embedding runtime binding is incomplete.")
        return _binding(
            stage=InferenceStage.EMBEDDING,
            profile_id=settings.chat_embedding_provider_profile_version_id,
            server_route_key=INTRANET_EMBEDDING_ROUTE_KEY,
            provider_identity="intranet-openai-compatible",
            model_identity=settings.intranet_openai_compatible_embedding_model,
            deployment_document={
                "adapter_contract": "openai-compatible-embeddings-v1",
                "allowed_hosts": sorted(settings.intranet_openai_compatible_allowed_hosts),
                "approved_public_hosts": sorted(
                    settings.intranet_openai_compatible_approved_public_hosts
                ),
                "base_url": str(settings.intranet_openai_compatible_embedding_base_url),
                "secret_ref_identity": (
                    settings.intranet_openai_compatible_embedding_api_key_secret_ref
                ),
                "timeout_seconds": (settings.intranet_openai_compatible_embedding_timeout_seconds),
            },
        )
    return None


def resolve_reranker_runtime_binding(settings: Settings) -> InferenceRuntimeBinding | None:
    if settings.local_llama_cpp_reranker_enabled:
        if (
            settings.local_llama_cpp_reranker_base_url is None
            or settings.local_llama_cpp_reranker_model is None
        ):
            raise ConflictError("The local reranker runtime binding is incomplete.")
        return _binding(
            stage=InferenceStage.RERANKER,
            profile_id=settings.chat_reranker_provider_profile_version_id,
            server_route_key=LOCAL_RERANKER_ROUTE_KEY,
            provider_identity="llama-cpp-reranker",
            model_identity=settings.local_llama_cpp_reranker_model,
            deployment_document={
                "adapter_contract": "rerank-v1",
                "base_url": str(settings.local_llama_cpp_reranker_base_url),
                "timeout_seconds": settings.local_llama_cpp_reranker_timeout_seconds,
                "top_n": settings.local_llama_cpp_reranker_top_n,
            },
        )
    if settings.intranet_reranker_enabled:
        if (
            settings.intranet_reranker_base_url is None
            or settings.intranet_reranker_model is None
            or settings.intranet_reranker_api_key_secret_ref is None
        ):
            raise ConflictError("The intranet reranker runtime binding is incomplete.")
        return _binding(
            stage=InferenceStage.RERANKER,
            profile_id=settings.chat_reranker_provider_profile_version_id,
            server_route_key=INTRANET_RERANKER_ROUTE_KEY,
            provider_identity="intranet-rerank-v1",
            model_identity=settings.intranet_reranker_model,
            deployment_document={
                "adapter_contract": "rerank-v1",
                "allowed_hosts": sorted(settings.intranet_openai_compatible_allowed_hosts),
                "approved_public_hosts": sorted(
                    settings.intranet_openai_compatible_approved_public_hosts
                ),
                "base_url": str(settings.intranet_reranker_base_url),
                "secret_ref_identity": settings.intranet_reranker_api_key_secret_ref,
                "timeout_seconds": settings.intranet_reranker_timeout_seconds,
                "top_n": settings.intranet_reranker_top_n,
            },
        )
    return None


def resolve_interactive_runtime_bindings(
    settings: Settings,
) -> tuple[InferenceRuntimeBinding, ...]:
    return tuple(
        binding
        for binding in (
            resolve_composition_runtime_binding(settings),
            resolve_embedding_runtime_binding(settings),
            resolve_reranker_runtime_binding(settings),
        )
        if binding is not None
    )


def _binding(
    *,
    stage: InferenceStage,
    profile_id: UUID | None,
    server_route_key: str,
    provider_identity: str,
    model_identity: str,
    deployment_document: dict[str, object],
) -> InferenceRuntimeBinding:
    deployment_hash = canonical_json_hash(
        {
            "contract": "DATARIVER_INTERACTIVE_INFERENCE_DEPLOYMENT_V1",
            "stage": stage.value,
            "server_route_key": server_route_key,
            "provider_identity": provider_identity,
            "model_identity": model_identity,
            **deployment_document,
        }
    )
    return InferenceRuntimeBinding(
        stage=stage,
        provider_profile_version_id=profile_id,
        server_route_key=server_route_key,
        provider_identity=provider_identity,
        model_identity=model_identity,
        deployment_identity=f"sha256:{deployment_hash}",
    )
