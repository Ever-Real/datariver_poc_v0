from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from datariver.application.classification_access import static_classification_access_floor
from datariver.application.dto import CatalogSyncResult, DataHubScanAsset
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.common import ConflictError
from datariver.infrastructure.db.catalog import (
    SqlCatalogIndexReader,
    SqlCatalogProjectionWriter,
    _scope_id,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.secrets import SecretResolver

_DATABASE_URL_ENV = "DATARIVER_CATALOG_SYNC_TEST_DATABASE_URL"
_ADMIN_DATABASE_URL_ENV = "DATARIVER_CATALOG_SYNC_TEST_ADMIN_DATABASE_URL"
_SECRET_REF_ENV = "DATARIVER_CATALOG_SYNC_TEST_DATABASE_SECRET_REF"
_ADMIN_SECRET_REF_ENV = "DATARIVER_CATALOG_SYNC_TEST_ADMIN_DATABASE_SECRET_REF"
_CONFIRM_ENV = "DATARIVER_CATALOG_SYNC_TEST_CONFIRM_ISOLATED"


def _engine(*, url_env: str, secret_ref_env: str) -> AsyncEngine:
    secret_reference = os.environ[secret_ref_env]
    password = SecretResolver().resolve(secret_reference)
    return create_async_engine(
        os.environ[url_env],
        connect_args={"password": password},
        pool_size=2,
        max_overflow=0,
    )


def _asset(name: str) -> DataHubScanAsset:
    return DataHubScanAsset(
        external_urn=f"urn:li:dataset:{name}",
        asset_type="DATASET",
        name=name,
        description=f"{name} description",
        platform="postgres",
        domain_ref=None,
        system_ref=None,
        owner_ref=None,
        classification=Classification.PUBLIC,
        source_version=f"{name}-v1",
    )


async def _security_context(session: AsyncSession, workspace_id: UUID) -> None:
    await set_security_context(
        session,
        workspace_id=workspace_id,
        subject_id=uuid4(),
    )


async def _watermark(admin: AsyncEngine, workspace_id: UUID) -> int | None:
    async with admin.connect() as connection:
        value = await connection.scalar(
            text(
                "SELECT projection_version FROM catalog.projection_watermarks "
                "WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": workspace_id},
        )
        return int(value) if value is not None else None


async def _prepare_workspaces(admin: AsyncEngine, workspace_ids: tuple[UUID, ...]) -> None:
    async with admin.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        for ordinal, workspace_id in enumerate(workspace_ids):
            await connection.execute(
                text(
                    "INSERT INTO platform.workspaces "
                    "(id, slug, name, status, settings, version) "
                    "VALUES (:id, :slug, :name, 'ACTIVE', '{}'::jsonb, 1)"
                ),
                {
                    "id": workspace_id,
                    "slug": f"catalog-sync-test-{workspace_id.hex}",
                    "name": f"Catalog sync test {ordinal}",
                },
            )


async def _cleanup_workspaces(admin: AsyncEngine, workspace_ids: tuple[UUID, ...]) -> None:
    async with admin.begin() as connection:
        parameters = {"workspace_ids": list(workspace_ids)}
        for statement in (
            text(
                "DELETE FROM integration.idempotency_keys WHERE workspace_id = ANY(:workspace_ids)"
            ),
            text("DELETE FROM catalog.assets_projection WHERE workspace_id = ANY(:workspace_ids)"),
            text("DELETE FROM catalog.sync_runs WHERE workspace_id = ANY(:workspace_ids)"),
            text(
                "DELETE FROM catalog.projection_watermarks WHERE workspace_id = ANY(:workspace_ids)"
            ),
            text("DELETE FROM platform.workspaces WHERE id = ANY(:workspace_ids)"),
        ):
            await connection.execute(statement, parameters)


@pytest.mark.asyncio
async def test_datahub_system_ref_never_materializes_canonical_system_authority() -> None:
    required = (
        _DATABASE_URL_ENV,
        _ADMIN_DATABASE_URL_ENV,
        _SECRET_REF_ENV,
        _ADMIN_SECRET_REF_ENV,
    )
    if os.getenv(_CONFIRM_ENV) != "1" or any(not os.getenv(name) for name in required):
        pytest.skip("isolated catalog sync PostgreSQL environment is not configured")

    database = _engine(url_env=_DATABASE_URL_ENV, secret_ref_env=_SECRET_REF_ENV)
    admin = _engine(url_env=_ADMIN_DATABASE_URL_ENV, secret_ref_env=_ADMIN_SECRET_REF_ENV)
    sessions = async_sessionmaker(database, expire_on_commit=False)
    workspace_id = uuid4()
    external_urn = "urn:li:dataset:provider-system-ref"
    provider_domain_ref = "urn:li:domain:provider-domain"
    expected_domain_id = _scope_id("domain", provider_domain_ref)
    legacy_orphan_system_id = uuid4()
    observed_at = datetime.now(UTC)
    item = DataHubScanAsset(
        external_urn=external_urn,
        asset_type="TABLE",
        name="provider-system-ref",
        description="Provider scoped projection",
        platform="oracle",
        database_name="ORCL",
        schema_name="semiconductor_seed",
        domain_ref=provider_domain_ref,
        system_ref="urn:li:dataPlatform:oracle",
        owner_ref=None,
        classification=Classification.CONFIDENTIAL,
        source_version="provider-v2",
        column_names=("unit_cost",),
    )

    await _prepare_workspaces(admin, (workspace_id,))
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO catalog.assets_projection "
                    "(id, workspace_id, external_urn, urn_hash, asset_type, name, "
                    "description, platform, database_name, schema_name, domain_ref, "
                    "tags, glossary_terms, column_names, domain_id, system_id, "
                    "classification, lifecycle, source_version, observed_at, "
                    "projection_source) VALUES "
                    "(:id, :workspace_id, :external_urn, :urn_hash, 'TABLE', :name, "
                    ":description, :platform, :database_name, :schema_name, :domain_ref, "
                    "'[]'::jsonb, '[]'::jsonb, '[\"unit_cost\"]'::jsonb, :domain_id, "
                    ":system_id, 2, 'ACTIVE', 'provider-v1', :observed_at, 'DATAHUB')"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "external_urn": external_urn,
                    "urn_hash": hashlib.sha256(external_urn.encode()).hexdigest(),
                    "name": item.name,
                    "description": item.description,
                    "platform": item.platform,
                    "database_name": item.database_name,
                    "schema_name": item.schema_name,
                    "domain_ref": provider_domain_ref,
                    "domain_id": expected_domain_id,
                    "system_id": legacy_orphan_system_id,
                    "observed_at": observed_at,
                },
            )

        async with sessions() as session:
            await _security_context(session, workspace_id)
            await SqlCatalogProjectionWriter(session).upsert_scan(
                workspace_id=workspace_id,
                sync_id=uuid4(),
                offset=0,
                cursor=None,
                next_offset=None,
                next_cursor=None,
                total=1,
                snapshot_consistent=False,
                snapshot_evidence_reference=None,
                snapshot_contract_hash=None,
                snapshot_provider_version=None,
                items=(item,),
                observed_at=observed_at,
                idempotency_key="catalog-sync-provider-system-ref",
                request_hash="f" * 64,
                operation="catalog.datahub.sync:0:100",
            )

        async with admin.connect() as connection:
            projection = (
                await connection.execute(
                    text(
                        "SELECT external_urn, platform, database_name, schema_name, "
                        "domain_id, system_id, classification, lifecycle, source_version, "
                        "column_names, projection_source "
                        "FROM catalog.assets_projection "
                        "WHERE workspace_id = :workspace_id AND external_urn = :external_urn"
                    ),
                    {"workspace_id": workspace_id, "external_urn": external_urn},
                )
            ).one()

        assert projection.external_urn == external_urn
        assert (projection.platform, projection.database_name, projection.schema_name) == (
            "oracle",
            "ORCL",
            "semiconductor_seed",
        )
        assert projection.domain_id == expected_domain_id
        assert projection.system_id is None
        assert projection.classification == int(Classification.CONFIDENTIAL)
        assert projection.lifecycle == "ACTIVE"
        assert projection.source_version == "provider-v2"
        assert projection.column_names == ["unit_cost"]
        assert projection.projection_source == "DATAHUB"
    finally:
        await _cleanup_workspaces(admin, (workspace_id,))
        await database.dispose()
        await admin.dispose()


