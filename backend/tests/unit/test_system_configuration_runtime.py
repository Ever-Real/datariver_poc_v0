from types import SimpleNamespace
from typing import cast

import pytest

from datariver.config import Settings
from datariver.domain.common import canonical_json_hash
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.infrastructure.db.models.platform import (
    ExternalServiceProfileModel,
    ExternalServiceProfileVersionModel,
)
from datariver.infrastructure.knowledge.runtime import (
    TBOX_SCHEMA_ASSISTANT_PROMPT_VERSION,
    TBOX_SCHEMA_ASSISTANT_SCHEMA_VERSION,
    resolve_knowledge_tbox_schema_binding,
)
from datariver.infrastructure.system_configuration_runtime import (
    _document,
    _knowledge_system_bindings,
    _runtime_updates,
    _settings_with_claim_activated_rows,
    validate_runtime_system_configuration,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u@localhost/db",
        database_secret_ref="file:/run/secrets/postgres_password",
        migration_database_url="postgresql+asyncpg://owner@localhost/db",
        migration_database_secret_ref="file:/run/secrets/postgres_owner_password",
        relay_database_url="postgresql+asyncpg://relay@localhost/db",
        relay_database_secret_ref="file:/run/secrets/postgres_relay_password",
        upload_database_url="postgresql+asyncpg://upload@localhost/db",
        upload_database_secret_ref="file:/run/secrets/postgres_upload_password",
        governance_database_url="postgresql+asyncpg://governance@localhost/db",
        governance_database_secret_ref="file:/run/secrets/postgres_governance_password",
        bootstrap_database_url="postgresql+asyncpg://bootstrap@localhost/db",
        bootstrap_database_secret_ref="file:/run/secrets/postgres_bootstrap_password",
        oidc_issuer="http://idp/realms/test",
        oidc_audience="datariver-api",
        oidc_jwks_url="http://idp/jwks",
        datahub_base_url="http://datahub",
        datahub_secret_ref="file:/run/secrets/datahub_token",
        datahub_expected_version="v1.6.0",
        redis_cache_url="redis://cache:6379/0",
        redis_delivery_url="redis://queue:6379/0",
        redis_cache_secret_ref="file:/run/secrets/redis_cache_password",
        redis_delivery_secret_ref="file:/run/secrets/redis_delivery_password",
        s3_endpoint_url="http://s3",
        s3_public_endpoint_url="http://localhost:8333",
        s3_bucket_quarantine="quarantine",
        s3_bucket_accepted="accepted",
        s3_access_key_file="/run/secrets/s3_access_key",
        s3_secret_key_file="/run/secrets/s3_secret_key",
        local_inference_allowed_hosts=("host.docker.internal",),
    )


def test_tbox_schema_binding_versions_kind_specific_typed_output() -> None:
    settings = _settings().model_copy(
        update={
            "local_ollama_chat_enabled": True,
            "local_ollama_chat_base_url": "http://host.docker.internal:11434/v1",
            "local_ollama_chat_model": "gemma4:latest",
        }
    )

    binding = resolve_knowledge_tbox_schema_binding(settings)
    legacy = ModelBinding(
        provider=binding.provider,
        model=binding.model,
        prompt_version="knowledge-tbox-schema-assistant-v1",
        tool_schema_version="knowledge-tbox-schema-proposal-v1",
        configuration_source=binding.configuration_source,
        configuration_version=binding.configuration_version,
        configuration_hash=binding.configuration_hash,
    )

    assert TBOX_SCHEMA_ASSISTANT_PROMPT_VERSION == "knowledge-tbox-schema-assistant-v2"
    assert TBOX_SCHEMA_ASSISTANT_SCHEMA_VERSION == "knowledge-tbox-schema-proposal-v2"
    assert binding.prompt_version == TBOX_SCHEMA_ASSISTANT_PROMPT_VERSION
    assert binding.tool_schema_version == TBOX_SCHEMA_ASSISTANT_SCHEMA_VERSION
    assert binding.to_document() != legacy.to_document()


