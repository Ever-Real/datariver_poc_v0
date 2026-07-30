from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.secrets import SecretResolver

_CONFIRM_ENV = "DATARIVER_PROFILE_TEST_CONFIRM_ISOLATED"
_OWNER_URL_ENV = "DATARIVER_PROFILE_TEST_OWNER_DATABASE_URL"
_OWNER_SECRET_REF_ENV = "DATARIVER_PROFILE_TEST_OWNER_DATABASE_SECRET_REF"
_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = _ROOT / "backend/alembic/versions/0068_catalog_profile_projection.py"


def _require_isolated_postgres() -> None:
    if (
        os.getenv(_CONFIRM_ENV) != "1"
        or not os.getenv(_OWNER_URL_ENV)
        or not os.getenv(_OWNER_SECRET_REF_ENV)
    ):
        pytest.skip("isolated Catalog Profile PostgreSQL environment is not configured")


def _revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("catalog_profile_0068_live", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine() -> AsyncEngine:
    return create_async_engine(
        os.environ[_OWNER_URL_ENV],
        connect_args={"password": SecretResolver().resolve(os.environ[_OWNER_SECRET_REF_ENV])},
        poolclass=NullPool,
    )


async def _set_context(
    connection: AsyncConnection, *, workspace_id: UUID, subject_id: UUID
) -> None:
    await connection.execute(
        text(
            "SELECT set_config('app.workspace_id', :workspace_id, false), "
            "set_config('app.subject_id', :subject_id, false)"
        ),
        {"workspace_id": str(workspace_id), "subject_id": str(subject_id)},
    )


@pytest.mark.asyncio
async def test_profile_projection_role_retention_and_reobservation() -> None:
    _require_isolated_postgres()
    engine = _engine()
    workspace_id, collector_id, requester_id, checker_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    asset_id, policy_id = uuid4(), uuid4()
    policy_hash = policy_id.hex * 2
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM public.alembic_version"))
                == REQUIRED_DATABASE_REVISION
            )
            await connection.commit()
            async with connection.begin():
                await _set_context(
                    connection,
                    workspace_id=workspace_id,
                    subject_id=collector_id,
                )
                await connection.execute(
                    text(
                        "INSERT INTO platform.workspaces "
                        "(id, slug, name, status, settings, version) "
                        "VALUES (:id, :slug, 'Profile integration', "
                        "'ACTIVE', '{}'::jsonb, 1)"
                    ),
                    {"id": workspace_id, "slug": f"profile-{workspace_id.hex}"},
                )
                for subject_id, label, job_function, attributes in (
                    (
                        collector_id,
                        "collector",
                        "SERVICE_ACCOUNT",
                        {
                            "groups": [
                                "service-accounts",
                                "catalog-profile-collectors",
                            ],
                            "allowed_actions": ["catalog.profile.collect"],
                            "denied_actions": [],
                            "allowed_system_ids": [],
                            "allowed_domain_ids": [],
                        },
                    ),
                    (requester_id, "requester", "OWNER", {}),
                    (checker_id, "checker", "CHECKER", {}),
                ):
                    await connection.execute(
                        text(
                            "INSERT INTO iam.subjects "
                            "(id, issuer, external_subject, display_name, active) "
                            "VALUES (:id, 'https://profile.test', :external, :label, true)"
                        ),
                        {
                            "id": subject_id,
                            "external": subject_id.hex,
                            "label": label,
                        },
                    )
                    membership = text(
                        "INSERT INTO iam.workspace_memberships ("
                        "workspace_id, subject_id, job_function, clearance, "
                        "attributes, active, version"
                        ") VALUES (:workspace_id, :subject_id, :job_function, "
                        "3, :attributes, true, 1)"
                    ).bindparams(bindparam("attributes", type_=JSONB))
                    await connection.execute(
                        membership,
                        {
                            "workspace_id": workspace_id,
                            "subject_id": subject_id,
                            "job_function": job_function,
                            "attributes": attributes,
                        },
                    )
                await connection.execute(
                    text(
                        "INSERT INTO retention.policy_versions ("
                        "id, workspace_id, policy_number, completed_operation_days, "
                        "chat_content_days, audit_online_months, immutable_archive_years, "
                        "contract_version, effective_from, execution_authorization_hours, "
                        "payload_hash, requester_id, request_reason, "
                        "request_policy_decision_id, state, checker_id, decision_reason, "
                        "decision_policy_decision_id, decided_at, version"
                        ") VALUES ("
                        ":policy_id, :workspace_id, 1, 30, 30, 12, 7, "
                        "'POLICY_BOOK_V4', transaction_timestamp() - interval '1 day', "
                        "24, :policy_hash, :requester_id, 'Profile test policy', "
                        ":request_decision_id, 'ACTIVE', :checker_id, 'approved', "
                        ":checker_decision_id, transaction_timestamp(), 1)"
                    ),
                    {
                        "policy_id": policy_id,
                        "workspace_id": workspace_id,
                        "policy_hash": policy_hash,
                        "requester_id": requester_id,
                        "request_decision_id": uuid4(),
                        "checker_id": checker_id,
                        "checker_decision_id": uuid4(),
                    },
                )
                for data_class in (
                    "COMPLETED_OPERATIONS",
                    "CHAT_CONTENT",
                    "AUDIT_EVIDENCE",
                    "OBJECT_DATA",
                    "QUALITY_RULE",
                    "QUALITY_RESULT",
                    "QUALITY_AUDIT",
                    "QUALITY_PROFILE",
                ):
                    rule_id = uuid4()
                    await connection.execute(
                        text(
                            "INSERT INTO retention.policy_class_rules ("
                            "id, workspace_id, policy_id, policy_hash, policy_number, "
                            "data_class, unit, minimum_value, maximum_value, "
                            "archive_disposition, payload_hash"
                            ") VALUES ("
                            ":id, :workspace_id, :policy_id, :policy_hash, 1, "
                            ":data_class, 'DAYS', 30, 365, 'NO_ARCHIVE', :rule_hash)"
                        ),
                        {
                            "id": rule_id,
                            "workspace_id": workspace_id,
                            "policy_id": policy_id,
                            "policy_hash": policy_hash,
                            "data_class": data_class,
                            "rule_hash": rule_id.hex * 2,
                        },
                    )
                await connection.execute(
                    text(
                        "INSERT INTO catalog.assets_projection ("
                        "id, workspace_id, external_urn, urn_hash, asset_type, name, "
                        "tags, glossary_terms, column_names, classification, lifecycle, "
                        "source_version, observed_at, projection_source"
                        ") VALUES ("
                        ":asset_id, :workspace_id, :urn, :urn_hash, 'DATASET', "
                        "'Profile asset', '[]'::jsonb, '[]'::jsonb, '[\"id\"]'::jsonb, "
                        "0, 'ACTIVE', 'source-v1', transaction_timestamp(), 'DATAHUB')"
                    ),
                    {
                        "asset_id": asset_id,
                        "workspace_id": workspace_id,
                        "urn": f"urn:li:dataset:{asset_id}",
                        "urn_hash": asset_id.hex * 2,
                    },
                )

        now = datetime.now(tz=UTC)
        payload = {
            "asset_source_version": "source-v1",
            "classification": 0,
            "column_count": 1,
            "columns": [
                {
                    "field_path": "id",
                    "null_count": 0,
                    "null_proportion": 0.0,
                    "unique_count": 10,
                    "unique_proportion": 1.0,
                }
            ],
            "completeness": "COMPLETE",
            "domain_id": None,
            "normalized_payload_hash": "1" * 64,
            "observed_at": now.isoformat(),
            "profile_kind": "FULL",
            "profiled_at": now.isoformat(),
            "provenance_fingerprint": None,
            "provenance_key_id": None,
            "provider_config_hash": "2" * 64,
            "provider_contract_hash": "3" * 64,
            "provider_query_hash": "4" * 64,
            "provider_version": "v1.6.0",
            "row_count": 10,
            "size_bytes": 100,
            "source_watermark_hash": "5" * 64,
            "stale_at": (now + timedelta(hours=1)).isoformat(),
            "system_id": None,
        }
        async with engine.connect() as collector:
            await collector.execute(text("SET SESSION AUTHORIZATION datariver_catalog_profile"))
            await _set_context(
                collector,
                workspace_id=workspace_id,
                subject_id=collector_id,
            )
            target = (
                await collector.execute(
                    text("SELECT * FROM catalog.read_profile_target_v1(:workspace_id, :asset_id)"),
                    {"workspace_id": workspace_id, "asset_id": asset_id},
                )
            ).one()
            assert target.source_version == "source-v1"
            project = text(
                "SELECT * FROM catalog.project_asset_profile_v1(:workspace_id, :asset_id, :payload)"
            ).bindparams(bindparam("payload", type_=JSONB))
            first = (
                await collector.execute(
                    project,
                    {
                        "workspace_id": workspace_id,
                        "asset_id": asset_id,
                        "payload": payload,
                    },
                )
            ).one()
            payload["observed_at"] = (now + timedelta(seconds=1)).isoformat()
            second = (
                await collector.execute(
                    project,
                    {
                        "workspace_id": workspace_id,
                        "asset_id": asset_id,
                        "payload": payload,
                    },
                )
            ).one()
            assert first.created is True
            assert second.created is False
            assert first.snapshot_id == second.snapshot_id
            assert second.last_observed_at > first.last_observed_at

            savepoint = await collector.begin_nested()
            with pytest.raises(DBAPIError):
                await collector.scalar(text("SELECT count(*) FROM catalog.asset_profile_snapshots"))
            await savepoint.rollback()
            await collector.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_catalog_fingerprint_detects_security_drift() -> None:
    _require_isolated_postgres()
    engine = _engine()
    revision = _revision()
    try:
        async with engine.connect() as connection:
            assert await connection.run_sync(revision._catalog_contract_hash) == (
                revision._PROFILE_CATALOG_CONTRACT_HASH
            )
            await connection.commit()
            transaction = await connection.begin()
            await connection.execute(
                text("ALTER TABLE catalog.asset_profile_snapshots DISABLE ROW LEVEL SECURITY")
            )
            assert await connection.run_sync(revision._catalog_contract_hash) != (
                revision._PROFILE_CATALOG_CONTRACT_HASH
            )
            await transaction.rollback()
    finally:
        await engine.dispose()
