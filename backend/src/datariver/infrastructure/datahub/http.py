from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from itertools import chain
from types import MappingProxyType
from typing import Any, Literal, Protocol
from urllib.parse import quote

import httpx

from datariver.application.dto import (
    MAX_CATALOG_SCHEMA_FIELDS,
    CapabilityStatus,
    DataHubApplyReceipt,
    DataHubAspectSnapshot,
    DataHubAssetEnrichment,
    DataHubLineageNode,
    DataHubLineagePage,
    DataHubScanAsset,
    DataHubScanPage,
    DataHubVocabularyEntry,
    DataHubVocabularyScanPage,
)
from datariver.application.errors import ExternalDependencyError
from datariver.domain.authz import Classification
from datariver.domain.common import canonical_json_hash

MAX_DATAHUB_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_DATAHUB_EXTERNAL_URN_CHARACTERS = 4_096
MAX_DATAHUB_SCHEMA_FIELD_PATH_CHARACTERS = 4_096
MAX_DATAHUB_SCHEMA_FIELD_TYPE_CHARACTERS = 500
MAX_DATAHUB_SCHEMA_FIELD_LABEL_CHARACTERS = 500
MAX_DATAHUB_SCHEMA_FIELD_DESCRIPTION_CHARACTERS = 10_000
MAX_DATAHUB_SCHEMA_FIELD_REFERENCES = 20
MAX_DATAHUB_SCHEMA_FIELD_REFERENCE_CHARACTERS = 240
CATALOG_SCAN_CONTRACT_VERSION = "datahub-scroll-v1"

ASSET_QUERY = """
query DataRiverAsset($urn: String!) {
  entity(urn: $urn) {
    urn
    type
    ... on Dataset {
      properties { created description }
      editableProperties { description }
      ownership {
        owners {
          owner {
            ... on CorpUser { urn }
            ... on CorpGroup { urn }
          }
          type
        }
      }
      globalTags: tags { tags { tag { urn name } } }
      glossaryTerms { terms { term { urn name } } }
      schemaMetadata(version: 0) {
        fields {
          fieldPath
          label
          type
          nativeDataType
          description
          globalTags { tags { tag { urn name } } }
          glossaryTerms { terms { term { urn name } } }
          schemaFieldEntity {
            globalTags: tags { tags { tag { urn name } } }
            glossaryTerms { terms { term { urn name } } }
          }
        }
      }
      editableSchemaMetadata {
        editableSchemaFieldInfo {
          fieldPath
          description
          globalTags { tags { tag { urn name } } }
          glossaryTerms { terms { term { urn name } } }
        }
      }
      latestFullTableProfile: datasetProfiles(
        limit: 1
        filter: {
          and: [{
            field: "partitionSpec.partition"
            values: ["FULL_TABLE_SNAPSHOT", "SAMPLE"]
            condition: START_WITH
          }]
        }
      ) {
        rowCount
        columnCount
        sizeInBytes
        timestampMillis
        partitionSpec {
          type
          partition
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
query DataRiverLineageNeighbors($urn: String!, $input: LineageInput!) {
  dataset(urn: $urn) {
    urn
    lineage(input: $input) {
      total
      filtered
      relationships {
        entity { urn type }
      }
    }
  }
}
"""

CATALOG_SCAN_QUERY = """
query DataRiverCatalogScroll($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    nextScrollId
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
          editableProperties { description }
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
          globalTags: tags { tags { tag { name properties { name } } } }
          glossaryTerms { terms { term { urn name } } }
          schemaMetadata { fields { fieldPath } }
        }
      }
    }
  }
}
"""


def _catalog_snapshot_contract_hash(
    *,
    base_url: str,
    expected_version: str,
    allowed_versions: tuple[str, ...],
    evidence_reference: str,
    version_enforcement: Literal["report", "enforce"],
) -> str:
    return canonical_json_hash(
        {
            "allowed_versions": sorted(allowed_versions),
            "base_url": base_url.rstrip("/"),
            "contract_version": CATALOG_SCAN_CONTRACT_VERSION,
            "entity_types": ["DATASET"],
            "evidence_reference": evidence_reference,
            "expected_version": expected_version,
            "keep_alive": "5m",
            "query": "*",
            "query_hash": canonical_json_hash(CATALOG_SCAN_QUERY),
            "search_flags": {
                "skip_aggregates": True,
                "skip_highlighting": True,
            },
            "sort": [{"field": "urn", "order": "ASCENDING"}],
            "version_enforcement": version_enforcement,
        }
    )


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


VOCABULARY_SCAN_QUERY = """
query DataRiverVocabularyScroll($input: ScrollAcrossEntitiesInput!) {
  scrollAcrossEntities(input: $input) {
    nextScrollId
    count
    total
    searchResults {
      entity {
        urn
        type
        ... on Domain { properties { name } }
        ... on Tag { name }
        ... on GlossaryTerm { properties { name } }
      }
    }
  }
}
"""


