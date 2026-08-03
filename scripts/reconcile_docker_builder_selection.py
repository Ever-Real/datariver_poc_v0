#!/usr/bin/env python3
"""Select the existing context-owned Docker driver builder exactly once."""

from __future__ import annotations

import json
import os
import platform
import re
import selectors
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from docker_capacity import (
    DOCKER_BUILDER_LIST_PROBE,
    BuilderSelectionPredicate,
    BuilderSelectionRecorder,
    CapacityExecutor,
    DockerBuilderSelectionPlan,
    DockerBuilderSelectionPlanPredicate,
    DockerBuilderSelectionPlanRecorder,
    DockerCapacityError,
    DockerWorkflowLock,
    NodeSchemaPredicate,
    NodeSchemaRecorder,
    PriorDriverPredicate,
    PriorDriverRecorder,
    docker_builder_is_idle,
    docker_builder_selection_residual_count,
    exclusive_docker_workflow_lock,
    parse_docker_builder_inventory,
    require_docker_builder_selection_plan,
    require_docker_builder_selection_poststate,
    require_local_unix_docker_context,
)
from platform_workflow import (
    ROOT,
    environment_key_hashes,
    load_applied_state,
    read_env_values,
    state_path,
)

PROFILE = "mac-development"
ENVIRONMENT_FILE = ".env.mac-development"
MAXIMUM_EVIDENCE_BYTES = 1024
_MAXIMUM_PROCESS_OUTPUT_BYTES = 256 * 1024
_PROCESS_REAP_SECONDS = 5
_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_BUILDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_GIT_STATUS = "DOCKER_BUILDER_SELECTION_GIT_STATUS"
_GIT_COMMIT = "DOCKER_BUILDER_SELECTION_GIT_COMMIT"
_GIT_BRANCH = "DOCKER_BUILDER_SELECTION_GIT_BRANCH"
_SELECTION_ACTION = "DOCKER_BUILDER_SELECTION_ACTION"


class BuilderSelectionReconcileClassification(StrEnum):
    PASS = "PASS"  # noqa: S105 - fixed result predicate, not a secret.
    REJECTED = "REJECTED"
    OPERATOR_REVIEW_REQUIRED = "OPERATOR_REVIEW_REQUIRED"


class BuilderSelectionReconcilePredicate(StrEnum):
    ARGUMENTS = "ARGUMENTS"
    PLATFORM = "PLATFORM"
    SOURCE = "SOURCE"
    HOST_ENVIRONMENT = "HOST_ENVIRONMENT"
    ENVIRONMENT_OVERRIDE = "ENVIRONMENT_OVERRIDE"
    DOCKER_CONTEXT = "DOCKER_CONTEXT"
    BUILDER_INVENTORY = "BUILDER_INVENTORY"
    PRESTATE = "PRESTATE"
    ACTIVE_BUILDS = "ACTIVE_BUILDS"
    ACTION = "ACTION"
    POSTSTATE = "POSTSTATE"
    ROLLBACK = "ROLLBACK"
    PASS = "PASS"  # noqa: S105 - fixed result predicate, not a secret.
    UNKNOWN = "UNKNOWN"


class BuilderSelectionPrestateCheckpoint(StrEnum):
    CAPTURE = "CAPTURE"
    REPROOF = "REPROOF"


_PRESTATE_DIAGNOSTIC_PHASE = "BUILDER_SELECTION_PRESTATE"


def _prestate_nested_evidence_is_consistent(
    plan: DockerBuilderSelectionPlanPredicate | None,
    builder: BuilderSelectionPredicate | None,
    node: NodeSchemaPredicate | None,
    prior_driver: PriorDriverPredicate | None,
) -> bool:
    if plan is None:
        return builder is None and node is None and prior_driver is None
    if node is not None and builder is None:
        return False
    if plan is DockerBuilderSelectionPlanPredicate.CURRENT_SELECTION_CONTRACT:
        if builder is None:
            return node is None and prior_driver is None
        return builder is not BuilderSelectionPredicate.PASS and prior_driver is None
    if plan is DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL:
        return (
            builder is BuilderSelectionPredicate.PASS
            and node is NodeSchemaPredicate.PASS
            and prior_driver is None
        )
    if plan is DockerBuilderSelectionPlanPredicate.CURRENT_COUNT:
        return (
            builder
            in {
                BuilderSelectionPredicate.CURRENT_MISSING,
                BuilderSelectionPredicate.CURRENT_AMBIGUOUS,
            }
            and node is NodeSchemaPredicate.PASS
            and prior_driver is None
        )
    if plan is DockerBuilderSelectionPlanPredicate.INVENTORY_DUPLICATE:
        return (
            builder is BuilderSelectionPredicate.DRIVER_NOT_DOCKER
            and node is NodeSchemaPredicate.PASS
            and prior_driver is None
        )
    if plan is DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER:
        return (
            builder is BuilderSelectionPredicate.DRIVER_NOT_DOCKER
            and node is NodeSchemaPredicate.PASS
            and prior_driver
            in {
                PriorDriverPredicate.CLOUD,
                PriorDriverPredicate.KUBERNETES,
                PriorDriverPredicate.REMOTE,
                PriorDriverPredicate.UNRECOGNIZED,
            }
        )
    if plan is DockerBuilderSelectionPlanPredicate.PRIOR_STATUS:
        return (
            builder is BuilderSelectionPredicate.DRIVER_NOT_DOCKER
            and node is NodeSchemaPredicate.PASS
            and prior_driver is PriorDriverPredicate.PASS
        )
    return (
        builder is BuilderSelectionPredicate.DRIVER_NOT_DOCKER
        and node is NodeSchemaPredicate.PASS
        and prior_driver is PriorDriverPredicate.PASS
    )


