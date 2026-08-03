#!/usr/bin/env python3
"""Apply one Git update and restart only affected DataRiver services."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from docker_capacity import (
    BuildCapacityPreflightPredicate,
    CapacityExecutor,
    DockerCapacityError,
    DockerCapacityMeasureOnlyStop,
    DockerCapacityMode,
    DockerCapacityPhaseError,
    DockerCapacityPhaseRecorder,
    DockerWorkflowLock,
    SubprocessCapacityExecutor,
    exclusive_docker_workflow_lock,
    governed_compose_build_capacity,
    require_no_active_builds,
)
from platform_workflow import (
    AIRFLOW_SERVICES,
    ROOT,
    WORKFLOW_PROFILE_NAMES,
    AppliedState,
    ChangePlan,
    Runner,
    TopologyReconciliationPlan,
    TopologyReconciliationSecretGuard,
    WorkflowError,
    build_local_topology_audit,
    build_topology_reconciliation_plan,
    capture_local_topology,
    changed_environment_keys,
    classify_changes,
    classify_environment_changes,
    compose_arguments,
    current_commit,
    enforce_local_topology,
    environment_key_hashes,
    load_applied_state,
    merge_change_plans,
    merge_no_proxy,
    prompt_confirm,
    read_env_values,
    release_layout,
    release_optional_compose,
    require_clean_worktree,
    require_command,
    require_regular_file,
    require_release_compatible_checkout,
    require_topology_reconciliation_secrets,
    requires_local_identity_bootstrap,
    select_restart_services,
    state_path,
    update_env_values,
    workflow_profile,
    write_applied_state,
)
from probe_gateway_auth_parity import (
    FIXTURE_CONTRACT,
    GATEWAY_LOG_TIMESTAMP_FORMAT,
    GatewayAuthParityError,
    GatewayAuthParityEvidence,
    GatewayAuthParitySession,
    GatewayAuthParityTraffic,
    GatewayCredentialLogEvidenceError,
    KeycloakGatewayAuthParityIdentity,
)

from datariver.gateway_auth_parity_fixture import (
    MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES,
    FixtureDiagnosticEnvelope,
    FixtureDiagnosticOperation,
    FixtureDiagnosticPredicate,
    FixtureDiagnosticProtocolError,
    current_fixture_source_sha256,
    fixture_diagnostic_failure_classification,
    parse_fixture_diagnostic_line,
    require_current_fixture_source,
)

DATAHUB_PROBE_PROGRAM = """\
import json
import os
import urllib.request
from pathlib import Path

base_url = os.environ["DATAHUB_BASE_URL"].rstrip("/")
token = Path("/run/secrets/datahub_token").read_text(encoding="utf-8").strip()
request = urllib.request.Request(
    base_url + "/config",
    headers={"Authorization": "Bearer " + token},
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(request, timeout=15) as response:
    document = json.load(response)
version = (
    document.get("versions", {})
    .get("acryldata/datahub", {})
    .get("version", "unknown")
)
print(f"DataHub GMS HTTP 200, version={version}")
"""

CATALOG_SYNC_PROGRAM = """\
import json
from datetime import UTC, datetime
from datariver_catalog_sync import synchronize_catalog_projection

run_id = "operator__update_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
result = synchronize_catalog_projection(run_id=run_id)
print(json.dumps(result, ensure_ascii=False, indent=2))
"""

HEALTH_PROGRAM = """\
import sys
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for url in sys.argv[1:]:
    with opener.open(url, timeout=10) as response:
        body = response.read(512).decode("utf-8", errors="replace").strip()
    print(f"{url} -> HTTP {response.status} {body}")
"""

GATEWAY_TRANSPARENCY_PROGRAM = """\
import sys
import urllib.error
import urllib.request

direct, gateway, web, origin = sys.argv[1:]
selected_headers = (
    "WWW-Authenticate",
    "Set-Cookie",
    "Access-Control-Allow-Origin",
    "Access-Control-Allow-Methods",
    "Access-Control-Allow-Headers",
    "Cache-Control",
    "Content-Type",
    "X-Request-Id",
)

def fail():
    raise SystemExit("GATEWAY_TRANSPARENCY_FAILED")

def request(base, path, *, method="GET", headers=None, data=None):
    selected = dict(headers or {})
    selected["X-Request-Id"] = "gateway-transparency-probe"
    value = urllib.request.Request(base + path, method=method, headers=selected, data=data)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(value, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    except (OSError, ValueError, urllib.error.URLError):
        fail()
    header_evidence = tuple(
        (name.casefold(), tuple(response.headers.get_all(name, [])))
        for name in selected_headers
    )
    return response.status, header_evidence

paths = ("/api/v1/knowledge/registry/assets", "/api/v1/change-requests")
for path in paths:
    for headers in (
        {},
        {
            "Authorization": "Bearer gateway-invalid-token-sentinel",
            "Cookie": "session=gateway-cookie-sentinel",
            "Origin": origin,
            "X-Gateway-Probe-Code": "gateway-code-sentinel",
            "X-Gateway-Probe-Secret": "gateway-secret-sentinel",
        },
    ):
        evidence = tuple(request(base, path, headers=headers) for base in (direct, gateway, web))
        if any(status != 401 for status, _ in evidence) or len(set(evidence)) != 1:
            fail()

body_evidence = tuple(
    request(
        base,
        paths[1],
        method="POST",
        headers={
            "Authorization": "Bearer gateway-invalid-token-sentinel",
            "Content-Type": "application/json",
        },
        data=b'{"probe":"gateway-body-secret-sentinel"}',
    )
    for base in (direct, gateway, web)
)
if any(status != 401 for status, _ in body_evidence) or len(set(body_evidence)) != 1:
    fail()

preflight_headers = {
    "Origin": origin,
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "authorization,x-request-id",
}
preflight = tuple(
    request(base, paths[0], method="OPTIONS", headers=preflight_headers)
    for base in (direct, gateway, web)
)
if len(set(preflight)) != 1 or preflight[0][0] not in (200, 204):
    fail()
print("GATEWAY_TRANSPARENCY_OK")
"""

_POSTGRES_SECRET_MOUNT_ENV_KEYS = frozenset(
    {
        "KNOWLEDGE_PROPOSAL_DATABASE_SECRET_REF",
    }
)
_DOCKER_DAEMON_PROBE = (
    "docker",
    "version",
    "--format",
    "{{.Server.Version}}",
)
_DOCKER_DAEMON_UNAVAILABLE = "DOCKER_DAEMON_UNAVAILABLE"
_COMPOSE_RUNNING_SERVICES_QUERY_FAILED = "COMPOSE_RUNNING_SERVICES_QUERY_FAILED"
_TOPOLOGY_RECONCILIATION = "mac-development-graph-gateway-v1"
_GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE = "GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE"
_GOVERNANCE_DOCUMENT_ROLE_QUERY = """\
password="$(tr -d '\\r\\n' </run/secrets/postgres_governance_document_password)"
export PGPASSWORD="$password"
exec psql --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 \
  --username datariver_governance_document --dbname "$POSTGRES_DB" \
  --command 'SELECT current_user;'
"""
_GOVERNANCE_DOCUMENT_BACKLOG_QUERY = """\
password="$(tr -d '\\r\\n' </run/secrets/postgres_governance_document_password)"
export PGPASSWORD="$password"
exec psql --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 \
  --username datariver_governance_document --dbname "$POSTGRES_DB" \
  --command "SELECT count(*)
    FROM governance.document_versions
    WHERE state = 'PUBLISHED'
      AND knowledge_state IN ('PENDING','FAILED')
      AND next_attempt_at <= clock_timestamp()
      AND (lease_until IS NULL OR lease_until <= clock_timestamp());"
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Optionally pull one fast-forward Git update, validate its runtime artifact, "
            "run migrations when needed, and recreate only affected services."
        )
    )
    parser.add_argument(
        "--profile",
        choices=WORKFLOW_PROFILE_NAMES,
        required=True,
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--release-dir",
        type=Path,
        help="New or retained immutable amd64 release directory for WSL.",
    )
    parser.add_argument(
        "--git-pull",
        action="store_true",
        help="Run git pull --ff-only before calculating the update.",
    )
    parser.add_argument(
        "--reload-release",
        action="store_true",
        help="Re-verify and reload the offline Core archive even if its commit is unchanged.",
    )
    parser.add_argument(
        "--refresh-bootstrap",
        action="store_true",
        help="Reapply bootstrap before Compose validation; existing secrets are preserved.",
    )
    parser.add_argument("--skip-catalog-sync", action="store_true")
    parser.add_argument("--assume-yes", action="store_true")
    parser.add_argument(
        "--reconcile-local-topology",
        choices=(_TOPOLOGY_RECONCILIATION,),
        help="Apply the sole reviewed Mac-development graph/gateway adoption.",
    )
    return parser.parse_args()


def _resolve_repo_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def _compose_files(state: AppliedState, *, release_override: Path | None) -> tuple[Path, ...]:
    files: tuple[Path, ...] = (ROOT / "compose.yaml", ROOT / "compose.identity.yaml")
    if state.local_gateway:
        files = (
            *files,
            ROOT / "compose.gateway.yaml",
            ROOT / "compose.gateway-routing.yaml",
        )
    if state.deployment_mode == "build":
        return files
    release_dir = release_override or (
        Path(state.release_dir) if state.release_dir is not None else None
    )
    if release_dir is None:
        raise WorkflowError("The offline state has no release directory.")
    layout = release_layout(release_dir, architecture="amd64")
    return (*files, layout.offline_compose)


def _airflow_compose_files(
    files: tuple[Path, ...],
    *,
    local_gateway: bool,
) -> tuple[Path, ...]:
    selected = (*files, ROOT / "compose.airflow.yaml")
    if local_gateway:
        selected = (*selected, ROOT / "compose.airflow.host-dev.yaml")
    return tuple(dict.fromkeys(selected))


def _private_compose_output(
    *,
    env_file: Path,
    files: tuple[Path, ...],
    trailing: tuple[str, ...],
    classification: str,
) -> str:
    command = [
        os.fspath(argument)
        for argument in compose_arguments(
            env_file=env_file,
            compose_files=files,
            trailing=trailing,
        )
    ]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, never a shell on the host.
            command,
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise WorkflowError(classification) from None
    output = result.stdout.strip()
    if len(output.encode("utf-8")) > 256 or "\n" in output or "\r" in output:
        raise WorkflowError(classification)
    return output


