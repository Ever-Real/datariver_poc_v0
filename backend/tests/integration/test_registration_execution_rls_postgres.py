from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.secrets import SecretResolver

_DATABASE_URL_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_URL"
_SECRET_REF_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_SECRET_REF"
_CONFIRM_ISOLATED_ENV = "DATARIVER_REGISTRATION_RLS_TEST_CONFIRM_ISOLATED"
_POSTGRES_ENABLED = bool(os.getenv(_DATABASE_URL_ENV)) and os.getenv(_CONFIRM_ISOLATED_ENV) == "1"


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


async def _set_context(
    connection: AsyncConnection,
    *,
    workspace_id: UUID | None,
    subject_id: UUID | None,
) -> None:
    if workspace_id is not None:
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :value, true)"),
            {"value": str(workspace_id)},
        )
    if subject_id is not None:
        await connection.execute(
            text("SELECT set_config('app.subject_id', :value, true)"),
            {"value": str(subject_id)},
        )


async def _app_count(
    engine: AsyncEngine,
    *,
    table: str,
    workspace_id: UUID | None,
    subject_id: UUID | None,
) -> int:
    if table not in {
        "manual_metadata_apply_attempts",
        "manual_metadata_aspect_reports",
    }:
        raise AssertionError("untrusted test table")
    async with engine.connect() as connection:
        async with connection.begin():
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await _set_context(
                connection,
                workspace_id=workspace_id,
                subject_id=subject_id,
            )
            value = await connection.scalar(
                text(f"SELECT count(*) FROM governance.{table}")  # noqa: S608
            )
            return int(value or 0)


async def _app_mutation_is_denied(
    engine: AsyncEngine,
    *,
    statement: str,
    workspace_id: UUID,
    subject_id: UUID,
    parameters: dict[str, object] | None = None,
    lease_token: str | None = None,
) -> None:
    async with engine.connect() as connection:
        with pytest.raises(DBAPIError):
            async with connection.begin():
                await connection.execute(text("SET LOCAL ROLE datariver_app"))
                await _set_context(
                    connection,
                    workspace_id=workspace_id,
                    subject_id=subject_id,
                )
                if lease_token is not None:
                    await connection.execute(
                        text("SELECT set_config('app.manual_metadata_lease_token', :value, true)"),
                        {"value": lease_token},
                    )
                await connection.execute(text(statement), parameters or {})


