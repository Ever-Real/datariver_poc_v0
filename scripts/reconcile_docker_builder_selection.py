#!/usr/bin/env python3
"""Select the existing context-owned Docker driver builder exactly once."""

from __future__ import annotations

import json
import math
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
from typing import NoReturn, Protocol

import docker_builder_prestate as _prestate
from docker_builder_prestate import (
    BuilderPrestateSnapshot,
    BuilderSelectionPredicate,
    BuildxAuthorityPredicate,
    BuildxVersionObservation,
    DockerBuilderSelectionPlanPredicate,
    NodeSchemaPredicate,
    PriorDriverPredicate,
    observe_buildx_version,
)
from docker_capacity import (
    DOCKER_BUILDER_LIST_PROBE,
    CapacityExecutor,
    DockerBuilderSelectionPlan,
    DockerCapacityError,
    DockerWorkflowLock,
    builder_prestate_snapshot_is_consistent,
    docker_builder_is_idle,
    docker_builder_selection_residual_count,
    evaluate_docker_builder_selection_plan,
    exclusive_docker_workflow_lock,
    parse_docker_builder_inventory,
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

BuilderErrorPredicate = _prestate.BuilderErrorPredicate
BuildxDistributionPredicate = _prestate.BuildxDistributionPredicate
PriorStatusPredicate = _prestate.PriorStatusPredicate
PriorTargetRelationPredicate = _prestate.PriorTargetRelationPredicate
TargetContractPredicate = _prestate.TargetContractPredicate

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
_BUILDX_VERSION_PROBE = "DOCKER_BUILDX_VERSION_PROBE"
_DAEMON_VERSION_PROBE = "DOCKER_DAEMON_VERSION_PROBE"
_DAEMON_VERSION_ARGUMENTS = ("docker", "version", "--format", "{{.Server.Version}}")
_MAXIMUM_DAEMON_VERSION_BYTES = 256
_DAEMON_VERSION_LINE = re.compile(r"^[!-~]+(?:\r?\n)?$")
_DESKTOP_STATUS_PROBE = "DOCKER_DESKTOP_STATUS_PROBE"
_DESKTOP_STATUS_ARGUMENTS = ("docker", "desktop", "status", "--format", "json")
_MAXIMUM_DESKTOP_STATUS_BYTES = 4096
_MAXIMUM_DESKTOP_STATUS_ENTRIES = 32
_DESKTOP_STATUS_SEMANTIC_TOKENS = ("running", "stopped")
_DESKTOP_STATUS_LIFECYCLE_TOKENS = ("running", "stopped", "starting", "unknown")


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
_CONTEXT_DEFAULT_PREFLIGHT_PHASE = "CONTEXT_DEFAULT_BUILDER_PREFLIGHT"
_CONTEXT_DEFAULT_PREFLIGHT_SCHEMA = "CONTEXT_DEFAULT_BUILDER_PREFLIGHT_V1"
_DESKTOP_STATUS_PREFLIGHT_PHASE = "DOCKER_DESKTOP_STATUS_PREFLIGHT"
_DESKTOP_STATUS_PREFLIGHT_SCHEMA = "DOCKER_DESKTOP_STATUS_PREFLIGHT_V1"


class ContextDefaultBuilderPreflightPredicate(StrEnum):
    DAEMON_API_UNAVAILABLE = "DAEMON_API_UNAVAILABLE"
    DAEMON_EVIDENCE_INVALID = "DAEMON_EVIDENCE_INVALID"
    BUILDX_DEFAULT_UNRESOLVED = "BUILDX_DEFAULT_UNRESOLVED"
    PRESTATE_DRIFT = "PRESTATE_DRIFT"
    UNKNOWN = "UNKNOWN"


class DockerDesktopStatusPreflightPredicate(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    STATUS_UNAVAILABLE = "STATUS_UNAVAILABLE"
    STATUS_EVIDENCE_INVALID = "STATUS_EVIDENCE_INVALID"
    PRESTATE_DRIFT = "PRESTATE_DRIFT"
    UNKNOWN = "UNKNOWN"


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
                PriorDriverPredicate.EMPTY,
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
    fields: dict[str, object] = {
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


_PRESTATE_DIAGNOSTIC_SCHEMA = "BUILDER_PRESTATE_V2"


@dataclass(frozen=True, slots=True)
class BuilderSelectionPrestateDiagnosticEvidence:
    classification: BuilderSelectionReconcileClassification
    predicate: BuilderSelectionReconcilePredicate
    prestate_known: bool
    prestate_checkpoint: BuilderSelectionPrestateCheckpoint | None = None
    prestate_predicate: DockerBuilderSelectionPlanPredicate | None = None
    observation_known: bool = False
    observation: BuilderPrestateSnapshot | None = None
    schema: str = _PRESTATE_DIAGNOSTIC_SCHEMA
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
        structured = self.prestate_checkpoint is not None and self.prestate_predicate is not None
        invalid = (
            not isinstance(self.classification, BuilderSelectionReconcileClassification)
            or not isinstance(self.predicate, BuilderSelectionReconcilePredicate)
            or self.schema != _PRESTATE_DIAGNOSTIC_SCHEMA
            or self.phase != _PRESTATE_DIAGNOSTIC_PHASE
            or type(self.prestate_known) is not bool
            or type(self.observation_known) is not bool
            or any(type(count) is not int or count != 0 for count in counts)
            or self.prestate_known != structured
            or self.observation_known != (self.observation is not None)
            or (self.observation_known and not self.prestate_known)
            or (
                self.prestate_checkpoint is not None
                and not isinstance(self.prestate_checkpoint, BuilderSelectionPrestateCheckpoint)
            )
            or (
                self.prestate_predicate is not None
                and (
                    not isinstance(self.prestate_predicate, DockerBuilderSelectionPlanPredicate)
                    or self.prestate_predicate is DockerBuilderSelectionPlanPredicate.UNKNOWN
                )
            )
            or (
                self.observation is not None
                and not builder_prestate_snapshot_is_consistent(self.observation)
            )
        )
        if invalid or not _diagnostic_classification_is_consistent(self):
            raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")


def _diagnostic_classification_is_consistent(
    evidence: BuilderSelectionPrestateDiagnosticEvidence,
) -> bool:
    plan = evidence.prestate_predicate
    observation = evidence.observation
    if observation is not None and plan not in {
        observation.first_defect,
        DockerBuilderSelectionPlanPredicate.PLAN_DRIFT,
    }:
        return False
    if evidence.classification is BuilderSelectionReconcileClassification.PASS:
        return (
            evidence.predicate is BuilderSelectionReconcilePredicate.PASS
            and evidence.prestate_checkpoint is BuilderSelectionPrestateCheckpoint.REPROOF
            and plan is DockerBuilderSelectionPlanPredicate.PASS
            and observation is not None
            and observation.first_defect is DockerBuilderSelectionPlanPredicate.PASS
            and observation.buildx_authority is not BuildxAuthorityPredicate.OUTPUT_INVALID
        )
    if evidence.classification is BuilderSelectionReconcileClassification.REJECTED:
        return (
            evidence.predicate is BuilderSelectionReconcilePredicate.PRESTATE
            and evidence.prestate_known
            and plan not in {None, DockerBuilderSelectionPlanPredicate.PASS}
        )
    return (
        evidence.classification is BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
        and evidence.predicate is BuilderSelectionReconcilePredicate.UNKNOWN
    )


def format_builder_selection_prestate_diagnostic(
    evidence: BuilderSelectionPrestateDiagnosticEvidence,
) -> str:
    if not isinstance(evidence, BuilderSelectionPrestateDiagnosticEvidence):
        raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")
    fields: dict[str, object] = {
        "classification": evidence.classification.value,
        "schema": evidence.schema,
        "phase": evidence.phase,
        "predicate": evidence.predicate.value,
        "prestate_known": evidence.prestate_known,
        "observation_known": evidence.observation_known,
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
    if evidence.observation is not None:
        observation = evidence.observation
        fields["observation"] = {
            name: getattr(observation, name).value
            for name in BuilderPrestateSnapshot.__dataclass_fields__
        }
    line = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    if len(line.encode("utf-8")) > MAXIMUM_EVIDENCE_BYTES:
        raise ValueError("DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID")
    return line


@dataclass(frozen=True, slots=True)
class ContextDefaultBuilderPreflightEvidence:
    classification: BuilderSelectionReconcileClassification
    predicate: ContextDefaultBuilderPreflightPredicate
    phenotype_known: bool
    buildx_version_query_count: int
    builder_inventory_query_count: int
    daemon_probe_count: int
    schema: str = _CONTEXT_DEFAULT_PREFLIGHT_SCHEMA
    phase: str = _CONTEXT_DEFAULT_PREFLIGHT_PHASE
    action_count: int = 0
    rollback_count: int = 0
    selection_mutation_count: int = 0
    cache_action_count: int = 0
    build_count: int = 0
    container_action_count: int = 0
    mutation_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        query_counts = (
            self.buildx_version_query_count,
            self.builder_inventory_query_count,
            self.daemon_probe_count,
        )
        action_counts = (
            self.action_count,
            self.rollback_count,
            self.selection_mutation_count,
            self.cache_action_count,
            self.build_count,
            self.container_action_count,
            self.mutation_count,
            self.retry_count,
        )
        if (
            not isinstance(self.classification, BuilderSelectionReconcileClassification)
            or not isinstance(self.predicate, ContextDefaultBuilderPreflightPredicate)
            or type(self.phenotype_known) is not bool
            or self.schema != _CONTEXT_DEFAULT_PREFLIGHT_SCHEMA
            or self.phase != _CONTEXT_DEFAULT_PREFLIGHT_PHASE
            or any(type(count) is not int for count in (*query_counts, *action_counts))
            or self.buildx_version_query_count not in {0, 1}
            or self.builder_inventory_query_count not in {0, 1, 2}
            or self.daemon_probe_count not in {0, 1}
            or any(count != 0 for count in action_counts)
            or not _context_default_preflight_evidence_is_consistent(self)
        ):
            raise ValueError("CONTEXT_DEFAULT_BUILDER_PREFLIGHT_EVIDENCE_INVALID")


def _context_default_preflight_evidence_is_consistent(
    evidence: ContextDefaultBuilderPreflightEvidence,
) -> bool:
    if evidence.builder_inventory_query_count > 0 and evidence.buildx_version_query_count != 1:
        return False
    if evidence.daemon_probe_count > 0 and (
        not evidence.phenotype_known or evidence.builder_inventory_query_count < 1
    ):
        return False
    if evidence.builder_inventory_query_count == 2 and evidence.daemon_probe_count != 1:
        return False
    if evidence.phenotype_known and (
        evidence.buildx_version_query_count != 1 or evidence.builder_inventory_query_count < 1
    ):
        return False
    if evidence.classification is BuilderSelectionReconcileClassification.REJECTED:
        if evidence.predicate is ContextDefaultBuilderPreflightPredicate.UNKNOWN:
            return False
        if evidence.predicate in {
            ContextDefaultBuilderPreflightPredicate.DAEMON_API_UNAVAILABLE,
            ContextDefaultBuilderPreflightPredicate.DAEMON_EVIDENCE_INVALID,
            ContextDefaultBuilderPreflightPredicate.BUILDX_DEFAULT_UNRESOLVED,
        }:
            return (
                evidence.phenotype_known
                and evidence.buildx_version_query_count == 1
                and evidence.builder_inventory_query_count == 2
                and evidence.daemon_probe_count == 1
            )
        return evidence.predicate is ContextDefaultBuilderPreflightPredicate.PRESTATE_DRIFT
    return (
        evidence.classification is BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
        and evidence.predicate is ContextDefaultBuilderPreflightPredicate.UNKNOWN
    )


def format_context_default_builder_preflight(
    evidence: ContextDefaultBuilderPreflightEvidence,
) -> str:
    if not isinstance(evidence, ContextDefaultBuilderPreflightEvidence):
        raise ValueError("CONTEXT_DEFAULT_BUILDER_PREFLIGHT_EVIDENCE_INVALID")
    fields: dict[str, object] = {
        "action_count": evidence.action_count,
        "builder_inventory_query_count": evidence.builder_inventory_query_count,
        "build_count": evidence.build_count,
        "buildx_version_query_count": evidence.buildx_version_query_count,
        "cache_action_count": evidence.cache_action_count,
        "classification": evidence.classification.value,
        "container_action_count": evidence.container_action_count,
        "daemon_probe_count": evidence.daemon_probe_count,
        "mutation_count": evidence.mutation_count,
        "phase": evidence.phase,
        "phenotype_known": evidence.phenotype_known,
        "predicate": evidence.predicate.value,
        "retry_count": evidence.retry_count,
        "rollback_count": evidence.rollback_count,
        "schema": evidence.schema,
        "selection_mutation_count": evidence.selection_mutation_count,
    }
    line = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    if len(line.encode("utf-8")) > MAXIMUM_EVIDENCE_BYTES:
        raise ValueError("CONTEXT_DEFAULT_BUILDER_PREFLIGHT_EVIDENCE_INVALID")
    return line


@dataclass(frozen=True, slots=True)
class DockerDesktopStatusPreflightEvidence:
    classification: BuilderSelectionReconcileClassification
    predicate: DockerDesktopStatusPreflightPredicate
    desktop_status_query_count: int
    schema: str = _DESKTOP_STATUS_PREFLIGHT_SCHEMA
    phase: str = _DESKTOP_STATUS_PREFLIGHT_PHASE
    action_count: int = 0
    rollback_count: int = 0
    selection_mutation_count: int = 0
    engine_query_count: int = 0
    buildx_query_count: int = 0
    cache_action_count: int = 0
    build_count: int = 0
    container_action_count: int = 0
    volume_action_count: int = 0
    business_mutation_count: int = 0
    state_mutation_count: int = 0
    push_count: int = 0
    mutation_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        fixed_zero_counts = (
            self.action_count,
            self.rollback_count,
            self.selection_mutation_count,
            self.engine_query_count,
            self.buildx_query_count,
            self.cache_action_count,
            self.build_count,
            self.container_action_count,
            self.volume_action_count,
            self.business_mutation_count,
            self.state_mutation_count,
            self.push_count,
            self.mutation_count,
            self.retry_count,
        )
        if (
            not isinstance(self.classification, BuilderSelectionReconcileClassification)
            or not isinstance(self.predicate, DockerDesktopStatusPreflightPredicate)
            or self.schema != _DESKTOP_STATUS_PREFLIGHT_SCHEMA
            or self.phase != _DESKTOP_STATUS_PREFLIGHT_PHASE
            or type(self.desktop_status_query_count) is not int
            or self.desktop_status_query_count not in {0, 1}
            or any(type(count) is not int or count != 0 for count in fixed_zero_counts)
            or not _desktop_status_preflight_evidence_is_consistent(self)
        ):
            raise ValueError("DOCKER_DESKTOP_STATUS_PREFLIGHT_EVIDENCE_INVALID")


def _desktop_status_preflight_evidence_is_consistent(
    evidence: DockerDesktopStatusPreflightEvidence,
) -> bool:
    if evidence.classification is BuilderSelectionReconcileClassification.REJECTED:
        if evidence.predicate is DockerDesktopStatusPreflightPredicate.UNKNOWN:
            return False
        if evidence.predicate is DockerDesktopStatusPreflightPredicate.PRESTATE_DRIFT:
            return True
        return evidence.desktop_status_query_count == 1
    return (
        evidence.classification is BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED
        and evidence.predicate is DockerDesktopStatusPreflightPredicate.UNKNOWN
    )


def format_docker_desktop_status_preflight(
    evidence: DockerDesktopStatusPreflightEvidence,
) -> str:
    if not isinstance(evidence, DockerDesktopStatusPreflightEvidence):
        raise ValueError("DOCKER_DESKTOP_STATUS_PREFLIGHT_EVIDENCE_INVALID")
    fields: dict[str, object] = {
        "action_count": evidence.action_count,
        "rollback_count": evidence.rollback_count,
        "selection_mutation_count": evidence.selection_mutation_count,
        "engine_query_count": evidence.engine_query_count,
        "buildx_query_count": evidence.buildx_query_count,
        "cache_action_count": evidence.cache_action_count,
        "build_count": evidence.build_count,
        "container_action_count": evidence.container_action_count,
        "volume_action_count": evidence.volume_action_count,
        "business_mutation_count": evidence.business_mutation_count,
        "state_mutation_count": evidence.state_mutation_count,
        "push_count": evidence.push_count,
        "mutation_count": evidence.mutation_count,
        "retry_count": evidence.retry_count,
        "desktop_status_query_count": evidence.desktop_status_query_count,
        "schema": evidence.schema,
        "phase": evidence.phase,
        "classification": evidence.classification.value,
        "predicate": evidence.predicate.value,
    }
    line = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    if len(line.encode("utf-8")) > MAXIMUM_EVIDENCE_BYTES:
        raise ValueError("DOCKER_DESKTOP_STATUS_PREFLIGHT_EVIDENCE_INVALID")
    return line


class _ReconcileFailure(RuntimeError):
    def __init__(self, predicate: BuilderSelectionReconcilePredicate) -> None:
        super().__init__(predicate.value)
        self.predicate = predicate


class _ProcessEvidenceInvalid(RuntimeError):
    """A reaped child emitted output outside the fixed bounded shape."""


class _BoundedProcessOutcomeKind(StrEnum):
    SUCCESS = "SUCCESS"
    REAPED_NONZERO = "REAPED_NONZERO"
    REAPED_TIMEOUT = "REAPED_TIMEOUT"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


class _BoundedOverflowMode(StrEnum):
    STOP_IMMEDIATELY = "STOP_IMMEDIATELY"
    OBSERVE_EXIT = "OBSERVE_EXIT"


@dataclass(frozen=True, slots=True)
class _BoundedProcessOutcome:
    kind: _BoundedProcessOutcomeKind
    output: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, _BoundedProcessOutcomeKind) or (
            (self.kind is _BoundedProcessOutcomeKind.SUCCESS) != (type(self.output) is str)
        ):
            raise ValueError("DOCKER_BUILDER_SELECTION_PROCESS_OUTCOME_INVALID")


class _ContextDefaultProcessExecutor(CapacityExecutor, Protocol):
    def bounded_outcome(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> _BoundedProcessOutcome: ...


class _ProcessUnreaped(BaseException):
    """A bounded child may still be running, so no later proof is trustworthy."""

    def __init__(self) -> None:
        super().__init__("DOCKER_BUILDER_SELECTION_PROCESS_UNREAPED")


def _finalize_bounded_process(
    process: subprocess.Popen[bytes] | None,
    selector: selectors.BaseSelector | None,
    *,
    completed: bool,
) -> bool:
    cleanup_failed = False
    if selector is not None:
        try:
            selector.close()
        except BaseException:
            cleanup_failed = True
    if process is None:
        return cleanup_failed

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
    return cleanup_failed


class _BoundedProcessExecutor:
    """Run fixed argv with one in-flight combined-output cap and no shell."""

    def _run_bounded(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
        overflow_mode: _BoundedOverflowMode,
    ) -> _BoundedProcessOutcome:
        del classification
        process: subprocess.Popen[bytes] | None = None
        selector: selectors.BaseSelector | None = None
        completed = False
        internal_failure = False
        timed_out = False
        output_invalid = False
        stopped_on_overflow = False
        return_code: int | None = None
        output = bytearray()
        try:
            process = subprocess.Popen(  # noqa: S603 - every argv is fixed or validated.
                arguments,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if process.stdout is None:
                raise OSError
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                events = selector.select(remaining)
                if not events:
                    timed_out = True
                    break
                requested_size = (
                    64 * 1024
                    if output_invalid
                    else min(
                        64 * 1024,
                        _MAXIMUM_PROCESS_OUTPUT_BYTES - len(output) + 1,
                    )
                )
                chunk = os.read(process.stdout.fileno(), requested_size)
                if not chunk:
                    break
                if not output_invalid:
                    if len(output) + len(chunk) > _MAXIMUM_PROCESS_OUTPUT_BYTES:
                        output_invalid = True
                        output.clear()
                        if overflow_mode is _BoundedOverflowMode.STOP_IMMEDIATELY:
                            stopped_on_overflow = True
                            break
                    else:
                        output.extend(chunk)
            if not timed_out and not stopped_on_overflow:
                return_code = process.wait(timeout=_PROCESS_REAP_SECONDS)
                completed = True
        except BaseException:
            internal_failure = True
        cleanup_failed = _finalize_bounded_process(process, selector, completed=completed)
        if cleanup_failed or internal_failure:
            return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.INTERNAL_FAILURE)
        if stopped_on_overflow:
            return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.OUTPUT_INVALID)
        if return_code is None and not timed_out:
            return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.INTERNAL_FAILURE)
        if return_code not in {None, 0}:
            return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.REAPED_NONZERO)
        if timed_out:
            return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.REAPED_TIMEOUT)
        if output_invalid:
            return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.OUTPUT_INVALID)
        try:
            decoded = bytes(output).decode("utf-8")
        except UnicodeDecodeError:
            return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.OUTPUT_INVALID)
        return _BoundedProcessOutcome(_BoundedProcessOutcomeKind.SUCCESS, decoded)

    def bounded_outcome(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> _BoundedProcessOutcome:
        return self._run_bounded(
            arguments,
            classification=classification,
            timeout_seconds=timeout_seconds,
            overflow_mode=_BoundedOverflowMode.OBSERVE_EXIT,
        )

    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str:
        outcome = self._run_bounded(
            arguments,
            classification=classification,
            timeout_seconds=timeout_seconds,
            overflow_mode=_BoundedOverflowMode.STOP_IMMEDIATELY,
        )
        if outcome.kind is _BoundedProcessOutcomeKind.SUCCESS:
            assert outcome.output is not None
            return outcome.output
        if outcome.kind is _BoundedProcessOutcomeKind.OUTPUT_INVALID:
            raise _ProcessEvidenceInvalid("DOCKER_BUILDER_SELECTION_PROCESS_FAILED") from None
        raise RuntimeError("DOCKER_BUILDER_SELECTION_PROCESS_FAILED") from None


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
    snapshot: BuilderPrestateSnapshot


@dataclass(frozen=True)
class _DiagnosticPrestate:
    source_commit: str
    host_identity: _HostIdentity
    docker_environment_identity: tuple[str, str, str, str]
    current_context: str = field(repr=False)
    snapshot: BuilderPrestateSnapshot


@dataclass(frozen=True)
class _DesktopStatusPrestate:
    source_commit: str
    host_identity: _HostIdentity
    docker_environment_identity: tuple[str, str, str, str]
    current_context: str = field(repr=False)


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
    plan_predicate: DockerBuilderSelectionPlanPredicate | None = None
    capture_snapshot: BuilderPrestateSnapshot | None = None
    buildx_version: BuildxVersionObservation | None = None
    context_default_phenotype_known: bool = False
    buildx_version_query_count: int = 0
    builder_inventory_query_count: int = 0
    daemon_probe_count: int = 0
    desktop_status_query_count: int = 0

    @property
    def mutation_count(self) -> int:
        return int(self.action_attempted) + int(self.rollback_attempted)

    def begin_prestate(self, checkpoint: BuilderSelectionPrestateCheckpoint) -> None:
        self.prestate_checkpoint = checkpoint


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


def _record_buildx_authority(runtime: _RuntimeState, executor: CapacityExecutor) -> None:
    runtime.buildx_version_query_count += 1
    try:
        raw = executor.output(
            ("docker", "buildx", "version"),
            classification=_BUILDX_VERSION_PROBE,
            timeout_seconds=10,
        )
    except Exception:
        _failure(BuilderSelectionReconcilePredicate.BUILDER_INVENTORY)
    runtime.buildx_version = observe_buildx_version(raw)


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
        evaluation = evaluate_docker_builder_selection_plan(
            raw,
            environ,
            current_context=current_context,
            version=runtime.buildx_version,
        )
    except DockerCapacityError:
        runtime.plan_predicate = DockerBuilderSelectionPlanPredicate.CURRENT_SELECTION_CONTRACT
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    runtime.plan_predicate = evaluation.snapshot.first_defect
    runtime.capture_snapshot = evaluation.snapshot
    if evaluation.plan is None:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    plan = evaluation.plan
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
        snapshot=evaluation.snapshot,
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
        evaluation = evaluate_docker_builder_selection_plan(
            raw,
            environ,
            current_context=current_context,
            version=runtime.buildx_version,
        )
    except DockerCapacityError:
        runtime.plan_predicate = DockerBuilderSelectionPlanPredicate.PLAN_DRIFT
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    if evaluation.snapshot != prestate.snapshot or evaluation.plan != prestate.plan:
        runtime.plan_predicate = DockerBuilderSelectionPlanPredicate.PLAN_DRIFT
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    runtime.plan_predicate = DockerBuilderSelectionPlanPredicate.PASS


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
    snapshot = runtime.capture_snapshot
    plan = runtime.plan_predicate
    prestate_known = plan is not None and runtime.prestate_checkpoint is not None
    prior_known = bool(
        snapshot is not None
        and snapshot.prior_driver is not PriorDriverPredicate.UNKNOWN
        and plan
        in {
            DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER,
            DockerBuilderSelectionPlanPredicate.PRIOR_STATUS,
            DockerBuilderSelectionPlanPredicate.TARGET_MISSING,
            DockerBuilderSelectionPlanPredicate.TARGET_DRIVER,
            DockerBuilderSelectionPlanPredicate.TARGET_STATUS,
            DockerBuilderSelectionPlanPredicate.TARGET_NODE_NAME,
            DockerBuilderSelectionPlanPredicate.TARGET_ENDPOINT,
            DockerBuilderSelectionPlanPredicate.TARGET_CURRENT,
            DockerBuilderSelectionPlanPredicate.PLAN_DRIFT,
            DockerBuilderSelectionPlanPredicate.PASS,
        }
    )
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
        prestate_predicate=plan if prestate_known else None,
        builder_selection_predicate=(
            snapshot.builder_selection if prestate_known and snapshot is not None else None
        ),
        node_schema_predicate=(
            snapshot.node_schema if prestate_known and snapshot is not None else None
        ),
        prior_driver_known=prior_known,
        prior_driver_predicate=snapshot.prior_driver
        if prior_known and snapshot is not None
        else None,
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
            and runtime.plan_predicate not in {None, DockerBuilderSelectionPlanPredicate.PASS}
            else BuilderSelectionReconcilePredicate.UNKNOWN
        )
        return _evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=predicate,
        )


