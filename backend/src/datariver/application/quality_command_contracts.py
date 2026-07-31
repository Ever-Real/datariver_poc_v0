from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from datariver.domain.quality import RuleDefinition

QualityLogicalType = Literal[
    "STRING",
    "INTEGER",
    "DECIMAL",
    "DATE",
    "TIMESTAMP",
    "BOOLEAN",
    "OTHER",
]


@dataclass(frozen=True, slots=True)
class QualityAuthoringField:
    field_identifier: str
    display_path: str
    logical_type: QualityLogicalType
    supported_rule_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityDeploymentBinding:
    asset_id: UUID
    system_id: UUID
    schema_hash: str
    fields: tuple[QualityAuthoringField, ...]
    source_connection_profile_id: str
    source_connection_profile_version: int
    source_connection_profile_hash: str
    workload_profile_id: str
    workload_profile_version: int
    workload_profile_hash: str


@dataclass(frozen=True, slots=True)
class QualityAuthoringAsset:
    asset_id: UUID
    name: str
    system_id: UUID | None
    domain_id: UUID | None
    classification: int
    lifecycle: str
    source_version: str
    column_names: tuple[str, ...]
    column_names_truncated: bool


@dataclass(frozen=True, slots=True)
class QualityAssetAuthoringDetail:
    state: Literal["READY", "UNAVAILABLE"]
    reason_code: str | None
    source_version: str
    schema_hash: str | None
    fields: tuple[QualityAuthoringField, ...]


@dataclass(frozen=True, slots=True)
class QualityRuleProposalTarget:
    asset: QualityAuthoringAsset
    deployment: QualityDeploymentBinding
    rules: tuple[RuleDefinition, ...]


@dataclass(frozen=True, slots=True)
class QualityRuleProposalCommand:
    workspace_id: UUID
    actor_id: UUID
    name_prefix: str
    targets: tuple[QualityRuleProposalTarget, ...]
    request_hash: str
    idempotency_key: str
    template_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class QualityRuleProposalItem:
    asset_id: UUID
    rule_set_id: UUID
    version_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class QualityRuleProposalResult:
    items: tuple[QualityRuleProposalItem, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class QualityCommonRuleTemplateCreateCommand:
    workspace_id: UUID
    actor_id: UUID
    name: str
    description: str | None
    rules: tuple[dict[str, object], ...]
    request_hash: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class QualityCommonRuleTemplateCreateResult:
    template_id: UUID
    replayed: bool


@dataclass(frozen=True, slots=True)
class QualityRuleVersionCommandResult:
    rule_set_id: UUID
    version_id: UUID
    state: str
    version: int


@dataclass(frozen=True, slots=True)
class QualityManualRunResult:
    run_id: UUID
    state: str
    created_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class QualityRuleCommandTarget:
    rule_set_id: UUID
    version_id: UUID | None
    asset_id: UUID
    author_id: UUID
    system_id: UUID | None
    domain_id: UUID | None
    classification: int
    lifecycle: str
    source_version: str
