from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from datariver.infrastructure.db.knowledge_studio_ingestion_sql import (
    STUDIO_INGESTION_ALL_FUNCTION_SQL,
    STUDIO_INGESTION_FUNCTION_SIGNATURES,
    STUDIO_INGESTION_INTERNAL_FUNCTION_SIGNATURES,
)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0081_governed_studio_database_ingestion.py"
INITIAL_MIGRATION = ROOT / "backend/alembic/versions/0001_initial_schema.py"


def _load_ingestion_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_studio_ingestion_0081", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_studio_ingestion_function_contract_is_exact_and_fenced() -> None:
    signatures = (
        *STUDIO_INGESTION_FUNCTION_SIGNATURES,
        *STUDIO_INGESTION_INTERNAL_FUNCTION_SIGNATURES,
    )

    assert len(signatures) == len(set(signatures))
    assert all(signature.startswith("knowledge.") for signature in signatures)
    assert "p_worker_fingerprint text" in STUDIO_INGESTION_ALL_FUNCTION_SQL
    assert "job.lease_owner_fingerprint IS DISTINCT FROM p_worker_fingerprint" in (
        STUDIO_INGESTION_ALL_FUNCTION_SQL
    )
    assert "current_authorization_hash <> job.requester_authorization_hash" in (
        STUDIO_INGESTION_ALL_FUNCTION_SQL
    )
    assert "actual_vectors <> expected_vectors" in STUDIO_INGESTION_ALL_FUNCTION_SQL
    assert "FOR UPDATE SKIP LOCKED" in STUDIO_INGESTION_ALL_FUNCTION_SQL


def test_revision_0081_and_canonical_schema_share_the_least_privilege_contract() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0081"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0080"' in migration
    for document in (migration, initial):
        assert "datariver_knowledge_ingestion" in document
        assert "FORCE ROW LEVEL SECURITY" in document
        assert "request_studio_ingestion_v1" in document
        assert "complete_studio_ingestion_v1" in document
        assert "REVOKE ALL ON FUNCTION" in document
    assert "actual_vectors <> expected_vectors" in initial
    assert "0081 requires explicit reconciliation of legacy Studio ingestion jobs" in migration
    assert "append-only and requires an explicit operator-authored" in migration


def test_revision_0081_splits_asyncpg_scripts_only_at_top_level_boundaries() -> None:
    migration = _load_ingestion_migration()

    statements = migration.split_postgresql_statements(
        """
        DO $guard$
        BEGIN
            PERFORM 'embedded;semicolon';
        END
        $guard$;
        CREATE TABLE knowledge.splitter_probe (id uuid PRIMARY KEY);
        """
    )

    assert len(statements) == 2
    assert statements[0].startswith("DO $guard$")
    assert statements[1].startswith("CREATE TABLE")
    assert len(
        migration.split_postgresql_statements(migration.STUDIO_INGESTION_ALL_FUNCTION_SQL)
    ) == len(
        (
            *migration.STUDIO_INGESTION_FUNCTION_SIGNATURES,
            *migration.STUDIO_INGESTION_INTERNAL_FUNCTION_SIGNATURES,
        )
    )
