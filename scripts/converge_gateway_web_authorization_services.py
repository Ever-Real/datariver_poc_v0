#!/usr/bin/env python3
"""Converge only the existing Mac Web client's Authorization Services flag."""

from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import sys
import time
from pathlib import Path

from docker_capacity import exclusive_docker_workflow_lock
from platform_workflow import (
    ROOT,
    TOPOLOGY_RECONCILIATION_SECRET_NAMES,
    environment_key_hashes,
    load_applied_state,
    read_env_values,
    require_topology_reconciliation_secrets,
    state_path,
)
from probe_gateway_auth_parity import (
    GatewayWebAuthorizationServicesClassification,
    GatewayWebAuthorizationServicesConvergenceEvidence,
    GatewayWebAuthorizationServicesStatus,
    KeycloakGatewayAuthParityIdentity,
    ProductionWebInvariantPredicate,
    format_gateway_web_authorization_services_evidence,
)
from workflow_update_restart import _read_gateway_admin_password

PROFILE = "mac-development"
ENVIRONMENT_FILE = ".env.mac-development"
SECRET_NAMES = TOPOLOGY_RECONCILIATION_SECRET_NAMES
KEYCLOAK_CONTAINER = "datariver-next-keycloak-1"
KEYCLOAK_IMAGE = "datariver-keycloak:26.7.0"
KEYCLOAK_BASE_IMAGE = (
    "quay.io/keycloak/keycloak:26.7.0@sha256:"
    "2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0"
)
_DOCKER_OUTPUT_MAXIMUM_BYTES = 256 * 1024
_DOCKER_TIMEOUT_SECONDS = 20
_DOCKER_REAP_SECONDS = 5
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_OVERRIDE_ENVIRONMENT = (
    "DATARIVER_ENV_FILE",
    "DATARIVER_KEYCLOAK_CONTAINER",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "KEYCLOAK_CLIENT_ID",
    "KEYCLOAK_REALM",
    "KEYCLOAK_URL",
)


def _unknown_evidence(
    identity: KeycloakGatewayAuthParityIdentity | None = None,
) -> GatewayWebAuthorizationServicesConvergenceEvidence:
    return GatewayWebAuthorizationServicesConvergenceEvidence(
        classification=GatewayWebAuthorizationServicesClassification.UNKNOWN,
        predicate=ProductionWebInvariantPredicate.UNKNOWN,
        pre_status=GatewayWebAuthorizationServicesStatus.UNKNOWN,
        action_attempted=False,
        action_succeeded=False,
        mutation_outcome_known=False,
        post_status_known=False,
        post_status=None,
        fingerprint_equal_known=False,
        fingerprint_equal=None,
        admin_token_grant_attempts=(identity.admin_token_grant_attempts if identity else 0),
        admin_request_attempts=(identity.admin_request_attempts if identity else 0),
        mutation_count=0,
    )


def _operator_review_evidence(
    evidence: GatewayWebAuthorizationServicesConvergenceEvidence,
    identity: KeycloakGatewayAuthParityIdentity | None,
) -> GatewayWebAuthorizationServicesConvergenceEvidence:
    identity_attempted = bool(
        identity is not None
        and getattr(identity, "web_authorization_services_action_attempted", False)
    )
    action_attempted = evidence.action_attempted or identity_attempted
    if not action_attempted:
        return _unknown_evidence(identity)
    identity_succeeded = bool(
        identity is not None
        and getattr(identity, "web_authorization_services_action_succeeded", False)
    )
    action_succeeded = evidence.action_succeeded or identity_succeeded
    return GatewayWebAuthorizationServicesConvergenceEvidence(
        classification=GatewayWebAuthorizationServicesClassification.OPERATOR_REVIEW_REQUIRED,
        predicate=ProductionWebInvariantPredicate.UNKNOWN,
        pre_status=evidence.pre_status,
        action_attempted=True,
        action_succeeded=action_succeeded,
        mutation_outcome_known=action_succeeded,
        post_status_known=evidence.post_status_known,
        post_status=evidence.post_status,
        fingerprint_equal_known=evidence.fingerprint_equal_known,
        fingerprint_equal=evidence.fingerprint_equal,
        admin_token_grant_attempts=(
            identity.admin_token_grant_attempts
            if identity is not None
            else evidence.admin_token_grant_attempts
        ),
        admin_request_attempts=(
            identity.admin_request_attempts
            if identity is not None
            else evidence.admin_request_attempts
        ),
        mutation_count=1,
    )


class _ConvergenceRuntimeState:
    def __init__(self) -> None:
        self.identity: KeycloakGatewayAuthParityIdentity | None = None
        self.evidence = _unknown_evidence()


def _mac_environment() -> tuple[Path, int]:
    state = load_applied_state(state_path(ROOT, PROFILE))
    expected_environment = (ROOT / ENVIRONMENT_FILE).resolve()
    selected_environment = Path(state.env_file).expanduser()
    if not selected_environment.is_absolute():
        selected_environment = ROOT / selected_environment
    if (
        state.profile != PROFILE
        or state.deployment_mode != "build"
        or state.local_gateway
        or state.local_graph
        or state.applied_commit != state.runtime_commit
        or selected_environment.resolve() != expected_environment
    ):
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_CONTEXT_INVALID")
    values = read_env_values(expected_environment)
    if not state.environment_key_hashes or (
        environment_key_hashes(values) != state.environment_key_hashes
    ):
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_CONTEXT_INVALID")
    raw_port = values.get("KEYCLOAK_PORT", "8081")
    if not raw_port.isdecimal():
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_CONTEXT_INVALID")
    port = int(raw_port)
    if not 1 <= port <= 65_535 or str(port) != raw_port:
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_CONTEXT_INVALID")
    return expected_environment, port


