from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from datariver.application.dto import (
    CapabilityStatus,
    DataHubApplyReceipt,
    DataHubAspectSnapshot,
    DataHubAssetEnrichment,
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
      ownership { owners { owner { urn type } type } }
      globalTags { tags { tag { urn name } } }
      glossaryTerms { terms { term { urn name } } }
      schemaMetadata { fields { fieldPath type description } }
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
    searchResults { entity { urn type } degree paths }
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
          platform { urn name }
          properties { name description }
          domain { domain { urn } }
          ownership { owners { owner { urn } } }
          globalTags { tags { tag { name } } }
        }
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
    if not isinstance(candidate, dict):
        raise ExternalDependencyError(
            "DataHub returned an invalid aspect envelope.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    return candidate


class HttpDataHubGateway:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
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
    ) -> tuple[dict[str, Any], ...]:
        if direction not in {"UPSTREAM", "DOWNSTREAM"} or not 1 <= depth <= 5:
            raise ValueError("Lineage direction or depth is invalid.")
        data = await self._graphql(
            LINEAGE_QUERY,
            {
                "input": {
                    "urn": external_urn,
                    "direction": direction,
                    "query": "*",
                    "count": 100,
                    "maxDegree": depth,
                }
            },
        )
        result = data.get("scrollAcrossLineage") or {}
        return tuple(result.get("searchResults") or ())

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
            items.append(
                DataHubScanAsset(
                    external_urn=entity["urn"],
                    asset_type=str(entity.get("type") or "DATASET"),
                    name=str(name)[:500],
                    description=(
                        str(properties["description"]) if properties.get("description") else None
                    ),
                    platform=str(platform_name)[:100] if platform_name else None,
                    domain_ref=str(domain_ref) if domain_ref else None,
                    system_ref=str(system_ref) if system_ref else None,
                    owner_ref=owner_refs[0] if owner_refs else None,
                    classification=_classification_from_tags(entity.get("globalTags")),
                    source_version=canonical_json_hash(entity),
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

    async def apply_change(
        self,
        *,
        external_urn: str,
        aspect_name: str,
        document: dict[str, Any],
        idempotency_key: str,
    ) -> DataHubApplyReceipt:
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
        encoded_urn = quote(external_urn, safe="")
        response = await self._request(
            "GET",
            f"/aspects/{encoded_urn}",
            params={"aspect": aspect_name, "version": 0},
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
        return DataHubAspectSnapshot(
            urn=external_urn,
            aspect_name=aspect_name,
            content_hash=canonical_json_hash(_aspect_document(document)),
            source_version=response.headers.get("etag", "unknown"),
            observed_at=datetime.now(UTC),
        )

    async def capability(self) -> CapabilityStatus:
        started = time.perf_counter()
        state = "healthy"
        detail_code = None
        try:
            response = await self._request("GET", "/config")
            if response.status_code >= 500:
                state = "unavailable"
                detail_code = str(response.status_code)
            elif response.status_code >= 400:
                state = "degraded"
                detail_code = str(response.status_code)
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
