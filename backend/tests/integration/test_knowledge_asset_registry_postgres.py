from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from datariver.domain.common import ValidationError
from datariver.infrastructure.db.knowledge_assets import SqlKnowledgeAssetRepository
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.secrets import SecretResolver

_OWNER_URL = "DATARIVER_KNOWLEDGE_SOURCE_TEST_OWNER_DATABASE_URL"
_OWNER_SECRET = "DATARIVER_KNOWLEDGE_SOURCE_TEST_OWNER_SECRET_REF"
_APP_URL = "DATARIVER_KNOWLEDGE_SOURCE_TEST_APP_DATABASE_URL"
_APP_SECRET = "DATARIVER_KNOWLEDGE_SOURCE_TEST_APP_SECRET_REF"
_CONFIRM = "DATARIVER_KNOWLEDGE_SOURCE_TEST_CONFIRM_ISOLATED"
_ENABLED = (
    all(os.getenv(name) for name in (_OWNER_URL, _OWNER_SECRET, _APP_URL, _APP_SECRET))
    and os.getenv(_CONFIRM) == "1"
)


def _engine(url_name: str, secret_name: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[url_name],
        connect_args={
            "password": SecretResolver().resolve(os.environ[secret_name]),
            "server_settings": {"application_name": f"datariver-knowledge-registry-{uuid4().hex}"},
        },
    )


