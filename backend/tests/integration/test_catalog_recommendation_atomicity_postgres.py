from __future__ import annotations

import importlib.util
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from datariver.application.services.catalog_recommendations import CatalogRecommendationStore
from datariver.application.services.governance import GovernanceService
from datariver.domain.authz import Classification, EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ForbiddenError, canonical_json_hash
from datariver.domain.governance import ChangeItem, ChangeRequest, change_target_binding_hash
from datariver.infrastructure.db.catalog_recommendations import SqlCatalogRecommendationStore
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.infrastructure.db.rls import set_security_context

_DATABASE_URL = "DATARIVER_DQ02_TEST_DATABASE_URL"
_DATABASE_PASSWORD = "DATARIVER_DQ02_TEST_DATABASE_PASSWORD"
_CONFIRM = "DATARIVER_DQ02_TEST_CONFIRM_ISOLATED"
_ENABLED = bool(os.getenv(_DATABASE_URL)) and os.getenv(_CONFIRM) == "1"
_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic/versions/0101_catalog_metadata_recommendations.py"
)


class _AllowAuthorization:
    async def authorize(self, **_: object) -> None:
        return None


class _BoundTargetAuthorizer:
    async def authorize_targets(
        self,
        *,
        items: Sequence[ChangeItem],
        **_: object,
    ) -> tuple[ChangeItem, ...]:
        return tuple(items)


