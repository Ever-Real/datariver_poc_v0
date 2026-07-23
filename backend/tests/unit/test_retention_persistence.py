from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar, Protocol, cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Table

from datariver.infrastructure.db.models.retention import (
    ArchiveCapabilityAttestationModel,
    ErasureRequestEventModel,
    ErasureRequestModel,
    ImmutableArchiveReceiptModel,
    LegalHoldEventModel,
    LegalHoldModel,
    RetentionPolicyVersionModel,
)


class _TableModel(Protocol):
    __table__: ClassVar[Table]


def _table(model: type[object]) -> Table:
    return cast(type[_TableModel], model).__table__


def _constraint_names(model: type[object]) -> set[str]:
    table = _table(model)
    return {
        str(constraint.name) if constraint.name is not None else ""
        for constraint in table.constraints
    }


def _index(model: type[object], name: str) -> Index:
    table = _table(model)
    return next(index for index in table.indexes if index.name == name)


def test_retention_tables_have_tenant_keys_and_shape_constraints() -> None:
    assert {
        "uq_retention_policy_versions_workspace_id_id",
        "uq_retention_policy_versions_workspace_number",
        "uq_retention_policy_versions_workspace_id_hash",
        "fk_retention_policy_versions_requester_membership",
        "fk_retention_policy_versions_checker_membership",
        "fk_retention_policy_versions_superseder_membership",
        "ck_policy_versions_state_shape",
    } <= _constraint_names(RetentionPolicyVersionModel)
    assert {
        "uq_legal_holds_workspace_id_id",
        "fk_legal_holds_creator_membership",
        "fk_legal_holds_release_requester_membership",
        "fk_legal_holds_release_checker_membership",
        "ck_legal_holds_scope_shape",
        "ck_legal_holds_state_shape",
        "ck_legal_holds_payload_hash_sha256",
    } <= _constraint_names(LegalHoldModel)
    assert {
        "uq_legal_hold_events_hold_version",
        "fk_legal_hold_events_hold",
        "fk_legal_hold_events_actor_membership",
        "ck_legal_hold_events_action_version_shape",
    } <= _constraint_names(LegalHoldEventModel)
    assert {
        "uq_erasure_requests_workspace_id_id",
        "uq_erasure_requests_idempotent_payload",
        "fk_erasure_requests_retention_policy",
        "fk_erasure_requests_requester_membership",
        "fk_erasure_requests_checker_membership",
        "fk_erasure_requests_target_owner_membership",
        "ck_erasure_requests_retention_policy_hash_sha256",
        "ck_erasure_requests_review_window",
        "ck_erasure_requests_state_shape",
    } <= _constraint_names(ErasureRequestModel)
    policy_binding = next(
        constraint
        for constraint in _table(ErasureRequestModel).constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_erasure_requests_retention_policy"
    )
    assert {column.name for column in policy_binding.columns} == {
        "workspace_id",
        "retention_policy_id",
        "retention_policy_hash",
    }
    assert {
        "uq_erasure_request_events_request_version",
        "fk_erasure_request_events_request",
        "fk_erasure_request_events_actor_membership",
        "ck_erasure_request_events_action_version_shape",
    } <= _constraint_names(ErasureRequestEventModel)

    for model in (
        RetentionPolicyVersionModel,
        LegalHoldModel,
        LegalHoldEventModel,
        ErasureRequestModel,
        ErasureRequestEventModel,
    ):
        table = _table(model)
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            local_columns = {column.name for column in constraint.columns}
            referred_schema = next(iter(constraint.elements)).target_fullname.split(".", 1)[0]
            if referred_schema in {"iam", "retention"}:
                assert "workspace_id" in local_columns
            if referred_schema in {"platform", "retention"}:
                assert constraint.ondelete in {None, "NO ACTION", "RESTRICT"}


def test_active_policy_is_unique_and_every_nonreleased_hold_blocks() -> None:
    active = _index(
        RetentionPolicyVersionModel,
        "uq_retention_policy_versions_workspace_active",
    )
    assert active.unique
    assert str(active.dialect_options["postgresql"]["where"]) == "state = 'ACTIVE'"

    blocking = _index(LegalHoldModel, "ix_legal_holds_workspace_blocking_scope")
    assert not blocking.unique
    assert str(blocking.dialect_options["postgresql"]["where"]) == "state <> 'RELEASED'"

    state_shape = next(
        constraint
        for constraint in _table(LegalHoldModel).constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_legal_holds_state_shape"
    )
    expression = str(state_shape.sqltext)
    assert "RELEASE_REQUESTED" in expression
    assert "RELEASE_REJECTED" in expression
    assert "released_at IS NULL" in expression


def test_legal_hold_events_are_append_only_for_the_application_role() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    migration = (root / "backend/alembic/versions/0008_retention_policy_legal_hold.py").read_text(
        encoding="utf-8"
    )

    for source in (generator, migration):
        assert "GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;" in source
        assert not re.search(
            r"GRANT[^;]*(?:UPDATE|DELETE)[^;]*retention\.legal_hold_events",
            source,
        )
    assert '("policy_versions", "legal_holds", "legal_hold_events")' in migration
    assert "ALTER TABLE retention.{table} FORCE ROW LEVEL SECURITY" in migration
    assert _table(LegalHoldEventModel).schema == "retention"


