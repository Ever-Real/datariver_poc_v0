from __future__ import annotations

import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from datariver.application.services.knowledge_studio_proposal_jobs import (
    KnowledgeStudioProposalJobService,
)
from datariver.domain.authz import Action, Classification, SubjectAttributes
from datariver.domain.common import canonical_json_hash
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio import TBoxProposalMode
from datariver.domain.knowledge_studio_proposal_jobs import (
    KnowledgeStudioAcceptedUploadPin,
    KnowledgeStudioProposalInputKind,
    KnowledgeStudioProposalJobPins,
    knowledge_studio_proposal_requester_authorization_hash,
)
from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SIGNATURES,
    TBOX_PROPOSAL_JOB_INTERNAL_FUNCTION_SIGNATURES,
    TBOX_PROPOSAL_JOB_WORKER_FUNCTION_SIGNATURES,
)
from datariver.infrastructure.db.knowledge_studio_proposal_jobs import (
    SqlKnowledgeStudioProposalJobStore,
    SqlKnowledgeStudioProposalJobWorkerStore,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.secrets import SecretResolver

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0084_governed_knowledge_studio_tbox_proposal_jobs.py"

_OWNER_URL = "DATARIVER_KNOWLEDGE_PROPOSAL_TEST_OWNER_DATABASE_URL"
_OWNER_SECRET = "DATARIVER_KNOWLEDGE_PROPOSAL_TEST_OWNER_SECRET_REF"
_APP_URL = "DATARIVER_KNOWLEDGE_PROPOSAL_TEST_APP_DATABASE_URL"
_APP_SECRET = "DATARIVER_KNOWLEDGE_PROPOSAL_TEST_APP_SECRET_REF"
_WORKER_URL = "DATARIVER_KNOWLEDGE_PROPOSAL_TEST_WORKER_DATABASE_URL"
_WORKER_SECRET = "DATARIVER_KNOWLEDGE_PROPOSAL_TEST_WORKER_SECRET_REF"
_CONFIRM = "DATARIVER_KNOWLEDGE_PROPOSAL_TEST_CONFIRM_ISOLATED"
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


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_knowledge_proposal_0084", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _engine(url_env: str, secret_env: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[url_env],
        connect_args={
            "password": SecretResolver().resolve(os.environ[secret_env]),
            "server_settings": {"application_name": f"datariver-knowledge-proposal-{uuid4().hex}"},
        },
    )


def test_revision_0084_declares_the_exact_function_only_contract() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    signatures = (
        *TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SIGNATURES,
        *TBOX_PROPOSAL_JOB_WORKER_FUNCTION_SIGNATURES,
        *TBOX_PROPOSAL_JOB_INTERNAL_FUNCTION_SIGNATURES,
    )

    assert 'revision: str = "0084"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0083"' in migration
    assert len(signatures) == len(set(signatures)) == 26
    assert "datariver_knowledge_proposal" in migration
    assert migration.count("FORCE ROW LEVEL SECURITY") == 3
    assert "REVOKE ALL PRIVILEGES ON knowledge.tbox_proposal_jobs" in migration
    assert "GRANT EXECUTE ON FUNCTION knowledge.claim_tbox_proposal_job_v1" in migration
    assert "GRANT EXECUTE ON FUNCTION knowledge.complete_tbox_proposal_job_v1" in migration
    assert "GRANT SELECT ON knowledge.tbox_proposal" not in migration
    assert "legacy_prompt_hash" in migration
    assert "prompt = 'Governed Schema Assistant proposal'" in migration
    assert "ck_tbox_proposal_jobs_terminal_completion" in migration
    assert "ck_tbox_proposal_jobs_terminal_stage" in migration
    assert "ck_tbox_proposal_jobs_state_progress" in migration


