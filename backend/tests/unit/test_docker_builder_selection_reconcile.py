from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
OPERATOR = ROOT / "scripts" / "reconcile_docker_builder_selection.py"


def _load_operator() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "reconcile_docker_builder_selection_for_test",
        OPERATOR,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    scripts_path = str(ROOT / "scripts")
    sys.path.insert(0, scripts_path)
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


def _diagnostic_observation(evidence: Any) -> Any:
    assert evidence.observation is not None
    return evidence.observation


def _builder_rows(*, target_current: bool = False) -> str:
    prior = {
        "Current": not target_current,
        "Driver": "docker-container",
        "Name": "managed-builder",
        "Nodes": [
            {
                "Endpoint": "desktop-linux",
                "Name": "managed-builder0",
                "Status": "running",
            }
        ],
    }
    target = {
        "Current": target_current,
        "Driver": "docker",
        "Name": "desktop-linux",
        "Nodes": [
            {
                "Endpoint": "desktop-linux",
                "Name": "desktop-linux",
                "Status": "running",
            }
        ],
    }
    return "\n".join((json.dumps(prior), json.dumps(target)))


class _Lock:
    def require_held(self) -> None:
        return None


class _LockContext:
    def __init__(self, exit_failure: BaseException | None = None) -> None:
        self.exit_failure = exit_failure

    def __enter__(self) -> _Lock:
        return _Lock()

    def __exit__(self, *_args: object) -> None:
        if self.exit_failure is not None:
            raise self.exit_failure


