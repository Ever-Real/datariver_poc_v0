from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.application.dto import (
    ChangeRequestAssigneeRecord,
    ChangeRequestSchemaOverview,
)
from datariver.application.ports import ChangeRequestOverviewReader
from datariver.domain.authz import SubjectAttributes
from datariver.domain.governance import ChangeRequest, ChangeState
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.platform import (
    DataSystemModel,
    SubjectModel,
    SystemAssigneeModel,
    SystemSchemaScopeModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context

SchemaKey = tuple[str, str, str]


class SqlChangeRequestOverviewReader(ChangeRequestOverviewReader):
    """Build the legacy-recognizable summary from authorized canonical projections.

    The reader deliberately receives already-authorized CR aggregates and reuses the exact catalog
    discovery predicate for zero-count schema rows.  It never fills missing system or assignee data
    with a browser-owned default.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_schema_overview(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        change_requests: Sequence[ChangeRequest],
    ) -> Sequence[ChangeRequestSchemaOverview]:
        await set_security_context(
            self._session,
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
        )
        catalog_reader = SqlCatalogIndexReader(self._session)
        visible_conditions = catalog_reader._scope_conditions(subject, access)

        schema_rows = (
            await self._session.execute(
                select(
                    AssetProjectionModel.platform,
                    AssetProjectionModel.database_name,
                    AssetProjectionModel.schema_name,
                    AssetProjectionModel.system_id,
                )
                .where(
                    and_(*visible_conditions),
                    AssetProjectionModel.platform.is_not(None),
                    AssetProjectionModel.database_name.is_not(None),
                    AssetProjectionModel.schema_name.is_not(None),
                )
                .group_by(
                    AssetProjectionModel.platform,
                    AssetProjectionModel.database_name,
                    AssetProjectionModel.schema_name,
                    AssetProjectionModel.system_id,
                )
            )
        ).all()

        schemas: dict[SchemaKey, UUID | None] = {}
        for platform, database_name, schema_name, system_id in schema_rows:
            if platform is None or database_name is None or schema_name is None:
                continue
            schemas[(platform, database_name, schema_name)] = system_id

        scope_rows = (
            await self._session.execute(
                select(SystemSchemaScopeModel, DataSystemModel)
                .join(
                    DataSystemModel,
                    and_(
                        DataSystemModel.workspace_id == SystemSchemaScopeModel.workspace_id,
                        DataSystemModel.id == SystemSchemaScopeModel.system_id,
                    ),
                )
                .where(
                    SystemSchemaScopeModel.workspace_id == subject.workspace_id,
                    SystemSchemaScopeModel.active.is_(True),
                    DataSystemModel.active.is_(True),
                )
            )
        ).all()
        systems: dict[UUID, DataSystemModel] = {}
        for scope, system in scope_rows:
            scope_key = (scope.platform, scope.database_name, scope.schema_name)
            if scope_key in schemas:
                schemas[scope_key] = system.id
                systems[system.id] = system

        mapped_system_ids = {system_id for system_id in schemas.values() if system_id is not None}
        if mapped_system_ids:
            additional_systems = (
                await self._session.scalars(
                    select(DataSystemModel).where(
                        DataSystemModel.workspace_id == subject.workspace_id,
                        DataSystemModel.id.in_(mapped_system_ids),
                        DataSystemModel.active.is_(True),
                    )
                )
            ).all()
            systems.update({system.id: system for system in additional_systems})

        assignees_by_system: dict[UUID, list[ChangeRequestAssigneeRecord]] = defaultdict(list)
        if systems:
            assignee_rows = (
                await self._session.execute(
                    select(SystemAssigneeModel, SubjectModel)
                    .join(
                        SubjectModel,
                        SubjectModel.id == SystemAssigneeModel.subject_id,
                    )
                    .join(
                        WorkspaceMembershipModel,
                        and_(
                            WorkspaceMembershipModel.workspace_id
                            == SystemAssigneeModel.workspace_id,
                            WorkspaceMembershipModel.subject_id == SystemAssigneeModel.subject_id,
                        ),
                    )
                    .where(
                        SystemAssigneeModel.workspace_id == subject.workspace_id,
                        SystemAssigneeModel.system_id.in_(systems),
                        SystemAssigneeModel.active.is_(True),
                        SubjectModel.active.is_(True),
                        WorkspaceMembershipModel.active.is_(True),
                    )
                    .order_by(
                        SystemAssigneeModel.system_id,
                        SystemAssigneeModel.priority,
                        SystemAssigneeModel.responsibility,
                        SubjectModel.display_name,
                        SubjectModel.id,
                    )
                )
            ).all()
            for assignment, subject_model in assignee_rows:
                assignees_by_system[assignment.system_id].append(
                    ChangeRequestAssigneeRecord(
                        subject_id=subject_model.id,
                        display_name=subject_model.display_name,
                        responsibility=assignment.responsibility,
                        priority=assignment.priority,
                    )
                )

        target_ids = {
            item.target_asset_id
            for change_request in change_requests
            for item in change_request.items
            if item.target_asset_id is not None
        }
        asset_schemas: dict[UUID, SchemaKey] = {}
        if target_ids:
            target_rows = (
                await self._session.execute(
                    select(
                        AssetProjectionModel.id,
                        AssetProjectionModel.platform,
                        AssetProjectionModel.database_name,
                        AssetProjectionModel.schema_name,
                    ).where(
                        AssetProjectionModel.id.in_(target_ids),
                        and_(*visible_conditions),
                    )
                )
            ).all()
            for asset_id, platform, database_name, schema_name in target_rows:
                if platform is None or database_name is None or schema_name is None:
                    continue
                key = (platform, database_name, schema_name)
                schemas.setdefault(key, None)
                asset_schemas[asset_id] = key

        counts: dict[SchemaKey, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for change_request in change_requests:
            for item in change_request.items:
                if item.target_asset_id is None:
                    continue
                schema_key = asset_schemas.get(item.target_asset_id)
                if schema_key is None:
                    continue
                bucket = counts[schema_key]
                bucket["total"] += 1
                if change_request.state is ChangeState.REGISTERED:
                    bucket["pending"] += 1
                    bucket["received"] += 1
                elif change_request.state is ChangeState.IN_REVIEW:
                    bucket["received"] += 1
                elif change_request.state in {ChangeState.CHANGES_REQUESTED, ChangeState.REJECTED}:
                    bucket["recheck"] += 1
                elif change_request.state in {
                    ChangeState.TESTING,
                    ChangeState.APPLY_QUEUED,
                    ChangeState.APPLYING,
                    ChangeState.APPLY_FAILED,
                }:
                    bucket["testing"] += 1
                elif change_request.state is ChangeState.FINAL_REVIEW:
                    bucket["final_review"] += 1
                elif change_request.state is ChangeState.APPLIED:
                    bucket["completed"] += 1

        rows: list[ChangeRequestSchemaOverview] = []
        for schema_key in sorted(
            schemas,
            key=lambda value: tuple(part.casefold() for part in value),
        ):
            system_id = schemas[schema_key]
            system = systems.get(system_id) if system_id is not None else None
            bucket = counts[schema_key]
            rows.append(
                ChangeRequestSchemaOverview(
                    platform=schema_key[0],
                    database_name=schema_key[1],
                    schema_name=schema_key[2],
                    system_id=system.id if system is not None else None,
                    system_code=system.code if system is not None else None,
                    system_name=system.name if system is not None else None,
                    assignees=tuple(assignees_by_system.get(system.id, ())) if system else (),
                    pending_count=bucket["pending"],
                    total_count=bucket["total"],
                    received_count=bucket["received"],
                    recheck_count=bucket["recheck"],
                    testing_count=bucket["testing"],
                    final_review_count=bucket["final_review"],
                    completed_count=bucket["completed"],
                )
            )
        return tuple(rows)
