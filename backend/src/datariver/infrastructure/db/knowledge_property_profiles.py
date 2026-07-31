from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from datariver.application.dto import IdempotencyRecord
from datariver.application.knowledge_property_profiles import (
    KnowledgePropertyProfileItem,
    KnowledgePropertyProfileRepository,
)
from datariver.domain.common import ConflictError, NotFoundError, utc_now, uuid7
from datariver.domain.knowledge_property_profiles import (
    KnowledgePropertyProfile,
    KnowledgePropertyTarget,
    PropertyProfileLifecycle,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.knowledge import GraphModel
from datariver.infrastructure.db.models.knowledge_studio import (
    KnowledgePropertyProfileModel,
    KnowledgePropertyProfileSynonymModel,
    KnowledgeStudioReleaseModel,
    OntologyElementModel,
)

CREATE_OPERATION = "kg.property-profile.create.v1"
UPDATE_OPERATION = "kg.property-profile.update.v1"
ARCHIVE_OPERATION = "kg.property-profile.archive.v1"


def _string(document: dict[str, object], key: str, fallback: str = "") -> str:
    value = document.get(key)
    return value if isinstance(value, str) else fallback


def _required_element_value(
    document: dict[str, object],
    key: str,
    *,
    label: str,
) -> str:
    value = _string(document, key).strip()
    if not value:
        raise ConflictError(f"The released Property {label} is missing.")
    return value


def _literal_contains_pattern(value: str) -> str:
    escaped = value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _profile_result(profile: KnowledgePropertyProfile) -> dict[str, object]:
    return {
        "profile_id": str(profile.profile_id),
        "workspace_id": str(profile.workspace_id),
        "graph_id": str(profile.graph_id),
        "studio_release_id": str(profile.studio_release_id),
        "ontology_version_id": str(profile.ontology_version_id),
        "ontology_element_id": str(profile.ontology_element_id),
        "stable_property_id": profile.stable_property_id,
        "description": profile.description,
        "unit": profile.unit,
        "synonyms": list(profile.synonyms),
        "lifecycle": profile.lifecycle.value,
        "created_by": str(profile.created_by),
        "updated_by": str(profile.updated_by),
        "archived_by": str(profile.archived_by) if profile.archived_by else None,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
        "archived_at": profile.archived_at.isoformat() if profile.archived_at else None,
        "version": profile.version,
    }


def _profile_from_result(document: dict[str, object]) -> KnowledgePropertyProfile:
    try:
        raw_synonyms = document["synonyms"]
        if not isinstance(raw_synonyms, list) or any(
            not isinstance(value, str) for value in raw_synonyms
        ):
            raise ValueError
        archived_by = document.get("archived_by")
        archived_at = document.get("archived_at")
        description = document.get("description")
        unit = document.get("unit")
        if description is not None and not isinstance(description, str):
            raise ValueError
        if unit is not None and not isinstance(unit, str):
            raise ValueError
        return KnowledgePropertyProfile(
            profile_id=UUID(str(document["profile_id"])),
            workspace_id=UUID(str(document["workspace_id"])),
            graph_id=UUID(str(document["graph_id"])),
            studio_release_id=UUID(str(document["studio_release_id"])),
            ontology_version_id=UUID(str(document["ontology_version_id"])),
            ontology_element_id=UUID(str(document["ontology_element_id"])),
            stable_property_id=str(document["stable_property_id"]),
            description=description,
            unit=unit,
            synonyms=tuple(raw_synonyms),
            lifecycle=PropertyProfileLifecycle(str(document["lifecycle"])),
            created_by=UUID(str(document["created_by"])),
            updated_by=UUID(str(document["updated_by"])),
            archived_by=UUID(str(archived_by)) if archived_by else None,
            created_at=datetime.fromisoformat(str(document["created_at"])),
            updated_at=datetime.fromisoformat(str(document["updated_at"])),
            archived_at=datetime.fromisoformat(str(archived_at)) if archived_at else None,
            version=int(str(document["version"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ConflictError("The idempotent Property profile result is invalid.") from error


def _replay(
    existing: IdempotencyRecord | None,
    *,
    workspace_id: UUID,
    request_hash: str,
) -> KnowledgePropertyProfile | None:
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise ConflictError("The idempotency key was used with a different request.")
    profile = _profile_from_result(existing.result)
    if profile.workspace_id != workspace_id:
        raise ConflictError("The idempotent Property profile result belongs to another Workspace.")
    return profile


class SqlKnowledgePropertyProfileRepository(KnowledgePropertyProfileRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _target(
        graph: GraphModel,
        release: KnowledgeStudioReleaseModel,
        element: OntologyElementModel,
    ) -> KnowledgePropertyTarget:
        document = element.element_document
        return KnowledgePropertyTarget(
            workspace_id=graph.workspace_id,
            graph_id=graph.id,
            graph_name=graph.name,
            studio_release_id=release.id,
            release_no=release.release_no,
            ontology_version_id=element.ontology_version_id,
            ontology_element_id=element.id,
            stable_property_id=element.stable_element_id,
            property_name=element.display_name,
            owner_class_id=_required_element_value(
                document,
                "parent_stable_element_id",
                label="owner Class reference",
            ),
            data_type=_required_element_value(
                document,
                "data_type",
                label="data type",
            ),
            property_urn=f"urn:uuid:{element.id}",
            classification=graph.classification,
            domain_id=graph.domain_ref_id,
        )

    async def _synonyms(
        self,
        *,
        workspace_id: UUID,
        profile_ids: tuple[UUID, ...],
    ) -> dict[UUID, tuple[str, ...]]:
        if not profile_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    KnowledgePropertyProfileSynonymModel.profile_id,
                    KnowledgePropertyProfileSynonymModel.value,
                )
                .where(
                    KnowledgePropertyProfileSynonymModel.workspace_id == workspace_id,
                    KnowledgePropertyProfileSynonymModel.profile_id.in_(profile_ids),
                )
                .order_by(
                    KnowledgePropertyProfileSynonymModel.profile_id,
                    KnowledgePropertyProfileSynonymModel.normalized_value,
                )
            )
        ).all()
        values: dict[UUID, list[str]] = {}
        for profile_id, value in rows:
            values.setdefault(profile_id, []).append(value)
        return {key: tuple(items) for key, items in values.items()}

    @staticmethod
    def _profile(
        model: KnowledgePropertyProfileModel,
        synonyms: tuple[str, ...],
    ) -> KnowledgePropertyProfile:
        return KnowledgePropertyProfile(
            profile_id=model.id,
            workspace_id=model.workspace_id,
            graph_id=model.graph_id,
            studio_release_id=model.studio_release_id,
            ontology_version_id=model.ontology_version_id,
            ontology_element_id=model.ontology_element_id,
            stable_property_id=model.stable_property_id,
            description=model.description,
            unit=model.unit,
            synonyms=synonyms,
            lifecycle=PropertyProfileLifecycle(model.lifecycle),
            created_by=model.created_by,
            updated_by=model.updated_by,
            archived_by=model.archived_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
            archived_at=model.archived_at,
            version=model.version,
        )

    @staticmethod
    def _target_statement(workspace_id: UUID) -> Select[Any]:
        return (
            select(GraphModel, KnowledgeStudioReleaseModel, OntologyElementModel)
            .join(
                KnowledgeStudioReleaseModel,
                (
                    (KnowledgeStudioReleaseModel.workspace_id == GraphModel.workspace_id)
                    & (KnowledgeStudioReleaseModel.id == GraphModel.active_studio_release_id)
                    & (KnowledgeStudioReleaseModel.graph_id == GraphModel.id)
                ),
            )
            .join(
                OntologyElementModel,
                (
                    (OntologyElementModel.workspace_id == GraphModel.workspace_id)
                    & (
                        OntologyElementModel.ontology_version_id
                        == KnowledgeStudioReleaseModel.ontology_version_id
                    )
                    & (OntologyElementModel.graph_id == GraphModel.id)
                ),
            )
            .where(
                GraphModel.workspace_id == workspace_id,
                GraphModel.status == "PUBLISHED",
                KnowledgeStudioReleaseModel.state == "ACTIVE",
                OntologyElementModel.kind == "PROPERTY",
            )
        )

    async def list_items(
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
        query: str,
        limit: int,
    ) -> tuple[KnowledgePropertyProfileItem, ...]:
        scope = [
            GraphModel.classification <= clearance,
            or_(
                GraphModel.classification == 0,
                GraphModel.domain_ref_id.is_(None),
                GraphModel.domain_ref_id.in_(tuple(allowed_domain_ids)),
            ),
        ]
        if query:
            pattern = _literal_contains_pattern(query)
            scope.append(
                or_(
                    func.lower(GraphModel.name).like(pattern, escape="\\"),
                    func.lower(OntologyElementModel.display_name).like(pattern, escape="\\"),
                    func.lower(OntologyElementModel.canonical_name).like(pattern, escape="\\"),
                    func.lower(OntologyElementModel.stable_element_id).like(pattern, escape="\\"),
                )
            )
        target_rows = (
            await self._session.execute(
                self._target_statement(workspace_id)
                .where(*scope)
                .order_by(
                    GraphModel.name,
                    KnowledgeStudioReleaseModel.release_no.desc(),
                    OntologyElementModel.ordinal,
                )
                .limit(limit)
            )
        ).all()
        element_ids = tuple(row[2].id for row in target_rows)
        profile_models = (
            tuple(
                (
                    await self._session.scalars(
                        select(KnowledgePropertyProfileModel).where(
                            KnowledgePropertyProfileModel.workspace_id == workspace_id,
                            KnowledgePropertyProfileModel.ontology_element_id.in_(element_ids),
                            KnowledgePropertyProfileModel.lifecycle
                            == PropertyProfileLifecycle.ACTIVE.value,
                        )
                    )
                ).all()
            )
            if element_ids
            else ()
        )
        profile_by_element = {item.ontology_element_id: item for item in profile_models}
        synonym_by_profile = await self._synonyms(
            workspace_id=workspace_id,
            profile_ids=tuple(item.id for item in profile_models),
        )
        return tuple(
            KnowledgePropertyProfileItem(
                target=self._target(graph, release, element),
                profile=(
                    self._profile(
                        profile_by_element[element.id],
                        synonym_by_profile.get(profile_by_element[element.id].id, ()),
                    )
                    if element.id in profile_by_element
                    else None
                ),
            )
            for graph, release, element in target_rows
        )

    async def get_target(
        self,
        *,
        workspace_id: UUID,
        ontology_element_id: UUID,
    ) -> KnowledgePropertyTarget | None:
        row = (
            await self._session.execute(
                self._target_statement(workspace_id).where(
                    OntologyElementModel.id == ontology_element_id,
                )
            )
        ).one_or_none()
        return self._target(*row) if row is not None else None

    async def get_target_for_profile(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
    ) -> KnowledgePropertyTarget | None:
        element_id = await self._session.scalar(
            select(KnowledgePropertyProfileModel.ontology_element_id).where(
                KnowledgePropertyProfileModel.workspace_id == workspace_id,
                KnowledgePropertyProfileModel.id == profile_id,
            )
        )
        return (
            await self.get_target(
                workspace_id=workspace_id,
                ontology_element_id=element_id,
            )
            if element_id is not None
            else None
        )

    def _add_synonyms(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
        synonyms: tuple[str, ...],
        created_at: datetime,
    ) -> None:
        self._session.add_all(
            [
                KnowledgePropertyProfileSynonymModel(
                    id=uuid7(),
                    workspace_id=workspace_id,
                    profile_id=profile_id,
                    value=value,
                    normalized_value=value.casefold(),
                    created_at=created_at,
                )
                for value in synonyms
            ]
        )

    async def _lock_active_target(self, target: KnowledgePropertyTarget) -> None:
        active_release_id = await self._session.scalar(
            select(GraphModel.active_studio_release_id)
            .where(
                GraphModel.workspace_id == target.workspace_id,
                GraphModel.id == target.graph_id,
                GraphModel.status == "PUBLISHED",
            )
            .with_for_update()
        )
        if active_release_id != target.studio_release_id:
            raise ConflictError(
                "The active Studio Release changed; reload the Property before saving."
            )

    async def create_profile(
        self,
        *,
        target: KnowledgePropertyTarget,
        actor_id: UUID,
        description: str | None,
        unit: str | None,
        synonyms: tuple[str, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgePropertyProfile:
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=target.workspace_id,
            key=idempotency_key,
            operation=CREATE_OPERATION,
        )
        replay = _replay(
            await idempotency.get_result(
                workspace_id=target.workspace_id,
                key=idempotency_key,
                operation=CREATE_OPERATION,
            ),
            workspace_id=target.workspace_id,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        await self._lock_active_target(target)
        existing = await self._session.scalar(
            select(KnowledgePropertyProfileModel.id).where(
                KnowledgePropertyProfileModel.workspace_id == target.workspace_id,
                KnowledgePropertyProfileModel.ontology_element_id == target.ontology_element_id,
                KnowledgePropertyProfileModel.lifecycle == PropertyProfileLifecycle.ACTIVE.value,
            )
        )
        if existing is not None:
            raise ConflictError("The released Property already has a managed profile.")
        now = utc_now()
        model = KnowledgePropertyProfileModel(
            id=uuid7(),
            workspace_id=target.workspace_id,
            graph_id=target.graph_id,
            studio_release_id=target.studio_release_id,
            ontology_version_id=target.ontology_version_id,
            ontology_element_id=target.ontology_element_id,
            element_kind="PROPERTY",
            stable_property_id=target.stable_property_id,
            description=description,
            unit=unit,
            lifecycle=PropertyProfileLifecycle.ACTIVE.value,
            created_by=actor_id,
            updated_by=actor_id,
            archived_at=None,
            archived_by=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._session.add(model)
        self._add_synonyms(
            workspace_id=target.workspace_id,
            profile_id=model.id,
            synonyms=synonyms,
            created_at=now,
        )
        profile = self._profile(model, synonyms)
        await idempotency.save_result(
            workspace_id=target.workspace_id,
            key=idempotency_key,
            operation=CREATE_OPERATION,
            request_hash=request_hash,
            result=_profile_result(profile),
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The Property profile could not be created.") from error
        return profile

    async def update_profile(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
        actor_id: UUID,
        description: str | None,
        unit: str | None,
        synonyms: tuple[str, ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgePropertyTarget, KnowledgePropertyProfile]:
        target = await self.get_target_for_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
        )
        if target is None:
            raise NotFoundError("The Property profile does not exist.")
        await self._lock_active_target(target)
        profile = await self._mutate_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
            actor_id=actor_id,
            description=description,
            unit=unit,
            synonyms=synonyms,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=UPDATE_OPERATION,
            archive=False,
        )
        return target, profile

    async def archive_profile(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
        actor_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgePropertyTarget, KnowledgePropertyProfile]:
        target = await self.get_target_for_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
        )
        if target is None:
            raise NotFoundError("The Property profile does not exist.")
        await self._lock_active_target(target)
        profile = await self._mutate_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
            actor_id=actor_id,
            description=None,
            unit=None,
            synonyms=(),
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=ARCHIVE_OPERATION,
            archive=True,
        )
        return target, profile

    async def _mutate_profile(
        self,
        *,
        workspace_id: UUID,
        profile_id: UUID,
        actor_id: UUID,
        description: str | None,
        unit: str | None,
        synonyms: tuple[str, ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        operation: str,
        archive: bool,
    ) -> KnowledgePropertyProfile:
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        replay = _replay(
            await idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            ),
            workspace_id=workspace_id,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        model = await self._session.scalar(
            select(KnowledgePropertyProfileModel)
            .where(
                KnowledgePropertyProfileModel.workspace_id == workspace_id,
                KnowledgePropertyProfileModel.id == profile_id,
            )
            .with_for_update()
        )
        if model is None:
            raise NotFoundError("The Property profile does not exist.")
        if model.version != expected_version:
            raise ConflictError("The Property profile changed; reload it before saving.")
        if model.lifecycle != PropertyProfileLifecycle.ACTIVE.value:
            raise ConflictError("An archived Property profile cannot be changed.")
        now = utc_now()
        if archive:
            existing_synonyms = await self._synonyms(
                workspace_id=workspace_id,
                profile_ids=(profile_id,),
            )
            model.lifecycle = PropertyProfileLifecycle.ARCHIVED.value
            model.archived_at = now
            model.archived_by = actor_id
            current_synonyms = existing_synonyms.get(profile_id, ())
        else:
            model.description = description
            model.unit = unit
            await self._session.execute(
                delete(KnowledgePropertyProfileSynonymModel).where(
                    KnowledgePropertyProfileSynonymModel.workspace_id == workspace_id,
                    KnowledgePropertyProfileSynonymModel.profile_id == profile_id,
                )
            )
            self._add_synonyms(
                workspace_id=workspace_id,
                profile_id=profile_id,
                synonyms=synonyms,
                created_at=now,
            )
            current_synonyms = synonyms
        model.updated_by = actor_id
        model.updated_at = now
        model.version += 1
        profile = self._profile(model, current_synonyms)
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result=_profile_result(profile),
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The Property profile could not be changed.") from error
        return profile
