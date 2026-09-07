#!/usr/bin/env python3
"""Redeploy the fixed PREP39083 OCI artifact without rebuilding Product source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit, urlunsplit
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "deploy/prep39083/release.json"
TRANSPORT = ROOT / "deploy/prep39083/transport.json"
BASE_COMPOSE = ROOT / "deploy/poc/docker-compose.poc.yaml"
ARTIFACT_COMPOSE = ROOT / "deploy/prep39083/docker-compose.artifact.yaml"
DEV_ARTIFACT_COMPOSE = ROOT / "deploy/dev_deploy.artifact.yaml"
DEFAULT_ENV = ROOT / "deploy/prep39083/.env.prep"
DEPLOY_PROFILE = ROOT / "deploy/dev_deploy.json"
RUNTIME_ROOT = ROOT / "runtime/dev_deploy"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_PATH = RUNTIME_ROOT / "admin-password"

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
PROJECT = "datariver-dev-deploy-39081"
PORT = 39081
NETWORK = "datariver-dev-deploy-39081-services"
STATE_PORTS = {"POC_NEO4J_HTTP_PORT": "17476", "POC_POSTGRES_HOST_PORT": "15433", "POC_REDIS_PORT": "16380"}
RELEASE_PROJECT = "datariver-prep39083"
RELEASE_PORT = 39083
TREE_PATH = f"prep39083/{PRODUCT}"
CHUNKS = tuple(f"{ARCHIVE_NAME}.part-{index:03d}" for index in range(3))
CHECKSUM = f"{ARCHIVE_NAME}.sha256"
FROZEN_SQL_FILES = tuple(f"deploy/poc/postgres-init/{index:03d}-{name}.sql" for index, name in (
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
    *FROZEN_SQL_FILES,
    "deploy/prep39083/docker-compose.artifact.yaml",
    "deploy/prep39083/release.json",
    "deploy/prep39083/transport.json",
)
ALLOWED_PATHS = frozenset((
    ".gitignore",
    *FROZEN_PATHS,
    "deploy/poc/postgres-init/000-poc-vector-extension.sql",
    "deploy/dev_deploy.artifact.yaml",
    "deploy/dev_deploy.json",
    "scripts/dev_deploy",
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
        detail = (completed.stderr or completed.stdout or "").strip()
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
        and release.get("port") == RELEASE_PORT
        and release.get("project") == RELEASE_PROJECT
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


def validate_deploy_profile() -> None:
    profile = read_json(DEPLOY_PROFILE)
    require(
        profile == {
            "contract": "DATARIVER_DEV_DEPLOY_39081_V1",
            "project": PROJECT,
            "port": PORT,
            "network": NETWORK,
            "state_host_ports": {
                "neo4j": 17476,
                "postgres": 15433,
                "redis": 16380,
            },
        },
        "dev_deploy profile differs from the isolated 39081 contract",
    )


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
    validate_deploy_profile()


def docker_server_platform() -> str:
    host = output("docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}")
    require(host in {"linux/amd64", "linux/x86_64", "linux/arm64", "linux/aarch64"}, f"Docker server must be Linux, got {host}")
    return "linux/arm64" if host in {"linux/arm64", "linux/aarch64"} else "linux/amd64"


def validate_docker() -> None:
    docker_server_platform()


def secure_env(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise DeployError("PREP environment file is absent") from error
    require(stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode), "PREP environment must be a regular file")
    require(stat.S_IMODE(metadata.st_mode) & 0o077 == 0, "PREP environment permissions must be 0600 or stricter")
    return path.resolve()


def environment_lines_from_container(container: str) -> tuple[list[str], str | None]:
    try:
        documents = json.loads(output("docker", "inspect", container))
        document = documents[0]
        values = document["Config"]["Env"]
    except (DeployError, IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise DeployError("source container environment is unavailable") from error
    require(document.get("State", {}).get("Running") is True, "source container is not running")
    require(isinstance(values, list) and all(isinstance(value, str) and "=" in value for value in values), "source container environment is invalid")
    ca_bind = None
    for mount in document.get("Mounts", []):
        if (
            isinstance(mount, dict)
            and mount.get("Destination") == "/run/datariver/runtime-ca.pem"
            and isinstance(mount.get("Source"), str)
            and Path(mount["Source"]).is_file()
        ):
            ca_bind = mount["Source"]
    return list(values), ca_bind


def public_origin(lines: list[str]) -> str:
    value = None
    for line in lines:
        if line.startswith("POC_PUBLIC_ORIGIN="):
            value = line.split("=", 1)[1].strip().strip("'\"")
    require(value is not None, "source environment has no POC_PUBLIC_ORIGIN")
    parsed = urlsplit(value)
    require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password, "source POC_PUBLIC_ORIGIN is unsafe")
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return urlunsplit((parsed.scheme, f"{host}:{PORT}", parsed.path, parsed.query, parsed.fragment))


def derived_environment(source_file: Path, source_container: str | None, bind_host: str) -> Path:
    require(bind_host in {"127.0.0.1", "0.0.0.0"}, "bind host must be 127.0.0.1 or 0.0.0.0")
    if source_container:
        lines, ca_bind = environment_lines_from_container(source_container)
    else:
        lines = secure_env(source_file).read_text(encoding="utf-8").splitlines()
        ca_bind = None
    origin = public_origin(lines)
    overrides = {
        "COMPOSE_PROJECT_NAME": PROJECT,
        "POC_BIND_HOST": bind_host,
        "POC_PORT": str(PORT),
        "POC_SHARED_NETWORK": NETWORK,
        "POC_IMAGE_TAG": PRODUCT,
        "POC_PLATFORM": docker_server_platform(),
        "POC_WEB_PLATFORM": "linux/amd64",
        "POC_SOURCE_COMMIT": PRODUCT,
        "PREP_RELEASE_PRODUCT_SHA": PRODUCT,
        "PREP_RELEASE_EVIDENCE_SHA": EVIDENCE,
        "POC_PUBLIC_ORIGIN": origin,
        **STATE_PORTS,
    }
    if ca_bind:
        overrides["POC_RUNTIME_CA_BIND_SOURCE"] = ca_bind
    key_pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
    retained = []
    for line in lines:
        match = key_pattern.match(line)
        if match and match.group(1) in overrides:
            continue
        retained.append(line)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    target = RUNTIME_ROOT / "dev_deploy.env"
    temporary = target.with_suffix(".tmp")
    temporary.write_text("\n".join((*retained, *(f"{key}={value}" for key, value in overrides.items()))) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return target


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
        "docker", "compose", "--project-name", PROJECT, "--project-directory", str(BASE_COMPOSE.parent),
        "--env-file", str(environment), "--file", str(BASE_COMPOSE), "--file", str(ARTIFACT_COMPOSE),
        "--file", str(DEV_ARTIFACT_COMPOSE),
    ]


def existing_web_port_containers() -> tuple[str, ...]:
    rows = output("docker", "ps", "--all", "--format", "{{.ID}}\t{{.Ports}}").splitlines()
    return tuple(sorted(row for row in rows if re.search(r"(?:^|:)(39080|39083)->", row)))


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
        document.get("Id") == MANIFEST_DIGEST
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


def local_admin_password() -> Path:
    """Create the private first-install password once; never expose it in output."""
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    if ADMIN_PASSWORD_PATH.exists():
        details = ADMIN_PASSWORD_PATH.stat()
        require(stat.S_ISREG(details.st_mode) and not details.st_mode & 0o077, "local admin password file is insecure")
        require(len(ADMIN_PASSWORD_PATH.read_text(encoding="utf-8").strip()) >= 12, "local admin password file is invalid")
        return ADMIN_PASSWORD_PATH
    temporary = ADMIN_PASSWORD_PATH.with_suffix(".tmp")
    temporary.write_text(f"{secrets.token_urlsafe(36)}\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, ADMIN_PASSWORD_PATH)
    return ADMIN_PASSWORD_PATH


def reconcile_runtime_identities(prefix: list[str]) -> None:
    """Use the Product-bundled operational bootstrap; no fixture or seed data is loaded."""
    password = local_admin_password()
    run(
        *prefix,
        "run", "--rm", "--no-deps",
        "--volume", f"{password}:/run/dev-deploy-admin-password:ro",
        "web", "node", "poc-prep-bootstrap.mjs", "reconcile",
        "--admin-username", ADMIN_USERNAME,
        "--admin-password-file", "/run/dev-deploy-admin-password",
        capture=False,
    )


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
        and document.get("Image") == MANIFEST_DIGEST
        and image_labels.get("org.opencontainers.image.revision") == PRODUCT,
        "running Web does not match the fixed Compose/OCI identity",
    )
    return document


def write_receipt(web: dict[str, Any]) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    receipt = {
        "contract": "DATARIVER_DEV_DEPLOY_39081_V1",
        "accepted_at": datetime.now(UTC).isoformat(),
        "product_sha": PRODUCT,
        "evidence_sha": EVIDENCE,
        "release_snapshot": RELEASE_SNAPSHOT,
        "artifact_commit": ARTIFACT_COMMIT,
        "archive_sha256": ARCHIVE_SHA256,
        "manifest_digest": MANIFEST_DIGEST,
        "config_digest": CONFIG_DIGEST,
        "container_id": web.get("Id"),
        "admin_username": ADMIN_USERNAME,
        "runtime_identities": "RECONCILED",
        "port_39081": PORT,
        "ports_39080_39083_untouched": True,
    }
    target = RUNTIME_ROOT / "exact-redeploy-receipt.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def deploy(environment: Path) -> None:
    validate_docker()
    before_existing_ports = existing_web_port_containers()
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
    reconcile_runtime_identities(prefix)
    run(*prefix, "up", "-d", "--no-build", "--pull", "never", "--wait", "--force-recreate", "--no-deps", "web", capture=False)
    web = running_web()
    after_existing_ports = existing_web_port_containers()
    require(after_existing_ports == before_existing_ports, "39080 or 39083 changed during isolated deploy; preserve state and investigate")
    run("docker", "exec", str(web["Id"]), "node", "-e", "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))", capture=False)
    write_receipt(web)
    print(f"DEV_DEPLOY_OK Product={PRODUCT} Port={PORT} Project={PROJECT}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "artifact", "deploy"))
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--from-container", help="derive a private isolated environment from one running local Web container")
    parser.add_argument("--bind-host", default="127.0.0.1", help="127.0.0.1 (default) or 0.0.0.0")
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
        deploy(derived_environment(arguments.env_file, arguments.from_container, arguments.bind_host))
        return 0
    except DeployError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
