from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol
from urllib.parse import quote

import httpx

from datariver.application.dto import (
    CapabilityStatus,
    DataHubApplyReceipt,
    DataHubAspectSnapshot,
    DataHubAssetEnrichment,
    DataHubLineageNode,
    DataHubLineagePage,
    DataHubScanAsset,
    DataHubScanPage,
)
from datariver.application.errors import ExternalDependencyError
from datariver.domain.authz import Classification
from datariver.domain.common import canonical_json_hash

ASSET_QUERY = """
query DataRiverAsset($urn: String!) {
  entity(urn: $urn) {
    urn
    type
    ... on Dataset {
      ownership {
        owners {
          owner {
            ... on CorpUser { urn }
            ... on CorpGroup { urn }
          }
          type
        }
      }
      globalTags { tags { tag { urn name } } }
      glossaryTerms { terms { term { urn name } } }
      schemaMetadata {
        fields {
          fieldPath
          type
          nativeDataType
          description
          globalTags { tags { tag { urn name } } }
          glossaryTerms { terms { term { urn name } } }
        }
      }
    }
  }
}
"""


class DataHubTelemetry(Protocol):
    def datahub_request_started(self, *, operation: str) -> None: ...

    def datahub_request_finished(
        self, *, operation: str, outcome: str, duration_seconds: float
    ) -> None: ...

    def datahub_queue_rejected(self, *, operation: str) -> None: ...

    def datahub_circuit_changed(self, *, state: str) -> None: ...


LINEAGE_QUERY = """
query DataRiverLineage($input: ScrollAcrossLineageInput!) {
  scrollAcrossLineage(input: $input) {
    count
    total
    isPartial
    searchResults {
      entity { urn type }
      degree
      truncatedChildren
      paths { path { urn type } }
    }
    nextScrollId
  }
}
"""

CATALOG_SCAN_QUERY = """
query DataRiverCatalogScan($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    start
    count
    total
    searchResults {
      entity {
        urn
        type
        ... on Dataset {
          name
          subTypes { typeNames }
          platform { urn name }
          properties { name description created customProperties { key value } }
          browsePathV2 {
            path {
              name
              entity {
                urn
                type
                ... on Container {
                  properties { name qualifiedName }
                  subTypes { typeNames }
                }
              }
            }
          }
          domain { domain { urn } }
          ownership {
            owners {
              owner {
                ... on CorpUser { urn }
                ... on CorpGroup { urn }
              }
            }
          }
          globalTags { tags { tag { name } } }
          glossaryTerms { terms { term { urn name } } }
          schemaMetadata { fields { fieldPath } }
        }
      }
    }
  }
}
"""

VOCABULARY_SEARCH_QUERY = """
query DataRiverVocabularySearch($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    searchResults {
      entity {
        urn
        type
        ... on Tag { name }
        ... on GlossaryTerm { properties { name } }
      }
    }
  }
}
"""


def _classification_from_tags(tags: object) -> Classification | None:
    values: set[Classification] = set()
    raw_tags = tags.get("tags", []) if isinstance(tags, dict) else []
    for raw in raw_tags if isinstance(raw_tags, list) else []:
        tag = raw.get("tag") if isinstance(raw, dict) else None
        name = tag.get("name") if isinstance(tag, dict) else None
        if not isinstance(name, str) or ":" not in name:
            continue
        namespace, value = (part.strip().upper() for part in name.split(":", 1))
        if namespace != "CLASSIFICATION":
            continue
        try:
            values.add(Classification[value])
        except KeyError:
            return None
    return next(iter(values)) if len(values) == 1 else None


def _container_hierarchy_kind(type_names: set[str]) -> str | None:
    """Map typed provider container aliases without deriving hierarchy from a URN."""
    normalized = {
        "".join(character for character in value.casefold() if character.isalnum())
        for value in type_names
    }
    if any(name == "schema" or name.endswith("schema") for name in normalized):
        return "SCHEMA"
    if any(name == "database" or name.endswith("database") for name in normalized):
        return "DATABASE"
    return None


