from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from sqlalchemy import func, select

from datariver.application.knowledge_source_job_contracts import KnowledgeSourceJobClaim
from datariver.config import Settings
from datariver.domain.common import canonical_json_hash
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.system_configuration import require_canonical_secret_references
from datariver.infrastructure.db.models.platform import (
    ExternalServiceProfileModel,
    ExternalServiceProfileVersionModel,
)
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.secrets import SecretResolver


def _mapping(document: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = document.get(key, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"Activated system configuration {key} must be a mapping.")
    return value


def _string(document: Mapping[str, Any], key: str, *, required: bool = True) -> str | None:
    value = document.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Activated system configuration requires {key}.")
    return value.strip()


def _secret_reference(document: Mapping[str, Any], key: str) -> str:
    reference = _string(_mapping(document, "secret_references"), key)
    assert reference is not None
    if not reference.startswith("file:/run/secrets/"):
        raise ValueError("Activated secret references must use file:/run/secrets/<name>.")
    return reference


def _document(configuration_yaml: str, expected_hash: str) -> dict[str, Any]:
    value = yaml.safe_load(configuration_yaml)
    if not isinstance(value, dict):
        raise ValueError("Activated system configuration is not one YAML mapping.")
    document = dict(value)
    if canonical_json_hash(document) != expected_hash:
        raise ValueError("Activated system configuration hash evidence does not match its YAML.")
    return document


def _runtime_updates(
    service_key: str,
    document: Mapping[str, Any],
) -> dict[str, object]:
    options = _mapping(document, "options")
    if service_key == "DATAHUB":
        require_canonical_secret_references(
            service_key,
            _mapping(document, "secret_references"),
        )
        return {
            "datahub_base_url": _string(document, "base_url"),
            "datahub_secret_ref": _secret_reference(document, "token"),
            "datahub_expected_version": _string(options, "expected_version"),
            "datahub_allowed_versions": tuple(options.get("allowed_versions", ())),
            "datahub_version_enforcement": options.get("version_enforcement"),
            "datahub_version_probe_ttl_seconds": options.get("version_probe_ttl_seconds"),
            "datahub_timeout_seconds": options.get("timeout_seconds"),
            "datahub_max_concurrency": options.get("maximum_concurrency"),
            "datahub_queue_timeout_seconds": options.get("queue_timeout_seconds"),
            "datahub_circuit_failure_threshold": options.get("circuit_failure_threshold"),
            "datahub_circuit_open_seconds": options.get("circuit_open_seconds"),
            "datahub_stale_ttl_seconds": options.get("stale_ttl_seconds"),
            # Existing activated DATAHUB profiles predate the PIT option.  They
            # must remain safe and loadable by defaulting to deletion-disabled.
            "datahub_catalog_pit_verified": options.get("catalog_pit_verified", False),
            "datahub_catalog_pit_evidence_reference": options.get("catalog_pit_evidence_reference"),
        }
    if service_key == "DATAHUB_FRONTEND":
        url = _string(document, "url")
        assert url is not None
        embed_enabled = options.get("embed_enabled", False)
        return {
            "ui_datahub_url": url,
            "datahub_embed_base_url": url if embed_enabled else None,
            "datahub_embed_enabled": embed_enabled,
        }
    if service_key == "AIRFLOW":
        return {"ui_airflow_url": _string(document, "base_url")}
    if service_key == "REDIS_CACHE":
        require_canonical_secret_references(
            service_key,
            _mapping(document, "secret_references"),
        )
        return {
            "redis_cache_url": _string(document, "url"),
            "redis_cache_secret_ref": _secret_reference(document, "password"),
        }
    if service_key == "REDIS_DELIVERY":
        require_canonical_secret_references(
            service_key,
            _mapping(document, "secret_references"),
        )
        return {
            "redis_delivery_url": _string(document, "url"),
            "redis_delivery_secret_ref": _secret_reference(document, "password"),
        }
    if service_key == "S3_STORAGE":
        require_canonical_secret_references(
            service_key,
            _mapping(document, "secret_references"),
        )
        buckets = _mapping(document, "buckets")
        access_key_reference = _secret_reference(document, "access_key")
        secret_key_reference = _secret_reference(document, "secret_key")
        return {
            "s3_endpoint_url": _string(document, "endpoint"),
            "s3_public_endpoint_url": _string(document, "public_endpoint"),
            "s3_region": _string(document, "region"),
            "s3_bucket_accepted": _string(buckets, "accepted"),
            "s3_bucket_exports": _string(buckets, "exports"),
            "s3_bucket_filefolder": _string(buckets, "filefolder", required=False),
            "s3_bucket_infoschema": _string(buckets, "infoschema", required=False),
            "s3_bucket_quarantine": _string(buckets, "quarantine"),
            "s3_access_key_file": access_key_reference.removeprefix("file:"),
            "s3_secret_key_file": secret_key_reference.removeprefix("file:"),
            "presigned_url_ttl_seconds": options.get("presigned_url_ttl_seconds"),
        }
    if service_key == "LLM_CHAT_MODEL":
        connection_mode = document.get("connection_mode", "LOCAL_OLLAMA")
        if not isinstance(connection_mode, str):
            raise ValueError("The LLM connection mode must be one string.")
        if options.get("api_style") != "openai_compatible":
            raise ValueError("The LLM adapter requires OpenAI-compatible API style.")
        if connection_mode == "LOCAL_OLLAMA":
            if _mapping(document, "secret_references"):
                raise ValueError(
                    "The current local Ollama adapter does not consume an API-key reference."
                )
            require_canonical_secret_references(
                service_key,
                _mapping(document, "secret_references"),
                connection_mode=connection_mode,
            )
            return {
                "local_ollama_chat_enabled": True,
                "local_ollama_chat_base_url": _string(document, "base_url"),
                "local_ollama_chat_model": _string(document, "model"),
                "local_ollama_chat_timeout_seconds": options.get("timeout_seconds"),
                "local_ollama_chat_context_tokens": options.get("context_tokens"),
                "intranet_openai_compatible_chat_enabled": False,
            }
        if connection_mode != "INTRANET_OPENAI_COMPATIBLE":
            raise ValueError("The LLM connection mode is not supported.")
        require_canonical_secret_references(
            service_key,
            _mapping(document, "secret_references"),
            connection_mode=connection_mode,
        )
        return {
            "local_ollama_chat_enabled": False,
            "intranet_openai_compatible_chat_enabled": True,
            "intranet_openai_compatible_chat_base_url": _string(document, "base_url"),
            "intranet_openai_compatible_chat_model": _string(document, "model"),
            "intranet_openai_compatible_chat_api_key_secret_ref": _secret_reference(
                document, "api_key"
            ),
            "intranet_openai_compatible_chat_timeout_seconds": options.get("timeout_seconds"),
            "intranet_openai_compatible_chat_context_tokens": options.get("context_tokens"),
        }
    if service_key == "LLM_EMBEDDING":
        connection_mode = document.get("connection_mode", "LOCAL_OLLAMA")
        if not isinstance(connection_mode, str):
            raise ValueError("The LLM connection mode must be one string.")
        if options.get("api_style") != "openai_compatible":
            raise ValueError("The embedding adapter requires OpenAI-compatible API style.")
        if connection_mode == "LOCAL_OLLAMA":
            if _mapping(document, "secret_references"):
                raise ValueError(
                    "The current local embedding adapter does not consume an API-key reference."
                )
            require_canonical_secret_references(
                service_key,
                _mapping(document, "secret_references"),
                connection_mode=connection_mode,
            )
            return {
                "local_ollama_embedding_enabled": True,
                "local_ollama_embedding_base_url": _string(document, "base_url"),
                "local_ollama_embedding_model": _string(document, "model"),
                "local_ollama_embedding_timeout_seconds": options.get("timeout_seconds"),
                "intranet_openai_compatible_embedding_enabled": False,
            }
        if connection_mode != "INTRANET_OPENAI_COMPATIBLE":
            raise ValueError("The LLM connection mode is not supported.")
        require_canonical_secret_references(
            service_key,
            _mapping(document, "secret_references"),
            connection_mode=connection_mode,
        )
        return {
            "local_ollama_embedding_enabled": False,
            "intranet_openai_compatible_embedding_enabled": True,
            "intranet_openai_compatible_embedding_base_url": _string(document, "base_url"),
            "intranet_openai_compatible_embedding_model": _string(document, "model"),
            "intranet_openai_compatible_embedding_api_key_secret_ref": _secret_reference(
                document, "api_key"
            ),
            "intranet_openai_compatible_embedding_timeout_seconds": options.get("timeout_seconds"),
        }
    if service_key == "NEO4J":
        require_canonical_secret_references(
            service_key,
            _mapping(document, "secret_references"),
        )
        return {
            "neo4j_projection_enabled": True,
            "neo4j_uri": _string(document, "uri"),
            "neo4j_database": _string(document, "database"),
            "neo4j_auth_secret_ref": _secret_reference(document, "credential"),
            "neo4j_connection_timeout_seconds": options.get("connection_timeout_seconds"),
            "neo4j_maximum_connection_pool_size": options.get("maximum_connection_pool_size"),
        }
    if service_key == "PROMETHEUS":
        return {"ui_prometheus_url": _string(document, "base_url")}
    if service_key == "GRAFANA_DASHBOARD":
        if options.get("embed_enabled", False):
            raise ValueError(
                "Grafana embedding remains deployment-governed and cannot be activated here."
            )
        url = _string(document, "url")
        assert url is not None
        dashboard_path = options.get("dashboard_path", "")
        if not isinstance(dashboard_path, str):
            raise ValueError("The Grafana dashboard path must be a string.")
        return {"ui_grafana_url": f"{url.rstrip('/')}/{dashboard_path.lstrip('/')}".rstrip("/")}
    raise ValueError(f"No runtime consumer is implemented for activated service {service_key}.")


def validate_runtime_system_configuration(
    settings: Settings,
    *,
    service_key: str,
    document: Mapping[str, Any],
) -> None:
    """Prove that one activated revision satisfies the process startup contract."""

    values = settings.model_dump()
    values.update(_runtime_updates(service_key, document))
    Settings.model_validate(values)


def _settings_with_activated_rows(
    settings: Settings,
    rows: Sequence[tuple[ExternalServiceProfileModel, ExternalServiceProfileVersionModel]],
) -> Settings:
    updates: dict[str, object] = {}
    versions: dict[str, int] = {}
    hashes: dict[str, str] = {}
    for profile, revision in rows:
        document = _document(revision.configuration_yaml, revision.configuration_hash)
        profile_updates = _runtime_updates(profile.service_key, document)
        overlap = set(updates) & set(profile_updates)
        if overlap:
            raise ValueError(
                "Activated system configurations overlap runtime settings: "
                + ", ".join(sorted(overlap))
            )
        updates.update(profile_updates)
        versions[profile.service_key] = revision.configuration_version
        hashes[profile.service_key] = revision.configuration_hash
    values = settings.model_dump()
    values.update(updates)
    if {"LLM_CHAT_MODEL", "LLM_EMBEDDING", "NEO4J"}.issubset(versions):
        values["knowledge_pipeline_enabled"] = True
    values["system_configuration_runtime_versions"] = versions
    values["system_configuration_runtime_hashes"] = hashes
    return Settings.model_validate(values)


def _knowledge_system_bindings(
    *,
    extraction_binding: ModelBinding,
    embedding_binding: ModelBinding,
) -> dict[str, ModelBinding]:
    bindings = {
        "LLM_CHAT_MODEL": extraction_binding,
        "LLM_EMBEDDING": embedding_binding,
    }
    system_bindings = {
        service_key: binding
        for service_key, binding in bindings.items()
        if binding.configuration_source == "SYSTEM_CONFIGURATION"
    }
    if system_bindings and len(system_bindings) != len(bindings):
        raise ValueError("Knowledge model bindings cannot mix deployment and system revisions.")
    return system_bindings


def _settings_with_claim_activated_rows(
    settings: Settings,
    *,
    bindings: Mapping[str, ModelBinding],
    rows: Sequence[tuple[ExternalServiceProfileModel, ExternalServiceProfileVersionModel]],
) -> Settings:
    if {profile.service_key for profile, _ in rows} != set(bindings):
        raise ValueError("A pinned Knowledge model configuration is unavailable.")
    for profile, revision in rows:
        binding = bindings[profile.service_key]
        if (
            binding.configuration_version != revision.configuration_version
            or binding.configuration_hash != revision.configuration_hash
        ):
            raise ValueError("A Knowledge model configuration drifted from its job pin.")
    return _settings_with_activated_rows(settings, rows)


async def resolve_activated_system_configuration(
    settings: Settings,
    *,
    database_role: Literal["api", "relay", "upload", "governance", "export", "knowledge"] = "api",
) -> Settings:
    """Load exact activated revisions once during API/worker startup.

    Each process performs this bounded RLS-scoped read with its existing least-privilege database
    principal; no bootstrap credential is mounted into a runtime process.
    """

    if not settings.system_configuration_runtime_activation_enabled:
        return settings
    workspace_id = settings.system_configuration_runtime_workspace_id
    if workspace_id is None:
        raise ValueError("Runtime system configuration has no Workspace identifier.")
    role_prefix = "" if database_role == "api" else f"{database_role}_"
    database_url = getattr(settings, f"{role_prefix}database_url")
    secret_reference = getattr(settings, f"{role_prefix}database_secret_ref")
    if not isinstance(database_url, str) or not isinstance(secret_reference, str):
        raise ValueError(f"Runtime configuration role {database_role} is not configured.")
    password = SecretResolver(
        virtual_secret_root=settings.system_configuration_secret_root
    ).resolve(secret_reference)
    database = Database(
        database_url,
        password=password,
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
    )
    try:
        async with database.session_factory() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=workspace_id,
                    subject_id=workspace_id,
                )
                result = await session.execute(
                    select(ExternalServiceProfileModel, ExternalServiceProfileVersionModel)
                    .join(
                        ExternalServiceProfileVersionModel,
                        (
                            ExternalServiceProfileVersionModel.workspace_id
                            == ExternalServiceProfileModel.workspace_id
                        )
                        & (
                            ExternalServiceProfileVersionModel.profile_id
                            == ExternalServiceProfileModel.id
                        )
                        & (
                            ExternalServiceProfileVersionModel.configuration_version
                            == ExternalServiceProfileModel.activated_version
                        ),
                    )
                    .where(
                        ExternalServiceProfileModel.workspace_id == workspace_id,
                        ExternalServiceProfileModel.active.is_(True),
                        ExternalServiceProfileVersionModel.test_status == "AVAILABLE",
                    )
                )
                rows = tuple((row[0], row[1]) for row in result.all())
    finally:
        await database.close()
    return _settings_with_activated_rows(settings, rows)


