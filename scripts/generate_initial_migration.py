# ruff: noqa: S608 -- this script renders SQL from fixed schema constants only.

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.autogenerate import render_python_code
from alembic.operations import ops
from sqlalchemy import ForeignKeyConstraint

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.identity_provisioning_sql import (
    IDENTITY_PROVISIONING_FUNCTION_SQL,
    IDENTITY_PROVISIONING_SIGNATURE,
)
from datariver.infrastructure.db.migration_scope import MANAGED_DATABASE_SCHEMAS

SCHEMAS = MANAGED_DATABASE_SCHEMAS
RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
RUNTIME_SCHEMAS = ", ".join(SCHEMAS)
_STATEMENT_BOUNDARY = "-- datariver-statement-boundary"
_GOVERNANCE_DOCUMENT_TABLES = frozenset(
    {
        "governance.documents",
        "governance.document_versions",
        "governance.document_reviews",
        "governance.document_events",
        "governance.document_artifact_receipts",
        "governance.document_attachments",
        "governance.document_knowledge_chunks",
        "governance.document_projection_receipts",
    }
)


def _current_subject_sql() -> str:
    return "NULLIF(current_setting('app.subject_id', true), '')::uuid"


def _studio_reviewer_sql(
    draft_reference: str,
    *,
    require_publish: bool = False,
) -> str:
    """Render the DB-side lower bound for an independently authorized Studio reviewer."""
    required_actions = ["kg.review"]
    if require_publish:
        required_actions.append("kg.publish")
    action_checks = " AND ".join(
        (
            "COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb) "
            f"? '{action}' AND NOT ("
            "COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb) "
            f"? '{action}')"
        )
        for action in required_actions
    )
    return (
        "EXISTS (SELECT 1 FROM iam.workspace_memberships AS membership "
        "JOIN iam.subjects AS reviewer_subject "
        "ON reviewer_subject.id = membership.subject_id "
        "JOIN platform.workspaces AS reviewer_workspace "
        "ON reviewer_workspace.id = membership.workspace_id "
        f"WHERE membership.workspace_id = {draft_reference}.workspace_id "
        f"AND membership.subject_id = {_current_subject_sql()} "
        f"AND membership.subject_id <> {draft_reference}.author_id "
        "AND reviewer_workspace.status = 'ACTIVE' "
        "AND reviewer_subject.active IS TRUE "
        "AND membership.active IS TRUE "
        "AND (membership.access_expires_at IS NULL "
        "OR membership.access_expires_at > transaction_timestamp()) "
        "AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT' "
        "AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb) "
        "? 'service-accounts') "
        f"AND membership.clearance >= {draft_reference}.classification "
        f"AND ({draft_reference}.classification = 0 OR "
        "COALESCE(membership.attributes -> 'allowed_domain_ids', '[]'::jsonb) "
        f"? {draft_reference}.domain_ref_id::text) "
        f"AND {action_checks})"
    )


def _draft_actor_read_sql(draft_reference: str) -> str:
    return (
        f"{draft_reference}.author_id = {_current_subject_sql()} OR "
        f"({draft_reference}.state IN ('REVIEW', 'PUBLISHED') AND "
        f"{_studio_reviewer_sql(draft_reference)})"
    )


