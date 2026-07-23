from __future__ import annotations

import runpy
from pathlib import Path

import pytest
import sqlalchemy as sa

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base

ROOT = Path(__file__).resolve().parents[3]

_NEW_INDEX_SIGNATURES = {
    ("iam.subjects", "ix_subjects_display_name_lower_id"): (
        "lower(display_name)",
        "subjects.id",
    ),
    (
        "platform.system_assignees",
        "ix_system_assignees_workspace_system_id",
    ): (
        "system_assignees.workspace_id",
        "system_assignees.system_id",
        "system_assignees.id",
    ),
    ("retention.legal_holds", "ix_legal_holds_workspace_created_id"): (
        "legal_holds.workspace_id",
        "created_at DESC",
        "legal_holds.id",
    ),
    (
        "retention.erasure_requests",
        "ix_erasure_requests_workspace_created_id",
    ): (
        "erasure_requests.workspace_id",
        "created_at DESC",
        "erasure_requests.id",
    ),
    (
        "authz.restricted_search_grants",
        "ix_restricted_search_grants_workspace_created_id",
    ): (
        "restricted_search_grants.workspace_id",
        "created_at DESC",
        "restricted_search_grants.id",
    ),
    (
        "integration.inference_provider_profile_versions",
        "ix_inference_profile_versions_workspace_order",
    ): (
        "inference_provider_profile_versions.workspace_id",
        "inference_provider_profile_versions.profile_key",
        "profile_version DESC",
        "inference_provider_profile_versions.id",
    ),
}


def test_admin_cursor_indexes_match_repository_keyset_order() -> None:
    actual: dict[tuple[str, str], tuple[str, ...]] = {
        (table.fullname, str(index.name)): tuple(
            str(expression) for expression in index.expressions
        )
        for table in Base.metadata.sorted_tables
        for index in table.indexes
        if index.name is not None
    }

    for key, expected_signature in _NEW_INDEX_SIGNATURES.items():
        assert actual[key] == expected_signature


def test_admin_cursor_index_migration_matches_canonical_schema() -> None:
    migration = (ROOT / "backend/alembic/versions/0044_admin_cursor_indexes.py").read_text(
        encoding="utf-8"
    )
    canonical = (ROOT / "backend/alembic/versions/0001_initial_schema.py").read_text(
        encoding="utf-8"
    )

    assert 'down_revision: str | Sequence[str] | None = "0043"' in migration
    for _, index_name in _NEW_INDEX_SIGNATURES:
        assert f'"{index_name}"' in migration
        assert canonical.count(f"'{index_name}'") == 1
    assert "indisvalid" in migration
    assert "indisready" in migration
    assert "access_method.amname" in migration
    assert "uses_default_opclasses" in migration
    assert "backs_constraint" in migration
    assert "indnatts" in migration
    assert "pg_get_indexdef(index_catalog.indexrelid, 0, true)" in migration
    assert "unexpected key terms" in migration
    assert "op.drop_index(" in migration
    assert "op.create_index(" in migration
    assert migration.count("postgresql_concurrently=True") == 2
    assert "autocommit_block" in migration
    assert "if_not_exists=True" not in migration


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"access_method": "hash"}, "unexpected definition"),
        ({"uses_default_opclasses": False}, "unexpected definition"),
        ({"indnatts": 3}, "unexpected definition"),
        ({"backs_constraint": True}, "unexpected definition"),
        (
            {
                "definition": (
                    "CREATE INDEX ix_subjects_display_name_lower_id ON iam.subjects "
                    "USING btree (lower(display_name) text_pattern_ops, id)"
                )
            },
            "unexpected canonical definition",
        ),
        (
            {
                "definition": (
                    "CREATE INDEX ix_subjects_display_name_lower_id ON iam.subjects "
                    'USING btree (lower(display_name) COLLATE "C", id)'
                )
            },
            "unexpected canonical definition",
        ),
    ],
)
def test_admin_cursor_index_fingerprint_fails_closed(
    patch: dict[str, object],
    message: str,
) -> None:
    namespace = runpy.run_path(str(ROOT / "backend/alembic/versions/0044_admin_cursor_indexes.py"))
    row: dict[str, object] = {
        "indisvalid": True,
        "indisready": True,
        "indisunique": False,
        "indisprimary": False,
        "indisexclusion": False,
        "indnatts": 2,
        "indnkeyatts": 2,
        "access_method": "btree",
        "key_options": [0, 0],
        "predicate": None,
        "uses_default_opclasses": True,
        "backs_constraint": False,
        "terms": ["lower(display_name)", "id"],
        "definition": (
            "CREATE INDEX ix_subjects_display_name_lower_id ON iam.subjects "
            "USING btree (lower(display_name), id)"
        ),
    }
    row.update(patch)

    class _Result:
        def mappings(self) -> _Result:
            return self

        def one_or_none(self) -> dict[str, object]:
            return row

    class _Binding:
        def execute(
            self,
            _statement: sa.TextClause,
            _parameters: dict[str, str],
        ) -> _Result:
            return _Result()

    class _Operation:
        @staticmethod
        def get_bind() -> _Binding:
            return _Binding()

    read_index_state = namespace["_read_index_state"]
    read_index_state.__globals__["op"] = _Operation()
    spec = namespace["_INDEXES"][0]

    with pytest.raises(RuntimeError, match=message):
        read_index_state(spec)


def test_system_assignee_runtime_contract_uses_soft_deactivation_without_delete_grant() -> None:
    repository = (ROOT / "backend/src/datariver/infrastructure/db/admin_access.py").read_text(
        encoding="utf-8"
    )
    grants = (ROOT / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")

    assert "delete(SystemAssigneeModel)" not in repository
    assert (
        "GRANT SELECT, INSERT, UPDATE ON platform.data_systems, platform.system_schema_scopes,\n"
        "            platform.system_assignees"
    ) in grants
    assert "GRANT DELETE ON platform.system_assignees" not in grants