@dataclass(frozen=True)
class BuilderSelectionReconcileEvidence:
    classification: BuilderSelectionReconcileClassification
    predicate: BuilderSelectionReconcilePredicate
    action_attempted: bool
    action_succeeded: bool
    mutation_outcome_known: bool
    poststate_known: bool
    poststate_valid: bool
    rollback_attempted: bool
    rollback_succeeded: bool
    rollback_outcome_known: bool
    selection_mutation_count: int
    residual_known: bool
    residual_count: int | None
    prestate_known: bool = False
    prestate_checkpoint: BuilderSelectionPrestateCheckpoint | None = None
    prestate_predicate: DockerBuilderSelectionPlanPredicate | None = None
    builder_selection_predicate: BuilderSelectionPredicate | None = None
    node_schema_predicate: NodeSchemaPredicate | None = None
    prior_driver_known: bool = False
    prior_driver_predicate: PriorDriverPredicate | None = None
    cache_action_count: int = 0
    build_count: int = 0
    container_action_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        boolean_values = (
            self.action_attempted,
            self.action_succeeded,
            self.mutation_outcome_known,
            self.poststate_known,
            self.poststate_valid,
            self.rollback_attempted,
            self.rollback_succeeded,
            self.rollback_outcome_known,
            self.residual_known,
            self.prestate_known,
            self.prior_driver_known,
        )
        counts = (
            self.selection_mutation_count,
            self.cache_action_count,
            self.build_count,
            self.container_action_count,
            self.retry_count,
        )
        if (
            not isinstance(self.classification, BuilderSelectionReconcileClassification)
            or not isinstance(self.predicate, BuilderSelectionReconcilePredicate)
            or any(type(value) is not bool for value in boolean_values)
            or any(type(value) is not int or value < 0 for value in counts)
            or self.selection_mutation_count not in {0, 1, 2}
            or self.cache_action_count != 0
            or self.build_count != 0
            or self.container_action_count != 0
            or self.retry_count != 0
            or (self.action_succeeded and not self.action_attempted)
            or (self.poststate_valid and not self.poststate_known)
            or (self.rollback_succeeded and not self.rollback_attempted)
            or (self.rollback_succeeded and not self.rollback_outcome_known)
            or (self.rollback_attempted and not self.action_attempted)
            or (not self.rollback_attempted and not self.rollback_outcome_known)
            or self.selection_mutation_count
            != int(self.action_attempted) + int(self.rollback_attempted)
            or self.residual_known != (self.residual_count is not None)
            or self.prestate_known
            != (self.prestate_checkpoint is not None and self.prestate_predicate is not None)
            or self.prior_driver_known != (self.prior_driver_predicate is not None)
            or (
                self.prestate_checkpoint is not None
                and not isinstance(
                    self.prestate_checkpoint,
                    BuilderSelectionPrestateCheckpoint,
                )
            )
            or (
                self.prestate_predicate is not None
                and not isinstance(
                    self.prestate_predicate,
                    DockerBuilderSelectionPlanPredicate,
                )
            )
            or (
                self.builder_selection_predicate is not None
                and not isinstance(
                    self.builder_selection_predicate,
                    BuilderSelectionPredicate,
                )
            )
            or (
                self.node_schema_predicate is not None
                and not isinstance(self.node_schema_predicate, NodeSchemaPredicate)
            )
            or (
                self.prior_driver_predicate is not None
                and not isinstance(self.prior_driver_predicate, PriorDriverPredicate)
            )
            or (
                not self.prestate_known
                and (
                    self.prestate_checkpoint is not None
                    or self.prestate_predicate is not None
                    or self.builder_selection_predicate is not None
                    or self.node_schema_predicate is not None
                    or self.prior_driver_known
                    or self.prior_driver_predicate is not None
                )
            )
            or self.prestate_predicate is DockerBuilderSelectionPlanPredicate.UNKNOWN
            or self.builder_selection_predicate is BuilderSelectionPredicate.UNKNOWN
            or self.node_schema_predicate is NodeSchemaPredicate.UNKNOWN
            or self.prior_driver_predicate is PriorDriverPredicate.UNKNOWN
            or not _prestate_nested_evidence_is_consistent(
                self.prestate_predicate,
                self.builder_selection_predicate,
                self.node_schema_predicate,
                self.prior_driver_predicate,
            )
            or (
                self.residual_count is not None
                and (type(self.residual_count) is not int or not 0 <= self.residual_count <= 128)
            )
        ):
            raise ValueError("DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID")
        if self.classification is BuilderSelectionReconcileClassification.PASS and not (
            self.predicate is BuilderSelectionReconcilePredicate.PASS
            and self.action_attempted
            and self.action_succeeded
            and self.mutation_outcome_known
            and self.poststate_known
            and self.poststate_valid
            and not self.rollback_attempted
            and self.rollback_outcome_known
            and self.residual_count == 0
        ):
            raise ValueError("DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID")
        if self.predicate is BuilderSelectionReconcilePredicate.PASS and (
            self.classification is not BuilderSelectionReconcileClassification.PASS
        ):
            raise ValueError("DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID")
        plan_failed = self.prestate_predicate not in {
            None,
            DockerBuilderSelectionPlanPredicate.PASS,
        }
        if (self.predicate is BuilderSelectionReconcilePredicate.PRESTATE) != bool(
            self.prestate_known and plan_failed
        ):
            raise ValueError("DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID")

    @classmethod
    def pass_evidence(cls) -> BuilderSelectionReconcileEvidence:
        return cls(
            classification=BuilderSelectionReconcileClassification.PASS,
            predicate=BuilderSelectionReconcilePredicate.PASS,
            action_attempted=True,
            action_succeeded=True,
            mutation_outcome_known=True,
            poststate_known=True,
            poststate_valid=True,
            rollback_attempted=False,
            rollback_succeeded=False,
            rollback_outcome_known=True,
            selection_mutation_count=1,
            residual_known=True,
            residual_count=0,
            prestate_known=True,
            prestate_checkpoint=BuilderSelectionPrestateCheckpoint.REPROOF,
            prestate_predicate=DockerBuilderSelectionPlanPredicate.PASS,
            builder_selection_predicate=BuilderSelectionPredicate.DRIVER_NOT_DOCKER,
            node_schema_predicate=NodeSchemaPredicate.PASS,
            prior_driver_known=True,
            prior_driver_predicate=PriorDriverPredicate.PASS,
        )

    @classmethod
    def review_required_after_action(cls) -> BuilderSelectionReconcileEvidence:
        return cls(
            classification=(BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED),
            predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
            action_attempted=True,
            action_succeeded=False,
            mutation_outcome_known=False,
            poststate_known=False,
            poststate_valid=False,
            rollback_attempted=False,
            rollback_succeeded=False,
            rollback_outcome_known=True,
            selection_mutation_count=1,
            residual_known=False,
            residual_count=None,
            prestate_known=True,
            prestate_checkpoint=BuilderSelectionPrestateCheckpoint.REPROOF,
            prestate_predicate=DockerBuilderSelectionPlanPredicate.PASS,
            builder_selection_predicate=BuilderSelectionPredicate.DRIVER_NOT_DOCKER,
            node_schema_predicate=NodeSchemaPredicate.PASS,
            prior_driver_known=True,
            prior_driver_predicate=PriorDriverPredicate.PASS,
        )