def _load_phase5_revision() -> ModuleType:
    """Load the self-contained Phase 5 SQL into the canonical baseline."""
    revision_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "0054_add_durable_knowledge_source_jobs.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datariver_canonical_phase5_revision",
        revision_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Phase 5 migration contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_phase6b_revision() -> ModuleType:
    """Load the self-contained atomic Sharing SQL into the canonical baseline."""
    revision_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "0055_atomic_sharing_invocation_results.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datariver_canonical_phase6b_revision",
        revision_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Phase 6B migration contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_quality_phase1_revision() -> ModuleType:
    """Load the self-contained Quality security contract into the canonical baseline."""
    revision_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "0067_quality_control_plane.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datariver_canonical_quality_phase1_revision",
        revision_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Quality Phase 1 migration contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_catalog_profile_phase2_revision() -> ModuleType:
    """Load the self-contained Catalog Profile security contract."""
    revision_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "0068_catalog_profile_projection.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datariver_canonical_catalog_profile_phase2_revision",
        revision_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Catalog Profile Phase 2 migration contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_quality_phase3_revision() -> ModuleType:
    """Load the self-contained Quality execution-plane function contract."""
    revision_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "0069_quality_execution_plane.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datariver_canonical_quality_phase3_revision",
        revision_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Quality Phase 3 migration contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_quality_authoring_revision() -> ModuleType:
    """Load the fixed Quality authoring and manual Run command contract."""
    revision_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "0071_quality_authoring_commands.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datariver_canonical_quality_authoring_revision",
        revision_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Quality authoring migration contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_governance_document_revision() -> ModuleType:
    """Load the fixed Governance Document RLS and transition contract."""
    revision_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "0072_governance_document_library.py"
    )
    spec = importlib.util.spec_from_file_location(
        "datariver_canonical_governance_document_revision",
        revision_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Governance Document migration contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql_statements(sql: str) -> tuple[str, ...]:
    return tuple(
        statement.strip() for statement in sql.split(_STATEMENT_BOUNDARY) if statement.strip()
    )


def build_upgrade() -> ops.UpgradeOps:
    operations: list[ops.MigrateOperation] = [
        ops.ExecuteSQLOp("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    ]
    for schema in SCHEMAS:
        operations.append(ops.ExecuteSQLOp(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    deferred_policy_operations: list[ops.MigrateOperation] = []
    for table in Base.metadata.sorted_tables:
        operations.append(ops.CreateTableOp.from_table(table))
        operations.extend(
            ops.CreateIndexOp.from_index(index)
            for index in sorted(table.indexes, key=lambda value: value.name or "")
        )
        if (
            "workspace_id" in table.columns or table.fullname == "platform.workspaces"
        ) and table.fullname not in _GOVERNANCE_DOCUMENT_TABLES:
            workspace_column = "id" if table.fullname == "platform.workspaces" else "workspace_id"
            operations.append(
                ops.ExecuteSQLOp(f"ALTER TABLE {table.fullname} ENABLE ROW LEVEL SECURITY")
            )
            operations.append(
                ops.ExecuteSQLOp(f"ALTER TABLE {table.fullname} FORCE ROW LEVEL SECURITY")
            )
            operations.append(
                ops.ExecuteSQLOp(
                    f"CREATE POLICY workspace_isolation ON {table.fullname} "
                    f"USING ({workspace_column} = {RLS_SETTING}) "
                    f"WITH CHECK ({workspace_column} = {RLS_SETTING})"
                )
            )
            policy_start = len(operations)
            if table.fullname == "catalog.export_requests":
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY catalog_export_owner_select ON catalog.export_requests "
                        "AS RESTRICTIVE FOR SELECT USING ("
                        "current_user <> 'datariver_app' OR requested_by = "
                        "NULLIF(current_setting('app.subject_id', true), '')::uuid)"
                    )
                )
            if table.fullname == "knowledge.source_analysis_jobs":
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY source_analysis_job_owner_select "
                        "ON knowledge.source_analysis_jobs "
                        "AS RESTRICTIVE FOR SELECT TO datariver_app USING ("
                        "requested_by = "
                        "NULLIF(current_setting('app.subject_id', true), '')::uuid)"
                    )
                )
            if table.fullname == "knowledge.source_analysis_events":
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY source_analysis_event_owner_select "
                        "ON knowledge.source_analysis_events "
                        "AS RESTRICTIVE FOR SELECT TO datariver_app USING ("
                        "EXISTS (SELECT 1 FROM knowledge.source_analysis_jobs AS job "
                        "WHERE job.workspace_id = source_analysis_events.workspace_id "
                        "AND job.id = source_analysis_events.job_id "
                        "AND job.requested_by = "
                        "NULLIF(current_setting('app.subject_id', true), '')::uuid))"
                    )
                )
            if table.fullname == "knowledge.studio_drafts":
                owner_expression = f"author_id = {_current_subject_sql()}"
                reviewer_expression = _studio_reviewer_sql("studio_drafts")
                publisher_expression = _studio_reviewer_sql(
                    "studio_drafts",
                    require_publish=True,
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_actor_select "
                        "ON knowledge.studio_drafts AS RESTRICTIVE FOR SELECT "
                        "TO datariver_app USING ("
                        f"{owner_expression} OR "
                        f"(state IN ('REVIEW', 'PUBLISHED') AND {reviewer_expression}))"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_author_insert "
                        "ON knowledge.studio_drafts AS RESTRICTIVE FOR INSERT "
                        f"TO datariver_app WITH CHECK ({owner_expression} AND state = 'DRAFT')"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_governed_update "
                        "ON knowledge.studio_drafts AS RESTRICTIVE FOR UPDATE "
                        "TO datariver_app USING ("
                        f"({owner_expression} AND state IN ('DRAFT', 'REVIEW')) OR "
                        f"(state = 'REVIEW' AND {publisher_expression})) "
                        "WITH CHECK ("
                        f"({owner_expression} AND state IN ('DRAFT', 'REVIEW', 'DISCARDED')) OR "
                        "(state = 'PUBLISHED' "
                        f"AND reviewed_by = {_current_subject_sql()} "
                        f"AND published_by = {_current_subject_sql()} "
                        f"AND {publisher_expression}))"
                    )
                )
            if table.fullname == "knowledge.source_references":
                owner_expression = f"created_by = {_current_subject_sql()}"
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY source_reference_actor_select "
                        "ON knowledge.source_references AS RESTRICTIVE FOR SELECT "
                        f"TO datariver_app USING ({owner_expression} OR EXISTS ("
                        "SELECT 1 FROM knowledge.abox_binding_drafts AS binding "
                        "JOIN knowledge.studio_drafts AS bound_draft "
                        "ON bound_draft.workspace_id = binding.workspace_id "
                        "AND bound_draft.id = binding.draft_id "
                        "WHERE binding.workspace_id = source_references.workspace_id "
                        "AND binding.source_reference_id = source_references.id "
                        "AND bound_draft.state IN ('REVIEW', 'PUBLISHED') "
                        f"AND {_studio_reviewer_sql('bound_draft')}))"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY source_reference_owner_insert "
                        "ON knowledge.source_references AS RESTRICTIVE FOR INSERT "
                        f"TO datariver_app WITH CHECK ({owner_expression})"
                    )
                )
            if table.fullname in {
                "knowledge.tbox_draft_elements",
                "knowledge.abox_binding_drafts",
                "knowledge.abox_mapping_rule_drafts",
            }:
                table_name = table.name
                owner_expression = (
                    "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS owned_draft "
                    f"WHERE owned_draft.workspace_id = {table_name}.workspace_id "
                    f"AND owned_draft.id = {table_name}.draft_id "
                    "AND owned_draft.author_id = "
                    f"{_current_subject_sql()} AND owned_draft.state = 'DRAFT')"
                )
                actor_read_expression = (
                    "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS visible_draft "
                    f"WHERE visible_draft.workspace_id = {table_name}.workspace_id "
                    f"AND visible_draft.id = {table_name}.draft_id "
                    f"AND ({_draft_actor_read_sql('visible_draft')}))"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_actor_select "
                        f"ON {table.fullname} AS RESTRICTIVE FOR SELECT "
                        f"TO datariver_app USING ({actor_read_expression})"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_owner_insert "
                        f"ON {table.fullname} AS RESTRICTIVE FOR INSERT "
                        f"TO datariver_app WITH CHECK ({owner_expression})"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_owner_update "
                        f"ON {table.fullname} AS RESTRICTIVE FOR UPDATE "
                        f"TO datariver_app USING ({owner_expression}) "
                        f"WITH CHECK ({owner_expression})"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_owner_delete "
                        f"ON {table.fullname} AS RESTRICTIVE FOR DELETE "
                        f"TO datariver_app USING ({owner_expression})"
                    )
                )
            if table.fullname == "knowledge.studio_preflight_checks":
                visible_parent = (
                    "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS visible_draft "
                    "WHERE visible_draft.workspace_id = studio_preflight_checks.workspace_id "
                    "AND visible_draft.id = studio_preflight_checks.draft_id "
                    f"AND ({_draft_actor_read_sql('visible_draft')}))"
                )
                insert_parent = (
                    "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS target_draft "
                    "WHERE target_draft.workspace_id = studio_preflight_checks.workspace_id "
                    "AND target_draft.id = studio_preflight_checks.draft_id "
                    "AND ((target_draft.state = 'DRAFT' "
                    f"AND target_draft.author_id = {_current_subject_sql()}) OR "
                    "(target_draft.state = 'REVIEW' "
                    f"AND {_studio_reviewer_sql('target_draft')})))"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_preflight_actor_select "
                        "ON knowledge.studio_preflight_checks AS RESTRICTIVE FOR SELECT "
                        f"TO datariver_app USING ({visible_parent})"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_preflight_actor_insert "
                        "ON knowledge.studio_preflight_checks AS RESTRICTIVE FOR INSERT "
                        f"TO datariver_app WITH CHECK (checked_by = {_current_subject_sql()} "
                        f"AND {insert_parent})"
                    )
                )
            if table.fullname == "knowledge.studio_releases":
                insert_parent = (
                    "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS source_draft "
                    "WHERE source_draft.workspace_id = studio_releases.workspace_id "
                    "AND source_draft.id = studio_releases.source_draft_id "
                    "AND source_draft.state = 'REVIEW' "
                    f"AND {_studio_reviewer_sql('source_draft', require_publish=True)})"
                )
                archive_parent = (
                    "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS source_draft "
                    "WHERE source_draft.workspace_id = studio_releases.workspace_id "
                    "AND source_draft.id = studio_releases.source_draft_id "
                    "AND source_draft.state = 'PUBLISHED' "
                    f"AND {_studio_reviewer_sql('source_draft', require_publish=True)})"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_release_publisher_insert "
                        "ON knowledge.studio_releases AS RESTRICTIVE FOR INSERT "
                        f"TO datariver_app WITH CHECK (reviewed_by = {_current_subject_sql()} "
                        f"AND published_by = {_current_subject_sql()} AND {insert_parent})"
                    )
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_release_publisher_archive "
                        "ON knowledge.studio_releases AS RESTRICTIVE FOR UPDATE "
                        f"TO datariver_app USING (state = 'ACTIVE' AND {archive_parent}) "
                        "WITH CHECK (state = 'ARCHIVED' "
                        f"AND archived_by = {_current_subject_sql()} AND {archive_parent})"
                    )
                )
            if table.fullname == "assistant.chat_sessions":
                owner_expression = (
                    "owner_id = NULLIF(current_setting('app.subject_id', true), '')::uuid"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY chat_session_owner_access "
                        "ON assistant.chat_sessions AS RESTRICTIVE FOR ALL "
                        f"TO datariver_app USING ({owner_expression}) "
                        f"WITH CHECK ({owner_expression})"
                    )
                )
            if table.fullname == "assistant.chat_messages":
                owner_expression = (
                    "EXISTS (SELECT 1 FROM assistant.chat_sessions AS owned_session "
                    "WHERE owned_session.workspace_id = chat_messages.workspace_id "
                    "AND owned_session.id = chat_messages.session_id "
                    "AND owned_session.owner_id = "
                    "NULLIF(current_setting('app.subject_id', true), '')::uuid)"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY chat_message_owner_access "
                        "ON assistant.chat_messages AS RESTRICTIVE FOR ALL "
                        f"TO datariver_app USING ({owner_expression}) "
                        f"WITH CHECK ({owner_expression})"
                    )
                )
            if table.fullname == "assistant.assistant_runs":
                owner_expression = (
                    "EXISTS (SELECT 1 FROM assistant.chat_sessions AS owned_session "
                    "WHERE owned_session.workspace_id = assistant_runs.workspace_id "
                    "AND owned_session.id = assistant_runs.session_id "
                    "AND owned_session.owner_id = "
                    "NULLIF(current_setting('app.subject_id', true), '')::uuid)"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY assistant_run_owner_access "
                        "ON assistant.assistant_runs AS RESTRICTIVE FOR ALL "
                        f"TO datariver_app USING ({owner_expression}) "
                        f"WITH CHECK ({owner_expression})"
                    )
                )
            if table.fullname == "assistant.evidence_citations":
                owner_expression = (
                    "EXISTS (SELECT 1 FROM assistant.assistant_runs AS owned_run "
                    "JOIN assistant.chat_sessions AS owned_session "
                    "ON owned_session.workspace_id = owned_run.workspace_id "
                    "AND owned_session.id = owned_run.session_id "
                    "WHERE owned_run.workspace_id = evidence_citations.workspace_id "
                    "AND owned_run.id = evidence_citations.run_id "
                    "AND owned_session.owner_id = "
                    "NULLIF(current_setting('app.subject_id', true), '')::uuid)"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY evidence_citation_owner_access "
                        "ON assistant.evidence_citations AS RESTRICTIVE FOR ALL "
                        f"TO datariver_app USING ({owner_expression}) "
                        f"WITH CHECK ({owner_expression})"
                    )
                )
            deferred_policy_operations.extend(operations[policy_start:])
            del operations[policy_start:]
    operations.extend(deferred_policy_operations)
    operations.extend(
        ops.ExecuteSQLOp(statement) for statement in _manifest_content_profile_immutability_sql()
    )
    operations.extend(
        ops.ExecuteSQLOp(statement) for statement in _candidate_evidence_immutability_sql()
    )
    operations.extend(ops.ExecuteSQLOp(statement) for statement in _chat_retention_binding_sql())
    operations.append(ops.ExecuteSQLOp(IDENTITY_PROVISIONING_FUNCTION_SQL))
    operations.append(
        ops.ExecuteSQLOp(f"REVOKE ALL ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE} FROM PUBLIC")
    )
    operations.extend(ops.ExecuteSQLOp(statement) for statement in _default_workspace_lookup_sql())
    operations.extend(
        ops.CreateForeignKeyOp.from_constraint(constraint)
        for constraint in _deferred_foreign_keys()
    )
    operations.append(ops.ExecuteSQLOp(_runtime_grants_sql()))
    phase5 = _load_phase5_revision()
    # Workspace RLS is generated generically above. Retain the exact principal
    # assertion, then install the worker-only discovery/locking functions,
    # database fences and least-privilege grants from the additive revision.
    role_assertion = _sql_statements(phase5._RLS_SQL)[0]
    operations.append(ops.ExecuteSQLOp(role_assertion))
    for attribute in (
        "_CLAIM_SCOPE_SQL",
        "_EVIDENCE_INDEX_SQL",
        "_WORKSPACE_DISCOVERY_SQL",
        "_TRIGGER_SQL",
        "_GRANTS_SQL",
    ):
        operations.extend(
            ops.ExecuteSQLOp(statement) for statement in _sql_statements(getattr(phase5, attribute))
        )
    phase6b = _load_phase6b_revision()
    for attribute in (
        "_FUNCTION_SQL",
        "_TRIGGER_FUNCTION_SQL",
        "_TRIGGER_SQL",
        "_GRANT_SQL",
    ):
        operations.extend(
            ops.ExecuteSQLOp(statement)
            for statement in _sql_statements(getattr(phase6b, attribute))
        )
    quality_phase1 = _load_quality_phase1_revision()
    operations.append(ops.ExecuteSQLOp(quality_phase1._QUALITY_ROLE_ASSERTION_SQL.strip()))
    for attribute in (
        "_HOLD_GENERATION_SQL",
        "_RESOLVER_SQL",
        "_QUALITY_SECURITY_SQL",
        "_IMMUTABILITY_SQL",
        "_RUN_ATTEMPT_INVARIANT_SQL",
        "_RUN_RESULT_INVARIANT_SQL",
        "_TRANSITION_SQL",
    ):
        operations.extend(
            ops.ExecuteSQLOp(statement)
            for statement in _sql_statements(getattr(quality_phase1, attribute))
        )
    for table_name in quality_phase1._IMMUTABLE_TABLES:
        operations.append(
            ops.ExecuteSQLOp(
                f"CREATE TRIGGER reject_evidence_mutation "
                f"BEFORE UPDATE OR DELETE ON quality.{table_name} "
                "FOR EACH ROW EXECUTE FUNCTION quality.reject_evidence_mutation()"
            )
        )
    for statement in _sql_statements(quality_phase1._RLS_AND_GRANTS_SQL):
        normalized = statement.lstrip()
        if (
            normalized.startswith("DO $$\nDECLARE\n    table_name text;")
            or normalized.startswith(
                "ALTER TABLE retention.legal_hold_generations ENABLE ROW LEVEL SECURITY"
            )
            or normalized.startswith(
                "ALTER TABLE retention.legal_hold_generations FORCE ROW LEVEL SECURITY"
            )
            or normalized.startswith(
                "CREATE POLICY workspace_isolation ON retention.legal_hold_generations"
            )
        ):
            continue
        operations.append(ops.ExecuteSQLOp(statement))
    catalog_profile_phase2 = _load_catalog_profile_phase2_revision()
    operations.append(ops.ExecuteSQLOp(catalog_profile_phase2._PROFILE_ROLE_ASSERTION_SQL.strip()))
    operations.extend(
        ops.ExecuteSQLOp(statement)
        for statement in _sql_statements(catalog_profile_phase2._RESOLVER_V4_SQL)
    )
    operations.extend(
        ops.ExecuteSQLOp(statement)
        for statement in _sql_statements(catalog_profile_phase2._PROFILE_FUNCTION_SQL)
    )
    for statement in _sql_statements(catalog_profile_phase2._PROFILE_RLS_AND_GRANTS_SQL):
        normalized = statement.lstrip()
        if (
            normalized.startswith(
                "ALTER TABLE catalog.asset_profile_snapshots ENABLE ROW LEVEL SECURITY"
            )
            or normalized.startswith(
                "ALTER TABLE catalog.asset_profile_snapshots FORCE ROW LEVEL SECURITY"
            )
            or normalized.startswith(
                "CREATE POLICY workspace_isolation ON catalog.asset_profile_snapshots"
            )
            or normalized.startswith(
                "ALTER TABLE catalog.column_profile_metrics ENABLE ROW LEVEL SECURITY"
            )
            or normalized.startswith(
                "ALTER TABLE catalog.column_profile_metrics FORCE ROW LEVEL SECURITY"
            )
            or normalized.startswith(
                "CREATE POLICY workspace_isolation ON catalog.column_profile_metrics"
            )
        ):
            continue
        operations.append(ops.ExecuteSQLOp(statement))
    quality_phase3 = _load_quality_phase3_revision()
    operations.extend(
        ops.ExecuteSQLOp(statement) for statement in _sql_statements(quality_phase3._FUNCTION_SQL)
    )
    operations.append(ops.ExecuteSQLOp(quality_phase3._GRANT_SQL.strip()))
    quality_authoring = _load_quality_authoring_revision()
    operations.extend(
        ops.ExecuteSQLOp(statement) for statement in _sql_statements(quality_authoring._COMMAND_SQL)
    )
    governance_documents = _load_governance_document_revision()
    operations.append(ops.ExecuteSQLOp(governance_documents._ROLE_ASSERTION_SQL.strip()))
    operations.extend(
        ops.ExecuteSQLOp(statement)
        for statement in _sql_statements(governance_documents._SECURITY_SQL)
    )
    return ops.UpgradeOps(ops=operations)


