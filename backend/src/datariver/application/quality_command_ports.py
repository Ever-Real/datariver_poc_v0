from __future__ import annotations

from typing import Protocol
from uuid import UUID

from datariver.application.quality_command_contracts import (
    QualityAuthoringAsset,
    QualityCommonRuleTemplateCreateCommand,
    QualityCommonRuleTemplateCreateResult,
    QualityDeploymentBinding,
    QualityManualRunResult,
    QualityRuleCommandTarget,
    QualityRuleProposalCommand,
    QualityRuleProposalResult,
    QualityRuleVersionCommandResult,
)


class QualityDeploymentDirectory(Protocol):
    @property
    def authoring_available(self) -> bool: ...

    def resolve(self, *, asset_id: UUID) -> QualityDeploymentBinding | None: ...


class QualityCommandRepository(Protocol):
    async def retention_ready(self, *, workspace_id: UUID) -> bool: ...

    async def get_authoring_assets(
        self,
        *,
        workspace_id: UUID,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[QualityAuthoringAsset, ...]: ...

    async def create_rule_sets(
        self,
        *,
        command: QualityRuleProposalCommand,
    ) -> QualityRuleProposalResult: ...

    async def create_common_rule_template(
        self, *, command: QualityCommonRuleTemplateCreateCommand
    ) -> QualityCommonRuleTemplateCreateResult: ...

    async def get_common_rule_template_rules(
        self, *, workspace_id: UUID, template_id: UUID
    ) -> tuple[str, tuple[dict[str, object], ...]] | None: ...

    async def get_rule_command_target(
        self,
        *,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID | None,
    ) -> QualityRuleCommandTarget | None: ...

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
    ) -> QualityRuleVersionCommandResult: ...

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
    ) -> QualityRuleVersionCommandResult: ...

    async def request_manual_run(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        rule_set_id: UUID,
        policy_decision_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> QualityManualRunResult: ...
