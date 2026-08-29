from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    Row,
    and_,
    case,
    desc,
    func,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.quality_contracts import (
    QUALITY_SCORE_POLICY_HASH,
    QUALITY_SCORE_POLICY_ID,
    QUALITY_SCORE_POLICY_VERSION,
)
from datariver.application.quality_read_contracts import (
    ProfileReadiness,
    QualityAssetPage,
    QualityAssetSummary,
    QualityAssetWorkspace,
    QualityCommonRuleTemplateDetail,
    QualityCommonRuleTemplateMapping,
    QualityCommonRuleTemplateRule,
    QualityCommonRuleTemplateSummary,
    QualityDashboard,
    QualityDashboardIndicator,
    QualityDashboardRisk,
    QualityFieldRuleSummary,
    QualityFieldRunSummary,
    QualityFieldSummary,
    QualityFieldWorkspace,
    QualityIndicatorId,
    QualityIssuePage,
    QualityIssueSummary,
    QualityManagedRuleSet,
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
    QualitySchemaDashboard,
    QualityScorePolicySummary,
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
    QualityCommonRuleTemplateMappingModel,
    QualityCommonRuleTemplateModel,
    QualityExpectationResultModel,
    QualityRuleDefinitionModel,
    QualityRuleSetModel,
    QualityRuleSetVersionModel,
    QualityValidationRunModel,
)

_CURSOR_MAX_LENGTH = 2_000
_TERMINAL_STATES = ("SUCCEEDED", "FAILED", "STALE", "CANCELLED")
_DASHBOARD_SCHEMA_LIMIT = 500
_DASHBOARD_RISK_QUERY_LIMIT = 5_000
_DASHBOARD_RISKS_PER_INDICATOR = 50
_DASHBOARD_INDICATOR_CONTRACT = "QUALITY_MANAGED_INDICATORS_V1"


@dataclass(frozen=True, slots=True)
class _AssetQualityAggregate:
    passed_count: int
    advisory_failed_count: int
    blocking_failed_count: int

    @property
    def evaluated_rule_count(self) -> int:
        return self.passed_count + self.advisory_failed_count + self.blocking_failed_count

    @property
    def outcome(self) -> str:
        return _outcome(
            evaluated=self.evaluated_rule_count,
            advisory_failed=self.advisory_failed_count,
            blocking_failed=self.blocking_failed_count,
        )

    @property
    def score_basis_points(self) -> int | None:
        return _basis_points(self.passed_count, self.evaluated_rule_count)


@dataclass(frozen=True, slots=True)
class _FieldQualityAggregate:
    configured_rule_count: int = 0
    active_rule_count: int = 0
    passed_count: int = 0
    advisory_failed_count: int = 0
    blocking_failed_count: int = 0
    latest_evaluated_at: datetime | None = None

    @property
    def evaluated_rule_count(self) -> int:
        return self.passed_count + self.advisory_failed_count + self.blocking_failed_count

    @property
    def outcome(self) -> str:
        return _outcome(
            evaluated=self.evaluated_rule_count,
            advisory_failed=self.advisory_failed_count,
            blocking_failed=self.blocking_failed_count,
        )

    @property
    def score_basis_points(self) -> int | None:
        return _basis_points(self.passed_count, self.evaluated_rule_count)