def _bounded_docker_output(command: tuple[str, ...]) -> bytes:
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    completed = False
    try:
        process = subprocess.Popen(  # noqa: S603 - exact fixed Docker inspect argv only.
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if process.stdout is None:
            raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + _DOCKER_TIMEOUT_SECONDS
        output = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")
            events = selector.select(remaining)
            if not events:
                raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")
            chunk = os.read(
                process.stdout.fileno(),
                min(64 * 1024, _DOCKER_OUTPUT_MAXIMUM_BYTES - len(output) + 1),
            )
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > _DOCKER_OUTPUT_MAXIMUM_BYTES:
                raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")
        return_code = process.wait(timeout=_DOCKER_REAP_SECONDS)
        completed = True
        if return_code != 0:
            raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")
        return bytes(output)
    except RuntimeError:
        raise
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID") from None
    finally:
        if selector is not None:
            selector.close()
        if process is not None and not completed and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=_DOCKER_REAP_SECONDS)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                    process.wait(timeout=_DOCKER_REAP_SECONDS)
                except (OSError, subprocess.SubprocessError):
                    pass
        if process is not None and process.stdout is not None:
            process.stdout.close()


def _inspect_one(command: tuple[str, ...]) -> dict[str, object]:
    try:
        document = json.loads(_bounded_docker_output(command))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID") from None
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")
    return document[0]


def _require_pinned_keycloak_runtime() -> None:
    dockerfile = (ROOT / "infra" / "keycloak" / "Dockerfile").read_text(encoding="utf-8")
    if dockerfile.count(KEYCLOAK_BASE_IMAGE) != 2:
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")
    container = _inspect_one(
        ("docker", "--context", "default", "container", "inspect", KEYCLOAK_CONTAINER)
    )
    image = _inspect_one(("docker", "--context", "default", "image", "inspect", KEYCLOAK_IMAGE))
    container_config = container.get("Config")
    container_state = container.get("State")
    image_id = container.get("Image")
    image_config = image.get("Config")
    container_labels = (
        container_config.get("Labels") if isinstance(container_config, dict) else None
    )
    image_tags = image.get("RepoTags")
    if (
        not isinstance(container_config, dict)
        or not isinstance(container_state, dict)
        or not isinstance(image_config, dict)
        or not isinstance(container_labels, dict)
        or not isinstance(image_tags, list)
        or not all(isinstance(item, str) for item in image_tags)
        or not isinstance(image_id, str)
        or _IMAGE_ID.fullmatch(image_id) is None
        or container_config.get("Image") != KEYCLOAK_IMAGE
        or container_labels.get("com.docker.compose.project") != "datariver-next"
        or container_labels.get("com.docker.compose.service") != "keycloak"
        or container_state.get("Running") is not True
        or not isinstance(container_state.get("Health"), dict)
        or container_state["Health"].get("Status") != "healthy"
        or image.get("Id") != image_id
        or image.get("Os") != "linux"
        or image.get("Architecture") != "arm64"
        or image_config.get("User") != "1000"
        or KEYCLOAK_IMAGE not in image_tags
    ):
        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID")


def _run_convergence(
    runtime: _ConvergenceRuntimeState,
) -> GatewayWebAuthorizationServicesConvergenceEvidence:
    password = ""
    finalization_failed = False
    try:
        with exclusive_docker_workflow_lock(ROOT):
            try:
                _environment_file, keycloak_port = _mac_environment()
                _require_pinned_keycloak_runtime()
                with require_topology_reconciliation_secrets(ROOT) as guard:
                    guard.revalidate()
                    expected_names = set(SECRET_NAMES)
                    if (
                        len(SECRET_NAMES) != 8
                        or set(guard.file_descriptors) != expected_names
                        or set(guard.file_identities) != expected_names
                    ):
                        raise RuntimeError("GATEWAY_WEB_AUTHORIZATION_SERVICES_CONTEXT_INVALID")
                    password = _read_gateway_admin_password(guard)
                    guard.revalidate()
                    try:
                        runtime.identity = KeycloakGatewayAuthParityIdentity(
                            base_url=f"http://127.0.0.1:{keycloak_port}",
                            admin_username="datariver-bootstrap",
                            admin_password=password,
                        )
                        runtime.evidence = (
                            runtime.identity.converge_web_authorization_services_disabled()
                        )
                    except BaseException:
                        runtime.evidence = _operator_review_evidence(
                            runtime.evidence,
                            runtime.identity,
                        )
                    finally:
                        password = ""
                        try:
                            if runtime.identity is not None:
                                runtime.identity.release_without_mutation()
                        except BaseException:
                            finalization_failed = True
                        finally:
                            try:
                                guard.revalidate()
                            except BaseException:
                                finalization_failed = True
            except BaseException:
                finalization_failed = True
                runtime.evidence = _operator_review_evidence(
                    runtime.evidence,
                    runtime.identity,
                )
    except BaseException:
        finalization_failed = True
    if finalization_failed:
        runtime.evidence = _operator_review_evidence(runtime.evidence, runtime.identity)
    return runtime.evidence


def main() -> int:
    runtime = _ConvergenceRuntimeState()
    evidence = runtime.evidence
    if len(sys.argv) == 1 and not any(
        os.environ.get(key) for key in _FORBIDDEN_OVERRIDE_ENVIRONMENT
    ):
        try:
            evidence = _run_convergence(runtime)
        except BaseException:
            evidence = _operator_review_evidence(runtime.evidence, runtime.identity)
    print(format_gateway_web_authorization_services_evidence(evidence), flush=True)
    return 0 if evidence.classification is GatewayWebAuthorizationServicesClassification.PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
