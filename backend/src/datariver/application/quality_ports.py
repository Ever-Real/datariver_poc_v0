from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.application.quality_contracts import (
    CompilerCapability,
    QualityAssetTarget,
    ValidationRunSummary,
)
from datariver.domain.quality import (
    QualityRuleSet,
    QualityRuleSetVersion,
    RetentionBinding,
    RetentionKind,
    RuleDefinition,
)


class QualityAssetTargetReader(Protocol):
    async def get_current_target(
        self, *, workspace_id: UUID, asset_id: UUID, for_update: bool
    ) -> QualityAssetTarget | None: ...


class QualityRetentionResolver(Protocol):
    async def resolve(
        self,
        *,
        workspace_id: UUID,
        kind: RetentionKind,
        resource_type: str,
        resource_id: UUID,
        basis_at: datetime,
    ) -> RetentionBinding: ...

    async def revalidate(self, *, workspace_id: UUID, binding: RetentionBinding) -> bool: ...


class QualityRuleCompilerPort(Protocol):
    async def capability(self) -> CompilerCapability: ...

    async def compile(self, rule: RuleDefinition) -> dict[str, object]: ...


class QualityRuleSetRepository(Protocol):
    async def add(self, rule_set: QualityRuleSet) -> None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, rule_set_id: UUID
    ) -> QualityRuleSet | None: ...

    async def save(self, rule_set: QualityRuleSet) -> None: ...


class QualityRuleSetVersionRepository(Protocol):
    async def add(self, version: QualityRuleSetVersion) -> None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, version_id: UUID
    ) -> QualityRuleSetVersion | None: ...

    async def active_for_update(
        self, *, workspace_id: UUID, rule_set_id: UUID
    ) -> QualityRuleSetVersion | None: ...

    async def save(self, version: QualityRuleSetVersion) -> None: ...


class QualityRunReader(Protocol):
    async def list_authorized(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> tuple[tuple[ValidationRunSummary, ...], str | None]: ...


class QualityUnitOfWork(Protocol):
    rule_sets: QualityRuleSetRepository
    rule_set_versions: QualityRuleSetVersionRepository

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...

    async def __aenter__(self) -> QualityUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class QualityUnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[QualityUnitOfWork]: ...
