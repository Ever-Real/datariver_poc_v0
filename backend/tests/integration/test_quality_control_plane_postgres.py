from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.secrets import SecretResolver

_OWNER_URL_ENV = "DATARIVER_QUALITY_TEST_OWNER_DATABASE_URL"
_OWNER_SECRET_REF_ENV = "DATARIVER_QUALITY_TEST_OWNER_DATABASE_SECRET_REF"
_CONFIRM_ENV = "DATARIVER_QUALITY_TEST_CONFIRM_ISOLATED"
_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = _ROOT / "backend/alembic/versions/0067_quality_control_plane.py"


def _engine() -> AsyncEngine:
    password = SecretResolver().resolve(os.environ[_OWNER_SECRET_REF_ENV])
    return create_async_engine(
        os.environ[_OWNER_URL_ENV],
        connect_args={"password": password},
        pool_size=2,
        max_overflow=0,
    )


def _quality_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quality_0067_live_test", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require_isolated_postgres() -> None:
    if (
        os.getenv(_CONFIRM_ENV) != "1"
        or not os.getenv(_OWNER_URL_ENV)
        or not os.getenv(_OWNER_SECRET_REF_ENV)
    ):
        pytest.skip("isolated Quality PostgreSQL environment is not configured")


async def _set_workspace(connection: AsyncConnection, workspace_id: UUID) -> None:
    await connection.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": str(workspace_id)},
    )


async def _set_subject(connection: AsyncConnection, subject_id: UUID) -> None:
    await connection.execute(
        text("SELECT set_config('app.subject_id', :subject_id, true)"),
        {"subject_id": str(subject_id)},
    )


