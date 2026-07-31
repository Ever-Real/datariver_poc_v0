from __future__ import annotations

import asyncio
import hashlib
import json
import os
import runpy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from datariver.application.knowledge_source_job_contracts import (
    KnowledgeSourceJobClaim,
    KnowledgeSourceJobRecord,
)
from datariver.application.typed_upload_profiles import KNOWLEDGE_SOURCE_DOCUMENT_V1
from datariver.domain.authz import Action, Classification, SubjectAttributes
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.knowledge_pipeline import (
    KNOWLEDGE_SOURCE_MEDIA_TYPES,
    MAX_SOURCE_BYTES,
    EmbeddingBatch,
    ExtractedNodeDraft,
    ExtractionDraft,
    KnowledgeSourceAnalysis,
    ModelBinding,
    PageEmbedding,
    PdfPage,
)
from datariver.infrastructure.db.knowledge_source_jobs import (
    SqlKnowledgeSourceJobStore,
    SqlKnowledgeSourceJobWorkerStore,
    knowledge_requester_authorization_hash,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.secrets import SecretResolver

_OWNER_URL = "DATARIVER_KNOWLEDGE_SOURCE_TEST_OWNER_DATABASE_URL"
_OWNER_SECRET = "DATARIVER_KNOWLEDGE_SOURCE_TEST_OWNER_SECRET_REF"
_APP_URL = "DATARIVER_KNOWLEDGE_SOURCE_TEST_APP_DATABASE_URL"
_APP_SECRET = "DATARIVER_KNOWLEDGE_SOURCE_TEST_APP_SECRET_REF"
_WORKER_URL = "DATARIVER_KNOWLEDGE_SOURCE_TEST_WORKER_DATABASE_URL"
_WORKER_SECRET = "DATARIVER_KNOWLEDGE_SOURCE_TEST_WORKER_SECRET_REF"
_CONFIRM = "DATARIVER_KNOWLEDGE_SOURCE_TEST_CONFIRM_ISOLATED"
_ENABLED = (
    all(
        os.getenv(name)
        for name in (
            _OWNER_URL,
            _OWNER_SECRET,
            _APP_URL,
            _APP_SECRET,
            _WORKER_URL,
            _WORKER_SECRET,
        )
    )
    and os.getenv(_CONFIRM) == "1"
)
_WORKER_SUBJECT_ID = UUID("00000000-0000-7000-8000-000000000004")


def _engine(url_name: str, secret_name: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[url_name],
        connect_args={
            "password": SecretResolver().resolve(os.environ[secret_name]),
            "server_settings": {"application_name": f"datariver-knowledge-source-{uuid4().hex}"},
        },
    )


def _binding(model: str, marker: str) -> ModelBinding:
    return ModelBinding(
        provider="ollama",
        model=model,
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_source="DEPLOYMENT",
        configuration_version=None,
        configuration_hash=marker * 64,
    )


def _system_binding(model: str, marker: str) -> ModelBinding:
    return ModelBinding(
        provider="openai-compatible",
        model=model,
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_source="SYSTEM_CONFIGURATION",
        configuration_version=1,
        configuration_hash=marker * 64,
    )


def _subject(workspace_id: UUID, subject_id: UUID) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=subject_id,
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.INTERNAL,
        allowed_system_ids=frozenset(),
        allowed_domain_ids=frozenset(),
        allowed_actions=frozenset({Action.KG_EDIT, Action.KG_READ}),
        denied_actions=frozenset(),
    )


def _validation_summary(*, content_type: str, size_bytes: int, sha256: str) -> str:
    return json.dumps(
        {
            "content_profile": "KNOWLEDGE_SOURCE_DOCUMENT_V1",
            "content_type": content_type,
            "coverage": "FULL_SIGNATURE" if content_type == "application/pdf" else "FULL",
            "parser_version": KNOWLEDGE_SOURCE_DOCUMENT_V1.parser_version,
            "profile_configuration_hash": KNOWLEDGE_SOURCE_DOCUMENT_V1.configuration_hash,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "validator_version": KNOWLEDGE_SOURCE_DOCUMENT_V1.acceptance_validator_version,
        }
    )


async def _seed(owner: AsyncEngine) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    workspace_id, actor_id, other_actor_id, graph_id, ontology_id, upload_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    other_graph_id, other_ontology_id, other_upload_id, other_source_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC)
    source_hash = hashlib.sha256(b"%PDF-1.7\nphase5\n%%EOF").hexdigest()
    attributes = json.dumps(
        {
            "groups": ["data-stewards"],
            "allowed_actions": ["kg.edit", "kg.read"],
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [],
        }
    )
    ontology = json.dumps({"entity_types": ["Asset"], "edge_types": []})
    async with owner.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, created_at, updated_at, version)
                VALUES
                    (:workspace_id, :slug, 'Knowledge source test', 'ACTIVE',
                     '{}'::jsonb, :now, :now, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "slug": f"knowledge-source-{workspace_id.hex}",
                "now": now,
            },
        )
        for subject_id, label in ((actor_id, "Actor"), (other_actor_id, "Other actor")):
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.subjects
                        (id, issuer, external_subject, display_name, active, created_at, updated_at)
                    VALUES
                        (:subject_id, 'knowledge-source-test', :external_subject,
                         :label, true, :now, :now)
                    """
                ),
                {
                    "subject_id": subject_id,
                    "external_subject": str(subject_id),
                    "label": label,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.workspace_memberships
                        (workspace_id, subject_id, job_function, clearance, attributes,
                         active, access_expires_at, created_at, updated_at, version)
                    VALUES
                        (:workspace_id, :subject_id, 'DATA_STEWARD', 1,
                         CAST(:attributes AS jsonb), true, :expires_at, :now, :now, 1)
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "subject_id": subject_id,
                    "attributes": attributes,
                    "expires_at": now + timedelta(days=30),
                    "now": now,
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.graphs
                    (id, workspace_id, slug, name, graph_type, status,
                     active_release_id, classification, created_at, updated_at, version)
                VALUES
                    (:graph_id, :workspace_id, :slug, 'Source graph', 'DOMAIN',
                     'DRAFT', NULL, 1, :now, :now, 1)
                """
            ),
            {
                "graph_id": graph_id,
                "workspace_id": workspace_id,
                "slug": f"source-graph-{graph_id.hex}",
                "now": now,
            },
        )
        for index, service_key in enumerate(
            ("LLM_CHAT_MODEL", "LLM_EMBEDDING", "DATAHUB"),
            start=1,
        ):
            profile_id, profile_version_id = uuid4(), uuid4()
            await connection.execute(
                text(
                    """
                    INSERT INTO platform.external_service_profiles (
                        id, workspace_id, service_key, display_name, endpoint_url,
                        configuration_yaml, active, activated_version, updated_by,
                        created_at, updated_at, version
                    ) VALUES (
                        :id, :workspace_id, :service_key, :display_name,
                        'http://example.invalid', '', true, 1, :actor_id,
                        :now, :now, 1
                    )
                    """
                ),
                {
                    "id": profile_id,
                    "workspace_id": workspace_id,
                    "service_key": service_key,
                    "display_name": f"{service_key} test profile",
                    "actor_id": actor_id,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO platform.external_service_profile_versions (
                        id, workspace_id, profile_id, configuration_version,
                        configuration_hash, configuration_yaml, endpoint_url,
                        created_by, test_status, test_scope, test_latency_ms,
                        tested_at, tested_by, activated_at, activated_by,
                        created_at, updated_at
                    ) VALUES (
                        :id, :workspace_id, :profile_id, 1,
                        :configuration_hash, '', 'http://example.invalid',
                        :actor_id, 'AVAILABLE', 'HTTP_HEALTH', 1,
                        :now, :actor_id, :now, :actor_id, :now, :now
                    )
                    """
                ),
                {
                    "id": profile_version_id,
                    "workspace_id": workspace_id,
                    "profile_id": profile_id,
                    "configuration_hash": f"{index}" * 64,
                    "actor_id": actor_id,
                    "now": now,
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.ontology_versions
                    (id, workspace_id, graph_id, version, schema_document,
                     checksum, status, created_at, updated_at)
                VALUES
                    (:ontology_id, :workspace_id, :graph_id, '1',
                     CAST(:ontology AS jsonb), :checksum, 'ACTIVE', :now, :now)
                """
            ),
            {
                "ontology_id": ontology_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "ontology": ontology,
                "checksum": "c" * 64,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.object_manifests (
                    id, workspace_id, bucket, object_key, display_name,
                    multipart_upload_id, size_bytes, mime, sha256,
                    actual_size_bytes, actual_mime, actual_sha256,
                    processing_lease_until, processing_attempts, validation_attempts,
                    last_error_code, validation_summary, completion_parts, state,
                    content_profile, legacy_knowledge_source_eligible,
                    knowledge_source_graph_id, classification, owner_id, retention_until,
                    expires_at, created_at, updated_at, version
                ) VALUES (
                    :upload_id, :workspace_id, 'datariver-accepted', :object_key,
                    'source.pdf', NULL, 23, 'application/pdf', :source_hash,
                    23, 'application/pdf', :source_hash, NULL, 0, 1, NULL,
                    CAST(:validation_summary AS jsonb), '[]'::jsonb, 'ACCEPTED',
                    'KNOWLEDGE_SOURCE_DOCUMENT_V1', false, :graph_id,
                    1, :actor_id, NULL, NULL, :now, :now, 1
                )
                """
            ),
            {
                "upload_id": upload_id,
                "workspace_id": workspace_id,
                "object_key": f"knowledge/{workspace_id}/{upload_id}.pdf",
                "source_hash": source_hash,
                "validation_summary": _validation_summary(
                    content_type="application/pdf", size_bytes=23, sha256=source_hash
                ),
                "graph_id": graph_id,
                "actor_id": actor_id,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.graphs
                    (id, workspace_id, slug, name, graph_type, status,
                     active_release_id, classification, created_at, updated_at, version)
                VALUES
                    (:graph_id, :workspace_id, :slug, 'Restricted source graph',
                     'DOMAIN', 'DRAFT', NULL, 3, :now, :now, 1)
                """
            ),
            {
                "graph_id": other_graph_id,
                "workspace_id": workspace_id,
                "slug": f"restricted-source-graph-{other_graph_id.hex}",
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.ontology_versions
                    (id, workspace_id, graph_id, version, schema_document,
                     checksum, status, created_at, updated_at)
                VALUES
                    (:ontology_id, :workspace_id, :graph_id, '1',
                     CAST(:ontology AS jsonb), :checksum, 'ACTIVE', :now, :now)
                """
            ),
            {
                "ontology_id": other_ontology_id,
                "workspace_id": workspace_id,
                "graph_id": other_graph_id,
                "ontology": ontology,
                "checksum": "e" * 64,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.object_manifests (
                    id, workspace_id, bucket, object_key, display_name,
                    multipart_upload_id, size_bytes, mime, sha256,
                    actual_size_bytes, actual_mime, actual_sha256,
                    processing_lease_until, processing_attempts, validation_attempts,
                    last_error_code, validation_summary, completion_parts, state,
                    content_profile, legacy_knowledge_source_eligible,
                    knowledge_source_graph_id, classification, owner_id, retention_until,
                    expires_at, created_at, updated_at, version
                ) VALUES (
                    :upload_id, :workspace_id, 'datariver-accepted', :object_key,
                    'restricted.pdf', NULL, 23, 'application/pdf', :source_hash,
                    23, 'application/pdf', :source_hash, NULL, 0, 1, NULL,
                    CAST(:validation_summary AS jsonb), '[]'::jsonb, 'ACCEPTED',
                    'KNOWLEDGE_SOURCE_DOCUMENT_V1', false, :graph_id,
                    3, :actor_id, NULL, NULL, :now, :now, 1
                )
                """
            ),
            {
                "upload_id": other_upload_id,
                "workspace_id": workspace_id,
                "object_key": f"accepted/{workspace_id}/{other_upload_id}.pdf",
                "source_hash": source_hash,
                "validation_summary": _validation_summary(
                    content_type="application/pdf", size_bytes=23, sha256=source_hash
                ),
                "graph_id": other_graph_id,
                "actor_id": other_actor_id,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.source_snapshots (
                    id, workspace_id, graph_id, upload_id, bucket, object_key,
                    storage_version, media_type, byte_size, content_sha256,
                    classification, state, created_by, created_at, updated_at
                ) VALUES (
                    :source_id, :workspace_id, :graph_id, :upload_id,
                    'datariver-accepted', :object_key, 'manifest-v1',
                    'application/pdf', 23, :source_hash, 3, 'PENDING',
                    :actor_id, :now, :now
                )
                """
            ),
            {
                "source_id": other_source_id,
                "workspace_id": workspace_id,
                "graph_id": other_graph_id,
                "upload_id": other_upload_id,
                "object_key": f"accepted/{workspace_id}/{other_upload_id}.pdf",
                "source_hash": source_hash,
                "actor_id": other_actor_id,
                "now": now,
            },
        )
    return workspace_id, actor_id, other_actor_id, graph_id, upload_id


async def _enqueue(
    app: AsyncEngine,
    *,
    workspace_id: UUID,
    actor_id: UUID,
    graph_id: UUID,
    upload_id: UUID,
    embedding: ModelBinding,
    extraction: ModelBinding,
    title: str = "Durable source proposal",
    request_hash: str = "d" * 64,
    idempotency_key: str | None = None,
) -> KnowledgeSourceJobRecord:
    sessions = async_sessionmaker(app, expire_on_commit=False)
    subject = _subject(workspace_id, actor_id)
    async with sessions() as session:
        return await SqlKnowledgeSourceJobStore(session).enqueue(
            workspace_id=workspace_id,
            graph_id=graph_id,
            upload_id=upload_id,
            actor_id=actor_id,
            title=title,
            request_hash=request_hash,
            requester_authorization_hash=knowledge_requester_authorization_hash(subject),
            embedding_binding=embedding,
            extraction_binding=extraction,
            maximum_attempts=3,
            idempotency_key=idempotency_key or f"source-analysis-{upload_id}",
        )


async def _add_upload(
    owner: AsyncEngine,
    *,
    workspace_id: UUID,
    actor_id: UUID,
    graph_id: UUID,
    display_name: str = "source.pdf",
    media_type: str = "application/pdf",
    content: bytes | None = None,
) -> UUID:
    upload_id = uuid4()
    now = datetime.now(UTC)
    source_content = content if content is not None else f"%PDF-1.7\n{upload_id}\n%%EOF".encode()
    source_hash = hashlib.sha256(source_content).hexdigest()
    async with owner.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO integration.object_manifests (
                    id, workspace_id, bucket, object_key, display_name,
                    multipart_upload_id, size_bytes, mime, sha256,
                    actual_size_bytes, actual_mime, actual_sha256,
                    processing_lease_until, processing_attempts, validation_attempts,
                    last_error_code, validation_summary, completion_parts, state,
                    content_profile, legacy_knowledge_source_eligible,
                    knowledge_source_graph_id, classification, owner_id, retention_until,
                    expires_at, created_at, updated_at, version
                ) VALUES (
                    :upload_id, :workspace_id, 'datariver-accepted', :object_key,
                    :display_name, NULL, :size_bytes, :media_type, :source_hash,
                    :size_bytes, :media_type, :source_hash, NULL, 0, 1, NULL,
                    CAST(:validation_summary AS jsonb), '[]'::jsonb, 'ACCEPTED',
                    'KNOWLEDGE_SOURCE_DOCUMENT_V1', false, :graph_id,
                    1, :actor_id, NULL, NULL, :now, :now, 1
                )
                """
            ),
            {
                "upload_id": upload_id,
                "workspace_id": workspace_id,
                "object_key": f"knowledge/{workspace_id}/{upload_id}",
                "display_name": display_name,
                "size_bytes": len(source_content),
                "media_type": media_type,
                "source_hash": source_hash,
                "validation_summary": _validation_summary(
                    content_type=media_type,
                    size_bytes=len(source_content),
                    sha256=source_hash,
                ),
                "graph_id": graph_id,
                "actor_id": actor_id,
                "now": now,
            },
        )
    return upload_id


