"""Pure, value-free Docker builder prestate observation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_MAXIMUM_VERSION_BYTES = 256
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}$")
_REVISION = re.compile(r"^[0-9a-f]{7,64}$")
_RELEASE = re.compile(
    r"^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:alpha|beta|rc)[0-9]+)?$"
)
_DESKTOP = re.compile(
    r"^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"-desktop\.[1-9][0-9]*$"
)
_UPSTREAM_MODULE = "github.com/docker/buildx"


class BuilderSelectionPredicate(StrEnum):
    EXTERNAL_BUILDKIT_HOST = "EXTERNAL_BUILDKIT_HOST"
    LIST_JSON = "LIST_JSON"
    ROW_SCHEMA = "ROW_SCHEMA"
    NODE_COUNT = "NODE_COUNT"
    NODE_SCHEMA = "NODE_SCHEMA"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    CURRENT_MISSING = "CURRENT_MISSING"
    CURRENT_AMBIGUOUS = "CURRENT_AMBIGUOUS"
    OVERRIDE_INVALID = "OVERRIDE_INVALID"
    OVERRIDE_NOT_CURRENT = "OVERRIDE_NOT_CURRENT"
    DRIVER_NOT_DOCKER = "DRIVER_NOT_DOCKER"
    NODE_NOT_RUNNING = "NODE_NOT_RUNNING"
    BUILDER_CONTEXT_MISMATCH = "BUILDER_CONTEXT_MISMATCH"
    NODE_NAME_MISMATCH = "NODE_NAME_MISMATCH"
    ENDPOINT_CONTEXT_MISMATCH = "ENDPOINT_CONTEXT_MISMATCH"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


class NodeSchemaPredicate(StrEnum):
    NODE_NOT_MAPPING = "NODE_NOT_MAPPING"
    NAME_MISSING = "NAME_MISSING"
    NAME_NULL = "NAME_NULL"
    NAME_NOT_STRING = "NAME_NOT_STRING"
    ENDPOINT_MISSING = "ENDPOINT_MISSING"
    ENDPOINT_NULL = "ENDPOINT_NULL"
    ENDPOINT_NOT_STRING = "ENDPOINT_NOT_STRING"
    STATUS_NULL = "STATUS_NULL"
    STATUS_NOT_STRING = "STATUS_NOT_STRING"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


class DockerBuilderSelectionPlanPredicate(StrEnum):
    CURRENT_SELECTION_CONTRACT = "CURRENT_SELECTION_CONTRACT"
    CURRENT_ALREADY_CANONICAL = "CURRENT_ALREADY_CANONICAL"
    INVENTORY_DUPLICATE = "INVENTORY_DUPLICATE"
    CURRENT_COUNT = "CURRENT_COUNT"
    PRIOR_DRIVER = "PRIOR_DRIVER"
    PRIOR_STATUS = "PRIOR_STATUS"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_DRIVER = "TARGET_DRIVER"
    TARGET_STATUS = "TARGET_STATUS"
    TARGET_NODE_NAME = "TARGET_NODE_NAME"
    TARGET_ENDPOINT = "TARGET_ENDPOINT"
    TARGET_CURRENT = "TARGET_CURRENT"
    PLAN_DRIFT = "PLAN_DRIFT"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


class PriorDriverPredicate(StrEnum):
    EMPTY = "EMPTY"
    CLOUD = "CLOUD"
    KUBERNETES = "KUBERNETES"
    REMOTE = "REMOTE"
    UNRECOGNIZED = "UNRECOGNIZED"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


class BuilderErrorPredicate(StrEnum):
    ABSENT = "ABSENT"
    PRESENT = "PRESENT"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class BuildxAuthorityPredicate(StrEnum):
    UPSTREAM_V0_35_0 = "UPSTREAM_V0_35_0"
    UPSTREAM_OTHER = "UPSTREAM_OTHER"
    OTHER_DISTRIBUTION = "OTHER_DISTRIBUTION"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    UNKNOWN = "UNKNOWN"


class BuildxDistributionPredicate(StrEnum):
    DOCUMENTED_DESKTOP_SUFFIX = "DOCUMENTED_DESKTOP_SUFFIX"
    UPSTREAM_MODULE_NONRELEASE = "UPSTREAM_MODULE_NONRELEASE"
    OTHER_MODULE = "OTHER_MODULE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class PriorTargetRelationPredicate(StrEnum):
    SAME = "SAME"
    DISTINCT = "DISTINCT"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_MULTIPLE = "TARGET_MULTIPLE"
    UNKNOWN = "UNKNOWN"


class PriorStatusPredicate(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    EMPTY = "EMPTY"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class TargetContractPredicate(StrEnum):
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    MISSING = "MISSING"
    MULTIPLE = "MULTIPLE"
    DRIVER = "DRIVER"
    STATUS = "STATUS"
    NODE_NAME = "NODE_NAME"
    ENDPOINT = "ENDPOINT"
    UNKNOWN = "UNKNOWN"


class BuilderDriverKind(StrEnum):
    DOCKER = "DOCKER"
    DOCKER_CONTAINER = "DOCKER_CONTAINER"
    EMPTY = "EMPTY"
    CLOUD = "CLOUD"
    KUBERNETES = "KUBERNETES"
    REMOTE = "REMOTE"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class BuilderPrestateRow:
    current: bool
    driver: BuilderDriverKind
    status: PriorStatusPredicate
    name_is_context: bool
    node_name_is_builder: bool
    node_name_is_context: bool
    endpoint_is_context: bool
    builder_error: BuilderErrorPredicate
    node_error: BuilderErrorPredicate = BuilderErrorPredicate.ABSENT


_Rows = tuple[BuilderPrestateRow, ...]


@dataclass(frozen=True, slots=True)
class BuilderPrestateSnapshot:
    buildx_authority: BuildxAuthorityPredicate
    buildx_distribution: BuildxDistributionPredicate
    builder_selection: BuilderSelectionPredicate
    node_schema: NodeSchemaPredicate
    prior_driver: PriorDriverPredicate
    builder_error: BuilderErrorPredicate
    prior_target_relation: PriorTargetRelationPredicate
    prior_status: PriorStatusPredicate
    prior_node_error: BuilderErrorPredicate
    target_contract: TargetContractPredicate
    first_defect: DockerBuilderSelectionPlanPredicate


@dataclass(frozen=True, slots=True)
class BuildxVersionObservation:
    authority: BuildxAuthorityPredicate
    distribution: BuildxDistributionPredicate


def observe_buildx_version(raw: str) -> BuildxVersionObservation:
    invalid = BuildxVersionObservation(
        BuildxAuthorityPredicate.OUTPUT_INVALID,
        BuildxDistributionPredicate.NOT_APPLICABLE,
    )
    if len(raw.encode("utf-8")) > _MAXIMUM_VERSION_BYTES:
        return invalid
    line = raw[:-1] if raw.endswith("\n") else raw
    if "\n" in line or "\r" in line:
        return invalid
    fields = line.split(" ")
    desktop = BuildxVersionObservation(
        BuildxAuthorityPredicate.OTHER_DISTRIBUTION,
        BuildxDistributionPredicate.DOCUMENTED_DESKTOP_SUFFIX,
    )
    if len(fields) == 2:
        return desktop if fields[0] == "buildx" and _DESKTOP.fullmatch(fields[1]) else invalid
    if len(fields) != 3 or not all(_TOKEN.fullmatch(value) for value in fields[:2]):
        return invalid
    module, version, revision = fields
    if _REVISION.fullmatch(revision) is None:
        return invalid
    if _DESKTOP.fullmatch(version):
        return desktop
    if module == _UPSTREAM_MODULE and version == "v0.35.0":
        authority = BuildxAuthorityPredicate.UPSTREAM_V0_35_0
    elif module == _UPSTREAM_MODULE and _RELEASE.fullmatch(version):
        authority = BuildxAuthorityPredicate.UPSTREAM_OTHER
    else:
        distribution = (
            BuildxDistributionPredicate.OTHER_MODULE
            if module != _UPSTREAM_MODULE
            else BuildxDistributionPredicate.UPSTREAM_MODULE_NONRELEASE
        )
        return BuildxVersionObservation(BuildxAuthorityPredicate.OTHER_DISTRIBUTION, distribution)
    return BuildxVersionObservation(authority, BuildxDistributionPredicate.NOT_APPLICABLE)


def _selection_predicate(rows: _Rows) -> BuilderSelectionPredicate:
    current = tuple(row for row in rows if row.current)
    if not current:
        return BuilderSelectionPredicate.CURRENT_MISSING
    if len(current) > 1:
        return BuilderSelectionPredicate.CURRENT_AMBIGUOUS
    selected = current[0]
    if selected.driver is not BuilderDriverKind.DOCKER:
        return BuilderSelectionPredicate.DRIVER_NOT_DOCKER
    if selected.status is not PriorStatusPredicate.RUNNING:
        return BuilderSelectionPredicate.NODE_NOT_RUNNING
    if not selected.name_is_context:
        return BuilderSelectionPredicate.BUILDER_CONTEXT_MISMATCH
    if not selected.node_name_is_builder:
        return BuilderSelectionPredicate.NODE_NAME_MISMATCH
    if not selected.endpoint_is_context:
        return BuilderSelectionPredicate.ENDPOINT_CONTEXT_MISMATCH
    return BuilderSelectionPredicate.PASS


def _prior_driver(row: BuilderPrestateRow | None) -> PriorDriverPredicate:
    if row is None:
        return PriorDriverPredicate.UNKNOWN
    return {
        BuilderDriverKind.DOCKER_CONTAINER: PriorDriverPredicate.PASS,
        BuilderDriverKind.EMPTY: PriorDriverPredicate.EMPTY,
        BuilderDriverKind.CLOUD: PriorDriverPredicate.CLOUD,
        BuilderDriverKind.KUBERNETES: PriorDriverPredicate.KUBERNETES,
        BuilderDriverKind.REMOTE: PriorDriverPredicate.REMOTE,
    }.get(row.driver, PriorDriverPredicate.UNRECOGNIZED)


def _relation(rows: _Rows, target_count: int) -> PriorTargetRelationPredicate:
    current = tuple(row for row in rows if row.current)
    targets = tuple(row for row in rows if row.name_is_context)
    if target_count == 0:
        return PriorTargetRelationPredicate.TARGET_MISSING
    if target_count > 1:
        return PriorTargetRelationPredicate.TARGET_MULTIPLE
    if len(current) != 1:
        return PriorTargetRelationPredicate.UNKNOWN
    return (
        PriorTargetRelationPredicate.SAME
        if current[0] is targets[0]
        else PriorTargetRelationPredicate.DISTINCT
    )


def _target_contract(rows: _Rows, target_count: int) -> TargetContractPredicate:
    targets = tuple(row for row in rows if row.name_is_context)
    if target_count == 0:
        return TargetContractPredicate.MISSING
    if target_count > 1:
        return TargetContractPredicate.MULTIPLE
    target = targets[0]
    if target.driver is not BuilderDriverKind.DOCKER:
        return TargetContractPredicate.DRIVER
    if target.status is not PriorStatusPredicate.RUNNING:
        return TargetContractPredicate.STATUS
    if not target.node_name_is_context:
        return TargetContractPredicate.NODE_NAME
    if not target.endpoint_is_context:
        return TargetContractPredicate.ENDPOINT
    return TargetContractPredicate.PASS


def observe_builder_prestate(
    rows: _Rows,
    *,
    row_count: int,
    context_target_count: int | None = None,
    version: BuildxVersionObservation | None = None,
) -> BuilderPrestateSnapshot:
    selection = _selection_predicate(rows)
    current = tuple(row for row in rows if row.current)
    target_count = (
        sum(row.name_is_context for row in rows)
        if context_target_count is None
        else context_target_count
    )
    prior = current[0] if len(current) == 1 else None
    prior_driver = _prior_driver(prior)
    first_defect = DockerBuilderSelectionPlanPredicate.CURRENT_SELECTION_CONTRACT
    if selection is BuilderSelectionPredicate.PASS:
        first_defect = DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL
    elif row_count != len(rows):
        first_defect = DockerBuilderSelectionPlanPredicate.INVENTORY_DUPLICATE
    elif len(current) != 1:
        first_defect = DockerBuilderSelectionPlanPredicate.CURRENT_COUNT
    elif not (
        selection is BuilderSelectionPredicate.DRIVER_NOT_DOCKER
        or (
            selection is BuilderSelectionPredicate.NODE_NOT_RUNNING
            and prior_driver is PriorDriverPredicate.PASS
        )
    ):
        first_defect = DockerBuilderSelectionPlanPredicate.CURRENT_SELECTION_CONTRACT
    elif prior_driver is not PriorDriverPredicate.PASS:
        first_defect = DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER
    elif prior is not None and prior.status is not PriorStatusPredicate.RUNNING:
        first_defect = DockerBuilderSelectionPlanPredicate.PRIOR_STATUS
    else:
        target_contract = _target_contract(rows, target_count)
        target_name = target_contract.name
        if target_name in {"MISSING", "MULTIPLE"}:
            target_name = "MISSING"
        if target_name != "PASS":
            target_name = f"TARGET_{target_name}"
        first_defect = DockerBuilderSelectionPlanPredicate(target_name)
        targets = tuple(row for row in rows if row.name_is_context)
        if first_defect is DockerBuilderSelectionPlanPredicate.PASS and targets[0].current:
            first_defect = DockerBuilderSelectionPlanPredicate.TARGET_CURRENT
    authority = version or BuildxVersionObservation(
        BuildxAuthorityPredicate.UNKNOWN,
        BuildxDistributionPredicate.NOT_APPLICABLE,
    )
    return BuilderPrestateSnapshot(
        buildx_authority=authority.authority,
        buildx_distribution=authority.distribution,
        builder_selection=selection,
        node_schema=NodeSchemaPredicate.PASS,
        prior_driver=prior_driver,
        builder_error=(prior.builder_error if prior is not None else BuilderErrorPredicate.UNKNOWN),
        prior_target_relation=_relation(rows, target_count),
        prior_status=(prior.status if prior is not None else PriorStatusPredicate.UNKNOWN),
        prior_node_error=(prior.node_error if prior is not None else BuilderErrorPredicate.UNKNOWN),
        target_contract=_target_contract(rows, target_count),
        first_defect=first_defect,
    )
