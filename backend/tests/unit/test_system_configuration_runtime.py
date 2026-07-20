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


def test_activated_yaml_hash_is_revalidated_before_process_configuration() -> None:
    yaml_document = "base_url: http://datahub-gms:8080\noptions: {}\n"
    parsed = {"base_url": "http://datahub-gms:8080", "options": {}}

    assert _document(yaml_document, canonical_json_hash(parsed)) == parsed

    with pytest.raises(ValueError, match="hash evidence"):
        _document(yaml_document, "0" * 64)