def _capture_diagnostic_prestate(
    runtime: _RuntimeState,
    *,
    root: Path,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> _DiagnosticPrestate:
    source_commit = _source_identity(executor)
    host_identity = _host_identity(root)
    if environ.get("BUILDKIT_HOST", "").strip() or environ.get("BUILDX_BUILDER", "").strip():
        _failure(BuilderSelectionReconcilePredicate.ENVIRONMENT_OVERRIDE)
    try:
        current_context = require_local_unix_docker_context(executor, environ)
        runtime.builder_inventory_query_count += 1
        evaluation = evaluate_docker_builder_selection_plan(
            _builder_listing(executor),
            environ,
            current_context=current_context,
            version=runtime.buildx_version,
        )
    except DockerCapacityError:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    runtime.prestate_checkpoint = BuilderSelectionPrestateCheckpoint.CAPTURE
    runtime.capture_snapshot = evaluation.snapshot
    runtime.plan_predicate = evaluation.snapshot.first_defect
    return _DiagnosticPrestate(
        source_commit,
        host_identity,
        (
            environ.get("BUILDKIT_HOST", ""),
            environ.get("BUILDX_BUILDER", ""),
            environ.get("DOCKER_HOST", ""),
            environ.get("DOCKER_CONTEXT", ""),
        ),
        current_context,
        evaluation.snapshot,
    )


def _reprove_diagnostic_prestate(
    runtime: _RuntimeState,
    prestate: _DiagnosticPrestate,
    *,
    root: Path,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> None:
    if _source_identity(executor) != prestate.source_commit or _host_identity(root) != (
        prestate.host_identity
    ):
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    environment_identity = tuple(
        environ.get(key, "")
        for key in ("BUILDKIT_HOST", "BUILDX_BUILDER", "DOCKER_HOST", "DOCKER_CONTEXT")
    )
    if environment_identity != prestate.docker_environment_identity:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    try:
        current_context = require_local_unix_docker_context(executor, environ)
        runtime.builder_inventory_query_count += 1
        evaluation = evaluate_docker_builder_selection_plan(
            _builder_listing(executor),
            environ,
            current_context=current_context,
            version=runtime.buildx_version,
        )
    except DockerCapacityError:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    if current_context != prestate.current_context or evaluation.snapshot != prestate.snapshot:
        runtime.plan_predicate = DockerBuilderSelectionPlanPredicate.PLAN_DRIFT
        runtime.prestate_checkpoint = BuilderSelectionPrestateCheckpoint.REPROOF
    elif prestate.snapshot.first_defect is DockerBuilderSelectionPlanPredicate.PASS:
        runtime.plan_predicate = DockerBuilderSelectionPlanPredicate.PASS
        runtime.prestate_checkpoint = BuilderSelectionPrestateCheckpoint.REPROOF


def _diagnostic_evidence_from_runtime(
    runtime: _RuntimeState,
    *,
    classification: BuilderSelectionReconcileClassification,
    predicate: BuilderSelectionReconcilePredicate,
) -> BuilderSelectionPrestateDiagnosticEvidence:
    observation = runtime.capture_snapshot
    plan = runtime.plan_predicate if observation is not None else None
    return BuilderSelectionPrestateDiagnosticEvidence(
        classification=classification,
        predicate=predicate,
        prestate_known=observation is not None,
        prestate_checkpoint=runtime.prestate_checkpoint if observation is not None else None,
        prestate_predicate=plan,
        observation_known=observation is not None,
        observation=observation,
    )


def _run_prestate_diagnostic_under_lock(
    runtime: _RuntimeState,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> BuilderSelectionPrestateDiagnosticEvidence:
    del lock
    _record_buildx_authority(runtime, executor)
    prestate = _capture_diagnostic_prestate(
        runtime,
        root=root,
        executor=executor,
        environ=environ,
    )
    _reprove_diagnostic_prestate(
        runtime,
        prestate,
        root=root,
        executor=executor,
        environ=environ,
    )
    snapshot = runtime.capture_snapshot
    assert snapshot is not None
    if snapshot.buildx_authority is BuildxAuthorityPredicate.OUTPUT_INVALID:
        return _diagnostic_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=BuilderSelectionReconcilePredicate.UNKNOWN,
        )
    if runtime.plan_predicate is DockerBuilderSelectionPlanPredicate.PLAN_DRIFT or (
        snapshot.first_defect is not DockerBuilderSelectionPlanPredicate.PASS
    ):
        return _diagnostic_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.REJECTED,
            predicate=BuilderSelectionReconcilePredicate.PRESTATE,
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


def _context_default_phenotype_matches(snapshot: BuilderPrestateSnapshot) -> bool:
    return (
        snapshot.first_defect is DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER
        and snapshot.prior_driver is PriorDriverPredicate.EMPTY
        and snapshot.builder_error is BuilderErrorPredicate.PRESENT
        and snapshot.prior_target_relation is PriorTargetRelationPredicate.SAME
        and snapshot.target_contract is TargetContractPredicate.DRIVER
    )


def _probe_context_default_daemon(
    runtime: _RuntimeState,
    executor: _ContextDefaultProcessExecutor,
) -> ContextDefaultBuilderPreflightPredicate | None:
    runtime.daemon_probe_count += 1
    outcome = executor.bounded_outcome(
        _DAEMON_VERSION_ARGUMENTS,
        classification=_DAEMON_VERSION_PROBE,
        timeout_seconds=10,
    )
    if outcome.kind is _BoundedProcessOutcomeKind.INTERNAL_FAILURE:
        return None
    if outcome.kind in {
        _BoundedProcessOutcomeKind.REAPED_NONZERO,
        _BoundedProcessOutcomeKind.REAPED_TIMEOUT,
    }:
        return ContextDefaultBuilderPreflightPredicate.DAEMON_API_UNAVAILABLE
    if outcome.kind is _BoundedProcessOutcomeKind.OUTPUT_INVALID:
        return ContextDefaultBuilderPreflightPredicate.DAEMON_EVIDENCE_INVALID
    output = outcome.output
    if (
        type(output) is not str
        or len(output.encode("utf-8")) > _MAXIMUM_DAEMON_VERSION_BYTES
        or _DAEMON_VERSION_LINE.fullmatch(output) is None
    ):
        return ContextDefaultBuilderPreflightPredicate.DAEMON_EVIDENCE_INVALID
    return ContextDefaultBuilderPreflightPredicate.BUILDX_DEFAULT_UNRESOLVED


def _context_default_evidence_from_runtime(
    runtime: _RuntimeState,
    *,
    classification: BuilderSelectionReconcileClassification,
    predicate: ContextDefaultBuilderPreflightPredicate,
) -> ContextDefaultBuilderPreflightEvidence:
    return ContextDefaultBuilderPreflightEvidence(
        classification=classification,
        predicate=predicate,
        phenotype_known=runtime.context_default_phenotype_known,
        buildx_version_query_count=runtime.buildx_version_query_count,
        builder_inventory_query_count=runtime.builder_inventory_query_count,
        daemon_probe_count=runtime.daemon_probe_count,
    )


def _run_context_default_builder_preflight_under_lock(
    runtime: _RuntimeState,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: _ContextDefaultProcessExecutor,
    environ: Mapping[str, str],
) -> ContextDefaultBuilderPreflightEvidence:
    del lock
    _record_buildx_authority(runtime, executor)
    prestate = _capture_diagnostic_prestate(
        runtime,
        root=root,
        executor=executor,
        environ=environ,
    )
    if not _context_default_phenotype_matches(prestate.snapshot):
        return _context_default_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.REJECTED,
            predicate=ContextDefaultBuilderPreflightPredicate.PRESTATE_DRIFT,
        )
    runtime.context_default_phenotype_known = True
    probe_predicate = _probe_context_default_daemon(runtime, executor)
    if probe_predicate is None:
        return _context_default_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=ContextDefaultBuilderPreflightPredicate.UNKNOWN,
        )
    _reprove_diagnostic_prestate(
        runtime,
        prestate,
        root=root,
        executor=executor,
        environ=environ,
    )
    if runtime.plan_predicate is DockerBuilderSelectionPlanPredicate.PLAN_DRIFT:
        probe_predicate = ContextDefaultBuilderPreflightPredicate.PRESTATE_DRIFT
    return _context_default_evidence_from_runtime(
        runtime,
        classification=BuilderSelectionReconcileClassification.REJECTED,
        predicate=probe_predicate,
    )


