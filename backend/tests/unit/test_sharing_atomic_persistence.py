from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import CheckConstraint

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.sharing import SqlSharingStore

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0055_atomic_sharing_invocation_results.py"
CANONICAL = ROOT / "backend/alembic/versions/0001_initial_schema.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"
STORE = ROOT / "backend/src/datariver/infrastructure/db/sharing.py"
ROUTES = ROOT / "backend/src/datariver/interfaces/http/routes/sharing.py"

PREPARE_TYPES = (
    "uuid",
    "uuid",
    "uuid",
    "text",
    "text",
    "text",
    "text",
    "uuid",
    "uuid",
    "uuid",
    "uuid",
    "text",
    "text",
    "text",
    "integer",
    "text",
    "text",
    "text",
)
COMPLETE_TYPES = (
    "uuid",
    "uuid",
    "uuid",
    "uuid",
    "text",
    "text",
    "text",
    "text",
    "uuid",
    "uuid",
    "uuid",
    "uuid",
    "text",
    "text",
    "text",
    "text",
    "integer",
    "text",
    "text",
    "text",
    "text",
    "text",
    "uuid",
    "text",
)


def _compact(value: str) -> str:
    return " ".join(value.split())


def _raw_sql_constant(source: str, name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)} = r\"\"\"(.*?)^\"\"\"",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"{name} is not a self-contained raw SQL contract"
    return match.group(1)


def _function_block(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION {re.escape(name)}\(.*?\)\s*"
        r"RETURNS TABLE \(.*?\)\s*LANGUAGE plpgsql.*?\n\$\$;",
        sql,
        flags=re.DOTALL,
    )
    assert match is not None, f"{name} is absent"
    return match.group(0)


def _signature(name: str, types: tuple[str, ...]) -> str:
    return f"{name}({', '.join(types)})"


def _check_sql(table_name: str) -> str:
    table = Base.metadata.tables[table_name]
    return _compact(
        " ".join(
            str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )
    )


def _foreign_key_delete_rules(table_name: str) -> dict[str, str | None]:
    table = Base.metadata.tables[table_name]
    return {
        constraint.referred_table.fullname: constraint.ondelete
        for constraint in table.foreign_key_constraints
    }


def _execute_sql_literals(source: str, function_name: str) -> tuple[str, ...]:
    module = ast.parse(source)
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    return tuple(
        call.args[0].value
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    )


def test_revision_and_schema_metadata_advance_to_atomic_sharing_head() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert REQUIRED_DATABASE_REVISION == "0062"
    assert 'revision: str = "0055"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0054"' in migration
    assert {
        "sharing.api_invocations",
        "sharing.api_invocation_results",
        "sharing.api_invocation_monthly_usage",
    } <= set(Base.metadata.tables)


def test_legacy_rows_remain_honest_and_new_rows_cannot_silently_be_legacy() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    grant = Base.metadata.tables["sharing.consumer_grants"]
    invocation = Base.metadata.tables["sharing.api_invocations"]
    grant_shape = _check_sql("sharing.consumer_grants")
    invocation_shape = _check_sql("sharing.api_invocations")

    assert grant.c.contract_version.server_default is None
    assert invocation.c.evidence_kind.server_default is None
    assert "LEGACY_CLIENT_V1" in grant_shape
    assert "consumer_subject_id IS NULL" in grant_shape
    assert "consumer_issuer IS NULL" in grant_shape
    assert "SUBJECT_CLIENT_V2" in grant_shape
    assert "consumer_subject_id IS NOT NULL" in grant_shape
    assert "LEGACY_USAGE_V1" in invocation_shape
    for column in (
        "actor_id",
        "consumer_issuer",
        "consumer_client_id",
        "product_id",
        "product_version_id",
        "graph_id",
        "release_id",
        "release_content_hash",
        "surface",
        "effective_classification",
        "security_scope_hash",
        "request_hash",
        "result_type",
        "result_hash",
        "result_size_bytes",
        "retention_data_class",
        "retention_policy_id",
        "retention_policy_hash",
        "retention_until",
        "audit_retention_policy_id",
        "audit_retention_policy_hash",
        "audit_retention_until",
        "completed_at",
    ):
        assert f"{column} IS NULL" in invocation_shape

    # Temporary defaults classify historical rows without inventing a V2 actor,
    # release, result, or policy binding. They are removed before runtime writes.
    assert 'server_default="LEGACY_CLIENT_V1"' in migration
    assert 'server_default="LEGACY_USAGE_V1"' in migration
    assert migration.count("server_default=None") >= 2
    assert "UPDATE sharing.consumer_grants" not in migration
    assert "UPDATE sharing.api_invocations" not in migration