def _catalog_hierarchy_from_browse_path(value: object) -> tuple[str | None, str | None]:
    path = value.get("path") if isinstance(value, dict) else None
    database_names: set[str] = set()
    schema_names: set[str] = set()
    untyped_path_names: set[str] = set()
    for entry in path if isinstance(path, list) else []:
        entity = entry.get("entity") if isinstance(entry, dict) else None
        if not isinstance(entity, dict) or entity.get("type") != "CONTAINER":
            label = entry.get("name") if isinstance(entry, dict) else None
            if isinstance(label, str) and label.strip() and not label.strip().startswith("urn:li:"):
                # DataHub may return a provider-owned path segment without a
                # materialized Container entity.  It is still an authoritative
                # browse-path label, so preserve it as a schema only; a missing
                # database is never guessed from a dataset URN or platform name.
                untyped_path_names.add(label.strip()[:255])
            continue
        subtypes = entity.get("subTypes")
        raw_type_names = subtypes.get("typeNames") if isinstance(subtypes, dict) else None
        type_names = {
            str(item).strip().casefold()
            for item in (raw_type_names if isinstance(raw_type_names, list) else [])
            if isinstance(item, str) and item.strip()
        }
        properties = entity.get("properties")
        raw_name = properties.get("name") if isinstance(properties, dict) else None
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        name = raw_name.strip()[:255]
        kind = _container_hierarchy_kind(type_names)
        if kind == "DATABASE":
            database_names.add(name)
        if kind == "SCHEMA":
            schema_names.add(name)
    return (
        next(iter(database_names)) if len(database_names) == 1 else None,
        next(iter(schema_names))
        if len(schema_names) == 1
        else next(iter(untyped_path_names))
        if len(untyped_path_names) == 1
        else None,
    )


