from __future__ import annotations

from dataclasses import dataclass

from datariver.application.knowledge_pipeline_ports import KnowledgeRuntimeBindings
from datariver.config import Settings
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.infrastructure.knowledge.openai_compatible import (
    HttpxOpenAIJsonTransport,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleKnowledgeAnswerComposer,
    OpenAICompatibleTypedKnowledgeExtractor,
)
from datariver.infrastructure.secrets import SecretResolver

LOCAL_OLLAMA_PROVIDER = "ollama-openai-compatible"
INTRANET_OPENAI_COMPATIBLE_PROVIDER = "intranet-openai-compatible"
EXTRACTION_PROMPT_VERSION = "knowledge-pdf-extraction-v1"
EXTRACTION_SCHEMA_VERSION = "knowledge-extraction-schema-v1"
GRAPHRAG_PROMPT_VERSION = "knowledge-graphrag-v1"
GRAPHRAG_SCHEMA_VERSION = "knowledge-graphrag-schema-v1"
EMBEDDING_ADAPTER_CONTRACT = "openai-compatible-embeddings-v1"
CHAT_JSON_SCHEMA_ADAPTER_CONTRACT = "openai-compatible-chat-json-schema-v1"


@dataclass(frozen=True, slots=True)
class KnowledgeRuntimeAdapters:
    embedding: OpenAICompatibleEmbeddingProvider
    extractor: OpenAICompatibleTypedKnowledgeExtractor
    composer: OpenAICompatibleKnowledgeAnswerComposer
    bindings: KnowledgeRuntimeBindings


@dataclass(frozen=True, slots=True)
class _RuntimeCoordinates:
    provider: str
    allowed_hosts: frozenset[str]
    chat_base_url: str
    chat_model: str
    chat_api_key_secret_ref: str | None
    chat_timeout_seconds: float
    embedding_base_url: str
    embedding_model: str
    embedding_api_key_secret_ref: str | None
    embedding_timeout_seconds: float
    connection_mode: str


def resolve_knowledge_runtime_bindings(settings: Settings) -> KnowledgeRuntimeBindings:
    coordinates = _coordinates(settings)
    embedding_deployment_hash = _deployment_hash(
        coordinates=coordinates,
        system_id="LLM_EMBEDDING",
        adapter_contract=EMBEDDING_ADAPTER_CONTRACT,
        model=coordinates.embedding_model,
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
    )
    chat_deployment_hash = _deployment_hash(
        coordinates=coordinates,
        system_id="LLM_CHAT_MODEL",
        adapter_contract=CHAT_JSON_SCHEMA_ADAPTER_CONTRACT,
        model=coordinates.chat_model,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        tool_schema_version=EXTRACTION_SCHEMA_VERSION,
    )
    return KnowledgeRuntimeBindings(
        embedding=_activated_binding(
            settings=settings,
            system_id="LLM_EMBEDDING",
            provider=coordinates.provider,
            model=coordinates.embedding_model,
            prompt_version="embedding-v1",
            tool_schema_version="openai-embeddings-v1",
            adapter_contract=EMBEDDING_ADAPTER_CONTRACT,
            deployment_configuration_hash=embedding_deployment_hash,
        ),
        extraction=_activated_binding(
            settings=settings,
            system_id="LLM_CHAT_MODEL",
            provider=coordinates.provider,
            model=coordinates.chat_model,
            prompt_version=EXTRACTION_PROMPT_VERSION,
            tool_schema_version=EXTRACTION_SCHEMA_VERSION,
            adapter_contract=CHAT_JSON_SCHEMA_ADAPTER_CONTRACT,
            deployment_configuration_hash=chat_deployment_hash,
        ),
        graphrag=_activated_binding(
            settings=settings,
            system_id="LLM_CHAT_MODEL",
            provider=coordinates.provider,
            model=coordinates.chat_model,
            prompt_version=GRAPHRAG_PROMPT_VERSION,
            tool_schema_version=GRAPHRAG_SCHEMA_VERSION,
            adapter_contract=CHAT_JSON_SCHEMA_ADAPTER_CONTRACT,
            deployment_configuration_hash=_deployment_hash(
                coordinates=coordinates,
                system_id="LLM_CHAT_MODEL",
                adapter_contract=CHAT_JSON_SCHEMA_ADAPTER_CONTRACT,
                model=coordinates.chat_model,
                prompt_version=GRAPHRAG_PROMPT_VERSION,
                tool_schema_version=GRAPHRAG_SCHEMA_VERSION,
            ),
        ),
    )


def build_knowledge_runtime_adapters(settings: Settings) -> KnowledgeRuntimeAdapters:
    coordinates = _coordinates(settings)
    bindings = resolve_knowledge_runtime_bindings(settings)
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    chat_api_key = (
        resolver.resolve(coordinates.chat_api_key_secret_ref)
        if coordinates.chat_api_key_secret_ref is not None
        else None
    )
    embedding_api_key = (
        resolver.resolve(coordinates.embedding_api_key_secret_ref)
        if coordinates.embedding_api_key_secret_ref is not None
        else None
    )
    embedding_transport = HttpxOpenAIJsonTransport(
        base_url=coordinates.embedding_base_url,
        allowed_hosts=coordinates.allowed_hosts,
        api_key=embedding_api_key,
        timeout_seconds=coordinates.embedding_timeout_seconds,
    )
    chat_transport = HttpxOpenAIJsonTransport(
        base_url=coordinates.chat_base_url,
        allowed_hosts=coordinates.allowed_hosts,
        api_key=chat_api_key,
        timeout_seconds=coordinates.chat_timeout_seconds,
    )
    return KnowledgeRuntimeAdapters(
        embedding=OpenAICompatibleEmbeddingProvider(transport=embedding_transport),
        extractor=OpenAICompatibleTypedKnowledgeExtractor(transport=chat_transport),
        composer=OpenAICompatibleKnowledgeAnswerComposer(transport=chat_transport),
        bindings=bindings,
    )


