from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.config import Settings, get_settings
from datariver.domain.authz import Action, Classification
from datariver.domain.capability_catalog import DEFAULT_HUMAN_ADMIN_ACTIONS
from datariver.domain.common import DomainEvent, canonical_json_hash, utc_now
from datariver.domain.knowledge import (
    GraphEdge,
    GraphNode,
    GraphRelease,
    GraphSnapshot,
    Ontology,
    Provenance,
)
from datariver.domain.membership_renewal import add_calendar_months
from datariver.infrastructure.db.catalog import advance_catalog_projection_version
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.integration import OutboxEventModel, SeedRunModel
from datariver.infrastructure.db.models.knowledge import (
    ChangeOperationModel,
    ChangeSetModel,
    GraphModel,
    OntologyVersionModel,
    ProjectionDeploymentModel,
    ReleaseEdgeModel,
    ReleaseModel,
    ReleaseNodeModel,
)
from datariver.infrastructure.db.models.platform import (
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.secrets import SecretResolver
from datariver.seed.semiconductor import (
    PACK_VERSION,
    SEED_NAMESPACE,
    SemiconductorPack,
    build_pack,
    seed_root,
    stable_id,
)

WORKSPACE_ID = stable_id("workspace:semiconductor-analysis")
SUBJECT_ID = stable_id("subject:local-datariver-admin")
AIRFLOW_SUBJECT_ID = stable_id("subject:local-datariver-airflow")
GRAPH_ID = stable_id("graph:semiconductor-value-chain")
ONTOLOGY_ID = stable_id("ontology:semiconductor-value-chain:1.0.0")
RELEASE_ID = stable_id("release:semiconductor-value-chain:1")
CHANGESET_ID = stable_id("changeset:semiconductor-value-chain:1")
PROJECTION_DEPLOYMENT_ID = stable_id("projection:semiconductor-value-chain:postgres:1")
SEED_RUN_ID = stable_id("seed-run:semiconductor:1.0.0")
REVIEWER_SUBJECT_ID = stable_id("subject:local-datariver-seed-reviewer")
SYSTEM_ID = stable_id("system:semiconductor-reference")
DOMAIN_ID = stable_id("domain:semiconductor-value-chain")
LOCAL_KEYCLOAK_SUBJECT = "00000000-0000-4000-8000-000000000001"
LOCAL_KEYCLOAK_AIRFLOW_SUBJECT = "00000000-0000-4000-8000-000000000002"
LOCAL_KEYCLOAK_REVIEWER_SUBJECT = "00000000-0000-4000-8000-000000000003"
LOCAL_KEYCLOAK_VIEWER_SUBJECT = "00000000-0000-4000-8000-000000000004"
VIEWER_SUBJECT_ID = stable_id("subject:local-datariver-seed-viewer")
ADMINISTRATOR_ACTIONS = tuple(
    action.value for action in Action if action in DEFAULT_HUMAN_ADMIN_ACTIONS
)
REVIEWER_ACTIONS = (
    Action.KG_READ.value,
    Action.KG_REVIEW.value,
    Action.ATTACHMENT_DOWNLOAD.value,
    Action.GOVERNANCE_DOCUMENT_READ.value,
    Action.GOVERNANCE_DOCUMENT_HISTORY_READ.value,
    Action.GOVERNANCE_DOCUMENT_CREATE.value,
    Action.GOVERNANCE_DOCUMENT_EDIT.value,
    Action.GOVERNANCE_DOCUMENT_REVIEW.value,
    Action.GOVERNANCE_DOCUMENT_PUBLISH.value,
    Action.GOVERNANCE_DOCUMENT_ARCHIVE.value,
    Action.GOVERNANCE_TEMPLATE_READ.value,
    Action.GOVERNANCE_TEMPLATE_PROPOSE.value,
    Action.GOVERNANCE_TEMPLATE_REVIEW.value,
    Action.GOVERNANCE_TEMPLATE_ACTIVATE.value,
    Action.GOVERNANCE_KNOWLEDGE_READ.value,
)


def graph_classification(pack: SemiconductorPack) -> int:
    """Return the graph envelope required by every synthetic assertion."""

    return max(
        (
            *(node.classification for node in pack.snapshot.nodes.values()),
            *(edge.classification for edge in pack.snapshot.edges.values()),
        ),
        default=int(Classification.PUBLIC),
    )


def seed_operation_ledger(pack: SemiconductorPack) -> tuple[dict[str, object], ...]:
    """Return the exact immutable operation ledger represented by the seed snapshot."""

    documents: list[dict[str, object]] = []
    sequence = 0
    for node in sorted(pack.snapshot.nodes.values(), key=lambda item: item.entity_id.int):
        sequence += 1
        documents.append(
            {
                "id": str(stable_id(f"changeset-operation:semiconductor:node:{node.entity_id}")),
                "sequence": sequence,
                "operation": "UPSERT",
                "entity_kind": "NODE",
                "stable_entity_id": str(node.entity_id),
                "document": {
                    "entity_type": node.entity_type,
                    "properties": node.properties,
                    "classification": node.classification,
                },
                "provenance": [_provenance(item) for item in node.provenance],
                "confidence": min(item.confidence for item in node.provenance),
            }
        )
    for edge in sorted(pack.snapshot.edges.values(), key=lambda item: item.edge_id.int):
        sequence += 1
        documents.append(
            {
                "id": str(stable_id(f"changeset-operation:semiconductor:edge:{edge.edge_id}")),
                "sequence": sequence,
                "operation": "UPSERT",
                "entity_kind": "EDGE",
                "stable_entity_id": str(edge.edge_id),
                "document": {
                    "source_id": str(edge.source_entity_id),
                    "target_id": str(edge.target_entity_id),
                    "edge_type": edge.edge_type,
                    "properties": edge.properties,
                    "classification": edge.classification,
                },
                "provenance": [_provenance(item) for item in edge.provenance],
                "confidence": min(item.confidence for item in edge.provenance),
            }
        )
    return tuple(documents)


def _release_snapshot(
    nodes: Sequence[ReleaseNodeModel],
    edges: Sequence[ReleaseEdgeModel],
) -> GraphSnapshot:
    return GraphSnapshot(
        nodes={
            item.entity_id: GraphNode(
                entity_id=item.entity_id,
                entity_type=item.entity_type,
                properties=item.properties,
                classification=item.classification,
                provenance=tuple(Provenance.from_document(value) for value in item.provenance),
            )
            for item in nodes
        },
        edges={
            item.edge_id: GraphEdge(
                edge_id=item.edge_id,
                source_entity_id=item.source_entity_id,
                target_entity_id=item.target_entity_id,
                edge_type=item.edge_type,
                properties=item.properties,
                classification=item.classification,
                provenance=tuple(Provenance.from_document(value) for value in item.provenance),
            )
            for item in edges
        },
    )


async def apply_pack(
    session: AsyncSession, *, settings: Settings, pack: SemiconductorPack
) -> dict[str, object]:
    existing_run = await session.get(SeedRunModel, SEED_RUN_ID)
    if existing_run is not None and existing_run.state == "APPLIED":
        # The pack payload may be unchanged while platform action contracts evolve.
        # Reconcile only the seed-owned identities before returning the immutable
        # content receipt so an idempotent apply cannot leave stale RBAC snapshots.
        await _ensure_identity(session, settings=settings)
        await session.commit()
        return await verify_pack(session, pack=pack)

    publisher_id, reviewer_id = await _ensure_identity(session, settings=settings)
    graph = await session.get(GraphModel, GRAPH_ID)
    if graph is not None:
        raise RuntimeError(
            "Seed graph exists without a matching applied seed run; refusing overwrite."
        )

    ontology_document = _load_ontology()
    ontology_checksum = hashlib.sha256(
        json.dumps(ontology_document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ontology = Ontology(
        version_id=ONTOLOGY_ID,
        entity_types=frozenset(ontology_document["entity_types"]),
        edge_types=frozenset(ontology_document["edge_types"]),
    )
    maximum_classification = graph_classification(pack)
    validated = GraphRelease.publish(
        graph_id=GRAPH_ID,
        release_no=1,
        ontology=ontology,
        snapshot=pack.snapshot,
        expected_base_hash=None,
        actual_base_hash=None,
        maximum_classification=maximum_classification,
    )
    now = utc_now()
    graph_model = GraphModel(
        id=GRAPH_ID,
        workspace_id=WORKSPACE_ID,
        slug="semiconductor-value-chain",
        name="Synthetic Semiconductor Value Chain",
        graph_type="ANALYTIC_PRODUCT",
        status="PUBLISHED",
        active_release_id=None,
        classification=maximum_classification,
        version=1,
    )
    session.add(graph_model)
    session.add(
        OntologyVersionModel(
            id=ONTOLOGY_ID,
            workspace_id=WORKSPACE_ID,
            graph_id=GRAPH_ID,
            version=PACK_VERSION,
            schema_document=ontology_document,
            checksum=ontology_checksum,
            status="ACTIVE",
        )
    )
    session.add(
        ReleaseModel(
            id=RELEASE_ID,
            workspace_id=WORKSPACE_ID,
            graph_id=GRAPH_ID,
            release_no=1,
            ontology_version_id=ONTOLOGY_ID,
            content_hash=validated.content_hash,
            node_count=validated.node_count,
            edge_count=validated.edge_count,
            manifest_ref="seed/semiconductor/manifest.yaml",
            published_by=publisher_id,
            published_at=now,
        )
    )
    await session.flush()
    release_nodes = [
        ReleaseNodeModel(
            workspace_id=WORKSPACE_ID,
            release_id=RELEASE_ID,
            entity_id=node.entity_id,
            entity_type=node.entity_type,
            properties=node.properties,
            classification=node.classification,
            provenance=[_provenance(item) for item in node.provenance],
        )
        for node in pack.snapshot.nodes.values()
    ]
    release_edges = [
        ReleaseEdgeModel(
            workspace_id=WORKSPACE_ID,
            release_id=RELEASE_ID,
            edge_id=edge.edge_id,
            source_entity_id=edge.source_entity_id,
            target_entity_id=edge.target_entity_id,
            edge_type=edge.edge_type,
            properties=edge.properties,
            classification=edge.classification,
            provenance=[_provenance(item) for item in edge.provenance],
        )
        for edge in pack.snapshot.edges.values()
    ]
    session.add_all(release_nodes)
    session.add_all(release_edges)
    changeset_model = ChangeSetModel(
        id=CHANGESET_ID,
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        base_release_id=None,
        ontology_version_id=ONTOLOGY_ID,
        title="Synthetic semiconductor seed publication",
        state="PUBLISHED",
        author_id=publisher_id,
        reviewed_by=reviewer_id,
        reviewed_at=now,
        review_reason="Approved deterministic synthetic seed content.",
        published_release_id=RELEASE_ID,
        version=4,
    )
    session.add(changeset_model)
    # There is intentionally no mutable ORM relationship from the immutable
    # operation ledger to its changeset, so make the FK flush order explicit.
    await session.flush((changeset_model,))
    operations = [
        ChangeOperationModel(
            id=document["id"],
            workspace_id=WORKSPACE_ID,
            changeset_id=CHANGESET_ID,
            sequence=document["sequence"],
            operation=document["operation"],
            entity_kind=document["entity_kind"],
            stable_entity_id=document["stable_entity_id"],
            document=document["document"],
            provenance=document["provenance"],
            confidence=document["confidence"],
        )
        for document in seed_operation_ledger(pack)
    ]
    session.add_all(operations)
    session.add_all(
        [
            ChangeSetModel(
                id=UUID("11111111-1111-1111-1111-111111111111"),
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                base_release_id=RELEASE_ID,
                ontology_version_id=ONTOLOGY_ID,
                title="Update customer masking policy (Draft)",
                state="DRAFT",
                author_id=publisher_id,
                version=1,
            ),
            ChangeSetModel(
                id=UUID("22222222-2222-2222-2222-222222222222"),
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                base_release_id=RELEASE_ID,
                ontology_version_id=ONTOLOGY_ID,
                title="Add standard properties for Supplier (Pending)",
                state="PENDING_REVIEW",
                author_id=publisher_id,
                version=1,
            ),
            ChangeSetModel(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                base_release_id=RELEASE_ID,
                ontology_version_id=ONTOLOGY_ID,
                title="Approve regional mapping adjustment",
                state="APPROVED",
                author_id=publisher_id,
                reviewed_by=reviewer_id,
                reviewed_at=now,
                review_reason="Looks good to me.",
                version=2,
            ),
            ChangeSetModel(
                id=UUID("44444444-4444-4444-4444-444444444444"),
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                base_release_id=RELEASE_ID,
                ontology_version_id=ONTOLOGY_ID,
                title="Reject invalid transaction classification",
                state="REJECTED",
                author_id=publisher_id,
                reviewed_by=reviewer_id,
                reviewed_at=now,
                review_reason="Fails basic security invariants.",
                version=2,
            ),
        ]
    )
    await session.flush()
    persisted_nodes = list(
        (
            await session.scalars(
                select(ReleaseNodeModel)
                .where(
                    ReleaseNodeModel.workspace_id == WORKSPACE_ID,
                    ReleaseNodeModel.release_id == RELEASE_ID,
                )
                .order_by(ReleaseNodeModel.entity_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    persisted_edges = list(
        (
            await session.scalars(
                select(ReleaseEdgeModel)
                .where(
                    ReleaseEdgeModel.workspace_id == WORKSPACE_ID,
                    ReleaseEdgeModel.release_id == RELEASE_ID,
                )
                .order_by(ReleaseEdgeModel.edge_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    persisted_snapshot = _release_snapshot(persisted_nodes, persisted_edges)
    if (
        persisted_snapshot.content_hash() != validated.content_hash
        or len(persisted_nodes) != validated.node_count
        or len(persisted_edges) != validated.edge_count
    ):
        raise RuntimeError("The synthetic seed release failed canonical database read-back.")
    verification_hash = canonical_json_hash(
        {
            "adapter": "postgres-adjacency-v1",
            "edge_count": validated.edge_count,
            "node_count": validated.node_count,
            "release_hash": validated.content_hash,
            "release_id": str(RELEASE_ID),
        }
    )
    session.add(
        ProjectionDeploymentModel(
            id=PROJECTION_DEPLOYMENT_ID,
            workspace_id=WORKSPACE_ID,
            graph_id=GRAPH_ID,
            release_id=RELEASE_ID,
            adapter="postgres-adjacency-v1",
            target_ref=f"postgresql://knowledge/releases/{RELEASE_ID}",
            state="CANONICAL_VERIFIED",
            content_hash=validated.content_hash,
            verification_hash=verification_hash,
            node_count=validated.node_count,
            edge_count=validated.edge_count,
            verified_at=now,
        )
    )
    graph_model.active_release_id = RELEASE_ID
    session.add_all(
        [
            AssetProjectionModel(
                id=stable_id(f"catalog-asset:{asset.key}"),
                workspace_id=WORKSPACE_ID,
                external_urn=(
                    "urn:li:dataset:(urn:li:dataPlatform:postgres,"
                    f"synthetic.semiconductor.{asset.key},PROD)"
                ),
                urn_hash=hashlib.sha256(
                    (
                        "urn:li:dataset:(urn:li:dataPlatform:postgres,"
                        f"synthetic.semiconductor.{asset.key},PROD)"
                    ).encode()
                ).hexdigest(),
                asset_type="DATASET",
                name=asset.name,
                description=asset.description,
                platform=asset.platform,
                domain_id=DOMAIN_ID,
                system_id=SYSTEM_ID,
                classification=asset.classification,
                lifecycle="ACTIVE",
                source_version=f"seed:{SEED_NAMESPACE}:{PACK_VERSION}",
                projection_source="SEED",
                observed_at=now,
            )
            for asset in pack.catalog_assets
        ]
    )
    row_counts = {
        "catalog_assets": len(pack.catalog_assets),
        "graph_nodes": len(pack.snapshot.nodes),
        "graph_edges": len(pack.snapshot.edges),
    }
    if existing_run is None:
        session.add(
            SeedRunModel(
                id=SEED_RUN_ID,
                workspace_id=WORKSPACE_ID,
                namespace=SEED_NAMESPACE,
                pack_version=PACK_VERSION,
                content_hash=pack.logical_hash,
                state="APPLIED",
                row_counts=row_counts,
                applied_at=now,
            )
        )
    else:
        existing_run.content_hash = pack.logical_hash
        existing_run.state = "APPLIED"
        existing_run.row_counts = row_counts
        existing_run.applied_at = now
        existing_run.removed_at = None
    await _append_seed_event(session, "seed.semiconductor.applied.v1", pack.logical_hash)
    await session.flush()
    await advance_catalog_projection_version(session, workspace_id=WORKSPACE_ID)
    await session.commit()
    return await verify_pack(session, pack=pack)


async def verify_pack(session: AsyncSession, *, pack: SemiconductorPack) -> dict[str, object]:
    seed_run = await session.get(SeedRunModel, SEED_RUN_ID)
    if seed_run is None or seed_run.state != "APPLIED":
        raise RuntimeError("The semiconductor seed pack is not applied.")
    release = await session.get(ReleaseModel, RELEASE_ID)
    if release is None:
        raise RuntimeError("The semiconductor graph release is missing.")
    graph = await session.get(GraphModel, GRAPH_ID)
    changeset = await session.get(ChangeSetModel, CHANGESET_ID)
    deployment = await session.get(ProjectionDeploymentModel, PROJECTION_DEPLOYMENT_ID)
    publisher = await session.get(SubjectModel, release.published_by)
    publisher_membership = await session.get(
        WorkspaceMembershipModel,
        {"workspace_id": WORKSPACE_ID, "subject_id": release.published_by},
    )
    reviewer = (
        await session.get(SubjectModel, changeset.reviewed_by)
        if changeset is not None and changeset.reviewed_by is not None
        else None
    )
    reviewer_membership = (
        await session.get(
            WorkspaceMembershipModel,
            {"workspace_id": WORKSPACE_ID, "subject_id": changeset.reviewed_by},
        )
        if changeset is not None and changeset.reviewed_by is not None
        else None
    )
    expected_verification_hash = canonical_json_hash(
        {
            "adapter": "postgres-adjacency-v1",
            "edge_count": release.edge_count,
            "node_count": release.node_count,
            "release_hash": release.content_hash,
            "release_id": str(RELEASE_ID),
        }
    )
    if (
        graph is None
        or graph.status != "PUBLISHED"
        or graph.active_release_id != RELEASE_ID
        or graph.classification != graph_classification(pack)
        or changeset is None
        or changeset.state != "PUBLISHED"
        or changeset.author_id == changeset.reviewed_by
        or changeset.reviewed_at is None
        or not (changeset.review_reason or "").strip()
        or changeset.published_release_id != RELEASE_ID
        or publisher is None
        or not publisher.active
        or publisher.external_subject != LOCAL_KEYCLOAK_SUBJECT
        or publisher_membership is None
        or not publisher_membership.active
        or set(publisher_membership.attributes.get("allowed_actions", []))
        != set(ADMINISTRATOR_ACTIONS)
        or Action.KG_PUBLISH.value not in publisher_membership.attributes.get("allowed_actions", [])
        or reviewer is None
        or not reviewer.active
        or reviewer.external_subject != LOCAL_KEYCLOAK_REVIEWER_SUBJECT
        or reviewer_membership is None
        or not reviewer_membership.active
        or Action.KG_REVIEW.value not in reviewer_membership.attributes.get("allowed_actions", [])
        or deployment is None
        or deployment.adapter != "postgres-adjacency-v1"
        or deployment.target_ref != f"postgresql://knowledge/releases/{RELEASE_ID}"
        or deployment.state != "CANONICAL_VERIFIED"
        or deployment.content_hash != release.content_hash
        or deployment.verification_hash != expected_verification_hash
        or deployment.node_count != release.node_count
        or deployment.edge_count != release.edge_count
        or deployment.verified_at is None
    ):
        raise RuntimeError("The semiconductor graph governance evidence is incomplete.")
    catalog_count = int(
        await session.scalar(
            select(func.count())
            .select_from(AssetProjectionModel)
            .where(
                AssetProjectionModel.workspace_id == WORKSPACE_ID,
                AssetProjectionModel.source_version == f"seed:{SEED_NAMESPACE}:{PACK_VERSION}",
            )
        )
        or 0
    )
    persisted_nodes = tuple(
        (
            await session.scalars(
                select(ReleaseNodeModel)
                .where(
                    ReleaseNodeModel.workspace_id == WORKSPACE_ID,
                    ReleaseNodeModel.release_id == RELEASE_ID,
                )
                .order_by(ReleaseNodeModel.entity_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    persisted_edges = tuple(
        (
            await session.scalars(
                select(ReleaseEdgeModel)
                .where(
                    ReleaseEdgeModel.workspace_id == WORKSPACE_ID,
                    ReleaseEdgeModel.release_id == RELEASE_ID,
                )
                .order_by(ReleaseEdgeModel.edge_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    node_count = len(persisted_nodes)
    edge_count = len(persisted_edges)
    persisted_snapshot = _release_snapshot(persisted_nodes, persisted_edges)
    operation_models = tuple(
        (
            await session.scalars(
                select(ChangeOperationModel)
                .where(
                    ChangeOperationModel.workspace_id == WORKSPACE_ID,
                    ChangeOperationModel.changeset_id == CHANGESET_ID,
                )
                .order_by(ChangeOperationModel.sequence)
            )
        ).all()
    )
    operation_ledger = tuple(
        {
            "id": str(model.id),
            "sequence": model.sequence,
            "operation": model.operation,
            "entity_kind": model.entity_kind,
            "stable_entity_id": str(model.stable_entity_id),
            "document": model.document,
            "provenance": model.provenance,
            "confidence": model.confidence,
        }
        for model in operation_models
    )
    if operation_ledger != seed_operation_ledger(pack):
        raise RuntimeError("The semiconductor changeset operation ledger is incomplete.")
    actual = {
        "catalog_assets": catalog_count,
        "graph_nodes": node_count,
        "graph_edges": edge_count,
    }
    expected = {
        "catalog_assets": len(pack.catalog_assets),
        "graph_nodes": len(pack.snapshot.nodes),
        "graph_edges": len(pack.snapshot.edges),
    }
    if actual != expected:
        raise RuntimeError(f"Seed count verification failed: expected {expected}, actual {actual}")
    if (
        seed_run.content_hash != pack.logical_hash
        or release.content_hash != pack.snapshot.content_hash()
        or persisted_snapshot.content_hash() != release.content_hash
        or release.node_count != node_count
        or release.edge_count != edge_count
    ):
        raise RuntimeError("Seed content hash verification failed.")
    return {
        "state": seed_run.state,
        "workspace_id": str(WORKSPACE_ID),
        "seed_run_id": str(SEED_RUN_ID),
        "content_hash": pack.logical_hash,
        "counts": actual,
    }


async def remove_pack(session: AsyncSession, *, pack: SemiconductorPack) -> dict[str, object]:
    seed_run = await session.get(SeedRunModel, SEED_RUN_ID)
    if seed_run is None:
        raise RuntimeError("The semiconductor seed run does not exist.")
    if seed_run.state == "REMOVED":
        return {"state": "REMOVED", "seed_run_id": str(SEED_RUN_ID)}
    await session.execute(delete(GraphModel).where(GraphModel.id == GRAPH_ID))
    await session.execute(
        delete(AssetProjectionModel).where(
            AssetProjectionModel.workspace_id == WORKSPACE_ID,
            AssetProjectionModel.source_version == f"seed:{SEED_NAMESPACE}:{PACK_VERSION}",
        )
    )
    seed_run.state = "REMOVED"
    seed_run.removed_at = utc_now()
    await _append_seed_event(session, "seed.semiconductor.removed.v1", pack.logical_hash)
    await session.flush()
    await advance_catalog_projection_version(session, workspace_id=WORKSPACE_ID)
    await session.commit()
    return {"state": "REMOVED", "seed_run_id": str(SEED_RUN_ID)}


async def _ensure_identity(session: AsyncSession, *, settings: Settings) -> tuple[UUID, UUID]:
    workspace = await session.get(WorkspaceModel, WORKSPACE_ID)
    if workspace is None:
        conflicting = await session.scalar(
            select(WorkspaceModel).where(WorkspaceModel.slug == "semiconductor-analysis")
        )
        if conflicting is not None:
            raise RuntimeError("Workspace slug is already owned by a non-seed workspace.")
        workspace = WorkspaceModel(
            id=WORKSPACE_ID,
            slug="semiconductor-analysis",
            name="Semiconductor Value Chain Analysis",
            status="ACTIVE",
            settings={"seed_namespace": SEED_NAMESPACE, "is_synthetic": True},
            version=1,
        )
        session.add(workspace)
        await session.flush()
    subject = await session.scalar(
        select(SubjectModel).where(
            SubjectModel.issuer == settings.oidc_issuer,
            SubjectModel.external_subject == LOCAL_KEYCLOAK_SUBJECT,
        )
    )
    if subject is None:
        subject = SubjectModel(
            id=SUBJECT_ID,
            issuer=settings.oidc_issuer,
            external_subject=LOCAL_KEYCLOAK_SUBJECT,
            display_name="김데이터 (DataRiver Admin)",
            active=True,
        )
        session.add(subject)
        await session.flush()
    else:
        subject.active = True
    membership = await session.get(
        WorkspaceMembershipModel,
        {"workspace_id": WORKSPACE_ID, "subject_id": subject.id},
    )
    administrator_attributes = {
        "groups": ["security-administrators"],
        "allowed_actions": list(ADMINISTRATOR_ACTIONS),
        "denied_actions": [],
        "allowed_system_ids": [str(SYSTEM_ID)],
        "allowed_domain_ids": [str(DOMAIN_ID)],
        "seed_namespace": SEED_NAMESPACE,
    }
    if membership is None:
        session.add(
            WorkspaceMembershipModel(
                workspace_id=WORKSPACE_ID,
                subject_id=subject.id,
                department_id=None,
                job_function="DATA_GOVERNANCE_ADMINISTRATOR",
                clearance=int(Classification.RESTRICTED),
                attributes=administrator_attributes,
                active=True,
                access_expires_at=add_calendar_months(utc_now(), 6),
            )
        )
    else:
        membership.job_function = "DATA_GOVERNANCE_ADMINISTRATOR"
        membership.clearance = int(Classification.RESTRICTED)
        membership.attributes = administrator_attributes
        membership.active = True
    reviewer_subject = await session.scalar(
        select(SubjectModel).where(
            SubjectModel.issuer == settings.oidc_issuer,
            SubjectModel.external_subject == LOCAL_KEYCLOAK_REVIEWER_SUBJECT,
        )
    )
    if reviewer_subject is None:
        reviewer_subject = SubjectModel(
            id=REVIEWER_SUBJECT_ID,
            issuer=settings.oidc_issuer,
            external_subject=LOCAL_KEYCLOAK_REVIEWER_SUBJECT,
            display_name="이스튜어드 (Data Steward)",
            active=True,
        )
        session.add(reviewer_subject)
        await session.flush()
    else:
        reviewer_subject.active = True
    reviewer_membership = await session.get(
        WorkspaceMembershipModel,
        {"workspace_id": WORKSPACE_ID, "subject_id": reviewer_subject.id},
    )
    reviewer_attributes = {
        "groups": ["data-stewards", "synthetic-seed-reviewers"],
        "allowed_actions": list(REVIEWER_ACTIONS),
        "denied_actions": [],
        "allowed_system_ids": [str(SYSTEM_ID)],
        "allowed_domain_ids": [str(DOMAIN_ID)],
        "seed_namespace": SEED_NAMESPACE,
    }
    if reviewer_membership is None:
        session.add(
            WorkspaceMembershipModel(
                workspace_id=WORKSPACE_ID,
                subject_id=reviewer_subject.id,
                department_id=None,
                job_function="DATA_STEWARD",
                clearance=int(Classification.RESTRICTED),
                attributes=reviewer_attributes,
                active=True,
                access_expires_at=add_calendar_months(utc_now(), 6),
            )
        )
    else:
        reviewer_membership.job_function = "DATA_STEWARD"
        reviewer_membership.clearance = int(Classification.RESTRICTED)
        reviewer_membership.attributes = reviewer_attributes
        reviewer_membership.active = True
    airflow_subject = await session.scalar(
        select(SubjectModel).where(
            SubjectModel.issuer == settings.oidc_issuer,
            SubjectModel.external_subject == LOCAL_KEYCLOAK_AIRFLOW_SUBJECT,
        )
    )
    if airflow_subject is None:
        airflow_subject = SubjectModel(
            id=AIRFLOW_SUBJECT_ID,
            issuer=settings.oidc_issuer,
            external_subject=LOCAL_KEYCLOAK_AIRFLOW_SUBJECT,
            display_name="DataRiver Airflow Service",
            active=True,
        )
        session.add(airflow_subject)
        await session.flush()
    airflow_membership = await session.get(
        WorkspaceMembershipModel,
        {"workspace_id": WORKSPACE_ID, "subject_id": airflow_subject.id},
    )
    airflow_attributes = {
        "groups": ["service-accounts"],
        "allowed_actions": [
            Action.CATALOG_READ.value,
            Action.CATALOG_SEARCH.value,
            Action.CATALOG_SYNC.value,
        ],
        "denied_actions": [],
        "allowed_system_ids": [str(SYSTEM_ID)],
        "allowed_domain_ids": [str(DOMAIN_ID)],
        "seed_namespace": SEED_NAMESPACE,
    }
    if airflow_membership is None:
        session.add(
            WorkspaceMembershipModel(
                workspace_id=WORKSPACE_ID,
                subject_id=airflow_subject.id,
                department_id=None,
                job_function="SERVICE_ACCOUNT",
                clearance=int(Classification.RESTRICTED),
                attributes=airflow_attributes,
                active=True,
                access_expires_at=None,
            )
        )
    else:
        airflow_membership.job_function = "SERVICE_ACCOUNT"
        airflow_membership.clearance = int(Classification.RESTRICTED)
        airflow_membership.attributes = airflow_attributes
        airflow_membership.active = True

    # --- Viewer 더미 사용자: 박뷰어 (Viewer) ---
    viewer_subject = await session.scalar(
        select(SubjectModel).where(
            SubjectModel.issuer == settings.oidc_issuer,
            SubjectModel.external_subject == LOCAL_KEYCLOAK_VIEWER_SUBJECT,
        )
    )
    if viewer_subject is None:
        viewer_subject = SubjectModel(
            id=VIEWER_SUBJECT_ID,
            issuer=settings.oidc_issuer,
            external_subject=LOCAL_KEYCLOAK_VIEWER_SUBJECT,
            display_name="박뷰어 (Viewer)",
            active=True,
        )
        session.add(viewer_subject)
        await session.flush()
    viewer_membership = await session.get(
        WorkspaceMembershipModel,
        {"workspace_id": WORKSPACE_ID, "subject_id": viewer_subject.id},
    )
    viewer_attributes = {
        "groups": ["data-viewers"],
        "allowed_actions": [
            Action.CATALOG_READ.value,
            Action.CATALOG_SEARCH.value,
            Action.KG_READ.value,
        ],
        "denied_actions": [],
        "allowed_system_ids": [str(SYSTEM_ID)],
        "allowed_domain_ids": [str(DOMAIN_ID)],
        "seed_namespace": SEED_NAMESPACE,
    }
    if viewer_membership is None:
        session.add(
            WorkspaceMembershipModel(
                workspace_id=WORKSPACE_ID,
                subject_id=viewer_subject.id,
                department_id=None,
                job_function="DATA_ANALYST",
                clearance=int(Classification.INTERNAL),
                attributes=viewer_attributes,
                active=True,
                access_expires_at=add_calendar_months(utc_now(), 6),
            )
        )
    else:
        viewer_membership.job_function = "DATA_ANALYST"
        viewer_membership.clearance = int(Classification.INTERNAL)
        viewer_membership.attributes = viewer_attributes
        viewer_membership.active = True
    return subject.id, reviewer_subject.id


async def _append_seed_event(session: AsyncSession, event_type: str, content_hash: str) -> None:
    event = DomainEvent.create(
        event_type=event_type,
        aggregate_type="seed_run",
        aggregate_id=SEED_RUN_ID,
        workspace_id=WORKSPACE_ID,
        payload={
            "seed_run_id": str(SEED_RUN_ID),
            "namespace": SEED_NAMESPACE,
            "pack_version": PACK_VERSION,
            "content_hash": content_hash,
        },
    )
    session.add(
        OutboxEventModel(
            id=event.event_id,
            workspace_id=event.workspace_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            schema_version=1,
            payload=event.payload,
            created_at=event.occurred_at,
            attempts=0,
        )
    )


def _load_ontology() -> dict[str, list[str]]:
    path = seed_root() / "semiconductor" / "ontology.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("Seed ontology must be a JSON object.")
    entity_types = document.get("entity_types")
    edge_types = document.get("edge_types")
    if not isinstance(entity_types, list) or not isinstance(edge_types, list):
        raise RuntimeError("Seed ontology type lists are invalid.")
    return {
        "entity_types": [str(value) for value in entity_types],
        "edge_types": [str(value) for value in edge_types],
    }


def _provenance(source: Provenance) -> dict[str, object]:
    return {
        "source_ref": source.source_ref,
        "source_locator": source.source_locator,
        "source_version": source.source_version,
        "method": source.method,
        "confidence": source.confidence,
    }


async def run(action: str) -> dict[str, object]:
    settings = get_settings()
    if settings.seed_profile != "semiconductor":
        raise RuntimeError("Set SEED_PROFILE=semiconductor to operate this optional seed pack.")
    resolver = SecretResolver()
    database = Database(
        settings.migration_database_url,
        password=resolver.resolve(settings.migration_database_secret_ref),
        pool_size=2,
        max_overflow=0,
        application_name="datariver-next-seed",
    )
    pack = build_pack()
    try:
        async with database.session_factory() as session:
            if action == "apply":
                return await apply_pack(session, settings=settings, pack=pack)
            if action == "verify":
                return await verify_pack(session, pack=pack)
            if action == "remove":
                return await remove_pack(session, pack=pack)
            raise RuntimeError(f"Unknown seed action: {action}")
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage explicit DataRiver seed packs.")
    parser.add_argument("action", choices=("apply", "verify", "remove"))
    parser.add_argument("--confirm-synthetic-data", action="store_true")
    arguments = parser.parse_args()
    if arguments.action in {"apply", "remove"} and not arguments.confirm_synthetic_data:
        parser.error("apply/remove requires --confirm-synthetic-data")
    result = asyncio.run(run(arguments.action))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
