from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataCandidateDraft,
    CatalogMetadataCandidateKind,
    compile_catalog_metadata_candidates,
)
from datariver.application.dto import CatalogAssetIndex, DataHubAspectSnapshot
from datariver.application.errors import ExternalDependencyError
from datariver.application.services.catalog_metadata_compiler import (
    CatalogMetadataVocabularyReference,
    compile_catalog_metadata_mutation,
)
from datariver.application.typed_upload_profiles import CATALOG_METADATA_ROWS_CSV_V1
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")
ASSET_ID = UUID("00000000-0000-4000-8000-000000000002")
TERM_ID = UUID("00000000-0000-4000-8000-000000000003")
TAG_ID = UUID("00000000-0000-4000-8000-000000000004")
DOMAIN_ID = UUID("00000000-0000-4000-8000-000000000005")


def _asset() -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=ASSET_ID,
        workspace_id=WORKSPACE_ID,
        external_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,db.public.events,PROD)",
        asset_type="DATASET",
        name="events",
        description=None,
        platform="postgres",
        domain_id=uuid4(),
        system_id=uuid4(),
        owner_department_id=uuid4(),
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="asset-v1",
        observed_at=datetime.now(UTC),
        database_name="db",
        schema_name="public",
    )


def _candidate(*rows: tuple[str, ...]) -> CatalogMetadataCandidateDraft:
    return compile_catalog_metadata_candidates(
        workspace_id=WORKSPACE_ID,
        rows=tuple(enumerate(rows, start=1)),
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )[0]


def _row(kind: str, field: str, operation: str, value: str, ref: str) -> tuple[str, ...]:
    return (
        kind,
        str(ASSET_ID),
        "postgres",
        "db",
        "public",
        "events",
        field,
        operation,
        value,
        ref,
    )


def _snapshot(
    asset: CatalogAssetIndex,
    aspect: str,
    document: dict[str, Any],
) -> DataHubAspectSnapshot:
    return DataHubAspectSnapshot(
        urn=asset.external_urn,
        aspect_name=aspect,
        document=document,
        content_hash=canonical_json_hash(document),
        source_version="provider-v1",
        observed_at=datetime.now(UTC),
    )


def test_compiler_merges_all_column_rows_and_preserves_unknown_fields() -> None:
    asset = _asset()
    candidate = _candidate(
        _row("COLUMN_DESCRIPTION", "event_id", "SET", "Stable identifier", ""),
        _row("COLUMN_DESCRIPTION", "payload", "CLEAR", "", ""),
    )
    document = {
        "schemaName": "events",
        "unknown": {"preserve": True},
        "fields": [
            {"fieldPath": "event_id", "description": "old", "nativeDataType": "uuid"},
            {"fieldPath": "payload", "description": "remove", "nativeDataType": "jsonb"},
        ],
    }

    compiled = compile_catalog_metadata_mutation(
        asset=asset,
        snapshot=_snapshot(asset, "schemaMetadata", document),
        candidate=candidate,
        vocabulary={},
    )

    assert compiled.current_descriptions == (
        ("event_id", "old"),
        ("payload", "remove"),
    )
    assert compiled.proposed_document["unknown"] == {"preserve": True}
    fields = compiled.proposed_document["fields"]
    assert isinstance(fields, list)
    assert fields[0]["description"] == "Stable identifier"
    assert "description" not in fields[1]


def test_compiler_adds_terms_to_current_set_from_local_vocabulary_ids() -> None:
    asset = _asset()
    candidate = _candidate(_row("DATASET_TERM", "", "ADD", "", str(TERM_ID)))
    document = {"terms": [{"urn": "urn:li:glossaryTerm:existing"}], "audit": {"keep": 1}}

    compiled = compile_catalog_metadata_mutation(
        asset=asset,
        snapshot=_snapshot(asset, "glossaryTerms", document),
        candidate=candidate,
        vocabulary={
            TERM_ID: CatalogMetadataVocabularyReference(
                vocabulary_id=TERM_ID,
                kind="TERM",
                provider_ref="urn:li:glossaryTerm:new",
                source_version="term-v1",
            )
        },
    )

    assert compiled.current_refs == ("urn:li:glossaryTerm:existing",)
    assert compiled.proposed_refs == (
        "urn:li:glossaryTerm:existing",
        "urn:li:glossaryTerm:new",
    )
    assert compiled.proposed_document["audit"] == {"keep": 1}