class _Executor:
    def __init__(
        self,
        *,
        action_error: BaseException | None = None,
        apply_action: bool = True,
        target_active: bool = False,
        inventory_drift_count: int = 0,
        rollback_error: BaseException | None = None,
        apply_rollback: bool = True,
        version_output: str | None = None,
        version_error: BaseException | None = None,
        daemon_output: str = "28.5.1\n",
        daemon_error: BaseException | None = None,
        daemon_outcome: Any | None = None,
        desktop_status_output: str = '{"Status":"running"}',
        desktop_status_error: BaseException | None = None,
        desktop_status_outcome: Any | None = None,
    ) -> None:
        self.action_error = action_error
        self.apply_action = apply_action
        self.target_active = target_active
        self.inventory_drift_count = inventory_drift_count
        self.rollback_error = rollback_error
        self.apply_rollback = apply_rollback
        self.version_output = (
            "github.com/docker/buildx v0.35.0 " + "a" * 40 + "\n"
            if version_output is None
            else version_output
        )
        self.version_error = version_error
        self.daemon_output = daemon_output
        self.daemon_error = daemon_error
        self.daemon_outcome = daemon_outcome
        self.desktop_status_output = desktop_status_output
        self.desktop_status_error = desktop_status_error
        self.desktop_status_outcome = desktop_status_outcome
        self.selected = "managed-builder"
        self.calls: list[tuple[str, ...]] = []
        self.selection_calls: list[tuple[str, ...]] = []

    def _rows(self) -> str:
        rows = [json.loads(row) for row in _builder_rows().splitlines()]
        for row in rows:
            row["Current"] = row["Name"] == self.selected
        if self.inventory_drift_count and self.selection_calls:
            for index in range(self.inventory_drift_count):
                name = f"drifted-builder-{index}"
                rows.append(
                    {
                        "Current": False,
                        "Driver": "docker-container",
                        "Name": name,
                        "Nodes": [
                            {
                                "Endpoint": "desktop-linux",
                                "Name": f"{name}-node",
                                "Status": "running",
                            }
                        ],
                    }
                )
        return "\n".join(json.dumps(row) for row in rows)

    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str:
        del classification, timeout_seconds
        self.calls.append(arguments)
        if arguments == ("docker", "buildx", "version"):
            if self.version_error is not None:
                raise self.version_error
            return self.version_output
        if arguments == ("docker", "version", "--format", "{{.Server.Version}}"):
            if self.daemon_error is not None:
                raise self.daemon_error
            return self.daemon_output
        if arguments == ("docker", "buildx", "ls", "--format", "{{json .}}"):
            return self._rows()
        if arguments[:4] == ("docker", "buildx", "history", "ls"):
            builder = arguments[arguments.index("--builder") + 1]
            if (
                builder == "desktop-linux"
                and self.selected == "desktop-linux"
                and self.target_active
            ):
                return "running\n"
            return ""
        if arguments == ("docker", "buildx", "use", "desktop-linux"):
            self.selection_calls.append(arguments)
            if self.apply_action:
                self.selected = "desktop-linux"
            if self.action_error is not None:
                raise self.action_error
            return "raw-provider-selection-sentinel"
        if arguments == ("docker", "buildx", "use", "managed-builder"):
            self.selection_calls.append(arguments)
            if self.apply_rollback:
                self.selected = "managed-builder"
                self.target_active = False
            if self.rollback_error is not None:
                raise self.rollback_error
            return "raw-provider-rollback-sentinel"
        raise AssertionError(f"unexpected argv: {arguments!r}")

    def bounded_outcome(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> Any:
        del classification, timeout_seconds
        self.calls.append(arguments)
        if arguments == ("docker", "version", "--format", "{{.Server.Version}}"):
            if self.daemon_error is not None:
                raise self.daemon_error
            assert self.daemon_outcome is not None
            return self.daemon_outcome
        if arguments == ("docker", "desktop", "status", "--format", "json"):
            if self.desktop_status_error is not None:
                raise self.desktop_status_error
            assert self.desktop_status_outcome is not None
            return self.desktop_status_outcome
        raise AssertionError(f"unexpected bounded argv: {arguments!r}")


class _ContextDefaultExecutor(_Executor):
    def _rows(self) -> str:
        return json.dumps(
            {
                "Current": True,
                "Driver": "",
                "Err": "raw-builder-error-sentinel",
                "Name": "desktop-linux",
                "Nodes": [
                    {
                        "Endpoint": "desktop-linux",
                        "Name": "desktop-linux",
                    }
                ],
            }
        )


def _context_default_executor(
    operator: ModuleType,
    *,
    outcome_kind: str = "SUCCESS",
    daemon_output: str = "28.5.1\n",
    daemon_error: BaseException | None = None,
) -> _ContextDefaultExecutor:
    output = daemon_output if outcome_kind == "SUCCESS" else None
    outcome = operator._BoundedProcessOutcome(
        operator._BoundedProcessOutcomeKind[outcome_kind],
        output,
    )
    return _ContextDefaultExecutor(
        daemon_output=daemon_output,
        daemon_error=daemon_error,
        daemon_outcome=outcome,
    )


def _desktop_status_executor(
    operator: ModuleType,
    *,
    outcome_kind: str = "SUCCESS",
    output: str = '{"Status":"running"}',
    error: BaseException | None = None,
) -> _Executor:
    bounded_output = output if outcome_kind == "SUCCESS" else None
    outcome = operator._BoundedProcessOutcome(
        operator._BoundedProcessOutcomeKind[outcome_kind],
        bounded_output,
    )
    return _Executor(
        desktop_status_output=output,
        desktop_status_error=error,
        desktop_status_outcome=outcome,
    )


def _install_fixed_context(
    operator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    lock_exit_failure: BaseException | None = None,
) -> None:
    monkeypatch.setattr(operator.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(operator.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        operator,
        "exclusive_docker_workflow_lock",
        lambda _root: _LockContext(lock_exit_failure),
    )
    monkeypatch.setattr(operator, "_source_identity", lambda _executor: "a" * 40)
    host_identity = operator._HostIdentity(
        state=("fixed",),
        environment_fingerprint=(("SAFE", "b" * 64),),
    )
    monkeypatch.setattr(operator, "_host_identity", lambda _root: host_identity)
    monkeypatch.setattr(
        operator,
        "require_local_unix_docker_context",
        lambda _executor, _environ: "desktop-linux",
    )


def test_fixed_builder_selection_operator_is_checked_in_and_no_argument() -> None:
    operator = _load_operator()

    assert OPERATOR.is_file()
    assert tuple(operator.BuilderSelectionReconcilePredicate) == (
        operator.BuilderSelectionReconcilePredicate.ARGUMENTS,
        operator.BuilderSelectionReconcilePredicate.PLATFORM,
        operator.BuilderSelectionReconcilePredicate.SOURCE,
        operator.BuilderSelectionReconcilePredicate.HOST_ENVIRONMENT,
        operator.BuilderSelectionReconcilePredicate.ENVIRONMENT_OVERRIDE,
        operator.BuilderSelectionReconcilePredicate.DOCKER_CONTEXT,
        operator.BuilderSelectionReconcilePredicate.BUILDER_INVENTORY,
        operator.BuilderSelectionReconcilePredicate.PRESTATE,
        operator.BuilderSelectionReconcilePredicate.ACTIVE_BUILDS,
        operator.BuilderSelectionReconcilePredicate.ACTION,
        operator.BuilderSelectionReconcilePredicate.POSTSTATE,
        operator.BuilderSelectionReconcilePredicate.ROLLBACK,
        operator.BuilderSelectionReconcilePredicate.PASS,
        operator.BuilderSelectionReconcilePredicate.UNKNOWN,
    )


def test_builder_selection_plan_uses_only_fixed_context_target() -> None:
    operator = _load_operator()

    evaluation = operator.evaluate_docker_builder_selection_plan(
        _builder_rows(),
        {},
        current_context="desktop-linux",
    )
    assert evaluation.plan is not None
    plan = evaluation.plan

    assert plan.prior_builder == "managed-builder"
    assert plan.target_builder == "desktop-linux"
    assert plan.selection_argv == ("docker", "buildx", "use", "desktop-linux")
    assert "--default" not in plan.selection_argv
    assert "--global" not in plan.selection_argv


def test_builder_selection_output_is_fixed_value_free_and_bounded() -> None:
    operator = _load_operator()
    evidence = operator.BuilderSelectionReconcileEvidence.pass_evidence()

    line = operator.format_builder_selection_reconcile_evidence(evidence)
    document = json.loads(line)

    assert document == {
        "action_attempted": True,
        "action_succeeded": True,
        "build_count": 0,
        "builder_selection_predicate": "DRIVER_NOT_DOCKER",
        "cache_action_count": 0,
        "classification": "PASS",
        "container_action_count": 0,
        "mutation_outcome_known": True,
        "poststate_known": True,
        "poststate_valid": True,
        "predicate": "PASS",
        "prior_driver_known": True,
        "prior_driver_predicate": "PASS",
        "prestate_checkpoint": "REPROOF",
        "prestate_known": True,
        "prestate_predicate": "PASS",
        "node_schema_predicate": "PASS",
        "residual_count": 0,
        "residual_known": True,
        "retry_count": 0,
        "rollback_attempted": False,
        "rollback_count": 0,
        "rollback_outcome_known": True,
        "rollback_succeeded": False,
        "selection_mutation_count": 1,
    }
    assert len(line.encode("utf-8")) <= operator.MAXIMUM_EVIDENCE_BYTES


def test_unknown_residual_never_estimates_or_leaks() -> None:
    operator = _load_operator()
    evidence = operator.BuilderSelectionReconcileEvidence.review_required_after_action()

    line = operator.format_builder_selection_reconcile_evidence(evidence)

    assert "residual_count" not in json.loads(line)
    assert "raw-builder-sentinel" not in line


@pytest.mark.parametrize(
    "case",
    (
        "known-without-fields",
        "false-with-fields",
        "known-with-null",
        "known-with-unknown",
        "prior-known-without-predicate",
        "prior-known-with-unknown",
        "prior-contradiction",
    ),
)
def test_prestate_evidence_rejects_partial_null_unknown_and_untyped_shapes(
    case: str,
) -> None:
    operator = _load_operator()
    values: dict[str, Any] = {
        "classification": operator.BuilderSelectionReconcileClassification.REJECTED,
        "predicate": operator.BuilderSelectionReconcilePredicate.SOURCE,
        "action_attempted": False,
        "action_succeeded": False,
        "mutation_outcome_known": False,
        "poststate_known": False,
        "poststate_valid": False,
        "rollback_attempted": False,
        "rollback_succeeded": False,
        "rollback_outcome_known": True,
        "selection_mutation_count": 0,
        "residual_known": True,
        "residual_count": 0,
    }
    if case == "known-without-fields":
        values["prestate_known"] = True
    elif case == "false-with-fields":
        values["prestate_known"] = False
        values["prestate_checkpoint"] = "CAPTURE"
    elif case == "known-with-null":
        values["prestate_known"] = True
        values["prestate_checkpoint"] = None
        values["prestate_predicate"] = None
    elif case == "known-with-unknown":
        values["prestate_known"] = True
        values["prestate_checkpoint"] = operator.BuilderSelectionPrestateCheckpoint.CAPTURE
        values["prestate_predicate"] = operator.DockerBuilderSelectionPlanPredicate.UNKNOWN
    elif case == "prior-known-without-predicate":
        values["prior_driver_known"] = True
    elif case == "prior-known-with-unknown":
        values["prior_driver_known"] = True
        values["prior_driver_predicate"] = operator.PriorDriverPredicate.UNKNOWN
    else:
        values.update(
            {
                "prestate_known": True,
                "prestate_checkpoint": operator.BuilderSelectionPrestateCheckpoint.CAPTURE,
                "prestate_predicate": (
                    operator.DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL
                ),
                "builder_selection_predicate": operator.BuilderSelectionPredicate.PASS,
                "node_schema_predicate": operator.NodeSchemaPredicate.PASS,
                "prior_driver_known": True,
                "prior_driver_predicate": operator.PriorDriverPredicate.REMOTE,
            }
        )

    with pytest.raises(ValueError, match="DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID"):
        operator.BuilderSelectionReconcileEvidence(**values)


@pytest.mark.parametrize(
    "field",
    (
        "cache_action_count",
        "build_count",
        "container_action_count",
        "retry_count",
    ),
)
def test_evidence_rejects_every_forbidden_action_count(field: str) -> None:
    operator = _load_operator()
    values: dict[str, Any] = {
        "classification": operator.BuilderSelectionReconcileClassification.REJECTED,
        "predicate": operator.BuilderSelectionReconcilePredicate.ACTION,
        "action_attempted": True,
        "action_succeeded": False,
        "mutation_outcome_known": True,
        "poststate_known": True,
        "poststate_valid": False,
        "rollback_attempted": False,
        "rollback_succeeded": False,
        "rollback_outcome_known": True,
        "selection_mutation_count": 1,
        "residual_known": True,
        "residual_count": 0,
        field: 1,
    }

    with pytest.raises(ValueError, match="DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID"):
        operator.BuilderSelectionReconcileEvidence(**values)


def test_success_runs_one_exact_selection_and_proves_both_builders_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor()
    runtime = operator._RuntimeState()

    evidence = operator._run_operator(runtime, executor=executor, environ={})

    assert evidence == operator.BuilderSelectionReconcileEvidence.pass_evidence()
    assert executor.selection_calls == [("docker", "buildx", "use", "desktop-linux")]
    assert executor.calls.count(("docker", "buildx", "ls", "--format", "{{json .}}")) == 3
    history = [call for call in executor.calls if call[:4] == ("docker", "buildx", "history", "ls")]
    assert len(history) == 6
    assert not any(
        forbidden in call
        for call in executor.calls
        for forbidden in ("create", "remove", "stop", "prune", "build", "volume")
    )


def test_response_loss_with_proven_target_is_accepted_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(action_error=RuntimeError("raw-response-sentinel"))

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.PASS
    assert evidence.action_succeeded is True
    assert evidence.mutation_outcome_known is True
    assert len(executor.selection_calls) == 1
    assert "raw-response-sentinel" not in operator.format_builder_selection_reconcile_evidence(
        evidence
    )


def test_interrupt_after_action_preserves_proven_mutation_but_requires_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(action_error=KeyboardInterrupt("raw-interrupt-sentinel"))

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.action_attempted is True
    assert evidence.action_succeeded is True
    assert evidence.mutation_outcome_known is True
    assert evidence.poststate_valid is True
    assert evidence.residual_count == 0
    assert len(executor.selection_calls) == 1


def test_failed_action_with_exact_prior_state_is_known_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(
        action_error=RuntimeError("raw-action-sentinel"),
        apply_action=False,
    )

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.ACTION
    assert evidence.action_attempted is True
    assert evidence.action_succeeded is False
    assert evidence.mutation_outcome_known is True
    assert evidence.residual_count == 0
    assert len(executor.selection_calls) == 1


def test_target_active_poststate_rolls_back_once_only_after_prior_idle_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(target_active=True)

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.POSTSTATE
    assert evidence.action_succeeded is True
    assert evidence.rollback_attempted is True
    assert evidence.rollback_succeeded is True
    assert evidence.rollback_outcome_known is True
    assert evidence.selection_mutation_count == 2
    assert evidence.residual_count == 0
    assert executor.selection_calls == [
        ("docker", "buildx", "use", "desktop-linux"),
        ("docker", "buildx", "use", "managed-builder"),
    ]


def test_rollback_response_loss_is_accepted_only_after_exact_prior_reproof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(
        target_active=True,
        rollback_error=RuntimeError("raw-rollback-response-sentinel"),
    )

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.rollback_attempted is True
    assert evidence.rollback_succeeded is True
    assert evidence.rollback_outcome_known is True
    assert evidence.residual_count == 0
    assert len(executor.selection_calls) == 2
    assert "raw-rollback" not in operator.format_builder_selection_reconcile_evidence(evidence)


def test_ambiguous_rollback_stops_without_a_third_selection_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(
        target_active=True,
        rollback_error=RuntimeError("raw-rollback-sentinel"),
        apply_rollback=False,
    )

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.rollback_attempted is True
    assert evidence.rollback_succeeded is False
    assert evidence.rollback_outcome_known is False
    assert evidence.selection_mutation_count == 2
    assert len(executor.selection_calls) == 2


def test_inventory_drift_never_rolls_back_or_estimates_residual_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(inventory_drift_count=1)

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.rollback_attempted is False
    assert evidence.residual_known is True
    assert evidence.residual_count is not None
    assert evidence.residual_count > 0
    assert len(executor.selection_calls) == 1


def test_post_proof_baseexception_preserves_action_and_never_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    source_calls = 0

    def source(_executor: object) -> str:
        nonlocal source_calls
        source_calls += 1
        if source_calls == 3:
            raise KeyboardInterrupt("raw-post-proof-sentinel")
        return "a" * 40

    monkeypatch.setattr(operator, "_source_identity", source)
    executor = _Executor()

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.action_attempted is True
    assert evidence.mutation_outcome_known is False
    assert evidence.residual_known is False
    assert evidence.rollback_attempted is False
    assert len(executor.selection_calls) == 1


@pytest.mark.parametrize(
    ("drift", "expected_predicate"),
    (
        ("source", "SOURCE"),
        ("host", "HOST_ENVIRONMENT"),
        ("override", "ENVIRONMENT_OVERRIDE"),
        ("context", "DOCKER_CONTEXT"),
        ("inventory", "PRESTATE"),
        ("active", "ACTIVE_BUILDS"),
    ),
)
def test_final_prestate_reproof_rejects_every_drift_before_selection(
    drift: str,
    expected_predicate: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    environ: dict[str, str] = {}
    source_calls = 0
    host_calls = 0
    context_calls = 0

    def source(_executor: object) -> str:
        nonlocal source_calls
        source_calls += 1
        if drift == "override" and source_calls == 2:
            environ["BUILDX_BUILDER"] = "raw-override-sentinel"
        return ("b" if drift == "source" and source_calls == 2 else "a") * 40

    fixed_host = operator._HostIdentity(
        state=("fixed",),
        environment_fingerprint=(("SAFE", "b" * 64),),
    )

    def host(_root: object) -> object:
        nonlocal host_calls
        host_calls += 1
        if drift == "host" and host_calls == 2:
            return operator._HostIdentity(
                state=("drifted",),
                environment_fingerprint=(("SAFE", "c" * 64),),
            )
        return fixed_host

    def context(_executor: object, _environ: object) -> str:
        nonlocal context_calls
        context_calls += 1
        return "other-context" if drift == "context" and context_calls == 2 else "desktop-linux"

    monkeypatch.setattr(operator, "_source_identity", source)
    monkeypatch.setattr(operator, "_host_identity", host)
    monkeypatch.setattr(operator, "require_local_unix_docker_context", context)
    executor = _Executor()
    if drift == "inventory":
        original_rows = executor._rows
        listing_calls = 0

        def rows() -> str:
            nonlocal listing_calls
            listing_calls += 1
            if listing_calls == 2:
                executor.selected = "desktop-linux"
            return original_rows()

        executor._rows = rows  # type: ignore[method-assign]
    if drift == "active":
        idle_results = iter((True, True, True, False))
        monkeypatch.setattr(
            operator,
            "docker_builder_is_idle",
            lambda **_kwargs: next(idle_results),
        )

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ=environ,
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate.value == expected_predicate
    assert evidence.action_attempted is False
    assert executor.selection_calls == []
    assert "raw-" not in operator.format_builder_selection_reconcile_evidence(evidence)


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt(), SystemExit(), BaseException()))
def test_final_prestate_reproof_interrupt_is_unknown_and_action_zero(
    interrupt: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    source_calls = 0

    def source(_executor: object) -> str:
        nonlocal source_calls
        source_calls += 1
        if source_calls == 2:
            raise interrupt
        return "a" * 40

    monkeypatch.setattr(operator, "_source_identity", source)
    executor = _Executor()

    evidence = operator._run_operator(operator._RuntimeState(), executor=executor, environ={})

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.action_attempted is False
    assert executor.selection_calls == []


def test_final_reproof_and_active_checks_are_immediately_before_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    events: list[str] = []
    fixed_host = operator._HostIdentity(
        state=("fixed",),
        environment_fingerprint=(("SAFE", "b" * 64),),
    )

    def source(_executor: object) -> str:
        events.append("source")
        return "a" * 40

    def host(_root: object) -> Any:
        events.append("host")
        return fixed_host

    def context(_executor: object, _environ: object) -> str:
        events.append("context")
        return "desktop-linux"

    monkeypatch.setattr(operator, "_source_identity", source)
    monkeypatch.setattr(operator, "_host_identity", host)
    monkeypatch.setattr(operator, "require_local_unix_docker_context", context)

    class RecordingExecutor(_Executor):
        def output(
            self,
            arguments: tuple[str, ...],
            *,
            classification: str,
            timeout_seconds: int,
        ) -> str:
            if arguments == ("docker", "buildx", "ls", "--format", "{{json .}}"):
                events.append("inventory")
            elif arguments[:4] == ("docker", "buildx", "history", "ls"):
                events.append(f"idle:{arguments[arguments.index('--builder') + 1]}")
            elif arguments[:3] == ("docker", "buildx", "use"):
                events.append("use")
            return super().output(
                arguments,
                classification=classification,
                timeout_seconds=timeout_seconds,
            )

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=RecordingExecutor(),
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.PASS
    assert events[:13] == [
        "source",
        "host",
        "context",
        "inventory",
        "idle:managed-builder",
        "idle:desktop-linux",
        "source",
        "host",
        "context",
        "inventory",
        "idle:managed-builder",
        "idle:desktop-linux",
        "use",
    ]


@pytest.mark.parametrize("residual_count", (128, 129))
def test_residual_evidence_is_exact_at_bound_and_unknown_above_it(
    residual_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(inventory_drift_count=residual_count)

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.residual_known is (residual_count == 128)
    assert evidence.residual_count == (128 if residual_count == 128 else None)
    document = json.loads(operator.format_builder_selection_reconcile_evidence(evidence))
    assert ("residual_count" in document) is (residual_count == 128)


def test_residual_over_bound_survives_lock_exit_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(
        operator,
        monkeypatch,
        lock_exit_failure=KeyboardInterrupt("raw-lock-sentinel"),
    )
    executor = _Executor(inventory_drift_count=129)

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.residual_known is False
    assert evidence.residual_count is None
    assert "raw-" not in operator.format_builder_selection_reconcile_evidence(evidence)


def test_main_fallback_formats_normalized_overbound_residual_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()

    def fail_after_normalization(runtime: object) -> object:
        typed_runtime: Any = runtime
        typed_runtime.action_attempted = True
        typed_runtime.residual_known = False
        typed_runtime.residual_count = None
        raise BaseException("raw-overbound-fallback-sentinel")

    monkeypatch.setattr(operator, "_run_operator", fail_after_normalization)
    monkeypatch.setattr(sys, "argv", [str(OPERATOR)])

    assert operator.main() == 2

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert captured.err == ""
    assert document["residual_known"] is False
    assert "residual_count" not in document
    assert "raw-" not in captured.out


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt(), SystemExit(), BaseException()))
@pytest.mark.parametrize("apply_rollback", (True, False))
def test_rollback_interrupt_preserves_observed_state_but_requires_review(
    interrupt: BaseException,
    apply_rollback: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(
        target_active=True,
        rollback_error=interrupt,
        apply_rollback=apply_rollback,
    )

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.rollback_attempted is True
    assert evidence.rollback_succeeded is apply_rollback
    assert evidence.rollback_outcome_known is True
    assert evidence.selection_mutation_count == 2
    assert len(executor.selection_calls) == 2
    assert "raw-" not in operator.format_builder_selection_reconcile_evidence(evidence)


def test_unreaped_action_stops_without_post_proof_or_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(action_error=operator._ProcessUnreaped(), apply_action=True)

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.action_attempted is True
    assert evidence.mutation_outcome_known is False
    assert evidence.poststate_known is False
    assert evidence.residual_known is False
    assert evidence.rollback_attempted is False
    assert executor.selection_calls == [("docker", "buildx", "use", "desktop-linux")]
    assert executor.calls[-1] == executor.selection_calls[-1]


def test_unreaped_read_only_prestate_process_is_review_required_action_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    monkeypatch.setattr(
        operator,
        "_source_identity",
        lambda _executor: (_ for _ in ()).throw(operator._ProcessUnreaped()),
    )
    executor = _Executor()

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.action_attempted is False
    assert evidence.selection_mutation_count == 0
    assert executor.selection_calls == []


def test_unreaped_rollback_stops_without_post_proof_or_third_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(
        target_active=True,
        rollback_error=operator._ProcessUnreaped(),
        apply_rollback=True,
    )

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.selection_mutation_count == 2
    assert evidence.rollback_attempted is True
    assert evidence.rollback_outcome_known is False
    assert evidence.mutation_outcome_known is False
    assert evidence.poststate_known is False
    assert evidence.residual_known is False
    assert len(executor.selection_calls) == 2
    assert executor.calls[-1] == executor.selection_calls[-1]


def test_prestate_active_builder_stops_before_selection_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    idle = iter((True, False))
    monkeypatch.setattr(operator, "docker_builder_is_idle", lambda **_kwargs: next(idle))
    executor = _Executor()

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.ACTIVE_BUILDS
    assert evidence.action_attempted is False
    assert executor.selection_calls == []


@pytest.mark.parametrize(
    "exit_failure",
    (
        RuntimeError("raw-lock-exit-sentinel"),
        KeyboardInterrupt("raw-lock-interrupt-sentinel"),
    ),
)
def test_lock_exit_failure_preserves_completed_action_and_post_proof(
    exit_failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch, lock_exit_failure=exit_failure)
    executor = _Executor()

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.action_attempted is True
    assert evidence.action_succeeded is True
    assert evidence.mutation_outcome_known is True
    assert evidence.poststate_known is True
    assert evidence.poststate_valid is True
    assert evidence.residual_count == 0


@pytest.mark.parametrize("override", ("BUILDKIT_HOST", "BUILDX_BUILDER"))
def test_builder_environment_override_stops_before_context_or_action(
    override: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor()

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={override: "raw-override-sentinel"},
    )

    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.ENVIRONMENT_OVERRIDE
    assert evidence.action_attempted is False
    assert executor.calls == []


def test_extra_arguments_are_rejected_before_lock_without_raw_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    entered: list[str] = []
    monkeypatch.setattr(
        operator,
        "exclusive_docker_workflow_lock",
        lambda _root: entered.append("lock"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(OPERATOR), "raw-argument-sentinel"],
    )

    assert operator.main() == 2

    assert entered == []
    output = capsys.readouterr()
    assert output.err == ""
    assert "raw-argument-sentinel" not in output.out
    assert json.loads(output.out)["predicate"] == "ARGUMENTS"


def test_read_only_prestate_diagnostic_reproves_plan_and_stops_before_active_or_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor()
    runtime = operator._RuntimeState()

    evidence = operator._run_prestate_diagnostic(runtime, executor=executor, environ={})

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.PASS
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.PASS
    assert evidence.phase == "BUILDER_SELECTION_PRESTATE"
    assert evidence.prestate_known is True
    assert evidence.prestate_checkpoint.value == "REPROOF"
    assert evidence.prestate_predicate.value == "PASS"
    observation = _diagnostic_observation(evidence)
    assert observation.builder_selection.value == "DRIVER_NOT_DOCKER"
    assert observation.node_schema.value == "PASS"
    assert observation.prior_driver.value == "PASS"
    assert observation.builder_error.value == "ABSENT"
    assert observation.buildx_authority.value == "UPSTREAM_V0_35_0"
    assert evidence.action_count == 0
    assert evidence.rollback_count == 0
    assert evidence.selection_mutation_count == 0
    assert evidence.retry_count == 0
    assert not any(call[:4] == ("docker", "buildx", "history", "ls") for call in executor.calls)
    assert executor.selection_calls == []
    assert executor.calls.count(("docker", "buildx", "version")) == 1


def test_read_only_prestate_diagnostic_classifies_capture_and_reproof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    capture_executor = _Executor()
    capture_executor.selected = "desktop-linux"

    capture = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=capture_executor,
        environ={},
    )

    assert capture.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert capture.predicate is operator.BuilderSelectionReconcilePredicate.PRESTATE
    assert capture.prestate_checkpoint.value == "CAPTURE"
    assert capture.prestate_predicate.value == "CURRENT_ALREADY_CANONICAL"
    capture_observation = _diagnostic_observation(capture)
    assert capture_observation.builder_selection.value == "PASS"
    assert capture_observation.node_schema.value == "PASS"
    assert capture_observation.prior_driver is operator.PriorDriverPredicate.UNRECOGNIZED
    assert capture_executor.selection_calls == []

    class ReorderedExecutor(_Executor):
        listing_count = 0

        def _rows(self) -> str:
            self.listing_count += 1
            rows = super()._rows().splitlines()
            if self.listing_count == 2:
                rows.reverse()
            return "\n".join(rows)

    reproof_executor = ReorderedExecutor()
    reproof = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=reproof_executor,
        environ={},
    )

    assert reproof.classification is operator.BuilderSelectionReconcileClassification.PASS
    assert reproof.predicate is operator.BuilderSelectionReconcilePredicate.PASS
    assert reproof.prestate_checkpoint.value == "REPROOF"
    assert reproof.prestate_predicate.value == "PASS"
    assert _diagnostic_observation(reproof).prior_driver.value == "PASS"
    assert reproof_executor.selection_calls == []


