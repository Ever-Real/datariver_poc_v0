#!/usr/bin/env python3
"""Prepare loopback-only infrastructure for source-host development."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from platform_workflow import (
    ROOT,
    RUNTIME_SERVICES,
    AppliedState,
    Runner,
    WorkflowError,
    compose_arguments,
    load_applied_state,
    read_env_values,
    release_layout,
    require_command,
    require_regular_file,
    state_path,
    update_env_values,
    validate_username_password_secret,
)

SOURCE_INFRASTRUCTURE_SERVICES = ("postgres", "keycloak")
CONTAINER_APPLICATION_SERVICES = tuple(
    service for service in RUNTIME_SERVICES if service != "keycloak"
)
EXPECTED_OFFLINE_PLATFORM = "linux/amd64"
NEO4J_BUNDLE_MANIFEST_GLOB = "neo4j-*-linux-amd64.manifest.tsv"
NEO4J_CONNECTOR_COMPOSE = ROOT / "compose.local-connectors.yaml"


@dataclass(frozen=True)
class SourceHostInfraPlan:
    """Resolved infrastructure inputs hidden behind one operator action."""

    profile: str
    env_file: Path
    compose_files: tuple[Path, ...]
    offline: bool
    local_image_reuse: bool
    release_platform_dir: Path | None


@dataclass(frozen=True)
class Neo4jBundle:
    """Verified metadata for one separately distributed AMD64 graph image."""

    archive: Path
    checksum: Path
    manifest: Path
    image: str
    source_image: str
    platform: str
    image_id: str
    repository_digest: str
    archive_sha256: str


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stop containerized DataRiver application processes and prepare PostgreSQL/Keycloak "
            "for loopback source-host access. Build and offline image references are resolved "
            "from recorded profile state; a pre-state explicit environment reuses only verified "
            "local AMD64 image references with registry access disabled."
        )
    )
    parser.add_argument(
        "action",
        choices=("prepare", "status", "config"),
        help="Prepare infrastructure, show status, or render the resolved image inventory.",
    )
    parser.add_argument(
        "--profile",
        default="wsl-preparation",
        help="Applied workflow profile (default: wsl-preparation).",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional source-host environment; defaults to the applied profile environment.",
    )
    parser.add_argument(
        "--reuse-local-images",
        action="store_true",
        help=(
            "Development-only: force registry-disabled reuse of the configured local PostgreSQL "
            "and final Keycloak images. Requires --env-file."
        ),
    )
    parser.add_argument(
        "--connected-build",
        action="store_true",
        help=("Deprecated alias for --reuse-local-images. No registry pull or image build occurs."),
    )
    parser.add_argument(
        "--neo4j-bundle-dir",
        type=Path,
        help=(
            "Directory from the separately distributed Neo4j AMD64 repository. The workflow "
            "verifies its archive checksum, manifest, platform and image ID before starting the "
            "local graph connector."
        ),
    )
    parser.add_argument(
        "--reuse-loaded-neo4j",
        action="store_true",
        help=(
            "Development-only: reuse the approved Neo4j tag already loaded in Docker, verify "
            "linux/amd64, and start it with registry access disabled. No bundle directory is "
            "required and no release acceptance is claimed."
        ),
    )
    return parser.parse_args()


def _resolve_path(root: Path, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def resolve_plan(
    *,
    root: Path,
    state: AppliedState | None,
    env_file_override: Path | None,
    reuse_local_images: bool = False,
) -> SourceHostInfraPlan:
    local_image_reuse = reuse_local_images or (state is None and env_file_override is not None)
    if local_image_reuse:
        if env_file_override is None:
            raise WorkflowError("--reuse-local-images requires an explicit --env-file.")
        env_file = _resolve_path(root, env_file_override)
        require_regular_file(env_file, label="Selected source-host environment")
        return SourceHostInfraPlan(
            profile="local-image-source-development",
            env_file=env_file,
            compose_files=(
                root / "compose.yaml",
                root / "compose.identity.yaml",
                root / "compose.source-host.yaml",
                root / "compose.connected-source-host.yaml",
            ),
            offline=False,
            local_image_reuse=True,
            release_platform_dir=None,
        )
    if state is None:
        raise WorkflowError(
            "The applied workflow state is unavailable. Supply an explicit --env-file to reuse "
            "already loaded local images without registry access. Managed offline acceptance "
            "still requires the wsl-preparation state and release evidence."
        )
    env_file = _resolve_path(root, env_file_override or state.env_file)
    require_regular_file(env_file, label="Selected source-host environment")
    compose_files: tuple[Path, ...] = (
        root / "compose.yaml",
        root / "compose.identity.yaml",
        root / "compose.source-host.yaml",
    )
    if state.deployment_mode == "build":
        return SourceHostInfraPlan(
            profile=state.profile,
            env_file=env_file,
            compose_files=compose_files,
            offline=False,
            local_image_reuse=False,
            release_platform_dir=None,
        )
    if state.release_dir is None:
        raise WorkflowError("The offline applied state has no release directory.")
    layout = release_layout(Path(state.release_dir), architecture="amd64")
    return SourceHostInfraPlan(
        profile=state.profile,
        env_file=env_file,
        compose_files=(*compose_files, layout.offline_compose),
        offline=True,
        local_image_reuse=False,
        release_platform_dir=layout.platform_dir,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: Path) -> str:
    artifact = path.with_suffix("")
    require_regular_file(path, label=f"{artifact.name} checksum")
    require_regular_file(artifact, label=artifact.name)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise WorkflowError(f"Checksum sidecar must contain exactly one entry: {path}")
    match = re.fullmatch(r"([0-9a-f]{64})[ \t]+[*]?(.+)", lines[0])
    if match is None or Path(match.group(2)).name != artifact.name:
        raise WorkflowError(f"Checksum sidecar has an invalid target: {path}")
    actual = sha256_file(artifact)
    if actual != match.group(1):
        raise WorkflowError(f"Checksum mismatch: {artifact}")
    return actual


def approved_neo4j_source_image() -> str:
    """Read the reviewed upstream trust anchor from the checked-in connector contract."""

    compose = require_regular_file(
        NEO4J_CONNECTOR_COMPOSE,
        label="Neo4j connector Compose contract",
    )
    matches: list[str] = re.findall(
        r"^\s*image:\s+\$\{NEO4J_IMAGE:-(neo4j:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        r"@sha256:[0-9a-f]{64})\}\s*$",
        compose.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if len(matches) != 1:
        raise WorkflowError("Neo4j connector Compose must contain one approved digest pin.")
    return matches[0]


def load_neo4j_bundle(
    directory: Path,
    *,
    approved_source_image: str | None = None,
) -> Neo4jBundle:
    expanded = directory.expanduser()
    if expanded.is_symlink():
        raise WorkflowError(f"Neo4j bundle directory must not be a symbolic link: {expanded}")
    candidate = expanded.resolve()
    if not candidate.is_dir():
        raise WorkflowError(f"Neo4j bundle directory is not a regular directory: {candidate}")
    manifests = tuple(candidate.glob(NEO4J_BUNDLE_MANIFEST_GLOB))
    if len(manifests) != 1:
        raise WorkflowError("Neo4j bundle directory must contain exactly one linux/amd64 manifest.")
    manifest = require_regular_file(manifests[0], label="Neo4j AMD64 manifest")
    with manifest.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        expected_header = [
            "archive",
            "image",
            "source_image",
            "platform",
            "image_id",
            "repo_digest",
            "archive_sha256",
        ]
        if reader.fieldnames != expected_header:
            raise WorkflowError("Neo4j AMD64 manifest header is invalid.")
        rows = list(reader)
    if len(rows) != 1:
        raise WorkflowError("Neo4j AMD64 manifest must contain exactly one image row.")
    row = rows[0]
    archive_name = row["archive"]
    if not archive_name or Path(archive_name).name != archive_name:
        raise WorkflowError("Neo4j AMD64 manifest contains an invalid archive name.")
    archive = require_regular_file(candidate / archive_name, label="Neo4j AMD64 archive")
    checksum = archive.with_name(f"{archive.name}.sha256")
    actual_sha256 = verify_checksum(checksum)
    if row["archive_sha256"] != actual_sha256:
        raise WorkflowError("Neo4j AMD64 manifest archive SHA-256 does not match the sidecar.")
    image = row["image"]
    if re.fullmatch(r"neo4j:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image) is None:
        raise WorkflowError("Neo4j AMD64 manifest image tag is invalid.")
    digest_suffix = r"@sha256:[0-9a-f]{64}"
    source_image = row["source_image"]
    repository_digest = row["repo_digest"]
    if re.fullmatch(re.escape(image) + digest_suffix, source_image) is None:
        raise WorkflowError("Neo4j AMD64 manifest source image is not digest-pinned.")
    if re.fullmatch(r"neo4j" + digest_suffix, repository_digest) is None:
        raise WorkflowError("Neo4j AMD64 manifest repository digest is invalid.")
    if source_image.partition("@")[2] != repository_digest.partition("@")[2]:
        raise WorkflowError("Neo4j AMD64 manifest digest fields do not match.")
    approved_image = approved_source_image or approved_neo4j_source_image()
    if source_image != approved_image:
        raise WorkflowError(
            "Neo4j AMD64 manifest source image does not match the approved Compose digest pin."
        )
    if row["platform"] != EXPECTED_OFFLINE_PLATFORM:
        raise WorkflowError("Neo4j bundle must target linux/amd64.")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", row["image_id"]) is None:
        raise WorkflowError("Neo4j AMD64 manifest image ID is invalid.")
    return Neo4jBundle(
        archive=archive,
        checksum=checksum,
        manifest=manifest,
        image=image,
        source_image=source_image,
        platform=row["platform"],
        image_id=row["image_id"],
        repository_digest=repository_digest,
        archive_sha256=actual_sha256,
    )


def read_release_image_inventory(manifest: Path) -> dict[str, tuple[str, str]]:
    require_regular_file(manifest, label="Core image manifest")
    inventory: dict[str, tuple[str, str]] = {}
    with manifest.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != [
            "image",
            "image_id",
            "repository_digests",
            "platform",
        ]:
            raise WorkflowError("Core image manifest header is invalid.")
        for row in reader:
            image = row["image"]
            local_tag = image.split("@sha256:", 1)[0]
            if local_tag in inventory:
                raise WorkflowError(f"Core image manifest contains a duplicate tag: {local_tag}")
            image_id = row["image_id"]
            platform = row["platform"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise WorkflowError(f"Core image manifest has an invalid image ID: {local_tag}")
            if platform not in {"linux/amd64", "linux/arm64"}:
                raise WorkflowError(f"Core image manifest has an invalid platform: {local_tag}")
            inventory[local_tag] = (image_id, platform)
    return inventory


def rendered_service_images(
    runner: Runner,
    plan: SourceHostInfraPlan,
) -> dict[str, str]:
    raw_config = runner.output(_compose_command(plan, ("config", "--format", "json")))
    try:
        document = json.loads(raw_config)
    except json.JSONDecodeError as error:
        raise WorkflowError("Resolved source-host Compose config is not valid JSON.") from error
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        raise WorkflowError("Resolved source-host Compose config has no services object.")
    images: dict[str, str] = {}
    for service_name in SOURCE_INFRASTRUCTURE_SERVICES:
        service = services.get(service_name)
        image = service.get("image") if isinstance(service, dict) else None
        if not isinstance(image, str) or not image.strip():
            raise WorkflowError(
                f"Resolved source-host service has no image reference: {service_name}"
            )
        images[service_name] = image.strip()
    return images


def verify_offline_images(
    runner: Runner,
    platform_directory: Path,
    service_images: dict[str, str],
) -> None:
    offline_compose_checksum = platform_directory / "offline-core.compose.yaml.sha256"
    manifest_checksum = platform_directory / "datariver-core-amd64.manifest.tsv.sha256"
    verify_checksum(offline_compose_checksum)
    verify_checksum(manifest_checksum)
    inventory = read_release_image_inventory(
        platform_directory / "datariver-core-amd64.manifest.tsv"
    )
    for service_name in SOURCE_INFRASTRUCTURE_SERVICES:
        image = service_images[service_name]
        if "@sha256:" in image:
            raise WorkflowError(
                f"Offline source-host service retained a registry-only digest: {service_name}"
            )
        expected = inventory.get(image)
        if expected is None:
            raise WorkflowError(
                f"Core release manifest omits the resolved {service_name} image: {image}"
            )
        expected_id, expected_platform = expected
        if expected_platform != EXPECTED_OFFLINE_PLATFORM:
            raise WorkflowError(
                f"Core release image has the wrong target platform: {image}={expected_platform}"
            )
        observed = runner.output(
            (
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}\t{{.Os}}/{{.Architecture}}",
                image,
            )
        )
        if observed != f"{expected_id}\t{expected_platform}":
            raise WorkflowError(
                f"Loaded image does not match the verified release manifest: {image}"
            )


def _compose_command(
    plan: SourceHostInfraPlan,
    trailing: tuple[str, ...],
) -> list[str]:
    return compose_arguments(
        env_file=plan.env_file,
        compose_files=plan.compose_files,
        trailing=trailing,
    )


def _local_graph_command(
    plan: SourceHostInfraPlan,
    trailing: tuple[str, ...],
) -> list[str]:
    return compose_arguments(
        env_file=plan.env_file,
        compose_files=(NEO4J_CONNECTOR_COMPOSE,),
        profiles=("graph",),
        trailing=trailing,
    )


def verify_and_load_neo4j_image(runner: Runner, bundle: Neo4jBundle) -> None:
    runner.run(("docker", "image", "load", "--input", bundle.archive))
    observed = runner.output(
        (
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}\t{{.Os}}/{{.Architecture}}",
            bundle.image,
        )
    )
    expected = f"{bundle.image_id}\t{bundle.platform}"
    if observed != expected:
        raise WorkflowError(
            "Loaded Neo4j image does not match its verified AMD64 manifest: "
            f"expected={expected}, observed={observed}"
        )


def configured_loaded_neo4j_image(plan: SourceHostInfraPlan) -> str:
    values = read_env_values(plan.env_file)
    image = values.get("NEO4J_IMAGE", approved_neo4j_source_image().partition("@")[0])
    approved_tag = approved_neo4j_source_image().partition("@")[0]
    if image != approved_tag:
        raise WorkflowError(
            "Loaded Neo4j development reuse requires the approved configured tag "
            f"{approved_tag}; selected={image}."
        )
    return image


def verify_loaded_neo4j_image(runner: Runner, image: str) -> None:
    try:
        observed = runner.output(
            (
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}\t{{.Os}}/{{.Architecture}}",
                image,
            )
        )
    except WorkflowError as error:
        raise WorkflowError(
            f"The loaded Neo4j image is unavailable: {image}. Load the verified AMD64 image "
            "before rerunning with --reuse-loaded-neo4j."
        ) from error
    fields = observed.split("\t")
    if len(fields) != 2 or fields[1] != EXPECTED_OFFLINE_PLATFORM:
        raise WorkflowError(
            f"Loaded Neo4j image must be {EXPECTED_OFFLINE_PLATFORM}: "
            f"image={image}, observed={observed}"
        )


def resolve_neo4j_environment(
    plan: SourceHostInfraPlan,
    image: str,
) -> dict[str, str]:
    credential_path = require_regular_file(
        ROOT / "secrets" / "neo4j_auth",
        label="Neo4j credential",
    )
    validate_username_password_secret(credential_path.read_text(encoding="utf-8"))
    values = read_env_values(plan.env_file)
    raw_bolt_port = values.get("NEO4J_BOLT_PORT", "17687")
    try:
        bolt_port = int(raw_bolt_port)
    except ValueError as error:
        raise WorkflowError("NEO4J_BOLT_PORT must be an integer.") from error
    if not 1 <= bolt_port <= 65535:
        raise WorkflowError("NEO4J_BOLT_PORT must be in the range 1..65535.")
    return {
        "NEO4J_IMAGE": image,
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_SOURCE_HOST_ENABLED": "true",
        "NEO4J_URI": f"bolt://127.0.0.1:{bolt_port}",
        "NEO4J_ALLOWED_HOSTS": "127.0.0.1",
        "NEO4J_AUTH_SECRET_REF": "file:/run/secrets/neo4j_auth",
    }


def start_and_verify_neo4j(
    runner: Runner,
    plan: SourceHostInfraPlan,
    environment: dict[str, str],
) -> None:
    process_environment = os.environ.copy()
    process_environment.update(environment)
    runner.run(
        _local_graph_command(
            plan,
            (
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "neo4j",
            ),
        ),
        env=process_environment,
    )
    runner.run(
        _local_graph_command(
            plan,
            (
                "exec",
                "-T",
                "neo4j",
                "sh",
                "-ec",
                (
                    "exec cypher-shell -u neo4j "
                    '-p "$(cut -d/ -f2- /run/secrets/neo4j_auth)" "RETURN 1"'
                ),
            ),
        ),
        env=process_environment,
    )
    runner.run(
        _local_graph_command(plan, ("port", "neo4j", "7687")),
        env=process_environment,
    )
    update_env_values(plan.env_file, environment)


def verify_local_source_images(
    runner: Runner,
    service_images: dict[str, str],
) -> None:
    for service in SOURCE_INFRASTRUCTURE_SERVICES:
        image = service_images[service]
        try:
            observed = runner.output(
                (
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}\t{{.Os}}/{{.Architecture}}",
                    image,
                )
            )
        except WorkflowError as error:
            raise WorkflowError(
                "Local-image source-host preparation requires the existing "
                f"{service} image {image}. Load the verified AMD64 distribution image or select "
                f"an existing local reference with SOURCE_HOST_{service.upper()}_IMAGE; "
                "the workflow will not pull or build it."
            ) from error
        fields = observed.split("\t")
        if len(fields) != 2 or fields[1] != EXPECTED_OFFLINE_PLATFORM:
            raise WorkflowError(
                f"Local {service} image must be {EXPECTED_OFFLINE_PLATFORM}: "
                f"image={image}, observed={observed}"
            )


def show_status(runner: Runner, plan: SourceHostInfraPlan) -> None:
    runner.run(_compose_command(plan, ("ps", "postgres", "keycloak")))
    runner.run(_compose_command(plan, ("port", "postgres", "5432")))
    runner.run(_compose_command(plan, ("port", "keycloak", "8080")))


def prepare(
    runner: Runner,
    plan: SourceHostInfraPlan,
    service_images: dict[str, str],
    neo4j_environment: dict[str, str] | None,
) -> None:
    if plan.local_image_reuse:
        runner.note("기존 PostgreSQL/Keycloak AMD64 image가 로컬에 있는지 먼저 확인합니다.")
        verify_local_source_images(runner, service_images)
    runner.note("동일 checkout의 source-host process를 중지합니다.")
    runner.run(
        (
            ROOT / "scripts" / "dev_host.sh",
            "stop",
            "--env-file",
            plan.env_file,
        )
    )
    runner.note("중복 writer가 될 container application service를 중지합니다.")
    runner.run(_compose_command(plan, ("stop", *CONTAINER_APPLICATION_SERVICES)))
    runner.note("PostgreSQL과 Keycloak을 loopback source-host 경계로 준비합니다.")
    mode_flags: tuple[str, ...]
    if plan.offline:
        mode_flags = ("--no-build", "--pull", "never")
    elif plan.local_image_reuse:
        mode_flags = ("--no-build", "--pull", "never")
    else:
        mode_flags = ("--build",)
    runner.run(
        _compose_command(
            plan,
            (
                "up",
                "-d",
                *mode_flags,
                "--wait",
                "postgres",
                "keycloak",
            ),
        )
    )
    runner.note("최종 loopback publication을 표시합니다.")
    show_status(runner, plan)
    if neo4j_environment is not None:
        runner.note("검증된 별도 AMD64 Neo4j image로 local graph connector를 준비합니다.")
        start_and_verify_neo4j(runner, plan, neo4j_environment)


def main() -> int:
    arguments = parse_arguments()
    runner = Runner(root=ROOT)
    try:
        require_command("docker")
        state: AppliedState | None = None
        force_local_image_reuse = arguments.reuse_local_images or arguments.connected_build
        if not force_local_image_reuse:
            applied_state_path = state_path(ROOT, arguments.profile)
            if applied_state_path.exists():
                state = load_applied_state(applied_state_path)
            elif arguments.env_file is None:
                raise WorkflowError(
                    "The applied workflow state is unavailable. Supply an explicit --env-file to "
                    "reuse already loaded local images without registry access, or complete the "
                    "managed offline setup first."
                )
        plan = resolve_plan(
            root=ROOT,
            state=state,
            env_file_override=arguments.env_file,
            reuse_local_images=force_local_image_reuse,
        )
        neo4j_bundle: Neo4jBundle | None = None
        neo4j_environment: dict[str, str] | None = None
        if arguments.neo4j_bundle_dir is not None and arguments.reuse_loaded_neo4j:
            raise WorkflowError(
                "--neo4j-bundle-dir and --reuse-loaded-neo4j are mutually exclusive."
            )
        if arguments.neo4j_bundle_dir is not None:
            if arguments.action != "prepare":
                raise WorkflowError("--neo4j-bundle-dir is supported only with the prepare action.")
            runner.note("별도 배포 Neo4j archive/checksum/manifest를 검증합니다.")
            neo4j_bundle = load_neo4j_bundle(arguments.neo4j_bundle_dir)
            runner.note("검증된 linux/amd64 Neo4j image를 로드하고 image ID를 대조합니다.")
            verify_and_load_neo4j_image(runner, neo4j_bundle)
            runner.note("Neo4j secret/port를 검증하고 source-host 환경을 확정합니다.")
            neo4j_environment = resolve_neo4j_environment(plan, neo4j_bundle.image)
        elif arguments.reuse_loaded_neo4j:
            if arguments.action != "prepare":
                raise WorkflowError("--reuse-loaded-neo4j is supported only with prepare.")
            runner.note("Docker에 이미 로드된 승인 Neo4j tag와 linux/amd64 platform을 검증합니다.")
            loaded_neo4j_image = configured_loaded_neo4j_image(plan)
            verify_loaded_neo4j_image(runner, loaded_neo4j_image)
            runner.note("Neo4j secret/port를 검증하고 source-host 환경을 확정합니다.")
            neo4j_environment = resolve_neo4j_environment(plan, loaded_neo4j_image)
        runner.note("선택 profile의 최종 Compose service image를 해석합니다.")
        service_images = rendered_service_images(runner, plan)
        if plan.offline:
            assert plan.release_platform_dir is not None
            runner.note("기록된 amd64 release checksum과 로컬 image identity를 검증합니다.")
            verify_offline_images(runner, plan.release_platform_dir, service_images)
        elif plan.local_image_reuse:
            runner.note(
                f"로컬-image 개발 경로에서 registry-disabled PostgreSQL image를 사용합니다: "
                f"{service_images['postgres']}"
            )
        if arguments.action == "config":
            runner.run(_compose_command(plan, ("config", "--images")))
        elif arguments.action == "status":
            show_status(runner, plan)
        else:
            prepare(runner, plan, service_images, neo4j_environment)
        return 0
    except (OSError, ValueError, WorkflowError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
