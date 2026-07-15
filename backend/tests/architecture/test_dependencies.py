from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "datariver"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def violations(root: Path, forbidden: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for path in root.rglob("*.py"):
        for module in imported_modules(path):
            if module.startswith(forbidden):
                result.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    return sorted(result)


def test_domain_is_framework_independent() -> None:
    assert (
        violations(
            SOURCE_ROOT / "domain",
            (
                "fastapi",
                "pydantic",
                "sqlalchemy",
                "redis",
                "httpx",
                "boto3",
                "datariver.application",
                "datariver.infrastructure",
                "datariver.interfaces",
            ),
        )
        == []
    )


def test_application_does_not_depend_on_adapters() -> None:
    assert (
        violations(
            SOURCE_ROOT / "application",
            (
                "fastapi",
                "sqlalchemy",
                "redis",
                "httpx",
                "boto3",
                "datariver.infrastructure",
                "datariver.interfaces",
            ),
        )
        == []
    )


def test_production_source_has_no_deferred_work_markers() -> None:
    markers: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        content = path.read_text(encoding="utf-8").upper()
        for marker in ("TODO", "FIXME"):
            if marker in content:
                markers.append(f"{path.relative_to(SOURCE_ROOT)} contains {marker}")
    assert markers == []