def test_datahub_activation_maps_only_validated_runtime_and_secret_references() -> None:
    updates = _runtime_updates(
        "DATAHUB",
        {
            "base_url": "http://datahub-gms:8080",
            "secret_references": {"token": "file:/run/secrets/datahub_token"},
            "options": {
                "allowed_versions": [],
                "circuit_failure_threshold": 5,
                "circuit_open_seconds": 30,
                "expected_version": "v1.6.0",
                "maximum_concurrency": 20,
                "queue_timeout_seconds": 2,
                "stale_ttl_seconds": 900,
                "timeout_seconds": 10,
                "version_enforcement": "report",
                "version_probe_ttl_seconds": 300,
            },
        },
    )

    assert updates["datahub_base_url"] == "http://datahub-gms:8080"
    assert updates["datahub_secret_ref"] == "file:/run/secrets/datahub_token"
    assert updates["datahub_catalog_pit_verified"] is False
    assert "token" not in updates


def test_datahub_pit_activation_is_fail_closed_and_requires_evidence() -> None:
    current = _settings()
    legacy_options: dict[str, object] = {
        "allowed_versions": [],
        "circuit_failure_threshold": 5,
        "circuit_open_seconds": 30,
        "expected_version": "v1.6.0",
        "maximum_concurrency": 20,
        "queue_timeout_seconds": 2,
        "stale_ttl_seconds": 900,
        "timeout_seconds": 10,
        "version_enforcement": "report",
        "version_probe_ttl_seconds": 300,
    }
    legacy_document: dict[str, object] = {
        "base_url": "http://datahub-gms:8080",
        "secret_references": {"token": "file:/run/secrets/datahub_token"},
        "options": legacy_options,
    }

    legacy_updates = _runtime_updates("DATAHUB", legacy_document)
    assert legacy_updates["datahub_catalog_pit_verified"] is False

    with pytest.raises(ValueError, match="operator evidence reference"):
        validate_runtime_system_configuration(
            current,
            service_key="DATAHUB",
            document={
                **legacy_document,
                "options": {
                    **legacy_options,
                    "catalog_pit_verified": True,
                },
            },
        )

    validate_runtime_system_configuration(
        current,
        service_key="DATAHUB",
        document={
            **legacy_document,
            "options": {
                **legacy_options,
                "catalog_pit_verified": True,
                "catalog_pit_evidence_reference": "ops://datahub/pit/2026-07-23",
                "version_enforcement": "enforce",
            },
        },
    )

    with pytest.raises(ValueError, match="enforced provider version"):
        validate_runtime_system_configuration(
            current,
            service_key="DATAHUB",
            document={
                **legacy_document,
                "options": {
                    **legacy_options,
                    "catalog_pit_verified": True,
                    "catalog_pit_evidence_reference": "ops://datahub/pit/2026-07-23",
                    "version_enforcement": "report",
                },
            },
        )


def test_redis_activation_maps_cache_and_delivery_to_separate_settings() -> None:
    cache = _runtime_updates(
        "REDIS_CACHE",
        {
            "url": "rediss://redis-cache.example:6379/0",
            "secret_references": {"password": "file:/run/secrets/redis_cache_password"},
            "options": {},
        },
    )
    delivery = _runtime_updates(
        "REDIS_DELIVERY",
        {
            "url": "rediss://redis-delivery.example:6379/0",
            "secret_references": {"password": "file:/run/secrets/redis_delivery_password"},
            "options": {},
        },
    )

    assert cache == {
        "redis_cache_url": "rediss://redis-cache.example:6379/0",
        "redis_cache_secret_ref": "file:/run/secrets/redis_cache_password",
    }
    assert delivery == {
        "redis_delivery_url": "rediss://redis-delivery.example:6379/0",
        "redis_delivery_secret_ref": "file:/run/secrets/redis_delivery_password",
    }

    with pytest.raises(ValueError, match="canonical operator-managed secret"):
        _runtime_updates(
            "REDIS_CACHE",
            {
                "url": "rediss://redis-cache.example:6379/0",
                "secret_references": {
                    "password": "file:/run/secrets/keycloak_identity_admin_client_secret"
                },
                "options": {},
            },
        )


