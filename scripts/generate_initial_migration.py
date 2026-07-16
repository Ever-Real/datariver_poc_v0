# ruff: noqa: S608 -- this script renders SQL from fixed schema constants only.

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import render_python_code
from alembic.operations import ops
from sqlalchemy import ForeignKeyConstraint

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base

SCHEMAS = (
    "platform",
    "iam",
    "authz",
    "catalog",
    "governance",
    "integration",
    "knowledge",
    "assistant",
    "sharing",
    "retention",
)
RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
RUNTIME_SCHEMAS = ", ".join(SCHEMAS)


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
    operations.extend(
        ops.CreateForeignKeyOp.from_constraint(constraint)
        for constraint in _deferred_foreign_keys()
    )
    operations.append(ops.ExecuteSQLOp(_runtime_grants_sql()))
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
        GRANT SELECT ON iam.workspace_memberships TO datariver_app;
        GRANT UPDATE (active, clearance, attributes, version, updated_at)
            ON iam.workspace_memberships TO datariver_app;
        GRANT SELECT, INSERT ON iam.admin_access_requests TO datariver_app;
        GRANT UPDATE (state, checker_id, consumed_by, consumed_at,
            consume_policy_decision_id, version, updated_at)
            ON iam.admin_access_requests TO datariver_app;
        GRANT SELECT, INSERT ON iam.admin_access_approvals TO datariver_app;
        GRANT INSERT ON authz.policy_decisions TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON catalog.assets_projection,
            catalog.sync_runs, catalog.projection_watermarks TO datariver_app;
        GRANT SELECT, INSERT ON governance.change_request_items,
            governance.approvals, governance.state_transitions TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON governance.change_requests TO datariver_app;
        GRANT SELECT ON integration.jobs, integration.job_attempts TO datariver_app;
        GRANT SELECT, INSERT, UPDATE ON integration.object_manifests TO datariver_app;
        GRANT SELECT, INSERT ON integration.idempotency_keys,
            integration.outbox_events TO datariver_app;
        GRANT SELECT ON knowledge.graphs, knowledge.ontology_versions,
            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,
            knowledge.changesets, knowledge.change_operations,
            knowledge.validation_results, knowledge.projection_deployments TO datariver_app;
        GRANT INSERT ON knowledge.graphs, knowledge.ontology_versions,
            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,
            knowledge.changesets, knowledge.change_operations,
            knowledge.validation_results, knowledge.projection_deployments TO datariver_app;
        GRANT UPDATE ON knowledge.graphs, knowledge.changesets,
            knowledge.projection_deployments TO datariver_app;
        GRANT DELETE ON knowledge.validation_results TO datariver_app;
        GRANT SELECT, INSERT ON assistant.chat_sessions, assistant.chat_messages,
            assistant.assistant_runs, assistant.evidence_citations TO datariver_app;
        GRANT UPDATE ON assistant.chat_sessions TO datariver_app;
        GRANT SELECT, INSERT ON retention.policy_versions TO datariver_app;
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
        GRANT SELECT, INSERT, UPDATE ON sharing.api_products,
            sharing.api_product_versions, sharing.consumer_grants TO datariver_app;
        GRANT SELECT, INSERT ON sharing.api_invocations TO datariver_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') THEN
        GRANT USAGE ON SCHEMA integration TO datariver_relay;
        GRANT SELECT, UPDATE ON integration.outbox_events TO datariver_relay;
        GRANT SELECT ON integration.inbox_messages TO datariver_relay;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_upload') THEN
        GRANT USAGE ON SCHEMA integration TO datariver_upload;
        GRANT SELECT, UPDATE ON integration.object_manifests TO datariver_upload;
        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_upload;
        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_upload;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN
        GRANT USAGE ON SCHEMA authz, governance, integration TO datariver_governance;
        GRANT SELECT, INSERT ON authz.policy_decisions TO datariver_governance;
        GRANT SELECT, UPDATE ON governance.change_requests TO datariver_governance;
        GRANT SELECT ON governance.change_request_items, governance.approvals,
            governance.state_transitions TO datariver_governance;
        GRANT INSERT ON governance.state_transitions TO datariver_governance;
        GRANT SELECT, INSERT, UPDATE ON integration.jobs,
            integration.job_attempts, integration.inbox_messages TO datariver_governance;
        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_governance;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_bootstrap') THEN
        GRANT USAGE ON SCHEMA platform, iam TO datariver_bootstrap;
        GRANT SELECT, INSERT, UPDATE ON platform.workspaces, iam.subjects,
            iam.workspace_memberships TO datariver_bootstrap;
    END IF;
END
$datariver$
""".strip()


def build_downgrade() -> ops.DowngradeOps:
    operations: list[ops.MigrateOperation] = [
        ops.DropConstraintOp.from_constraint(constraint)
        for constraint in reversed(_deferred_foreign_keys())
    ]
    for table in reversed(Base.metadata.sorted_tables):
        operations.append(ops.DropTableOp.from_table(table))
    for schema in reversed(SCHEMAS):
        operations.append(ops.ExecuteSQLOp(f"DROP SCHEMA IF EXISTS {schema}"))
    return ops.DowngradeOps(ops=operations)


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
