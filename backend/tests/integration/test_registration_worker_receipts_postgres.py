from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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
                os.getenv(_SECRET_REF_ENV, "file:/run/secrets/postgres_password")
            )
        },
    )


async def _prepare_worker_fixture(engine: AsyncEngine) -> tuple[UUID, UUID, UUID]:
    workspace_id = uuid4()
    worker_id = uuid4()
    other_worker_id = uuid4()
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces (
                    id, slug, name, status, settings,
                    created_at, updated_at, version
                ) VALUES (
                    :workspace_id, :slug, 'receipt test', 'ACTIVE',
                    '{}'::jsonb, :now, :now, 1
                )
                """
            ),
            {
                "workspace_id": workspace_id,
                "slug": f"receipt-{workspace_id}",
                "now": now,
            },
        )
        for subject_id in (worker_id, other_worker_id):
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.subjects (
                        id, issuer, external_subject, display_name,
                        active, created_at, updated_at
                    ) VALUES (
                        :subject_id, 'receipt-test', :external_subject,
                        'receipt worker', true, :now, :now
                    )
                    """
                ),
                {
                    "subject_id": subject_id,
                    "external_subject": str(subject_id),
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.workspace_memberships (
                        workspace_id, subject_id, department_id, job_function,
                        clearance, attributes, active, access_expires_at,
                        created_at, updated_at, version
                    ) VALUES (
                        :workspace_id, :subject_id, NULL, 'SERVICE_ACCOUNT',
                        3, '{}'::jsonb, true, NULL, :now, :now, 1
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "subject_id": subject_id,
                    "now": now,
                },
            )
    return workspace_id, worker_id, other_worker_id