@pytest.mark.parametrize(
    ("driver", "expected"),
    (
        ("", "EMPTY"),
        ("cloud", "CLOUD"),
        ("kubernetes", "KUBERNETES"),
        ("remote", "REMOTE"),
        ("future-driver-raw-sentinel", "UNRECOGNIZED"),
    ),
)
def test_prestate_diagnostic_classifies_prior_driver_without_action(
    driver: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)

    class PriorDriverExecutor(_Executor):
        def _rows(self) -> str:
            rows = [json.loads(row) for row in super()._rows().splitlines()]
            rows[0]["Driver"] = driver
            rows[0]["Nodes"][0]["Status"] = "stopped"
            rows[1]["Driver"] = "remote"
            return "\n".join(json.dumps(row) for row in rows)

    diagnostic_executor = PriorDriverExecutor()
    diagnostic = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=diagnostic_executor,
        environ={},
    )
    operator_executor = PriorDriverExecutor()
    ordinary = operator._run_operator(
        operator._RuntimeState(),
        executor=operator_executor,
        environ={},
    )

    assert diagnostic.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert diagnostic.predicate is operator.BuilderSelectionReconcilePredicate.PRESTATE
    assert diagnostic.prestate_checkpoint is operator.BuilderSelectionPrestateCheckpoint.CAPTURE
    assert (
        diagnostic.prestate_predicate is operator.DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER
    )
    observation = _diagnostic_observation(diagnostic)
    assert observation.prior_driver.value == expected
    assert observation.builder_error.value == "ABSENT"
    assert observation.buildx_authority.value == "UPSTREAM_V0_35_0"
    assert observation.prior_target_relation.value == "DISTINCT"
    assert observation.prior_status.value == "STOPPED"
    assert observation.prior_node_error.value == "ABSENT"
    assert observation.target_contract.value == "DRIVER"
    assert diagnostic.action_count == 0
    assert diagnostic_executor.selection_calls == []
    assert ordinary.predicate is operator.BuilderSelectionReconcilePredicate.PRESTATE
    assert ordinary.prior_driver_predicate.value == expected
    assert ordinary.action_attempted is False
    assert operator_executor.selection_calls == []
    assert ("docker", "buildx", "version") not in operator_executor.calls
    assert "raw-sentinel" not in operator.format_builder_selection_prestate_diagnostic(diagnostic)


@pytest.mark.parametrize(
    ("err_present", "err_value", "expected"),
    (
        (False, None, "ABSENT"),
        (True, "raw-builder-error-sentinel", "PRESENT"),
        (True, "", "INVALID"),
        (True, None, "INVALID"),
        (True, ["raw-builder-error-sentinel"], "INVALID"),
    ),
)
def test_prestate_diagnostic_reports_only_builder_error_shape(
    err_present: bool,
    err_value: object,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)

    class BuilderErrorExecutor(_Executor):
        def _rows(self) -> str:
            rows = [json.loads(row) for row in super()._rows().splitlines()]
            rows[0]["Driver"] = "raw-unrecognized-driver-sentinel"
            if err_present:
                rows[0]["Err"] = err_value
            return "\n".join(json.dumps(row) for row in rows)

    executor = BuilderErrorExecutor()
    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.PRESTATE
    observation = _diagnostic_observation(evidence)
    assert observation.prior_driver is operator.PriorDriverPredicate.UNRECOGNIZED
    assert observation.builder_error.value == expected
    assert executor.selection_calls == []
    line = operator.format_builder_selection_prestate_diagnostic(evidence)
    assert "raw-builder" not in line
    assert "raw-unrecognized" not in line


_BUILDER_ERROR_ABSENT = object()


class _BuilderErrorTransitionExecutor(_Executor):
    def __init__(self, capture: object, reproof: object) -> None:
        super().__init__()
        self._builder_error_states = (capture, reproof)
        self._listing_count = 0

    def _rows(self) -> str:
        rows = [json.loads(row) for row in super()._rows().splitlines()]
        state = self._builder_error_states[min(self._listing_count, 1)]
        self._listing_count += 1
        if state is not _BUILDER_ERROR_ABSENT:
            rows[0]["Err"] = state
        return "\n".join(json.dumps(row) for row in rows)


