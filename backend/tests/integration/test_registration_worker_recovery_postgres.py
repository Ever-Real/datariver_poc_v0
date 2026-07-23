from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from datariver.application.services.bulk_registration import BulkPreparationClaim
from datariver.application.typed_upload_profiles import typed_profile_definition
from datariver.domain.authz import Classification
from datariver.domain.governance import ChangeItem, ChangeRequest, change_target_binding_hash
from datariver.domain.manual_metadata import ManualMetadataApplyClaim, ManualMetadataSubmission
from datariver.domain.registration import UploadContentProfile
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)
from datariver.infrastructure.db.bulk_registration import SqlBulkPreparationExecutionStore
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.infrastructure.db.governance_apply import SqlGovernanceApplyStore
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.integration import (
    JobAttemptModel,
    JobModel,
    ObjectManifestModel,
    UploadPreparationJobModel,
)
from datariver.infrastructure.db.models.platform import (
    DataSystemModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
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


def _governance_role_engine() -> AsyncEngine:
    return create_async_engine(
        os.environ[_DATABASE_URL_ENV],
        connect_args={
            "password": SecretResolver().resolve(
                os.getenv(_SECRET_REF_ENV, "file:/run/secrets/postgres_password")
            ),
            "server_settings": {"role": "datariver_governance"},
        },
    )


def _app_role_engine() -> AsyncEngine:
    return create_async_engine(
        os.environ[_DATABASE_URL_ENV],
        connect_args={
            "password": SecretResolver().resolve(
                os.getenv(_SECRET_REF_ENV, "file:/run/secrets/postgres_password")
            ),
            "server_settings": {"role": "datariver_app"},
        },
    )


async def _governance_mutation_is_denied(
    engine: AsyncEngine,
    *,
    statement: str,
    parameters: dict[str, object],
    lease_token: str | None = None,
    workspace_id: UUID | None = None,
    subject_id: UUID | None = None,
) -> None:
    with pytest.raises(DBAPIError):
        async with engine.begin() as connection:
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
            if lease_token is not None:
                await connection.execute(
                    text(
                        "SELECT set_config('app.governance_apply_lease_token', :lease_token, true)"
                    ),
                    {"lease_token": lease_token},
                )
            await connection.execute(text(statement), parameters)


async def _existing_identity(engine: AsyncEngine) -> tuple[UUID, UUID, UUID]:
    async with engine.connect() as connection:
        rows = list(
            await connection.execute(
                text(
                    """
                    SELECT membership.workspace_id,
                           membership.subject_id,
                           membership.job_function
                    FROM iam.workspace_memberships AS membership
                    ORDER BY membership.workspace_id::text DESC,
                             membership.subject_id::text
                    """
                )
            )
        )
    by_workspace: dict[UUID, tuple[UUID | None, UUID | None]] = {}
    for row in rows:
        workspace_id = UUID(str(row.workspace_id))
        requester_id, worker_id = by_workspace.get(workspace_id, (None, None))
        if row.job_function == "SERVICE_ACCOUNT":
            worker_id = UUID(str(row.subject_id))
        else:
            requester_id = requester_id or UUID(str(row.subject_id))
        by_workspace[workspace_id] = requester_id, worker_id
    for workspace_id, (requester_id, worker_id) in by_workspace.items():
        if requester_id is not None and worker_id is not None:
            return workspace_id, requester_id, worker_id
    raise AssertionError("registration recovery fixture requires human and service memberships")


async def _create_isolated_identity(engine: AsyncEngine) -> tuple[UUID, UUID, UUID]:
    """Reuse real subjects but isolate every recovery run in a fresh workspace."""
    _, requester_id, worker_id = await _existing_identity(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    suffix = uuid4().hex
    workspace = WorkspaceModel(
        slug=f"registration-recovery-{suffix}",
        name=f"Registration recovery {suffix}",
        status="ACTIVE",
        settings={},
    )
    async with session_factory() as session, session.begin():
        session.add(workspace)
        await session.flush()
        session.add_all(
            (
                WorkspaceMembershipModel(
                    workspace_id=workspace.id,
                    subject_id=requester_id,
                    department_id=None,
                    job_function="DATA_STEWARD",
                    clearance=int(Classification.RESTRICTED),
                    attributes={
                        "groups": ["data-stewards"],
                        "allowed_actions": ["registration.read"],
                    },
                    active=True,
                    access_expires_at=datetime.now(UTC) + timedelta(days=1),
                ),
                WorkspaceMembershipModel(
                    workspace_id=workspace.id,
                    subject_id=worker_id,
                    department_id=None,
                    job_function="SERVICE_ACCOUNT",
                    clearance=int(Classification.RESTRICTED),
                    attributes={
                        "groups": ["service-accounts", "registration-workers"],
                        "allowed_actions": ["catalog.sync"],
                    },
                    active=True,
                    access_expires_at=None,
                ),
            )
        )
    return workspace.id, requester_id, worker_id


async def _add_asset(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: UUID,
    suffix: str,
    system_id: UUID | None = None,
) -> AssetProjectionModel:
    now = datetime.now(UTC)
    asset = AssetProjectionModel(
        id=uuid4(),
        workspace_id=workspace_id,
        external_urn=f"urn:li:dataset:registration-recovery-{suffix}",
        urn_hash=uuid4().hex.ljust(64, "0"),
        asset_type="DATASET",
        name=f"registration_recovery_{suffix}",
        description=None,
        platform="postgres",
        database_name="recovery",
        schema_name="public",
        domain_id=None,
        system_id=system_id,
        owner_department_id=None,
        tags=[],
        glossary_terms=[],
        column_names=["id"],
        classification=int(Classification.INTERNAL),
        lifecycle="ACTIVE",
        source_version="source-v1",
        observed_at=now,
        projection_source="DATAHUB",
        deleted_at=None,
    )
    async with session_factory() as session, session.begin():
        session.add(asset)
    return asset


async def _synchronize_manual_serial_sequence(engine: AsyncEngine) -> None:
    """Repair only the disposable fixture after prior direct-row integration tests."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                SELECT setval(
                    'governance.manual_metadata_submission_serial_seq',
                    GREATEST(
                        COALESCE(
                            (
                                SELECT max(serial_number)
                                FROM governance.manual_metadata_submissions
                            ),
                            0
                        ),
                        1
                    ),
                    EXISTS (
                        SELECT 1
                        FROM governance.manual_metadata_submissions
                    )
                )
                """
            )
        )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration PostgreSQL URL is required",
)
async def test_manual_and_bulk_expired_final_attempts_terminalize_and_scan_onward() -> None:
    engine = _engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        workspace_id, requester_id, worker_id = await _create_isolated_identity(engine)
        await _synchronize_manual_serial_sequence(engine)
        first_asset = await _add_asset(
            session_factory,
            workspace_id=workspace_id,
            suffix=uuid4().hex,
        )
        second_asset = await _add_asset(
            session_factory,
            workspace_id=workspace_id,
            suffix=uuid4().hex,
        )
        manual_ids: list[UUID] = []
        for asset in (first_asset, second_asset):
            async with SqlGovernanceUnitOfWork(session_factory) as uow:
                await uow.set_security_context(
                    workspace_id=workspace_id,
                    subject_id=requester_id,
                )
                serial = await uow.manual_metadata_submissions.allocate_serial_number()
                submission = ManualMetadataSubmission.queue(
                    workspace_id=workspace_id,
                    asset_id=asset.id,
                    external_urn=asset.external_urn,
                    requester_id=requester_id,
                    source_version="source-v1",
                    provider_source_version="a" * 64,
                    serial_number=serial,
                    description="recovery",
                    domain=None,
                    tags=(),
                    terms=(),
                    columns=(),
                    bucket="registration-test",
                    object_key=f"registration-recovery/{workspace_id}/{serial}.csv",
                    csv_sha256="b" * 64,
                    csv_size_bytes=1,
                    row_count=1,
                )
                await uow.manual_metadata_submissions.add(submission)
                await uow.commit()
                manual_ids.append(submission.submission_id)

        async with SqlGovernanceUnitOfWork(session_factory) as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=worker_id)
            first_claim = await uow.manual_metadata_submissions.claim_next(
                workspace_id=workspace_id,
                worker_subject_id=worker_id,
                now=datetime.now(UTC),
                lease_seconds=30,
                maximum_attempts=1,
            )
            await uow.commit()
        assert isinstance(first_claim, ManualMetadataApplyClaim)
        assert first_claim.submission.submission_id == manual_ids[0]
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE governance.manual_metadata_submissions
                    SET lease_started_at = clock_timestamp() - interval '31 seconds',
                        lease_expires_at = clock_timestamp() - interval '1 second'
                    WHERE id = :submission_id
                    """
                ),
                {"submission_id": manual_ids[0]},
            )
        async with SqlGovernanceUnitOfWork(session_factory) as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=worker_id)
            next_claim = await uow.manual_metadata_submissions.claim_next(
                workspace_id=workspace_id,
                worker_subject_id=worker_id,
                now=datetime.now(UTC),
                lease_seconds=30,
                maximum_attempts=1,
            )
            await uow.commit()
        assert isinstance(next_claim, ManualMetadataApplyClaim)
        assert next_claim.submission.submission_id == manual_ids[1]
        async with engine.connect() as connection:
            state = await connection.scalar(
                text("SELECT state FROM governance.manual_metadata_submissions WHERE id = :id"),
                {"id": manual_ids[0]},
            )
            attempt_state = await connection.scalar(
                text(
                    """
                    SELECT state
                    FROM governance.manual_metadata_apply_attempts
                    WHERE submission_id = :id
                    """
                ),
                {"id": manual_ids[0]},
            )
        assert state == "FAILED"
        assert attempt_state == "FAILED"

        profile = UploadContentProfile.DATASET_DESCRIPTION_CSV_V1
        definition = typed_profile_definition(profile)
        preparation_ids: list[UUID] = []
        now = datetime.now(UTC)
        async with session_factory() as session, session.begin():
            for ordinal in range(2):
                upload_id = uuid4()
                preparation_id = uuid4()
                digest = f"{ordinal + 1:064x}"
                session.add(
                    ObjectManifestModel(
                        id=upload_id,
                        workspace_id=workspace_id,
                        bucket="registration-test",
                        object_key=f"bulk-recovery/{upload_id}.csv",
                        display_name="bulk recovery.csv",
                        multipart_upload_id=None,
                        size_bytes=1,
                        mime="text/csv",
                        sha256=digest,
                        actual_size_bytes=1,
                        actual_mime="text/csv",
                        actual_sha256=digest,
                        processing_lease_until=None,
                        processing_attempts=0,
                        validation_attempts=1,
                        last_error_code=None,
                        validation_summary={"validator_version": "test-v1"},
                        completion_parts=[],
                        state="ACCEPTED",
                        content_profile=profile.value,
                        classification=int(Classification.INTERNAL),
                        owner_id=requester_id,
                        retention_until=None,
                        expires_at=None,
                    )
                )
                session.add(
                    UploadPreparationJobModel(
                        id=preparation_id,
                        workspace_id=workspace_id,
                        upload_id=upload_id,
                        requested_by=requester_id,
                        content_profile=profile.value,
                        source_manifest_version=1,
                        source_sha256=digest,
                        configuration_hash=definition.configuration_hash,
                        state="PREPARING" if ordinal == 0 else "QUEUED",
                        next_attempt_at=None if ordinal == 0 else now - timedelta(seconds=1),
                        lease_token=uuid4() if ordinal == 0 else None,
                        lease_until=now - timedelta(seconds=1) if ordinal == 0 else None,
                        attempts=1 if ordinal == 0 else 0,
                        rows_processed=0,
                        total_rows=None,
                        last_error_code=None,
                        version=1,
                    )
                )
                preparation_ids.append(preparation_id)
        bulk_store = SqlBulkPreparationExecutionStore(session_factory)
        bulk_claim = await bulk_store.claim_next(
            workspace_id=workspace_id,
            worker_subject_id=worker_id,
            lease_seconds=30,
            maximum_attempts=1,
        )
        assert isinstance(bulk_claim, BulkPreparationClaim)
        assert bulk_claim.preparation_id == preparation_ids[1]
        async with session_factory() as session:
            first_bulk_state = await session.scalar(
                select(UploadPreparationJobModel.state).where(
                    UploadPreparationJobModel.id == preparation_ids[0]
                )
            )
            first_bulk_error = await session.scalar(
                select(UploadPreparationJobModel.last_error_code).where(
                    UploadPreparationJobModel.id == preparation_ids[0]
                )
            )
        assert first_bulk_state == "FAILED"
        assert first_bulk_error == "WORKER_LEASE_EXHAUSTED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration PostgreSQL URL is required",
)
async def test_old_manual_and_bulk_run_calls_replay_superseded_after_a_newer_claim() -> None:
    engine = _engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    app_engine = _app_role_engine()
    app_session_factory = async_sessionmaker(
        app_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        workspace_id, requester_id, worker_id = await _create_isolated_identity(engine)
        await _synchronize_manual_serial_sequence(engine)
        asset = await _add_asset(
            session_factory,
            workspace_id=workspace_id,
            suffix=uuid4().hex,
        )
        async with SqlGovernanceUnitOfWork(app_session_factory) as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=requester_id,
            )
            serial = await uow.manual_metadata_submissions.allocate_serial_number()
            submission = ManualMetadataSubmission.queue(
                workspace_id=workspace_id,
                asset_id=asset.id,
                external_urn=asset.external_urn,
                requester_id=requester_id,
                source_version="source-v1",
                provider_source_version="a" * 64,
                serial_number=serial,
                description="superseded replay",
                domain=None,
                tags=(),
                terms=(),
                columns=(),
                bucket="registration-test",
                object_key=f"registration-superseded/{workspace_id}/{serial}.csv",
                csv_sha256="b" * 64,
                csv_size_bytes=1,
                row_count=1,
            )
            await uow.manual_metadata_submissions.add(submission)
            await uow.commit()

        manual_a = RegistrationWorkerCallIdentity(
            operation="registration.manual-metadata.apply-run.v1",
            key_hash="1" * 64,
            request_hash="2" * 64,
            worker_subject_id=worker_id,
        )
        manual_b = RegistrationWorkerCallIdentity(
            operation=manual_a.operation,
            key_hash="3" * 64,
            request_hash="4" * 64,
            worker_subject_id=worker_id,
        )
        async with SqlGovernanceUnitOfWork(app_session_factory) as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=worker_id)
            first_manual = await uow.manual_metadata_submissions.claim_next(
                workspace_id=workspace_id,
                worker_subject_id=worker_id,
                now=datetime.now(UTC),
                lease_seconds=30,
                maximum_attempts=3,
                run_call=manual_a,
            )
            await uow.commit()
        assert isinstance(first_manual, ManualMetadataApplyClaim)

        expired_at = datetime.now(UTC) - timedelta(seconds=1)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE governance.manual_metadata_submissions
                    SET lease_started_at = :lease_started_at,
                        lease_expires_at = :lease_expires_at
                    WHERE workspace_id = :workspace_id
                      AND id = :submission_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "submission_id": submission.submission_id,
                    "lease_started_at": expired_at - timedelta(seconds=30),
                    "lease_expires_at": expired_at,
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
                text("SELECT set_config('app.registration_worker_claim_token', :value, true)"),
                {"value": first_manual.lease_token},
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.registration_worker_call_receipts
                    SET lease_expires_at = :lease_expires_at,
                        updated_at = clock_timestamp()
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": manual_a.operation,
                    "key_hash": manual_a.key_hash,
                    "lease_expires_at": expired_at,
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
                    text("SELECT set_config('app.manual_metadata_lease_token', :value, true)"),
                    {"value": first_manual.lease_token},
                )
                await connection.execute(
                    text(
                        """
                        UPDATE governance.manual_metadata_apply_attempts
                        SET state = 'SUPERSEDED',
                            failure_code = 'LEASE_EXPIRED',
                            report_root_hash = :report_root_hash,
                            finished_at = clock_timestamp()
                        WHERE workspace_id = :workspace_id
                          AND id = :attempt_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "attempt_id": first_manual.attempt_id,
                        "report_root_hash": "c" * 64,
                    },
                )

        async with SqlGovernanceUnitOfWork(app_session_factory) as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=worker_id)
            second_manual = await uow.manual_metadata_submissions.claim_next(
                workspace_id=workspace_id,
                worker_subject_id=worker_id,
                now=datetime.now(UTC),
                lease_seconds=30,
                maximum_attempts=3,
                run_call=manual_b,
            )
            await uow.commit()
        assert isinstance(second_manual, ManualMetadataApplyClaim)
        assert second_manual.attempt_no == first_manual.attempt_no + 1
        async with engine.connect() as connection:
            old_manual_state = await connection.scalar(
                text(
                    """
                    SELECT state
                    FROM integration.registration_worker_call_receipts
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": manual_a.operation,
                    "key_hash": manual_a.key_hash,
                },
            )
        assert old_manual_state == "COMPLETED"

        async with SqlGovernanceUnitOfWork(app_session_factory) as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=worker_id)
            manual_replay = await uow.manual_metadata_submissions.claim_next(
                workspace_id=workspace_id,
                worker_subject_id=worker_id,
                now=datetime.now(UTC),
                lease_seconds=30,
                maximum_attempts=3,
                run_call=manual_a,
            )
            await uow.commit()
        assert isinstance(manual_replay, RegistrationWorkerCallReplay)
        assert manual_replay.result == {
            "processed": True,
            "submission_id": str(submission.submission_id),
            "serial_number": serial,
            "state": "SUPERSEDED",
        }

        profile = UploadContentProfile.DATASET_DESCRIPTION_CSV_V1
        definition = typed_profile_definition(profile)
        upload_id = uuid4()
        preparation_id = uuid4()
        digest = "d" * 64
        async with session_factory() as session, session.begin():
            session.add(
                ObjectManifestModel(
                    id=upload_id,
                    workspace_id=workspace_id,
                    bucket="registration-test",
                    object_key=f"bulk-superseded/{upload_id}.csv",
                    display_name="bulk superseded.csv",
                    multipart_upload_id=None,
                    size_bytes=1,
                    mime="text/csv",
                    sha256=digest,
                    actual_size_bytes=1,
                    actual_mime="text/csv",
                    actual_sha256=digest,
                    processing_lease_until=None,
                    processing_attempts=0,
                    validation_attempts=1,
                    last_error_code=None,
                    validation_summary={"validator_version": "test-v1"},
                    completion_parts=[],
                    state="ACCEPTED",
                    content_profile=profile.value,
                    classification=int(Classification.INTERNAL),
                    owner_id=requester_id,
                    retention_until=None,
                    expires_at=None,
                )
            )
            session.add(
                UploadPreparationJobModel(
                    id=preparation_id,
                    workspace_id=workspace_id,
                    upload_id=upload_id,
                    requested_by=requester_id,
                    content_profile=profile.value,
                    source_manifest_version=1,
                    source_sha256=digest,
                    configuration_hash=definition.configuration_hash,
                    state="QUEUED",
                    next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
                    lease_token=None,
                    lease_until=None,
                    attempts=0,
                    rows_processed=0,
                    total_rows=None,
                    last_error_code=None,
                    version=1,
                )
            )
        bulk_a = RegistrationWorkerCallIdentity(
            operation="registration.bulk-preparation.execute-run.v1",
            key_hash="5" * 64,
            request_hash="6" * 64,
            worker_subject_id=worker_id,
        )
        bulk_b = RegistrationWorkerCallIdentity(
            operation=bulk_a.operation,
            key_hash="7" * 64,
            request_hash="8" * 64,
            worker_subject_id=worker_id,
        )
        bulk_store = SqlBulkPreparationExecutionStore(app_session_factory)
        first_bulk = await bulk_store.claim_next(
            workspace_id=workspace_id,
            worker_subject_id=worker_id,
            lease_seconds=30,
            maximum_attempts=3,
            run_call=bulk_a,
        )
        assert isinstance(first_bulk, BulkPreparationClaim)
        bulk_expired_at = datetime.now(UTC) - timedelta(seconds=1)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE integration.upload_preparation_jobs
                    SET lease_until = :lease_expires_at
                    WHERE workspace_id = :workspace_id
                      AND id = :preparation_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "preparation_id": preparation_id,
                    "lease_expires_at": bulk_expired_at,
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
                text("SELECT set_config('app.registration_worker_claim_token', :value, true)"),
                {"value": str(first_bulk.lease_token)},
            )
            await connection.execute(
                text(
                    """
                    UPDATE integration.registration_worker_call_receipts
                    SET lease_expires_at = :lease_expires_at,
                        updated_at = clock_timestamp()
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": bulk_a.operation,
                    "key_hash": bulk_a.key_hash,
                    "lease_expires_at": bulk_expired_at,
                },
            )
        second_bulk = await bulk_store.claim_next(
            workspace_id=workspace_id,
            worker_subject_id=worker_id,
            lease_seconds=30,
            maximum_attempts=3,
            run_call=bulk_b,
        )
        assert isinstance(second_bulk, BulkPreparationClaim)
        assert second_bulk.attempt == first_bulk.attempt + 1
        async with engine.connect() as connection:
            old_bulk_state = await connection.scalar(
                text(
                    """
                    SELECT state
                    FROM integration.registration_worker_call_receipts
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                      AND key_hash = :key_hash
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": bulk_a.operation,
                    "key_hash": bulk_a.key_hash,
                },
            )
        assert old_bulk_state == "COMPLETED"
        bulk_replay = await bulk_store.claim_next(
            workspace_id=workspace_id,
            worker_subject_id=worker_id,
            lease_seconds=30,
            maximum_attempts=3,
            run_call=bulk_a,
        )
        assert isinstance(bulk_replay, RegistrationWorkerCallReplay)
        assert bulk_replay.result == {
            "processed": True,
            "preparation_id": str(preparation_id),
            "state": "SUPERSEDED",
            "item_count": None,
        }
    finally:
        await app_engine.dispose()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration PostgreSQL URL is required",
)
async def test_governance_apply_expired_final_attempt_terminalizes() -> None:
    engine = _engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        workspace_id, requester_id, worker_id = await _create_isolated_identity(engine)
        suffix = uuid4().hex
        target_system = DataSystemModel(
            workspace_id=workspace_id,
            code=f"recovery_{suffix}",
            name=f"Recovery {suffix}",
            description="Disposable registration recovery fixture.",
            active=True,
        )
        async with session_factory() as session, session.begin():
            session.add(target_system)
        target_asset = await _add_asset(
            session_factory,
            workspace_id=workspace_id,
            suffix=suffix,
            system_id=target_system.id,
        )
        target_asset_id = target_asset.id
        target_system_id = target_system.id
        target_ref = target_asset.external_urn
        change_request = ChangeRequest.create(
            workspace_id=workspace_id,
            number=f"CR-RECOVERY-{uuid4().hex}",
            request_type="DATASET_DESCRIPTION_CHANGE",
            title="Expired final attempt recovery",
            description="integration recovery evidence",
            requester_id=requester_id,
            classification=Classification.INTERNAL,
            items=[
                ChangeItem(
                    item_id=uuid4(),
                    target_type="DATAHUB_ASPECT",
                    target_ref=target_ref,
                    operation="UPSERT",
                    after_document={"description": "recovery"},
                    aspect_name="datasetProperties",
                    before_hash="a" * 64,
                    target_asset_id=target_asset_id,
                    target_asset_type="DATASET",
                    target_system_id=target_system_id,
                    target_classification=Classification.INTERNAL,
                    target_lifecycle="ACTIVE",
                    target_source_version="source-v1",
                    target_observed_at=datetime.now(UTC),
                    target_binding_hash=change_target_binding_hash(
                        target_ref=target_ref,
                        asset_id=target_asset_id,
                        asset_type="DATASET",
                        system_id=target_system_id,
                        domain_id=None,
                        owner_department_id=None,
                        classification=Classification.INTERNAL,
                        lifecycle="ACTIVE",
                    ),
                    routing_system_id=target_system_id,
                )
            ],
        )
        async with SqlGovernanceUnitOfWork(session_factory) as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=requester_id,
            )
            await uow.change_requests.add(change_request)
            await uow.commit()
        job_id = uuid4()
        attempt_id = uuid4()
        now = datetime.now(UTC)
        async with session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    UPDATE governance.change_requests
                    SET state = 'APPLYING'
                    WHERE id = :change_request_id
                    """
                ),
                {"change_request_id": change_request.change_request_id},
            )
            job = JobModel(
                id=job_id,
                workspace_id=workspace_id,
                job_type=SqlGovernanceApplyStore.job_type,
                causation_id=change_request.change_request_id,
                state="RUNNING",
                requested_by=requester_id,
                progress={},
                result_ref=None,
                lease_until=now - timedelta(seconds=1),
                attempts=1,
                attempt_cycle=1,
                cycle_attempts=1,
                lease_token_hash="a" * 64,
                lease_owner_id=worker_id,
                last_error_code=None,
                version=1,
            )
            session.add(job)
            await session.flush()
            session.add(
                JobAttemptModel(
                    id=attempt_id,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    attempt_no=1,
                    worker_id="integration-recovery",
                    state="RUNNING",
                    error_class=None,
                    external_response_hash=None,
                    started_at=now - timedelta(minutes=1),
                    finished_at=None,
                )
            )
        claim = await SqlGovernanceApplyStore(session_factory).claim_next(
            worker_id="integration-recovery",
            system_actor_id=worker_id,
            lease_seconds=30,
            maximum_attempts=1,
        )
        assert claim is None
        async with session_factory() as session:
            cr_state = await session.scalar(
                select(ChangeRequestModel.state).where(
                    ChangeRequestModel.id == change_request.change_request_id
                )
            )
            job_state = await session.scalar(select(JobModel.state).where(JobModel.id == job_id))
            attempt_state = await session.scalar(
                select(JobAttemptModel.state).where(JobAttemptModel.id == attempt_id)
            )
        assert cr_state == "APPLY_FAILED"
        assert job_state == "FAILED"
        assert attempt_state == "FAILED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _POSTGRES_ENABLED,
    reason="confirmed isolated registration PostgreSQL URL is required",
)
async def test_governance_apply_role_requires_current_lease_and_requeue_is_monotonic() -> None:
    owner_engine = _engine()
    app_engine = _app_role_engine()
    governance_engine = _governance_role_engine()
    owner_factory = async_sessionmaker(
        owner_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    governance_factory = async_sessionmaker(
        governance_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        workspace_id, requester_id, worker_id = await _create_isolated_identity(owner_engine)
        suffix = uuid4().hex
        target_system = DataSystemModel(
            workspace_id=workspace_id,
            code=f"fence_{suffix}",
            name=f"Fence {suffix}",
            description="Disposable governance apply fence fixture.",
            active=True,
        )
        async with owner_factory() as session, session.begin():
            session.add(target_system)
        target_asset = await _add_asset(
            owner_factory,
            workspace_id=workspace_id,
            suffix=suffix,
            system_id=target_system.id,
        )
        expected_hash = "b" * 64
        target_ref = target_asset.external_urn
        request = ChangeRequest.create(
            workspace_id=workspace_id,
            number=f"CR-FENCE-{suffix}",
            request_type="DATASET_DESCRIPTION_CHANGE",
            title="Governance apply fencing",
            description="integration fence evidence",
            requester_id=requester_id,
            classification=Classification.INTERNAL,
            items=[
                ChangeItem(
                    item_id=uuid4(),
                    target_type="DATAHUB_ASPECT",
                    target_ref=target_ref,
                    operation="UPSERT",
                    after_document={"description": "fenced"},
                    aspect_name="datasetProperties",
                    before_hash="a" * 64,
                    after_hash=expected_hash,
                    target_asset_id=target_asset.id,
                    target_asset_type="DATASET",
                    target_system_id=target_system.id,
                    target_classification=Classification.INTERNAL,
                    target_lifecycle="ACTIVE",
                    target_source_version="source-v1",
                    target_observed_at=datetime.now(UTC),
                    target_binding_hash=change_target_binding_hash(
                        target_ref=target_ref,
                        asset_id=target_asset.id,
                        asset_type="DATASET",
                        system_id=target_system.id,
                        domain_id=None,
                        owner_department_id=None,
                        classification=Classification.INTERNAL,
                        lifecycle="ACTIVE",
                    ),
                    routing_system_id=target_system.id,
                )
            ],
        )
        async with SqlGovernanceUnitOfWork(owner_factory) as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=requester_id,
            )
            await uow.change_requests.add(request)
            await uow.commit()
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE governance.change_requests
                    SET state = 'APPLY_QUEUED',
                        created_at = TIMESTAMPTZ '2000-01-01 00:00:00+00'
                    WHERE id = :change_request_id
                    """
                ),
                {"change_request_id": request.change_request_id},
            )

        store = SqlGovernanceApplyStore(governance_factory)
        await _governance_mutation_is_denied(
            app_engine,
            statement="""
                UPDATE governance.change_requests
                SET state = 'APPLIED',
                    version = version + 1,
                    updated_at = clock_timestamp()
                WHERE id = :change_request_id
            """,
            parameters={"change_request_id": request.change_request_id},
            workspace_id=workspace_id,
            subject_id=requester_id,
        )
        await _governance_mutation_is_denied(
            app_engine,
            statement="""
                INSERT INTO integration.jobs (
                    id, workspace_id, job_type, causation_id, state,
                    requested_by, progress, attempts, attempt_cycle,
                    cycle_attempts, lease_token_hash, lease_owner_id,
                    lease_until, version
                ) VALUES (
                    :job_id, :workspace_id, 'DATAHUB_CHANGE_APPLY',
                    :change_request_id, 'RUNNING', :requester_id,
                    '{}'::jsonb, 1, 1, 1, :lease_token_hash,
                    :worker_id, clock_timestamp() + interval '1 minute', 1
                )
            """,
            parameters={
                "job_id": uuid4(),
                "workspace_id": workspace_id,
                "change_request_id": request.change_request_id,
                "requester_id": requester_id,
                "lease_token_hash": "d" * 64,
                "worker_id": worker_id,
            },
            workspace_id=workspace_id,
            subject_id=requester_id,
        )
        await _governance_mutation_is_denied(
            governance_engine,
            statement="""
                INSERT INTO integration.jobs (
                    id, workspace_id, job_type, causation_id, state,
                    requested_by, progress, attempts, attempt_cycle,
                    cycle_attempts, version
                ) VALUES (
                    :job_id, :workspace_id, 'CATALOG_EXPORT',
                    :change_request_id, 'PENDING', :requester_id,
                    '{}'::jsonb, 0, 1, 0, 1
                )
            """,
            parameters={
                "job_id": uuid4(),
                "workspace_id": workspace_id,
                "change_request_id": request.change_request_id,
                "requester_id": requester_id,
            },
        )
        with pytest.raises(DBAPIError):
            await store.claim_next(
                worker_id="governance-human-test",
                system_actor_id=requester_id,
                lease_seconds=30,
                maximum_attempts=1,
            )
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET active = false
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :worker_id
                    """
                ),
                {"workspace_id": workspace_id, "worker_id": worker_id},
            )
        with pytest.raises(DBAPIError):
            await store.claim_next(
                worker_id="governance-inactive-test",
                system_actor_id=worker_id,
                lease_seconds=30,
                maximum_attempts=1,
            )
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET active = true,
                        access_expires_at = clock_timestamp() - interval '1 second'
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :worker_id
                    """
                ),
                {"workspace_id": workspace_id, "worker_id": worker_id},
            )
        with pytest.raises(DBAPIError):
            await store.claim_next(
                worker_id="governance-expired-test",
                system_actor_id=worker_id,
                lease_seconds=30,
                maximum_attempts=1,
            )
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET access_expires_at = NULL
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :worker_id
                    """
                ),
                {"workspace_id": workspace_id, "worker_id": worker_id},
            )
        first_claim = await store.claim_next(
            worker_id="governance-fence-test",
            system_actor_id=worker_id,
            lease_seconds=30,
            maximum_attempts=1,
        )
        assert first_claim is not None
        assert first_claim.attempt_no == 1

        await _governance_mutation_is_denied(
            governance_engine,
            statement="""
                UPDATE governance.change_requests
                SET version = version + 1,
                    updated_at = clock_timestamp()
                WHERE id = :change_request_id
            """,
            parameters={"change_request_id": request.change_request_id},
        )
        await _governance_mutation_is_denied(
            governance_engine,
            statement="""
                UPDATE governance.change_requests
                SET state = 'APPLIED', version = version + 1
                WHERE id = :change_request_id
            """,
            parameters={"change_request_id": request.change_request_id},
        )
        await _governance_mutation_is_denied(
            governance_engine,
            statement="""
                UPDATE integration.job_attempts
                SET state = 'COMPLETED', finished_at = clock_timestamp()
                WHERE id = :attempt_id
            """,
            parameters={"attempt_id": first_claim.attempt_id},
            lease_token="wrong-token",
        )
        await _governance_mutation_is_denied(
            governance_engine,
            statement="""
                UPDATE integration.jobs
                SET progress = '{"forged": true}'::jsonb
                WHERE id = :job_id
            """,
            parameters={"job_id": first_claim.job_id},
        )

        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET active = false
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :worker_id
                    """
                ),
                {"workspace_id": workspace_id, "worker_id": worker_id},
            )
        with pytest.raises(DBAPIError):
            await store.mark_failed(
                claim=first_claim,
                system_actor_id=worker_id,
                error_code="REVOKED_WORKER",
                retryable=False,
                maximum_attempts=1,
            )
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET active = true
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :worker_id
                    """
                ),
                {"workspace_id": workspace_id, "worker_id": worker_id},
            )
        await store.mark_failed(
            claim=first_claim,
            system_actor_id=worker_id,
            error_code="PROVIDER_REJECTED",
            retryable=False,
            maximum_attempts=1,
        )
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE governance.change_requests
                    SET state = 'APPLY_QUEUED', version = version + 1
                    WHERE id = :change_request_id
                    """
                ),
                {"change_request_id": request.change_request_id},
            )

        second_claim = await store.claim_next(
            worker_id="governance-fence-test",
            system_actor_id=worker_id,
            lease_seconds=30,
            maximum_attempts=1,
        )
        assert second_claim is not None
        assert second_claim.job_id == first_claim.job_id
        assert second_claim.attempt_no == 2
        assert second_claim.attempt_id != first_claim.attempt_id

        await store.mark_applied(
            claim=second_claim,
            system_actor_id=worker_id,
            expected_hash=expected_hash,
            observed_hash=expected_hash,
            item_results=[{"outcome": "APPLIED_VERIFIED"}],
        )
        async with owner_factory() as session:
            cr_state = await session.scalar(
                select(ChangeRequestModel.state).where(
                    ChangeRequestModel.id == request.change_request_id
                )
            )
            job = await session.get(JobModel, first_claim.job_id)
            attempt_numbers = tuple(
                await session.scalars(
                    select(JobAttemptModel.attempt_no)
                    .where(JobAttemptModel.job_id == first_claim.job_id)
                    .order_by(JobAttemptModel.attempt_no)
                )
            )
        assert cr_state == "APPLIED"
        assert job is not None
        assert job.state == "COMPLETED"
        assert job.attempts == 2
        assert job.attempt_cycle == 2
        assert job.cycle_attempts == 1
        assert attempt_numbers == (1, 2)

        await _governance_mutation_is_denied(
            app_engine,
            statement="""
                UPDATE governance.change_requests
                SET state = 'APPLY_QUEUED',
                    version = version + 1,
                    updated_at = clock_timestamp()
                WHERE id = :change_request_id
            """,
            parameters={"change_request_id": request.change_request_id},
            workspace_id=workspace_id,
            subject_id=requester_id,
        )
        next_token = "completed-job-reclaim-must-fail"
        await _governance_mutation_is_denied(
            governance_engine,
            statement="""
                UPDATE integration.jobs
                SET state = 'RUNNING',
                    progress = '{}'::jsonb,
                    result_ref = NULL,
                    lease_until = clock_timestamp() + interval '1 minute',
                    attempts = attempts + 1,
                    cycle_attempts = cycle_attempts + 1,
                    lease_token_hash =
                        encode(sha256(convert_to(:lease_token, 'UTF8')), 'hex'),
                    lease_owner_id = :worker_id,
                    last_error_code = NULL,
                    version = version + 1,
                    updated_at = clock_timestamp()
                WHERE id = :job_id
            """,
            parameters={
                "job_id": first_claim.job_id,
                "lease_token": next_token,
                "worker_id": worker_id,
            },
            lease_token=next_token,
            subject_id=worker_id,
        )

        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE governance.change_requests
                    SET state = 'APPLY_QUEUED',
                        version = version + 1,
                        updated_at = clock_timestamp()
                    WHERE id = :change_request_id
                    """
                ),
                {"change_request_id": request.change_request_id},
            )
        await store.claim_next(
            worker_id="governance-fence-test",
            system_actor_id=worker_id,
            lease_seconds=30,
            maximum_attempts=1,
        )
        async with owner_factory() as session:
            completed_job = await session.get(JobModel, first_claim.job_id)
            completed_attempts = tuple(
                await session.scalars(
                    select(JobAttemptModel.attempt_no)
                    .where(JobAttemptModel.job_id == first_claim.job_id)
                    .order_by(JobAttemptModel.attempt_no)
                )
            )
        assert completed_job is not None
        assert completed_job.state == "COMPLETED"
        assert completed_job.attempts == 2
        assert completed_attempts == (1, 2)
    finally:
        await app_engine.dispose()
        await governance_engine.dispose()
        await owner_engine.dispose()