def test_proposal_sql_is_fenced_bounded_and_split_at_top_level_only() -> None:
    migration = _migration()
    statements = migration.split_postgresql_statements(TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL)

    assert len(statements) == 26
    assert not {
        bind_name for statement in statements for bind_name in text(statement).compile().params
    }
    assert "FOR UPDATE SKIP LOCKED" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "lease_token_hash" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "lease_epoch" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "worker_fingerprint" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "current_tbox_proposal_authorization_hash_v1" in (TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL)
    assert "STALE_MODEL_BINDING" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "STALE_SOURCE" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "RETURN 'CANCELLED'" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "'READY'" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "knowledge.emit_tbox_proposal_outbox_v1" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "source_locator" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "'bucket', manifest.bucket" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    assert "INSERT INTO knowledge.tbox_proposal_jobs" in TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL
    job_insert = TBOX_PROPOSAL_JOB_ALL_FUNCTION_SQL.split(
        "INSERT INTO knowledge.tbox_proposal_jobs", maxsplit=1
    )[1].split(");", maxsplit=1)[0]
    assert "bucket" not in job_insert
    assert "object_key" not in job_insert


def _subject(workspace_id: UUID, actor_id: UUID) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=actor_id,
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


async def _seed(owner: AsyncEngine) -> tuple[UUID, UUID, UUID, UUID, UUID, int, str]:
    workspace_id, actor_id, worker_id, domain_id, draft_id, upload_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC)
    parser_hash = "b" * 64
    source_hash = "c" * 64
    human_attributes = {
        "groups": ["data-stewards"],
        "allowed_actions": ["kg.edit", "kg.read"],
        "denied_actions": [],
        "allowed_system_ids": [],
        "allowed_domain_ids": [],
    }
    worker_attributes = {
        "groups": ["service-accounts", "knowledge-proposal-workers"],
        "allowed_actions": ["kg.proposal.execute"],
        "denied_actions": [],
        "allowed_system_ids": [],
        "allowed_domain_ids": [],
    }
    validation_summary = {
        "validator_version": "knowledge-studio-document-validator-v1",
        "size_bytes": 18,
        "sha256": source_hash,
        "content_type": "text/plain",
        "content_profile": "KNOWLEDGE_STUDIO_DOCUMENT_V1",
        "parser_version": "knowledge-studio-document-parser-v1",
        "profile_configuration_hash": parser_hash,
    }
    async with owner.begin() as connection:
        assert (
            await connection.scalar(text("SELECT version_num FROM alembic_version"))
            == REQUIRED_DATABASE_REVISION
        )
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, created_at, updated_at, version)
                VALUES
                    (:id, :slug, 'Proposal test', 'ACTIVE', '{}'::jsonb,
                     :now, :now, 1)
                """
            ),
            {"id": workspace_id, "slug": f"proposal-{workspace_id.hex}", "now": now},
        )
        for subject_id, label in ((actor_id, "Proposal author"), (worker_id, "Worker")):
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.subjects
                        (id, issuer, external_subject, display_name, active,
                         created_at, updated_at)
                    VALUES (:id, 'proposal-test', :external, :label, true, :now, :now)
                    """
                ),
                {
                    "id": subject_id,
                    "external": str(subject_id),
                    "label": label,
                    "now": now,
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO iam.workspace_memberships
                    (workspace_id, subject_id, department_id, job_function,
                     clearance, attributes, active, access_expires_at,
                     created_at, updated_at, version)
                VALUES
                    (:workspace_id, :actor_id, NULL, 'DATA_STEWARD', 1,
                     CAST(:human_attributes AS jsonb), true, NULL, :now, :now, 1),
                    (:workspace_id, :worker_id, NULL, 'SERVICE_ACCOUNT', 3,
                     CAST(:worker_attributes AS jsonb), true, NULL, :now, :now, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "worker_id": worker_id,
                "human_attributes": json.dumps(human_attributes),
                "worker_attributes": json.dumps(worker_attributes),
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.vocabulary_entries
                    (id, workspace_id, kind, provider_ref, display_name, lifecycle,
                     source_version, observed_at, created_by, version, updated_at)
                VALUES
                    (:id, :workspace_id, 'DOMAIN', :provider_ref, 'Proposal domain',
                     'ACTIVE', 'v1', :now, :actor_id, 1, :now)
                """
            ),
            {
                "id": domain_id,
                "workspace_id": workspace_id,
                "provider_ref": f"urn:li:domain:proposal-{domain_id}",
                "actor_id": actor_id,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.studio_drafts
                    (id, workspace_id, author_id, kind, state, current_step, name,
                     endpoint_alias, endpoint_aliases, domain_ref_id, domain_ref_kind,
                     domain_source_version, classification, base_graph_id,
                     base_ontology_version_id, base_release_id, last_autosaved_at,
                     created_at, updated_at, version)
                VALUES
                    (:id, :workspace_id, :actor_id, 'CREATE', 'DRAFT', 'TBOX',
                     'Proposal draft', :alias, CAST(:aliases AS jsonb), :domain_id,
                     'DOMAIN', 'v1', 0, NULL, NULL, NULL, :now, :now, :now, 1)
                """
            ),
            {
                "id": draft_id,
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "alias": f"proposal_{draft_id.hex}",
                "aliases": json.dumps([f"proposal_{draft_id.hex}"]),
                "domain_id": domain_id,
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
                    content_profile, classification, owner_id, retention_until,
                    expires_at, created_at, updated_at, version
                ) VALUES (
                    :id, :workspace_id, 'knowledge-eligible', :object_key,
                    'schema.txt', NULL, 18, 'text/plain', :source_hash,
                    18, 'text/plain', :source_hash, NULL, 0, 1, NULL,
                    CAST(:validation_summary AS jsonb), '[]'::jsonb, 'ACCEPTED',
                    'KNOWLEDGE_STUDIO_DOCUMENT_V1', 0, :actor_id,
                    NULL, NULL, :now, :now, 1
                )
                """
            ),
            {
                "id": upload_id,
                "workspace_id": workspace_id,
                "object_key": f"knowledge/{workspace_id}/{upload_id}",
                "source_hash": source_hash,
                "validation_summary": json.dumps(validation_summary),
                "actor_id": actor_id,
                "now": now,
            },
        )
    validation_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_UPLOAD_VALIDATION_EVIDENCE_V1",
            "manifest_id": str(upload_id),
            "manifest_version": 1,
            "validation_summary": validation_summary,
        }
    )
    return workspace_id, actor_id, worker_id, draft_id, upload_id, 1, validation_hash


@pytest.mark.skipif(not _ENABLED, reason="isolated Proposal PostgreSQL test is not enabled")
@pytest.mark.asyncio
async def test_function_only_claim_and_running_cancel_are_atomically_fenced() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    worker = _engine(_WORKER_URL, _WORKER_SECRET)
    try:
        (
            workspace_id,
            actor_id,
            worker_id,
            draft_id,
            upload_id,
            version,
            validation_hash,
        ) = await _seed(owner)
        subject = _subject(workspace_id, actor_id)
        source_hash = "c" * 64
        parser_hash = "b" * 64
        binding = ModelBinding(
            provider="openai-compatible",
            model="schema-test",
            prompt_version="knowledge-v1",
            tool_schema_version="knowledge-schema-v1",
            configuration_source="DEPLOYMENT",
            configuration_version=None,
            configuration_hash="d" * 64,
        )
        pins = KnowledgeStudioProposalJobPins(
            workspace_id=workspace_id,
            draft_id=draft_id,
            requested_by=actor_id,
            input_kind=KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA,
            mode=TBoxProposalMode.APPEND_LAYER,
            target_block_id=None,
            base_draft_version=version,
            base_tbox_hash=canonical_json_hash(
                {
                    "contract": "KNOWLEDGE_STUDIO_PROPOSAL_BASE_TBOX_V1",
                    "draft_id": str(draft_id),
                    "blocks": [],
                }
            ),
            source=KnowledgeStudioAcceptedUploadPin(
                manifest_id=upload_id,
                manifest_version=1,
                content_sha256=source_hash,
                media_type="text/plain",
                size_bytes=18,
                classification=0,
                content_profile="KNOWLEDGE_STUDIO_DOCUMENT_V1",
                validation_evidence_hash=validation_hash,
                filename="schema.txt",
            ),
            parser_configuration_hash=parser_hash,
            schema_binding=binding,
            requester_authorization_hash=(
                knowledge_studio_proposal_requester_authorization_hash(subject)
            ),
            prepared_at=datetime.now(UTC),
        )
        app_sessions = async_sessionmaker(app, expire_on_commit=False)
        async with app_sessions() as session, session.begin():
            service = KnowledgeStudioProposalJobService(
                store=SqlKnowledgeStudioProposalJobStore(session)
            )
            queued = await service.enqueue(
                pins=pins,
                request_hash="e" * 64,
                maximum_attempts=3,
                idempotency_key=f"proposal-request-{uuid4()}",
            )
        worker_store = SqlKnowledgeStudioProposalJobWorkerStore(
            async_sessionmaker(worker, expire_on_commit=False)
        )
        claim = await worker_store.claim_next(
            workspace_id=workspace_id,
            worker_subject_id=worker_id,
            worker_fingerprint="proposal-worker-test",
            lease_seconds=60,
        )
        assert claim is not None
        assert claim.job.job_id == queued.job_id
        assert claim.source_locator is not None
        async with app_sessions() as session, session.begin():
            service = KnowledgeStudioProposalJobService(
                store=SqlKnowledgeStudioProposalJobStore(session)
            )
            cancelling = await service.cancel(
                workspace_id=workspace_id,
                draft_id=draft_id,
                job_id=queued.job_id,
                actor_id=actor_id,
                expected_version=claim.job.version,
                reason="Browser cancellation",
                request_hash="f" * 64,
                idempotency_key=f"proposal-cancel-{uuid4()}",
            )
        assert cancelling.state.value == "CANCEL_REQUESTED"
        assert (
            await worker_store.ensure_current(
                claim=claim,
                worker_subject_id=worker_id,
                current_schema_binding=binding,
            )
            == "CANCELLED"
        )
        async with app_sessions() as session, session.begin():
            record = await SqlKnowledgeStudioProposalJobStore(session).get_owned(
                workspace_id=workspace_id,
                draft_id=draft_id,
                job_id=queued.job_id,
                actor_id=actor_id,
            )
        assert record is not None
        assert record.state.value == "CANCELLED"
        assert record.stage.value == "COMPLETED"
        async with owner.connect() as connection:
            grants = await connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege('datariver_app',
                            'knowledge.tbox_proposal_jobs', 'INSERT,UPDATE,DELETE'),
                        has_table_privilege('datariver_knowledge_proposal',
                            'knowledge.tbox_proposal_jobs', 'SELECT,INSERT,UPDATE,DELETE'),
                        (SELECT relrowsecurity AND relforcerowsecurity
                         FROM pg_class
                         WHERE oid = 'knowledge.tbox_proposal_jobs'::regclass),
                        (SELECT count(*) FROM knowledge.tbox_proposal_attempts
                         WHERE workspace_id = :workspace_id AND job_id = :job_id
                           AND state = 'CANCELLED'),
                        (SELECT count(*) FROM integration.outbox_events
                         WHERE workspace_id = :workspace_id
                           AND aggregate_id = :job_id
                           AND event_type =
                               'knowledge.tbox-proposal-job.cancelled.v1')
                    """
                ),
                {"workspace_id": workspace_id, "job_id": queued.job_id},
            )
            app_dml, worker_dml, forced_rls, attempts, outbox = grants.one()
        assert app_dml is False
        assert worker_dml is False
        assert forced_rls is True
        assert attempts == 1
        assert outbox == 1
    finally:
        await owner.dispose()
        await app.dispose()
        await worker.dispose()