@dataclass(frozen=True, slots=True)
class _DashboardRuleMetric:
    counted_target_count: int
    target_count: int
    valid_value_count: int
    evaluated_value_count: int
    advisory_failed_count: int
    blocking_failed_count: int
    risk_count: int

    @property
    def coverage_basis_points(self) -> int | None:
        return _basis_points(self.counted_target_count, self.target_count)

    @property
    def score_basis_points(self) -> int | None:
        return _basis_points(self.valid_value_count, self.evaluated_value_count)

    @property
    def outcome(self) -> str:
        return _outcome(
            evaluated=self.evaluated_value_count,
            advisory_failed=self.advisory_failed_count,
            blocking_failed=self.blocking_failed_count,
        )


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

    async def dashboard(self, *, context: QualityReadContext) -> QualityDashboard:
        visible = self._visible_assets(context).subquery("visible_quality_dashboard_assets")
        active_join = and_(
            QualityRuleSetModel.workspace_id == context.subject.workspace_id,
            QualityRuleSetModel.asset_id == visible.c.id,
            QualityRuleSetModel.state == "ACTIVE",
        )
        schema_groups = (
            select(
                visible.c.platform,
                visible.c.database_name,
                visible.c.schema_name,
            )
            .select_from(visible)
            .group_by(
                visible.c.platform,
                visible.c.database_name,
                visible.c.schema_name,
            )
        ).subquery("visible_quality_schema_groups")
        schema_count = int(
            await self._session.scalar(select(func.count()).select_from(schema_groups)) or 0
        )
        table_count = int(
            await self._session.scalar(select(func.count()).select_from(visible)) or 0
        )
        active_rule_set_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(QualityRuleSetModel)
                .join(visible, visible.c.id == QualityRuleSetModel.asset_id)
                .where(
                    QualityRuleSetModel.workspace_id == context.subject.workspace_id,
                    QualityRuleSetModel.state == "ACTIVE",
                )
            )
            or 0
        )
        covered_table_count = int(
            await self._session.scalar(
                select(func.count(func.distinct(QualityRuleSetModel.asset_id)))
                .select_from(QualityRuleSetModel)
                .join(visible, visible.c.id == QualityRuleSetModel.asset_id)
                .where(
                    QualityRuleSetModel.workspace_id == context.subject.workspace_id,
                    QualityRuleSetModel.state == "ACTIVE",
                )
            )
            or 0
        )
        common_rule_template_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(QualityCommonRuleTemplateModel)
                .where(QualityCommonRuleTemplateModel.workspace_id == context.subject.workspace_id)
            )
            or 0
        )
        schema_rows = list(
            (
                await self._session.execute(
                    select(
                        visible.c.platform,
                        visible.c.database_name,
                        visible.c.schema_name,
                        func.count(func.distinct(visible.c.id)).label("table_count"),
                        func.count(func.distinct(QualityRuleSetModel.asset_id)).label(
                            "covered_table_count"
                        ),
                    )
                    .select_from(visible)
                    .outerjoin(QualityRuleSetModel, active_join)
                    .group_by(
                        visible.c.platform,
                        visible.c.database_name,
                        visible.c.schema_name,
                    )
                    .order_by(
                        visible.c.platform,
                        visible.c.database_name,
                        visible.c.schema_name,
                    )
                    .limit(_DASHBOARD_SCHEMA_LIMIT)
                )
            ).all()
        )
        rule_metrics, rule_risks = await self._dashboard_rule_metrics(
            context=context,
            visible=visible,
        )
        timeliness_metrics, timeliness_risks = await self._dashboard_timeliness_metrics(
            context=context,
            visible=visible,
        )
        schemas: list[QualitySchemaDashboard] = []
        for row in schema_rows:
            key = _schema_key(row.platform, row.database_name, row.schema_name)
            indicators = (
                _rule_dashboard_indicator(
                    indicator_id="ACCURACY",
                    metric=rule_metrics.get((*key, "ACCURACY")),
                    risks=rule_risks.get((*key, "ACCURACY"), ()),
                ),
                _rule_dashboard_indicator(
                    indicator_id="COMPLETENESS",
                    metric=rule_metrics.get((*key, "COMPLETENESS")),
                    risks=rule_risks.get((*key, "COMPLETENESS"), ()),
                ),
                _timeliness_dashboard_indicator(
                    metric=timeliness_metrics.get(key),
                    risks=timeliness_risks.get(key, ()),
                    profile_allowed=context.profile_allowed,
                ),
            )
            schemas.append(
                QualitySchemaDashboard(
                    schema_id=_schema_id(*key),
                    platform=row.platform,
                    database_name=row.database_name,
                    schema_name=row.schema_name,
                    table_count=int(row.table_count),
                    covered_table_count=int(row.covered_table_count),
                    indicators=indicators,
                )
            )
        return QualityDashboard(
            as_of=context.observed_at,
            schema_count=schema_count,
            table_count=table_count,
            active_rule_set_count=active_rule_set_count,
            common_rule_template_count=common_rule_template_count,
            covered_table_count=covered_table_count,
            table_coverage_basis_points=_basis_points(covered_table_count, table_count),
            managed_rule_sets=_managed_rule_sets(),
            schemas=tuple(schemas),
            schemas_truncated=schema_count > len(schemas),
        )

    async def list_assets(
        self,
        *,
        context: QualityReadContext,
        limit: int,
        cursor: str | None,
        query: str = "",
        platform: str | None = None,
        database_name: str | None = None,
        schema_name: str | None = None,
    ) -> QualityAssetPage:
        conditions = catalog_asset_scope_conditions(context.subject, context.access)
        normalized_query = query.strip()
        if normalized_query:
            pattern = _literal_contains_pattern(normalized_query)
            conditions.append(
                or_(
                    AssetProjectionModel.name.ilike(pattern, escape="\\"),
                    AssetProjectionModel.schema_name.ilike(pattern, escape="\\"),
                    AssetProjectionModel.database_name.ilike(pattern, escape="\\"),
                    AssetProjectionModel.platform.ilike(pattern, escape="\\"),
                )
            )
        if platform:
            conditions.append(AssetProjectionModel.platform == platform)
        if database_name:
            conditions.append(AssetProjectionModel.database_name == database_name)
        if schema_name:
            conditions.append(AssetProjectionModel.schema_name == schema_name)
        cursor_resource = _asset_cursor_resource(
            query=normalized_query,
            platform=platform,
            database_name=database_name,
            schema_name=schema_name,
        )
        if cursor:
            boundary = _decode_cursor(
                cursor,
                resource=cursor_resource,
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
        items = await self._asset_summaries(context=context, rows=selected)
        next_cursor = None
        if has_more and selected:
            next_cursor = _encode_cursor(
                resource=cursor_resource,
                context=context,
                limit=limit,
                boundary={"name": selected[-1].name, "id": str(selected[-1].id)},
            )
        return QualityAssetPage(items=items, next_cursor=next_cursor)

    async def get_assets(
        self, *, context: QualityReadContext, asset_ids: tuple[UUID, ...]
    ) -> tuple[QualityAssetSummary, ...]:
        if not asset_ids:
            return ()
        rows = list(
            (
                await self._session.scalars(
                    select(AssetProjectionModel).where(
                        and_(
                            *catalog_asset_scope_conditions(context.subject, context.access),
                            AssetProjectionModel.id.in_(asset_ids),
                        )
                    )
                )
            ).all()
        )
        summaries = await self._asset_summaries(context=context, rows=rows)
        by_id = {item.asset_id: item for item in summaries}
        return tuple(by_id[asset_id] for asset_id in asset_ids if asset_id in by_id)

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
        values = await self.get_assets(context=context, asset_ids=(asset_id,))
        return values[0] if values else None

    async def get_asset_workspace(
        self, *, context: QualityReadContext, asset_id: UUID, days: int
    ) -> QualityAssetWorkspace | None:
        asset = await self.get_asset(context=context, asset_id=asset_id)
        if asset is None:
            return None
        visible = self._visible_assets(context).subquery("visible_quality_assets")
        rule_rows = list(
            (
                await self._session.execute(
                    select(QualityRuleSetModel, visible.c.name.label("asset_name"))
                    .join(visible, visible.c.id == QualityRuleSetModel.asset_id)
                    .where(
                        QualityRuleSetModel.workspace_id == context.subject.workspace_id,
                        QualityRuleSetModel.asset_id == asset_id,
                    )
                    .order_by(
                        desc(QualityRuleSetModel.updated_at),
                        desc(QualityRuleSetModel.id),
                    )
                    .limit(50)
                )
            ).all()
        )
        runs = await self._run_rows(
            context=context,
            conditions=(QualityValidationRunModel.asset_id == asset_id,),
            limit=50,
        )
        asset_visible = (
            self._visible_assets(context)
            .where(AssetProjectionModel.id == asset_id)
            .subquery("selected_quality_asset")
        )
        return QualityAssetWorkspace(
            asset=asset,
            rule_sets=await self._rule_set_summaries(rule_rows),
            runs=tuple(_run_summary(row) for row in runs),
            trend=await self._trend(
                context=context,
                visible=asset_visible,
                since=context.observed_at - timedelta(days=days),
            ),
            fields=await self._field_summaries(
                workspace_id=context.subject.workspace_id,
                asset_id=asset_id,
            ),
            score_policy=_score_policy_summary(),
        )

    async def get_field_workspace(
        self,
        *,
        context: QualityReadContext,
        asset_id: UUID,
        field_identifier: str,
        days: int,
    ) -> QualityFieldWorkspace | None:
        if await self.get_asset(context=context, asset_id=asset_id) is None:
            return None
        workspace_id = context.subject.workspace_id
        rules = await self._field_rules(
            workspace_id=workspace_id,
            asset_id=asset_id,
            field_identifier=field_identifier,
        )
        runs = await self._field_runs(
            context=context,
            asset_id=asset_id,
            field_identifier=field_identifier,
        )
        return QualityFieldWorkspace(
            asset_id=asset_id,
            field_identifier=field_identifier,
            rules=rules,
            runs=runs,
            trend=await self._field_trend(
                workspace_id=workspace_id,
                asset_id=asset_id,
                field_identifier=field_identifier,
                since=context.observed_at - timedelta(days=days),
            ),
            score_policy=_score_policy_summary(),
        )

    async def list_common_rule_templates(
        self, *, context: QualityReadContext
    ) -> tuple[QualityCommonRuleTemplateSummary, ...]:
        visible = self._visible_assets(context).subquery("visible_template_assets")
        counts = (
            select(
                QualityCommonRuleTemplateMappingModel.template_id,
                func.count().label("mapping_count"),
            )
            .join(
                visible,
                visible.c.id == QualityCommonRuleTemplateMappingModel.asset_id,
            )
            .where(
                QualityCommonRuleTemplateMappingModel.workspace_id == context.subject.workspace_id
            )
            .group_by(QualityCommonRuleTemplateMappingModel.template_id)
        ).subquery("visible_template_mapping_counts")
        rows = list(
            (
                await self._session.execute(
                    select(
                        QualityCommonRuleTemplateModel,
                        func.coalesce(counts.c.mapping_count, 0).label("mapping_count"),
                    )
                    .outerjoin(
                        counts,
                        counts.c.template_id == QualityCommonRuleTemplateModel.id,
                    )
                    .where(
                        QualityCommonRuleTemplateModel.workspace_id == context.subject.workspace_id
                    )
                    .order_by(
                        desc(QualityCommonRuleTemplateModel.updated_at),
                        desc(QualityCommonRuleTemplateModel.id),
                    )
                    .limit(100)
                )
            ).all()
        )
        return tuple(_common_template_summary(row[0], int(row.mapping_count)) for row in rows)

    async def get_common_rule_template(
        self, *, context: QualityReadContext, template_id: UUID
    ) -> QualityCommonRuleTemplateDetail | None:
        template = (
            await self._session.scalars(
                select(QualityCommonRuleTemplateModel).where(
                    QualityCommonRuleTemplateModel.workspace_id == context.subject.workspace_id,
                    QualityCommonRuleTemplateModel.id == template_id,
                )
            )
        ).one_or_none()
        if template is None:
            return None
        visible = self._visible_assets(context).subquery("visible_template_assets")
        rows = list(
            (
                await self._session.execute(
                    select(
                        QualityCommonRuleTemplateMappingModel,
                        AssetProjectionModel,
                        QualityRuleSetModel,
                    )
                    .join(
                        visible,
                        visible.c.id == QualityCommonRuleTemplateMappingModel.asset_id,
                    )
                    .join(
                        AssetProjectionModel,
                        and_(
                            AssetProjectionModel.workspace_id
                            == QualityCommonRuleTemplateMappingModel.workspace_id,
                            AssetProjectionModel.id
                            == QualityCommonRuleTemplateMappingModel.asset_id,
                        ),
                    )
                    .join(
                        QualityRuleSetModel,
                        and_(
                            QualityRuleSetModel.workspace_id
                            == QualityCommonRuleTemplateMappingModel.workspace_id,
                            QualityRuleSetModel.id
                            == QualityCommonRuleTemplateMappingModel.rule_set_id,
                        ),
                    )
                    .where(
                        QualityCommonRuleTemplateMappingModel.workspace_id
                        == context.subject.workspace_id,
                        QualityCommonRuleTemplateMappingModel.template_id == template_id,
                    )
                    .order_by(
                        AssetProjectionModel.schema_name,
                        AssetProjectionModel.name,
                        AssetProjectionModel.id,
                    )
                    .limit(500)
                )
            ).all()
        )
        mappings = tuple(
            QualityCommonRuleTemplateMapping(
                asset_id=asset.id,
                asset_name=asset.name,
                platform=asset.platform,
                database_name=asset.database_name,
                schema_name=asset.schema_name,
                rule_set_id=rule_set.id,
                rule_set_name=rule_set.name,
                mapped_at=mapping.created_at,
            )
            for mapping, asset, rule_set in rows
        )
        return QualityCommonRuleTemplateDetail(
            template=_common_template_summary(template, len(mappings)),
            mappings=mappings,
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

    async def _dashboard_rule_metrics(
        self,
        *,
        context: QualityReadContext,
        visible: Any,
    ) -> tuple[
        dict[tuple[str, str, str, str], _DashboardRuleMetric],
        dict[tuple[str, str, str, str], tuple[QualityDashboardRisk, ...]],
    ]:
        workspace_id = context.subject.workspace_id
        active_versions = (
            select(
                visible.c.id.label("asset_id"),
                visible.c.name.label("asset_name"),
                visible.c.platform,
                visible.c.database_name,
                visible.c.schema_name,
                QualityRuleSetModel.id.label("rule_set_id"),
                QualityRuleSetVersionModel.id.label("version_id"),
            )
            .select_from(visible)
            .join(
                QualityRuleSetModel,
                and_(
                    QualityRuleSetModel.workspace_id == workspace_id,
                    QualityRuleSetModel.asset_id == visible.c.id,
                    QualityRuleSetModel.state == "ACTIVE",
                ),
            )
            .join(
                QualityRuleSetVersionModel,
                and_(
                    QualityRuleSetVersionModel.workspace_id == workspace_id,
                    QualityRuleSetVersionModel.rule_set_id == QualityRuleSetModel.id,
                    QualityRuleSetVersionModel.state == "ACTIVE",
                ),
            )
        ).subquery("active_quality_dashboard_versions")
        ranked_runs = (
            select(
                QualityValidationRunModel.id.label("run_id"),
                QualityValidationRunModel.rule_set_id,
                QualityValidationRunModel.rule_set_version_id,
                QualityValidationRunModel.completed_at,
                func.row_number()
                .over(
                    partition_by=(
                        QualityValidationRunModel.rule_set_id,
                        QualityValidationRunModel.rule_set_version_id,
                    ),
                    order_by=(
                        desc(QualityValidationRunModel.completed_at),
                        desc(QualityValidationRunModel.id),
                    ),
                )
                .label("ordinal"),
            )
            .join(
                active_versions,
                and_(
                    active_versions.c.rule_set_id == QualityValidationRunModel.rule_set_id,
                    active_versions.c.version_id == QualityValidationRunModel.rule_set_version_id,
                    active_versions.c.asset_id == QualityValidationRunModel.asset_id,
                ),
            )
            .where(
                QualityValidationRunModel.workspace_id == workspace_id,
                QualityValidationRunModel.state == "SUCCEEDED",
            )
        ).subquery("ranked_quality_dashboard_runs")
        latest_runs = (
            select(
                ranked_runs.c.run_id,
                ranked_runs.c.rule_set_id,
                ranked_runs.c.rule_set_version_id,
                ranked_runs.c.completed_at,
            ).where(ranked_runs.c.ordinal == 1)
        ).subquery("latest_quality_dashboard_runs")
        dimension = case(
            (QualityRuleDefinitionModel.kind == "NOT_NULL", "COMPLETENESS"),
            (
                QualityRuleDefinitionModel.kind.in_(("RANGE", "REGEX")),
                "ACCURACY",
            ),
        )
        target_identity = tuple_(
            active_versions.c.asset_id,
            QualityRuleDefinitionModel.field_identifier,
        )
        has_result = QualityExpectationResultModel.id.is_not(None)
        valid_values = case(
            (
                QualityRuleDefinitionModel.kind == "NOT_NULL",
                QualityExpectationResultModel.evaluated_count
                - QualityExpectationResultModel.missing_count,
            ),
            else_=(
                QualityExpectationResultModel.evaluated_count
                - QualityExpectationResultModel.unexpected_count
            ),
        )
        rows = list(
            (
                await self._session.execute(
                    select(
                        active_versions.c.platform,
                        active_versions.c.database_name,
                        active_versions.c.schema_name,
                        dimension.label("indicator_id"),
                        func.count(func.distinct(target_identity)).label("target_count"),
                        func.count(func.distinct(target_identity))
                        .filter(has_result)
                        .label("counted_count"),
                        func.coalesce(
                            func.sum(QualityExpectationResultModel.evaluated_count),
                            0,
                        ).label("evaluated_count"),
                        func.coalesce(func.sum(valid_values), 0).label("valid_count"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "ADVISORY_FAIL")
                        .label("advisory_count"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "BLOCKING_FAIL")
                        .label("blocking_count"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(
                            QualityExpectationResultModel.outcome.in_(
                                ("ADVISORY_FAIL", "BLOCKING_FAIL")
                            )
                        )
                        .label("risk_count"),
                    )
                    .select_from(active_versions)
                    .join(
                        QualityRuleDefinitionModel,
                        and_(
                            QualityRuleDefinitionModel.workspace_id == workspace_id,
                            QualityRuleDefinitionModel.rule_set_version_id
                            == active_versions.c.version_id,
                        ),
                    )
                    .outerjoin(
                        latest_runs,
                        and_(
                            latest_runs.c.rule_set_id == active_versions.c.rule_set_id,
                            latest_runs.c.rule_set_version_id == active_versions.c.version_id,
                        ),
                    )
                    .outerjoin(
                        QualityExpectationResultModel,
                        and_(
                            QualityExpectationResultModel.workspace_id == workspace_id,
                            QualityExpectationResultModel.run_id == latest_runs.c.run_id,
                            QualityExpectationResultModel.rule_definition_id
                            == QualityRuleDefinitionModel.id,
                        ),
                    )
                    .where(QualityRuleDefinitionModel.kind.in_(("NOT_NULL", "RANGE", "REGEX")))
                    .group_by(
                        active_versions.c.platform,
                        active_versions.c.database_name,
                        active_versions.c.schema_name,
                        dimension,
                    )
                )
            ).all()
        )
        metrics = {
            (
                *_schema_key(row.platform, row.database_name, row.schema_name),
                str(row.indicator_id),
            ): _DashboardRuleMetric(
                counted_target_count=int(row.counted_count),
                target_count=int(row.target_count),
                valid_value_count=int(row.valid_count),
                evaluated_value_count=int(row.evaluated_count),
                advisory_failed_count=int(row.advisory_count),
                blocking_failed_count=int(row.blocking_count),
                risk_count=int(row.risk_count),
            )
            for row in rows
        }
        risk_rows = list(
            (
                await self._session.execute(
                    select(
                        active_versions.c.asset_id,
                        active_versions.c.asset_name,
                        active_versions.c.platform,
                        active_versions.c.database_name,
                        active_versions.c.schema_name,
                        latest_runs.c.run_id,
                        latest_runs.c.completed_at,
                        QualityRuleDefinitionModel.id.label("rule_definition_id"),
                        QualityRuleDefinitionModel.field_identifier,
                        QualityRuleDefinitionModel.kind,
                        QualityRuleDefinitionModel.severity,
                        QualityExpectationResultModel.outcome,
                        QualityExpectationResultModel.evaluated_count,
                        QualityExpectationResultModel.missing_count,
                        QualityExpectationResultModel.unexpected_count,
                    )
                    .select_from(active_versions)
                    .join(
                        QualityRuleDefinitionModel,
                        and_(
                            QualityRuleDefinitionModel.workspace_id == workspace_id,
                            QualityRuleDefinitionModel.rule_set_version_id
                            == active_versions.c.version_id,
                        ),
                    )
                    .join(
                        latest_runs,
                        and_(
                            latest_runs.c.rule_set_id == active_versions.c.rule_set_id,
                            latest_runs.c.rule_set_version_id == active_versions.c.version_id,
                        ),
                    )
                    .join(
                        QualityExpectationResultModel,
                        and_(
                            QualityExpectationResultModel.workspace_id == workspace_id,
                            QualityExpectationResultModel.run_id == latest_runs.c.run_id,
                            QualityExpectationResultModel.rule_definition_id
                            == QualityRuleDefinitionModel.id,
                        ),
                    )
                    .where(
                        QualityExpectationResultModel.outcome.in_(
                            ("ADVISORY_FAIL", "BLOCKING_FAIL")
                        ),
                        QualityRuleDefinitionModel.kind.in_(("NOT_NULL", "RANGE", "REGEX")),
                    )
                    .order_by(
                        desc(QualityExpectationResultModel.occurred_at),
                        desc(QualityExpectationResultModel.id),
                    )
                    .limit(_DASHBOARD_RISK_QUERY_LIMIT)
                )
            ).all()
        )
        risks: dict[tuple[str, str, str, str], list[QualityDashboardRisk]] = {}
        for row in risk_rows:
            indicator_id = "COMPLETENESS" if row.kind == "NOT_NULL" else "ACCURACY"
            key = (
                *_schema_key(row.platform, row.database_name, row.schema_name),
                indicator_id,
            )
            selected = risks.setdefault(key, [])
            if len(selected) >= _DASHBOARD_RISKS_PER_INDICATOR:
                continue
            failed_count = (
                int(row.missing_count)
                if indicator_id == "COMPLETENESS"
                else int(row.unexpected_count)
            )
            evaluated_count = int(row.evaluated_count)
            selected.append(
                QualityDashboardRisk(
                    risk_id=canonical_json_hash(
                        {
                            "contract": "QUALITY_DASHBOARD_RISK_V1",
                            "run_id": str(row.run_id),
                            "rule_definition_id": str(row.rule_definition_id),
                        }
                    ),
                    asset_id=row.asset_id,
                    asset_name=row.asset_name,
                    field_identifier=row.field_identifier,
                    severity=row.severity,
                    outcome=row.outcome,
                    score_basis_points=_basis_points(
                        max(0, evaluated_count - failed_count),
                        evaluated_count,
                    ),
                    evaluated_count=evaluated_count,
                    failed_count=failed_count,
                    observed_at=row.completed_at,
                    detail=(
                        f"최근 성공 실행에서 {failed_count:,}개 값이 비어 있습니다."
                        if indicator_id == "COMPLETENESS"
                        else f"최근 성공 실행에서 {failed_count:,}개 값이 허용 범위를 벗어났습니다."
                    ),
                )
            )
        return metrics, {key: tuple(values) for key, values in risks.items()}

    async def _dashboard_timeliness_metrics(
        self,
        *,
        context: QualityReadContext,
        visible: Any,
    ) -> tuple[
        dict[tuple[str, str, str], _DashboardRuleMetric],
        dict[tuple[str, str, str], tuple[QualityDashboardRisk, ...]],
    ]:
        if not context.profile_allowed:
            return {}, {}
        workspace_id = context.subject.workspace_id
        ranked_profiles = (
            select(
                AssetProfileSnapshotModel.id.label("snapshot_id"),
                AssetProfileSnapshotModel.asset_id,
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
                AssetProfileSnapshotModel.profile_kind.in_(("FULL", "PARTITION")),
                AssetProfileSnapshotModel.completeness == "COMPLETE",
            )
        ).subquery("ranked_quality_dashboard_profiles")
        latest_profiles = (
            select(
                ranked_profiles.c.snapshot_id,
                ranked_profiles.c.asset_id,
            ).where(ranked_profiles.c.ordinal == 1)
        ).subquery("latest_quality_dashboard_profiles")
        profile_present = AssetProfileSnapshotModel.id.is_not(None)
        profile_current = and_(
            profile_present,
            AssetProfileSnapshotModel.stale_at > context.observed_at,
        )
        rows = list(
            (
                await self._session.execute(
                    select(
                        visible.c.platform,
                        visible.c.database_name,
                        visible.c.schema_name,
                        func.count(func.distinct(visible.c.id)).label("target_count"),
                        func.count(func.distinct(latest_profiles.c.asset_id)).label(
                            "counted_count"
                        ),
                        func.count(func.distinct(visible.c.id))
                        .filter(profile_current)
                        .label("current_count"),
                        func.count(func.distinct(visible.c.id))
                        .filter(latest_profiles.c.asset_id.is_(None))
                        .label("missing_count"),
                        func.count(func.distinct(visible.c.id))
                        .filter(
                            and_(
                                profile_present,
                                AssetProfileSnapshotModel.stale_at <= context.observed_at,
                            )
                        )
                        .label("stale_count"),
                    )
                    .select_from(visible)
                    .outerjoin(
                        latest_profiles,
                        latest_profiles.c.asset_id == visible.c.id,
                    )
                    .outerjoin(
                        AssetProfileSnapshotModel,
                        and_(
                            AssetProfileSnapshotModel.workspace_id == workspace_id,
                            AssetProfileSnapshotModel.id == latest_profiles.c.snapshot_id,
                        ),
                    )
                    .group_by(
                        visible.c.platform,
                        visible.c.database_name,
                        visible.c.schema_name,
                    )
                )
            ).all()
        )
        metrics = {
            _schema_key(row.platform, row.database_name, row.schema_name): _DashboardRuleMetric(
                counted_target_count=int(row.counted_count),
                target_count=int(row.target_count),
                valid_value_count=int(row.current_count),
                evaluated_value_count=int(row.target_count),
                advisory_failed_count=int(row.missing_count),
                blocking_failed_count=int(row.stale_count),
                risk_count=int(row.missing_count) + int(row.stale_count),
            )
            for row in rows
        }
        risk_rows = list(
            (
                await self._session.execute(
                    select(
                        visible.c.id.label("asset_id"),
                        visible.c.name.label("asset_name"),
                        visible.c.platform,
                        visible.c.database_name,
                        visible.c.schema_name,
                        AssetProfileSnapshotModel.id.label("snapshot_id"),
                        AssetProfileSnapshotModel.profiled_at,
                        AssetProfileSnapshotModel.stale_at,
                    )
                    .select_from(visible)
                    .outerjoin(
                        latest_profiles,
                        latest_profiles.c.asset_id == visible.c.id,
                    )
                    .outerjoin(
                        AssetProfileSnapshotModel,
                        and_(
                            AssetProfileSnapshotModel.workspace_id == workspace_id,
                            AssetProfileSnapshotModel.id == latest_profiles.c.snapshot_id,
                        ),
                    )
                    .where(
                        or_(
                            latest_profiles.c.asset_id.is_(None),
                            AssetProfileSnapshotModel.stale_at <= context.observed_at,
                        )
                    )
                    .order_by(
                        AssetProfileSnapshotModel.profiled_at,
                        visible.c.name,
                        visible.c.id,
                    )
                    .limit(_DASHBOARD_RISK_QUERY_LIMIT)
                )
            ).all()
        )
        risks: dict[tuple[str, str, str], list[QualityDashboardRisk]] = {}
        for row in risk_rows:
            key = _schema_key(row.platform, row.database_name, row.schema_name)
            selected = risks.setdefault(key, [])
            if len(selected) >= _DASHBOARD_RISKS_PER_INDICATOR:
                continue
            missing = row.snapshot_id is None
            age_days = (
                max(0, (context.observed_at - row.profiled_at).days)
                if row.profiled_at is not None
                else None
            )
            selected.append(
                QualityDashboardRisk(
                    risk_id=canonical_json_hash(
                        {
                            "contract": "QUALITY_DASHBOARD_TIMELINESS_RISK_V1",
                            "asset_id": str(row.asset_id),
                            "snapshot_id": (
                                str(row.snapshot_id) if row.snapshot_id is not None else None
                            ),
                        }
                    ),
                    asset_id=row.asset_id,
                    asset_name=row.asset_name,
                    field_identifier=None,
                    severity="ADVISORY" if missing else "BLOCKING",
                    outcome="ADVISORY_FAIL" if missing else "BLOCKING_FAIL",
                    score_basis_points=None if missing else 0,
                    evaluated_count=None,
                    failed_count=None,
                    observed_at=row.profiled_at,
                    detail=(
                        "완전한 최신 Profile 증거가 없습니다."
                        if missing
                        else f"최신 Profile이 {age_days:,}일 전에 생성되어 stale 기준을 넘었습니다."
                    ),
                )
            )
        return metrics, {key: tuple(values) for key, values in risks.items()}

    def _visible_assets(self, context: QualityReadContext) -> Any:
        return select(
            AssetProjectionModel.id,
            AssetProjectionModel.name,
            AssetProjectionModel.platform,
            AssetProjectionModel.database_name,
            AssetProjectionModel.schema_name,
            AssetProjectionModel.classification,
            AssetProjectionModel.system_id,
            AssetProjectionModel.domain_id,
        ).where(and_(*catalog_asset_scope_conditions(context.subject, context.access)))

    async def _field_summaries(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> tuple[QualityFieldSummary, ...]:
        configured_rows = list(
            (
                await self._session.execute(
                    select(
                        QualityRuleDefinitionModel.field_identifier,
                        func.count(QualityRuleDefinitionModel.id).label("configured"),
                        func.count(QualityRuleDefinitionModel.id)
                        .filter(QualityRuleSetVersionModel.state == "ACTIVE")
                        .label("active"),
                    )
                    .join(
                        QualityRuleSetVersionModel,
                        and_(
                            QualityRuleSetVersionModel.workspace_id
                            == QualityRuleDefinitionModel.workspace_id,
                            QualityRuleSetVersionModel.id
                            == QualityRuleDefinitionModel.rule_set_version_id,
                        ),
                    )
                    .join(
                        QualityRuleSetModel,
                        and_(
                            QualityRuleSetModel.workspace_id
                            == QualityRuleSetVersionModel.workspace_id,
                            QualityRuleSetModel.id == QualityRuleSetVersionModel.rule_set_id,
                        ),
                    )
                    .where(
                        QualityRuleDefinitionModel.workspace_id == workspace_id,
                        QualityRuleSetModel.asset_id == asset_id,
                        QualityRuleSetModel.state == "ACTIVE",
                        QualityRuleSetVersionModel.state.in_(("PROPOSED", "APPROVED", "ACTIVE")),
                    )
                    .group_by(QualityRuleDefinitionModel.field_identifier)
                )
            ).all()
        )
        configured = {
            row.field_identifier: (int(row.configured), int(row.active)) for row in configured_rows
        }
        if not configured:
            return ()
        active_versions = (
            select(
                QualityRuleSetVersionModel.id.label("version_id"),
                QualityRuleSetVersionModel.rule_set_id,
            )
            .join(
                QualityRuleSetModel,
                and_(
                    QualityRuleSetModel.workspace_id == QualityRuleSetVersionModel.workspace_id,
                    QualityRuleSetModel.id == QualityRuleSetVersionModel.rule_set_id,
                ),
            )
            .where(
                QualityRuleSetVersionModel.workspace_id == workspace_id,
                QualityRuleSetVersionModel.state == "ACTIVE",
                QualityRuleSetModel.asset_id == asset_id,
                QualityRuleSetModel.state == "ACTIVE",
            )
        ).subquery("active_field_quality_versions")
        ranked_runs = (
            select(
                QualityValidationRunModel.id.label("run_id"),
                QualityValidationRunModel.rule_set_version_id,
                QualityValidationRunModel.completed_at,
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
            .where(
                QualityValidationRunModel.workspace_id == workspace_id,
                QualityValidationRunModel.asset_id == asset_id,
                QualityValidationRunModel.state == "SUCCEEDED",
            )
        ).subquery("ranked_field_quality_runs")
        latest_runs = (
            select(
                ranked_runs.c.run_id,
                ranked_runs.c.rule_set_version_id,
                ranked_runs.c.completed_at,
            ).where(ranked_runs.c.ordinal == 1)
        ).subquery("latest_field_quality_runs")
        evidence_rows = list(
            (
                await self._session.execute(
                    select(
                        QualityRuleDefinitionModel.field_identifier,
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "PASS")
                        .label("passed"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "ADVISORY_FAIL")
                        .label("advisory"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "BLOCKING_FAIL")
                        .label("blocking"),
                        func.max(latest_runs.c.completed_at).label("latest_evaluated_at"),
                    )
                    .select_from(active_versions)
                    .join(
                        QualityRuleDefinitionModel,
                        and_(
                            QualityRuleDefinitionModel.workspace_id == workspace_id,
                            QualityRuleDefinitionModel.rule_set_version_id
                            == active_versions.c.version_id,
                        ),
                    )
                    .outerjoin(
                        latest_runs,
                        latest_runs.c.rule_set_version_id == active_versions.c.version_id,
                    )
                    .outerjoin(
                        QualityExpectationResultModel,
                        and_(
                            QualityExpectationResultModel.workspace_id == workspace_id,
                            QualityExpectationResultModel.run_id == latest_runs.c.run_id,
                            QualityExpectationResultModel.rule_definition_id
                            == QualityRuleDefinitionModel.id,
                        ),
                    )
                    .group_by(QualityRuleDefinitionModel.field_identifier)
                )
            ).all()
        )
        evidence = {
            row.field_identifier: _FieldQualityAggregate(
                configured_rule_count=configured[row.field_identifier][0],
                active_rule_count=configured[row.field_identifier][1],
                passed_count=int(row.passed),
                advisory_failed_count=int(row.advisory),
                blocking_failed_count=int(row.blocking),
                latest_evaluated_at=row.latest_evaluated_at,
            )
            for row in evidence_rows
        }
        values: list[QualityFieldSummary] = []
        for field_identifier, counts in sorted(configured.items()):
            aggregate = evidence.get(
                field_identifier,
                _FieldQualityAggregate(
                    configured_rule_count=counts[0],
                    active_rule_count=counts[1],
                    passed_count=0,
                    advisory_failed_count=0,
                    blocking_failed_count=0,
                    latest_evaluated_at=None,
                ),
            )
            values.append(
                QualityFieldSummary(
                    field_identifier=field_identifier,
                    configured_rule_count=aggregate.configured_rule_count,
                    active_rule_count=aggregate.active_rule_count,
                    evaluated_rule_count=aggregate.evaluated_rule_count,
                    passed_count=aggregate.passed_count,
                    advisory_failed_count=aggregate.advisory_failed_count,
                    blocking_failed_count=aggregate.blocking_failed_count,
                    latest_score_basis_points=aggregate.score_basis_points,
                    latest_quality_outcome=aggregate.outcome,
                    latest_evaluated_at=aggregate.latest_evaluated_at,
                )
            )
        return tuple(values)

    async def _field_rules(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        field_identifier: str,
    ) -> tuple[QualityFieldRuleSummary, ...]:
        rows = list(
            (
                await self._session.execute(
                    select(
                        QualityRuleDefinitionModel,
                        QualityRuleSetVersionModel,
                        QualityRuleSetModel,
                    )
                    .join(
                        QualityRuleSetVersionModel,
                        and_(
                            QualityRuleSetVersionModel.workspace_id
                            == QualityRuleDefinitionModel.workspace_id,
                            QualityRuleSetVersionModel.id
                            == QualityRuleDefinitionModel.rule_set_version_id,
                        ),
                    )
                    .join(
                        QualityRuleSetModel,
                        and_(
                            QualityRuleSetModel.workspace_id
                            == QualityRuleSetVersionModel.workspace_id,
                            QualityRuleSetModel.id == QualityRuleSetVersionModel.rule_set_id,
                        ),
                    )
                    .where(
                        QualityRuleDefinitionModel.workspace_id == workspace_id,
                        QualityRuleDefinitionModel.field_identifier == field_identifier,
                        QualityRuleSetModel.asset_id == asset_id,
                        QualityRuleSetModel.state == "ACTIVE",
                        QualityRuleSetVersionModel.state.in_(("PROPOSED", "APPROVED", "ACTIVE")),
                    )
                    .order_by(
                        case((QualityRuleSetVersionModel.state == "ACTIVE", 0), else_=1),
                        desc(QualityRuleSetVersionModel.version_number),
                        QualityRuleDefinitionModel.ordinal,
                    )
                    .limit(200)
                )
            ).all()
        )
        return tuple(
            QualityFieldRuleSummary(
                rule_definition_id=definition.id,
                rule_set_id=rule_set.id,
                rule_set_name=rule_set.name,
                version_id=version.id,
                version_number=version.version_number,
                version_state=version.state,
                kind=definition.kind,
                severity=definition.severity,
                parameters=dict(definition.parameters),
            )
            for definition, version, rule_set in rows
        )

    async def _field_runs(
        self,
        *,
        context: QualityReadContext,
        asset_id: UUID,
        field_identifier: str,
    ) -> tuple[QualityFieldRunSummary, ...]:
        workspace_id = context.subject.workspace_id
        target_versions = select(QualityRuleDefinitionModel.rule_set_version_id).where(
            QualityRuleDefinitionModel.workspace_id == workspace_id,
            QualityRuleDefinitionModel.field_identifier == field_identifier,
        )
        run_rows = await self._run_rows(
            context=context,
            conditions=(
                QualityValidationRunModel.asset_id == asset_id,
                QualityValidationRunModel.rule_set_version_id.in_(target_versions),
            ),
            limit=50,
        )
        run_ids = tuple(row[0].id for row in run_rows)
        metrics: dict[UUID, Any] = {}
        if run_ids:
            metric_rows = list(
                (
                    await self._session.execute(
                        select(
                            QualityExpectationResultModel.run_id,
                            func.count(QualityExpectationResultModel.id)
                            .filter(QualityExpectationResultModel.outcome == "PASS")
                            .label("passed"),
                            func.count(QualityExpectationResultModel.id)
                            .filter(QualityExpectationResultModel.outcome == "ADVISORY_FAIL")
                            .label("advisory"),
                            func.count(QualityExpectationResultModel.id)
                            .filter(QualityExpectationResultModel.outcome == "BLOCKING_FAIL")
                            .label("blocking"),
                            func.coalesce(
                                func.sum(QualityExpectationResultModel.evaluated_count), 0
                            ).label("evaluated"),
                            func.coalesce(
                                func.sum(QualityExpectationResultModel.missing_count), 0
                            ).label("missing"),
                            func.coalesce(
                                func.sum(QualityExpectationResultModel.unexpected_count), 0
                            ).label("unexpected"),
                        )
                        .join(
                            QualityRuleDefinitionModel,
                            and_(
                                QualityRuleDefinitionModel.workspace_id
                                == QualityExpectationResultModel.workspace_id,
                                QualityRuleDefinitionModel.id
                                == QualityExpectationResultModel.rule_definition_id,
                            ),
                        )
                        .where(
                            QualityExpectationResultModel.workspace_id == workspace_id,
                            QualityExpectationResultModel.run_id.in_(run_ids),
                            QualityRuleDefinitionModel.field_identifier == field_identifier,
                        )
                        .group_by(QualityExpectationResultModel.run_id)
                    )
                ).all()
            )
            metrics = {row.run_id: row for row in metric_rows}
        values: list[QualityFieldRunSummary] = []
        for model, rule_set_name, _asset_name in run_rows:
            metric = metrics.get(model.id)
            passed = int(metric.passed) if metric is not None else 0
            advisory = int(metric.advisory) if metric is not None else 0
            blocking = int(metric.blocking) if metric is not None else 0
            field_outcome, field_score = _field_run_quality(
                state=model.state,
                passed=passed,
                advisory_failed=advisory,
                blocking_failed=blocking,
            )
            values.append(
                QualityFieldRunSummary(
                    run_id=model.id,
                    rule_set_id=model.rule_set_id,
                    rule_set_name=rule_set_name,
                    state=model.state,
                    run_quality_outcome=model.quality_outcome,
                    field_quality_outcome=field_outcome,
                    score_basis_points=field_score,
                    passed_count=passed,
                    advisory_failed_count=advisory,
                    blocking_failed_count=blocking,
                    evaluated_value_count=(int(metric.evaluated) if metric is not None else 0),
                    missing_count=(int(metric.missing) if metric is not None else 0),
                    unexpected_count=(int(metric.unexpected) if metric is not None else 0),
                    created_at=model.created_at,
                    completed_at=model.completed_at,
                    failure_code=model.failure_code,
                )
            )
        return tuple(values)

    async def _field_trend(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        field_identifier: str,
        since: datetime,
    ) -> tuple[QualityTrendPoint, ...]:
        bucket = func.date_trunc("day", QualityValidationRunModel.completed_at)
        rows = list(
            (
                await self._session.execute(
                    select(
                        bucket.label("bucket_start"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "PASS")
                        .label("passed"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "ADVISORY_FAIL")
                        .label("advisory"),
                        func.count(QualityExpectationResultModel.id)
                        .filter(QualityExpectationResultModel.outcome == "BLOCKING_FAIL")
                        .label("blocking"),
                    )
                    .join(
                        QualityRuleDefinitionModel,
                        and_(
                            QualityRuleDefinitionModel.workspace_id
                            == QualityExpectationResultModel.workspace_id,
                            QualityRuleDefinitionModel.id
                            == QualityExpectationResultModel.rule_definition_id,
                        ),
                    )
                    .join(
                        QualityValidationRunModel,
                        and_(
                            QualityValidationRunModel.workspace_id
                            == QualityExpectationResultModel.workspace_id,
                            QualityValidationRunModel.id == QualityExpectationResultModel.run_id,
                        ),
                    )
                    .where(
                        QualityExpectationResultModel.workspace_id == workspace_id,
                        QualityValidationRunModel.asset_id == asset_id,
                        QualityValidationRunModel.state == "SUCCEEDED",
                        QualityValidationRunModel.completed_at.is_not(None),
                        QualityValidationRunModel.completed_at >= since,
                        QualityRuleDefinitionModel.field_identifier == field_identifier,
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

    async def _asset_summaries(
        self,
        *,
        context: QualityReadContext,
        rows: Sequence[AssetProjectionModel],
    ) -> tuple[QualityAssetSummary, ...]:
        asset_ids = tuple(row.id for row in rows)
        counts = await self._active_rule_set_counts(
            workspace_id=context.subject.workspace_id,
            asset_ids=asset_ids,
        )
        quality_aggregates = await self._latest_active_rule_set_aggregates(
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
        return tuple(
            QualityAssetSummary(
                asset_id=row.id,
                name=row.name,
                platform=row.platform,
                database_name=row.database_name,
                schema_name=row.schema_name,
                classification=Classification(row.classification).name,
                lifecycle=row.lifecycle,
                active_rule_set_count=counts.get(row.id, 0),
                latest_run_state=("SUCCEEDED" if row.id in quality_aggregates else None),
                latest_quality_outcome=(
                    quality_aggregates[row.id].outcome if row.id in quality_aggregates else None
                ),
                latest_score_basis_points=(
                    quality_aggregates[row.id].score_basis_points
                    if row.id in quality_aggregates
                    else None
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
            for row in rows
        )

    async def _latest_active_rule_set_aggregates(
        self, *, workspace_id: UUID, asset_ids: Sequence[UUID]
    ) -> dict[UUID, _AssetQualityAggregate]:
        if not asset_ids:
            return {}
        active_versions = (
            select(
                QualityRuleSetModel.asset_id,
                QualityRuleSetModel.id.label("rule_set_id"),
                QualityRuleSetVersionModel.id.label("version_id"),
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
                QualityRuleSetModel.workspace_id == workspace_id,
                QualityRuleSetModel.asset_id.in_(asset_ids),
                QualityRuleSetModel.state == "ACTIVE",
            )
        ).subquery("active_asset_quality_versions")
        ranked = (
            select(
                active_versions.c.asset_id,
                active_versions.c.rule_set_id,
                QualityValidationRunModel.passed_count,
                QualityValidationRunModel.advisory_failed_count,
                QualityValidationRunModel.blocking_failed_count,
                func.row_number()
                .over(
                    partition_by=(
                        active_versions.c.asset_id,
                        active_versions.c.rule_set_id,
                    ),
                    order_by=(
                        desc(QualityValidationRunModel.completed_at),
                        desc(QualityValidationRunModel.id),
                    ),
                )
                .label("ordinal"),
            )
            .join(
                QualityValidationRunModel,
                and_(
                    QualityValidationRunModel.workspace_id == workspace_id,
                    QualityValidationRunModel.rule_set_id == active_versions.c.rule_set_id,
                    QualityValidationRunModel.rule_set_version_id == active_versions.c.version_id,
                    QualityValidationRunModel.asset_id == active_versions.c.asset_id,
                ),
            )
            .where(
                QualityValidationRunModel.workspace_id == workspace_id,
                QualityValidationRunModel.state == "SUCCEEDED",
            )
        ).subquery("ranked_active_asset_quality_runs")
        rows = list(
            (
                await self._session.execute(
                    select(
                        ranked.c.asset_id,
                        func.coalesce(func.sum(ranked.c.passed_count), 0).label("passed"),
                        func.coalesce(
                            func.sum(ranked.c.advisory_failed_count),
                            0,
                        ).label("advisory"),
                        func.coalesce(
                            func.sum(ranked.c.blocking_failed_count),
                            0,
                        ).label("blocking"),
                    )
                    .where(ranked.c.ordinal == 1)
                    .group_by(ranked.c.asset_id)
                )
            ).all()
        )
        return {
            row.asset_id: _AssetQualityAggregate(
                passed_count=int(row.passed),
                advisory_failed_count=int(row.advisory),
                blocking_failed_count=int(row.blocking),
            )
            for row in rows
        }

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


def _common_template_summary(
    model: QualityCommonRuleTemplateModel,
    mapping_count: int,
) -> QualityCommonRuleTemplateSummary:
    rules: list[QualityCommonRuleTemplateRule] = []
    for value in model.rules:
        field_identifier = value.get("field_identifier")
        kind = value.get("kind")
        severity = value.get("severity")
        parameters = value.get("parameters")
        if (
            not isinstance(field_identifier, str)
            or not isinstance(kind, str)
            or not isinstance(severity, str)
            or not isinstance(parameters, dict)
            or any(not isinstance(key, str) for key in parameters)
        ):
            raise RuntimeError("A stored Quality common Rule template is invalid.")
        rules.append(
            QualityCommonRuleTemplateRule(
                field_identifier=field_identifier,
                kind=kind,
                severity=severity,
                parameters=dict(parameters),
            )
        )
    return QualityCommonRuleTemplateSummary(
        template_id=model.id,
        name=model.name,
        description=model.description,
        rules=tuple(rules),
        mapping_count=mapping_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _score_policy_summary() -> QualityScorePolicySummary:
    return QualityScorePolicySummary(
        policy_id=QUALITY_SCORE_POLICY_ID,
        policy_version=QUALITY_SCORE_POLICY_VERSION,
        policy_hash=QUALITY_SCORE_POLICY_HASH,
        calculation="passed / (passed + advisory_failed + blocking_failed)",
        pass_condition=(  # noqa: S106 - outcome rule, never credential material
            "evaluated > 0 and advisory_failed = 0 and blocking_failed = 0"
        ),
        warn_condition="blocking_failed = 0 and advisory_failed > 0",
        fail_condition="blocking_failed > 0",
        unknown_condition="evaluated = 0",
    )


def _managed_rule_sets() -> tuple[QualityManagedRuleSet, ...]:
    return (
        QualityManagedRuleSet(
            indicator_id="ACCURACY",
            name="정확성",
            definition="검증 대상으로 지정한 값이 허용 범위 또는 패턴과 일치하는지 평가합니다.",
            calculation=("최근 성공 실행의 (평가 값 수 - 예상 밖 값 수) ÷ 평가 값 수"),
            target_grain="FIELD",
            rule_kinds=("RANGE", "REGEX"),
            contract_version=_DASHBOARD_INDICATOR_CONTRACT,
        ),
        QualityManagedRuleSet(
            indicator_id="COMPLETENESS",
            name="완전성",
            definition="검증 대상으로 지정한 필드에 값이 빠짐없이 존재하는지 평가합니다.",
            calculation="최근 성공 실행의 (평가 값 수 - 결측 값 수) ÷ 평가 값 수",
            target_grain="FIELD",
            rule_kinds=("NOT_NULL",),
            contract_version=_DASHBOARD_INDICATOR_CONTRACT,
        ),
        QualityManagedRuleSet(
            indicator_id="TIMELINESS",
            name="적시성",
            definition=(
                "각 테이블의 최신 완전 Profile이 서버가 보관한 stale 기준 안에 있는지 평가합니다."
            ),
            calculation="현재 Profile을 보유한 테이블 수 ÷ 대상 테이블 수",
            target_grain="TABLE",
            rule_kinds=(),
            contract_version=_DASHBOARD_INDICATOR_CONTRACT,
        ),
    )


def _rule_dashboard_indicator(
    *,
    indicator_id: QualityIndicatorId,
    metric: _DashboardRuleMetric | None,
    risks: tuple[QualityDashboardRisk, ...],
) -> QualityDashboardIndicator:
    if indicator_id not in {"ACCURACY", "COMPLETENESS"}:
        raise ValueError("The dashboard Rule indicator is unsupported.")
    label = "정확성" if indicator_id == "ACCURACY" else "완전성"
    if metric is None:
        return QualityDashboardIndicator(
            indicator_id=indicator_id,
            counted_target_count=0,
            target_count=0,
            coverage_basis_points=None,
            score_basis_points=None,
            outcome="UNKNOWN",
            risk_count=0,
            evaluated_value_count=0,
            report_state="FACTS_ONLY",
            report_reason_code="QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE",
            report_summary=(
                f"활성 {label} 대상 필드가 없습니다. 공통 룰셋에서 대상 필드를 지정한 뒤 "
                "성공 실행이 완료되면 이 지표를 계산합니다."
            ),
            risks=(),
        )
    return QualityDashboardIndicator(
        indicator_id=indicator_id,
        counted_target_count=metric.counted_target_count,
        target_count=metric.target_count,
        coverage_basis_points=metric.coverage_basis_points,
        score_basis_points=metric.score_basis_points,
        outcome=metric.outcome,
        risk_count=metric.risk_count,
        evaluated_value_count=metric.evaluated_value_count,
        report_state="FACTS_ONLY",
        report_reason_code="QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE",
        report_summary=(
            f"{label} 대상 {metric.target_count:,}개 필드 중 "
            f"{metric.counted_target_count:,}개가 최근 성공 실행에서 평가되었습니다. "
            f"위험 룰 결과는 {metric.risk_count:,}개이며, 지표는 "
            f"{_basis_points_text(metric.score_basis_points)}입니다."
        ),
        risks=risks,
    )


def _timeliness_dashboard_indicator(
    *,
    metric: _DashboardRuleMetric | None,
    risks: tuple[QualityDashboardRisk, ...],
    profile_allowed: bool,
) -> QualityDashboardIndicator:
    if not profile_allowed:
        return QualityDashboardIndicator(
            indicator_id="TIMELINESS",
            counted_target_count=0,
            target_count=0,
            coverage_basis_points=None,
            score_basis_points=None,
            outcome="UNKNOWN",
            risk_count=0,
            evaluated_value_count=0,
            report_state="UNAVAILABLE",
            report_reason_code="QUALITY_PROFILE_READ_DENIED",
            report_summary=(
                "Profile 열람 권한이 없어 적시성 근거와 위험 테이블을 표시하지 않습니다."
            ),
            risks=(),
        )
    if metric is None:
        return QualityDashboardIndicator(
            indicator_id="TIMELINESS",
            counted_target_count=0,
            target_count=0,
            coverage_basis_points=None,
            score_basis_points=None,
            outcome="UNKNOWN",
            risk_count=0,
            evaluated_value_count=0,
            report_state="FACTS_ONLY",
            report_reason_code="QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE",
            report_summary="적시성을 평가할 권한 범위의 테이블이 없습니다.",
            risks=(),
        )
    return QualityDashboardIndicator(
        indicator_id="TIMELINESS",
        counted_target_count=metric.counted_target_count,
        target_count=metric.target_count,
        coverage_basis_points=metric.coverage_basis_points,
        score_basis_points=metric.score_basis_points,
        outcome=metric.outcome,
        risk_count=metric.risk_count,
        evaluated_value_count=metric.evaluated_value_count,
        report_state="FACTS_ONLY",
        report_reason_code="QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE",
        report_summary=(
            f"대상 {metric.target_count:,}개 테이블 중 "
            f"{metric.counted_target_count:,}개가 완전한 최신 Profile을 보유합니다. "
            f"stale 또는 미수집 위험 테이블은 {metric.risk_count:,}개이며, "
            f"적시성은 {_basis_points_text(metric.score_basis_points)}입니다."
        ),
        risks=risks,
    )


def _schema_key(
    platform: str | None,
    database_name: str | None,
    schema_name: str | None,
) -> tuple[str, str, str]:
    sentinel = "\u0000"
    return (
        platform if platform is not None else sentinel,
        database_name if database_name is not None else sentinel,
        schema_name if schema_name is not None else sentinel,
    )


def _schema_id(platform: str, database_name: str, schema_name: str) -> str:
    sentinel = "\u0000"
    return canonical_json_hash(
        {
            "contract": "QUALITY_SCHEMA_ID_V1",
            "platform": None if platform == sentinel else platform,
            "database_name": None if database_name == sentinel else database_name,
            "schema_name": None if schema_name == sentinel else schema_name,
        }
    )


def _basis_points_text(value: int | None) -> str:
    if value is None:
        return "평가 없음"
    percentage = value / 100
    return f"{percentage:.2f}".rstrip("0").rstrip(".") + "%"


def _asset_cursor_resource(
    *,
    query: str,
    platform: str | None,
    database_name: str | None,
    schema_name: str | None,
) -> str:
    scope = canonical_json_hash(
        {
            "contract": "QUALITY_ASSET_FILTER_V2",
            "query": query,
            "platform": platform,
            "database_name": database_name,
            "schema_name": schema_name,
        }
    )
    return f"assets:{scope}"


def _literal_contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _run_basis_points(model: QualityValidationRunModel) -> int | None:
    if model.state != "SUCCEEDED":
        return None
    passed = model.passed_count or 0
    evaluated = passed + (model.advisory_failed_count or 0) + (model.blocking_failed_count or 0)
    return _basis_points(passed, evaluated)


def _field_run_quality(
    *,
    state: str,
    passed: int,
    advisory_failed: int,
    blocking_failed: int,
) -> tuple[str, int | None]:
    if state != "SUCCEEDED":
        return "UNKNOWN", None
    evaluated = passed + advisory_failed + blocking_failed
    return (
        _outcome(
            evaluated=evaluated,
            advisory_failed=advisory_failed,
            blocking_failed=blocking_failed,
        ),
        _basis_points(passed, evaluated),
    )


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
