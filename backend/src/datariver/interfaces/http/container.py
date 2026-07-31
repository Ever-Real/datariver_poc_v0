from __future__ import annotations

from dataclasses import dataclass

from datariver.application.ports import KnowledgeStudioSampleReader
from datariver.config import Settings
from datariver.infrastructure.cache.redis import RedisCache, RedisChatRequestBudgetGuard
from datariver.infrastructure.datahub.http import HttpDataHubGateway
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.identity.keycloak import KeycloakIdentityAdministration
from datariver.infrastructure.knowledge.neo4j import BoltNeo4jQueryExecutor
from datariver.infrastructure.knowledge_studio.postgres_source import (
    KnowledgeStudioSourceManifest,
    build_knowledge_studio_sample_reader,
    load_knowledge_studio_source_manifest,
)
from datariver.infrastructure.object_store.governance_document_attachments import (
    S3GovernanceDocumentAttachmentStore,
)
from datariver.infrastructure.object_store.s3 import S3ObjectStore
from datariver.infrastructure.observability.metrics import HttpMetrics
from datariver.infrastructure.secrets import SecretResolver
from datariver.infrastructure.security.oidc import OidcTokenVerifier


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    database: Database
    cache: RedisCache
    chat_budget: RedisChatRequestBudgetGuard
    datahub: HttpDataHubGateway
    oidc: OidcTokenVerifier
    object_store: S3ObjectStore
    metrics: HttpMetrics
    knowledge_neo4j: BoltNeo4jQueryExecutor | None = None
    governance_document_attachments: S3GovernanceDocumentAttachmentStore | None = None
    identity_admin: KeycloakIdentityAdministration | None = None
    knowledge_studio_samples: KnowledgeStudioSampleReader | None = None
    knowledge_studio_source_manifest: KnowledgeStudioSourceManifest | None = None

    async def close(self) -> None:
        await self.datahub.close()
        await self.cache.close()
        await self.chat_budget.close()
        await self.database.close()
        if self.knowledge_neo4j is not None:
            await self.knowledge_neo4j.close()
        if self.identity_admin is not None:
            await self.identity_admin.close()


def build_container(settings: Settings) -> AppContainer:
    secret_resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    database_password = secret_resolver.resolve(settings.database_secret_ref)
    datahub_token = secret_resolver.resolve(settings.datahub_secret_ref)
    cache_password = secret_resolver.resolve(settings.redis_cache_secret_ref)
    delivery_password = secret_resolver.resolve(settings.redis_delivery_secret_ref)
    s3_access_key = secret_resolver.resolve(f"file:{settings.s3_access_key_file}")
    s3_secret_key = secret_resolver.resolve(f"file:{settings.s3_secret_key_file}")
    metrics = HttpMetrics()
    knowledge_neo4j: BoltNeo4jQueryExecutor | None = None
    governance_document_attachments: S3GovernanceDocumentAttachmentStore | None = None
    identity_admin: KeycloakIdentityAdministration | None = None
    knowledge_studio_samples: KnowledgeStudioSampleReader | None = None
    knowledge_studio_source_manifest: KnowledgeStudioSourceManifest | None = None
    if settings.knowledge_studio_source_manifest_file is not None:
        knowledge_studio_source_manifest = load_knowledge_studio_source_manifest(
            settings.knowledge_studio_source_manifest_file
        )
        knowledge_studio_samples = build_knowledge_studio_sample_reader(
            manifest=knowledge_studio_source_manifest,
            secret_root=settings.knowledge_studio_source_secret_root,
        )
    if settings.neo4j_projection_enabled:
        if settings.neo4j_uri is None or settings.neo4j_auth_secret_ref is None:
            raise ValueError("Enabled Neo4j projection has incomplete settings.")
        credential = secret_resolver.resolve(settings.neo4j_auth_secret_ref).strip()
        username, separator, password = credential.partition("/")
        if not separator or not username or not password:
            raise ValueError("The Neo4j secret must use the username/password format.")
        knowledge_neo4j = BoltNeo4jQueryExecutor(
            uri=settings.neo4j_uri,
            username=username,
            password=password,
            database=settings.neo4j_database,
            connection_timeout_seconds=settings.neo4j_connection_timeout_seconds,
            maximum_connection_pool_size=settings.neo4j_maximum_connection_pool_size,
        )
    if settings.governance_document_worker_enabled:
        if (
            settings.s3_bucket_filefolder is None
            or settings.s3_governance_document_access_key_file is None
            or settings.s3_governance_document_secret_key_file is None
        ):
            raise ValueError("Enabled Governance Document storage has incomplete settings.")
        governance_document_attachments = S3GovernanceDocumentAttachmentStore(
            endpoint_url=settings.s3_endpoint_url,
            public_endpoint_url=settings.s3_public_endpoint_url,
            region=settings.s3_region,
            bucket=settings.s3_bucket_filefolder,
            access_key=secret_resolver.resolve(
                f"file:{settings.s3_governance_document_access_key_file}"
            ),
            secret_key=secret_resolver.resolve(
                f"file:{settings.s3_governance_document_secret_key_file}"
            ),
        )
    if settings.identity_admin_enabled:
        if (
            settings.identity_admin_base_url is None
            or settings.identity_admin_client_secret_ref is None
        ):
            raise ValueError("Enabled identity administration has incomplete settings.")
        identity_admin = KeycloakIdentityAdministration(
            base_url=str(settings.identity_admin_base_url),
            realm=settings.identity_admin_realm,
            client_id=settings.identity_admin_client_id,
            client_secret=secret_resolver.resolve(settings.identity_admin_client_secret_ref),
            timeout_seconds=settings.identity_admin_timeout_seconds,
        )
    return AppContainer(
        settings=settings,
        database=Database(
            settings.database_url,
            password=database_password,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_pool_max_overflow,
            pool_timeout_seconds=settings.database_pool_timeout_seconds,
        ),
        cache=RedisCache(
            settings.redis_cache_url,
            password=cache_password,
            maximum_value_bytes=settings.cache_max_value_bytes,
        ),
        chat_budget=RedisChatRequestBudgetGuard(
            settings.redis_delivery_url,
            password=delivery_password,
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
            catalog_scan_snapshot_consistent=settings.datahub_catalog_pit_verified,
            catalog_scan_snapshot_evidence_reference=(
                settings.datahub_catalog_pit_evidence_reference
            ),
            telemetry=metrics,
        ),
        oidc=OidcTokenVerifier(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_url=settings.oidc_jwks_url,
            allowed_algorithms=settings.oidc_allowed_algorithms,
            hardware_acr_values=settings.oidc_hardware_acr_values,
            hardware_amr_values=settings.oidc_hardware_amr_values,
            hardware_webauthn_enabled=settings.oidc_hardware_webauthn_enabled,
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
        knowledge_neo4j=knowledge_neo4j,
        governance_document_attachments=governance_document_attachments,
        identity_admin=identity_admin,
        knowledge_studio_samples=knowledge_studio_samples,
        knowledge_studio_source_manifest=knowledge_studio_source_manifest,
    )