@pytest.mark.asyncio
async def test_quality_catalog_fingerprint_rejects_same_name_security_drift() -> None:
    _require_isolated_postgres()
    revision = _quality_revision()
    engine = _engine()
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                REQUIRED_DATABASE_REVISION
            )
            assert await connection.run_sync(revision._catalog_contract_hash) == (
                revision._QUALITY_CANONICAL_HEAD_CONTRACT_HASH
            )
            await connection.commit()

            async def assert_rejected_drift(statement: str) -> None:
                transaction = await connection.begin()
                await connection.execute(text(statement))
                assert await connection.run_sync(revision._catalog_contract_hash) != (
                    revision._QUALITY_CANONICAL_HEAD_CONTRACT_HASH
                )
                await transaction.rollback()
                assert await connection.run_sync(revision._catalog_contract_hash) == (
                    revision._QUALITY_CANONICAL_HEAD_CONTRACT_HASH
                )
                await connection.commit()

            await assert_rejected_drift(
                "ALTER FUNCTION quality.current_target_matches_v1("
                "uuid, uuid, integer, uuid, uuid, text, text, text) "
                "SECURITY INVOKER"
            )
            await assert_rejected_drift("ALTER TABLE quality.rule_sets DISABLE ROW LEVEL SECURITY")
            await assert_rejected_drift(
                "GRANT EXECUTE ON FUNCTION quality.current_target_matches_v1("
                "uuid, uuid, integer, uuid, uuid, text, text, text) "
                "TO datariver_relay"
            )
            await assert_rejected_drift(
                "ALTER TABLE retention.policy_class_rules "
                "DROP CONSTRAINT ck_policy_class_rules_data_class, "
                "ADD CONSTRAINT ck_policy_class_rules_data_class "
                "CHECK (true) NOT VALID"
            )
            await assert_rejected_drift(
                "ALTER TABLE retention.legal_holds DISABLE TRIGGER refresh_legal_hold_generation"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_quality_current_target_rejects_live_catalog_drift() -> None:
    _require_isolated_postgres()
    engine = _engine()
    workspace_id, subject_id, asset_id = uuid4(), uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await _set_workspace(connection, workspace_id)
            await _set_subject(connection, subject_id)
            await connection.execute(
                text(
                    "INSERT INTO platform.workspaces "
                    "(id, slug, name, status, settings, version) "
                    "VALUES (:id, :slug, :name, 'ACTIVE', '{}'::jsonb, 1)"
                ),
                {
                    "id": workspace_id,
                    "slug": f"quality-target-{workspace_id.hex}",
                    "name": "Quality live target test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO iam.subjects "
                    "(id, issuer, external_subject, display_name, active) "
                    "VALUES (:id, :issuer, :external_subject, 'Quality reviewer', true)"
                ),
                {
                    "id": subject_id,
                    "issuer": f"https://quality.test/{workspace_id}",
                    "external_subject": subject_id.hex,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO iam.workspace_memberships "
                    "(workspace_id, subject_id, clearance, attributes, active, version) "
                    "VALUES ("
                    ":workspace_id, :subject_id, 3, "
                    "jsonb_build_object("
                    "'allowed_actions', jsonb_build_array("
                    "'quality.rule.review', 'quality.rule.activate'"
                    ")), true, 1)"
                ),
                {"workspace_id": workspace_id, "subject_id": subject_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO catalog.assets_projection ("
                    "id, workspace_id, external_urn, urn_hash, asset_type, name, "
                    "tags, glossary_terms, column_names, classification, lifecycle, "
                    "source_version, observed_at, projection_source"
                    ") VALUES ("
                    ":asset_id, :workspace_id, :urn, :urn_hash, 'DATASET', "
                    "'Quality target', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, "
                    "0, 'ACTIVE', 'source-v1', transaction_timestamp(), 'DATAHUB')"
                ),
                {
                    "asset_id": asset_id,
                    "workspace_id": workspace_id,
                    "urn": f"urn:li:dataset:quality:{asset_id}",
                    "urn_hash": asset_id.hex * 2,
                },
            )

            target_query = text(
                "SELECT quality.current_target_matches_v1("
                ":workspace_id, :asset_id, 0, NULL, NULL, "
                "'ACTIVE', 'source-v1', :action)"
            )
            parameters = {
                "workspace_id": workspace_id,
                "asset_id": asset_id,
                "action": "quality.rule.review",
            }
            assert await connection.scalar(target_query, parameters) is True

            await connection.execute(
                text(
                    "UPDATE catalog.assets_projection SET source_version = 'source-v2' "
                    "WHERE workspace_id = :workspace_id AND id = :asset_id"
                ),
                parameters,
            )
            assert await connection.scalar(target_query, parameters) is False

            await connection.execute(
                text(
                    "UPDATE catalog.assets_projection "
                    "SET source_version = 'source-v1', classification = 1 "
                    "WHERE workspace_id = :workspace_id AND id = :asset_id"
                ),
                parameters,
            )
            assert await connection.scalar(target_query, parameters) is False

            await connection.execute(
                text(
                    "UPDATE catalog.assets_projection "
                    "SET classification = 0, deleted_at = transaction_timestamp() "
                    "WHERE workspace_id = :workspace_id AND id = :asset_id"
                ),
                parameters,
            )
            assert await connection.scalar(target_query, parameters) is False
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_quality_retention_resolver_initializes_a_new_workspace_generation() -> None:
    _require_isolated_postgres()
    engine = _engine()
    workspace_id, requester_id, checker_id = uuid4(), uuid4(), uuid4()
    policy_id, resource_id = uuid4(), uuid4()
    policy_hash = policy_id.hex * 2
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await _set_workspace(connection, workspace_id)
            await _set_subject(connection, requester_id)
            await connection.execute(
                text(
                    "INSERT INTO platform.workspaces "
                    "(id, slug, name, status, settings, version) "
                    "VALUES (:id, :slug, 'Quality genesis test', 'ACTIVE', '{}'::jsonb, 1)"
                ),
                {
                    "id": workspace_id,
                    "slug": f"quality-genesis-{workspace_id.hex}",
                },
            )
            for subject_id, label in (
                (requester_id, "requester"),
                (checker_id, "checker"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO iam.subjects "
                        "(id, issuer, external_subject, display_name, active) "
                        "VALUES (:id, :issuer, :external_subject, :display_name, true)"
                    ),
                    {
                        "id": subject_id,
                        "issuer": f"https://quality-genesis.test/{workspace_id}",
                        "external_subject": subject_id.hex,
                        "display_name": f"Quality {label}",
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO iam.workspace_memberships "
                        "(workspace_id, subject_id, clearance, attributes, active, version) "
                        "VALUES (:workspace_id, :subject_id, 3, '{}'::jsonb, true, 1)"
                    ),
                    {"workspace_id": workspace_id, "subject_id": subject_id},
                )
            await connection.execute(
                text(
                    "INSERT INTO retention.policy_versions ("
                    "id, workspace_id, policy_number, completed_operation_days, "
                    "chat_content_days, audit_online_months, immutable_archive_years, "
                    "contract_version, effective_from, execution_authorization_hours, "
                    "payload_hash, requester_id, request_reason, request_policy_decision_id, "
                    "state, checker_id, decision_reason, decision_policy_decision_id, "
                    "decided_at, version"
                    ") VALUES ("
                    ":policy_id, :workspace_id, 1, 30, 30, 12, 7, 'POLICY_BOOK_V3', "
                    "transaction_timestamp() - interval '1 day', 24, :policy_hash, "
                    ":requester_id, 'Quality genesis policy', :request_decision_id, "
                    "'ACTIVE', :checker_id, 'Approved for isolated test', "
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
            ):
                class_rule_id = uuid4()
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
                        "id": class_rule_id,
                        "workspace_id": workspace_id,
                        "policy_id": policy_id,
                        "policy_hash": policy_hash,
                        "data_class": data_class,
                        "rule_hash": class_rule_id.hex * 2,
                    },
                )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM retention.legal_hold_generations "
                        "WHERE workspace_id = :workspace_id "
                        "AND data_class = 'QUALITY_RULE'"
                    ),
                    {"workspace_id": workspace_id},
                )
                == 0
            )
            binding = (
                await connection.execute(
                    text(
                        "SELECT hold_generation, hold_hash "
                        "FROM retention.resolve_quality_binding_v1("
                        ":workspace_id, 'QUALITY_RULE', 'QUALITY_RULE_SET', "
                        ":resource_id, transaction_timestamp())"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "resource_id": resource_id,
                    },
                )
            ).one()
            assert binding.hold_generation == 1
            assert len(binding.hold_hash) == 64
            assert (
                await connection.scalar(
                    text(
                        "SELECT generation FROM retention.legal_hold_generations "
                        "WHERE workspace_id = :workspace_id "
                        "AND data_class = 'QUALITY_RULE'"
                    ),
                    {"workspace_id": workspace_id},
                )
                == 1
            )
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_quality_command_creates_run_event_and_outbox_atomically() -> None:
    _require_isolated_postgres()
    engine = _engine()
    workspace_id, author_id, runner_id = uuid4(), uuid4(), uuid4()
    policy_id, asset_id, rule_set_id, version_id, definition_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    policy_decision_id = uuid4()
    policy_hash = policy_id.hex * 2
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await _set_workspace(connection, workspace_id)
            await _set_subject(connection, runner_id)
            await connection.execute(
                text(
                    "INSERT INTO platform.workspaces "
                    "(id, slug, name, status, settings, version) "
                    "VALUES (:id, :slug, 'Quality command test', 'ACTIVE', '{}'::jsonb, 1)"
                ),
                {
                    "id": workspace_id,
                    "slug": f"quality-command-{workspace_id.hex}",
                },
            )
            for subject_id, label, attributes in (
                (author_id, "author", "{}"),
                (
                    runner_id,
                    "runner",
                    '{"allowed_actions":["quality.run.request"]}',
                ),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO iam.subjects "
                        "(id, issuer, external_subject, display_name, active) "
                        "VALUES (:id, :issuer, :external_subject, :display_name, true)"
                    ),
                    {
                        "id": subject_id,
                        "issuer": f"https://quality-command.test/{workspace_id}",
                        "external_subject": subject_id.hex,
                        "display_name": f"Quality {label}",
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO iam.workspace_memberships "
                        "(workspace_id, subject_id, clearance, attributes, active, version) "
                        "VALUES (:workspace_id, :subject_id, 3, "
                        "CAST(:attributes AS jsonb), true, 1)"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "subject_id": subject_id,
                        "attributes": attributes,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO retention.policy_versions ("
                    "id, workspace_id, policy_number, completed_operation_days, "
                    "chat_content_days, audit_online_months, immutable_archive_years, "
                    "contract_version, effective_from, execution_authorization_hours, "
                    "payload_hash, requester_id, request_reason, request_policy_decision_id, "
                    "state, checker_id, decision_reason, decision_policy_decision_id, "
                    "decided_at, version"
                    ") VALUES ("
                    ":policy_id, :workspace_id, 1, 30, 30, 12, 7, 'POLICY_BOOK_V3', "
                    "transaction_timestamp() - interval '1 day', 24, :policy_hash, "
                    ":author_id, 'Quality command policy', :request_decision_id, "
                    "'ACTIVE', :runner_id, 'Approved for isolated command test', "
                    ":checker_decision_id, transaction_timestamp(), 1)"
                ),
                {
                    "policy_id": policy_id,
                    "workspace_id": workspace_id,
                    "policy_hash": policy_hash,
                    "author_id": author_id,
                    "request_decision_id": uuid4(),
                    "runner_id": runner_id,
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
            ):
                class_rule_id = uuid4()
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
                        "id": class_rule_id,
                        "workspace_id": workspace_id,
                        "policy_id": policy_id,
                        "policy_hash": policy_hash,
                        "data_class": data_class,
                        "rule_hash": class_rule_id.hex * 2,
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
                    "'Quality command asset', '[]'::jsonb, '[]'::jsonb, "
                    "'[\"id\"]'::jsonb, 0, 'ACTIVE', 'source-v1', "
                    "transaction_timestamp(), 'DATAHUB')"
                ),
                {
                    "asset_id": asset_id,
                    "workspace_id": workspace_id,
                    "urn": f"urn:li:dataset:quality-command:{asset_id}",
                    "urn_hash": asset_id.hex * 2,
                },
            )
            rule_binding = (
                (
                    await connection.execute(
                        text(
                            "SELECT * FROM retention.resolve_quality_binding_v1("
                            ":workspace_id, 'QUALITY_RULE', 'QUALITY_RULE_SET', "
                            ":rule_set_id, transaction_timestamp())"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "rule_set_id": rule_set_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            binding_parameters = {
                "workspace_id": workspace_id,
                "rule_set_id": rule_set_id,
                "asset_id": asset_id,
                "author_id": author_id,
                "runner_id": runner_id,
                "policy_id": rule_binding["policy_id"],
                "policy_number": rule_binding["policy_number"],
                "policy_hash": rule_binding["policy_hash"],
                "retain_until": rule_binding["retain_until"],
                "hold_generation": rule_binding["hold_generation"],
                "hold_hash": rule_binding["hold_hash"],
            }
            await _set_subject(connection, author_id)
            await connection.execute(
                text(
                    "INSERT INTO quality.rule_sets ("
                    "id, workspace_id, asset_id, name, state, created_by, updated_by, "
                    "rule_retention_kind, rule_retention_policy_id, "
                    "rule_retention_policy_number, rule_retention_policy_hash, "
                    "rule_retention_basis_at, rule_retain_until, "
                    "rule_hold_generation, rule_hold_hash, version"
                    ") VALUES ("
                    ":rule_set_id, :workspace_id, :asset_id, 'Manual command', 'ACTIVE', "
                    ":author_id, :author_id, 'QUALITY_RULE', :policy_id, :policy_number, "
                    ":policy_hash, transaction_timestamp(), :retain_until, "
                    ":hold_generation, :hold_hash, 1)"
                ),
                binding_parameters,
            )
            await connection.execute(
                text(
                    "INSERT INTO quality.rule_set_versions ("
                    "id, workspace_id, rule_set_id, version_number, author_id, state, "
                    "asset_id, classification, lifecycle, source_version, "
                    "target_binding_hash, schema_hash, "
                    "source_connection_profile_id, source_connection_profile_version, "
                    "source_connection_profile_hash, workload_profile_id, "
                    "workload_profile_version, workload_profile_hash, "
                    "compiler_contract_version, gx_version, compiler_hash, "
                    "score_policy_id, score_policy_version, score_policy_hash, "
                    "schedule_mode, rule_retention_kind, rule_retention_policy_id, "
                    "rule_retention_policy_number, rule_retention_policy_hash, "
                    "rule_retention_basis_at, rule_retain_until, rule_hold_generation, "
                    "rule_hold_hash, reviewed_by, reviewed_at, activated_by, "
                    "activated_at, version"
                    ") VALUES ("
                    ":version_id, :workspace_id, :rule_set_id, 1, :author_id, 'ACTIVE', "
                    ":asset_id, 0, 'ACTIVE', 'source-v1', "
                    ":target_hash, :schema_hash, 'source-profile', 1, :source_hash, "
                    "'workload-profile', 1, :workload_hash, "
                    "'GX_RULE_COMPILER_V1', '1.19.1', :compiler_hash, "
                    "'blocking-weighted-v1', 1, :score_hash, "
                    "'MANUAL_ONLY', 'QUALITY_RULE', :policy_id, :policy_number, "
                    ":policy_hash, transaction_timestamp(), :retain_until, "
                    ":hold_generation, :hold_hash, :runner_id, transaction_timestamp(), "
                    ":runner_id, transaction_timestamp(), 3)"
                ),
                {
                    **binding_parameters,
                    "version_id": version_id,
                    "target_hash": "1" * 64,
                    "schema_hash": "2" * 64,
                    "source_hash": "3" * 64,
                    "workload_hash": "4" * 64,
                    "compiler_hash": "5" * 64,
                    "score_hash": "6" * 64,
                },
            )
            await _set_subject(connection, runner_id)
            await connection.execute(
                text(
                    "INSERT INTO quality.rule_definitions ("
                    "id, workspace_id, rule_set_version_id, ordinal, field_identifier, "
                    "kind, severity, parameters, definition_hash, rule_retention_kind, "
                    "rule_retention_policy_id, rule_retention_policy_number, "
                    "rule_retention_policy_hash, rule_retain_until, "
                    "rule_hold_generation, rule_hold_hash"
                    ") VALUES ("
                    ":definition_id, :workspace_id, :version_id, 1, 'id', "
                    "'NOT_NULL', 'BLOCKING', '{}'::jsonb, :definition_hash, "
                    "'QUALITY_RULE', :policy_id, :policy_number, :policy_hash, "
                    ":retain_until, :hold_generation, :hold_hash)"
                ),
                {
                    **binding_parameters,
                    "definition_id": definition_id,
                    "version_id": version_id,
                    "definition_hash": "7" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO authz.policy_decisions ("
                    "id, workspace_id, subject_id, resource_id, action, effect, "
                    "reason_codes, policy_versions, evaluation_context, request_id, decided_at"
                    ") VALUES ("
                    ":decision_id, :workspace_id, :runner_id, :version_id, "
                    "'quality.run.request', 'ALLOW', '[\"QUALITY_RUN_ALLOWED\"]'::jsonb, "
                    "'[\"builtin-abac-v2\"]'::jsonb, '{}'::jsonb, "
                    ":request_id, transaction_timestamp())"
                ),
                {
                    "decision_id": policy_decision_id,
                    "workspace_id": workspace_id,
                    "runner_id": runner_id,
                    "version_id": version_id,
                    "request_id": f"quality-run-{version_id.hex}",
                },
            )
            run_id = await connection.scalar(
                text(
                    "SELECT quality.request_manual_validation_run_v1("
                    ":workspace_id, :rule_set_id, :decision_id)"
                ),
                {
                    "workspace_id": workspace_id,
                    "rule_set_id": rule_set_id,
                    "decision_id": policy_decision_id,
                },
            )
            assert run_id is not None
            await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            run = (
                await connection.execute(
                    text(
                        "SELECT state, trigger_kind, requested_by "
                        "FROM quality.validation_runs "
                        "WHERE workspace_id = :workspace_id AND id = :run_id"
                    ),
                    {"workspace_id": workspace_id, "run_id": run_id},
                )
            ).one()
            assert (run.state, run.trigger_kind, run.requested_by) == (
                "QUEUED",
                "MANUAL",
                runner_id,
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM quality.run_events "
                        "WHERE workspace_id = :workspace_id AND run_id = :run_id "
                        "AND state = 'QUEUED'"
                    ),
                    {"workspace_id": workspace_id, "run_id": run_id},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM integration.outbox_events "
                        "WHERE workspace_id = :workspace_id "
                        "AND aggregate_id = :run_id "
                        "AND event_type = 'quality.validation_run.queued.v1'"
                    ),
                    {"workspace_id": workspace_id, "run_id": run_id},
                )
                == 1
            )
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legal_hold_generation_serializes_concurrent_events() -> None:
    _require_isolated_postgres()
    engine = _engine()
    workspace_id = uuid4()
    first_hold_id, second_hold_id = uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await _set_workspace(connection, workspace_id)
            await connection.execute(
                text(
                    "INSERT INTO platform.workspaces "
                    "(id, slug, name, status, settings, version) "
                    "VALUES (:id, :slug, :name, 'ACTIVE', '{}'::jsonb, 1)"
                ),
                {
                    "id": workspace_id,
                    "slug": f"quality-generation-{workspace_id.hex}",
                    "name": "Quality generation concurrency test",
                },
            )

        ready = asyncio.Event()
        entered = 0
        entered_lock = asyncio.Lock()

        async def advance(hold_id: UUID) -> None:
            nonlocal entered
            async with engine.begin() as connection:
                await _set_workspace(connection, workspace_id)
                async with entered_lock:
                    entered += 1
                    if entered == 2:
                        ready.set()
                await ready.wait()
                await connection.execute(
                    text(
                        "SELECT retention.advance_legal_hold_generation("
                        "CAST(:workspace_id AS uuid), 'QUALITY_AUDIT'::text, 'INSERT'::text, "
                        "CAST(:hold_id AS uuid), 1, CAST(:payload_hash AS text), "
                        "'RESOURCE'::text, 'QUALITY_RULE_SET'::text, "
                        "CAST(:hold_id AS uuid), 'ACTIVE'::text)"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "hold_id": hold_id,
                        "payload_hash": hold_id.hex * 2,
                    },
                )

        await asyncio.gather(advance(first_hold_id), advance(second_hold_id))

        async with engine.begin() as connection:
            await _set_workspace(connection, workspace_id)
            generation = (
                await connection.execute(
                    text(
                        "SELECT generation, resolution_hash "
                        "FROM retention.legal_hold_generations "
                        "WHERE workspace_id = :workspace_id "
                        "AND data_class = 'QUALITY_AUDIT'"
                    ),
                    {"workspace_id": workspace_id},
                )
            ).one()
            assert generation.generation == 2
            assert len(generation.resolution_hash) == 64
            await connection.execute(
                text(
                    "DELETE FROM retention.legal_hold_generations "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
            await connection.execute(
                text("DELETE FROM platform.workspaces WHERE id = :workspace_id"),
                {"workspace_id": workspace_id},
            )
    finally:
        await engine.dispose()