def _verify_governance_document_worker_database(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    role = _private_compose_output(
        env_file=env_file,
        files=files,
        trailing=(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-ec",
            _GOVERNANCE_DOCUMENT_ROLE_QUERY,
        ),
        classification="GOVERNANCE_DOCUMENT_DATABASE_ROLE_INVALID",
    )
    if role != "datariver_governance_document":
        raise WorkflowError("GOVERNANCE_DOCUMENT_DATABASE_ROLE_INVALID")
    raw_backlog = _private_compose_output(
        env_file=env_file,
        files=files,
        trailing=(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-ec",
            _GOVERNANCE_DOCUMENT_BACKLOG_QUERY,
        ),
        classification="GOVERNANCE_DOCUMENT_BACKLOG_INVALID",
    )
    if not raw_backlog.isascii() or not raw_backlog.isdecimal():
        raise WorkflowError("GOVERNANCE_DOCUMENT_BACKLOG_INVALID")
    backlog = int(raw_backlog)
    if backlog > 1_000_000_000:
        raise WorkflowError("GOVERNANCE_DOCUMENT_BACKLOG_INVALID")
    runner.note(f"Governance document worker database role/backlog verified count={backlog}")


_GATEWAY_LOG_MAXIMUM_BYTES = 256 * 1024
_GATEWAY_LOG_TIMEOUT_SECONDS = 20
_GATEWAY_LOG_REAP_SECONDS = 5


def _bounded_gateway_log_output(command: tuple[str, ...]) -> bytes:
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    completed = False
    try:
        process = subprocess.Popen(  # noqa: S603 - repository-owned Compose argv only.
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if process.stdout is None:
            raise GatewayCredentialLogEvidenceError(evidence_known=False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + _GATEWAY_LOG_TIMEOUT_SECONDS
        output = bytearray()
        while True:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise GatewayCredentialLogEvidenceError(evidence_known=False)
            events = selector.select(remaining_time)
            if not events:
                raise GatewayCredentialLogEvidenceError(evidence_known=False)
            chunk = os.read(
                process.stdout.fileno(),
                min(64 * 1024, _GATEWAY_LOG_MAXIMUM_BYTES - len(output) + 1),
            )
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > _GATEWAY_LOG_MAXIMUM_BYTES:
                raise GatewayCredentialLogEvidenceError(evidence_known=False)
        return_code = process.wait(timeout=_GATEWAY_LOG_REAP_SECONDS)
        completed = True
        if return_code != 0:
            raise GatewayCredentialLogEvidenceError(evidence_known=False)
        return bytes(output)
    except GatewayCredentialLogEvidenceError:
        raise
    except (OSError, subprocess.SubprocessError):
        raise GatewayCredentialLogEvidenceError(evidence_known=False) from None
    finally:
        if selector is not None:
            selector.close()
        if process is not None and not completed and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=_GATEWAY_LOG_REAP_SECONDS)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                    process.wait(timeout=_GATEWAY_LOG_REAP_SECONDS)
                except (OSError, subprocess.SubprocessError):
                    pass
        if process is not None and process.stdout is not None:
            process.stdout.close()


def _verify_gateway_logs_do_not_persist_probe_credentials(
    *,
    env_file: Path,
    files: tuple[Path, ...],
    started_at: str,
    sentinels: tuple[str, ...] = (
        "gateway-invalid-token-sentinel",
        "gateway-cookie-sentinel",
        "gateway-code-sentinel",
        "gateway-secret-sentinel",
        "gateway-body-secret-sentinel",
    ),
) -> None:
    try:
        parsed_started_at = datetime.strptime(started_at, GATEWAY_LOG_TIMESTAMP_FORMAT)
    except ValueError:
        raise GatewayCredentialLogEvidenceError(evidence_known=False) from None
    if parsed_started_at.strftime(GATEWAY_LOG_TIMESTAMP_FORMAT) != started_at:
        raise GatewayCredentialLogEvidenceError(evidence_known=False)
    if len(sentinels) > 16 or any(
        not value or len(value.encode("utf-8")) > 16_384 for value in sentinels
    ):
        raise GatewayCredentialLogEvidenceError(evidence_known=False)
    command = tuple(
        os.fspath(argument)
        for argument in compose_arguments(
            env_file=env_file,
            compose_files=files,
            trailing=(
                "logs",
                "--no-color",
                "--since",
                started_at,
                "api",
                "apisix",
                "web",
            ),
        )
    )
    combined = _bounded_gateway_log_output(command)
    for sentinel in sentinels:
        if sentinel.encode("utf-8") in combined:
            raise GatewayCredentialLogEvidenceError(evidence_known=True)


def _verify_gateway_transparency(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    values = read_env_values(env_file)
    api_port = values.get("API_PORT", "8000")
    gateway_port = values.get("APISIX_PORT", "9080")
    web_port = values.get("WEB_PORT", "8080")
    origin = values.get("APP_PUBLIC_ORIGIN", f"http://127.0.0.1:{web_port}")
    started_at = datetime.now(UTC).strftime(GATEWAY_LOG_TIMESTAMP_FORMAT)
    runner.run(
        (
            sys.executable,
            "-",
            f"http://127.0.0.1:{api_port}",
            f"http://127.0.0.1:{gateway_port}",
            f"http://127.0.0.1:{web_port}",
            origin,
        ),
        input_text=GATEWAY_TRANSPARENCY_PROGRAM,
    )
    _verify_gateway_logs_do_not_persist_probe_credentials(
        env_file=env_file,
        files=files,
        started_at=started_at,
    )
    # This remains a routing/header negative. The ephemeral PKCE session is the only
    # accepted positive human authentication and revocation evidence.


def _require_gateway_auth_parity_evidence_available(reconciliation_name: str | None) -> None:
    """Accept only the reviewed exact fixture-backed reconciliation source contract."""

    if reconciliation_name is not None and reconciliation_name != _TOPOLOGY_RECONCILIATION:
        raise WorkflowError(_GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE)


_FIXTURE_DIAGNOSTIC_TIMEOUT_SECONDS = 30
_FIXTURE_DIAGNOSTIC_REAP_SECONDS = 5
_FIXTURE_DIAGNOSTIC_BUILD_TIMEOUT_SECONDS = 20 * 60
MAXIMUM_FIXTURE_EXECUTION_EVIDENCE_BYTES = 2_048
_FIXTURE_DIAGNOSTIC_CONTAINER_NAME = "datariver-gateway-auth-parity-require-absent"
_FIXTURE_DIAGNOSTIC_CONTAINER_CONTRACT_LABEL = f"datariver.fixture.contract={FIXTURE_CONTRACT}"
_FIXTURE_DIAGNOSTIC_CONTAINER_OPERATION_LABEL = "datariver.fixture.operation=REQUIRE_ABSENT"
_HOST_ENVIRONMENT_PREFLIGHT_ARGUMENTS = (
    "--diagnostic-phase",
    "HOST_ENVIRONMENT_PREFLIGHT",
)
_BUILD_CAPACITY_PREFLIGHT_ARGUMENTS = (
    "--diagnostic-phase",
    "BUILD_CAPACITY_PREFLIGHT",
)
_DIAGNOSTIC_PHASE_EQUALS_PREFIX = "--diagnostic-phase="
_BUILD_CAPACITY_PREFLIGHT_EQUALS_PREFIX = (
    _DIAGNOSTIC_PHASE_EQUALS_PREFIX + "BUILD_CAPACITY_PREFLIGHT"
)
_HOST_ENVIRONMENT_PREFLIGHT_EQUALS_PREFIX = (
    _DIAGNOSTIC_PHASE_EQUALS_PREFIX + "HOST_ENVIRONMENT_PREFLIGHT"
)
MAXIMUM_HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_BYTES = 256
MAXIMUM_BUILD_CAPACITY_PREFLIGHT_EVIDENCE_BYTES = 384


class FixtureDiagnosticExecutionClassification(StrEnum):
    PASS = "PASS"  # noqa: S105 - fixed diagnostic classification, not a secret.
    REJECTED = "REJECTED"
    OPERATOR_REVIEW_REQUIRED = "OPERATOR_REVIEW_REQUIRED"


class HostEnvironmentPreflightClassification(StrEnum):
    PASS = "PASS"  # noqa: S105 - fixed diagnostic classification, not a secret.
    REJECTED = "REJECTED"
    OPERATOR_REVIEW_REQUIRED = "OPERATOR_REVIEW_REQUIRED"


class BuildCapacityPreflightClassification(StrEnum):
    PASS = "PASS"  # noqa: S105 - fixed diagnostic classification, not a secret.
    REJECTED = "REJECTED"
    OPERATOR_REVIEW_REQUIRED = "OPERATOR_REVIEW_REQUIRED"


class HostEnvironmentPreflightPhase(StrEnum):
    HOST_ENVIRONMENT_PREFLIGHT = "HOST_ENVIRONMENT_PREFLIGHT"


class BuildCapacityPreflightPhase(StrEnum):
    BUILD_CAPACITY_PREFLIGHT = "BUILD_CAPACITY_PREFLIGHT"


class HostEnvironmentPreflightPredicate(StrEnum):
    APPLIED_STATE_CONTRACT = "APPLIED_STATE_CONTRACT"
    PROFILE_SELECTION = "PROFILE_SELECTION"
    DEPLOYMENT_MODE_SELECTION = "DEPLOYMENT_MODE_SELECTION"
    GATEWAY_SELECTION = "GATEWAY_SELECTION"
    GRAPH_SELECTION = "GRAPH_SELECTION"
    ENV_PATH_CONTRACT = "ENV_PATH_CONTRACT"
    ENV_FILE_CONTRACT = "ENV_FILE_CONTRACT"
    ENV_READ = "ENV_READ"
    ENV_FINGERPRINT = "ENV_FINGERPRINT"
    COMPOSE_SELECTION = "COMPOSE_SELECTION"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


class _FixtureContainerState(StrEnum):
    ABSENT = "ABSENT"
    OWNED_RUNNING = "OWNED_RUNNING"
    OWNED_STOPPED = "OWNED_STOPPED"
    FOREIGN = "FOREIGN"
    UNKNOWN = "UNKNOWN"


class _FixtureSourceCleanState(StrEnum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class _DockerActionOutcome:
    succeeded: bool
    outcome_known: bool


@dataclass(frozen=True, slots=True)
class _FixtureBuildOutcome:
    attempted: bool
    succeeded: bool
    outcome_known: bool


@dataclass(frozen=True, slots=True)
class HostEnvironmentPreflightEvidence:
    classification: HostEnvironmentPreflightClassification
    phase: HostEnvironmentPreflightPhase
    predicate: HostEnvironmentPreflightPredicate
    mutation_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        if (
            self.phase is not HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT
            or type(self.mutation_count) is not int
            or self.mutation_count != 0
            or type(self.retry_count) is not int
            or self.retry_count != 0
            or (
                self.classification is HostEnvironmentPreflightClassification.PASS
                and self.predicate is not HostEnvironmentPreflightPredicate.PASS
            )
            or (
                self.classification is HostEnvironmentPreflightClassification.REJECTED
                and self.predicate is HostEnvironmentPreflightPredicate.PASS
            )
            or (
                self.classification
                is HostEnvironmentPreflightClassification.OPERATOR_REVIEW_REQUIRED
                and self.predicate is not HostEnvironmentPreflightPredicate.UNKNOWN
            )
        ):
            raise WorkflowError("HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_INVALID")


@dataclass(frozen=True, slots=True)
class BuildCapacityPreflightEvidence:
    classification: BuildCapacityPreflightClassification
    phase: BuildCapacityPreflightPhase
    predicate: BuildCapacityPreflightPredicate
    mutation_count: int = 0
    cache_action_count: int = 0
    build_count: int = 0
    container_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        counts = (
            self.mutation_count,
            self.cache_action_count,
            self.build_count,
            self.container_count,
            self.retry_count,
        )
        if (
            self.phase is not BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT
            or any(type(value) is not int or value != 0 for value in counts)
            or (
                self.classification is BuildCapacityPreflightClassification.PASS
                and self.predicate is not BuildCapacityPreflightPredicate.PASS
            )
            or (
                self.classification is BuildCapacityPreflightClassification.REJECTED
                and self.predicate is BuildCapacityPreflightPredicate.PASS
            )
            or (
                self.classification is BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED
                and self.predicate is not BuildCapacityPreflightPredicate.UNKNOWN
            )
        ):
            raise WorkflowError("BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID")


@dataclass(frozen=True, slots=True)
class _HostEnvironmentPreflightResult:
    evidence: HostEnvironmentPreflightEvidence
    state: AppliedState | None = None
    env_file: Path | None = None
    files: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        passed = self.evidence.predicate is HostEnvironmentPreflightPredicate.PASS
        if passed != (self.state is not None and self.env_file is not None and bool(self.files)):
            raise WorkflowError("HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_INVALID")


@dataclass(frozen=True, slots=True)
class FixtureDiagnosticExecutionEvidence:
    classification: FixtureDiagnosticExecutionClassification
    operation: FixtureDiagnosticOperation
    predicate: FixtureDiagnosticPredicate
    cache_action_count_known: bool
    cache_action_count: int | None
    cache_action_succeeded: bool
    cache_action_outcome_known: bool
    build_attempted: bool
    build_succeeded: bool
    build_outcome_known: bool
    builder_idle_known: bool
    builder_idle: bool
    container_attempted: bool
    container_stop_attempts: int
    container_remove_attempts: int
    container_cleanup_known: bool
    container_cleanup_required: bool
    container_residual_known: bool
    container_residual_count: int | None
    business_mutation_count: int = 0
    data_mutation_count: int = 0
    identity_mutation_count: int = 0
    topology_mutation_count: int = 0
    state_mutation_count: int = 0
    push_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        boolean_fields = (
            self.cache_action_count_known,
            self.cache_action_succeeded,
            self.cache_action_outcome_known,
            self.build_attempted,
            self.build_succeeded,
            self.build_outcome_known,
            self.builder_idle_known,
            self.builder_idle,
            self.container_attempted,
            self.container_cleanup_known,
            self.container_cleanup_required,
            self.container_residual_known,
        )
        bounded_counts = (
            self.container_stop_attempts,
            self.container_remove_attempts,
            self.business_mutation_count,
            self.data_mutation_count,
            self.identity_mutation_count,
            self.topology_mutation_count,
            self.state_mutation_count,
            self.push_count,
            self.retry_count,
        )
        if (
            any(type(value) is not bool for value in boolean_fields)
            or any(type(value) is not int or value < 0 or value > 1 for value in bounded_counts)
            or self.operation is not FixtureDiagnosticOperation.REQUIRE_ABSENT
            or (self.cache_action_count_known and self.cache_action_count not in {0, 1})
            or (not self.cache_action_count_known and self.cache_action_count is not None)
            or (
                self.cache_action_succeeded
                and (
                    not self.cache_action_count_known
                    or self.cache_action_count != 1
                    or not self.cache_action_outcome_known
                )
            )
            or (not self.cache_action_count_known and self.cache_action_outcome_known)
            or (self.build_succeeded and (not self.build_attempted or not self.build_outcome_known))
            or (self.builder_idle and not self.builder_idle_known)
            or (
                not self.container_attempted
                and (self.container_stop_attempts != 0 or self.container_remove_attempts != 0)
            )
            or (not self.container_cleanup_known and not self.container_cleanup_required)
            or (self.container_residual_known and self.container_residual_count not in {0, 1})
            or (not self.container_residual_known and self.container_residual_count is not None)
            or any(
                value != 0
                for value in (
                    self.business_mutation_count,
                    self.data_mutation_count,
                    self.identity_mutation_count,
                    self.topology_mutation_count,
                    self.state_mutation_count,
                    self.push_count,
                    self.retry_count,
                )
            )
        ):
            raise WorkflowError("GATEWAY_AUTH_PARITY_FIXTURE_DIAGNOSTIC_INVALID")


@dataclass(slots=True)
class _FixtureDiagnosticExecutionState:
    cache_action_count_known: bool = True
    cache_action_count: int | None = 0
    cache_action_succeeded: bool = False
    cache_action_outcome_known: bool = True
    build_attempted: bool = False
    build_succeeded: bool = False
    build_outcome_known: bool = True
    builder_idle_known: bool = False
    builder_idle: bool = False
    container_attempted: bool = False
    container_stop_attempts: int = 0
    container_remove_attempts: int = 0
    container_cleanup_known: bool = True
    container_cleanup_required: bool = False
    container_residual_known: bool = True
    container_residual_count: int | None = 0
    operator_review_required: bool = False

    @property
    def container_cleanup_proven(self) -> bool:
        return (
            self.container_attempted
            and self.container_cleanup_known
            and not self.container_cleanup_required
            and self.container_residual_known
            and self.container_residual_count == 0
        )

    def to_evidence(
        self,
        predicate: FixtureDiagnosticPredicate,
    ) -> FixtureDiagnosticExecutionEvidence:
        review_required = (
            self.operator_review_required
            or not self.cache_action_count_known
            or (self.cache_action_count == 1 and not self.cache_action_outcome_known)
        )
        if self.build_attempted and (
            not self.build_outcome_known or not self.builder_idle_known or not self.builder_idle
        ):
            review_required = True
        if self.container_attempted and not self.container_cleanup_proven:
            review_required = True
        if not self.container_attempted and self.container_cleanup_required:
            review_required = True
        if predicate is FixtureDiagnosticPredicate.PASS and (
            not self.build_attempted
            or not self.build_succeeded
            or not self.build_outcome_known
            or not self.builder_idle_known
            or not self.builder_idle
            or not self.container_cleanup_proven
        ):
            review_required = True
        classification = (
            FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED
            if review_required
            else (
                FixtureDiagnosticExecutionClassification.PASS
                if predicate is FixtureDiagnosticPredicate.PASS
                else FixtureDiagnosticExecutionClassification.REJECTED
            )
        )
        return FixtureDiagnosticExecutionEvidence(
            classification=classification,
            operation=FixtureDiagnosticOperation.REQUIRE_ABSENT,
            predicate=predicate,
            cache_action_count_known=self.cache_action_count_known,
            cache_action_count=self.cache_action_count,
            cache_action_succeeded=self.cache_action_succeeded,
            cache_action_outcome_known=self.cache_action_outcome_known,
            build_attempted=self.build_attempted,
            build_succeeded=self.build_succeeded,
            build_outcome_known=self.build_outcome_known,
            builder_idle_known=self.builder_idle_known,
            builder_idle=self.builder_idle,
            container_attempted=self.container_attempted,
            container_stop_attempts=self.container_stop_attempts,
            container_remove_attempts=self.container_remove_attempts,
            container_cleanup_known=self.container_cleanup_known,
            container_cleanup_required=self.container_cleanup_required,
            container_residual_known=self.container_residual_known,
            container_residual_count=self.container_residual_count,
        )


def format_fixture_diagnostic_execution_line(
    evidence: FixtureDiagnosticExecutionEvidence,
) -> str:
    line = json.dumps(
        {
            "build_attempted": evidence.build_attempted,
            "build_outcome_known": evidence.build_outcome_known,
            "build_succeeded": evidence.build_succeeded,
            "builder_idle": evidence.builder_idle,
            "builder_idle_known": evidence.builder_idle_known,
            "business_mutation_count": evidence.business_mutation_count,
            "cache_action_count": evidence.cache_action_count,
            "cache_action_count_known": evidence.cache_action_count_known,
            "cache_action_succeeded": evidence.cache_action_succeeded,
            "cache_action_outcome_known": evidence.cache_action_outcome_known,
            "classification": evidence.classification.value,
            "container_attempted": evidence.container_attempted,
            "container_cleanup_known": evidence.container_cleanup_known,
            "container_cleanup_required": evidence.container_cleanup_required,
            "container_remove_attempts": evidence.container_remove_attempts,
            "container_residual_count": evidence.container_residual_count,
            "container_residual_known": evidence.container_residual_known,
            "container_stop_attempts": evidence.container_stop_attempts,
            "data_mutation_count": evidence.data_mutation_count,
            "identity_mutation_count": evidence.identity_mutation_count,
            "operation": evidence.operation.value,
            "predicate": evidence.predicate.value,
            "push_count": evidence.push_count,
            "retry_count": evidence.retry_count,
            "state_mutation_count": evidence.state_mutation_count,
            "topology_mutation_count": evidence.topology_mutation_count,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(line.encode("utf-8")) > MAXIMUM_FIXTURE_EXECUTION_EVIDENCE_BYTES:
        raise WorkflowError("GATEWAY_AUTH_PARITY_FIXTURE_DIAGNOSTIC_INVALID")
    return line


class _FixtureDiagnosticCapacityExecutor:
    def __init__(self, delegate: CapacityExecutor | None = None) -> None:
        self._delegate = delegate or SubprocessCapacityExecutor()
        self.action_count_known = True
        self.action_count = 0
        self.action_succeeded = False
        self.action_outcome_known = True

    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str:
        is_cache_action = arguments[:3] == ("docker", "buildx", "prune")
        if is_cache_action:
            if self.action_count != 0:
                self.action_count_known = False
                self.action_outcome_known = False
                raise DockerCapacityError("DOCKER_BUILD_CACHE_ACTION_COUNT_INVALID")
            self.action_count = 1
            self.action_succeeded = False
        try:
            result = self._delegate.output(
                arguments,
                classification=classification,
                timeout_seconds=timeout_seconds,
            )
        except BaseException:
            if is_cache_action:
                self.action_outcome_known = False
            raise
        if is_cache_action:
            self.action_succeeded = True
            self.action_outcome_known = True
        return result


class _BuildCapacityPreflightExecutor:
    """Permit canonical read-only probes while structurally refusing cache mutation."""

    def __init__(self, delegate: CapacityExecutor | None = None) -> None:
        self._delegate = delegate or SubprocessCapacityExecutor()

    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str:
        if arguments == ("docker", "buildx", "prune", "--help"):
            return self._delegate.output(
                arguments,
                classification=classification,
                timeout_seconds=timeout_seconds,
            )
        if arguments[:3] == ("docker", "buildx", "prune"):
            raise DockerCapacityError("BUILD_CAPACITY_PREFLIGHT_MUTATION_FORBIDDEN")
        return self._delegate.output(
            arguments,
            classification=classification,
            timeout_seconds=timeout_seconds,
        )


def _bounded_fixture_diagnostic_process(
    command: tuple[str, ...],
    input_text: str,
) -> subprocess.CompletedProcess[str] | FixtureDiagnosticPredicate:
    """Capture both diagnostic streams under hard in-flight caps and fixed reaping."""

    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    completed = False
    failure: FixtureDiagnosticPredicate | None = None
    result: subprocess.CompletedProcess[str] | None = None
    stdout = bytearray()
    stderr = bytearray()
    try:
        encoded_input = input_text.encode("utf-8")
        if not encoded_input or len(encoded_input) > 4_096:
            return FixtureDiagnosticPredicate.FIXED_INPUT_PROTOCOL
        process = subprocess.Popen(  # noqa: S603 - fixed repository-owned Compose argv.
            command,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise OSError
        try:
            process.stdin.write(encoded_input)
            process.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ, stderr)
        deadline = time.monotonic() + _FIXTURE_DIAGNOSTIC_TIMEOUT_SECONDS
        while selector.get_map():
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                failure = FixtureDiagnosticPredicate.PROCESS_TIMEOUT
                break
            events = selector.select(remaining_time)
            if not events:
                failure = FixtureDiagnosticPredicate.PROCESS_TIMEOUT
                break
            for key, _mask in events:
                target = key.data
                assert isinstance(target, bytearray)
                combined_size = len(stdout) + len(stderr)
                chunk = os.read(
                    key.fd,
                    min(
                        64 * 1024,
                        MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES + 1 - combined_size,
                    ),
                )
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target.extend(chunk)
                if len(stdout) + len(stderr) > MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES:
                    failure = FixtureDiagnosticPredicate.OUTPUT_SIZE
                    break
            if failure is not None:
                break
        if failure is None:
            return_code = process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)
            completed = True
            try:
                decoded_stdout = stdout.decode("utf-8")
                decoded_stderr = stderr.decode("utf-8")
            except UnicodeDecodeError:
                failure = FixtureDiagnosticPredicate.OUTPUT_JSON
            else:
                result = subprocess.CompletedProcess(
                    command,
                    return_code,
                    decoded_stdout,
                    decoded_stderr,
                )
    except OSError:
        failure = (
            FixtureDiagnosticPredicate.PROCESS_SPAWN
            if process is None
            else FixtureDiagnosticPredicate.UNKNOWN
        )
    except subprocess.TimeoutExpired:
        failure = FixtureDiagnosticPredicate.PROCESS_TIMEOUT
    except BaseException:
        failure = FixtureDiagnosticPredicate.UNKNOWN
    finally:
        if selector is not None:
            try:
                selector.close()
            except BaseException:
                failure = FixtureDiagnosticPredicate.UNKNOWN
        if process is not None and not completed and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)
                completed = True
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                    process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)
                    completed = True
                except (OSError, subprocess.SubprocessError):
                    failure = FixtureDiagnosticPredicate.UNKNOWN
        if process is not None:
            for child_stream in (process.stdin, process.stdout, process.stderr):
                if child_stream is not None and not child_stream.closed:
                    try:
                        child_stream.close()
                    except BaseException:
                        failure = FixtureDiagnosticPredicate.UNKNOWN
    if failure is not None:
        return failure
    assert result is not None
    return result


def _bounded_suppressed_fixture_build(command: tuple[str, ...]) -> _FixtureBuildOutcome:
    """Run one fixed build without retaining output or erasing ambiguous delivery."""

    process: subprocess.Popen[bytes] | None = None
    completed = False
    succeeded = False
    outcome_known = True
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed repository-owned Compose argv.
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        succeeded = process.wait(timeout=_FIXTURE_DIAGNOSTIC_BUILD_TIMEOUT_SECONDS) == 0
        completed = True
    except OSError:
        succeeded = False
        outcome_known = process is None
    except subprocess.TimeoutExpired:
        outcome_known = False
    except BaseException:
        outcome_known = False
    finally:
        if process is not None and not completed and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)
                completed = True
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                    process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)
                    completed = True
                except (OSError, subprocess.SubprocessError):
                    outcome_known = False
    return _FixtureBuildOutcome(
        attempted=True,
        succeeded=succeeded,
        outcome_known=outcome_known,
    )


def _build_current_fixture_image(
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> _FixtureBuildOutcome:
    command = tuple(
        os.fspath(argument)
        for argument in compose_arguments(
            env_file=env_file,
            compose_files=files,
            profiles=("tools",),
            trailing=("build", "local-bootstrap"),
        )
    )
    return _bounded_suppressed_fixture_build(command)


def _fixture_diagnostic_source_state() -> _FixtureSourceCleanState:
    result = _bounded_fixture_diagnostic_process(
        ("git", "status", "--porcelain", "--untracked-files=normal"),
        "{}",
    )
    if result is FixtureDiagnosticPredicate.UNKNOWN:
        return _FixtureSourceCleanState.UNKNOWN
    if not isinstance(result, subprocess.CompletedProcess):
        return _FixtureSourceCleanState.INVALID
    if result.returncode != 0 or result.stderr != "":
        return _FixtureSourceCleanState.INVALID
    if result.stdout != "":
        return _FixtureSourceCleanState.DIRTY
    return _FixtureSourceCleanState.CLEAN


def _fixture_diagnostic_source_is_clean() -> bool:
    return _fixture_diagnostic_source_state() is _FixtureSourceCleanState.CLEAN


def _fixed_diagnostic_stream(raw: str) -> str | None:
    if not raw:
        return ""
    if raw.endswith("\n"):
        raw = raw[:-1]
    if not raw or "\n" in raw or "\r" in raw:
        return None
    return raw


def _fixture_container_snapshot() -> _FixtureContainerState:
    listing = _bounded_fixture_diagnostic_process(
        (
            "docker",
            "container",
            "ls",
            "--all",
            "--filter",
            f"name=^/{_FIXTURE_DIAGNOSTIC_CONTAINER_NAME}$",
            "--format",
            "{{.Names}}",
        ),
        "{}",
    )
    if (
        not isinstance(listing, subprocess.CompletedProcess)
        or listing.returncode != 0
        or listing.stderr
    ):
        return _FixtureContainerState.UNKNOWN
    listed_name = _fixed_diagnostic_stream(listing.stdout)
    if listed_name == "":
        return _FixtureContainerState.ABSENT
    if listed_name != _FIXTURE_DIAGNOSTIC_CONTAINER_NAME:
        return _FixtureContainerState.UNKNOWN
    inspected = _bounded_fixture_diagnostic_process(
        (
            "docker",
            "container",
            "inspect",
            "--format",
            (
                "{{json .State.Status}}|{{json (index .Config.Labels "
                '"datariver.fixture.contract")}}|{{json (index .Config.Labels '
                '"datariver.fixture.operation")}}'
            ),
            _FIXTURE_DIAGNOSTIC_CONTAINER_NAME,
        ),
        "{}",
    )
    if (
        not isinstance(inspected, subprocess.CompletedProcess)
        or inspected.returncode != 0
        or inspected.stderr
    ):
        return _FixtureContainerState.UNKNOWN
    inspected_line = _fixed_diagnostic_stream(inspected.stdout)
    if inspected_line is None:
        return _FixtureContainerState.UNKNOWN
    parts = inspected_line.split("|")
    if len(parts) != 3:
        return _FixtureContainerState.UNKNOWN
    try:
        status, contract, operation = tuple(json.loads(part) for part in parts)
    except (json.JSONDecodeError, TypeError):
        return _FixtureContainerState.UNKNOWN
    if not all(isinstance(value, str) for value in (status, contract, operation)):
        return _FixtureContainerState.UNKNOWN
    if contract != FIXTURE_CONTRACT or operation != "REQUIRE_ABSENT":
        return _FixtureContainerState.FOREIGN
    if status in {"running", "restarting", "paused"}:
        return _FixtureContainerState.OWNED_RUNNING
    if status in {"created", "exited", "dead"}:
        return _FixtureContainerState.OWNED_STOPPED
    return _FixtureContainerState.UNKNOWN


def _fixed_docker_action(command: tuple[str, ...]) -> _DockerActionOutcome:
    result = _bounded_fixture_diagnostic_process(command, "{}")
    if isinstance(result, subprocess.CompletedProcess):
        return _DockerActionOutcome(
            succeeded=result.returncode == 0,
            outcome_known=True,
        )
    return _DockerActionOutcome(
        succeeded=False,
        outcome_known=result
        in {
            FixtureDiagnosticPredicate.FIXED_INPUT_PROTOCOL,
            FixtureDiagnosticPredicate.PROCESS_SPAWN,
        },
    )


def _stop_fixture_container() -> _DockerActionOutcome:
    return _fixed_docker_action(
        (
            "docker",
            "container",
            "stop",
            "--time",
            "10",
            _FIXTURE_DIAGNOSTIC_CONTAINER_NAME,
        )
    )


def _remove_fixture_container() -> _DockerActionOutcome:
    return _fixed_docker_action(("docker", "container", "rm", _FIXTURE_DIAGNOSTIC_CONTAINER_NAME))


def _record_fixture_container_residual(
    execution: _FixtureDiagnosticExecutionState,
    snapshot: _FixtureContainerState,
) -> None:
    if snapshot is _FixtureContainerState.ABSENT:
        execution.container_cleanup_known = True
        execution.container_cleanup_required = False
        execution.container_residual_known = True
        execution.container_residual_count = 0
    elif snapshot in {
        _FixtureContainerState.OWNED_RUNNING,
        _FixtureContainerState.OWNED_STOPPED,
        _FixtureContainerState.FOREIGN,
    }:
        execution.container_cleanup_known = True
        execution.container_cleanup_required = True
        execution.container_residual_known = True
        execution.container_residual_count = 1
    else:
        execution.container_cleanup_known = False
        execution.container_cleanup_required = True
        execution.container_residual_known = False
        execution.container_residual_count = None


def _cleanup_fixture_container(execution: _FixtureDiagnosticExecutionState) -> None:
    try:
        snapshot = _fixture_container_snapshot()
        if snapshot is _FixtureContainerState.ABSENT:
            _record_fixture_container_residual(execution, snapshot)
            return
        if snapshot in {_FixtureContainerState.FOREIGN, _FixtureContainerState.UNKNOWN}:
            _record_fixture_container_residual(execution, snapshot)
            return
        if snapshot is _FixtureContainerState.OWNED_RUNNING:
            execution.container_stop_attempts += 1
            if execution.container_stop_attempts > 1:
                execution.operator_review_required = True
                _record_fixture_container_residual(execution, snapshot)
                return
            _stop_fixture_container()
            snapshot = _fixture_container_snapshot()
            if snapshot is _FixtureContainerState.ABSENT:
                _record_fixture_container_residual(execution, snapshot)
                return
            if snapshot is not _FixtureContainerState.OWNED_STOPPED:
                _record_fixture_container_residual(execution, snapshot)
                return
        execution.container_remove_attempts += 1
        if execution.container_remove_attempts > 1:
            execution.operator_review_required = True
            _record_fixture_container_residual(execution, snapshot)
            return
        _remove_fixture_container()
        _record_fixture_container_residual(execution, _fixture_container_snapshot())
    except BaseException:
        execution.operator_review_required = True
        execution.container_cleanup_known = False
        execution.container_cleanup_required = True
        execution.container_residual_known = False
        execution.container_residual_count = None


class _FixtureDiagnosticRunner(Runner):
    def note(self, _message: str) -> None:
        return None


class _ComposeGatewayAuthParityFixture:
    """Private fixed-operation adapter to the canonical local-bootstrap image."""

    _PLACEHOLDER_ALLOW = "00000000-0000-4000-8000-00000000010a"
    _PLACEHOLDER_DENY = "00000000-0000-4000-8000-00000000010b"
    _EXPECTED: ClassVar[dict[str, tuple[str, int, int, int]]] = {
        "require-absent": ("absent", 0, 0, 0),
        "prepare": ("prepared", 2, 2, 0),
        "enable": ("enabled", 2, 2, 0),
        "revoke-allow-membership": ("membership-revoked", 2, 2, 0),
        "cleanup": ("clean", 0, 0, 0),
        "require-zero-residual": ("zero-residual", 0, 0, 0),
    }

    def __init__(
        self,
        *,
        env_file: Path,
        files: tuple[Path, ...],
        source_sha256: str | None = None,
        execution_state: _FixtureDiagnosticExecutionState | None = None,
    ) -> None:
        self._env_file = env_file
        self._files = files
        self._source_sha256 = source_sha256 or current_fixture_source_sha256()
        if len(self._source_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self._source_sha256
        ):
            raise GatewayAuthParityError(
                fixture_diagnostic_failure_classification(
                    FixtureDiagnosticPredicate.IMAGE_PROVENANCE
                )
            )
        self._allow_subject: str | None = None
        self._deny_subject: str | None = None
        self._execution_state = execution_state or _FixtureDiagnosticExecutionState()

    def _execute(
        self,
        operation: str,
        *,
        allow_subject: str | None = None,
        deny_subject: str | None = None,
    ) -> FixtureDiagnosticEnvelope | None:
        if operation not in self._EXPECTED:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_FAILED")
        allow = allow_subject or self._allow_subject or self._PLACEHOLDER_ALLOW
        deny = deny_subject or self._deny_subject or self._PLACEHOLDER_DENY
        try:
            allow = str(UUID(allow))
            deny = str(UUID(deny))
        except ValueError:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_FAILED") from None
        request_document = json.dumps(
            {
                "contract": FIXTURE_CONTRACT,
                "operation": operation,
                "allow_external_subject": allow,
                "deny_external_subject": deny,
                "source_sha256": self._source_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        diagnostic_container_arguments = (
            (
                "--name",
                _FIXTURE_DIAGNOSTIC_CONTAINER_NAME,
                "--label",
                _FIXTURE_DIAGNOSTIC_CONTAINER_CONTRACT_LABEL,
                "--label",
                _FIXTURE_DIAGNOSTIC_CONTAINER_OPERATION_LABEL,
            )
            if operation == "require-absent"
            else ()
        )
        command = [
            os.fspath(argument)
            for argument in compose_arguments(
                env_file=self._env_file,
                compose_files=self._files,
                profiles=("tools",),
                trailing=(
                    "run",
                    "--rm",
                    *diagnostic_container_arguments,
                    "--no-deps",
                    "--no-build",
                    "-T",
                    "local-bootstrap",
                    "/app/.venv/bin/python",
                    "-m",
                    "datariver.gateway_auth_parity_fixture",
                    operation,
                ),
            )
        ]
        if operation == "require-absent":
            try:
                prestate = _fixture_container_snapshot()
            except BaseException:
                prestate = _FixtureContainerState.UNKNOWN
            if prestate is not _FixtureContainerState.ABSENT:
                self._execution_state.operator_review_required = True
                _record_fixture_container_residual(self._execution_state, prestate)
                return self._diagnostic_envelope(FixtureDiagnosticPredicate.UNKNOWN)
            self._execution_state.container_attempted = True
            self._execution_state.container_cleanup_known = False
            self._execution_state.container_residual_known = False
            self._execution_state.container_residual_count = None
            evidence = self._diagnostic_envelope(FixtureDiagnosticPredicate.UNKNOWN)
            try:
                outcome = _bounded_fixture_diagnostic_process(tuple(command), request_document)
                if isinstance(outcome, FixtureDiagnosticPredicate):
                    evidence = self._diagnostic_envelope(outcome)
                else:
                    evidence = self._parse_require_absent_result(outcome)
            except BaseException:
                evidence = self._diagnostic_envelope(FixtureDiagnosticPredicate.UNKNOWN)
            finally:
                _cleanup_fixture_container(self._execution_state)
            if (
                evidence.predicate is FixtureDiagnosticPredicate.PASS
                and not self._execution_state.container_cleanup_proven
            ):
                return self._diagnostic_envelope(FixtureDiagnosticPredicate.UNKNOWN)
            return evidence

        try:
            result = subprocess.run(  # noqa: S603 - fixed Compose and module argv.
                command,
                cwd=ROOT,
                check=True,
                text=True,
                input=request_document,
                capture_output=True,
                timeout=30,
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_FAILED") from None
        try:
            raw = result.stdout.strip()
            if len(raw.encode("utf-8")) > 256 or "\n" in raw or "\r" in raw:
                raise ValueError
            document = json.loads(raw)
        except (
            ValueError,
            json.JSONDecodeError,
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_FAILED") from None
        if (
            not isinstance(document, dict)
            or set(document)
            != {"state", "subject_count", "membership_count", "privilege_residual_count"}
            or (
                document["state"],
                document["subject_count"],
                document["membership_count"],
                document["privilege_residual_count"],
            )
            != self._EXPECTED[operation]
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_FAILED")
        if allow_subject is not None and deny_subject is not None:
            self._allow_subject = allow
            self._deny_subject = deny
        return None

    @staticmethod
    def _diagnostic_envelope(
        predicate: FixtureDiagnosticPredicate,
    ) -> FixtureDiagnosticEnvelope:
        return FixtureDiagnosticEnvelope(
            operation=FixtureDiagnosticOperation.REQUIRE_ABSENT,
            predicate=predicate,
        )

    @staticmethod
    def _diagnostic_stream(raw: str) -> str:
        if len(raw.encode("utf-8")) > MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES + 1:
            raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_SIZE)
        return raw[:-1] if raw.endswith("\n") else raw

    def _parse_require_absent_result(
        self,
        result: subprocess.CompletedProcess[str],
    ) -> FixtureDiagnosticEnvelope:
        try:
            stdout = self._diagnostic_stream(result.stdout)
            stderr = self._diagnostic_stream(result.stderr)
            if stdout and stderr:
                raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
            if result.returncode == 0:
                if stderr:
                    raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
                evidence = parse_fixture_diagnostic_line(stdout)
                if evidence.predicate is not FixtureDiagnosticPredicate.PASS:
                    raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
                return evidence
            if stdout:
                raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
            if not stderr:
                return self._diagnostic_envelope(FixtureDiagnosticPredicate.PROCESS_NONZERO)
            evidence = parse_fixture_diagnostic_line(stderr)
            if evidence.predicate is FixtureDiagnosticPredicate.PASS:
                raise FixtureDiagnosticProtocolError(FixtureDiagnosticPredicate.OUTPUT_TUPLE)
            return evidence
        except FixtureDiagnosticProtocolError as error:
            return self._diagnostic_envelope(error.predicate)

    def diagnose_require_absent(self) -> FixtureDiagnosticEnvelope:
        evidence = self._execute("require-absent")
        assert evidence is not None
        return evidence

    def require_absent(self) -> None:
        evidence = self.diagnose_require_absent()
        if evidence.predicate is not FixtureDiagnosticPredicate.PASS:
            raise GatewayAuthParityError(
                fixture_diagnostic_failure_classification(evidence.predicate)
            )

    def prepare(self, allow_subject: str, deny_subject: str) -> None:
        self._execute("prepare", allow_subject=allow_subject, deny_subject=deny_subject)

    def enable(self, allow_subject: str, deny_subject: str) -> None:
        self._execute("enable", allow_subject=allow_subject, deny_subject=deny_subject)

    def revoke_allow_membership(self, allow_subject: str, deny_subject: str) -> None:
        self._execute(
            "revoke-allow-membership",
            allow_subject=allow_subject,
            deny_subject=deny_subject,
        )

    def cleanup(self, allow_subject: str, deny_subject: str) -> None:
        self._execute("cleanup", allow_subject=allow_subject, deny_subject=deny_subject)

    def require_zero_residual(self) -> None:
        self._execute("require-zero-residual")


def _read_gateway_admin_password(secret_guard: TopologyReconciliationSecretGuard) -> str:
    secret_guard.revalidate()
    try:
        descriptor = secret_guard.file_descriptors["keycloak_admin_password"]
        raw = os.pread(descriptor, 4_097, 0)
        if not raw or len(raw) > 4_096 or b"\x00" in raw:
            raise ValueError
        value = raw.decode("utf-8").strip()
    except (KeyError, OSError, UnicodeDecodeError, ValueError):
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_ADMIN_CREDENTIAL_INVALID") from None
    secret_guard.revalidate()
    if not value or "\n" in value or "\r" in value:
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_ADMIN_CREDENTIAL_INVALID")
    return value


def _gateway_auth_parity_session(
    *,
    env_file: Path,
    files: tuple[Path, ...],
    secret_guard: TopologyReconciliationSecretGuard,
) -> GatewayAuthParitySession:
    values = read_env_values(env_file)
    api_port = values.get("API_PORT", "8000")
    gateway_port = values.get("APISIX_PORT", "9080")
    web_port = values.get("WEB_PORT", "8080")
    keycloak_port = values.get("KEYCLOAK_PORT", "8081")
    origin = values.get("APP_PUBLIC_ORIGIN", f"http://127.0.0.1:{web_port}")

    def check_logs(started_at: str, sentinels: tuple[str, ...]) -> None:
        _verify_gateway_logs_do_not_persist_probe_credentials(
            env_file=env_file,
            files=files,
            started_at=started_at,
            sentinels=sentinels,
        )

    traffic = GatewayAuthParityTraffic(
        direct_url=f"http://127.0.0.1:{api_port}",
        gateway_url=f"http://127.0.0.1:{gateway_port}",
        web_url=f"http://127.0.0.1:{web_port}",
        origin=origin,
        log_checker=check_logs,
    )
    password = _read_gateway_admin_password(secret_guard)
    return GatewayAuthParitySession(
        identity=KeycloakGatewayAuthParityIdentity(
            base_url=f"http://127.0.0.1:{keycloak_port}",
            admin_username="datariver-bootstrap",
            admin_password=password,
        ),
        fixture=_ComposeGatewayAuthParityFixture(env_file=env_file, files=files),
        traffic=traffic,
    )


def _reconcile_topology_with_gateway_parity(
    *,
    session: GatewayAuthParitySession,
    runner: Runner,
    env_file: Path,
    files: tuple[Path, ...],
    plan: TopologyReconciliationPlan,
    selected_builder: str | None,
    capacity_lock: DockerWorkflowLock | None,
    secret_guard: TopologyReconciliationSecretGuard,
) -> GatewayAuthParityEvidence:
    with session:
        session.prepare()
        session.enable()
        _apply_topology_reconciliation(
            runner,
            env_file=env_file,
            files=files,
            plan=plan,
            selected_builder=selected_builder,
            capacity_lock=capacity_lock,
            secret_guard=secret_guard,
        )
        evidence = session.verify_after_topology()
    if evidence.immediate_logout != "OPEN_UNSUPPORTED" or evidence.retry_count != 0:
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_EVIDENCE_INVALID")
    runner.note("Gateway human auth parity verified; immediate logout remains OPEN_UNSUPPORTED")
    return evidence


def _prepare_topology_reconciliation(
    runner: Runner,
    *,
    state: AppliedState,
    environment_values: dict[str, str],
    reconciliation: str,
) -> TopologyReconciliationPlan:
    audit = build_local_topology_audit(
        state=state,
        environment_values=environment_values,
        observations=capture_local_topology(runner),
    )
    runner.note(f"Local topology reconciliation preflight {audit.summary()}")
    return build_topology_reconciliation_plan(
        reconciliation,
        state=state,
        environment_values=environment_values,
        audit=audit,
    )


def _apply_topology_reconciliation(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
    plan: TopologyReconciliationPlan,
    selected_builder: str | None,
    capacity_lock: DockerWorkflowLock | None,
    secret_guard: TopologyReconciliationSecretGuard,
) -> None:
    runner.note("누락된 governance document worker만 복구합니다.")
    secret_guard.revalidate()
    try:
        _compose(
            runner,
            env_file=env_file,
            files=files,
            profiles=("governance-documents",),
            trailing=(
                "up",
                "-d",
                "--wait",
                "--no-deps",
                "--no-build",
                plan.missing_worker_service,
            ),
        )
    finally:
        secret_guard.revalidate()
    _verify_governance_document_worker_database(
        runner,
        env_file=env_file,
        files=files,
    )

    _require_idle_builder(selected_builder, capacity_lock)
    gateway_files = tuple(dict.fromkeys((*files, ROOT / "compose.gateway.yaml")))
    runner.note("검증된 APISIX image만 빌드하고 기존 gateway를 재생성합니다.")
    _compose(
        runner,
        env_file=env_file,
        files=gateway_files,
        trailing=("build", "apisix"),
    )
    _compose(
        runner,
        env_file=env_file,
        files=gateway_files,
        trailing=(
            "up",
            "-d",
            "--wait",
            "--no-deps",
            "--force-recreate",
            "--no-build",
            "apisix",
        ),
    )

    runner.note("Web의 내부 API upstream을 APISIX로 고정해 재생성합니다.")
    _compose(
        runner,
        env_file=env_file,
        files=files,
        trailing=(
            "up",
            "-d",
            "--wait",
            "--no-deps",
            "--force-recreate",
            "--no-build",
            "web",
        ),
    )
    if plan.target_state.local_airflow:
        airflow_files = _airflow_compose_files(
            files,
            local_gateway=True,
        )
        runner.note("선택된 Airflow API 호출만 동일 Bearer로 APISIX를 경유시킵니다.")
        _compose(
            runner,
            env_file=env_file,
            files=airflow_files,
            trailing=(
                "up",
                "-d",
                "--wait",
                "--no-deps",
                "--force-recreate",
                "--no-build",
                *AIRFLOW_SERVICES,
            ),
        )


def _compose(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
    trailing: tuple[str, ...],
    profiles: tuple[str, ...] = (),
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> None:
    runner.run(
        compose_arguments(
            env_file=env_file,
            compose_files=files,
            profiles=profiles,
            trailing=trailing,
        ),
        env=env,
        input_text=input_text,
    )


def _preflight_build_capacity(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
    selected_build_services: tuple[str, ...],
    lock: DockerWorkflowLock,
    executor: CapacityExecutor | None = None,
    mode: DockerCapacityMode = DockerCapacityMode.ACTION_ENABLED,
    phase_recorder: DockerCapacityPhaseRecorder | None = None,
) -> str:
    if phase_recorder is not None:
        phase_recorder.mark(BuildCapacityPreflightPredicate.COMPOSE_ARGUMENTS)
    evidence = governed_compose_build_capacity(
        root=ROOT,
        compose_config_command=compose_arguments(
            env_file=env_file,
            compose_files=files,
            profiles=("*",),
            trailing=("config", "--format", "json"),
        ),
        docker_filesystem_probe_command=compose_arguments(
            env_file=env_file,
            compose_files=files,
            trailing=("exec", "-T", "postgres", "df", "-Pk", "/"),
        ),
        selected_build_services=selected_build_services,
        environ=os.environ,
        lock=lock,
        executor=executor,
        mode=mode,
        phase_recorder=phase_recorder,
    )
    runner.note(evidence.summary())
    return evidence.builder


def _require_idle_builder(
    builder: str | None,
    lock: DockerWorkflowLock | None,
    *,
    executor: CapacityExecutor | None = None,
    phase_recorder: DockerCapacityPhaseRecorder | None = None,
) -> None:
    if phase_recorder is not None:
        phase_recorder.mark(BuildCapacityPreflightPredicate.INITIAL_BUILDER_IDLE_PROBE)
    try:
        if builder is None or lock is None:
            raise DockerCapacityError("DOCKER_BUILD_CAPACITY_EVIDENCE_MISSING")
        require_no_active_builds(
            builder=builder,
            lock=lock,
            executor=executor,
            phase_recorder=phase_recorder,
            probe_predicate=BuildCapacityPreflightPredicate.INITIAL_BUILDER_IDLE_PROBE,
            active_predicate=BuildCapacityPreflightPredicate.INITIAL_BUILDER_ACTIVE,
        )
    except DockerCapacityPhaseError:
        raise
    except DockerCapacityError as error:
        if phase_recorder is not None:
            raise DockerCapacityPhaseError(str(error), phase_recorder.predicate) from None
        raise


def _git_paths(runner: Runner, older: str, newer: str) -> tuple[str, ...]:
    if older == newer:
        return ()
    try:
        runner.run(("git", "merge-base", "--is-ancestor", older, newer))
    except WorkflowError as error:
        raise WorkflowError(
            "The previously applied commit is not an ancestor of the current checkout. "
            "Use a reviewed rollback procedure instead of this forward-update workflow."
        ) from error
    return tuple(
        line
        for line in runner.output(("git", "diff", "--name-only", f"{older}..{newer}")).splitlines()
        if line
    )


def _running_services(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> tuple[str, ...]:
    arguments = compose_arguments(
        env_file=env_file,
        compose_files=files,
        trailing=("ps", "--services", "--filter", "status=running"),
    )
    try:
        output = runner.output(arguments)
    except WorkflowError:
        try:
            runner.output(_DOCKER_DAEMON_PROBE)
        except WorkflowError as error:
            raise WorkflowError(
                "The Compose running-service query stopped "
                f"(classification={_DOCKER_DAEMON_UNAVAILABLE})."
            ) from error
        runner.note("Docker daemon probe 통과 후 실행 서비스 조회를 1회 재시도합니다.")
        try:
            output = runner.output(arguments)
        except WorkflowError as error:
            raise WorkflowError(
                "The Compose running-service query stopped after one bounded retry "
                f"(classification={_COMPOSE_RUNNING_SERVICES_QUERY_FAILED})."
            ) from error
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def _verify_and_load_release(runner: Runner, *, release_dir: Path) -> None:
    layout = release_layout(release_dir, architecture="amd64")
    runner.note("오프라인 release의 source/checksum/manifest/platform을 검증·로드합니다.")
    runner.run(
        (
            ROOT / "scripts" / "verify_offline_release.sh",
            layout.root,
            "--platform",
            "linux/amd64",
            "--load",
        )
    )


def _bootstrap(runner: Runner, *, state: AppliedState, env_file: Path) -> None:
    values = read_env_values(env_file)
    datahub_base_url = values.get("DATAHUB_BASE_URL")
    if not datahub_base_url:
        raise WorkflowError("DATAHUB_BASE_URL is missing from the selected environment file.")
    preserved = {
        key: value
        for key, value in values.items()
        if key.startswith(
            (
                "REDIS_",
                "S3_",
                "UI_",
                "INTRANET_OPENAI_",
                "LOCAL_OLLAMA_",
                "LOCAL_LLAMA_CPP_",
                "NEO4J_",
            )
        )
        or key in {"NO_PROXY", "OIDC_HARDWARE_WEBAUTHN_ENABLED"}
    }
    runner.run(
        (
            ROOT / "scripts" / "bootstrap.sh",
            "--env-file",
            env_file,
            f"--{state.profile}",
            "--datahub-base-url",
            datahub_base_url,
        )
    )
    update_env_values(env_file, preserved)


def _reconcile_postgres(runner: Runner, *, env_file: Path) -> None:
    _compose(
        runner,
        env_file=env_file,
        files=(ROOT / "compose.yaml",),
        trailing=(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-ec",
            'export PGPASSWORD="$(tr -d "\\r\\n" </run/secrets/postgres_password)"; '
            "exec sh /docker-entrypoint-initdb.d/010_roles.sh",
        ),
    )


def _enabled_optional_runtime_services(values: dict[str, str]) -> tuple[str, ...]:
    services: list[str] = []
    if values.get("KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED", "").lower() == "true":
        services.append("knowledge-tbox-proposal-worker")
    return tuple(services)


def _requires_postgres_secret_remount(environment_keys: tuple[str, ...]) -> bool:
    return bool(_POSTGRES_SECRET_MOUNT_ENV_KEYS.intersection(environment_keys))


def _health_check(runner: Runner, *, env_file: Path) -> None:
    values = read_env_values(env_file)
    api_port = values.get("API_PORT", "8000")
    web_port = values.get("WEB_PORT", "8080")
    runner.run(
        (
            sys.executable,
            "-",
            f"http://127.0.0.1:{api_port}/api/v1/health/live",
            f"http://127.0.0.1:{api_port}/api/v1/health/ready",
            f"http://127.0.0.1:{web_port}/healthz",
        ),
        input_text=HEALTH_PROGRAM,
    )


def _reconcile_local_reranker(runner: Runner, *, env_file: Path, profile: str) -> None:
    values = read_env_values(env_file)
    enabled = values.get("LOCAL_LLAMA_CPP_RERANKER_ENABLED", "").lower() == "true"
    manager = ROOT / "scripts" / "local_reranker_service.py"
    if not workflow_profile(profile).local_reranker_supported or not enabled:
        runner.note("비활성 로컬 llama.cpp reranker의 소유 프로세스를 정리합니다.")
        runner.run((sys.executable, manager, "stop"))
        return
    model = values.get("LOCAL_LLAMA_CPP_RERANKER_MODEL")
    if not model:
        raise WorkflowError("LOCAL_LLAMA_CPP_RERANKER_MODEL is required when enabled.")
    runner.note("Ollama GGUF 기반 로컬 llama.cpp reranker를 검증·시작합니다.")
    runner.run(
        (
            sys.executable,
            manager,
            "start",
            "--model",
            model,
        )
    )


def _probe_datahub(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    _compose(
        runner,
        env_file=env_file,
        files=files,
        trailing=("exec", "-T", "api", "/app/.venv/bin/python", "-"),
        input_text=DATAHUB_PROBE_PROGRAM,
    )


def _sync_catalog(runner: Runner, *, env_file: Path) -> None:
    values = read_env_values(env_file)
    api_port = values.get("API_PORT", "8000")
    keycloak_port = values.get("KEYCLOAK_PORT", "8081")
    environment = os.environ.copy()
    environment.update(
        {
            "DATARIVER_API_BASE_URL": f"http://127.0.0.1:{api_port}",
            "DATARIVER_WORKSPACE_ID": "00000000-0000-4000-8000-000000000100",
            "DATARIVER_OIDC_TOKEN_URL": (
                f"http://127.0.0.1:{keycloak_port}/realms/datariver/protocol/openid-connect/token"
            ),
            "DATARIVER_OIDC_CLIENT_ID": "datariver-airflow",
            "DATARIVER_OIDC_CLIENT_SECRET_FILE": os.fspath(
                ROOT / "secrets" / "airflow_client_secret"
            ),
            "DATARIVER_CATALOG_SYNC_MAX_PAGES": values.get(
                "DATARIVER_CATALOG_SYNC_MAX_PAGES", "10002"
            ),
            "NO_PROXY": merge_no_proxy(
                os.environ.get("NO_PROXY", ""),
                ("127.0.0.1", "localhost"),
            ),
            "PYTHONPATH": os.fspath(ROOT / "infra" / "airflow" / "dags"),
        }
    )
    environment["no_proxy"] = environment["NO_PROXY"]
    runner.run((sys.executable, "-"), env=environment, input_text=CATALOG_SYNC_PROGRAM)


def _reconcile_local_admin_catalog_access(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    _compose(
        runner,
        env_file=env_file,
        files=files,
        trailing=(
            "--profile",
            "tools",
            "run",
            "--rm",
            "--no-deps",
            "--build",
            "local-bootstrap",
            "/app/.venv/bin/python",
            "-m",
            "datariver.local_admin_catalog_access",
        ),
    )


def _print_plan(
    *,
    previous_commit: str,
    current_source_commit: str,
    runtime_commit: str,
    paths: tuple[str, ...],
    environment_keys: tuple[str, ...],
    plan: ChangePlan,
    restart_services: tuple[str, ...],
) -> None:
    print("Update plan", flush=True)
    print(f"  source:  {previous_commit[:12]} -> {current_source_commit[:12]}", flush=True)
    print(f"  runtime: {runtime_commit[:12]}", flush=True)
    print(f"  changed paths: {len(paths)}", flush=True)
    for path in paths:
        print(f"    - {path}", flush=True)
    print(f"  changed environment keys: {len(environment_keys)}", flush=True)
    for key in environment_keys:
        print(f"    - {key}", flush=True)
    print(
        "  restart services: " + (", ".join(restart_services) if restart_services else "none"),
        flush=True,
    )
    print(f"  migration: {'yes' if plan.requires_migration else 'no'}", flush=True)
    print(f"  DataHub: {'restart' if plan.restart_datahub else 'unchanged'}", flush=True)
    print(f"  Airflow: {'restart' if plan.restart_airflow else 'unchanged'}", flush=True)
    print(f"  APISIX: {'restart' if plan.restart_gateway else 'unchanged'}", flush=True)
    print(f"  Neo4j: {'restart' if plan.restart_graph else 'unchanged'}", flush=True)


def format_host_environment_preflight_line(
    evidence: HostEnvironmentPreflightEvidence,
) -> str:
    line = json.dumps(
        {
            "classification": evidence.classification.value,
            "mutation_count": evidence.mutation_count,
            "phase": evidence.phase.value,
            "predicate": evidence.predicate.value,
            "retry_count": evidence.retry_count,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(line.encode("utf-8")) > MAXIMUM_HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_BYTES:
        raise WorkflowError("HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_INVALID")
    return line


def format_build_capacity_preflight_line(
    evidence: BuildCapacityPreflightEvidence,
) -> str:
    line = json.dumps(
        {
            "build_count": evidence.build_count,
            "cache_action_count": evidence.cache_action_count,
            "classification": evidence.classification.value,
            "container_count": evidence.container_count,
            "mutation_count": evidence.mutation_count,
            "phase": evidence.phase.value,
            "predicate": evidence.predicate.value,
            "retry_count": evidence.retry_count,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(line.encode("utf-8")) > MAXIMUM_BUILD_CAPACITY_PREFLIGHT_EVIDENCE_BYTES:
        raise WorkflowError("BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID")
    return line


def _fixed_invalid_diagnostic_line() -> str:
    line = json.dumps(
        {
            "classification": "REJECTED",
            "mutation_count": 0,
            "phase": "INVALID_DIAGNOSTIC",
            "predicate": "UNKNOWN",
            "retry_count": 0,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(line.encode("utf-8")) > MAXIMUM_HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_BYTES:
        raise WorkflowError("INVALID_DIAGNOSTIC_EVIDENCE_INVALID")
    return line


def _host_environment_preflight_failure(
    predicate: HostEnvironmentPreflightPredicate,
) -> _HostEnvironmentPreflightResult:
    return _HostEnvironmentPreflightResult(
        HostEnvironmentPreflightEvidence(
            classification=HostEnvironmentPreflightClassification.REJECTED,
            phase=HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
            predicate=predicate,
        )
    )


def _host_environment_preflight_under_lock() -> _HostEnvironmentPreflightResult:
    try:
        state = load_applied_state(state_path(ROOT, "mac-development"))
    except Exception:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.APPLIED_STATE_CONTRACT
        )
    if state.profile != "mac-development":
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.PROFILE_SELECTION
        )
    if state.deployment_mode != "build":
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.DEPLOYMENT_MODE_SELECTION
        )
    if state.local_gateway:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.GATEWAY_SELECTION
        )
    if state.local_graph:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.GRAPH_SELECTION
        )
    try:
        env_file = _resolve_repo_path(state.env_file)
    except Exception:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.ENV_PATH_CONTRACT
        )
    try:
        require_regular_file(env_file, label="Environment file")
    except Exception:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.ENV_FILE_CONTRACT
        )
    try:
        environment_values = read_env_values(env_file)
    except Exception:
        return _host_environment_preflight_failure(HostEnvironmentPreflightPredicate.ENV_READ)
    try:
        environment_fingerprint = environment_key_hashes(environment_values)
    except Exception:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.ENV_FINGERPRINT
        )
    if environment_fingerprint != state.environment_key_hashes:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.ENV_FINGERPRINT
        )
    try:
        files = _compose_files(state, release_override=None)
    except Exception:
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.COMPOSE_SELECTION
        )
    if files != (ROOT / "compose.yaml", ROOT / "compose.identity.yaml"):
        return _host_environment_preflight_failure(
            HostEnvironmentPreflightPredicate.COMPOSE_SELECTION
        )
    return _HostEnvironmentPreflightResult(
        HostEnvironmentPreflightEvidence(
            classification=HostEnvironmentPreflightClassification.PASS,
            phase=HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
            predicate=HostEnvironmentPreflightPredicate.PASS,
        ),
        state=state,
        env_file=env_file,
        files=files,
    )


def _host_environment_preflight_diagnostic() -> HostEnvironmentPreflightEvidence:
    try:
        with exclusive_docker_workflow_lock(ROOT):
            result = _host_environment_preflight_under_lock()
    except BaseException:
        return HostEnvironmentPreflightEvidence(
            classification=HostEnvironmentPreflightClassification.OPERATOR_REVIEW_REQUIRED,
            phase=HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
            predicate=HostEnvironmentPreflightPredicate.UNKNOWN,
        )
    return result.evidence


def _build_capacity_preflight_failure(
    predicate: BuildCapacityPreflightPredicate,
) -> BuildCapacityPreflightEvidence:
    if predicate in {
        BuildCapacityPreflightPredicate.PASS,
        BuildCapacityPreflightPredicate.UNKNOWN,
    }:
        raise WorkflowError("BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID")
    return BuildCapacityPreflightEvidence(
        classification=BuildCapacityPreflightClassification.REJECTED,
        phase=BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=predicate,
    )


def _build_capacity_preflight_review_required() -> BuildCapacityPreflightEvidence:
    return BuildCapacityPreflightEvidence(
        classification=BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED,
        phase=BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=BuildCapacityPreflightPredicate.UNKNOWN,
    )


def _fixture_diagnostic_source_is_stable(expected_sha256: str) -> bool:
    if _fixture_diagnostic_source_state() is not _FixtureSourceCleanState.CLEAN:
        return False
    try:
        require_current_fixture_source(expected_sha256)
    except Exception:
        return False
    return True


def _build_capacity_preflight_under_lock(
    capacity_lock: DockerWorkflowLock,
) -> BuildCapacityPreflightEvidence:
    preflight = _host_environment_preflight_under_lock()
    if preflight.evidence.predicate is not HostEnvironmentPreflightPredicate.PASS:
        return _build_capacity_preflight_failure(
            BuildCapacityPreflightPredicate.HOST_ENVIRONMENT_PREFLIGHT
        )
    assert preflight.env_file is not None
    env_file = preflight.env_file
    files = preflight.files
    source_state = _fixture_diagnostic_source_state()
    if source_state is _FixtureSourceCleanState.UNKNOWN:
        return _build_capacity_preflight_review_required()
    if source_state is not _FixtureSourceCleanState.CLEAN:
        return _build_capacity_preflight_failure(BuildCapacityPreflightPredicate.CLEAN_CHECKOUT)
    try:
        source_sha256 = current_fixture_source_sha256()
    except Exception:
        return _build_capacity_preflight_failure(BuildCapacityPreflightPredicate.SOURCE_PROVENANCE)

    phase_recorder = DockerCapacityPhaseRecorder()
    command_executor = _BuildCapacityPreflightExecutor()
    try:
        selected_builder = _preflight_build_capacity(
            _FixtureDiagnosticRunner(),
            env_file=env_file,
            files=files,
            selected_build_services=("local-bootstrap",),
            lock=capacity_lock,
            executor=command_executor,
            mode=DockerCapacityMode.MEASURE_ONLY,
            phase_recorder=phase_recorder,
        )
    except DockerCapacityMeasureOnlyStop:
        if not _fixture_diagnostic_source_is_stable(source_sha256):
            return _build_capacity_preflight_review_required()
        return _build_capacity_preflight_failure(
            BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED
        )
    except DockerCapacityPhaseError as error:
        return _build_capacity_preflight_failure(error.predicate)
    except Exception:
        predicate = phase_recorder.predicate
        if predicate in {
            BuildCapacityPreflightPredicate.PASS,
            BuildCapacityPreflightPredicate.UNKNOWN,
        }:
            predicate = BuildCapacityPreflightPredicate.UNKNOWN
        if predicate is BuildCapacityPreflightPredicate.UNKNOWN:
            raise
        return _build_capacity_preflight_failure(predicate)
    if not _fixture_diagnostic_source_is_stable(source_sha256):
        return _build_capacity_preflight_review_required()

    try:
        _require_idle_builder(
            selected_builder,
            capacity_lock,
            executor=command_executor,
            phase_recorder=phase_recorder,
        )
    except DockerCapacityPhaseError as error:
        return _build_capacity_preflight_failure(error.predicate)
    except Exception:
        predicate = phase_recorder.predicate
        if predicate not in {
            BuildCapacityPreflightPredicate.INITIAL_BUILDER_IDLE_PROBE,
            BuildCapacityPreflightPredicate.INITIAL_BUILDER_ACTIVE,
        }:
            raise
        return _build_capacity_preflight_failure(predicate)
    if not _fixture_diagnostic_source_is_stable(source_sha256):
        return _build_capacity_preflight_review_required()

    phase_recorder.mark(BuildCapacityPreflightPredicate.PASS)
    return BuildCapacityPreflightEvidence(
        classification=BuildCapacityPreflightClassification.PASS,
        phase=BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=phase_recorder.predicate,
    )


def _build_capacity_preflight_diagnostic() -> BuildCapacityPreflightEvidence:
    try:
        with exclusive_docker_workflow_lock(ROOT) as capacity_lock:
            evidence = _build_capacity_preflight_under_lock(capacity_lock)
    except BaseException:
        return _build_capacity_preflight_review_required()
    return evidence


def _fixture_require_absent_diagnostic() -> FixtureDiagnosticExecutionEvidence:
    """Run the sole locked fixture absence diagnostic with honest Docker evidence."""

    execution = _FixtureDiagnosticExecutionState()
    capacity_executor = _FixtureDiagnosticCapacityExecutor()
    try:
        with exclusive_docker_workflow_lock(ROOT) as capacity_lock:
            preflight = _host_environment_preflight_under_lock()
            if preflight.evidence.predicate is not HostEnvironmentPreflightPredicate.PASS:
                return execution.to_evidence(FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY)
            assert preflight.state is not None
            assert preflight.env_file is not None
            env_file = preflight.env_file
            files = preflight.files
            try:
                if not _fixture_diagnostic_source_is_clean():
                    raise WorkflowError("GATEWAY_AUTH_PARITY_FIXTURE_IMAGE_PROVENANCE_INVALID")
                source_sha256 = current_fixture_source_sha256()
            except BaseException:
                return execution.to_evidence(FixtureDiagnosticPredicate.IMAGE_PROVENANCE)
            selected_builder: str | None = None
            try:
                selected_builder = _preflight_build_capacity(
                    _FixtureDiagnosticRunner(),
                    env_file=env_file,
                    files=files,
                    selected_build_services=("local-bootstrap",),
                    lock=capacity_lock,
                    executor=capacity_executor,
                )
                _require_idle_builder(selected_builder, capacity_lock)
                execution.builder_idle_known = True
                execution.builder_idle = True
            except BaseException:
                execution.cache_action_count_known = capacity_executor.action_count_known
                execution.cache_action_count = (
                    capacity_executor.action_count if capacity_executor.action_count_known else None
                )
                execution.cache_action_outcome_known = capacity_executor.action_outcome_known
                execution.cache_action_succeeded = capacity_executor.action_succeeded
                if not capacity_executor.action_outcome_known:
                    execution.operator_review_required = True
                return execution.to_evidence(FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY)
            execution.cache_action_count_known = capacity_executor.action_count_known
            execution.cache_action_count = (
                capacity_executor.action_count if capacity_executor.action_count_known else None
            )
            execution.cache_action_outcome_known = capacity_executor.action_outcome_known
            execution.cache_action_succeeded = capacity_executor.action_succeeded
            build_outcome = _FixtureBuildOutcome(
                attempted=False,
                succeeded=False,
                outcome_known=False,
            )
            try:
                build_outcome = _build_current_fixture_image(
                    env_file=env_file,
                    files=files,
                )
            except BaseException:
                build_outcome = _FixtureBuildOutcome(
                    attempted=True,
                    succeeded=False,
                    outcome_known=False,
                )
            finally:
                execution.build_attempted = build_outcome.attempted
                execution.build_succeeded = build_outcome.succeeded
                execution.build_outcome_known = build_outcome.outcome_known
                execution.builder_idle_known = False
                execution.builder_idle = False
                try:
                    _require_idle_builder(selected_builder, capacity_lock)
                    execution.builder_idle_known = True
                    execution.builder_idle = True
                except BaseException:
                    execution.operator_review_required = True
            if (
                not build_outcome.succeeded
                or not build_outcome.outcome_known
                or not execution.builder_idle_known
                or not execution.builder_idle
            ):
                return execution.to_evidence(FixtureDiagnosticPredicate.IMAGE_PROVENANCE)
            try:
                if (
                    not _fixture_diagnostic_source_is_clean()
                    or current_fixture_source_sha256() != source_sha256
                ):
                    raise WorkflowError("GATEWAY_AUTH_PARITY_FIXTURE_IMAGE_PROVENANCE_INVALID")
            except BaseException:
                return execution.to_evidence(FixtureDiagnosticPredicate.IMAGE_PROVENANCE)
            fixture = _ComposeGatewayAuthParityFixture(
                env_file=env_file,
                files=files,
                source_sha256=source_sha256,
                execution_state=execution,
            )
            return execution.to_evidence(fixture.diagnose_require_absent().predicate)
    except BaseException:
        if (
            execution.cache_action_count == 1
            or execution.build_attempted
            or execution.container_attempted
        ):
            execution.operator_review_required = True
        return execution.to_evidence(FixtureDiagnosticPredicate.UNKNOWN)


def main() -> int:
    diagnostic_arguments = tuple(sys.argv[1:])
    diagnostic_equals_arguments = tuple(
        argument
        for argument in diagnostic_arguments
        if argument.startswith(_DIAGNOSTIC_PHASE_EQUALS_PREFIX)
    )
    if len(diagnostic_equals_arguments) > 1 or (
        diagnostic_equals_arguments and "--diagnostic-phase" in diagnostic_arguments
    ):
        print(_fixed_invalid_diagnostic_line())
        return 2
    if diagnostic_arguments == _BUILD_CAPACITY_PREFLIGHT_ARGUMENTS:
        capacity_evidence = _build_capacity_preflight_diagnostic()
        print(format_build_capacity_preflight_line(capacity_evidence))
        return (
            0
            if capacity_evidence.classification is BuildCapacityPreflightClassification.PASS
            else 2
        )
    if diagnostic_equals_arguments:
        diagnostic_equals_argument = diagnostic_equals_arguments[0]
        if diagnostic_equals_argument.startswith(_BUILD_CAPACITY_PREFLIGHT_EQUALS_PREFIX):
            capacity_evidence = BuildCapacityPreflightEvidence(
                classification=BuildCapacityPreflightClassification.REJECTED,
                phase=BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
                predicate=BuildCapacityPreflightPredicate.UNKNOWN,
            )
            print(format_build_capacity_preflight_line(capacity_evidence))
            return 2
        if diagnostic_equals_argument.startswith(_HOST_ENVIRONMENT_PREFLIGHT_EQUALS_PREFIX):
            environment_evidence = HostEnvironmentPreflightEvidence(
                classification=HostEnvironmentPreflightClassification.REJECTED,
                phase=HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
                predicate=HostEnvironmentPreflightPredicate.UNKNOWN,
            )
            print(format_host_environment_preflight_line(environment_evidence))
            return 2
        print(_fixed_invalid_diagnostic_line())
        return 2
    if "BUILD_CAPACITY_PREFLIGHT" in diagnostic_arguments:
        capacity_evidence = BuildCapacityPreflightEvidence(
            classification=BuildCapacityPreflightClassification.REJECTED,
            phase=BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
            predicate=BuildCapacityPreflightPredicate.UNKNOWN,
        )
        print(format_build_capacity_preflight_line(capacity_evidence))
        return 2
    if diagnostic_arguments == _HOST_ENVIRONMENT_PREFLIGHT_ARGUMENTS:
        environment_evidence = _host_environment_preflight_diagnostic()
        print(format_host_environment_preflight_line(environment_evidence))
        return (
            0
            if environment_evidence.classification is HostEnvironmentPreflightClassification.PASS
            else 2
        )
    if "--diagnostic-phase" in diagnostic_arguments:
        environment_evidence = HostEnvironmentPreflightEvidence(
            classification=HostEnvironmentPreflightClassification.REJECTED,
            phase=HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
            predicate=HostEnvironmentPreflightPredicate.UNKNOWN,
        )
        print(format_host_environment_preflight_line(environment_evidence))
        return 2
    if len(sys.argv) == 1:
        evidence = _fixture_require_absent_diagnostic()
        print(format_fixture_diagnostic_execution_line(evidence))
        return 0 if evidence.classification is FixtureDiagnosticExecutionClassification.PASS else 2
    args = parse_args()
    reconciliation_name = getattr(args, "reconcile_local_topology", None)
    runner = Runner()
    mutation_stack = ExitStack()
    try:
        for command in ("docker", "git"):
            require_command(command)
        state_file = state_path(ROOT, args.profile)
        state = load_applied_state(state_file)
        if state.profile != args.profile:
            raise WorkflowError("The requested profile does not match its applied state.")
        capacity_lock: DockerWorkflowLock | None = None
        if reconciliation_name is not None:
            capacity_lock = mutation_stack.enter_context(exclusive_docker_workflow_lock(ROOT))
            _require_gateway_auth_parity_evidence_available(reconciliation_name)
        if args.git_pull:
            require_clean_worktree(runner)
            runner.note("현재 branch를 fast-forward 방식으로 pull합니다.")
            runner.run(("git", "pull", "--ff-only"))
        require_clean_worktree(runner)

        current_source_commit = current_commit(runner)
        env_file = (
            args.env_file.expanduser().resolve()
            if args.env_file is not None
            else _resolve_repo_path(state.env_file)
        )
        require_regular_file(env_file, label="Environment file")

        source_paths = _git_paths(runner, state.applied_commit, current_source_commit)
        runtime_commit = current_source_commit
        release_dir: Path | None = None
        offline_layout = None
        runtime_paths: tuple[str, ...] = ()
        if state.deployment_mode == "offline":
            require_command("sha256sum")
            selected_release = args.release_dir or (
                Path(state.release_dir) if state.release_dir is not None else None
            )
            if selected_release is None:
                raise WorkflowError("The offline update requires --release-dir.")
            release_dir = selected_release.expanduser().resolve()
            layout = release_layout(release_dir, architecture="amd64")
            offline_layout = layout
            release_optional_compose(
                layout,
                "offline-airflow.compose.yaml",
                required=state.local_airflow,
            )
            release_optional_compose(
                layout,
                "offline-graph.compose.yaml",
                required=state.local_graph,
            )
            release_optional_compose(
                layout,
                "offline-local-connectors.compose.yaml",
                required=state.local_storage,
            )
            require_release_compatible_checkout(
                runner=runner,
                release_commit=layout.source_commit,
                checkout_commit=current_source_commit,
            )
            runtime_commit = layout.source_commit
            runtime_paths = _git_paths(runner, state.runtime_commit, runtime_commit)
            if args.reload_release or runtime_commit != state.runtime_commit:
                _verify_and_load_release(runner, release_dir=release_dir)
        elif args.release_dir is not None:
            raise WorkflowError("--release-dir is valid only for an offline applied state.")

        changed_paths = tuple(dict.fromkeys((*source_paths, *runtime_paths)))
        source_plan = classify_changes(changed_paths)
        reapply_local_identity = requires_local_identity_bootstrap(
            changed_paths,
            profile=state.profile,
        )
        files = _compose_files(state, release_override=release_dir)

        if args.refresh_bootstrap:
            runner.note("기존 secret을 보존하며 bootstrap 파생 설정을 재적용합니다.")
            _bootstrap(runner, state=state, env_file=env_file)

        environment_values = read_env_values(env_file)
        current_environment_hashes = environment_key_hashes(environment_values)
        environment_keys = changed_environment_keys(
            state.environment_key_hashes,
            current_environment_hashes,
        )
        immutable_bootstrap_keys = {"POSTGRES_DB", "POSTGRES_USER"}
        changed_immutable_keys = sorted(immutable_bootstrap_keys.intersection(environment_keys))
        if state.environment_key_hashes and changed_immutable_keys:
            raise WorkflowError(
                "Bootstrap-owned PostgreSQL identity cannot be changed by the update workflow: "
                + ", ".join(changed_immutable_keys)
                + ". Use a reviewed fresh setup or database migration procedure."
            )
        plan = merge_change_plans(
            source_plan,
            classify_environment_changes(environment_keys),
        )

        runner.note("Compose 구성을 서비스 변경 전에 검증합니다.")
        _compose(
            runner,
            env_file=env_file,
            files=files,
            trailing=("config", "--quiet"),
        )
        running = _running_services(runner, env_file=env_file, files=files)
        reconciliation_plan: TopologyReconciliationPlan | None = None
        if reconciliation_name is None:
            enforce_local_topology(
                runner=runner,
                state=state,
                environment_values=environment_values,
            )
        else:
            reconciliation_plan = _prepare_topology_reconciliation(
                runner,
                state=state,
                environment_values=environment_values,
                reconciliation=reconciliation_name,
            )
        operating_state = (
            reconciliation_plan.target_state if reconciliation_plan is not None else state
        )
        files = _compose_files(operating_state, release_override=release_dir)
        enabled_optional_services = _enabled_optional_runtime_services(environment_values)
        restart_services = select_restart_services(
            plan.services,
            running_services=(*running, *enabled_optional_services),
        )
        immediate_restart_services = tuple(
            service
            for service in restart_services
            if reconciliation_plan is None or service != "web"
        )
        _print_plan(
            previous_commit=state.applied_commit,
            current_source_commit=current_source_commit,
            runtime_commit=runtime_commit,
            paths=changed_paths,
            environment_keys=environment_keys,
            plan=plan,
            restart_services=restart_services,
        )
        if not args.assume_yes and (changed_paths or environment_keys):
            if not prompt_confirm("위 변경만 적용할까요?", default=True):
                raise WorkflowError("Operator cancelled before service mutation.")

        offline = state.deployment_mode == "offline"
        core_build_services: list[str] = []
        selected_build_services: list[str] = []
        capacity_files = list(files)
        if not offline:
            if restart_services:
                core_build_services.extend(restart_services)
                core_build_services.extend(("migrate",) if plan.requires_migration else ())
                selected_build_services.extend(core_build_services)
            if reapply_local_identity:
                selected_build_services.append("local-bootstrap")
            if reconciliation_plan is not None:
                selected_build_services.append("local-bootstrap")
            if (
                plan.restart_airflow
                and operating_state.local_airflow
                and reconciliation_plan is None
            ):
                selected_build_services.extend(AIRFLOW_SERVICES)
                capacity_files.append(ROOT / "compose.airflow.yaml")
            if plan.restart_gateway and operating_state.local_gateway:
                selected_build_services.append("apisix")
                capacity_files.append(ROOT / "compose.gateway.yaml")
        core_build_services = list(dict.fromkeys(core_build_services))
        selected_build_services = list(dict.fromkeys(selected_build_services))

        topology_secret_guard: TopologyReconciliationSecretGuard | None = None
        selected_builder: str | None = None
        if not offline:
            if capacity_lock is None:
                capacity_lock = mutation_stack.enter_context(exclusive_docker_workflow_lock(ROOT))
            if reconciliation_plan is not None:
                runner.note(
                    "Topology mutation 전 canonical secret/config/runtime preflight를 반복합니다."
                )
                topology_secret_guard = mutation_stack.enter_context(
                    require_topology_reconciliation_secrets(ROOT)
                )
                locked_plan = _prepare_topology_reconciliation(
                    runner,
                    state=state,
                    environment_values=environment_values,
                    reconciliation=reconciliation_plan.name,
                )
                if locked_plan != reconciliation_plan:
                    raise WorkflowError("TOPOLOGY_RECONCILIATION_PRECONDITION_FAILED")
                _compose(
                    runner,
                    env_file=env_file,
                    files=files,
                    trailing=("config", "--quiet"),
                )
            if selected_build_services:
                runner.note("Docker 변경 전에 선택 build의 용량·cache 계약을 검증합니다.")
                selected_builder = _preflight_build_capacity(
                    runner,
                    env_file=env_file,
                    files=tuple(dict.fromkeys(capacity_files)),
                    selected_build_services=tuple(selected_build_services),
                    lock=capacity_lock,
                )

        if reconciliation_plan is not None:
            _require_idle_builder(selected_builder, capacity_lock)
            runner.note("Gateway parity의 고정 local-bootstrap 모듈을 현재 source로 빌드합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                profiles=("tools",),
                trailing=("build", "local-bootstrap"),
            )

        _reconcile_local_reranker(runner, env_file=env_file, profile=state.profile)

        if not offline and restart_services:
            _require_idle_builder(selected_builder, capacity_lock)
            runner.note("선택한 build 프로필에서 영향받은 이미지만 빌드합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=("build", *core_build_services),
            )
        if reapply_local_identity:
            if not offline:
                _require_idle_builder(selected_builder, capacity_lock)
            runner.note("변경된 Mac 로컬 identity bootstrap 이미지를 빌드합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                profiles=("tools",),
                trailing=("build", "local-bootstrap"),
            )

        if plan.requires_migration:
            stop_services = tuple(service for service in restart_services if service in running)
            if stop_services:
                runner.note("Schema 변경 전에 영향받는 실행 서비스를 중지합니다.")
                _compose(
                    runner,
                    env_file=env_file,
                    files=files,
                    trailing=("stop", *stop_services),
                )
            if _requires_postgres_secret_remount(environment_keys):
                runner.note("새 PostgreSQL role secret mount를 migration 전에 재적용합니다.")
                _compose(
                    runner,
                    env_file=env_file,
                    files=(ROOT / "compose.yaml",),
                    trailing=(
                        "up",
                        "-d",
                        "--wait",
                        "--no-deps",
                        "--force-recreate",
                        *(("--pull", "never") if offline else ()),
                        "postgres",
                    ),
                )
            runner.note("Migration 선행 PostgreSQL 역할 계약을 재적용합니다.")
            _reconcile_postgres(runner, env_file=env_file)
            runner.note("Alembic migration을 적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "migrate",
                ),
            )
            runner.note("Migration 후 PostgreSQL 역할 grant를 재적용합니다.")
            _reconcile_postgres(runner, env_file=env_file)

        if reapply_local_identity:
            runner.note("변경된 Mac 로컬 maker/checker identity를 재적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                profiles=("tools",),
                trailing=("run", "--rm", "local-bootstrap"),
            )

        if state.local_storage and (
            environment_values.get("KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED", "").lower() == "true"
        ):
            knowledge_storage_files: tuple[Path, ...] = (ROOT / "compose.local-connectors.yaml",)
            if offline_layout is not None:
                storage_override = release_optional_compose(
                    offline_layout,
                    "offline-local-connectors.compose.yaml",
                    required=True,
                )
                assert storage_override is not None
                knowledge_storage_files = (*knowledge_storage_files, storage_override)
            runner.note("Knowledge Proposal worker의 전용 Object Storage identity를 검증합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=knowledge_storage_files,
                profiles=("object-storage",),
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "minio-knowledge-identity-init",
                ),
            )

        if immediate_restart_services:
            runner.note("영향받은 DataRiver 서비스만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    *immediate_restart_services,
                ),
            )

        if plan.configure_keycloak and "keycloak" not in running:
            runner.note("중단된 update 재시도를 위해 Keycloak을 기동합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    *(("--pull", "never") if offline else ()),
                    "keycloak",
                ),
            )

        if plan.configure_keycloak:
            values = read_env_values(env_file)
            keycloak_env = os.environ.copy()
            keycloak_env["DATARIVER_WEB_ORIGIN"] = values["APP_PUBLIC_ORIGIN"]
            runner.note("Keycloak redirect와 service client를 현재 origin에 재적용합니다.")
            runner.run(
                (ROOT / "scripts" / "configure_keycloak_host_dev.sh",),
                env=keycloak_env,
            )

        if plan.restart_local_connectors and (state.local_redis or state.local_storage):
            connector_files: tuple[Path, ...] = (ROOT / "compose.local-connectors.yaml",)
            if offline_layout is not None:
                connector_override = release_optional_compose(
                    offline_layout,
                    "offline-local-connectors.compose.yaml",
                    required=state.local_storage,
                )
                if connector_override is not None:
                    connector_files = (*connector_files, connector_override)
            connector_services: list[str] = []
            profiles: tuple[str, ...] = ()
            connector_env = os.environ.copy()
            if state.local_redis:
                connector_services.extend(
                    service
                    for service in ("redis-cache", "redis-delivery")
                    if service in plan.local_connector_services
                )
                if offline:
                    connector_env["REDIS_IMAGE"] = "redis:8.2.6-bookworm"
            if state.local_storage and "minio" in plan.local_connector_services:
                connector_services.append("minio")
                profiles = ("object-storage",)
            if connector_services:
                runner.note("변경된 로컬 connector만 재생성합니다.")
                _compose(
                    runner,
                    env_file=env_file,
                    files=connector_files,
                    profiles=profiles,
                    trailing=(
                        "up",
                        "-d",
                        "--wait",
                        "--no-deps",
                        "--force-recreate",
                        *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                        *connector_services,
                    ),
                    env=connector_env,
                )

        if plan.restart_airflow and state.local_airflow and reconciliation_plan is None:
            airflow_files = _airflow_compose_files(
                files,
                local_gateway=operating_state.local_gateway,
            )
            if offline_layout is not None:
                airflow_override = release_optional_compose(
                    offline_layout,
                    "offline-airflow.compose.yaml",
                    required=True,
                )
                assert airflow_override is not None
                airflow_files = (*airflow_files, airflow_override)
            if not offline:
                _require_idle_builder(selected_builder, capacity_lock)
                _compose(
                    runner,
                    env_file=env_file,
                    files=airflow_files,
                    trailing=("build", *AIRFLOW_SERVICES),
                )
            runner.note("Airflow metadata migration 전에 scheduler/API를 중지합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=("stop", *AIRFLOW_SERVICES),
            )
            runner.note("Airflow DB role/database 계약을 재적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "airflow-db-init",
                ),
            )
            runner.note("Airflow metadata migration을 적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "airflow-init",
                ),
            )
            runner.note("로컬 Airflow 서비스만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    *AIRFLOW_SERVICES,
                ),
            )

        if plan.restart_datahub and state.local_datahub:
            runner.note("Mac 개발용 DataHub 구성을 재적용합니다.")
            runner.run((ROOT / "scripts" / "start_datahub_mac_dev.sh", "start-offline"))

        if plan.restart_graph and operating_state.local_graph:
            graph_files = (*files, ROOT / "compose.graph.yaml")
            if offline_layout is not None:
                graph_override = release_optional_compose(
                    offline_layout,
                    "offline-graph.compose.yaml",
                    required=True,
                )
                assert graph_override is not None
                graph_files = (*graph_files, graph_override)
            runner.note("로컬 Neo4j projection sandbox만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=graph_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    "neo4j",
                ),
            )

        if reconciliation_plan is None and plan.restart_gateway and operating_state.local_gateway:
            gateway_files = tuple(dict.fromkeys((*files, ROOT / "compose.gateway.yaml")))
            if not offline:
                _require_idle_builder(selected_builder, capacity_lock)
                _compose(
                    runner,
                    env_file=env_file,
                    files=gateway_files,
                    trailing=("build", "apisix"),
                )
            runner.note("로컬 APISIX gateway만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=gateway_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    "apisix",
                ),
            )

        if reconciliation_plan is not None:
            if topology_secret_guard is None:
                raise WorkflowError("TOPOLOGY_SECRET_PREFLIGHT_FAILED")
            _reconcile_topology_with_gateway_parity(
                session=_gateway_auth_parity_session(
                    env_file=env_file,
                    files=files,
                    secret_guard=topology_secret_guard,
                ),
                runner=runner,
                env_file=env_file,
                files=files,
                plan=reconciliation_plan,
                selected_builder=selected_builder,
                capacity_lock=capacity_lock,
                secret_guard=topology_secret_guard,
            )

        connector_changed = (
            state.local_redis
            and any(
                service in plan.local_connector_services
                for service in ("redis-cache", "redis-delivery")
            )
        ) or (state.local_storage and "minio" in plan.local_connector_services)
        auxiliary_changed = any(
            (
                plan.restart_datahub and state.local_datahub,
                plan.restart_airflow and state.local_airflow,
                plan.restart_graph and operating_state.local_graph,
                plan.restart_gateway and operating_state.local_gateway,
                connector_changed,
            )
        )
        if restart_services or plan.requires_migration or auxiliary_changed:
            runner.note("DataRiver liveness/readiness/Web health를 검증합니다.")
            _health_check(runner, env_file=env_file)
            runner.note("DataHub GMS token/version 계약을 API 컨테이너에서 검증합니다.")
            _probe_datahub(runner, env_file=env_file, files=files)

        if reconciliation_plan is not None:
            runner.note("APISIX transparent auth/header/log 계약을 state write 전에 검증합니다.")
            _verify_gateway_transparency(
                runner,
                env_file=env_file,
                files=files,
            )

        backend_changed = any(
            path.startswith("backend/") or path in {"compose.yaml", "pyproject.toml"}
            for path in changed_paths
        ) or any(key.startswith("DATAHUB_") for key in environment_keys)
        catalog_synced = False
        if (backend_changed or (plan.restart_datahub and state.local_datahub)) and (
            not args.skip_catalog_sync
        ):
            runner.note("Backend 변경 후 DataHub catalog projection을 동기화합니다.")
            _sync_catalog(runner, env_file=env_file)
            catalog_synced = True
        if catalog_synced or reapply_local_identity:
            runner.note("활성 Catalog System/Domain 범위를 로컬 관리자에게 동기화합니다.")
            _reconcile_local_admin_catalog_access(
                runner,
                env_file=env_file,
                files=files,
            )

        if reconciliation_plan is not None:
            if topology_secret_guard is None:
                raise WorkflowError("TOPOLOGY_SECRET_PREFLIGHT_FAILED")
            topology_secret_guard.revalidate()
            runner.note("Graph/gateway target topology를 state write 전에 최종 검증합니다.")
            enforce_local_topology(
                runner,
                state=operating_state,
                environment_values=environment_values,
            )

        write_applied_state(
            state_file,
            replace(
                operating_state,
                applied_commit=current_source_commit,
                runtime_commit=runtime_commit,
                env_file=(
                    os.fspath(env_file.relative_to(ROOT))
                    if env_file.is_relative_to(ROOT)
                    else os.fspath(env_file)
                ),
                release_dir=os.fspath(release_dir) if release_dir else state.release_dir,
                environment_key_hashes=current_environment_hashes,
            ),
        )
        if not changed_paths and not environment_keys:
            runner.note("적용할 source/runtime/환경 변경이 없어 컨테이너를 재시작하지 않았습니다.")
        else:
            runner.note("업데이트 적용과 선택적 재시작을 완료했습니다.")
        return 0
    except (
        DockerCapacityError,
        GatewayAuthParityError,
        WorkflowError,
        KeyError,
        OSError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        mutation_stack.close()


if __name__ == "__main__":
    raise SystemExit(main())