def _vocabulary_snapshot_contract_hash(
    *,
    base_url: str,
    accepted_versions: frozenset[str],
    evidence_reference: str,
    kind: str,
) -> str:
    return canonical_json_hash(
        {
            "accepted_versions": sorted(accepted_versions),
            "base_url": base_url.rstrip("/"),
            "contract_version": "datahub-vocabulary-scroll-v1",
            "entity_type": {
                "DOMAIN": "DOMAIN",
                "TAG": "TAG",
                "TERM": "GLOSSARY_TERM",
            }[kind],
            "evidence_reference": evidence_reference,
            "keep_alive": "5m",
            "query": "*",
            "query_hash": canonical_json_hash(VOCABULARY_SCAN_QUERY),
            "search_flags": {
                "skip_aggregates": True,
                "skip_highlighting": True,
            },
            "sort": [{"field": "urn", "order": "ASCENDING"}],
        }
    )


def _classification_from_tags(tags: object) -> Classification | None:
    values: set[Classification] = set()
    raw_tags = tags.get("tags", []) if isinstance(tags, dict) else []
    for raw in raw_tags if isinstance(raw_tags, list) else []:
        tag = raw.get("tag") if isinstance(raw, dict) else None
        properties = tag.get("properties") if isinstance(tag, dict) else None
        properties_name = properties.get("name") if isinstance(properties, dict) else None
        name = (
            properties_name
            if isinstance(properties_name, str)
            else (tag.get("name") if isinstance(tag, dict) else None)
        )
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


