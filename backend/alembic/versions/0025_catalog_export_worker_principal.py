"""Provision the isolated catalog-export worker principal and grants.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-19
"""

import os
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXPORT_SECRET_PATH = Path(
    os.environ.get("POSTGRES_EXPORT_PASSWORD_FILE", "/run/secrets/postgres_export_password")
)


def upgrade() -> None:
    """Create or reconcile only the scoped worker principal, never a shared worker role."""
    password = _read_export_password()
    bind = op.get_bind()
    exists = bool(
        bind.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_export')")
        ).scalar_one()
    )
    if not exists:
        bind.execute(sa.text("CREATE ROLE datariver_export LOGIN NOBYPASSRLS"))
    statement = bind.execute(
        sa.text(
            "SELECT format('ALTER ROLE datariver_export WITH LOGIN PASSWORD %L "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', "
            "CAST(:password AS text))"
        ),
        {"password": password},
    ).scalar_one()
    bind.execute(sa.text(str(statement)))
    _install_grants()


def downgrade() -> None:
    # Roles and their credential lifecycle are deployment assets.  Do not drop a
    # principal or revoke a still-running worker during an application downgrade.
    pass


def _read_export_password() -> str:
    try:
        password = _EXPORT_SECRET_PATH.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(
            "The catalog export migration requires the mounted postgres_export_password secret."
        ) from error
    if not password:
        raise RuntimeError("The mounted postgres_export_password secret is empty.")
    return password


def _install_grants() -> None:
    statements = (
        "GRANT USAGE ON SCHEMA platform, iam, authz, catalog, integration TO datariver_export",
        "GRANT SELECT ON platform.workspaces, iam.subjects, iam.workspace_memberships "
        "TO datariver_export",
        "GRANT SELECT ON authz.classification_access_policy_versions, "
        "authz.classification_access_policy_rules, authz.classification_access_generations, "
        "authz.restricted_search_grants TO datariver_export",
        "GRANT INSERT ON authz.policy_decisions TO datariver_export",
        "GRANT SELECT ON catalog.assets_projection, catalog.projection_watermarks, "
        "catalog.export_requests TO datariver_export",
        "GRANT UPDATE (object_bucket, object_key, row_count, size_bytes, content_sha256, "
        "provider_checksum, completed_at, version, updated_at) "
        "ON catalog.export_requests TO datariver_export",
        "GRANT SELECT ON integration.inference_provider_profile_versions, integration.jobs, "
        "integration.job_attempts TO datariver_export",
        "GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_export",
        "GRANT UPDATE (state, progress, result_ref, lease_until, attempts, last_error_code, "
        "version, updated_at) ON integration.jobs TO datariver_export",
        "GRANT INSERT, UPDATE (state, error_class, external_response_hash, finished_at) "
        "ON integration.job_attempts TO datariver_export",
    )
    for statement in statements:
        op.execute(statement)
