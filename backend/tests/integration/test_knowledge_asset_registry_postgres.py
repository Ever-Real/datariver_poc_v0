from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from datariver.domain.common import ValidationError
from datariver.infrastructure.db.knowledge_assets import SqlKnowledgeAssetRepository
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.knowledge import GraphModel, OntologyVersionModel
from datariver.infrastructure.db.models.knowledge_studio import (
    ABoxBindingVersionModel,
    ABoxMappingRuleVersionModel,
    KnowledgeSourceReferenceModel,
    KnowledgeStudioDraftModel,
    KnowledgeStudioPreflightCheckModel,
    KnowledgeStudioReleaseModel,
    OntologyElementModel,
)
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


async def _seed_operational_detail(
    connection: AsyncConnection,
    *,
    workspace_id: UUID,
    graph_id: UUID,
    domain_id: UUID,
    author_id: UUID,
    reviewer_id: UUID,
    now: datetime,
) -> None:
    catalog_asset_id = uuid4()
    ontology_id = uuid4()
    draft_id = uuid4()
    preflight_id = uuid4()
    studio_release_id = uuid4()
    class_element_id = uuid4()
    property_element_id = uuid4()
    source_reference_id = uuid4()
    binding_id = uuid4()
    contract_hash = "3" * 64

    await connection.execute(
        insert(AssetProjectionModel),
        {
            "id": catalog_asset_id,
            "workspace_id": workspace_id,
            "external_urn": f"urn:li:dataset:registry-coverage-{catalog_asset_id.hex}",
            "urn_hash": "1" * 64,
            "asset_type": "DATASET",
            "name": "crm_customer",
            "platform": "postgres",
            "database_name": "crm",
            "schema_name": "public",
            "tags": [],
            "glossary_terms": [],
            "column_names": ["customer_id", "customer_name"],
            "domain_id": domain_id,
            "classification": 1,
            "lifecycle": "ACTIVE",
            "source_version": "catalog-v3",
            "observed_at": now,
            "projection_source": "DATAHUB",
            "created_at": now,
            "updated_at": now,
        },
    )
    await connection.execute(
        insert(OntologyVersionModel),
        {
            "id": ontology_id,
            "workspace_id": workspace_id,
            "graph_id": graph_id,
            "version": "ks-registry-coverage",
            "schema_document": {},
            "checksum": "2" * 64,
            "status": "PUBLISHED",
            "schema_contract_version": "KNOWLEDGE_STUDIO_TBOX_V1",
            "created_by": author_id,
            "created_at": now,
            "updated_at": now,
        },
    )
    await connection.execute(
        insert(KnowledgeStudioDraftModel),
        {
            "id": draft_id,
            "workspace_id": workspace_id,
            "author_id": author_id,
            "kind": "CREATE",
            "state": "REVIEW",
            "current_step": "ABOX",
            "name": "Registry coverage graph",
            "endpoint_alias": "registry_coverage",
            "endpoint_aliases": ["registry_coverage"],
            "domain_ref_id": domain_id,
            "domain_ref_kind": "DOMAIN",
            "domain_source_version": "registry-test-v1",
            "classification": 1,
            "review_requested_at": now,
            "last_autosaved_at": now,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        },
    )
    await connection.execute(
        insert(KnowledgeStudioPreflightCheckModel),
        {
            "id": preflight_id,
            "workspace_id": workspace_id,
            "draft_id": draft_id,
            "draft_version": 1,
            "contract_hash": contract_hash,
            "status": "PASS",
            "valid": True,
            "validation_contract_version": "KNOWLEDGE_STUDIO_PREFLIGHT_V1",
            "evidence_document": [],
            "evidence_hash": "6" * 64,
            "checked_by": reviewer_id,
            "checked_at": now,
        },
    )
    await connection.execute(
        insert(OntologyElementModel),
        [
            {
                "id": class_element_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "ontology_version_id": ontology_id,
                "stable_element_id": "class.customer",
                "kind": "CLASS",
                "canonical_name": "Customer",
                "display_name": "고객",
                "ordinal": 0,
                "element_document": {"parent_stable_element_id": None},
                "element_hash": "7" * 64,
            },
            {
                "id": property_element_id,
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "ontology_version_id": ontology_id,
                "stable_element_id": "property.customer.name",
                "kind": "PROPERTY",
                "canonical_name": "name",
                "display_name": "고객명",
                "ordinal": 1,
                "element_document": {
                    "parent_stable_element_id": "class.customer",
                    "data_type": "STRING",
                },
                "element_hash": "8" * 64,
            },
        ],
    )
    await connection.execute(
        insert(KnowledgeStudioReleaseModel),
        {
            "id": studio_release_id,
            "workspace_id": workspace_id,
            "graph_id": graph_id,
            "source_draft_id": draft_id,
            "source_draft_version": 1,
            "release_no": 1,
            "state": "ACTIVE",
            "ontology_version_id": ontology_id,
            "preflight_check_id": preflight_id,
            "contract_version": "KNOWLEDGE_STUDIO_RELEASE_V1",
            "contract_hash": contract_hash,
            "tbox_hash": "4" * 64,
            "abox_hash": "5" * 64,
            "author_id": author_id,
            "reviewed_by": reviewer_id,
            "review_reason": "Registry coverage fixture",
            "published_by": reviewer_id,
            "published_at": now,
        },
    )
    await connection.execute(
        insert(KnowledgeSourceReferenceModel),
        {
            "id": source_reference_id,
            "workspace_id": workspace_id,
            "kind": "CATALOG_DATASET",
            "catalog_asset_id": catalog_asset_id,
            "source_version": "catalog-v3",
            "projection_source_version": "projection-v3",
            "classification": 1,
            "selection_document": {"source_name": "crm.customer"},
            "selection_hash": "a" * 64,
            "created_by": author_id,
            "created_at": now,
        },
    )
    await connection.execute(
        insert(ABoxBindingVersionModel),
        {
            "id": binding_id,
            "workspace_id": workspace_id,
            "graph_id": graph_id,
            "studio_release_id": studio_release_id,
            "ontology_version_id": ontology_id,
            "target_ontology_element_id": class_element_id,
            "target_stable_element_id": "class.customer",
            "source_reference_id": source_reference_id,
            "ordinal": 0,
            "mapping_hash": "9" * 64,
            "created_by": author_id,
            "created_at": now,
        },
    )
    await connection.execute(
        insert(ABoxMappingRuleVersionModel),
        [
            {
                "id": uuid4(),
                "workspace_id": workspace_id,
                "studio_release_id": studio_release_id,
                "binding_version_id": binding_id,
                "ontology_version_id": ontology_id,
                "target_ontology_element_id": class_element_id,
                "ordinal": 0,
                "method": "SUBJECT_ID",
                "source_field_path": "customer_id",
                "target_stable_element_id": "class.customer",
                "transform_id": "IDENTITY",
                "transform_version": "1",
            },
            {
                "id": uuid4(),
                "workspace_id": workspace_id,
                "studio_release_id": studio_release_id,
                "binding_version_id": binding_id,
                "ontology_version_id": ontology_id,
                "target_ontology_element_id": property_element_id,
                "ordinal": 1,
                "method": "PROPERTY",
                "source_field_path": "customer_name",
                "target_stable_element_id": "property.customer.name",
                "transform_id": "IDENTITY",
                "transform_version": "1",
            },
        ],
    )
    await connection.execute(
        update(GraphModel)
        .where(GraphModel.workspace_id == workspace_id, GraphModel.id == graph_id)
        .values(
            active_studio_release_id=studio_release_id,
            updated_by=reviewer_id,
            updated_at=now,
        )
    )
    await connection.execute(
        update(KnowledgeStudioDraftModel)
        .where(
            KnowledgeStudioDraftModel.workspace_id == workspace_id,
            KnowledgeStudioDraftModel.id == draft_id,
        )
        .values(
            state="PUBLISHED",
            submitted_preflight_check_id=preflight_id,
            reviewed_by=reviewer_id,
            reviewed_at=now,
            review_reason="Registry coverage fixture",
            published_at=now,
            published_by=reviewer_id,
            materialized_graph_id=graph_id,
            materialized_ontology_version_id=ontology_id,
            published_studio_release_id=studio_release_id,
            updated_at=now,
            version=2,
        )
    )


