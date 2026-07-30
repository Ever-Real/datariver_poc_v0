# ruff: noqa: S608 -- identifiers are exact manifest values and are always quoted.
from __future__ import annotations

import asyncio
import ipaddress
import ssl
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from types import TracebackType

import asyncpg  # type: ignore[import-untyped]

from datariver.application.quality_execution_contracts import CompiledQualityExpectation
from datariver.application.quality_worker_contracts import (
    QualityBatchExecutorPort,
    QualityExecutionSession,
    QualityFence,
    QualityRunClaim,
    ResolvedQualitySourceContract,
)
from datariver.domain.common import ConflictError
from datariver.domain.quality import RuleKind
from datariver.infrastructure.quality.source_manifest import QualitySourceSecretReader


class AsyncpgGxAggregateExecutor(QualityBatchExecutorPort):
    """Execute fixed GX semantics as source-side aggregates; never fetch source rows."""

    def __init__(self, *, secret_reader: QualitySourceSecretReader) -> None:
        self._secret_reader = secret_reader

    def execute(
        self,
        *,
        claim: QualityRunClaim,
        source: ResolvedQualitySourceContract,
        expectations: Sequence[CompiledQualityExpectation],
        fence: QualityFence,
    ) -> QualityExecutionSession:
        return _AsyncpgExecutionSession(
            claim=claim,
            source=source,
            expectations=expectations,
            fence=fence,
            password=self._secret_reader.resolve(source.source.password_secret_ref),
        )