async def _app_mutation_succeeds(
    engine: AsyncEngine,
    *,
    statement: str,
    workspace_id: UUID,
    subject_id: UUID,
    parameters: dict[str, object] | None = None,
    lease_token: str | None = None,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE datariver_app"))
        await _set_context(
            connection,
            workspace_id=workspace_id,
            subject_id=subject_id,
        )
        if lease_token is not None:
            await connection.execute(
                text("SELECT set_config('app.manual_metadata_lease_token', :value, true)"),
                {"value": lease_token},
            )
        await connection.execute(text(statement), parameters or {})


async def _prepare_fixture(
    engine: AsyncEngine,
) -> tuple[UUID, tuple[UUID, ...]]:
    workspace_id = uuid4()
    admin_id, steward_id, other_steward_id, worker_id, inactive_id, expired_id = (
        uuid4() for _ in range(6)
    )
    subject_ids = (
        admin_id,
        steward_id,
        other_steward_id,
        worker_id,
        inactive_id,
        expired_id,
    )
    administrator_attributes = json.dumps(
        {
            "groups": ["security-administrators"],
            "allowed_actions": ["registration.read"],
            "denied_actions": [],
        }
    )
    steward_attributes = json.dumps(
        {
            "groups": ["data-stewards"],
            "allowed_actions": ["registration.read"],
            "denied_actions": [],
        }
    )
    worker_attributes = json.dumps(
        {
            "groups": ["service-accounts", "registration-workers"],
            "allowed_actions": ["catalog.sync"],
            "denied_actions": [],
        }
    )
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version)
                VALUES
                    (:workspace_id, :slug, 'Registration RLS test',
                     'ACTIVE', '{}'::jsonb, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "slug": f"registration-rls-{workspace_id.hex[:12]}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.subjects
                    (id, issuer, external_subject, display_name, active)
                SELECT id, 'registration-rls-test', id::text, label, true
                FROM unnest(
                    CAST(:ids AS uuid[]),
                    CAST(:labels AS text[])
                ) AS subjects(id, label)
                """
            ),
            {
                "ids": list(subject_ids),
                "labels": [
                    "Admin",
                    "Steward",
                    "Other steward",
                    "Worker",
                    "Inactive",
                    "Expired",
                ],
            },
        )
        membership_rows: Sequence[dict[str, object]] = (
            {
                "subject_id": admin_id,
                "job_function": "SECURITY_ADMINISTRATOR",
                "attributes": administrator_attributes,
                "active": True,
                "expires_at": now + timedelta(days=30),
            },
            {
                "subject_id": steward_id,
                "job_function": "DATA_STEWARD",
                "attributes": steward_attributes,
                "active": True,
                "expires_at": now + timedelta(days=30),
            },
            {
                "subject_id": other_steward_id,
                "job_function": "DATA_STEWARD",
                "attributes": steward_attributes,
                "active": True,
                "expires_at": now + timedelta(days=30),
            },
            {
                "subject_id": worker_id,
                "job_function": "SERVICE_ACCOUNT",
                "attributes": worker_attributes,
                "active": True,
                "expires_at": None,
            },
            {
                "subject_id": inactive_id,
                "job_function": "DATA_STEWARD",
                "attributes": steward_attributes,
                "active": False,
                "expires_at": now + timedelta(days=30),
            },
            {
                "subject_id": expired_id,
                "job_function": "DATA_STEWARD",
                "attributes": steward_attributes,
                "active": True,
                "expires_at": now - timedelta(days=1),
            },
        )
        for row in membership_rows:
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.workspace_memberships
                        (workspace_id, subject_id, job_function, clearance,
                         attributes, active, access_expires_at, version)
                    VALUES
                        (:workspace_id, :subject_id, :job_function, 3,
                         CAST(:attributes AS jsonb), :active, :expires_at, 1)
                    """
                ),
                {"workspace_id": workspace_id, **row},
            )
        for serial_number, requester_id in enumerate(
            (admin_id, steward_id, other_steward_id),
            start=1,
        ):
            asset_id = uuid4()
            submission_id = uuid4()
            attempt_id = uuid4()
            await connection.execute(
                text(
                    """
                    INSERT INTO catalog.assets_projection
                        (id, workspace_id, external_urn, urn_hash, asset_type,
                         name, tags, glossary_terms, column_names,
                         classification, lifecycle, source_version, observed_at,
                         projection_source)
                    VALUES
                        (:asset_id, :workspace_id, :urn, :hash, 'DATASET',
                         :name, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                         1, 'ACTIVE', 'source-v1', :now, 'DATAHUB')
                    """
                ),
                {
                    "asset_id": asset_id,
                    "workspace_id": workspace_id,
                    "urn": f"urn:li:dataset:registration-rls-{serial_number}",
                    "hash": f"{serial_number:064x}",
                    "name": f"registration_rls_{serial_number}",
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO governance.manual_metadata_submissions
                        (id, workspace_id, asset_id, requester_id, external_urn,
                         source_version, provider_source_version, serial_number,
                         payload, bucket, object_key, csv_sha256,
                         csv_size_bytes, row_count, state, attempts,
                         lease_epoch, lease_token_hash, lease_owner_id,
                         lease_started_at, lease_expires_at, version)
                    VALUES
                        (:submission_id, :workspace_id, :asset_id, :requester_id,
                         :urn, 'source-v1', :hash, :serial_number, '{}'::jsonb,
                         'registration-test', :object_key, :hash,
                         1, 1, 'APPLYING', 1, 1, :hash, :worker_id,
                         :now, :lease_expires_at, 1)
                    """
                ),
                {
                    "submission_id": submission_id,
                    "workspace_id": workspace_id,
                    "asset_id": asset_id,
                    "requester_id": requester_id,
                    "urn": f"urn:li:dataset:registration-rls-{serial_number}",
                    "hash": f"{serial_number:064x}",
                    "serial_number": serial_number,
                    "object_key": (f"registration-rls/{workspace_id}/{serial_number}.csv"),
                    "worker_id": worker_id,
                    "now": now,
                    "lease_expires_at": now + timedelta(minutes=5),
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO governance.manual_metadata_apply_attempts
                        (id, workspace_id, submission_id, attempt_no, lease_epoch,
                         lease_token_hash, worker_subject_id, state, started_at)
                    VALUES
                        (:attempt_id, :workspace_id, :submission_id, 1, 1,
                         :hash, :worker_id, 'RUNNING', :now)
                    """
                ),
                {
                    "attempt_id": attempt_id,
                    "workspace_id": workspace_id,
                    "submission_id": submission_id,
                    "hash": f"{serial_number:064x}",
                    "worker_id": worker_id,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO governance.manual_metadata_aspect_reports
                        (id, workspace_id, submission_id, attempt_id,
                         aspect_name, aspect_ordinal, outcome, write_attempted,
                         failure_code, observed_at, created_at)
                    VALUES
                        (:id, :workspace_id, :submission_id, :attempt_id,
                         'datasetProperties', 1, 'FAILED_BEFORE_WRITE', false,
                         'TEST_FAILURE', :now, :now)
                    """
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "submission_id": submission_id,
                    "attempt_id": attempt_id,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE governance.manual_metadata_apply_attempts
                    SET state = 'FAILED',
                        failure_code = 'TEST_FAILURE',
                        report_root_hash = :hash,
                        finished_at = :now
                    WHERE id = :attempt_id
                    """
                ),
                {
                    "hash": f"{serial_number:064x}",
                    "now": now,
                    "attempt_id": attempt_id,
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE governance.manual_metadata_submissions
                    SET state = 'FAILED',
                        last_error_code = 'TEST_FAILURE',
                        lease_token_hash = NULL,
                        lease_owner_id = NULL,
                        lease_started_at = NULL,
                        lease_expires_at = NULL
                    WHERE id = :submission_id
                    """
                ),
                {"submission_id": submission_id},
            )
    return workspace_id, subject_ids


async def _prepare_running_submission(
    engine: AsyncEngine,
    *,
    workspace_id: UUID,
    requester_id: UUID,
    worker_id: UUID,
    serial_number: int,
    expired: bool,
) -> tuple[UUID, UUID, str]:
    asset_id = uuid4()
    submission_id = uuid4()
    attempt_id = uuid4()
    raw_token = f"registration-lease-token-{uuid4()}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(UTC)
    lease_started_at = now - timedelta(minutes=10) if expired else now
    lease_expires_at = now - timedelta(minutes=5) if expired else now + timedelta(minutes=5)
    content_hash = f"{serial_number:064x}"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO catalog.assets_projection
                    (id, workspace_id, external_urn, urn_hash, asset_type,
                     name, tags, glossary_terms, column_names,
                     classification, lifecycle, source_version, observed_at,
                     projection_source)
                VALUES
                    (:asset_id, :workspace_id, :urn, :hash, 'DATASET',
                     :name, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                     1, 'ACTIVE', 'source-v1', :now, 'DATAHUB')
                """
            ),
            {
                "asset_id": asset_id,
                "workspace_id": workspace_id,
                "urn": f"urn:li:dataset:registration-fence-{serial_number}",
                "hash": content_hash,
                "name": f"registration_fence_{serial_number}",
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO governance.manual_metadata_submissions
                    (id, workspace_id, asset_id, requester_id, external_urn,
                     source_version, provider_source_version, serial_number,
                     payload, bucket, object_key, csv_sha256,
                     csv_size_bytes, row_count, state, attempts,
                     lease_epoch, lease_token_hash, lease_owner_id,
                     lease_started_at, lease_expires_at, version)
                VALUES
                    (:submission_id, :workspace_id, :asset_id, :requester_id,
                     :urn, 'source-v1', :hash, :serial_number, '{}'::jsonb,
                     'registration-test', :object_key, :hash,
                     1, 1, 'APPLYING', 1, 1, :token_hash, :worker_id,
                     :lease_started_at, :lease_expires_at, 1)
                """
            ),
            {
                "submission_id": submission_id,
                "workspace_id": workspace_id,
                "asset_id": asset_id,
                "requester_id": requester_id,
                "urn": f"urn:li:dataset:registration-fence-{serial_number}",
                "hash": content_hash,
                "serial_number": serial_number,
                "object_key": (f"registration-fence/{workspace_id}/{serial_number}.csv"),
                "token_hash": token_hash,
                "worker_id": worker_id,
                "lease_started_at": lease_started_at,
                "lease_expires_at": lease_expires_at,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO governance.manual_metadata_apply_attempts
                    (id, workspace_id, submission_id, attempt_no, lease_epoch,
                     lease_token_hash, worker_subject_id, state, started_at)
                VALUES
                    (:attempt_id, :workspace_id, :submission_id, 1, 1,
                     :token_hash, :worker_id, 'RUNNING', :lease_started_at)
                """
            ),
            {
                "attempt_id": attempt_id,
                "workspace_id": workspace_id,
                "submission_id": submission_id,
                "token_hash": token_hash,
                "worker_id": worker_id,
                "lease_started_at": lease_started_at,
            },
        )
    return submission_id, attempt_id, raw_token


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration RLS PostgreSQL URL is required",
)
async def test_registration_execution_evidence_rls_matrix_on_postgres() -> None:
    engine = _engine()
    try:
        workspace_id, subject_ids = await _prepare_fixture(engine)
        admin_id, steward_id, other_steward_id, worker_id, inactive_id, expired_id = subject_ids
        for table in (
            "manual_metadata_apply_attempts",
            "manual_metadata_aspect_reports",
        ):
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=None,
                    subject_id=None,
                )
                == 0
            )
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=uuid4(),
                    subject_id=admin_id,
                )
                == 0
            )
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=workspace_id,
                    subject_id=admin_id,
                )
                == 3
            )
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=workspace_id,
                    subject_id=steward_id,
                )
                == 1
            )
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=workspace_id,
                    subject_id=other_steward_id,
                )
                == 1
            )
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=workspace_id,
                    subject_id=inactive_id,
                )
                == 0
            )
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=workspace_id,
                    subject_id=expired_id,
                )
                == 0
            )
            assert (
                await _app_count(
                    engine,
                    table=table,
                    workspace_id=workspace_id,
                    subject_id=worker_id,
                )
                == 3
            )
        await _app_mutation_is_denied(
            engine,
            statement=(
                "UPDATE governance.manual_metadata_apply_attempts SET attempt_no = attempt_no + 1"
            ),
            workspace_id=workspace_id,
            subject_id=admin_id,
        )
        await _app_mutation_is_denied(
            engine,
            statement="DELETE FROM governance.manual_metadata_aspect_reports",
            workspace_id=workspace_id,
            subject_id=worker_id,
        )
        await _app_mutation_is_denied(
            engine,
            statement="""
                INSERT INTO governance.manual_metadata_apply_attempts
                    (id, workspace_id, submission_id, attempt_no, lease_epoch,
                     lease_token_hash, worker_subject_id, state,
                     failure_code, report_root_hash, started_at, finished_at)
                SELECT
                    :attempt_id, workspace_id, id, attempts, lease_epoch,
                    :hash, :worker_id, 'APPLIED', NULL, :hash,
                    clock_timestamp(), clock_timestamp()
                FROM governance.manual_metadata_submissions
                ORDER BY serial_number
                LIMIT 1
            """,
            parameters={
                "attempt_id": uuid4(),
                "hash": "f" * 64,
                "worker_id": worker_id,
            },
            workspace_id=workspace_id,
            subject_id=worker_id,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration RLS PostgreSQL URL is required",
)
async def test_registration_terminal_mutations_require_current_raw_lease_on_postgres() -> None:
    engine = _engine()
    try:
        workspace_id, subject_ids = await _prepare_fixture(engine)
        admin_id, _, _, worker_id, _, _ = subject_ids
        submission_id, attempt_id, raw_token = await _prepare_running_submission(
            engine,
            workspace_id=workspace_id,
            requester_id=admin_id,
            worker_id=worker_id,
            serial_number=101,
            expired=False,
        )
        terminal_attempt = """
            UPDATE governance.manual_metadata_apply_attempts
            SET state = 'FAILED',
                failure_code = 'TEST_FAILURE',
                report_root_hash = :report_hash,
                finished_at = clock_timestamp()
            WHERE id = :attempt_id
        """
        parameters: dict[str, object] = {
            "attempt_id": attempt_id,
            "report_hash": "a" * 64,
        }
        await _app_mutation_is_denied(
            engine,
            statement=terminal_attempt,
            parameters=parameters,
            workspace_id=workspace_id,
            subject_id=worker_id,
        )
        await _app_mutation_is_denied(
            engine,
            statement=terminal_attempt,
            parameters=parameters,
            workspace_id=workspace_id,
            subject_id=worker_id,
            lease_token="wrong-raw-token",
        )
        await _app_mutation_is_denied(
            engine,
            statement=terminal_attempt,
            parameters=parameters,
            workspace_id=workspace_id,
            subject_id=admin_id,
            lease_token=raw_token,
        )
        await _app_mutation_is_denied(
            engine,
            statement="""
                UPDATE governance.manual_metadata_apply_attempts
                SET lease_epoch = lease_epoch + 1,
                    state = 'FAILED',
                    failure_code = 'TEST_FAILURE',
                    report_root_hash = :report_hash,
                    finished_at = clock_timestamp()
                WHERE id = :attempt_id
            """,
            parameters=parameters,
            workspace_id=workspace_id,
            subject_id=worker_id,
            lease_token=raw_token,
        )
        await _app_mutation_is_denied(
            engine,
            statement="""
                UPDATE governance.manual_metadata_submissions
                SET state = 'FAILED',
                    last_error_code = 'TEST_FAILURE',
                    lease_token_hash = NULL,
                    lease_owner_id = NULL,
                    lease_started_at = NULL,
                    lease_expires_at = NULL
                WHERE id = :submission_id
            """,
            parameters={"submission_id": submission_id},
            workspace_id=workspace_id,
            subject_id=worker_id,
        )

        await _app_mutation_succeeds(
            engine,
            statement=terminal_attempt,
            parameters=parameters,
            workspace_id=workspace_id,
            subject_id=worker_id,
            lease_token=raw_token,
        )
        await _app_mutation_succeeds(
            engine,
            statement="""
                UPDATE governance.manual_metadata_submissions
                SET state = 'FAILED',
                    last_error_code = 'TEST_FAILURE',
                    lease_token_hash = NULL,
                    lease_owner_id = NULL,
                    lease_started_at = NULL,
                    lease_expires_at = NULL
                WHERE id = :submission_id
            """,
            parameters={"submission_id": submission_id},
            workspace_id=workspace_id,
            subject_id=worker_id,
            lease_token=raw_token,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration RLS PostgreSQL URL is required",
)
async def test_expired_lease_denies_business_terminal_but_allows_fixed_recovery_on_postgres() -> (
    None
):
    engine = _engine()
    try:
        workspace_id, subject_ids = await _prepare_fixture(engine)
        admin_id, _, _, worker_id, _, _ = subject_ids
        submission_id, attempt_id, raw_token = await _prepare_running_submission(
            engine,
            workspace_id=workspace_id,
            requester_id=admin_id,
            worker_id=worker_id,
            serial_number=102,
            expired=True,
        )
        await _app_mutation_is_denied(
            engine,
            statement="""
                UPDATE governance.manual_metadata_apply_attempts
                SET state = 'FAILED',
                    failure_code = 'TEST_FAILURE',
                    report_root_hash = :report_hash,
                    finished_at = clock_timestamp()
                WHERE id = :attempt_id
            """,
            parameters={"attempt_id": attempt_id, "report_hash": "b" * 64},
            workspace_id=workspace_id,
            subject_id=worker_id,
            lease_token=raw_token,
        )
        await _app_mutation_is_denied(
            engine,
            statement="""
                UPDATE governance.manual_metadata_submissions
                SET state = 'FAILED',
                    last_error_code = 'TEST_FAILURE',
                    lease_token_hash = NULL,
                    lease_owner_id = NULL,
                    lease_started_at = NULL,
                    lease_expires_at = NULL
                WHERE id = :submission_id
            """,
            parameters={"submission_id": submission_id},
            workspace_id=workspace_id,
            subject_id=worker_id,
            lease_token=raw_token,
        )

        await _app_mutation_succeeds(
            engine,
            statement="""
                UPDATE governance.manual_metadata_apply_attempts
                SET state = 'FAILED',
                    failure_code = 'WORKER_LEASE_EXHAUSTED',
                    report_root_hash = :report_hash,
                    finished_at = clock_timestamp()
                WHERE id = :attempt_id
            """,
            parameters={"attempt_id": attempt_id, "report_hash": "c" * 64},
            workspace_id=workspace_id,
            subject_id=worker_id,
        )
        await _app_mutation_succeeds(
            engine,
            statement="""
                UPDATE governance.manual_metadata_submissions
                SET state = 'FAILED',
                    last_error_code = 'WORKER_LEASE_EXHAUSTED',
                    lease_token_hash = NULL,
                    lease_owner_id = NULL,
                    lease_started_at = NULL,
                    lease_expires_at = NULL
                WHERE id = :submission_id
            """,
            parameters={"submission_id": submission_id},
            workspace_id=workspace_id,
            subject_id=worker_id,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration RLS PostgreSQL URL is required",
)
async def test_fixed_manual_recovery_atomically_completes_the_worker_receipt_on_postgres() -> None:
    engine = _engine()
    try:
        workspace_id, subject_ids = await _prepare_fixture(engine)
        admin_id, _, _, worker_id, _, _ = subject_ids
        serial_number = 103
        submission_id, attempt_id, raw_token = await _prepare_running_submission(
            engine,
            workspace_id=workspace_id,
            requester_id=admin_id,
            worker_id=worker_id,
            serial_number=serial_number,
            expired=True,
        )
        operation = "registration.manual-metadata.apply-run.v1"
        key_hash = "d" * 64
        request_hash = "e" * 64
        result = json.dumps(
            {
                "processed": True,
                "submission_id": str(submission_id),
                "serial_number": serial_number,
                "state": "FAILED",
            }
        )
        async with engine.begin() as connection:
            lease_expires_at = await connection.scalar(
                text(
                    """
                    SELECT lease_expires_at
                    FROM governance.manual_metadata_submissions
                    WHERE id = :submission_id
                    """
                ),
                {"submission_id": submission_id},
            )
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await _set_context(
                connection,
                workspace_id=workspace_id,
                subject_id=worker_id,
            )
            await connection.execute(
                text("SELECT set_config('app.registration_worker_claim_token', :value, true)"),
                {"value": raw_token},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.registration_worker_call_receipts (
                        workspace_id, operation, key_hash, request_hash,
                        worker_subject_id, state, work_kind, work_id,
                        claim_attempt, claim_token_hash, lease_expires_at,
                        processed, result, created_at, updated_at
                    ) VALUES (
                        :workspace_id, :operation, :key_hash, :request_hash,
                        :worker_id, 'RUNNING', 'MANUAL', :submission_id,
                        1, encode(sha256(convert_to(:raw_token, 'UTF8')), 'hex'),
                        :lease_expires_at, NULL, NULL,
                        clock_timestamp(), clock_timestamp()
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": operation,
                    "key_hash": key_hash,
                    "request_hash": request_hash,
                    "worker_id": worker_id,
                    "submission_id": submission_id,
                    "raw_token": raw_token,
                    "lease_expires_at": lease_expires_at,
                },
            )

        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await _set_context(
                connection,
                workspace_id=workspace_id,
                subject_id=worker_id,
            )
            await connection.execute(
                text(
                    """
                    UPDATE governance.manual_metadata_apply_attempts
                    SET state = 'FAILED',
                        failure_code = 'WORKER_LEASE_EXHAUSTED',
                        report_root_hash = :report_hash,
                        finished_at = clock_timestamp()
                    WHERE id = :attempt_id
                    """
                ),
                {"attempt_id": attempt_id, "report_hash": "f" * 64},
            )
            await connection.execute(
                text(
                    """
                    UPDATE governance.manual_metadata_submissions
                    SET state = 'FAILED',
                        last_error_code = 'WORKER_LEASE_EXHAUSTED',
                        lease_token_hash = NULL,
                        lease_owner_id = NULL,
                        lease_started_at = NULL,
                        lease_expires_at = NULL
                    WHERE id = :submission_id
                    """
                ),
                {"submission_id": submission_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.registration_worker_call_receipts
                    SET state = 'COMPLETED',
                        processed = true,
                        result = CAST(:result AS jsonb),
                        claim_token_hash = NULL,
                        lease_expires_at = NULL,
                        updated_at = clock_timestamp()
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": operation,
                    "key_hash": key_hash,
                    "result": result,
                },
            )
            observed = await connection.scalar(
                text(
                    """
                    SELECT result
                    FROM integration.registration_worker_call_receipts
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": operation,
                    "key_hash": key_hash,
                },
            )
            assert observed == json.loads(result)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration RLS PostgreSQL URL is required",
)
async def test_fixed_bulk_recovery_atomically_completes_the_worker_receipt_on_postgres() -> None:
    engine = _engine()
    try:
        workspace_id, subject_ids = await _prepare_fixture(engine)
        admin_id, _, _, worker_id, _, _ = subject_ids
        upload_id = uuid4()
        preparation_id = uuid4()
        lease_token = uuid4()
        now = datetime.now(UTC)
        lease_expires_at = now - timedelta(minutes=5)
        source_hash = "1" * 64
        configuration_hash = "2" * 64
        operation = "registration.bulk-preparation.execute-run.v1"
        key_hash = "3" * 64
        request_hash = "4" * 64
        attempt = 3
        result = json.dumps(
            {
                "processed": True,
                "preparation_id": str(preparation_id),
                "state": "FAILED",
                "item_count": None,
            }
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.object_manifests (
                        id, workspace_id, bucket, object_key, display_name,
                        multipart_upload_id, size_bytes, mime, sha256,
                        actual_size_bytes, actual_mime, actual_sha256,
                        processing_lease_until, processing_attempts,
                        validation_attempts, last_error_code, validation_summary,
                        completion_parts, state, content_profile, classification,
                        owner_id, retention_until, expires_at,
                        created_at, updated_at, version
                    ) VALUES (
                        :upload_id, :workspace_id, 'registration-test',
                        :object_key, 'bulk.csv', NULL, 1, 'text/csv', :source_hash,
                        1, 'text/csv', :source_hash, NULL, 0, 1, NULL,
                        '{}'::jsonb, '[]'::jsonb, 'ACCEPTED',
                        'DATASET_DESCRIPTION_CSV_V1', 1, :owner_id, NULL, NULL,
                        :now, :now, 1
                    )
                    """
                ),
                {
                    "upload_id": upload_id,
                    "workspace_id": workspace_id,
                    "object_key": f"bulk-recovery/{workspace_id}/{upload_id}.csv",
                    "source_hash": source_hash,
                    "owner_id": admin_id,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.upload_preparation_jobs (
                        id, workspace_id, upload_id, requested_by,
                        content_profile, source_manifest_version,
                        source_sha256, configuration_hash, state,
                        next_attempt_at, lease_token, lease_until, attempts,
                        rows_processed, total_rows, last_error_code,
                        created_at, updated_at, version
                    ) VALUES (
                        :preparation_id, :workspace_id, :upload_id, :owner_id,
                        'DATASET_DESCRIPTION_CSV_V1', 1,
                        :source_hash, :configuration_hash, 'PREPARING',
                        NULL, :lease_token, :lease_expires_at, :attempt,
                        0, NULL, NULL, :now, :now, 1
                    )
                    """
                ),
                {
                    "preparation_id": preparation_id,
                    "workspace_id": workspace_id,
                    "upload_id": upload_id,
                    "owner_id": admin_id,
                    "source_hash": source_hash,
                    "configuration_hash": configuration_hash,
                    "lease_token": lease_token,
                    "lease_expires_at": lease_expires_at,
                    "attempt": attempt,
                    "now": now,
                },
            )

        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await _set_context(
                connection,
                workspace_id=workspace_id,
                subject_id=worker_id,
            )
            await connection.execute(
                text("SELECT set_config('app.registration_worker_claim_token', :value, true)"),
                {"value": str(lease_token)},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.registration_worker_call_receipts (
                        workspace_id, operation, key_hash, request_hash,
                        worker_subject_id, state, work_kind, work_id,
                        claim_attempt, claim_token_hash, lease_expires_at,
                        processed, result, created_at, updated_at
                    ) VALUES (
                        :workspace_id, :operation, :key_hash, :request_hash,
                        :worker_id, 'RUNNING', 'BULK', :preparation_id,
                        :attempt,
                        encode(sha256(convert_to(:raw_token, 'UTF8')), 'hex'),
                        :lease_expires_at, NULL, NULL,
                        clock_timestamp(), clock_timestamp()
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": operation,
                    "key_hash": key_hash,
                    "request_hash": request_hash,
                    "worker_id": worker_id,
                    "preparation_id": preparation_id,
                    "attempt": attempt,
                    "raw_token": str(lease_token),
                    "lease_expires_at": lease_expires_at,
                },
            )

        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await _set_context(
                connection,
                workspace_id=workspace_id,
                subject_id=worker_id,
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.upload_preparation_jobs
                    SET state = 'FAILED',
                        lease_token = NULL,
                        lease_until = NULL,
                        last_error_code = 'WORKER_LEASE_EXHAUSTED',
                        version = version + 1,
                        updated_at = clock_timestamp()
                    WHERE id = :preparation_id
                    """
                ),
                {"preparation_id": preparation_id},
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.registration_worker_call_receipts
                    SET state = 'COMPLETED',
                        processed = true,
                        result = CAST(:result AS jsonb),
                        claim_token_hash = NULL,
                        lease_expires_at = NULL,
                        updated_at = clock_timestamp()
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": operation,
                    "key_hash": key_hash,
                    "result": result,
                },
            )
            observed = await connection.scalar(
                text(
                    """
                    SELECT result
                    FROM integration.registration_worker_call_receipts
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": operation,
                    "key_hash": key_hash,
                },
            )
            assert observed == json.loads(result)
    finally:
        await engine.dispose()
