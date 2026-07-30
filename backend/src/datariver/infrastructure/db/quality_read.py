from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    Row,
    and_,
    desc,
    func,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.quality_read_contracts import (
    ProfileReadiness,
    QualityAssetPage,
    QualityAssetSummary,
    QualityIssuePage,
    QualityIssueSummary,
    QualityOverview,
    QualityReadContext,
    QualityResultPage,
    QualityResultSummary,
    QualityRuleDefinitionSummary,
    QualityRuleSetDetail,
    QualityRuleSetPage,
    QualityRuleSetSummary,
    QualityRuleVersionSummary,
    QualityRunPage,
    QualityRunSummary,
    QualityTrendPoint,
)
from datariver.application.quality_read_ports import QualityReadRepository
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.infrastructure.db.catalog_visibility import catalog_asset_scope_conditions
from datariver.infrastructure.db.models.catalog import (
    AssetProfileSnapshotModel,
    AssetProjectionModel,
)
from datariver.infrastructure.db.models.quality import (
    QualityExpectationResultModel,
    QualityRuleDefinitionModel,
    QualityRuleSetModel,
    QualityRuleSetVersionModel,
    QualityValidationRunModel,
)

_CURSOR_MAX_LENGTH = 2_000
_TERMINAL_STATES = ("SUCCEEDED", "FAILED", "STALE", "CANCELLED")