async def _write_replay_first_page(
    writer: SqlCatalogProjectionWriter,
    *,
    workspace_id: UUID,
    sync_id: UUID,
    observed_at: datetime,
) -> CatalogSyncResult:
    return await writer.upsert_scan(
        workspace_id=workspace_id,
        sync_id=sync_id,
        offset=0,
        cursor=None,
        next_offset=1,
        next_cursor="cursor-1",
        total=2,
        snapshot_consistent=False,
        snapshot_evidence_reference=None,
        snapshot_contract_hash=None,
        snapshot_provider_version=None,
        items=(_asset("first-page"),),
        observed_at=observed_at,
        idempotency_key="catalog-sync-replay",
        request_hash="3" * 64,
        operation="catalog.datahub.sync:0:100",
    )


async def _seed_projection_ownership(admin: AsyncEngine, workspace_id: UUID) -> None:
    stale_urn = "urn:li:dataset:stale-datahub"
    seed_urn = "urn:li:dataset:seed-owned"
    async with admin.begin() as connection:
        for ordinal, (external_urn, projection_source) in enumerate(
            ((stale_urn, "DATAHUB"), (seed_urn, "SEED"))
        ):
            await connection.execute(
                text(
                    "INSERT INTO catalog.assets_projection "
                    "(id, workspace_id, external_urn, urn_hash, asset_type, name, "
                    "description, tags, glossary_terms, column_names, classification, "
                    "lifecycle, source_version, observed_at, projection_source) "
                    "VALUES (:id, :workspace_id, :external_urn, :urn_hash, 'DATASET', "
                    ":name, NULL, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 0, "
                    "'ACTIVE', 'fixture-v1', now(), :projection_source)"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "external_urn": external_urn,
                    "urn_hash": hashlib.sha256(external_urn.encode()).hexdigest(),
                    "name": f"fixture-{ordinal}",
                    "projection_source": projection_source,
                },
            )


