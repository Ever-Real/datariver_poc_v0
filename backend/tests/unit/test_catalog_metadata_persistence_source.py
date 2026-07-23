from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_catalog_metadata_vocabulary_resolver_is_local_typed_and_bounded() -> None:
    source = (ROOT / "src/datariver/infrastructure/db/catalog_metadata.py").read_text(
        encoding="utf-8"
    )
    resolver = source[
        source.index("class SqlCatalogMetadataVocabularyResolver") : source.index(
            "class SqlCatalogMetadataVocabularyProjection"
        )
    ]

    assert 'expected_kind not in {"DOMAIN", "TAG", "TERM"}' in resolver
    assert 'CatalogVocabularyEntryModel.lifecycle == "ACTIVE"' in resolver
    assert "len(unique_ids) > 100" in resolver
    assert "provider_ref=model.provider_ref" in resolver
    assert "search_vocabulary" not in resolver
    assert "DataHub" not in resolver


def test_catalog_metadata_publish_reauthorizes_before_evidence_insert() -> None:
    source = (ROOT / "src/datariver/infrastructure/db/bulk_registration.py").read_text(
        encoding="utf-8"
    )
    publish = source[
        source.index("    async def publish(") : source.index("    async def mark_failed(")
    ]

    reauthorization_call = "self._require_catalog_metadata_preparation_authorization("
    first_reauthorization = publish.index(reauthorization_call)
    second_reauthorization = publish.index(
        reauthorization_call,
        first_reauthorization + len(reauthorization_call),
    )
    receipt_insert = publish.index("UploadPreparationReceiptModel(")
    candidate_insert = publish.index("self._insert_catalog_metadata_candidates(")
    target_validation = publish.index("self._verify_current_catalog_metadata(")
    assert (
        first_reauthorization
        < target_validation
        < second_reauthorization
        < receipt_insert
        < candidate_insert
    )
    assert publish.count(reauthorization_call) == 2
    assert "lock_for_publication=False" in publish
    assert "lock_for_publication=True" in publish

    helper = source[
        source.index(
            "    async def _require_catalog_metadata_preparation_authorization("
        ) : source.index("    async def _verify_current_catalog_metadata(")
    ]
    assert "integration.reauthorize_catalog_metadata_preparation" in helper
    assert "CAST(:target_asset_ids AS uuid[])" in helper
    assert ":lock_for_publication" in helper
    assert '"requested_by": claim.requested_by' in helper
    assert '"worker_subject_id": claim.run_call.worker_subject_id' in helper
    assert '"CATALOG_METADATA_PREPARATION_DENIED"' in helper


def test_catalog_metadata_publish_replays_bounded_spool_without_full_candidate_tuple() -> None:
    source = (ROOT / "src/datariver/infrastructure/db/bulk_registration.py").read_text(
        encoding="utf-8"
    )
    publish = source[
        source.index("    async def publish(") : source.index("    async def mark_failed(")
    ]
    scanner = source[
        source.index("def _scan_catalog_metadata_candidates(") : source.index(
            "def _require_valid_catalog_metadata_candidate("
        )
    ]

    assert "tuple(catalog_candidates())" not in publish
    assert "staged_catalog_candidates = catalog_candidates" in publish
    assert "for candidate in candidates():" in scanner
    assert "target_asset_ids: set[UUID]" in scanner
    assert "list(candidates())" not in source
    assert "tuple(candidates())" not in source
