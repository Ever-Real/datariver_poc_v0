from __future__ import annotations

from collections.abc import Mapping

_NO_SECRETS: Mapping[str, str] = {}

CANONICAL_SYSTEM_SECRET_REFERENCES: Mapping[str, Mapping[str, str]] = {
    "DATAHUB_GMS": {"token": "file:/run/secrets/datahub_token"},
    "DATAHUB": {"token": "file:/run/secrets/datahub_token"},
    "DATAHUB_FRONTEND": _NO_SECRETS,
    "AIRFLOW": _NO_SECRETS,
    "REDIS_CACHE": {"password": "file:/run/secrets/redis_cache_password"},
    "REDIS_DELIVERY": {"password": "file:/run/secrets/redis_delivery_password"},
    "S3_STORAGE": {
        "access_key": "file:/run/secrets/s3_access_key",
        "secret_key": "file:/run/secrets/s3_secret_key",
    },
    "LLM_RERANKER": _NO_SECRETS,
    "NEO4J": {"credential": "file:/run/secrets/neo4j_auth"},
    "PROMETHEUS": _NO_SECRETS,
    "GRAFANA_DASHBOARD": _NO_SECRETS,
}

_INTRANET_LLM_SECRET_REFERENCES: Mapping[str, Mapping[str, str]] = {
    "LLM_CHAT_MODEL": {
        "api_key": "file:/run/secrets/intranet_llm_chat_api_key",
    },
    "LLM_EMBEDDING": {
        "api_key": "file:/run/secrets/intranet_llm_embedding_api_key",
    },
}


def canonical_secret_references(
    system_id: str,
    *,
    connection_mode: object = None,
) -> Mapping[str, str]:
    if system_id in _INTRANET_LLM_SECRET_REFERENCES:
        if connection_mode == "INTRANET_OPENAI_COMPATIBLE":
            return _INTRANET_LLM_SECRET_REFERENCES[system_id]
        return _NO_SECRETS
    try:
        return CANONICAL_SYSTEM_SECRET_REFERENCES[system_id]
    except KeyError as error:
        raise ValueError("The system configuration secret contract is undefined.") from error


def require_canonical_secret_references(
    system_id: str,
    references: Mapping[str, str],
    *,
    connection_mode: object = None,
) -> None:
    expected = canonical_secret_references(system_id, connection_mode=connection_mode)
    if dict(references) != dict(expected):
        raise ValueError(
            "Every connector secret slot must use its canonical operator-managed secret target."
        )
