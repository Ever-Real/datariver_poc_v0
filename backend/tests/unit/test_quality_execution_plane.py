from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import UUID, uuid4

import pytest

from datariver.application.quality_execution_contracts import (
    CompiledQualityExpectation,
    SanitizedQualityExpectationResult,
)
from datariver.application.quality_worker_contracts import (
    ClaimedQualityRule,
    QualityExecutionSession,
    QualityFence,
    QualityRuleResult,
    QualityRunClaim,
    ResolvedQualitySourceContract,
)
from datariver.application.services.quality_execution import QualityExecutionWorker
from datariver.domain.quality import RuleDefinition, RuleKind, RuleSeverity
from datariver.infrastructure.quality.result_sanitizer import StrictGxResultSanitizer

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0069_quality_execution_plane.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"
ROLE_RECONCILIATION = ROOT / "infra/postgres/init/010_roles.sh"


def _load_migration() -> ModuleType:
    specification = importlib.util.spec_from_file_location("quality_execution_0069", MIGRATION)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_0069_is_single_parented_and_capability_closed() -> None:
    migration = _load_migration()
    source = MIGRATION.read_text(encoding="utf-8")
    grants = migration._GRANT_SQL

    assert migration.revision == "0069"
    assert migration.down_revision == "0068"
    assert "session_user = 'datariver_app'" in source
    assert "session_user = 'datariver_quality'" in source
    assert "snapshot.profile_kind IN ('FULL', 'PARTITION')" in source
    assert "'SAMPLE'" not in source
    assert "source_access_deadline <= now_at" in source
    assert "current_quality_target_matches_v1" in source
    assert "partial_unexpected" not in source
    assert "GRANT EXECUTE ON FUNCTION quality.claim_validation_run_v1" in grants
    assert "GRANT INSERT" not in grants
    assert "GRANT UPDATE" not in grants
    assert "GRANT SELECT" not in grants
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES" in grants


def test_0069_terminal_changes_write_history_receipts_and_outbox() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    completion = source.split(
        "CREATE OR REPLACE FUNCTION quality.complete_validation_run_v1",
        maxsplit=1,
    )[1].split(
        "CREATE OR REPLACE FUNCTION quality.fail_validation_run_v1",
        maxsplit=1,
    )[0]

    for marker in (
        "QUALITY_RUN_COMPLETION_EVENT_V1",
        "QUALITY_RUN_FAILURE_EVENT_V1",
        "quality.execution_call_receipts",
        "quality.validation_run.succeeded.v1",
        "quality.validation_run.failed.v1",
        "quality.validation_run.retry_wait.v1",
    ):
        assert marker in source
    assert completion.index("UPDATE quality.validation_attempts") < completion.index(
        "INSERT INTO quality.expectation_results"
    )
    assert completion.index("INSERT INTO quality.expectation_results") < completion.index(
        "UPDATE quality.validation_runs"
    )
    assert source.index("DROP FUNCTION IF EXISTS quality.fail_validation_run_v1") < source.index(
        "DROP FUNCTION IF EXISTS quality.claim_validation_run_v1"
    )


def test_canonical_generator_and_role_reconciliation_include_phase3() -> None:
    generator = GENERATOR.read_text(encoding="utf-8")
    roles = ROLE_RECONCILIATION.read_text(encoding="utf-8")

    assert "_load_quality_phase3_revision" in generator
    assert generator.index("_load_quality_phase3_revision") < generator.index("def build_upgrade")
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA quality" in roles
    for function in (
        "claim_validation_run_v1",
        "freeze_source_access_v1",
        "assert_source_statement_fence_v1",
        "complete_validation_run_v1",
        "fail_validation_run_v1",
    ):
        assert function in roles


@dataclass(frozen=True)
class _Workload:
    hard_timeout_seconds: int = 30
    cancel_timeout_seconds: int = 2
    close_timeout_seconds: int = 2
    completion_timeout_seconds: int = 2
    statement_timeout_seconds: int = 10
    lock_timeout_seconds: int = 1
    idle_transaction_timeout_seconds: int = 20
    max_rows: int = 100
    max_bytes: int = 1_000_000


@dataclass(frozen=True)
class _Source:
    workload: _Workload = _Workload()
    source: object = object()


class _Manifest:
    def __init__(self, source: ResolvedQualitySourceContract) -> None:
        self._source = source

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
    ) -> ResolvedQualitySourceContract:
        del (
            asset_id,
            source_connection_profile_id,
            source_connection_profile_version,
            source_connection_profile_hash,
            workload_profile_id,
            workload_profile_version,
            workload_profile_hash,
        )
        return self._source