def _engine() -> AsyncEngine:
    return create_async_engine(
        os.environ[_DATABASE_URL],
        connect_args={"password": os.environ[_DATABASE_PASSWORD]},
        poolclass=NullPool,
    )


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("catalog_recommendations_0101_pg", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _seed(owner: AsyncEngine) -> dict[str, Any]:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "workspace_id": uuid4(),
        "actor_id": uuid4(),
        "asset_id": uuid4(),
        "vocabulary_id": uuid4(),
        "recommendation_id": uuid4(),
        "now": now,
    }
    values["urn"] = f"urn:li:dataset:dq02-{values['asset_id']}"
    values["urn_hash"] = canonical_json_hash(values["urn"])
    values["provider_ref"] = f"urn:li:tag:dq02-{values['vocabulary_id']}"
    async with owner.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version, created_at, updated_at)
                VALUES (:workspace_id, :slug, 'DQ-02 atomicity', 'ACTIVE', '{}'::jsonb,
                        1, :now, :now)
                """
            ),
            {**values, "slug": f"dq02-{values['workspace_id'].hex}"},
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.subjects
                    (id, issuer, external_subject, display_name, active, created_at, updated_at)
                VALUES (:actor_id, 'dq02-test', :external, 'DQ-02 actor', true, :now, :now)
                """
            ),
            {**values, "external": str(values["actor_id"])},
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.workspace_memberships
                    (workspace_id, subject_id, job_function, clearance, attributes,
                     active, version, created_at, updated_at)
                VALUES (:workspace_id, :actor_id, 'DATA_STEWARD', 1, '{}'::jsonb,
                        true, 1, :now, :now)
                """
            ),
            values,
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.assets_projection
                    (id, workspace_id, external_urn, urn_hash, asset_type, name,
                     platform, tags, glossary_terms, column_names, classification,
                     lifecycle, source_version, observed_at, projection_source)
                VALUES (:asset_id, :workspace_id, :urn, :urn_hash, 'DATASET', 'orders',
                        'postgres', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 1,
                        'ACTIVE', 'catalog-v1', :now, 'DATAHUB')
                """
            ),
            values,
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.vocabulary_entries
                    (id, workspace_id, kind, provider_ref, display_name, lifecycle,
                     source_version, version, observed_at, updated_at)
                VALUES (:vocabulary_id, :workspace_id, 'TAG', :provider_ref, 'governed-tag',
                        'ACTIVE', 'vocabulary-v1', 1, :now, :now)
                """
            ),
            values,
        )
        await connection.execute(
            text("SELECT set_config('app.subject_id', :subject, true)"),
            {"subject": str(values["actor_id"])},
        )
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace, true)"),
            {"workspace": str(values["workspace_id"])},
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.metadata_recommendations
                    (id, workspace_id, asset_id, field_path_key, vocabulary_id, kind,
                     source_version, provider_source_version, vocabulary_source_version,
                     aspect_name, aspect_source_version, aspect_content_hash,
                     target_binding_hash, input_context_hash, confidence, reason, evidence,
                     provider, model, prompt_version, rule_version, state, version, created_by)
                VALUES (:recommendation_id, :workspace_id, :asset_id, '', :vocabulary_id, 'TAG',
                        'catalog-v1', 'provider-v1', 'vocabulary-v1', 'globalTags',
                        'aspect-v1', :hash, :hash, :hash, 0.8, 'bounded reason',
                        '["bounded evidence"]'::jsonb, 'typed-provider', 'model-v1',
                        'prompt-v1', 'rule-v1', 'NEEDS_DECISION', 1, :actor_id)
                """
            ),
            {**values, "hash": "a" * 64},
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.metadata_recommendation_events
                    (id, workspace_id, recommendation_id, recommendation_version, decision,
                     actor_id, request_hash, occurred_at)
                VALUES (:recommendation_id, :workspace_id, :recommendation_id, 1,
                        'PREVIEWED', :actor_id, :hash, :now)
                """
            ),
            {**values, "hash": "b" * 64},
        )
    return values


def _subject(values: dict[str, Any]) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=values["actor_id"],
        workspace_id=values["workspace_id"],
        active=True,
        department_id=None,
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.INTERNAL,
    )


def _item(values: dict[str, Any]) -> ChangeItem:
    binding = change_target_binding_hash(
        target_ref=values["urn"],
        asset_id=values["asset_id"],
        asset_type="DATASET",
        system_id=None,
        domain_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
    )
    return ChangeItem(
        item_id=uuid4(),
        target_type="DATAHUB_ASPECT",
        target_ref=values["urn"],
        operation="UPSERT",
        after_document={"tags": [{"tag": values["provider_ref"]}]},
        aspect_name="globalTags",
        before_hash="a" * 64,
        after_hash="c" * 64,
        target_asset_id=values["asset_id"],
        target_asset_type="DATASET",
        target_classification=Classification.INTERNAL,
        target_lifecycle="ACTIVE",
        target_source_version="catalog-v1",
        target_observed_at=values["now"],
        target_binding_hash=binding,
        item_contract_hash="d" * 64,
    )


async def _counts(owner: AsyncEngine, values: dict[str, Any], number: str) -> tuple[Any, ...]:
    async with owner.connect() as connection:
        return tuple(
            (
                await connection.execute(
                    text(
                        """
                        SELECT recommendation.state, recommendation.version,
                          (SELECT count(*) FROM catalog.metadata_recommendation_events event
                           WHERE event.workspace_id = :workspace_id
                             AND event.recommendation_id = :recommendation_id),
                          (SELECT count(*) FROM governance.change_requests request
                           WHERE request.workspace_id = :workspace_id AND request.number = :number),
                          (SELECT count(*) FROM integration.idempotency_keys receipt
                           WHERE receipt.workspace_id = :workspace_id
                             AND receipt.operation = 'change_request.create')
                        FROM catalog.metadata_recommendations recommendation
                        WHERE recommendation.workspace_id = :workspace_id
                          AND recommendation.id = :recommendation_id
                        """
                    ),
                    {**values, "number": number},
                )
            ).one()
        )


async def _execute_atomic(
    owner: AsyncEngine,
    values: dict[str, Any],
    *,
    number: str,
    fail_after_finalize: bool,
) -> None:
    factory = async_sessionmaker(owner, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("SET ROLE datariver_app"))
        await set_security_context(
            session,
            workspace_id=values["workspace_id"],
            subject_id=values["actor_id"],
        )
        store: CatalogRecommendationStore = SqlCatalogRecommendationStore(session)
        governance = GovernanceService(
            lambda: SqlGovernanceUnitOfWork(factory, session=session),
            _AllowAuthorization(),  # type: ignore[arg-type]
            target_authorizer=_BoundTargetAuthorizer(),  # type: ignore[arg-type]
        )

        class TestRecommendationFinalizer:
            async def finalize_catalog_recommendation_approval(
                self,
                *,
                change_request: ChangeRequest,
            ) -> None:
                await store.finalize_approval(
                    workspace_id=values["workspace_id"],
                    recommendation_ids=(values["recommendation_id"],),
                    expected_versions=(1,),
                    actor_id=values["actor_id"],
                    idempotency_key="dq02-atomic-idempotency",
                    request_hash="e" * 64,
                    reason="reviewed",
                    change_request_id=change_request.change_request_id,
                )
                if fail_after_finalize:
                    raise RuntimeError("catalog finalize failed")

        await governance.create_catalog_recommendation_change_request(
            workspace_id=values["workspace_id"],
            number=number,
            request_type="CATALOG_METADATA_RECOMMENDATION",
            title="Atomic recommendation",
            description="reviewed",
            requester_id=values["actor_id"],
            items=[_item(values)],
            subject=_subject(values),
            classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(values["now"]),
            request_id="dq02-atomic",
            idempotency_key="dq02-atomic-idempotency",
            request_hash="e" * 64,
            require_raw_operator_gate=False,
            recommendation_finalizer=TestRecommendationFinalizer(),
        )


@pytest.mark.skipif(not _ENABLED, reason="isolated DQ-02 PostgreSQL is not configured")
@pytest.mark.asyncio
async def test_catalog_finalize_failure_rolls_back_cr_idempotency_and_decision_event() -> None:
    owner = _engine()
    values = await _seed(owner)
    number = f"DQ02-FINALIZE-{uuid4().hex}"
    try:
        with pytest.raises(RuntimeError, match="catalog finalize failed"):
            await _execute_atomic(owner, values, number=number, fail_after_finalize=True)
        assert await _counts(owner, values, number) == ("NEEDS_DECISION", 1, 1, 0, 0)
    finally:
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated DQ-02 PostgreSQL is not configured")
@pytest.mark.asyncio
async def test_deferred_cr_commit_failure_rolls_back_catalog_decision_and_event() -> None:
    owner = _engine()
    values = await _seed(owner)
    number = f"DQ02-COMMIT-{uuid4().hex}"
    try:
        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE FUNCTION governance.dq02_test_reject_cr_commit() RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'forced deferred CR failure'; END
                    $$
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE CONSTRAINT TRIGGER dq02_test_reject_cr_commit
                    AFTER INSERT ON governance.change_requests DEFERRABLE INITIALLY DEFERRED
                    FOR EACH ROW EXECUTE FUNCTION governance.dq02_test_reject_cr_commit()
                    """
                )
            )
        with pytest.raises(DBAPIError, match="forced deferred CR failure"):
            await _execute_atomic(owner, values, number=number, fail_after_finalize=False)
        assert await _counts(owner, values, number) == ("NEEDS_DECISION", 1, 1, 0, 0)
    finally:
        async with owner.begin() as connection:
            await connection.execute(
                text(
                    """
                    DROP TRIGGER IF EXISTS dq02_test_reject_cr_commit
                      ON governance.change_requests
                    """
                )
            )
            await connection.execute(
                text("DROP FUNCTION IF EXISTS governance.dq02_test_reject_cr_commit()")
            )
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated DQ-02 PostgreSQL is not configured")
@pytest.mark.asyncio
async def test_completed_approval_replay_is_subject_bound_and_not_duplicated() -> None:
    owner = _engine()
    values = await _seed(owner)
    number = f"DQ02-SUCCESS-{uuid4().hex}"
    factory = async_sessionmaker(owner, expire_on_commit=False)
    try:
        await _execute_atomic(owner, values, number=number, fail_after_finalize=False)
        assert await _counts(owner, values, number) == ("APPROVED", 2, 2, 1, 1)

        async with factory() as session:
            await session.execute(text("SET ROLE datariver_app"))
            await set_security_context(
                session,
                workspace_id=values["workspace_id"],
                subject_id=values["actor_id"],
            )
            store = SqlCatalogRecommendationStore(session)
            replay = await store.get_approval_replay(
                workspace_id=values["workspace_id"],
                subject_id=values["actor_id"],
                recommendation_ids=(values["recommendation_id"],),
                idempotency_key="dq02-atomic-idempotency",
                request_hash="e" * 64,
            )
            assert replay is not None
            assert replay.completed_change_request_id is not None
            with pytest.raises(ForbiddenError, match="another subject"):
                await store.get_approval_replay(
                    workspace_id=values["workspace_id"],
                    subject_id=uuid4(),
                    recommendation_ids=(values["recommendation_id"],),
                    idempotency_key="dq02-atomic-idempotency",
                    request_hash="e" * 64,
                )

        assert await _counts(owner, values, number) == ("APPROVED", 2, 2, 1, 1)
    finally:
        await owner.dispose()