def _runtime_grants_sql() -> str:
    return f"""
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT USAGE ON SCHEMA {RUNTIME_SCHEMAS} TO datariver_app;
        GRANT USAGE ON SCHEMA public TO datariver_app;
        GRANT SELECT ON public.alembic_version TO datariver_app;
        GRANT SELECT ON platform.workspaces, iam.subjects TO datariver_app;
        GRANT UPDATE (email, last_login_at, last_login_ip, updated_at)
            ON iam.subjects TO datariver_app;
        GRANT SELECT ON iam.workspace_memberships TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON iam.membership_renewal_requests TO datariver_app;
        GRANT SELECT, INSERT ON iam.access_roles TO datariver_app;
        GRANT UPDATE (name, description, clearance, groups, allowed_actions, denied_actions,
            allowed_system_ids, allowed_domain_ids, active, updated_by, version, updated_at)
            ON iam.access_roles TO datariver_app;
        GRANT SELECT, INSERT ON iam.access_role_data_rules,
            iam.access_role_assignment_events TO datariver_app;
        GRANT SELECT, INSERT ON iam.access_role_assignments TO datariver_app;
        GRANT UPDATE (role_id, role_version, membership_version, access_payload_hash,
            assigned_by, active, version, updated_at)
            ON iam.access_role_assignments TO datariver_app;
        GRANT EXECUTE ON FUNCTION iam.resolve_default_workspace(text, text) TO datariver_app;
        GRANT EXECUTE ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE} TO datariver_app;
        GRANT UPDATE (active, clearance, attributes, version, updated_at)
            ON iam.workspace_memberships TO datariver_app;
        GRANT UPDATE (access_expires_at, version, updated_at)
            ON iam.workspace_memberships TO datariver_app;
        GRANT SELECT, INSERT ON iam.admin_access_requests TO datariver_app;
        GRANT UPDATE (state, checker_id, consumed_by, consumed_at,
            consume_policy_decision_id, version, updated_at)
            ON iam.admin_access_requests TO datariver_app;
        GRANT SELECT, INSERT ON iam.admin_access_approvals TO datariver_app;
        GRANT INSERT ON authz.policy_decisions TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON catalog.assets_projection,
            catalog.sync_runs, catalog.projection_watermarks TO datariver_app;
        GRANT SELECT ON catalog.asset_profile_snapshots,
            catalog.column_profile_metrics TO datariver_app;
        GRANT SELECT, INSERT ON catalog.export_requests TO datariver_app;
        GRANT SELECT, INSERT ON quality.common_rule_templates,
            quality.common_rule_template_mappings TO datariver_app;
        GRANT SELECT, INSERT ON governance.change_request_items,
            governance.approvals, governance.state_transitions TO datariver_app;
        GRANT SELECT, INSERT ON governance.change_request_attachments TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON governance.change_request_rounds TO datariver_app;
        GRANT SELECT, INSERT ON governance.change_test_runs TO datariver_app;
        GRANT SELECT, INSERT ON governance.registration_content_bindings TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON governance.change_requests TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON platform.data_systems, platform.system_schema_scopes,
            platform.system_assignees, platform.external_service_profiles TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON platform.external_service_profile_versions
            TO datariver_app;
        GRANT SELECT ON integration.jobs, integration.job_attempts TO datariver_app;
        GRANT INSERT ON integration.jobs TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON integration.object_manifests TO datariver_app;
        GRANT SELECT, INSERT ON integration.upload_preparation_jobs TO datariver_app;
        GRANT UPDATE (state, lease_token, lease_until, attempts, rows_processed,
            total_rows, last_error_code, version, updated_at)
            ON integration.upload_preparation_jobs TO datariver_app;
        GRANT SELECT ON integration.upload_preparation_receipts,
            integration.upload_registration_candidates TO datariver_app;
        GRANT INSERT ON integration.upload_preparation_receipts,
            integration.upload_registration_candidates TO datariver_app;
        GRANT SELECT, INSERT ON integration.idempotency_keys,
            integration.outbox_events TO datariver_app;
        GRANT SELECT ON knowledge.graphs, knowledge.ontology_versions,
            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,
            knowledge.changesets, knowledge.change_operations,
            knowledge.validation_results, knowledge.projection_deployments,
            knowledge.source_snapshots, knowledge.source_pages,
            knowledge.source_page_embeddings, knowledge.extraction_runs,
            knowledge.graphrag_audits, knowledge.studio_drafts,
            knowledge.tbox_draft_elements, knowledge.source_references,
            knowledge.abox_binding_drafts,
            knowledge.abox_mapping_rule_drafts,
            knowledge.studio_preflight_checks, knowledge.studio_releases,
            knowledge.ontology_elements, knowledge.abox_binding_versions,
            knowledge.abox_mapping_rule_versions TO datariver_app;
        GRANT INSERT ON knowledge.graphs, knowledge.ontology_versions,
            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,
            knowledge.changesets, knowledge.change_operations,
            knowledge.validation_results, knowledge.projection_deployments,
            knowledge.source_snapshots, knowledge.source_pages,
            knowledge.source_page_embeddings, knowledge.extraction_runs,
            knowledge.graphrag_audits, knowledge.studio_drafts,
            knowledge.studio_preflight_checks, knowledge.studio_releases,
            knowledge.ontology_elements, knowledge.abox_binding_versions,
            knowledge.abox_mapping_rule_versions TO datariver_app;
        GRANT UPDATE ON knowledge.graphs, knowledge.changesets,
            knowledge.projection_deployments, knowledge.source_snapshots TO datariver_app;
        GRANT UPDATE (
            state, current_step, name, endpoint_alias, endpoint_aliases,
            domain_ref_id, domain_ref_kind, domain_source_version,
            classification, review_requested_at, submitted_preflight_check_id,
            reviewed_by, reviewed_at, review_reason,
            published_by, published_at,
            materialized_graph_id, materialized_ontology_version_id,
            published_studio_release_id, discarded_at,
            discarded_by, last_autosaved_at,
            version, updated_at
        ) ON knowledge.studio_drafts TO datariver_app;
        GRANT UPDATE (state, archived_at, archived_by)
            ON knowledge.studio_releases TO datariver_app;
        GRANT INSERT ON knowledge.source_references,
            knowledge.abox_binding_drafts,
            knowledge.abox_mapping_rule_drafts TO datariver_app;
        GRANT UPDATE (
            source_reference_id, readiness, tbox_version, updated_by,
            version, updated_at
        ) ON knowledge.abox_binding_drafts TO datariver_app;
        GRANT DELETE ON knowledge.abox_mapping_rule_drafts TO datariver_app;
        GRANT DELETE ON knowledge.validation_results TO datariver_app;
        GRANT SELECT, INSERT ON assistant.chat_sessions, assistant.chat_messages,
            assistant.assistant_runs, assistant.evidence_citations TO datariver_app;
        GRANT UPDATE (is_favorite, is_archived, version, updated_at)
            ON assistant.chat_sessions TO datariver_app;
        GRANT SELECT, INSERT ON retention.policy_versions,
            retention.policy_class_rules TO datariver_app;
        GRANT UPDATE (state, checker_id, decision_reason,
            decision_policy_decision_id, decided_at, superseded_by, supersede_reason,
            supersede_policy_decision_id, superseded_at, version, updated_at)
            ON retention.policy_versions TO datariver_app;
        GRANT SELECT, INSERT ON retention.legal_holds TO datariver_app;
        GRANT UPDATE (state, release_requested_by, release_request_reason,
            release_request_policy_decision_id, release_checker_id,
            release_decision_reason, release_decision_policy_decision_id,
            released_at, version, updated_at)
            ON retention.legal_holds TO datariver_app;
        GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;
        GRANT SELECT, INSERT ON retention.erasure_requests TO datariver_app;
        GRANT UPDATE (state, checker_id, decision_reason,
            decision_policy_decision_id, decided_at, version, updated_at)
            ON retention.erasure_requests TO datariver_app;
        GRANT SELECT, INSERT ON retention.erasure_request_events TO datariver_app;
        GRANT SELECT ON retention.archive_capability_attestations,
            retention.immutable_archive_receipts TO datariver_app;
        GRANT SELECT ON retention.execution_jobs TO datariver_app;
        GRANT SELECT ON retention.execution_attempts,
            retention.execution_events TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON sharing.api_products,
            sharing.api_product_versions, sharing.consumer_grants TO datariver_app;
        GRANT SELECT, INSERT ON sharing.api_invocations TO datariver_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') THEN
        GRANT USAGE ON SCHEMA platform, integration TO datariver_relay;
        GRANT SELECT ON platform.external_service_profiles,
            platform.external_service_profile_versions TO datariver_relay;
        GRANT SELECT, UPDATE ON integration.outbox_events TO datariver_relay;
        GRANT SELECT ON integration.inbox_messages TO datariver_relay;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_upload') THEN
        GRANT USAGE ON SCHEMA platform, integration TO datariver_upload;
        GRANT SELECT ON platform.external_service_profiles,
            platform.external_service_profile_versions TO datariver_upload;
        GRANT SELECT, UPDATE ON integration.object_manifests TO datariver_upload;
        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_upload;
        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_upload;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN
        GRANT USAGE ON SCHEMA platform, iam, authz, governance, integration
            TO datariver_governance;
        GRANT SELECT ON platform.external_service_profiles,
            platform.external_service_profile_versions TO datariver_governance;
        GRANT SELECT, INSERT ON authz.policy_decisions TO datariver_governance;
        GRANT SELECT ON governance.change_requests TO datariver_governance;
        GRANT UPDATE (state, version, updated_at)
            ON governance.change_requests TO datariver_governance;
        GRANT SELECT ON governance.change_request_items, governance.approvals,
            governance.state_transitions, governance.change_request_rounds,
            governance.change_test_runs TO datariver_governance;
        GRANT INSERT ON governance.state_transitions TO datariver_governance;
        GRANT SELECT, INSERT ON integration.jobs, integration.job_attempts
            TO datariver_governance;
        GRANT UPDATE (state, progress, result_ref, lease_until, attempts,
            attempt_cycle, cycle_attempts, lease_token_hash, lease_owner_id,
            last_error_code, version, updated_at)
            ON integration.jobs TO datariver_governance;
        GRANT UPDATE (state, error_class, external_response_hash, finished_at)
            ON integration.job_attempts TO datariver_governance;
        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages
            TO datariver_governance;
        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_governance;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_export') THEN
        GRANT USAGE ON SCHEMA platform, iam, authz, catalog, integration TO datariver_export;
        GRANT SELECT ON platform.workspaces, iam.subjects,
            iam.workspace_memberships TO datariver_export;
        GRANT SELECT ON platform.external_service_profiles,
            platform.external_service_profile_versions TO datariver_export;
        GRANT SELECT ON authz.classification_access_policy_versions,
            authz.classification_access_policy_rules, authz.classification_access_generations,
            authz.restricted_search_grants TO datariver_export;
        GRANT INSERT ON authz.policy_decisions TO datariver_export;
        GRANT SELECT ON catalog.assets_projection, catalog.projection_watermarks,
            catalog.export_requests TO datariver_export;
        GRANT UPDATE (object_bucket, object_key, row_count, size_bytes, content_sha256,
            provider_checksum, completed_at, version, updated_at)
            ON catalog.export_requests TO datariver_export;
        GRANT SELECT ON integration.inference_provider_profile_versions,
            integration.jobs, integration.job_attempts TO datariver_export;
        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_export;
        GRANT UPDATE (state, progress, result_ref, lease_until, attempts, last_error_code,
            version, updated_at) ON integration.jobs TO datariver_export;
        GRANT INSERT, UPDATE (state, error_class, external_response_hash, finished_at)
            ON integration.job_attempts TO datariver_export;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'datariver_retention_scheduler'
    ) THEN
        GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention
            TO datariver_retention_scheduler;
        GRANT SELECT ON platform.workspaces, iam.subjects,
            iam.workspace_memberships, iam.access_roles,
            iam.access_role_assignments, authz.policy_decisions,
            retention.policy_versions, retention.policy_class_rules,
            retention.legal_holds, retention.erasure_requests,
            retention.erasure_request_events,
            assistant.chat_sessions TO datariver_retention_scheduler;
        GRANT SELECT, INSERT ON retention.execution_jobs,
            retention.execution_events TO datariver_retention_scheduler;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_archive') THEN
        GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention
            TO datariver_archive;
        GRANT SELECT ON platform.workspaces, iam.subjects,
            iam.workspace_memberships, iam.access_roles,
            iam.access_role_assignments, authz.policy_decisions,
            retention.policy_versions, retention.policy_class_rules,
            retention.legal_holds, retention.erasure_requests,
            retention.erasure_request_events,
            assistant.chat_sessions, retention.execution_jobs,
            retention.execution_attempts,
            retention.archive_capability_attestations,
            retention.immutable_archive_receipts TO datariver_archive;
        GRANT INSERT ON retention.archive_capability_attestations,
            retention.immutable_archive_receipts,
            retention.execution_attempts TO datariver_archive;
        GRANT SELECT, INSERT ON retention.execution_events TO datariver_archive;
        GRANT UPDATE (state, next_attempt_at, attempt_count, lease_epoch,
            lease_token_hash, lease_owner_fingerprint, lease_until,
            archive_receipt_id, archive_manifest_hash, last_failure_code,
            version, updated_at) ON retention.execution_jobs TO datariver_archive;
        GRANT UPDATE (state, stage, evidence_hash, external_response_hash,
            failure_code, finished_at) ON retention.execution_attempts TO datariver_archive;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_bootstrap') THEN
        GRANT USAGE ON SCHEMA platform, iam TO datariver_bootstrap;
        GRANT SELECT, INSERT, UPDATE ON platform.workspaces, iam.subjects,
            iam.workspace_memberships TO datariver_bootstrap;
    END IF;
END
$datariver$
""".strip()


