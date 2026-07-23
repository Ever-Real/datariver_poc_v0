from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from datariver.infrastructure.secrets import SecretResolver

_DATABASE_URL_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_URL"
_SECRET_REF_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_SECRET_REF"
_CONFIRM_ISOLATED_ENV = "DATARIVER_REGISTRATION_RLS_TEST_CONFIRM_ISOLATED"
_POSTGRES_ENABLED = bool(os.getenv(_DATABASE_URL_ENV)) and os.getenv(_CONFIRM_ISOLATED_ENV) == "1"
_FUNCTION_SIGNATURE = (
    "governance.reauthorize_datahub_apply("
    "uuid,uuid,integer,text,uuid,integer,uuid,text,text,text,text,text,text,text,"
    "uuid,text,uuid,uuid,uuid,integer,text,text,text,uuid,uuid,integer,uuid,text)"
)
_PREPARATION_FUNCTION_SIGNATURE = (
    "integration.reauthorize_catalog_metadata_preparation("
    "uuid,uuid,uuid,uuid,integer,text,uuid[],boolean)"
)
_SENSITIVE_TABLES = (
    "platform.workspaces",
    "platform.data_systems",
    "iam.subjects",
    "iam.workspace_memberships",
    "catalog.assets_projection",
    "catalog.vocabulary_entries",
    "authz.classification_access_policy_versions",
    "authz.classification_access_policy_rules",
    "authz.classification_access_generations",
    "authz.restricted_search_grants",
    "governance.registration_content_bindings",
    "governance.registration_metadata_content_bindings",
    "integration.object_manifests",
    "integration.upload_preparation_jobs",
    "integration.upload_preparation_receipts",
    "integration.upload_registration_candidates",
    "integration.catalog_metadata_rows",
    "integration.catalog_metadata_candidates",
    "integration.catalog_metadata_candidate_rows",
)
_CALL = text(
    """
    SELECT governance.reauthorize_datahub_apply(
        :workspace_id,
        :change_request_id,
        :change_request_version,
        :request_type,
        :requester_id,
        :request_classification,
        :item_id,
        :action,
        :target_type,
        :target_ref,
        :operation,
        :aspect_name,
        :before_hash,
        :after_hash,
        :target_asset_id,
        :target_asset_type,
        :target_system_id,
        :target_domain_id,
        :target_owner_department_id,
        :target_classification,
        :target_lifecycle,
        :target_source_version,
        :target_binding_hash,
        :job_id,
        :attempt_id,
        :attempt_no,
        :worker_subject_id,
        :lease_token_hash
    )
    """
).bindparams(
    bindparam("workspace_id"),
    bindparam("change_request_id"),
    bindparam("change_request_version"),
    bindparam("request_type"),
    bindparam("requester_id"),
    bindparam("request_classification"),
    bindparam("item_id"),
    bindparam("action"),
    bindparam("target_type"),
    bindparam("target_ref"),
    bindparam("operation"),
    bindparam("aspect_name"),
    bindparam("before_hash"),
    bindparam("after_hash"),
    bindparam("target_asset_id"),
    bindparam("target_asset_type"),
    bindparam("target_system_id"),
    bindparam("target_domain_id"),
    bindparam("target_owner_department_id"),
    bindparam("target_classification"),
    bindparam("target_lifecycle"),
    bindparam("target_source_version"),
    bindparam("target_binding_hash"),
    bindparam("job_id"),
    bindparam("attempt_id"),
    bindparam("attempt_no"),
    bindparam("worker_subject_id"),
    bindparam("lease_token_hash"),
)
_PREPARATION_CALL = text(
    """
    SELECT integration.reauthorize_catalog_metadata_preparation(
        :workspace_id,
        :preparation_id,
        :requested_by,
        :worker_subject_id,
        :attempt,
        :lease_token_hash,
        :target_asset_ids,
        :lock_for_publication
    )
    """
)


def _engine() -> AsyncEngine:
    return create_async_engine(
        os.environ[_DATABASE_URL_ENV],
        connect_args={
            "password": SecretResolver().resolve(
                os.getenv(
                    _SECRET_REF_ENV,
                    "file:/run/secrets/postgres_password",
                )
            )
        },
    )


async def _call_as_governance(
    engine: AsyncEngine,
    parameters: dict[str, object],
) -> bool:
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE datariver_governance"))
        return bool(await connection.scalar(_CALL, parameters))


async def _call_preparation_as_app(
    engine: AsyncEngine,
    parameters: dict[str, object],
) -> bool:
    async with engine.begin() as connection:
        return await _call_preparation_on_connection(connection, parameters)


async def _call_preparation_on_connection(
    connection: AsyncConnection,
    parameters: dict[str, object],
) -> bool:
    await connection.execute(text("SET LOCAL ROLE datariver_app"))
    return bool(await connection.scalar(_PREPARATION_CALL, parameters))