@pytest.mark.parametrize(
    ("capture", "reproof", "capture_predicate", "expected_plan"),
    (
        (_BUILDER_ERROR_ABSENT, _BUILDER_ERROR_ABSENT, "ABSENT", "PASS"),
        ("raw-capture-error", "raw-reproof-error", "PRESENT", "PASS"),
        (None, None, "INVALID", "PASS"),
        (_BUILDER_ERROR_ABSENT, "raw-reproof-error", "ABSENT", "PLAN_DRIFT"),
        (_BUILDER_ERROR_ABSENT, None, "ABSENT", "PLAN_DRIFT"),
        ("raw-capture-error", _BUILDER_ERROR_ABSENT, "PRESENT", "PLAN_DRIFT"),
        ("raw-capture-error", None, "PRESENT", "PLAN_DRIFT"),
        (None, _BUILDER_ERROR_ABSENT, "INVALID", "PLAN_DRIFT"),
        (None, "raw-reproof-error", "INVALID", "PLAN_DRIFT"),
    ),
)
def test_prestate_diagnostic_fails_closed_on_every_builder_error_transition(
    capture: object,
    reproof: object,
    capture_predicate: str,
    expected_plan: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _BuilderErrorTransitionExecutor(capture, reproof)

    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    expected_classification = "PASS" if expected_plan == "PASS" else "REJECTED"
    assert evidence.classification.value == expected_classification
    assert evidence.prestate_checkpoint.value == "REPROOF"
    assert evidence.prestate_predicate.value == expected_plan
    assert _diagnostic_observation(evidence).builder_error.value == capture_predicate
    assert executor.selection_calls == []
    line = operator.format_builder_selection_prestate_diagnostic(evidence)
    assert "raw-capture" not in line
    assert "raw-reproof" not in line


def test_builder_error_drift_survives_lock_exit_as_capture_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(
        operator,
        monkeypatch,
        lock_exit_failure=KeyboardInterrupt("raw-lock-exit-sentinel"),
    )
    executor = _BuilderErrorTransitionExecutor("raw-capture-error", _BUILDER_ERROR_ABSENT)

    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.prestate_checkpoint is operator.BuilderSelectionPrestateCheckpoint.REPROOF
    assert evidence.prestate_predicate is operator.DockerBuilderSelectionPlanPredicate.PLAN_DRIFT
    assert _diagnostic_observation(evidence).builder_error is operator.BuilderErrorPredicate.PRESENT
    assert executor.selection_calls == []
    line = operator.format_builder_selection_prestate_diagnostic(evidence)
    assert "raw-" not in line
    assert "Traceback" not in line


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("buildx_authority", "UPSTREAM_OTHER"),
        ("buildx_distribution", "OTHER_MODULE"),
        ("builder_selection", "NODE_NOT_RUNNING"),
        ("node_schema", "NODE_NOT_MAPPING"),
        ("prior_driver", "REMOTE"),
        ("builder_error", "PRESENT"),
        ("prior_target_relation", "SAME"),
        ("prior_status", "STOPPED"),
        ("prior_node_error", "PRESENT"),
        ("target_contract", "STATUS"),
        ("first_defect", "PLAN_DRIFT"),
    ),
)
def test_every_snapshot_field_drift_maps_to_existing_plan_drift(
    field: str,
    changed: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    original = operator.evaluate_docker_builder_selection_plan
    evaluations = 0

    def evaluate(*args: object, **kwargs: object) -> Any:
        nonlocal evaluations
        evaluations += 1
        result = original(*args, **kwargs)
        if evaluations == 2:
            enum_type = type(getattr(result.snapshot, field))
            changed_snapshot = cast(Any, replace)(
                result.snapshot,
                **{field: enum_type[changed]},
            )
            return replace(result, snapshot=changed_snapshot)
        return result

    monkeypatch.setattr(operator, "evaluate_docker_builder_selection_plan", evaluate)
    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(), executor=_Executor(), environ={}
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.PRESTATE
    assert evidence.prestate_checkpoint is operator.BuilderSelectionPrestateCheckpoint.REPROOF
    assert evidence.prestate_predicate is operator.DockerBuilderSelectionPlanPredicate.PLAN_DRIFT
    assert evidence.observation_known is True
    assert _diagnostic_observation(evidence).first_defect is (
        operator.DockerBuilderSelectionPlanPredicate.PASS
    )


def test_normal_operator_builder_error_drift_stops_before_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _BuilderErrorTransitionExecutor("raw-capture-error", _BUILDER_ERROR_ABSENT)

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.PRESTATE
    assert evidence.prestate_checkpoint is operator.BuilderSelectionPrestateCheckpoint.REPROOF
    assert evidence.prestate_predicate is operator.DockerBuilderSelectionPlanPredicate.PLAN_DRIFT
    assert evidence.action_attempted is False
    assert executor.selection_calls == []
    assert "raw-" not in operator.format_builder_selection_reconcile_evidence(evidence)


@pytest.mark.parametrize(
    ("version_output", "expected"),
    (
        ("github.com/docker/buildx v0.35.0 " + "a" * 40 + "\n", "UPSTREAM_V0_35_0"),
        ("github.com/docker/buildx v0.34.1 " + "b" * 40 + "\n", "UPSTREAM_OTHER"),
        (
            "github.com/docker/buildx v0.35.0-desktop.1 " + "c" * 40 + "\n",
            "OTHER_DISTRIBUTION",
        ),
        ("raw-malformed-version-sentinel", "OUTPUT_INVALID"),
        ("github.com/docker/buildx v0.35.0 " + "d" * 40 + "\nraw-extra\n", "OUTPUT_INVALID"),
        ("x" * 257, "OUTPUT_INVALID"),
    ),
)
def test_prestate_diagnostic_classifies_one_bounded_buildx_version_query(
    version_output: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(version_output=version_output)
    executor.selected = "desktop-linux"

    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert _diagnostic_observation(evidence).buildx_authority.value == expected
    assert executor.calls.count(("docker", "buildx", "version")) == 1
    assert executor.selection_calls == []
    line = operator.format_builder_selection_prestate_diagnostic(evidence)
    assert "raw-" not in line
    assert "github.com" not in line


@pytest.mark.parametrize(
    "failure",
    (
        RuntimeError("raw-version-nonzero-sentinel"),
        subprocess.TimeoutExpired(("docker", "buildx", "version"), 1),
        KeyboardInterrupt("raw-version-interrupt-sentinel"),
    ),
)
def test_prestate_diagnostic_version_failure_is_unknown_and_stops_before_listing(
    failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor(version_error=failure)

    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.observation_known is False
    assert evidence.observation is None
    assert evidence.prestate_known is False
    assert executor.calls == [("docker", "buildx", "version")]
    line = operator.format_builder_selection_prestate_diagnostic(evidence)
    assert "raw-version" not in line
    assert "Traceback" not in line


def test_normal_operator_prestate_failure_retains_exact_capture_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor()
    executor.selected = "desktop-linux"

    evidence = operator._run_operator(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.PRESTATE
    assert evidence.prestate_known is True
    assert evidence.prestate_checkpoint is operator.BuilderSelectionPrestateCheckpoint.CAPTURE
    assert evidence.prestate_predicate is (
        operator.DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL
    )
    assert evidence.builder_selection_predicate is operator.BuilderSelectionPredicate.PASS
    assert evidence.node_schema_predicate is operator.NodeSchemaPredicate.PASS
    assert evidence.prior_driver_known is False
    assert evidence.prior_driver_predicate is None
    assert evidence.action_attempted is False
    assert executor.selection_calls == []


@pytest.mark.parametrize(
    "exit_failure",
    (
        RuntimeError("raw-lock-exit-sentinel"),
        KeyboardInterrupt("raw-lock-interrupt-sentinel"),
        BaseException("raw-lock-base-sentinel"),
    ),
)
def test_prestate_diagnostic_lock_exit_is_unknown_and_retains_observed_pass(
    exit_failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch, lock_exit_failure=exit_failure)
    executor = _Executor()

    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.prestate_known is True
    assert evidence.prestate_checkpoint is operator.BuilderSelectionPrestateCheckpoint.REPROOF
    assert evidence.prestate_predicate is operator.DockerBuilderSelectionPlanPredicate.PASS
    observation = _diagnostic_observation(evidence)
    assert observation.prior_driver is operator.PriorDriverPredicate.PASS
    assert observation.builder_error is operator.BuilderErrorPredicate.ABSENT
    assert observation.buildx_authority is operator.BuildxAuthorityPredicate.UPSTREAM_V0_35_0
    assert executor.selection_calls == []
    line = operator.format_builder_selection_prestate_diagnostic(evidence)
    assert "raw-lock" not in line
    assert "Traceback" not in line


@pytest.mark.parametrize("failure", (KeyboardInterrupt(), SystemExit(), BaseException()))
def test_read_only_prestate_diagnostic_interrupt_is_unknown_and_value_free(
    failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    source_calls = 0

    def source(_executor: object) -> str:
        nonlocal source_calls
        source_calls += 1
        if source_calls == 2:
            raise failure
        return "a" * 40

    monkeypatch.setattr(operator, "_source_identity", source)
    executor = _Executor()

    evidence = operator._run_prestate_diagnostic(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.BuilderSelectionReconcilePredicate.UNKNOWN
    assert evidence.prestate_known is True
    assert evidence.observation_known is True
    assert _diagnostic_observation(evidence).prior_driver is operator.PriorDriverPredicate.PASS
    assert evidence.action_count == 0
    assert evidence.selection_mutation_count == 0
    assert executor.selection_calls == []
    assert "raw-" not in operator.format_builder_selection_prestate_diagnostic(evidence)


def test_fixed_prestate_diagnostic_argv_outputs_one_bounded_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    observation = operator.BuilderPrestateSnapshot(
        buildx_authority=operator.BuildxAuthorityPredicate.UPSTREAM_V0_35_0,
        buildx_distribution=operator.BuildxDistributionPredicate.NOT_APPLICABLE,
        builder_selection=operator.BuilderSelectionPredicate.DRIVER_NOT_DOCKER,
        node_schema=operator.NodeSchemaPredicate.PASS,
        prior_driver=operator.PriorDriverPredicate.PASS,
        builder_error=operator.BuilderErrorPredicate.ABSENT,
        prior_target_relation=operator.PriorTargetRelationPredicate.DISTINCT,
        prior_status=operator.PriorStatusPredicate.RUNNING,
        prior_node_error=operator.BuilderErrorPredicate.ABSENT,
        target_contract=operator.TargetContractPredicate.PASS,
        first_defect=operator.DockerBuilderSelectionPlanPredicate.PASS,
    )
    fixed = operator.BuilderSelectionPrestateDiagnosticEvidence(
        classification=operator.BuilderSelectionReconcileClassification.PASS,
        predicate=operator.BuilderSelectionReconcilePredicate.PASS,
        prestate_known=True,
        prestate_checkpoint=operator.BuilderSelectionPrestateCheckpoint.REPROOF,
        prestate_predicate=operator.DockerBuilderSelectionPlanPredicate.PASS,
        observation_known=True,
        observation=observation,
    )
    calls: list[str] = []

    def run_diagnostic(_runtime: object) -> Any:
        calls.append("diagnostic")
        return fixed

    monkeypatch.setattr(
        operator,
        "_run_prestate_diagnostic",
        run_diagnostic,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(OPERATOR), "--diagnostic-phase", "BUILDER_SELECTION_PRESTATE"],
    )

    assert operator.main() == 0

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert captured.err == ""
    assert calls == ["diagnostic"]
    assert document["phase"] == "BUILDER_SELECTION_PRESTATE"
    assert document["prestate_checkpoint"] == "REPROOF"
    assert document["prestate_predicate"] == "PASS"
    assert document["schema"] == "BUILDER_PRESTATE_V2"
    assert document["observation_known"] is True
    assert document["observation"]["prior_driver"] == "PASS"
    assert document["observation"]["builder_error"] == "ABSENT"
    assert document["observation"]["buildx_authority"] == "UPSTREAM_V0_35_0"
    assert document["mutation_count"] == 0
    assert document["retry_count"] == 0


def test_malformed_prestate_diagnostic_arguments_stop_before_lock_without_raw(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    entered: list[str] = []
    monkeypatch.setattr(
        operator,
        "exclusive_docker_workflow_lock",
        lambda _root: entered.append("lock"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(OPERATOR),
            "--diagnostic-phase",
            "BUILDER_SELECTION_PRESTATE",
            "raw-argument-sentinel",
        ],
    )

    assert operator.main() == 2

    output = capsys.readouterr()
    assert entered == []
    assert output.err == ""
    assert "raw-argument-sentinel" not in output.out
    assert json.loads(output.out)["predicate"] == "ARGUMENTS"


@pytest.mark.parametrize(
    "case",
    (
        "partial-known",
        "unknown-enum",
        "pass-with-capture",
        "rejected-with-pass",
        "nested-contradiction",
        "observation-partial",
        "observation-without-prestate",
        "observation-mismatch",
        "observation-internally-inconsistent",
        "authority-distribution-pairs",
        "selection-prior-contradiction",
        "relation-target-contradiction",
        "target-first-defect-contradiction",
        "pass-with-invalid-authority",
        "nonzero-action",
    ),
)
def test_prestate_diagnostic_evidence_rejects_contradictory_shapes(case: str) -> None:
    operator = _load_operator()
    observation = operator.BuilderPrestateSnapshot(
        buildx_authority=operator.BuildxAuthorityPredicate.UPSTREAM_V0_35_0,
        buildx_distribution=operator.BuildxDistributionPredicate.NOT_APPLICABLE,
        builder_selection=operator.BuilderSelectionPredicate.PASS,
        node_schema=operator.NodeSchemaPredicate.PASS,
        prior_driver=operator.PriorDriverPredicate.UNRECOGNIZED,
        builder_error=operator.BuilderErrorPredicate.ABSENT,
        prior_target_relation=operator.PriorTargetRelationPredicate.SAME,
        prior_status=operator.PriorStatusPredicate.RUNNING,
        prior_node_error=operator.BuilderErrorPredicate.ABSENT,
        target_contract=operator.TargetContractPredicate.PASS,
        first_defect=(operator.DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL),
    )
    values: dict[str, Any] = {
        "classification": operator.BuilderSelectionReconcileClassification.REJECTED,
        "predicate": operator.BuilderSelectionReconcilePredicate.PRESTATE,
        "prestate_known": True,
        "prestate_checkpoint": operator.BuilderSelectionPrestateCheckpoint.CAPTURE,
        "prestate_predicate": (
            operator.DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL
        ),
        "observation_known": True,
        "observation": observation,
    }
    if case == "partial-known":
        values["prestate_predicate"] = None
    elif case == "unknown-enum":
        values["prestate_predicate"] = operator.DockerBuilderSelectionPlanPredicate.UNKNOWN
    elif case == "pass-with-capture":
        values["classification"] = operator.BuilderSelectionReconcileClassification.PASS
        values["predicate"] = operator.BuilderSelectionReconcilePredicate.PASS
        values["prestate_predicate"] = operator.DockerBuilderSelectionPlanPredicate.PASS
    elif case == "rejected-with-pass":
        values["prestate_predicate"] = operator.DockerBuilderSelectionPlanPredicate.PASS
    elif case == "nested-contradiction":
        values["predicate"] = operator.BuilderSelectionReconcilePredicate.UNKNOWN
    elif case == "observation-partial":
        values["observation"] = None
    elif case == "observation-without-prestate":
        values["prestate_known"] = False
        values["prestate_checkpoint"] = None
        values["prestate_predicate"] = None
    elif case == "observation-mismatch":
        values["observation"] = replace(
            observation,
            first_defect=operator.DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER,
        )
    elif case == "observation-internally-inconsistent":
        values["observation"] = replace(
            observation,
            buildx_distribution=(operator.BuildxDistributionPredicate.DOCUMENTED_DESKTOP_SUFFIX),
        )
    elif case == "authority-distribution-pairs":
        allowed = {
            operator.BuildxAuthorityPredicate.UPSTREAM_V0_35_0: {
                operator.BuildxDistributionPredicate.NOT_APPLICABLE
            },
            operator.BuildxAuthorityPredicate.UPSTREAM_OTHER: {
                operator.BuildxDistributionPredicate.NOT_APPLICABLE
            },
            operator.BuildxAuthorityPredicate.OTHER_DISTRIBUTION: {
                operator.BuildxDistributionPredicate.DOCUMENTED_DESKTOP_SUFFIX,
                operator.BuildxDistributionPredicate.UPSTREAM_MODULE_NONRELEASE,
                operator.BuildxDistributionPredicate.OTHER_MODULE,
            },
            operator.BuildxAuthorityPredicate.OUTPUT_INVALID: {
                operator.BuildxDistributionPredicate.NOT_APPLICABLE
            },
        }
        for authority in operator.BuildxAuthorityPredicate:
            for distribution in operator.BuildxDistributionPredicate:
                if distribution in allowed.get(authority, set()):
                    continue
                with pytest.raises(
                    ValueError,
                    match="DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID",
                ):
                    operator.BuilderSelectionPrestateDiagnosticEvidence(
                        **{
                            **values,
                            "observation": replace(
                                observation,
                                buildx_authority=authority,
                                buildx_distribution=distribution,
                            ),
                        }
                    )
        return
    elif case == "selection-prior-contradiction":
        values["observation"] = replace(
            observation,
            prior_driver=operator.PriorDriverPredicate.PASS,
        )
    elif case == "relation-target-contradiction":
        values["observation"] = replace(
            observation,
            prior_target_relation=operator.PriorTargetRelationPredicate.TARGET_MISSING,
        )
    elif case == "target-first-defect-contradiction":
        values["prestate_predicate"] = operator.DockerBuilderSelectionPlanPredicate.TARGET_STATUS
        values["observation"] = replace(
            observation,
            builder_selection=operator.BuilderSelectionPredicate.DRIVER_NOT_DOCKER,
            prior_driver=operator.PriorDriverPredicate.PASS,
            prior_target_relation=operator.PriorTargetRelationPredicate.DISTINCT,
            first_defect=operator.DockerBuilderSelectionPlanPredicate.TARGET_STATUS,
        )
    elif case == "pass-with-invalid-authority":
        values.update(
            classification=operator.BuilderSelectionReconcileClassification.PASS,
            predicate=operator.BuilderSelectionReconcilePredicate.PASS,
            prestate_checkpoint=operator.BuilderSelectionPrestateCheckpoint.REPROOF,
            prestate_predicate=operator.DockerBuilderSelectionPlanPredicate.PASS,
            observation=replace(
                observation,
                buildx_authority=operator.BuildxAuthorityPredicate.OUTPUT_INVALID,
                builder_selection=operator.BuilderSelectionPredicate.DRIVER_NOT_DOCKER,
                prior_driver=operator.PriorDriverPredicate.PASS,
                first_defect=operator.DockerBuilderSelectionPlanPredicate.PASS,
            ),
        )
    else:
        values["action_count"] = 1

    with pytest.raises(
        ValueError,
        match="DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID",
    ):
        operator.BuilderSelectionPrestateDiagnosticEvidence(**values)


def test_source_identity_requires_clean_dev_and_exact_commit() -> None:
    operator = _load_operator()

    class SourceExecutor:
        def __init__(self, values: list[str]) -> None:
            self.values = values

        def output(self, *_args: object, **_kwargs: object) -> str:
            return self.values.pop(0)

    assert operator._source_identity(SourceExecutor(["", "a" * 40, "dev\n"])) == "a" * 40
    for values in (
        ["dirty", "a" * 40, "dev"],
        ["", "short", "dev"],
        ["", "a" * 40, "main"],
    ):
        with pytest.raises(RuntimeError) as captured:
            operator._source_identity(SourceExecutor(values))
        assert str(captured.value) == "SOURCE"


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
    ),
)
def test_mac_state_environment_drift_is_fixed_and_value_free(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operator = _load_operator()
    state = SimpleNamespace(
        profile="other" if drift == "profile" else "mac-development",
        deployment_mode="offline" if drift == "deployment" else "build",
        env_file="raw-path-sentinel" if drift == "environment-path" else ".env.mac-development",
        environment_key_hashes={"SAFE": "wrong" if drift == "environment-hash" else "digest"},
        local_gateway=drift == "gateway",
        local_graph=drift == "graph",
        applied_commit="a" * 40,
        runtime_commit=("b" if drift == "commit" else "a") * 40,
    )
    monkeypatch.setattr(operator, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(operator, "read_env_values", lambda _path: {"SAFE": "opaque"})
    monkeypatch.setattr(operator, "environment_key_hashes", lambda _values: {"SAFE": "digest"})

    with pytest.raises(RuntimeError) as captured:
        operator._host_identity(tmp_path)

    assert str(captured.value) == "HOST_ENVIRONMENT"
    assert "raw-" not in str(captured.value)


def test_bounded_process_output_overflow_terminates_and_reaps_without_raw_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = cast(Any, original_popen)(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(operator.subprocess, "Popen", popen)
    monkeypatch.setattr(operator, "_MAXIMUM_PROCESS_OUTPUT_BYTES", 64)
    executor = operator._BoundedProcessExecutor()

    with pytest.raises(RuntimeError, match="DOCKER_BUILDER_SELECTION_PROCESS_FAILED"):
        executor.output(
            (
                sys.executable,
                "-c",
                "import os,time;os.write(1,b'raw-secret-sentinel'+b'x'*1024);time.sleep(5)",
            ),
            classification="FIXED",
            timeout_seconds=2,
        )

    assert len(processes) == 1
    assert processes[0].poll() is not None
    exposed = capsys.readouterr().out + capsys.readouterr().err
    assert "raw-secret-sentinel" not in exposed


def test_legacy_output_stops_reading_and_begins_cleanup_at_first_overflow(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    chunks = [b"raw-first-overflow", b"raw-later-payload", b""]
    events: list[str] = []
    requested_sizes: list[int] = []

    class Output:
        def fileno(self) -> int:
            return 99

        def close(self) -> None:
            events.append("stdout-close")

    class Process:
        stdout = Output()
        terminated = False
        reaped = False

        def poll(self) -> int | None:
            events.append("poll")
            if not self.reaped:
                return None
            return 143 if self.terminated else 0

        def terminate(self) -> None:
            events.append("terminate")
            self.terminated = True

        def kill(self) -> None:
            raise AssertionError("reaped process must not be killed")

        def wait(self, *, timeout: float) -> int:
            del timeout
            events.append("cleanup-wait" if self.terminated else "natural-wait")
            self.reaped = True
            return 143 if self.terminated else 0

    class Selector:
        def register(self, *_args: object) -> None:
            return None

        def select(self, _timeout: float) -> list[object]:
            events.append("select")
            return [object()]

        def close(self) -> None:
            events.append("selector-close")

    def read(_fd: int, requested_size: int) -> bytes:
        events.append("read")
        requested_sizes.append(requested_size)
        return chunks.pop(0)

    monkeypatch.setattr(operator.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(operator.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(operator.os, "read", read)
    monkeypatch.setattr(operator, "_MAXIMUM_PROCESS_OUTPUT_BYTES", 8)

    with pytest.raises(
        operator._ProcessEvidenceInvalid,
        match="DOCKER_BUILDER_SELECTION_PROCESS_FAILED",
    ):
        operator._BoundedProcessExecutor().output(
            ("fixed",),
            classification="FIXED",
            timeout_seconds=1,
        )

    assert events.count("read") == 1
    assert requested_sizes == [9]
    assert "natural-wait" not in events
    assert events.index("read") < events.index("selector-close")
    assert events.index("selector-close") < events.index("terminate")
    assert events.index("terminate") < events.index("cleanup-wait")
    assert chunks == [b"raw-later-payload", b""]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_diagnostic_outcome_uses_discard_reads_only_after_first_bounded_breach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    chunks = [b"x" * 9, b"raw-discarded-payload", b""]
    requested_sizes: list[int] = []

    class Output:
        def fileno(self) -> int:
            return 99

        def close(self) -> None:
            return None

    class Process:
        stdout = Output()

        def wait(self, *, timeout: float) -> int:
            del timeout
            return 0

        def poll(self) -> int:
            return 0

    class Selector:
        def register(self, *_args: object) -> None:
            return None

        def select(self, _timeout: float) -> list[object]:
            return [object()]

        def close(self) -> None:
            return None

    def read(_fd: int, requested_size: int) -> bytes:
        requested_sizes.append(requested_size)
        return chunks.pop(0)

    monkeypatch.setattr(operator.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(operator.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(operator.os, "read", read)
    monkeypatch.setattr(operator, "_MAXIMUM_PROCESS_OUTPUT_BYTES", 8)

    outcome = operator._BoundedProcessExecutor().bounded_outcome(
        ("fixed",),
        classification="FIXED",
        timeout_seconds=1,
    )

    assert outcome.kind is operator._BoundedProcessOutcomeKind.OUTPUT_INVALID
    assert requested_sizes == [9, 64 * 1024, 64 * 1024]


def test_bounded_process_timeout_kills_terminate_ignoring_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = cast(Any, original_popen)(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(operator.subprocess, "Popen", popen)
    monkeypatch.setattr(operator, "_PROCESS_REAP_SECONDS", 0.05)
    executor = operator._BoundedProcessExecutor()

    with pytest.raises(RuntimeError, match="DOCKER_BUILDER_SELECTION_PROCESS_FAILED"):
        executor.output(
            (
                sys.executable,
                "-c",
                "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(5)",
            ),
            classification="FIXED",
            timeout_seconds=0.05,
        )

    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_bounded_process_unreaped_failure_is_distinct_and_never_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []

    class Output:
        def fileno(self) -> int:
            return 99

        def close(self) -> None:
            events.append("stdout-close")

    class Process:
        stdout = Output()

        def poll(self) -> None:
            events.append("poll")
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")

        def wait(self, *, timeout: float) -> None:
            del timeout
            events.append("wait")
            raise subprocess.TimeoutExpired("fixed", 1)

    class Selector:
        def register(self, *_args: object) -> None:
            return None

        def select(self, _timeout: float) -> list[object]:
            return []

        def close(self) -> None:
            events.append("selector-close")

    monkeypatch.setattr(operator.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(operator.selectors, "DefaultSelector", Selector)

    with pytest.raises(
        operator._ProcessUnreaped, match="DOCKER_BUILDER_SELECTION_PROCESS_UNREAPED"
    ):
        operator._BoundedProcessExecutor().output(
            ("fixed",),
            classification="FIXED",
            timeout_seconds=1,
        )

    assert events.count("wait") == 2
    assert "terminate" in events
    assert "kill" in events
    assert events[-1] == "stdout-close"
    exposed = capsys.readouterr().out + capsys.readouterr().err
    assert "raw-" not in exposed


@pytest.mark.parametrize(
    ("failure_step", "cleanup_error"),
    (
        ("selector", OSError("raw-selector-close-sentinel")),
        ("selector", KeyboardInterrupt("raw-selector-interrupt-sentinel")),
        ("terminate", KeyboardInterrupt("raw-terminate-interrupt-sentinel")),
        ("terminate", SystemExit("raw-terminate-exit-sentinel")),
        ("terminate", BaseException("raw-terminate-base-sentinel")),
        ("wait-1", KeyboardInterrupt("raw-wait-one-interrupt-sentinel")),
        ("wait-1", SystemExit("raw-wait-one-exit-sentinel")),
        ("wait-1", BaseException("raw-wait-one-base-sentinel")),
        ("kill", KeyboardInterrupt("raw-kill-interrupt-sentinel")),
        ("kill", SystemExit("raw-kill-exit-sentinel")),
        ("kill", BaseException("raw-kill-base-sentinel")),
        ("wait-2", KeyboardInterrupt("raw-wait-two-interrupt-sentinel")),
        ("wait-2", SystemExit("raw-wait-two-exit-sentinel")),
        ("wait-2", BaseException("raw-wait-two-base-sentinel")),
        ("final-poll", KeyboardInterrupt("raw-final-poll-interrupt-sentinel")),
        ("final-poll", SystemExit("raw-final-poll-exit-sentinel")),
        ("final-poll", BaseException("raw-final-poll-base-sentinel")),
        ("stdout", OSError("raw-stdout-close-sentinel")),
        ("stdout", KeyboardInterrupt("raw-stdout-interrupt-sentinel")),
    ),
)
def test_cleanup_defects_never_mask_an_unreaped_process(
    failure_step: str,
    cleanup_error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []

    class Output:
        def fileno(self) -> int:
            return 99

        def close(self) -> None:
            events.append("stdout")
            if failure_step == "stdout":
                raise cleanup_error

    class Process:
        stdout = Output()
        wait_count = 0
        poll_count = 0

        def poll(self) -> None:
            self.poll_count += 1
            events.append("poll")
            if failure_step == "final-poll" and self.poll_count == 2:
                raise cleanup_error
            return None

        def terminate(self) -> None:
            events.append("terminate")
            if failure_step == "terminate":
                raise cleanup_error

        def kill(self) -> None:
            events.append("kill")
            if failure_step == "kill":
                raise cleanup_error

        def wait(self, *, timeout: float) -> None:
            del timeout
            self.wait_count += 1
            events.append(f"wait-{self.wait_count}")
            if failure_step == f"wait-{self.wait_count}":
                raise cleanup_error
            raise subprocess.TimeoutExpired("fixed", 1)

    class Selector:
        def register(self, *_args: object) -> None:
            return None

        def select(self, _timeout: float) -> list[object]:
            return []

        def close(self) -> None:
            events.append("selector")
            if failure_step == "selector":
                raise cleanup_error

    monkeypatch.setattr(operator.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(operator.selectors, "DefaultSelector", Selector)

    with pytest.raises(operator._ProcessUnreaped):
        operator._BoundedProcessExecutor().output(
            ("fixed",),
            classification="FIXED",
            timeout_seconds=1,
        )

    assert events.count("poll") >= 2
    assert events.index("selector") < events.index("terminate")
    assert events.index("terminate") < events.index("wait-1")
    assert events.index("wait-1") < events.index("kill")
    assert events.index("kill") < events.index("wait-2")
    assert events.index("wait-2") < events.index("stdout")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    "close_error",
    (
        OSError("raw-reaped-selector-close-sentinel"),
        KeyboardInterrupt("raw-reaped-selector-interrupt-sentinel"),
    ),
)
def test_reaped_process_close_only_defect_is_fixed_failure_not_unreaped(
    close_error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    events: list[str] = []

    class Output:
        def fileno(self) -> int:
            return 99

        def close(self) -> None:
            events.append("stdout")

    class Process:
        stdout = Output()

        def poll(self) -> int:
            events.append("poll")
            return 7

    class Selector:
        def register(self, *_args: object) -> None:
            return None

        def select(self, _timeout: float) -> list[object]:
            return []

        def close(self) -> None:
            events.append("selector")
            raise close_error

    monkeypatch.setattr(operator.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(operator.selectors, "DefaultSelector", Selector)

    with pytest.raises(RuntimeError, match="DOCKER_BUILDER_SELECTION_PROCESS_FAILED") as captured:
        operator._BoundedProcessExecutor().output(
            ("fixed",),
            classification="FIXED",
            timeout_seconds=1,
        )

    assert not isinstance(captured.value, operator._ProcessUnreaped)
    assert events == ["selector", "poll", "poll", "stdout"]
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_bounded_process_spawn_nonzero_and_invalid_utf8_never_emit_raw(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    executor = operator._BoundedProcessExecutor()

    for command in (
        (sys.executable, "-c", "import sys;print('raw-nonzero-sentinel');sys.exit(7)"),
        (sys.executable, "-c", "import os;os.write(1,b'\\xffraw-decode-sentinel')"),
    ):
        with pytest.raises(RuntimeError, match="DOCKER_BUILDER_SELECTION_PROCESS_FAILED"):
            executor.output(command, classification="FIXED", timeout_seconds=2)

    def spawn_failure(*_args: object, **_kwargs: object) -> object:
        raise OSError("raw-spawn-sentinel")

    monkeypatch.setattr(operator.subprocess, "Popen", spawn_failure)
    with pytest.raises(RuntimeError, match="DOCKER_BUILDER_SELECTION_PROCESS_FAILED"):
        executor.output(("fixed",), classification="FIXED", timeout_seconds=2)
    exposed = capsys.readouterr().out + capsys.readouterr().err
    assert "raw-" not in exposed


def test_context_default_preflight_requires_exact_phenotype_before_daemon_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _Executor()

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.ContextDefaultBuilderPreflightPredicate.PRESTATE_DRIFT
    assert evidence.phenotype_known is False
    assert evidence.buildx_version_query_count == 1
    assert evidence.builder_inventory_query_count == 1
    assert evidence.daemon_probe_count == 0
    assert ("docker", "version", "--format", "{{.Server.Version}}") not in executor.calls
    assert executor.selection_calls == []


def test_context_default_preflight_classifies_stable_unresolved_builder_value_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(
        operator,
        daemon_output="raw-version-sentinel\n",
    )

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )
    line = operator.format_context_default_builder_preflight(evidence)
    document = json.loads(line)

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is (
        operator.ContextDefaultBuilderPreflightPredicate.BUILDX_DEFAULT_UNRESOLVED
    )
    assert evidence.phenotype_known is True
    assert evidence.buildx_version_query_count == 1
    assert evidence.builder_inventory_query_count == 2
    assert evidence.daemon_probe_count == 1
    assert executor.calls.count(("docker", "version", "--format", "{{.Server.Version}}")) == 1
    assert set(document) == {
        "action_count",
        "builder_inventory_query_count",
        "build_count",
        "buildx_version_query_count",
        "cache_action_count",
        "classification",
        "container_action_count",
        "daemon_probe_count",
        "mutation_count",
        "phase",
        "phenotype_known",
        "predicate",
        "retry_count",
        "rollback_count",
        "schema",
        "selection_mutation_count",
    }
    assert document["schema"] == "CONTEXT_DEFAULT_BUILDER_PREFLIGHT_V1"
    assert document["phase"] == "CONTEXT_DEFAULT_BUILDER_PREFLIGHT"
    assert all(
        document[name] == 0
        for name in (
            "action_count",
            "rollback_count",
            "selection_mutation_count",
            "cache_action_count",
            "build_count",
            "container_action_count",
            "mutation_count",
            "retry_count",
        )
    )
    assert "raw-" not in line
    assert "28.5.1" not in line
    assert executor.selection_calls == []


@pytest.mark.parametrize(
    "outcome_kind",
    ("REAPED_NONZERO", "REAPED_TIMEOUT"),
)
def test_context_default_preflight_classifies_reaped_daemon_failure_and_reproves(
    outcome_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(operator, outcome_kind=outcome_kind)

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is (
        operator.ContextDefaultBuilderPreflightPredicate.DAEMON_API_UNAVAILABLE
    )
    assert evidence.phenotype_known is True
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 2
    assert executor.selection_calls == []
    assert "raw-" not in operator.format_context_default_builder_preflight(evidence)


@pytest.mark.parametrize(
    "output",
    (
        "",
        "\n",
        "   \n",
        "\t\n",
        "\x00\n",
        " leading\n",
        "trailing \n",
        "embedded\tcontrol\n",
        "one\ntwo\n",
        "x" * 257 + "\n",
    ),
)
def test_context_default_preflight_rejects_invalid_daemon_evidence(
    output: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(operator, daemon_output=output)

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is (
        operator.ContextDefaultBuilderPreflightPredicate.DAEMON_EVIDENCE_INVALID
    )
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 2
    assert executor.selection_calls == []


@pytest.mark.parametrize(
    "error",
    (
        OSError("raw-spawn-sentinel"),
        subprocess.SubprocessError("raw-process-boundary-sentinel"),
    ),
)
def test_context_default_preflight_process_boundary_failure_is_unknown_without_reproof(
    error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(operator, daemon_error=error)

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.ContextDefaultBuilderPreflightPredicate.UNKNOWN
    assert evidence.phenotype_known is True
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 1
    assert executor.calls.count(("docker", "buildx", "ls", "--format", "{{json .}}")) == 1
    assert executor.selection_calls == []
    assert "raw-" not in operator.format_context_default_builder_preflight(evidence)


def test_context_default_preflight_typed_internal_failure_is_unknown_without_reproof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(operator, outcome_kind="INTERNAL_FAILURE")

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.ContextDefaultBuilderPreflightPredicate.UNKNOWN
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 1


def test_context_default_preflight_trustworthy_output_failure_is_invalid_and_reproved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(operator, outcome_kind="OUTPUT_INVALID")

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is (
        operator.ContextDefaultBuilderPreflightPredicate.DAEMON_EVIDENCE_INVALID
    )
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 2


@pytest.mark.parametrize(
    ("return_code", "payload", "cleanup_step", "expected_kind"),
    (
        (7, b"raw-oversized-sentinel", None, "REAPED_NONZERO"),
        (7, b"   \n", None, "REAPED_NONZERO"),
        (0, b"raw-oversized-sentinel", None, "OUTPUT_INVALID"),
        (7, b"\xffraw-invalid-utf8", None, "REAPED_NONZERO"),
        (0, b"\xffraw-invalid-utf8", None, "OUTPUT_INVALID"),
        (7, b"raw-oversized-sentinel", "selector", "INTERNAL_FAILURE"),
        (0, b"raw-oversized-sentinel", "selector", "INTERNAL_FAILURE"),
        (7, b"raw-oversized-sentinel", "stdout", "INTERNAL_FAILURE"),
    ),
)
def test_bounded_process_outcome_preserves_exit_output_and_cleanup_precedence(
    return_code: int,
    payload: bytes,
    cleanup_step: str | None,
    expected_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    chunks = [payload, b""]
    events: list[str] = []

    class Output:
        def fileno(self) -> int:
            return 99

        def close(self) -> None:
            events.append("stdout-close")
            if cleanup_step == "stdout":
                raise OSError("raw-stdout-close-sentinel")

    class Process:
        stdout = Output()

        def wait(self, *, timeout: float) -> int:
            del timeout
            events.append("wait")
            return return_code

        def poll(self) -> int:
            events.append("poll")
            return return_code

    class Selector:
        def register(self, *_args: object) -> None:
            return None

        def select(self, _timeout: float) -> list[object]:
            return [object()]

        def close(self) -> None:
            events.append("selector-close")
            if cleanup_step == "selector":
                raise KeyboardInterrupt("raw-selector-close-sentinel")

    def read(_fd: int, _size: int) -> bytes:
        events.append("read")
        return chunks.pop(0)

    monkeypatch.setattr(operator.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(operator.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(operator.os, "read", read)
    monkeypatch.setattr(operator, "_MAXIMUM_PROCESS_OUTPUT_BYTES", 8)

    outcome = operator._BoundedProcessExecutor().bounded_outcome(
        ("fixed",),
        classification="FIXED",
        timeout_seconds=1,
    )

    assert outcome.kind.value == expected_kind
    assert outcome.output is None
    assert events.count("read") == 2
    assert events.index("wait") < events.index("selector-close")
    assert events.index("selector-close") < events.index("poll")
    assert events.index("poll") < events.index("stdout-close")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    ("failure_step", "expected_kind"),
    (
        ("spawn", "INTERNAL_FAILURE"),
        ("register", "INTERNAL_FAILURE"),
        ("select", "INTERNAL_FAILURE"),
        ("read", "INTERNAL_FAILURE"),
        ("wait", "INTERNAL_FAILURE"),
        ("timeout", "REAPED_TIMEOUT"),
        ("timeout-cleanup", "INTERNAL_FAILURE"),
    ),
)
def test_bounded_process_outcome_distinguishes_timeout_from_internal_boundary_failure(
    failure_step: str,
    expected_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    events: list[str] = []

    class Output:
        def fileno(self) -> int:
            return 99

        def close(self) -> None:
            events.append("stdout-close")

    class Process:
        stdout = Output()
        reaped = False

        def poll(self) -> int | None:
            events.append("poll")
            return 143 if self.reaped else None

        def terminate(self) -> None:
            events.append("terminate")
            if failure_step == "timeout-cleanup":
                raise KeyboardInterrupt("raw-terminate-sentinel")

        def kill(self) -> None:
            events.append("kill")

        def wait(self, *, timeout: float) -> int:
            del timeout
            events.append("wait")
            if failure_step == "wait":
                self.reaped = True
                raise OSError("raw-wait-sentinel")
            self.reaped = True
            return 143

    class Selector:
        def register(self, *_args: object) -> None:
            events.append("register")
            if failure_step == "register":
                raise OSError("raw-register-sentinel")

        def select(self, _timeout: float) -> list[object]:
            events.append("select")
            if failure_step == "select":
                raise KeyboardInterrupt("raw-select-sentinel")
            if failure_step in {"timeout", "timeout-cleanup"}:
                return []
            return [object()]

        def close(self) -> None:
            events.append("selector-close")

    def popen(*_args: object, **_kwargs: object) -> Process:
        if failure_step == "spawn":
            raise OSError("raw-spawn-sentinel")
        return Process()

    def read(_fd: int, _size: int) -> bytes:
        events.append("read")
        if failure_step == "read":
            raise OSError("raw-read-sentinel")
        return b""

    monkeypatch.setattr(operator.subprocess, "Popen", popen)
    monkeypatch.setattr(operator.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(operator.os, "read", read)

    outcome = operator._BoundedProcessExecutor().bounded_outcome(
        ("fixed",),
        classification="FIXED",
        timeout_seconds=1,
    )

    assert outcome.kind.value == expected_kind
    assert outcome.output is None


@pytest.mark.parametrize(
    ("field_name", "enum_name", "member_name"),
    (
        ("buildx_authority", "BuildxAuthorityPredicate", "UNKNOWN"),
        ("buildx_distribution", "BuildxDistributionPredicate", "DOCUMENTED_DESKTOP_SUFFIX"),
        ("builder_selection", "BuilderSelectionPredicate", "PASS"),
        ("node_schema", "NodeSchemaPredicate", "NODE_NOT_MAPPING"),
        ("prior_driver", "PriorDriverPredicate", "UNRECOGNIZED"),
        ("builder_error", "BuilderErrorPredicate", "ABSENT"),
        ("prior_target_relation", "PriorTargetRelationPredicate", "DISTINCT"),
        ("prior_status", "PriorStatusPredicate", "RUNNING"),
        ("prior_node_error", "BuilderErrorPredicate", "PRESENT"),
        ("target_contract", "TargetContractPredicate", "PASS"),
        ("first_defect", "DockerBuilderSelectionPlanPredicate", "CURRENT_ALREADY_CANONICAL"),
    ),
)
def test_context_default_preflight_detects_every_snapshot_field_drift(
    field_name: str,
    enum_name: str,
    member_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(operator)
    original = operator.evaluate_docker_builder_selection_plan
    calls = 0

    def drifting_evaluation(*args: object, **kwargs: object) -> Any:
        nonlocal calls
        calls += 1
        evaluation = original(*args, **kwargs)
        if calls == 2:
            enum_type = getattr(operator, enum_name)
            changed = replace(
                evaluation.snapshot,
                **{field_name: getattr(enum_type, member_name)},
            )
            return replace(evaluation, snapshot=changed)
        return evaluation

    monkeypatch.setattr(operator, "evaluate_docker_builder_selection_plan", drifting_evaluation)

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.ContextDefaultBuilderPreflightPredicate.PRESTATE_DRIFT
    assert evidence.phenotype_known is True
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 2
    assert executor.selection_calls == []


@pytest.mark.parametrize(
    "error",
    (
        KeyboardInterrupt("raw-interrupt-sentinel"),
        SystemExit("raw-system-exit-sentinel"),
    ),
)
def test_context_default_preflight_interrupt_stops_before_reproof(
    error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(operator, daemon_error=error)

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.ContextDefaultBuilderPreflightPredicate.UNKNOWN
    assert evidence.phenotype_known is True
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 1
    assert executor.selection_calls == []
    assert "raw-" not in operator.format_context_default_builder_preflight(evidence)


def test_context_default_preflight_unreaped_probe_never_runs_reproof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _context_default_executor(
        operator,
        daemon_error=operator._ProcessUnreaped(),
    )

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.ContextDefaultBuilderPreflightPredicate.UNKNOWN
    assert evidence.phenotype_known is True
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 1
    assert executor.calls.count(("docker", "buildx", "ls", "--format", "{{json .}}")) == 1
    assert executor.selection_calls == []


def test_context_default_preflight_lock_exit_downgrades_without_erasing_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(
        operator,
        monkeypatch,
        lock_exit_failure=RuntimeError("raw-lock-exit-sentinel"),
    )
    executor = _context_default_executor(operator)

    evidence = operator._run_context_default_builder_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.ContextDefaultBuilderPreflightPredicate.UNKNOWN
    assert evidence.phenotype_known is True
    assert evidence.daemon_probe_count == 1
    assert evidence.builder_inventory_query_count == 2
    assert executor.selection_calls == []


def test_context_default_preflight_main_is_fixed_nonzero_and_normal_operator_query_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    fixed = operator.ContextDefaultBuilderPreflightEvidence(
        classification=operator.BuilderSelectionReconcileClassification.REJECTED,
        predicate=operator.ContextDefaultBuilderPreflightPredicate.BUILDX_DEFAULT_UNRESOLVED,
        phenotype_known=True,
        buildx_version_query_count=1,
        builder_inventory_query_count=2,
        daemon_probe_count=1,
    )
    monkeypatch.setattr(
        operator,
        "_run_context_default_builder_preflight",
        lambda _runtime: fixed,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(OPERATOR),
            "--diagnostic-phase",
            "CONTEXT_DEFAULT_BUILDER_PREFLIGHT",
        ],
    )

    assert operator.main() == 2
    document = json.loads(capsys.readouterr().out)
    assert document["classification"] == "REJECTED"
    assert document["predicate"] == "BUILDX_DEFAULT_UNRESOLVED"

    ordinary_executor = _Executor()
    ordinary = operator._run_operator(
        operator._RuntimeState(),
        executor=ordinary_executor,
        environ={},
    )
    assert ordinary.action_attempted is True
    assert ("docker", "version", "--format", "{{.Server.Version}}") not in (ordinary_executor.calls)


def test_context_default_preflight_evidence_rejects_pass_and_impossible_counts() -> None:
    operator = _load_operator()
    valid = {
        "classification": operator.BuilderSelectionReconcileClassification.REJECTED,
        "predicate": operator.ContextDefaultBuilderPreflightPredicate.BUILDX_DEFAULT_UNRESOLVED,
        "phenotype_known": True,
        "buildx_version_query_count": 1,
        "builder_inventory_query_count": 2,
        "daemon_probe_count": 1,
    }

    for changed in (
        {"classification": operator.BuilderSelectionReconcileClassification.PASS},
        {"predicate": operator.ContextDefaultBuilderPreflightPredicate.UNKNOWN},
        {"phenotype_known": False},
        {"buildx_version_query_count": 0},
        {"builder_inventory_query_count": 3},
        {"daemon_probe_count": 0},
        {"action_count": 1},
    ):
        with pytest.raises(
            ValueError,
            match="CONTEXT_DEFAULT_BUILDER_PREFLIGHT_EVIDENCE_INVALID",
        ):
            operator.ContextDefaultBuilderPreflightEvidence(**(valid | changed))


@pytest.mark.parametrize(
    ("output", "predicate_name"),
    (
        ('{"Status":"running"}', "RUNNING"),
        ('{"undocumented-key-name":"stopped"}', "STOPPED"),
        (
            '{"opaque-name":"raw-name-sentinel","session":7,'
            '"provider-state":"running","ready":true,"optional":null}',
            "RUNNING",
        ),
        (
            json.dumps(
                {**{f"opaque-{index}": index for index in range(31)}, "semantic": "stopped"}
            ),
            "STOPPED",
        ),
    ),
)
def test_desktop_status_document_accepts_one_key_agnostic_semantic_token(
    output: str,
    predicate_name: str,
) -> None:
    operator = _load_operator()

    predicate = operator._classify_desktop_status_document(output)

    assert predicate is operator.DockerDesktopStatusPreflightPredicate[predicate_name]


@pytest.mark.parametrize(
    "output",
    (
        "[]",
        '"running"',
        "{}",
        '{"Status":"starting"}',
        '{"Status":"unknown"}',
        '{"Status":"RUNNING"}',
        '{"first":"running","second":"stopped"}',
        '{"first":"running","second":"running"}',
        '{"Status":"running","Status":"running"}',
        '{"nested":{"Status":"running"}}',
        '{"nested":["running"]}',
        '{"name":"raw-name-sentinel","session":7}',
        '{"Status":null}',
        '{"Status":NaN}',
        '{"Status":Infinity}',
        '{"Status":1e999}',
        json.dumps({**{f"opaque-{index}": index for index in range(32)}, "state": "running"}),
        '{"Status":"running"',
        '{"Status":"' + "x" * 4096 + '"}',
    ),
)
def test_desktop_status_document_rejects_ambiguous_nested_or_invalid_evidence(
    output: str,
) -> None:
    operator = _load_operator()

    predicate = operator._classify_desktop_status_document(output)

    assert predicate is operator.DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID


@pytest.mark.parametrize(
    ("semantic_token", "ambiguous_token"),
    (
        ("running", "starting"),
        ("stopped", "unknown"),
        ("running", "Running"),
        ("stopped", "STOPPED"),
        ("running", " stopped "),
        ("stopped", "\trunning\t"),
        ("running", " Starting "),
        ("stopped", " UNKNOWN "),
    ),
)
def test_desktop_status_document_rejects_combined_lifecycle_ambiguity(
    semantic_token: str,
    ambiguous_token: str,
) -> None:
    operator = _load_operator()
    output = json.dumps(
        {
            "opaque-name": "raw-name-sentinel",
            "semantic": semantic_token,
            "auxiliary": ambiguous_token,
        }
    )

    predicate = operator._classify_desktop_status_document(output)

    assert predicate is operator.DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID


def test_desktop_status_preflight_combined_ambiguity_is_fixed_and_nonleaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _desktop_status_executor(
        operator,
        output=json.dumps(
            {
                "semantic": "running",
                "auxiliary": " UNKNOWN ",
                "opaque-name": "raw-name-sentinel",
            }
        ),
    )

    evidence = operator._run_docker_desktop_status_preflight(
        operator._RuntimeState(), executor=executor, environ={}
    )
    line = operator.format_docker_desktop_status_preflight(evidence)

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is (
        operator.DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
    )
    assert evidence.desktop_status_query_count == 1
    assert "UNKNOWN" not in line
    assert "raw-name-sentinel" not in line


@pytest.mark.parametrize(
    ("semantic_token", "predicate_name"),
    (("running", "RUNNING"), ("stopped", "STOPPED")),
)
def test_desktop_status_preflight_observes_status_without_later_action(
    semantic_token: str,
    predicate_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _desktop_status_executor(
        operator,
        output=json.dumps(
            {
                "opaque-name": "raw-name-sentinel",
                "session": "raw-session-sentinel",
                "provider-state": semantic_token,
                "ready": True,
            }
        ),
    )

    evidence = operator._run_docker_desktop_status_preflight(
        operator._RuntimeState(),
        executor=executor,
        environ={},
    )
    line = operator.format_docker_desktop_status_preflight(evidence)
    document = json.loads(line)

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.DockerDesktopStatusPreflightPredicate[predicate_name]
    assert evidence.desktop_status_query_count == 1
    assert executor.calls == [("docker", "desktop", "status", "--format", "json")]
    assert executor.selection_calls == []
    assert document["predicate"] == predicate_name
    assert all(
        document[name] == 0
        for name in (
            "action_count",
            "rollback_count",
            "selection_mutation_count",
            "engine_query_count",
            "buildx_query_count",
            "cache_action_count",
            "build_count",
            "container_action_count",
            "volume_action_count",
            "business_mutation_count",
            "state_mutation_count",
            "push_count",
            "mutation_count",
            "retry_count",
        )
    )
    assert "provider-state" not in line
    assert "raw-name-sentinel" not in line
    assert "raw-session-sentinel" not in line


@pytest.mark.parametrize(
    ("outcome_kind", "predicate_name"),
    (
        ("REAPED_NONZERO", "STATUS_UNAVAILABLE"),
        ("REAPED_TIMEOUT", "STATUS_UNAVAILABLE"),
        ("OUTPUT_INVALID", "STATUS_EVIDENCE_INVALID"),
    ),
)
def test_desktop_status_preflight_classifies_trustworthy_process_outcomes_and_reproves(
    outcome_kind: str,
    predicate_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    source_calls = 0

    def stable_source(_executor: object) -> str:
        nonlocal source_calls
        source_calls += 1
        return "a" * 40

    monkeypatch.setattr(operator, "_source_identity", stable_source)
    executor = _desktop_status_executor(operator, outcome_kind=outcome_kind)

    evidence = operator._run_docker_desktop_status_preflight(
        operator._RuntimeState(), executor=executor, environ={}
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.DockerDesktopStatusPreflightPredicate[predicate_name]
    assert evidence.desktop_status_query_count == 1
    assert source_calls == 2
    assert executor.calls == [("docker", "desktop", "status", "--format", "json")]


@pytest.mark.parametrize(
    "error",
    (
        OSError("raw-spawn-sentinel"),
        KeyboardInterrupt("raw-interrupt-sentinel"),
        SystemExit("raw-system-exit-sentinel"),
    ),
)
def test_desktop_status_preflight_ambiguous_process_stops_without_reproof(
    error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    source_calls = 0

    def stable_source(_executor: object) -> str:
        nonlocal source_calls
        source_calls += 1
        return "a" * 40

    monkeypatch.setattr(operator, "_source_identity", stable_source)
    executor = _desktop_status_executor(operator, error=error)

    evidence = operator._run_docker_desktop_status_preflight(
        operator._RuntimeState(), executor=executor, environ={}
    )
    line = operator.format_docker_desktop_status_preflight(evidence)

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.DockerDesktopStatusPreflightPredicate.UNKNOWN
    assert evidence.desktop_status_query_count == 1
    assert source_calls == 1
    assert executor.selection_calls == []
    assert "raw-" not in line


def test_desktop_status_preflight_typed_internal_failure_stops_without_reproof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    executor = _desktop_status_executor(operator, outcome_kind="INTERNAL_FAILURE")

    evidence = operator._run_docker_desktop_status_preflight(
        operator._RuntimeState(), executor=executor, environ={}
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.DockerDesktopStatusPreflightPredicate.UNKNOWN
    assert evidence.desktop_status_query_count == 1


@pytest.mark.parametrize("drift_kind", ("source", "context"))
def test_desktop_status_preflight_detects_source_or_context_drift(
    drift_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(operator, monkeypatch)
    source_values = iter(("a" * 40, "b" * 40 if drift_kind == "source" else "a" * 40))
    context_values = iter(
        ("desktop-linux", "changed" if drift_kind == "context" else "desktop-linux")
    )
    monkeypatch.setattr(operator, "_source_identity", lambda _executor: next(source_values))
    monkeypatch.setattr(
        operator,
        "require_local_unix_docker_context",
        lambda _executor, _environ: next(context_values),
    )
    executor = _desktop_status_executor(operator)

    evidence = operator._run_docker_desktop_status_preflight(
        operator._RuntimeState(), executor=executor, environ={}
    )

    assert evidence.classification is operator.BuilderSelectionReconcileClassification.REJECTED
    assert evidence.predicate is operator.DockerDesktopStatusPreflightPredicate.PRESTATE_DRIFT
    assert evidence.desktop_status_query_count == 1
    assert executor.selection_calls == []


def test_desktop_status_preflight_lock_exit_preserves_query_and_downgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _load_operator()
    _install_fixed_context(
        operator,
        monkeypatch,
        lock_exit_failure=RuntimeError("raw-lock-exit-sentinel"),
    )
    executor = _desktop_status_executor(operator)

    evidence = operator._run_docker_desktop_status_preflight(
        operator._RuntimeState(), executor=executor, environ={}
    )

    assert evidence.classification is (
        operator.BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is operator.DockerDesktopStatusPreflightPredicate.UNKNOWN
    assert evidence.desktop_status_query_count == 1
    assert "raw-" not in operator.format_docker_desktop_status_preflight(evidence)


def test_desktop_status_preflight_main_is_fixed_nonzero_and_normal_query_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = _load_operator()
    fixed = operator.DockerDesktopStatusPreflightEvidence(
        classification=operator.BuilderSelectionReconcileClassification.REJECTED,
        predicate=operator.DockerDesktopStatusPreflightPredicate.RUNNING,
        desktop_status_query_count=1,
    )
    monkeypatch.setattr(operator, "_run_docker_desktop_status_preflight", lambda _runtime: fixed)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(OPERATOR), "--diagnostic-phase", "DOCKER_DESKTOP_STATUS_PREFLIGHT"],
    )

    assert operator.main() == 2
    document = json.loads(capsys.readouterr().out)
    assert document["schema"] == "DOCKER_DESKTOP_STATUS_PREFLIGHT_V1"
    assert document["classification"] == "REJECTED"
    assert document["predicate"] == "RUNNING"

    _install_fixed_context(operator, monkeypatch)
    ordinary_executor = _Executor()
    ordinary = operator._run_operator(
        operator._RuntimeState(), executor=ordinary_executor, environ={}
    )
    assert ordinary.action_attempted is True
    assert ("docker", "desktop", "status", "--format", "json") not in ordinary_executor.calls


def test_desktop_status_preflight_evidence_rejects_pass_unknown_and_nonzero_actions() -> None:
    operator = _load_operator()
    valid = {
        "classification": operator.BuilderSelectionReconcileClassification.REJECTED,
        "predicate": operator.DockerDesktopStatusPreflightPredicate.RUNNING,
        "desktop_status_query_count": 1,
    }

    for changed in (
        {"classification": operator.BuilderSelectionReconcileClassification.PASS},
        {"predicate": operator.DockerDesktopStatusPreflightPredicate.UNKNOWN},
        {"desktop_status_query_count": 0},
        {"engine_query_count": 1},
        {"buildx_query_count": 1},
        {"action_count": 1},
        {"retry_count": 1},
    ):
        with pytest.raises(ValueError, match="DOCKER_DESKTOP_STATUS_PREFLIGHT_EVIDENCE_INVALID"):
            operator.DockerDesktopStatusPreflightEvidence(**(valid | changed))
