from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from datariver.infrastructure.db.change_history import (
    CaptureSource,
    CrLinkEvent,
    NormalizedLedgerEvent,
    SqlChangeHistoryStore,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.secrets import SecretResolver

_OWNER_URL = "DATARIVER_CHANGE_HISTORY_TEST_OWNER_DATABASE_URL"
_OWNER_SECRET = "DATARIVER_CHANGE_HISTORY_TEST_OWNER_SECRET_REF"
_APP_URL = "DATARIVER_CHANGE_HISTORY_TEST_APP_DATABASE_URL"
_APP_SECRET = "DATARIVER_CHANGE_HISTORY_TEST_APP_SECRET_REF"
_CONFIRM = "DATARIVER_CHANGE_HISTORY_TEST_CONFIRM_ISOLATED"
_ENABLED = (
    all(os.getenv(name) for name in (_OWNER_URL, _OWNER_SECRET, _APP_URL, _APP_SECRET))
    and os.getenv(_CONFIRM) == "1"
)


def _engine(url_name: str, secret_name: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[url_name],
        connect_args={
            "password": SecretResolver().resolve(os.environ[secret_name]),
            "server_settings": {"application_name": f"datariver-change-history-{uuid4().hex}"},
        },
    )


async def _seed(owner: AsyncEngine) -> tuple[UUID, UUID, UUID, UUID]:
    workspace_id = uuid4()
    actor_id = uuid4()
    change_request_id = uuid4()
    round_id = uuid4()
    now = datetime.now(UTC)
    async with owner.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await connection.execute(
            text(
                "INSERT INTO platform.workspaces "
                "(id, slug, name, status, settings, version, created_at, updated_at) "
                "VALUES (:id, :slug, 'Change History test', 'ACTIVE', '{}'::jsonb, 1, :now, :now)"
            ),
            {"id": workspace_id, "slug": f"change-history-{workspace_id.hex}", "now": now},
        )
        await connection.execute(
            text(
                "INSERT INTO iam.subjects "
                "(id, issuer, external_subject, display_name, active, created_at, updated_at) "
                "VALUES (:id, 'test', :external_subject, 'Change History actor', true, :now, :now)"
            ),
            {"id": actor_id, "external_subject": actor_id.hex, "now": now},
        )
        await connection.execute(
            text(
                "INSERT INTO iam.workspace_memberships "
                "(workspace_id, subject_id, clearance, attributes, active, version, "
                "created_at, updated_at) "
                "VALUES (:workspace_id, :subject_id, 3, '{}'::jsonb, true, 1, :now, :now)"
            ),
            {"workspace_id": workspace_id, "subject_id": actor_id, "now": now},
        )
        await connection.execute(
            text(
                "INSERT INTO governance.change_requests "
                "(id, workspace_id, number, request_type, title, description, state, "
                "requester_id, current_round_id, current_round_number, classification, "
                "version, created_at, updated_at) VALUES "
                "(:id, :workspace_id, :number, 'METADATA', 'History link target', '', "
                "'REGISTERED', :actor_id, :round_id, 1, 0, 1, :now, :now)"
            ),
            {
                "id": change_request_id,
                "workspace_id": workspace_id,
                "number": f"CH-{change_request_id.hex[:12]}",
                "actor_id": actor_id,
                "round_id": round_id,
                "now": now,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO governance.change_request_rounds "
                "(id, workspace_id, change_request_id, round_number, submitted_by, "
                "submitted_at, evidence_hash, revision_kind, title, request_department, "
                "request_reason, request_content, classification) VALUES "
                "(:id, :workspace_id, :change_request_id, 1, :actor_id, :now, :hash, "
                "'INITIAL', 'History link target', 'Test', 'Test', 'Test', 0)"
            ),
            {
                "id": round_id,
                "workspace_id": workspace_id,
                "change_request_id": change_request_id,
                "actor_id": actor_id,
                "now": now,
                "hash": "1" * 64,
            },
        )
    return workspace_id, actor_id, change_request_id, round_id


def _event(workspace_id: UUID, source_id: UUID) -> NormalizedLedgerEvent:
    observed = datetime.now(UTC)
    return NormalizedLedgerEvent(
        workspace_id=workspace_id,
        source_id=source_id,
        event_identity="2" * 64,
        source_event_identity="3" * 64,
        normalized_change_transaction_id="4" * 64,
        deterministic_ordinal=0,
        source_kind="MCL",
        topic_contract="MetadataChangeLog_Versioned_v1@schema-contract",
        source_partition=0,
        source_offset=100,
        asset_id=None,
        entity_urn="urn:li:dataset:(urn:li:dataPlatform:test,db.schema.table,PROD)",
        entity_urn_hash="5" * 64,
        entity_type="dataset",
        platform="test",
        database_name="db",
        schema_name="schema",
        table_or_view_name="table",
        field_path="column",
        normalized_entity_key="db.schema.table.column",
        system_id=None,
        category="TECHNICAL_SCHEMA",
        source_aspect="schemaMetadata",
        operation="UPDATE",
        before_data={"field_type": "string"},
        after_data={"field_type": "integer"},
        before_hash="6" * 64,
        after_hash="7" * 64,
        actor_ref="urn:li:corpuser:test",
        source_occurred_at=observed,
        detected_at=observed,
        captured_at=observed,
        effective_week_start=date(2026, 8, 10),
        precision="EXACT_MCL",
        tombstone=False,
        source_metadata={"schema_contract_version": "v1"},
    )


@pytest.mark.skipif(not _ENABLED, reason="confirmed isolated Change History PostgreSQL is required")
async def test_change_history_replay_fence_rls_grants_and_cr_links_on_postgres() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    app_sessions = async_sessionmaker(app, expire_on_commit=False)
    store = SqlChangeHistoryStore(app_sessions)
    try:
        workspace_id, actor_id, change_request_id, round_id = await _seed(owner)
        source = CaptureSource(
            workspace_id=workspace_id,
            source_identity_hash="8" * 64,
            source_generation=1,
            provider_name="DataHub",
            provider_version="validated-source-version",
            schema_contract_hash="9" * 64,
        )
        source_id = await store.ensure_source(source)
        assert await store.ensure_source(source) == source_id

        event = _event(workspace_id, source_id)
        first = await store.append_ledger_event(event)
        replay = await store.append_ledger_event(event)
        assert replay.event_id == first.event_id
        assert first.replayed is False
        assert replay.replayed is True

        owner_fingerprint = "a" * 64
        lease_token_hash = "b" * 64
        async with owner.connect() as connection:
            before_claim = await connection.scalar(text("SELECT clock_timestamp()"))
        lease = await store.acquire_checkpoint_lease(
            workspace_id=workspace_id,
            source_id=source_id,
            topic_contract="MetadataChangeLog_Versioned_v1@schema-contract",
            source_partition=0,
            initial_next_offset=100,
            owner_fingerprint=owner_fingerprint,
            lease_token_hash=lease_token_hash,
            lease_duration_seconds=300,
        )
        async with owner.connect() as connection:
            after_claim = await connection.scalar(text("SELECT clock_timestamp()"))
            lease_clock = (
                (
                    await connection.execute(
                        text(
                            "SELECT lease_acquired_at, lease_expires_at "
                            "FROM change_history.checkpoints WHERE id = :checkpoint_id"
                        ),
                        {"checkpoint_id": lease.checkpoint_id},
                    )
                )
                .mappings()
                .one()
            )
            claim_arguments = await connection.scalar(
                text(
                    "SELECT proargnames FROM pg_proc WHERE oid = "
                    "'change_history.claim_checkpoint_v1(uuid,uuid,text,integer,bigint,text,text,integer)'::regprocedure"
                )
            )
        assert before_claim <= lease_clock["lease_acquired_at"] <= after_claim
        assert lease_clock["lease_expires_at"] - lease_clock["lease_acquired_at"] == timedelta(
            minutes=5
        )
        assert "p_lease_duration_seconds" in claim_arguments
        assert "p_acquired_at" not in claim_arguments
        assert "p_expires_at" not in claim_arguments
        with pytest.raises(DBAPIError):
            await store.acquire_checkpoint_lease(
                workspace_id=workspace_id,
                source_id=source_id,
                topic_contract="MetadataChangeLog_Versioned_v1@schema-contract",
                source_partition=0,
                initial_next_offset=100,
                owner_fingerprint="c" * 64,
                lease_token_hash="d" * 64,
                lease_duration_seconds=300,
            )
        advanced = await store.advance_checkpoint(
            workspace_id=workspace_id,
            checkpoint_id=lease.checkpoint_id,
            expected_version=lease.version,
            expected_fence_epoch=lease.fence_epoch,
            expected_next_offset=100,
            next_offset=101,
            owner_fingerprint=owner_fingerprint,
            lease_token_hash=lease_token_hash,
            last_event_identity=event.event_identity,
            source_occurred_at=event.source_occurred_at,
            captured_at=event.captured_at,
            establish_first_exact=True,
        )
        assert advanced.next_offset == 101
        with pytest.raises(DBAPIError):
            await store.advance_checkpoint(
                workspace_id=workspace_id,
                checkpoint_id=lease.checkpoint_id,
                expected_version=lease.version,
                expected_fence_epoch=lease.fence_epoch,
                expected_next_offset=100,
                next_offset=102,
                owner_fingerprint=owner_fingerprint,
                lease_token_hash=lease_token_hash,
                last_event_identity=event.event_identity,
                source_occurred_at=event.source_occurred_at,
                captured_at=event.captured_at,
            )

        primary_hash = "c" * 64
        primary = CrLinkEvent(
            workspace_id=workspace_id,
            ledger_event_id=first.event_id,
            link_version=1,
            link_kind="PRIMARY",
            action="SET_PRIMARY",
            change_request_id=change_request_id,
            change_request_round_id=round_id,
            active_result=True,
            resulting_primary_change_request_id=change_request_id,
            resulting_primary_round_id=round_id,
            prior_link_hash=None,
            event_hash=primary_hash,
            reason="Link exact captured change evidence",
            policy_hash="d" * 64,
            basis_hash="e" * 64,
            actor_id=actor_id,
            created_at=datetime.now(UTC),
        )
        primary_result = await store.append_cr_link_event(primary)
        assert (await store.append_cr_link_event(primary)).event_id == primary_result.event_id
        await store.append_cr_link_event(
            CrLinkEvent(
                workspace_id=workspace_id,
                ledger_event_id=first.event_id,
                link_version=2,
                link_kind="PRIMARY",
                action="CLEAR_PRIMARY",
                change_request_id=change_request_id,
                change_request_round_id=round_id,
                active_result=False,
                resulting_primary_change_request_id=None,
                resulting_primary_round_id=None,
                prior_link_hash=primary_hash,
                event_hash="f" * 64,
                reason="Clear the primary without changing the CR",
                policy_hash="d" * 64,
                basis_hash="e" * 64,
                actor_id=actor_id,
                created_at=datetime.now(UTC),
            )
        )

        async with app_sessions() as session, session.begin():
            await set_security_context(session, workspace_id=uuid4(), subject_id=actor_id)
            assert (
                await session.scalar(text("SELECT count(*) FROM change_history.ledger_events")) == 0
            )
        async with app_sessions() as session, session.begin():
            await set_security_context(session, workspace_id=workspace_id, subject_id=actor_id)
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "UPDATE change_history.ledger_events "
                        "SET operation = 'DELETE' WHERE id = :id"
                    ),
                    {"id": first.event_id},
                )

        async with owner.connect() as connection:
            forced = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_class AS c "
                    "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'change_history' "
                    "AND c.relname IN ('sources','ledger_events','checkpoints','cr_link_events') "
                    "AND c.relrowsecurity AND c.relforcerowsecurity"
                )
            )
            assert forced == 4
            mutable_evidence = await connection.scalar(
                text(
                    "SELECT count(*) FROM (VALUES "
                    "('ledger_events'), ('cr_link_events')) AS names(table_name) "
                    "WHERE has_table_privilege('datariver_app', "
                    "'change_history.' || table_name, 'UPDATE') "
                    "OR has_table_privilege('datariver_app', "
                    "'change_history.' || table_name, 'DELETE')"
                )
            )
            assert mutable_evidence == 0
    finally:
        await app.dispose()
        await owner.dispose()