class _AsyncpgExecutionSession(QualityExecutionSession):
    def __init__(
        self,
        *,
        claim: QualityRunClaim,
        source: ResolvedQualitySourceContract,
        expectations: Sequence[CompiledQualityExpectation],
        fence: QualityFence,
        password: str,
    ) -> None:
        self._claim = claim
        self._source = source
        self._expectations = expectations
        self._fence = fence
        self._password = password
        self._connection: asyncpg.Connection[asyncpg.Record] | None = None
        self._transaction: asyncpg.Transaction | None = None

    async def __aenter__(self) -> Sequence[Mapping[str, object]]:
        try:
            profile = self._source.source
            workload = self._source.workload
            try:
                address = str(ipaddress.ip_address(profile.host))
            except ValueError as error:
                raise ConflictError(
                    "Quality source DNS execution is disabled until a pinned resolver "
                    "is configured.",
                    details={"code": "SOURCE_DNS_PIN_UNAVAILABLE"},
                ) from error
            if address not in profile.allowed_ips:
                raise ConflictError(
                    "The Quality source address is outside its exact allowlist.",
                    details={"code": "SOURCE_ADDRESS_DENIED"},
                )
            ssl_context = _ssl_context(str(profile.tls_mode))
            async with asyncio.timeout(workload.hard_timeout_seconds):
                await self._fence()
                self._connection = await asyncpg.connect(
                    host=address,
                    port=profile.port,
                    user=profile.username,
                    password=self._password,
                    database=profile.database,
                    ssl=ssl_context,
                    timeout=min(30, workload.hard_timeout_seconds),
                    command_timeout=workload.statement_timeout_seconds,
                    statement_cache_size=0,
                    server_settings={
                        "application_name": "datariver-quality-worker",
                        "statement_timeout": f"{workload.statement_timeout_seconds * 1000}",
                        "lock_timeout": f"{workload.lock_timeout_seconds * 1000}",
                        "idle_in_transaction_session_timeout": (
                            f"{workload.idle_transaction_timeout_seconds * 1000}"
                        ),
                        "default_transaction_read_only": "on",
                    },
                )
                self._transaction = self._connection.transaction(
                    isolation="repeatable_read",
                    readonly=True,
                )
                await self._transaction.start()
                await self._preflight()
                return await self._execute_rules()
        except BaseException:
            # __aexit__ is not called when __aenter__ fails. Shield cleanup so a
            # cancellation cannot strand a source transaction or retain its password.
            with suppress(BaseException):
                await asyncio.shield(self._close())
            self._password = ""
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        del exc_type, exc_value, traceback
        await self._close()
        return None

    async def _close(self) -> None:
        transaction = self._transaction
        connection = self._connection
        self._transaction = None
        self._connection = None
        try:
            if transaction is not None:
                async with asyncio.timeout(self._source.workload.cancel_timeout_seconds):
                    await transaction.rollback()
        finally:
            try:
                if connection is not None:
                    async with asyncio.timeout(self._source.workload.close_timeout_seconds):
                        await connection.close()
            finally:
                self._password = ""

    async def _preflight(self) -> None:
        connection = self._require_connection()
        profile = self._source.source
        relation_name = f"{profile.schema}.{profile.relation}"
        await self._fence()
        relation_bytes = await connection.fetchval(
            "SELECT pg_relation_size($1::regclass)",
            relation_name,
        )
        if (
            isinstance(relation_bytes, bool)
            or not isinstance(relation_bytes, int)
            or relation_bytes < 0
            or relation_bytes > self._source.workload.max_bytes
        ):
            raise ConflictError(
                "The Quality source relation exceeds its byte budget.",
                details={"code": "SOURCE_BYTE_BUDGET_EXCEEDED"},
            )
        await self._fence()
        row_count = await connection.fetchval(
            f"SELECT count(*) FROM {_qualified(profile.schema, profile.relation)}"
        )
        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count < 0
            or row_count > self._source.workload.max_rows
        ):
            raise ConflictError(
                "The Quality source relation exceeds its row budget.",
                details={"code": "SOURCE_ROW_BUDGET_EXCEEDED"},
            )

    async def _execute_rules(self) -> tuple[Mapping[str, object], ...]:
        if len(self._expectations) != len(self._claim.rules):
            raise ConflictError("The Quality compiler result set is incomplete.")
        results: list[Mapping[str, object]] = []
        for claimed, expectation in zip(
            self._claim.rules,
            self._expectations,
            strict=True,
        ):
            await self._fence()
            started = time.monotonic()
            if claimed.definition.kind is RuleKind.NOT_NULL:
                counts = await self._not_null_counts(claimed.definition.field_identifier)
            elif claimed.definition.kind is RuleKind.RANGE:
                counts = await self._range_counts(
                    claimed.definition.field_identifier,
                    claimed.definition.parameters,
                )
            else:  # pragma: no cover - domain and compiler both reject this boundary
                raise ConflictError("The Quality rule kind is not executable.")
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            results.append(
                {
                    "success": counts["unexpected_count"] == 0,
                    "duration_ms": duration_ms,
                    "expectation_config": expectation.gx_configuration(),
                    "result": counts,
                    "exception_info": {
                        "raised_exception": False,
                        "exception_message": None,
                        "exception_traceback": None,
                    },
                }
            )
        return tuple(results)

    async def _not_null_counts(self, field_identifier: str) -> dict[str, int]:
        connection = self._require_connection()
        profile = self._source.source
        column = _identifier(profile.column_for(field_identifier))
        row = await connection.fetchrow(
            "SELECT count(*) AS element_count, "
            f"count(*) FILTER (WHERE {column} IS NULL) AS unexpected_count "
            f"FROM {_qualified(profile.schema, profile.relation)}"
        )
        assert row is not None
        return {
            "element_count": int(row["element_count"]),
            "missing_count": int(row["unexpected_count"]),
            "unexpected_count": int(row["unexpected_count"]),
        }

    async def _range_counts(
        self,
        field_identifier: str,
        parameters: Mapping[str, object],
    ) -> dict[str, int]:
        connection = self._require_connection()
        profile = self._source.source
        column = _identifier(profile.column_for(field_identifier))
        value_type = parameters["value_type"]
        if not isinstance(value_type, str):
            raise ConflictError("The Quality RANGE value type is not executable.")
        cast_name = {
            "DECIMAL": "numeric",
            "DATE": "date",
            "TIMESTAMP": "timestamptz",
        }.get(value_type)
        if cast_name is None:
            raise ConflictError("The Quality RANGE value type is not executable.")
        min_operator = ">=" if parameters["inclusive_min"] is True else ">"
        max_operator = "<=" if parameters["inclusive_max"] is True else "<"
        row = await connection.fetchrow(
            f"SELECT count(*) AS element_count, "
            f"count(*) FILTER (WHERE {column} IS NULL) AS missing_count, "
            f"count(*) FILTER (WHERE {column} IS NOT NULL AND NOT "
            f"({column} {min_operator} $1::{cast_name} AND "
            f"{column} {max_operator} $2::{cast_name})) AS unexpected_count "
            f"FROM {_qualified(profile.schema, profile.relation)}",
            parameters["min_value"],
            parameters["max_value"],
        )
        assert row is not None
        return {
            "element_count": int(row["element_count"]),
            "missing_count": int(row["missing_count"]),
            "unexpected_count": int(row["unexpected_count"]),
        }

    def _require_connection(self) -> asyncpg.Connection[asyncpg.Record]:
        if self._connection is None:
            raise RuntimeError("The Quality source connection is not open.")
        return self._connection


def _identifier(value: str) -> str:
    # The manifest already enforces PostgreSQL identifiers. Quoting remains mandatory so
    # reserved words never become syntax and no user string becomes an SQL fragment.
    return '"' + value.replace('"', '""') + '"'


def _qualified(schema: str, relation: str) -> str:
    return f"{_identifier(schema)}.{_identifier(relation)}"


def _ssl_context(mode: str) -> ssl.SSLContext:
    normalized = mode.rsplit(".", 1)[-1]
    if normalized == "REQUIRE":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    context = ssl.create_default_context()
    context.check_hostname = normalized == "VERIFY_FULL"
    return context