async def _seed_fixture(engine: AsyncEngine) -> dict[str, object]:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    requester_id = uuid4()
    checker_id = uuid4()
    worker_id = uuid4()
    system_id = uuid4()
    asset_id = uuid4()
    request_id = uuid4()
    round_id = uuid4()
    item_id = uuid4()
    job_id = uuid4()
    attempt_id = uuid4()
    policy_id = uuid4()
    target_ref = f"urn:li:dataset:reauthorization-{asset_id}"
    policy_hash = "1" * 64
    before_hash = "2" * 64
    after_hash = "3" * 64
    binding_hash = "4" * 64
    lease_token_hash = "7" * 64
    attributes = json.dumps(
        {
            "groups": ["security-administrators"],
            "allowed_actions": ["change.create"],
            "denied_actions": [],
            "allowed_system_ids": [str(system_id)],
            "allowed_domain_ids": [],
        }
    )
    checker_attributes = json.dumps(
        {
            "groups": ["security-administrators"],
            "allowed_actions": ["change.approve"],
            "denied_actions": [],
            "allowed_system_ids": [str(system_id)],
            "allowed_domain_ids": [],
        }
    )
    worker_attributes = json.dumps(
        {
            "groups": ["service-accounts", "registration-workers"],
            "allowed_actions": ["catalog.sync"],
            "denied_actions": [],
            "allowed_system_ids": [str(system_id)],
            "allowed_domain_ids": [],
        }
    )
    async with engine.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0052"
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version)
                VALUES
                    (:workspace_id, :slug, 'Apply reauthorization test',
                     'ACTIVE', '{}'::jsonb, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "slug": f"apply-reauth-{workspace_id.hex[:12]}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.subjects
                    (id, issuer, external_subject, display_name, active)
                VALUES
                    (:requester_id, 'apply-reauth-test', :requester_external,
                     'Requester', true),
                    (:checker_id, 'apply-reauth-test', :checker_external,
                     'Checker', true),
                    (:worker_id, 'apply-reauth-test', :worker_external,
                     'Worker', true)
                """
            ),
            {
                "requester_id": requester_id,
                "requester_external": str(requester_id),
                "checker_id": checker_id,
                "checker_external": str(checker_id),
                "worker_id": worker_id,
                "worker_external": str(worker_id),
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.workspace_memberships
                    (workspace_id, subject_id, job_function, clearance,
                     attributes, active, access_expires_at, version)
                VALUES
                    (:workspace_id, :requester_id, 'SECURITY_ADMINISTRATOR', 3,
                     CAST(:attributes AS jsonb), true, :expires_at, 1),
                    (:workspace_id, :checker_id, 'SECURITY_ADMINISTRATOR', 3,
                     CAST(:checker_attributes AS jsonb), true, :expires_at, 1),
                    (:workspace_id, :worker_id, 'SERVICE_ACCOUNT', 3,
                     CAST(:worker_attributes AS jsonb), true, :expires_at, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "requester_id": requester_id,
                "checker_id": checker_id,
                "worker_id": worker_id,
                "attributes": attributes,
                "checker_attributes": checker_attributes,
                "worker_attributes": worker_attributes,
                "expires_at": now + timedelta(days=30),
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO platform.data_systems
                    (id, workspace_id, code, name, description, active, version)
                VALUES
                    (:system_id, :workspace_id, :code, 'Apply test system',
                     'Isolated PostgreSQL fixture', true, 1)
                """
            ),
            {
                "system_id": system_id,
                "workspace_id": workspace_id,
                "code": f"reauth_{system_id.hex[:12]}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.assets_projection
                    (id, workspace_id, external_urn, urn_hash, asset_type,
                     name, platform, database_name, schema_name,
                     tags, glossary_terms, column_names, system_id,
                     classification, lifecycle, source_version, observed_at,
                     projection_source)
                VALUES
                    (:asset_id, :workspace_id, :target_ref, :urn_hash, 'DATASET',
                     'orders', 'postgres', 'warehouse', 'public',
                     '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, :system_id,
                     2, 'ACTIVE', 'source-v1', :now, 'DATAHUB')
                """
            ),
            {
                "asset_id": asset_id,
                "workspace_id": workspace_id,
                "target_ref": target_ref,
                "urn_hash": asset_id.hex * 2,
                "system_id": system_id,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO authz.classification_access_policy_versions
                    (id, workspace_id, policy_number, required_jurisdiction,
                     restricted_search_grant_maximum_days, payload_hash,
                     requester_id, request_reason, request_policy_decision_id,
                     state, checker_id, decision_reason,
                     decision_policy_decision_id, decided_at, version)
                VALUES
                    (:policy_id, :workspace_id, 1, 'KR', 30, :policy_hash,
                     :requester_id, 'test policy', :request_decision_id,
                     'ACTIVE', :checker_id, 'approved',
                     :decision_id, :now, 2)
                """
            ),
            {
                "policy_id": policy_id,
                "workspace_id": workspace_id,
                "policy_hash": policy_hash,
                "requester_id": requester_id,
                "checker_id": checker_id,
                "request_decision_id": uuid4(),
                "decision_id": uuid4(),
                "now": now,
            },
        )
        for classification in range(4):
            await connection.execute(
                text(
                    """
                    INSERT INTO authz.classification_access_policy_rules
                        (id, workspace_id, policy_id, policy_hash,
                         classification, search_mode, chat_mode)
                    VALUES
                        (:id, :workspace_id, :policy_id, :policy_hash,
                         :classification, :search_mode, 'DENY')
                    """
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "policy_id": policy_id,
                    "policy_hash": policy_hash,
                    "classification": classification,
                    "search_mode": ("EXPLICIT_GRANT_ONLY" if classification == 3 else "ABAC"),
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO authz.classification_access_generations
                    (workspace_id, generation, updated_at)
                VALUES (:workspace_id, 1, :now)
                """
            ),
            {"workspace_id": workspace_id, "now": now},
        )
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await connection.execute(
            text(
                """
                INSERT INTO governance.change_requests
                    (id, workspace_id, number, request_type, title, description,
                     state, requester_id, current_round_id,
                     current_round_number, classification, version)
                VALUES
                    (:request_id, :workspace_id, :number, 'CATALOG_DESCRIPTION',
                     'Apply reauthorization', 'Integration test',
                     'APPLYING', :requester_id, :round_id, 1, 2, 7)
                """
            ),
            {
                "request_id": request_id,
                "workspace_id": workspace_id,
                "number": f"REAUTH-{request_id.hex[:12]}",
                "requester_id": requester_id,
                "round_id": round_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO governance.change_request_rounds
                    (id, workspace_id, change_request_id, round_number,
                     submitted_by, submitted_at, evidence_hash)
                VALUES
                    (:round_id, :workspace_id, :request_id, 1,
                     :requester_id, :now, :evidence_hash)
                """
            ),
            {
                "round_id": round_id,
                "workspace_id": workspace_id,
                "request_id": request_id,
                "requester_id": requester_id,
                "now": now,
                "evidence_hash": "5" * 64,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO governance.change_request_items
                    (id, workspace_id, change_request_id, target_type,
                     target_ref, aspect_name, ordinal, operation, before_hash,
                     after_document, after_hash, target_asset_id,
                     target_asset_type, target_system_id, target_classification,
                     target_lifecycle, target_source_version, target_observed_at,
                     target_binding_hash, routing_system_id)
                VALUES
                    (:item_id, :workspace_id, :request_id, 'DATAHUB_ASPECT',
                     :target_ref, 'datasetProperties', 1, 'UPSERT', :before_hash,
                     '{"description":"governed"}'::jsonb, :after_hash, :asset_id,
                     'DATASET', :system_id, 2, 'ACTIVE', 'source-v1', :now,
                     :binding_hash, :system_id)
                """
            ),
            {
                "item_id": item_id,
                "workspace_id": workspace_id,
                "request_id": request_id,
                "target_ref": target_ref,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "asset_id": asset_id,
                "system_id": system_id,
                "now": now,
                "binding_hash": binding_hash,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.jobs
                    (id, workspace_id, job_type, causation_id, state,
                     requested_by, progress, lease_until, attempts,
                     attempt_cycle, cycle_attempts, lease_token_hash,
                     lease_owner_id, version)
                VALUES
                    (:job_id, :workspace_id, 'DATAHUB_CHANGE_APPLY',
                     :request_id, 'RUNNING', :requester_id, '{}'::jsonb,
                     :lease_until, 3, 1, 3, :lease_token_hash,
                     :worker_id, 1)
                """
            ),
            {
                "job_id": job_id,
                "workspace_id": workspace_id,
                "request_id": request_id,
                "requester_id": requester_id,
                "lease_until": now + timedelta(minutes=30),
                "lease_token_hash": lease_token_hash,
                "worker_id": worker_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.job_attempts
                    (id, workspace_id, job_id, attempt_no, worker_id,
                     state, started_at)
                VALUES
                    (:attempt_id, :workspace_id, :job_id, 3,
                     'apply-reauth-worker', 'RUNNING', :now)
                """
            ),
            {
                "attempt_id": attempt_id,
                "workspace_id": workspace_id,
                "job_id": job_id,
                "now": now,
            },
        )
    return {
        "workspace_id": workspace_id,
        "change_request_id": request_id,
        "change_request_version": 7,
        "request_type": "CATALOG_DESCRIPTION",
        "requester_id": requester_id,
        "checker_id": checker_id,
        "request_classification": 2,
        "item_id": item_id,
        "action": "change.create",
        "target_type": "DATAHUB_ASPECT",
        "target_ref": target_ref,
        "operation": "UPSERT",
        "aspect_name": "datasetProperties",
        "before_hash": before_hash,
        "after_hash": after_hash,
        "target_asset_id": asset_id,
        "target_asset_type": "DATASET",
        "target_system_id": system_id,
        "target_domain_id": None,
        "target_owner_department_id": None,
        "target_classification": 2,
        "target_lifecycle": "ACTIVE",
        "target_source_version": "source-v1",
        "target_binding_hash": binding_hash,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "attempt_no": 3,
        "worker_subject_id": worker_id,
        "lease_token_hash": lease_token_hash,
        "policy_id": policy_id,
        "policy_hash": policy_hash,
    }


async def _seed_preparation_fixture(
    engine: AsyncEngine,
    base: dict[str, object],
    *,
    receipt_created_at: datetime | None = None,
) -> dict[str, object]:
    now = datetime.now(UTC)
    receipt_created_at = receipt_created_at or now
    preparation_id = uuid4()
    upload_id = uuid4()
    raw_lease_token = uuid4()
    lease_token_hash = hashlib.sha256(str(raw_lease_token).encode()).hexdigest()
    key_hash = uuid4().hex * 2
    lease_until = now + timedelta(minutes=30)
    source_hash = "8" * 64
    configuration_hash = "9" * 64
    other_workspace_id = uuid4()
    other_system_id = uuid4()
    other_asset_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO integration.object_manifests
                    (id, workspace_id, bucket, object_key, display_name,
                     size_bytes, mime, sha256, actual_size_bytes, actual_mime,
                     actual_sha256, processing_attempts, validation_attempts,
                     validation_summary, completion_parts, state,
                     content_profile, classification, owner_id, version)
                VALUES
                    (:upload_id, :workspace_id, 'preparation-reauth-test',
                     :object_key, 'catalog.csv', 1, 'text/csv', :source_hash,
                     1, 'text/csv', :source_hash, 0, 1,
                     '{"validator_version":"scanner-v1"}'::jsonb,
                     '[]'::jsonb, 'ACCEPTED',
                     'CATALOG_METADATA_ROWS_CSV_V1', 2, :requested_by, 1)
                """
            ),
            {
                "upload_id": upload_id,
                "workspace_id": base["workspace_id"],
                "object_key": f"preparation-reauth/{upload_id}.csv",
                "source_hash": source_hash,
                "requested_by": base["requester_id"],
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.upload_preparation_jobs
                    (id, workspace_id, upload_id, requested_by,
                     content_profile, source_manifest_version, source_sha256,
                     configuration_hash, state, lease_token, lease_until,
                     attempts, rows_processed, version)
                VALUES
                    (:preparation_id, :workspace_id, :upload_id, :requested_by,
                     'CATALOG_METADATA_ROWS_CSV_V1', 1, :source_hash,
                     :configuration_hash, 'PREPARING', :lease_token,
                     :lease_until, 2, 0, 1)
                """
            ),
            {
                "preparation_id": preparation_id,
                "workspace_id": base["workspace_id"],
                "upload_id": upload_id,
                "requested_by": base["requester_id"],
                "source_hash": source_hash,
                "configuration_hash": configuration_hash,
                "lease_token": raw_lease_token,
                "lease_until": lease_until,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version)
                VALUES
                    (:workspace_id, :slug, 'Other workspace',
                     'ACTIVE', '{}'::jsonb, 1)
                """
            ),
            {
                "workspace_id": other_workspace_id,
                "slug": f"preparation-other-{other_workspace_id.hex[:12]}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO platform.data_systems
                    (id, workspace_id, code, name, description, active, version)
                VALUES
                    (:system_id, :workspace_id, :code, 'Other system',
                     'Cross-workspace fixture', true, 1)
                """
            ),
            {
                "system_id": other_system_id,
                "workspace_id": other_workspace_id,
                "code": f"other_{other_system_id.hex[:12]}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.assets_projection
                    (id, workspace_id, external_urn, urn_hash, asset_type,
                     name, platform, database_name, schema_name,
                     tags, glossary_terms, column_names, system_id,
                     classification, lifecycle, source_version, observed_at,
                     projection_source)
                VALUES
                    (:asset_id, :workspace_id, :target_ref, :urn_hash, 'DATASET',
                     'other_orders', 'postgres', 'other_db', 'public',
                     '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, :system_id,
                     1, 'ACTIVE', 'source-v1', :now, 'DATAHUB')
                """
            ),
            {
                "asset_id": other_asset_id,
                "workspace_id": other_workspace_id,
                "target_ref": f"urn:li:dataset:other-{other_asset_id}",
                "urn_hash": other_asset_id.hex * 2,
                "system_id": other_system_id,
                "now": now,
            },
        )
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE datariver_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :value, true)"),
            {"value": str(base["workspace_id"])},
        )
        await connection.execute(
            text("SELECT set_config('app.subject_id', :value, true)"),
            {"value": str(base["worker_subject_id"])},
        )
        await connection.execute(
            text(
                """
                SELECT set_config(
                    'app.registration_worker_claim_token',
                    :value,
                    true
                )
                """
            ),
            {"value": str(raw_lease_token)},
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.registration_worker_call_receipts
                    (workspace_id, operation, key_hash, request_hash,
                     worker_subject_id, state, work_kind, work_id,
                     claim_attempt, claim_token_hash, lease_expires_at,
                     processed, result, created_at, updated_at)
                VALUES
                    (:workspace_id,
                     'registration.bulk-preparation.execute-run.v1',
                     :key_hash, :request_hash, :worker_subject_id,
                     'RUNNING', 'BULK', :preparation_id, 2,
                     :lease_token_hash, :lease_until, NULL, NULL, :now, :now)
                """
            ),
            {
                "workspace_id": base["workspace_id"],
                "key_hash": key_hash,
                "request_hash": uuid4().hex * 2,
                "worker_subject_id": base["worker_subject_id"],
                "preparation_id": preparation_id,
                "lease_token_hash": lease_token_hash,
                "lease_until": lease_until,
                "now": receipt_created_at,
            },
        )
    return {
        "workspace_id": base["workspace_id"],
        "preparation_id": preparation_id,
        "requested_by": base["requester_id"],
        "worker_subject_id": base["worker_subject_id"],
        "attempt": 2,
        "lease_token_hash": lease_token_hash,
        "target_asset_ids": [base["target_asset_id"]],
        "target_asset_id": base["target_asset_id"],
        "target_system_id": base["target_system_id"],
        "cross_workspace_asset_id": other_asset_id,
        "lease_until": lease_until,
        "key_hash": key_hash,
        "lock_for_publication": True,
    }


async def _update(
    engine: AsyncEngine,
    statement: str,
    parameters: dict[str, object],
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(statement), parameters)


async def _install_v2_description_binding(
    engine: AsyncEngine,
    parameters: dict[str, object],
) -> UUID:
    now = datetime.now(UTC)
    upload_id = uuid4()
    preparation_id = uuid4()
    receipt_id = uuid4()
    candidate_id = uuid4()
    source_hash = "8" * 64
    configuration_hash = "9" * 64
    candidate_hash = "a" * 64
    content_profile = "DATASET_DESCRIPTION_CSV_V1"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO integration.object_manifests
                    (id, workspace_id, bucket, object_key, display_name,
                     size_bytes, mime, sha256, actual_size_bytes, actual_mime,
                     actual_sha256, processing_attempts, validation_attempts,
                     validation_summary, completion_parts, state,
                     content_profile, classification, owner_id, version)
                VALUES
                    (:upload_id, :workspace_id, 'apply-reauth-test',
                     :object_key, 'descriptions.csv', 1, 'text/csv', :source_hash,
                     1, 'text/csv', :source_hash, 0, 1,
                     '{}'::jsonb, '[]'::jsonb, 'ACCEPTED',
                     :content_profile, 2, :requester_id, 1)
                """
            ),
            {
                "upload_id": upload_id,
                "workspace_id": parameters["workspace_id"],
                "object_key": f"apply-reauth-v2/{upload_id}.csv",
                "source_hash": source_hash,
                "content_profile": content_profile,
                "requester_id": parameters["requester_id"],
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.upload_preparation_jobs
                    (id, workspace_id, upload_id, requested_by,
                     content_profile, source_manifest_version, source_sha256,
                     configuration_hash, state, attempts, rows_processed,
                     total_rows, version)
                VALUES
                    (:preparation_id, :workspace_id, :upload_id, :requester_id,
                     :content_profile, 1, :source_hash, :configuration_hash,
                     'READY', 1, 1, 1, 1)
                """
            ),
            {
                "preparation_id": preparation_id,
                "workspace_id": parameters["workspace_id"],
                "upload_id": upload_id,
                "requester_id": parameters["requester_id"],
                "content_profile": content_profile,
                "source_hash": source_hash,
                "configuration_hash": configuration_hash,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.upload_preparation_receipts
                    (id, workspace_id, preparation_job_id, upload_id,
                     manifest_version, source_sha256, accepted_sha256,
                     object_locator_hash, content_profile, parser_version,
                     scanner_version, schema_version, configuration_hash,
                     item_count, rejected_count, candidate_root_hash,
                     receipt_hash, observed_at, created_at)
                VALUES
                    (:receipt_id, :workspace_id, :preparation_id, :upload_id,
                     1, :source_hash, :source_hash, :locator_hash,
                     :content_profile, 'dataset-description-csv-parser-v1',
                     'scanner-v1', 'dataset-description-v2',
                     :configuration_hash, 1, 0, :candidate_root_hash,
                     :receipt_hash, :now, :now)
                """
            ),
            {
                "receipt_id": receipt_id,
                "workspace_id": parameters["workspace_id"],
                "preparation_id": preparation_id,
                "upload_id": upload_id,
                "source_hash": source_hash,
                "locator_hash": "b" * 64,
                "content_profile": content_profile,
                "configuration_hash": configuration_hash,
                "candidate_root_hash": "c" * 64,
                "receipt_hash": "d" * 64,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.upload_registration_candidates
                    (id, workspace_id, receipt_id, ordinal, target_asset_id,
                     candidate_kind, proposed_description, evidence_version,
                     submitted_platform, submitted_database_name,
                     submitted_schema_name, submitted_table_name,
                     submitted_identity_hash, candidate_hash, created_at)
                VALUES
                    (:candidate_id, :workspace_id, :receipt_id, 1, :asset_id,
                     'DATASET_DESCRIPTION_UPDATE', 'governed',
                     'DATASET_DESCRIPTION_CANDIDATE_V2', 'postgres', 'warehouse',
                     'public', 'orders', :identity_hash, :candidate_hash, :now)
                """
            ),
            {
                "candidate_id": candidate_id,
                "workspace_id": parameters["workspace_id"],
                "receipt_id": receipt_id,
                "asset_id": parameters["target_asset_id"],
                "identity_hash": "e" * 64,
                "candidate_hash": candidate_hash,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO governance.registration_content_bindings
                    (id, workspace_id, candidate_id, candidate_hash,
                     change_request_id, change_item_id, created_by, created_at)
                VALUES
                    (:binding_id, :workspace_id, :candidate_id, :candidate_hash,
                     :request_id, :item_id, :requester_id, :now)
                """
            ),
            {
                "binding_id": uuid4(),
                "workspace_id": parameters["workspace_id"],
                "candidate_id": candidate_id,
                "candidate_hash": candidate_hash,
                "request_id": parameters["change_request_id"],
                "item_id": parameters["item_id"],
                "requester_id": parameters["requester_id"],
                "now": now,
            },
        )
    return preparation_id