def test_v2_evidence_fks_are_restrictive_and_shapes_are_fail_closed() -> None:
    grant_rules = _foreign_key_delete_rules("sharing.consumer_grants")
    invocation_rules = _foreign_key_delete_rules("sharing.api_invocations")
    result_rules = _foreign_key_delete_rules("sharing.api_invocation_results")
    monthly_rules = _foreign_key_delete_rules("sharing.api_invocation_monthly_usage")
    invocation_shape = _check_sql("sharing.api_invocations")

    assert grant_rules["sharing.api_product_versions"] == "RESTRICT"
    assert grant_rules["iam.workspace_memberships"] == "RESTRICT"
    assert invocation_rules["sharing.consumer_grants"] == "RESTRICT"
    assert invocation_rules["iam.workspace_memberships"] == "RESTRICT"
    assert invocation_rules["sharing.api_product_versions"] == "RESTRICT"
    assert result_rules["sharing.api_invocations"] == "RESTRICT"
    assert monthly_rules["sharing.consumer_grants"] == "RESTRICT"

    for contract in (
        "ATOMIC_RESULT_V2",
        "effective_classification BETWEEN 0 AND 3",
        "result_size_bytes BETWEEN 2 AND 1048576",
        "retention_until > completed_at",
        "SNAPSHOT_V1",
        "NEIGHBORS_V1",
        "CHAT_LOCAL_V1",
        "OBJECT_DATA",
        "CHAT_CONTENT",
    ):
        assert contract in invocation_shape


def test_result_body_is_canonical_hash_bound_and_limited_to_one_mibibyte() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    function_sql = _raw_sql_constant(migration, "_FUNCTION_SQL")
    complete = _function_block(function_sql, "sharing.complete_api_invocation_v2")
    result_shape = _check_sql("sharing.api_invocation_results")

    for contract in (
        "jsonb_typeof(result_document::jsonb) = 'object'",
        "result_size_bytes BETWEEN 2 AND 1048576",
        "octet_length(convert_to(result_document, 'UTF8')) = result_size_bytes",
        "encode(sha256(convert_to(result_document, 'UTF8')), 'hex') = result_hash",
        "retention_until > created_at",
    ):
        assert contract in result_shape
    for contract in (
        "jsonb_typeof(p_result_document::jsonb) <> 'object'",
        "canonical_size := octet_length(convert_to(COALESCE(p_result_document, ''), 'UTF8'))",
        "canonical_hash := encode(sha256(convert_to(p_result_document, 'UTF8')), 'hex')",
        "canonical_size > 1048576",
        "p_result_document, canonical_size, canonical_hash",
    ):
        assert contract in _compact(complete)
    assert complete.index("canonical_size :=") < complete.index(
        "jsonb_typeof(p_result_document::jsonb)"
    )


def test_database_capabilities_bound_inputs_and_lock_revocable_authority() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    function_sql = _raw_sql_constant(migration, "_FUNCTION_SQL")
    prepare = _compact(_function_block(function_sql, "sharing.prepare_api_invocation_v2"))
    complete = _compact(_function_block(function_sql, "sharing.complete_api_invocation_v2"))

    for function in (prepare, complete):
        for contract in (
            "COALESCE(char_length(p_invocation_key_hash), 0) <> 64",
            "COALESCE(char_length(p_legacy_invocation_key), 0) NOT BETWEEN 16 AND 200",
            "COALESCE(char_length(p_consumer_issuer), 0) NOT BETWEEN 1 AND 500",
            "COALESCE(char_length(p_consumer_client_id), 0) NOT BETWEEN 3 AND 255",
            "FROM iam.workspace_memberships AS membership",
            "membership.access_expires_at IS NULL FOR SHARE",
            "FROM iam.subjects AS subject_value",
            "subject_value.issuer = p_consumer_issuer FOR SHARE",
            "FROM knowledge.releases AS release",
            "release.content_hash = p_release_content_hash FOR SHARE",
            "FROM knowledge.changesets AS changeset",
            "FOR SHARE ) AS governed_lineage",
        ):
            assert contract in function
    assert "COALESCE(char_length(p_request_id), 0) NOT BETWEEN 1 AND 100" in complete