def test_retention_grants_cannot_mutate_policy_or_hold_identity() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    app_block = generator.split("rolname = 'datariver_app'", maxsplit=1)[1].split(
        "END IF;", maxsplit=1
    )[0]

    assert "GRANT SELECT, INSERT ON retention.policy_versions" in app_block
    assert "GRANT SELECT, INSERT ON retention.legal_holds" in app_block
    assert not re.search(r"GRANT[^;]*DELETE[^;]*retention\.", app_block)
    assert "completed_operation_days" not in app_block
    assert "chat_content_days" not in app_block
    assert "audit_online_months" not in app_block
    assert "immutable_archive_years" not in app_block
    assert "data_class" not in app_block
    assert "scope_id" not in app_block
    assert "created_by" not in app_block


def test_erasure_persistence_has_no_execution_or_destructive_grant() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    migration = (root / "backend/alembic/versions/0009_erasure_request_maker_checker.py").read_text(
        encoding="utf-8"
    )
    repository = (root / "backend/src/datariver/infrastructure/db/retention.py").read_text(
        encoding="utf-8"
    )

    for source in (generator, migration):
        assert "GRANT SELECT, INSERT ON retention.erasure_requests TO datariver_app;" in source
        assert (
            "GRANT SELECT, INSERT ON retention.erasure_request_events TO datariver_app;" in source
        )
        assert not re.search(
            r"GRANT[^;]*(?:UPDATE|DELETE)[^;]*retention\.erasure_request_events",
            source,
        )
        assert not re.search(r"GRANT[^;]*DELETE[^;]*retention\.erasure", source)

    grant_columns = migration.split("GRANT UPDATE (", maxsplit=1)[1].split(")", maxsplit=1)[0]
    assert "state" in grant_columns
    assert "checker_id" in grant_columns
    for immutable_column in (
        "target_id",
        "target_version",
        "classification",
        "retention_policy_id",
        "retention_policy_hash",
        "requester_id",
        "payload_hash",
        "expires_at",
    ):
        assert immutable_column not in grant_columns

    erasure_repository = repository.split("class SqlErasureRequestRepository", maxsplit=1)[1].split(
        "class SqlErasureTargetReader", maxsplit=1
    )[0]
    assert "delete(" not in erasure_repository.lower()
    assert "archive" not in erasure_repository.lower()
    assert "execution" not in erasure_repository.lower()
    assert _table(ErasureRequestEventModel).schema == "retention"


def test_erasure_review_window_allows_expired_rejection_but_not_approval() -> None:
    review_window = next(
        constraint
        for constraint in _table(ErasureRequestModel).constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_erasure_requests_review_window"
    )
    expression = str(review_window.sqltext)
    assert "state <> 'APPROVED' OR decided_at < expires_at" in expression
    assert "decided_at IS NULL OR decided_at >= created_at" in expression


def test_archive_evidence_has_exact_bindings_and_no_cascade() -> None:
    assert {
        "uq_archive_capability_attestations_workspace_id_fingerprint",
        "ck_archive_capability_attestations_observation_window",
        "ck_archive_capability_attestations_state_shape",
        "ck_archive_capability_attestations_encryption_profile_fingerprint_sha256",
    } <= _constraint_names(ArchiveCapabilityAttestationModel)
    assert {
        "fk_immutable_archive_receipts_capability_attestation",
        "fk_immutable_archive_receipts_retention_policy",
        "ck_immutable_archive_receipts_content_readback_match",
        "ck_immutable_archive_receipts_retention_readback_match",
        "ck_immutable_archive_receipts_object_version_id",
    } <= _constraint_names(ImmutableArchiveReceiptModel)

    capability_binding = next(
        constraint
        for constraint in _table(ImmutableArchiveReceiptModel).constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_immutable_archive_receipts_capability_attestation"
    )
    assert [column.name for column in capability_binding.columns] == [
        "workspace_id",
        "capability_attestation_id",
        "capability_fingerprint",
        "encryption_profile_fingerprint",
        "worker_principal_fingerprint",
    ]
    policy_binding = next(
        constraint
        for constraint in _table(ImmutableArchiveReceiptModel).constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_immutable_archive_receipts_retention_policy"
    )
    assert [column.name for column in policy_binding.columns] == [
        "workspace_id",
        "retention_policy_id",
        "retention_policy_hash",
    ]
    for model in (ArchiveCapabilityAttestationModel, ImmutableArchiveReceiptModel):
        table = _table(model)
        assert "version" not in table.columns
        for constraint in table.foreign_key_constraints:
            assert constraint.ondelete in {None, "NO ACTION", "RESTRICT"}


def test_archive_evidence_is_owner_written_and_application_read_only() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    migration = (root / "backend/alembic/versions/0010_immutable_archive_evidence.py").read_text(
        encoding="utf-8"
    )
    repository = (root / "backend/src/datariver/infrastructure/db/retention.py").read_text(
        encoding="utf-8"
    )

    for source in (generator, migration):
        assert "GRANT SELECT ON retention.archive_capability_attestations" in source
        assert "retention.immutable_archive_receipts TO datariver_app" in source
        assert not re.search(
            r"GRANT[^;]*(?:INSERT|UPDATE|DELETE)[^;]*"
            r"(?:archive_capability_attestations|immutable_archive_receipts)"
            r"[^;]*TO datariver_app",
            source,
        )
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "REVOKE INSERT, UPDATE, DELETE" in migration
    archive_repository = repository.split("class SqlArchiveEvidenceRepository", maxsplit=1)[
        1
    ].split("class SqlRetentionUnitOfWork", maxsplit=1)[0]
    assert "delete(" not in archive_repository.lower()
    assert "ImmutableArchiveStore" not in archive_repository
    unit_of_work = repository.split("class SqlRetentionUnitOfWork", maxsplit=1)[1].split(
        "def _policy_model", maxsplit=1
    )[0]
    assert "SqlArchiveEvidenceRepository" not in unit_of_work