@pytest.mark.asyncio
async def test_catalog_projection_writer_persists_replays_and_tombstones_fail_closed() -> None:
    required = (
        _DATABASE_URL_ENV,
        _ADMIN_DATABASE_URL_ENV,
        _SECRET_REF_ENV,
        _ADMIN_SECRET_REF_ENV,
    )
    if os.getenv(_CONFIRM_ENV) != "1" or any(not os.getenv(name) for name in required):
        pytest.skip("isolated catalog sync PostgreSQL environment is not configured")

    database = _engine(url_env=_DATABASE_URL_ENV, secret_ref_env=_SECRET_REF_ENV)
    admin = _engine(url_env=_ADMIN_DATABASE_URL_ENV, secret_ref_env=_ADMIN_SECRET_REF_ENV)
    sessions = async_sessionmaker(database, expire_on_commit=False)
    (
        workspace_suppressed,
        workspace_replay,
        workspace_drift,
        workspace_incomplete,
        workspace_serialized,
        workspace_concurrent_replay,
    ) = (uuid4() for _ in range(6))
    workspace_ids = (
        workspace_suppressed,
        workspace_replay,
        workspace_drift,
        workspace_incomplete,
        workspace_serialized,
        workspace_concurrent_replay,
    )
    now = datetime.now(UTC)
    evidence_reference = "ops://datahub/pit/catalog-sync-integration"
    contract_hash = "a" * 64

    await _prepare_workspaces(admin, workspace_ids)
    try:
        await _seed_projection_ownership(admin, workspace_suppressed)
        async with sessions() as session:
            writer = SqlCatalogProjectionWriter(session)
            await _security_context(session, workspace_suppressed)
            suppressed = await writer.upsert_scan(
                workspace_id=workspace_suppressed,
                sync_id=uuid4(),
                offset=0,
                cursor=None,
                next_offset=None,
                next_cursor=None,
                total=1,
                snapshot_consistent=False,
                snapshot_evidence_reference=None,
                snapshot_contract_hash=None,
                snapshot_provider_version=None,
                items=(_asset("current"),),
                observed_at=now,
                idempotency_key="catalog-sync-suppressed",
                request_hash="1" * 64,
                operation="catalog.datahub.sync:0:100",
            )
        assert suppressed.tombstoned == 0
        assert suppressed.tombstone_status == "SUPPRESSED_UNVERIFIED_SNAPSHOT"

        async with admin.connect() as connection:
            stale_lifecycle = await connection.scalar(
                text(
                    "SELECT lifecycle FROM catalog.assets_projection "
                    "WHERE workspace_id = :workspace_id AND external_urn = :urn"
                ),
                {
                    "workspace_id": workspace_suppressed,
                    "urn": "urn:li:dataset:stale-datahub",
                },
            )
        assert stale_lifecycle == "ACTIVE"

        async with sessions() as session:
            writer = SqlCatalogProjectionWriter(session)
            await _security_context(session, workspace_suppressed)
            applied = await writer.upsert_scan(
                workspace_id=workspace_suppressed,
                sync_id=uuid4(),
                offset=0,
                cursor=None,
                next_offset=None,
                next_cursor=None,
                total=1,
                snapshot_consistent=True,
                snapshot_evidence_reference=evidence_reference,
                snapshot_contract_hash=contract_hash,
                snapshot_provider_version="v1.6.0",
                items=(_asset("current"),),
                observed_at=now,
                idempotency_key="catalog-sync-applied",
                request_hash="2" * 64,
                operation="catalog.datahub.sync:0:100",
            )
        assert applied.tombstoned == 1
        assert applied.tombstone_status == "APPLIED"
        async with admin.connect() as connection:
            ownership_states = (
                await connection.execute(
                    text(
                        "SELECT projection_source, lifecycle FROM catalog.assets_projection "
                        "WHERE workspace_id = :workspace_id "
                        "AND external_urn IN (:stale_urn, :seed_urn) "
                        "ORDER BY projection_source"
                    ),
                    {
                        "workspace_id": workspace_suppressed,
                        "stale_urn": "urn:li:dataset:stale-datahub",
                        "seed_urn": "urn:li:dataset:seed-owned",
                    },
                )
            ).all()
        assert [(str(row[0]), str(row[1])) for row in ownership_states] == [
            ("DATAHUB", "DELETED"),
            ("SEED", "ACTIVE"),
        ]
        async with sessions() as session:
            await _security_context(session, workspace_suppressed)
            facets = await SqlCatalogIndexReader(session).facets(
                subject=SubjectAttributes(
                    subject_id=uuid4(),
                    workspace_id=workspace_suppressed,
                    active=True,
                    department_id=None,
                    groups=frozenset(),
                    job_function="catalog-sync-test",
                    clearance=Classification.PUBLIC,
                ),
                access=static_classification_access_floor(),
                query="",
                filters={},
                limit=10,
            )
        assert facets.asset_types[0].value == "DATASET"
        assert facets.asset_types[0].count == 2

        replay_sync_id = uuid4()
        async with sessions() as session:
            writer = SqlCatalogProjectionWriter(session)
            await _security_context(session, workspace_replay)
            first_result = await _write_replay_first_page(
                writer,
                workspace_id=workspace_replay,
                sync_id=replay_sync_id,
                observed_at=now,
            )
            await _security_context(session, workspace_replay)
            replayed_result = await _write_replay_first_page(
                writer,
                workspace_id=workspace_replay,
                sync_id=replay_sync_id,
                observed_at=now,
            )
        assert replayed_result == first_result
        assert await _watermark(admin, workspace_replay) == 1

        async with sessions() as session:
            writer = SqlCatalogProjectionWriter(session)
            await _security_context(session, workspace_replay)
            with pytest.raises(ConflictError, match="repeated an asset"):
                await writer.upsert_scan(
                    workspace_id=workspace_replay,
                    sync_id=replay_sync_id,
                    offset=1,
                    cursor="cursor-1",
                    next_offset=None,
                    next_cursor=None,
                    total=2,
                    snapshot_consistent=False,
                    snapshot_evidence_reference=None,
                    snapshot_contract_hash=None,
                    snapshot_provider_version=None,
                    items=(_asset("first-page"),),
                    observed_at=now,
                    idempotency_key="catalog-sync-duplicate",
                    request_hash="4" * 64,
                    operation="catalog.datahub.sync:1:100",
                )
            await session.rollback()
        assert await _watermark(admin, workspace_replay) == 1

        drift_sync_id = uuid4()
        async with sessions() as session:
            writer = SqlCatalogProjectionWriter(session)
            await _security_context(session, workspace_drift)
            await writer.upsert_scan(
                workspace_id=workspace_drift,
                sync_id=drift_sync_id,
                offset=0,
                cursor=None,
                next_offset=1,
                next_cursor="verified-cursor",
                total=2,
                snapshot_consistent=True,
                snapshot_evidence_reference=evidence_reference,
                snapshot_contract_hash=contract_hash,
                snapshot_provider_version="v1.6.0",
                items=(_asset("verified-first"),),
                observed_at=now,
                idempotency_key="catalog-sync-drift-first",
                request_hash="5" * 64,
                operation="catalog.datahub.sync:0:100",
            )
            await _security_context(session, workspace_drift)
            with pytest.raises(ConflictError, match="snapshot changed"):
                await writer.upsert_scan(
                    workspace_id=workspace_drift,
                    sync_id=drift_sync_id,
                    offset=1,
                    cursor="verified-cursor",
                    next_offset=None,
                    next_cursor=None,
                    total=2,
                    snapshot_consistent=True,
                    snapshot_evidence_reference="ops://datahub/pit/different",
                    snapshot_contract_hash="b" * 64,
                    snapshot_provider_version="v1.6.0",
                    items=(_asset("verified-second"),),
                    observed_at=now,
                    idempotency_key="catalog-sync-drift-second",
                    request_hash="6" * 64,
                    operation="catalog.datahub.sync:1:100",
                )
            await session.rollback()
        assert await _watermark(admin, workspace_drift) == 1

        async with sessions() as session:
            writer = SqlCatalogProjectionWriter(session)
            await _security_context(session, workspace_incomplete)
            with pytest.raises(ConflictError, match="snapshot is incomplete"):
                await writer.upsert_scan(
                    workspace_id=workspace_incomplete,
                    sync_id=uuid4(),
                    offset=0,
                    cursor=None,
                    next_offset=None,
                    next_cursor=None,
                    total=2,
                    snapshot_consistent=False,
                    snapshot_evidence_reference=None,
                    snapshot_contract_hash=None,
                    snapshot_provider_version=None,
                    items=(_asset("incomplete"),),
                    observed_at=now,
                    idempotency_key="catalog-sync-incomplete",
                    request_hash="7" * 64,
                    operation="catalog.datahub.sync:0:100",
                )
            await session.rollback()
        assert await _watermark(admin, workspace_incomplete) is None

        first_sync_id = uuid4()
        second_sync_id = uuid4()
        async with sessions() as first_session, sessions() as second_session:
            first_writer = SqlCatalogProjectionWriter(first_session)
            second_writer = SqlCatalogProjectionWriter(second_session)
            await _security_context(first_session, workspace_serialized)
            await _security_context(second_session, workspace_serialized)
            first_reservation = await first_writer.reserve_scan(
                workspace_id=workspace_serialized,
                sync_id=first_sync_id,
                offset=0,
                idempotency_key="catalog-sync-serialized-first",
                request_hash="8" * 64,
                operation="catalog.datahub.sync:0:100",
            )
            assert first_reservation.cursor is None
            second_reservation_task = asyncio.create_task(
                second_writer.reserve_scan(
                    workspace_id=workspace_serialized,
                    sync_id=second_sync_id,
                    offset=0,
                    idempotency_key="catalog-sync-serialized-second",
                    request_hash="9" * 64,
                    operation="catalog.datahub.sync:0:100",
                )
            )
            await asyncio.sleep(0.05)
            assert second_reservation_task.done() is False
            await first_writer.upsert_scan(
                workspace_id=workspace_serialized,
                sync_id=first_sync_id,
                offset=0,
                cursor=None,
                next_offset=None,
                next_cursor=None,
                total=1,
                snapshot_consistent=False,
                snapshot_evidence_reference=None,
                snapshot_contract_hash=None,
                snapshot_provider_version=None,
                items=(_asset("serialized-first"),),
                observed_at=now,
                idempotency_key="catalog-sync-serialized-first",
                request_hash="8" * 64,
                operation="catalog.datahub.sync:0:100",
            )
            second_reservation = await asyncio.wait_for(second_reservation_task, timeout=1)
            assert second_reservation.cursor is None
            assert second_reservation.replayed is None
            await second_writer.release_scan()

        concurrent_sync_id = uuid4()
        async with sessions() as first_session, sessions() as second_session:
            first_writer = SqlCatalogProjectionWriter(first_session)
            second_writer = SqlCatalogProjectionWriter(second_session)
            await _security_context(first_session, workspace_concurrent_replay)
            await _security_context(second_session, workspace_concurrent_replay)
            reservation = await first_writer.reserve_scan(
                workspace_id=workspace_concurrent_replay,
                sync_id=concurrent_sync_id,
                offset=0,
                idempotency_key="catalog-sync-concurrent-replay",
                request_hash="a" * 64,
                operation="catalog.datahub.sync:0:100",
            )
            assert reservation.replayed is None
            committed = await first_writer.upsert_scan(
                workspace_id=workspace_concurrent_replay,
                sync_id=concurrent_sync_id,
                offset=0,
                cursor=None,
                next_offset=None,
                next_cursor=None,
                total=1,
                snapshot_consistent=False,
                snapshot_evidence_reference=None,
                snapshot_contract_hash=None,
                snapshot_provider_version=None,
                items=(_asset("concurrent-replay"),),
                observed_at=now,
                idempotency_key="catalog-sync-concurrent-replay",
                request_hash="a" * 64,
                operation="catalog.datahub.sync:0:100",
            )
            replay_reservation = await second_writer.reserve_scan(
                workspace_id=workspace_concurrent_replay,
                sync_id=concurrent_sync_id,
                offset=0,
                idempotency_key="catalog-sync-concurrent-replay",
                request_hash="a" * 64,
                operation="catalog.datahub.sync:0:100",
            )
            assert replay_reservation.replayed == committed
        assert await _watermark(admin, workspace_concurrent_replay) == 1
    finally:
        await _cleanup_workspaces(admin, workspace_ids)
        await database.dispose()
        await admin.dispose()