def _manifest_content_profile_immutability_sql() -> tuple[str, ...]:
    function = """
CREATE FUNCTION integration.reject_object_manifest_content_profile_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    IF NEW.content_profile IS DISTINCT FROM OLD.content_profile THEN
        RAISE EXCEPTION 'object manifest content_profile is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()
    trigger = """
CREATE TRIGGER reject_object_manifest_content_profile_change
BEFORE UPDATE OF content_profile ON integration.object_manifests
FOR EACH ROW
EXECUTE FUNCTION integration.reject_object_manifest_content_profile_change()
""".strip()
    return function, trigger


def _candidate_evidence_immutability_sql() -> tuple[str, ...]:
    function = """
CREATE FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.evidence_version <> 'DATASET_DESCRIPTION_CANDIDATE_V2' THEN
        RAISE EXCEPTION 'new upload registration candidates require V2 evidence'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'upload registration candidate evidence is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()
    trigger = """
CREATE TRIGGER reject_upload_registration_candidate_evidence_mutation
BEFORE INSERT OR UPDATE OR DELETE ON integration.upload_registration_candidates
FOR EACH ROW
EXECUTE FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()
""".strip()
    return function, trigger


def _chat_retention_binding_sql() -> tuple[str, ...]:
    session_function = """
CREATE FUNCTION assistant.enforce_chat_session_retention_binding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
DECLARE
    policy_days integer;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
           OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.retention_until IS DISTINCT FROM OLD.retention_until
           OR NEW.retention_policy_id IS DISTINCT FROM OLD.retention_policy_id
           OR NEW.retention_policy_hash IS DISTINCT FROM OLD.retention_policy_hash
           OR NEW.retention_basis_at IS DISTINCT FROM OLD.retention_basis_at
           OR NEW.retention_binding_version IS DISTINCT FROM OLD.retention_binding_version THEN
            RAISE EXCEPTION 'Chat session retention evidence is immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.retention_binding_version <> 'ACTIVE_POLICY_V1' THEN
        RAISE EXCEPTION 'new Chat sessions require an active-policy retention binding'
            USING ERRCODE = '23514';
    END IF;

    SELECT policy.chat_content_days
    INTO policy_days
    FROM retention.policy_versions AS policy
    WHERE policy.workspace_id = NEW.workspace_id
      AND policy.id = NEW.retention_policy_id
      AND policy.payload_hash = NEW.retention_policy_hash
      AND policy.state = 'ACTIVE'
    FOR KEY SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Chat retention policy binding is not active'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.retention_basis_at IS DISTINCT FROM transaction_timestamp() THEN
        RAISE EXCEPTION 'Chat retention basis must equal the persistence transaction time'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.retention_until IS DISTINCT FROM
       NEW.retention_basis_at + make_interval(days => policy_days) THEN
        RAISE EXCEPTION 'Chat retention deadline does not match the active policy'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()
    session_trigger = """