@pytest.mark.skipif(not _ENABLED, reason="isolated DQ-02 PostgreSQL is not configured")
@pytest.mark.asyncio
async def test_complete_migration_shape_and_workspace_rls_are_enforced() -> None:
    owner = _engine()
    values = await _seed(owner)
    factory = async_sessionmaker(owner, expire_on_commit=False)
    try:
        migration = _load_migration()
        async with owner.connect() as connection:
            await connection.run_sync(migration._assert_complete_state)

        async with factory() as session:
            await session.execute(text("SET ROLE datariver_app"))
            await set_security_context(
                session,
                workspace_id=values["workspace_id"],
                subject_id=values["actor_id"],
            )
            visible = await session.scalar(
                text(
                    """
                    SELECT count(*) FROM catalog.metadata_recommendations
                    WHERE id = :recommendation_id
                    """
                ),
                values,
            )
            assert visible == 1

        async with factory() as session:
            await session.execute(text("SET ROLE datariver_app"))
            await set_security_context(
                session,
                workspace_id=uuid4(),
                subject_id=values["actor_id"],
            )
            hidden = await session.scalar(
                text(
                    """
                    SELECT count(*) FROM catalog.metadata_recommendations
                    WHERE id = :recommendation_id
                    """
                ),
                values,
            )
            assert hidden == 0
    finally:
        await owner.dispose()
