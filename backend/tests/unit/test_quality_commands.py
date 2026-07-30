from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from datariver.application.quality_command_contracts import (
    QualityAuthoringAsset,
    QualityAuthoringField,
    QualityDeploymentBinding,
    QualityRuleProposalResult,
)
from datariver.application.quality_command_ports import (
    QualityCommandRepository,
    QualityDeploymentDirectory,
)
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.quality_commands import QualityCommandService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError

NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)


class _Repository:
    def __init__(self, asset: QualityAuthoringAsset, *, retention_ready: bool = True) -> None:
        self.asset = asset
        self.ready = retention_ready
        self.command: object | None = None

    async def retention_ready(self, *, workspace_id: UUID) -> bool:
        del workspace_id
        return self.ready

    async def get_authoring_assets(
        self,
        *,
        workspace_id: UUID,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[QualityAuthoringAsset, ...]:
        del workspace_id
        return (self.asset,) if asset_ids == (self.asset.asset_id,) else ()

    async def create_rule_sets(self, *, command: object) -> QualityRuleProposalResult:
        self.command = command
        return QualityRuleProposalResult(items=(), replayed=False)


class _Directory:
    def __init__(self, binding: QualityDeploymentBinding | None) -> None:
        self.binding = binding

    @property
    def authoring_available(self) -> bool:
        return self.binding is not None

    def resolve(self, *, asset_id: UUID) -> QualityDeploymentBinding | None:
        if self.binding is None or self.binding.asset_id != asset_id:
            return None
        return self.binding


def _subject(
    workspace_id: UUID,
    *,
    system_ids: frozenset[UUID] = frozenset(),
    domain_ids: frozenset[UUID] = frozenset(),
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
        allowed_system_ids=system_ids,
        allowed_domain_ids=domain_ids,
        allowed_actions=frozenset({Action.QUALITY_RULE_PROPOSE}),
    )


@pytest.mark.asyncio
async def test_proposal_uses_server_directory_and_one_atomic_repository_command() -> None:
    workspace_id, asset_id, system_id, domain_id = uuid4(), uuid4(), uuid4(), uuid4()
    asset = QualityAuthoringAsset(
        asset_id=asset_id,
        name="yield_summary",
        system_id=system_id,
        domain_id=domain_id,
        classification=2,
        lifecycle="ACTIVE",
        source_version="source-v4",
        column_names=("yield_rate",),
        column_names_truncated=False,
    )
    binding = QualityDeploymentBinding(
        asset_id=asset_id,
        system_id=system_id,
        schema_hash="a" * 64,
        fields=(
            QualityAuthoringField(
                field_identifier="yield_rate",
                display_path="yield_rate",
                logical_type="DECIMAL",
                supported_rule_kinds=("NOT_NULL", "RANGE"),
            ),
        ),
        source_connection_profile_id="semiconductor-readonly",
        source_connection_profile_version=1,
        source_connection_profile_hash="b" * 64,
        workload_profile_id="quality-bounded",
        workload_profile_version=1,
        workload_profile_hash="c" * 64,
    )
    repository = _Repository(asset)
    service = QualityCommandService(
        repository=cast(QualityCommandRepository, repository),
        directory=cast(QualityDeploymentDirectory, _Directory(binding)),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        worker_enabled=False,
    )

    result = await service.propose_rule_sets(
        subject=_subject(
            workspace_id,
            system_ids=frozenset({system_id}),
            domain_ids=frozenset({domain_id}),
        ),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="quality-proposal",
        idempotency_key="quality-proposal-key-0001",
        name_prefix="Yield contract",
        asset_ids=(asset_id,),
        rules=(
            {
                "field_identifier": "yield_rate",
                "kind": "RANGE",
                "severity": "BLOCKING",
                "parameters": {
                    "value_type": "DECIMAL",
                    "min_value": "0",
                    "max_value": "100",
                    "inclusive_min": True,
                    "inclusive_max": True,
                },
            },
        ),
    )

    assert result.replayed is False
    assert repository.command is not None


@pytest.mark.asyncio
async def test_proposal_fails_closed_before_authorization_without_retention_readiness() -> None:
    workspace_id, asset_id = uuid4(), uuid4()
    asset = QualityAuthoringAsset(
        asset_id=asset_id,
        name="asset",
        system_id=None,
        domain_id=None,
        classification=0,
        lifecycle="ACTIVE",
        source_version="v1",
        column_names=("id",),
        column_names_truncated=False,
    )
    service = QualityCommandService(
        repository=cast(QualityCommandRepository, _Repository(asset, retention_ready=False)),
        directory=cast(QualityDeploymentDirectory, _Directory(None)),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        worker_enabled=False,
    )

    with pytest.raises(ConflictError) as caught:
        await service.propose_rule_sets(
            subject=_subject(workspace_id),
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="quality-not-ready",
            idempotency_key="quality-not-ready-key-01",
            name_prefix="Contract",
            asset_ids=(asset_id,),
            rules=(
                {
                    "field_identifier": "id",
                    "kind": "NOT_NULL",
                    "severity": "BLOCKING",
                    "parameters": {},
                },
            ),
        )

    assert caught.value.details["code"] == "AUTHORING_READINESS_UNAVAILABLE"
