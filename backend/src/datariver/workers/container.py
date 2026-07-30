from __future__ import annotations

from dataclasses import dataclass

from datariver.config import Settings
from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.cache.redis import RedisEventDelivery
from datariver.infrastructure.datahub.http import HttpDataHubGateway
from datariver.infrastructure.datahub.profile_http import HttpDataHubProfileGateway
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.object_store.archive_s3 import S3ImmutableArchiveStore
from datariver.infrastructure.object_store.s3 import S3ObjectStore
from datariver.infrastructure.secrets import SecretResolver


@dataclass(slots=True)
class RelayWorkerContainer:
    database: Database
    event_delivery: RedisEventDelivery

    async def close(self) -> None:
        await self.event_delivery.close()
        await self.database.close()


@dataclass(slots=True)
class UploadWorkerContainer(RelayWorkerContainer):
    object_store: S3ObjectStore


@dataclass(slots=True)
class GovernanceWorkerContainer(RelayWorkerContainer):
    datahub: HttpDataHubGateway

    async def close(self) -> None:
        await self.datahub.close()
        await super().close()


@dataclass(slots=True)
class CatalogExportWorkerContainer(RelayWorkerContainer):
    object_store: S3ObjectStore


@dataclass(slots=True)
class KnowledgeSourceWorkerContainer(RelayWorkerContainer):
    object_store: S3ObjectStore


@dataclass(slots=True)
class RetentionSchedulerContainer:
    database: Database

    async def close(self) -> None:
        await self.database.close()


@dataclass(slots=True)
class RetentionArchiveContainer(RetentionSchedulerContainer):
    archive: S3ImmutableArchiveStore


@dataclass(slots=True)
class CatalogProfileCollectorContainer:
    database: Database
    datahub: HttpDataHubProfileGateway

    async def close(self) -> None:
        await self.datahub.close()
        await self.database.close()


@dataclass(slots=True)
class QualityWorkerContainer(RelayWorkerContainer):
    pass


def retention_archive_configuration_fingerprint(settings: Settings) -> str:
    return canonical_json_hash(
        {
            "contract": "S3_COMPLIANCE_ARCHIVE_V1",
            "endpoint_url": str(settings.s3_archive_endpoint_url or "").rstrip("/"),
            "region": settings.s3_archive_region,
            "bucket": settings.s3_archive_bucket,
            "prefix": str(settings.s3_archive_prefix or "").rstrip("/"),
            "encryption_profile_fingerprint": (settings.s3_archive_encryption_profile_fingerprint),
        }
    )


def _database(settings: Settings, *, role: str) -> Database:
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    url = getattr(settings, f"{role}_database_url")
    secret_ref = getattr(settings, f"{role}_database_secret_ref")
    if not isinstance(url, str) or not isinstance(secret_ref, str):
        raise RuntimeError(f"Database credentials for worker role {role} are not configured.")
    retention_role = role in {"retention_scheduler", "archive"}
    return Database(
        url,
        password=resolver.resolve(secret_ref),
        pool_size=(
            settings.retention_worker_database_pool_size
            if retention_role
            else settings.worker_database_pool_size
        ),
        max_overflow=(
            settings.retention_worker_database_pool_max_overflow
            if retention_role
            else settings.worker_database_pool_max_overflow
        ),
        pool_timeout_seconds=settings.worker_database_pool_timeout_seconds,
        application_name=f"datariver-next-{role}",
    )


def _delivery(settings: Settings, resolver: SecretResolver) -> RedisEventDelivery:
    return RedisEventDelivery(
        settings.redis_delivery_url,
        password=resolver.resolve(settings.redis_delivery_secret_ref),
    )


def build_relay_container(settings: Settings) -> RelayWorkerContainer:
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    return RelayWorkerContainer(
        database=_database(settings, role="relay"),
        event_delivery=_delivery(settings, resolver),
    )


def build_upload_container(settings: Settings) -> UploadWorkerContainer:
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    return UploadWorkerContainer(
        database=_database(settings, role="upload"),
        event_delivery=_delivery(settings, resolver),
        object_store=S3ObjectStore(
            endpoint_url=settings.s3_endpoint_url,
            public_endpoint_url=settings.s3_public_endpoint_url,
            region=settings.s3_region,
            access_key=resolver.resolve(f"file:{settings.s3_access_key_file}"),
            secret_key=resolver.resolve(f"file:{settings.s3_secret_key_file}"),
        ),
    )