def format_builder_selection_reconcile_evidence(
    evidence: BuilderSelectionReconcileEvidence,
) -> str:
    if not isinstance(evidence, BuilderSelectionReconcileEvidence):
        raise ValueError("DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID")
    fields: dict[str, str | bool | int] = {
        "classification": evidence.classification.value,
        "predicate": evidence.predicate.value,
        "action_attempted": evidence.action_attempted,
        "action_succeeded": evidence.action_succeeded,
        "mutation_outcome_known": evidence.mutation_outcome_known,
        "poststate_known": evidence.poststate_known,
        "poststate_valid": evidence.poststate_valid,
        "rollback_attempted": evidence.rollback_attempted,
        "rollback_succeeded": evidence.rollback_succeeded,
        "rollback_outcome_known": evidence.rollback_outcome_known,
        "rollback_count": int(evidence.rollback_attempted),
        "selection_mutation_count": evidence.selection_mutation_count,
        "residual_known": evidence.residual_known,
        "prestate_known": evidence.prestate_known,
        "prior_driver_known": evidence.prior_driver_known,
        "cache_action_count": evidence.cache_action_count,
        "build_count": evidence.build_count,
        "container_action_count": evidence.container_action_count,
        "retry_count": evidence.retry_count,
    }
    if evidence.residual_known:
        assert evidence.residual_count is not None
        fields["residual_count"] = evidence.residual_count
    if evidence.prestate_known:
        assert evidence.prestate_checkpoint is not None
        assert evidence.prestate_predicate is not None
        fields["prestate_checkpoint"] = evidence.prestate_checkpoint.value
        fields["prestate_predicate"] = evidence.prestate_predicate.value
        if evidence.builder_selection_predicate is not None:
            fields["builder_selection_predicate"] = evidence.builder_selection_predicate.value
        if evidence.node_schema_predicate is not None:
            fields["node_schema_predicate"] = evidence.node_schema_predicate.value
    if evidence.prior_driver_known:
        assert evidence.prior_driver_predicate is not None
        fields["prior_driver_predicate"] = evidence.prior_driver_predicate.value
    line = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    if len(line.encode("utf-8")) > MAXIMUM_EVIDENCE_BYTES:
        raise ValueError("DOCKER_BUILDER_SELECTION_EVIDENCE_INVALID")
    return line


@dataclass(frozen=True)
class BuilderSelectionPrestateDiagnosticEvidence:
    classification: BuilderSelectionReconcileClassification
    predicate: BuilderSelectionReconcilePredicate
    prestate_known: bool
    prestate_checkpoint: BuilderSelectionPrestateCheckpoint | None = None
    prestate_predicate: DockerBuilderSelectionPlanPredicate | None = None
    builder_selection_predicate: BuilderSelectionPredicate | None = None
    node_schema_predicate: NodeSchemaPredicate | None = None
    prior_driver_known: bool = False
    prior_driver_predicate: PriorDriverPredicate | None = None
    phase: str = _PRESTATE_DIAGNOSTIC_PHASE
    action_count: int = 0
    rollback_count: int = 0
    selection_mutation_count: int = 0
    cache_action_count: int = 0
    build_count: int = 0
    container_action_count: int = 0
    mutation_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        counts = (
            self.action_count,
            self.rollback_count,
            self.selection_mutation_count,
            self.cache_action_count,
            self.build_count,
            self.container_action_count,
            self.mutation_count,
            self.retry_count,
        )
        structured = (
            self.prestate_checkpoint,
            self.prestate_predicate,
            self.builder_selection_predicate,
            self.node_schema_predicate,
            self.prior_driver_predicate,
        )
        if (
            not isinstance(self.classification, BuilderSelectionReconcileClassification)
            or not isinstance(self.predicate, BuilderSelectionReconcilePredicate)
            or self.phase != _PRESTATE_DIAGNOSTIC_PHASE
            or type(self.prestate_known) is not bool
            or type(self.prior_driver_known) is not bool
            or any(type(count) is not int or count != 0 for count in counts)
            or self.prestate_known
            != (self.prestate_checkpoint is not None and self.prestate_predicate is not None)
            or self.prior_driver_known != (self.prior_driver_predicate is not None)
            or (
                not self.prestate_known
                and (any(value is not None for value in structured) or self.prior_driver_known)
            )
            or (
                self.prestate_checkpoint is not None
                and not isinstance(
                    self.prestate_checkpoint,
                    BuilderSelectionPrestateCheckpoint,
                )
            )
            or (
                self.prestate_predicate is not None
                and (
                    not isinstance(
                        self.prestate_predicate,
                        DockerBuilderSelectionPlanPredicate,
                    )
                    or self.prestate_predicate is DockerBuilderSelectionPlanPredicate.UNKNOWN
                )
            )
            or (
                self.builder_selection_predicate is not None
                and (
                    not isinstance(
                        self.builder_selection_predicate,
                        BuilderSelectionPredicate,
                    )
                    or self.builder_selection_predicate is BuilderSelectionPredicate.UNKNOWN
                )
            )
            or (
                self.node_schema_predicate is not None
                and (
                    not isinstance(self.node_schema_predicate, NodeSchemaPredicate)
                    or self.node_schema_predicate is NodeSchemaPredicate.UNKNOWN
                )
            )
            or (
                self.prior_driver_predicate is not None
                and (
                    not isinstance(self.prior_driver_predicate, PriorDriverPredicate)
                    or self.prior_driver_predicate is PriorDriverPredicate.UNKNOWN
                )
            )
            or not _prestate_nested_evidence_is_consistent(
                self.prestate_predicate,
                self.builder_selection_predicate,
                self.node_schema_predicate,
                self.prior_driver_predicate,
            )
        ):
            raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")
        plan_failed = self.prestate_predicate not in {
            None,
            DockerBuilderSelectionPlanPredicate.PASS,
        }
        if self.classification is BuilderSelectionReconcileClassification.PASS:
            if not (
                self.predicate is BuilderSelectionReconcilePredicate.PASS
                and self.prestate_checkpoint is BuilderSelectionPrestateCheckpoint.REPROOF
                and self.prestate_predicate is DockerBuilderSelectionPlanPredicate.PASS
                and self.builder_selection_predicate is BuilderSelectionPredicate.DRIVER_NOT_DOCKER
                and self.node_schema_predicate is NodeSchemaPredicate.PASS
                and self.prior_driver_predicate is PriorDriverPredicate.PASS
            ):
                raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")
        elif self.classification is BuilderSelectionReconcileClassification.REJECTED:
            if not (
                self.predicate is BuilderSelectionReconcilePredicate.PRESTATE
                and self.prestate_known
                and plan_failed
            ):
                raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")
        elif not (
            self.classification is BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
            and self.predicate is BuilderSelectionReconcilePredicate.UNKNOWN
        ):
            raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")

    @classmethod
    def pass_evidence(
        cls,
        *,
        checkpoint: BuilderSelectionPrestateCheckpoint,
        plan_predicate: DockerBuilderSelectionPlanPredicate,
        builder_predicate: BuilderSelectionPredicate,
        node_predicate: NodeSchemaPredicate,
        prior_driver_predicate: PriorDriverPredicate,
    ) -> BuilderSelectionPrestateDiagnosticEvidence:
        return cls(
            classification=BuilderSelectionReconcileClassification.PASS,
            predicate=BuilderSelectionReconcilePredicate.PASS,
            prestate_known=True,
            prestate_checkpoint=checkpoint,
            prestate_predicate=plan_predicate,
            builder_selection_predicate=builder_predicate,
            node_schema_predicate=node_predicate,
            prior_driver_known=True,
            prior_driver_predicate=prior_driver_predicate,
        )


