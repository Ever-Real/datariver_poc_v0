#!/usr/bin/env python3
"""Discard exact Knowledge Studio test Drafts and unlink exact test artifacts.

The default mode is read-only. Apply mode requires the manifest SHA-256 as a
second, explicit confirmation and never issues recursive deletion or SQL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "KNOWLEDGE_STUDIO_TEST_CLEANUP_V1"
MAX_TARGETS = 100


class CleanupError(RuntimeError):
    """A fail-closed cleanup contract violation."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


@dataclass(frozen=True, slots=True)
class DraftTarget:
    draft_id: UUID
    expected_version: int


@dataclass(frozen=True, slots=True)
class FileTarget:
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class CleanupManifest:
    workspace_id: UUID
    drafts: tuple[DraftTarget, ...]
    files: tuple[FileTarget, ...]


def _required_mapping(value: object, *, location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CleanupError(f"{location} must be a JSON object.")
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str], *, location: str) -> None:
    if frozenset(value) != expected:
        raise CleanupError(f"{location} has unknown or missing fields.")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_untracked_file(
    *,
    raw_path: str,
    expected_sha256: str,
    artifact_root: Path,
    repository_root: Path,
) -> FileTarget:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise CleanupError("Cleanup file paths must be absolute.")
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError as error:
        raise CleanupError(f"Cleanup file does not exist: {candidate}") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise CleanupError(f"Cleanup target is not a regular non-symlink file: {candidate}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(artifact_root)
    except ValueError as error:
        raise CleanupError("Cleanup file escapes the explicit test artifact root.") from error
    try:
        repository_relative = resolved.relative_to(repository_root)
    except ValueError as error:
        raise CleanupError("Cleanup files must remain inside the repository.") from error
    git_path = shutil.which("git")
    if git_path is None:
        raise CleanupError("Git is required to prove that cleanup files are untracked.")
    tracked = subprocess.run(  # noqa: S603 - fixed git argv without shell interpolation.
        [
            git_path,
            "-C",
            str(repository_root),
            "ls-files",
            "--error-unmatch",
            "--",
            str(repository_relative),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if tracked.returncode == 0:
        raise CleanupError(f"Refusing to unlink a Git-tracked file: {resolved}")
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise CleanupError("Cleanup file SHA-256 must be lowercase hexadecimal.")
    observed_sha256 = _sha256_file(resolved)
    if observed_sha256 != expected_sha256:
        raise CleanupError(f"Cleanup file hash changed: {resolved}")
    return FileTarget(path=resolved, sha256=expected_sha256)


def load_manifest(
    *,
    manifest_path: Path,
    artifact_root: Path,
    repository_root: Path = ROOT,
) -> tuple[CleanupManifest, str]:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CleanupError("The cleanup manifest must be a regular non-symlink file.")
    raw = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        document = _required_mapping(json.loads(raw), location="manifest")
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CleanupError("The cleanup manifest is not valid UTF-8 JSON.") from error
    _exact_keys(
        document,
        frozenset({"contract_version", "workspace_id", "drafts", "files"}),
        location="manifest",
    )
    if document["contract_version"] != CONTRACT_VERSION:
        raise CleanupError("The cleanup manifest contract version is unsupported.")
    try:
        workspace_id = UUID(str(document["workspace_id"]))
    except ValueError as error:
        raise CleanupError("The cleanup workspace ID is invalid.") from error
    raw_drafts = document["drafts"]
    raw_files = document["files"]
    if not isinstance(raw_drafts, list) or not isinstance(raw_files, list):
        raise CleanupError("Cleanup drafts and files must be arrays.")
    if len(raw_drafts) > MAX_TARGETS or len(raw_files) > MAX_TARGETS:
        raise CleanupError("The cleanup manifest exceeds the target bound.")

    drafts: list[DraftTarget] = []
    seen_drafts: set[UUID] = set()
    for index, raw_draft in enumerate(raw_drafts):
        draft = _required_mapping(raw_draft, location=f"drafts[{index}]")
        _exact_keys(
            draft,
            frozenset({"draft_id", "expected_version"}),
            location=f"drafts[{index}]",
        )
        try:
            draft_id = UUID(str(draft["draft_id"]))
        except ValueError as error:
            raise CleanupError(f"drafts[{index}].draft_id is invalid.") from error
        expected_version = draft["expected_version"]
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 1
        ):
            raise CleanupError(f"drafts[{index}].expected_version is invalid.")
        if draft_id in seen_drafts:
            raise CleanupError("The cleanup manifest repeats a Draft target.")
        seen_drafts.add(draft_id)
        drafts.append(DraftTarget(draft_id=draft_id, expected_version=expected_version))

    resolved_root = artifact_root.resolve(strict=True)
    resolved_repository = repository_root.resolve(strict=True)
    try:
        resolved_root.relative_to(resolved_repository)
    except ValueError as error:
        raise CleanupError("The test artifact root must be inside the repository.") from error
    files: list[FileTarget] = []
    seen_files: set[Path] = set()
    for index, raw_file in enumerate(raw_files):
        file_document = _required_mapping(raw_file, location=f"files[{index}]")
        _exact_keys(
            file_document,
            frozenset({"path", "sha256"}),
            location=f"files[{index}]",
        )
        if not isinstance(file_document["path"], str):
            raise CleanupError(f"files[{index}].path is invalid.")
        target = _require_untracked_file(
            raw_path=file_document["path"],
            expected_sha256=str(file_document["sha256"]),
            artifact_root=resolved_root,
            repository_root=resolved_repository,
        )
        if target.path in seen_files:
            raise CleanupError("The cleanup manifest repeats a file target.")
        seen_files.add(target.path)
        files.append(target)
    if not drafts and not files:
        raise CleanupError("The cleanup manifest has no exact targets.")
    return (
        CleanupManifest(
            workspace_id=workspace_id,
            drafts=tuple(drafts),
            files=tuple(files),
        ),
        manifest_sha256,
    )


def _validated_api_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise CleanupError("The cleanup API base URL contains forbidden components.")
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if parsed.scheme != "https" and not local_http:
        raise CleanupError("The cleanup API requires HTTPS or loopback HTTP.")
    return value.rstrip("/")


def _read_token(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CleanupError("The access token file must be a regular non-symlink file.")
    if path.stat().st_mode & 0o077:
        raise CleanupError("The access token file must not be group/world accessible.")
    token = path.read_text(encoding="utf-8").strip()
    if not token or "\n" in token or "\r" in token:
        raise CleanupError("The access token file is invalid.")
    return token


def discard_drafts(
    *,
    manifest: CleanupManifest,
    manifest_sha256: str,
    api_base_url: str,
    token: str,
) -> None:
    base = _validated_api_base_url(api_base_url)
    opener = urllib.request.build_opener(_NoRedirectHandler())
    for target in manifest.drafts:
        request = urllib.request.Request(  # noqa: S310 - URL was restricted above.
            (f"{base}/knowledge/studio/drafts/{target.draft_id}/discard"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Cache-Control": "no-store",
                "Content-Type": "application/json",
                "Idempotency-Key": (f"ks-cleanup-{manifest_sha256[:24]}-{target.draft_id}"),
                "If-Match": f'"{target.expected_version}"',
                "X-Workspace-Id": str(manifest.workspace_id),
            },
        )
        try:
            with opener.open(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read(4096).decode("utf-8", errors="replace")
            raise CleanupError(f"Draft discard failed with HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise CleanupError("Draft discard endpoint is unavailable.") from error
        if (
            not isinstance(payload, dict)
            or payload.get("id") != str(target.draft_id)
            or payload.get("state") != "DISCARDED"
        ):
            raise CleanupError("Draft discard returned an invalid lifecycle receipt.")


def unlink_files(files: tuple[FileTarget, ...]) -> None:
    for target in files:
        if target.path.is_symlink() or not target.path.is_file():
            raise CleanupError(f"Cleanup file changed before unlink: {target.path}")
        if _sha256_file(target.path) != target.sha256:
            raise CleanupError(f"Cleanup file hash changed before unlink: {target.path}")
    for target in files:
        target.path.unlink()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--test-artifact-root", type=Path, required=True)
    parser.add_argument("--api-base-url")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-manifest-sha256")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    manifest, manifest_sha256 = load_manifest(
        manifest_path=arguments.manifest.resolve(strict=True),
        artifact_root=arguments.test_artifact_root,
    )
    print(f"manifest_sha256={manifest_sha256}")
    print(f"workspace_id={manifest.workspace_id}")
    for draft in manifest.drafts:
        print(f'DRY-RUN draft={draft.draft_id} expected_etag="{draft.expected_version}"')
    for file in manifest.files:
        print(f"DRY-RUN file={file.path} sha256={file.sha256}")
    if not arguments.apply:
        print("No state changed. Re-run with --apply and the exact manifest hash.")
        return 0
    if arguments.confirm_manifest_sha256 != manifest_sha256:
        raise CleanupError("Apply confirmation does not match the manifest SHA-256.")
    if not arguments.api_base_url and manifest.drafts:
        raise CleanupError("--api-base-url is required when Draft targets exist.")
    if not arguments.token_file and manifest.drafts:
        raise CleanupError("--token-file is required when Draft targets exist.")
    if manifest.drafts:
        discard_drafts(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            api_base_url=arguments.api_base_url,
            token=_read_token(arguments.token_file),
        )
    unlink_files(manifest.files)
    print(
        f"Applied cleanup: {len(manifest.drafts)} Draft(s) discarded, "
        f"{len(manifest.files)} file(s) unlinked."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CleanupError, OSError, subprocess.SubprocessError) as error:
        print(f"cleanup failed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