class SqlQualityReadRepository(QualityReadRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def database_now(self) -> datetime:
        value = await self._session.scalar(select(func.transaction_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("The database did not return an aware Quality clock.")
        return value

    async def overview(self, *, context: QualityReadContext, days: int) -> QualityOverview:
        visible = self._visible_assets(context).subquery("visible_quality_assets")
        active_versions = (
            select(
                QualityRuleSetModel.id.label("rule_set_id"),
                QualityRuleSetVersionModel.id.label("version_id"),
            )
            .join(
                visible,
                visible.c.id == QualityRuleSetModel.asset_id,
            )
            .join(
                QualityRuleSetVersionModel,
                and_(
                    QualityRuleSetVersionModel.workspace_id == QualityRuleSetModel.workspace_id,
                    QualityRuleSetVersionModel.rule_set_id == QualityRuleSetModel.id,
                    QualityRuleSetVersionModel.state == "ACTIVE",
                ),
            )
            .where(
                QualityRuleSetModel.workspace_id == context.subject.workspace_id,
                QualityRuleSetModel.state == "ACTIVE",
            )
        ).subquery("active_quality_versions")
        active_count = int(
            await self._session.scalar(select(func.count()).select_from(active_versions)) or 0
        )
        ranked_runs = (
            select(
                QualityValidationRunModel.rule_set_id,
                QualityValidationRunModel.rule_set_version_id,
                QualityValidationRunModel.state,
                QualityValidationRunModel.passed_count,
                QualityValidationRunModel.advisory_failed_count,
                QualityValidationRunModel.blocking_failed_count,
                func.row_number()
                .over(
                    partition_by=QualityValidationRunModel.rule_set_version_id,
                    order_by=(
                        desc(QualityValidationRunModel.completed_at),
                        desc(QualityValidationRunModel.id),
                    ),
                )
                .label("ordinal"),
            )
            .join(
                active_versions,
                active_versions.c.version_id == QualityValidationRunModel.rule_set_version_id,
            )
            .where(QualityValidationRunModel.state.in_(_TERMINAL_STATES))
        ).subquery("ranked_quality_runs")
        aggregate = (
            await self._session.execute(
                select(
                    func.count()
                    .filter(
                        and_(
                            ranked_runs.c.ordinal == 1,
                            ranked_runs.c.state == "SUCCEEDED",
                        )
                    )
                    .label("evaluated_rule_sets"),
                    func.coalesce(
                        func.sum(ranked_runs.c.passed_count).filter(
                            and_(
                                ranked_runs.c.ordinal == 1,
                                ranked_runs.c.state == "SUCCEEDED",
                            )
                        ),
                        0,
                    ).label("passed"),
                    func.coalesce(
                        func.sum(ranked_runs.c.advisory_failed_count).filter(
                            and_(
                                ranked_runs.c.ordinal == 1,
                                ranked_runs.c.state == "SUCCEEDED",
                            )
                        ),
                        0,
                    ).label("advisory"),
                    func.coalesce(
                        func.sum(ranked_runs.c.blocking_failed_count).filter(
                            and_(
                                ranked_runs.c.ordinal == 1,
                                ranked_runs.c.state == "SUCCEEDED",
                            )
                        ),
                        0,
                    ).label("blocking"),
                )
            )
        ).one()
        evaluated_rule_sets = int(aggregate.evaluated_rule_sets or 0)
        passed = int(aggregate.passed or 0)
        advisory = int(aggregate.advisory or 0)
        blocking = int(aggregate.blocking or 0)
        evaluated_rules = passed + advisory + blocking
        trend = await self._trend(
            context=context,
            visible=visible,
            since=context.observed_at - timedelta(days=days),
        )
        return QualityOverview(
            availability="AVAILABLE",
            freshness="CURRENT",
            as_of=context.observed_at,
            authorization_valid_until=context.authorization_valid_until,
            overall_state=_outcome(
                evaluated=evaluated_rules,
                advisory_failed=advisory,
                blocking_failed=blocking,
            ),
            active_rule_set_count=active_count,
            evaluated_rule_set_count=evaluated_rule_sets,
            unknown_rule_set_count=max(0, active_count - evaluated_rule_sets),
            passed_count=passed,
            advisory_failed_count=advisory,
            blocking_failed_count=blocking,
            evaluated_rule_count=evaluated_rules,
            score_basis_points=_basis_points(passed, evaluated_rules),
            coverage_basis_points=_basis_points(evaluated_rule_sets, active_count),
            trend=trend,
        )

    async def list_assets(
        self, *, context: QualityReadContext, limit: int, cursor: str | None
    ) -> QualityAssetPage:
        conditions = catalog_asset_scope_conditions(context.subject, context.access)
        if cursor:
            boundary = _decode_cursor(
                cursor,
                resource="assets",
                context=context,
                limit=limit,
            )
            name = _required_string(boundary, "name")
            asset_id = _required_uuid(boundary, "id")
            conditions.append(
                or_(
                    AssetProjectionModel.name > name,
                    and_(
                        AssetProjectionModel.name == name,
                        AssetProjectionModel.id > asset_id,
                    ),
                )
            )
        rows = list(
            (
                await self._session.scalars(
                    select(AssetProjectionModel)
                    .where(and_(*conditions))
                    .order_by(AssetProjectionModel.name, AssetProjectionModel.id)
                    .limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        selected = rows[:limit]
        asset_ids = tuple(row.id for row in selected)
        counts = await self._active_rule_set_counts(
            workspace_id=context.subject.workspace_id,
            asset_ids=asset_ids,
        )
        latest_runs = await self._latest_runs_by_asset(
            workspace_id=context.subject.workspace_id,
            asset_ids=asset_ids,
        )
        profiles = (
            await self._latest_profiles(
                workspace_id=context.subject.workspace_id,
                asset_ids=asset_ids,
            )
            if context.profile_allowed
            else {}
        )
        items = tuple(
            QualityAssetSummary(
                asset_id=row.id,
                name=row.name,
                platform=row.platform,
                database_name=row.database_name,
                schema_name=row.schema_name,
                classification=Classification(row.classification).name,
                lifecycle=row.lifecycle,
                active_rule_set_count=counts.get(row.id, 0),
                latest_run_state=(latest_runs[row.id].state if row.id in latest_runs else None),
                latest_quality_outcome=(
                    latest_runs[row.id].quality_outcome if row.id in latest_runs else None
                ),
                latest_score_basis_points=(
                    _run_basis_points(latest_runs[row.id]) if row.id in latest_runs else None
                ),
                profile_readiness=(
                    _profile_readiness(
                        profile=profiles.get(row.id),
                        observed_at=context.observed_at,
                    )
                    if context.profile_allowed
                    else "REDACTED"
                ),
                profile_observed_at=(profiles[row.id].profiled_at if row.id in profiles else None),
            )
            for row in selected
        )
        next_cursor = None
        if has_more and selected:
            next_cursor = _encode_cursor(
                resource="assets",
                context=context,
                limit=limit,
                boundary={"name": selected[-1].name, "id": str(selected[-1].id)},
            )
        return QualityAssetPage(items=items, next_cursor=next_cursor)

    async def list_rule_sets(
        self, *, context: QualityReadContext, limit: int, cursor: str | None
    ) -> QualityRuleSetPage:
        visible = self._visible_assets(context).subquery("visible_quality_assets")
        conditions: list[Any] = [
            QualityRuleSetModel.workspace_id == context.subject.workspace_id,
        ]
        if cursor:
            boundary = _decode_cursor(
                cursor,
                resource="rule-sets",
                context=context,
                limit=limit,
            )
            created_at = _required_datetime(boundary, "created_at")
            rule_set_id = _required_uuid(boundary, "id")
            conditions.append(
                or_(
                    QualityRuleSetModel.created_at < created_at,
                    and_(
                        QualityRuleSetModel.created_at == created_at,
                        QualityRuleSetModel.id < rule_set_id,
                    ),
                )
            )
        rows = list(
            (
                await self._session.execute(
                    select(QualityRuleSetModel, visible.c.name.label("asset_name"))
                    .join(visible, visible.c.id == QualityRuleSetModel.asset_id)
                    .where(and_(*conditions))
                    .order_by(
                        desc(QualityRuleSetModel.created_at),
                        desc(QualityRuleSetModel.id),
                    )
                    .limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        selected = rows[:limit]
        summaries = await self._rule_set_summaries(selected)
        next_cursor = None
        if has_more and selected:
            model = selected[-1][0]
            next_cursor = _encode_cursor(
                resource="rule-sets",
                context=context,
                limit=limit,
                boundary={
                    "created_at": model.created_at.isoformat(),
                    "id": str(model.id),
                },
            )
        return QualityRuleSetPage(items=summaries, next_cursor=next_cursor)

    async def get_asset(
        self, *, context: QualityReadContext, asset_id: UUID
    ) -> QualityAssetSummary | None:
        row = (
            await self._session.scalars(
                select(AssetProjectionModel).where(
                    and_(
                        *catalog_asset_scope_conditions(context.subject, context.access),
                        AssetProjectionModel.id == asset_id,
                    )
                )
            )
        ).one_or_none()
        if row is None:
            return None
        counts = await self._active_rule_set_counts(
            workspace_id=context.subject.workspace_id,
            asset_ids=(asset_id,),
        )
        latest_runs = await self._latest_runs_by_asset(
            workspace_id=context.subject.workspace_id,
            asset_ids=(asset_id,),
        )
        profiles = (
            await self._latest_profiles(
                workspace_id=context.subject.workspace_id,
                asset_ids=(asset_id,),
            )
            if context.profile_allowed
            else {}
        )
        latest_run = latest_runs.get(asset_id)
        profile = profiles.get(asset_id)
        return QualityAssetSummary(
            asset_id=row.id,
            name=row.name,
            platform=row.platform,
            database_name=row.database_name,
            schema_name=row.schema_name,
            classification=Classification(row.classification).name,
            lifecycle=row.lifecycle,
            active_rule_set_count=counts.get(asset_id, 0),
            latest_run_state=latest_run.state if latest_run is not None else None,
            latest_quality_outcome=(latest_run.quality_outcome if latest_run is not None else None),
            latest_score_basis_points=(
                _run_basis_points(latest_run) if latest_run is not None else None
            ),
            profile_readiness=(
                _profile_readiness(profile=profile, observed_at=context.observed_at)
                if context.profile_allowed
                else "REDACTED"
            ),
            profile_observed_at=profile.profiled_at if profile is not None else None,
        )

    async def get_rule_set(
        self, *, context: QualityReadContext, rule_set_id: UUID
    ) -> QualityRuleSetDetail | None:
        visible = self._visible_assets(context).subquery("visible_quality_assets")
        row = (
            await self._session.execute(
                select(QualityRuleSetModel, visible.c.name.label("asset_name"))
                .join(visible, visible.c.id == QualityRuleSetModel.asset_id)
                .where(
                    QualityRuleSetModel.workspace_id == context.subject.workspace_id,
                    QualityRuleSetModel.id == rule_set_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        summary = (await self._rule_set_summaries([row]))[0]
        versions = list(
            (
                await self._session.scalars(
                    select(QualityRuleSetVersionModel)
                    .where(
                        QualityRuleSetVersionModel.workspace_id == context.subject.workspace_id,
                        QualityRuleSetVersionModel.rule_set_id == rule_set_id,
                    )
                    .order_by(
                        desc(QualityRuleSetVersionModel.version_number),
                        desc(QualityRuleSetVersionModel.id),
                    )
                )
            ).all()
        )
        version_ids = tuple(value.id for value in versions)
        rule_counts = await self._rule_counts(
            workspace_id=context.subject.workspace_id,
            version_ids=version_ids,
        )
        definitions = (
            list(
                (
                    await self._session.scalars(
                        select(QualityRuleDefinitionModel)
                        .where(
                            QualityRuleDefinitionModel.workspace_id == context.subject.workspace_id,
                            QualityRuleDefinitionModel.rule_set_version_id.in_(version_ids),
                        )
                        .order_by(
                            desc(QualityRuleDefinitionModel.created_at),
                            QualityRuleDefinitionModel.ordinal,
                        )
                    )
                ).all()
            )
            if version_ids
            else []
        )
        return QualityRuleSetDetail(
            rule_set=summary,
            versions=tuple(
                QualityRuleVersionSummary(
                    version_id=value.id,
                    version_number=value.version_number,
                    state=value.state,
                    author_id=value.author_id,
                    reviewed_by=value.reviewed_by,
                    activated_by=value.activated_by,
                    rule_count=rule_counts.get(value.id, 0),
                    schedule_mode=value.schedule_mode,
                    created_at=value.created_at,
                    updated_at=value.updated_at,
                    version=value.version,
                )
                for value in versions
            ),
            definitions=tuple(
                QualityRuleDefinitionSummary(
                    rule_definition_id=value.id,
                    version_id=value.rule_set_version_id,
                    ordinal=value.ordinal,
                    field_identifier=value.field_identifier,
                    kind=value.kind,
                    severity=value.severity,
                    parameters=value.parameters,
                )
                for value in definitions
            ),
        )

    async def list_runs(
        self, *, context: QualityReadContext, limit: int, cursor: str | None
    ) -> QualityRunPage:
        conditions: list[Any] = []
        if cursor:
            boundary = _decode_cursor(
                cursor,
                resource="runs",
                context=context,
                limit=limit,
            )
            created_at = _required_datetime(boundary, "created_at")
            run_id = _required_uuid(boundary, "id")
            conditions.append(
                or_(
                    QualityValidationRunModel.created_at < created_at,
                    and_(
                        QualityValidationRunModel.created_at == created_at,
                        QualityValidationRunModel.id < run_id,
                    ),
                )
            )
        rows = await self._run_rows(
            context=context,
            conditions=conditions,
            limit=limit + 1,
        )
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(_run_summary(row) for row in selected)
        next_cursor = None
        if has_more and selected:
            model = selected[-1][0]
            next_cursor = _encode_cursor(
                resource="runs",
                context=context,
                limit=limit,
                boundary={
                    "created_at": model.created_at.isoformat(),
                    "id": str(model.id),
                },
            )
        return QualityRunPage(items=items, next_cursor=next_cursor)

    async def get_run(
        self, *, context: QualityReadContext, run_id: UUID
    ) -> QualityRunSummary | None:
        rows = await self._run_rows(
            context=context,
            conditions=[QualityValidationRunModel.id == run_id],
            limit=1,
        )
        return _run_summary(rows[0]) if rows else None

    async def list_results(
        self,
        *,
        context: QualityReadContext,
        run_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> QualityResultPage | None:
        if await self.get_run(context=context, run_id=run_id) is None:
            return None
        conditions: list[Any] = [
            QualityExpectationResultModel.workspace_id == context.subject.workspace_id,
            QualityExpectationResultModel.run_id == run_id,
        ]
        if cursor:
            boundary = _decode_cursor(
                cursor,
                resource=f"run-results:{run_id}",
                context=context,
                limit=limit,
            )
            occurred_at = _required_datetime(boundary, "occurred_at")
            result_id = _required_uuid(boundary, "id")
            conditions.append(
                or_(
                    QualityExpectationResultModel.occurred_at < occurred_at,
                    and_(
                        QualityExpectationResultModel.occurred_at == occurred_at,
                        QualityExpectationResultModel.id < result_id,
                    ),
                )
            )
        rows = list(
            (
                await self._session.execute(
                    select(QualityExpectationResultModel, QualityRuleDefinitionModel)
                    .join(
                        QualityRuleDefinitionModel,
                        and_(
                            QualityRuleDefinitionModel.workspace_id
                            == QualityExpectationResultModel.workspace_id,
                            QualityRuleDefinitionModel.id
                            == QualityExpectationResultModel.rule_definition_id,
                        ),
                    )
                    .where(and_(*conditions))
                    .order_by(
                        desc(QualityExpectationResultModel.occurred_at),
                        desc(QualityExpectationResultModel.id),
                    )
                    .limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(
            QualityResultSummary(
                result_id=result.id,
                rule_definition_id=result.rule_definition_id,
                field_identifier=definition.field_identifier,
                kind=definition.kind,
                severity=definition.severity,
                outcome=result.outcome,
                evaluated_count=result.evaluated_count,
                missing_count=result.missing_count,
                unexpected_count=result.unexpected_count,
                missing_ratio=result.missing_ratio,
                unexpected_ratio=result.unexpected_ratio,
                duration_ms=result.duration_ms,
                occurred_at=result.occurred_at,
            )
            for result, definition in selected
        )
        next_cursor = None
        if has_more and selected:
            result = selected[-1][0]
            next_cursor = _encode_cursor(
                resource=f"run-results:{run_id}",
                context=context,
                limit=limit,
                boundary={
                    "occurred_at": result.occurred_at.isoformat(),
                    "id": str(result.id),
                },
            )
        return QualityResultPage(items=items, next_cursor=next_cursor)

    async def list_issues(
        self, *, context: QualityReadContext, limit: int, cursor: str | None
    ) -> QualityIssuePage:
        visible = self._visible_assets(context).subquery("visible_quality_assets")
        last_observed = func.max(QualityExpectationResultModel.occurred_at)
        conditions: list[Any] = [
            QualityExpectationResultModel.outcome.in_(("ADVISORY_FAIL", "BLOCKING_FAIL"))
        ]
        having_condition: Any | None = None
        if cursor:
            boundary = _decode_cursor(
                cursor,
                resource="issues",
                context=context,
                limit=limit,
            )
            observed_at = _required_datetime(boundary, "last_observed_at")
            asset_id = _required_uuid(boundary, "asset_id")
            field_identifier = _required_string(boundary, "field_identifier")
            kind = _required_string(boundary, "kind")
            severity = _required_string(boundary, "severity")
            outcome = _required_string(boundary, "outcome")
            having_condition = tuple_(
                last_observed,
                QualityValidationRunModel.asset_id,
                QualityRuleDefinitionModel.field_identifier,
                QualityRuleDefinitionModel.kind,
                QualityRuleDefinitionModel.severity,
                QualityExpectationResultModel.outcome,
            ) < tuple_(
                literal(observed_at),
                literal(asset_id),
                literal(field_identifier),
                literal(kind),
                literal(severity),
                literal(outcome),
            )
        statement = (
            select(
                QualityValidationRunModel.asset_id,
                visible.c.name.label("asset_name"),
                QualityRuleDefinitionModel.field_identifier,
                QualityRuleDefinitionModel.kind,
                QualityRuleDefinitionModel.severity,
                QualityExpectationResultModel.outcome,
                func.count().label("occurrence_count"),
                last_observed.label("last_observed_at"),
            )
            .join(
                QualityValidationRunModel,
                and_(
                    QualityValidationRunModel.workspace_id
                    == QualityExpectationResultModel.workspace_id,
                    QualityValidationRunModel.id == QualityExpectationResultModel.run_id,
                ),
            )
            .join(visible, visible.c.id == QualityValidationRunModel.asset_id)
            .join(
                QualityRuleDefinitionModel,
                and_(
                    QualityRuleDefinitionModel.workspace_id
                    == QualityExpectationResultModel.workspace_id,
                    QualityRuleDefinitionModel.id
                    == QualityExpectationResultModel.rule_definition_id,
                ),
            )
            .where(and_(*conditions))
            .group_by(
                QualityValidationRunModel.asset_id,
                visible.c.name,
                QualityRuleDefinitionModel.field_identifier,
                QualityRuleDefinitionModel.kind,
                QualityRuleDefinitionModel.severity,
                QualityExpectationResultModel.outcome,
            )
            .order_by(
                desc(last_observed),
                desc(QualityValidationRunModel.asset_id),
                desc(QualityRuleDefinitionModel.field_identifier),
                desc(QualityRuleDefinitionModel.kind),
                desc(QualityRuleDefinitionModel.severity),
                desc(QualityExpectationResultModel.outcome),
            )
            .limit(limit + 1)
        )
        if having_condition is not None:
            statement = statement.having(having_condition)
        rows = list((await self._session.execute(statement)).all())
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(
            QualityIssueSummary(
                issue_id=canonical_json_hash(
                    {
                        "contract": "QUALITY_ISSUE_ID_V1",
                        "workspace_id": str(context.subject.workspace_id),
                        "asset_id": str(row.asset_id),
                        "field_identifier": row.field_identifier,
                        "kind": row.kind,
                        "severity": row.severity,
                        "outcome": row.outcome,
                    }
                ),
                asset_id=row.asset_id,
                asset_name=row.asset_name,
                field_identifier=row.field_identifier,
                kind=row.kind,
                severity=row.severity,
                outcome=row.outcome,
                occurrence_count=int(row.occurrence_count),
                last_observed_at=row.last_observed_at,
            )
            for row in selected
        )
        next_cursor = None
        if has_more and selected:
            row = selected[-1]
            next_cursor = _encode_cursor(
                resource="issues",
                context=context,
                limit=limit,
                boundary={
                    "last_observed_at": row.last_observed_at.isoformat(),
                    "asset_id": str(row.asset_id),
                    "field_identifier": row.field_identifier,
                    "kind": row.kind,
                    "severity": row.severity,
                    "outcome": row.outcome,
                },
            )
        return QualityIssuePage(items=items, next_cursor=next_cursor)

    def _visible_assets(self, context: QualityReadContext) -> Any:
        return select(
            AssetProjectionModel.id,
            AssetProjectionModel.name,
            AssetProjectionModel.classification,
            AssetProjectionModel.system_id,
            AssetProjectionModel.domain_id,
        ).where(and_(*catalog_asset_scope_conditions(context.subject, context.access)))

    async def _trend(
        self,
        *,
        context: QualityReadContext,
        visible: Any,
        since: datetime,
    ) -> tuple[QualityTrendPoint, ...]:
        bucket = func.date_trunc("day", QualityValidationRunModel.completed_at)
        rows = list(
            (
                await self._session.execute(
                    select(
                        bucket.label("bucket_start"),
                        func.coalesce(func.sum(QualityValidationRunModel.passed_count), 0).label(
                            "passed"
                        ),
                        func.coalesce(
                            func.sum(QualityValidationRunModel.advisory_failed_count),
                            0,
                        ).label("advisory"),
                        func.coalesce(
                            func.sum(QualityValidationRunModel.blocking_failed_count),
                            0,
                        ).label("blocking"),
                    )
                    .join(visible, visible.c.id == QualityValidationRunModel.asset_id)
                    .where(
                        QualityValidationRunModel.workspace_id == context.subject.workspace_id,
                        QualityValidationRunModel.state == "SUCCEEDED",
                        QualityValidationRunModel.completed_at.is_not(None),
                        QualityValidationRunModel.completed_at >= since,
                    )
                    .group_by(bucket)
                    .order_by(bucket)
                    .limit(90)
                )
            ).all()
        )
        return tuple(
            QualityTrendPoint(
                bucket_start=row.bucket_start,
                passed_count=int(row.passed),
                advisory_failed_count=int(row.advisory),
                blocking_failed_count=int(row.blocking),
                evaluated_rule_count=int(row.passed) + int(row.advisory) + int(row.blocking),
                score_basis_points=_basis_points(
                    int(row.passed),
                    int(row.passed) + int(row.advisory) + int(row.blocking),
                ),
            )
            for row in rows
        )

    async def _active_rule_set_counts(
        self, *, workspace_id: UUID, asset_ids: Sequence[UUID]
    ) -> dict[UUID, int]:
        if not asset_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    QualityRuleSetModel.asset_id,
                    func.count().label("aggregate_count"),
                )
                .where(
                    QualityRuleSetModel.workspace_id == workspace_id,
                    QualityRuleSetModel.asset_id.in_(asset_ids),
                    QualityRuleSetModel.state == "ACTIVE",
                )
                .group_by(QualityRuleSetModel.asset_id)
            )
        ).all()
        return {row.asset_id: int(row._mapping["aggregate_count"]) for row in rows}

    async def _latest_runs_by_asset(
        self, *, workspace_id: UUID, asset_ids: Sequence[UUID]
    ) -> dict[UUID, QualityValidationRunModel]:
        if not asset_ids:
            return {}
        ranked = (
            select(
                QualityValidationRunModel.id,
                func.row_number()
                .over(
                    partition_by=QualityValidationRunModel.asset_id,
                    order_by=(
                        desc(QualityValidationRunModel.created_at),
                        desc(QualityValidationRunModel.id),
                    ),
                )
                .label("ordinal"),
            ).where(
                QualityValidationRunModel.workspace_id == workspace_id,
                QualityValidationRunModel.asset_id.in_(asset_ids),
            )
        ).subquery("ranked_asset_runs")
        models = list(
            (
                await self._session.scalars(
                    select(QualityValidationRunModel)
                    .join(ranked, ranked.c.id == QualityValidationRunModel.id)
                    .where(ranked.c.ordinal == 1)
                )
            ).all()
        )
        return {model.asset_id: model for model in models}

    async def _latest_profiles(
        self, *, workspace_id: UUID, asset_ids: Sequence[UUID]
    ) -> dict[UUID, AssetProfileSnapshotModel]:
        if not asset_ids:
            return {}
        ranked = (
            select(
                AssetProfileSnapshotModel.id,
                func.row_number()
                .over(
                    partition_by=AssetProfileSnapshotModel.asset_id,
                    order_by=(
                        desc(AssetProfileSnapshotModel.profiled_at),
                        desc(AssetProfileSnapshotModel.id),
                    ),
                )
                .label("ordinal"),
            ).where(
                AssetProfileSnapshotModel.workspace_id == workspace_id,
                AssetProfileSnapshotModel.asset_id.in_(asset_ids),
                AssetProfileSnapshotModel.profile_kind.in_(("FULL", "PARTITION")),
                AssetProfileSnapshotModel.completeness == "COMPLETE",
            )
        ).subquery("ranked_asset_profiles")
        models = list(
            (
                await self._session.scalars(
                    select(AssetProfileSnapshotModel)
                    .join(ranked, ranked.c.id == AssetProfileSnapshotModel.id)
                    .where(ranked.c.ordinal == 1)
                )
            ).all()
        )
        return {model.asset_id: model for model in models}

    async def _rule_set_summaries(
        self,
        rows: Sequence[Row[tuple[QualityRuleSetModel, str]]],
    ) -> tuple[QualityRuleSetSummary, ...]:
        rule_set_ids = tuple(row[0].id for row in rows)
        if not rule_set_ids:
            return ()
        versions = list(
            (
                await self._session.scalars(
                    select(QualityRuleSetVersionModel).where(
                        QualityRuleSetVersionModel.rule_set_id.in_(rule_set_ids),
                        QualityRuleSetVersionModel.state == "ACTIVE",
                    )
                )
            ).all()
        )
        by_rule_set = {value.rule_set_id: value for value in versions}
        rule_counts = await self._rule_counts(
            workspace_id=rows[0][0].workspace_id,
            version_ids=tuple(value.id for value in versions),
        )
        return tuple(
            QualityRuleSetSummary(
                rule_set_id=model.id,
                name=model.name,
                asset_id=model.asset_id,
                asset_name=asset_name,
                state=model.state,
                active_version_id=(by_rule_set[model.id].id if model.id in by_rule_set else None),
                active_version_number=(
                    by_rule_set[model.id].version_number if model.id in by_rule_set else None
                ),
                active_version_state=(
                    by_rule_set[model.id].state if model.id in by_rule_set else None
                ),
                rule_count=(
                    rule_counts.get(by_rule_set[model.id].id, 0) if model.id in by_rule_set else 0
                ),
                created_at=model.created_at,
                updated_at=model.updated_at,
                version=model.version,
            )
            for model, asset_name in rows
        )

    async def _rule_counts(
        self, *, workspace_id: UUID, version_ids: Sequence[UUID]
    ) -> dict[UUID, int]:
        if not version_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    QualityRuleDefinitionModel.rule_set_version_id,
                    func.count().label("aggregate_count"),
                )
                .where(
                    QualityRuleDefinitionModel.workspace_id == workspace_id,
                    QualityRuleDefinitionModel.rule_set_version_id.in_(version_ids),
                )
                .group_by(QualityRuleDefinitionModel.rule_set_version_id)
            )
        ).all()
        return {row.rule_set_version_id: int(row._mapping["aggregate_count"]) for row in rows}

    async def _run_rows(
        self,
        *,
        context: QualityReadContext,
        conditions: Sequence[Any],
        limit: int,
    ) -> list[Row[tuple[QualityValidationRunModel, str, str]]]:
        visible = self._visible_assets(context).subquery("visible_quality_assets")
        return list(
            (
                await self._session.execute(
                    select(
                        QualityValidationRunModel,
                        QualityRuleSetModel.name.label("rule_set_name"),
                        visible.c.name.label("asset_name"),
                    )
                    .join(visible, visible.c.id == QualityValidationRunModel.asset_id)
                    .join(
                        QualityRuleSetModel,
                        and_(
                            QualityRuleSetModel.workspace_id
                            == QualityValidationRunModel.workspace_id,
                            QualityRuleSetModel.id == QualityValidationRunModel.rule_set_id,
                        ),
                    )
                    .where(
                        QualityValidationRunModel.workspace_id == context.subject.workspace_id,
                        *conditions,
                    )
                    .order_by(
                        desc(QualityValidationRunModel.created_at),
                        desc(QualityValidationRunModel.id),
                    )
                    .limit(limit)
                )
            ).all()
        )


def _run_summary(
    row: Row[tuple[QualityValidationRunModel, str, str]],
) -> QualityRunSummary:
    model, rule_set_name, asset_name = row
    return QualityRunSummary(
        run_id=model.id,
        rule_set_id=model.rule_set_id,
        rule_set_name=rule_set_name,
        asset_id=model.asset_id,
        asset_name=asset_name,
        trigger_kind=model.trigger_kind,
        state=model.state,
        quality_outcome=model.quality_outcome,
        score_basis_points=_run_basis_points(model),
        passed_count=model.passed_count,
        advisory_failed_count=model.advisory_failed_count,
        blocking_failed_count=model.blocking_failed_count,
        created_at=model.created_at,
        completed_at=model.completed_at,
        failure_code=model.failure_code,
        version=model.version,
    )


def _run_basis_points(model: QualityValidationRunModel) -> int | None:
    if model.state != "SUCCEEDED":
        return None
    passed = model.passed_count or 0
    evaluated = passed + (model.advisory_failed_count or 0) + (model.blocking_failed_count or 0)
    return _basis_points(passed, evaluated)


def _basis_points(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    return (numerator * 10_000 + denominator // 2) // denominator


def _outcome(*, evaluated: int, advisory_failed: int, blocking_failed: int) -> str:
    if evaluated <= 0:
        return "UNKNOWN"
    if blocking_failed > 0:
        return "FAIL"
    if advisory_failed > 0:
        return "WARN"
    return "PASS"


def _profile_readiness(
    *, profile: AssetProfileSnapshotModel | None, observed_at: datetime
) -> ProfileReadiness:
    if profile is None:
        return "UNAVAILABLE"
    return "READY" if profile.stale_at > observed_at else "STALE"


def _encode_cursor(
    *,
    resource: str,
    context: QualityReadContext,
    limit: int,
    boundary: Mapping[str, object],
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "resource": resource,
            "workspace_id": str(context.subject.workspace_id),
            "cache_scope": context.cache_scope,
            "limit": limit,
            "boundary": boundary,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    resource: str,
    context: QualityReadContext,
    limit: int,
) -> dict[str, object]:
    try:
        if not cursor or len(cursor) > _CURSOR_MAX_LENGTH:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(payload)
        if (
            not isinstance(document, dict)
            or frozenset(document)
            != frozenset(
                {
                    "v",
                    "resource",
                    "workspace_id",
                    "cache_scope",
                    "limit",
                    "boundary",
                }
            )
            or document.get("v") != 1
            or document.get("resource") != resource
            or document.get("workspace_id") != str(context.subject.workspace_id)
            or document.get("cache_scope") != context.cache_scope
            or document.get("limit") != limit
            or not isinstance(document.get("boundary"), dict)
        ):
            raise ValueError
        boundary = cast(dict[str, object], document["boundary"])
        if cursor != _encode_cursor(
            resource=resource,
            context=context,
            limit=limit,
            boundary=boundary,
        ):
            raise ValueError
        return boundary
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValidationError(
            "The Quality cursor is stale or does not match this request."
        ) from error


def _required_string(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value or len(value) > 500:
        raise ValidationError("The Quality cursor boundary is invalid.")
    return value


def _required_uuid(document: Mapping[str, object], key: str) -> UUID:
    try:
        return UUID(_required_string(document, key))
    except ValueError as error:
        raise ValidationError("The Quality cursor boundary is invalid.") from error


def _required_datetime(document: Mapping[str, object], key: str) -> datetime:
    try:
        value = datetime.fromisoformat(_required_string(document, key))
    except ValueError as error:
        raise ValidationError("The Quality cursor boundary is invalid.") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("The Quality cursor boundary is invalid.")
    return value