def test_canonical_bridge_rejects_malformed_security_objects() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    for contract in (
        "_PHASE6B_COLUMN_CONTRACT",
        "_PHASE6B_CONSTRAINT_DEFINITION_MD5",
        "_PHASE6B_INDEX_DEFINITION_MD5",
        "_PHASE6B_TRIGGER_DEFINITION",
        "Malformed atomic Sharing column contract.",
        "Malformed atomic Sharing constraint contract.",
        "Malformed atomic Sharing index contract.",
        "Atomic Sharing evidence tables must use FORCE RLS.",
        "Malformed atomic Sharing RLS policy contract.",
        "Malformed atomic Sharing trigger contract.",
        "Malformed atomic Sharing function contract:",
        "aclexplode",
        '"ck_api_invocations_single_unit"',
        '"uq_api_invocations_workspace_id_id"',
        '"fk_consumer_grants_workspace_id_product_id_product_vers_3221"',
        "trigger_state.tgenabled::text",
        "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'",
        "role_state.rolname NOT LIKE 'pg\\\\_%'",
        "has_function_privilege(",
        "datariver_app must be an unprivileged direct LOGIN principal",
        "datariver_app must not inherit or SET ROLE to another principal",
        "datariver_app must not be assumable by another non-superuser principal",
        "Atomic Sharing protected objects must remain migration-owner controlled",
        "to_regrole(current_user)::oid",
        "pg_has_role(app_role.oid, candidate.oid, 'MEMBER')",
        "pg_has_role(candidate.oid, app_role.oid, 'MEMBER')",
    ):
        assert contract in migration
    bridge = migration[
        migration.index("def upgrade() -> None:") : migration.index("def downgrade() -> None:")
    ]
    assert bridge.count("_assert_phase6b_contract()") == 2


def test_security_definer_functions_recheck_context_identity_grant_and_release() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    function_sql = _raw_sql_constant(migration, "_FUNCTION_SQL")
    prepare = _compact(_function_block(function_sql, "sharing.prepare_api_invocation_v2"))
    complete = _compact(_function_block(function_sql, "sharing.complete_api_invocation_v2"))

    assert "SECURITY DEFINER SET search_path = pg_catalog, sharing" in prepare
    assert "SET TimeZone = 'UTC'" in prepare
    assert (
        "SECURITY DEFINER SET search_path = pg_catalog, sharing, iam, knowledge, retention"
    ) in complete
    assert "SET TimeZone = 'UTC'" in complete
    for function in (prepare, complete):
        for contract in (
            "current_setting('app.workspace_id', true)",
            "current_setting('app.subject_id', true)",
            "contract_version = 'SUBJECT_CLIENT_V2'",
            "consumer_subject_id = p_subject_id",
            "consumer_issuer = p_consumer_issuer",
            "consumer_client_id = p_consumer_client_id",
            "grant_value.state <> 'ACTIVE'",
            "observed_at < grant_value.valid_from",
            "observed_at >= grant_value.expires_at",
            "grant_value.scopes ? p_requested_scope",
            "membership.job_function = 'SERVICE_ACCOUNT'",
            "membership.access_expires_at IS NULL",
            "subject_value.active",
            "subject_value.issuer = p_consumer_issuer",
            "release.content_hash = p_release_content_hash",
            "changeset.state = 'PUBLISHED'",
            "changeset.reviewed_by <> changeset.author_id",
            "length(btrim(changeset.review_reason)) > 0",
        ):
            assert contract in function

    # Prepare resolves and row-locks the active rule for both first execution and replay.
    for contract in (
        "selected_policy.contract_version = 'POLICY_BOOK_V2'",
        "selected_policy.state = 'ACTIVE'",
        "selected_rule.policy_hash = selected_policy.payload_hash",
        "selected_rule.data_class = current_retention_data_class",
        "selected_rule.minimum_value >= 1",
        "FOR SHARE OF selected_policy, selected_rule",
        "stored.retention_policy_id IS DISTINCT FROM current_retention_policy_id",
        "stored.retention_policy_hash IS DISTINCT FROM current_retention_policy_hash",
    ):
        assert contract in prepare


