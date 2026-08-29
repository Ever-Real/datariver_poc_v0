from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.application.quality_read_contracts import (
    QualityAssetPage,
    QualityAssetSummary,
    QualityAssetWorkspace,
    QualityCommonRuleTemplateDetail,
    QualityCommonRuleTemplateSummary,
    QualityDashboard,
    QualityFieldWorkspace,
    QualityIssuePage,
    QualityOverview,
    QualityReadContext,
    QualityResultPage,
    QualityRuleSetDetail,
    QualityRuleSetPage,
    QualityRunPage,
    QualityRunSummary,
)


class QualityReadRepository(Protocol):
    async def database_now(self) -> datetime: ...

    async def overview(self, *, context: QualityReadContext, days: int) -> QualityOverview: ...

    async def dashboard(self, *, context: QualityReadContext) -> QualityDashboard: ...

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
    ) -> QualityAssetPage: ...

    async def get_assets(
        self, *, context: QualityReadContext, asset_ids: tuple[UUID, ...]
    ) -> tuple[QualityAssetSummary, ...]: ...

    async def get_asset(
        self, *, context: QualityReadContext, asset_id: UUID
    ) -> QualityAssetSummary | None: ...

    async def get_asset_workspace(
        self, *, context: QualityReadContext, asset_id: UUID, days: int
    ) -> QualityAssetWorkspace | None: ...

    async def get_field_workspace(
        self,
        *,
        context: QualityReadContext,
        asset_id: UUID,
        field_identifier: str,
        days: int,
    ) -> QualityFieldWorkspace | None: ...

    async def list_common_rule_templates(
        self, *, context: QualityReadContext
    ) -> tuple[QualityCommonRuleTemplateSummary, ...]: ...

    async def get_common_rule_template(
        self, *, context: QualityReadContext, template_id: UUID
    ) -> QualityCommonRuleTemplateDetail | None: ...

    async def list_rule_sets(
        self, *, context: QualityReadContext, limit: int, cursor: str | None
    ) -> QualityRuleSetPage: ...

    async def get_rule_set(
        self, *, context: QualityReadContext, rule_set_id: UUID
    ) -> QualityRuleSetDetail | None: ...

    async def list_runs(
        self, *, context: QualityReadContext, limit: int, cursor: str | None
    ) -> QualityRunPage: ...

    async def get_run(
        self, *, context: QualityReadContext, run_id: UUID
    ) -> QualityRunSummary | None: ...

    async def list_results(
        self,
        *,
        context: QualityReadContext,
        run_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> QualityResultPage | None: ...

    async def list_issues(
        self, *, context: QualityReadContext, limit: int, cursor: str | None
    ) -> QualityIssuePage: ...
