from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from datariver.application.quality_execution_contracts import (
    GX_COMPILER_CONTRACT,
    GX_RUNTIME_VERSION,
)
from datariver.domain.common import canonical_json_hash
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


QUALITY_COMPILER_HASH = canonical_json_hash(
    {
        "contract": GX_COMPILER_CONTRACT,
        "gx_version": GX_RUNTIME_VERSION,
        "rule_kinds": ["NOT_NULL", "RANGE"],
        "result_contract": "DATARIVER_GX_RESULT_V1",
        "result_format": {
            "include_config": True,
            "partial_unexpected_count": 0,
            "result_format": "SUMMARY",
            "return_unexpected_index_query": False,
        },
    }
)

QUALITY_SCORE_POLICY_ID = "UNWEIGHTED_RULE_PASS_RATE_V1"
QUALITY_SCORE_POLICY_VERSION = 1
QUALITY_SCORE_POLICY_HASH = canonical_json_hash(
    {
        "contract": "QUALITY_SCORE_POLICY_V1",
        "formula": "passed/(passed+advisory_failed+blocking_failed)",
        "outcome_order": ["PASS", "WARN", "FAIL"],
        "policy_id": QUALITY_SCORE_POLICY_ID,
        "policy_version": QUALITY_SCORE_POLICY_VERSION,
        "zero_evaluated": "UNKNOWN",
    }
)
