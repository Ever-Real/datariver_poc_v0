from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from datariver.domain.quality import (
    QualityOutcome,
    RuleKind,
    RuleSetVersionState,
    RuleSeverity,
    ValidationRunState,
)


@dataclass(frozen=True, slots=True)
class QualityAssetTarget:
    workspace_id: UUID
    asset_id: UUID
    field_identifiers: frozenset[str]
    system_id: UUID | None
    domain_id: UUID | None
    owner_department_id: UUID | None
    classification: int
    lifecycle: str
    source_version: str
    schema_hash: str


@dataclass(frozen=True, slots=True)
class RuleDefinitionInput:
    field_identifier: str
    kind: RuleKind
    severity: RuleSeverity
    parameters: dict[str, object]


@dataclass(frozen=True, slots=True)
class RuleSetVersionSummary:
    version_id: UUID
    rule_set_id: UUID
    version_number: int
    state: RuleSetVersionState
    rule_count: int
    author_id: UUID


@dataclass(frozen=True, slots=True)
class ValidationRunSummary:
    run_id: UUID
    rule_set_version_id: UUID
    state: ValidationRunState
    outcome: QualityOutcome
    score: int | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CompilerCapability:
    available: bool
    contract_version: str
    gx_version: str
    supported_rule_kinds: frozenset[RuleKind]
    reason_code: str | None = None
