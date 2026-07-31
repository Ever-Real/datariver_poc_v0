from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from datariver.application.quality_command_contracts import (
    QualityAuthoringAsset,
    QualityCommonRuleTemplateCreateCommand,
    QualityCommonRuleTemplateCreateResult,
    QualityManualRunResult,
    QualityRuleCommandTarget,
    QualityRuleProposalCommand,
    QualityRuleProposalItem,
    QualityRuleProposalResult,
    QualityRuleVersionCommandResult,
)
from datariver.application.quality_command_ports import QualityCommandRepository
from datariver.application.quality_contracts import (
    QUALITY_COMPILER_HASH,
    QUALITY_SCORE_POLICY_HASH,
    QUALITY_SCORE_POLICY_ID,
    QUALITY_SCORE_POLICY_VERSION,
)
from datariver.application.quality_execution_contracts import (
    GX_COMPILER_CONTRACT,
    GX_RUNTIME_VERSION,
)
from datariver.domain.common import ConflictError, PreconditionFailedError, uuid7
from datariver.domain.quality import TargetBinding
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.quality import (
    QualityCommonRuleTemplateMappingModel,
    QualityCommonRuleTemplateModel,
    QualityRuleDefinitionModel,
    QualityRuleSetModel,
    QualityRuleSetVersionModel,
    QualityValidationRunModel,
)

_CREATE_OPERATION = "quality.rule_sets.batch_create.v1"
_CREATE_TEMPLATE_OPERATION = "quality.common_rule_template.create.v1"
_REVIEW_OPERATION = "quality.rule_version.review.v2"
_ACTIVATE_OPERATION = "quality.rule_version.activate.v2"
_MANUAL_RUN_OPERATION = "quality.manual_run.request.v1"


@dataclass(frozen=True, slots=True)
class _RetentionBinding:
    policy_id: UUID
    policy_number: int
    policy_hash: str
    retain_until: datetime
    hold_generation: int
    hold_hash: str


