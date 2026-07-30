from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import TextClause

from datariver.application.errors import ExternalDependencyError
from datariver.application.quality_worker_contracts import (
    ClaimedQualityRule,
    QualityExecutionStorePort,
    QualityRuleResult,
    QualityRunClaim,
)
from datariver.application.services.quality_dispatch import (
    QualityDispatchResult,
    QualityDispatchStore,
)
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError
from datariver.domain.quality import RuleDefinition, RuleKind, RuleSeverity
from datariver.infrastructure.db.rls import set_security_context

_DISPATCH = text(
    """
    SELECT quality.dispatch_due_validation_runs_v1(
        :workspace_id, :call_id, :max_due_schedules, :max_created_runs
    )
    """
)
_CLAIM = text(
    """
    SELECT quality.claim_validation_run_v1(
        :workspace_id, :worker_fingerprint, :lease_token, :lease_seconds
    )
    """
)
_FREEZE = text(
    """
    SELECT quality.freeze_source_access_v1(
        :workspace_id, :run_id, :attempt_id, :lease_epoch, :lease_token,
        :hard_timeout_seconds, :cancel_timeout_seconds, :close_timeout_seconds,
        :completion_timeout_seconds
    )
    """
)
_FENCE = text(
    """
    SELECT quality.assert_source_statement_fence_v1(
        :workspace_id, :run_id, :attempt_id, :lease_epoch, :lease_token
    )
    """
)
_COMPLETE = text(
    """
    SELECT quality.complete_validation_run_v1(
        :workspace_id, :run_id, :attempt_id, :lease_epoch, :lease_token,
        :call_id, :compiler_result_hash, :gx_result_hash,
        :normalized_result_hash, :results
    )
    """
).bindparams(bindparam("results", type_=JSONB))
_FAIL = text(
    """
    SELECT quality.fail_validation_run_v1(
        :workspace_id, :run_id, :attempt_id, :lease_epoch, :lease_token,
        :call_id, :failure_code, :retryable
    )
    """
)


class SqlQualityDispatchStore(QualityDispatchStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def dispatch(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        call_id: str,
        max_due_schedules: int,
        max_created_runs: int,
    ) -> QualityDispatchResult:
        try:
            async with self._session_factory() as session, session.begin():
                await set_security_context(
                    session,
                    workspace_id=workspace_id,
                    subject_id=subject_id,
                )
                document = await session.scalar(
                    _DISPATCH,
                    {
                        "workspace_id": workspace_id,
                        "call_id": call_id,
                        "max_due_schedules": max_due_schedules,
                        "max_created_runs": max_created_runs,
                    },
                )
        except DBAPIError as error:
            sqlstate = getattr(error.orig, "sqlstate", None)
            if sqlstate == "42501":
                raise ForbiddenError("Quality dispatch authority is unavailable.") from error
            if sqlstate == "23514":
                raise ExternalDependencyError(
                    "Quality dispatch prerequisites are unavailable.",
                    dependency="quality_control_plane",
                    retryable=True,
                    provider_code="QUALITY_DISPATCH_PREREQUISITE_UNAVAILABLE",
                ) from error
            if sqlstate in {"23503", "23505"}:
                raise ConflictError("Quality dispatch state changed concurrently.") from error
            raise
        value = _mapping(document, "Quality dispatch result")
        _exact_keys(
            value,
            {"created_run_ids", "created_run_count", "skipped_window_count", "replayed"},
            "Quality dispatch result",
        )
        run_ids = tuple(UUID(item) for item in _string_array(value["created_run_ids"], 100))
        created_count = _count(value["created_run_count"], maximum=100)
        skipped_count = _count(value["skipped_window_count"])
        replayed = value["replayed"]
        if created_count != len(run_ids) or not isinstance(replayed, bool):
            raise ConflictError("The database returned an invalid Quality dispatch receipt.")
        return QualityDispatchResult(
            created_run_ids=run_ids,
            skipped_window_count=skipped_count,
            replayed=replayed,
        )


class SqlQualityExecutionStore(QualityExecutionStorePort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> QualityRunClaim | None:
        lease_token = secrets.token_urlsafe(32)
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=workspace_id,
                subject_id=worker_subject_id,
            )
            document = await session.scalar(
                _CLAIM,
                {
                    "workspace_id": workspace_id,
                    "worker_fingerprint": worker_fingerprint,
                    "lease_token": lease_token,
                    "lease_seconds": lease_seconds,
                },
            )
        if document is None:
            return None
        return _claim_from_document(_mapping(document, "Quality claim"), lease_token=lease_token)

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
        value = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_FREEZE,
            extra={
                "hard_timeout_seconds": hard_timeout_seconds,
                "cancel_timeout_seconds": cancel_timeout_seconds,
                "close_timeout_seconds": close_timeout_seconds,
                "completion_timeout_seconds": completion_timeout_seconds,
            },
        )
        if not isinstance(value, datetime):
            raise ConflictError("The database returned an invalid source-access deadline.")
        return value

    async def assert_statement_fence(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
    ) -> int:
        value = await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_FENCE,
        )
        return _count(value, maximum=86_400_000)

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
        await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_COMPLETE,
            extra={
                "call_id": call_id,
                "compiler_result_hash": compiler_result_hash,
                "gx_result_hash": gx_result_hash,
                "normalized_result_hash": normalized_result_hash,
                "results": [result.document() for result in results],
            },
        )

    async def fail(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
        call_id: str,
        failure_code: str,
        retryable: bool,
    ) -> None:
        await self._claim_scalar(
            claim=claim,
            worker_subject_id=worker_subject_id,
            statement=_FAIL,
            extra={
                "call_id": call_id,
                "failure_code": failure_code,
                "retryable": retryable,
            },
        )

    async def _claim_scalar(
        self,
        *,
        claim: QualityRunClaim,
        worker_subject_id: UUID,
        statement: TextClause,
        extra: Mapping[str, object] | None = None,
    ) -> object:
        parameters: dict[str, object] = {
            "workspace_id": claim.workspace_id,
            "run_id": claim.run_id,
            "attempt_id": claim.attempt_id,
            "lease_epoch": claim.lease_epoch,
            "lease_token": claim.lease_token,
        }
        parameters.update(extra or {})
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=claim.workspace_id,
                subject_id=worker_subject_id,
            )
            return await session.scalar(statement, parameters)


