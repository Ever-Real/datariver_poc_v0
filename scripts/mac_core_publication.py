"""Pure contracts for Mac Level1+Level2 publication and optional integration impact."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class PublicationCategory(StrEnum):
    LEVEL1 = "LEVEL1"
    LEVEL2_REDIS = "LEVEL2_REDIS"
    LEVEL2_GRAPH = "LEVEL2_GRAPH"
    LEVEL2_GATEWAY = "LEVEL2_GATEWAY"
    OPTIONAL_DATAHUB = "OPTIONAL_DATAHUB"
    OPTIONAL_AIRFLOW = "OPTIONAL_AIRFLOW"
    OPTIONAL_STORAGE = "OPTIONAL_STORAGE"
    OPTIONAL_LOCAL_LLM_OBSERVABILITY = "OPTIONAL_LOCAL_LLM_OBSERVABILITY"
    OPERATOR_ONLY = "OPERATOR_ONLY"
    UNKNOWN = "UNKNOWN"


_EXACT_PATH_CATEGORIES: dict[str, tuple[PublicationCategory, ...]] = {
    "AGENTS.md": (PublicationCategory.OPERATOR_ONLY,),
    "README.md": (PublicationCategory.OPERATOR_ONLY,),
    "pyproject.toml": (PublicationCategory.LEVEL1,),
    "uv.lock": (PublicationCategory.LEVEL1,),
    "backend/Dockerfile": (PublicationCategory.LEVEL1,),
    "frontend/Dockerfile": (PublicationCategory.LEVEL1,),
    "frontend/package.json": (PublicationCategory.LEVEL1,),
    "frontend/package-lock.json": (PublicationCategory.LEVEL1,),
    "compose.yaml": (PublicationCategory.LEVEL1,),
    "compose.identity.yaml": (PublicationCategory.LEVEL1,),
    "compose.host-dev.yaml": (PublicationCategory.LEVEL1,),
    "compose.graph.yaml": (PublicationCategory.LEVEL2_GRAPH,),
    "compose.gateway.yaml": (PublicationCategory.LEVEL2_GATEWAY,),
    "compose.gateway-routing.yaml": (PublicationCategory.LEVEL2_GATEWAY,),
    "compose.gateway.host-dev.yaml": (PublicationCategory.LEVEL2_GATEWAY,),
    "compose.local-connectors.yaml": (
        PublicationCategory.LEVEL2_REDIS,
        PublicationCategory.OPTIONAL_STORAGE,
    ),
    "compose.airflow.yaml": (PublicationCategory.OPTIONAL_AIRFLOW,),
    "compose.airflow.host-dev.yaml": (PublicationCategory.OPTIONAL_AIRFLOW,),
    "infra/contracts/datahub-v1.6.0-images.json": (PublicationCategory.OPTIONAL_DATAHUB,),
    "infra/postgres/init-airflow.sh": (PublicationCategory.OPTIONAL_AIRFLOW,),
    "scripts/development_cycle.py": (PublicationCategory.OPERATOR_ONLY,),
    "scripts/mac_core_publication.py": (PublicationCategory.OPERATOR_ONLY,),
    "scripts/platform_workflow.py": (PublicationCategory.OPERATOR_ONLY,),
    "scripts/start_datahub_mac_dev.sh": (PublicationCategory.OPTIONAL_DATAHUB,),
    "scripts/verify_datahub_contract.py": (PublicationCategory.OPTIONAL_DATAHUB,),
    "scripts/verify_datahub_image_inventory.py": (PublicationCategory.OPTIONAL_DATAHUB,),
    "scripts/local_reranker_service.py": (PublicationCategory.OPTIONAL_LOCAL_LLM_OBSERVABILITY,),
    "scripts/verify_static.py": (PublicationCategory.OPERATOR_ONLY,),
    "scripts/workflow_update_restart.py": (PublicationCategory.OPERATOR_ONLY,),
}

_PREFIX_CATEGORIES: tuple[tuple[str, tuple[PublicationCategory, ...]], ...] = (
    (
        "backend/src/datariver/infrastructure/cache/",
        (PublicationCategory.LEVEL1, PublicationCategory.LEVEL2_REDIS),
    ),
    (
        "backend/src/datariver/infrastructure/knowledge/neo4j",
        (PublicationCategory.LEVEL1, PublicationCategory.LEVEL2_GRAPH),
    ),
    (
        "backend/src/datariver/infrastructure/datahub/",
        (PublicationCategory.LEVEL1, PublicationCategory.OPTIONAL_DATAHUB),
    ),
    (
        "backend/src/datariver/infrastructure/object_store/",
        (PublicationCategory.LEVEL1, PublicationCategory.OPTIONAL_STORAGE),
    ),
    (
        "backend/src/datariver/infrastructure/llm/",
        (PublicationCategory.LEVEL1, PublicationCategory.OPTIONAL_LOCAL_LLM_OBSERVABILITY),
    ),
    (
        "backend/src/datariver/infrastructure/observability/",
        (PublicationCategory.LEVEL1, PublicationCategory.OPTIONAL_LOCAL_LLM_OBSERVABILITY),
    ),
    ("backend/src/", (PublicationCategory.LEVEL1,)),
    ("backend/alembic/", (PublicationCategory.LEVEL1,)),
    ("frontend/", (PublicationCategory.LEVEL1,)),
    ("infra/apisix/", (PublicationCategory.LEVEL2_GATEWAY,)),
    ("infra/neo4j/", (PublicationCategory.LEVEL2_GRAPH,)),
    ("infra/datahub/", (PublicationCategory.OPTIONAL_DATAHUB,)),
    ("infra/airflow/", (PublicationCategory.OPTIONAL_AIRFLOW,)),
    ("infra/minio/", (PublicationCategory.OPTIONAL_STORAGE,)),
    (
        "infra/observability/",
        (PublicationCategory.OPTIONAL_LOCAL_LLM_OBSERVABILITY,),
    ),
    ("infra/keycloak/", (PublicationCategory.LEVEL1,)),
    ("infra/postgres/", (PublicationCategory.LEVEL1,)),
    ("backend/tests/", (PublicationCategory.OPERATOR_ONLY,)),
    ("docs/", (PublicationCategory.OPERATOR_ONLY,)),
    (".github/", (PublicationCategory.OPERATOR_ONLY,)),
)


@dataclass(frozen=True, slots=True)
class PublicationTierPlan:
    core_paths: tuple[str, ...] = field(repr=False)
    categories: tuple[PublicationCategory, ...]

    @property
    def accepted(self) -> bool:
        return PublicationCategory.UNKNOWN not in self.categories


def _classify_path(path: str) -> tuple[PublicationCategory, ...]:
    exact = _EXACT_PATH_CATEGORIES.get(path)
    if exact is not None:
        return exact
    for prefix, matched in _PREFIX_CATEGORIES:
        if path.startswith(prefix):
            return matched
    return (PublicationCategory.UNKNOWN,)


def classify_publication_paths(paths: Sequence[str]) -> PublicationTierPlan:
    if any(not path or path.startswith("/") or "\n" in path or "\r" in path for path in paths):
        raise ValueError("PUBLICATION_PATH_INVALID")
    categories: list[PublicationCategory] = []
    core_paths: list[str] = []
    for path in paths:
        path_categories = _classify_path(path)
        categories.extend(path_categories)
        if any(category.value.startswith("LEVEL") for category in path_categories):
            core_paths.append(path)
    ordered = tuple(dict.fromkeys(categories))
    return PublicationTierPlan(tuple(core_paths), ordered)


class CoreServiceKey(StrEnum):
    LEVEL1_POSTGRES = "LEVEL1_POSTGRES"
    LEVEL1_KEYCLOAK = "LEVEL1_KEYCLOAK"
    LEVEL1_API = "LEVEL1_API"
    LEVEL1_WEB = "LEVEL1_WEB"
    LEVEL1_OUTBOX_RELAY = "LEVEL1_OUTBOX_RELAY"
    LEVEL1_UPLOAD_WORKER = "LEVEL1_UPLOAD_WORKER"
    LEVEL1_UPLOAD_VALIDATION_WORKER = "LEVEL1_UPLOAD_VALIDATION_WORKER"
    LEVEL1_GOVERNANCE_APPLY_WORKER = "LEVEL1_GOVERNANCE_APPLY_WORKER"
    LEVEL1_CATALOG_EXPORT_WORKER = "LEVEL1_CATALOG_EXPORT_WORKER"
    LEVEL1_GOVERNANCE_DOCUMENT_WORKER = "LEVEL1_GOVERNANCE_DOCUMENT_WORKER"
    LEVEL1_KNOWLEDGE_SOURCE_WORKER = "LEVEL1_KNOWLEDGE_SOURCE_WORKER"
    LEVEL1_KNOWLEDGE_INGESTION_WORKER = "LEVEL1_KNOWLEDGE_INGESTION_WORKER"
    LEVEL1_KNOWLEDGE_PROPOSAL_WORKER = "LEVEL1_KNOWLEDGE_PROPOSAL_WORKER"
    LEVEL1_QUALITY_WORKER = "LEVEL1_QUALITY_WORKER"
    LEVEL1_RETENTION_SCHEDULER = "LEVEL1_RETENTION_SCHEDULER"
    LEVEL1_RETENTION_ARCHIVE_WORKER = "LEVEL1_RETENTION_ARCHIVE_WORKER"
    LEVEL2_REDIS_CACHE = "LEVEL2_REDIS_CACHE"
    LEVEL2_REDIS_DELIVERY = "LEVEL2_REDIS_DELIVERY"
    LEVEL2_GRAPH = "LEVEL2_GRAPH"
    LEVEL2_GATEWAY = "LEVEL2_GATEWAY"


@dataclass(frozen=True, slots=True)
class CoreServiceSpec:
    key: CoreServiceKey
    project: str
    service: str
    health_required: bool
    environment_key: str | None = None


def _service(
    key: CoreServiceKey,
    service: str,
    *,
    health: bool = False,
    environment_key: str | None = None,
    project: str = "datariver-next",
) -> CoreServiceSpec:
    return CoreServiceSpec(key, project, service, health, environment_key)


_HEALTHCHECKED_BASE = {
    CoreServiceKey.LEVEL1_POSTGRES,
    CoreServiceKey.LEVEL1_KEYCLOAK,
    CoreServiceKey.LEVEL1_API,
    CoreServiceKey.LEVEL1_WEB,
}
_BASE_SERVICE_SPECS = tuple(
    _service(key, service, health=key in _HEALTHCHECKED_BASE)
    for key, service in (
        (CoreServiceKey.LEVEL1_POSTGRES, "postgres"),
        (CoreServiceKey.LEVEL1_KEYCLOAK, "keycloak"),
        (CoreServiceKey.LEVEL1_API, "api"),
        (CoreServiceKey.LEVEL1_WEB, "web"),
        (CoreServiceKey.LEVEL1_OUTBOX_RELAY, "outbox-relay"),
        (CoreServiceKey.LEVEL1_UPLOAD_WORKER, "upload-worker"),
        (CoreServiceKey.LEVEL1_UPLOAD_VALIDATION_WORKER, "upload-validation-worker"),
        (CoreServiceKey.LEVEL1_GOVERNANCE_APPLY_WORKER, "governance-apply-worker"),
    )
)

_ENVIRONMENT_SERVICE_SPECS = tuple(
    _service(key, service, environment_key=environment_key)
    for key, service, environment_key in (
        (
            CoreServiceKey.LEVEL1_CATALOG_EXPORT_WORKER,
            "catalog-export-worker",
            "CATALOG_EXPORT_WORKER_ENABLED",
        ),
        (
            CoreServiceKey.LEVEL1_GOVERNANCE_DOCUMENT_WORKER,
            "governance-document-worker",
            "GOVERNANCE_DOCUMENT_WORKER_ENABLED",
        ),
        (
            CoreServiceKey.LEVEL1_KNOWLEDGE_SOURCE_WORKER,
            "knowledge-source-worker",
            "KNOWLEDGE_SOURCE_WORKER_ENABLED",
        ),
        (
            CoreServiceKey.LEVEL1_KNOWLEDGE_INGESTION_WORKER,
            "knowledge-studio-ingestion-worker",
            "KNOWLEDGE_STUDIO_INGESTION_WORKER_ENABLED",
        ),
        (
            CoreServiceKey.LEVEL1_KNOWLEDGE_PROPOSAL_WORKER,
            "knowledge-tbox-proposal-worker",
            "KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED",
        ),
        (CoreServiceKey.LEVEL1_QUALITY_WORKER, "quality-worker", "QUALITY_WORKER_ENABLED"),
        (
            CoreServiceKey.LEVEL1_RETENTION_SCHEDULER,
            "retention-scheduler",
            "RETENTION_ARCHIVE_EXECUTION_ENABLED",
        ),
        (
            CoreServiceKey.LEVEL1_RETENTION_ARCHIVE_WORKER,
            "retention-archive-worker",
            "RETENTION_ARCHIVE_EXECUTION_ENABLED",
        ),
    )
)

_LEVEL2_SERVICE_SPECS = (
    _service(
        CoreServiceKey.LEVEL2_REDIS_CACHE,
        "redis-cache",
        health=True,
        project="datariver-local-connectors",
    ),
    _service(
        CoreServiceKey.LEVEL2_REDIS_DELIVERY,
        "redis-delivery",
        health=True,
        project="datariver-local-connectors",
    ),
    _service(CoreServiceKey.LEVEL2_GRAPH, "neo4j", health=True),
    _service(CoreServiceKey.LEVEL2_GATEWAY, "apisix", health=True),
)


def selected_core_service_specs(values: Mapping[str, str]) -> tuple[CoreServiceSpec, ...]:
    selected: list[CoreServiceSpec] = [*_BASE_SERVICE_SPECS]
    for spec in _ENVIRONMENT_SERVICE_SPECS:
        assert spec.environment_key is not None
        value = values.get(spec.environment_key, "false")
        if value not in {"true", "false"}:
            raise ValueError("LEVEL2_CORE_ENVIRONMENT_INVALID")
        if value == "true":
            selected.append(spec)
    return (*selected, *_LEVEL2_SERVICE_SPECS)


class CoreServiceCondition(StrEnum):
    ABSENT = "ABSENT"
    CREATED = "CREATED"
    RUNNING_NO_HEALTH = "RUNNING_NO_HEALTH"
    RUNNING_STARTING = "RUNNING_STARTING"
    RUNNING_HEALTHY = "RUNNING_HEALTHY"
    RUNNING_UNHEALTHY = "RUNNING_UNHEALTHY"
    PAUSED = "PAUSED"
    RESTARTING = "RESTARTING"
    REMOVING = "REMOVING"
    EXITED = "EXITED"
    DEAD = "DEAD"


@dataclass(frozen=True, slots=True)
class CoreServiceObservation:
    key: CoreServiceKey
    private_id: str | None = field(repr=False)
    condition: CoreServiceCondition

    def __post_init__(self) -> None:
        if (self.private_id is None) != (self.condition is CoreServiceCondition.ABSENT) or (
            self.private_id is not None and not re.fullmatch(r"[0-9a-f]{64}", self.private_id)
        ):
            raise ValueError("LEVEL2_CORE_OBSERVATION_INVALID")


class Level2CorePredicate(StrEnum):
    LEVEL2_ADOPTION_REQUIRED = "LEVEL2_ADOPTION_REQUIRED"
    LEVEL1_CONTRACT = "LEVEL1_CONTRACT"
    LEVEL2_CONTRACT = "LEVEL2_CONTRACT"
    PASS = "PASS"  # noqa: S105 - fixed evidence predicate, not a secret.


@dataclass(frozen=True, slots=True)
class Level2CoreProjection:
    predicate: Level2CorePredicate
    local_redis: bool
    local_graph: bool
    local_gateway: bool
    level1_pass: bool
    level1_first_defect: CoreServiceKey | None
    redis_cache: CoreServiceCondition
    redis_delivery: CoreServiceCondition
    graph: CoreServiceCondition
    gateway: CoreServiceCondition
    observed_count: int
    missing_count: int

    def __post_init__(self) -> None:
        level2_ready = all(
            value is CoreServiceCondition.RUNNING_HEALTHY
            for value in (self.redis_cache, self.redis_delivery, self.graph, self.gateway)
        )
        expected = (
            Level2CorePredicate.LEVEL2_ADOPTION_REQUIRED
            if not (self.local_redis and self.local_graph and self.local_gateway)
            else Level2CorePredicate.LEVEL1_CONTRACT
            if not self.level1_pass
            else Level2CorePredicate.LEVEL2_CONTRACT
            if not level2_ready
            else Level2CorePredicate.PASS
        )
        if (
            any(
                type(value) is not bool
                for value in (
                    self.local_redis,
                    self.local_graph,
                    self.local_gateway,
                    self.level1_pass,
                )
            )
            or (self.level1_first_defect is None) != self.level1_pass
            or type(self.observed_count) is not int
            or type(self.missing_count) is not int
            or min(self.observed_count, self.missing_count) < 0
            or self.observed_count + self.missing_count < 12
            or self.predicate is not expected
        ):
            raise ValueError("LEVEL2_CORE_PROJECTION_INVALID")


@dataclass(frozen=True, slots=True)
class Level2CoreCapture:
    observations: tuple[CoreServiceObservation, ...]
    projection: Level2CoreProjection


class Level2CoreClassification(StrEnum):
    PASS = "PASS"  # noqa: S105 - fixed diagnostic classification, not a secret.
    REJECTED = "REJECTED"
    OPERATOR_REVIEW_REQUIRED = "OPERATOR_REVIEW_REQUIRED"


class Level2CoreDiagnosticPredicate(StrEnum):
    HOST_CONTRACT = "HOST_CONTRACT"
    SOURCE_CONTRACT = "SOURCE_CONTRACT"
    APPLIED_STATE_CONTRACT = "APPLIED_STATE_CONTRACT"
    ENVIRONMENT_FINGERPRINT = "ENVIRONMENT_FINGERPRINT"
    COMPOSE_CONTRACT = "COMPOSE_CONTRACT"
    QUERY = "QUERY"
    DOCKER_QUERY_UNAVAILABLE = "DOCKER_QUERY_UNAVAILABLE"
    QUERY_EVIDENCE_INVALID = "QUERY_EVIDENCE_INVALID"
    LEVEL2_ADOPTION_REQUIRED = "LEVEL2_ADOPTION_REQUIRED"
    LEVEL1_CONTRACT = "LEVEL1_CONTRACT"
    LEVEL2_CONTRACT = "LEVEL2_CONTRACT"
    PRESTATE_DRIFT = "PRESTATE_DRIFT"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Level2CoreEvidence:
    classification: Level2CoreClassification
    predicate: Level2CoreDiagnosticPredicate
    observation: Level2CoreProjection | None = None
    docker_query_count: int = 0
    action_count: int = 0
    mutation_count: int = 0
    retry_count: int = 0

    def __post_init__(self) -> None:
        observation_required = self.predicate in {
            Level2CoreDiagnosticPredicate.LEVEL2_ADOPTION_REQUIRED,
            Level2CoreDiagnosticPredicate.LEVEL1_CONTRACT,
            Level2CoreDiagnosticPredicate.LEVEL2_CONTRACT,
            Level2CoreDiagnosticPredicate.PRESTATE_DRIFT,
            Level2CoreDiagnosticPredicate.PASS,
        }
        if (
            type(self.docker_query_count) is not int
            or not 0 <= self.docker_query_count <= 44
            or any(
                type(value) is not int or value != 0
                for value in (self.action_count, self.mutation_count, self.retry_count)
            )
            or (
                self.classification is Level2CoreClassification.PASS
                and self.predicate is not Level2CoreDiagnosticPredicate.PASS
            )
            or (
                self.classification is Level2CoreClassification.REJECTED
                and self.predicate
                in {Level2CoreDiagnosticPredicate.PASS, Level2CoreDiagnosticPredicate.UNKNOWN}
            )
            or (
                self.classification is Level2CoreClassification.OPERATOR_REVIEW_REQUIRED
                and self.predicate is not Level2CoreDiagnosticPredicate.UNKNOWN
            )
            or (
                observation_required != (self.observation is not None)
                and self.predicate
                not in {
                    Level2CoreDiagnosticPredicate.DOCKER_QUERY_UNAVAILABLE,
                    Level2CoreDiagnosticPredicate.QUERY_EVIDENCE_INVALID,
                    Level2CoreDiagnosticPredicate.UNKNOWN,
                }
            )
            or (
                self.observation is not None
                and self.predicate
                not in {
                    Level2CoreDiagnosticPredicate.PRESTATE_DRIFT,
                    Level2CoreDiagnosticPredicate.DOCKER_QUERY_UNAVAILABLE,
                    Level2CoreDiagnosticPredicate.QUERY_EVIDENCE_INVALID,
                    Level2CoreDiagnosticPredicate.UNKNOWN,
                    Level2CoreDiagnosticPredicate(self.observation.predicate.value),
                }
            )
        ):
            raise ValueError("LEVEL2_CORE_EVIDENCE_INVALID")


def projection_diagnostic_predicate(
    value: Level2CoreProjection,
) -> Level2CoreDiagnosticPredicate:
    return Level2CoreDiagnosticPredicate(value.predicate.value)


def format_level2_core_evidence(value: Level2CoreEvidence) -> str:
    document: dict[str, object] = {
        "action_count": value.action_count,
        "classification": value.classification.value,
        "docker_query_count": value.docker_query_count,
        "mutation_count": value.mutation_count,
        "observation_known": value.observation is not None,
        "phase": "LEVEL2_CORE_PRESTATE",
        "predicate": value.predicate.value,
        "retry_count": value.retry_count,
        "schema": "DATARIVER_LEVEL2_CORE_PRESTATE_V1",
    }
    if value.observation is not None:
        observation = value.observation
        projected: dict[str, bool | int | str] = {
            "gateway": observation.gateway.value,
            "graph": observation.graph.value,
            "level1_first_defect_known": observation.level1_first_defect is not None,
            "level1_pass": observation.level1_pass,
            "local_gateway": observation.local_gateway,
            "local_graph": observation.local_graph,
            "local_redis": observation.local_redis,
            "missing_count": observation.missing_count,
            "observed_count": observation.observed_count,
            "redis_cache": observation.redis_cache.value,
            "redis_delivery": observation.redis_delivery.value,
        }
        if observation.level1_first_defect is not None:
            projected["level1_first_defect"] = observation.level1_first_defect.value
        document["observation"] = projected
    line = json.dumps(document, sort_keys=True, separators=(",", ":"))
    if len(line.encode("utf-8")) > 1_024:
        raise ValueError("LEVEL2_CORE_EVIDENCE_INVALID")
    return line


def _condition_passes(spec: CoreServiceSpec, condition: CoreServiceCondition) -> bool:
    if spec.health_required:
        return condition is CoreServiceCondition.RUNNING_HEALTHY
    return condition in {
        CoreServiceCondition.RUNNING_NO_HEALTH,
        CoreServiceCondition.RUNNING_HEALTHY,
    }


def evaluate_level2_core_snapshot(
    *,
    observations: Sequence[CoreServiceObservation],
    expected_specs: Sequence[CoreServiceSpec],
    local_redis: bool,
    local_graph: bool,
    local_gateway: bool,
) -> Level2CoreProjection:
    by_key = {observation.key: observation for observation in observations}
    if len(by_key) != len(observations) or set(by_key) != {spec.key for spec in expected_specs}:
        raise ValueError("LEVEL2_CORE_OBSERVATION_INVALID")
    level1_defect = next(
        (
            spec.key
            for spec in expected_specs
            if spec.key.value.startswith("LEVEL1_")
            and not _condition_passes(spec, by_key[spec.key].condition)
        ),
        None,
    )
    level2 = {
        spec.key: by_key[spec.key].condition
        for spec in expected_specs
        if spec.key.value.startswith("LEVEL2_")
    }
    selected = local_redis and local_graph and local_gateway
    if not selected:
        predicate = Level2CorePredicate.LEVEL2_ADOPTION_REQUIRED
    elif level1_defect is not None:
        predicate = Level2CorePredicate.LEVEL1_CONTRACT
    elif any(
        condition is not CoreServiceCondition.RUNNING_HEALTHY for condition in level2.values()
    ):
        predicate = Level2CorePredicate.LEVEL2_CONTRACT
    else:
        predicate = Level2CorePredicate.PASS
    return Level2CoreProjection(
        predicate=predicate,
        local_redis=local_redis,
        local_graph=local_graph,
        local_gateway=local_gateway,
        level1_pass=level1_defect is None,
        level1_first_defect=level1_defect,
        redis_cache=level2[CoreServiceKey.LEVEL2_REDIS_CACHE],
        redis_delivery=level2[CoreServiceKey.LEVEL2_REDIS_DELIVERY],
        graph=level2[CoreServiceKey.LEVEL2_GRAPH],
        gateway=level2[CoreServiceKey.LEVEL2_GATEWAY],
        observed_count=sum(value.private_id is not None for value in observations),
        missing_count=sum(value.private_id is None for value in observations),
    )
