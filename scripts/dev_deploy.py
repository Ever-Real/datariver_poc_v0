#!/usr/bin/env python3
"""Build and deploy the single-branch DataRiver PREP source package."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from build_progress import run_build


ROOT = Path(__file__).resolve().parents[1]
BASE_PRODUCT = "2bd5494d6f100abc8e50a844e0d01c30b93cc698"
BRANCH = "dev_deploy"
BASE_COMPOSE = ROOT / "deploy/compose.yaml"
ENV_CONTRACT = ROOT / "deploy/env-contract.json"
DEFAULT_ENV = ROOT / "deploy/.env.prep"
BUILD_DEPENDENCIES = ROOT / "deploy/build-dependencies.json"
SMOKE_TOOL = ROOT / "scripts/smoke_prep39083.mjs"
ACCEPT_TOOL = ROOT / "scripts/accept_dev_deploy.mjs"
RUNTIME_ROOT = ROOT / "runtime/dev_deploy"
KNOWN_GOOD_IMAGE = f"datariver-poc:{BASE_PRODUCT}"
ADMIN_USERNAME = "admin"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SOURCE_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HASH64 = re.compile(r"^[0-9a-f]{64}$")


class DeployError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    name: str
    project: str
    port: int
    network: str
    state_ports: Mapping[str, str]
    kafka_client: str
    kafka_group: str
    bind_host: str
    validation_only: bool


VALIDATION_39081 = Target(
        name="validation39081",
        project="datariver-dev-deploy-39081",
        port=39081,
        network="datariver-dev-deploy-39081-services",
        state_ports={
            "POC_POSTGRES_HOST_PORT": "15433",
            "POC_REDIS_PORT": "16380",
            "POC_NEO4J_HTTP_PORT": "17476",
        },
        kafka_client="datariver-dev-deploy-39081-mcl-v1",
        kafka_group="datariver-dev-deploy-39081-mcl-capture-v1",
        bind_host="127.0.0.1",
        validation_only=True,
    )
PREP_39083 = Target(
        name="prep39083",
        project="datariver-prep39083",
        port=39083,
        network="datariver-prep39083-services",
        state_ports={
            "POC_POSTGRES_HOST_PORT": "25432",
            "POC_REDIS_PORT": "26379",
            "POC_NEO4J_HTTP_PORT": "27475",
        },
        kafka_client="datariver-prep39083-mcl-v1",
        kafka_group="datariver-prep39083-mcl-capture-v1",
        bind_host="0.0.0.0",
        validation_only=False,
    )
DEV_39091 = Target(
        name="dev",
        project="datariver-dev",
        port=39091,
        network="datariver-dev-services",
        state_ports={
            "POC_POSTGRES_HOST_PORT": "35432",
            "POC_REDIS_PORT": "36379",
            "POC_NEO4J_HTTP_PORT": "37475",
        },
        kafka_client="datariver-dev-mcl-v1",
        kafka_group="datariver-dev-mcl-capture-v1",
        bind_host="0.0.0.0",
        validation_only=True,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DeployError(message)


def run(
    arguments: Sequence[str], *, cwd: Path = ROOT,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if environment is None and list(arguments[:2]) == ["docker", "compose"]:
        environment = subprocess_environment({})
    completed = subprocess.run(
        list(arguments), cwd=cwd, env=None if environment is None else dict(environment),
        text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        raise DeployError(f"COMMAND_FAILED:{Path(arguments[0]).name}:{arguments[-1]}")
    return completed


def output(*arguments: str, cwd: Path = ROOT) -> str:
    return run(arguments, cwd=cwd).stdout.strip()


def run_logged(arguments: Sequence[str], path: Path, *, cwd: Path = ROOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(list(arguments), cwd=cwd, text=True, stdout=log, stderr=subprocess.STDOUT, check=False)
    if completed.returncode:
        raise DeployError(f"COMMAND_FAILED:{Path(arguments[0]).name}:{arguments[-1]}:see_runtime_log")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeployError(f"TRACKED_JSON_INVALID:{path.name}") from error
    require(isinstance(value, dict), f"TRACKED_JSON_INVALID:{path.name}")
    return value


def atomic_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
    os.replace(temporary, path)


def atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_private_text(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def source_paths() -> list[Path]:
    # Private/generated inputs never enter the Docker context. No Git index,
    # history, remote, external manifest, or application image is consulted.
    excluded = {".git", ".DS_Store", ".npmrc", ".yarnrc", "node_modules", "dist",
                "dist-poc", "coverage", "__pycache__", ".pytest_cache", ".idea", ".vscode"}
    paths: list[Path] = []
    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            name = path.name
            if (name in excluded or name.startswith(".env")
                    or path.suffix.lower() in {".pem", ".key", ".crt", ".p12", ".pfx", ".tsbuildinfo", ".pyc"}
                    or (path.parent == ROOT and name in {"runtime", "README.md"})):
                continue
            metadata = path.lstat()
            require(not stat.S_ISLNK(metadata.st_mode), "SOURCE_SYMLINK_NOT_SUPPORTED:" + str(path.relative_to(ROOT)))
            if stat.S_ISDIR(metadata.st_mode):
                visit(path)
            else:
                require(stat.S_ISREG(metadata.st_mode), "SOURCE_NOT_REGULAR:" + str(path.relative_to(ROOT)))
                paths.append(path)
    visit(ROOT)
    return sorted(paths)


def source_archive(paths: Sequence[Path] | None = None) -> bytes:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.PAX_FORMAT) as target:
        for path in source_paths() if paths is None else paths:
            # Stable across hosts/mtime/ownership. Preserve the executable bit.
            with path.open("rb") as source:
                metadata = os.fstat(source.fileno())
                require(stat.S_ISREG(metadata.st_mode), "SOURCE_NOT_REGULAR")
                info = tarfile.TarInfo(path.relative_to(ROOT).as_posix())
                info.size = metadata.st_size
                info.mode = 0o755 if metadata.st_mode & 0o111 else 0o644
                target.addfile(info, source)
    return archive.getvalue()


def build_input_hash() -> str:
    return hashlib.sha256(source_archive()).hexdigest()


def validate_source(*, clean: bool) -> tuple[str, int]:
    # `clean` is retained for internal callers; current content, not Git state,
    # is authoritative. Deploy requires the exact snapshot recorded at build.
    paths = source_paths()
    for relative in ("deploy/Dockerfile", "deploy/compose.yaml", "package.json", "package-lock.json",
                     "backend/src/bootstrap.mjs", "frontend/index.html", "frontend/vite.config.ts"):
        require((ROOT / relative).is_file(), "BUILD_INPUT_MISSING:" + relative)
    require(read_json(ROOT / "package.json").get("type") == "module", "PACKAGE_SCOPE_INVALID")
    return hashlib.sha256(source_archive(paths)).hexdigest(), len(paths)


def private_env_file(path: Path) -> tuple[Path, str]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise DeployError("PREP_ENV_NOT_AVAILABLE") from error
    require(stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode), "PREP_ENV_NOT_REGULAR")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        os.chmod(path, 0o600)
        metadata = path.lstat()
    require(stat.S_IMODE(metadata.st_mode) & 0o077 == 0, "PREP_ENV_MODE_INVALID")
    return path.resolve(), sha256_file(path)


def env_value(raw: str) -> str:
    if not raw:
        return ""
    if raw.startswith("'"):
        match = re.fullmatch(r"'((?:\\'|[^'])*)'(?:\s+#.*)?", raw)
        require(match is not None, "PREP_ENV_SYNTAX_INVALID")
        value = match.group(1).replace("\\'", "'")
    elif raw.startswith('"'):
        match = re.fullmatch(r'("(?:\\.|[^"\\])*")(?:\s+#.*)?', raw)
        require(match is not None, "PREP_ENV_SYNTAX_INVALID")
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise DeployError("PREP_ENV_SYNTAX_INVALID") from error
    else:
        value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
    require(not any(character in value for character in "\r\n\x00"), "PREP_ENV_CONTROL_CHARACTER")
    return value


def read_env(path: Path, prior: Mapping[str, str] | None = None) -> dict[str, str]:
    keys = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", raw)
        if match:
            require(match[1] not in keys, "PREP_ENV_KEY_DUPLICATED")
            keys.append(match[1])
    # config is read-only and needs no daemon. Neither values nor parser errors reach logs.
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="env-parse-", dir=RUNTIME_ROOT) as directory:
        definition = Path(directory) / "compose.json"
        definition.write_text(json.dumps({"services": {"parser": {
            "image": "unused", "environment": {key: "${" + key + "}" for key in keys},
        }}}), encoding="utf-8")
        parsed = run(["docker", "compose", "--project-name", "datariver-env-parser",
                      "--env-file", str(path.resolve()), "--file", str(definition),
                      "config", "--format", "json"], environment=subprocess_environment(prior or {}))
    # Compose serializes literal dollars as $$ so its config can be reused.
    values = {key: value.replace("$$", "$") if isinstance(value, str) else value
              for key, value in json.loads(parsed.stdout)["services"]["parser"]["environment"].items()}
    require(all(isinstance(value, str) and not any(c in value for c in "\r\n\x00")
                for value in values.values()), "PREP_ENV_VALUE_INVALID")
    return values


def operator_environment(path: Path) -> dict[str, str]:
    values = read_env(path)
    optional = path.with_name(path.name + ".optional")
    if optional.is_file():
        private_env_file(optional)
        extra = read_env(optional, values)
        require(not set(values).intersection(extra), "PREP_ENV_OWNERSHIP_CONFLICT")
        values.update(extra)
    return values


def env_preflight(path: Path) -> tuple[dict[str, str], str]:
    resolved, before = private_env_file(path)
    values = operator_environment(resolved)
    contract = read_json(ENV_CONTRACT)
    core = contract.get("ownership", {}).get("CORE_REQUIRED", [])
    require(isinstance(core, list) and all(isinstance(key, str) for key in core), "ENV_CONTRACT_INVALID")
    missing = [key for key in core if not values.get(key) or values[key].startswith("CHANGE_ME")]
    provider_required = (
        "AIRFLOW_URL", "AIRFLOW_USERNAME", "AIRFLOW_PASSWORD", "POC_AIRFLOW_SERVICE_TOKEN",
        "MINIO_URL", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY",
    )
    missing.extend(key for key in provider_required if not values.get(key) or values[key].startswith("CHANGE_ME"))
    sasl = [values.get(key, "") for key in (
        "POC_MCL_KAFKA_SASL_MECHANISM", "POC_MCL_KAFKA_SASL_USERNAME", "POC_MCL_KAFKA_SASL_PASSWORD",
    )]
    require(not any(sasl) or all(sasl), "MCL_SASL_INCOMPLETE")
    registry_auth = [values.get(key, "") for key in (
        "POC_MCL_SCHEMA_REGISTRY_USERNAME", "POC_MCL_SCHEMA_REGISTRY_PASSWORD",
    )]
    require(not any(registry_auth) or all(registry_auth), "MCL_SCHEMA_AUTH_INCOMPLETE")
    tls = values.get("POC_MCL_KAFKA_SSL", "false").lower()
    require(tls in {"true", "false"}, "MCL_TLS_INVALID")
    require(not missing, "ENV_INCOMPLETE:" + ",".join(sorted(set(missing))))
    require(sha256_file(resolved) == before, "PREP_ENV_CHANGED")
    return values, before


def replace_origin_port(value: str, port: int) -> str:
    parsed = urlsplit(value)
    require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password, "PUBLIC_ORIGIN_INVALID")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return urlunsplit((parsed.scheme, f"{host}:{port}", "", "", ""))


def deployment_environment(path: Path, profile: Target, public_origin: str | None) -> tuple[dict[str, str], str]:
    values, source_hash = env_preflight(path)
    if public_origin is not None:
        # A new host's browser origin is an explicit runtime override, never an env-file edit.
        normalized = replace_origin_port(public_origin, profile.port)
        require(public_origin.rstrip("/") == normalized, "PUBLIC_ORIGIN_TARGET_MISMATCH")
        values["POC_PUBLIC_ORIGIN"] = normalized
    return values, source_hash


def source_image(head: str) -> str:
    return f"datariver-dev-deploy-source:{head[:12]}"


def docker_platform() -> str:
    value = output("docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}")
    require(value.startswith("linux/"), "DOCKER_SERVER_NOT_LINUX")
    return "linux/amd64"


def state_kind(profile: Target) -> str:
    names = [f"{profile.project}_{name}" for name in ("pgvector-data", "neo4j-data", "neo4j-logs")]
    present = []
    for name in names:
        completed = subprocess.run(["docker", "volume", "inspect", name], capture_output=True, text=True, check=False)
        present.append(completed.returncode == 0)
    require(not any(present) or all(present), "STATE_VOLUMES_INCOMPLETE")
    return "EXISTING" if all(present) else "FRESH"


def fixed_values(profile: Target, head: str) -> dict[str, str]:
    contract = read_json(ENV_CONTRACT)
    fixed = contract.get("ownership", {}).get("FIXED")
    require(isinstance(fixed, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in fixed.items()), "ENV_FIXED_CONTRACT_INVALID")
    result = dict(fixed)
    result.update({
        "COMPOSE_PROJECT_NAME": profile.project,
        "POC_BIND_HOST": profile.bind_host,
        "POC_PORT": str(profile.port),
        "POC_SHARED_NETWORK": profile.network,
        "POC_PLATFORM": docker_platform(),
        "POC_WEB_PLATFORM": "linux/amd64",
        "POC_SOURCE_COMMIT": head,
        "POC_IMAGE_TAG": head[:12],
        "DEV_DEPLOY_SOURCE_IMAGE": source_image(head),
        "POC_MCL_KAFKA_CLIENT_ID": profile.kafka_client,
        "POC_MCL_KAFKA_GROUP_ID": profile.kafka_group,
        **profile.state_ports,
    })
    return result


def compose_quote(value: str) -> str:
    require(not any(character in value for character in "\r\n\x00"), "DERIVED_ENV_VALUE_INVALID")
    return "'" + value.replace("'", "\\'") + "'"


def deployment_kafka_values(profile: Target, generated: Mapping[str, Any]) -> dict[str, str]:
    suffix = ""
    if profile == DEV_39091:
        installation = generated.get("installation_id", "")
        require(isinstance(installation, str) and re.fullmatch(r"[0-9a-f]{16}", installation) is not None,
                "DEPLOYMENT_IDENTITY_REQUIRED")
        suffix = "-" + installation
    return {
        "POC_MCL_KAFKA_CLIENT_ID": profile.kafka_client + suffix,
        "POC_MCL_KAFKA_GROUP_ID": profile.kafka_group + suffix,
    }


def write_derived_environment(
    source: Mapping[str, str], profile: Target, head: str, *, state: str, image: str | None = None,
    discovered: Mapping[str, str] | None = None,
    preserved_runtime: Mapping[str, str] | None = None,
) -> tuple[Path, dict[str, str]]:
    values = dict(source)
    if preserved_runtime:
        for key in read_json(ENV_CONTRACT)["ownership"]["GENERATED"]:
            if preserved_runtime.get(key):
                require(not values.get(key) or values[key] == preserved_runtime[key], "PREP_GENERATED_VALUE_DRIFT")
                values[key] = preserved_runtime[key]
    values.update(fixed_values(profile, head))
    if image is not None:
        values["DEV_DEPLOY_SOURCE_IMAGE"] = image
    if profile.validation_only:
        values["POC_PUBLIC_ORIGIN"] = replace_origin_port(source["POC_PUBLIC_ORIGIN"], profile.port)
    generated = read_json(RUNTIME_ROOT / profile.name / "generated.json") if (RUNTIME_ROOT / profile.name / "generated.json").exists() else {}
    generated_keys = read_json(ENV_CONTRACT).get("ownership", {}).get("GENERATED", {})
    require(isinstance(generated_keys, dict), "ENV_GENERATED_CONTRACT_INVALID")
    for key, length in generated_keys.items():
        if profile == DEV_39091:
            # New project credentials belong to its own state, even if the operator
            # copied the old PREP env and its runtime credential sidecar unchanged.
            values.pop(key, None)
        if values.get(key):
            continue
        existing = generated.get(key)
        if isinstance(existing, str) and len(existing) >= 16:
            values[key] = existing
        elif state == "FRESH":
            values[key] = secrets.token_urlsafe(max(24, int(length)))
            generated[key] = values[key]
        else:
            raise DeployError("EXISTING_STATE_CREDENTIALS_REQUIRED")
    if profile == DEV_39091 and state == "FRESH" and "installation_id" not in generated:
        generated["installation_id"] = secrets.token_hex(8)
    values.update(deployment_kafka_values(profile, generated))
    if state == "FRESH":
        atomic_private_json(RUNTIME_ROOT / profile.name / "generated.json", generated)
    if discovered:
        values.update(discovered)
    contract = read_json(ENV_CONTRACT)
    def merged(*items: str) -> str:
        return ",".join(dict.fromkeys(part.strip() for item in items for part in item.split(",") if part.strip()))
    values["NO_PROXY"] = merged(values.get("NO_PROXY", ""), values.get("EXTERNAL_SERVICE_NO_PROXY", ""),
                                ",".join(contract.get("required_no_proxy", [])))
    values["no_proxy"] = values["NO_PROXY"]
    for name in ("HTTP_PROXY", "HTTPS_PROXY"):
        values[name.lower()] = values.get(name, "")
    values["POC_RUNTIME_NO_PROXY"] = (merged(values.get("POC_RUNTIME_NO_PROXY", ""),
        ",".join(contract.get("required_runtime_no_proxy", [])))
        if values.get("POC_RUNTIME_HTTP_PROXY") or values.get("POC_RUNTIME_HTTPS_PROXY") else "")
    source_ca = values.get("RUNTIME_CA_CERT_FILE", "").strip()
    if source_ca:
        ca_path = Path(source_ca)
        require(ca_path.is_absolute() and ca_path.is_file(), "RUNTIME_CA_INVALID")
        values["POC_RUNTIME_CA_BIND_SOURCE"] = str(ca_path)
        values["POC_RUNTIME_CA_CONTAINER_FILE"] = "/run/datariver/runtime-ca.pem"
    target = RUNTIME_ROOT / profile.name / "derived.env"
    contents = "\n".join(f"{key}={compose_quote(value)}" for key, value in sorted(values.items())) + "\n"
    atomic_private_text(target, contents)
    return target, values


def protected_state(*, ignore_project: str | None = None) -> dict[str, Any]:
    rows = output("docker", "ps", "--all", "--format", "{{.ID}}").splitlines()
    containers: list[dict[str, Any]] = []
    for container_id in rows:
        document = json.loads(output("docker", "inspect", container_id))[0]
        labels = document.get("Config", {}).get("Labels", {}) or {}
        project = labels.get("com.docker.compose.project", "")
        if ignore_project and project == ignore_project:
            continue
        ports = document.get("NetworkSettings", {}).get("Ports", {}) or {}
        published = {
            int(binding.get("HostPort"))
            for bindings in ports.values() if isinstance(bindings, list)
            for binding in bindings if isinstance(binding, dict) and str(binding.get("HostPort", "")).isdigit()
        }
        if project not in {"datariver-prep39083", "datariver-poc"} and not published.intersection({39080, 39083}):
            continue
        containers.append({
            "id": document.get("Id"), "image_id": document.get("Image"), "project": project,
            "service": labels.get("com.docker.compose.service", ""),
            "running": document.get("State", {}).get("Running") is True,
            "volumes": sorted(
                mount.get("Name") or mount.get("Source") for mount in document.get("Mounts", [])
                if isinstance(mount, dict) and (mount.get("Name") or mount.get("Source"))
            ),
        })
    image = subprocess.run(["docker", "image", "inspect", KNOWN_GOOD_IMAGE], capture_output=True, text=True, check=False)
    known_good = None
    if image.returncode == 0:
        known_good = json.loads(image.stdout)[0].get("Id")
    return {"containers": sorted(containers, key=lambda value: value["id"]), "known_good_image_id": known_good}


def assert_protected_unchanged(before: Mapping[str, Any], *, ignore_project: str | None = None) -> None:
    require(protected_state(ignore_project=ignore_project) == before, "PROTECTED_39080_OR_39083_CHANGED")


def state_volume_identity(profile: Target) -> tuple[tuple[str, str], ...]:
    result = []
    for name in ("pgvector-data", "neo4j-data", "neo4j-logs"):
        volume = f"{profile.project}_{name}"
        completed = subprocess.run(["docker", "volume", "inspect", volume], capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            document = json.loads(completed.stdout)[0]
            result.append((document.get("Name", ""), document.get("CreatedAt", "")))
    return tuple(sorted(result))


def build_proxy_environment(path: Path | None) -> tuple[dict[str, str], list[str]]:
    environment = dict(os.environ)
    keys = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
    if path is not None:
        resolved, before = private_env_file(path)
        values = operator_environment(resolved)
        require(sha256_file(resolved) == before, "PREP_ENV_CHANGED")
        for key in keys:
            if key in values or key.lower() in values:
                value = values.get(key, values.get(key.lower(), ""))
                environment[key] = environment[key.lower()] = value
    arguments: list[str] = []
    for key in keys:
        if key in environment or key.lower() in environment:
            value = environment.get(key, environment.get(key.lower(), ""))
            environment[key] = environment[key.lower()] = value
            # Docker reads these values from the CLI environment; never argv/logs.
            arguments.extend(("--build-arg", key, "--build-arg", key.lower()))
    print("BUILD_NETWORK|proxy_input=" + ("ENV_FILE" if path else "SHELL_OR_DOCKER_CONFIG")
          + "|runtime_provider_env=NOT_FORWARDED", flush=True)
    return environment, arguments


def build_image(head: str, *, no_cache: bool = False, build_env_file: Path | None = None) -> tuple[str, str]:
    docker_platform()
    if not no_cache:
        try:
            image, image_id = require_built_image(head)
        except DeployError:
            pass  # Missing/obsolete receipt or image: build the current snapshot.
        else:
            print(f"SOURCE_BUILD|status=REUSED|source_sha256={head}|image={image}", flush=True)
            return image, image_id
    image = source_image(head)
    present = subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
    if present.returncode == 0:
        # An explicit rebuild must not move an image reference used by a deployment.
        image += "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    before = protected_state()
    log = RUNTIME_ROOT / "build" / f"{head}.log"
    archive = source_archive()
    require(hashlib.sha256(archive).hexdigest() == head, "SOURCE_CHANGED_BEFORE_BUILD")
    arguments = ["docker", "build", "--progress=plain", "--platform", "linux/amd64"]
    environment, proxy_arguments = build_proxy_environment(build_env_file)
    arguments.extend(proxy_arguments)
    if no_cache:
        arguments.append("--no-cache")
    arguments.extend(["--build-arg", f"POC_SOURCE_COMMIT={head}", "--tag", image,
                      "--file", "deploy/Dockerfile", "-"])
    with tempfile.TemporaryFile() as context:
        context.write(archive)
        context.seek(0)
        exit_code = run_build(arguments, cwd=ROOT, archive=context, log_path=log, environment=environment)
    assert_protected_unchanged(before)
    require(exit_code == 0, f"SOURCE_BUILD_FAILED:exit={exit_code}:log={log}")
    require(build_input_hash() == head, "SOURCE_CHANGED_DURING_BUILD:rebuild_current_source")
    document = json.loads(output("docker", "image", "inspect", image))[0]
    labels = document.get("Config", {}).get("Labels", {}) or {}
    image_id = document.get("Id")
    require(isinstance(image_id, str) and image_id.startswith("sha256:"), "BUILT_IMAGE_ID_INVALID")
    require(labels.get("org.opencontainers.image.revision") == head, "BUILT_IMAGE_REVISION_INVALID")
    require(labels.get("io.datariver.source.sha256") == head, "BUILT_SOURCE_HASH_INVALID")
    require(document.get("Os") == "linux" and document.get("Architecture") == "amd64", "BUILT_PLATFORM_INVALID")
    require(image != KNOWN_GOOD_IMAGE, "KNOWN_GOOD_IMAGE_TAG_COLLISION")
    atomic_private_json(RUNTIME_ROOT / "build" / "receipt.json", {
        "contract": "DATARIVER_DEV_DEPLOY_SOURCE_BUILD_V2", "source_sha256": head,
        "source_identity_kind": "FOLDER_SHA256", "git_dependency": False,
        "base_product": BASE_PRODUCT, "image": image, "image_id": image_id,
        "no_cache": no_cache, "artifact_branch_dependency": False,
        "built_at": datetime.now(UTC).isoformat(), "log": str(log),
        "build_input_sha256": head,
    })
    return image, image_id


def require_built_image(head: str) -> tuple[str, str]:
    receipt = read_json(RUNTIME_ROOT / "build" / "receipt.json")
    image = receipt.get("image", "")
    image_pattern = re.escape(source_image(head)) + r"(?:-[0-9]{8}T[0-9]{12}Z)?"
    require(
        receipt.get("contract") == "DATARIVER_DEV_DEPLOY_SOURCE_BUILD_V2"
        and receipt.get("source_sha256") == head
        and isinstance(image, str) and re.fullmatch(image_pattern, image) is not None
        and receipt.get("source_identity_kind") == "FOLDER_SHA256"
        and receipt.get("git_dependency") is False
        and receipt.get("artifact_branch_dependency") is False
        and receipt.get("build_input_sha256") == head == build_input_hash(),
        "SOURCE_BUILD_RECEIPT_INVALID:run_build_for_current_source",
    )
    document = json.loads(output("docker", "image", "inspect", image))[0]
    image_id = document.get("Id")
    require(image_id == receipt.get("image_id"), "SOURCE_BUILD_IMAGE_CHANGED")
    labels = document.get("Config", {}).get("Labels", {}) or {}
    require(labels.get("org.opencontainers.image.revision") == head
            and labels.get("io.datariver.source.sha256") == head, "SOURCE_BUILD_REVISION_CHANGED")
    require(document.get("Os") == "linux" and document.get("Architecture") == "amd64", "BUILT_PLATFORM_INVALID")
    return image, image_id


def show_build_log(*, follow: bool) -> int:
    logs = list((RUNTIME_ROOT / "build").glob("*.log"))
    require(bool(logs), "BUILD_LOG_NOT_FOUND:run_from_source_directory")
    log = max(logs, key=lambda path: path.stat().st_mtime_ns)
    print(f"BUILD_LOG|path={log}", flush=True)
    arguments = ["tail", "-n", "60"]
    if follow:
        arguments.append("-f")
    return subprocess.call([*arguments, str(log)])


def subprocess_environment(values: Mapping[str, str]) -> dict[str, str]:
    retained = {key: os.environ[key] for key in (
        "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
    ) if key in os.environ}
    retained.update(values)
    return retained


def provider_preflight(
    image: str, values: Mapping[str, str], *, validation_only: bool = False,
) -> dict[str, str]:
    provider_values = dict(values)
    if validation_only:
        # Product preflight validates the actual PREP intranet bind contract;
        # the temporary host-local validation publish remains loopback-only.
        provider_values["POC_BIND_HOST"] = "0.0.0.0"
    environment = subprocess_environment(provider_values)
    arguments = ["docker", "run", "--rm", "--platform", "linux/amd64"]
    for key in sorted(provider_values):
        arguments.extend(("--env", key))
    source_ca = values.get("RUNTIME_CA_CERT_FILE", "").strip()
    if source_ca:
        arguments.extend(("--volume", f"{source_ca}:/run/datariver/runtime-ca.pem:ro", "--env", "POC_RUNTIME_CA_CERT_FILE=/run/datariver/runtime-ca.pem"))
    arguments.extend((image, "node", "backend/scripts/provider-preflight.mjs"))
    completed = subprocess.run(arguments, cwd=ROOT, env=environment, text=True, capture_output=True, check=False)
    require(completed.returncode == 0, "PROVIDER_PREFLIGHT_FAILED")
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        discovery = result["mcl_discovery"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise DeployError("PROVIDER_PREFLIGHT_CONTRACT_INVALID") from error
    require(result.get("status") == "PASS" and discovery.get("contract") == "DATARIVER_MCL_DISCOVERY_V1", "PROVIDER_PREFLIGHT_NOT_READY")
    mapped = {
        "POC_MCL_KAFKA_TOPIC": discovery.get("topic"),
        "POC_MCL_SOURCE_IDENTITY_HASH": discovery.get("source_identity_hash"),
        "POC_MCL_SCHEMA_CONTRACT_HASH": discovery.get("schema_contract_hash"),
        "POC_MCL_PROVIDER_NAME": discovery.get("provider_name"),
        "POC_MCL_PROVIDER_VERSION": discovery.get("provider_version"),
    }
    require(
        all(isinstance(value, str) and value for value in mapped.values())
        and HASH64.fullmatch(mapped["POC_MCL_SOURCE_IDENTITY_HASH"]) is not None
        and HASH64.fullmatch(mapped["POC_MCL_SCHEMA_CONTRACT_HASH"]) is not None,
        "MCL_DISCOVERY_IDENTITY_INVALID",
    )
    return mapped


def compose_prefix(profile: Target, environment_file: Path) -> list[str]:
    prefix = [
        "docker", "compose", "--project-name", profile.project,
        "--project-directory", str(BASE_COMPOSE.parent), "--env-file", str(environment_file),
        "--file", str(BASE_COMPOSE),
    ]
    return prefix


def validate_compose(profile: Target, prefix: Sequence[str], image: str) -> None:
    config = json.loads(output(*prefix, "config", "--format", "json"))
    services = config.get("services", {})
    require(isinstance(services, dict) and set(services) == {"web", "neo4j", "pgvector", "redis"}, "COMPOSE_SERVICES_INVALID")
    web = services["web"]
    require(web.get("image") == image and isinstance(web.get("build"), dict), "COMPOSE_SOURCE_IMAGE_INVALID")
    generated = read_json(RUNTIME_ROOT / profile.name / "generated.json") if profile == DEV_39091 else {}
    kafka = deployment_kafka_values(profile, generated)
    require(web.get("environment", {}).get("POC_MCL_KAFKA_CLIENT_ID") == kafka["POC_MCL_KAFKA_CLIENT_ID"], "KAFKA_CLIENT_NOT_ISOLATED")
    require(web.get("environment", {}).get("POC_MCL_KAFKA_GROUP_ID") == kafka["POC_MCL_KAFKA_GROUP_ID"], "KAFKA_GROUP_NOT_ISOLATED")
    published = {
        int(item.get("published")) for service in services.values()
        for item in (service.get("ports") or []) if str(item.get("published", "")).isdigit()
    }
    require(profile.port in published and not published.intersection({39080, 39083} - {profile.port}), "COMPOSE_PROTECTED_PORT_COLLISION")
    networks = config.get("networks", {})
    require({value.get("name") for value in networks.values()} == {profile.network}, "COMPOSE_NETWORK_IDENTITY_INVALID")
    volumes = config.get("volumes", {})
    expected_volumes = {f"{profile.project}_{name}" for name in ("pgvector-data", "neo4j-data", "neo4j-logs")}
    require({value.get("name") for value in volumes.values()} == expected_volumes, "COMPOSE_VOLUME_IDENTITY_INVALID")


def project_containers(profile: Target) -> dict[str, dict[str, Any]]:
    identifiers = output(
        "docker", "ps", "--all", "--filter", f"label=com.docker.compose.project={profile.project}", "--format", "{{.ID}}",
    ).splitlines()
    result: dict[str, dict[str, Any]] = {}
    for identifier in identifiers:
        document = json.loads(output("docker", "inspect", identifier))[0]
        service = (document.get("Config", {}).get("Labels", {}) or {}).get("com.docker.compose.service")
        require(service in {"web", "neo4j", "pgvector", "redis"} and service not in result, "PROJECT_CONTAINER_INVENTORY_INVALID")
        result[service] = document
    return result


def require_target_port_ownership(profile: Target) -> None:
    target_ports = {profile.port, *(int(port) for port in profile.state_ports.values())}
    identifiers = output("docker", "ps", "--all", "--format", "{{.ID}}").splitlines()
    for identifier in identifiers:
        document = json.loads(output("docker", "inspect", identifier))[0]
        bindings = document.get("HostConfig", {}).get("PortBindings", {}) or {}
        published = {
            int(binding.get("HostPort"))
            for values in bindings.values() if isinstance(values, list)
            for binding in values if isinstance(binding, dict) and str(binding.get("HostPort", "")).isdigit()
        }
        if not target_ports.intersection(published):
            continue
        project = (document.get("Config", {}).get("Labels", {}) or {}).get("com.docker.compose.project")
        require(project == profile.project, "TARGET_PORT_OWNED_BY_OTHER_PROJECT")


def wait_state(prefix: Sequence[str], profile: Target, existing: Mapping[str, Any]) -> None:
    state_services = ("pgvector", "neo4j", "redis")
    if existing:
        require(all(service in existing for service in state_services), "EXISTING_STATE_SERVICES_INCOMPLETE")
        run((*prefix, "up", "-d", "--no-build", "--pull", "never", "--no-recreate", "--wait", *state_services))
    else:
        run((*prefix, "up", "-d", "--no-build", "--pull", "missing", "--wait", *state_services))


def password_file(profile: Target, *, existing_state: bool, supplied: Path | None) -> Path:
    if supplied:
        resolved, _ = private_env_file(supplied)
        require(bool(resolved.read_text(encoding="utf-8").strip()), "ADMIN_PASSWORD_EMPTY")
        return resolved
    target = RUNTIME_ROOT / profile.name / "admin-password"
    if target.exists():
        resolved, _ = private_env_file(target)
        return resolved
    if existing_state:
        require(sys.stdin.isatty(), "EXISTING_ADMIN_PASSWORD_REQUIRED")
        value = getpass.getpass("Existing PREP administrator password: ")
        require(len(value) >= 12, "ADMIN_PASSWORD_INVALID")
    else:
        value = secrets.token_urlsafe(36)
    atomic_private_text(target, value + "\n")
    return target


def reconcile(prefix: Sequence[str], password: Path, existing_state: bool) -> None:
    inspect = run((*prefix, "run", "--rm", "--no-deps", "web", "node", "backend/scripts/prep-bootstrap.mjs", "inspect"))
    try:
        state = json.loads(inspect.stdout.strip().splitlines()[-1])
        administrators = state.get("administrators")
    except (IndexError, TypeError, json.JSONDecodeError) as error:
        raise DeployError("BOOTSTRAP_INSPECTION_INVALID") from error
    require(isinstance(administrators, list), "BOOTSTRAP_INSPECTION_INVALID")
    command = [*prefix, "run", "--rm", "--no-deps"]
    if administrators:
        command.extend(("web", "node", "backend/scripts/prep-bootstrap.mjs", "reconcile"))
    else:
        require(not existing_state, "EXISTING_STATE_ADMIN_MISSING")
        command.extend((
            "--volume", f"{password}:/run/dev-deploy-admin-password:ro", "web", "node", "backend/scripts/prep-bootstrap.mjs", "reconcile",
            "--admin-username", ADMIN_USERNAME, "--admin-password-file", "/run/dev-deploy-admin-password",
        ))
    run(command)


def running_web(profile: Target, image: str, image_id: str) -> dict[str, Any]:
    containers = project_containers(profile)
    require(set(containers) == {"web", "neo4j", "pgvector", "redis"}, "RUNNING_PROJECT_INCOMPLETE")
    web = containers["web"]
    labels = web.get("Config", {}).get("Labels", {}) or {}
    require(
        web.get("State", {}).get("Running") is True
        and web.get("State", {}).get("Health", {}).get("Status") == "healthy"
        and labels.get("com.docker.compose.project") == profile.project
        and labels.get("com.docker.compose.service") == "web"
        and web.get("Config", {}).get("Image") == image and web.get("Image") == image_id,
        "RUNNING_WEB_IDENTITY_INVALID",
    )
    for service in ("neo4j", "pgvector", "redis"):
        require(containers[service].get("State", {}).get("Health", {}).get("Status") == "healthy", "STATE_SERVICE_NOT_HEALTHY")
    return web


def run_acceptance(profile: Target, image: str, web: Mapping[str, Any], password: Path, request_origin: str, head: str) -> dict[str, Any]:
    receipt_root = RUNTIME_ROOT / profile.name
    receipt_root.mkdir(parents=True, exist_ok=True)
    common = [
        "docker", "run", "--rm", "--platform", "linux/amd64", "--network", f"container:{web['Id']}",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--volume", f"{ROOT}:/source:ro", "--volume", f"{receipt_root}:/receipts",
        "--volume", f"{password}:/run/dev-deploy-admin-password:ro", image, "node",
    ]
    # Cheap readiness first, six canonical gates once, then route/preview acceptance.
    run((*common, "/source/scripts/accept_dev_deploy.mjs", "--phase", "readiness",
         "--origin", "http://127.0.0.1:8080", "--request-origin", request_origin,
         "--username", ADMIN_USERNAME, "--password-file", "/run/dev-deploy-admin-password",
         "--output", "/receipts/readiness.json"))
    readiness = read_json(receipt_root / "readiness.json")
    require(readiness.get("mcl_current") == "READY" and readiness.get("k9_semantic") == "READY",
            "FOCUSED_READINESS_NOT_READY")
    smoke_output = "/receipts/smoke.json"
    smoke_failure = "/receipts/smoke-failure.json"
    run((*common, "/source/scripts/smoke_prep39083.mjs", "--origin", "http://127.0.0.1:8080",
         "--request-origin", request_origin, "--username", ADMIN_USERNAME,
         "--password-file", "/run/dev-deploy-admin-password", "--output", smoke_output,
         "--failure-output", smoke_failure, "--smoke-product-sha", head, "--k9-mode", "required"))
    smoke = read_json(receipt_root / "smoke.json")
    require(
        smoke.get("datahub") == "PASS" and smoke.get("llm_general") == "PASS"
        and smoke.get("mcl_current_capture") == "READY"
        and smoke.get("mcl_history_completeness") in {"EXACT", "DEGRADED_GAP"}
        and (smoke.get("mcl_history_completeness") != "DEGRADED_GAP" or smoke.get("mcl_history_gap_reason") == "RETENTION_EXPIRED")
        and smoke.get("semantic_index") == "PASS",
        "FULL_SMOKE_NOT_READY",
    )
    run((*common, "/source/scripts/accept_dev_deploy.mjs", "--phase", "features",
         "--canonical-smoke", smoke_output, "--source-sha", head,
         "--origin", "http://127.0.0.1:8080", "--request-origin", request_origin,
         "--username", ADMIN_USERNAME, "--password-file", "/run/dev-deploy-admin-password",
         "--output", "/receipts/features.json"))
    features = read_json(receipt_root / "features.json")
    require(all(features.get(key) == "PASS" for key in (
        "auto_chat", "graph_chat", "auto_graph", "auto_search", "vector_chat", "knowledge_graph_preview")),
        "FEATURE_ACCEPTANCE_NOT_READY")
    return {"smoke": smoke, "features": features}


def unexpected_5xx(web: Mapping[str, Any], since: str) -> bool:
    completed = subprocess.run(["docker", "logs", "--since", since, str(web["Id"])], capture_output=True, text=True, check=False)
    require(completed.returncode == 0, "WEB_LOG_READ_FAILED")
    patterns = (
        re.compile(r'"status(?:Code)?"\s*:\s*5\d\d'),
        re.compile(r'\bHTTP[/0-9.]*\s+5\d\d\b'),
    )
    return any(pattern.search(completed.stdout + completed.stderr) for pattern in patterns)


def deploy(profile: Target, env_file: Path, supplied_password: Path | None, public_origin: str | None = None) -> None:
    head, _ = validate_source(clean=True)
    image, image_id = require_built_image(head)
    ignored_project = None if profile.validation_only else profile.project
    before = protected_state(ignore_project=ignored_project)
    source, source_hash = deployment_environment(env_file, profile, public_origin)
    state = state_kind(profile)
    if profile == VALIDATION_39081:
        require(state == "EXISTING", "VALIDATION_39081_STATE_NOT_PRESENT")
    volume_before = state_volume_identity(profile)
    require_target_port_ownership(profile)
    runtime_file = env_file.with_name(env_file.name + ".runtime")
    preserved = {}
    if runtime_file.is_file() and not profile.validation_only:
        private_env_file(runtime_file)
        preserved = read_env(runtime_file)
    derived, values = write_derived_environment(source, profile, head, state=state, image=image, preserved_runtime=preserved)
    discovered = provider_preflight(image, values, validation_only=profile.validation_only)
    derived, values = write_derived_environment(source, profile, head, state=state, image=image, discovered=discovered, preserved_runtime=preserved)
    require(sha256_file(env_file) == source_hash, "PREP_ENV_CHANGED")
    prefix = compose_prefix(profile, derived)
    validate_compose(profile, prefix, image)
    existing = project_containers(profile)
    if existing.get("web"):
        old_web = existing["web"].get("Config", {})
        old_image = old_web.get("Image", "")
        old_revision = (old_web.get("Labels") or {}).get("org.opencontainers.image.revision", "")
        require(old_image in {image, KNOWN_GOOD_IMAGE}
                or (old_image.startswith("datariver-dev-deploy-source:") and SOURCE_ID.fullmatch(old_revision)),
                "EXISTING_WEB_OWNER_INVALID")
    wait_state(prefix, profile, existing)
    password = password_file(profile, existing_state=state == "EXISTING", supplied=supplied_password)
    reconcile(prefix, password, existing_state=state == "EXISTING")
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    run((*prefix, "up", "-d", "--no-build", "--pull", "never", "--force-recreate", "--no-deps", "--wait", "web"))
    web = running_web(profile, image, image_id)
    acceptance = run_acceptance(profile, image, web, password, values["POC_PUBLIC_ORIGIN"], head)
    containers = project_containers(profile)
    require(not any(container.get("State", {}).get("OOMKilled") is True for container in containers.values()), "CONTAINER_OOM_DETECTED")
    require(not unexpected_5xx(web, started), "UNEXPECTED_WEB_5XX")
    assert_protected_unchanged(before, ignore_project=ignored_project)
    volume_after = state_volume_identity(profile)
    if state == "EXISTING":
        require(volume_after == volume_before, "EXISTING_STATE_VOLUMES_CHANGED")
    require(sha256_file(env_file) == source_hash, "PREP_ENV_CHANGED")
    atomic_private_json(RUNTIME_ROOT / profile.name / "acceptance.json", {
        "contract": "DATARIVER_DEV_DEPLOY_RUNTIME_ACCEPTANCE_V1",
        "accepted_at": datetime.now(UTC).isoformat(), "branch": BRANCH, "source_sha256": head,
        "source_identity_kind": "FOLDER_SHA256",
        "base_product": BASE_PRODUCT, "image": image, "image_id": image_id,
        "profile": profile.name, "project": profile.project, "port": profile.port,
        "env_sha256": source_hash, "source_env_unchanged": True,
        "existing_state_preserved": state != "EXISTING" or volume_after == volume_before,
        "mcl_current": acceptance["smoke"]["mcl_current_capture"],
        "mcl_history": acceptance["smoke"]["mcl_history_completeness"],
        "k9_semantic": acceptance["smoke"]["semantic_index"],
        "auto_chat": acceptance["features"]["auto_chat"],
        "graph_chat": acceptance["features"]["graph_chat"],
        "auto_graph": acceptance["features"]["auto_graph"],
        "auto_search": acceptance["features"]["auto_search"],
        "vector_chat": acceptance["features"]["vector_chat"],
        "knowledge_graph_preview": acceptance["features"]["knowledge_graph_preview"],
        "unexpected_5xx": "NONE", "oom": "NONE", "protected_39080": "UNTOUCHED",
        "p39083": "UNTOUCHED" if profile.validation_only else "DEPLOYED",
    })


def preflight_line(values: Mapping[str, str]) -> str:
    return (
        "PREP_ENV_PREFLIGHT|status=PASS|datahub=SET|chat=SET|embedding=SET|"
        f"mcl_broker={'SET' if values.get('POC_MCL_KAFKA_BROKERS') else 'ABSENT'}|"
        "mcl_topic=DISCOVERED_AT_DEPLOY|mcl_schema_registry=DISCOVERED_AT_DEPLOY|"
        "mcl_auth=VALID|mcl_source_hash=DISCOVERED_AT_DEPLOY|mcl_schema_hash=DISCOVERED_AT_DEPLOY|blocker=NONE"
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check-source", "preflight", "build", "build-log", "validate-39081", "deploy"))
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--admin-password-file", type=Path)
    parser.add_argument("--port", type=int, choices=(39083, 39091), default=None,
                        help="Default: datariver-dev on 39091; explicit 39083 targets the existing PREP project")
    parser.add_argument("--public-origin", help="Browser origin on a new host, including the selected port")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="Force a clean source build instead of reusing the image/cache")
    parser.add_argument("--build-env-file", type=Path,
                        help="Read only HTTP_PROXY/HTTPS_PROXY/NO_PROXY for build from this private env file and optional sidecar")
    parser.add_argument("--follow", action="store_true", help="Follow the most recent build log")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        require(not arguments.no_cache or arguments.command == "build", "NO_CACHE_BUILD_ONLY")
        require(arguments.build_env_file is None or arguments.command == "build", "BUILD_ENV_FILE_BUILD_ONLY")
        require(not arguments.follow or arguments.command == "build-log", "FOLLOW_BUILD_LOG_ONLY")
        if arguments.command == "build-log":
            return show_build_log(follow=arguments.follow)
        head, count = validate_source(clean=arguments.command in {"build", "deploy"})
        if arguments.command == "validate-39081":
            require(arguments.port is None, "VALIDATION_PORT_OPTION_CONFLICT")
            profile = VALIDATION_39081
        else:
            profile = PREP_39083 if arguments.port == 39083 else DEV_39091
        if arguments.command == "check-source":
            print(f"SOURCE_CHECK|status=PASS|branch={BRANCH}|source_sha256={head}|files={count}|git_dependency=NONE|base_product={BASE_PRODUCT[:12]}|artifact_dependency=NONE")
            return 0
        if arguments.command == "preflight":
            values, before = deployment_environment(arguments.env_file, profile, arguments.public_origin)
            require(sha256_file(arguments.env_file) == before, "PREP_ENV_CHANGED")
            print(preflight_line(values))
            return 0
        if arguments.command == "build":
            image, image_id = build_image(head, no_cache=arguments.no_cache, build_env_file=arguments.build_env_file)
            print(f"SOURCE_BUILD|status=PASS|branch={BRANCH}|source_sha256={head}|image={image}|image_digest={image_id}|no_cache_requested={'Y' if arguments.no_cache else 'N'}|artifact_dependency=NONE")
            return 0
        require(arguments.apply, "DEPLOY_REQUIRES_APPLY")
        deploy(profile, arguments.env_file, arguments.admin_password_file, arguments.public_origin)
        print(f"DEV_DEPLOY_ACCEPTANCE|status=PASS|target={profile.name}|mcl=READY|k9=READY|smoke=6/6_PASS|chat=PASS|graph=PASS|preview=PASS|p39080=UNTOUCHED|p39083={'DEPLOYED' if not profile.validation_only else 'UNTOUCHED'}")
        return 0
    except KeyboardInterrupt:
        print("INTERRUPTED|operation=" + arguments.command, file=sys.stderr)
        return 130
    except DeployError as error:
        print(f"FAILED|code={error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