def format_builder_selection_prestate_diagnostic(
    evidence: BuilderSelectionPrestateDiagnosticEvidence,
) -> str:
    if not isinstance(evidence, BuilderSelectionPrestateDiagnosticEvidence):
        raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")
    fields: dict[str, str | bool | int] = {
        "classification": evidence.classification.value,
        "phase": evidence.phase,
        "predicate": evidence.predicate.value,
        "prestate_known": evidence.prestate_known,
        "prior_driver_known": evidence.prior_driver_known,
        "action_count": evidence.action_count,
        "rollback_count": evidence.rollback_count,
        "selection_mutation_count": evidence.selection_mutation_count,
        "cache_action_count": evidence.cache_action_count,
        "build_count": evidence.build_count,
        "container_action_count": evidence.container_action_count,
        "mutation_count": evidence.mutation_count,
        "retry_count": evidence.retry_count,
    }
    if evidence.prestate_known:
        assert evidence.prestate_checkpoint is not None
        assert evidence.prestate_predicate is not None
        fields["prestate_checkpoint"] = evidence.prestate_checkpoint.value
        fields["prestate_predicate"] = evidence.prestate_predicate.value
        if evidence.builder_selection_predicate is not None:
            fields["builder_selection_predicate"] = evidence.builder_selection_predicate.value
        if evidence.node_schema_predicate is not None:
            fields["node_schema_predicate"] = evidence.node_schema_predicate.value
    if evidence.prior_driver_known:
        assert evidence.prior_driver_predicate is not None
        fields["prior_driver_predicate"] = evidence.prior_driver_predicate.value
    line = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    if len(line.encode("utf-8")) > MAXIMUM_EVIDENCE_BYTES:
        raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")
    return line


class _ReconcileFailure(RuntimeError):
    def __init__(self, predicate: BuilderSelectionReconcilePredicate) -> None:
        super().__init__(predicate.value)
        self.predicate = predicate


class _ProcessUnreaped(BaseException):
    """A bounded child may still be running, so no later proof is trustworthy."""

    def __init__(self) -> None:
        super().__init__("DOCKER_BUILDER_SELECTION_PROCESS_UNREAPED")


def _finalize_bounded_process(
    process: subprocess.Popen[bytes] | None,
    selector: selectors.BaseSelector | None,
    *,
    completed: bool,
) -> None:
    cleanup_failed = False
    if selector is not None:
        try:
            selector.close()
        except BaseException:
            cleanup_failed = True
    if process is None:
        if cleanup_failed:
            raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED") from None
        return

    child_reaped = completed
    if not child_reaped:
        try:
            child_reaped = process.poll() is not None
        except BaseException:
            cleanup_failed = True
            child_reaped = False
        if not child_reaped:
            try:
                process.terminate()
            except BaseException:
                cleanup_failed = True
            try:
                wait_result = process.wait(timeout=_PROCESS_REAP_SECONDS)
                child_reaped = type(wait_result) is int
                cleanup_failed = cleanup_failed or not child_reaped
            except BaseException:
                cleanup_failed = True
                child_reaped = False
        if not child_reaped:
            try:
                process.kill()
            except BaseException:
                cleanup_failed = True
            try:
                wait_result = process.wait(timeout=_PROCESS_REAP_SECONDS)
                child_reaped = type(wait_result) is int
                cleanup_failed = cleanup_failed or not child_reaped
            except BaseException:
                cleanup_failed = True
                child_reaped = False

    try:
        child_reaped = process.poll() is not None
    except BaseException:
        cleanup_failed = True
        child_reaped = False
    try:
        process_output = process.stdout
    except BaseException:
        cleanup_failed = True
    else:
        if process_output is not None:
            try:
                process_output.close()
            except BaseException:
                cleanup_failed = True

    if not child_reaped:
        raise _ProcessUnreaped() from None
    if cleanup_failed:
        raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED") from None