async def _seed(
    owner: AsyncEngine,
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    (
        workspace_id,
        other_workspace_id,
        actor_id,
        reviewer_id,
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
                INSERT INTO iam.subjects
                    (id, issuer, external_subject, display_name, active, created_at, updated_at)
                VALUES
                    (:reviewer_id, 'knowledge-registry-test', :external_subject,
                     'Registry reviewer', true, :now, :now)
                """
            ),
            {
                "reviewer_id": reviewer_id,
                "external_subject": str(reviewer_id),
                "now": now,
            },
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
        await connection.execute(
            text(
                """
                INSERT INTO iam.workspace_memberships
                    (workspace_id, subject_id, job_function, clearance, attributes,
                     active, access_expires_at, created_at, updated_at, version)
                VALUES
                    (:workspace_id, :reviewer_id, 'DOMAIN_STEWARD', 1,
                     CAST(:attributes AS jsonb), true, :expires_at, :now, :now, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "reviewer_id": reviewer_id,
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

        allowed_graph_id = uuid4()
        denied_graph_id = uuid4()
        graphs = (
            (
                allowed_graph_id,
                "alpha-finance",
                "Alpha finance",
                "PUBLISHED",
                1,
                allowed_domain_id,
            ),
            (uuid4(), "beta-finance", "Beta finance", "PUBLISHED", 1, allowed_domain_id),
            (uuid4(), "secret-finance", "Secret finance", "PUBLISHED", 2, allowed_domain_id),
            (uuid4(), "archived-finance", "Archived finance", "ARCHIVED", 1, allowed_domain_id),
            (
                denied_graph_id,
                "disallowed-only",
                "Disallowed only",
                "PUBLISHED",
                1,
                denied_domain_id,
            ),
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
        await _seed_operational_detail(
            connection,
            workspace_id=workspace_id,
            graph_id=allowed_graph_id,
            domain_id=allowed_domain_id,
            author_id=actor_id,
            reviewer_id=reviewer_id,
            now=now,
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
        reviewer_id,
        allowed_domain_id,
        denied_domain_id,
        public_domain_id,
        other_workspace_domain_id,
        allowed_graph_id,
        denied_graph_id,
    )


async def _cleanup(
    owner: AsyncEngine,
    *,
    workspace_id: UUID,
    other_workspace_id: UUID,
    actor_id: UUID,
    reviewer_id: UUID,
) -> None:
    async with owner.begin() as connection:
        for statement in (
            text(
                "DELETE FROM knowledge.abox_mapping_rule_versions "
                "WHERE workspace_id = :workspace_id"
            ),
            text("DELETE FROM knowledge.abox_binding_versions WHERE workspace_id = :workspace_id"),
        ):
            await connection.execute(
                statement,
                {"workspace_id": workspace_id},
            )
        await connection.execute(
            text(
                "UPDATE knowledge.graphs SET active_studio_release_id = NULL "
                "WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": workspace_id},
        )
        await connection.execute(
            text(
                """
                UPDATE knowledge.studio_drafts
                SET state = 'REVIEW', submitted_preflight_check_id = NULL,
                    reviewed_by = NULL, reviewed_at = NULL, review_reason = NULL,
                    published_at = NULL, published_by = NULL,
                    materialized_graph_id = NULL,
                    materialized_ontology_version_id = NULL,
                    published_studio_release_id = NULL,
                    version = version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE workspace_id = :workspace_id
                """
            ),
            {"workspace_id": workspace_id},
        )
        for statement in (
            text("DELETE FROM knowledge.studio_releases WHERE workspace_id = :workspace_id"),
            text("DELETE FROM knowledge.ontology_elements WHERE workspace_id = :workspace_id"),
            text(
                "DELETE FROM knowledge.studio_preflight_checks WHERE workspace_id = :workspace_id"
            ),
            text("DELETE FROM knowledge.studio_drafts WHERE workspace_id = :workspace_id"),
            text("DELETE FROM knowledge.ontology_versions WHERE workspace_id = :workspace_id"),
            text("DELETE FROM knowledge.source_references WHERE workspace_id = :workspace_id"),
            text("DELETE FROM catalog.assets_projection WHERE workspace_id = :workspace_id"),
        ):
            await connection.execute(
                statement,
                {"workspace_id": workspace_id},
            )
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
            text("DELETE FROM iam.subjects WHERE id IN (:actor_id, :reviewer_id)"),
            {"actor_id": actor_id, "reviewer_id": reviewer_id},
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
    reviewer_id: UUID | None = None
    try:
        (
            workspace_id,
            other_workspace_id,
            actor_id,
            reviewer_id,
            allowed_domain_id,
            denied_domain_id,
            public_domain_id,
            other_workspace_domain_id,
            allowed_graph_id,
            denied_graph_id,
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

            detail = await repository.get_operational_detail(
                workspace_id=workspace_id,
                graph_id=allowed_graph_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
            )
            assert detail is not None
            assert [
                (
                    element.stable_element_id,
                    element.kind,
                    element.parent_stable_element_id,
                    element.data_type,
                )
                for element in detail.schema_elements
            ] == [
                ("class.customer", "CLASS", None, None),
                ("property.customer.name", "PROPERTY", "class.customer", "STRING"),
            ]
            assert len(detail.bindings) == 1
            binding = detail.bindings[0]
            assert binding.target_stable_element_id == "class.customer"
            assert binding.source_name == "crm.customer"
            assert binding.source_version == "catalog-v3"
            assert binding.mapping_rule_count == 2
            assert [
                (rule.method, rule.source_field_path, rule.target_stable_element_id)
                for rule in binding.mapping_rules
            ] == [
                ("SUBJECT_ID", "customer_id", "class.customer"),
                ("PROPERTY", "customer_name", "property.customer.name"),
            ]

            denied_detail = await repository.get_operational_detail(
                workspace_id=workspace_id,
                graph_id=denied_graph_id,
                clearance=1,
                allowed_domain_ids=frozenset({allowed_domain_id}),
            )
            assert denied_detail is None
    finally:
        if (
            workspace_id is not None
            and other_workspace_id is not None
            and actor_id is not None
            and reviewer_id is not None
        ):
            await _cleanup(
                owner,
                workspace_id=workspace_id,
                other_workspace_id=other_workspace_id,
                actor_id=actor_id,
                reviewer_id=reviewer_id,
            )
        await owner.dispose()
        await app.dispose()