def build_governance_container(settings: Settings) -> GovernanceWorkerContainer:
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    return GovernanceWorkerContainer(
        database=_database(settings, role="governance"),
        event_delivery=_delivery(settings, resolver),
        datahub=HttpDataHubGateway(
            base_url=settings.datahub_base_url,
            token=resolver.resolve(settings.datahub_secret_ref),
            timeout_seconds=settings.datahub_timeout_seconds,
            expected_version=settings.datahub_expected_version,
            allowed_versions=settings.datahub_allowed_versions,
            version_enforcement=settings.datahub_version_enforcement,
            development_version_bypass=settings.app_env == "development",
            version_probe_ttl_seconds=settings.datahub_version_probe_ttl_seconds,
            maximum_concurrency=settings.datahub_max_concurrency,
            queue_timeout_seconds=settings.datahub_queue_timeout_seconds,
            circuit_failure_threshold=settings.datahub_circuit_failure_threshold,
            circuit_open_seconds=settings.datahub_circuit_open_seconds,
            catalog_scan_snapshot_consistent=settings.datahub_catalog_pit_verified,
            catalog_scan_snapshot_evidence_reference=(
                settings.datahub_catalog_pit_evidence_reference
            ),
        ),
    )


def build_catalog_profile_collector_container(
    settings: Settings,
) -> CatalogProfileCollectorContainer:
    required = (
        settings.catalog_profile_database_url,
        settings.catalog_profile_database_secret_ref,
        settings.catalog_profile_datahub_secret_ref,
        settings.catalog_profile_subject_id,
        settings.catalog_profile_freshness_sla_seconds,
        settings.catalog_profile_provider_config_hash,
        settings.catalog_profile_provenance_key_id,
        settings.catalog_profile_provenance_key_secret_ref,
    )
    if not settings.catalog_profile_collector_enabled or any(value is None for value in required):
        raise RuntimeError(
            "Catalog Profile collector requires explicit enablement and dedicated credentials."
        )
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    database_url = settings.catalog_profile_database_url
    database_secret_ref = settings.catalog_profile_database_secret_ref
    datahub_secret_ref = settings.catalog_profile_datahub_secret_ref
    freshness_sla_seconds = settings.catalog_profile_freshness_sla_seconds
    provider_config_hash = settings.catalog_profile_provider_config_hash
    provenance_key_id = settings.catalog_profile_provenance_key_id
    provenance_key_secret_ref = settings.catalog_profile_provenance_key_secret_ref
    assert database_url is not None
    assert database_secret_ref is not None
    assert datahub_secret_ref is not None
    assert freshness_sla_seconds is not None
    assert provider_config_hash is not None
    assert provenance_key_id is not None
    assert provenance_key_secret_ref is not None
    return CatalogProfileCollectorContainer(
        database=Database(
            database_url,
            password=resolver.resolve(database_secret_ref),
            pool_size=1,
            max_overflow=0,
            pool_timeout_seconds=settings.worker_database_pool_timeout_seconds,
            application_name="datariver-next-catalog-profile",
        ),
        datahub=HttpDataHubProfileGateway(
            base_url=settings.datahub_base_url,
            token=resolver.resolve(datahub_secret_ref),
            timeout_seconds=settings.datahub_timeout_seconds,
            expected_version=settings.datahub_expected_version,
            allowed_versions=settings.datahub_allowed_versions,
            version_enforcement=settings.datahub_version_enforcement,
            development_version_bypass=False,
            version_probe_ttl_seconds=settings.datahub_version_probe_ttl_seconds,
            maximum_concurrency=1,
            queue_timeout_seconds=settings.datahub_queue_timeout_seconds,
            circuit_failure_threshold=settings.datahub_circuit_failure_threshold,
            circuit_open_seconds=settings.datahub_circuit_open_seconds,
            provider_config_hash=provider_config_hash,
            freshness_sla_seconds=freshness_sla_seconds,
            provenance_key_id=provenance_key_id,
            provenance_key=resolver.resolve(provenance_key_secret_ref).encode("utf-8"),
        ),
    )


def build_quality_container(settings: Settings) -> QualityWorkerContainer:
    required = (
        settings.quality_database_url,
        settings.quality_database_secret_ref,
        settings.quality_worker_subject_id,
        settings.quality_worker_workspace_id,
        settings.quality_source_manifest_file,
        settings.quality_worker_fingerprint,
    )
    if not settings.quality_worker_enabled or any(value is None for value in required):
        raise RuntimeError(
            "Quality worker requires explicit enablement, an exact manifest and dedicated identity."
        )
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    return QualityWorkerContainer(
        database=_database(settings, role="quality"),
        event_delivery=_delivery(settings, resolver),
    )


