import pytest

from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.system_configuration_runtime import (
    _document,
    _runtime_updates,
)


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
    assert "token" not in updates


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