async def _insert_bulk_claim(
    engine: AsyncEngine,
    *,
    workspace_id: UUID,
    worker_id: UUID,
    preparation_id: UUID,
    lease_token: UUID,
    lease_expires_at: datetime,
    attempt: int,
) -> None:
    upload_id = uuid4()
    now = datetime.now(UTC)
    source_hash = uuid4().hex * 2
    configuration_hash = uuid4().hex * 2
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
                    :upload_id, :workspace_id, 'receipt-test',
                    :object_key, 'bulk.csv', NULL, 1, 'text/csv', :source_hash,
                    1, 'text/csv', :source_hash, NULL, 0, 1, NULL,
                    '{}'::jsonb, '[]'::jsonb, 'ACCEPTED',
                    'DATASET_DESCRIPTION_CSV_V1', 1, :worker_id, NULL, NULL,
                    :now, :now, 1
                )
                """
            ),
            {
                "upload_id": upload_id,
                "workspace_id": workspace_id,
                "object_key": f"receipt-test/{workspace_id}/{upload_id}.csv",
                "source_hash": source_hash,
                "worker_id": worker_id,
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
                    :preparation_id, :workspace_id, :upload_id, :worker_id,
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
                "worker_id": worker_id,
                "source_hash": source_hash,
                "configuration_hash": configuration_hash,
                "lease_token": lease_token,
                "lease_expires_at": lease_expires_at,
                "attempt": attempt,
                "now": now,
            },
        )


async def _insert_running_bulk_receipt(
    engine: AsyncEngine,
    *,
    workspace_id: UUID,
    worker_id: UUID,
    preparation_id: UUID,
    lease_token: UUID,
    lease_expires_at: datetime,
    attempt: int,
    key_hash: str,
    request_hash: str,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE datariver_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :value, true)"),
            {"value": str(workspace_id)},
        )
        await connection.execute(
            text("SELECT set_config('app.subject_id', :value, true)"),
            {"value": str(worker_id)},
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
                    :workspace_id,
                    'registration.bulk-preparation.execute-run.v1',
                    :key_hash, :request_hash, :worker_id,
                    'RUNNING', 'BULK', :preparation_id, :attempt,
                    encode(sha256(convert_to(:raw_token, 'UTF8')), 'hex'),
                    :lease_expires_at, NULL, NULL,
                    clock_timestamp(), clock_timestamp()
                )
                """
            ),
            {
                "workspace_id": workspace_id,
                "key_hash": key_hash,
                "request_hash": request_hash,
                "worker_id": worker_id,
                "preparation_id": preparation_id,
                "attempt": attempt,
                "raw_token": str(lease_token),
                "lease_expires_at": lease_expires_at,
            },
        )


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL receipt gate not enabled")
@pytest.mark.asyncio
async def test_no_work_receipt_is_subject_scoped_immutable_and_forged_running_is_denied() -> None:
    engine = _engine()
    workspace_id, worker_id, other_worker_id = await _prepare_worker_fixture(engine)
    now = datetime.now(UTC)
    operation = "registration.manual-metadata.apply-run.v1"
    key_hash = "1" * 64
    request_hash = "2" * 64
    result = {
        "processed": False,
        "submission_id": None,
        "serial_number": None,
        "state": None,
    }
    try:
        async with engine.begin() as connection:
            policies = (
                await connection.execute(
                    text(
                        """
                        SELECT policyname, permissive, cmd
                        FROM pg_policies
                        WHERE schemaname = 'integration'
                          AND tablename = 'registration_worker_call_receipts'
                        ORDER BY policyname
                        """
                    )
                )
            ).all()
            assert [tuple(row) for row in policies] == [
                ("registration_worker_call_scope", "PERMISSIVE", "ALL")
            ]

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
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
                            :worker_id, 'COMPLETED', NULL, NULL,
                            NULL, NULL, NULL, false, CAST(:result AS jsonb), :now, :now
                        )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "operation": operation,
                        "key_hash": "0" * 64,
                        "request_hash": request_hash,
                        "worker_id": worker_id,
                        "result": json.dumps(result),
                        "now": now,
                    },
                )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE datariver_app"))
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(worker_id)},
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
                            :worker_id, 'COMPLETED', NULL, NULL,
                            NULL, NULL, NULL, false, '{"processed": false}'::jsonb,
                            :now, :now
                        )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "operation": operation,
                        "key_hash": "f" * 64,
                        "request_hash": request_hash,
                        "worker_id": worker_id,
                        "now": now,
                    },
                )

        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(workspace_id)},
            )
            await connection.execute(
                text("SELECT set_config('app.subject_id', :value, true)"),
                {"value": str(worker_id)},
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
                        :worker_id, 'COMPLETED', NULL, NULL,
                        NULL, NULL, NULL, false, CAST(:result AS jsonb), :now, :now
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": operation,
                    "key_hash": key_hash,
                    "request_hash": request_hash,
                    "worker_id": worker_id,
                    "result": json.dumps(result),
                    "now": now,
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
            assert observed == result
            bulk_result = {
                "processed": False,
                "preparation_id": None,
                "state": None,
                "item_count": None,
            }
            await connection.execute(
                text(
                    """
                    INSERT INTO integration.registration_worker_call_receipts (
                        workspace_id, operation, key_hash, request_hash,
                        worker_subject_id, state, work_kind, work_id,
                        claim_attempt, claim_token_hash, lease_expires_at,
                        processed, result, created_at, updated_at
                    ) VALUES (
                        :workspace_id,
                        'registration.bulk-preparation.execute-run.v1',
                        :key_hash, :request_hash, :worker_id,
                        'COMPLETED', NULL, NULL, NULL, NULL, NULL,
                        false, CAST(:result AS jsonb), :now, :now
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "key_hash": "9" * 64,
                    "request_hash": "a" * 64,
                    "worker_id": worker_id,
                    "result": json.dumps(bulk_result),
                    "now": now,
                },
            )
            observed_bulk = await connection.scalar(
                text(
                    """
                    SELECT result
                    FROM integration.registration_worker_call_receipts
                    WHERE workspace_id = :workspace_id
                      AND operation =
                          'registration.bulk-preparation.execute-run.v1'
                      AND key_hash = :key_hash
                    """
                ),
                {"workspace_id": workspace_id, "key_hash": "9" * 64},
            )
            assert observed_bulk == bulk_result
            recovery_results = (
                (
                    operation,
                    "7" * 64,
                    "8" * 64,
                    {
                        "processed": False,
                        "submission_id": None,
                        "serial_number": None,
                        "state": "RECOVERY_LIMIT_REACHED",
                    },
                ),
                (
                    "registration.bulk-preparation.execute-run.v1",
                    "b" * 64,
                    "c" * 64,
                    {
                        "processed": False,
                        "preparation_id": None,
                        "state": "RECOVERY_LIMIT_REACHED",
                        "item_count": None,
                    },
                ),
            )
            for (
                recovery_operation,
                recovery_key,
                recovery_request,
                recovery_result,
            ) in recovery_results:
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
                            :worker_id, 'COMPLETED', NULL, NULL, NULL, NULL, NULL,
                            false, CAST(:result AS jsonb), :now, :now
                        )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "operation": recovery_operation,
                        "key_hash": recovery_key,
                        "request_hash": recovery_request,
                        "worker_id": worker_id,
                        "result": json.dumps(recovery_result),
                        "now": now,
                    },
                )

        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(workspace_id)},
            )
            await connection.execute(
                text("SELECT set_config('app.subject_id', :value, true)"),
                {"value": str(other_worker_id)},
            )
            hidden = await connection.scalar(
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
            assert hidden is None

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE datariver_app"))
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(worker_id)},
                )
                await connection.execute(
                    text(
                        """
                        UPDATE integration.registration_worker_call_receipts
                            SET result = CAST(:tampered_result AS jsonb),
                            processed = true,
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
                        "tampered_result": json.dumps({"processed": True}),
                    },
                )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE datariver_app"))
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(worker_id)},
                )
                await connection.execute(
                    text(
                        "SELECT set_config("
                        "'app.registration_worker_claim_token', 'forged-token', true)"
                    )
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
                            :worker_id, 'RUNNING', 'MANUAL', :work_id,
                            1, encode(sha256(convert_to('forged-token', 'UTF8')), 'hex'),
                            clock_timestamp() + interval '1 minute',
                            NULL, NULL, clock_timestamp(), clock_timestamp()
                        )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "operation": operation,
                        "key_hash": "3" * 64,
                        "request_hash": "4" * 64,
                        "worker_id": worker_id,
                        "work_id": uuid4(),
                    },
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL receipt gate not enabled")
@pytest.mark.asyncio
async def test_bulk_terminal_receipt_requires_exact_canonical_result_and_supersession() -> None:
    engine = _engine()
    workspace_id, worker_id, _ = await _prepare_worker_fixture(engine)
    preparation_id = uuid4()
    lease_token = uuid4()
    lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    attempt = 2
    key_hash = "5" * 64
    request_hash = "6" * 64
    operation = "registration.bulk-preparation.execute-run.v1"
    try:
        await _insert_bulk_claim(
            engine,
            workspace_id=workspace_id,
            worker_id=worker_id,
            preparation_id=preparation_id,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
            attempt=attempt,
        )
        await _insert_running_bulk_receipt(
            engine,
            workspace_id=workspace_id,
            worker_id=worker_id,
            preparation_id=preparation_id,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
            attempt=attempt,
            key_hash=key_hash,
            request_hash=request_hash,
        )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE datariver_app"))
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(worker_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.registration_worker_claim_token', :value, true)"),
                    {"value": str(lease_token)},
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
                        "result": json.dumps(
                            {
                                "processed": True,
                                "preparation_id": str(preparation_id),
                                "state": "SUPERSEDED",
                                "item_count": None,
                            }
                        ),
                    },
                )

        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(workspace_id)},
            )
            await connection.execute(
                text("SELECT set_config('app.subject_id', :value, true)"),
                {"value": str(worker_id)},
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.upload_preparation_jobs
                    SET state = 'FAILED',
                        lease_token = NULL,
                        lease_until = NULL,
                        last_error_code = 'PERMANENT_PARSE_FAILURE',
                        version = version + 1,
                        updated_at = clock_timestamp()
                    WHERE workspace_id = :workspace_id
                      AND id = :preparation_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "preparation_id": preparation_id,
                },
            )

        for invalid_result in (
            {
                "processed": True,
                "preparation_id": str(uuid4()),
                "state": "FAILED",
                "item_count": None,
            },
            {
                "processed": True,
                "preparation_id": str(preparation_id),
                "state": "FAILED",
                "item_count": 1,
            },
            {
                "processed": True,
                "preparation_id": str(preparation_id),
                "state": "SUPERSEDED",
                "item_count": None,
            },
        ):
            with pytest.raises(DBAPIError):
                async with engine.begin() as connection:
                    await connection.execute(text("SET LOCAL ROLE datariver_app"))
                    await connection.execute(
                        text("SELECT set_config('app.workspace_id', :value, true)"),
                        {"value": str(workspace_id)},
                    )
                    await connection.execute(
                        text("SELECT set_config('app.subject_id', :value, true)"),
                        {"value": str(worker_id)},
                    )
                    await connection.execute(
                        text(
                            "SELECT set_config('app.registration_worker_claim_token', :value, true)"
                        ),
                        {"value": str(lease_token)},
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
                            "result": json.dumps(invalid_result),
                        },
                    )

        terminal_result = {
            "processed": True,
            "preparation_id": str(preparation_id),
            "state": "FAILED",
            "item_count": None,
        }
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(workspace_id)},
            )
            await connection.execute(
                text("SELECT set_config('app.subject_id', :value, true)"),
                {"value": str(worker_id)},
            )
            await connection.execute(
                text("SELECT set_config('app.registration_worker_claim_token', :value, true)"),
                {"value": str(lease_token)},
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
                    "result": json.dumps(terminal_result),
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
            assert observed == terminal_result

        superseded_preparation_id = uuid4()
        superseded_token = uuid4()
        superseded_expiry = datetime.now(UTC) - timedelta(seconds=1)
        superseded_key_hash = "7" * 64
        await _insert_bulk_claim(
            engine,
            workspace_id=workspace_id,
            worker_id=worker_id,
            preparation_id=superseded_preparation_id,
            lease_token=superseded_token,
            lease_expires_at=superseded_expiry,
            attempt=attempt,
        )
        await _insert_running_bulk_receipt(
            engine,
            workspace_id=workspace_id,
            worker_id=worker_id,
            preparation_id=superseded_preparation_id,
            lease_token=superseded_token,
            lease_expires_at=superseded_expiry,
            attempt=attempt,
            key_hash=superseded_key_hash,
            request_hash="8" * 64,
        )
        superseded_result = {
            "processed": True,
            "preparation_id": str(superseded_preparation_id),
            "state": "SUPERSEDED",
            "item_count": None,
        }
        replacement_token = uuid4()
        replacement_expiry = datetime.now(UTC) + timedelta(minutes=5)
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(workspace_id)},
            )
            await connection.execute(
                text("SELECT set_config('app.subject_id', :value, true)"),
                {"value": str(worker_id)},
            )
            await connection.execute(
                text(
                    """
                        UPDATE integration.upload_preparation_jobs
                        SET state = 'PREPARING',
                            next_attempt_at = NULL,
                            lease_token = :replacement_token,
                            lease_until = :replacement_expiry,
                            attempts = attempts + 1,
                            last_error_code = NULL,
                            version = version + 1,
                            updated_at = clock_timestamp()
                    WHERE workspace_id = :workspace_id
                      AND id = :preparation_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "preparation_id": superseded_preparation_id,
                    "replacement_token": replacement_token,
                    "replacement_expiry": replacement_expiry,
                },
            )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL ROLE datariver_app"))
                await connection.execute(
                    text("SELECT set_config('app.workspace_id', :value, true)"),
                    {"value": str(workspace_id)},
                )
                await connection.execute(
                    text("SELECT set_config('app.subject_id', :value, true)"),
                    {"value": str(worker_id)},
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
                        "key_hash": superseded_key_hash,
                        "result": json.dumps(superseded_result),
                    },
                )

        await _insert_running_bulk_receipt(
            engine,
            workspace_id=workspace_id,
            worker_id=worker_id,
            preparation_id=superseded_preparation_id,
            lease_token=replacement_token,
            lease_expires_at=replacement_expiry,
            attempt=attempt + 1,
            key_hash="9" * 64,
            request_hash="a" * 64,
        )
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE datariver_app"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(workspace_id)},
            )
            await connection.execute(
                text("SELECT set_config('app.subject_id', :value, true)"),
                {"value": str(worker_id)},
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
                    "key_hash": superseded_key_hash,
                    "result": json.dumps(superseded_result),
                },
            )
    finally:
        await engine.dispose()