def build_catalog_export_container(settings: Settings) -> CatalogExportWorkerContainer:
    if (
        not settings.catalog_export_worker_enabled
        or settings.export_database_url is None
        or settings.export_database_secret_ref is None
        or settings.s3_export_access_key_file is None
        or settings.s3_export_secret_key_file is None
    ):
        raise RuntimeError(
            "Catalog export worker requires explicit enablement and separate DB/S3 credentials."
        )
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    return CatalogExportWorkerContainer(
        database=_database(settings, role="export"),
        event_delivery=_delivery(settings, resolver),
        object_store=S3ObjectStore(
            endpoint_url=settings.s3_endpoint_url,
            public_endpoint_url=settings.s3_public_endpoint_url,
            region=settings.s3_region,
            access_key=resolver.resolve(f"file:{settings.s3_export_access_key_file}"),
            secret_key=resolver.resolve(f"file:{settings.s3_export_secret_key_file}"),
        ),
    )


def build_knowledge_source_container(settings: Settings) -> KnowledgeSourceWorkerContainer:
    if (
        not settings.knowledge_source_worker_enabled
        or settings.knowledge_database_url is None
        or settings.knowledge_database_secret_ref is None
        or settings.s3_knowledge_access_key_file is None
        or settings.s3_knowledge_secret_key_file is None
    ):
        raise RuntimeError(
            "Knowledge source worker requires explicit enablement and separate DB/S3 credentials."
        )
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    return KnowledgeSourceWorkerContainer(
        database=_database(settings, role="knowledge"),
        event_delivery=_delivery(settings, resolver),
        object_store=S3ObjectStore(
            endpoint_url=settings.s3_endpoint_url,
            public_endpoint_url=settings.s3_public_endpoint_url,
            region=settings.s3_region,
            access_key=resolver.resolve(f"file:{settings.s3_knowledge_access_key_file}"),
            secret_key=resolver.resolve(f"file:{settings.s3_knowledge_secret_key_file}"),
        ),
    )


def build_retention_scheduler_container(settings: Settings) -> RetentionSchedulerContainer:
    if (
        not settings.retention_archive_execution_enabled
        or settings.retention_scheduler_database_url is None
        or settings.retention_scheduler_database_secret_ref is None
    ):
        raise RuntimeError(
            "Retention scheduler requires explicit archive-only enablement and credentials."
        )
    return RetentionSchedulerContainer(database=_database(settings, role="retention_scheduler"))


def build_retention_archive_container(settings: Settings) -> RetentionArchiveContainer:
    required = (
        settings.archive_database_url,
        settings.archive_database_secret_ref,
        settings.s3_archive_endpoint_url,
        settings.s3_archive_region,
        settings.s3_archive_bucket,
        settings.s3_archive_prefix,
        settings.s3_archive_access_key_file,
        settings.s3_archive_secret_key_file,
        settings.s3_archive_encryption_profile_fingerprint,
    )
    if not settings.retention_archive_execution_enabled or any(value is None for value in required):
        raise RuntimeError(
            "Retention archive executor requires explicit enablement and isolated DB/S3 settings."
        )
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    endpoint = settings.s3_archive_endpoint_url
    region = settings.s3_archive_region
    bucket = settings.s3_archive_bucket
    prefix = settings.s3_archive_prefix
    access_file = settings.s3_archive_access_key_file
    secret_file = settings.s3_archive_secret_key_file
    encryption_fingerprint = settings.s3_archive_encryption_profile_fingerprint
    assert isinstance(endpoint, str)
    assert isinstance(region, str)
    assert isinstance(bucket, str)
    assert isinstance(prefix, str)
    assert isinstance(access_file, str)
    assert isinstance(secret_file, str)
    assert isinstance(encryption_fingerprint, str)
    return RetentionArchiveContainer(
        database=_database(settings, role="archive"),
        archive=S3ImmutableArchiveStore(
            endpoint_url=endpoint,
            region=region,
            bucket=bucket,
            prefix=prefix,
            access_key=resolver.resolve(f"file:{access_file}"),
            secret_key=resolver.resolve(f"file:{secret_file}"),
            encryption_profile_fingerprint=encryption_fingerprint,
        ),
    )
