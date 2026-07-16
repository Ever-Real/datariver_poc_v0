from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed PgBouncer transaction-pooling gate for DataRiver RLS context. "
            "Run only against an isolated integration database containing assets in two workspaces."
        )
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--database-secret-ref", required=True)
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--admin-secret-ref", required=True)
    parser.add_argument("--workspace-a", required=True, type=UUID)
    parser.add_argument("--workspace-b", required=True, type=UUID)
    args = parser.parse_args()
    if args.workspace_a == args.workspace_b:
        parser.error("--workspace-a and --workspace-b must be different")
    return args


def _connection_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("PgBouncer URLs must use a PostgreSQL scheme.")
    if parsed.password is not None:
        raise ValueError("PgBouncer URLs must not embed passwords.")
    if not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("PgBouncer URLs require a host and database name.")
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def _read_secret(reference: str) -> str:
    if not reference.startswith("file:"):
        raise ValueError("PgBouncer probe secrets must use file: references.")
    path = Path(reference.removeprefix("file:")).expanduser()
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("PgBouncer probe secret files cannot be empty.")
    return value


def _config_document(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    document: dict[str, str] = {}
    for row in rows:
        key = str(row.get("key", "")).strip()
        if key:
            document[key] = str(row.get("value", "")).strip()
    return document


def _validate_transaction_pool_config(config: Mapping[str, str]) -> None:
    if config.get("pool_mode") != "transaction":
        raise RuntimeError("PgBouncer test pool must use transaction mode.")
    try:
        default_pool_size = int(config.get("default_pool_size", ""))
    except ValueError as error:
        raise RuntimeError("PgBouncer default_pool_size is not an integer.") from error
    if default_pool_size != 1:
        raise RuntimeError(
            "PgBouncer test pool must set default_pool_size=1 to force server reuse."
        )


def _validate_visible_workspaces(
    *, expected: UUID, other: UUID, rows: Iterable[Mapping[str, Any]]
) -> None:
    counts = {UUID(str(row["workspace_id"])): int(row["asset_count"]) for row in rows}
    if set(counts) != {expected} or counts[expected] < 1:
        raise RuntimeError(
            "The RLS probe requires at least one visible fixture asset "
            "in only the expected workspace."
        )
    if other in counts:
        raise RuntimeError("Cross-workspace asset rows were visible through RLS.")


async def _verify_admin_console(*, url: str, password: str) -> None:
    connection = await asyncpg.connect(
        dsn=_connection_url(url),
        password=password,
        command_timeout=5,
        statement_cache_size=0,
    )
    try:
        rows = await connection.fetch("SHOW CONFIG")
        _validate_transaction_pool_config(_config_document(rows))
    finally:
        await connection.close()


async def _set_context(
    connection: asyncpg.Connection, *, workspace_id: UUID, subject_id: UUID
) -> int:
    await connection.execute(
        "SELECT set_config('app.workspace_id', $1, true), set_config('app.subject_id', $2, true)",
        str(workspace_id),
        str(subject_id),
    )
    return int(await connection.fetchval("SELECT pg_backend_pid()"))


async def _assert_clean(connection: asyncpg.Connection) -> int:
    workspace, subject, visible = await connection.fetchrow(
        "SELECT current_setting('app.workspace_id', true), "
        "current_setting('app.subject_id', true), "
        "(SELECT count(*) FROM catalog.assets_projection)"
    )
    if workspace not in {None, ""} or subject not in {None, ""}:
        raise RuntimeError("Transaction-local RLS context leaked into the next transaction.")
    if int(visible) != 0:
        raise RuntimeError("Assets were visible without a transaction-local RLS context.")
    return int(await connection.fetchval("SELECT pg_backend_pid()"))


async def _assert_workspace_scope(
    connection: asyncpg.Connection, *, expected: UUID, other: UUID
) -> None:
    rows = await connection.fetch(
        "SELECT workspace_id, count(*) AS asset_count "
        "FROM catalog.assets_projection GROUP BY workspace_id"
    )
    _validate_visible_workspaces(expected=expected, other=other, rows=rows)
    other_count = await connection.fetchval(
        "SELECT count(*) FROM catalog.assets_projection WHERE workspace_id = $1", other
    )
    if int(other_count) != 0:
        raise RuntimeError("A direct cross-workspace predicate bypassed RLS.")


async def _commit_case(
    pool: asyncpg.Pool, *, workspace_id: UUID, other: UUID, subject_id: UUID
) -> tuple[int, int]:
    async with pool.acquire() as connection:
        async with connection.transaction():
            context_pid = await _set_context(
                connection, workspace_id=workspace_id, subject_id=subject_id
            )
            await _assert_workspace_scope(connection, expected=workspace_id, other=other)
        async with connection.transaction():
            clean_pid = await _assert_clean(connection)
    return context_pid, clean_pid


async def _rollback_case(
    pool: asyncpg.Pool, *, workspace_id: UUID, subject_id: UUID
) -> tuple[int, int]:
    async with pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        context_pid = await _set_context(
            connection, workspace_id=workspace_id, subject_id=subject_id
        )
        await transaction.rollback()
        async with connection.transaction():
            clean_pid = await _assert_clean(connection)
    return context_pid, clean_pid


async def _error_case(
    pool: asyncpg.Pool, *, workspace_id: UUID, subject_id: UUID
) -> tuple[int, int]:
    async with pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        context_pid = await _set_context(
            connection, workspace_id=workspace_id, subject_id=subject_id
        )
        try:
            await connection.execute("SELECT 1 / 0")
        except asyncpg.PostgresError:
            await transaction.rollback()
        else:
            raise RuntimeError("The forced database error did not occur.")
        async with connection.transaction():
            clean_pid = await _assert_clean(connection)
    return context_pid, clean_pid


async def _cancel_case(pool: asyncpg.Pool, *, workspace_id: UUID, subject_id: UUID) -> None:
    context_set = asyncio.Event()

    async def cancelled_transaction() -> None:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await _set_context(connection, workspace_id=workspace_id, subject_id=subject_id)
                context_set.set()
                await connection.execute("SELECT pg_sleep(30)")

    task = asyncio.create_task(cancelled_transaction())
    await asyncio.wait_for(context_set.wait(), timeout=5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    async with pool.acquire() as connection, connection.transaction():
        await _assert_clean(connection)


async def run_probe(args: argparse.Namespace) -> None:
    database_url = _connection_url(str(args.database_url))
    database_password = _read_secret(str(args.database_secret_ref))
    admin_password = _read_secret(str(args.admin_secret_ref))
    await _verify_admin_console(url=str(args.admin_url), password=admin_password)
    pool = await asyncpg.create_pool(
        dsn=database_url,
        password=database_password,
        min_size=1,
        max_size=1,
        command_timeout=10,
        statement_cache_size=0,
    )
    if pool is None:
        raise RuntimeError("asyncpg did not create the PgBouncer test pool.")
    subject_a = UUID("00000000-0000-7000-8000-000000000101")
    subject_b = UUID("00000000-0000-7000-8000-000000000102")
    try:
        pids = {
            *await _commit_case(
                pool,
                workspace_id=args.workspace_a,
                other=args.workspace_b,
                subject_id=subject_a,
            ),
            *await _commit_case(
                pool,
                workspace_id=args.workspace_b,
                other=args.workspace_a,
                subject_id=subject_b,
            ),
            *await _rollback_case(pool, workspace_id=args.workspace_a, subject_id=subject_a),
            *await _error_case(pool, workspace_id=args.workspace_b, subject_id=subject_b),
        }
        if len(pids) != 1:
            raise RuntimeError(
                "The test did not reuse exactly one PostgreSQL server connection; "
                "the RLS leakage result is inconclusive."
            )
        await _cancel_case(pool, workspace_id=args.workspace_a, subject_id=subject_a)
    finally:
        await pool.close()
    print("PgBouncer transaction-pooling RLS gate passed.")


def main() -> None:
    asyncio.run(run_probe(parse_args()))


if __name__ == "__main__":
    main()
