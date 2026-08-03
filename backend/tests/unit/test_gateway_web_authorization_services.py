from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
OPERATOR = ROOT / "scripts" / "converge_gateway_web_authorization_services.py"


def _load_operator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "converge_gateway_web_authorization_services",
        OPERATOR,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts_path = str(ROOT / "scripts")
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


class _RecordingContext:
    def __init__(
        self,
        events: list[str],
        label: str,
        value: object,
        *,
        exit_failure: BaseException | None = None,
    ) -> None:
        self.events = events
        self.label = label
        self.value = value
        self.exit_failure = exit_failure

    def __enter__(self) -> object:
        self.events.append(f"{self.label}-enter")
        return self.value

    def __exit__(self, *_args: object) -> None:
        self.events.append(f"{self.label}-exit")
        if self.exit_failure is not None:
            raise self.exit_failure


def _success_evidence(operator: ModuleType) -> object:
    return operator.GatewayWebAuthorizationServicesConvergenceEvidence(
        classification=operator.GatewayWebAuthorizationServicesClassification.PASS,
        predicate=operator.ProductionWebInvariantPredicate.PASS,
        pre_status=operator.GatewayWebAuthorizationServicesStatus.MISSING,
        action_attempted=True,
        action_succeeded=True,
        mutation_outcome_known=True,
        post_status_known=True,
        post_status=operator.GatewayWebAuthorizationServicesStatus.MISSING,
        fingerprint_equal_known=True,
        fingerprint_equal=True,
        admin_token_grant_attempts=1,
        admin_request_attempts=7,
        mutation_count=1,
    )


def _install_runtime(
    operator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    failure: BaseException | None = None,
) -> None:
    guard = SimpleNamespace(
        file_descriptors={name: index for index, name in enumerate(operator.SECRET_NAMES)},
        file_identities={name: (index,) for index, name in enumerate(operator.SECRET_NAMES)},
        revalidate=lambda: events.append("guard-revalidate"),
    )
    monkeypatch.setattr(
        operator,
        "exclusive_docker_workflow_lock",
        lambda _root: _RecordingContext(events, "lock", object()),
    )

    def applied_state(_path: Path) -> SimpleNamespace:
        events.append("state")
        return SimpleNamespace(
            profile="mac-development",
            deployment_mode="build",
            env_file=".env.mac-development",
            environment_key_hashes={"SAFE": "digest"},
            local_gateway=False,
            local_graph=False,
            applied_commit="a" * 40,
            runtime_commit="a" * 40,
        )

    monkeypatch.setattr(operator, "load_applied_state", applied_state)

    def environment_values(_path: Path) -> dict[str, str]:
        events.append("env")
        return {"SAFE": "opaque", "KEYCLOAK_PORT": "8081"}

    monkeypatch.setattr(
        operator,
        "read_env_values",
        environment_values,
    )
    monkeypatch.setattr(operator, "environment_key_hashes", lambda _values: {"SAFE": "digest"})
    monkeypatch.setattr(
        operator,
        "_require_pinned_keycloak_runtime",
        lambda: events.append("image"),
    )
    monkeypatch.setattr(
        operator,
        "require_topology_reconciliation_secrets",
        lambda _root: _RecordingContext(events, "guard", guard),
    )

    def admin_password(_guard: object) -> str:
        events.append("password-read")
        return "admin-secret-sentinel"

    monkeypatch.setattr(operator, "_read_gateway_admin_password", admin_password)

    class Identity:
        admin_token_grant_attempts = 1
        admin_request_attempts = 7

        def __init__(self, **kwargs: object) -> None:
            assert kwargs == {
                "base_url": "http://127.0.0.1:8081",
                "admin_username": "datariver-bootstrap",
                "admin_password": "admin-secret-sentinel",
            }
            events.append("identity")

        def converge_web_authorization_services_disabled(self) -> object:
            events.append("converge")
            if failure is not None:
                raise failure
            return _success_evidence(operator)

        def release_without_mutation(self) -> None:
            events.append("release")

    monkeypatch.setattr(operator, "KeycloakGatewayAuthParityIdentity", Identity)


