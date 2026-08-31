from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MODULE_PATH = SCRIPTS / "prep39083_release_prepare.py"


def _load_module() -> ModuleType:
    sys.path.insert(0, os.fspath(SCRIPTS))
    try:
        specification = importlib.util.spec_from_file_location(
            "prep39083_release_prepare_for_test",
            MODULE_PATH,
        )
        assert specification is not None
        assert specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(os.fspath(SCRIPTS))


prepare = _load_module()


def test_disposable_release_builds_runtime_before_server_regression() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    build = 'run(["npm", "run", "build:poc"]'
    regression = 'run(["npm", "run", "test:poc-server"]'

    assert build in source
    assert regression in source
    assert source.index(build) < source.index(regression)


def _git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603 - test-owned fixed Git argv.
        ["git", *arguments],  # noqa: S607 - Git is the tested release dependency.
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str, str]:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "config", "user.name", "test")
    (repository / "README.md").write_text("base", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    (repository / "frontend").mkdir()
    (repository / "frontend/product.mjs").write_text("export const value = 1\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "product")
    product = _git(repository, "rev-parse", "HEAD")
    (repository / "docs").mkdir()
    (repository / "docs/evidence.md").write_text("evidence", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "metadata")
    metadata = _git(repository, "rev-parse", "HEAD")
    (repository / "local-dirty.txt").write_text("uncommitted", encoding="utf-8")
    return repository, product, metadata, _git(repository, "rev-parse", "HEAD")


def test_product_selection_ignores_dirty_worktree_and_rejects_metadata_commit(
    tmp_path: Path,
) -> None:
    repository, product, metadata, origin_dev = _repository(tmp_path)

    prepare.validate_product(product, repository=repository, origin_dev=origin_dev)
    with pytest.raises(prepare.PrepareError) as captured:
        prepare.validate_product(metadata, repository=repository, origin_dev=origin_dev)
    assert captured.value.code == "PREP_RELEASE_METADATA_COMMIT_SELECTED"


def test_release_bridge_keeps_previous_snapshot_and_selected_product_as_ancestors(
    tmp_path: Path,
) -> None:
    repository, product, metadata, _origin_dev = _repository(tmp_path)
    (repository / "local-dirty.txt").unlink()

    bridge = prepare.create_release_base(
        repository,
        product_sha=product,
        previous_release=metadata,
    )

    assert _git(repository, "branch", "--show-current") == prepare.RELEASE_REF
    assert subprocess.run(  # noqa: S603 - test-owned fixed Git argv.
        [  # noqa: S607 - Git is the tested release dependency.
            "git",
            "merge-base",
            "--is-ancestor",
            metadata,
            bridge,
        ],
        cwd=repository,
        check=False,
    ).returncode == 0
    assert subprocess.run(  # noqa: S603 - test-owned fixed Git argv.
        [  # noqa: S607 - Git is the tested release dependency.
            "git",
            "merge-base",
            "--is-ancestor",
            product,
            bridge,
        ],
        cwd=repository,
        check=False,
    ).returncode == 0
    assert _git(repository, "rev-parse", f"{bridge}^{{tree}}") == _git(
        repository,
        "rev-parse",
        f"{product}^{{tree}}",
    )


def test_archive_split_is_deterministic_and_reconstructs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prepare, "CHUNK_SIZE", 5)
    archive = tmp_path / f"datariver-poc-{'a' * 40}-linux-amd64.tar"
    archive.write_bytes(b"0123456789ABC")

    chunks = prepare.split_archive(archive, tmp_path / "parts")

    assert chunks == tuple(f"{archive.name}.part-{index:03d}" for index in range(3))
    assert b"".join((tmp_path / "parts" / name).read_bytes() for name in chunks) == (
        archive.read_bytes()
    )