def _run_context_default_builder_preflight(
    runtime: _RuntimeState,
    *,
    root: Path = ROOT,
    executor: _ContextDefaultProcessExecutor | None = None,
    environ: Mapping[str, str] | None = None,
) -> ContextDefaultBuilderPreflightEvidence:
    command_executor = executor or _BoundedProcessExecutor()
    selected_environment = os.environ if environ is None else environ
    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        return _context_default_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=ContextDefaultBuilderPreflightPredicate.UNKNOWN,
        )
    try:
        with exclusive_docker_workflow_lock(root) as lock:
            try:
                return _run_context_default_builder_preflight_under_lock(
                    runtime,
                    root=root,
                    lock=lock,
                    executor=command_executor,
                    environ=selected_environment,
                )
            except _ReconcileFailure:
                return _context_default_evidence_from_runtime(
                    runtime,
                    classification=BuilderSelectionReconcileClassification.REJECTED,
                    predicate=ContextDefaultBuilderPreflightPredicate.PRESTATE_DRIFT,
                )
    except BaseException:
        return _context_default_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=ContextDefaultBuilderPreflightPredicate.UNKNOWN,
        )


def _unique_json_mapping(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("DOCKER_DESKTOP_STATUS_JSON_DUPLICATE")
        document[key] = value
    return document


def _reject_nonstandard_json_constant(_value: str) -> NoReturn:
    raise ValueError("DOCKER_DESKTOP_STATUS_JSON_CONSTANT")


def _classify_desktop_status_document(
    output: str,
) -> DockerDesktopStatusPreflightPredicate:
    try:
        encoded = output.encode("utf-8")
    except UnicodeEncodeError:
        return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
    if len(encoded) > _MAXIMUM_DESKTOP_STATUS_BYTES:
        return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
    try:
        document = json.loads(
            output,
            object_pairs_hook=_unique_json_mapping,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (RecursionError, TypeError, ValueError):
        return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
    if type(document) is not dict or len(document) > _MAXIMUM_DESKTOP_STATUS_ENTRIES:
        return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
    semantic_tokens: list[str] = []
    lifecycle_ambiguous = False
    for value in document.values():
        if type(value) not in (str, int, float, bool, type(None)):
            return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
        if isinstance(value, float) and not math.isfinite(value):
            return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
        if type(value) is str:
            normalized_lifecycle = value.strip().lower()
            if normalized_lifecycle in _DESKTOP_STATUS_LIFECYCLE_TOKENS:
                if value in _DESKTOP_STATUS_SEMANTIC_TOKENS:
                    semantic_tokens.append(value)
                else:
                    lifecycle_ambiguous = True
    if lifecycle_ambiguous or len(semantic_tokens) != 1:
        return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
    semantic_token = semantic_tokens[0]
    if semantic_token == "running":  # noqa: S105 - documented fixed lifecycle state.
        return DockerDesktopStatusPreflightPredicate.RUNNING
    if semantic_token == "stopped":  # noqa: S105 - documented fixed lifecycle state.
        return DockerDesktopStatusPreflightPredicate.STOPPED
    return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID


def _capture_desktop_status_prestate(
    *,
    root: Path,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> _DesktopStatusPrestate:
    source_commit = _source_identity(executor)
    host_identity = _host_identity(root)
    environment_identity = (
        environ.get("BUILDKIT_HOST", ""),
        environ.get("BUILDX_BUILDER", ""),
        environ.get("DOCKER_HOST", ""),
        environ.get("DOCKER_CONTEXT", ""),
    )
    if environment_identity[0].strip() or environment_identity[1].strip():
        _failure(BuilderSelectionReconcilePredicate.ENVIRONMENT_OVERRIDE)
    try:
        current_context = require_local_unix_docker_context(executor, environ)
    except DockerCapacityError:
        _failure(BuilderSelectionReconcilePredicate.DOCKER_CONTEXT)
    return _DesktopStatusPrestate(
        source_commit,
        host_identity,
        environment_identity,
        current_context,
    )


def _reprove_desktop_status_prestate(
    prestate: _DesktopStatusPrestate,
    *,
    root: Path,
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> None:
    if _source_identity(executor) != prestate.source_commit or _host_identity(root) != (
        prestate.host_identity
    ):
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    environment_identity = (
        environ.get("BUILDKIT_HOST", ""),
        environ.get("BUILDX_BUILDER", ""),
        environ.get("DOCKER_HOST", ""),
        environ.get("DOCKER_CONTEXT", ""),
    )
    if environment_identity != prestate.docker_environment_identity:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    try:
        current_context = require_local_unix_docker_context(executor, environ)
    except DockerCapacityError:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)
    if current_context != prestate.current_context:
        _failure(BuilderSelectionReconcilePredicate.PRESTATE)


def _probe_docker_desktop_status(
    runtime: _RuntimeState,
    executor: _ContextDefaultProcessExecutor,
) -> DockerDesktopStatusPreflightPredicate | None:
    runtime.desktop_status_query_count += 1
    outcome = executor.bounded_outcome(
        _DESKTOP_STATUS_ARGUMENTS,
        classification=_DESKTOP_STATUS_PROBE,
        timeout_seconds=10,
    )
    if outcome.kind is _BoundedProcessOutcomeKind.INTERNAL_FAILURE:
        return None
    if outcome.kind in {
        _BoundedProcessOutcomeKind.REAPED_NONZERO,
        _BoundedProcessOutcomeKind.REAPED_TIMEOUT,
    }:
        return DockerDesktopStatusPreflightPredicate.STATUS_UNAVAILABLE
    if outcome.kind is _BoundedProcessOutcomeKind.OUTPUT_INVALID:
        return DockerDesktopStatusPreflightPredicate.STATUS_EVIDENCE_INVALID
    assert outcome.output is not None
    return _classify_desktop_status_document(outcome.output)


def _desktop_status_evidence_from_runtime(
    runtime: _RuntimeState,
    *,
    classification: BuilderSelectionReconcileClassification,
    predicate: DockerDesktopStatusPreflightPredicate,
) -> DockerDesktopStatusPreflightEvidence:
    return DockerDesktopStatusPreflightEvidence(
        classification=classification,
        predicate=predicate,
        desktop_status_query_count=runtime.desktop_status_query_count,
    )


def _run_docker_desktop_status_preflight_under_lock(
    runtime: _RuntimeState,
    *,
    root: Path,
    lock: DockerWorkflowLock,
    executor: _ContextDefaultProcessExecutor,
    environ: Mapping[str, str],
) -> DockerDesktopStatusPreflightEvidence:
    del lock
    prestate = _capture_desktop_status_prestate(
        root=root,
        executor=executor,
        environ=environ,
    )
    predicate = _probe_docker_desktop_status(runtime, executor)
    if predicate is None:
        return _desktop_status_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=DockerDesktopStatusPreflightPredicate.UNKNOWN,
        )
    _reprove_desktop_status_prestate(
        prestate,
        root=root,
        executor=executor,
        environ=environ,
    )
    return _desktop_status_evidence_from_runtime(
        runtime,
        classification=BuilderSelectionReconcileClassification.REJECTED,
        predicate=predicate,
    )


def _run_docker_desktop_status_preflight(
    runtime: _RuntimeState,
    *,
    root: Path = ROOT,
    executor: _ContextDefaultProcessExecutor | None = None,
    environ: Mapping[str, str] | None = None,
) -> DockerDesktopStatusPreflightEvidence:
    command_executor = executor or _BoundedProcessExecutor()
    selected_environment = os.environ if environ is None else environ
    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        return _desktop_status_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=DockerDesktopStatusPreflightPredicate.UNKNOWN,
        )
    try:
        with exclusive_docker_workflow_lock(root) as lock:
            try:
                return _run_docker_desktop_status_preflight_under_lock(
                    runtime,
                    root=root,
                    lock=lock,
                    executor=command_executor,
                    environ=selected_environment,
                )
            except _ReconcileFailure:
                return _desktop_status_evidence_from_runtime(
                    runtime,
                    classification=BuilderSelectionReconcileClassification.REJECTED,
                    predicate=DockerDesktopStatusPreflightPredicate.PRESTATE_DRIFT,
                )
    except BaseException:
        return _desktop_status_evidence_from_runtime(
            runtime,
            classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
            predicate=DockerDesktopStatusPreflightPredicate.UNKNOWN,
        )


def main() -> int:
    runtime = _RuntimeState()
    arguments = tuple(sys.argv[1:])
    if arguments == ("--diagnostic-phase", _DESKTOP_STATUS_PREFLIGHT_PHASE):
        try:
            status = _run_docker_desktop_status_preflight(runtime)
        except BaseException:
            status = _desktop_status_evidence_from_runtime(
                runtime,
                classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
                predicate=DockerDesktopStatusPreflightPredicate.UNKNOWN,
            )
        print(format_docker_desktop_status_preflight(status), flush=True)
        return 2
    if arguments == ("--diagnostic-phase", _CONTEXT_DEFAULT_PREFLIGHT_PHASE):
        try:
            preflight = _run_context_default_builder_preflight(runtime)
        except BaseException:
            preflight = _context_default_evidence_from_runtime(
                runtime,
                classification=BuilderSelectionReconcileClassification.OPERATOR_REVIEW_REQUIRED,
                predicate=ContextDefaultBuilderPreflightPredicate.UNKNOWN,
            )
        print(format_context_default_builder_preflight(preflight), flush=True)
        return 2
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
