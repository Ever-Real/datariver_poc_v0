from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/cleanup_knowledge_studio_test_artifacts.py"
WORKSPACE_ID = "019fa57b-52de-74c0-9f5e-06ae7b1bf3b1"
DRAFT_ID = "019fa57b-52de-74c0-9f5e-06ae7b1bf3b2"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository script with test-owned argv.
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_cleanup_defaults_to_dry_run_and_requires_exact_apply_confirmation(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "KNOWLEDGE_STUDIO_TEST_CLEANUP_V1",
                "workspace_id": WORKSPACE_ID,
                "drafts": [{"draft_id": DRAFT_ID, "expected_version": 7}],
                "files": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    dry_run = _run(
        "--manifest",
        str(manifest),
        "--test-artifact-root",
        str(ROOT),
    )
    assert dry_run.returncode == 0
    assert "No state changed" in dry_run.stdout
    assert f'draft={DRAFT_ID} expected_etag="7"' in dry_run.stdout

    refused = _run(
        "--manifest",
        str(manifest),
        "--test-artifact-root",
        str(ROOT),
        "--apply",
        "--confirm-manifest-sha256",
        "0" * 64,
    )
    assert refused.returncode == 2
    assert "confirmation does not match" in refused.stderr


def test_cleanup_unlinks_only_an_exact_untracked_regular_file() -> None:
    with tempfile.TemporaryDirectory(prefix=".ks-cleanup-", dir=ROOT) as directory:
        artifact_root = Path(directory)
        artifact = artifact_root / "dummy-preview.csv"
        artifact.write_text("employee_id,name\n7,Kim\n", encoding="utf-8")
        artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        manifest = artifact_root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "contract_version": "KNOWLEDGE_STUDIO_TEST_CLEANUP_V1",
                    "workspace_id": WORKSPACE_ID,
                    "drafts": [],
                    "files": [{"path": str(artifact), "sha256": artifact_hash}],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()

        applied = _run(
            "--manifest",
            str(manifest),
            "--test-artifact-root",
            str(artifact_root),
            "--apply",
            "--confirm-manifest-sha256",
            manifest_hash,
        )

        assert applied.returncode == 0, applied.stderr
        assert "1 file(s) unlinked" in applied.stdout
        assert not artifact.exists()
        assert manifest.exists()