def _datahub_timestamp(value: object) -> datetime | None:
    raw_time = value.get("time") if isinstance(value, dict) else value
    if isinstance(raw_time, bool) or not isinstance(raw_time, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(raw_time / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _metadata_names(value: object, *, wrapper: str, entity: str) -> tuple[str, ...]:
    raw_items = value.get(wrapper, []) if isinstance(value, dict) else []
    items = raw_items if isinstance(raw_items, list) else []
    names = {
        str(reference.get("name") or reference.get("urn")).strip()
        for item in items
        if isinstance(item, dict)
        for reference in [item.get(entity)]
        if isinstance(reference, dict) and (reference.get("name") or reference.get("urn"))
    }
    return tuple(sorted(names))


def _custom_property_value(value: object, *, key: str) -> str | None:
    entries = value if isinstance(value, list) else []
    values = {
        str(entry.get("value")).strip()
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("key") == key
        and isinstance(entry.get("value"), str)
        and entry["value"].strip()
    }
    return next(iter(values)) if len(values) == 1 else None


def _dataset_asset_type(entity: dict[str, Any]) -> str:
    subtypes = entity.get("subTypes")
    raw_names = subtypes.get("typeNames") if isinstance(subtypes, dict) else []
    type_names = raw_names if isinstance(raw_names, list) else []
    normalized = {
        "".join(character for character in value.casefold() if character.isalnum())
        for value in type_names
        if isinstance(value, str)
    }
    if any(name == "view" or name.endswith("view") for name in normalized):
        return "VIEW"
    if any(name == "table" or name.endswith("table") for name in normalized):
        return "TABLE"
    properties = entity.get("properties")
    seed_kind = _custom_property_value(
        properties.get("customProperties") if isinstance(properties, dict) else None,
        key="datariver.seed.object_kind",
    )
    if seed_kind is not None:
        normalized_seed_kind = seed_kind.casefold()
        if normalized_seed_kind == "view":
            return "VIEW"
        if normalized_seed_kind == "table":
            return "TABLE"
    return "DATASET"


def _column_names(value: object) -> tuple[str, ...]:
    raw_fields = value.get("fields") if isinstance(value, dict) else []
    fields = raw_fields if isinstance(raw_fields, list) else []
    return tuple(
        sorted(
            {
                str(field["fieldPath"]).strip()[:500]
                for field in fields
                if isinstance(field, dict)
                and isinstance(field.get("fieldPath"), str)
                and field["fieldPath"].strip()
            }
        )
    )


def _aspect_document(envelope: Any) -> dict[str, Any]:
    candidate = envelope.get("aspect", envelope) if isinstance(envelope, dict) else envelope
    if isinstance(candidate, dict) and "value" in candidate:
        candidate = candidate["value"]
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except ValueError as error:
            raise ExternalDependencyError(
                "DataHub returned an invalid aspect envelope.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            ) from error
    if isinstance(candidate, dict) and len(candidate) == 1:
        type_name, typed_value = next(iter(candidate.items()))
        if type_name.startswith("com.linkedin.") and isinstance(typed_value, dict):
            candidate = typed_value
    if not isinstance(candidate, dict):
        raise ExternalDependencyError(
            "DataHub returned an invalid aspect envelope.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    return candidate


def _immutable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _immutable_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_immutable_json(item) for item in value)
    return value


def _datahub_version_from_config(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ExternalDependencyError(
            "DataHub returned an invalid version contract.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_VERSION_CONTRACT",
        )
    versions = payload.get("versions")
    product = versions.get("acryldata/datahub") if isinstance(versions, dict) else None
    version = product.get("version") if isinstance(product, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ExternalDependencyError(
            "DataHub did not report a supported version contract.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_VERSION_CONTRACT",
        )
    return version.strip()


class HttpDataHubGateway:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        expected_version: str | None = None,
        allowed_versions: tuple[str, ...] = (),
        version_enforcement: Literal["report", "enforce"] = "report",
        development_version_bypass: bool = False,
        version_probe_ttl_seconds: int = 300,
        maximum_concurrency: int = 20,
        queue_timeout_seconds: float = 2.0,
        circuit_failure_threshold: int = 5,
        circuit_open_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        telemetry: DataHubTelemetry | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 3)),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "datariver-next/0.1"},
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._expected_version = expected_version
        self._accepted_versions = frozenset(
            version for version in (expected_version, *allowed_versions) if version is not None
        )
        self._version_enforcement = version_enforcement
        self._development_version_bypass = development_version_bypass
        self._version_probe_ttl_seconds = version_probe_ttl_seconds
        self._version_lock = asyncio.Lock()
        self._version_checked_at = 0.0
        self._observed_version: str | None = None
        self._semaphore = asyncio.Semaphore(maximum_concurrency)
        self._queue_timeout_seconds = queue_timeout_seconds
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_open_seconds = circuit_open_seconds
        self._circuit_lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._half_open_in_flight = False
        self._telemetry = telemetry

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        operation = self._operation(url)
        started = time.perf_counter()
        outcome = "cancelled"
        if self._telemetry is not None:
            self._telemetry.datahub_request_started(operation=operation)
        try:
            try:
                half_open_probe = await self._before_request()
            except ExternalDependencyError:
                outcome = "circuit_open"
                raise
            try:
                await asyncio.wait_for(
                    self._semaphore.acquire(), timeout=self._queue_timeout_seconds
                )
            except TimeoutError as error:
                outcome = "overloaded"
                await self._cancel_half_open_probe(half_open_probe)
                if self._telemetry is not None:
                    self._telemetry.datahub_queue_rejected(operation=operation)
                raise ExternalDependencyError(
                    "DataHub concurrency capacity is exhausted.",
                    dependency="datahub",
                    retryable=True,
                    provider_code="OVERLOADED",
                ) from error
            try:
                try:
                    response = await self._client.request(method, url, **kwargs)
                except httpx.TimeoutException as error:
                    outcome = "timeout"
                    await self._record_failure(half_open_probe=half_open_probe)
                    raise ExternalDependencyError(
                        "DataHub timed out.",
                        dependency="datahub",
                        retryable=True,
                        provider_code="TIMEOUT",
                    ) from error
                except httpx.HTTPError as error:
                    outcome = "network"
                    await self._record_failure(half_open_probe=half_open_probe)
                    raise ExternalDependencyError(
                        "DataHub is unavailable.",
                        dependency="datahub",
                        retryable=True,
                        provider_code="NETWORK",
                    ) from error
                except asyncio.CancelledError:
                    await self._cancel_half_open_probe(half_open_probe)
                    raise
                outcome = self._response_outcome(response.status_code)
                if response.status_code == 429 or response.status_code >= 500:
                    await self._record_failure(half_open_probe=half_open_probe)
                else:
                    await self._record_success()
                return response
            finally:
                self._semaphore.release()
        finally:
            if self._telemetry is not None:
                self._telemetry.datahub_request_finished(
                    operation=operation,
                    outcome=outcome,
                    duration_seconds=time.perf_counter() - started,
                )

    async def _before_request(self) -> bool:
        async with self._circuit_lock:
            now = time.monotonic()
            if self._circuit_open_until > now:
                raise ExternalDependencyError(
                    "DataHub circuit breaker is open.",
                    dependency="datahub",
                    retryable=True,
                    provider_code="CIRCUIT_OPEN",
                )
            if self._circuit_open_until > 0:
                if self._half_open_in_flight:
                    raise ExternalDependencyError(
                        "DataHub circuit breaker is awaiting a recovery probe.",
                        dependency="datahub",
                        retryable=True,
                        provider_code="CIRCUIT_OPEN",
                    )
                self._half_open_in_flight = True
                if self._telemetry is not None:
                    self._telemetry.datahub_circuit_changed(state="half_open")
                return True
            return False

    async def _record_failure(self, *, half_open_probe: bool) -> None:
        async with self._circuit_lock:
            self._consecutive_failures += 1
            opened = (
                half_open_probe or self._consecutive_failures >= self._circuit_failure_threshold
            )
            if opened:
                self._circuit_open_until = time.monotonic() + self._circuit_open_seconds
            self._half_open_in_flight = False
            if self._telemetry is not None:
                self._telemetry.datahub_circuit_changed(state="open" if opened else "closed")

    async def _record_success(self) -> None:
        async with self._circuit_lock:
            self._consecutive_failures = 0
            self._circuit_open_until = 0.0
            self._half_open_in_flight = False
            if self._telemetry is not None:
                self._telemetry.datahub_circuit_changed(state="closed")

    async def _cancel_half_open_probe(self, half_open_probe: bool) -> None:
        if not half_open_probe:
            return
        async with self._circuit_lock:
            self._half_open_in_flight = False

    @staticmethod
    def _operation(url: str) -> str:
        if url == "/api/graphql":
            return "graphql"
        if url == "/aspects?action=ingestProposal":
            return "ingest_proposal"
        if url.startswith("/aspects/"):
            return "read_aspect"
        if url == "/config":
            return "capability"
        return "other"

    @staticmethod
    def _response_outcome(status_code: int) -> str:
        if status_code < 400:
            return "success"
        if status_code == 429:
            return "rate_limited"
        if status_code >= 500:
            return "server_error"
        return "client_error"

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_version_contract()
        response = await self._request(
            "POST", "/api/graphql", json={"query": query, "variables": variables}
        )
        if response.status_code in {401, 403}:
            raise ExternalDependencyError(
                "DataHub rejected the service identity.",
                dependency="datahub",
                retryable=False,
                provider_code="UNAUTHORIZED",
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise ExternalDependencyError(
                "DataHub could not process the request.",
                dependency="datahub",
                retryable=True,
                provider_code=str(response.status_code),
            )
        if response.status_code >= 400:
            raise ExternalDependencyError(
                "DataHub rejected the typed request.",
                dependency="datahub",
                retryable=False,
                provider_code=str(response.status_code),
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise ExternalDependencyError(
                "DataHub returned invalid JSON.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            ) from error
        if not isinstance(payload, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid response.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        if payload.get("errors"):
            raise ExternalDependencyError(
                "DataHub returned a GraphQL contract error.",
                dependency="datahub",
                retryable=False,
                provider_code="GRAPHQL_ERROR",
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid response.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        return data

    async def get_asset(self, external_urn: str) -> DataHubAssetEnrichment:
        data = await self._graphql(ASSET_QUERY, {"urn": external_urn})
        entity = data.get("entity")
        if not isinstance(entity, dict):
            raise ExternalDependencyError(
                "The DataHub asset does not exist.",
                dependency="datahub",
                retryable=False,
                provider_code="NOT_FOUND",
            )
        ownership = entity.get("ownership")
        ownership_document = ownership if isinstance(ownership, dict) else {}
        owners = tuple(
            item for item in (ownership_document.get("owners") or ()) if isinstance(item, dict)
        )
        global_tags = entity.get("globalTags")
        tags_document = global_tags if isinstance(global_tags, dict) else {}
        tags = tuple(
            str(tag.get("name") or tag.get("urn"))
            for item in (tags_document.get("tags") or ())
            if isinstance(item, dict)
            and isinstance((tag := item.get("tag")), dict)
            and (tag.get("name") or tag.get("urn"))
        )
        glossary_terms = entity.get("glossaryTerms")
        glossary_document = glossary_terms if isinstance(glossary_terms, dict) else {}
        glossary = tuple(
            item for item in (glossary_document.get("terms") or ()) if isinstance(item, dict)
        )
        schema_metadata = entity.get("schemaMetadata")
        schema_document = schema_metadata if isinstance(schema_metadata, dict) else {}
        fields = tuple(
            item for item in (schema_document.get("fields") or ()) if isinstance(item, dict)
        )
        now = datetime.now(UTC)
        return DataHubAssetEnrichment(
            ownership=owners,
            glossary_terms=glossary,
            tags=tags,
            schema_fields=fields,
            quality={},
            raw_version=canonical_json_hash(entity),
            observed_at=now,
        )

    async def get_lineage(
        self, *, external_urn: str, direction: str, depth: int
    ) -> DataHubLineagePage:
        if direction not in {"UPSTREAM", "DOWNSTREAM"} or not 1 <= depth <= 3:
            raise ValueError("Lineage direction or depth is invalid.")
        # ``ScrollAcrossLineageInput`` has no ``maxDegree`` input in the
        # reviewed DataHub v1.6 contract.  Depth is instead a facet value;
        # ``3+`` is needed to include the third hop and is bounded again below
        # because it can also represent results deeper than three hops.
        degree_values = [str(value) for value in range(1, depth + 1)]
        if depth == 3:
            degree_values[-1] = "3+"
        data = await self._graphql(
            LINEAGE_QUERY,
            {
                "input": {
                    "urn": external_urn,
                    "direction": direction,
                    "query": "*",
                    "count": 100,
                    "orFilters": [
                        {
                            "and": [
                                {
                                    "condition": "EQUAL",
                                    "negated": False,
                                    "field": "degree",
                                    "values": degree_values,
                                }
                            ]
                        }
                    ],
                }
            },
        )
        result = data.get("scrollAcrossLineage")
        raw_items = result.get("searchResults") if isinstance(result, dict) else None
        if not isinstance(result, dict) or not isinstance(raw_items, list):
            raise ExternalDependencyError(
                "DataHub returned an invalid lineage contract.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        items: list[DataHubLineageNode] = []
        excluded_deeper_result = False
        for raw in raw_items:
            entity = raw.get("entity") if isinstance(raw, dict) else None
            raw_paths = raw.get("paths") if isinstance(raw, dict) else None
            if (
                not isinstance(raw, dict)
                or not isinstance(entity, dict)
                or not isinstance(entity.get("urn"), str)
                or not isinstance(raw.get("degree"), int)
                or not isinstance(raw_paths, list)
            ):
                raise ExternalDependencyError(
                    "DataHub returned an invalid lineage result.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            if int(raw["degree"]) > depth:
                # DataHub represents a depth of three as the ``3+`` facet.
                # Never let an over-depth path escape the facade's fixed
                # 1..3-hop contract.
                excluded_deeper_result = True
                continue
            paths: list[tuple[str, ...]] = []
            for raw_path in raw_paths:
                raw_entities = raw_path.get("path") if isinstance(raw_path, dict) else None
                if not isinstance(raw_entities, list):
                    continue
                path = tuple(
                    str(path_entity["urn"])
                    for path_entity in raw_entities
                    if isinstance(path_entity, dict) and isinstance(path_entity.get("urn"), str)
                )
                if path:
                    paths.append(path)
            items.append(
                DataHubLineageNode(
                    external_urn=str(entity["urn"]),
                    degree=int(raw["degree"]),
                    paths=tuple(paths),
                    truncated_children=bool(raw.get("truncatedChildren", False)),
                )
            )
        try:
            total = int(result.get("total", len(items)))
        except (TypeError, ValueError) as error:
            raise ExternalDependencyError(
                "DataHub returned invalid lineage pagination.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            ) from error
        return DataHubLineagePage(
            items=tuple(items),
            total=total,
            partial=bool(result.get("isPartial", False)) or excluded_deeper_result,
        )

    async def scan_assets(self, *, offset: int, limit: int) -> DataHubScanPage:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("DataHub scan bounds are invalid.")
        data = await self._graphql(
            CATALOG_SCAN_QUERY,
            {"input": {"types": ["DATASET"], "query": "*", "start": offset, "count": limit}},
        )
        result = data.get("searchAcrossEntities")
        if not isinstance(result, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid scan contract.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        raw_results = result.get("searchResults")
        if not isinstance(raw_results, list):
            raise ExternalDependencyError(
                "DataHub returned an invalid scan result list.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        items: list[DataHubScanAsset] = []
        for raw in raw_results:
            entity = raw.get("entity") if isinstance(raw, dict) else None
            if not isinstance(entity, dict) or not isinstance(entity.get("urn"), str):
                raise ExternalDependencyError(
                    "DataHub returned an invalid scan entity.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            properties = entity.get("properties")
            properties = properties if isinstance(properties, dict) else {}
            platform = entity.get("platform")
            platform_name = platform.get("name") if isinstance(platform, dict) else None
            system_ref = platform.get("urn") if isinstance(platform, dict) else None
            domain_wrapper = entity.get("domain")
            domain = domain_wrapper.get("domain") if isinstance(domain_wrapper, dict) else None
            domain_ref = domain.get("urn") if isinstance(domain, dict) else None
            ownership = entity.get("ownership")
            raw_owners = ownership.get("owners", []) if isinstance(ownership, dict) else []
            owner_refs = sorted(
                str(owner["urn"])
                for item in raw_owners
                if isinstance(raw_owners, list)
                if isinstance(item, dict)
                for owner in [item.get("owner")]
                if isinstance(owner, dict) and owner.get("urn")
            )
            name = properties.get("name") or entity.get("name") or entity["urn"]
            database_name, schema_name = _catalog_hierarchy_from_browse_path(
                entity.get("browsePathV2")
            )
            if database_name is None:
                database_name = _custom_property_value(
                    properties.get("customProperties") if isinstance(properties, dict) else None,
                    key="datariver.seed.database_name",
                )
            items.append(
                DataHubScanAsset(
                    external_urn=entity["urn"],
                    asset_type=_dataset_asset_type(entity),
                    name=str(name)[:500],
                    description=(
                        str(properties["description"]) if properties.get("description") else None
                    ),
                    platform=str(platform_name)[:100] if platform_name else None,
                    database_name=database_name[:255] if database_name else None,
                    schema_name=schema_name,
                    domain_ref=str(domain_ref) if domain_ref else None,
                    system_ref=str(system_ref) if system_ref else None,
                    owner_ref=owner_refs[0] if owner_refs else None,
                    classification=_classification_from_tags(entity.get("globalTags")),
                    source_version=canonical_json_hash(entity),
                    tags=_metadata_names(entity.get("globalTags"), wrapper="tags", entity="tag"),
                    glossary_terms=_metadata_names(
                        entity.get("glossaryTerms"), wrapper="terms", entity="term"
                    ),
                    column_names=_column_names(entity.get("schemaMetadata")),
                    created_at=_datahub_timestamp(properties.get("created")),
                )
            )
        try:
            start = int(result.get("start", offset))
            count = int(result.get("count", len(items)))
            total = int(result.get("total", start + count))
        except (TypeError, ValueError) as error:
            raise ExternalDependencyError(
                "DataHub returned invalid scan pagination.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            ) from error
        next_offset = start + count if count > 0 and start + count < total else None
        return DataHubScanPage(
            items=tuple(items),
            next_offset=next_offset,
            total=total,
            observed_at=datetime.now(UTC),
        )

    async def search_vocabulary(self, *, kind: str, query: str, limit: int) -> tuple[str, ...]:
        if kind not in {"TAG", "TERM"} or not query.strip() or not 1 <= limit <= 50:
            raise ValueError("DataHub vocabulary search request is invalid.")
        entity_type = "TAG" if kind == "TAG" else "GLOSSARY_TERM"
        # Result ordering is provider-defined.  Inspect a bounded discovery
        # window before the catalog service applies its presentation limit so
        # controlled tags and terms do not vanish after a short first page.
        page_size = 50
        maximum_results = min(250, max(page_size, limit * 8))
        values: set[str] = set()
        for start in range(0, maximum_results, page_size):
            data = await self._graphql(
                VOCABULARY_SEARCH_QUERY,
                {
                    "input": {
                        "types": [entity_type],
                        "query": query.strip(),
                        "start": start,
                        "count": page_size,
                    }
                },
            )
            result = data.get("searchAcrossEntities")
            raw_results = result.get("searchResults") if isinstance(result, dict) else None
            if not isinstance(raw_results, list):
                raise ExternalDependencyError(
                    "DataHub returned an invalid vocabulary search result.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            for raw in raw_results:
                entity = raw.get("entity") if isinstance(raw, dict) else None
                if not isinstance(entity, dict):
                    continue
                if kind == "TAG":
                    name = entity.get("name")
                else:
                    properties = entity.get("properties")
                    name = properties.get("name") if isinstance(properties, dict) else None
                if isinstance(name, str) and (normalized_name := name.strip()):
                    values.add(normalized_name[:500])
            if len(raw_results) < page_size:
                break
        return tuple(sorted(values, key=str.casefold))

    async def apply_change(
        self,
        *,
        external_urn: str,
        aspect_name: str,
        document: dict[str, Any],
        idempotency_key: str,
    ) -> DataHubApplyReceipt:
        await self._ensure_version_contract()
        proposal = {
            "proposal": {
                "entityType": "dataset",
                "entityUrn": external_urn,
                "changeType": "UPSERT",
                "aspectName": aspect_name,
                "aspect": {
                    "value": json.dumps(document, ensure_ascii=False, separators=(",", ":")),
                    "contentType": "application/json",
                },
            }
        }
        response = await self._request(
            "POST",
            "/aspects?action=ingestProposal",
            json=proposal,
            headers={"Idempotency-Key": idempotency_key},
        )
        if response.status_code >= 400:
            raise ExternalDependencyError(
                "DataHub rejected the metadata proposal.",
                dependency="datahub",
                retryable=response.status_code == 429 or response.status_code >= 500,
                provider_code=str(response.status_code),
            )
        try:
            response_document = response.json() if response.content else {}
        except ValueError as error:
            raise ExternalDependencyError(
                "DataHub returned invalid apply confirmation.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            ) from error
        response_hash = canonical_json_hash(response_document)
        return DataHubApplyReceipt(
            operation_id=response.headers.get("x-request-id", idempotency_key),
            accepted_at=datetime.now(UTC),
            provider_version=response.headers.get("x-datahub-version", "unknown"),
            response_hash=response_hash,
        )

    async def read_aspect(self, *, external_urn: str, aspect_name: str) -> DataHubAspectSnapshot:
        await self._ensure_version_contract()
        encoded_urn = quote(external_urn, safe="")
        response = await self._request(
            "GET",
            f"/aspects/{encoded_urn}",
            params={"aspect": aspect_name, "version": 0},
        )
        if response.status_code == 404:
            return DataHubAspectSnapshot(
                urn=external_urn,
                aspect_name=aspect_name,
                content_hash=canonical_json_hash({}),
                source_version="absent",
                observed_at=datetime.now(UTC),
                document=MappingProxyType({}),
            )
        if response.status_code >= 400:
            raise ExternalDependencyError(
                "DataHub aspect reconciliation failed.",
                dependency="datahub",
                retryable=response.status_code == 429 or response.status_code >= 500,
                provider_code=str(response.status_code),
            )
        try:
            document = response.json()
        except ValueError as error:
            raise ExternalDependencyError(
                "DataHub returned invalid aspect JSON.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            ) from error
        normalized = _aspect_document(document)
        return DataHubAspectSnapshot(
            urn=external_urn,
            aspect_name=aspect_name,
            content_hash=canonical_json_hash(normalized),
            source_version=response.headers.get("etag", "unknown"),
            observed_at=datetime.now(UTC),
            document=_immutable_json(normalized),
        )

    async def _read_reported_version(self) -> str:
        response = await self._request("GET", "/config")
        if response.status_code in {401, 403}:
            raise ExternalDependencyError(
                "DataHub rejected the service identity.",
                dependency="datahub",
                retryable=False,
                provider_code="UNAUTHORIZED",
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise ExternalDependencyError(
                "DataHub could not report its version contract.",
                dependency="datahub",
                retryable=True,
                provider_code=str(response.status_code),
            )
        if response.status_code >= 400:
            raise ExternalDependencyError(
                "DataHub rejected the version contract probe.",
                dependency="datahub",
                retryable=False,
                provider_code=str(response.status_code),
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise ExternalDependencyError(
                "DataHub returned invalid version JSON.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_VERSION_CONTRACT",
            ) from error
        return _datahub_version_from_config(payload)

    async def _reported_version(self, *, force: bool = False) -> str:
        now = time.monotonic()
        if (
            not force
            and self._observed_version is not None
            and now - self._version_checked_at < self._version_probe_ttl_seconds
        ):
            return self._observed_version
        async with self._version_lock:
            now = time.monotonic()
            if (
                not force
                and self._observed_version is not None
                and now - self._version_checked_at < self._version_probe_ttl_seconds
            ):
                return self._observed_version
            observed = await self._read_reported_version()
            self._observed_version = observed
            self._version_checked_at = time.monotonic()
            return observed

    async def _ensure_version_contract(self) -> None:
        if self._expected_version is None:
            return
        observed = await self._reported_version()
        if observed not in self._accepted_versions and self._version_enforcement == "enforce":
            raise ExternalDependencyError(
                "DataHub does not match the approved release contract.",
                dependency="datahub",
                retryable=False,
                provider_code="VERSION_MISMATCH",
            )

    async def capability(self) -> CapabilityStatus:
        started = time.perf_counter()
        state = "healthy"
        detail_code = None
        try:
            observed = await self._reported_version(force=True)
            if (
                self._expected_version is not None
                and observed not in self._accepted_versions
                and not self._development_version_bypass
            ):
                state = "degraded"
                detail_code = "VERSION_MISMATCH"
        except ExternalDependencyError as error:
            state = "unavailable"
            detail_code = str(error.details.get("provider_code") or "NETWORK")
        return CapabilityStatus(
            name="datahub",
            state=state,
            observed_at=datetime.now(UTC),
            latency_ms=round((time.perf_counter() - started) * 1000),
            detail_code=detail_code,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