def test_local_ollama_activation_requires_openai_compatible_style_and_no_api_key() -> None:
    options: dict[str, object] = {
        "api_style": "openai_compatible",
        "context_tokens": 8192,
        "timeout_seconds": 60,
    }
    document: dict[str, object] = {
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "llama3.1:latest",
        "secret_references": {},
        "options": options,
    }

    updates = _runtime_updates("LLM_CHAT_MODEL", document)

    assert updates == {
        "local_ollama_chat_enabled": True,
        "local_ollama_chat_base_url": "http://host.docker.internal:11434/v1",
        "local_ollama_chat_model": "llama3.1:latest",
        "local_ollama_chat_timeout_seconds": 60,
        "local_ollama_chat_context_tokens": 8192,
        "intranet_openai_compatible_chat_enabled": False,
    }

    with pytest.raises(ValueError, match="OpenAI-compatible"):
        _runtime_updates(
            "LLM_CHAT_MODEL",
            {
                **document,
                "options": {**options, "api_style": "ollama_native"},
            },
        )
    with pytest.raises(ValueError, match="does not consume an API-key reference"):
        _runtime_updates(
            "LLM_CHAT_MODEL",
            {
                **document,
                "secret_references": {"api_key": "file:/run/secrets/ollama_api_key"},
            },
        )


def test_intranet_openai_compatible_activation_requires_a_file_api_key_reference() -> None:
    updates = _runtime_updates(
        "LLM_CHAT_MODEL",
        {
            "connection_mode": "INTRANET_OPENAI_COMPATIBLE",
            "base_url": "https://10.42.0.15/v1",
            "model": "gemma4:latest",
            "secret_references": {"api_key": "file:/run/secrets/intranet_llm_chat_api_key"},
            "options": {
                "api_style": "openai_compatible",
                "context_tokens": 8192,
                "timeout_seconds": 60,
            },
        },
    )

    assert updates == {
        "local_ollama_chat_enabled": False,
        "intranet_openai_compatible_chat_enabled": True,
        "intranet_openai_compatible_chat_base_url": "https://10.42.0.15/v1",
        "intranet_openai_compatible_chat_model": "gemma4:latest",
        "intranet_openai_compatible_chat_api_key_secret_ref": (
            "file:/run/secrets/intranet_llm_chat_api_key"
        ),
        "intranet_openai_compatible_chat_timeout_seconds": 60,
        "intranet_openai_compatible_chat_context_tokens": 8192,
    }


def test_activated_yaml_hash_is_revalidated_before_process_configuration() -> None:
    yaml_document = "base_url: http://datahub-gms:8080\noptions: {}\n"
    parsed = {"base_url": "http://datahub-gms:8080", "options": {}}

    assert _document(yaml_document, canonical_json_hash(parsed)) == parsed

    with pytest.raises(ValueError, match="hash evidence"):
        _document(yaml_document, "0" * 64)


def test_activation_preflight_uses_the_same_settings_contract_as_process_startup() -> None:
    current = _settings()
    invalid_local_ollama = {
        "base_url": "http://another-host:11434/v1",
        "model": "llama3.1:latest",
        "secret_references": {},
        "options": {
            "api_style": "openai_compatible",
            "context_tokens": 8192,
            "timeout_seconds": 60,
        },
    }

    with pytest.raises(ValueError, match="allowlisted host"):
        validate_runtime_system_configuration(
            current,
            service_key="LLM_CHAT_MODEL",
            document=invalid_local_ollama,
        )


