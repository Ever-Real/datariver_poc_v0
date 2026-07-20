from __future__ import annotations

from dataclasses import dataclass

from datariver.config import Settings
from datariver.infrastructure.cache.valkey import ValkeyCache
from datariver.infrastructure.datahub.http import HttpDataHubGateway
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.object_store.s3 import S3ObjectStore
from datariver.infrastructure.observability.metrics import HttpMetrics
from datariver.infrastructure.secrets import SecretResolver
from datariver.infrastructure.security.oidc import OidcTokenVerifier


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    database: Database
    cache: ValkeyCache
    datahub: HttpDataHubGateway
    oidc: OidcTokenVerifier
    object_store: S3ObjectStore
    metrics: HttpMetrics

    async def close(self) -> None:
        await self.datahub.close()
        await self.cache.close()
        await self.database.close()


def build_container(settings: Settings) -> AppContainer:
    secret_resolver = SecretResolver()
    database_password = secret_resolver.resolve(settings.database_secret_ref)
    datahub_token = secret_resolver.resolve(settings.datahub_secret_ref)
    cache_password = secret_resolver.resolve(settings.valkey_cache_secret_ref)
    s3_access_key = SecretResolver().resolve(f"file:{settings.s3_access_key_file}")
    s3_secret_key = SecretResolver().resolve(f"file:{settings.s3_secret_key_file}")
    metrics = HttpMetrics()
    return AppContainer(
        settings=settings,
        database=Database(
            settings.database_url,
            password=database_password,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_pool_max_overflow,
            pool_timeout_seconds=settings.database_pool_timeout_seconds,
        ),
        cache=ValkeyCache(
            settings.valkey_cache_url,
            password=cache_password,
            maximum_value_bytes=settings.cache_max_value_bytes,
        ),
        datahub=HttpDataHubGateway(
            base_url=settings.datahub_base_url,
            token=datahub_token,
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
            telemetry=metrics,
        ),
        oidc=OidcTokenVerifier(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_url=settings.oidc_jwks_url,
            allowed_algorithms=settings.oidc_allowed_algorithms,
            hardware_acr_values=settings.oidc_hardware_acr_values,
            hardware_amr_values=settings.oidc_hardware_amr_values,
            password_reauth_acr_values=settings.oidc_password_reauth_acr_values,
            password_amr_values=settings.oidc_password_amr_values,
        ),
        object_store=S3ObjectStore(
            endpoint_url=settings.s3_endpoint_url,
            public_endpoint_url=settings.s3_public_endpoint_url,
            region=settings.s3_region,
            access_key=s3_access_key,
            secret_key=s3_secret_key,
        ),
        metrics=metrics,
    )