async def _install_v3_tag_binding(
    engine: AsyncEngine,
    parameters: dict[str, object],
) -> UUID:
    now = datetime.now(UTC)
    upload_id = uuid4()
    preparation_id = uuid4()
    receipt_id = uuid4()
    vocabulary_id = uuid4()
    row_id = uuid4()
    candidate_id = uuid4()
    source_hash = "a" * 64
    configuration_hash = "b" * 64
    row_hash = "c" * 64
    candidate_hash = "d" * 64
    item_contract_hash = "e" * 64
    content_profile = "CATALOG_METADATA_ROWS_CSV_V1"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE governance.change_request_items
                SET aspect_name = 'globalTags',
                    after_document = jsonb_build_object(
                        'tags',
                        jsonb_build_array(CAST(:provider_ref AS text))
                    ),
                    item_contract_hash = :item_contract_hash
                WHERE workspace_id = :workspace_id AND id = :item_id
                """
            ),
            {
                "workspace_id": parameters["workspace_id"],
                "item_id": parameters["item_id"],
                "provider_ref": f"urn:li:tag:{vocabulary_id}",
                "item_contract_hash": item_contract_hash,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.object_manifests
                    (id, workspace_id, bucket, object_key, display_name,
                     size_bytes, mime, sha256, actual_size_bytes, actual_mime,
                     actual_sha256, processing_attempts, validation_attempts,
                     validation_summary, completion_parts, state,
                     content_profile, classification, owner_id, version)
                VALUES
                    (:upload_id, :workspace_id, 'apply-reauth-test',
                     :object_key, 'metadata.csv', 1, 'text/csv', :source_hash,
                     1, 'text/csv', :source_hash, 0, 1,
                     '{}'::jsonb, '[]'::jsonb, 'ACCEPTED',
                     :content_profile, 2, :requester_id, 1)
                """
            ),
            {
                "upload_id": upload_id,
                "workspace_id": parameters["workspace_id"],
                "object_key": f"apply-reauth/{upload_id}.csv",
                "source_hash": source_hash,
                "content_profile": content_profile,
                "requester_id": parameters["requester_id"],
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.upload_preparation_jobs
                    (id, workspace_id, upload_id, requested_by,
                     content_profile, source_manifest_version, source_sha256,
                     configuration_hash, state, attempts, rows_processed,
                     total_rows, version)
                VALUES
                    (:preparation_id, :workspace_id, :upload_id, :requester_id,
                     :content_profile, 1, :source_hash, :configuration_hash,
                     'READY', 1, 1, 1, 1)
                """
            ),
            {
                "preparation_id": preparation_id,
                "workspace_id": parameters["workspace_id"],
                "upload_id": upload_id,
                "requester_id": parameters["requester_id"],
                "content_profile": content_profile,
                "source_hash": source_hash,
                "configuration_hash": configuration_hash,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.upload_preparation_receipts
                    (id, workspace_id, preparation_job_id, upload_id,
                     manifest_version, source_sha256, accepted_sha256,
                     object_locator_hash, content_profile, parser_version,
                     scanner_version, schema_version, configuration_hash,
                     item_count, rejected_count, candidate_root_hash,
                     receipt_hash, observed_at, created_at)
                VALUES
                    (:receipt_id, :workspace_id, :preparation_id, :upload_id,
                     1, :source_hash, :source_hash, :locator_hash,
                     :content_profile, 'catalog-metadata-csv-parser-v1',
                     'scanner-v1', 'catalog-metadata-rows-v1',
                     :configuration_hash, 1, 0, :candidate_root_hash,
                     :receipt_hash, :now, :now)
                """
            ),
            {
                "receipt_id": receipt_id,
                "workspace_id": parameters["workspace_id"],
                "preparation_id": preparation_id,
                "upload_id": upload_id,
                "source_hash": source_hash,
                "locator_hash": "f" * 64,
                "content_profile": content_profile,
                "configuration_hash": configuration_hash,
                "candidate_root_hash": "1" * 64,
                "receipt_hash": "2" * 64,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.vocabulary_entries
                    (id, workspace_id, kind, provider_ref, display_name,
                     lifecycle, source_version, observed_at, updated_at)
                VALUES
                    (:vocabulary_id, :workspace_id, 'TAG', :provider_ref,
                     'governed-tag', 'ACTIVE', 'v1', :now, :now)
                """
            ),
            {
                "vocabulary_id": vocabulary_id,
                "workspace_id": parameters["workspace_id"],
                "provider_ref": f"urn:li:tag:{vocabulary_id}",
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.catalog_metadata_rows
                    (id, workspace_id, receipt_id, ordinal, content_profile,
                     evidence_version, record_kind, aspect_name,
                     target_asset_id, submitted_platform,
                     submitted_database_name, submitted_schema_name,
                     submitted_table_name, operation, controlled_ref_id,
                     controlled_kind, submitted_identity_hash,
                     semantic_target_hash, row_hash, created_at)
                VALUES
                    (:row_id, :workspace_id, :receipt_id, 1, :content_profile,
                     'CATALOG_METADATA_CANDIDATE_V3', 'DATASET_TAG',
                     'globalTags', :asset_id, 'postgres', 'warehouse',
                     'public', 'orders', 'ADD', :vocabulary_id, 'TAG',
                     :identity_hash, :target_hash, :row_hash, :now)
                """
            ),
            {
                "row_id": row_id,
                "workspace_id": parameters["workspace_id"],
                "receipt_id": receipt_id,
                "content_profile": content_profile,
                "asset_id": parameters["target_asset_id"],
                "vocabulary_id": vocabulary_id,
                "identity_hash": "3" * 64,
                "target_hash": "4" * 64,
                "row_hash": row_hash,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.catalog_metadata_candidates
                    (id, workspace_id, receipt_id, candidate_ordinal,
                     content_profile, record_kind, candidate_kind,
                     evidence_version, target_asset_id, aspect_name,
                     submitted_identity_hash, row_count, first_row_ordinal,
                     last_row_ordinal, row_root_hash, candidate_hash, created_at)
                VALUES
                    (:candidate_id, :workspace_id, :receipt_id, 1,
                     :content_profile, 'DATASET_TAG', 'DATASET_TAG_ADD',
                     'CATALOG_METADATA_CANDIDATE_V3', :asset_id, 'globalTags',
                     :identity_hash, 1, 1, 1, :row_root_hash,
                     :candidate_hash, :now)
                """
            ),
            {
                "candidate_id": candidate_id,
                "workspace_id": parameters["workspace_id"],
                "receipt_id": receipt_id,
                "content_profile": content_profile,
                "asset_id": parameters["target_asset_id"],
                "identity_hash": "3" * 64,
                "row_root_hash": "5" * 64,
                "candidate_hash": candidate_hash,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO integration.catalog_metadata_candidate_rows
                    (workspace_id, receipt_id, candidate_id, row_id,
                     content_profile, candidate_hash, row_hash,
                     member_ordinal, source_ordinal, created_at)
                VALUES
                    (:workspace_id, :receipt_id, :candidate_id, :row_id,
                     :content_profile, :candidate_hash, :row_hash, 1, 1, :now)
                """
            ),
            {
                "workspace_id": parameters["workspace_id"],
                "receipt_id": receipt_id,
                "candidate_id": candidate_id,
                "row_id": row_id,
                "content_profile": content_profile,
                "candidate_hash": candidate_hash,
                "row_hash": row_hash,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO governance.registration_metadata_content_bindings
                    (id, workspace_id, candidate_id, candidate_hash,
                     content_profile, candidate_kind, aspect_name,
                     before_hash, after_hash, item_contract_hash,
                     change_request_id, change_item_id, created_by, created_at)
                VALUES
                    (:binding_id, :workspace_id, :candidate_id,
                     :candidate_hash, :content_profile, 'DATASET_TAG_ADD',
                     'globalTags', :before_hash, :after_hash,
                     :item_contract_hash, :request_id, :item_id,
                     :requester_id, :now)
                """
            ),
            {
                "binding_id": uuid4(),
                "workspace_id": parameters["workspace_id"],
                "candidate_id": candidate_id,
                "candidate_hash": candidate_hash,
                "content_profile": content_profile,
                "before_hash": parameters["before_hash"],
                "after_hash": parameters["after_hash"],
                "item_contract_hash": item_contract_hash,
                "request_id": parameters["change_request_id"],
                "item_id": parameters["item_id"],
                "requester_id": parameters["requester_id"],
                "now": now,
            },
        )
    return vocabulary_id


async def _reason_codes(
    engine: AsyncEngine,
    request_id: UUID,
) -> list[str]:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT reason_codes ->> 0
                    FROM authz.policy_decisions
                    WHERE resource_id = :request_id
                      AND request_id LIKE 'apply-reauth:%'
                    ORDER BY decided_at, id
                    """
                ),
                {"request_id": request_id},
            )
        ).scalars()
        return list(rows)


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="isolated PostgreSQL evidence is not configured",
)
@pytest.mark.asyncio
async def test_reauthorization_function_has_least_privilege_contract() -> None:
    engine = _engine()
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "0052"
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT procedure.prosecdef,
                               procedure.proconfig,
                               owner.rolname,
                               ARRAY(
                                   SELECT COALESCE(grantee.rolname, 'PUBLIC')
                                   FROM pg_catalog.aclexplode(
                                       COALESCE(
                                           procedure.proacl,
                                           pg_catalog.acldefault(
                                               'f',
                                               procedure.proowner
                                           )
                                       )
                                   ) AS privilege
                                   LEFT JOIN pg_catalog.pg_roles AS grantee
                                     ON grantee.oid = privilege.grantee
                                   WHERE privilege.privilege_type = 'EXECUTE'
                                   ORDER BY COALESCE(grantee.rolname, 'PUBLIC')
                               )
                        FROM pg_catalog.pg_proc AS procedure
                        JOIN pg_catalog.pg_roles AS owner
                          ON owner.oid = procedure.proowner
                        WHERE procedure.oid = CAST(:signature AS regprocedure)
                        """
                    ),
                    {"signature": _FUNCTION_SIGNATURE},
                )
            ).one()
            assert row[0] is True
            assert row[1] == ["search_path=pg_catalog"]
            assert row[2] != "datariver_governance"
            assert set(row[3]) == {row[2], "datariver_governance"}
            preparation_row = (
                await connection.execute(
                    text(
                        """
                        SELECT procedure.prosecdef,
                               procedure.proconfig,
                               owner.rolname,
                               ARRAY(
                                   SELECT COALESCE(grantee.rolname, 'PUBLIC')
                                   FROM pg_catalog.aclexplode(
                                       COALESCE(
                                           procedure.proacl,
                                           pg_catalog.acldefault(
                                               'f',
                                               procedure.proowner
                                           )
                                       )
                                   ) AS privilege
                                   LEFT JOIN pg_catalog.pg_roles AS grantee
                                     ON grantee.oid = privilege.grantee
                                   WHERE privilege.privilege_type = 'EXECUTE'
                                   ORDER BY COALESCE(grantee.rolname, 'PUBLIC')
                               )
                        FROM pg_catalog.pg_proc AS procedure
                        JOIN pg_catalog.pg_roles AS owner
                          ON owner.oid = procedure.proowner
                        WHERE procedure.oid = CAST(:signature AS regprocedure)
                        """
                    ),
                    {"signature": _PREPARATION_FUNCTION_SIGNATURE},
                )
            ).one()
            assert preparation_row[0] is True
            assert preparation_row[1] == ["search_path=pg_catalog"]
            assert preparation_row[2] != "datariver_app"
            assert set(preparation_row[3]) == {
                preparation_row[2],
                "datariver_app",
            }
            grants = {
                table: bool(
                    await connection.scalar(
                        text(
                            """
                            SELECT pg_catalog.has_table_privilege(
                                'datariver_governance',
                                :table_name,
                                'SELECT'
                            )
                            """
                        ),
                        {"table_name": table},
                    )
                )
                for table in _SENSITIVE_TABLES
            }
            assert not any(grants.values()), grants
            assert bool(
                await connection.scalar(
                    text(
                        """
                        SELECT pg_catalog.has_table_privilege(
                            'datariver_governance',
                            'integration.jobs',
                            'SELECT'
                        )
                        AND pg_catalog.has_table_privilege(
                            'datariver_governance',
                            'integration.job_attempts',
                            'SELECT'
                        )
                        """
                    )
                )
            )

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await connection.execute(text("SET LOCAL ROLE datariver_governance"))
                    await connection.execute(text("SELECT id FROM iam.subjects LIMIT 1"))
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="isolated PostgreSQL evidence is not configured",
)
@pytest.mark.asyncio
async def test_reauthorization_rechecks_current_state_and_records_each_decision() -> None:
    engine = _engine()
    try:
        parameters = await _seed_fixture(engine)
        workspace_id = UUID(str(parameters["workspace_id"]))
        requester_id = UUID(str(parameters["requester_id"]))
        system_id = UUID(str(parameters["target_system_id"]))
        asset_id = UUID(str(parameters["target_asset_id"]))
        policy_id = UUID(str(parameters["policy_id"]))
        checker_id = UUID(str(parameters["checker_id"]))
        request_id = UUID(str(parameters["change_request_id"]))

        assert await _call_as_governance(engine, parameters) is True

        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET job_function = 'DATA_ANALYST',
                attributes = jsonb_set(
                    attributes,
                    '{groups}',
                    '["catalog-users"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_as_governance(engine, parameters) is True
        await _update(
            engine,
            """
            UPDATE governance.change_requests
            SET request_type = 'CATALOG_COLUMN_DESCRIPTION'
            WHERE workspace_id = :workspace_id AND id = :request_id
            """,
            {"workspace_id": workspace_id, "request_id": request_id},
        )
        assert (
            await _call_as_governance(
                engine,
                {**parameters, "request_type": "CATALOG_COLUMN_DESCRIPTION"},
            )
            is True
        )
        await _update(
            engine,
            """
            UPDATE governance.change_requests
            SET request_type = 'CATALOG_CONTROLLED_METADATA'
            WHERE workspace_id = :workspace_id AND id = :request_id
            """,
            {"workspace_id": workspace_id, "request_id": request_id},
        )
        assert (
            await _call_as_governance(
                engine,
                {**parameters, "request_type": "CATALOG_CONTROLLED_METADATA"},
            )
            is True
        )
        await _update(
            engine,
            """
            UPDATE governance.change_requests
            SET request_type = 'CATALOG_DESCRIPTION'
            WHERE workspace_id = :workspace_id AND id = :request_id
            """,
            {"workspace_id": workspace_id, "request_id": request_id},
        )
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET job_function = 'SECURITY_ADMINISTRATOR',
                attributes = jsonb_set(
                    attributes,
                    '{groups}',
                    '["security-administrators"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )

        assert (
            await _call_as_governance(
                engine,
                {**parameters, "job_id": uuid4()},
            )
            is False
        )
        assert (
            await _call_as_governance(
                engine,
                {**parameters, "attempt_id": uuid4()},
            )
            is False
        )
        assert (
            await _call_as_governance(
                engine,
                {**parameters, "attempt_no": 4},
            )
            is False
        )
        assert (
            await _call_as_governance(
                engine,
                {**parameters, "worker_subject_id": checker_id},
            )
            is False
        )
        assert (
            await _call_as_governance(
                engine,
                {**parameters, "lease_token_hash": "8" * 64},
            )
            is False
        )
        await _update(
            engine,
            """
            UPDATE integration.jobs
            SET lease_until = clock_timestamp() - interval '1 minute'
            WHERE workspace_id = :workspace_id AND id = :job_id
            """,
            {
                "workspace_id": workspace_id,
                "job_id": parameters["job_id"],
            },
        )
        assert await _call_as_governance(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE integration.jobs
            SET lease_until = clock_timestamp() + interval '30 minutes'
            WHERE workspace_id = :workspace_id AND id = :job_id
            """,
            {
                "workspace_id": workspace_id,
                "job_id": parameters["job_id"],
            },
        )
        await _update(
            engine,
            """
            UPDATE integration.job_attempts
            SET state = 'SUPERSEDED', finished_at = clock_timestamp()
            WHERE workspace_id = :workspace_id AND id = :attempt_id
            """,
            {
                "workspace_id": workspace_id,
                "attempt_id": parameters["attempt_id"],
            },
        )
        assert await _call_as_governance(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE integration.job_attempts
            SET state = 'RUNNING', finished_at = NULL
            WHERE workspace_id = :workspace_id AND id = :attempt_id
            """,
            {
                "workspace_id": workspace_id,
                "attempt_id": parameters["attempt_id"],
            },
        )

        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET attributes = jsonb_set(
                    attributes,
                    '{denied_actions}',
                    '["change.create"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_as_governance(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET attributes = jsonb_set(
                    attributes,
                    '{denied_actions}',
                    '[]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )

        await _update(
            engine,
            """
            UPDATE platform.data_systems
            SET active = false, version = version + 1
            WHERE workspace_id = :workspace_id AND id = :system_id
            """,
            {"workspace_id": workspace_id, "system_id": system_id},
        )
        assert await _call_as_governance(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE platform.data_systems
            SET active = true, version = version + 1
            WHERE workspace_id = :workspace_id AND id = :system_id
            """,
            {"workspace_id": workspace_id, "system_id": system_id},
        )

        stale_parameters = {**parameters, "target_source_version": "source-stale"}
        assert await _call_as_governance(engine, stale_parameters) is False

        await _update(
            engine,
            """
            UPDATE authz.classification_access_policy_rules
            SET search_mode = 'DENY'
            WHERE workspace_id = :workspace_id
              AND policy_id = :policy_id
              AND classification = 2
            """,
            {"workspace_id": workspace_id, "policy_id": policy_id},
        )
        assert await _call_as_governance(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE authz.classification_access_policy_rules
            SET search_mode = 'ABAC'
            WHERE workspace_id = :workspace_id
              AND policy_id = :policy_id
              AND classification = 2
            """,
            {"workspace_id": workspace_id, "policy_id": policy_id},
        )

        await _update(
            engine,
            """
            UPDATE governance.change_requests
            SET request_type = 'BULK_DATASET_DESCRIPTION', version = version + 1
            WHERE workspace_id = :workspace_id AND id = :request_id
            """,
            {"workspace_id": workspace_id, "request_id": request_id},
        )
        v2_parameters = {
            **parameters,
            "request_type": "BULK_DATASET_DESCRIPTION",
            "change_request_version": 8,
        }
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET job_function = 'DATA_ANALYST',
                attributes = jsonb_set(
                    attributes,
                    '{groups}',
                    '["catalog-users"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_as_governance(engine, v2_parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET job_function = 'SECURITY_ADMINISTRATOR',
                attributes = jsonb_set(
                    attributes,
                    '{groups}',
                    '["security-administrators"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_as_governance(engine, v2_parameters) is False
        v2_preparation_id = await _install_v2_description_binding(engine, v2_parameters)
        assert await _call_as_governance(engine, v2_parameters) is True
        await _update(
            engine,
            """
            UPDATE catalog.assets_projection
            SET name = 'orders-drifted'
            WHERE workspace_id = :workspace_id AND id = :asset_id
            """,
            {
                "workspace_id": workspace_id,
                "asset_id": asset_id,
            },
        )
        assert await _call_as_governance(engine, v2_parameters) is False
        await _update(
            engine,
            """
            UPDATE catalog.assets_projection
            SET name = 'orders'
            WHERE workspace_id = :workspace_id AND id = :asset_id
            """,
            {
                "workspace_id": workspace_id,
                "asset_id": asset_id,
            },
        )
        await _update(
            engine,
            """
            UPDATE integration.upload_preparation_jobs
            SET state = 'FAILED', version = version + 1
            WHERE workspace_id = :workspace_id AND id = :preparation_id
            """,
            {
                "workspace_id": workspace_id,
                "preparation_id": v2_preparation_id,
            },
        )
        assert await _call_as_governance(engine, v2_parameters) is False
        await _update(
            engine,
            """
            UPDATE integration.upload_preparation_jobs
            SET state = 'READY', version = version + 1
            WHERE workspace_id = :workspace_id AND id = :preparation_id
            """,
            {
                "workspace_id": workspace_id,
                "preparation_id": v2_preparation_id,
            },
        )
        await _update(
            engine,
            """
            UPDATE governance.change_requests
            SET request_type = 'BULK_CATALOG_METADATA', version = version + 1
            WHERE workspace_id = :workspace_id AND id = :request_id
            """,
            {"workspace_id": workspace_id, "request_id": request_id},
        )
        v3_parameters = {
            **parameters,
            "request_type": "BULK_CATALOG_METADATA",
            "change_request_version": 9,
        }
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET job_function = 'DATA_ANALYST',
                attributes = jsonb_set(
                    attributes,
                    '{groups}',
                    '["catalog-users"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_as_governance(engine, v3_parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET job_function = 'SECURITY_ADMINISTRATOR',
                attributes = jsonb_set(
                    attributes,
                    '{groups}',
                    '["security-administrators"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_as_governance(engine, v3_parameters) is False
        vocabulary_id = await _install_v3_tag_binding(engine, parameters)
        v3_parameters = {**v3_parameters, "aspect_name": "globalTags"}
        assert await _call_as_governance(engine, v3_parameters) is True
        await _update(
            engine,
            """
            UPDATE catalog.vocabulary_entries
            SET lifecycle = 'INACTIVE',
                updated_at = clock_timestamp()
            WHERE workspace_id = :workspace_id AND id = :vocabulary_id
            """,
            {
                "workspace_id": workspace_id,
                "vocabulary_id": vocabulary_id,
            },
        )
        assert await _call_as_governance(engine, v3_parameters) is False
        await _update(
            engine,
            """
            UPDATE catalog.vocabulary_entries
            SET lifecycle = 'ACTIVE',
                updated_at = clock_timestamp()
            WHERE workspace_id = :workspace_id AND id = :vocabulary_id
            """,
            {
                "workspace_id": workspace_id,
                "vocabulary_id": vocabulary_id,
            },
        )
        parameters = v3_parameters
        await _update(
            engine,
            """
            UPDATE governance.change_requests
            SET request_type = 'BULK_UNKNOWN', version = version + 1
            WHERE workspace_id = :workspace_id AND id = :request_id
            """,
            {"workspace_id": workspace_id, "request_id": request_id},
        )
        unknown_parameters = {
            **parameters,
            "request_type": "BULK_UNKNOWN",
            "change_request_version": 10,
        }
        assert await _call_as_governance(engine, unknown_parameters) is False

        await _update(
            engine,
            """
            UPDATE catalog.assets_projection
            SET classification = 3
            WHERE workspace_id = :workspace_id AND id = :asset_id
            """,
            {"workspace_id": workspace_id, "asset_id": asset_id},
        )
        await _update(
            engine,
            """
            UPDATE governance.change_request_items
            SET target_classification = 3
            WHERE workspace_id = :workspace_id AND id = :item_id
            """,
            {
                "workspace_id": workspace_id,
                "item_id": parameters["item_id"],
            },
        )
        await _update(
            engine,
            """
            UPDATE governance.change_requests
            SET request_type = 'CATALOG_DESCRIPTION',
                classification = 3,
                version = version + 1
            WHERE workspace_id = :workspace_id AND id = :request_id
            """,
            {
                "workspace_id": workspace_id,
                "request_id": request_id,
            },
        )
        restricted_parameters = {
            **parameters,
            "request_type": "CATALOG_DESCRIPTION",
            "request_classification": 3,
            "target_classification": 3,
            "change_request_version": 11,
        }
        assert await _call_as_governance(engine, restricted_parameters) is False
        await _update(
            engine,
            """
            INSERT INTO authz.restricted_search_grants
                (id, workspace_id, classification_policy_id,
                 classification_policy_hash, subject_id, scope, scope_id,
                 purpose, valid_from, expires_at, payload_hash,
                 requester_id, request_reason, request_policy_decision_id,
                 state, checker_id, decision_reason,
                 decision_policy_decision_id, decided_at, version)
            VALUES
                (:grant_id, :workspace_id, :policy_id, :policy_hash,
                 :requester_id, 'RESOURCE', :asset_id, 'apply test',
                 clock_timestamp() - interval '1 minute',
                 clock_timestamp() + interval '1 hour', :payload_hash,
                 :requester_id, 'apply test', :request_decision_id,
                 'ACTIVE', :checker_id, 'approved', :decision_id,
                 clock_timestamp(), 2)
            """,
            {
                "grant_id": uuid4(),
                "workspace_id": workspace_id,
                "policy_id": policy_id,
                "policy_hash": "1" * 64,
                "requester_id": requester_id,
                "asset_id": asset_id,
                "payload_hash": "6" * 64,
                "request_decision_id": uuid4(),
                "checker_id": checker_id,
                "decision_id": uuid4(),
            },
        )
        assert await _call_as_governance(engine, restricted_parameters) is True
        await _update(
            engine,
            """
            UPDATE authz.restricted_search_grants
            SET valid_from = clock_timestamp() - interval '2 hours',
                expires_at = clock_timestamp() - interval '1 hour'
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
              AND scope_id = :asset_id
            """,
            {
                "workspace_id": workspace_id,
                "requester_id": requester_id,
                "asset_id": asset_id,
            },
        )
        assert await _call_as_governance(engine, restricted_parameters) is False

        assert await _reason_codes(engine, request_id) == [
            "POLICY_ALLOW",
            "POLICY_ALLOW",
            "POLICY_ALLOW",
            "POLICY_ALLOW",
            "CURRENT_WORKER_LEASE_INVALID",
            "CURRENT_WORKER_LEASE_INVALID",
            "CURRENT_WORKER_LEASE_INVALID",
            "CURRENT_WORKER_LEASE_INVALID",
            "CURRENT_WORKER_LEASE_INVALID",
            "CURRENT_WORKER_LEASE_INVALID",
            "CURRENT_WORKER_LEASE_INVALID",
            "CURRENT_ACTION_SCOPE_DENIED",
            "DATA_SYSTEM_INACTIVE",
            "CURRENT_CLAIM_ITEM_MISMATCH",
            "CLASSIFICATION_POLICY_DENIED",
            "REGISTRATION_OPERATOR_INELIGIBLE",
            "TYPED_V2_BINDING_INVALID",
            "POLICY_ALLOW",
            "TYPED_V2_BINDING_INVALID",
            "TYPED_V2_BINDING_INVALID",
            "REGISTRATION_OPERATOR_INELIGIBLE",
            "TYPED_V3_BINDING_INVALID",
            "POLICY_ALLOW",
            "TYPED_V3_BINDING_INVALID",
            "UNKNOWN_BULK_CONTRACT",
            "RESTRICTED_GRANT_REQUIRED",
            "POLICY_ALLOW",
            "RESTRICTED_GRANT_REQUIRED",
        ]
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="isolated PostgreSQL evidence is not configured",
)
@pytest.mark.asyncio
async def test_preparation_reauthorization_precedes_candidate_persistence() -> None:
    engine = _engine()
    try:
        base = await _seed_fixture(engine)
        parameters = await _seed_preparation_fixture(engine, base)
        workspace_id = UUID(str(parameters["workspace_id"]))
        preparation_id = UUID(str(parameters["preparation_id"]))
        requester_id = UUID(str(parameters["requested_by"]))
        target_asset_id = UUID(str(parameters["target_asset_id"]))
        target_system_id = UUID(str(parameters["target_system_id"]))
        policy_id = UUID(str(base["policy_id"]))
        policy_hash = str(base["policy_hash"])
        checker_id = UUID(str(base["checker_id"]))

        async def persisted_candidate_count() -> int:
            async with engine.connect() as connection:
                value = await connection.scalar(
                    text(
                        """
                        SELECT
                            (
                                SELECT pg_catalog.count(*)
                                FROM integration.upload_preparation_receipts
                                WHERE workspace_id = :workspace_id
                                  AND preparation_job_id = :preparation_id
                            )
                            + (
                                SELECT pg_catalog.count(*)
                                FROM integration.catalog_metadata_candidates
                                    AS candidate
                                JOIN integration.upload_preparation_receipts
                                    AS receipt
                                  ON receipt.workspace_id =
                                        candidate.workspace_id
                                 AND receipt.id = candidate.receipt_id
                                WHERE receipt.workspace_id = :workspace_id
                                  AND receipt.preparation_job_id =
                                        :preparation_id
                            )
                            + (
                                SELECT pg_catalog.count(*)
                                FROM integration.catalog_metadata_rows AS source_row
                                JOIN integration.upload_preparation_receipts
                                    AS receipt
                                  ON receipt.workspace_id =
                                        source_row.workspace_id
                                 AND receipt.id = source_row.receipt_id
                                WHERE receipt.workspace_id = :workspace_id
                                  AND receipt.preparation_job_id =
                                        :preparation_id
                            )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "preparation_id": preparation_id,
                    },
                )
                return int(value or 0)

        assert await persisted_candidate_count() == 0
        assert await _call_preparation_as_app(engine, parameters) is True

        await _update(
            engine,
            """
            UPDATE authz.classification_access_policy_rules
            SET search_mode = 'DENY'
            WHERE workspace_id = :workspace_id
              AND policy_id = :policy_id
              AND classification = 2
            """,
            {"workspace_id": workspace_id, "policy_id": policy_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE authz.classification_access_policy_rules
            SET search_mode = 'ABAC'
            WHERE workspace_id = :workspace_id
              AND policy_id = :policy_id
              AND classification = 2
            """,
            {"workspace_id": workspace_id, "policy_id": policy_id},
        )

        await _update(
            engine,
            """
            UPDATE authz.classification_access_generations
            SET generation = generation + 1,
                updated_at = clock_timestamp()
            WHERE workspace_id = :workspace_id
            """,
            {"workspace_id": workspace_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE authz.classification_access_generations
            SET generation = 1,
                updated_at = clock_timestamp() - interval '1 day'
            WHERE workspace_id = :workspace_id
            """,
            {"workspace_id": workspace_id},
        )

        await _update(
            engine,
            """
            UPDATE catalog.assets_projection
            SET classification = 3
            WHERE workspace_id = :workspace_id AND id = :asset_id
            """,
            {"workspace_id": workspace_id, "asset_id": target_asset_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            INSERT INTO authz.restricted_search_grants
                (id, workspace_id, classification_policy_id,
                 classification_policy_hash, subject_id, scope, scope_id,
                 purpose, valid_from, expires_at, payload_hash,
                 requester_id, request_reason, request_policy_decision_id,
                 state, checker_id, decision_reason,
                 decision_policy_decision_id, decided_at, version)
            VALUES
                (:grant_id, :workspace_id, :policy_id, :policy_hash,
                 :requester_id, 'RESOURCE', :asset_id, 'preparation test',
                 clock_timestamp() - interval '1 minute',
                 clock_timestamp() + interval '1 hour', :payload_hash,
                 :requester_id, 'preparation test', :request_decision_id,
                 'ACTIVE', :checker_id, 'approved', :decision_id,
                 clock_timestamp(), 2)
            """,
            {
                "grant_id": uuid4(),
                "workspace_id": workspace_id,
                "policy_id": policy_id,
                "policy_hash": policy_hash,
                "requester_id": requester_id,
                "asset_id": target_asset_id,
                "payload_hash": "6" * 64,
                "request_decision_id": uuid4(),
                "checker_id": checker_id,
                "decision_id": uuid4(),
            },
        )
        assert await _call_preparation_as_app(engine, parameters) is True
        await _update(
            engine,
            """
            UPDATE catalog.assets_projection
            SET classification = 2
            WHERE workspace_id = :workspace_id AND id = :asset_id
            """,
            {"workspace_id": workspace_id, "asset_id": target_asset_id},
        )

        assert (
            await _call_preparation_as_app(
                engine,
                {**parameters, "target_asset_ids": [uuid4()]},
            )
            is False
        )

        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET active = false, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET active = true, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )

        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET attributes = jsonb_set(
                    attributes,
                    '{allowed_actions}',
                    '[]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET attributes = jsonb_set(
                    attributes,
                    '{allowed_actions}',
                    '["change.create"]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )

        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET clearance = 1, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET clearance = 3, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )

        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET attributes = jsonb_set(
                    attributes,
                    '{allowed_system_ids}',
                    '[]'::jsonb
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {"workspace_id": workspace_id, "requester_id": requester_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET attributes = jsonb_set(
                    attributes,
                    '{allowed_system_ids}',
                    jsonb_build_array(CAST(:system_id AS text))
                ),
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            {
                "workspace_id": workspace_id,
                "requester_id": requester_id,
                "system_id": str(target_system_id),
            },
        )

        domain_id = uuid4()
        await _update(
            engine,
            """
            UPDATE catalog.assets_projection
            SET domain_id = :domain_id
            WHERE workspace_id = :workspace_id AND id = :asset_id
            """,
            {
                "workspace_id": workspace_id,
                "asset_id": target_asset_id,
                "domain_id": domain_id,
            },
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE catalog.assets_projection
            SET domain_id = NULL
            WHERE workspace_id = :workspace_id AND id = :asset_id
            """,
            {"workspace_id": workspace_id, "asset_id": target_asset_id},
        )

        await _update(
            engine,
            """
            UPDATE integration.upload_preparation_jobs
            SET lease_until = clock_timestamp() - interval '1 minute'
            WHERE workspace_id = :workspace_id AND id = :preparation_id
            """,
            {
                "workspace_id": workspace_id,
                "preparation_id": preparation_id,
            },
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE integration.upload_preparation_jobs
            SET lease_until = :lease_until
            WHERE workspace_id = :workspace_id AND id = :preparation_id
            """,
            {
                "workspace_id": workspace_id,
                "preparation_id": preparation_id,
                "lease_until": parameters["lease_until"],
            },
        )

        assert (
            await _call_preparation_as_app(
                engine,
                {**parameters, "worker_subject_id": uuid4()},
            )
            is False
        )
        assert (
            await _call_preparation_as_app(
                engine,
                {
                    **parameters,
                    "target_asset_ids": [parameters["cross_workspace_asset_id"]],
                },
            )
            is False
        )

        await _update(
            engine,
            """
            UPDATE platform.data_systems
            SET active = false, version = version + 1
            WHERE workspace_id = :workspace_id AND id = :system_id
            """,
            {"workspace_id": workspace_id, "system_id": target_system_id},
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE platform.data_systems
            SET active = true, version = version + 1
            WHERE workspace_id = :workspace_id AND id = :system_id
            """,
            {"workspace_id": workspace_id, "system_id": target_system_id},
        )

        assert await persisted_candidate_count() == 0
        async with engine.connect() as connection:
            reasons = list(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT reason_codes ->> 0
                            FROM authz.policy_decisions
                            WHERE resource_id = :preparation_id
                              AND action =
                                    'registration.bulk.prepare.publish'
                            ORDER BY decided_at, id
                            """
                        ),
                        {"preparation_id": preparation_id},
                    )
                ).scalars()
            )
        assert reasons == [
            "POLICY_ALLOW",
            "CLASSIFICATION_POLICY_DENIED",
            "AUTHORIZATION_GENERATION_DRIFT",
            "RESTRICTED_GRANT_REQUIRED",
            "POLICY_ALLOW",
            "CURRENT_TARGET_SET_INVALID",
            "CURRENT_REQUESTER_INVALID",
            "CURRENT_ACTION_DENIED",
            "CURRENT_TARGET_SCOPE_DENIED",
            "CURRENT_TARGET_SCOPE_DENIED",
            "CURRENT_TARGET_SCOPE_DENIED",
            "CURRENT_PREPARATION_LEASE_INVALID",
            "CURRENT_PREPARATION_LEASE_INVALID",
            "CURRENT_TARGET_SET_INVALID",
            "CURRENT_TARGET_SET_INVALID",
        ]
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="isolated PostgreSQL evidence is not configured",
)
@pytest.mark.asyncio
async def test_preparation_reauthorization_uses_latest_running_claim_fence() -> None:
    engine = _engine()
    try:
        receipt_created_at = datetime.now(UTC) - timedelta(hours=2)
        generation_changed_at = receipt_created_at + timedelta(hours=1)
        reclaim_at = generation_changed_at + timedelta(minutes=30)
        base = await _seed_fixture(engine)
        parameters = await _seed_preparation_fixture(
            engine,
            base,
            receipt_created_at=receipt_created_at,
        )
        raw_lease_token = uuid4()
        lease_token_hash = hashlib.sha256(str(raw_lease_token).encode()).hexdigest()
        lease_until = datetime.now(UTC) + timedelta(minutes=30)

        await _update(
            engine,
            """
            UPDATE authz.classification_access_generations
            SET generation = generation + 1,
                updated_at = :generation_changed_at
            WHERE workspace_id = :workspace_id
            """,
            {
                "workspace_id": parameters["workspace_id"],
                "generation_changed_at": generation_changed_at,
            },
        )
        await _update(
            engine,
            """
            UPDATE integration.upload_preparation_jobs
            SET attempts = 3,
                lease_token = :lease_token,
                lease_until = :lease_until,
                version = version + 1
            WHERE workspace_id = :workspace_id
              AND id = :preparation_id
            """,
            {
                "workspace_id": parameters["workspace_id"],
                "preparation_id": parameters["preparation_id"],
                "lease_token": raw_lease_token,
                "lease_until": lease_until,
            },
        )
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(parameters["workspace_id"])},
            )
            await connection.execute(
                text("SELECT set_config('app.subject_id', :value, true)"),
                {"value": str(parameters["worker_subject_id"])},
            )
            await connection.execute(
                text(
                    """
                    SELECT set_config(
                        'app.registration_worker_claim_token',
                        :value,
                        true
                    )
                    """
                ),
                {"value": str(raw_lease_token)},
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.registration_worker_call_receipts
                    SET claim_attempt = 3,
                        claim_token_hash = :lease_token_hash,
                        lease_expires_at = :lease_until,
                        updated_at = :reclaim_at
                    WHERE workspace_id = :workspace_id
                      AND operation =
                            'registration.bulk-preparation.execute-run.v1'
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": parameters["workspace_id"],
                    "key_hash": parameters["key_hash"],
                    "lease_token_hash": lease_token_hash,
                    "lease_until": lease_until,
                    "reclaim_at": reclaim_at,
                },
            )

        reclaimed_parameters = {
            **parameters,
            "attempt": 3,
            "lease_token_hash": lease_token_hash,
            "lease_until": lease_until,
        }
        async with engine.connect() as connection:
            timestamps = (
                await connection.execute(
                    text(
                        """
                        SELECT call_receipt.created_at,
                               generation.updated_at,
                               call_receipt.updated_at
                        FROM integration.registration_worker_call_receipts
                            AS call_receipt
                        JOIN authz.classification_access_generations AS generation
                          ON generation.workspace_id =
                                call_receipt.workspace_id
                        WHERE call_receipt.workspace_id = :workspace_id
                          AND call_receipt.key_hash = :key_hash
                        """
                    ),
                    {
                        "workspace_id": parameters["workspace_id"],
                        "key_hash": parameters["key_hash"],
                    },
                )
            ).one()
        assert timestamps[0] < timestamps[1] < timestamps[2]
        assert await _call_preparation_as_app(engine, reclaimed_parameters) is True
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="isolated PostgreSQL evidence is not configured",
)
@pytest.mark.asyncio
async def test_preparation_success_holds_reauthorization_rows_until_commit() -> None:
    engine = _engine()
    try:
        base = await _seed_fixture(engine)
        parameters = await _seed_preparation_fixture(engine, base)
        membership_revoke = """
            UPDATE iam.workspace_memberships
            SET active = false, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
        """
        membership_parameters = {
            "workspace_id": parameters["workspace_id"],
            "requester_id": parameters["requested_by"],
        }

        async def bounded_update(
            statement: str,
            update_parameters: dict[str, object],
        ) -> None:
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL lock_timeout = '2s'"))
                await connection.execute(text(statement), update_parameters)

        async def assert_update_blocks_until_authorization_commit(
            statement: str,
            update_parameters: dict[str, object],
        ) -> None:
            update_task: asyncio.Task[None] | None = None
            async with engine.connect() as authorization_connection:
                transaction = await authorization_connection.begin()
                try:
                    await authorization_connection.execute(
                        text(
                            """
                            SELECT asset.id
                            FROM catalog.assets_projection AS asset
                            WHERE asset.workspace_id = :workspace_id
                              AND asset.id = :target_asset_id
                            ORDER BY asset.id
                            FOR SHARE
                            """
                        ),
                        {
                            "workspace_id": parameters["workspace_id"],
                            "target_asset_id": parameters["target_asset_id"],
                        },
                    )
                    assert (
                        await _call_preparation_on_connection(
                            authorization_connection,
                            parameters,
                        )
                        is True
                    )
                    update_task = asyncio.create_task(bounded_update(statement, update_parameters))
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(
                            asyncio.shield(update_task),
                            timeout=0.2,
                        )
                    await transaction.commit()
                    await asyncio.wait_for(update_task, timeout=5)
                finally:
                    if transaction.is_active:
                        await transaction.rollback()
                    if update_task is not None and not update_task.done():
                        update_task.cancel()
                        await asyncio.gather(update_task, return_exceptions=True)

        coarse_update_task: asyncio.Task[None] | None = None
        async with engine.connect() as coarse_connection:
            coarse_transaction = await coarse_connection.begin()
            try:
                assert (
                    await _call_preparation_on_connection(
                        coarse_connection,
                        {**parameters, "lock_for_publication": False},
                    )
                    is True
                )
                coarse_update_task = asyncio.create_task(
                    bounded_update(membership_revoke, membership_parameters)
                )
                await asyncio.wait_for(coarse_update_task, timeout=1)
            finally:
                if coarse_transaction.is_active:
                    await coarse_transaction.rollback()
                if coarse_update_task is not None and not coarse_update_task.done():
                    coarse_update_task.cancel()
                    await asyncio.gather(
                        coarse_update_task,
                        return_exceptions=True,
                    )
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET active = true, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            membership_parameters,
        )

        await assert_update_blocks_until_authorization_commit(
            membership_revoke,
            membership_parameters,
        )
        assert await _call_preparation_as_app(engine, parameters) is False
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET active = true, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            membership_parameters,
        )

        await assert_update_blocks_until_authorization_commit(
            """
            UPDATE authz.classification_access_policy_rules
            SET search_mode = 'DENY'
            WHERE workspace_id = :workspace_id
              AND policy_id = :policy_id
              AND classification = 2
            """,
            {
                "workspace_id": parameters["workspace_id"],
                "policy_id": base["policy_id"],
            },
        )
        assert await _call_preparation_as_app(engine, parameters) is False

        denied_update_task: asyncio.Task[None] | None = None
        async with engine.connect() as denied_connection:
            denied_transaction = await denied_connection.begin()
            try:
                assert (
                    await _call_preparation_on_connection(
                        denied_connection,
                        parameters,
                    )
                    is False
                )
                denied_update_task = asyncio.create_task(
                    bounded_update(membership_revoke, membership_parameters)
                )
                await asyncio.wait_for(denied_update_task, timeout=1)
            finally:
                if denied_transaction.is_active:
                    await denied_transaction.rollback()
                if denied_update_task is not None and not denied_update_task.done():
                    denied_update_task.cancel()
                    await asyncio.gather(
                        denied_update_task,
                        return_exceptions=True,
                    )
        await _update(
            engine,
            """
            UPDATE iam.workspace_memberships
            SET active = true, version = version + 1
            WHERE workspace_id = :workspace_id
              AND subject_id = :requester_id
            """,
            membership_parameters,
        )

        async with engine.connect() as connection:
            persisted_evidence_count = await connection.scalar(
                text(
                    """
                    SELECT
                        (
                            SELECT pg_catalog.count(*)
                            FROM integration.upload_preparation_receipts
                            WHERE workspace_id = :workspace_id
                              AND preparation_job_id = :preparation_id
                        )
                        + (
                            SELECT pg_catalog.count(*)
                            FROM integration.catalog_metadata_rows AS source_row
                            JOIN integration.upload_preparation_receipts AS receipt
                              ON receipt.workspace_id = source_row.workspace_id
                             AND receipt.id = source_row.receipt_id
                            WHERE receipt.workspace_id = :workspace_id
                              AND receipt.preparation_job_id = :preparation_id
                        )
                        + (
                            SELECT pg_catalog.count(*)
                            FROM integration.catalog_metadata_candidates
                                AS candidate
                            JOIN integration.upload_preparation_receipts AS receipt
                              ON receipt.workspace_id = candidate.workspace_id
                             AND receipt.id = candidate.receipt_id
                            WHERE receipt.workspace_id = :workspace_id
                              AND receipt.preparation_job_id = :preparation_id
                        )
                        + (
                            SELECT pg_catalog.count(*)
                            FROM integration.catalog_metadata_candidate_rows
                                AS candidate_row
                            JOIN integration.upload_preparation_receipts AS receipt
                              ON receipt.workspace_id =
                                    candidate_row.workspace_id
                             AND receipt.id = candidate_row.receipt_id
                            WHERE receipt.workspace_id = :workspace_id
                              AND receipt.preparation_job_id = :preparation_id
                        )
                    """
                ),
                {
                    "workspace_id": parameters["workspace_id"],
                    "preparation_id": parameters["preparation_id"],
                },
            )
        assert int(persisted_evidence_count or 0) == 0
    finally:
        await engine.dispose()
