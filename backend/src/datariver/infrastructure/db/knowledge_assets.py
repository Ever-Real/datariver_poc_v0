from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import TypeGuard
from uuid import UUID

from sqlalchemy import Select, and_, cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from datariver.application.knowledge_asset_contracts import (
    KnowledgeAssetBindingSummary,
    KnowledgeAssetOperationalDetail,
    KnowledgeAssetPage,
    KnowledgeAssetProjectionSummary,
    KnowledgeAssetSchemaElementSummary,
    KnowledgeAssetSummary,
    KnowledgeAssetVersionEvent,
    KnowledgeAssetVersionPage,
    KnowledgeChatCandidate,
)
from datariver.application.knowledge_asset_ports import KnowledgeAssetRepository
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError, utc_now, uuid7
from datariver.domain.knowledge_assets import KnowledgeDeliveryPolicy
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import CatalogVocabularyEntryModel
from datariver.infrastructure.db.models.knowledge import (
    ChangeSetModel,
    GraphModel,
    KnowledgeDeliveryPolicyModel,
    ProjectionDeploymentModel,
    ReleaseModel,
)
from datariver.infrastructure.db.models.knowledge_studio import (
    ABoxBindingVersionModel,
    ABoxMappingRuleVersionModel,
    KnowledgeSourceReferenceModel,
    KnowledgeStudioDraftModel,
    KnowledgeStudioReleaseModel,
    OntologyElementModel,
)
from datariver.infrastructure.db.models.platform import SubjectModel

_POLICY_OPERATION = "kg.delivery-policy.save.v1"
_CURSOR_VERSION = 1


def _encode_cursor(
    *,
    sort: str,
    key: str,
    graph_id: UUID,
    domain_id: UUID | None = None,
) -> str:
    document = {"v": _CURSOR_VERSION, "sort": sort, "key": key, "id": str(graph_id)}
    if domain_id is not None:
        document["domain_id"] = str(domain_id)
    payload = json.dumps(
        document,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    sort: str,
    domain_id: UUID | None = None,
) -> tuple[str, UUID]:
    try:
        payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        document = json.loads(payload)
        if (
            not isinstance(document, dict)
            or document.get("v") != _CURSOR_VERSION
            or document.get("sort") != sort
            or not isinstance(document.get("key"), str)
            or not isinstance(document.get("id"), str)
            or (domain_id is None and "domain_id" in document)
            or (domain_id is not None and document.get("domain_id") != str(domain_id))
        ):
            raise ValueError
        key = document["key"]
        graph_id = UUID(document["id"])
        if cursor != _encode_cursor(
            sort=sort,
            key=key,
            graph_id=graph_id,
            domain_id=domain_id,
        ):
            raise ValueError
        return key, graph_id
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValidationError("The Knowledge Asset page cursor is invalid.") from error