async def _seed(owner: AsyncEngine) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    (
        workspace_id,
        other_workspace_id,
        actor_id,
        allowed_domain_id,
        denied_domain_id,
        public_domain_id,
        other_workspace_domain_id,
    ) = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC)
    attributes = json.dumps(
        {
            "groups": ["data-stewards"],
            "allowed_actions": ["kg.read"],
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [str(allowed_domain_id)],
        }
    )
    async with owner.begin() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            REQUIRED_DATABASE_REVISION
        )
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, created_at, updated_at, version)
                VALUES
                    (:workspace_id, :slug, 'Knowledge registry test', 'ACTIVE',
                     '{}'::jsonb, :now, :now, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "slug": f"knowledge-registry-{workspace_id.hex}",
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.subjects
                    (id, issuer, external_subject, display_name, active, created_at, updated_at)
                VALUES
                    (:actor_id, 'knowledge-registry-test', :external_subject,
                     'Registry reader', true, :now, :now)
                """
            ),
            {"actor_id": actor_id, "external_subject": str(actor_id), "now": now},
        )
        await connection.execute(
            text(
                """
                INSERT INTO iam.workspace_memberships
                    (workspace_id, subject_id, job_function, clearance, attributes,
                     active, access_expires_at, created_at, updated_at, version)
                VALUES
                    (:workspace_id, :actor_id, 'DATA_STEWARD', 1,
                     CAST(:attributes AS jsonb), true, :expires_at, :now, :now, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "attributes": attributes,
                "expires_at": now + timedelta(days=30),
                "now": now,
            },
        )
        for domain_id, name in (
            (allowed_domain_id, "Allowed domain"),
            (denied_domain_id, "Denied domain"),
            (public_domain_id, "Public domain"),
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO catalog.vocabulary_entries
                        (id, workspace_id, kind, provider_ref, display_name, lifecycle,
                         source_version, observed_at, created_by, version, updated_at)
                    VALUES
                        (:domain_id, :workspace_id, 'DOMAIN', :provider_ref, :name, 'ACTIVE',
                         'registry-test-v1', :now, :actor_id, 1, :now)
                    """
                ),
                {
                    "domain_id": domain_id,
                    "workspace_id": workspace_id,
                    "provider_ref": f"urn:li:domain:registry-{domain_id.hex}",
                    "name": name,
                    "actor_id": actor_id,
                    "now": now,
                },
            )

        graphs = (
            (uuid4(), "alpha-finance", "Alpha finance", "PUBLISHED", 1, allowed_domain_id),
            (uuid4(), "beta-finance", "Beta finance", "PUBLISHED", 1, allowed_domain_id),
            (uuid4(), "secret-finance", "Secret finance", "PUBLISHED", 2, allowed_domain_id),
            (uuid4(), "archived-finance", "Archived finance", "ARCHIVED", 1, allowed_domain_id),
            (uuid4(), "disallowed-only", "Disallowed only", "PUBLISHED", 1, denied_domain_id),
            (uuid4(), "public-reference", "Public reference", "PUBLISHED", 0, public_domain_id),
        )
        for graph_id, slug, name, status, classification, domain_id in graphs:
            archived = status == "ARCHIVED"
            await connection.execute(
                text(
                    """
                    INSERT INTO knowledge.graphs
                        (id, workspace_id, slug, name, graph_type, status,
                         active_release_id, active_studio_release_id, classification,
                         domain_ref_id, domain_ref_kind, domain_source_version,
                         created_by, updated_by, archived_at, archived_by,
                         created_at, updated_at, version)
                    VALUES
                        (:graph_id, :workspace_id, :slug, :name, 'DOMAIN', :status,
                         NULL, NULL, :classification, :domain_id, 'DOMAIN', 'registry-test-v1',
                         :actor_id, :actor_id, :archived_at, :archived_by,
                         :now, :now, 1)
                    """
                ),
                {
                    "graph_id": graph_id,
                    "workspace_id": workspace_id,
                    "slug": slug,
                    "name": name,
                    "status": status,
                    "classification": classification,
                    "domain_id": domain_id,
                    "actor_id": actor_id,
                    "archived_at": now if archived else None,
                    "archived_by": actor_id if archived else None,
                    "now": now,
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, created_at, updated_at, version)
                VALUES
                    (:workspace_id, :slug, 'Other registry workspace', 'ACTIVE',
                     '{}'::jsonb, :now, :now, 1)
                """
            ),
            {
                "workspace_id": other_workspace_id,
                "slug": f"other-registry-{other_workspace_id.hex}",
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO catalog.vocabulary_entries
                    (id, workspace_id, kind, provider_ref, display_name, lifecycle,
                     source_version, observed_at, created_by, version, updated_at)
                VALUES
                    (:domain_id, :workspace_id, 'DOMAIN', :provider_ref,
                     'Other workspace domain', 'ACTIVE', 'registry-test-v1',
                     :now, NULL, 1, :now)
                """
            ),
            {
                "domain_id": other_workspace_domain_id,
                "workspace_id": other_workspace_id,
                "provider_ref": f"urn:li:domain:registry-{other_workspace_domain_id.hex}",
                "now": now,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO knowledge.graphs
                    (id, workspace_id, slug, name, graph_type, status,
                     active_release_id, active_studio_release_id, classification,
                     domain_ref_id, domain_ref_kind, domain_source_version,
                     created_by, updated_by, archived_at, archived_by,
                     created_at, updated_at, version)
                VALUES
                    (:graph_id, :workspace_id, :slug, 'Other workspace graph', 'DOMAIN',
                     'PUBLISHED', NULL, NULL, 0, :domain_id, 'DOMAIN', 'registry-test-v1',
                     NULL, NULL, NULL, NULL, :now, :now, 1)
                """
            ),
            {
                "graph_id": uuid4(),
                "workspace_id": other_workspace_id,
                "slug": f"other-workspace-{other_workspace_id.hex}",
                "domain_id": other_workspace_domain_id,
                "now": now,
            },
        )
    return (
        workspace_id,
        other_workspace_id,
        actor_id,
        allowed_domain_id,
        denied_domain_id,
        public_domain_id,
        other_workspace_domain_id,
    )