def _claim_from_document(document: Mapping[str, object], *, lease_token: str) -> QualityRunClaim:
    _exact_keys(
        document,
        {
            "workspace_id",
            "run_id",
            "attempt_id",
            "lease_epoch",
            "asset_id",
            "source_connection_profile_id",
            "source_connection_profile_version",
            "source_connection_profile_hash",
            "workload_profile_id",
            "workload_profile_version",
            "workload_profile_hash",
            "compiler_hash",
            "rules",
        },
        "Quality claim",
    )
    raw_rules = document["rules"]
    if not isinstance(raw_rules, list) or not 1 <= len(raw_rules) <= 1_000:
        raise ValidationError("The Quality claim has an invalid rule set.")
    rules = tuple(_claimed_rule(value) for value in raw_rules)
    if len({rule.rule_definition_id for rule in rules}) != len(rules):
        raise ValidationError("The Quality claim repeats a rule.")
    return QualityRunClaim(
        workspace_id=_uuid(document["workspace_id"]),
        run_id=_uuid(document["run_id"]),
        attempt_id=_uuid(document["attempt_id"]),
        lease_epoch=_positive_count(document["lease_epoch"]),
        lease_token=lease_token,
        asset_id=_uuid(document["asset_id"]),
        source_connection_profile_id=_text(document["source_connection_profile_id"], 255),
        source_connection_profile_version=_positive_count(
            document["source_connection_profile_version"]
        ),
        source_connection_profile_hash=_hash(document["source_connection_profile_hash"]),
        workload_profile_id=_text(document["workload_profile_id"], 255),
        workload_profile_version=_positive_count(document["workload_profile_version"]),
        workload_profile_hash=_hash(document["workload_profile_hash"]),
        compiler_hash=_hash(document["compiler_hash"]),
        rules=rules,
    )


def _claimed_rule(value: object) -> ClaimedQualityRule:
    document = _mapping(value, "Quality claimed rule")
    _exact_keys(
        document,
        {
            "rule_definition_id",
            "ordinal",
            "field_identifier",
            "kind",
            "severity",
            "parameters",
            "definition_hash",
        },
        "Quality claimed rule",
    )
    rule_id = _uuid(document["rule_definition_id"])
    parameters = _mapping(document["parameters"], "Quality rule parameters")
    rule = RuleDefinition(
        rule_id=rule_id,
        ordinal=_positive_count(document["ordinal"]),
        field_identifier=_text(document["field_identifier"], 255),
        kind=RuleKind(_text(document["kind"], 20)),
        severity=RuleSeverity(_text(document["severity"], 20)),
        parameters=dict(parameters),
    )
    if rule.definition_hash != _hash(document["definition_hash"]):
        raise ConflictError("The claimed Quality rule definition has drifted.")
    return ClaimedQualityRule(
        rule_definition_id=rule_id,
        severity=rule.severity,
        definition=rule,
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValidationError(f"{label} is invalid.")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValidationError(f"{label} has an invalid field set.")


def _uuid(value: object) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as error:
        raise ValidationError("The Quality database UUID is invalid.") from error


def _text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip():
        raise ValidationError("The Quality database text is invalid.")
    return value


def _hash(value: object) -> str:
    result = _text(value, 64)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ValidationError("The Quality database hash is invalid.")
    return result


def _count(value: object, *, maximum: int = (1 << 63) - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValidationError("The Quality database count is invalid.")
    return value


def _positive_count(value: object) -> int:
    result = _count(value)
    if result == 0:
        raise ValidationError("The Quality database counter must be positive.")
    return result


def _string_array(value: object, maximum: int) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(not isinstance(item, str) for item in value)
    ):
        raise ValidationError("The Quality database string array is invalid.")
    return cast(list[str], value)