async def resolve_claim_activated_knowledge_configuration(
    settings: Settings,
    *,
    claim: KnowledgeSourceJobClaim,
) -> Settings:
    """Resolve only model revisions pinned to one live, fenced Knowledge claim."""

    system_bindings = _knowledge_system_bindings(
        extraction_binding=claim.pins.extraction_binding,
        embedding_binding=claim.pins.embedding_binding,
    )
    if not system_bindings:
        return settings
    if not isinstance(settings.knowledge_database_url, str) or not isinstance(
        settings.knowledge_database_secret_ref, str
    ):
        raise ValueError("The Knowledge worker database role is not configured.")
    password = SecretResolver(
        virtual_secret_root=settings.system_configuration_secret_root
    ).resolve(settings.knowledge_database_secret_ref)
    database = Database(
        settings.knowledge_database_url,
        password=password,
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
    )
    try:
        async with database.session_factory() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=claim.job.workspace_id,
                    subject_id=settings.knowledge_worker_subject_id,
                )
                await session.scalar(
                    select(
                        func.set_config(
                            "app.knowledge_source_job_id",
                            str(claim.job.job_id),
                            True,
                        )
                    )
                )
                await session.scalar(
                    select(
                        func.set_config(
                            "app.knowledge_source_lease_token",
                            claim.lease_token,
                            True,
                        )
                    )
                )
                result = await session.execute(
                    select(
                        ExternalServiceProfileModel,
                        ExternalServiceProfileVersionModel,
                    )
                    .join(
                        ExternalServiceProfileVersionModel,
                        (
                            ExternalServiceProfileVersionModel.workspace_id
                            == ExternalServiceProfileModel.workspace_id
                        )
                        & (
                            ExternalServiceProfileVersionModel.profile_id
                            == ExternalServiceProfileModel.id
                        )
                        & (
                            ExternalServiceProfileVersionModel.configuration_version
                            == ExternalServiceProfileModel.activated_version
                        ),
                    )
                    .where(
                        ExternalServiceProfileModel.workspace_id == claim.job.workspace_id,
                        ExternalServiceProfileModel.service_key.in_(tuple(system_bindings)),
                        ExternalServiceProfileModel.active.is_(True),
                        ExternalServiceProfileVersionModel.test_status == "AVAILABLE",
                    )
                )
                rows = tuple((row[0], row[1]) for row in result.all())
    finally:
        await database.close()
    return _settings_with_claim_activated_rows(
        settings,
        bindings=system_bindings,
        rows=rows,
    )