async def _cleanup(
    owner: AsyncEngine,
    *,
    workspace_id: UUID,
    other_workspace_id: UUID,
    actor_id: UUID,
) -> None:
    async with owner.begin() as connection:
        await connection.execute(
            text("DELETE FROM knowledge.graphs WHERE workspace_id IN (:first, :second)"),
            {"first": workspace_id, "second": other_workspace_id},
        )
        await connection.execute(
            text("DELETE FROM catalog.vocabulary_entries WHERE workspace_id IN (:first, :second)"),
            {"first": workspace_id, "second": other_workspace_id},
        )
        await connection.execute(
            text("DELETE FROM iam.workspace_memberships WHERE workspace_id = :workspace_id"),
            {"workspace_id": workspace_id},
        )
        await connection.execute(
            text("DELETE FROM iam.subjects WHERE id = :actor_id"),
            {"actor_id": actor_id},
        )
        await connection.execute(
            text("DELETE FROM platform.workspaces WHERE id IN (:first, :second)"),
            {"first": workspace_id, "second": other_workspace_id},
        )


@pytest.mark.skipif(not _ENABLED, reason="isolated Knowledge registry PostgreSQL gate not enabled")
@pytest.mark.asyncio
async def test_registry_domain_filter_intersects_exact_domain_abac_query_and_cursor() -> None:
    owner = _engine(_OWNER_URL, _OWNER_SECRET)
    app = _engine(_APP_URL, _APP_SECRET)
    workspace_id: UUID | None = None
    other_workspace_id: UUID | None = None
    actor_id: UUID | None = None
    try:
        (
            workspace_id,
            other_workspace_id,
            actor_id,
            allowed_domain_id,
            denied_domain_id,
            public_domain_id,
            other_workspace_domain_id,
        ) = await _seed(owner)
        sessions = async_sessionmaker(app, expire_on_commit=False)
        async with sessions() as session:
            await set_security_context(
                session,
                workspace_id=workspace_id,
                subject_id=actor_id,
            )
            repository = SqlKnowledgeAssetRepository(session)
            page = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="",
                domain_id=allowed_domain_id,
                sort="NAME_ASC",
                cursor=None,
                limit=1,
            )
            assert [item.name for item in page.items] == ["Alpha finance"]
            assert page.next_cursor is not None

            second = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="",
                domain_id=allowed_domain_id,
                sort="NAME_ASC",
                cursor=page.next_cursor,
                limit=1,
            )
            assert [item.name for item in second.items] == ["Beta finance"]
            assert second.next_cursor is None

            with pytest.raises(ValidationError, match="page cursor is invalid"):
                await repository.list_assets(
                    workspace_id=workspace_id,
                    clearance=1,
                    allowed_domain_ids=frozenset({allowed_domain_id}),
                    query="",
                    domain_id=denied_domain_id,
                    sort="NAME_ASC",
                    cursor=page.next_cursor,
                    limit=1,
                )

            denied = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="",
                domain_id=denied_domain_id,
                sort="NAME_ASC",
                cursor=None,
                limit=25,
            )
            assert denied.items == ()

            public = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="",
                domain_id=public_domain_id,
                sort="NAME_ASC",
                cursor=None,
                limit=25,
            )
            assert [item.name for item in public.items] == ["Public reference"]

            query_and_domain = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="disallowed only",
                domain_id=allowed_domain_id,
                sort="NAME_ASC",
                cursor=None,
                limit=25,
            )
            assert query_and_domain.items == ()

            unknown = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="",
                domain_id=uuid4(),
                sort="NAME_ASC",
                cursor=None,
                limit=25,
            )
            assert unknown.items == ()

            other_workspace = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="",
                domain_id=other_workspace_domain_id,
                sort="NAME_ASC",
                cursor=None,
                limit=25,
            )
            assert other_workspace.items == ()

            unfiltered = await repository.list_assets(
                workspace_id=workspace_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
                query="",
                domain_id=None,
                sort="NAME_ASC",
                cursor=None,
                limit=100,
            )
            assert [item.name for item in unfiltered.items] == [
                "Alpha finance",
                "Beta finance",
                "Public reference",
            ]
    finally:
        if workspace_id is not None and other_workspace_id is not None and actor_id is not None:
            await _cleanup(
                owner,
                workspace_id=workspace_id,
                other_workspace_id=other_workspace_id,
                actor_id=actor_id,
            )
        await owner.dispose()
        await app.dispose()