class _Compiler:
    def compile(self, rule: RuleDefinition) -> CompiledQualityExpectation:
        return CompiledQualityExpectation(
            rule_definition_hash=rule.definition_hash,
            rule_kind=rule.kind,
            expectation_type="expect_column_values_to_not_be_null",
            kwargs={
                "column": rule.field_identifier,
                "result_format": {
                    "result_format": "SUMMARY",
                    "partial_unexpected_count": 0,
                    "include_config": True,
                    "return_unexpected_index_query": False,
                },
            },
        )


class _Session(QualityExecutionSession):
    def __init__(self, events: list[str], fence: QualityFence) -> None:
        self._events = events
        self._fence = fence

    async def __aenter__(self) -> Sequence[Mapping[str, object]]:
        self._events.append("source_opened")
        await self._fence()
        return (
            {
                "success": True,
                "duration_ms": 5,
                "expectation_config": {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {
                        "result_format": {
                            "partial_unexpected_count": 0,
                        }
                    },
                },
                "result": {
                    "element_count": 10,
                    "missing_count": 0,
                    "unexpected_count": 0,
                },
                "exception_info": {
                    "raised_exception": False,
                    "exception_message": None,
                    "exception_traceback": None,
                },
            },
        )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool | None:
        del exc_type, exc_value, traceback
        self._events.append("source_closed")
        return None


class _Executor:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def execute(
        self,
        *,
        claim: QualityRunClaim,
        source: ResolvedQualitySourceContract,
        expectations: Sequence[CompiledQualityExpectation],
        fence: QualityFence,
    ) -> QualityExecutionSession:
        del claim, source, expectations
        return _Session(self._events, fence)


class _Store:
    def __init__(self, claim: QualityRunClaim, events: list[str]) -> None:
        self._claim = claim
        self._events = events
        self.results: Sequence[QualityRuleResult] = ()
        self.failure_code: str | None = None

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> QualityRunClaim | None:
        del workspace_id, worker_subject_id, worker_fingerprint, lease_seconds
        return self._claim

    async def freeze_source_access(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
        hard_timeout_seconds: int,
        cancel_timeout_seconds: int,
        close_timeout_seconds: int,
        completion_timeout_seconds: int,
    ) -> datetime:
        del (
            claim,
            worker_subject_id,
            hard_timeout_seconds,
            cancel_timeout_seconds,
            close_timeout_seconds,
            completion_timeout_seconds,
        )
        self._events.append("source_frozen")
        return datetime.now(tz=UTC)

    async def assert_statement_fence(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
    ) -> int:
        del claim, worker_subject_id
        self._events.append("statement_fenced")
        return 10_000

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
    ) -> None:
        del (
            claim,
            worker_subject_id,
            call_id,
            compiler_result_hash,
            gx_result_hash,
            normalized_result_hash,
        )
        assert self._events[-1] == "source_closed"
        self._events.append("completed")
        self.results = results

    async def fail(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
        call_id: str,
        failure_code: str,
        retryable: bool,
    ) -> None:
        del claim, worker_subject_id, call_id, retryable
        self.failure_code = failure_code


def _claim() -> QualityRunClaim:
    definition = RuleDefinition.create(
        ordinal=1,
        field_identifier="customer_id",
        kind=RuleKind.NOT_NULL,
        severity=RuleSeverity.BLOCKING,
        parameters={},
    )
    return QualityRunClaim(
        workspace_id=uuid4(),
        run_id=uuid4(),
        attempt_id=uuid4(),
        lease_epoch=1,
        lease_token="lease-token",
        asset_id=uuid4(),
        source_connection_profile_id="warehouse",
        source_connection_profile_version=1,
        source_connection_profile_hash="a" * 64,
        workload_profile_id="bounded",
        workload_profile_version=1,
        workload_profile_hash="b" * 64,
        compiler_hash="c" * 64,
        rules=(
            ClaimedQualityRule(
                rule_definition_id=definition.rule_id,
                severity=definition.severity,
                definition=definition,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_worker_closes_source_before_persisting_sanitized_results() -> None:
    claim = _claim()
    events: list[str] = []
    store = _Store(claim, events)
    worker = QualityExecutionWorker(
        store=store,
        manifest=_Manifest(cast(ResolvedQualitySourceContract, _Source())),
        compiler=_Compiler(),
        sanitizer=StrictGxResultSanitizer(),
        executor=_Executor(events),
        workspace_id=claim.workspace_id,
        worker_subject_id=uuid4(),
        worker_fingerprint="quality-worker-1",
        lease_seconds=60,
        call_id_factory=lambda: "call-1",
    )

    assert await worker.run_once() is True
    assert events == [
        "source_frozen",
        "source_opened",
        "statement_fenced",
        "source_closed",
        "completed",
    ]
    assert len(store.results) == 1
    assert store.results[0].outcome == "PASS"
    assert isinstance(store.results[0].result, SanitizedQualityExpectationResult)
    assert store.failure_code is None
