from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from datariver.application.quality_execution_contracts import (
    CompiledQualityExpectation,
    SanitizedQualityExpectationResult,
)
from datariver.domain.quality import RuleDefinition, RuleSeverity


@dataclass(frozen=True, slots=True)
class ClaimedQualityRule:
    rule_definition_id: UUID
    severity: RuleSeverity
    definition: RuleDefinition


@dataclass(frozen=True, slots=True)
class QualityRunClaim:
    workspace_id: UUID
    run_id: UUID
    attempt_id: UUID
    lease_epoch: int
    lease_token: str
    asset_id: UUID
    source_connection_profile_id: str
    source_connection_profile_version: int
    source_connection_profile_hash: str
    workload_profile_id: str
    workload_profile_version: int
    workload_profile_hash: str
    compiler_hash: str
    rules: tuple[ClaimedQualityRule, ...]


@dataclass(frozen=True, slots=True)
class QualityRuleResult:
    rule_definition_id: UUID
    severity: RuleSeverity
    result: SanitizedQualityExpectationResult

    @property
    def outcome(self) -> str:
        if self.result.success:
            return "PASS"
        return "BLOCKING_FAIL" if self.severity is RuleSeverity.BLOCKING else "ADVISORY_FAIL"

    def document(self) -> dict[str, object]:
        return {
            "rule_definition_id": str(self.rule_definition_id),
            "outcome": self.outcome,
            "evaluated_count": self.result.evaluated_count,
            "missing_count": self.result.missing_count,
            "unexpected_count": self.result.unexpected_count,
            "missing_ratio": self.result.missing_ratio,
            "unexpected_ratio": self.result.unexpected_ratio,
            "duration_ms": self.result.duration_ms,
            "result_hash": self.result.result_hash,
        }


QualityFence = Callable[[], Awaitable[int]]


class QualityWorkloadContract(Protocol):
    hard_timeout_seconds: int
    cancel_timeout_seconds: int
    close_timeout_seconds: int
    completion_timeout_seconds: int
    statement_timeout_seconds: int
    lock_timeout_seconds: int
    idle_transaction_timeout_seconds: int
    max_rows: int
    max_bytes: int


class QualityPostgresSourceContract(Protocol):
    host: str
    port: int
    database: str
    schema: str
    relation: str
    username: str
    password_secret_ref: str
    tls_mode: object
    allowed_ips: tuple[str, ...]

    def column_for(self, field_identifier: str) -> str: ...


class ResolvedQualitySourceContract(Protocol):
    source: QualityPostgresSourceContract
    workload: QualityWorkloadContract


class QualitySourceResolverPort(Protocol):
    def resolve(
        self,
        *,
        asset_id: UUID,
        source_connection_profile_id: str,
        source_connection_profile_version: int,
        source_connection_profile_hash: str,
        workload_profile_id: str,
        workload_profile_version: int,
        workload_profile_hash: str,
    ) -> ResolvedQualitySourceContract: ...


class QualityExecutionSession(Protocol):
    """A source session that is guaranteed closed when its context exits."""

    async def __aenter__(self) -> Sequence[Mapping[str, object]]: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class QualityBatchExecutorPort(Protocol):
    def execute(
        self,
        *,
        claim: QualityRunClaim,
        source: ResolvedQualitySourceContract,
        expectations: Sequence[CompiledQualityExpectation],
        fence: QualityFence,
    ) -> QualityExecutionSession: ...


class QualityExecutionStorePort(Protocol):
    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> QualityRunClaim | None: ...

    async def freeze_source_access(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
        hard_timeout_seconds: int,
        cancel_timeout_seconds: int,
        close_timeout_seconds: int,
        completion_timeout_seconds: int,
    ) -> datetime: ...

    async def assert_statement_fence(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
    ) -> int: ...

    async def complete(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
        call_id: str,
        compiler_result_hash: str,
        gx_result_hash: str,
        normalized_result_hash: str,
        results: Sequence[QualityRuleResult],
    ) -> None: ...

    async def fail(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
        call_id: str,
        failure_code: str,
        retryable: bool,
    ) -> None: ...