def test_compiler_uses_the_validated_datahub_domain_string_contract() -> None:
    asset = _asset()
    candidate = _candidate(_row("DATASET_DOMAIN", "", "SET", "", str(DOMAIN_ID)))
    document = {"domains": ["urn:li:domain:old"], "audit": {"keep": 1}}

    compiled = compile_catalog_metadata_mutation(
        asset=asset,
        snapshot=_snapshot(asset, "domains", document),
        candidate=candidate,
        vocabulary={
            DOMAIN_ID: CatalogMetadataVocabularyReference(
                vocabulary_id=DOMAIN_ID,
                kind="DOMAIN",
                provider_ref="urn:li:domain:manufacturing",
                source_version="domain-v1",
            )
        },
    )

    assert compiled.current_refs == ("urn:li:domain:old",)
    assert compiled.proposed_refs == ("urn:li:domain:manufacturing",)
    assert compiled.proposed_document == {
        "domains": ["urn:li:domain:manufacturing"],
        "audit": {"keep": 1},
    }


def test_compiler_fails_closed_on_vocabulary_kind_or_target_drift() -> None:
    asset = _asset()
    candidate = _candidate(_row("DATASET_TAG", "", "ADD", "", str(TAG_ID)))
    snapshot = _snapshot(asset, "globalTags", {"tags": []})

    with pytest.raises(ConflictError, match="vocabulary"):
        compile_catalog_metadata_mutation(
            asset=asset,
            snapshot=snapshot,
            candidate=candidate,
            vocabulary={
                TAG_ID: CatalogMetadataVocabularyReference(
                    vocabulary_id=TAG_ID,
                    kind="TERM",
                    provider_ref="urn:li:tag:new",
                    source_version="tag-v1",
                )
            },
        )

    with pytest.raises(ConflictError, match="target"):
        compile_catalog_metadata_mutation(
            asset=asset,
            snapshot=snapshot,
            candidate=CatalogMetadataCandidateDraft(
                workspace_id=uuid4(),
                ordinal=candidate.ordinal,
                target_asset_id=candidate.target_asset_id,
                platform=candidate.platform,
                database_name=candidate.database_name,
                schema_name=candidate.schema_name,
                table_name=candidate.table_name,
                record_kind=candidate.record_kind,
                candidate_kind=CatalogMetadataCandidateKind.DATASET_TAG_ADD,
                aspect_name=candidate.aspect_name,
                rows=candidate.rows,
                submitted_identity_hash=candidate.submitted_identity_hash,
                candidate_hash=candidate.candidate_hash,
            ),
            vocabulary={},
        )


@pytest.mark.parametrize(
    ("aspect_name", "document"),
    [
        ("domains", {"domains": [{"urn": "urn:li:domain:legacy-shape"}]}),
        ("globalTags", {"tags": ["urn:li:tag:malformed"]}),
        ("glossaryTerms", {"terms": [{"urn": 42}]}),
        (
            "globalTags",
            {
                "tags": [
                    {"tag": "urn:li:tag:duplicate"},
                    {"tag": "urn:li:tag:duplicate"},
                ]
            },
        ),
    ],
)
def test_compiler_rejects_malformed_current_controlled_metadata_without_data_loss(
    aspect_name: str,
    document: dict[str, object],
) -> None:
    asset = _asset()
    kind, reference_id, record_kind, provider_ref = {
        "domains": ("DOMAIN", DOMAIN_ID, "DATASET_DOMAIN", "urn:li:domain:new"),
        "globalTags": ("TAG", TAG_ID, "DATASET_TAG", "urn:li:tag:new"),
        "glossaryTerms": ("TERM", TERM_ID, "DATASET_TERM", "urn:li:glossaryTerm:new"),
    }[aspect_name]
    operation = "SET" if record_kind == "DATASET_DOMAIN" else "ADD"
    candidate = _candidate(_row(record_kind, "", operation, "", str(reference_id)))

    with pytest.raises(ExternalDependencyError, match="controlled metadata"):
        compile_catalog_metadata_mutation(
            asset=asset,
            snapshot=_snapshot(asset, aspect_name, document),
            candidate=candidate,
            vocabulary={
                reference_id: CatalogMetadataVocabularyReference(
                    vocabulary_id=reference_id,
                    kind=kind,
                    provider_ref=provider_ref,
                    source_version="v1",
                )
            },
        )