def _coordinates(settings: Settings) -> _RuntimeCoordinates:
    if settings.local_ollama_chat_enabled and settings.local_ollama_embedding_enabled:
        if (
            settings.local_ollama_chat_base_url is None
            or settings.local_ollama_chat_model is None
            or settings.local_ollama_embedding_base_url is None
            or settings.local_ollama_embedding_model is None
        ):
            raise ConflictError("The activated local Knowledge model bindings are incomplete.")
        return _RuntimeCoordinates(
            provider=LOCAL_OLLAMA_PROVIDER,
            allowed_hosts=frozenset(
                {"host.docker.internal", "127.0.0.1"}
                if settings.local_inference_source_host_enabled
                else {"host.docker.internal"}
            ),
            chat_base_url=str(settings.local_ollama_chat_base_url),
            chat_model=settings.local_ollama_chat_model,
            chat_api_key_secret_ref=None,
            chat_timeout_seconds=settings.local_ollama_chat_timeout_seconds,
            embedding_base_url=str(settings.local_ollama_embedding_base_url),
            embedding_model=settings.local_ollama_embedding_model,
            embedding_api_key_secret_ref=None,
            embedding_timeout_seconds=settings.local_ollama_embedding_timeout_seconds,
            connection_mode="LOCAL_OLLAMA",
        )
    if (
        settings.intranet_openai_compatible_chat_enabled
        and settings.intranet_openai_compatible_embedding_enabled
    ):
        if (
            settings.intranet_openai_compatible_chat_base_url is None
            or settings.intranet_openai_compatible_chat_model is None
            or settings.intranet_openai_compatible_chat_api_key_secret_ref is None
            or settings.intranet_openai_compatible_embedding_base_url is None
            or settings.intranet_openai_compatible_embedding_model is None
            or settings.intranet_openai_compatible_embedding_api_key_secret_ref is None
        ):
            raise ConflictError("The activated intranet Knowledge model bindings are incomplete.")
        return _RuntimeCoordinates(
            provider=INTRANET_OPENAI_COMPATIBLE_PROVIDER,
            allowed_hosts=frozenset(settings.intranet_openai_compatible_allowed_hosts),
            chat_base_url=str(settings.intranet_openai_compatible_chat_base_url),
            chat_model=settings.intranet_openai_compatible_chat_model,
            chat_api_key_secret_ref=(settings.intranet_openai_compatible_chat_api_key_secret_ref),
            chat_timeout_seconds=(settings.intranet_openai_compatible_chat_timeout_seconds),
            embedding_base_url=str(settings.intranet_openai_compatible_embedding_base_url),
            embedding_model=settings.intranet_openai_compatible_embedding_model,
            embedding_api_key_secret_ref=(
                settings.intranet_openai_compatible_embedding_api_key_secret_ref
            ),
            embedding_timeout_seconds=(
                settings.intranet_openai_compatible_embedding_timeout_seconds
            ),
            connection_mode="INTRANET_OPENAI_COMPATIBLE",
        )
    raise ConflictError("The activated Knowledge model bindings are incomplete.")


def _deployment_hash(
    *,
    coordinates: _RuntimeCoordinates,
    system_id: str,
    adapter_contract: str,
    model: str,
    prompt_version: str,
    tool_schema_version: str,
) -> str:
    is_embedding = system_id == "LLM_EMBEDDING"
    return canonical_json_hash(
        {
            "contract": "KNOWLEDGE_RUNTIME_DEPLOYMENT_BINDING_V1",
            "system_id": system_id,
            "connection_mode": coordinates.connection_mode,
            "adapter_contract": adapter_contract,
            "provider": coordinates.provider,
            "model": model,
            "prompt_version": prompt_version,
            "tool_schema_version": tool_schema_version,
            "base_url": (
                coordinates.embedding_base_url if is_embedding else coordinates.chat_base_url
            ),
            "allowed_hosts": sorted(coordinates.allowed_hosts),
            "secret_ref_identity": (
                coordinates.embedding_api_key_secret_ref
                if is_embedding
                else coordinates.chat_api_key_secret_ref
            ),
            "timeout_seconds": (
                coordinates.embedding_timeout_seconds
                if is_embedding
                else coordinates.chat_timeout_seconds
            ),
        }
    )


def _activated_binding(
    *,
    settings: Settings,
    system_id: str,
    provider: str,
    model: str,
    prompt_version: str,
    tool_schema_version: str,
    adapter_contract: str,
    deployment_configuration_hash: str,
) -> ModelBinding:
    version = settings.system_configuration_runtime_versions.get(system_id)
    configuration_hash = settings.system_configuration_runtime_hashes.get(system_id)
    if version is not None and configuration_hash is None:
        raise ConflictError(
            "The activated model configuration is missing its immutable revision hash."
        )
    return ModelBinding.activated(
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        tool_schema_version=tool_schema_version,
        configuration_version=version,
        configuration_hash=configuration_hash,
        adapter_contract=adapter_contract,
        deployment_configuration_hash=deployment_configuration_hash,
    )