CREATE TRIGGER enforce_chat_session_retention_binding
BEFORE INSERT OR UPDATE ON assistant.chat_sessions
FOR EACH ROW
EXECUTE FUNCTION assistant.enforce_chat_session_retention_binding()
""".strip()
    message_function = """
CREATE FUNCTION assistant.enforce_chat_message_retention_binding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    PERFORM 1
    FROM assistant.chat_sessions AS session
    JOIN retention.policy_versions AS policy
      ON policy.workspace_id = session.workspace_id
     AND policy.id = session.retention_policy_id
     AND policy.payload_hash = session.retention_policy_hash
    WHERE session.workspace_id = NEW.workspace_id
      AND session.id = NEW.session_id
      AND session.owner_id =
          NULLIF(current_setting('app.subject_id', true), '')::uuid
      AND session.retention_binding_version = 'ACTIVE_POLICY_V1'
      AND session.retention_until > transaction_timestamp()
      AND policy.state = 'ACTIVE'
    FOR KEY SHARE OF session, policy;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Chat session is not appendable under the active retention policy'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()
    message_trigger = """
CREATE TRIGGER enforce_chat_message_retention_binding
BEFORE INSERT ON assistant.chat_messages
FOR EACH ROW
EXECUTE FUNCTION assistant.enforce_chat_message_retention_binding()
""".strip()
    return session_function, session_trigger, message_function, message_trigger


