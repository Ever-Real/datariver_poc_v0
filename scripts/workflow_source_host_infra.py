#!/usr/bin/env python3
"""Prepare loopback-only infrastructure for source-host development."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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
    release_layout,
    require_command,
    require_regular_file,
    state_path,
)

SOURCE_INFRASTRUCTURE_SERVICES = ("postgres", "keycloak")
CONTAINER_APPLICATION_SERVICES = tuple(
    service for service in RUNTIME_SERVICES if service != "keycloak"
)
EXPECTED_OFFLINE_PLATFORM = "linux/amd64"


@dataclass(frozen=True)
class SourceHostInfraPlan:
    """Resolved infrastructure inputs hidden behind one operator action."""

    profile: str
    env_file: Path
    compose_files: tuple[Path, ...]
    offline: bool
    release_platform_dir: Path | None


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stop containerized DataRiver application processes and prepare PostgreSQL/Keycloak "
            "for loopback source-host access. Build and offline image references are resolved "
            "from the recorded profile state."
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
    return parser.parse_args()


def _resolve_path(root: Path, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def resolve_plan(
    *,
    root: Path,
    state: AppliedState,
    env_file_override: Path | None,
) -> SourceHostInfraPlan:
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
        release_platform_dir=layout.platform_dir,
    )


def verify_checksum(path: Path) -> None:
    artifact = path.with_suffix("")
    require_regular_file(path, label=f"{artifact.name} checksum")
    require_regular_file(artifact, label=artifact.name)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise WorkflowError(f"Checksum sidecar must contain exactly one entry: {path}")
    match = re.fullmatch(r"([0-9a-f]{64})[ \t]+[*]?(.+)", lines[0])
    if match is None or Path(match.group(2)).name != artifact.name:
        raise WorkflowError(f"Checksum sidecar has an invalid target: {path}")
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual != match.group(1):
        raise WorkflowError(f"Checksum mismatch: {artifact}")


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


def show_status(runner: Runner, plan: SourceHostInfraPlan) -> None:
    runner.run(_compose_command(plan, ("ps", "postgres", "keycloak")))
    runner.run(_compose_command(plan, ("port", "postgres", "5432")))
    runner.run(_compose_command(plan, ("port", "keycloak", "8080")))


def prepare(runner: Runner, plan: SourceHostInfraPlan) -> None:
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
    mode_flags = ("--no-build", "--pull", "never") if plan.offline else ("--build",)
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


def main() -> int:
    arguments = parse_arguments()
    runner = Runner(root=ROOT)
    try:
        require_command("docker")
        state = load_applied_state(state_path(ROOT, arguments.profile))
        plan = resolve_plan(
            root=ROOT,
            state=state,
            env_file_override=arguments.env_file,
        )
        runner.note("선택 profile의 최종 Compose service image를 해석합니다.")
        service_images = rendered_service_images(runner, plan)
        if plan.offline:
            assert plan.release_platform_dir is not None
            runner.note("기록된 amd64 release checksum과 로컬 image identity를 검증합니다.")
            verify_offline_images(runner, plan.release_platform_dir, service_images)
        if arguments.action == "config":
            runner.run(_compose_command(plan, ("config", "--images")))
        elif arguments.action == "status":
            show_status(runner, plan)
        else:
            prepare(runner, plan)
        return 0
    except (OSError, ValueError, WorkflowError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