def _clear_forbidden_environment(
    operator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in operator._FORBIDDEN_OVERRIDE_ENVIRONMENT:
        monkeypatch.delenv(key, raising=False)


def test_fixed_gateway_web_authorization_services_operator_is_checked_in() -> None:
    assert OPERATOR.is_file()
    assert OPERATOR.stat().st_mode & 0o111


def test_operator_holds_lock_context_image_exact8_guard_and_releases_before_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []
    _install_runtime(operator, monkeypatch, events)
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 0

    assert events == [
        "lock-enter",
        "state",
        "env",
        "image",
        "guard-enter",
        "guard-revalidate",
        "password-read",
        "guard-revalidate",
        "identity",
        "converge",
        "release",
        "guard-revalidate",
        "guard-exit",
        "lock-exit",
    ]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "classification=PASS predicate=PASS pre_status=MISSING action_attempted=true "
        "action_succeeded=true mutation_outcome_known=true post_status_known=true "
        "post_status=MISSING fingerprint_equal_known=true fingerprint_equal=true "
        "admin_token_grant_attempts=1 admin_request_attempts=7 mutation_count=1 "
        "retry_count=0\n"
    )
    assert "admin-secret-sentinel" not in output.out


def test_operator_rejects_exact8_guard_key_drift_before_admin_or_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []
    _install_runtime(operator, monkeypatch, events)
    guard = SimpleNamespace(
        file_descriptors={name: index for index, name in enumerate(operator.SECRET_NAMES[:-1])},
        file_identities={name: (index,) for index, name in enumerate(operator.SECRET_NAMES[:-1])},
        revalidate=lambda: events.append("drift-guard-revalidate"),
    )
    monkeypatch.setattr(
        operator,
        "require_topology_reconciliation_secrets",
        lambda _root: _RecordingContext(events, "drift-guard", guard),
    )
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 2

    assert "password-read" not in events
    assert "identity" not in events
    assert "converge" not in events
    assert events[-2:] == ["drift-guard-exit", "lock-exit"]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("classification=UNKNOWN ")