def _preferred_description(*, properties: object, editable_properties: object) -> str | None:
    """Use the DataHub user-editable description when it is non-blank.

    DataHub persists ingestion-source text in ``properties`` and UI/governed
    edits in ``editableProperties``.  The latter is the effective description
    shown by DataHub, so a projection must use the same precedence rather than
    silently losing a valid UI edit on the next reconciliation.
    """

    for value in (editable_properties, properties):
        description = value.get("description") if isinstance(value, dict) else None
        if description is not None and not isinstance(description, str):
            raise ExternalDependencyError(
                "DataHub returned an invalid description.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        if isinstance(description, str) and description.strip():
            return description
    return None


def _metadata_names_with_truncation(
    value: object,
    *,
    wrapper: str,
    entity: str,
) -> tuple[tuple[str, ...], bool]:
    if value is not None and not isinstance(value, dict):
        raise ExternalDependencyError(
            "DataHub returned invalid metadata.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    raw_items = value.get(wrapper, []) if isinstance(value, dict) else []
    if not isinstance(raw_items, list):
        raise ExternalDependencyError(
            "DataHub returned an invalid metadata collection.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    raw_names: set[str] = set()
    for item in raw_items:
        reference = item.get(entity) if isinstance(item, dict) else None
        if not isinstance(reference, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid metadata reference.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        name = reference.get("name")
        urn = reference.get("urn")
        if (name is not None and not isinstance(name, str)) or (
            urn is not None and not isinstance(urn, str)
        ):
            raise ExternalDependencyError(
                "DataHub returned an invalid metadata identity.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        identity = name if isinstance(name, str) and name.strip() else urn
        if isinstance(identity, str) and identity.strip():
            raw_names.add(identity.strip())
    names = {name[:1_000] for name in raw_names}
    return tuple(sorted(names)[:100]), len(names) > 100 or any(
        len(name) > 1_000 for name in raw_names
    )


def _metadata_names(value: object, *, wrapper: str, entity: str) -> tuple[str, ...]:
    return _metadata_names_with_truncation(value, wrapper=wrapper, entity=entity)[0]


def _metadata_references_with_truncation(
    value: object,
    *,
    wrapper: str,
    entity: str,
    maximum_items: int = 100,
    maximum_characters: int = 1_000,
) -> tuple[tuple[dict[str, Any], ...], bool]:
    if value is not None and not isinstance(value, dict):
        raise ExternalDependencyError(
            "DataHub returned invalid metadata.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    raw_items = value.get(wrapper, []) if isinstance(value, dict) else []
    if not isinstance(raw_items, list):
        raise ExternalDependencyError(
            "DataHub returned an invalid metadata collection.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    items = raw_items
    references: dict[str, dict[str, Any]] = {}
    truncated = False
    for item in items:
        reference = item.get(entity) if isinstance(item, dict) else None
        if not isinstance(reference, dict):
            continue
        urn = reference.get("urn")
        name = reference.get("name")
        if (urn is not None and not isinstance(urn, str)) or (
            name is not None and not isinstance(name, str)
        ):
            raise ExternalDependencyError(
                "DataHub returned an invalid metadata identity.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        identity = urn if isinstance(urn, str) and urn else name
        if not isinstance(identity, str) or not identity:
            continue
        normalized_reference: dict[str, Any] = (
            {"urn": urn[:maximum_characters]} if isinstance(urn, str) else {}
        )
        if isinstance(name, str):
            normalized_reference["name"] = name[:maximum_characters]
        truncated = (
            truncated
            or len(identity) > maximum_characters
            or (isinstance(name, str) and len(name) > maximum_characters)
        )
        references[identity] = {entity: normalized_reference}
    ordered = tuple(references[key] for key in sorted(references)[:maximum_items])
    return ordered, truncated or len(references) > maximum_items


def _metadata_references(
    value: object,
    *,
    wrapper: str,
    entity: str,
) -> tuple[dict[str, Any], ...]:
    return _metadata_references_with_truncation(
        value,
        wrapper=wrapper,
        entity=entity,
    )[0]


def _merged_metadata_references(
    values: tuple[object, ...], *, wrapper: str, entity: str
) -> dict[str, list[dict[str, Any]]]:
    return _merged_metadata_references_with_truncation(
        values,
        wrapper=wrapper,
        entity=entity,
    )[0]


def _merged_metadata_references_with_truncation(
    values: tuple[object, ...],
    *,
    wrapper: str,
    entity: str,
    maximum_items: int = 100,
    maximum_characters: int = 1_000,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    merged: dict[str, dict[str, Any]] = {}
    truncated = False
    for value in values:
        references, value_truncated = _metadata_references_with_truncation(
            value,
            wrapper=wrapper,
            entity=entity,
            maximum_items=maximum_items,
            maximum_characters=maximum_characters,
        )
        truncated = truncated or value_truncated
        for item in references:
            reference = item[entity]
            identity = str(reference.get("urn") or reference.get("name"))
            merged[identity] = item
    return (
        {wrapper: [merged[key] for key in sorted(merged)[:maximum_items]]},
        truncated or len(merged) > maximum_items,
    )


def _schema_fields(
    entity: dict[str, Any],
) -> tuple[tuple[dict[str, Any], ...], int, bool, bool]:
    schema_metadata = entity.get("schemaMetadata")
    schema_document = schema_metadata if isinstance(schema_metadata, dict) else {}
    raw_fields = schema_document.get("fields")
    base_fields = raw_fields if isinstance(raw_fields, list) else []
    editable_metadata = entity.get("editableSchemaMetadata")
    editable_document = editable_metadata if isinstance(editable_metadata, dict) else {}
    raw_editable_fields = editable_document.get("editableSchemaFieldInfo")
    editable_fields = raw_editable_fields if isinstance(raw_editable_fields, list) else []
    selected_paths: list[str] = []
    observed_paths: set[str] = set()
    truncated = False
    for raw_field in chain(base_fields, editable_fields):
        if not isinstance(raw_field, dict):
            continue
        raw_field_path = raw_field.get("fieldPath")
        field_path = raw_field_path.strip() if isinstance(raw_field_path, str) else ""
        if not field_path or field_path in observed_paths:
            continue
        if len(field_path) > MAX_DATAHUB_SCHEMA_FIELD_PATH_CHARACTERS:
            raise ExternalDependencyError(
                "DataHub returned a schema field path larger than the supported limit.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        if len(observed_paths) >= MAX_CATALOG_SCHEMA_FIELDS:
            truncated = True
            break
        observed_paths.add(field_path)
        selected_paths.append(field_path)
    selected_path_set = set(selected_paths)
    base_by_path: dict[str, dict[str, Any]] = {}
    editable_by_path: dict[str, dict[str, Any]] = {}
    for target, values in (
        (base_by_path, base_fields),
        (editable_by_path, editable_fields),
    ):
        for item in values:
            raw_path = item.get("fieldPath") if isinstance(item, dict) else None
            path = raw_path.strip() if isinstance(raw_path, str) else ""
            if path in selected_path_set:
                target[path] = item
    merged_fields: list[dict[str, Any]] = []
    for field_path in selected_paths:
        base = base_by_path.get(field_path, {})
        editable = editable_by_path.get(field_path, {})
        field: dict[str, Any] = {"fieldPath": field_path}
        for key in ("type", "nativeDataType"):
            value = base.get(key)
            if isinstance(value, str) and value:
                field[key] = value[:MAX_DATAHUB_SCHEMA_FIELD_TYPE_CHARACTERS]
                field[f"{key}_truncated"] = len(value) > MAX_DATAHUB_SCHEMA_FIELD_TYPE_CHARACTERS
        label = base.get("label")
        if isinstance(label, str) and label.strip():
            normalized_label = label.strip()
            field["label"] = normalized_label[:MAX_DATAHUB_SCHEMA_FIELD_LABEL_CHARACTERS]
            field["label_truncated"] = (
                len(normalized_label) > MAX_DATAHUB_SCHEMA_FIELD_LABEL_CHARACTERS
            )
        description = editable.get("description", base.get("description"))
        if isinstance(description, str):
            field["description"] = description[:MAX_DATAHUB_SCHEMA_FIELD_DESCRIPTION_CHARACTERS]
            field["description_truncated"] = (
                len(description) > MAX_DATAHUB_SCHEMA_FIELD_DESCRIPTION_CHARACTERS
            )
        schema_field_entity = base.get("schemaFieldEntity")
        schema_field_document = schema_field_entity if isinstance(schema_field_entity, dict) else {}
        field["globalTags"], field["tags_truncated"] = _merged_metadata_references_with_truncation(
            (
                base.get("globalTags"),
                schema_field_document.get("globalTags"),
                editable.get("globalTags"),
            ),
            wrapper="tags",
            entity="tag",
            maximum_items=MAX_DATAHUB_SCHEMA_FIELD_REFERENCES,
            maximum_characters=MAX_DATAHUB_SCHEMA_FIELD_REFERENCE_CHARACTERS,
        )
        field["glossaryTerms"], field["terms_truncated"] = (
            _merged_metadata_references_with_truncation(
                (
                    base.get("glossaryTerms"),
                    schema_field_document.get("glossaryTerms"),
                    editable.get("glossaryTerms"),
                ),
                wrapper="terms",
                entity="term",
                maximum_items=MAX_DATAHUB_SCHEMA_FIELD_REFERENCES,
                maximum_characters=MAX_DATAHUB_SCHEMA_FIELD_REFERENCE_CHARACTERS,
            )
        )
        merged_fields.append(field)
    total = len(observed_paths) + (1 if truncated else 0)
    return tuple(merged_fields), total, truncated, not truncated


def _dataset_quality(value: object) -> dict[str, Any]:
    profiles = value if isinstance(value, list) else []
    profile = profiles[0] if profiles and isinstance(profiles[0], dict) else {}
    partition_spec = profile.get("partitionSpec")
    if (
        not isinstance(partition_spec, dict)
        or partition_spec.get("type") != "FULL_TABLE"
        or partition_spec.get("partition") != "FULL_TABLE_SNAPSHOT"
    ):
        return {}
    quality: dict[str, Any] = {}
    for source_key, response_key in (
        ("rowCount", "rowCount"),
        ("columnCount", "columnCount"),
        ("sizeInBytes", "sizeInBytes"),
    ):
        raw_value = profile.get(source_key)
        if isinstance(raw_value, int) and not isinstance(raw_value, bool) and raw_value >= 0:
            quality[response_key] = raw_value
    profiled_at = _datahub_timestamp(profile.get("timestampMillis"))
    if profiled_at is not None:
        quality["profiledAt"] = profiled_at.isoformat()
    return quality


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


def _column_names_with_truncation(value: object) -> tuple[tuple[str, ...], bool]:
    raw_fields = value.get("fields") if isinstance(value, dict) else []
    fields = raw_fields if isinstance(raw_fields, list) else []
    raw_names = {
        field["fieldPath"].strip()
        for field in fields
        if isinstance(field, dict)
        and isinstance(field.get("fieldPath"), str)
        and field["fieldPath"].strip()
    }
    names = {name[:500] for name in raw_names}
    return tuple(sorted(names)[:1_000]), len(names) > 1_000 or any(
        len(name) > 500 for name in raw_names
    )


def _column_names(value: object) -> tuple[str, ...]:
    return _column_names_with_truncation(value)[0]


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
        catalog_scan_snapshot_consistent: bool = False,
        catalog_scan_snapshot_evidence_reference: str | None = None,
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
        self._lineage_traversal_concurrency = max(1, min(maximum_concurrency, 10))
        self._queue_timeout_seconds = queue_timeout_seconds
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_open_seconds = circuit_open_seconds
        evidence_reference = (
            catalog_scan_snapshot_evidence_reference.strip()
            if catalog_scan_snapshot_evidence_reference
            else None
        )
        if catalog_scan_snapshot_consistent and (
            version_enforcement != "enforce"
            or expected_version is None
            or evidence_reference is None
            or len(evidence_reference) > 500
        ):
            raise ValueError(
                "Verified catalog scan snapshots require enforced version and bounded evidence."
            )
        self._catalog_scan_snapshot_consistent = catalog_scan_snapshot_consistent
        self._catalog_scan_snapshot_evidence_reference = (
            evidence_reference if catalog_scan_snapshot_consistent else None
        )
        self._catalog_scan_snapshot_contract_hash: str | None
        if catalog_scan_snapshot_consistent:
            assert expected_version is not None
            assert evidence_reference is not None
            self._catalog_scan_snapshot_contract_hash = _catalog_snapshot_contract_hash(
                base_url=self._base_url,
                expected_version=expected_version,
                allowed_versions=allowed_versions,
                evidence_reference=evidence_reference,
                version_enforcement=version_enforcement,
            )
        else:
            self._catalog_scan_snapshot_contract_hash = None
        self._circuit_lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._half_open_in_flight = False
        self._telemetry = telemetry

    @property
    def observed_version(self) -> str | None:
        return self._observed_version

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
                    request = self._client.build_request(method, url, **kwargs)
                    streamed_response = await self._client.send(request, stream=True)
                    try:
                        content_length = streamed_response.headers.get("content-length")
                        if content_length is not None:
                            try:
                                declared_size = int(content_length)
                            except ValueError:
                                declared_size = 0
                            if declared_size > MAX_DATAHUB_RESPONSE_BYTES:
                                outcome = "response_too_large"
                                await self._record_success()
                                raise ExternalDependencyError(
                                    "DataHub returned a response larger than the configured limit.",
                                    dependency="datahub",
                                    retryable=False,
                                    provider_code="RESPONSE_TOO_LARGE",
                                )
                        response_body = bytearray()
                        async for chunk in streamed_response.aiter_bytes():
                            response_body.extend(chunk)
                            if len(response_body) > MAX_DATAHUB_RESPONSE_BYTES:
                                outcome = "response_too_large"
                                await self._record_success()
                                raise ExternalDependencyError(
                                    "DataHub returned a response larger than the configured limit.",
                                    dependency="datahub",
                                    retryable=False,
                                    provider_code="RESPONSE_TOO_LARGE",
                                )
                        response = httpx.Response(
                            streamed_response.status_code,
                            headers=streamed_response.headers,
                            content=bytes(response_body),
                            request=request,
                            extensions=streamed_response.extensions,
                        )
                    finally:
                        await streamed_response.aclose()
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
        if (
            not isinstance(entity, dict)
            or entity.get("urn") != external_urn
            or entity.get("type") != "DATASET"
        ):
            raise ExternalDependencyError(
                "DataHub returned an asset that does not match the requested dataset.",
                dependency="datahub",
                retryable=False,
                provider_code=("NOT_FOUND" if not isinstance(entity, dict) else "INVALID_RESPONSE"),
            )
        ownership = entity.get("ownership")
        ownership_document = ownership if isinstance(ownership, dict) else {}
        owners, owners_truncated = _metadata_references_with_truncation(
            ownership_document,
            wrapper="owners",
            entity="owner",
        )
        global_tags = entity.get("globalTags")
        tags_document = global_tags if isinstance(global_tags, dict) else {}
        tags, tags_truncated = _metadata_names_with_truncation(
            tags_document,
            wrapper="tags",
            entity="tag",
        )
        glossary_terms = entity.get("glossaryTerms")
        glossary_document = glossary_terms if isinstance(glossary_terms, dict) else {}
        glossary, glossary_truncated = _metadata_references_with_truncation(
            glossary_document,
            wrapper="terms",
            entity="term",
        )
        now = datetime.now(UTC)
        properties = entity.get("properties")
        properties_document = properties if isinstance(properties, dict) else {}
        editable_properties = entity.get("editableProperties")
        (
            schema_fields,
            schema_fields_total,
            schema_fields_truncated,
            schema_fields_total_exact,
        ) = _schema_fields(entity)
        description = _preferred_description(
            properties=properties_document,
            editable_properties=editable_properties,
        )
        return DataHubAssetEnrichment(
            ownership=owners,
            glossary_terms=glossary,
            tags=tags,
            schema_fields=schema_fields,
            quality=_dataset_quality(entity.get("latestFullTableProfile")),
            raw_version=canonical_json_hash(entity),
            observed_at=now,
            created_at=_datahub_timestamp(properties_document.get("created")),
            description=description[:10_000] if description is not None else None,
            schema_fields_total=schema_fields_total,
            schema_fields_truncated=schema_fields_truncated,
            schema_fields_total_exact=schema_fields_total_exact,
            ownership_truncated=owners_truncated,
            glossary_terms_truncated=glossary_truncated,
            tags_truncated=tags_truncated,
            description_truncated=description is not None and len(description) > 10_000,
        )

    async def get_lineage(
        self, *, external_urn: str, direction: str, depth: int
    ) -> DataHubLineagePage:
        if (
            direction not in {"UPSTREAM", "DOWNSTREAM"}
            or not 1 <= depth <= 3
            or not 1 <= len(external_urn) <= MAX_DATAHUB_EXTERNAL_URN_CHARACTERS
        ):
            raise ValueError("Lineage direction or depth is invalid.")
        # DataHub's direct Dataset.lineage contract is the stable v1.6 UI
        # contract.  Traverse it breadth-first so DataRiver keeps the public
        # 1..3 hop bound without depending on the optional lineage search
        # index/resolver used by scrollAcrossLineage.
        maximum_nodes = 100
        frontier: list[tuple[str, tuple[str, ...]]] = [(external_urn, (external_urn,))]
        queried = {external_urn}
        discovered: dict[str, DataHubLineageNode] = {}
        partial = False
        for degree in range(1, depth + 1):
            next_frontier: list[tuple[str, tuple[str, ...]]] = []
            batch_size = self._lineage_traversal_concurrency
            for batch_start in range(0, len(frontier), batch_size):
                batch = frontier[batch_start : batch_start + batch_size]
                responses = await asyncio.gather(
                    *(
                        self._graphql(
                            LINEAGE_QUERY,
                            {
                                "urn": source_urn,
                                "input": {
                                    "direction": direction,
                                    "start": 0,
                                    "count": 100,
                                },
                            },
                        )
                        for source_urn, _ in batch
                    )
                )
                for (_, source_path), data in zip(batch, responses, strict=True):
                    dataset = data.get("dataset")
                    lineage = dataset.get("lineage") if isinstance(dataset, dict) else None
                    relationships = (
                        lineage.get("relationships") if isinstance(lineage, dict) else None
                    )
                    if not isinstance(lineage, dict) or not isinstance(relationships, list):
                        raise ExternalDependencyError(
                            "DataHub returned an invalid lineage contract.",
                            dependency="datahub",
                            retryable=False,
                            provider_code="INVALID_RESPONSE",
                        )
                    raw_total = lineage.get("total")
                    if raw_total is None:
                        relationship_total = len(relationships)
                        partial = True
                    else:
                        try:
                            relationship_total = int(raw_total)
                        except (TypeError, ValueError) as error:
                            raise ExternalDependencyError(
                                "DataHub returned invalid lineage pagination.",
                                dependency="datahub",
                                retryable=False,
                                provider_code="INVALID_RESPONSE",
                            ) from error
                    raw_filtered = lineage.get("filtered")
                    if raw_filtered is None:
                        partial = True
                    else:
                        try:
                            filtered = int(raw_filtered)
                        except (TypeError, ValueError) as error:
                            raise ExternalDependencyError(
                                "DataHub returned invalid lineage pagination.",
                                dependency="datahub",
                                retryable=False,
                                provider_code="INVALID_RESPONSE",
                            ) from error
                        if filtered < 0:
                            raise ExternalDependencyError(
                                "DataHub returned invalid lineage pagination.",
                                dependency="datahub",
                                retryable=False,
                                provider_code="INVALID_RESPONSE",
                            )
                        partial = partial or filtered > 0
                    if relationship_total < 0:
                        raise ExternalDependencyError(
                            "DataHub returned invalid lineage pagination.",
                            dependency="datahub",
                            retryable=False,
                            provider_code="INVALID_RESPONSE",
                        )
                    partial = partial or relationship_total > len(relationships)
                    for relationship in relationships:
                        entity = (
                            relationship.get("entity") if isinstance(relationship, dict) else None
                        )
                        urn = entity.get("urn") if isinstance(entity, dict) else None
                        entity_type = entity.get("type") if isinstance(entity, dict) else None
                        if entity is None:
                            partial = True
                            continue
                        if (
                            not isinstance(urn, str)
                            or not 1 <= len(urn) <= MAX_DATAHUB_EXTERNAL_URN_CHARACTERS
                        ):
                            raise ExternalDependencyError(
                                "DataHub returned an invalid lineage result.",
                                dependency="datahub",
                                retryable=False,
                                provider_code="INVALID_RESPONSE",
                            )
                        if entity_type != "DATASET":
                            partial = True
                            continue
                        if urn in source_path:
                            continue
                        path = (*source_path, urn)
                        if urn not in discovered:
                            if len(discovered) >= maximum_nodes:
                                partial = True
                                continue
                            discovered[urn] = DataHubLineageNode(
                                external_urn=urn,
                                degree=degree,
                                paths=(path,),
                                truncated_children=False,
                            )
                        if degree < depth and entity_type == "DATASET" and urn not in queried:
                            queried.add(urn)
                            next_frontier.append((urn, path))
            frontier = next_frontier
            if not frontier:
                break
        return DataHubLineagePage(
            items=tuple(discovered.values()),
            total=len(discovered),
            partial=partial,
        )

    async def scan_assets(self, *, cursor: str | None, limit: int) -> DataHubScanPage:
        if not 1 <= limit <= 100 or (cursor is not None and (not cursor or len(cursor) > 4_096)):
            raise ValueError("DataHub scan bounds are invalid.")
        if self._catalog_scan_snapshot_consistent and cursor is None:
            observed_version = await self._reported_version(force=True)
            if observed_version not in self._accepted_versions:
                raise ExternalDependencyError(
                    "DataHub does not match the approved reconciliation release contract.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="VERSION_MISMATCH",
                )
        scan_input: dict[str, Any] = {
            "types": ["DATASET"],
            "query": "*",
            "count": limit,
            "keepAlive": "5m",
            "sortInput": {
                "sortCriteria": [{"field": "urn", "sortOrder": "ASCENDING"}],
            },
            "searchFlags": {
                "skipHighlighting": True,
                "skipAggregates": True,
            },
        }
        if cursor is not None:
            scan_input["scrollId"] = cursor
        data = await self._graphql(
            CATALOG_SCAN_QUERY,
            {"input": scan_input},
        )
        result = data.get("scrollAcrossEntities")
        if not isinstance(result, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid scan contract.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        raw_results = result.get("searchResults")
        if not isinstance(raw_results, list) or len(raw_results) > limit:
            raise ExternalDependencyError(
                "DataHub returned an invalid scan result list.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        items: list[DataHubScanAsset] = []
        observed_urns: set[str] = set()
        for raw in raw_results:
            entity = raw.get("entity") if isinstance(raw, dict) else None
            external_urn = entity.get("urn") if isinstance(entity, dict) else None
            if (
                not isinstance(entity, dict)
                or not isinstance(external_urn, str)
                or not 1 <= len(external_urn) <= MAX_DATAHUB_EXTERNAL_URN_CHARACTERS
                or entity.get("type") != "DATASET"
                or external_urn in observed_urns
            ):
                raise ExternalDependencyError(
                    "DataHub returned an invalid scan entity.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            observed_urns.add(external_urn)
            properties = entity.get("properties")
            if properties is not None and not isinstance(properties, dict):
                raise ExternalDependencyError(
                    "DataHub returned invalid dataset properties.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            properties = properties if isinstance(properties, dict) else {}
            editable_properties = entity.get("editableProperties")
            platform = entity.get("platform")
            if platform is not None and not isinstance(platform, dict):
                raise ExternalDependencyError(
                    "DataHub returned an invalid platform.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            platform_name = platform.get("name") if isinstance(platform, dict) else None
            system_ref = platform.get("urn") if isinstance(platform, dict) else None
            if (platform_name is not None and not isinstance(platform_name, str)) or (
                system_ref is not None and not isinstance(system_ref, str)
            ):
                raise ExternalDependencyError(
                    "DataHub returned an invalid platform identity.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            domain_wrapper = entity.get("domain")
            if domain_wrapper is not None and not isinstance(domain_wrapper, dict):
                raise ExternalDependencyError(
                    "DataHub returned an invalid domain.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            domain = domain_wrapper.get("domain") if isinstance(domain_wrapper, dict) else None
            if domain is not None and not isinstance(domain, dict):
                raise ExternalDependencyError(
                    "DataHub returned an invalid domain reference.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            domain_ref = domain.get("urn") if isinstance(domain, dict) else None
            if domain_ref is not None and not isinstance(domain_ref, str):
                raise ExternalDependencyError(
                    "DataHub returned an invalid domain identity.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            ownership = entity.get("ownership")
            if ownership is not None and not isinstance(ownership, dict):
                raise ExternalDependencyError(
                    "DataHub returned invalid ownership.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            raw_owners = ownership.get("owners", []) if isinstance(ownership, dict) else []
            if not isinstance(raw_owners, list):
                raise ExternalDependencyError(
                    "DataHub returned an invalid owner collection.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            owner_refs: list[str] = []
            for owner_item in raw_owners:
                owner = owner_item.get("owner") if isinstance(owner_item, dict) else None
                owner_urn = owner.get("urn") if isinstance(owner, dict) else None
                if not isinstance(owner_urn, str) or not owner_urn:
                    raise ExternalDependencyError(
                        "DataHub returned an invalid owner identity.",
                        dependency="datahub",
                        retryable=False,
                        provider_code="INVALID_RESPONSE",
                    )
                owner_refs.append(owner_urn)
            owner_refs.sort()
            property_name = properties.get("name")
            entity_name = entity.get("name")
            if (property_name is not None and not isinstance(property_name, str)) or (
                entity_name is not None and not isinstance(entity_name, str)
            ):
                raise ExternalDependencyError(
                    "DataHub returned an invalid dataset name.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            name = property_name or entity_name or external_urn
            database_name, schema_name = _catalog_hierarchy_from_browse_path(
                entity.get("browsePathV2")
            )
            if database_name is None:
                database_name = _custom_property_value(
                    properties.get("customProperties") if isinstance(properties, dict) else None,
                    key="datariver.seed.database_name",
                )
            description = _preferred_description(
                properties=properties,
                editable_properties=editable_properties,
            )
            tags, tags_truncated = _metadata_names_with_truncation(
                entity.get("globalTags"),
                wrapper="tags",
                entity="tag",
            )
            terms, terms_truncated = _metadata_names_with_truncation(
                entity.get("glossaryTerms"),
                wrapper="terms",
                entity="term",
            )
            column_names, column_names_truncated = _column_names_with_truncation(
                entity.get("schemaMetadata")
            )
            items.append(
                DataHubScanAsset(
                    external_urn=external_urn,
                    asset_type=_dataset_asset_type(entity),
                    name=str(name)[:500],
                    description=description[:10_000] if description else None,
                    platform=platform_name[:100] if platform_name else None,
                    database_name=database_name[:255] if database_name else None,
                    schema_name=schema_name[:255] if schema_name else None,
                    domain_ref=domain_ref[:1_000] if domain_ref else None,
                    system_ref=system_ref[:1_000] if system_ref else None,
                    owner_ref=owner_refs[0][:1_000] if owner_refs else None,
                    classification=_classification_from_tags(entity.get("globalTags")),
                    source_version=canonical_json_hash(entity),
                    tags=tags,
                    glossary_terms=terms,
                    column_names=column_names,
                    created_at=_datahub_timestamp(properties.get("created")),
                    description_truncated=description is not None and len(description) > 10_000,
                    tags_truncated=tags_truncated,
                    glossary_terms_truncated=terms_truncated,
                    column_names_truncated=column_names_truncated,
                )
            )
        count_value = result.get("count")
        total_value = result.get("total")
        next_cursor_value = result.get("nextScrollId")
        if (
            isinstance(count_value, bool)
            or not isinstance(count_value, int)
            or count_value < 0
            or isinstance(total_value, bool)
            or not isinstance(total_value, int)
            or total_value < 0
        ):
            raise ExternalDependencyError(
                "DataHub returned invalid scan pagination.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        count = count_value
        total = total_value
        if (
            count > limit
            or count != min(limit, total)
            or len(items) > count
            or (
                next_cursor_value is not None
                and (
                    not isinstance(next_cursor_value, str)
                    or not next_cursor_value
                    or len(next_cursor_value) > 4_096
                    or next_cursor_value == cursor
                )
            )
            or (not items and next_cursor_value is not None)
            or (cursor is None and len(items) < total and next_cursor_value is None)
        ):
            raise ExternalDependencyError(
                "DataHub returned inconsistent scan pagination.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        return DataHubScanPage(
            items=tuple(items),
            next_cursor=next_cursor_value,
            total=total,
            observed_at=datetime.now(UTC),
            snapshot_consistent=self._catalog_scan_snapshot_consistent,
            snapshot_evidence_reference=self._catalog_scan_snapshot_evidence_reference,
            snapshot_contract_hash=self._catalog_scan_snapshot_contract_hash,
            snapshot_provider_version=(
                self._observed_version if self._catalog_scan_snapshot_consistent else None
            ),
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

    async def scan_vocabulary(
        self,
        *,
        kind: str,
        cursor: str | None,
        limit: int,
    ) -> DataHubVocabularyScanPage:
        if (
            kind not in {"DOMAIN", "TAG", "TERM"}
            or not 1 <= limit <= 100
            or (cursor is not None and (not cursor or len(cursor) > 4_096))
        ):
            raise ValueError("DataHub vocabulary scan bounds are invalid.")
        if self._catalog_scan_snapshot_consistent and cursor is None:
            observed_version = await self._reported_version(force=True)
            if observed_version not in self._accepted_versions:
                raise ExternalDependencyError(
                    "DataHub does not match the approved vocabulary release contract.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="VERSION_MISMATCH",
                )
        entity_type = {
            "DOMAIN": "DOMAIN",
            "TAG": "TAG",
            "TERM": "GLOSSARY_TERM",
        }[kind]
        scan_input: dict[str, Any] = {
            "types": [entity_type],
            "query": "*",
            "count": limit,
            "keepAlive": "5m",
            "sortInput": {
                "sortCriteria": [{"field": "urn", "sortOrder": "ASCENDING"}],
            },
            "searchFlags": {
                "skipHighlighting": True,
                "skipAggregates": True,
            },
        }
        if cursor is not None:
            scan_input["scrollId"] = cursor
        data = await self._graphql(VOCABULARY_SCAN_QUERY, {"input": scan_input})
        result = data.get("scrollAcrossEntities")
        if not isinstance(result, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid vocabulary scan contract.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        raw_results = result.get("searchResults")
        if not isinstance(raw_results, list) or len(raw_results) > limit:
            raise ExternalDependencyError(
                "DataHub returned an invalid vocabulary scan result list.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        expected_prefix = {
            "DOMAIN": "urn:li:domain:",
            "TAG": "urn:li:tag:",
            "TERM": "urn:li:glossaryTerm:",
        }[kind]
        items: list[DataHubVocabularyEntry] = []
        observed_refs: set[str] = set()
        for raw in raw_results:
            entity = raw.get("entity") if isinstance(raw, dict) else None
            provider_ref = entity.get("urn") if isinstance(entity, dict) else None
            if (
                not isinstance(entity, dict)
                or entity.get("type") != entity_type
                or not isinstance(provider_ref, str)
                or not provider_ref.startswith(expected_prefix)
                or not 1 <= len(provider_ref) <= 1_000
                or provider_ref in observed_refs
            ):
                raise ExternalDependencyError(
                    "DataHub returned an invalid vocabulary identity.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            observed_refs.add(provider_ref)
            if kind == "TAG":
                name = entity.get("name")
            else:
                properties = entity.get("properties")
                name = properties.get("name") if isinstance(properties, dict) else None
            if (
                not isinstance(name, str)
                or not (display_name := name.strip())
                or len(display_name) > 500
            ):
                raise ExternalDependencyError(
                    "DataHub returned an invalid vocabulary display name.",
                    dependency="datahub",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            items.append(
                DataHubVocabularyEntry(
                    provider_ref=provider_ref,
                    kind=kind,
                    display_name=display_name,
                    source_version=canonical_json_hash(entity),
                )
            )
        count_value = result.get("count")
        total_value = result.get("total")
        next_cursor = result.get("nextScrollId")
        if (
            isinstance(count_value, bool)
            or not isinstance(count_value, int)
            or count_value < 0
            or count_value != len(items)
            or isinstance(total_value, bool)
            or not isinstance(total_value, int)
            or total_value < len(items)
            or (
                next_cursor is not None
                and (
                    not isinstance(next_cursor, str)
                    or not next_cursor
                    or len(next_cursor) > 4_096
                    or next_cursor == cursor
                )
            )
            or (not items and next_cursor is not None)
            or (cursor is None and len(items) < total_value and next_cursor is None)
        ):
            raise ExternalDependencyError(
                "DataHub returned inconsistent vocabulary pagination.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        evidence_reference = self._catalog_scan_snapshot_evidence_reference
        return DataHubVocabularyScanPage(
            items=tuple(items),
            next_cursor=next_cursor,
            total=total_value,
            observed_at=datetime.now(UTC),
            snapshot_consistent=self._catalog_scan_snapshot_consistent,
            snapshot_evidence_reference=evidence_reference,
            snapshot_contract_hash=(
                _vocabulary_snapshot_contract_hash(
                    base_url=self._base_url,
                    accepted_versions=self._accepted_versions,
                    evidence_reference=evidence_reference,
                    kind=kind,
                )
                if self._catalog_scan_snapshot_consistent and evidence_reference is not None
                else None
            ),
            snapshot_provider_version=(
                self._observed_version if self._catalog_scan_snapshot_consistent else None
            ),
        )

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
