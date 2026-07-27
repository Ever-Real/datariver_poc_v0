from __future__ import annotations

from pathlib import Path

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0054_add_durable_knowledge_source_jobs.py"
CANONICAL = ROOT / "backend/alembic/versions/0001_initial_schema.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"


def test_durable_knowledge_schema_is_in_metadata_and_canonical_baseline() -> None:
    assert REQUIRED_DATABASE_REVISION == "0059"
    expected_tables = {
        "knowledge.source_analysis_jobs",
        "knowledge.source_analysis_attempts",
        "knowledge.source_analysis_events",
    }
    assert expected_tables <= set(Base.metadata.tables)

    changesets = Base.metadata.tables["knowledge.changesets"]
    extraction_runs = Base.metadata.tables["knowledge.extraction_runs"]
    assert "source_analysis_job_id" in changesets.columns
    assert {
        "source_analysis_job_id",
        "source_analysis_attempt_id",
        "contract_version",
    } <= set(extraction_runs.columns.keys())

    canonical = CANONICAL.read_text(encoding="utf-8")
    for contract in (
        "source_analysis_jobs",
        "source_analysis_attempts",
        "source_analysis_events",
        "source_analysis_job_owner_select",
        "list_knowledge_worker_workspaces",
        "lock_source_analysis_finalization",
        "trg_source_analysis_job_fence",
        "trg_knowledge_source_outbox_scope",
        "DURABLE_SOURCE_V1",
        "datariver_knowledge",
    ):
        assert contract in canonical


def test_additive_migration_has_canonical_reentry_and_cycle_breaking_fks() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "if _canonical_phase5_contract_exists():" in migration
    assert "_execute_blocks(_GRANTS_SQL)" in migration
    assert "_assert_phase5_privileges()" in migration
    assert (
        migration.count("fk_source_analysis_jobs_workspace_id_graph_id_base_release_id_releases")
        >= 2
    )
    assert (
        migration.count(
            "fk_source_analysis_jobs_workspace_id_graph_id_result_changeset_id_changesets"
        )
        >= 2
    )
    assert "Downgrade would erase durable Knowledge job evidence" in migration


def test_canonical_generator_reuses_exact_phase5_security_sql() -> None:
    generator = GENERATOR.read_text(encoding="utf-8")
    assert "_load_phase5_revision" in generator
    assert '"_CLAIM_SCOPE_SQL"' in generator
    assert '"_EVIDENCE_INDEX_SQL"' in generator
    assert '"_WORKSPACE_DISCOVERY_SQL"' in generator
    assert '"_TRIGGER_SQL"' in generator
    assert '"_GRANTS_SQL"' in generator
    assert "source_analysis_job_owner_select" in generator
    assert "source_analysis_event_owner_select" in generator
    assert "_DROP_TRIGGER_SQL" in generator


def test_worker_role_is_fail_closed_and_reconciled_to_an_exact_allowlist() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    role_init = (ROOT / "infra/postgres/init/010_roles.sh").read_text(encoding="utf-8")

    for contract in (
        "rolcanlogin",
        "rolsuper",
        "rolcreatedb",
        "rolcreaterole",
        "rolreplication",
        "rolbypassrls",
        "pg_has_role('datariver_knowledge', candidate.oid, 'MEMBER')",
        "pg_has_role(candidate.oid, 'datariver_knowledge', 'MEMBER')",
        "datariver_knowledge must not be assumable by another non-superuser principal",
        "Knowledge worker writes require a direct worker session",
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA",
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA",
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA",
        "REVOKE ALL PRIVILEGES ON SCHEMA",
        "'knowledge.source_pages', 'UPDATE,DELETE'",
        "'knowledge.source_pages', 'SELECT'",
        "'knowledge.release_nodes', 'SELECT'",
        "'authz.policy_decisions', 'SELECT'",
        "'knowledge.releases', 'INSERT,UPDATE,DELETE'",
        "'knowledge', 'CREATE'",
        "NEW.consumer <> 'knowledge-source-analysis-v1'",
        "trg_knowledge_source_inbox_scope",
        "current_source_claim_scope",
        "knowledge_worker_current_manifest",
        "knowledge_worker_current_source",
        "knowledge_worker_inference_profiles",
    ):
        assert contract in migration
    assert "pg_has_role('datariver_knowledge', candidate.oid, 'MEMBER')" in role_init
    assert "pg_has_role(candidate.oid, 'datariver_knowledge', 'MEMBER')" in role_init


def test_worker_canonical_write_fences_cover_future_accidental_delete_grants() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "Knowledge canonical evidence is not worker-deletable" in migration
    for table in (
        "knowledge.source_pages",
        "knowledge.source_page_embeddings",
        "knowledge.extraction_runs",
        "knowledge.changesets",
        "knowledge.change_operations",
    ):
        assert f"BEFORE INSERT OR UPDATE OR DELETE ON {table}" in migration
    assert "BEFORE UPDATE OR DELETE ON knowledge.source_snapshots" in migration
