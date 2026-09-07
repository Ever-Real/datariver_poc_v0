#!/usr/bin/env python3
"""Redeploy the fixed PREP39083 OCI artifact without rebuilding Product source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "deploy/prep39083/release.json"
TRANSPORT = ROOT / "deploy/prep39083/transport.json"
BASE_COMPOSE = ROOT / "deploy/poc/docker-compose.poc.yaml"
ARTIFACT_COMPOSE = ROOT / "deploy/prep39083/docker-compose.artifact.yaml"
DEFAULT_ENV = ROOT / "deploy/prep39083/.env.prep"
RUNTIME_ROOT = ROOT / "runtime/prep39083"

PRODUCT = "2bd5494d6f100abc8e50a844e0d01c30b93cc698"
EVIDENCE = "4473135c3c9aa1cb44f317f1e3ae1a63de1eeacf"
RELEASE_SNAPSHOT = "5ae0e49b7943fb80e727d31cb3b1c90152fdf8ad"
ARTIFACT_HANDOFF = "751742d5f77c82e8584dfc3593036c79587340d7"
ARTIFACT_BRANCH = "prep39083-artifact-2bd5494d6f10"
ARTIFACT_COMMIT = "08d93f97a7678ae8ebe84ceb8e767516803e88e2"
ARCHIVE_NAME = f"datariver-poc-{PRODUCT}-linux-amd64.tar"
ARCHIVE_SHA256 = "728ead91be01af6bb91e3125ebd8bb0717152ef79e9b40bc43470e8a1f70d206"
ARCHIVE_SIZE = 124389376
IMAGE = f"datariver-poc:{PRODUCT}"
CONFIG_DIGEST = "sha256:45e3f943b48709aca6b19864b522fb8ec01e866ac967e3afb18d154c6a415c7d"
MANIFEST_DIGEST = "sha256:4a88ae49cbc40c01c85d2fdc7512b646ea8040c5c20246208ee394a619efe3b2"
PROJECT = "datariver-prep39083"
PORT = 39083
TREE_PATH = f"prep39083/{PRODUCT}"
CHUNKS = tuple(f"{ARCHIVE_NAME}.part-{index:03d}" for index in range(3))
CHECKSUM = f"{ARCHIVE_NAME}.sha256"
SQL_FILES = tuple(f"deploy/poc/postgres-init/{index:03d}-{name}.sql" for index, name in (
    (1, "poc-state"),
    (2, "poc-knowledge-ingestion"),
    (3, "poc-k9-managed-graphs"),
    (4, "poc-local-security-events"),
    (5, "poc-mcp-read-receipts"),
    (6, "poc-local-credential-provision-audit"),
    (7, "poc-chat-discovery"),
    (8, "poc-k9-lifecycle-v2"),
    (9, "poc-change-history-retention-gap"),
    (10, "poc-k9-source-payload-chunks"),
))
FROZEN_PATHS = (
    "deploy/poc/docker-compose.poc.yaml",
    *SQL_FILES,
    "deploy/prep39083/docker-compose.artifact.yaml",
    "deploy/prep39083/release.json",
    "deploy/prep39083/transport.json",
)
ALLOWED_PATHS = frozenset((
    ".gitignore",
    *FROZEN_PATHS,
    "scripts/prep39083",
    "scripts/prep39083_exact_redeploy.py",
))
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DeployError(RuntimeError):
    pass


def run(*arguments: str, cwd: Path = ROOT, capture: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(arguments), cwd=cwd, text=True, capture_output=capture, check=False
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise DeployError(f"command failed: {' '.join(arguments[:3])}{': ' + detail if detail else ''}")
    return completed


def output(*arguments: str, cwd: Path = ROOT) -> str:
    return run(*arguments, cwd=cwd).stdout.strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeployError(message)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeployError(f"cannot read tracked contract: {path.relative_to(ROOT)}") from error
    require(isinstance(value, dict), f"invalid tracked contract: {path.relative_to(ROOT)}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_release_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    release = read_json(RELEASE)
    transport = read_json(TRANSPORT)
    artifact = release.get("web_artifact")
    require(
        release.get("contract") == "DATARIVER_PREP39083_RELEASE_V3"
        and release.get("product_sha") == PRODUCT
        and release.get("evidence_sha") == EVIDENCE
        and release.get("handoff_commit_policy") == "CURRENT_COMMITTED_HEAD"
        and release.get("platform") == "linux/amd64"
        and release.get("port") == PORT
        and release.get("project") == PROJECT
        and isinstance(artifact, dict),
        "release.json does not equal the fixed successful release contract",
    )
    require(
        artifact == {
            "archive_sha256": ARCHIVE_SHA256,
            "artifact_id": f"datariver-poc-{PRODUCT}-linux-amd64",
            "config_digest": CONFIG_DIGEST,
            "contract": "DATARIVER_PREP39083_WEB_ARTIFACT_V1",
            "image_reference": IMAGE,
            "manifest_digest": MANIFEST_DIGEST,
            "oci_revision": PRODUCT,
            "path": f"runtime/prep39083/artifacts/{ARCHIVE_NAME}",
            "platform": "linux/amd64",
            "transport": "APPROVED_DOCKER_ARCHIVE",
        },
        "release.json web artifact differs from the fixed successful OCI artifact",
    )
    require(
        transport == {
            "contract": "DATARIVER_PREP39083_GIT_ARTIFACT_TRANSPORT_V2",
            "product_sha": PRODUCT,
            "evidence_sha": EVIDENCE,
            "handoff_sha": ARTIFACT_HANDOFF,
            "artifact_branch": ARTIFACT_BRANCH,
            "artifact_commit": ARTIFACT_COMMIT,
            "tree_path": TREE_PATH,
            "archive_filename": ARCHIVE_NAME,
            "archive_size": ARCHIVE_SIZE,
            "archive_sha256": ARCHIVE_SHA256,
            "checksum_filename": CHECKSUM,
            "chunk_size": 50331648,
            "chunk_count": len(CHUNKS),
            "ordered_chunks": list(CHUNKS),
        },
        "transport.json differs from the fixed successful Git artifact transport",
    )
    return release, transport


def validate_checkout() -> None:
    require(Path(output("git", "rev-parse", "--show-toplevel")).resolve() == ROOT, "unexpected Git root")
    require(not output("git", "status", "--porcelain", "--untracked-files=all"), "worktree must be clean")
    current_paths = frozenset(output("git", "ls-files").splitlines())
    require(current_paths == ALLOWED_PATHS, "checkout contains a file outside the minimal runtime allowlist")
    for commit, label in ((RELEASE_SNAPSHOT, "release snapshot"), (ARTIFACT_HANDOFF, "artifact handoff")):
        require(SHA40.fullmatch(commit) is not None, f"invalid {label} constant")
        relation = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT, check=False
        )
        require(relation.returncode == 0, f"fixed {label} is not an ancestor of this checkout")
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", RELEASE_SNAPSHOT, "HEAD", "--", *FROZEN_PATHS], cwd=ROOT, check=False
    )
    require(unchanged.returncode == 0, "one or more frozen deploy inputs differ from the release snapshot")
    validate_release_contract()


def validate_linux_amd64_docker() -> None:
    host = output("docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}")
    require(host in {"linux/amd64", "linux/x86_64"}, f"target Docker server must be linux/amd64, got {host}")
    require(platform.system() == "Linux", "run this bundle on the PREP Linux host, not Docker Desktop")


def secure_env(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise DeployError("PREP environment file is absent") from error
    require(stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode), "PREP environment must be a regular file")
    require(stat.S_IMODE(metadata.st_mode) & 0o077 == 0, "PREP environment permissions must be 0600 or stricter")
    return path.resolve()


def archive_path() -> Path:
    return RUNTIME_ROOT / "artifacts" / ARCHIVE_NAME


def verify_existing_archive(path: Path) -> bool:
    return path.is_file() and path.stat().st_size == ARCHIVE_SIZE and sha256_file(path) == ARCHIVE_SHA256


def extract_artifact() -> Path:
    destination = archive_path()
    if verify_existing_archive(destination):
        return destination
    if destination.exists():
        destination.unlink()
    run("git", "fetch", "--no-tags", "origin", ARTIFACT_BRANCH)
    require(output("git", "rev-parse", "FETCH_HEAD") == ARTIFACT_COMMIT, "artifact branch does not equal the pinned artifact commit")
    temporary_root = destination.parent
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".artifact-", dir=temporary_root) as temporary_name:
        temporary = Path(temporary_name)
        archive = temporary / "artifact-branch.tar"
        run(
            "git", "archive", "--format=tar", f"--output={archive}", ARTIFACT_COMMIT, TREE_PATH,
        )
        with tarfile.open(archive, "r") as bundle:
            expected = {f"{TREE_PATH}/{name}" for name in (*CHUNKS, CHECKSUM, "transfer-manifest.json")}
            actual = {member.name for member in bundle.getmembers() if member.isfile()}
            require(actual == expected, "artifact branch inventory is not the fixed transport inventory")
            contents: dict[str, bytes] = {}
            for name in (*CHUNKS, CHECKSUM, "transfer-manifest.json"):
                member = bundle.getmember(f"{TREE_PATH}/{name}")
                source = bundle.extractfile(member)
                require(source is not None, "artifact branch file is unreadable")
                contents[name] = source.read()
        try:
            transfer = json.loads(contents["transfer-manifest.json"])
        except json.JSONDecodeError as error:
            raise DeployError("artifact transfer manifest is invalid") from error
        require(
            transfer == {
                "contract": "DATARIVER_PREP39083_GIT_ARTIFACT_TRANSPORT_V1",
                "purpose": "TRANSPORT_ONLY_NOT_PRODUCT_SOURCE",
                "product_sha": PRODUCT,
                "handoff_sha": ARTIFACT_HANDOFF,
                "original_filename": ARCHIVE_NAME,
                "original_size": ARCHIVE_SIZE,
                "original_sha256": ARCHIVE_SHA256,
                "chunk_size": 50331648,
                "chunk_count": len(CHUNKS),
                "chunks": list(CHUNKS),
            },
            "artifact transfer manifest differs from the fixed release",
        )
        require(contents[CHECKSUM].decode("ascii").strip() == f"{ARCHIVE_SHA256}  {ARCHIVE_NAME}", "artifact checksum sidecar differs")
        reconstructed = temporary / ARCHIVE_NAME
        with reconstructed.open("wb") as target:
            for name in CHUNKS:
                target.write(contents[name])
            target.flush()
            os.fsync(target.fileno())
        require(verify_existing_archive(reconstructed), "reconstructed artifact SHA-256 or size differs")
        os.replace(reconstructed, destination)
    return destination


def compose_prefix(environment: Path) -> list[str]:
    return [
        "docker", "compose", "--project-name", PROJECT, "--project-directory", str(ROOT),
        "--env-file", str(environment), "--file", str(BASE_COMPOSE), "--file", str(ARTIFACT_COMPOSE),
    ]


def port_39080_containers() -> tuple[str, ...]:
    rows = output("docker", "ps", "--all", "--format", "{{.ID}}\t{{.Ports}}").splitlines()
    return tuple(sorted(row.split("\t", 1)[0] for row in rows if re.search(r"(?:^|:)39080->", row)))


def compose_config(prefix: list[str]) -> dict[str, Any]:
    value = json.loads(output(*prefix, "config", "--format", "json"))
    require(isinstance(value, dict), "Compose did not render one configuration object")
    web = value.get("services", {}).get("web") if isinstance(value.get("services"), dict) else None
    require(isinstance(web, dict) and web.get("image") == IMAGE and "build" not in web, "Compose web must use only the fixed OCI image")
    return value


def project_containers() -> dict[str, list[dict[str, Any]]]:
    raw = output(
        "docker", "ps", "--all", "--filter", f"label=com.docker.compose.project={PROJECT}", "--format", "{{.ID}}"
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for container_id in filter(None, raw.splitlines()):
        document = json.loads(output("docker", "inspect", container_id))[0]
        labels = document.get("Config", {}).get("Labels", {}) or {}
        service = labels.get("com.docker.compose.service")
        require(service in {"web", "neo4j", "pgvector", "redis"}, "PREP project has an unexpected Compose service")
        result.setdefault(service, []).append(document)
    return result


def verify_loaded_image() -> None:
    document = json.loads(output("docker", "image", "inspect", IMAGE))[0]
    labels = document.get("Config", {}).get("Labels", {}) or {}
    require(
        document.get("Id") == CONFIG_DIGEST
        and document.get("Os") == "linux"
        and document.get("Architecture") in {"amd64", "x86_64"}
        and labels.get("org.opencontainers.image.revision") == PRODUCT,
        "loaded image does not match the fixed OCI config/revision identity",
    )


def start_state_services(prefix: list[str], existing: dict[str, list[dict[str, Any]]]) -> None:
    state = ("pgvector", "neo4j", "redis")
    if existing:
        require(all(len(existing.get(service, [])) == 1 for service in state), "existing PREP state services are incomplete; preserve and inspect them")
        run(*prefix, "up", "-d", "--no-build", "--pull", "never", "--no-recreate", "--wait", *state, capture=False)
        return
    run(*prefix, "up", "-d", "--no-build", "--pull", "never", "--wait", *state, capture=False)


def running_web() -> dict[str, Any]:
    rows = output(
        "docker", "ps", "--all", "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", "label=com.docker.compose.service=web", "--format", "{{.ID}}",
    ).splitlines()
    require(len(rows) == 1, "PREP project must own exactly one Web container")
    document = json.loads(output("docker", "inspect", rows[0]))[0]
    labels = document.get("Config", {}).get("Labels", {}) or {}
    image = json.loads(output("docker", "image", "inspect", document["Image"]))[0]
    image_labels = image.get("Config", {}).get("Labels", {}) or {}
    health = document.get("State", {}).get("Health", {}).get("Status")
    require(
        document.get("State", {}).get("Running") is True
        and health == "healthy"
        and labels.get("com.docker.compose.project") == PROJECT
        and labels.get("com.docker.compose.service") == "web"
        and document.get("Config", {}).get("Image") == IMAGE
        and document.get("Image") == CONFIG_DIGEST
        and image_labels.get("org.opencontainers.image.revision") == PRODUCT,
        "running Web does not match the fixed Compose/OCI identity",
    )
    return document


def write_receipt(web: dict[str, Any]) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    receipt = {
        "contract": "DATARIVER_PREP39083_EXACT_REDEPLOY_V1",
        "accepted_at": datetime.now(UTC).isoformat(),
        "product_sha": PRODUCT,
        "evidence_sha": EVIDENCE,
        "release_snapshot": RELEASE_SNAPSHOT,
        "artifact_commit": ARTIFACT_COMMIT,
        "archive_sha256": ARCHIVE_SHA256,
        "manifest_digest": MANIFEST_DIGEST,
        "config_digest": CONFIG_DIGEST,
        "container_id": web.get("Id"),
        "port_39083": PORT,
        "port_39080_untouched": True,
    }
    target = RUNTIME_ROOT / "exact-redeploy-receipt.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def deploy(environment: Path) -> None:
    validate_linux_amd64_docker()
    before_39080 = port_39080_containers()
    archive = extract_artifact()
    require(verify_existing_archive(archive), "local artifact identity changed before image load")
    run("docker", "load", "--input", str(archive), capture=False)
    verify_loaded_image()
    prefix = compose_prefix(environment)
    compose_config(prefix)
    existing = project_containers()
    if existing.get("web"):
        old = existing["web"]
        require(len(old) == 1 and old[0].get("Config", {}).get("Image") == IMAGE, "existing Web is not the fixed Product; preserve it")
    start_state_services(prefix, existing)
    run(*prefix, "up", "-d", "--no-build", "--pull", "never", "--wait", "--force-recreate", "--no-deps", "web", capture=False)
    web = running_web()
    after_39080 = port_39080_containers()
    require(after_39080 == before_39080, "39080 changed during PREP deploy; preserve state and investigate")
    run("docker", "exec", str(web["Id"]), "node", "-e", "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))", capture=False)
    write_receipt(web)
    print(f"EXACT_REDEPLOY_OK Product={PRODUCT} Port={PORT} Project={PROJECT}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "artifact", "deploy"))
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true", help="required for Docker mutation with deploy")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        validate_checkout()
        if arguments.command == "check":
            print(f"CHECK_OK Product={PRODUCT} Files={len(ALLOWED_PATHS)}")
            return 0
        if arguments.command == "artifact":
            archive = extract_artifact()
            print(f"ARTIFACT_OK {archive} SHA256={ARCHIVE_SHA256}")
            return 0
        require(arguments.apply, "deploy requires --apply")
        deploy(secure_env(arguments.env_file))
        return 0
    except DeployError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
