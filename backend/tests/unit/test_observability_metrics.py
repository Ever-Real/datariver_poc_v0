from __future__ import annotations

from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine

from datariver.infrastructure.db.session import Database, DatabasePoolSnapshot
from datariver.infrastructure.observability.metrics import HttpMetrics


class _Pool:
    def checkedin(self) -> int:
        return 6

    def checkedout(self) -> int:
        return 2

    def overflow(self) -> int:
        return -3


class _SyncEngine:
    pool = _Pool()


class _Engine:
    sync_engine = _SyncEngine()


def test_database_pool_snapshot_clamps_sqlalchemy_negative_overflow() -> None:
    database = Database.__new__(Database)
    database._configured_pool_size = 8
    database._configured_max_overflow = 4
    database.engine = cast(AsyncEngine, cast(Any, _Engine()))

    assert database.pool_snapshot() == DatabasePoolSnapshot(
        configured_size=8,
        configured_max_overflow=4,
        checked_in=6,
        checked_out=2,
        overflow=0,
    )


def test_database_pool_metrics_use_only_bounded_state_and_limit_labels() -> None:
    metrics = HttpMetrics()

    metrics.database_pool_observed(
        configured_size=10,
        configured_max_overflow=5,
        checked_in=7,
        checked_out=3,
        overflow=1,
    )

    rendered = metrics.render().decode()
    assert 'datariver_database_pool_limit{kind="base"} 10.0' in rendered
    assert 'datariver_database_pool_limit{kind="overflow"} 5.0' in rendered
    assert 'datariver_database_pool_connections{state="checked_in"} 7.0' in rendered
    assert 'datariver_database_pool_connections{state="checked_out"} 3.0' in rendered
    assert 'datariver_database_pool_connections{state="overflow"} 1.0' in rendered
    assert "workspace" not in rendered
    assert "database_url" not in rendered
