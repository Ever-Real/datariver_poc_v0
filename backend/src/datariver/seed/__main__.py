from __future__ import annotations

import argparse
import asyncio
import hashlib
import json

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.config import Settings, get_settings
from datariver.domain.authz import Action, Classification
from datariver.domain.common import DomainEvent, utc_now
from datariver.domain.knowledge import GraphRelease, Ontology, Provenance
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.integration import OutboxEventModel, SeedRunModel
from datariver.infrastructure.db.models.knowledge import (
    GraphModel,
    OntologyVersionModel,
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
SEED_RUN_ID = stable_id("seed-run:semiconductor:1.0.0")
SYSTEM_ID = stable_id("system:semiconductor-reference")
DOMAIN_ID = stable_id("domain:semiconductor-value-chain")
LOCAL_KEYCLOAK_SUBJECT = "00000000-0000-4000-8000-000000000001"
LOCAL_KEYCLOAK_AIRFLOW_SUBJECT = "00000000-0000-4000-8000-000000000002"


async def apply_pack(
    session: AsyncSession, *, settings: Settings, pack: SemiconductorPack
) -> dict[str, object]:
    existing_run = await session.get(SeedRunModel, SEED_RUN_ID)
    if existing_run is not None and existing_run.state == "APPLIED":
        return await verify_pack(session, pack=pack)

    await _ensure_identity(session, settings=settings)
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
    validated = GraphRelease.publish(
        graph_id=GRAPH_ID,
        release_no=1,
        ontology=ontology,
        snapshot=pack.snapshot,
        expected_base_hash=None,
        actual_base_hash=None,
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
        classification=int(Classification.INTERNAL),
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
            published_by=SUBJECT_ID,
            published_at=now,
        )
    )
    await session.flush()
    graph_model.active_release_id = RELEASE_ID
    session.add_all(
        [
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
    )
    session.add_all(
        [
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
    )
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
    await session.commit()
    return await verify_pack(session, pack=pack)


async def verify_pack(session: AsyncSession, *, pack: SemiconductorPack) -> dict[str, object]:
    seed_run = await session.get(SeedRunModel, SEED_RUN_ID)
    if seed_run is None or seed_run.state != "APPLIED":
        raise RuntimeError("The semiconductor seed pack is not applied.")
    release = await session.get(ReleaseModel, RELEASE_ID)
    if release is None:
        raise RuntimeError("The semiconductor graph release is missing.")
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
    node_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ReleaseNodeModel)
            .where(ReleaseNodeModel.release_id == RELEASE_ID)
        )
        or 0
    )
    edge_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ReleaseEdgeModel)
            .where(ReleaseEdgeModel.release_id == RELEASE_ID)
        )
        or 0
    )
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
    await session.commit()
    return {"state": "REMOVED", "seed_run_id": str(SEED_RUN_ID)}


async def _ensure_identity(session: AsyncSession, *, settings: Settings) -> None:
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
            display_name="DataRiver Local Administrator",
            active=True,
        )
        session.add(subject)
        await session.flush()
    membership = await session.get(
        WorkspaceMembershipModel,
        {"workspace_id": WORKSPACE_ID, "subject_id": subject.id},
    )
    administrator_attributes = {
        "groups": ["security-administrators"],
        "allowed_actions": [action.value for action in Action],
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
            )
        )
    else:
        membership.job_function = "DATA_GOVERNANCE_ADMINISTRATOR"
        membership.clearance = int(Classification.RESTRICTED)
        membership.attributes = administrator_attributes
        membership.active = True
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
            )
        )
    else:
        airflow_membership.job_function = "SERVICE_ACCOUNT"
        airflow_membership.clearance = int(Classification.RESTRICTED)
        airflow_membership.attributes = airflow_attributes
        airflow_membership.active = True


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