def test_retention_deadline_is_computed_by_database_not_supplied_by_caller() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    function_sql = _raw_sql_constant(migration, "_FUNCTION_SQL")
    complete = _compact(_function_block(function_sql, "sharing.complete_api_invocation_v2"))
    store = STORE.read_text(encoding="utf-8")

    assert "p_retention_until" not in complete
    assert ":retention_until" not in store
    assert "RetentionPolicyVersionModel" not in store
    assert "RetentionPolicyClassRuleModel" not in store
    assert "current_retention_policy_id" in _compact(
        _function_block(function_sql, "sharing.prepare_api_invocation_v2")
    )
    for contract in (
        "calculated_retention_until := CASE class_rule.unit",
        "observed_at + make_interval(days => class_rule.minimum_value)",
        "observed_at + make_interval(months => class_rule.minimum_value)",
        "observed_at + make_interval(years => class_rule.minimum_value)",
        "class_rule.minimum_value < 1",
        "calculated_audit_retention_until := CASE audit_rule.unit",
        "audit_rule.minimum_value < 1",
        "'AUDIT_EVIDENCE'",
        "calculated_retention_until, p_retention_policy_id, "
        "p_retention_policy_hash, calculated_audit_retention_until, "
        "observed_at, observed_at, 1",
        "p_retention_policy_id",
        "p_retention_policy_hash",
        "p_retention_data_class",
    ):
        assert contract in complete


def test_app_role_can_only_invoke_exact_database_capabilities() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    grant_sql = (
        _compact(_raw_sql_constant(migration, "_GRANT_SQL")).replace("( ", "(").replace(" )", ")")
    )
    downgrade_sql = " ".join(
        _compact(statement) for statement in _execute_sql_literals(migration, "downgrade")
    )
    prepare_signature = _signature("sharing.prepare_api_invocation_v2", PREPARE_TYPES)
    complete_signature = _signature("sharing.complete_api_invocation_v2", COMPLETE_TYPES)

    assert (
        "REVOKE ALL ON sharing.api_invocations, sharing.api_invocation_results, "
        "sharing.api_invocation_monthly_usage FROM datariver_app"
    ) in grant_sql
    assert "GRANT SELECT" not in grant_sql
    assert "GRANT INSERT" not in grant_sql
    assert "GRANT UPDATE" not in grant_sql
    assert "GRANT DELETE" not in grant_sql
    assert (
        "REVOKE ALL ON FUNCTION sharing.reject_invocation_evidence_mutation() FROM PUBLIC"
        in grant_sql
    )
    assert (
        "REVOKE ALL ON FUNCTION sharing.require_atomic_invocation_result() FROM PUBLIC" in grant_sql
    )
    for signature in (prepare_signature, complete_signature):
        assert f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC" in grant_sql
        assert f"GRANT EXECUTE ON FUNCTION {signature} TO datariver_app" in grant_sql
        assert f"DROP FUNCTION {signature}" in downgrade_sql


def test_deferred_exact_result_trigger_keeps_table_privileges_private() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    trigger_sql = _compact(_raw_sql_constant(migration, "_TRIGGER_FUNCTION_SQL"))

    assert (
        "CREATE OR REPLACE FUNCTION sharing.require_atomic_invocation_result() "
        "RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER "
        "SET search_path = pg_catalog, sharing"
    ) in trigger_sql
    assert "FROM sharing.api_invocation_results AS result" in trigger_sql


def test_downgrade_refuses_atomic_evidence_then_restores_legacy_privilege() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    downgrade = migration[migration.index("def downgrade() -> None:") :]

    assert "WHERE evidence_kind = 'ATOMIC_RESULT_V2'" in downgrade
    assert "WHERE contract_version = 'SUBJECT_CLIENT_V2'" in downgrade
    assert "if evidence or v2_grants:" in downgrade
    assert (
        '"Downgrade refused while atomic Sharing evidence or subject-bound grants exist."'
        in downgrade
    )
    assert downgrade.index("if evidence or v2_grants:") < downgrade.index(
        "DROP FUNCTION sharing.complete_api_invocation_v2("
    )
    assert (
        'op.execute("GRANT SELECT, INSERT ON sharing.api_invocations TO datariver_app")'
        in downgrade
    )
    assert 'ondelete="CASCADE"' in downgrade