class _BoundedProcessExecutor:
    """Run fixed argv with one in-flight combined-output cap and no shell."""

    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str:
        del classification
        process: subprocess.Popen[bytes] | None = None
        selector: selectors.BaseSelector | None = None
        completed = False
        try:
            process = subprocess.Popen(  # noqa: S603 - every argv is fixed or validated.
                arguments,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if process.stdout is None:
                raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED")
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout_seconds
            output = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED")
                events = selector.select(remaining)
                if not events:
                    raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED")
                chunk = os.read(
                    process.stdout.fileno(),
                    min(64 * 1024, _MAXIMUM_PROCESS_OUTPUT_BYTES - len(output) + 1),
                )
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > _MAXIMUM_PROCESS_OUTPUT_BYTES:
                    raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED")
            return_code = process.wait(timeout=_PROCESS_REAP_SECONDS)
            completed = True
            if return_code != 0:
                raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED")
            try:
                return bytes(output).decode("utf-8")
            except UnicodeDecodeError:
                raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED") from None
        except RuntimeError:
            raise
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED") from None
        finally:
            _finalize_bounded_process(process, selector, completed=completed)


@dataclass(frozen=True)
class _HostIdentity:
    state: tuple[object, ...]
    environment_fingerprint: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _Prestate:
    source_commit: str
    host_identity: _HostIdentity
    docker_environment_identity: tuple[str, str, str, str]
    plan: DockerBuilderSelectionPlan


@dataclass(frozen=True)
class _PostProof:
    selected: str | None
    known: bool
    valid: bool
    residual_count: int | None
    target_idle: bool | None
    prior_idle: bool | None


@dataclass(slots=True)
class _RuntimeState:
    predicate: BuilderSelectionReconcilePredicate = BuilderSelectionReconcilePredicate.UNKNOWN
    action_attempted: bool = False
    action_succeeded: bool = False
    mutation_outcome_known: bool = False
    poststate_known: bool = False
    poststate_valid: bool = False
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    rollback_outcome_known: bool = True
    residual_known: bool = True
    residual_count: int | None = 0
    prestate_checkpoint: BuilderSelectionPrestateCheckpoint | None = None
    plan_recorder: DockerBuilderSelectionPlanRecorder = field(
        default_factory=DockerBuilderSelectionPlanRecorder
    )
    builder_selection_recorder: BuilderSelectionRecorder = field(
        default_factory=BuilderSelectionRecorder
    )
    node_schema_recorder: NodeSchemaRecorder = field(default_factory=NodeSchemaRecorder)
    prior_driver_recorder: PriorDriverRecorder = field(default_factory=PriorDriverRecorder)

    @property
    def mutation_count(self) -> int:
        return int(self.action_attempted) + int(self.rollback_attempted)

    def begin_prestate(self, checkpoint: BuilderSelectionPrestateCheckpoint) -> None:
        self.prestate_checkpoint = checkpoint
        self.plan_recorder = DockerBuilderSelectionPlanRecorder()
        self.builder_selection_recorder = BuilderSelectionRecorder()
        self.node_schema_recorder = NodeSchemaRecorder()
        self.prior_driver_recorder = PriorDriverRecorder()


def _failure(predicate: BuilderSelectionReconcilePredicate) -> NoReturn:
    raise _ReconcileFailure(predicate)


def _source_identity(executor: CapacityExecutor) -> str:
    try:
        status = executor.output(
            ("git", "status", "--porcelain", "--untracked-files=normal"),
            classification=_GIT_STATUS,
            timeout_seconds=10,
        )
        commit = executor.output(
            ("git", "rev-parse", "--verify", "HEAD"),
            classification=_GIT_COMMIT,
            timeout_seconds=10,
        ).strip()
        branch = executor.output(
            ("git", "branch", "--show-current"),
            classification=_GIT_BRANCH,
            timeout_seconds=10,
        ).strip()
    except Exception:
        _failure(BuilderSelectionReconcilePredicate.SOURCE)
    if status or _SOURCE_COMMIT.fullmatch(commit) is None or branch != "dev":
        _failure(BuilderSelectionReconcilePredicate.SOURCE)
    return commit


def _host_identity(root: Path) -> _HostIdentity:
    try:
        state = load_applied_state(state_path(root, PROFILE))
        expected_environment = (root / ENVIRONMENT_FILE).resolve()
        selected_environment = Path(state.env_file).expanduser()
        if not selected_environment.is_absolute():
            selected_environment = root / selected_environment
        if (
            state.profile != PROFILE
            or state.deployment_mode != "build"
            or state.local_gateway
            or state.local_graph
            or state.applied_commit != state.runtime_commit
            or selected_environment.resolve() != expected_environment
        ):
            _failure(BuilderSelectionReconcilePredicate.HOST_ENVIRONMENT)
        values = read_env_values(expected_environment)
        fingerprints = environment_key_hashes(values)
        if not state.environment_key_hashes or fingerprints != state.environment_key_hashes:
            _failure(BuilderSelectionReconcilePredicate.HOST_ENVIRONMENT)
    except _ReconcileFailure:
        raise
    except Exception:
        _failure(BuilderSelectionReconcilePredicate.HOST_ENVIRONMENT)
    return _HostIdentity(
        state=(
            state.profile,
            state.applied_commit,
            state.runtime_commit,
            state.env_file,
            state.deployment_mode,
            state.local_gateway,
            state.local_graph,
        ),
        environment_fingerprint=tuple(sorted(fingerprints.items())),
    )


def _builder_listing(executor: CapacityExecutor) -> str:
    try:
        return executor.output(
            ("docker", "buildx", "ls", "--format", "{{json .}}"),
            classification=DOCKER_BUILDER_LIST_PROBE,
            timeout_seconds=20,
        )
    except Exception:
        _failure(BuilderSelectionReconcilePredicate.BUILDER_INVENTORY)


def _require_idle(
    builder: str,
    *,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
) -> bool:
    try:
        return docker_builder_is_idle(builder=builder, lock=lock, executor=executor)
    except Exception:
        _failure(BuilderSelectionReconcilePredicate.ACTIVE_BUILDS)


def _capture_plan_prestate(
    runtime: _RuntimeState,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> _Prestate:
    source_commit = _source_identity(executor)
    host_identity = _host_identity(root)
    if environ.get("BUILDKIT_HOST", "").strip() or environ.get("BUILDX_BUILDER", "").strip():
        _failure(BuilderSelectionReconcilePredicate.ENVIRONMENT_OVERRIDE)
    try:
        current_context = require_local_unix_docker_context(executor, environ)
    except Exception:
        _failure(BuilderSelectionReconcilePredicate.DOCKER_CONTEXT)
    raw = _builder_listing(executor)
    runtime.begin_prestate(BuilderSelectionPrestateCheckpoint.CAPTURE)
    try:
        plan = require_docker_builder_selection_plan(
            raw,
            environ,
            current_context=current_context,
            plan_recorder=runtime.plan_recorder,
            builder_selection_recorder=runtime.builder_selection_recorder,
            node_schema_recorder=runtime.node_schema_recorder,
            prior_driver_recorder=runtime.prior_driver_recorder,
        )
    except DockerCapacityError:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    return _Prestate(
        source_commit=source_commit,
        host_identity=host_identity,
        docker_environment_identity=(
            environ.get("BUILDKIT_HOST", ""),
            environ.get("BUILDX_BUILDER", ""),
            environ.get("DOCKER_HOST", ""),
            environ.get("DOCKER_CONTEXT", ""),
        ),
        plan=plan,
    )


def _capture_prestate(
    runtime: _RuntimeState,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> _Prestate:
    prestate = _capture_plan_prestate(
        runtime,
        root=root,
        lock=lock,
        executor=executor,
        environ=environ,
    )
    if not _require_idle(
        prestate.plan.prior_builder,
        lock=lock,
        executor=executor,
    ) or not _require_idle(
        prestate.plan.target_builder,
        lock=lock,
        executor=executor,
    ):
        _failure(BuilderSelectionReconcilePredicate.ACTIVE_BUILDS)
    return prestate


def _reprove_plan_prestate(
    runtime: _RuntimeState,
    prestate: _Prestate,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> None:
    runtime.begin_prestate(BuilderSelectionPrestateCheckpoint.REPROOF)
    if _source_identity(executor) != prestate.source_commit:
        _failure(BuilderSelectionReconcilePredicate.SOURCE)
    if _host_identity(root) != prestate.host_identity:
        _failure(BuilderSelectionReconcilePredicate.HOST_ENVIRONMENT)
    docker_environment_identity = tuple(
        environ.get(key, "")
        for key in ("BUILDKIT_HOST", "BUILDX_BUILDER", "DOCKER_HOST", "DOCKER_CONTEXT")
    )
    if (
        docker_environment_identity != prestate.docker_environment_identity
        or environ.get("BUILDKIT_HOST", "").strip()
        or environ.get("BUILDX_BUILDER", "").strip()
    ):
        _failure(BuilderSelectionReconcilePredicate.ENVIRONMENT_OVERRIDE)
    try:
        current_context = require_local_unix_docker_context(executor, environ)
    except Exception:
        _failure(BuilderSelectionReconcilePredicate.DOCKER_CONTEXT)
    if current_context != prestate.plan.inventory.current_context:
        _failure(BuilderSelectionReconcilePredicate.DOCKER_CONTEXT)
    raw = _builder_listing(executor)
    try:
        plan = require_docker_builder_selection_plan(
            raw,
            environ,
            current_context=current_context,
            plan_recorder=runtime.plan_recorder,
            builder_selection_recorder=runtime.builder_selection_recorder,
            node_schema_recorder=runtime.node_schema_recorder,
            prior_driver_recorder=runtime.prior_driver_recorder,
        )
    except DockerCapacityError:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    if plan != prestate.plan:
        runtime.plan_recorder.replace_pass_with_drift()
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)


def _reprove_prestate(
    runtime: _RuntimeState,
    prestate: _Prestate,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> None:
    _reprove_plan_prestate(
        runtime,
        prestate,
        root=root,
        lock=lock,
        executor=executor,
        environ=environ,
    )
    if not _require_idle(prestate.plan.prior_builder, lock=lock, executor=executor):
        _failure(BuilderSelectionReconcilePredicate.ACTIVE_BUILDS)
    if not _require_idle(prestate.plan.target_builder, lock=lock, executor=executor):
        _failure(BuilderSelectionReconcilePredicate.ACTIVE_BUILDS)


def _capture_poststate(
    prestate: _Prestate,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> _PostProof:
    try:
        if (
            _source_identity(executor) != prestate.source_commit
            or _host_identity(root) != prestate.host_identity
            or tuple(
                environ.get(key, "")
                for key in (
                    "BUILDKIT_HOST",
                    "BUILDX_BUILDER",
                    "DOCKER_HOST",
                    "DOCKER_CONTEXT",
                )
            )
            != prestate.docker_environment_identity
            or environ.get("BUILDKIT_HOST", "").strip()
            or environ.get("BUILDX_BUILDER", "").strip()
        ):
            return _PostProof(None, False, False, None, None, None)
        current_context = require_local_unix_docker_context(executor, environ)
        if current_context != prestate.plan.inventory.current_context:
            return _PostProof(None, False, False, None, None, None)
        raw = _builder_listing(executor)
        observed = parse_docker_builder_inventory(
            raw,
            environ,
            current_context=current_context,
        )
    except BaseException:
        return _PostProof(None, False, False, None, None, None)

    target_residual = docker_builder_selection_residual_count(
        prestate.plan.inventory,
        observed,
        selected_builder=prestate.plan.target_builder,
    )
    prior_residual = docker_builder_selection_residual_count(
        prestate.plan.inventory,
        observed,
        selected_builder=prestate.plan.prior_builder,
    )
    selected: str | None = None
    try:
        if target_residual == 0:
            require_docker_builder_selection_poststate(
                prestate.plan,
                raw,
                environ,
                selected_builder=prestate.plan.target_builder,
            )
            selected = prestate.plan.target_builder
        elif prior_residual == 0:
            require_docker_builder_selection_poststate(
                prestate.plan,
                raw,
                environ,
                selected_builder=prestate.plan.prior_builder,
            )
            selected = prestate.plan.prior_builder
    except DockerCapacityError:
        selected = None
    if selected is None:
        exact_residual_count = min(target_residual, prior_residual)
        return _PostProof(
            None,
            True,
            False,
            exact_residual_count if exact_residual_count <= 128 else None,
            None,
            None,
        )
    try:
        target_idle = docker_builder_is_idle(
            builder=prestate.plan.target_builder,
            lock=lock,
            executor=executor,
        )
        prior_idle = docker_builder_is_idle(
            builder=prestate.plan.prior_builder,
            lock=lock,
            executor=executor,
        )
    except BaseException:
        return _PostProof(selected, False, False, None, None, None)
    return _PostProof(
        selected,
        True,
        selected == prestate.plan.target_builder and target_idle and prior_idle,
        0,
        target_idle,
        prior_idle,
    )


def _evidence_from_runtime(
    runtime: _RuntimeState,
    *,
    classification: BuilderSelectionReconcileClassification,
    predicate: BuilderSelectionReconcilePredicate,
) -> BuilderSelectionReconcileEvidence:
    prestate_known = runtime.plan_recorder.known
    return BuilderSelectionReconcileEvidence(
        classification=classification,
        predicate=predicate,
        action_attempted=runtime.action_attempted,
        action_succeeded=runtime.action_succeeded,
        mutation_outcome_known=runtime.mutation_outcome_known,
        poststate_known=runtime.poststate_known,
        poststate_valid=runtime.poststate_valid,
        rollback_attempted=runtime.rollback_attempted,
        rollback_succeeded=runtime.rollback_succeeded,
        rollback_outcome_known=runtime.rollback_outcome_known,
        selection_mutation_count=runtime.mutation_count,
        residual_known=runtime.residual_known,
        residual_count=runtime.residual_count,
        prestate_known=prestate_known,
        prestate_checkpoint=runtime.prestate_checkpoint if prestate_known else None,
        prestate_predicate=runtime.plan_recorder.predicate if prestate_known else None,
        builder_selection_predicate=(
            runtime.builder_selection_recorder.predicate
            if prestate_known and runtime.builder_selection_recorder.known
            else None
        ),
        node_schema_predicate=(
            runtime.node_schema_recorder.predicate
            if prestate_known and runtime.node_schema_recorder.known
            else None
        ),
        prior_driver_known=(prestate_known and runtime.prior_driver_recorder.known),
        prior_driver_predicate=(
            runtime.prior_driver_recorder.predicate
            if prestate_known and runtime.prior_driver_recorder.known
            else None
        ),
    )


def _rejected_before_action(
    predicate: BuilderSelectionReconcilePredicate,
) -> BuilderSelectionReconcileEvidence:
    return BuilderSelectionReconcileEvidence(
        classification=BuilderSelectionReconcileClassification.REJECTED,
        predicate=predicate,
        action_attempted=False,
        action_succeeded=False,
        mutation_outcome_known=True,
        poststate_known=False,
        poststate_valid=False,
        rollback_attempted=False,
        rollback_succeeded=False,
        rollback_outcome_known=True,
        selection_mutation_count=0,
        residual_known=True,
        residual_count=0,
    )


def _run_under_lock(
    runtime: _RuntimeState,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> BuilderSelectionReconcileEvidence:
    prestate = _capture_prestate(
        runtime,
        root=root,
        lock=lock,
        executor=executor,
        environ=environ,
    )
    action_interrupted = False
    _reprove_prestate(
        runtime,
        prestate,
        root=root,
        lock=lock,
        executor=executor,
        environ=environ,
    )
    runtime.action_attempted = True
    runtime.residual_known = False
    runtime.residual_count = None
    try:
        executor.output(
            prestate.plan.selection_argv,
            classification=_SELECTION_ACTION,
            timeout_seconds=30,
        )
    except _ProcessUnreaped:
        return _evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
        )
    except BaseException as error:
        action_interrupted = not isinstance(error, Exception)
    post = _capture_poststate(
        prestate,
        root=root,
        lock=lock,
        executor=executor,
        environ=environ,
    )
    runtime.poststate_known = post.known
    runtime.poststate_valid = post.valid
    runtime.residual_known = post.residual_count is not None
    runtime.residual_count = post.residual_count
    if post.selected == prestate.plan.target_builder and post.known:
        runtime.action_succeeded = True
        runtime.mutation_outcome_known = True
    elif post.selected == prestate.plan.prior_builder and post.known:
        runtime.action_succeeded = False
        runtime.mutation_outcome_known = True

    if post.valid:
        runtime.rollback_outcome_known = True
        if action_interrupted:
            return _evidence_from_runtime(
                runtime,
                classification=(BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED),
                predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
            )
        return BuilderSelectionReconcileEvidence.pass_evidence()
    if post.selected == prestate.plan.prior_builder and post.known:
        runtime.rollback_outcome_known = True
        return _evidence_from_runtime(
            runtime,
            classification=(
                BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
                if action_interrupted
                else BuilderSelectionReconcileClassification.REJECTED
            ),
            predicate=(
                BuilderSelectionReconcilePredicate.UNKNOWN
                if action_interrupted
                else BuilderSelectionReconcilePredicate.ACTION
            ),
        )
    if (
        post.selected == prestate.plan.target_builder
        and post.known
        and post.target_idle is False
        and post.prior_idle is True
        and not action_interrupted
    ):
        runtime.rollback_attempted = True
        runtime.rollback_outcome_known = False
        rollback_interrupted = False
        try:
            executor.output(
                prestate.plan.rollback_argv,
                classification=_SELECTION_ACTION,
                timeout_seconds=30,
            )
        except _ProcessUnreaped:
            runtime.mutation_outcome_known = False
            runtime.poststate_known = False
            runtime.poststate_valid = False
            runtime.residual_known = False
            runtime.residual_count = None
            return _evidence_from_runtime(
                runtime,
                classification=(BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED),
                predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
            )
        except BaseException as error:
            rollback_interrupted = not isinstance(error, Exception)
        rollback_post = _capture_poststate(
            prestate,
            root=root,
            lock=lock,
            executor=executor,
            environ=environ,
        )
        runtime.poststate_known = rollback_post.known
        runtime.poststate_valid = False
        runtime.residual_known = rollback_post.residual_count is not None
        runtime.residual_count = rollback_post.residual_count
        if (
            rollback_post.selected == prestate.plan.prior_builder
            and rollback_post.known
            and rollback_post.prior_idle is True
            and rollback_post.target_idle is True
        ):
            runtime.rollback_succeeded = True
            runtime.rollback_outcome_known = True
            runtime.mutation_outcome_known = True
            return _evidence_from_runtime(
                runtime,
                classification=(
                    BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
                    if rollback_interrupted
                    else BuilderSelectionReconcileClassification.REJECTED
                ),
                predicate=(
                    BuilderSelectionReconcilePredicate.UNKNOWN
                    if rollback_interrupted
                    else BuilderSelectionReconcilePredicate.POSTSTATE
                ),
            )
        if rollback_post.selected == prestate.plan.target_builder and rollback_post.known:
            runtime.rollback_outcome_known = True
            runtime.mutation_outcome_known = True
            if rollback_interrupted:
                return _evidence_from_runtime(
                    runtime,
                    classification=(
                        BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
                    ),
                    predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
                )
    runtime.rollback_outcome_known = not runtime.rollback_attempted
    return _evidence_from_runtime(
        runtime,
        classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
        predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
    )


def _run_operator(
    runtime: _RuntimeState,
    *,
    root: Path = ROOT,
    executor: CapacityExecutor | None = None,
    environ: Mapping[str, str] | None = None,
) -> BuilderSelectionReconcileEvidence:
    command_executor = executor or _BoundedProcessExecutor()
    selected_environment = os.environ if environ is None else environ
    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        return _rejected_before_action(BuilderSelectionReconcilePredicate.PLATFORM)
    try:
        with exclusive_docker_workflow_lock(root) as lock:
            try:
                return _run_under_lock(
                    runtime,
                    root=root,
                    lock=lock,
                    executor=command_executor,
                    environ=selected_environment,
                )
            except _ReconcileFailure as error:
                runtime.predicate = error.predicate
                return _evidence_from_runtime(
                    runtime,
                    classification=BuilderSelectionReconcileClassification.REJECTED,
                    predicate=error.predicate,
                )
    except BaseException:
        predicate = (
            BuilderSelectionReconcilePredicate.PRESTATE
            if runtime.predicate is BuilderSelectionReconcilePredicate.PRESTATE
            and runtime.plan_recorder.known
            and runtime.plan_recorder.predicate is not DockerBuilderSelectionPlanPredicate.PASS
            else BuilderSelectionReconcilePredicate.UNKNOWN
        )
        return _evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=predicate,
        )


def _diagnostic_evidence_from_runtime(
    runtime: _RuntimeState,
    *,
    classification: BuilderSelectionReconcileClassification,
    predicate: BuilderSelectionReconcilePredicate,
) -> BuilderSelectionPrestateDiagnosticEvidence:
    prestate_known = runtime.plan_recorder.known
    return BuilderSelectionPrestateDiagnosticEvidence(
        classification=classification,
        predicate=predicate,
        prestate_known=prestate_known,
        prestate_checkpoint=runtime.prestate_checkpoint if prestate_known else None,
        prestate_predicate=runtime.plan_recorder.predicate if prestate_known else None,
        builder_selection_predicate=(
            runtime.builder_selection_recorder.predicate
            if prestate_known and runtime.builder_selection_recorder.known
            else None
        ),
        node_schema_predicate=(
            runtime.node_schema_recorder.predicate
            if prestate_known and runtime.node_schema_recorder.known
            else None
        ),
        prior_driver_known=(prestate_known and runtime.prior_driver_recorder.known),
        prior_driver_predicate=(
            runtime.prior_driver_recorder.predicate
            if prestate_known and runtime.prior_driver_recorder.known
            else None
        ),
    )


def _run_prestate_diagnostic_under_lock(
    runtime: _RuntimeState,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> BuilderSelectionPrestateDiagnosticEvidence:
    prestate = _capture_plan_prestate(
        runtime,
        root=root,
        lock=lock,
        executor=executor,
        environ=environ,
    )
    _reprove_plan_prestate(
        runtime,
        prestate,
        root=root,
        lock=lock,
        executor=executor,
        environ=environ,
    )
    return _diagnostic_evidence_from_runtime(
        runtime,
        classification=BuilderSelectionReconcileClassification.PASS,
        predicate=BuilderSelectionReconcilePredicate.PASS,
    )


def _run_prestate_diagnostic(
    runtime: _RuntimeState,
    *,
    root: Path = ROOT,
    executor: CapacityExecutor | None = None,
    environ: Mapping[str, str] | None = None,
) -> BuilderSelectionPrestateDiagnosticEvidence:
    command_executor = executor or _BoundedProcessExecutor()
    selected_environment = os.environ if environ is None else environ
    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        return BuilderSelectionPrestateDiagnosticEvidence(
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
            prestate_known=False,
        )
    try:
        with exclusive_docker_workflow_lock(root) as lock:
            try:
                return _run_prestate_diagnostic_under_lock(
                    runtime,
                    root=root,
                    lock=lock,
                    executor=command_executor,
                    environ=selected_environment,
                )
            except _ReconcileFailure as error:
                runtime.predicate = error.predicate
                if (
                    error.predicate is BuilderSelectionReconcilePredicate.PRESTATE
                    and runtime.plan_recorder.known
                ):
                    return _diagnostic_evidence_from_runtime(
                        runtime,
                        classification=BuilderSelectionReconcileClassification.REJECTED,
                        predicate=error.predicate,
                    )
                return _diagnostic_evidence_from_runtime(
                    runtime,
                    classification=(
                        BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
                    ),
                    predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
                )
    except BaseException:
        return _diagnostic_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
        )


def main() -> int:
    runtime = _RuntimeState()
    arguments = tuple(sys.argv[1:])
    if arguments == ("--diagnostic-phase", _PRESTATE_DIAGNOSTIC_PHASE):
        try:
            diagnostic = _run_prestate_diagnostic(runtime)
        except BaseException:
            diagnostic = _diagnostic_evidence_from_runtime(
                runtime,
                classification=(BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED),
                predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
            )
        print(format_builder_selection_prestate_diagnostic(diagnostic), flush=True)
        return 0 if diagnostic.classification is BuilderSelectionReconcileClassification.PASS else 2
    if arguments:
        evidence = _rejected_before_action(BuilderSelectionReconcilePredicate.ARGUMENTS)
    else:
        try:
            evidence = _run_operator(runtime)
        except BaseException:
            evidence = _evidence_from_runtime(
                runtime,
                classification=(BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED),
                predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
            )
    print(format_builder_selection_reconcile_evidence(evidence), flush=True)
    return 0 if evidence.classification is BuilderSelectionReconcileClassification.PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
