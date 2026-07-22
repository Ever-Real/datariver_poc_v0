from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol, cast

from sqlalchemy import ForeignKeyConstraint, Table

from datariver.infrastructure.db.models.classification_access import (
    ClassificationAccessGenerationModel,
    ClassificationAccessPolicyRuleModel,
    ClassificationAccessPolicyVersionModel,
    RestrictedSearchGrantEventModel,
    RestrictedSearchGrantModel,
)
from datariver.infrastructure.db.models.inference import (
    InferenceProviderGenerationModel,
    InferenceProviderProfileVersionModel,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


class _TableModel(Protocol):
    __table__: ClassVar[Table]


def _table(model: type[object]) -> Table:
    return cast(type[_TableModel], model).__table__


def _constraint_names(model: type[object]) -> set[str]:
    return {
        str(constraint.name) if constraint.name is not None else ""
        for constraint in _table(model).constraints
    }


def test_classification_models_bind_workspace_policy_and_provider_versions() -> None:
    assert {
        "uq_classification_policy_versions_exact",
        "uq_classification_policy_versions_number",
        "fk_classification_policy_versions_requester_membership",
        "fk_classification_policy_versions_checker_membership",
        "ck_classification_access_policy_versions_state_shape",
    } <= _constraint_names(ClassificationAccessPolicyVersionModel)
    assert {
        "fk_classification_policy_rules_policy",
        "fk_classification_policy_rules_provider_profile",
        "uq_classification_policy_rules_classification",
        "ck_classification_access_policy_rules_restricted_floor",
        "ck_classification_access_policy_rules_confidential_chat_floor",
    } <= _constraint_names(ClassificationAccessPolicyRuleModel)
    assert {
        "fk_restricted_search_grants_policy",
        "fk_restricted_search_grants_subject_membership",
        "fk_restricted_search_grants_checker_membership",
        "ck_restricted_search_grants_state_shape",
    } <= _constraint_names(RestrictedSearchGrantModel)
    assert {
        "fk_restricted_search_grant_events_grant",
        "fk_restricted_search_grant_events_actor_membership",
        "uq_grant_events_version",
    } <= _constraint_names(RestrictedSearchGrantEventModel)

    policy_binding = next(
        constraint
        for constraint in _table(RestrictedSearchGrantModel).constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_restricted_search_grants_policy"
    )
    assert {column.name for column in policy_binding.columns} == {
        "workspace_id",
        "classification_policy_id",
        "classification_policy_hash",
    }


def test_inference_models_are_versioned_without_endpoint_or_secret_columns() -> None:
    table = _table(InferenceProviderProfileVersionModel)
    assert {
        "uq_inference_profile_versions_workspace_id",
        "uq_inference_profile_versions_key_version",
        "fk_inference_profile_versions_maker_membership",
        "fk_inference_profile_versions_checker_membership",
        "ck_inference_provider_profile_versions_external_classification_floor",
        "ck_inference_provider_profile_versions_no_endpoint_values",
        "ck_inference_provider_profile_versions_state_shape",
    } <= _constraint_names(InferenceProviderProfileVersionModel)
    assert not ({"url", "endpoint", "credential", "api_key", "secret"} & set(table.columns))
    assert _table(ClassificationAccessGenerationModel).schema == "authz"
    assert _table(InferenceProviderGenerationModel).schema == "integration"


def test_migration_installs_fail_closed_triggers_rls_and_limited_role_grants() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0011_governed_classification_access.py"
    ).read_text(encoding="utf-8")
    assert REQUIRED_DATABASE_REVISION == "0039"
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "validate_classification_policy_activation" in migration
    assert "validate_restricted_search_grant" in migration
    assert "validate_inference_provider_approval" in migration
    assert "bump_classification_access_generation" in migration
    assert "bump_inference_provider_generation" in migration
    assert "REVOKE DELETE" in migration
    assert "REVOKE UPDATE" in migration
    assert "CREATE POLICY workspace_isolation" in migration
    assert "ON DELETE CASCADE" not in migration
