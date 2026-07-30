from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from hashlib import sha256
from uuid import UUID

from datariver.application.quality_execution_ports import (
    QualityExpectationCompilerPort,
    QualityResultSanitizerPort,
)
from datariver.application.quality_worker_contracts import (
    QualityBatchExecutorPort,
    QualityExecutionStorePort,
    QualityRuleResult,
    QualitySourceResolverPort,
)
from datariver.domain.common import DomainError, canonical_json_hash


class QualityExecutionWorker:
    """Run one claimed Quality validation without retaining source values or raw GX output."""

    def __init__(
        self,
        *,
        store: QualityExecutionStorePort,
        manifest: QualitySourceResolverPort,
        compiler: QualityExpectationCompilerPort,
        sanitizer: QualityResultSanitizerPort,
        executor: QualityBatchExecutorPort,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
        call_id_factory: Callable[[], str],
    ) -> None:
        self._store = store
        self._manifest = manifest
        self._compiler = compiler
        self._sanitizer = sanitizer
        self._executor = executor
        self._workspace_id = workspace_id
        self._worker_subject_id = worker_subject_id
        self._worker_fingerprint = worker_fingerprint
        self._lease_seconds = lease_seconds
        self._call_id_factory = call_id_factory

    async def run_once(self) -> bool:
        claim = await self._store.claim_next(
            workspace_id=self._workspace_id,
            worker_subject_id=self._worker_subject_id,
            worker_fingerprint=self._worker_fingerprint,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return False
        call_id = self._call_id_factory()
        source_opened = False
        try:
            source = self._manifest.resolve(
                asset_id=claim.asset_id,
                source_connection_profile_id=claim.source_connection_profile_id,
                source_connection_profile_version=claim.source_connection_profile_version,
                source_connection_profile_hash=claim.source_connection_profile_hash,
                workload_profile_id=claim.workload_profile_id,
                workload_profile_version=claim.workload_profile_version,
                workload_profile_hash=claim.workload_profile_hash,
            )
            expectations = tuple(self._compiler.compile(rule.definition) for rule in claim.rules)
            await self._store.freeze_source_access(
                claim=claim,
                worker_subject_id=self._worker_subject_id,
                hard_timeout_seconds=source.workload.hard_timeout_seconds,
                cancel_timeout_seconds=source.workload.cancel_timeout_seconds,
                close_timeout_seconds=source.workload.close_timeout_seconds,
                completion_timeout_seconds=source.workload.completion_timeout_seconds,
            )
            source_opened = True
            async with self._executor.execute(
                claim=claim,
                source=source,
                expectations=expectations,
                fence=lambda: self._store.assert_statement_fence(
                    claim=claim,
                    worker_subject_id=self._worker_subject_id,
                ),
            ) as raw_results:
                if len(raw_results) != len(claim.rules):
                    raise RuntimeError("GX returned an incomplete Quality result set.")
                normalized = tuple(
                    QualityRuleResult(
                        rule_definition_id=rule.rule_definition_id,
                        severity=rule.severity,
                        result=self._sanitizer.sanitize(raw),
                    )
                    for rule, raw in zip(claim.rules, raw_results, strict=True)
                )
                gx_result_hash = canonical_json_hash(
                    [result.result.result_document() for result in normalized]
                )
            # Completion is deliberately outside the source context: the source connection
            # has been closed before any durable terminal state is written.
            await self._store.complete(
                claim=claim,
                worker_subject_id=self._worker_subject_id,
                call_id=call_id,
                compiler_result_hash=canonical_json_hash(
                    [expectation.configuration_document() for expectation in expectations]
                ),
                gx_result_hash=gx_result_hash,
                normalized_result_hash=canonical_json_hash(
                    [result.document() for result in normalized]
                ),
                results=normalized,
            )
        except Exception as error:
            retryable = not isinstance(error, DomainError)
            failure_code = _failure_code(error, source_opened=source_opened)
            with suppress(Exception):
                await self._store.fail(
                    claim=claim,
                    worker_subject_id=self._worker_subject_id,
                    call_id=call_id,
                    failure_code=failure_code,
                    retryable=retryable,
                )
        return True


def _failure_code(error: Exception, *, source_opened: bool) -> str:
    prefix = "SOURCE" if source_opened else "PRE_SOURCE"
    error_name = type(error).__name__.upper()
    digest = sha256(error_name.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}_EXECUTION_{digest}"[:100]