def build_downgrade() -> ops.DowngradeOps:
    phase5 = _load_phase5_revision()
    quality_phase1 = _load_quality_phase1_revision()
    operations: list[ops.MigrateOperation] = [
        ops.ExecuteSQLOp(
            "DROP FUNCTION governance.can_read_document_v1(uuid), "
            "governance.can_act_on_document_v1(uuid,text,text), "
            "governance.current_human_can_document_v1(uuid,text,integer,uuid,uuid), "
            "governance.enforce_document_mutation_v1(), "
            "governance.enforce_document_version_mutation_v1(), "
            "governance.reject_document_evidence_mutation_v1() CASCADE"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.request_manual_validation_run_v1(uuid, uuid, uuid)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.activate_rule_set_version_command_v2("
            "uuid, uuid, uuid, text, integer)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.review_rule_set_version_command_v2("
            "uuid, uuid, text, text, uuid, integer)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.fail_validation_run_v1("
            "uuid, uuid, uuid, bigint, text, text, text, boolean)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.complete_validation_run_v1("
            "uuid, uuid, uuid, bigint, text, text, text, text, text, jsonb)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.assert_source_statement_fence_v1(uuid, uuid, uuid, bigint, text)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.freeze_source_access_v1("
            "uuid, uuid, uuid, bigint, text, integer, integer, integer, integer)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.claim_validation_run_v1(uuid, text, text, integer)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.dispatch_due_validation_runs_v1(uuid, text, integer, integer)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.current_quality_target_matches_v1("
            "uuid, uuid, integer, uuid, uuid, text, text)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.current_quality_service_can_v1(uuid, text, integer, uuid, uuid)"
        ),
        ops.ExecuteSQLOp("DROP FUNCTION catalog.project_asset_profile_v1(uuid, uuid, jsonb)"),
        ops.ExecuteSQLOp("DROP FUNCTION catalog.read_profile_target_v1(uuid, uuid)"),
        ops.ExecuteSQLOp(
            "DROP FUNCTION catalog.current_profile_collector_can_v1(uuid, integer, uuid, uuid)"
        ),
        ops.ExecuteSQLOp("DROP TRIGGER enforce_run_results_shape ON quality.expectation_results"),
        ops.ExecuteSQLOp("DROP TRIGGER enforce_run_results_shape ON quality.validation_runs"),
        ops.ExecuteSQLOp("DROP TRIGGER enforce_run_attempt_shape ON quality.validation_attempts"),
        ops.ExecuteSQLOp("DROP TRIGGER enforce_run_attempt_shape ON quality.validation_runs"),
        *(
            ops.ExecuteSQLOp(f"DROP TRIGGER reject_evidence_mutation ON quality.{table_name}")
            for table_name in quality_phase1._IMMUTABLE_TABLES
        ),
        ops.ExecuteSQLOp("DROP TRIGGER enforce_rule_set_binding ON quality.rule_sets"),
        ops.ExecuteSQLOp("DROP TRIGGER refresh_legal_hold_generation ON retention.legal_holds"),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.archive_rule_set_v1("
            "uuid, uuid, uuid, text, text, text, integer, "
            "uuid, integer, text, timestamptz, bigint, text)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.revoke_rule_set_version_v1("
            "uuid, uuid, uuid, text, text, text, text, integer, "
            "uuid, integer, text, timestamptz, bigint, text)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.activate_rule_set_version_v1("
            "uuid, uuid, uuid, text, text, text, text, text, integer, "
            "uuid, integer, text, timestamptz, bigint, text)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.review_rule_set_version_v1("
            "uuid, uuid, text, text, uuid, text, integer, "
            "uuid, integer, text, timestamptz, bigint, text)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.require_human_decision_v1(uuid, uuid, uuid, text, uuid, boolean)"
        ),
        ops.ExecuteSQLOp("DROP FUNCTION quality.reject_evidence_mutation()"),
        ops.ExecuteSQLOp("DROP FUNCTION quality.assert_run_results_shape_v1()"),
        ops.ExecuteSQLOp("DROP FUNCTION quality.assert_run_attempt_shape_v1()"),
        ops.ExecuteSQLOp("DROP FUNCTION quality.enforce_rule_set_binding_v1()"),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.current_target_matches_v1("
            "uuid, uuid, integer, uuid, uuid, text, text, text)"
        ),
        ops.ExecuteSQLOp("DROP FUNCTION quality.can_read_asset(uuid, uuid, integer, uuid, uuid)"),
        ops.ExecuteSQLOp(
            "DROP FUNCTION quality.current_human_can(uuid, text, integer, uuid, uuid)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION retention.resolve_quality_binding_v1("
            "uuid, text, text, uuid, timestamptz)"
        ),
        ops.ExecuteSQLOp("DROP FUNCTION retention.refresh_legal_hold_generation()"),
        ops.ExecuteSQLOp(
            "DROP FUNCTION retention.advance_legal_hold_generation("
            "uuid, text, text, uuid, integer, text, text, text, uuid, text)"
        ),
        ops.ExecuteSQLOp("DROP TRIGGER api_invocation_exact_result ON sharing.api_invocations"),
        ops.ExecuteSQLOp(
            "DROP TRIGGER api_invocation_results_immutable ON sharing.api_invocation_results"
        ),
        ops.ExecuteSQLOp("DROP TRIGGER api_invocations_immutable ON sharing.api_invocations"),
        ops.ExecuteSQLOp("DROP FUNCTION sharing.require_atomic_invocation_result()"),
        ops.ExecuteSQLOp("DROP FUNCTION sharing.reject_invocation_evidence_mutation()"),
        ops.ExecuteSQLOp(
            "DROP FUNCTION sharing.complete_api_invocation_v2("
            "uuid, uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid, "
            "text, text, text, text, integer, text, text, text, text, text, uuid, text)"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION sharing.prepare_api_invocation_v2("
            "uuid, uuid, uuid, text, text, text, text, uuid, uuid, uuid, uuid, text, "
            "text, text, integer, text, text, text)"
        ),
        *(ops.ExecuteSQLOp(statement) for statement in _sql_statements(phase5._DROP_TRIGGER_SQL)),
        ops.ExecuteSQLOp(f"DROP FUNCTION {IDENTITY_PROVISIONING_SIGNATURE}"),
        ops.ExecuteSQLOp("DROP FUNCTION iam.resolve_default_workspace(text, text)"),
        ops.ExecuteSQLOp(
            "DROP TRIGGER enforce_chat_message_retention_binding ON assistant.chat_messages"
        ),
        ops.ExecuteSQLOp("DROP FUNCTION assistant.enforce_chat_message_retention_binding()"),
        ops.ExecuteSQLOp(
            "DROP TRIGGER enforce_chat_session_retention_binding ON assistant.chat_sessions"
        ),
        ops.ExecuteSQLOp("DROP FUNCTION assistant.enforce_chat_session_retention_binding()"),
        ops.ExecuteSQLOp(
            "DROP TRIGGER reject_upload_registration_candidate_evidence_mutation "
            "ON integration.upload_registration_candidates"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()"
        ),
        ops.ExecuteSQLOp(
            "DROP TRIGGER reject_object_manifest_content_profile_change "
            "ON integration.object_manifests"
        ),
        ops.ExecuteSQLOp(
            "DROP FUNCTION integration.reject_object_manifest_content_profile_change()"
        ),
        *(
            ops.DropConstraintOp.from_constraint(constraint)
            for constraint in reversed(_deferred_foreign_keys())
        ),
    ]
    for table in reversed(Base.metadata.sorted_tables):
        operations.append(ops.DropTableOp.from_table(table))
    for schema in reversed(SCHEMAS):
        operations.append(ops.ExecuteSQLOp(f"DROP SCHEMA IF EXISTS {schema}"))
    return ops.DowngradeOps(ops=operations)


def _default_workspace_lookup_sql() -> tuple[str, ...]:
    """Create the only cross-workspace IAM lookup available to the app role.

    Normal IAM tables are forced through workspace RLS.  OIDC hydration happens
    before a workspace is selected, so this function returns one deterministic
    active membership for the already verified issuer/subject pair.  It has no
    list shape and therefore cannot become a membership-discovery API.
    """
    return (
        """
        CREATE FUNCTION iam.resolve_default_workspace(
            p_issuer text,
            p_external_subject text
        )
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, iam, platform
        AS $datariver$
            SELECT membership.workspace_id
            FROM iam.subjects AS subject
            JOIN iam.workspace_memberships AS membership
              ON membership.subject_id = subject.id
            JOIN platform.workspaces AS workspace
              ON workspace.id = membership.workspace_id
            WHERE subject.issuer = p_issuer
              AND subject.external_subject = p_external_subject
              AND subject.active IS TRUE
              AND membership.active IS TRUE
              AND (
                  membership.access_expires_at IS NULL
                  OR membership.access_expires_at > CURRENT_TIMESTAMP
              )
              AND workspace.status = 'ACTIVE'
            ORDER BY
              CASE WHEN membership.attributes ->> 'default_workspace' = 'true'
                THEN 0 ELSE 1 END,
              workspace.slug ASC,
              membership.workspace_id ASC
            LIMIT 1
        $datariver$
        """,
        "REVOKE ALL ON FUNCTION iam.resolve_default_workspace(text, text) FROM PUBLIC",
    )


def _deferred_foreign_keys() -> list[ForeignKeyConstraint]:
    constraints = [
        constraint
        for table in Base.metadata.tables.values()
        for constraint in table.foreign_key_constraints
        if constraint.use_alter
    ]
    return sorted(constraints, key=lambda constraint: str(constraint.name or ""))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "backend" / "alembic" / "versions" / "0001_initial_schema.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    upgrade = render_python_code(build_upgrade(), migration_context=None)
    downgrade = render_python_code(build_downgrade(), migration_context=None)
    content = f'''"""Initial canonical schemas.

Revision ID: 0001
Revises:
Create Date: 2026-07-14
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
{_indent(upgrade)}


def downgrade() -> None:
{_indent(downgrade)}
'''
    destination.write_text(content, encoding="utf-8", newline="\n")


def _indent(rendered: str) -> str:
    body = rendered.removeprefix("# ### commands auto generated by Alembic - please adjust! ###\n")
    body = body.removesuffix("    # ### end Alembic commands ###")
    return "\n".join("    " + line if line else "" for line in body.splitlines())


if __name__ == "__main__":
    main()
