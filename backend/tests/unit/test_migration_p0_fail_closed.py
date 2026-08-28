from __future__ import annotations

import ast
from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Never, cast

import pytest

from datariver.infrastructure.db.migration_definition_fingerprint import (
    RELATION_DEFINITION_FINGERPRINT_SQL_V1,
)

ROOT = Path(__file__).resolve().parents[3]


def _load_source(path: Path, name: str) -> ModuleType:
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load source: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_static = _load_source(ROOT / "scripts/verify_static.py", "test_verify_static")


def _load_migration(filename: str) -> ModuleType:
    return _load_source(
        ROOT / "backend/alembic/versions" / filename,
        f"test_p0_{Path(filename).stem}",
    )


def _callable(module: ModuleType, name: str) -> Callable[[], None]:
    value = getattr(module, name)
    if not callable(value):
        raise AssertionError(f"{module.__name__}.{name} is not callable")
    return cast(Callable[[], None], value)


class _RejectingOperations:
    def __getattr__(self, operation: str) -> Never:
        raise AssertionError(f"migration unexpectedly executed Alembic operation: {operation}")


class _LegacyCreateProbe:
    def __getattr__(self, operation: str) -> Callable[..., object]:
        if operation == "f":
            return lambda value: value
        if operation != "create_table":
            raise AssertionError(f"unexpected legacy operation: {operation}")

        def entered(*args: object, **kwargs: object) -> Never:
            del args, kwargs
            raise _LegacyPathEntered

        return entered


class _LegacyPathEntered(Exception):
    pass


class _MappingResult:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def mappings(self) -> _MappingResult:
        return self

    def one(self) -> dict[str, object]:
        return self._row


class _SequentialDefinitionBind:
    def __init__(self, *rows: dict[str, object]) -> None:
        self._rows = list(rows)

    def execute(self, *_args: object, **_kwargs: object) -> _MappingResult:
        if not self._rows:
            raise AssertionError("unexpected fingerprint fixture query")
        return _MappingResult(self._rows.pop(0))


def test_0011_fresh_canonical_and_malformed_states_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_migration("0011_governed_classification_access.py")
    monkeypatch.setattr(module, "_existing_object_count", lambda: 0)
    monkeypatch.setattr(module, "op", _LegacyCreateProbe())
    with pytest.raises(_LegacyPathEntered):
        _callable(module, "upgrade")()

    module = _load_migration("0011_governed_classification_access.py")
    installer_calls = 0

    def installed() -> None:
        nonlocal installer_calls
        installer_calls += 1

    monkeypatch.setattr(module, "_existing_object_count", lambda: 7)
    monkeypatch.setattr(module, "_is_canonical_schema", lambda: True)
    monkeypatch.setattr(module, "_install_security_contract", installed)
    monkeypatch.setattr(module, "op", _RejectingOperations())
    _callable(module, "upgrade")()
    assert installer_calls == 1

    module = _load_migration("0011_governed_classification_access.py")
    monkeypatch.setattr(module, "_existing_object_count", lambda: 7)
    monkeypatch.setattr(module, "_is_canonical_schema", lambda: False)
    monkeypatch.setattr(module, "op", _RejectingOperations())
    with pytest.raises(RuntimeError, match="partially present"):
        _callable(module, "upgrade")()


def _column_type_signature(type_node: ast.expr) -> tuple[str, str, str]:
    rendered = ast.unparse(type_node)
    if "Uuid" in rendered:
        return "uuid", "uuid", ""
    if "BigInteger" in rendered:
        return "bigint", "int8", ""
    if "Integer" in rendered:
        return "integer", "int4", ""
    if "DateTime" in rendered:
        return "timestamp with time zone", "timestamptz", ""
    if "Date()" in rendered:
        return "date", "date", ""
    if "Boolean" in rendered:
        return "boolean", "bool", ""
    if "JSONB" in rendered or "JSON()" in rendered:
        return "jsonb", "jsonb", ""
    if "Text" in rendered:
        return "text", "text", ""
    if "String" in rendered and isinstance(type_node, ast.Call):
        length = next(
            (
                str(keyword.value.value)
                for keyword in type_node.keywords
                if keyword.arg == "length" and isinstance(keyword.value, ast.Constant)
            ),
            "",
        )
        return "character varying", "varchar", length
    raise AssertionError(f"unsupported canonical type in fixture: {rendered}")


def _canonical_0001_columns() -> dict[str, tuple[str, ...]]:
    tree = ast.parse(
        (ROOT / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")
    )
    wanted = {
        "authz.classification_access_generations",
        "authz.classification_access_policy_versions",
        "authz.classification_access_policy_rules",
        "authz.restricted_search_grants",
        "authz.restricted_search_grant_events",
        "integration.inference_provider_generations",
        "integration.inference_provider_profile_versions",
        "iam.access_roles",
        "iam.membership_renewal_requests",
        "platform.external_service_profile_versions",
        "governance.change_request_rounds",
        "governance.change_test_runs",
        "knowledge.source_snapshots",
        "knowledge.source_pages",
        "knowledge.source_page_embeddings",
        "knowledge.extraction_runs",
        "knowledge.graphrag_audits",
    }
    tables: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            continue
        table_name = str(node.args[0].value)
        schema_name = next(
            (
                str(keyword.value.value)
                for keyword in node.keywords
                if keyword.arg == "schema" and isinstance(keyword.value, ast.Constant)
            ),
            "",
        )
        relation = f"{schema_name}.{table_name}"
        if relation not in wanted:
            continue
        columns: list[str] = []
        for argument in node.args[1:]:
            if not (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Attribute)
                and argument.func.attr == "Column"
                and len(argument.args) >= 2
                and isinstance(argument.args[0], ast.Constant)
                and isinstance(argument.args[0].value, str)
            ):
                continue
            data_type, udt_name, length = _column_type_signature(argument.args[1])
            nullable = next(
                (
                    bool(keyword.value.value)
                    for keyword in argument.keywords
                    if keyword.arg == "nullable" and isinstance(keyword.value, ast.Constant)
                ),
                True,
            )
            columns.append(
                f"{argument.args[0].value}|{data_type}|{udt_name}|{length}|"
                f"{'YES' if nullable else 'NO'}"
            )
        tables[relation] = tuple(columns)
    return tables