class SqlQualityCommandRepository(QualityCommandRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._idempotency = SqlIdempotencyStore(session)

    async def retention_ready(self, *, workspace_id: UUID) -> bool:
        value = await self._session.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM retention.policy_versions AS policy
                    WHERE policy.workspace_id = :workspace_id
                      AND policy.state = 'ACTIVE'
                      AND policy.contract_version IN ('POLICY_BOOK_V3', 'POLICY_BOOK_V4')
                      AND policy.effective_from <= transaction_timestamp()
                      AND (
                          policy.effective_until IS NULL
                          OR policy.effective_until > transaction_timestamp()
                      )
                      AND (
                          SELECT count(*)
                          FROM retention.policy_class_rules AS class_rule
                          WHERE class_rule.workspace_id = policy.workspace_id
                            AND class_rule.policy_id = policy.id
                            AND class_rule.policy_hash = policy.payload_hash
                            AND class_rule.policy_number = policy.policy_number
                            AND class_rule.data_class IN (
                                'QUALITY_RULE', 'QUALITY_RESULT', 'QUALITY_AUDIT'
                            )
                      ) = 3
                )
                """
            ),
            {"workspace_id": workspace_id},
        )
        return value is True

    async def get_authoring_assets(
        self,
        *,
        workspace_id: UUID,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[QualityAuthoringAsset, ...]:
        if not asset_ids:
            return ()
        rows = (
            await self._session.scalars(
                select(AssetProjectionModel).where(
                    AssetProjectionModel.workspace_id == workspace_id,
                    AssetProjectionModel.id.in_(asset_ids),
                    AssetProjectionModel.deleted_at.is_(None),
                )
            )
        ).all()
        return tuple(
            QualityAuthoringAsset(
                asset_id=row.id,
                name=row.name,
                system_id=row.system_id,
                domain_id=row.domain_id,
                classification=row.classification,
                lifecycle=row.lifecycle,
                source_version=row.source_version,
                column_names=tuple(row.column_names),
                column_names_truncated=row.column_names_truncated,
            )
            for row in rows
        )

    async def create_common_rule_template(
        self, *, command: QualityCommonRuleTemplateCreateCommand
    ) -> QualityCommonRuleTemplateCreateResult:
        await self._idempotency.acquire_key_lock(
            workspace_id=command.workspace_id,
            key=command.idempotency_key,
            operation=_CREATE_TEMPLATE_OPERATION,
        )
        existing = await self._idempotency.get_result(
            workspace_id=command.workspace_id,
            key=command.idempotency_key,
            operation=_CREATE_TEMPLATE_OPERATION,
        )
        if existing is not None:
            _require_idempotent_actor(
                existing.request_hash,
                existing.result,
                request_hash=command.request_hash,
                actor_id=command.actor_id,
            )
            return QualityCommonRuleTemplateCreateResult(
                template_id=UUID(str(existing.result["template_id"])),
                replayed=True,
            )
        template_id = uuid7()
        self._session.add(
            QualityCommonRuleTemplateModel(
                id=template_id,
                workspace_id=command.workspace_id,
                name=command.name,
                description=command.description,
                rules=[dict(rule) for rule in command.rules],
                created_by=command.actor_id,
            )
        )
        try:
            await self._session.flush()
            await self._idempotency.save_result(
                workspace_id=command.workspace_id,
                key=command.idempotency_key,
                operation=_CREATE_TEMPLATE_OPERATION,
                request_hash=command.request_hash,
                result={
                    "actor_id": str(command.actor_id),
                    "template_id": str(template_id),
                },
            )
            await self._session.commit()
        except DBAPIError as error:
            raise ConflictError(
                "The Quality common Rule template conflicts with current state."
            ) from error
        return QualityCommonRuleTemplateCreateResult(
            template_id=template_id,
            replayed=False,
        )

    async def get_common_rule_template_rules(
        self, *, workspace_id: UUID, template_id: UUID
    ) -> tuple[str, tuple[dict[str, object], ...]] | None:
        template = (
            await self._session.scalars(
                select(QualityCommonRuleTemplateModel).where(
                    QualityCommonRuleTemplateModel.workspace_id == workspace_id,
                    QualityCommonRuleTemplateModel.id == template_id,
                )
            )
        ).one_or_none()
        if template is None:
            return None
        return template.name, tuple(dict(rule) for rule in template.rules)

    async def create_rule_sets(
        self,
        *,
        command: QualityRuleProposalCommand,
    ) -> QualityRuleProposalResult:
        await self._idempotency.acquire_key_lock(
            workspace_id=command.workspace_id,
            key=command.idempotency_key,
            operation=_CREATE_OPERATION,
        )
        existing = await self._idempotency.get_result(
            workspace_id=command.workspace_id,
            key=command.idempotency_key,
            operation=_CREATE_OPERATION,
        )
        if existing is not None:
            _require_idempotent_actor(
                existing.request_hash,
                existing.result,
                request_hash=command.request_hash,
                actor_id=command.actor_id,
            )
            return QualityRuleProposalResult(
                items=tuple(
                    QualityRuleProposalItem(
                        asset_id=UUID(str(item["asset_id"])),
                        rule_set_id=UUID(str(item["rule_set_id"])),
                        version_id=UUID(str(item["version_id"])),
                        version=_result_version(item),
                    )
                    for item in _result_items(existing.result)
                ),
                replayed=True,
            )
        template = None
        if command.template_id is not None:
            template = (
                await self._session.scalars(
                    select(QualityCommonRuleTemplateModel)
                    .where(
                        QualityCommonRuleTemplateModel.workspace_id == command.workspace_id,
                        QualityCommonRuleTemplateModel.id == command.template_id,
                    )
                    .with_for_update(read=True)
                )
            ).one_or_none()
            if template is None:
                raise ConflictError("The Quality common Rule template is unavailable.")
        now = await self._database_now()
        items: list[QualityRuleProposalItem] = []
        try:
            for target in command.targets:
                current = (
                    await self._session.scalars(
                        select(AssetProjectionModel)
                        .where(
                            AssetProjectionModel.workspace_id == command.workspace_id,
                            AssetProjectionModel.id == target.asset.asset_id,
                            AssetProjectionModel.deleted_at.is_(None),
                            AssetProjectionModel.lifecycle == "ACTIVE",
                        )
                        .with_for_update(read=True)
                    )
                ).one_or_none()
                if (
                    current is None
                    or current.source_version != target.asset.source_version
                    or current.classification != target.asset.classification
                    or current.system_id != target.asset.system_id
                    or current.domain_id != target.asset.domain_id
                    or current.column_names_truncated
                    or set(current.column_names)
                    != {field.field_identifier for field in target.deployment.fields}
                ):
                    raise ConflictError("The Quality authoring target changed before commit.")
                rule_set_id = uuid7()
                version_id = uuid7()
                retention = await self._resolve_retention(
                    workspace_id=command.workspace_id,
                    data_class="QUALITY_RULE",
                    resource_type="QUALITY_RULE_SET",
                    resource_id=rule_set_id,
                    basis_at=now,
                )
                name = f"{command.name_prefix} · {current.name}"
                if len(name) > 255:
                    name = f"{command.name_prefix[:180]} · {str(current.id)[:36]}"
                target_binding = TargetBinding(
                    workspace_id=command.workspace_id,
                    asset_id=current.id,
                    system_id=current.system_id,
                    domain_id=current.domain_id,
                    classification=current.classification,
                    lifecycle=current.lifecycle,
                    source_version=current.source_version,
                    schema_hash=target.deployment.schema_hash,
                    source_connection_profile_id=(target.deployment.source_connection_profile_id),
                    source_connection_profile_version=(
                        target.deployment.source_connection_profile_version
                    ),
                    source_connection_profile_hash=(
                        target.deployment.source_connection_profile_hash
                    ),
                    workload_profile_id=target.deployment.workload_profile_id,
                    workload_profile_version=(target.deployment.workload_profile_version),
                    workload_profile_hash=target.deployment.workload_profile_hash,
                )
                self._session.add(
                    QualityRuleSetModel(
                        id=rule_set_id,
                        workspace_id=command.workspace_id,
                        asset_id=current.id,
                        name=name,
                        state="ACTIVE",
                        created_by=command.actor_id,
                        updated_by=command.actor_id,
                        archived_at=None,
                        rule_retention_kind="QUALITY_RULE",
                        rule_retention_policy_id=retention.policy_id,
                        rule_retention_policy_number=retention.policy_number,
                        rule_retention_policy_hash=retention.policy_hash,
                        rule_retention_basis_at=now,
                        rule_retain_until=retention.retain_until,
                        rule_hold_generation=retention.hold_generation,
                        rule_hold_hash=retention.hold_hash,
                        version=1,
                    )
                )
                self._session.add(
                    QualityRuleSetVersionModel(
                        id=version_id,
                        workspace_id=command.workspace_id,
                        rule_set_id=rule_set_id,
                        version_number=1,
                        author_id=command.actor_id,
                        state="PROPOSED",
                        asset_id=current.id,
                        system_id=current.system_id,
                        domain_id=current.domain_id,
                        classification=current.classification,
                        lifecycle=current.lifecycle,
                        source_version=current.source_version,
                        target_binding_hash=target_binding.binding_hash,
                        schema_hash=target.deployment.schema_hash,
                        source_connection_profile_id=(
                            target.deployment.source_connection_profile_id
                        ),
                        source_connection_profile_version=(
                            target.deployment.source_connection_profile_version
                        ),
                        source_connection_profile_hash=(
                            target.deployment.source_connection_profile_hash
                        ),
                        workload_profile_id=target.deployment.workload_profile_id,
                        workload_profile_version=(target.deployment.workload_profile_version),
                        workload_profile_hash=(target.deployment.workload_profile_hash),
                        compiler_contract_version=GX_COMPILER_CONTRACT,
                        gx_version=GX_RUNTIME_VERSION,
                        compiler_hash=QUALITY_COMPILER_HASH,
                        score_policy_id=QUALITY_SCORE_POLICY_ID,
                        score_policy_version=QUALITY_SCORE_POLICY_VERSION,
                        score_policy_hash=QUALITY_SCORE_POLICY_HASH,
                        schedule_mode="MANUAL_ONLY",
                        schedule_profile_id=None,
                        schedule_profile_version=None,
                        schedule_profile_hash=None,
                        rule_retention_kind="QUALITY_RULE",
                        rule_retention_policy_id=retention.policy_id,
                        rule_retention_policy_number=retention.policy_number,
                        rule_retention_policy_hash=retention.policy_hash,
                        rule_retention_basis_at=now,
                        rule_retain_until=retention.retain_until,
                        rule_hold_generation=retention.hold_generation,
                        rule_hold_hash=retention.hold_hash,
                        reviewed_by=None,
                        reviewed_at=None,
                        activated_by=None,
                        activated_at=None,
                        revoked_by=None,
                        revoked_at=None,
                        version=1,
                    )
                )
                for rule in target.rules:
                    self._session.add(
                        QualityRuleDefinitionModel(
                            id=rule.rule_id,
                            workspace_id=command.workspace_id,
                            rule_set_version_id=version_id,
                            ordinal=rule.ordinal,
                            field_identifier=rule.field_identifier,
                            kind=rule.kind.value,
                            severity=rule.severity.value,
                            parameters=rule.parameters,
                            definition_hash=rule.definition_hash,
                            rule_retention_kind="QUALITY_RULE",
                            rule_retention_policy_id=retention.policy_id,
                            rule_retention_policy_number=retention.policy_number,
                            rule_retention_policy_hash=retention.policy_hash,
                            rule_retain_until=retention.retain_until,
                            rule_hold_generation=retention.hold_generation,
                            rule_hold_hash=retention.hold_hash,
                        )
                    )
                if template is not None:
                    self._session.add(
                        QualityCommonRuleTemplateMappingModel(
                            id=uuid7(),
                            workspace_id=command.workspace_id,
                            template_id=template.id,
                            asset_id=current.id,
                            rule_set_id=rule_set_id,
                            mapped_by=command.actor_id,
                        )
                    )
                items.append(
                    QualityRuleProposalItem(
                        asset_id=current.id,
                        rule_set_id=rule_set_id,
                        version_id=version_id,
                        version=1,
                    )
                )
            await self._session.flush()
            result_document: dict[str, object] = {
                "actor_id": str(command.actor_id),
                "items": [
                    {
                        "asset_id": str(item.asset_id),
                        "rule_set_id": str(item.rule_set_id),
                        "version_id": str(item.version_id),
                        "version": item.version,
                    }
                    for item in items
                ],
            }
            await self._idempotency.save_result(
                workspace_id=command.workspace_id,
                key=command.idempotency_key,
                operation=_CREATE_OPERATION,
                request_hash=command.request_hash,
                result=result_document,
            )
            await self._session.commit()
        except DBAPIError as error:
            raise ConflictError(
                "The Quality Rule proposal conflicts with current state."
            ) from error
        return QualityRuleProposalResult(items=tuple(items), replayed=False)

    async def get_rule_command_target(
        self,
        *,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID | None,
    ) -> QualityRuleCommandTarget | None:
        statement = (
            select(
                QualityRuleSetModel,
                QualityRuleSetVersionModel,
                AssetProjectionModel,
            )
            .join(
                QualityRuleSetVersionModel,
                and_(
                    QualityRuleSetVersionModel.workspace_id == QualityRuleSetModel.workspace_id,
                    QualityRuleSetVersionModel.rule_set_id == QualityRuleSetModel.id,
                ),
            )
            .join(
                AssetProjectionModel,
                and_(
                    AssetProjectionModel.workspace_id == QualityRuleSetModel.workspace_id,
                    AssetProjectionModel.id == QualityRuleSetModel.asset_id,
                ),
            )
            .where(
                QualityRuleSetModel.workspace_id == workspace_id,
                QualityRuleSetModel.id == rule_set_id,
            )
        )
        if version_id is None:
            statement = statement.where(QualityRuleSetVersionModel.state == "ACTIVE")
        else:
            statement = statement.where(QualityRuleSetVersionModel.id == version_id)
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        rule_set, version, asset = row
        return QualityRuleCommandTarget(
            rule_set_id=rule_set.id,
            version_id=version.id,
            asset_id=asset.id,
            author_id=version.author_id,
            system_id=asset.system_id,
            domain_id=asset.domain_id,
            classification=asset.classification,
            lifecycle=asset.lifecycle,
            source_version=asset.source_version,
        )

    async def review_rule_set_version(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        decision: str,
        reason: str,
        expected_version: int,
        policy_decision_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> QualityRuleVersionCommandResult:
        return await self._version_command(
            workspace_id=workspace_id,
            actor_id=actor_id,
            rule_set_id=rule_set_id,
            version_id=version_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=_REVIEW_OPERATION,
            statement=text(
                """
                SELECT quality.review_rule_set_version_command_v2(
                    :workspace_id, :version_id, :decision, :reason,
                    :policy_decision_id, :expected_version
                )
                """
            ),
            parameters={
                "decision": decision,
                "reason": reason,
                "policy_decision_id": policy_decision_id,
                "expected_version": expected_version,
            },
        )

    async def activate_rule_set_version(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        expected_version: int,
        policy_decision_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> QualityRuleVersionCommandResult:
        return await self._version_command(
            workspace_id=workspace_id,
            actor_id=actor_id,
            rule_set_id=rule_set_id,
            version_id=version_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=_ACTIVATE_OPERATION,
            statement=text(
                """
                SELECT quality.activate_rule_set_version_command_v2(
                    :workspace_id, :version_id, :policy_decision_id,
                    :idempotency_key_hash, :expected_version
                )
                """
            ),
            parameters={
                "policy_decision_id": policy_decision_id,
                "idempotency_key_hash": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
                "expected_version": expected_version,
            },
        )

    async def request_manual_run(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        rule_set_id: UUID,
        policy_decision_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> QualityManualRunResult:
        await self._idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_MANUAL_RUN_OPERATION,
        )
        existing = await self._idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_MANUAL_RUN_OPERATION,
        )
        if existing is not None:
            _require_idempotent_actor(
                existing.request_hash,
                existing.result,
                request_hash=request_hash,
                actor_id=actor_id,
            )
            run_id = UUID(str(existing.result["run_id"]))
            run = await self._session.get(
                QualityValidationRunModel,
                run_id,
            )
            if run is None or run.workspace_id != workspace_id:
                raise ConflictError("The idempotent Quality Run is unavailable.")
            return QualityManualRunResult(
                run_id=run.id,
                state=run.state,
                created_at=run.created_at,
                replayed=True,
            )
        try:
            run_id = await self._session.scalar(
                text(
                    """
                    SELECT quality.request_manual_validation_run_v1(
                        :workspace_id, :rule_set_id, :policy_decision_id
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "rule_set_id": rule_set_id,
                    "policy_decision_id": policy_decision_id,
                },
            )
            if not isinstance(run_id, UUID):
                raise RuntimeError("The database returned an invalid Quality Run ID.")
            await self._idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=_MANUAL_RUN_OPERATION,
                request_hash=request_hash,
                result={"actor_id": str(actor_id), "run_id": str(run_id)},
            )
            await self._session.commit()
        except DBAPIError as error:
            raise ConflictError(
                "The Quality manual Run request conflicts with current state."
            ) from error
        run = await self._session.get(QualityValidationRunModel, run_id)
        if run is None:
            raise RuntimeError("The committed Quality Run is unavailable.")
        return QualityManualRunResult(
            run_id=run.id,
            state=run.state,
            created_at=run.created_at,
            replayed=False,
        )

    async def _version_command(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        idempotency_key: str,
        request_hash: str,
        operation: str,
        statement: TextClause,
        parameters: dict[str, object],
    ) -> QualityRuleVersionCommandResult:
        await self._idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        existing = await self._idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if existing is not None:
            _require_idempotent_actor(
                existing.request_hash,
                existing.result,
                request_hash=request_hash,
                actor_id=actor_id,
            )
            result_version_id = UUID(str(existing.result["version_id"]))
            if result_version_id != version_id:
                raise ConflictError("The idempotency key belongs to another Quality Version.")
            return await self._version_result(
                workspace_id=workspace_id,
                rule_set_id=rule_set_id,
                version_id=version_id,
            )
        locked_version = (
            await self._session.scalars(
                select(QualityRuleSetVersionModel)
                .where(
                    QualityRuleSetVersionModel.workspace_id == workspace_id,
                    QualityRuleSetVersionModel.rule_set_id == rule_set_id,
                    QualityRuleSetVersionModel.id == version_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        expected_version = parameters.get("expected_version")
        if (
            locked_version is not None
            and isinstance(expected_version, int)
            and locked_version.version != expected_version
        ):
            raise PreconditionFailedError("The Quality Rule Version has changed.")
        try:
            await self._session.scalar(
                statement,
                {
                    "workspace_id": workspace_id,
                    "version_id": version_id,
                    **parameters,
                },
            )
            await self._idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(actor_id),
                    "rule_set_id": str(rule_set_id),
                    "version_id": str(version_id),
                },
            )
            await self._session.commit()
        except DBAPIError as error:
            raise ConflictError("The Quality Rule command conflicts with current state.") from error
        return await self._version_result(
            workspace_id=workspace_id,
            rule_set_id=rule_set_id,
            version_id=version_id,
        )

    async def _version_result(
        self,
        *,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
    ) -> QualityRuleVersionCommandResult:
        version = await self._session.get(QualityRuleSetVersionModel, version_id)
        if (
            version is None
            or version.workspace_id != workspace_id
            or version.rule_set_id != rule_set_id
        ):
            raise ConflictError("The Quality Rule Version is unavailable.")
        return QualityRuleVersionCommandResult(
            rule_set_id=rule_set_id,
            version_id=version_id,
            state=version.state,
            version=version.version,
        )

    async def _resolve_retention(
        self,
        *,
        workspace_id: UUID,
        data_class: str,
        resource_type: str,
        resource_id: UUID,
        basis_at: datetime,
    ) -> _RetentionBinding:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT *
                    FROM retention.resolve_quality_binding_v1(
                        :workspace_id, :data_class, :resource_type,
                        :resource_id, :basis_at
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "data_class": data_class,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "basis_at": basis_at,
                },
            )
        ).one()
        return _RetentionBinding(
            policy_id=row.policy_id,
            policy_number=int(row.policy_number),
            policy_hash=str(row.policy_hash),
            retain_until=row.retain_until,
            hold_generation=int(row.hold_generation),
            hold_hash=str(row.hold_hash),
        )

    async def _database_now(self) -> datetime:
        value = await self._session.scalar(select(func.transaction_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("The database did not return a Quality transaction clock.")
        return value


def _require_idempotent_actor(
    existing_hash: str,
    result: dict[str, object],
    *,
    request_hash: str,
    actor_id: UUID,
) -> None:
    if existing_hash != request_hash:
        raise ConflictError("The idempotency key was reused with another request.")
    if result.get("actor_id") != str(actor_id):
        raise ConflictError("The idempotency key belongs to another actor.")


def _result_items(result: dict[str, object]) -> tuple[dict[str, object], ...]:
    value = result.get("items")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConflictError("The idempotent Quality result is invalid.")
    return tuple(value)


def _result_version(result: dict[str, object]) -> int:
    value = result.get("version")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConflictError("The idempotent Quality result is invalid.")
    return value
