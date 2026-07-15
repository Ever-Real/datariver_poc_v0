from __future__ import annotations

from dataclasses import dataclass

from datariver.config import Settings
from datariver.infrastructure.cache.valkey import ValkeyEventDelivery
from datariver.infrastructure.datahub.http import HttpDataHubGateway
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.object_store.s3 import S3ObjectStore
from datariver.infrastructure.secrets import SecretResolver


@dataclass(slots=True)
class RelayWorkerContainer:
    database: Database
    event_delivery: ValkeyEventDelivery

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


def _database(settings: Settings, *, role: str) -> Database:
    resolver = SecretResolver()
    url = getattr(settings, f"{role}_database_url")
    secret_ref = getattr(settings, f"{role}_database_secret_ref")
    return Database(
        url,
        password=resolver.resolve(secret_ref),
        pool_size=settings.worker_database_pool_size,
        max_overflow=settings.worker_database_pool_max_overflow,
        pool_timeout_seconds=settings.worker_database_pool_timeout_seconds,
        application_name=f"datariver-next-{role}",
    )


def _delivery(settings: Settings, resolver: SecretResolver) -> ValkeyEventDelivery:
    return ValkeyEventDelivery(
        settings.valkey_queue_url,
        password=resolver.resolve(settings.valkey_queue_secret_ref),
    )


def build_relay_container(settings: Settings) -> RelayWorkerContainer:
    resolver = SecretResolver()
    return RelayWorkerContainer(
        database=_database(settings, role="relay"),
        event_delivery=_delivery(settings, resolver),
    )


def build_upload_container(settings: Settings) -> UploadWorkerContainer:
    resolver = SecretResolver()
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
    resolver = SecretResolver()
    return GovernanceWorkerContainer(
        database=_database(settings, role="governance"),
        event_delivery=_delivery(settings, resolver),
        datahub=HttpDataHubGateway(
            base_url=settings.datahub_base_url,
            token=resolver.resolve(settings.datahub_secret_ref),
            timeout_seconds=settings.datahub_timeout_seconds,
            maximum_concurrency=settings.datahub_max_concurrency,
            queue_timeout_seconds=settings.datahub_queue_timeout_seconds,
            circuit_failure_threshold=settings.datahub_circuit_failure_threshold,
            circuit_open_seconds=settings.datahub_circuit_open_seconds,
        ),
    )