def test_explicit_compatibility_manifests_match_squashed_0001_columns() -> None:
    canonical = _canonical_0001_columns()
    governed = _load_migration("0011_governed_classification_access.py")
    for relation, expected in governed._CANONICAL_TABLES.items():
        assert set(expected[0]) == set(canonical[relation])

    single_tables = {
        "0031_workspace_access_roles.py": "iam.access_roles",
        "0032_membership_renewal_workflow.py": "iam.membership_renewal_requests",
        "0034_system_configuration_activation.py": ("platform.external_service_profile_versions"),
    }
    for filename, relation in single_tables.items():
        module = _load_migration(filename)
        assert set(module._CANONICAL_COLUMNS) == set(canonical[relation])

    for filename, schema_name in (
        ("0035_change_request_rounds_and_test_evidence.py", "governance"),
        ("0037_knowledge_source_graphrag_projection.py", "knowledge"),
    ):
        module = _load_migration(filename)
        for table_name, expected in module._CANONICAL_TABLES.items():
            assert set(expected[0]) == set(canonical[f"{schema_name}.{table_name}"])


def test_definition_fingerprint_v1_normalizes_security_and_integrity_definitions() -> None:
    source = str(RELATION_DEFINITION_FINGERPRINT_SQL_V1)
    for required_fragment in (
        "pg_get_constraintdef",
        "pg_get_indexdef",
        "indisunique",
        "indpred",
        "polpermissive",
        "polcmd",
        "polroles",
        "polqual",
        "polwithcheck",
        "pg_get_triggerdef",
        "tgenabled",
        "tgfoid::regprocedure",
        "relrowsecurity",
        "relforcerowsecurity",
        "[[:space:]]+",
    ):
        assert required_fragment in source


@pytest.mark.parametrize(
    "malformed_field",
    ("constraints", "indexes", "policies", "triggers", "rls"),
)
def test_0037_same_name_wrong_definition_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    malformed_field: str,
) -> None:
    module = _load_migration("0037_knowledge_source_graphrag_projection.py")
    relation = "knowledge.source_snapshots"
    expected_columns, expected_constraints, expected_indexes, expected_triggers = (
        module._CANONICAL_TABLES["source_snapshots"]
    )
    expected_fingerprint = module._CANONICAL_DEFINITION_FINGERPRINTS[relation]
    malformed_value = "false|true" if malformed_field == "rls" else "0" * 64
    malformed_fingerprint = expected_fingerprint._replace(**{malformed_field: malformed_value})
    bind = _SequentialDefinitionBind(
        {
            "columns": expected_columns,
            "constraints": expected_constraints,
            "indexes": expected_indexes,
            "policies": module._CANONICAL_POLICIES[relation],
            "triggers": expected_triggers,
            "force_rls": True,
        },
        malformed_fingerprint._asdict(),
    )
    monkeypatch.setattr(module.op, "get_bind", lambda: bind)

    assert not module._table_contract_is_exact(
        "source_snapshots",
        expected_columns,
        expected_constraints,
        expected_indexes,
        expected_triggers,
    )


def _static_fixture(tmp_path: Path) -> tuple[Path, Path]:
    migration_root = tmp_path / "backend/alembic/versions"
    scripts_root = tmp_path / "scripts"
    migration_root.mkdir(parents=True)
    scripts_root.mkdir()
    (migration_root / "0001.py").write_text("revision = '0001'\n", encoding="utf-8")
    return migration_root, scripts_root


def test_static_gate_rejects_fail_open_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    migration_root, _scripts_root = _static_fixture(tmp_path)
    monkeypatch.setattr(verify_static, "ROOT", tmp_path)
    verify_static.verify_migration_fail_closed_integrity()

    (migration_root / "0002.py").write_text(
        'print("Bypassed strict schema check")\n', encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="fail-open migration marker"):
        verify_static.verify_migration_fail_closed_integrity()


def test_static_gate_rejects_patch_tool_and_blanket_rewriter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _migration_root, scripts_root = _static_fixture(tmp_path)
    monkeypatch.setattr(verify_static, "ROOT", tmp_path)

    patch_tool = tmp_path / "patch_migrations.py"
    patch_tool.write_text("pass\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="blanket migration patch tool"):
        verify_static.verify_migration_fail_closed_integrity()
    patch_tool.unlink()

    (scripts_root / "rewrite.py").write_text(
        'source.replace("raise RuntimeError", "print(")\n', encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="RuntimeError-to-print"):
        verify_static.verify_migration_fail_closed_integrity()