def test_legacy_grant_can_be_explicitly_subject_bound_without_losing_usage() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")
    grant = Base.metadata.tables["sharing.consumer_grants"]
    index_names = {index.name for index in grant.indexes}

    assert "uq_consumer_grants_legacy_client" in index_names
    assert "uq_consumer_grants_v2_subject_client" in index_names
    assert "uq_consumer_grants_legacy_client" in migration
    assert "uq_consumer_grants_v2_subject_client" in migration
    assert 'ConsumerGrantModel.contract_version == "LEGACY_CLIENT_V1"' in store
    assert 'legacy_grant.contract_version = "SUBJECT_CLIENT_V2"' in store
    assert 'event_type="sharing.grant.identity-bound.v2"' in store
    assert '"preserved_legacy_usage": True' in store


def test_month_boundary_and_sensitive_http_results_are_cache_safe() -> None:
    month_shape = _check_sql("sharing.api_invocation_monthly_usage")
    migration = MIGRATION.read_text(encoding="utf-8")
    routes = ROUTES.read_text(encoding="utf-8")
    utc_expression = "date_trunc('month', month_start AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"

    assert utc_expression in month_shape
    assert utc_expression in migration
    assert routes.count('response.headers["Cache-Control"] = "private, no-store"') == 3


def test_monthly_retry_uses_the_precompletion_utc_boundary_snapshot() -> None:
    store = STORE.read_text(encoding="utf-8")
    capture = "completion_observed_at = await self._database_time()"
    completion = "completion = await self._complete_invocation("
    retry = "self._monthly_retry_after_seconds(\n                            completion_observed_at"

    assert store.index(capture) < store.index(completion) < store.index(retry)
    assert (
        SqlSharingStore._monthly_retry_after_seconds(
            datetime(2026, 12, 31, 23, 59, 59, 500_000, tzinfo=UTC)
        )
        == 60
    )
    assert (
        SqlSharingStore._monthly_retry_after_seconds(datetime(2026, 1, 31, 12, 0, 0, tzinfo=UTC))
        == 12 * 60 * 60
    )


def test_store_never_reads_or_writes_invocation_evidence_tables_directly() -> None:
    store = STORE.read_text(encoding="utf-8")

    for forbidden in (
        "ApiInvocationModel",
        "ApiInvocationResultModel",
        "ApiInvocationMonthlyUsageModel",
        "INSERT INTO sharing.api_invocations",
        "UPDATE sharing.api_invocations",
        "DELETE FROM sharing.api_invocations",
        "FROM sharing.api_invocations AS",
        "INSERT INTO sharing.api_invocation_results",
        "FROM sharing.api_invocation_results AS",
        "INSERT INTO sharing.api_invocation_monthly_usage",
        "FROM sharing.api_invocation_monthly_usage AS",
    ):
        assert forbidden not in store
    assert "FROM sharing.prepare_api_invocation_v2(" in store
    assert "FROM sharing.complete_api_invocation_v2(" in store


def test_generator_and_canonical_baseline_install_the_exact_phase6b_boundary() -> None:
    generator = GENERATOR.read_text(encoding="utf-8")
    canonical = CANONICAL.read_text(encoding="utf-8")
    runtime_grants = "operations.append(ops.ExecuteSQLOp(_runtime_grants_sql()))"
    phase6_upgrade = "phase6b = _load_phase6b_revision()"

    assert "0055_atomic_sharing_invocation_results.py" in generator
    assert "_load_phase6b_revision" in generator
    assert runtime_grants in generator
    assert phase6_upgrade in generator
    assert generator.index(runtime_grants) < generator.index(phase6_upgrade)
    assert '"_TRIGGER_FUNCTION_SQL"' in generator
    assert '"_TRIGGER_SQL"' in generator

    generator_downgrade = generator[generator.index("def build_downgrade()") :]
    for contract in (
        "prepare_api_invocation_v2",
        "complete_api_invocation_v2",
        "require_atomic_invocation_result",
        "reject_invocation_evidence_mutation",
    ):
        assert contract in generator_downgrade
        assert contract in canonical
    for contract in (
        "api_invocation_results",
        "api_invocation_monthly_usage",
        "ATOMIC_RESULT_V2",
        "REVOKE ALL ON sharing.api_invocations",
        "calculated_retention_until",
    ):
        assert contract in canonical
    assert canonical.rindex("REVOKE ALL ON sharing.api_invocations") > canonical.rindex(
        "GRANT SELECT, INSERT ON sharing.api_invocations"
    )