def _encode_version_cursor(*, created_at: datetime, event_id: UUID) -> str:
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "created_at": created_at.isoformat(),
            "id": str(event_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_version_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        document = json.loads(payload)
        if (
            not isinstance(document, dict)
            or document.get("v") != _CURSOR_VERSION
            or not isinstance(document.get("created_at"), str)
            or not isinstance(document.get("id"), str)
        ):
            raise ValueError
        created_at = datetime.fromisoformat(document["created_at"])
        event_id = UUID(document["id"])
        if cursor != _encode_version_cursor(created_at=created_at, event_id=event_id):
            raise ValueError
        return created_at, event_id
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValidationError("The Knowledge Asset version cursor is invalid.") from error


def _policy(model: KnowledgeDeliveryPolicyModel | None) -> KnowledgeDeliveryPolicy | None:
    if model is None:
        return None
    return KnowledgeDeliveryPolicy(
        policy_id=model.id,
        workspace_id=model.workspace_id,
        graph_id=model.graph_id,
        api_enabled=model.api_enabled,
        chat_enabled=model.chat_enabled,
        priority=model.priority,
        match_any_terms=tuple(model.match_any_terms),
        match_all_terms=tuple(model.match_all_terms),
        excluded_terms=tuple(model.excluded_terms),
        created_by=model.created_by,
        updated_by=model.updated_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _policy_result(policy: KnowledgeDeliveryPolicy) -> dict[str, object]:
    return {
        "policy_id": str(policy.policy_id),
        "workspace_id": str(policy.workspace_id),
        "graph_id": str(policy.graph_id),
        "api_enabled": policy.api_enabled,
        "chat_enabled": policy.chat_enabled,
        "priority": policy.priority,
        "match_any_terms": list(policy.match_any_terms),
        "match_all_terms": list(policy.match_all_terms),
        "excluded_terms": list(policy.excluded_terms),
        "created_by": str(policy.created_by),
        "updated_by": str(policy.updated_by),
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
        "version": policy.version,
    }


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _replayed_policy(
    document: dict[str, object],
    *,
    workspace_id: UUID,
    graph_id: UUID,
) -> KnowledgeDeliveryPolicy:
    try:
        api_enabled = document["api_enabled"]
        chat_enabled = document["chat_enabled"]
        priority = document["priority"]
        version = document["version"]
        any_terms = document["match_any_terms"]
        all_terms = document["match_all_terms"]
        excluded_terms = document["excluded_terms"]
        if (
            not isinstance(api_enabled, bool)
            or not isinstance(chat_enabled, bool)
            or not isinstance(priority, int)
            or isinstance(priority, bool)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or not _is_string_list(any_terms)
            or not _is_string_list(all_terms)
            or not _is_string_list(excluded_terms)
        ):
            raise TypeError
        policy = KnowledgeDeliveryPolicy(
            policy_id=UUID(str(document["policy_id"])),
            workspace_id=UUID(str(document["workspace_id"])),
            graph_id=UUID(str(document["graph_id"])),
            api_enabled=api_enabled,
            chat_enabled=chat_enabled,
            priority=priority,
            match_any_terms=tuple(any_terms),
            match_all_terms=tuple(all_terms),
            excluded_terms=tuple(excluded_terms),
            created_by=UUID(str(document["created_by"])),
            updated_by=UUID(str(document["updated_by"])),
            created_at=datetime.fromisoformat(str(document["created_at"])),
            updated_at=datetime.fromisoformat(str(document["updated_at"])),
            version=version,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ConflictError("The idempotent Knowledge delivery policy is invalid.") from error
    if policy.workspace_id != workspace_id or policy.graph_id != graph_id:
        raise ConflictError("The idempotent Knowledge delivery policy belongs to another resource.")
    return policy


class SqlKnowledgeAssetRepository(KnowledgeAssetRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _scope(
        *,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            GraphModel.status != "ARCHIVED",
            GraphModel.classification <= clearance,
            or_(
                GraphModel.classification == int(Classification.PUBLIC),
                GraphModel.domain_ref_id.is_(None),
                GraphModel.domain_ref_id.in_(tuple(allowed_domain_ids)),
            ),
        )

    @staticmethod
    def _statement(workspace_id: UUID) -> Select[tuple[object, ...]]:
        creator = aliased(SubjectModel)
        editor = aliased(SubjectModel)
        tbox_counts = (
            select(
                OntologyElementModel.ontology_version_id.label("ontology_version_id"),
                func.count().filter(OntologyElementModel.kind == "CLASS").label("class_count"),
                func.count()
                .filter(OntologyElementModel.kind == "PROPERTY")
                .label("property_count"),
                func.count()
                .filter(OntologyElementModel.kind == "RELATION")
                .label("relationship_count"),
            )
            .where(OntologyElementModel.workspace_id == workspace_id)
            .group_by(OntologyElementModel.ontology_version_id)
            .subquery()
        )
        binding_counts = (
            select(
                ABoxBindingVersionModel.studio_release_id.label("studio_release_id"),
                func.count(ABoxBindingVersionModel.id).label("binding_count"),
                func.count(func.distinct(ABoxBindingVersionModel.source_reference_id)).label(
                    "source_count"
                ),
            )
            .where(ABoxBindingVersionModel.workspace_id == workspace_id)
            .group_by(ABoxBindingVersionModel.studio_release_id)
            .subquery()
        )
        projection_state = (
            select(ProjectionDeploymentModel.state)
            .where(
                ProjectionDeploymentModel.workspace_id == GraphModel.workspace_id,
                ProjectionDeploymentModel.graph_id == GraphModel.id,
                ProjectionDeploymentModel.release_id == GraphModel.active_release_id,
            )
            .order_by(
                ProjectionDeploymentModel.updated_at.desc(),
                ProjectionDeploymentModel.id.desc(),
            )
            .limit(1)
            .scalar_subquery()
        )
        return (
            select(
                GraphModel,
                CatalogVocabularyEntryModel.display_name.label("domain_name"),
                creator.display_name.label("creator_name"),
                creator.email.label("creator_email"),
                editor.display_name.label("editor_name"),
                editor.email.label("editor_email"),
                KnowledgeStudioReleaseModel.release_no.label("studio_release_no"),
                ReleaseModel.release_no.label("instance_release_no"),
                func.coalesce(tbox_counts.c.class_count, 0).label("class_count"),
                func.coalesce(tbox_counts.c.property_count, 0).label("property_count"),
                func.coalesce(tbox_counts.c.relationship_count, 0).label("relationship_count"),
                func.coalesce(binding_counts.c.binding_count, 0).label("binding_count"),
                func.coalesce(binding_counts.c.source_count, 0).label("source_count"),
                func.coalesce(ReleaseModel.node_count, 0).label("node_count"),
                func.coalesce(ReleaseModel.edge_count, 0).label("edge_count"),
                projection_state.label("projection_state"),
                func.lower(GraphModel.name).label("name_sort_key"),
                KnowledgeDeliveryPolicyModel,
            )
            .outerjoin(
                CatalogVocabularyEntryModel,
                and_(
                    CatalogVocabularyEntryModel.workspace_id == GraphModel.workspace_id,
                    CatalogVocabularyEntryModel.id == GraphModel.domain_ref_id,
                    CatalogVocabularyEntryModel.kind == "DOMAIN",
                ),
            )
            .outerjoin(creator, creator.id == GraphModel.created_by)
            .outerjoin(editor, editor.id == GraphModel.updated_by)
            .outerjoin(
                KnowledgeStudioReleaseModel,
                and_(
                    KnowledgeStudioReleaseModel.workspace_id == GraphModel.workspace_id,
                    KnowledgeStudioReleaseModel.graph_id == GraphModel.id,
                    KnowledgeStudioReleaseModel.id == GraphModel.active_studio_release_id,
                ),
            )
            .outerjoin(
                KnowledgeStudioDraftModel,
                and_(
                    KnowledgeStudioDraftModel.workspace_id == GraphModel.workspace_id,
                    KnowledgeStudioDraftModel.id == KnowledgeStudioReleaseModel.source_draft_id,
                ),
            )
            .outerjoin(
                ReleaseModel,
                and_(
                    ReleaseModel.workspace_id == GraphModel.workspace_id,
                    ReleaseModel.graph_id == GraphModel.id,
                    ReleaseModel.id == GraphModel.active_release_id,
                ),
            )
            .outerjoin(
                tbox_counts,
                tbox_counts.c.ontology_version_id
                == KnowledgeStudioReleaseModel.ontology_version_id,
            )
            .outerjoin(
                binding_counts,
                binding_counts.c.studio_release_id == KnowledgeStudioReleaseModel.id,
            )
            .outerjoin(
                KnowledgeDeliveryPolicyModel,
                and_(
                    KnowledgeDeliveryPolicyModel.workspace_id == GraphModel.workspace_id,
                    KnowledgeDeliveryPolicyModel.graph_id == GraphModel.id,
                ),
            )
            .where(GraphModel.workspace_id == workspace_id)
        )

    @staticmethod
    def _summary(row: object) -> KnowledgeAssetSummary:
        values = row._mapping  # type: ignore[attr-defined]
        graph: GraphModel = values[GraphModel]
        return KnowledgeAssetSummary(
            graph_id=graph.id,
            slug=graph.slug,
            name=graph.name,
            graph_type=graph.graph_type,
            status=graph.status,
            classification=Classification(graph.classification),
            domain_id=graph.domain_ref_id,
            domain_name=values["domain_name"],
            creator_name=values["creator_name"],
            creator_email=values["creator_email"],
            editor_name=values["editor_name"],
            editor_email=values["editor_email"],
            active_studio_release_id=graph.active_studio_release_id,
            active_studio_release_no=values["studio_release_no"],
            active_release_id=graph.active_release_id,
            active_release_no=values["instance_release_no"],
            class_count=int(values["class_count"]),
            property_count=int(values["property_count"]),
            relationship_count=int(values["relationship_count"]),
            binding_count=int(values["binding_count"]),
            source_count=int(values["source_count"]),
            node_count=int(values["node_count"]),
            edge_count=int(values["edge_count"]),
            projection_state=values["projection_state"],
            created_at=graph.created_at,
            updated_at=graph.updated_at,
            version=graph.version,
            delivery_policy=_policy(values[KnowledgeDeliveryPolicyModel]),
        )

    async def list_assets(
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        query: str,
        domain_id: UUID | None,
        sort: str,
        cursor: str | None,
        limit: int,
    ) -> KnowledgeAssetPage:
        if sort not in {"UPDATED_DESC", "NAME_ASC"}:
            raise ValidationError("The Knowledge Asset sort is not supported.")
        statement = self._statement(workspace_id).where(
            *self._scope(clearance=clearance, allowed_domain_ids=allowed_domain_ids)
        )
        if domain_id is not None:
            statement = statement.where(GraphModel.domain_ref_id == domain_id)
        if query:
            escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            statement = statement.where(
                or_(
                    func.lower(GraphModel.name).like(pattern, escape="\\"),
                    func.lower(GraphModel.slug).like(pattern, escape="\\"),
                    func.lower(CatalogVocabularyEntryModel.display_name).like(
                        pattern,
                        escape="\\",
                    ),
                )
            )
        if cursor is not None:
            key, graph_id = _decode_cursor(cursor, sort=sort, domain_id=domain_id)
            if sort == "UPDATED_DESC":
                try:
                    boundary = datetime.fromisoformat(key)
                except ValueError as error:
                    raise ValidationError("The Knowledge Asset page cursor is invalid.") from error
                statement = statement.where(
                    or_(
                        GraphModel.updated_at < boundary,
                        and_(GraphModel.updated_at == boundary, GraphModel.id < graph_id),
                    )
                )
            else:
                statement = statement.where(
                    or_(
                        func.lower(GraphModel.name) > key,
                        and_(func.lower(GraphModel.name) == key, GraphModel.id > graph_id),
                    )
                )
        if sort == "UPDATED_DESC":
            statement = statement.order_by(GraphModel.updated_at.desc(), GraphModel.id.desc())
        else:
            statement = statement.order_by(func.lower(GraphModel.name), GraphModel.id)
        rows = (await self._session.execute(statement.limit(limit + 1))).all()
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            values = visible[-1]._mapping
            graph = values[GraphModel]
            next_cursor = _encode_cursor(
                sort=sort,
                key=(
                    graph.updated_at.isoformat()
                    if sort == "UPDATED_DESC"
                    else str(values["name_sort_key"])
                ),
                graph_id=graph.id,
                domain_id=domain_id,
            )
        return KnowledgeAssetPage(
            items=tuple(self._summary(row) for row in visible),
            next_cursor=next_cursor,
        )

    async def get_asset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
    ) -> KnowledgeAssetSummary | None:
        row = (
            await self._session.execute(
                self._statement(workspace_id).where(
                    GraphModel.id == graph_id,
                    *self._scope(
                        clearance=clearance,
                        allowed_domain_ids=allowed_domain_ids,
                    ),
                )
            )
        ).one_or_none()
        return self._summary(row) if row is not None else None

    async def get_asset_by_alias(
        self,
        *,
        workspace_id: UUID,
        alias: str,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        require_api_enabled: bool,
    ) -> KnowledgeAssetSummary | None:
        conditions: list[ColumnElement[bool]] = [
            or_(
                GraphModel.slug == alias,
                cast(KnowledgeStudioDraftModel.endpoint_aliases, JSONB).contains([alias]),
            ),
            GraphModel.active_release_id.is_not(None),
            *self._scope(clearance=clearance, allowed_domain_ids=allowed_domain_ids),
        ]
        if require_api_enabled:
            conditions.append(KnowledgeDeliveryPolicyModel.api_enabled.is_(True))
        row = (
            await self._session.execute(self._statement(workspace_id).where(*conditions))
        ).one_or_none()
        return self._summary(row) if row is not None else None

    async def get_operational_detail(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
    ) -> KnowledgeAssetOperationalDetail | None:
        asset = await self.get_asset(
            workspace_id=workspace_id,
            graph_id=graph_id,
            clearance=clearance,
            allowed_domain_ids=allowed_domain_ids,
        )
        if asset is None:
            return None
        bindings: tuple[KnowledgeAssetBindingSummary, ...] = ()
        schema_elements: tuple[KnowledgeAssetSchemaElementSummary, ...] = ()
        if asset.active_studio_release_id is not None:
            release = await self._session.get(
                KnowledgeStudioReleaseModel,
                asset.active_studio_release_id,
            )
            if release is not None and release.workspace_id == workspace_id:
                element_models = (
                    await self._session.scalars(
                        select(OntologyElementModel)
                        .where(
                            OntologyElementModel.workspace_id == workspace_id,
                            OntologyElementModel.graph_id == graph_id,
                            OntologyElementModel.ontology_version_id == release.ontology_version_id,
                        )
                        .order_by(
                            OntologyElementModel.ordinal,
                            OntologyElementModel.stable_element_id,
                        )
                        .limit(500)
                    )
                ).all()
                schema_elements = tuple(
                    KnowledgeAssetSchemaElementSummary(
                        stable_element_id=model.stable_element_id,
                        kind=model.kind,
                        display_name=model.display_name,
                        canonical_name=model.canonical_name,
                        data_type=(
                            str(model.element_document["data_type"])
                            if model.element_document.get("data_type") is not None
                            else None
                        ),
                        source_stable_element_id=(
                            str(model.element_document["source_stable_element_id"])
                            if model.element_document.get("source_stable_element_id") is not None
                            else None
                        ),
                        target_stable_element_id=(
                            str(model.element_document["target_stable_element_id"])
                            if model.element_document.get("target_stable_element_id") is not None
                            else None
                        ),
                    )
                    for model in element_models
                )
            rule_count = (
                select(
                    ABoxMappingRuleVersionModel.binding_version_id.label("binding_id"),
                    func.count(ABoxMappingRuleVersionModel.id).label("rule_count"),
                )
                .where(
                    ABoxMappingRuleVersionModel.workspace_id == workspace_id,
                    ABoxMappingRuleVersionModel.studio_release_id == asset.active_studio_release_id,
                )
                .group_by(ABoxMappingRuleVersionModel.binding_version_id)
                .subquery()
            )
            rows = (
                await self._session.execute(
                    select(
                        ABoxBindingVersionModel,
                        KnowledgeSourceReferenceModel,
                        func.coalesce(rule_count.c.rule_count, 0),
                    )
                    .join(
                        KnowledgeSourceReferenceModel,
                        and_(
                            KnowledgeSourceReferenceModel.workspace_id
                            == ABoxBindingVersionModel.workspace_id,
                            KnowledgeSourceReferenceModel.id
                            == ABoxBindingVersionModel.source_reference_id,
                        ),
                    )
                    .outerjoin(
                        rule_count,
                        rule_count.c.binding_id == ABoxBindingVersionModel.id,
                    )
                    .where(
                        ABoxBindingVersionModel.workspace_id == workspace_id,
                        ABoxBindingVersionModel.studio_release_id == asset.active_studio_release_id,
                    )
                    .order_by(ABoxBindingVersionModel.ordinal)
                )
            ).all()
            bindings = tuple(
                KnowledgeAssetBindingSummary(
                    binding_id=binding.id,
                    target_stable_element_id=binding.target_stable_element_id,
                    source_reference_id=source.id,
                    source_kind=source.kind,
                    source_name=str(source.selection_document.get("source_name") or source.id),
                    source_version=source.source_version,
                    mapping_rule_count=int(count),
                )
                for binding, source, count in rows
            )
        projections = tuple(
            KnowledgeAssetProjectionSummary(
                deployment_id=model.id,
                release_id=model.release_id,
                adapter=model.adapter,
                state=model.state,
                node_count=model.node_count,
                edge_count=model.edge_count,
                verified_at=model.verified_at,
                error_code=model.error_code,
                updated_at=model.updated_at,
            )
            for model in (
                await self._session.scalars(
                    select(ProjectionDeploymentModel)
                    .where(
                        ProjectionDeploymentModel.workspace_id == workspace_id,
                        ProjectionDeploymentModel.graph_id == graph_id,
                    )
                    .order_by(
                        ProjectionDeploymentModel.updated_at.desc(),
                        ProjectionDeploymentModel.id.desc(),
                    )
                    .limit(50)
                )
            ).all()
        )
        return KnowledgeAssetOperationalDetail(
            asset=asset,
            schema_elements=schema_elements,
            bindings=bindings,
            projections=projections,
        )

    async def list_version_events(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> KnowledgeAssetVersionPage:
        graph = (
            await self._session.scalars(
                select(GraphModel).where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.id == graph_id,
                    GraphModel.status != "ARCHIVED",
                )
            )
        ).one_or_none()
        if graph is None:
            return KnowledgeAssetVersionPage(items=(), next_cursor=None)

        boundary = _decode_version_cursor(cursor) if cursor is not None else None
        studio_statement = select(KnowledgeStudioReleaseModel).where(
            KnowledgeStudioReleaseModel.workspace_id == workspace_id,
            KnowledgeStudioReleaseModel.graph_id == graph_id,
        )
        instance_statement = select(ReleaseModel).where(
            ReleaseModel.workspace_id == workspace_id,
            ReleaseModel.graph_id == graph_id,
        )
        changeset_statement = select(ChangeSetModel).where(
            ChangeSetModel.workspace_id == workspace_id,
            ChangeSetModel.graph_id == graph_id,
        )
        if boundary is not None:
            created_at, event_id = boundary
            studio_statement = studio_statement.where(
                or_(
                    KnowledgeStudioReleaseModel.published_at < created_at,
                    and_(
                        KnowledgeStudioReleaseModel.published_at == created_at,
                        KnowledgeStudioReleaseModel.id < event_id,
                    ),
                )
            )
            instance_statement = instance_statement.where(
                or_(
                    ReleaseModel.published_at < created_at,
                    and_(
                        ReleaseModel.published_at == created_at,
                        ReleaseModel.id < event_id,
                    ),
                )
            )
            changeset_statement = changeset_statement.where(
                or_(
                    ChangeSetModel.created_at < created_at,
                    and_(
                        ChangeSetModel.created_at == created_at,
                        ChangeSetModel.id < event_id,
                    ),
                )
            )
        studio_releases = tuple(
            (
                await self._session.scalars(
                    studio_statement.order_by(
                        KnowledgeStudioReleaseModel.published_at.desc(),
                        KnowledgeStudioReleaseModel.id.desc(),
                    ).limit(limit + 1)
                )
            ).all()
        )
        instance_releases = tuple(
            (
                await self._session.scalars(
                    instance_statement.order_by(
                        ReleaseModel.published_at.desc(),
                        ReleaseModel.id.desc(),
                    ).limit(limit + 1)
                )
            ).all()
        )
        changesets = tuple(
            (
                await self._session.scalars(
                    changeset_statement.order_by(
                        ChangeSetModel.created_at.desc(),
                        ChangeSetModel.id.desc(),
                    ).limit(limit + 1)
                )
            ).all()
        )
        published_changeset_release_ids = {
            changeset.published_release_id
            for changeset in changesets
            if changeset.published_release_id is not None
        }
        linked_instance_releases = (
            tuple(
                (
                    await self._session.scalars(
                        select(ReleaseModel).where(
                            ReleaseModel.workspace_id == workspace_id,
                            ReleaseModel.graph_id == graph_id,
                            ReleaseModel.id.in_(tuple(published_changeset_release_ids)),
                        )
                    )
                ).all()
            )
            if published_changeset_release_ids
            else ()
        )
        linked_release_by_id = {release.id: release for release in linked_instance_releases}
        subject_ids = {
            subject_id
            for subject_id in (
                *(
                    value
                    for release in studio_releases
                    for value in (
                        release.author_id,
                        release.reviewed_by,
                        release.published_by,
                    )
                ),
                *(release.published_by for release in instance_releases),
                *(
                    value
                    for changeset in changesets
                    for value in (
                        changeset.author_id,
                        changeset.reviewed_by,
                        (
                            linked_release_by_id[changeset.published_release_id].published_by
                            if changeset.published_release_id in linked_release_by_id
                            else None
                        ),
                    )
                    if value is not None
                ),
            )
            if subject_id is not None
        }
        subjects = (
            tuple(
                (
                    await self._session.scalars(
                        select(SubjectModel).where(SubjectModel.id.in_(tuple(subject_ids)))
                    )
                ).all()
            )
            if subject_ids
            else ()
        )
        subject_by_id = {item.id: item for item in subjects}

        def identity(subject_id: UUID | None) -> tuple[str | None, str | None]:
            subject = subject_by_id.get(subject_id) if subject_id is not None else None
            return (
                subject.display_name if subject is not None else None,
                subject.email if subject is not None else None,
            )

        events: list[KnowledgeAssetVersionEvent] = []
        for studio_release in studio_releases:
            author_name, author_email = identity(studio_release.author_id)
            reviewer_name, reviewer_email = identity(studio_release.reviewed_by)
            publisher_name, publisher_email = identity(studio_release.published_by)
            events.append(
                KnowledgeAssetVersionEvent(
                    event_id=studio_release.id,
                    kind="STUDIO_RELEASE",
                    version_label=f"Schema v{studio_release.release_no}",
                    title="T-Box + Mapping contract",
                    status=studio_release.state,
                    author_id=studio_release.author_id,
                    author_name=author_name,
                    author_email=author_email,
                    reviewed_by=studio_release.reviewed_by,
                    reviewer_name=reviewer_name,
                    reviewer_email=reviewer_email,
                    published_by=studio_release.published_by,
                    publisher_name=publisher_name,
                    publisher_email=publisher_email,
                    created_at=studio_release.published_at,
                    is_current=graph.active_studio_release_id == studio_release.id,
                    studio_release_id=studio_release.id,
                    content_hash=studio_release.contract_hash,
                )
            )
        for instance_release in instance_releases:
            publisher_name, publisher_email = identity(instance_release.published_by)
            events.append(
                KnowledgeAssetVersionEvent(
                    event_id=instance_release.id,
                    kind="INSTANCE_RELEASE",
                    version_label=f"Instance v{instance_release.release_no}",
                    title="Immutable A-Box release",
                    status=(
                        "ACTIVE" if graph.active_release_id == instance_release.id else "SUPERSEDED"
                    ),
                    author_id=instance_release.published_by,
                    author_name=publisher_name,
                    author_email=publisher_email,
                    reviewed_by=None,
                    reviewer_name=None,
                    reviewer_email=None,
                    published_by=instance_release.published_by,
                    publisher_name=publisher_name,
                    publisher_email=publisher_email,
                    created_at=instance_release.published_at,
                    is_current=graph.active_release_id == instance_release.id,
                    instance_release_id=instance_release.id,
                    content_hash=instance_release.content_hash,
                    node_count=instance_release.node_count,
                    edge_count=instance_release.edge_count,
                )
            )
        for changeset in changesets:
            author_name, author_email = identity(changeset.author_id)
            reviewer_name, reviewer_email = identity(changeset.reviewed_by)
            published_release = (
                linked_release_by_id.get(changeset.published_release_id)
                if changeset.published_release_id is not None
                else None
            )
            published_by = published_release.published_by if published_release is not None else None
            publisher_name, publisher_email = identity(published_by)
            events.append(
                KnowledgeAssetVersionEvent(
                    event_id=changeset.id,
                    kind="CHANGESET",
                    version_label=f"Changeset {str(changeset.id)[:8]}",
                    title=changeset.title,
                    status=changeset.state,
                    author_id=changeset.author_id,
                    author_name=author_name,
                    author_email=author_email,
                    reviewed_by=changeset.reviewed_by,
                    reviewer_name=reviewer_name,
                    reviewer_email=reviewer_email,
                    published_by=published_by,
                    publisher_name=publisher_name,
                    publisher_email=publisher_email,
                    created_at=changeset.created_at,
                    is_current=False,
                    changeset_id=changeset.id,
                    instance_release_id=changeset.published_release_id,
                )
            )
        events.sort(
            key=lambda item: (item.created_at, item.event_id),
            reverse=True,
        )
        page_items = tuple(events[:limit])
        return KnowledgeAssetVersionPage(
            items=page_items,
            next_cursor=(
                _encode_version_cursor(
                    created_at=page_items[-1].created_at,
                    event_id=page_items[-1].event_id,
                )
                if len(events) > limit and page_items
                else None
            ),
        )

    async def save_delivery_policy(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        actor_id: UUID,
        api_enabled: bool,
        chat_enabled: bool,
        priority: int,
        match_any_terms: tuple[str, ...],
        match_all_terms: tuple[str, ...],
        excluded_terms: tuple[str, ...],
        expected_version: int | None,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeDeliveryPolicy:
        idempotency = SqlIdempotencyStore(self._session)
        operation = f"{_POLICY_OPERATION}:{graph_id}"
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        replay = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if replay is not None:
            if replay.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with another request.")
            return _replayed_policy(
                replay.result,
                workspace_id=workspace_id,
                graph_id=graph_id,
            )
        locked_graph_id = (
            await self._session.scalars(
                select(GraphModel.id)
                .where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.id == graph_id,
                    GraphModel.status != "ARCHIVED",
                )
                .with_for_update()
            )
        ).one_or_none()
        if locked_graph_id is None:
            raise ConflictError("The Knowledge Asset is unavailable.")
        model = (
            await self._session.scalars(
                select(KnowledgeDeliveryPolicyModel)
                .where(
                    KnowledgeDeliveryPolicyModel.workspace_id == workspace_id,
                    KnowledgeDeliveryPolicyModel.graph_id == graph_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        now = utc_now()
        if model is None:
            if expected_version is not None:
                raise ConflictError("The Knowledge delivery policy does not exist.")
            model = KnowledgeDeliveryPolicyModel(
                id=uuid7(),
                workspace_id=workspace_id,
                graph_id=graph_id,
                api_enabled=api_enabled,
                chat_enabled=chat_enabled,
                priority=priority,
                match_any_terms=list(match_any_terms),
                match_all_terms=list(match_all_terms),
                excluded_terms=list(excluded_terms),
                created_by=actor_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
                version=1,
            )
            self._session.add(model)
        else:
            if expected_version is None or model.version != expected_version:
                raise ConflictError("The Knowledge delivery policy version is stale.")
            model.api_enabled = api_enabled
            model.chat_enabled = chat_enabled
            model.priority = priority
            model.match_any_terms = list(match_any_terms)
            model.match_all_terms = list(match_all_terms)
            model.excluded_terms = list(excluded_terms)
            model.updated_by = actor_id
            model.updated_at = now
            model.version += 1
        await self._session.flush()
        result = _policy(model)
        assert result is not None
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result=_policy_result(result),
        )
        await self._session.commit()
        return result

    async def list_chat_candidates(
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        requested_graph_id: UUID | None,
        normalized_question: str | None,
        limit: int,
    ) -> tuple[KnowledgeChatCandidate, ...]:
        statement = (
            select(
                GraphModel,
                GraphModel.active_release_id,
                KnowledgeDeliveryPolicyModel,
            )
            .join(
                KnowledgeDeliveryPolicyModel,
                and_(
                    KnowledgeDeliveryPolicyModel.workspace_id == GraphModel.workspace_id,
                    KnowledgeDeliveryPolicyModel.graph_id == GraphModel.id,
                ),
            )
            .where(
                GraphModel.workspace_id == workspace_id,
                *self._scope(clearance=clearance, allowed_domain_ids=allowed_domain_ids),
                GraphModel.active_release_id.is_not(None),
                KnowledgeDeliveryPolicyModel.chat_enabled.is_(True),
            )
        )
        if requested_graph_id is not None:
            statement = statement.where(GraphModel.id == requested_graph_id)
        elif normalized_question is not None:
            any_terms = (
                func.jsonb_array_elements_text(KnowledgeDeliveryPolicyModel.match_any_terms)
                .table_valued("value")
                .alias("knowledge_any_terms")
            )
            all_terms = (
                func.jsonb_array_elements_text(KnowledgeDeliveryPolicyModel.match_all_terms)
                .table_valued("value")
                .alias("knowledge_all_terms")
            )
            excluded_terms = (
                func.jsonb_array_elements_text(KnowledgeDeliveryPolicyModel.excluded_terms)
                .table_valued("value")
                .alias("knowledge_excluded_terms")
            )
            statement = statement.where(
                or_(
                    func.jsonb_array_length(KnowledgeDeliveryPolicyModel.match_any_terms) == 0,
                    exists(
                        select(1)
                        .select_from(any_terms)
                        .where(
                            func.strpos(
                                literal(normalized_question),
                                any_terms.c.value,
                            )
                            > 0
                        )
                    ),
                ),
                ~exists(
                    select(1)
                    .select_from(all_terms)
                    .where(
                        func.strpos(
                            literal(normalized_question),
                            all_terms.c.value,
                        )
                        == 0
                    )
                ),
                ~exists(
                    select(1)
                    .select_from(excluded_terms)
                    .where(
                        func.strpos(
                            literal(normalized_question),
                            excluded_terms.c.value,
                        )
                        > 0
                    )
                ),
            )
        rows = (
            await self._session.execute(
                statement.order_by(
                    KnowledgeDeliveryPolicyModel.priority.desc(),
                    (
                        func.jsonb_array_length(KnowledgeDeliveryPolicyModel.match_any_terms)
                        + func.jsonb_array_length(KnowledgeDeliveryPolicyModel.match_all_terms)
                    ).desc(),
                    GraphModel.id,
                ).limit(limit)
            )
        ).all()
        values: list[KnowledgeChatCandidate] = []
        for graph, release_id, policy_model in rows:
            policy = _policy(policy_model)
            if release_id is None or policy is None:
                continue
            values.append(
                KnowledgeChatCandidate(
                    graph_id=graph.id,
                    release_id=release_id,
                    domain_id=graph.domain_ref_id,
                    classification=Classification(graph.classification),
                    delivery_policy=policy,
                )
            )
        return tuple(values)