def test_claim_configuration_rejects_mixed_sources_and_reconstructs_exact_pins() -> None:
    chat_document = {
        "connection_mode": "LOCAL_OLLAMA",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "claim-chat",
        "secret_references": {},
        "options": {
            "api_style": "openai_compatible",
            "context_tokens": 8192,
            "timeout_seconds": 60,
        },
    }
    embedding_document = {
        "connection_mode": "LOCAL_OLLAMA",
        "base_url": "http://host.docker.internal:11434/v1",
        "model": "claim-embedding",
        "secret_references": {},
        "options": {
            "api_style": "openai_compatible",
            "timeout_seconds": 60,
        },
    }
    chat_hash = canonical_json_hash(chat_document)
    embedding_hash = canonical_json_hash(embedding_document)
    system_chat = ModelBinding(
        provider="ollama",
        model="claim-chat",
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_source="SYSTEM_CONFIGURATION",
        configuration_version=1,
        configuration_hash=chat_hash,
    )
    system_embedding = ModelBinding(
        provider="ollama",
        model="claim-embedding",
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_source="SYSTEM_CONFIGURATION",
        configuration_version=1,
        configuration_hash=embedding_hash,
    )
    deployment_embedding = ModelBinding(
        provider="ollama",
        model="claim-embedding",
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_source="DEPLOYMENT",
        configuration_version=None,
        configuration_hash="d" * 64,
    )

    with pytest.raises(ValueError, match="cannot mix"):
        _knowledge_system_bindings(
            extraction_binding=system_chat,
            embedding_binding=deployment_embedding,
        )

    bindings = _knowledge_system_bindings(
        extraction_binding=system_chat,
        embedding_binding=system_embedding,
    )
    rows = (
        (
            cast(
                ExternalServiceProfileModel,
                SimpleNamespace(service_key="LLM_CHAT_MODEL"),
            ),
            cast(
                ExternalServiceProfileVersionModel,
                SimpleNamespace(
                    configuration_version=1,
                    configuration_hash=chat_hash,
                    configuration_yaml=(
                        "connection_mode: LOCAL_OLLAMA\n"
                        "base_url: http://host.docker.internal:11434/v1\n"
                        "model: claim-chat\n"
                        "secret_references: {}\n"
                        "options:\n"
                        "  api_style: openai_compatible\n"
                        "  context_tokens: 8192\n"
                        "  timeout_seconds: 60\n"
                    ),
                ),
            ),
        ),
        (
            cast(
                ExternalServiceProfileModel,
                SimpleNamespace(service_key="LLM_EMBEDDING"),
            ),
            cast(
                ExternalServiceProfileVersionModel,
                SimpleNamespace(
                    configuration_version=1,
                    configuration_hash=embedding_hash,
                    configuration_yaml=(
                        "connection_mode: LOCAL_OLLAMA\n"
                        "base_url: http://host.docker.internal:11434/v1\n"
                        "model: claim-embedding\n"
                        "secret_references: {}\n"
                        "options:\n"
                        "  api_style: openai_compatible\n"
                        "  timeout_seconds: 60\n"
                    ),
                ),
            ),
        ),
    )
    resolved = _settings_with_claim_activated_rows(
        _settings(),
        bindings=bindings,
        rows=rows,
    )

    assert resolved.local_ollama_chat_model == "claim-chat"
    assert resolved.local_ollama_embedding_model == "claim-embedding"
    assert resolved.system_configuration_runtime_versions == {
        "LLM_CHAT_MODEL": 1,
        "LLM_EMBEDDING": 1,
    }
    with pytest.raises(ValueError, match="drifted"):
        _settings_with_claim_activated_rows(
            _settings(),
            bindings={
                **bindings,
                "LLM_EMBEDDING": ModelBinding(
                    provider="ollama",
                    model="claim-embedding",
                    prompt_version="knowledge-v1",
                    tool_schema_version="knowledge-schema-v1",
                    configuration_source="SYSTEM_CONFIGURATION",
                    configuration_version=1,
                    configuration_hash="0" * 64,
                ),
            },
            rows=rows,
        )
