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
    for table in Base.metadata.sorted_tables:
        operations.append(ops.CreateTableOp.from_table(table))
        operations.extend(
            ops.CreateIndexOp.from_index(index)
            for index in sorted(table.indexes, key=lambda value: value.name or "")
        )
        if "workspace_id" in table.columns or table.fullname == "platform.workspaces":
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
                owner_expression = (
                    "author_id = NULLIF(current_setting('app.subject_id', true), '')::uuid"
                )
                operations.append(
                    ops.ExecuteSQLOp(
                        "CREATE POLICY studio_draft_owner_access "
                        "ON knowledge.studio_drafts AS RESTRICTIVE FOR ALL "
                        f"TO datariver_app USING ({owner_expression}) "
                        f"WITH CHECK ({owner_expression})"
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
        GRANT SELECT, INSERT ON catalog.export_requests TO datariver_app;
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
            knowledge.graphrag_audits, knowledge.studio_drafts TO datariver_app;
        GRANT INSERT ON knowledge.graphs, knowledge.ontology_versions,
            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,
            knowledge.changesets, knowledge.change_operations,
            knowledge.validation_results, knowledge.projection_deployments,
            knowledge.source_snapshots, knowledge.source_pages,
            knowledge.source_page_embeddings, knowledge.extraction_runs,
            knowledge.graphrag_audits, knowledge.studio_drafts TO datariver_app;
        GRANT UPDATE ON knowledge.graphs, knowledge.changesets,
            knowledge.projection_deployments, knowledge.source_snapshots TO datariver_app;
        GRANT UPDATE (
            state, current_step, name, endpoint_alias,
            domain_ref_id, domain_ref_kind, domain_source_version,
            classification, review_requested_at, discarded_at,
            discarded_by, last_autosaved_at,
            version, updated_at
        ) ON knowledge.studio_drafts TO datariver_app;
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
    operations: list[ops.MigrateOperation] = [
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
    return sorted(constraints, key=lambda constraint: constraint.name or "")


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