@pytest.mark.parametrize(
    "override",
    (
        "DATARIVER_ENV_FILE",
        "DATARIVER_KEYCLOAK_CONTAINER",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "KEYCLOAK_CLIENT_ID",
        "KEYCLOAK_REALM",
        "KEYCLOAK_URL",
    ),
)
def test_operator_rejects_args_and_target_environment_overrides_before_lock_or_admin(
    override: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    entered: list[str] = []
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setenv(override, "provider-target-secret")
    monkeypatch.setattr(
        operator,
        "exclusive_docker_workflow_lock",
        lambda _root: entered.append("lock"),
    )
    monkeypatch.setattr(sys, "argv", [str(OPERATOR), "provider-argument-secret"])

    assert operator.main() == 2

    assert entered == []
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("classification=UNKNOWN ")
    assert "provider-" not in output.out


@pytest.mark.parametrize(
    "drift",
    (
        "profile",
        "deployment",
        "gateway",
        "graph",
        "commit",
        "environment-path",
        "environment-hash",
        "port",
    ),
)
def test_operator_context_drift_fails_before_image_secret_or_admin(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    state = SimpleNamespace(
        profile="portable-development" if drift == "profile" else "mac-development",
        deployment_mode="offline" if drift == "deployment" else "build",
        env_file="provider-path-secret" if drift == "environment-path" else ".env.mac-development",
        environment_key_hashes={"SAFE": "wrong" if drift == "environment-hash" else "digest"},
        local_gateway=drift == "gateway",
        local_graph=drift == "graph",
        applied_commit="a" * 40,
        runtime_commit=("b" if drift == "commit" else "a") * 40,
    )
    monkeypatch.setattr(operator, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(
        operator,
        "read_env_values",
        lambda _path: {
            "SAFE": "opaque",
            "KEYCLOAK_PORT": "provider-port-secret" if drift == "port" else "8081",
        },
    )
    monkeypatch.setattr(operator, "environment_key_hashes", lambda _values: {"SAFE": "digest"})

    with pytest.raises(
        RuntimeError,
        match=r"^GATEWAY_WEB_AUTHORIZATION_SERVICES_CONTEXT_INVALID$",
    ):
        operator._mac_environment()


def _pinned_container_document(operator: ModuleType) -> dict[str, object]:
    image_id = "sha256:" + "1" * 64
    return {
        "Image": image_id,
        "Config": {
            "Image": operator.KEYCLOAK_IMAGE,
            "Labels": {
                "com.docker.compose.project": "datariver-next",
                "com.docker.compose.service": "keycloak",
            },
        },
        "State": {"Running": True, "Health": {"Status": "healthy"}},
    }


def _pinned_image_document(operator: ModuleType) -> dict[str, object]:
    return {
        "Id": "sha256:" + "1" * 64,
        "Os": "linux",
        "Architecture": "arm64",
        "Config": {"User": "1000"},
        "RepoTags": [operator.KEYCLOAK_IMAGE],
    }


def test_operator_pins_fixed_keycloak_container_image_and_source_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    commands: list[tuple[str, ...]] = []

    def inspect(command: tuple[str, ...]) -> dict[str, object]:
        commands.append(command)
        return (
            _pinned_container_document(operator)
            if command[3] == "container"
            else _pinned_image_document(operator)
        )

    monkeypatch.setattr(operator, "_inspect_one", inspect)

    operator._require_pinned_keycloak_runtime()

    assert commands == [
        ("docker", "--context", "default", "container", "inspect", "datariver-next-keycloak-1"),
        ("docker", "--context", "default", "image", "inspect", "datariver-keycloak:26.7.0"),
    ]
    assert operator.KEYCLOAK_BASE_IMAGE in (ROOT / "infra" / "keycloak" / "Dockerfile").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "drift",
    (
        "tag",
        "project",
        "service",
        "running",
        "health",
        "container-image",
        "local-image",
        "os",
        "arch",
        "user",
        "repo-tag",
    ),
)
def test_operator_rejects_keycloak_container_or_image_identity_drift(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    container = _pinned_container_document(operator)
    image = _pinned_image_document(operator)
    config = container["Config"]
    state = container["State"]
    assert isinstance(config, dict)
    assert isinstance(state, dict)
    labels = config["Labels"]
    assert isinstance(labels, dict)
    if drift == "tag":
        config["Image"] = "provider-image-secret"
    elif drift == "project":
        labels["com.docker.compose.project"] = "provider-project-secret"
    elif drift == "service":
        labels["com.docker.compose.service"] = "provider-service-secret"
    elif drift == "running":
        state["Running"] = False
    elif drift == "health":
        state["Health"] = {"Status": "starting"}
    elif drift == "container-image":
        container["Image"] = "provider-image-secret"
    elif drift == "local-image":
        image["Id"] = "sha256:" + "2" * 64
    elif drift == "os":
        image["Os"] = "provider-os-secret"
    elif drift == "arch":
        image["Architecture"] = "amd64"
    elif drift == "user":
        image["Config"] = {"User": "0"}
    elif drift == "repo-tag":
        image["RepoTags"] = ["provider-tag-secret"]
    documents = iter((container, image))
    monkeypatch.setattr(operator, "_inspect_one", lambda _command: next(documents))

    with pytest.raises(
        RuntimeError,
        match=r"^GATEWAY_WEB_AUTHORIZATION_SERVICES_IMAGE_INVALID$",
    ) as captured:
        operator._require_pinned_keycloak_runtime()

    assert "provider-" not in str(captured.value)


@pytest.mark.parametrize("failure", (RuntimeError("raw-runtime-sentinel"), KeyboardInterrupt()))
def test_operator_baseexception_releases_identity_guard_and_lock_with_raw0(
    failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []
    _install_runtime(operator, monkeypatch, events, failure=failure)
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 2

    assert events.count("converge") == 1
    assert events.count("release") == 1
    assert events[-2:] == ["guard-exit", "lock-exit"]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("classification=UNKNOWN ")
    assert "raw-runtime-sentinel" not in output.out


def test_operator_release_failure_still_revalidates_guard_and_preserves_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []
    _install_runtime(operator, monkeypatch, events)
    identity_type = operator.KeycloakGatewayAuthParityIdentity

    def failed_release(self: object) -> None:
        del self
        events.append("release-failed")
        raise RuntimeError("raw-release-sentinel")

    monkeypatch.setattr(identity_type, "release_without_mutation", failed_release)
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 2

    assert events.count("converge") == 1
    assert events.count("release-failed") == 1
    assert events[events.index("release-failed") + 1] == "guard-revalidate"
    assert events[-2:] == ["guard-exit", "lock-exit"]
    output = capsys.readouterr()
    assert output.err == ""
    assert "classification=OPERATOR_REVIEW_REQUIRED" in output.out
    assert "action_attempted=true" in output.out
    assert "action_succeeded=true" in output.out
    assert "mutation_outcome_known=true" in output.out
    assert "mutation_count=1" in output.out
    assert "raw-release-sentinel" not in output.out


def test_operator_final_guard_revalidation_failure_preserves_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []
    _install_runtime(operator, monkeypatch, events)
    revalidations = 0

    def revalidate() -> None:
        nonlocal revalidations
        revalidations += 1
        events.append("guard-revalidate")
        if revalidations == 3:
            raise RuntimeError("raw-final-guard-sentinel")

    guard = SimpleNamespace(
        file_descriptors={name: index for index, name in enumerate(operator.SECRET_NAMES)},
        file_identities={name: (index,) for index, name in enumerate(operator.SECRET_NAMES)},
        revalidate=revalidate,
    )
    monkeypatch.setattr(
        operator,
        "require_topology_reconciliation_secrets",
        lambda _root: _RecordingContext(events, "guard", guard),
    )
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 2

    assert revalidations == 3
    assert events[-2:] == ["guard-exit", "lock-exit"]
    output = capsys.readouterr()
    assert output.err == ""
    assert "classification=OPERATOR_REVIEW_REQUIRED" in output.out
    assert "action_attempted=true" in output.out
    assert "action_succeeded=true" in output.out
    assert "mutation_count=1" in output.out
    assert "raw-final-guard-sentinel" not in output.out


@pytest.mark.parametrize("failed_context", ("guard", "lock"))
def test_operator_context_exit_failure_after_action_preserves_evidence(
    failed_context: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []
    _install_runtime(operator, monkeypatch, events)
    guard = SimpleNamespace(
        file_descriptors={name: index for index, name in enumerate(operator.SECRET_NAMES)},
        file_identities={name: (index,) for index, name in enumerate(operator.SECRET_NAMES)},
        revalidate=lambda: events.append("guard-revalidate"),
    )
    monkeypatch.setattr(
        operator,
        "exclusive_docker_workflow_lock",
        lambda _root: _RecordingContext(
            events,
            "lock",
            object(),
            exit_failure=KeyboardInterrupt() if failed_context == "lock" else None,
        ),
    )
    monkeypatch.setattr(
        operator,
        "require_topology_reconciliation_secrets",
        lambda _root: _RecordingContext(
            events,
            "guard",
            guard,
            exit_failure=(
                RuntimeError("raw-guard-exit-sentinel") if failed_context == "guard" else None
            ),
        ),
    )
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 2

    assert events.count("converge") == 1
    assert events.count("release") == 1
    assert events[-1] == "lock-exit"
    output = capsys.readouterr()
    assert output.err == ""
    assert "classification=OPERATOR_REVIEW_REQUIRED" in output.out
    assert "action_attempted=true" in output.out
    assert "action_succeeded=true" in output.out
    assert "mutation_outcome_known=true" in output.out
    assert "mutation_count=1" in output.out
    assert "raw-" not in output.out


def test_operator_outer_fallback_preserves_monotonic_action_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()

    class AttemptedIdentity:
        web_authorization_services_action_attempted = True
        web_authorization_services_action_succeeded = False
        admin_token_grant_attempts = 1
        admin_request_attempts = 4

    def failed_run(runtime: Any) -> object:
        runtime.identity = AttemptedIdentity()
        raise KeyboardInterrupt()

    monkeypatch.setattr(operator, "_run_convergence", failed_run)
    _clear_forbidden_environment(operator, monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 2

    output = capsys.readouterr()
    assert output.err == ""
    assert "classification=OPERATOR_REVIEW_REQUIRED" in output.out
    assert "action_attempted=true" in output.out
    assert "action_succeeded=false" in output.out
    assert "mutation_outcome_known=false" in output.out
    assert "admin_token_grant_attempts=1" in output.out
    assert "admin_request_attempts=4" in output.out
    assert "mutation_count=1" in output.out


def test_operator_source_forbids_broad_keycloak_mutation_and_full_updater() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    for forbidden in (
        "configure_keycloak_host_dev",
        '"DELETE"',
        '"POST"',
        "create_disabled_fixture",
        "cleanup_client",
        "write_applied_state",
        "docker compose",
        "kcadm",
    ):
        assert forbidden not in source
    assert "converge_web_authorization_services_disabled" in source