async def _add_migration_owned_legacy_upload(
    owner: AsyncEngine,
    *,
    workspace_id: UUID,
    actor_id: UUID,
) -> UUID:
    upload_id = uuid4()
    now = datetime.now(UTC)
    source_content = f"%PDF-1.7\nlegacy-{upload_id}\n%%EOF".encode()
    source_hash = hashlib.sha256(source_content).hexdigest()
    validation_summary = json.dumps(
        {
            "content_type": "application/pdf",
            "coverage": "FULL_SIGNATURE",
            "sha256": source_hash,
            "size_bytes": len(source_content),
            "validator_version": "integrity-format-v1",
        }
    )
    async with owner.begin() as connection:
        # This fixture represents an exact row marked by the 0085 migration.
        # Product principals cannot create or mutate the marker because its
        # trigger remains enabled outside this isolated owner transaction.
        await connection.execute(
            text(
                "ALTER TABLE integration.object_manifests DISABLE TRIGGER "
                "trg_object_manifest_legacy_knowledge_source_marker"
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.object_manifests (
                    id, workspace_id, bucket, object_key, display_name,
                    multipart_upload_id, size_bytes, mime, sha256,
                    actual_size_bytes, actual_mime, actual_sha256,
                    processing_lease_until, processing_attempts, validation_attempts,
                    last_error_code, validation_summary, completion_parts, state,
                    content_profile, legacy_knowledge_source_eligible,
                    knowledge_source_graph_id, classification, owner_id, retention_until,
                    expires_at, created_at, updated_at, version
                ) VALUES (
                    :upload_id, :workspace_id, 'datariver-accepted', :object_key,
                    'legacy-source.pdf', NULL, :size_bytes, 'application/pdf', :source_hash,
                    :size_bytes, 'application/pdf', :source_hash, NULL, 0, 1, NULL,
                    CAST(:validation_summary AS jsonb), '[]'::jsonb, 'ACCEPTED',
                    'FORMAT_ONLY_V1', true, NULL,
                    1, :actor_id, NULL, NULL, :now, :now, 1
                )
                """
            ),
            {
                "upload_id": upload_id,
                "workspace_id": workspace_id,
                "object_key": f"legacy/{workspace_id}/{upload_id}.pdf",
                "size_bytes": len(source_content),
                "source_hash": source_hash,
                "validation_summary": validation_summary,
                "actor_id": actor_id,
                "now": now,
            },
        )
        await connection.execute(
            text(
                "ALTER TABLE integration.object_manifests ENABLE TRIGGER "
                "trg_object_manifest_legacy_knowledge_source_marker"
            )
        )
    return upload_id


async def _add_internal_graph(
    owner: AsyncEngine,
    *,
    workspace_id: UUID,
) -> UUID:
    graph_id, ontology_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    async with owner.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.graphs
                    (id, workspace_id, slug, name, graph_type, status,
                     active_release_id, classification, created_at, updated_at, version)
                VALUES
                    (:graph_id, :workspace_id, :slug, 'Legacy race graph', 'DOMAIN',
                     'DRAFT', NULL, 1, :now, :now, 1)
                """
            ),
            {
                "graph_id": graph_id,
                "workspace_id": workspace_id,
                "slug": f"legacy-race-{graph_id.hex}",
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.ontology_versions
                    (id, workspace_id, graph_id, version, schema_document,
                     checksum, status, created_at, updated_at)
                VALUES
                    (:ontology_id, :workspace_id, :graph_id, '1',
                     '{"entity_types":["Asset"],"edge_types":[]}'::jsonb,
                     :checksum, 'ACTIVE', :now, :now)
                """
            ),
            {
                "ontology_id": ontology_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "checksum": hashlib.sha256(str(graph_id).encode()).hexdigest(),
                "now": now,
            },
        )
    return graph_id


def _analysis(
    *,
    claim: KnowledgeSourceJobClaim,
    embedding: ModelBinding,
    extraction: ModelBinding,
) -> KnowledgeSourceAnalysis:
    page = PdfPage.create(page_number=1, text="asset one")
    return KnowledgeSourceAnalysis(
        source=claim.source,
        pages=(page,),
        embeddings=EmbeddingBatch(
            binding=embedding,
            embeddings=(PageEmbedding(page_number=1, vector=(0.1, 0.2)),),
            input_tokens=2,
        ),
        extraction=ExtractionDraft(
            binding=extraction,
            nodes=(
                ExtractedNodeDraft(
                    local_key="AssetOne",
                    entity_type="Asset",
                    properties={"name": "asset one"},
                    classification=1,
                    page_number=1,
                    evidence_text="asset one",
                    confidence=0.9,
                ),
            ),
            edges=(),
            input_tokens=2,
            output_tokens=2,
        ),
    )


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_source_snapshot_database_enforces_exact_governed_media_vocabulary() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, _ = await _seed(owner)
        inserted: set[str] = set()
        for index, media_type in enumerate(sorted(KNOWLEDGE_SOURCE_MEDIA_TYPES), start=1):
            upload_id = await _add_upload(
                owner,
                workspace_id=workspace_id,
                actor_id=actor_id,
                graph_id=graph_id,
                display_name=f"approved-source-{index}",
                media_type=media_type,
                content=f"approved-source-{index}".encode(),
            )
            async with owner.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO knowledge.source_snapshots (
                            id, workspace_id, graph_id, upload_id, bucket, object_key,
                            storage_version, media_type, byte_size, content_sha256,
                            classification, state, created_by, created_at, updated_at
                        )
                        SELECT
                            :source_id, manifest.workspace_id, :graph_id, manifest.id,
                            manifest.bucket, manifest.object_key, 'manifest-v1',
                            manifest.mime, manifest.size_bytes, manifest.sha256,
                            manifest.classification, 'PENDING', manifest.owner_id,
                            :now, :now
                        FROM integration.object_manifests AS manifest
                        WHERE manifest.workspace_id = :workspace_id
                          AND manifest.id = :upload_id
                        """
                    ),
                    {
                        "source_id": uuid4(),
                        "workspace_id": workspace_id,
                        "graph_id": graph_id,
                        "upload_id": upload_id,
                        "now": datetime.now(UTC),
                    },
                )
            inserted.add(media_type)

        async with owner.connect() as connection:
            stored = frozenset(
                await connection.scalars(
                    text(
                        """
                        SELECT media_type
                        FROM knowledge.source_snapshots
                        WHERE workspace_id = :workspace_id
                          AND graph_id = :graph_id
                          AND classification = 1
                        """
                    ),
                    {"workspace_id": workspace_id, "graph_id": graph_id},
                )
            )
        assert stored == KNOWLEDGE_SOURCE_MEDIA_TYPES
        assert inserted == KNOWLEDGE_SOURCE_MEDIA_TYPES

        rejected_media_types = (
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
            "application/vnd.ms-word.document.macroEnabled.12",
            "application/vnd.ms-excel.sheet.macroEnabled.12",
            "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
            "application/octet-stream",
        )
        for index, media_type in enumerate(rejected_media_types, start=1):
            upload_id = await _add_upload(
                owner,
                workspace_id=workspace_id,
                actor_id=actor_id,
                graph_id=graph_id,
                display_name=f"rejected-source-{index}",
                media_type=media_type,
                content=f"rejected-source-{index}".encode(),
            )
            with pytest.raises(
                DBAPIError,
                match="ck_source_snapshots_media_type_vocabulary",
            ):
                async with owner.begin() as connection:
                    await connection.execute(
                        text(
                            """
                            INSERT INTO knowledge.source_snapshots (
                                id, workspace_id, graph_id, upload_id, bucket, object_key,
                                storage_version, media_type, byte_size, content_sha256,
                                classification, state, created_by, created_at, updated_at
                            )
                            SELECT
                                :source_id, manifest.workspace_id, :graph_id, manifest.id,
                                manifest.bucket, manifest.object_key, 'manifest-v1',
                                manifest.mime, manifest.size_bytes, manifest.sha256,
                                manifest.classification, 'PENDING', manifest.owner_id,
                                :now, :now
                            FROM integration.object_manifests AS manifest
                            WHERE manifest.workspace_id = :workspace_id
                              AND manifest.id = :upload_id
                            """
                        ),
                        {
                            "source_id": uuid4(),
                            "workspace_id": workspace_id,
                            "graph_id": graph_id,
                            "upload_id": upload_id,
                            "now": datetime.now(UTC),
                        },
                    )
    finally:
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_governed_graph_a_upload_cannot_enqueue_or_rebind_through_graph_b() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        competing_graph_id = await _add_internal_graph(
            owner,
            workspace_id=workspace_id,
        )
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")

        with pytest.raises(ValidationError, match="different graph"):
            await _enqueue(
                app,
                workspace_id=workspace_id,
                actor_id=actor_id,
                graph_id=competing_graph_id,
                upload_id=upload_id,
                embedding=embedding,
                extraction=extraction,
                idempotency_key=f"cross-graph-{competing_graph_id}",
            )

        with pytest.raises(DBAPIError, match="graph binding is immutable"):
            async with app.begin() as connection:
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(actor_id)},
                )
                await connection.execute(
                    text(
                        """
                        UPDATE integration.object_manifests
                        SET knowledge_source_graph_id = :competing_graph_id
                        WHERE workspace_id = :workspace_id AND id = :upload_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "upload_id": upload_id,
                        "competing_graph_id": competing_graph_id,
                    },
                )

        with pytest.raises(DBAPIError, match="fk_source_snapshots_manifest_graph"):
            async with app.begin() as connection:
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(actor_id)},
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO knowledge.source_snapshots (
                            id, workspace_id, graph_id, upload_id, bucket, object_key,
                            storage_version, media_type, byte_size, content_sha256,
                            classification, state, created_by, created_at, updated_at
                        )
                        SELECT
                            :source_id, manifest.workspace_id, :competing_graph_id,
                            manifest.id, manifest.bucket, manifest.object_key,
                            'manifest-v' || manifest.version::text, manifest.mime,
                            manifest.size_bytes, manifest.sha256, manifest.classification,
                            'PENDING', manifest.owner_id, clock_timestamp(), clock_timestamp()
                        FROM integration.object_manifests AS manifest
                        WHERE manifest.workspace_id = :workspace_id
                          AND manifest.id = :upload_id
                        """
                    ),
                    {
                        "source_id": uuid4(),
                        "workspace_id": workspace_id,
                        "upload_id": upload_id,
                        "competing_graph_id": competing_graph_id,
                    },
                )

        for principal, subject_id in (
            (app, actor_id),
            (worker, _WORKER_SUBJECT_ID),
        ):
            with pytest.raises(DBAPIError):
                async with principal.begin() as connection:
                    await connection.execute(
                        text("SELECT set_config('app.workspace_id', :value, true)"),
                        {"value": str(workspace_id)},
                    )
                    await connection.execute(
                        text("SELECT set_config('app.subject_id', :value, true)"),
                        {"value": str(subject_id)},
                    )
                    await connection.execute(
                        text(
                            """
                            UPDATE integration.object_manifests
                            SET legacy_knowledge_source_eligible = true
                            WHERE workspace_id = :workspace_id AND id = :upload_id
                            """
                        ),
                        {"workspace_id": workspace_id, "upload_id": upload_id},
                    )

        async with owner.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM knowledge.source_snapshots
                             WHERE workspace_id = :workspace_id AND upload_id = :upload_id),
                            (SELECT count(*) FROM knowledge.source_analysis_jobs
                             WHERE workspace_id = :workspace_id),
                            (SELECT count(*) FROM integration.outbox_events
                             WHERE workspace_id = :workspace_id
                               AND aggregate_type = 'knowledge_source_analysis_job'),
                            (SELECT knowledge_source_graph_id
                             FROM integration.object_manifests
                             WHERE workspace_id = :workspace_id AND id = :upload_id)
                        """
                    ),
                    {"workspace_id": workspace_id, "upload_id": upload_id},
                )
            ).one()
        assert counts == (0, 0, 0, graph_id)

        valid_job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=embedding,
            extraction=extraction,
            idempotency_key=f"valid-composite-graph-{graph_id}",
        )
        async with owner.connect() as connection:
            job_fk = await connection.scalar(
                text(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conname = 'fk_source_analysis_jobs_snapshot_graph'
                    """
                )
            )
        assert job_fk is not None
        assert "FOREIGN KEY (workspace_id, graph_id, source_snapshot_id)" in job_fk

        with pytest.raises(DBAPIError):
            async with app.begin() as connection:
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(actor_id)},
                )
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.source_analysis_jobs
                        SET graph_id = :competing_graph_id
                        WHERE workspace_id = :workspace_id AND id = :job_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "job_id": valid_job.job_id,
                        "competing_graph_id": competing_graph_id,
                    },
                )

        sessions = async_sessionmaker(app, expire_on_commit=False)
        async with sessions() as session:
            cancelled = await SqlKnowledgeSourceJobStore(session).cancel(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=valid_job.job_id,
                actor_id=actor_id,
                expected_version=valid_job.version,
                reason="Composite graph fence fixture cleanup",
                request_hash="7" * 64,
                idempotency_key=f"composite-graph-cleanup-{valid_job.job_id}",
            )
        assert cancelled.state.value == "CANCELLED"
    finally:
        await worker.dispose()
        await app.dispose()
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_legacy_unsnapshotted_pdf_binds_once_under_cross_graph_race() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, _ = await _seed(owner)
        competing_graph_id = await _add_internal_graph(
            owner,
            workspace_id=workspace_id,
        )
        upload_id = await _add_migration_owned_legacy_upload(
            owner,
            workspace_id=workspace_id,
            actor_id=actor_id,
        )
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")

        outcomes = await asyncio.gather(
            _enqueue(
                app,
                workspace_id=workspace_id,
                actor_id=actor_id,
                graph_id=graph_id,
                upload_id=upload_id,
                embedding=embedding,
                extraction=extraction,
                idempotency_key=f"legacy-first-{graph_id}",
            ),
            _enqueue(
                app,
                workspace_id=workspace_id,
                actor_id=actor_id,
                graph_id=competing_graph_id,
                upload_id=upload_id,
                embedding=embedding,
                extraction=extraction,
                idempotency_key=f"legacy-first-{competing_graph_id}",
            ),
            return_exceptions=True,
        )
        successes = [
            outcome for outcome in outcomes if isinstance(outcome, KnowledgeSourceJobRecord)
        ]
        failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], ValidationError)
        assert "different graph" in str(failures[0])

        winner = successes[0]
        assert winner.graph_id in {graph_id, competing_graph_id}
        async with owner.connect() as connection:
            binding = await connection.scalar(
                text(
                    """
                    SELECT knowledge_source_graph_id
                    FROM integration.object_manifests
                    WHERE workspace_id = :workspace_id AND id = :upload_id
                    """
                ),
                {"workspace_id": workspace_id, "upload_id": upload_id},
            )
            source_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM knowledge.source_snapshots
                    WHERE workspace_id = :workspace_id AND upload_id = :upload_id
                    """
                ),
                {"workspace_id": workspace_id, "upload_id": upload_id},
            )
        assert binding == winner.graph_id
        assert source_count == 1
        sessions = async_sessionmaker(app, expire_on_commit=False)
        async with sessions() as session:
            cancelled = await SqlKnowledgeSourceJobStore(session).cancel(
                workspace_id=workspace_id,
                graph_id=winner.graph_id,
                job_id=winner.job_id,
                actor_id=actor_id,
                expected_version=winner.version,
                reason="Isolated legacy race fixture cleanup",
                request_hash="f" * 64,
                idempotency_key=f"legacy-race-cleanup-{winner.job_id}",
            )
        assert cancelled.state.value == "CANCELLED"
    finally:
        await app.dispose()
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_enqueue_is_one_actor_bound_job_under_race_and_rejects_key_reuse() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        workspace_id, actor_id, other_actor_id, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        key = f"source-analysis-race-{upload_id}"
        first, second = await asyncio.gather(
            *(
                _enqueue(
                    app,
                    workspace_id=workspace_id,
                    actor_id=actor_id,
                    graph_id=graph_id,
                    upload_id=upload_id,
                    embedding=embedding,
                    extraction=extraction,
                    idempotency_key=key,
                )
                for _ in range(2)
            )
        )
        assert first.job_id == second.job_id

        conflict_cases: tuple[tuple[UUID, UUID, UUID, str, str], ...] = (
            (actor_id, graph_id, upload_id, "Changed title", "e" * 64),
            (actor_id, graph_id, uuid4(), "Durable source proposal", "d" * 64),
            (actor_id, uuid4(), upload_id, "Durable source proposal", "d" * 64),
            (other_actor_id, graph_id, upload_id, "Durable source proposal", "d" * 64),
        )
        for (
            conflicting_actor,
            conflicting_graph,
            conflicting_upload,
            conflicting_title,
            conflicting_hash,
        ) in conflict_cases:
            with pytest.raises(ConflictError, match="idempotency key"):
                await _enqueue(
                    app,
                    workspace_id=workspace_id,
                    actor_id=conflicting_actor,
                    graph_id=conflicting_graph,
                    upload_id=conflicting_upload,
                    embedding=embedding,
                    extraction=extraction,
                    title=conflicting_title,
                    request_hash=conflicting_hash,
                    idempotency_key=key,
                )

        async with owner.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (
                                SELECT count(*)
                                FROM knowledge.source_analysis_jobs
                                WHERE workspace_id = :workspace_id
                                  AND source_snapshot_id = :source_snapshot_id
                            ),
                            (
                                SELECT count(*)
                                FROM knowledge.source_analysis_events
                                WHERE workspace_id = :workspace_id
                                  AND job_id = :job_id
                                  AND event_type = 'QUEUED'
                            ),
                            (
                                SELECT count(*)
                                FROM integration.outbox_events
                                WHERE workspace_id = :workspace_id
                                  AND aggregate_type = 'knowledge_source_analysis_job'
                                  AND aggregate_id = :job_id
                                  AND event_type = 'knowledge.source-analysis.queued.v1'
                            )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "source_snapshot_id": first.source_snapshot_id,
                        "job_id": first.job_id,
                    },
                )
            ).one()
            assert tuple(counts) == (1, 1, 1)
        sessions = async_sessionmaker(app, expire_on_commit=False)
        async with sessions() as session:
            cancelled = await SqlKnowledgeSourceJobStore(session).cancel(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=first.job_id,
                actor_id=actor_id,
                expected_version=first.version,
                reason="Race test cleanup",
                request_hash="c" * 64,
                idempotency_key=f"cancel-race-{first.job_id}",
            )
            assert cancelled.state.value == "CANCELLED"
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_api_event_and_outbox_require_exact_same_transaction_transition() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=_binding("embed", "a"),
            extraction=_binding("extract", "b"),
        )
        event_insert = text(
            """
            INSERT INTO knowledge.source_analysis_events (
                id, workspace_id, job_id, sequence, attempt_id,
                event_type, actor_ref, reason_code, evidence_hash,
                details, occurred_at
            ) VALUES (
                :id, :workspace_id, :job_id, 2, NULL,
                'CANCELLED', :actor_ref, 'USER_REQUEST', :evidence_hash,
                CAST(:details AS jsonb), :occurred_at
            )
            """
        )
        outbox_insert = text(
            """
            INSERT INTO integration.outbox_events (
                id, workspace_id, aggregate_type, aggregate_id,
                event_type, schema_version, payload, created_at,
                published_at, dead_lettered_at, lease_until,
                attempts, last_error_code
            ) VALUES (
                :id, :workspace_id, 'knowledge_source_analysis_job',
                :job_id, 'knowledge.source-analysis.cancelled.v1',
                :schema_version, CAST(:payload AS jsonb), :created_at,
                :published_at, :dead_lettered_at, :lease_until,
                :attempts, :last_error_code
            )
            """
        )

        async with app.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text(
                        """
                        SELECT
                            set_config('app.workspace_id', :workspace_id, true),
                            set_config('app.subject_id', :subject_id, true)
                        """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "subject_id": str(actor_id),
                    },
                )
                unchanged_at = await connection.scalar(text("SELECT clock_timestamp()"))
                with pytest.raises(DBAPIError, match="API event evidence is invalid"):
                    async with connection.begin_nested():
                        await connection.execute(
                            event_insert,
                            {
                                "id": uuid4(),
                                "workspace_id": workspace_id,
                                "job_id": job.job_id,
                                "actor_ref": f"subject:{actor_id}",
                                "evidence_hash": "0" * 64,
                                "details": json.dumps({}),
                                "occurred_at": unchanged_at,
                            },
                        )
                with pytest.raises(DBAPIError, match="API outbox evidence is invalid"):
                    async with connection.begin_nested():
                        await connection.execute(
                            outbox_insert,
                            {
                                "id": uuid4(),
                                "workspace_id": workspace_id,
                                "job_id": job.job_id,
                                "schema_version": 1,
                                "payload": json.dumps(
                                    {
                                        "job_id": str(job.job_id),
                                        "graph_id": str(graph_id),
                                        "state": "CANCELLED",
                                        "version": 2,
                                    }
                                ),
                                "created_at": unchanged_at,
                                "published_at": None,
                                "dead_lettered_at": None,
                                "lease_until": None,
                                "attempts": 0,
                                "last_error_code": None,
                            },
                        )

        event_id, outbox_id = uuid4(), uuid4()
        async with app.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text(
                        """
                        SELECT
                            set_config('app.workspace_id', :workspace_id, true),
                            set_config('app.subject_id', :subject_id, true)
                        """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "subject_id": str(actor_id),
                    },
                )
                cancelled_at = await connection.scalar(text("SELECT clock_timestamp()"))
                version = await connection.scalar(
                    text(
                        """
                        UPDATE knowledge.source_analysis_jobs
                        SET state = 'CANCELLED',
                            stage = 'COMPLETED',
                            cancel_requested_by = :actor_id,
                            cancel_requested_at = :cancelled_at,
                            cancel_reason = 'Direct evidence test',
                            completed_at = :cancelled_at,
                            updated_at = :cancelled_at,
                            version = version + 1
                        WHERE workspace_id = :workspace_id
                          AND id = :job_id
                        RETURNING version
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "job_id": job.job_id,
                        "actor_id": actor_id,
                        "cancelled_at": cancelled_at,
                    },
                )
                canonical_event = {
                    "id": event_id,
                    "workspace_id": workspace_id,
                    "job_id": job.job_id,
                    "actor_ref": f"subject:{actor_id}",
                    "evidence_hash": "0" * 64,
                    "details": json.dumps({}),
                    "occurred_at": cancelled_at,
                }
                for mutation in (
                    {"details": json.dumps({"forged": True})},
                    {"occurred_at": cancelled_at + timedelta(seconds=1)},
                ):
                    with pytest.raises(DBAPIError, match="API event evidence is invalid"):
                        async with connection.begin_nested():
                            await connection.execute(
                                event_insert,
                                {
                                    **canonical_event,
                                    **mutation,
                                    "id": uuid4(),
                                },
                            )
                await connection.execute(event_insert, canonical_event)
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():
                        await connection.execute(
                            event_insert,
                            {**canonical_event, "id": uuid4()},
                        )

                payload = json.dumps(
                    {
                        "job_id": str(job.job_id),
                        "graph_id": str(graph_id),
                        "state": "CANCELLED",
                        "version": version,
                    }
                )
                canonical_outbox = {
                    "id": outbox_id,
                    "workspace_id": workspace_id,
                    "job_id": job.job_id,
                    "schema_version": 1,
                    "payload": payload,
                    "created_at": cancelled_at + timedelta(days=1),
                    "published_at": None,
                    "dead_lettered_at": None,
                    "lease_until": None,
                    "attempts": 0,
                    "last_error_code": None,
                }
                for mutation in (
                    {"schema_version": 2},
                    {"payload": json.dumps({"job_id": str(job.job_id)})},
                    {"published_at": cancelled_at},
                    {"attempts": 1},
                ):
                    with pytest.raises(DBAPIError, match="API outbox evidence is invalid"):
                        async with connection.begin_nested():
                            await connection.execute(
                                outbox_insert,
                                {
                                    **canonical_outbox,
                                    **mutation,
                                    "id": uuid4(),
                                },
                            )
                await connection.execute(outbox_insert, canonical_outbox)
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():
                        await connection.execute(
                            outbox_insert,
                            {**canonical_outbox, "id": uuid4()},
                        )

        async with owner.connect() as connection:
            stored_hash, recomputed_hash = (
                await connection.execute(
                    text(
                        """
                        SELECT event.evidence_hash,
                               encode(
                                   sha256(
                                       convert_to(
                                           jsonb_build_object(
                                               'job_id', event.job_id,
                                               'sequence', event.sequence,
                                               'attempt_id', event.attempt_id,
                                               'event_type', event.event_type,
                                               'actor_ref', event.actor_ref,
                                               'reason_code', event.reason_code,
                                               'details', event.details,
                                               'occurred_at', event.occurred_at
                                           )::text,
                                           'UTF8'
                                       )
                                   ),
                                   'hex'
                               )
                        FROM knowledge.source_analysis_events AS event
                        WHERE event.id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).one()
            assert stored_hash == recomputed_hash
            assert stored_hash != "0" * 64
            created_at = await connection.scalar(
                text("SELECT created_at FROM integration.outbox_events WHERE id = :id"),
                {"id": outbox_id},
            )
            assert created_at == cancelled_at
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.parametrize(
    ("drift_kind", "expected_code"),
    (
        ("source_manifest", "STALE_SOURCE_MANIFEST"),
        ("source_validation", "STALE_SOURCE_VALIDATION"),
        ("graph_version", "STALE_GRAPH_VERSION"),
        ("base_release", "STALE_BASE_BINDING"),
        ("ontology", "STALE_ONTOLOGY_BINDING"),
        ("model_binding", "STALE_MODEL_BINDING"),
        ("classification", "STALE_CLASSIFICATION_ENVELOPE"),
    ),
)
@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_each_pinned_runtime_drift_fails_closed(
    drift_kind: str,
    expected_code: str,
) -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, other_actor_id, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint=f"worker-drift-{drift_kind}",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id

        current_embedding = embedding
        current_extraction = extraction
        async with owner.begin() as connection:
            if drift_kind == "source_manifest":
                await connection.execute(
                    text(
                        """
                        UPDATE integration.object_manifests
                        SET version = version + 1,
                            updated_at = clock_timestamp()
                        WHERE workspace_id = :workspace_id
                          AND id = :upload_id
                        """
                    ),
                    {"workspace_id": workspace_id, "upload_id": upload_id},
                )
            elif drift_kind == "source_validation":
                await connection.execute(
                    text(
                        """
                        UPDATE integration.object_manifests
                        SET validation_summary = jsonb_set(
                                validation_summary,
                                '{profile_configuration_hash}',
                                to_jsonb(CAST(:stale_hash AS text))
                            ),
                            updated_at = clock_timestamp()
                        WHERE workspace_id = :workspace_id
                          AND id = :upload_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "upload_id": upload_id,
                        "stale_hash": "0" * 64,
                    },
                )
            elif drift_kind == "graph_version":
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.graphs
                        SET version = version + 1,
                            updated_at = clock_timestamp()
                        WHERE workspace_id = :workspace_id
                          AND id = :graph_id
                        """
                    ),
                    {"workspace_id": workspace_id, "graph_id": graph_id},
                )
            elif drift_kind == "base_release":
                release_id, changeset_id = uuid4(), uuid4()
                await connection.execute(
                    text(
                        """
                        INSERT INTO knowledge.releases (
                            id, workspace_id, graph_id, release_no, ontology_version_id,
                            content_hash, node_count, edge_count, manifest_ref,
                            published_by, published_at, deprecated_at
                        ) VALUES (
                            :release_id, :workspace_id, :graph_id, 1, :ontology_id,
                            :content_hash, 0, 0, NULL, :actor_id, clock_timestamp(), NULL
                        )
                        """
                    ),
                    {
                        "release_id": release_id,
                        "workspace_id": workspace_id,
                        "graph_id": graph_id,
                        "ontology_id": claim.pins.ontology_version_id,
                        "content_hash": "f" * 64,
                        "actor_id": actor_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO knowledge.changesets (
                            id, workspace_id, graph_id, base_release_id,
                            ontology_version_id, title, state, author_id,
                            source_analysis_job_id, reviewed_by, reviewed_at,
                            review_reason, published_release_id,
                            created_at, updated_at, version
                        ) VALUES (
                            :changeset_id, :workspace_id, :graph_id, NULL,
                            :ontology_id, 'External governed base', 'PUBLISHED', :actor_id,
                            NULL, :reviewer_id, clock_timestamp(),
                            'Independent review evidence', :release_id,
                            clock_timestamp(), clock_timestamp(), 1
                        )
                        """
                    ),
                    {
                        "changeset_id": changeset_id,
                        "workspace_id": workspace_id,
                        "graph_id": graph_id,
                        "ontology_id": claim.pins.ontology_version_id,
                        "actor_id": actor_id,
                        "reviewer_id": other_actor_id,
                        "release_id": release_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.graphs
                        SET active_release_id = :release_id,
                            updated_at = clock_timestamp()
                        WHERE workspace_id = :workspace_id
                          AND id = :graph_id
                        """
                    ),
                    {
                        "release_id": release_id,
                        "workspace_id": workspace_id,
                        "graph_id": graph_id,
                    },
                )
            elif drift_kind == "ontology":
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.ontology_versions
                        SET checksum = :checksum
                        WHERE workspace_id = :workspace_id
                          AND graph_id = :graph_id
                          AND id = :ontology_id
                        """
                    ),
                    {
                        "checksum": "e" * 64,
                        "workspace_id": workspace_id,
                        "graph_id": graph_id,
                        "ontology_id": claim.pins.ontology_version_id,
                    },
                )
            elif drift_kind == "model_binding":
                current_embedding = replace(embedding, configuration_hash="e" * 64)
            elif drift_kind == "classification":
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.graphs
                        SET classification = 0,
                            updated_at = clock_timestamp()
                        WHERE workspace_id = :workspace_id
                          AND id = :graph_id
                        """
                    ),
                    {"workspace_id": workspace_id, "graph_id": graph_id},
                )
            else:  # pragma: no cover - the parametrization is closed above.
                raise AssertionError(f"Unsupported drift kind: {drift_kind}")

        drift_code = await store.ensure_current(
            claim=claim,
            current_embedding_binding=current_embedding,
            current_extraction_binding=current_extraction,
        )
        assert drift_code == expected_code
        await store.mark_stale(claim=claim, failure_code=expected_code)

        async with owner.connect() as connection:
            state = (
                await connection.execute(
                    text(
                        """
                        SELECT state, last_failure_code, result_changeset_id,
                               result_evidence_hash
                        FROM knowledge.source_analysis_jobs
                        WHERE workspace_id = :workspace_id
                          AND id = :job_id
                        """
                    ),
                    {"workspace_id": workspace_id, "job_id": job.job_id},
                )
            ).one()
            assert tuple(state) == ("STALE", expected_code, None, None)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_owner_job_history_orders_nonterminal_before_newer_terminal_rows() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, first_upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        active = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=first_upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        second_upload_id = await _add_upload(
            owner,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
        )
        terminal = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=second_upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        sessions = async_sessionmaker(app, expire_on_commit=False)
        async with sessions() as session:
            store = SqlKnowledgeSourceJobStore(session)
            await store.cancel(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=terminal.job_id,
                actor_id=actor_id,
                expected_version=terminal.version,
                reason="list ordering test",
                request_hash="e" * 64,
                idempotency_key=f"cancel-{terminal.job_id}",
            )
        async with sessions() as session:
            first = await SqlKnowledgeSourceJobStore(session).list_owned(
                workspace_id=workspace_id,
                graph_id=graph_id,
                actor_id=actor_id,
                limit=1,
                cursor=None,
            )
        assert [item.job_id for item in first.items] == [active.job_id]
        assert first.next_cursor is not None
        async with sessions() as session:
            second = await SqlKnowledgeSourceJobStore(session).list_owned(
                workspace_id=workspace_id,
                graph_id=graph_id,
                actor_id=actor_id,
                limit=1,
                cursor=first.next_cursor,
            )
        assert [item.job_id for item in second.items] == [terminal.job_id]
        async with sessions() as session:
            await SqlKnowledgeSourceJobStore(session).cancel(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=active.job_id,
                actor_id=actor_id,
                expected_version=active.version,
                reason="history test cleanup",
                request_hash="f" * 64,
                idempotency_key=f"cancel-{active.job_id}",
            )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_owner_active_job_capacity_keeps_every_active_job_on_the_first_page() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        active_jobs: list[KnowledgeSourceJobRecord] = []
        for index in range(20):
            current_upload_id = (
                upload_id
                if index == 0
                else await _add_upload(
                    owner,
                    workspace_id=workspace_id,
                    actor_id=actor_id,
                    graph_id=graph_id,
                )
            )
            active_jobs.append(
                await _enqueue(
                    app,
                    workspace_id=workspace_id,
                    actor_id=actor_id,
                    graph_id=graph_id,
                    upload_id=current_upload_id,
                    embedding=embedding,
                    extraction=extraction,
                )
            )
        rejected_upload_id = await _add_upload(
            owner,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
        )
        with pytest.raises(ConflictError, match="maximum number of active"):
            await _enqueue(
                app,
                workspace_id=workspace_id,
                actor_id=actor_id,
                graph_id=graph_id,
                upload_id=rejected_upload_id,
                embedding=embedding,
                extraction=extraction,
            )
        sessions = async_sessionmaker(app, expire_on_commit=False)
        async with sessions() as session:
            page = await SqlKnowledgeSourceJobStore(session).list_owned(
                workspace_id=workspace_id,
                graph_id=graph_id,
                actor_id=actor_id,
                limit=100,
                cursor=None,
            )
        assert len(page.items) == 20
        assert all(not item.state.terminal for item in page.items)
        assert page.next_cursor is None
        for active_job in active_jobs:
            async with sessions() as session:
                await SqlKnowledgeSourceJobStore(session).cancel(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    job_id=active_job.job_id,
                    actor_id=actor_id,
                    expected_version=active_job.version,
                    reason="capacity test cleanup",
                    request_hash=hashlib.sha256(str(active_job.job_id).encode()).hexdigest(),
                    idempotency_key=f"cancel-{active_job.job_id}",
                )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_claim_is_single_fenced_and_retry_terminal_pair_is_atomic() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, other_actor_id, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        worker_sessions = async_sessionmaker(worker, expire_on_commit=False)
        stores = (
            SqlKnowledgeSourceJobWorkerStore(worker_sessions, worker_subject_id=_WORKER_SUBJECT_ID),
            SqlKnowledgeSourceJobWorkerStore(worker_sessions, worker_subject_id=_WORKER_SUBJECT_ID),
        )
        claims = await asyncio.gather(
            *(
                store.claim_next(
                    worker_fingerprint=f"worker-{index}",
                    lease_seconds=300,
                    maximum_attempts=3,
                )
                for index, store in enumerate(stores)
            )
        )
        claimed = [claim for claim in claims if claim is not None]
        assert len(claimed) == 1
        claim = claimed[0]
        with pytest.raises(ConflictError, match="no longer current"):
            await stores[0].ensure_current(
                claim=replace(claim, lease_token="wrong-token"),
                current_embedding_binding=embedding,
                current_extraction_binding=extraction,
            )
        await stores[0].mark_failed(
            claim=claim,
            failure_code="PROVIDER_TIMEOUT",
            retryable=True,
        )
        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT job.state, attempt.state, attempt.retryable
                        FROM knowledge.source_analysis_jobs AS job
                        JOIN knowledge.source_analysis_attempts AS attempt
                          ON attempt.workspace_id = job.workspace_id
                         AND attempt.job_id = job.id
                        WHERE job.id = :job_id
                        """
                    ),
                    {"job_id": job.job_id},
                )
            ).one()
            assert tuple(row) == ("RETRY_WAIT", "FAILED", True)
        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.source_analysis_jobs
                    SET next_attempt_at = clock_timestamp() + interval '1 day'
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job.job_id},
            )
        app_sessions = async_sessionmaker(app, expire_on_commit=False)
        async with app_sessions() as session:
            await session.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(workspace_id)},
            )
            await session.execute(
                text("SELECT set_config('app.subject_id', :subject_id, true)"),
                {"subject_id": str(other_actor_id)},
            )
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge.source_analysis_events
                            (id, workspace_id, job_id, sequence, event_type,
                             actor_ref, evidence_hash, details, occurred_at)
                        VALUES
                            (:id, :workspace_id, :job_id, 999, 'CANCELLED',
                             :actor_ref, :evidence_hash, '{}'::jsonb, clock_timestamp())
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "job_id": job.job_id,
                        "actor_ref": f"subject:{other_actor_id}",
                        "evidence_hash": "e" * 64,
                    },
                )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_live_attempt_cannot_be_superseded_without_token_and_expiry_recovers_pair() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=_system_binding("embed", "2"),
            extraction=_system_binding("extract", "1"),
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-expiry",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                },
            )
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.source_analysis_attempts
                        SET state = 'SUPERSEDED',
                            stage = 'COMPLETED',
                            failure_code = 'LEASE_EXPIRED',
                            finished_at = clock_timestamp()
                        WHERE workspace_id = :workspace_id
                          AND id = :attempt_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "attempt_id": claim.attempt_id,
                    },
                )
            assert "attempt lease is superseded" in str(error.value.orig)

        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.source_analysis_jobs
                    SET lease_expires_at = clock_timestamp() - interval '1 second'
                    WHERE workspace_id = :workspace_id
                      AND id = :job_id
                    """
                ),
                {"workspace_id": workspace_id, "job_id": job.job_id},
            )

        assert await store._recover_one_expired(
            workspace_id=workspace_id,
            maximum_attempts=3,
        )
        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT job.state, job.stage, job.lease_token_hash,
                               job.lease_expires_at, attempt.state, attempt.stage,
                               attempt.failure_code, attempt.finished_at IS NOT NULL
                        FROM knowledge.source_analysis_jobs AS job
                        JOIN knowledge.source_analysis_attempts AS attempt
                          ON attempt.workspace_id = job.workspace_id
                         AND attempt.job_id = job.id
                         AND attempt.lease_epoch = job.lease_epoch
                        WHERE job.workspace_id = :workspace_id
                          AND job.id = :job_id
                        """
                    ),
                    {"workspace_id": workspace_id, "job_id": job.job_id},
                )
            ).one()
            assert tuple(row) == (
                "RETRY_WAIT",
                "QUEUED",
                None,
                None,
                "SUPERSEDED",
                "COMPLETED",
                "LEASE_EXPIRED",
                True,
            )
        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.source_analysis_jobs
                    SET next_attempt_at = clock_timestamp() + interval '1 day'
                    WHERE workspace_id = :workspace_id
                      AND id = :job_id
                    """
                ),
                {"workspace_id": workspace_id, "job_id": job.job_id},
            )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_cancel_requested_rejects_success_and_worker_resolves_cancelled() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        worker_sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            worker_sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-cancel",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id

        app_sessions = async_sessionmaker(app, expire_on_commit=False)
        async with app_sessions() as session:
            cancelled = await SqlKnowledgeSourceJobStore(session).cancel(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=job.job_id,
                actor_id=actor_id,
                expected_version=claim.job.version,
                reason="No longer required",
                request_hash="f" * 64,
                idempotency_key=f"cancel-{job.job_id}",
            )
        assert cancelled.state.value == "CANCEL_REQUESTED"

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true),
                        set_config('app.knowledge_source_lease_token', :lease_token, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                    "lease_token": claim.lease_token,
                },
            )
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.source_analysis_jobs
                        SET state = 'SUCCEEDED',
                            stage = 'COMPLETED',
                            lease_token_hash = NULL,
                            lease_owner_fingerprint = NULL,
                            lease_started_at = NULL,
                            lease_expires_at = NULL,
                            completed_at = clock_timestamp(),
                            updated_at = clock_timestamp(),
                            version = version + 1
                        WHERE workspace_id = :workspace_id
                          AND id = :job_id
                        """
                    ),
                    {"workspace_id": workspace_id, "job_id": job.job_id},
                )
            assert "cancellation request may only become cancelled" in str(error.value.orig)

        result = await store.finalize(
            claim=claim,
            analysis=_analysis(claim=claim, embedding=embedding, extraction=extraction),
            current_embedding_binding=embedding,
            current_extraction_binding=extraction,
        )
        assert result.state.value == "CANCELLED"
        assert result.result is None
        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT job.state, job.stage, attempt.state, attempt.stage,
                               count(changeset.id), count(extraction.id)
                        FROM knowledge.source_analysis_jobs AS job
                        JOIN knowledge.source_analysis_attempts AS attempt
                          ON attempt.workspace_id = job.workspace_id
                         AND attempt.job_id = job.id
                         AND attempt.lease_epoch = job.lease_epoch
                        LEFT JOIN knowledge.changesets AS changeset
                          ON changeset.workspace_id = job.workspace_id
                         AND changeset.source_analysis_job_id = job.id
                        LEFT JOIN knowledge.extraction_runs AS extraction
                          ON extraction.workspace_id = job.workspace_id
                         AND extraction.source_analysis_job_id = job.id
                        WHERE job.workspace_id = :workspace_id
                          AND job.id = :job_id
                        GROUP BY job.state, job.stage, attempt.state, attempt.stage
                        """
                    ),
                    {"workspace_id": workspace_id, "job_id": job.job_id},
                )
            ).one()
            assert tuple(row) == (
                "CANCELLED",
                "COMPLETED",
                "CANCELLED",
                "COMPLETED",
                0,
                0,
            )
            cancelled_outbox_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM integration.outbox_events
                    WHERE workspace_id = :workspace_id
                      AND aggregate_type = 'knowledge_source_analysis_job'
                      AND aggregate_id = :job_id
                      AND event_type = 'knowledge.source-analysis.cancelled.v1'
                    """
                ),
                {"workspace_id": workspace_id, "job_id": job.job_id},
            )
            assert cancelled_outbox_count == 1
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_worker_outbox_is_fenced_to_exact_selected_job() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=_system_binding("embed", "2"),
            extraction=_system_binding("extract", "1"),
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-outbox",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id
        other_job_id = uuid4()

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                },
            )
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        """
                        INSERT INTO integration.outbox_events (
                            id, workspace_id, aggregate_type, aggregate_id,
                            event_type, schema_version, payload, created_at,
                            published_at, dead_lettered_at, lease_until,
                            attempts, last_error_code
                        ) VALUES (
                            :id, :workspace_id, 'knowledge_source_analysis_job',
                            :other_job_id, 'knowledge.source-analysis.failed.v1',
                            1, CAST(:payload AS jsonb), clock_timestamp(),
                            NULL, NULL, NULL, 0, NULL
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "other_job_id": other_job_id,
                        "payload": json.dumps({"job_id": str(job.job_id)}),
                    },
                )
            assert "outbox evidence is outside the selected job" in str(error.value.orig)

        await store.mark_failed(
            claim=claim,
            failure_code="TEST_COMPLETE",
            retryable=False,
        )
        async with owner.connect() as connection:
            outbox_job_ids = tuple(
                (
                    await connection.scalars(
                        text(
                            """
                            SELECT aggregate_id
                            FROM integration.outbox_events
                            WHERE workspace_id = :workspace_id
                              AND aggregate_type = 'knowledge_source_analysis_job'
                            ORDER BY created_at, id
                            """
                        ),
                        {"workspace_id": workspace_id},
                    )
                ).all()
            )
            assert outbox_job_ids
            assert set(outbox_job_ids) == {job.job_id}
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_worker_data_plane_is_exact_claim_scoped_and_inbox_is_consumer_scoped() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=_system_binding("embed", "2"),
            extraction=_system_binding("extract", "1"),
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-claim-scope",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id
        fixed_event_id, foreign_event_id = uuid4(), uuid4()
        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.inbox_messages
                        (workspace_id, consumer, event_id, received_at)
                    VALUES
                        (:workspace_id, 'foreign-consumer', :event_id, clock_timestamp())
                    """
                ),
                {"workspace_id": workspace_id, "event_id": foreign_event_id},
            )

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true),
                        set_config('app.knowledge_source_lease_token', :lease_token, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                    "lease_token": claim.lease_token,
                },
            )
            scoped_counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM integration.object_manifests),
                            (SELECT count(*) FROM knowledge.source_snapshots),
                            (SELECT count(*) FROM knowledge.graphs),
                            (SELECT count(*) FROM knowledge.ontology_versions),
                            (SELECT count(*) FROM iam.subjects),
                            (SELECT count(*) FROM iam.workspace_memberships),
                            (SELECT count(*) FROM integration.inbox_messages),
                            (SELECT count(*)
                             FROM platform.external_service_profiles),
                            (SELECT count(*)
                             FROM platform.external_service_profile_versions)
                        """
                    )
                )
            ).one()
            assert tuple(scoped_counts) == (1, 1, 1, 1, 1, 1, 0, 2, 2)
            non_inference_profiles = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM platform.external_service_profiles
                    WHERE service_key = 'DATAHUB'
                    """
                )
            )
            assert non_inference_profiles == 0
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.inbox_messages
                        (workspace_id, consumer, event_id, received_at)
                    VALUES
                        (:workspace_id, 'knowledge-source-analysis-v1',
                         :event_id, clock_timestamp())
                    """
                ),
                {"workspace_id": workspace_id, "event_id": fixed_event_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.inbox_messages
                    SET completed_at = clock_timestamp(), result_hash = :result_hash
                    WHERE consumer = 'knowledge-source-analysis-v1'
                      AND event_id = :event_id
                    """
                ),
                {"event_id": fixed_event_id, "result_hash": "a" * 64},
            )

        for lease_token in (None, "wrong-lease-token"):
            async with worker.begin() as connection:
                await connection.execute(
                    text(
                        """
                        SELECT
                            set_config('app.workspace_id', :workspace_id, true),
                            set_config('app.subject_id', :subject_id, true),
                            set_config('app.knowledge_source_job_id', :job_id, true)
                        """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "subject_id": str(_WORKER_SUBJECT_ID),
                        "job_id": str(job.job_id),
                    },
                )
                if lease_token is not None:
                    await connection.execute(
                        text(
                            """
                            SELECT set_config(
                                'app.knowledge_source_lease_token',
                                :lease_token,
                                true
                            )
                            """
                        ),
                        {"lease_token": lease_token},
                    )
                hidden_counts = (
                    await connection.execute(
                        text(
                            """
                            SELECT
                                (SELECT count(*) FROM integration.object_manifests),
                                (SELECT count(*) FROM knowledge.source_snapshots),
                                (SELECT count(*) FROM knowledge.graphs),
                                (SELECT count(*) FROM iam.subjects),
                                (SELECT count(*) FROM iam.workspace_memberships),
                                (SELECT count(*)
                                 FROM platform.external_service_profiles),
                                (SELECT count(*)
                                 FROM platform.external_service_profile_versions)
                            """
                        )
                    )
                ).one()
                assert tuple(hidden_counts) == (0, 0, 0, 0, 0, 0, 0)

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                },
            )
            with pytest.raises(DBAPIError):
                await connection.execute(text("SELECT * FROM knowledge.source_pages LIMIT 1"))

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                },
            )
            with pytest.raises(DBAPIError, match="inbox consumer"):
                await connection.execute(
                    text(
                        """
                        INSERT INTO integration.inbox_messages
                            (workspace_id, consumer, event_id, received_at)
                        VALUES
                            (:workspace_id, 'foreign-consumer',
                             :event_id, clock_timestamp())
                        """
                    ),
                    {"workspace_id": workspace_id, "event_id": uuid4()},
                )

        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.source_analysis_jobs
                    SET lease_expires_at = clock_timestamp() - interval '1 second'
                    WHERE workspace_id = :workspace_id AND id = :job_id
                    """
                ),
                {"workspace_id": workspace_id, "job_id": job.job_id},
            )
        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true),
                        set_config('app.knowledge_source_lease_token', :lease_token, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                    "lease_token": claim.lease_token,
                },
            )
            expired_counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM integration.object_manifests),
                            (SELECT count(*) FROM knowledge.source_snapshots),
                            (SELECT count(*) FROM knowledge.graphs),
                            (SELECT count(*) FROM iam.subjects),
                            (SELECT count(*) FROM iam.workspace_memberships),
                            (SELECT count(*)
                             FROM platform.external_service_profiles),
                            (SELECT count(*)
                             FROM platform.external_service_profile_versions)
                        """
                    )
                )
            ).one()
            assert tuple(expired_counts) == (0, 0, 0, 0, 0, 0, 0)
        assert await store._recover_one_expired(
            workspace_id=workspace_id,
            maximum_attempts=3,
        )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_worker_event_policy_and_outbox_require_live_transition_evidence() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=_binding("embed", "a"),
            extraction=_binding("extract", "b"),
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-evidence-scope",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                },
            )
            with pytest.raises(DBAPIError, match="bound to this transition"):
                await connection.execute(
                    text(
                        """
                        INSERT INTO knowledge.source_analysis_events (
                            id, workspace_id, job_id, sequence, attempt_id,
                            event_type, actor_ref, reason_code, evidence_hash,
                            details, occurred_at
                        ) VALUES (
                            :id, :workspace_id, :job_id, 3, :attempt_id,
                            'LEASE_RENEWED', :actor_ref, NULL, :evidence_hash,
                            CAST(:details AS jsonb), clock_timestamp()
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "job_id": job.job_id,
                        "attempt_id": claim.attempt_id,
                        "actor_ref": f"worker:{claim.worker_fingerprint}",
                        "evidence_hash": "e" * 64,
                        "details": json.dumps({"stage": "SOURCE_READ", "progress": {}}),
                    },
                )

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true),
                        set_config('app.knowledge_source_lease_token', :lease_token, true)
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                    "lease_token": claim.lease_token,
                },
            )
            with pytest.raises(DBAPIError, match="policy evidence"):
                await connection.execute(
                    text(
                        """
                        INSERT INTO authz.policy_decisions (
                            id, workspace_id, subject_id, resource_id, action,
                            effect, reason_codes, policy_versions,
                            evaluation_context, request_id, decided_at
                        ) VALUES (
                            :id, :workspace_id, :actor_id, :graph_id, 'kg.edit',
                            'ALLOW', '["POLICY_ALLOW"]'::jsonb,
                            '["builtin-abac-v2"]'::jsonb,
                            CAST(:context AS jsonb), :request_id, clock_timestamp()
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "actor_id": actor_id,
                        "graph_id": graph_id,
                        "context": json.dumps(
                            {
                                "kind": "knowledge_source_job_finalization",
                                "job_id": str(job.job_id),
                                "pin_hash": claim.pins.evidence_hash(),
                            }
                        ),
                        "request_id": str(job.job_id),
                    },
                )

        policy_context = json.dumps(
            {
                "kind": "knowledge_source_job_finalization",
                "job_id": str(job.job_id),
                "pin_hash": claim.pins.evidence_hash(),
            }
        )
        policy_insert = text(
            """
            INSERT INTO authz.policy_decisions (
                id, workspace_id, subject_id, resource_id, action,
                effect, reason_codes, policy_versions,
                evaluation_context, request_id, decided_at
            ) VALUES (
                :id, :workspace_id, :actor_id, :graph_id, 'kg.edit',
                'ALLOW', '["POLICY_ALLOW"]'::jsonb,
                '["builtin-abac-v3"]'::jsonb,
                CAST(:context AS jsonb), :request_id, clock_timestamp()
            )
            """
        )
        async with worker.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text(
                        """
                        SELECT
                            set_config('app.workspace_id', :workspace_id, true),
                            set_config('app.subject_id', :subject_id, true),
                            set_config('app.knowledge_source_job_id', :job_id, true),
                            set_config(
                                'app.knowledge_source_lease_token',
                                :lease_token,
                                true
                            )
                        """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "subject_id": str(_WORKER_SUBJECT_ID),
                        "job_id": str(job.job_id),
                        "lease_token": claim.lease_token,
                    },
                )
                policy_parameters = {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "actor_id": actor_id,
                    "graph_id": graph_id,
                    "context": policy_context,
                    "request_id": str(job.job_id),
                }
                await connection.execute(policy_insert, policy_parameters)
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():
                        await connection.execute(
                            policy_insert,
                            {**policy_parameters, "id": uuid4()},
                        )

        tampered_event_id = uuid4()
        async with worker.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text(
                        """
                        SELECT
                            set_config('app.workspace_id', :workspace_id, true),
                            set_config('app.subject_id', :subject_id, true),
                            set_config('app.knowledge_source_job_id', :job_id, true),
                            set_config(
                                'app.knowledge_source_lease_token',
                                :lease_token,
                                true
                            )
                        """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "subject_id": str(_WORKER_SUBJECT_ID),
                        "job_id": str(job.job_id),
                        "lease_token": claim.lease_token,
                    },
                )
                renewed_at = await connection.scalar(
                    text(
                        """
                        UPDATE knowledge.source_analysis_jobs
                        SET stage = 'PARSED',
                            progress = '{"completed_pages": 1, "total_pages": 1}'::jsonb,
                            lease_expires_at = clock_timestamp() + interval '5 minutes',
                            updated_at = clock_timestamp(),
                            version = version + 1
                        WHERE workspace_id = :workspace_id AND id = :job_id
                        RETURNING updated_at
                        """
                    ),
                    {"workspace_id": workspace_id, "job_id": job.job_id},
                )
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.source_analysis_attempts
                        SET stage = 'PARSED'
                        WHERE workspace_id = :workspace_id AND id = :attempt_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "attempt_id": claim.attempt_id,
                    },
                )
                renewal_event_insert = text(
                    """
                    INSERT INTO knowledge.source_analysis_events (
                        id, workspace_id, job_id, sequence, attempt_id,
                        event_type, actor_ref, reason_code, evidence_hash,
                        details, occurred_at
                    ) VALUES (
                        :id, :workspace_id, :job_id, :sequence, :attempt_id,
                        'LEASE_RENEWED', :actor_ref, NULL, :evidence_hash,
                        '{"stage": "PARSED", "progress": {
                            "completed_pages": 1, "total_pages": 1
                        }}'::jsonb,
                        :occurred_at
                    )
                    """
                )
                renewal_parameters = {
                    "id": tampered_event_id,
                    "workspace_id": workspace_id,
                    "job_id": job.job_id,
                    "sequence": 3,
                    "attempt_id": claim.attempt_id,
                    "actor_ref": f"worker:{claim.worker_fingerprint}",
                    "evidence_hash": "0" * 64,
                    "occurred_at": renewed_at,
                }
                await connection.execute(renewal_event_insert, renewal_parameters)
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():
                        await connection.execute(
                            renewal_event_insert,
                            {
                                **renewal_parameters,
                                "id": uuid4(),
                                "sequence": 4,
                                "evidence_hash": "1" * 64,
                            },
                        )

        async with owner.connect() as connection:
            stored_hash, recomputed_hash = (
                await connection.execute(
                    text(
                        """
                        SELECT event.evidence_hash,
                               encode(
                                   sha256(
                                       convert_to(
                                           jsonb_build_object(
                                               'job_id', event.job_id,
                                               'sequence', event.sequence,
                                               'attempt_id', event.attempt_id,
                                               'event_type', event.event_type,
                                               'actor_ref', event.actor_ref,
                                               'reason_code', event.reason_code,
                                               'details', event.details,
                                               'occurred_at', event.occurred_at
                                           )::text,
                                           'UTF8'
                                       )
                                   ),
                                   'hex'
                               )
                        FROM knowledge.source_analysis_events AS event
                        WHERE event.id = :event_id
                        """
                    ),
                    {"event_id": tampered_event_id},
                )
            ).one()
            assert stored_hash == recomputed_hash
            assert stored_hash != "0" * 64

        outbox_insert = text(
            """
            INSERT INTO integration.outbox_events (
                id, workspace_id, aggregate_type, aggregate_id,
                event_type, schema_version, payload, created_at,
                published_at, dead_lettered_at, lease_until,
                attempts, last_error_code
            ) VALUES (
                :id, :workspace_id, 'knowledge_source_analysis_job',
                :job_id, 'knowledge.source-analysis.failed.v1',
                :schema_version, CAST(:payload AS jsonb), :created_at,
                :published_at, :dead_lettered_at, :lease_until,
                :attempts, :last_error_code
            )
            """
        )
        outbox_id = uuid4()
        async with worker.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text(
                        """
                        SELECT
                            set_config('app.workspace_id', :workspace_id, true),
                            set_config('app.subject_id', :subject_id, true),
                            set_config('app.knowledge_source_job_id', :job_id, true),
                            set_config(
                                'app.knowledge_source_lease_token',
                                :lease_token,
                                true
                            )
                        """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "subject_id": str(_WORKER_SUBJECT_ID),
                        "job_id": str(job.job_id),
                        "lease_token": claim.lease_token,
                    },
                )
                terminal_at = await connection.scalar(text("SELECT clock_timestamp()"))
                await connection.execute(
                    text(
                        """
                        UPDATE knowledge.source_analysis_attempts
                        SET state = 'FAILED', stage = 'COMPLETED',
                            retryable = false, failure_code = 'TEST_COMPLETE',
                            finished_at = :terminal_at
                        WHERE workspace_id = :workspace_id AND id = :attempt_id
                        """
                    ),
                    {
                        "terminal_at": terminal_at,
                        "workspace_id": workspace_id,
                        "attempt_id": claim.attempt_id,
                    },
                )
                version = await connection.scalar(
                    text(
                        """
                        UPDATE knowledge.source_analysis_jobs
                        SET state = 'FAILED', stage = 'COMPLETED',
                            lease_token_hash = NULL,
                            lease_owner_fingerprint = NULL,
                            lease_started_at = NULL,
                            lease_expires_at = NULL,
                            last_failure_code = 'TEST_COMPLETE',
                            completed_at = :terminal_at,
                            updated_at = :terminal_at,
                            version = version + 1
                        WHERE workspace_id = :workspace_id AND id = :job_id
                        RETURNING version
                        """
                    ),
                    {
                        "terminal_at": terminal_at,
                        "workspace_id": workspace_id,
                        "job_id": job.job_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO knowledge.source_analysis_events (
                            id, workspace_id, job_id, sequence, attempt_id,
                            event_type, actor_ref, reason_code, evidence_hash,
                            details, occurred_at
                        ) VALUES (
                            :id, :workspace_id, :job_id, 4, :attempt_id,
                            'FAILED', :actor_ref, 'TEST_COMPLETE', :evidence_hash,
                            '{"retryable": false}'::jsonb, :occurred_at
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "job_id": job.job_id,
                        "attempt_id": claim.attempt_id,
                        "actor_ref": f"worker:{claim.worker_fingerprint}",
                        "evidence_hash": "2" * 64,
                        "occurred_at": terminal_at,
                    },
                )
                payload = json.dumps(
                    {
                        "job_id": str(job.job_id),
                        "graph_id": str(graph_id),
                        "state": "FAILED",
                        "version": version,
                    }
                )
                canonical_outbox = {
                    "id": outbox_id,
                    "workspace_id": workspace_id,
                    "job_id": job.job_id,
                    "schema_version": 1,
                    "payload": payload,
                    "created_at": terminal_at + timedelta(days=1),
                    "published_at": None,
                    "dead_lettered_at": None,
                    "lease_until": None,
                    "attempts": 0,
                    "last_error_code": None,
                }
                mutations = (
                    {"schema_version": 2},
                    {"published_at": terminal_at},
                    {"dead_lettered_at": terminal_at},
                    {"lease_until": terminal_at + timedelta(minutes=1)},
                    {"attempts": 1},
                    {"last_error_code": "FORGED"},
                )
                for mutation in mutations:
                    with pytest.raises(DBAPIError, match="outbox evidence"):
                        async with connection.begin_nested():
                            await connection.execute(
                                outbox_insert,
                                {
                                    **canonical_outbox,
                                    **mutation,
                                    "id": uuid4(),
                                },
                            )
                await connection.execute(outbox_insert, canonical_outbox)
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():
                        await connection.execute(
                            outbox_insert,
                            {**canonical_outbox, "id": uuid4()},
                        )

        async with owner.connect() as connection:
            outbox_row = (
                await connection.execute(
                    text(
                        """
                        SELECT created_at, published_at, dead_lettered_at,
                               lease_until, attempts, last_error_code
                        FROM integration.outbox_events
                        WHERE id = :outbox_id
                        """
                    ),
                    {"outbox_id": outbox_id},
                )
            ).one()
            assert tuple(outbox_row) == (terminal_at, None, None, None, 0, None)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_set_role_cannot_impersonate_a_direct_knowledge_worker_session() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    try:
        workspace_id, _, _, _, _ = await _seed(owner)
        async with owner.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(workspace_id)},
            )
            await connection.execute(text("SET LOCAL ROLE datariver_knowledge"))
            with pytest.raises(DBAPIError, match="direct worker session"):
                await connection.execute(
                    text(
                        """
                        INSERT INTO integration.inbox_messages
                            (workspace_id, consumer, event_id, received_at)
                        VALUES
                            (:workspace_id, 'knowledge-source-analysis-v1',
                             :event_id, clock_timestamp())
                        """
                    ),
                    {"workspace_id": workspace_id, "event_id": uuid4()},
                )
    finally:
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_other_service_roles_cannot_forge_knowledge_shared_evidence() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=_binding("embed", "a"),
            extraction=_binding("extract", "b"),
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-shared-namespace",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id
        inbox_event_id = uuid4()
        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true),
                        set_config(
                            'app.knowledge_source_lease_token',
                            :lease_token,
                            true
                        )
                    """
                ),
                {
                    "workspace_id": str(workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                    "lease_token": claim.lease_token,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.inbox_messages (
                        workspace_id, consumer, event_id, received_at
                    ) VALUES (
                        :workspace_id, 'knowledge-source-analysis-v1',
                        :event_id, clock_timestamp()
                    )
                    """
                ),
                {"workspace_id": workspace_id, "event_id": inbox_event_id},
            )

        role_cases = (
            (
                "datariver_upload",
                text(
                    """
                    INSERT INTO integration.outbox_events (
                        id, workspace_id, aggregate_type, aggregate_id,
                        event_type, schema_version, payload, created_at,
                        attempts
                    ) VALUES (
                        :id, :workspace_id, 'knowledge_source_analysis_job',
                        :job_id, 'knowledge.source-analysis.failed.v1', 1,
                        CAST(:payload AS jsonb), clock_timestamp(), 0
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "job_id": job.job_id,
                    "payload": json.dumps(
                        {
                            "job_id": str(job.job_id),
                            "graph_id": str(graph_id),
                            "state": "FAILED",
                            "version": 99,
                        }
                    ),
                },
                "unauthorized producer",
            ),
            (
                "datariver_governance",
                text(
                    """
                    INSERT INTO authz.policy_decisions (
                        id, workspace_id, subject_id, resource_id, action,
                        effect, reason_codes, policy_versions,
                        evaluation_context, request_id, decided_at
                    ) VALUES (
                        :id, :workspace_id, :actor_id, :graph_id, 'kg.edit',
                        'ALLOW', '["POLICY_ALLOW"]'::jsonb,
                        '["builtin-abac-v3"]'::jsonb,
                        CAST(:context AS jsonb), :request_id, clock_timestamp()
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "actor_id": actor_id,
                    "graph_id": graph_id,
                    "context": json.dumps(
                        {
                            "kind": "knowledge_source_job_finalization",
                            "job_id": str(job.job_id),
                            "pin_hash": claim.pins.evidence_hash(),
                        }
                    ),
                    "request_id": str(job.job_id),
                },
                "unauthorized producer",
            ),
            (
                "datariver_governance",
                text(
                    """
                    UPDATE integration.inbox_messages
                    SET completed_at = clock_timestamp(),
                        result_hash = :result_hash
                    WHERE workspace_id = :workspace_id
                      AND consumer = 'knowledge-source-analysis-v1'
                      AND event_id = :event_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "event_id": inbox_event_id,
                    "result_hash": "f" * 64,
                },
                "unauthorized consumer",
            ),
        )
        for role, statement, parameters, expected_message in role_cases:
            async with owner.connect() as connection:
                async with connection.begin():
                    await connection.execute(
                        text(
                            """
                            SELECT
                                set_config('app.workspace_id', :workspace_id, true),
                                set_config('app.subject_id', :subject_id, true)
                            """
                        ),
                        {
                            "workspace_id": str(workspace_id),
                            "subject_id": str(actor_id),
                        },
                    )
                    await connection.execute(text(f"SET LOCAL ROLE {role}"))
                    with pytest.raises(DBAPIError, match=expected_message):
                        async with connection.begin_nested():
                            await connection.execute(statement, parameters)

        async with owner.connect() as connection:
            outbox_id = await connection.scalar(
                text(
                    """
                    SELECT id
                    FROM integration.outbox_events
                    WHERE workspace_id = :workspace_id
                      AND aggregate_type = 'knowledge_source_analysis_job'
                      AND aggregate_id = :job_id
                      AND event_type = 'knowledge.source-analysis.queued.v1'
                    """
                ),
                {"workspace_id": workspace_id, "job_id": job.job_id},
            )
        assert outbox_id is not None
        async with owner.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                    {"workspace_id": str(workspace_id)},
                )
                await connection.execute(text("SET LOCAL ROLE datariver_relay"))
                with pytest.raises(DBAPIError, match="transition evidence is immutable"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                UPDATE integration.outbox_events
                                SET payload = '{"forged": true}'::jsonb
                                WHERE id = :id
                                """
                            ),
                            {"id": outbox_id},
                        )
                await connection.execute(
                    text(
                        """
                        UPDATE integration.outbox_events
                        SET attempts = attempts + 1,
                            lease_until = clock_timestamp() + interval '1 minute'
                        WHERE id = :id
                        """
                    ),
                    {"id": outbox_id},
                )

        async with owner.connect() as connection:
            payload, attempts, lease_until = (
                await connection.execute(
                    text(
                        """
                        SELECT payload, attempts, lease_until
                        FROM integration.outbox_events
                        WHERE id = :id
                        """
                    ),
                    {"id": outbox_id},
                )
            ).one()
            assert payload["job_id"] == str(job.job_id)
            assert attempts == 1
            assert lease_until is not None
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_phase5_role_reconciliation_rejects_inbound_worker_membership() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    role_name = "datariver_phase5_inbound_test"
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0054_add_durable_knowledge_source_jobs.py"
    )
    role_assertion = str(runpy.run_path(str(migration_path))["_RLS_SQL"]).split(
        "-- datariver-statement-boundary",
        maxsplit=1,
    )[0]
    try:
        async with owner.begin() as connection:
            await connection.execute(text(f"DROP ROLE IF EXISTS {role_name}"))
            await connection.execute(text(f"CREATE ROLE {role_name} NOLOGIN"))
            await connection.execute(text(f"GRANT datariver_knowledge TO {role_name}"))
        async with owner.begin() as connection:
            with pytest.raises(DBAPIError, match="must not be assumable"):
                await connection.execute(text(role_assertion))
    finally:
        async with owner.begin() as connection:
            await connection.execute(text(f"REVOKE datariver_knowledge FROM {role_name}"))
            await connection.execute(text(f"DROP ROLE {role_name}"))
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_finalize_commits_exact_typed_draft_and_terminal_evidence() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(sessions, worker_subject_id=_WORKER_SUBJECT_ID)
        claim = await store.claim_next(
            worker_fingerprint="worker-finalize",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        page = PdfPage.create(page_number=1, text="asset one")
        analysis = KnowledgeSourceAnalysis(
            source=claim.source,
            pages=(page,),
            embeddings=EmbeddingBatch(
                binding=embedding,
                embeddings=(PageEmbedding(page_number=1, vector=(0.1, 0.2)),),
                input_tokens=2,
            ),
            extraction=ExtractionDraft(
                binding=extraction,
                nodes=(
                    ExtractedNodeDraft(
                        local_key="AssetOne",
                        entity_type="Asset",
                        properties={"name": "asset one"},
                        classification=1,
                        page_number=1,
                        evidence_text="asset one",
                        confidence=0.9,
                    ),
                ),
                edges=(),
                input_tokens=2,
                output_tokens=2,
            ),
        )
        result = await store.finalize(
            claim=claim,
            analysis=analysis,
            current_embedding_binding=embedding,
            current_extraction_binding=extraction,
        )
        assert result.state.value == "SUCCEEDED"
        assert result.result is not None
        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT job.state, attempt.state, changeset.state,
                               changeset.source_analysis_job_id,
                               extraction.contract_version,
                               source.state
                        FROM knowledge.source_analysis_jobs AS job
                        JOIN knowledge.source_analysis_attempts AS attempt
                          ON attempt.workspace_id = job.workspace_id
                         AND attempt.job_id = job.id
                        JOIN knowledge.changesets AS changeset
                          ON changeset.workspace_id = job.workspace_id
                         AND changeset.id = job.result_changeset_id
                        JOIN knowledge.extraction_runs AS extraction
                          ON extraction.workspace_id = job.workspace_id
                         AND extraction.source_analysis_job_id = job.id
                        JOIN knowledge.source_snapshots AS source
                          ON source.workspace_id = job.workspace_id
                         AND source.id = job.source_snapshot_id
                        WHERE job.id = :job_id
                        """
                    ),
                    {"job_id": job.job_id},
                )
            ).one()
            assert tuple(row) == (
                "SUCCEEDED",
                "SUCCEEDED",
                "DRAFT",
                job.job_id,
                "DURABLE_SOURCE_V1",
                "ANALYZED",
            )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_requester_revocation_makes_finalize_stale_without_canonical_rows() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-revoked-requester",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id

        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET active = false,
                        updated_at = clock_timestamp(),
                        version = version + 1
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :actor_id
                    """
                ),
                {"workspace_id": workspace_id, "actor_id": actor_id},
            )

        drift_code = await store.ensure_current(
            claim=claim,
            current_embedding_binding=embedding,
            current_extraction_binding=extraction,
        )
        assert drift_code == "STALE_REQUESTER_AUTHORIZATION"
        await store.mark_stale(
            claim=claim,
            failure_code=drift_code,
        )

        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT job.state, job.stage, job.last_failure_code,
                               job.result_changeset_id, job.result_evidence_hash,
                               attempt.state, attempt.stage, attempt.failure_code,
                               source.state,
                               (
                                   SELECT count(*)
                                   FROM knowledge.source_pages AS page
                                   WHERE page.workspace_id = job.workspace_id
                                     AND page.source_snapshot_id = source.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.source_page_embeddings AS embedding
                                   WHERE embedding.workspace_id = job.workspace_id
                                     AND embedding.source_snapshot_id = source.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.changesets AS changeset
                                   WHERE changeset.workspace_id = job.workspace_id
                                     AND changeset.source_analysis_job_id = job.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.change_operations AS operation
                                   JOIN knowledge.changesets AS changeset
                                     ON changeset.workspace_id = operation.workspace_id
                                    AND changeset.id = operation.changeset_id
                                   WHERE changeset.workspace_id = job.workspace_id
                                     AND changeset.source_analysis_job_id = job.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.extraction_runs AS extraction
                                   WHERE extraction.workspace_id = job.workspace_id
                                     AND extraction.source_analysis_job_id = job.id
                               )
                        FROM knowledge.source_analysis_jobs AS job
                        JOIN knowledge.source_analysis_attempts AS attempt
                          ON attempt.workspace_id = job.workspace_id
                         AND attempt.job_id = job.id
                         AND attempt.lease_epoch = job.lease_epoch
                        JOIN knowledge.source_snapshots AS source
                          ON source.workspace_id = job.workspace_id
                         AND source.id = job.source_snapshot_id
                        WHERE job.workspace_id = :workspace_id
                          AND job.id = :job_id
                        """
                    ),
                    {"workspace_id": workspace_id, "job_id": job.job_id},
                )
            ).one()
            assert tuple(row) == (
                "STALE",
                "COMPLETED",
                "STALE_REQUESTER_AUTHORIZATION",
                None,
                None,
                "STALE",
                "COMPLETED",
                "STALE_REQUESTER_AUTHORIZATION",
                "PENDING",
                0,
                0,
                0,
                0,
                0,
            )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_mid_finalize_failure_rolls_back_every_canonical_write() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    trigger_suffix = uuid4().hex
    trigger_name = f"source_analysis_test_failure_{trigger_suffix}"
    function_name = f"source_analysis_test_failure_{trigger_suffix}"
    trigger_created = False
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        embedding, extraction = _binding("embed", "a"), _binding("extract", "b")
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=embedding,
            extraction=extraction,
        )
        sessions = async_sessionmaker(worker, expire_on_commit=False)
        store = SqlKnowledgeSourceJobWorkerStore(
            sessions,
            worker_subject_id=_WORKER_SUBJECT_ID,
        )
        claim = await store.claim_next(
            worker_fingerprint="worker-controlled-db-failure",
            lease_seconds=300,
            maximum_attempts=3,
        )
        assert claim is not None
        assert claim.job.job_id == job.job_id

        async with owner.begin() as connection:
            await connection.execute(
                text(
                    f"""
                    CREATE FUNCTION knowledge.{function_name}()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $function$
                    BEGIN
                        IF NEW.workspace_id::text = TG_ARGV[0]
                           AND NEW.source_analysis_job_id::text = TG_ARGV[1] THEN
                            RAISE EXCEPTION 'controlled source analysis finalize failure'
                                USING ERRCODE = 'P0001';
                        END IF;
                        RETURN NEW;
                    END
                    $function$
                    """
                )
            )
            await connection.execute(
                text(
                    f"""
                    CREATE TRIGGER {trigger_name}
                    BEFORE INSERT ON knowledge.extraction_runs
                    FOR EACH ROW
                    EXECUTE FUNCTION knowledge.{function_name}(
                        '{workspace_id}', '{job.job_id}'
                    )
                    """
                )
            )
        trigger_created = True

        with pytest.raises(DBAPIError, match="controlled source analysis finalize failure"):
            await store.finalize(
                claim=claim,
                analysis=_analysis(
                    claim=claim,
                    embedding=embedding,
                    extraction=extraction,
                ),
                current_embedding_binding=embedding,
                current_extraction_binding=extraction,
            )

        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT job.state, job.stage, job.result_changeset_id,
                               job.result_evidence_hash, job.completed_at,
                               attempt.state, attempt.stage, attempt.output_hash,
                               attempt.finished_at, source.state,
                               (
                                   SELECT count(*)
                                   FROM knowledge.source_pages AS page
                                   WHERE page.workspace_id = job.workspace_id
                                     AND page.source_snapshot_id = source.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.source_page_embeddings AS embedding
                                   WHERE embedding.workspace_id = job.workspace_id
                                     AND embedding.source_snapshot_id = source.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.changesets AS changeset
                                   WHERE changeset.workspace_id = job.workspace_id
                                     AND changeset.source_analysis_job_id = job.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.change_operations AS operation
                                   JOIN knowledge.changesets AS changeset
                                     ON changeset.workspace_id = operation.workspace_id
                                    AND changeset.id = operation.changeset_id
                                   WHERE changeset.workspace_id = job.workspace_id
                                     AND changeset.source_analysis_job_id = job.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM knowledge.extraction_runs AS extraction
                                   WHERE extraction.workspace_id = job.workspace_id
                                     AND extraction.source_analysis_job_id = job.id
                               ),
                               (
                                   SELECT count(*)
                                   FROM authz.policy_decisions AS decision
                                   WHERE decision.workspace_id = job.workspace_id
                                     AND decision.evaluation_context->>'job_id'
                                         = job.id::text
                               )
                        FROM knowledge.source_analysis_jobs AS job
                        JOIN knowledge.source_analysis_attempts AS attempt
                          ON attempt.workspace_id = job.workspace_id
                         AND attempt.job_id = job.id
                         AND attempt.lease_epoch = job.lease_epoch
                        JOIN knowledge.source_snapshots AS source
                          ON source.workspace_id = job.workspace_id
                         AND source.id = job.source_snapshot_id
                        WHERE job.workspace_id = :workspace_id
                          AND job.id = :job_id
                        """
                    ),
                    {"workspace_id": workspace_id, "job_id": job.job_id},
                )
            ).one()
            assert tuple(row) == (
                "RUNNING",
                "SOURCE_READ",
                None,
                None,
                None,
                "RUNNING",
                "SOURCE_READ",
                None,
                None,
                "PENDING",
                0,
                0,
                0,
                0,
                0,
                0,
            )
            terminal_event_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM knowledge.source_analysis_events
                    WHERE workspace_id = :workspace_id
                      AND job_id = :job_id
                      AND event_type IN ('SUCCEEDED', 'STALE', 'FAILED', 'CANCELLED')
                    """
                ),
                {"workspace_id": workspace_id, "job_id": job.job_id},
            )
            terminal_outbox_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM integration.outbox_events
                    WHERE workspace_id = :workspace_id
                      AND aggregate_type = 'knowledge_source_analysis_job'
                      AND aggregate_id = :job_id
                      AND event_type IN (
                          'knowledge.source-analysis.succeeded.v1',
                          'knowledge.source-analysis.stale.v1',
                          'knowledge.source-analysis.failed.v1',
                          'knowledge.source-analysis.cancelled.v1'
                      )
                    """
                ),
                {"workspace_id": workspace_id, "job_id": job.job_id},
            )
            assert terminal_event_count == 0
            assert terminal_outbox_count == 0
        await store.mark_failed(
            claim=claim,
            failure_code="TEST_COMPLETE",
            retryable=False,
        )
    finally:
        if trigger_created:
            async with owner.begin() as connection:
                await connection.execute(
                    text(
                        f"""
                        DROP TRIGGER IF EXISTS {trigger_name}
                        ON knowledge.extraction_runs
                        """
                    )
                )
                await connection.execute(
                    text(f"DROP FUNCTION IF EXISTS knowledge.{function_name}()")
                )
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_app_and_worker_direct_reads_cannot_cross_workspace_boundary() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        other_workspace_id, other_actor_id, _, _, _ = await _seed(owner)
        job = await _enqueue(
            app,
            workspace_id=workspace_id,
            actor_id=actor_id,
            graph_id=graph_id,
            upload_id=upload_id,
            embedding=_binding("embed", "a"),
            extraction=_binding("extract", "b"),
        )

        async with app.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true)
                    """
                ),
                {
                    "workspace_id": str(other_workspace_id),
                    "subject_id": str(other_actor_id),
                },
            )
            app_visible = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM knowledge.source_analysis_jobs
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job.job_id},
            )
            assert app_visible == 0

        async with worker.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT
                        set_config('app.workspace_id', :workspace_id, true),
                        set_config('app.subject_id', :subject_id, true),
                        set_config('app.knowledge_source_job_id', :job_id, true)
                    """
                ),
                {
                    "workspace_id": str(other_workspace_id),
                    "subject_id": str(_WORKER_SUBJECT_ID),
                    "job_id": str(job.job_id),
                },
            )
            worker_visible = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM knowledge.source_analysis_jobs
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job.job_id},
            )
            assert worker_visible == 0
        app_sessions = async_sessionmaker(app, expire_on_commit=False)
        async with app_sessions() as session:
            cancelled = await SqlKnowledgeSourceJobStore(session).cancel(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=job.job_id,
                actor_id=actor_id,
                expected_version=job.version,
                reason="Cross-workspace isolation test complete",
                request_hash="f" * 64,
                idempotency_key=f"cancel-{job.job_id}",
            )
        assert cancelled.state.value == "CANCELLED"
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge source PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_oversize_accepted_pdf_is_rejected_before_any_job_evidence() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        workspace_id, actor_id, _, graph_id, upload_id = await _seed(owner)
        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE integration.object_manifests
                    SET size_bytes = :oversize,
                        actual_size_bytes = :oversize,
                        updated_at = clock_timestamp(),
                        version = version + 1
                    WHERE workspace_id = :workspace_id
                      AND id = :upload_id
                    """
                ),
                {
                    "oversize": MAX_SOURCE_BYTES + 1,
                    "workspace_id": workspace_id,
                    "upload_id": upload_id,
                },
            )

        with pytest.raises(
            ValidationError,
            match=r"integrity-verified accepted Knowledge document.*within 50 MiB",
        ):
            await _enqueue(
                app,
                workspace_id=workspace_id,
                actor_id=actor_id,
                graph_id=graph_id,
                upload_id=upload_id,
                embedding=_binding("embed", "a"),
                extraction=_binding("extract", "b"),
            )

        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (
                                SELECT count(*)
                                FROM knowledge.source_snapshots
                                WHERE workspace_id = :workspace_id
                                  AND upload_id = :upload_id
                            ),
                            (
                                SELECT count(*)
                                FROM knowledge.source_analysis_jobs
                                WHERE workspace_id = :workspace_id
                            ),
                            (
                                SELECT count(*)
                                FROM knowledge.source_analysis_events
                                WHERE workspace_id = :workspace_id
                            ),
                            (
                                SELECT count(*)
                                FROM integration.outbox_events
                                WHERE workspace_id = :workspace_id
                                  AND aggregate_type
                                      = 'knowledge_source_analysis_job'
                            )
                        """
                    ),
                    {"workspace_id": workspace_id, "upload_id": upload_id},
                )
            ).one()
            assert tuple(row) == (0, 0, 0, 0)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose(), worker.dispose())
