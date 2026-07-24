from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from datariver.application.dto import InvocationAuthorizationRecord, InvocationResultRecord
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    RateLimitError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.retention import (
    GovernanceDecision,
    RetentionArchiveDisposition,
    RetentionClassRule,
    RetentionDataClass,
    RetentionPeriodUnit,
    RetentionPolicyContract,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.db.sharing import SqlSharingStore
from datariver.infrastructure.secrets import SecretResolver

_OWNER_URL = "DATARIVER_SHARING_TEST_OWNER_DATABASE_URL"
_OWNER_SECRET = "DATARIVER_SHARING_TEST_OWNER_SECRET_REF"
_APP_URL = "DATARIVER_SHARING_TEST_APP_DATABASE_URL"
_APP_SECRET = "DATARIVER_SHARING_TEST_APP_SECRET_REF"
_CONFIRM = "DATARIVER_SHARING_TEST_CONFIRM_ISOLATED"
_ENABLED = (
    all(os.getenv(name) for name in (_OWNER_URL, _OWNER_SECRET, _APP_URL, _APP_SECRET))
    and os.getenv(_CONFIRM) == "1"
)
_RESULT_DOCUMENT: dict[str, Any] = {"nodes": [], "edges": [], "truncated": False}


@dataclass(frozen=True, slots=True)
class _Fixture:
    workspace_id: UUID
    owner_id: UUID
    reviewer_id: UUID
    consumer_id: UUID
    other_consumer_id: UUID
    graph_id: UUID
    changeset_id: UUID
    release_id: UUID
    release_content_hash: str
    product_id: UUID
    product_version_id: UUID
    grant_id: UUID
    retention_policy_id: UUID
    retention_policy_hash: str
    consumer_issuer: str
    consumer_client_id: str


def _engine(url_name: str, secret_name: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[url_name],
        connect_args={
            "password": SecretResolver().resolve(os.environ[secret_name]),
            "server_settings": {
                "application_name": f"datariver-sharing-atomic-{uuid4().hex}",
                "lock_timeout": "5s",
                "statement_timeout": "20s",
            },
        },
        pool_size=5,
        max_overflow=0,
    )


async def _seed(
    owner: AsyncEngine,
    *,
    requests_per_minute: int = 10,
    monthly_quota: int = 100,
) -> _Fixture:
    workspace_id = uuid4()
    owner_id = uuid4()
    reviewer_id = uuid4()
    consumer_id = uuid4()
    other_consumer_id = uuid4()
    graph_id = uuid4()
    ontology_id = uuid4()
    changeset_id = uuid4()
    release_id = uuid4()
    product_id = uuid4()
    product_version_id = uuid4()
    grant_id = uuid4()
    consumer_issuer = f"https://issuer.test/{workspace_id}"
    consumer_client_id = f"sharing-client-{workspace_id.hex}"
    now = datetime.now(UTC)
    release_hash = hashlib.sha256(f"release:{release_id}".encode()).hexdigest()
    class_rules = tuple(
        RetentionClassRule(
            data_class=data_class,
            unit=RetentionPeriodUnit.DAYS,
            minimum=7 if data_class is RetentionDataClass.AUDIT_EVIDENCE else 1,
            maximum=maximum,
            archive_disposition=disposition,
        )
        for data_class, maximum, disposition in (
            (
                RetentionDataClass.COMPLETED_OPERATIONS,
                30,
                RetentionArchiveDisposition.NO_ARCHIVE,
            ),
            (
                RetentionDataClass.CHAT_CONTENT,
                30,
                RetentionArchiveDisposition.EVIDENCE_ONLY,
            ),
            (
                RetentionDataClass.AUDIT_EVIDENCE,
                365,
                RetentionArchiveDisposition.EVIDENCE_ONLY,
            ),
            (
                RetentionDataClass.OBJECT_DATA,
                30,
                RetentionArchiveDisposition.NO_ARCHIVE,
            ),
        )
    )
    retention_contract = RetentionPolicyContract(
        effective_from=now - timedelta(days=1),
        effective_until=now + timedelta(days=365),
        execution_authorization_hours=24,
        class_rules=class_rules,
    )
    retention_policy = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=1,
        rules=RetentionRules(30, 30, 12, 1),
        contract=retention_contract,
        requester_id=owner_id,
        reason="Atomic Sharing retention fixture",
        policy_decision_id=uuid4(),
    )
    retention_policy.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=reviewer_id,
        reason="Independent retention approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now - timedelta(minutes=1),
    )
    retention_policy_id = retention_policy.policy_id
    retention_policy_hash = retention_policy.payload_hash
    contract = json.dumps(
        {
            "scopes": ["neighbors.query"],
            "response_schema": {"type": "object", "additionalProperties": False},
            "query_template": "neighbors-v1",
        }
    )

    async with owner.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version)
                VALUES
                    (:workspace_id, :slug, 'Atomic Sharing integration',
                     'ACTIVE', '{}'::jsonb, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "slug": f"sharing-atomic-{workspace_id.hex}",
            },
        )
        for subject_id, issuer, label in (
            (owner_id, "sharing-owner-test", "Sharing owner"),
            (reviewer_id, "sharing-reviewer-test", "Sharing reviewer"),
            (consumer_id, consumer_issuer, "Sharing consumer"),
            (other_consumer_id, consumer_issuer, "Other Sharing consumer"),
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.subjects
                        (id, issuer, external_subject, display_name, active)
                    VALUES
                        (:subject_id, :issuer, :external_subject, :label, true)
                    """
                ),
                {
                    "subject_id": subject_id,
                    "issuer": issuer,
                    "external_subject": str(subject_id),
                    "label": label,
                },
            )
            service_account = subject_id in {consumer_id, other_consumer_id}
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.workspace_memberships (
                        workspace_id, subject_id, job_function, clearance,
                        attributes, active, access_expires_at, version
                    ) VALUES (
                        :workspace_id, :subject_id, :job_function, 1,
                        '{}'::jsonb, true, :access_expires_at, 1
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "subject_id": subject_id,
                    "job_function": "SERVICE_ACCOUNT" if service_account else "DATA_OWNER",
                    "access_expires_at": None if service_account else now + timedelta(days=30),
                },
            )

        await connection.execute(
            text(
                """
                INSERT INTO knowledge.graphs (
                    id, workspace_id, slug, name, graph_type, status,
                    active_release_id, classification, version
                ) VALUES (
                    :graph_id, :workspace_id, :slug, 'Atomic Sharing graph',
                    'DOMAIN', 'DRAFT', NULL, 1, 1
                )
                """
            ),
            {
                "graph_id": graph_id,
                "workspace_id": workspace_id,
                "slug": f"sharing-graph-{graph_id.hex}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.ontology_versions (
                    id, workspace_id, graph_id, version, schema_document,
                    checksum, status
                ) VALUES (
                    :ontology_id, :workspace_id, :graph_id, '1.0.0',
                    '{"entity_types":["Dataset"],"edge_types":[]}'::jsonb,
                    :checksum, 'ACTIVE'
                )
                """
            ),
            {
                "ontology_id": ontology_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "checksum": hashlib.sha256(b"sharing-ontology").hexdigest(),
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.changesets (
                    id, workspace_id, graph_id, base_release_id,
                    ontology_version_id, title, state, author_id,
                    reviewed_by, reviewed_at, review_reason,
                    published_release_id, version
                ) VALUES (
                    :changeset_id, :workspace_id, :graph_id, NULL,
                    :ontology_id, 'Atomic Sharing governed release',
                    'PUBLISHED', :owner_id, :reviewer_id, :reviewed_at,
                    'Independent integration review', NULL, 4
                )
                """
            ),
            {
                "changeset_id": changeset_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "ontology_id": ontology_id,
                "owner_id": owner_id,
                "reviewer_id": reviewer_id,
                "reviewed_at": now - timedelta(minutes=1),
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.releases (
                    id, workspace_id, graph_id, release_no, ontology_version_id,
                    content_hash, node_count, edge_count, manifest_ref,
                    published_by, published_at
                ) VALUES (
                    :release_id, :workspace_id, :graph_id, 1, :ontology_id,
                    :content_hash, 1, 0, NULL, :reviewer_id, :published_at
                )
                """
            ),
            {
                "release_id": release_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "ontology_id": ontology_id,
                "content_hash": release_hash,
                "reviewer_id": reviewer_id,
                "published_at": now,
            },
        )
        await connection.execute(
            text(
                """
                UPDATE knowledge.changesets
                SET published_release_id = :release_id
                WHERE workspace_id = :workspace_id AND id = :changeset_id
                """
            ),
            {
                "release_id": release_id,
                "workspace_id": workspace_id,
                "changeset_id": changeset_id,
            },
        )
        await connection.execute(
            text(
                """
                UPDATE knowledge.graphs
                SET active_release_id = :release_id, status = 'PUBLISHED', version = 2
                WHERE workspace_id = :workspace_id AND id = :graph_id
                """
            ),
            {
                "release_id": release_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
            },
        )

        await connection.execute(
            text(
                """
                INSERT INTO sharing.api_products (
                    id, workspace_id, slug, name, description, graph_id,
                    classification, owner_id, state, current_version_id, version
                ) VALUES (
                    :product_id, :workspace_id, :slug, 'Atomic neighbors',
                    'Atomic invocation fixture', :graph_id, 1, :owner_id,
                    'PUBLISHED', NULL, 2
                )
                """
            ),
            {
                "product_id": product_id,
                "workspace_id": workspace_id,
                "slug": f"atomic-neighbors-{product_id.hex}",
                "graph_id": graph_id,
                "owner_id": owner_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO sharing.api_product_versions (
                    id, workspace_id, product_id, graph_id, release_id,
                    version_no, surface, contract_document, maximum_hops,
                    maximum_nodes, timeout_ms, state, created_by,
                    published_by, published_at
                ) VALUES (
                    :version_id, :workspace_id, :product_id, :graph_id,
                    :release_id, 1, 'NEIGHBORS', CAST(:contract AS jsonb),
                    2, 100, 5000, 'PUBLISHED', :owner_id, :owner_id, :now
                )
                """
            ),
            {
                "version_id": product_version_id,
                "workspace_id": workspace_id,
                "product_id": product_id,
                "graph_id": graph_id,
                "release_id": release_id,
                "contract": contract,
                "owner_id": owner_id,
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                UPDATE sharing.api_products
                SET current_version_id = :version_id
                WHERE workspace_id = :workspace_id AND id = :product_id
                """
            ),
            {
                "version_id": product_version_id,
                "workspace_id": workspace_id,
                "product_id": product_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO sharing.consumer_grants (
                    id, workspace_id, product_id, product_version_id,
                    contract_version, consumer_subject_id, consumer_issuer,
                    consumer_client_id, scopes, maximum_classification,
                    requests_per_minute, monthly_quota, valid_from, expires_at,
                    state, created_by, version
                ) VALUES (
                    :grant_id, :workspace_id, :product_id, :version_id,
                    'SUBJECT_CLIENT_V2', :consumer_id, :issuer, :client_id,
                    '["neighbors.query"]'::jsonb, 1, :rpm, :monthly_quota,
                    :valid_from, :expires_at, 'ACTIVE', :owner_id, 1
                )
                """
            ),
            {
                "grant_id": grant_id,
                "workspace_id": workspace_id,
                "product_id": product_id,
                "version_id": product_version_id,
                "consumer_id": consumer_id,
                "issuer": consumer_issuer,
                "client_id": consumer_client_id,
                "rpm": requests_per_minute,
                "monthly_quota": monthly_quota,
                "valid_from": now - timedelta(minutes=1),
                "expires_at": now + timedelta(days=1),
                "owner_id": owner_id,
            },
        )

        await connection.execute(
            text(
                """
                INSERT INTO retention.policy_versions (
                    id, workspace_id, policy_number, completed_operation_days,
                    chat_content_days, audit_online_months, immutable_archive_years,
                    contract_version, effective_from, effective_until,
                    execution_authorization_hours, payload_hash, requester_id,
                    request_reason, request_policy_decision_id, state, checker_id,
                    decision_reason, decision_policy_decision_id, decided_at, version
                ) VALUES (
                    :policy_id, :workspace_id, 1, 30, 30, 12, 1,
                    'POLICY_BOOK_V2', :effective_from, :effective_until, 24,
                    :policy_hash, :owner_id, 'Atomic Sharing retention fixture',
                    :request_decision_id, 'ACTIVE', :reviewer_id,
                    'Independent retention approval', :decision_id, :decided_at, 2
                )
                """
            ),
            {
                "policy_id": retention_policy_id,
                "workspace_id": workspace_id,
                "effective_from": retention_contract.effective_from,
                "effective_until": retention_contract.effective_until,
                "policy_hash": retention_policy_hash,
                "owner_id": owner_id,
                "request_decision_id": retention_policy.request_policy_decision_id,
                "reviewer_id": reviewer_id,
                "decision_id": retention_policy.decision_policy_decision_id,
                "decided_at": retention_policy.decided_at,
            },
        )
        for rule in class_rules:
            await connection.execute(
                text(
                    """
                    INSERT INTO retention.policy_class_rules (
                        id, workspace_id, policy_id, policy_hash, policy_number,
                        data_class, unit, minimum_value, maximum_value,
                        archive_disposition, payload_hash
                    ) VALUES (
                        :id, :workspace_id, :policy_id, :policy_hash, 1,
                        :data_class, :unit, :minimum, :maximum,
                        :disposition, :payload_hash
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "policy_id": retention_policy_id,
                    "policy_hash": retention_policy_hash,
                    "data_class": rule.data_class.value,
                    "unit": rule.unit.value,
                    "minimum": rule.minimum,
                    "maximum": rule.maximum,
                    "disposition": rule.archive_disposition.value,
                    "payload_hash": canonical_json_hash(rule.document()),
                },
            )

    return _Fixture(
        workspace_id=workspace_id,
        owner_id=owner_id,
        reviewer_id=reviewer_id,
        consumer_id=consumer_id,
        other_consumer_id=other_consumer_id,
        graph_id=graph_id,
        changeset_id=changeset_id,
        release_id=release_id,
        release_content_hash=release_hash,
        product_id=product_id,
        product_version_id=product_version_id,
        grant_id=grant_id,
        retention_policy_id=retention_policy_id,
        retention_policy_hash=retention_policy_hash,
        consumer_issuer=consumer_issuer,
        consumer_client_id=consumer_client_id,
    )


async def _invoke(
    app: AsyncEngine,
    fixture: _Fixture,
    *,
    invocation_key: str,
    request_id: str,
    result_builder: Callable[[InvocationAuthorizationRecord], Awaitable[dict[str, Any]]],
    actor_id: UUID | None = None,
    issuer: str | None = None,
    payload_document: dict[str, Any] | None = None,
    security_scopes: frozenset[str] | None = None,
) -> InvocationResultRecord:
    selected_actor = actor_id or fixture.consumer_id
    sessions = async_sessionmaker(app, expire_on_commit=False)
    async with sessions() as session:
        await set_security_context(
            session,
            workspace_id=fixture.workspace_id,
            subject_id=selected_actor,
        )
        return await SqlSharingStore(session).execute_invocation(
            workspace_id=fixture.workspace_id,
            product_id=fixture.product_id,
            actor_id=selected_actor,
            consumer_issuer=issuer or fixture.consumer_issuer,
            consumer_client_id=fixture.consumer_client_id,
            security_scopes=security_scopes
            or frozenset(
                {
                    "active:true",
                    "clearance:1",
                    "job_function:SERVICE_ACCOUNT",
                }
            ),
            effective_classification=1,
            requested_scope="neighbors.query",
            operation="NEIGHBORS_V1",
            result_type="NEIGHBORS_V1",
            payload_document=payload_document or {"node_id": "root", "hops": 1},
            invocation_key=invocation_key,
            request_id=request_id,
            result_builder=result_builder,
        )


async def _counts(owner: AsyncEngine, fixture: _Fixture) -> tuple[int, int, int]:
    async with owner.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*) FROM sharing.api_invocations
                            WHERE workspace_id = :workspace_id
                              AND grant_id = :grant_id
                        ),
                        (
                            SELECT count(*) FROM sharing.api_invocation_results
                            WHERE workspace_id = :workspace_id
                        ),
                        COALESCE(
                            (
                                SELECT sum(units)
                                FROM sharing.api_invocation_monthly_usage
                                WHERE workspace_id = :workspace_id
                                  AND grant_id = :grant_id
                            ),
                            0
                        )
                    """
                ),
                {
                    "workspace_id": fixture.workspace_id,
                    "grant_id": fixture.grant_id,
                },
            )
        ).one()
    return int(row[0]), int(row[1]), int(row[2])


async def _fixed_result(_: InvocationAuthorizationRecord) -> dict[str, Any]:
    return _RESULT_DOCUMENT


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_first_invocation_and_replay_are_one_durable_exact_result() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        fixture = await _seed(owner)
        builder_calls = 0

        async def build(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            nonlocal builder_calls
            builder_calls += 1
            return _RESULT_DOCUMENT

        first = await _invoke(
            app,
            fixture,
            invocation_key="durable-result-key",
            request_id="first-delivery",
            result_builder=build,
        )
        replay = await _invoke(
            app,
            fixture,
            invocation_key="durable-result-key",
            request_id="retry-delivery",
            result_builder=build,
        )

        assert builder_calls == 1
        assert first.replayed is False
        assert replay.replayed is True
        assert replay.authorization.invocation_id == first.authorization.invocation_id
        assert replay.result_document == first.result_document == _RESULT_DOCUMENT
        assert await _counts(owner, fixture) == (1, 1, 1)

        expected_document = json.dumps(
            _RESULT_DOCUMENT,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        async with owner.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            invocation.invocation_key,
                            invocation.request_id,
                            invocation.actor_id,
                            invocation.consumer_client_id,
                            invocation.release_id,
                            invocation.result_hash,
                            invocation.result_size_bytes,
                            invocation.retention_policy_id,
                            invocation.retention_policy_hash,
                            invocation.retention_until,
                            invocation.audit_retention_policy_id,
                            invocation.audit_retention_policy_hash,
                            invocation.audit_retention_until,
                            result.result_document,
                            result.result_hash,
                            result.result_size_bytes,
                            result.retention_until
                        FROM sharing.api_invocations AS invocation
                        JOIN sharing.api_invocation_results AS result
                          ON result.workspace_id = invocation.workspace_id
                         AND result.invocation_id = invocation.id
                        WHERE invocation.workspace_id = :workspace_id
                          AND invocation.grant_id = :grant_id
                        """
                    ),
                    {
                        "workspace_id": fixture.workspace_id,
                        "grant_id": fixture.grant_id,
                    },
                )
            ).one()
        expected_hash = hashlib.sha256(expected_document.encode()).hexdigest()
        assert row[0] == hashlib.sha256(b"durable-result-key").hexdigest()
        assert row[0] != "durable-result-key"
        assert row[1] == "first-delivery"
        assert row[2] == fixture.consumer_id
        assert row[3] == fixture.consumer_client_id
        assert row[4] == fixture.release_id
        assert row[5] == row[14] == expected_hash
        assert row[6] == row[15] == len(expected_document.encode())
        assert row[7] == fixture.retention_policy_id
        assert row[8] == fixture.retention_policy_hash
        assert row[10] == fixture.retention_policy_id
        assert row[11] == fixture.retention_policy_hash
        assert row[12] > row[9] + timedelta(days=5)
        assert row[9] == row[16]
        assert row[13] == expected_document
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_same_key_race_executes_once_and_changed_payload_conflicts() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        fixture = await _seed(owner)
        builder_calls = 0

        async def build(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            nonlocal builder_calls
            builder_calls += 1
            await asyncio.sleep(0.05)
            return _RESULT_DOCUMENT

        first, second = await asyncio.gather(
            _invoke(
                app,
                fixture,
                invocation_key="concurrent-key-0001",
                request_id="concurrent-one",
                result_builder=build,
            ),
            _invoke(
                app,
                fixture,
                invocation_key="concurrent-key-0001",
                request_id="concurrent-two",
                result_builder=build,
            ),
        )
        assert builder_calls == 1
        assert {first.replayed, second.replayed} == {False, True}
        assert first.authorization.invocation_id == second.authorization.invocation_id
        assert first.result_document == second.result_document
        assert await _counts(owner, fixture) == (1, 1, 1)

        different_binding_calls = 0

        async def build_different(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            nonlocal different_binding_calls
            different_binding_calls += 1
            await asyncio.sleep(0.05)
            return _RESULT_DOCUMENT

        different_binding_outcomes = await asyncio.gather(
            _invoke(
                app,
                fixture,
                invocation_key="different-binding-race",
                request_id="different-binding-one",
                payload_document={"node_id": "first", "hops": 1},
                result_builder=build_different,
            ),
            _invoke(
                app,
                fixture,
                invocation_key="different-binding-race",
                request_id="different-binding-two",
                payload_document={"node_id": "second", "hops": 1},
                result_builder=build_different,
            ),
            return_exceptions=True,
        )
        assert different_binding_calls == 1
        assert (
            sum(isinstance(value, InvocationResultRecord) for value in different_binding_outcomes)
            == 1
        )
        assert sum(isinstance(value, ConflictError) for value in different_binding_outcomes) == 1
        assert await _counts(owner, fixture) == (2, 2, 2)

        with pytest.raises(ConflictError, match="different or invalid result binding"):
            await _invoke(
                app,
                fixture,
                invocation_key="concurrent-key-0001",
                request_id="changed-payload",
                payload_document={"node_id": "different", "hops": 1},
                result_builder=build,
            )
        assert builder_calls == 1
        assert await _counts(owner, fixture) == (2, 2, 2)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_failed_and_oversize_builders_do_not_consume_usage() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        fixture = await _seed(owner)

        async def fail(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            raise RuntimeError("injected-builder-failure")

        async def oversize(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            return {"payload": "x" * 1_048_576}

        with pytest.raises(RuntimeError, match="injected-builder-failure"):
            await _invoke(
                app,
                fixture,
                invocation_key="failed-builder-0001",
                request_id="failed-builder",
                result_builder=fail,
            )
        with pytest.raises(ValidationError, match="1 MiB"):
            await _invoke(
                app,
                fixture,
                invocation_key="oversize-builder",
                request_id="oversize-builder",
                result_builder=oversize,
            )
        assert await _counts(owner, fixture) == (0, 0, 0)

        result = await _invoke(
            app,
            fixture,
            invocation_key="valid-after-failure",
            request_id="valid-after-failure",
            result_builder=_fixed_result,
        )
        assert result.replayed is False
        assert await _counts(owner, fixture) == (1, 1, 1)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_subject_issuer_and_revocation_deny_result_disclosure() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        fixture = await _seed(owner)
        await _invoke(
            app,
            fixture,
            invocation_key="identity-bound-key",
            request_id="identity-first",
            result_builder=_fixed_result,
        )
        forbidden_builder_calls = 0

        async def forbidden_builder(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            nonlocal forbidden_builder_calls
            forbidden_builder_calls += 1
            return {"leaked": True}

        with pytest.raises(ForbiddenError, match="No active current-version grant"):
            await _invoke(
                app,
                fixture,
                invocation_key="identity-bound-key",
                request_id="other-subject",
                actor_id=fixture.other_consumer_id,
                result_builder=forbidden_builder,
            )
        with pytest.raises(ForbiddenError, match="No active current-version grant"):
            await _invoke(
                app,
                fixture,
                invocation_key="identity-bound-key",
                request_id="wrong-issuer",
                issuer="https://wrong-issuer.test",
                result_builder=forbidden_builder,
            )

        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE sharing.consumer_grants
                    SET state = 'REVOKED', revoked_by = :owner_id,
                        revoked_at = clock_timestamp(), version = version + 1
                    WHERE workspace_id = :workspace_id AND id = :grant_id
                    """
                ),
                {
                    "workspace_id": fixture.workspace_id,
                    "grant_id": fixture.grant_id,
                    "owner_id": fixture.owner_id,
                },
            )
        with pytest.raises(ForbiddenError):
            await _invoke(
                app,
                fixture,
                invocation_key="identity-bound-key",
                request_id="revoked-replay",
                result_builder=forbidden_builder,
            )
        assert forbidden_builder_calls == 0
        assert await _counts(owner, fixture) == (1, 1, 1)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_app_has_only_fixed_function_access_and_evidence_is_immutable() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        fixture = await _seed(owner)
        result = await _invoke(
            app,
            fixture,
            invocation_key="privilege-key-0001",
            request_id="privilege-request",
            result_builder=_fixed_result,
        )
        async with owner.connect() as connection:
            privileges = (
                await connection.execute(
                    text(
                        """
                        SELECT table_name, privilege,
                               has_table_privilege('datariver_app', table_name, privilege)
                        FROM unnest(ARRAY[
                            'sharing.api_invocations',
                            'sharing.api_invocation_results',
                            'sharing.api_invocation_monthly_usage'
                            ]) AS table_name
                            CROSS JOIN unnest(ARRAY[
                                'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                'TRUNCATE', 'REFERENCES', 'TRIGGER'
                            ]) AS privilege
                        ORDER BY table_name, privilege
                        """
                    )
                )
            ).all()
        assert len(privileges) == 21
        assert all(row[2] is False for row in privileges)
        async with owner.connect() as connection:
            trigger_states = (
                await connection.execute(
                    text(
                        """
                        SELECT tgname, tgenabled::text
                        FROM pg_trigger
                        WHERE tgname IN (
                            'api_invocations_immutable',
                            'api_invocation_results_immutable',
                            'api_invocation_exact_result'
                        )
                        ORDER BY tgname
                        """
                    )
                )
            ).all()
        assert [tuple(row) for row in trigger_states] == [
            ("api_invocation_exact_result", "O"),
            ("api_invocation_results_immutable", "O"),
            ("api_invocations_immutable", "O"),
        ]

        async with app.connect() as connection:
            with pytest.raises(DBAPIError, match="permission denied"):
                await connection.execute(text("SELECT * FROM sharing.api_invocations"))

        async with app.connect() as connection:
            with pytest.raises(DBAPIError, match="context is absent or mismatched"):
                await connection.execute(
                    text(
                        """
                        SELECT *
                        FROM sharing.prepare_api_invocation_v2(
                            CAST(:workspace_id AS uuid),
                            CAST(:subject_id AS uuid),
                            CAST(:grant_id AS uuid),
                            :key_hash,
                            'context-probe',
                            :issuer,
                            :client_id,
                            CAST(:product_id AS uuid),
                            CAST(:version_id AS uuid),
                            CAST(:graph_id AS uuid),
                            CAST(:release_id AS uuid),
                            :release_hash,
                            'NEIGHBORS',
                            'neighbors.query',
                            1,
                            :scope_hash,
                            :request_hash,
                            'NEIGHBORS_V1'
                        )
                        """
                    ),
                    {
                        "workspace_id": fixture.workspace_id,
                        "subject_id": fixture.consumer_id,
                        "grant_id": fixture.grant_id,
                        "key_hash": "a" * 64,
                        "issuer": fixture.consumer_issuer,
                        "client_id": fixture.consumer_client_id,
                        "product_id": fixture.product_id,
                        "version_id": fixture.product_version_id,
                        "graph_id": fixture.graph_id,
                        "release_id": fixture.release_id,
                        "release_hash": "b" * 64,
                        "scope_hash": "c" * 64,
                        "request_hash": "d" * 64,
                    },
                )

        sessions = async_sessionmaker(app, expire_on_commit=False)
        async with sessions() as session:
            await set_security_context(
                session,
                workspace_id=fixture.workspace_id,
                subject_id=fixture.consumer_id,
            )
            direct_oversize_status = await session.scalar(
                text(
                    """
                    SELECT status
                    FROM sharing.complete_api_invocation_v2(
                        CAST(:workspace_id AS uuid),
                        CAST(:subject_id AS uuid),
                        CAST(:grant_id AS uuid),
                        CAST(:invocation_id AS uuid),
                        :key_hash,
                        :legacy_key,
                        :issuer,
                        :client_id,
                        CAST(:product_id AS uuid),
                        CAST(:version_id AS uuid),
                        CAST(:graph_id AS uuid),
                        CAST(:release_id AS uuid),
                        :release_hash,
                        'NEIGHBORS',
                        'neighbors.query',
                        'direct-oversize',
                        1,
                        :scope_hash,
                        :request_hash,
                        'NEIGHBORS_V1',
                        :result_document,
                        'OBJECT_DATA',
                        CAST(:retention_policy_id AS uuid),
                        :retention_policy_hash
                    )
                    """
                ),
                {
                    "workspace_id": fixture.workspace_id,
                    "subject_id": fixture.consumer_id,
                    "grant_id": fixture.grant_id,
                    "invocation_id": uuid4(),
                    "key_hash": hashlib.sha256(b"direct-oversize-key").hexdigest(),
                    "legacy_key": "direct-oversize-key",
                    "issuer": fixture.consumer_issuer,
                    "client_id": fixture.consumer_client_id,
                    "product_id": fixture.product_id,
                    "version_id": fixture.product_version_id,
                    "graph_id": fixture.graph_id,
                    "release_id": fixture.release_id,
                    "release_hash": fixture.release_content_hash,
                    "scope_hash": "c" * 64,
                    "request_hash": "d" * 64,
                    # Deliberately invalid JSON: a parser-first function would raise instead
                    # of returning the bounded status.
                    "result_document": "x" * 1_048_577,
                    "retention_policy_id": fixture.retention_policy_id,
                    "retention_policy_hash": fixture.retention_policy_hash,
                },
            )
            await session.rollback()
        assert direct_oversize_status == "OVERSIZE"

        async with owner.connect() as connection:
            async with connection.begin():
                with pytest.raises(DBAPIError, match="evidence is immutable"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                UPDATE sharing.api_invocations
                                SET request_id = 'forged'
                                WHERE workspace_id = :workspace_id AND id = :invocation_id
                                """
                            ),
                            {
                                "workspace_id": fixture.workspace_id,
                                "invocation_id": result.authorization.invocation_id,
                            },
                        )
                with pytest.raises(DBAPIError, match="evidence is immutable"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                """
                                DELETE FROM sharing.api_invocation_results
                                WHERE workspace_id = :workspace_id
                                  AND invocation_id = :invocation_id
                                """
                            ),
                            {
                                "workspace_id": fixture.workspace_id,
                                "invocation_id": result.authorization.invocation_id,
                            },
                        )

        with pytest.raises(DBAPIError, match="has no exact result"):
            async with owner.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO sharing.api_invocations (
                            id, workspace_id, grant_id, invocation_key, evidence_kind,
                            actor_id, consumer_issuer, consumer_client_id, product_id,
                            product_version_id, graph_id, release_id,
                            release_content_hash, surface, requested_scope, request_id,
                            effective_classification, security_scope_hash, request_hash,
                            result_type, result_hash, result_size_bytes,
                            retention_data_class, retention_policy_id,
                            retention_policy_hash, retention_until,
                            audit_retention_policy_id, audit_retention_policy_hash,
                            audit_retention_until, occurred_at, completed_at, units
                        )
                        SELECT
                            :new_id, workspace_id, grant_id, :new_key, evidence_kind,
                            actor_id, consumer_issuer, consumer_client_id, product_id,
                            product_version_id, graph_id, release_id,
                            release_content_hash, surface, requested_scope,
                            'orphan-copy', effective_classification,
                            security_scope_hash, request_hash, result_type,
                            result_hash, result_size_bytes, retention_data_class,
                            retention_policy_id, retention_policy_hash, retention_until,
                            audit_retention_policy_id, audit_retention_policy_hash,
                            audit_retention_until, occurred_at, completed_at, units
                        FROM sharing.api_invocations
                        WHERE workspace_id = :workspace_id AND id = :invocation_id
                        """
                    ),
                    {
                        "new_id": uuid4(),
                        "new_key": hashlib.sha256(b"orphan-copy").hexdigest(),
                        "workspace_id": fixture.workspace_id,
                        "invocation_id": result.authorization.invocation_id,
                    },
                )
        assert await _counts(owner, fixture) == (1, 1, 1)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_current_service_membership_is_locked_until_invocation_commit() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        fixture = await _seed(owner)
        builder_entered = asyncio.Event()
        release_builder = asyncio.Event()

        async def build(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            builder_entered.set()
            await release_builder.wait()
            return _RESULT_DOCUMENT

        invocation = asyncio.create_task(
            _invoke(
                app,
                fixture,
                invocation_key="membership-linearization",
                request_id="membership-linearization",
                result_builder=build,
            )
        )
        await asyncio.wait_for(builder_entered.wait(), timeout=2)

        async def deactivate_membership() -> None:
            async with owner.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE iam.workspace_memberships
                        SET active = false, version = version + 1
                        WHERE workspace_id = :workspace_id
                          AND subject_id = :subject_id
                        """
                    ),
                    {
                        "workspace_id": fixture.workspace_id,
                        "subject_id": fixture.consumer_id,
                    },
                )

        deactivation = asyncio.create_task(deactivate_membership())
        await asyncio.sleep(0.1)
        assert deactivation.done() is False

        release_builder.set()
        result = await invocation
        await deactivation
        assert result.replayed is False
        assert await _counts(owner, fixture) == (1, 1, 1)

        with pytest.raises(ForbiddenError):
            await _invoke(
                app,
                fixture,
                invocation_key="membership-linearization",
                request_id="membership-after-revoke",
                result_builder=_fixed_result,
            )
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_concurrent_rpm_and_completed_monthly_usage_enforce_quota() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        rpm_fixture = await _seed(owner, requests_per_minute=1, monthly_quota=100)
        rpm_builder_calls = 0

        async def rpm_builder(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            nonlocal rpm_builder_calls
            rpm_builder_calls += 1
            await asyncio.sleep(0.05)
            return _RESULT_DOCUMENT

        rpm_outcomes = await asyncio.gather(
            _invoke(
                app,
                rpm_fixture,
                invocation_key="rpm-key-one-0001",
                request_id="rpm-one",
                result_builder=rpm_builder,
            ),
            _invoke(
                app,
                rpm_fixture,
                invocation_key="rpm-key-two-0001",
                request_id="rpm-two",
                result_builder=rpm_builder,
            ),
            return_exceptions=True,
        )
        assert rpm_builder_calls == 1
        assert sum(isinstance(value, InvocationResultRecord) for value in rpm_outcomes) == 1
        assert sum(isinstance(value, RateLimitError) for value in rpm_outcomes) == 1
        assert await _counts(owner, rpm_fixture) == (1, 1, 1)

        monthly_fixture = await _seed(owner, requests_per_minute=10, monthly_quota=1)
        monthly_builder_calls = 0

        async def monthly_builder(_: InvocationAuthorizationRecord) -> dict[str, Any]:
            nonlocal monthly_builder_calls
            monthly_builder_calls += 1
            await asyncio.sleep(0.05)
            return _RESULT_DOCUMENT

        monthly_outcomes = await asyncio.gather(
            _invoke(
                app,
                monthly_fixture,
                invocation_key="monthly-key-one-0001",
                request_id="monthly-one",
                result_builder=monthly_builder,
            ),
            _invoke(
                app,
                monthly_fixture,
                invocation_key="monthly-key-two-0001",
                request_id="monthly-two",
                result_builder=monthly_builder,
            ),
            return_exceptions=True,
        )
        assert monthly_builder_calls == 1
        assert sum(isinstance(value, InvocationResultRecord) for value in monthly_outcomes) == 1
        assert sum(isinstance(value, RateLimitError) for value in monthly_outcomes) == 1
        assert await _counts(owner, monthly_fixture) == (1, 1, 1)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_database_time_windows_and_legacy_usage_are_exact() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        expired_window = await _seed(owner, requests_per_minute=1, monthly_quota=100)
        live_window = await _seed(owner, requests_per_minute=1, monthly_quota=100)
        previous_month = await _seed(owner, requests_per_minute=10, monthly_quota=1)
        async with owner.begin() as connection:
            for fixture, key, age in (
                (expired_window, "legacy-window-0061", 61),
                (live_window, "legacy-window-0059", 59),
            ):
                await connection.execute(
                    text(
                        """
                        INSERT INTO sharing.api_invocations (
                            id, workspace_id, grant_id, invocation_key,
                            requested_scope, request_id, occurred_at, units,
                            evidence_kind
                        ) VALUES (
                            :id, :workspace_id, :grant_id, :invocation_key,
                            'neighbors.query', :request_id,
                            clock_timestamp() - make_interval(secs => :age), 1,
                            'LEGACY_USAGE_V1'
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": fixture.workspace_id,
                        "grant_id": fixture.grant_id,
                        "invocation_key": key,
                        "request_id": f"legacy-{age}",
                        "age": age,
                    },
                )
            await connection.execute(
                text(
                    """
                    INSERT INTO sharing.api_invocation_monthly_usage (
                        workspace_id, grant_id, month_start, units, updated_at
                    ) VALUES (
                        :workspace_id, :grant_id,
                        date_trunc('month', clock_timestamp() AT TIME ZONE 'UTC')
                            AT TIME ZONE 'UTC' - interval '1 month',
                        1, clock_timestamp()
                    )
                    """
                ),
                {
                    "workspace_id": previous_month.workspace_id,
                    "grant_id": previous_month.grant_id,
                },
            )

        assert (
            await _invoke(
                app,
                expired_window,
                invocation_key="new-after-sixty-one",
                request_id="after-sixty-one",
                result_builder=_fixed_result,
            )
        ).replayed is False
        with pytest.raises(ConflictError, match="legacy invocation"):
            await _invoke(
                app,
                live_window,
                invocation_key="legacy-window-0059",
                request_id="legacy-replay",
                result_builder=_fixed_result,
            )
        with pytest.raises(RateLimitError, match="per-minute"):
            await _invoke(
                app,
                live_window,
                invocation_key="new-inside-fifty-nine",
                request_id="inside-fifty-nine",
                result_builder=_fixed_result,
            )
        assert (
            await _invoke(
                app,
                previous_month,
                invocation_key="current-utc-month",
                request_id="current-utc-month",
                result_builder=_fixed_result,
            )
        ).replayed is False
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())


@pytest.mark.skipif(not _ENABLED, reason="isolated atomic Sharing PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_replay_denies_permission_product_and_retention_drift() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    try:
        permission_fixture = await _seed(owner)
        product_fixture = await _seed(owner)
        retention_fixture = await _seed(owner)
        for fixture, key in (
            (permission_fixture, "permission-drift-key"),
            (product_fixture, "product-drift-key-01"),
            (retention_fixture, "retention-drift-key"),
        ):
            await _invoke(
                app,
                fixture,
                invocation_key=key,
                request_id=f"first-{key}",
                result_builder=_fixed_result,
            )

        with pytest.raises(ConflictError, match="different or invalid result binding"):
            await _invoke(
                app,
                permission_fixture,
                invocation_key="permission-drift-key",
                request_id="permission-drift",
                security_scopes=frozenset(
                    {
                        "active:true",
                        "clearance:1",
                        "job_function:SERVICE_ACCOUNT",
                        "policy-generation:2",
                    }
                ),
                result_builder=_fixed_result,
            )

        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE sharing.api_products
                    SET current_version_id = NULL, version = version + 1
                    WHERE workspace_id = :workspace_id AND id = :product_id
                    """
                ),
                {
                    "workspace_id": product_fixture.workspace_id,
                    "product_id": product_fixture.product_id,
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE retention.policy_versions
                    SET state = 'SUPERSEDED', version = version + 1,
                        superseded_by = :actor_id,
                        supersede_reason = 'Atomic replay drift test',
                        supersede_policy_decision_id = :decision_id,
                        superseded_at = clock_timestamp()
                    WHERE workspace_id = :workspace_id AND id = :policy_id
                    """
                ),
                {
                    "workspace_id": retention_fixture.workspace_id,
                    "policy_id": retention_fixture.retention_policy_id,
                    "actor_id": retention_fixture.owner_id,
                    "decision_id": uuid4(),
                },
            )
        with pytest.raises(ForbiddenError):
            await _invoke(
                app,
                product_fixture,
                invocation_key="product-drift-key-01",
                request_id="product-drift",
                result_builder=_fixed_result,
            )
        with pytest.raises(ForbiddenError):
            await _invoke(
                app,
                retention_fixture,
                invocation_key="retention-drift-key",
                request_id="retention-drift",
                result_builder=_fixed_result,
            )
        assert await _counts(owner, permission_fixture) == (1, 1, 1)
        assert await _counts(owner, product_fixture) == (1, 1, 1)
        assert await _counts(owner, retention_fixture) == (1, 1, 1)
    finally:
        await asyncio.gather(owner.dispose(), app.dispose())
