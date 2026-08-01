from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from datariver.infrastructure.db.identity_provisioning_sql import (
    IDENTITY_PROVISIONING_FUNCTION_SQL,
    IDENTITY_PROVISIONING_FUNCTION_SQL_V1,
    IDENTITY_PROVISIONING_FUNCTION_SQL_V3,
)


def test_identity_provisioning_function_is_fixed_and_rechecks_admin_context() -> None:
    sql = IDENTITY_PROVISIONING_FUNCTION_SQL
    assert "SECURITY DEFINER" in sql
    assert "current_setting('app.subject_id'" in sql
    assert "current_setting('app.workspace_id'" in sql
    assert "security-administrators" in sql
    assert "admin.manage" in sql
    assert "IDENTITY_PROVISIONING_V1" in sql
    assert "role_kind = 'HUMAN_ROLE'" in sql
    assert "not an assignable human role" in sql
    assert "EXECUTE " not in sql
    assert "password" not in sql.lower()


def test_0089_pins_human_role_only_provisioning_and_a_legacy_downgrade_body() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0089_canonical_admin_role_binding.py").read_text(
        encoding="utf-8"
    )
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert "role_kind = 'HUMAN_ROLE'" not in IDENTITY_PROVISIONING_FUNCTION_SQL_V1
    assert "The selected workspace role is not active" in IDENTITY_PROVISIONING_FUNCTION_SQL_V1
    assert "IDENTITY_PROVISIONING_FUNCTION_SQL_V1" in migration
    assert "_PROVISIONING_V2_SHA256" in migration
    assert "_PROVISIONING_V1_SHA256" in migration
    assert "role_kind = 'HUMAN_ROLE'" in initial


def test_0090_new_human_provisioning_is_atomic_viewer_confidential_only() -> None:
    sql = IDENTITY_PROVISIONING_FUNCTION_SQL_V3

    assert "access_clearance integer := 2" in sql
    assert "New human identities always receive the Viewer profile Role" in sql
    assert "INSERT INTO iam.workspace_memberships" in sql
    assert "INSERT INTO iam.profile_role_assignments" in sql
    assert "INSERT INTO iam.profile_role_assignment_events" in sql
    assert "p_policy_decision_id uuid" in sql
    assert "p_policy_decision_id IS NULL" in sql
    assert "policy_decision_id, reason, assurance" in sql
    assert "'VIEWER', 'PROFILE_ROLE_POLICY_V1'" in sql
    assert "UPDATE iam.workspace_memberships" not in sql
    assert sql.index("IF p_role_id IS NOT NULL") < sql.index("INSERT INTO iam.subjects")


def test_identity_migration_and_initial_baseline_have_execute_only_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0039_governed_identity_provisioning.py"
    ).read_text(encoding="utf-8")
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "0038"' in migration
    assert "IDENTITY_PROVISIONING_FUNCTION_SQL" in migration
    assert "IDENTITY_PROVISIONING_SIGNATURE" in migration
    for source in (migration, initial):
        assert "REVOKE ALL ON FUNCTION" in source
        assert "GRANT EXECUTE ON FUNCTION" in source
    assert "provision_workspace_identity" in initial
    assert "GRANT INSERT ON iam.subjects" not in initial
    assert "GRANT INSERT ON iam.workspace_memberships" not in initial


def test_api_does_not_receive_keycloak_bootstrap_admin_secret() -> None:
    root = Path(__file__).resolve().parents[3]
    compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    api_secrets = {
        entry if isinstance(entry, str) else entry["source"]
        for entry in compose["services"]["api"]["secrets"]
    }

    assert "keycloak_identity_admin_client_secret" in api_secrets
    assert "keycloak_admin_password" not in api_secrets
    assert "postgres_bootstrap_password" not in api_secrets


def test_password_change_template_preserves_provider_action_without_product_exposure() -> None:
    root = Path(__file__).resolve().parents[3]
    template = (root / "infra/keycloak/themes/datariver/login/login-update-password.ftl").read_text(
        encoding="utf-8"
    )

    assert 'name="password-new"' in template
    assert 'name="password-confirm"' in template
    assert 'name="cancel-aia"' in template
    assert "passwordCommons.logoutOtherSessions" in template
    assert "Keycloak" not in template