def test_compiler_rejects_missing_or_unchanged_schema_field() -> None:
    asset = _asset()
    candidate = _candidate(_row("COLUMN_DESCRIPTION", "event_id", "SET", "Stable identifier", ""))
    with pytest.raises((ConflictError, ValidationError)):
        compile_catalog_metadata_mutation(
            asset=asset,
            snapshot=_snapshot(asset, "schemaMetadata", {"fields": []}),
            candidate=candidate,
            vocabulary={},
        )
    with pytest.raises(ValidationError, match="does not change"):
        compile_catalog_metadata_mutation(
            asset=asset,
            snapshot=_snapshot(
                asset,
                "schemaMetadata",
                {"fields": [{"fieldPath": "event_id", "description": "Stable identifier"}]},
            ),
            candidate=candidate,
            vocabulary={},
        )


@pytest.mark.parametrize(
    ("row", "aspect_name", "document", "vocabulary"),
    [
        (
            _row("TABLE_DESCRIPTION", "", "SET", "Same", ""),
            "datasetProperties",
            {"description": "Same"},
            {},
        ),
        (
            _row("COLUMN_DESCRIPTION", "event_id", "SET", "Same", ""),
            "schemaMetadata",
            {"fields": [{"fieldPath": "event_id", "description": "Same"}]},
            {},
        ),
        (
            _row("DATASET_DOMAIN", "", "SET", "", str(DOMAIN_ID)),
            "domains",
            {"domains": ["urn:li:domain:manufacturing"]},
            {
                DOMAIN_ID: CatalogMetadataVocabularyReference(
                    DOMAIN_ID,
                    "DOMAIN",
                    "urn:li:domain:manufacturing",
                    "domain-v1",
                )
            },
        ),
        (
            _row("DATASET_TERM", "", "ADD", "", str(TERM_ID)),
            "glossaryTerms",
            {"terms": [{"urn": "urn:li:glossaryTerm:wafer"}]},
            {
                TERM_ID: CatalogMetadataVocabularyReference(
                    TERM_ID,
                    "TERM",
                    "urn:li:glossaryTerm:wafer",
                    "term-v1",
                )
            },
        ),
        (
            _row("DATASET_TAG", "", "ADD", "", str(TAG_ID)),
            "globalTags",
            {"tags": [{"tag": "urn:li:tag:governed"}]},
            {
                TAG_ID: CatalogMetadataVocabularyReference(
                    TAG_ID,
                    "TAG",
                    "urn:li:tag:governed",
                    "tag-v1",
                )
            },
        ),
    ],
)
def test_compiler_rejects_noop_for_each_fixed_aspect(
    row: tuple[str, ...],
    aspect_name: str,
    document: dict[str, object],
    vocabulary: dict[UUID, CatalogMetadataVocabularyReference],
) -> None:
    asset = _asset()
    candidate = _candidate(row)

    with pytest.raises(ValidationError, match="does not change"):
        compile_catalog_metadata_mutation(
            asset=asset,
            snapshot=_snapshot(asset, aspect_name, document),
            candidate=candidate,
            vocabulary=vocabulary,
        )
