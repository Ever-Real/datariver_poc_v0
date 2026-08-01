from __future__ import annotations

import inspect
import tracemalloc

import pytest

from datariver.application.dto import DataHubScanAsset
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError
from datariver.infrastructure.db.catalog import (
    SqlCatalogProjectionWriter,
    _bounded_scan_asset,
    _catalog_query_condition,
    _match_fragments,
    _search_fields,
)


def test_datahub_projection_writer_keeps_provider_system_ref_out_of_canonical_system_id() -> None:
    source = inspect.getsource(SqlCatalogProjectionWriter.upsert_scan)

    assert "item.domain_ref is not None and item.system_ref is not None" in source
    assert '_scope_id("system", item.system_ref)' not in source
    assert "system_id = None" in source
    assert '"system_id": system_id' in source


def _compiled_query(fields: str) -> str:
    condition = _catalog_query_condition(
        "wafer yield", search_fields=_search_fields({"search_fields": fields})
    )
    return str(condition)


def test_catalog_search_field_vocabulary_covers_all_legacy_metadata_targets() -> None:
    compiled = _compiled_query("SCHEMA,TABLE,COLUMN,TAG,TERM,DESCRIPTION")

    assert "schema_name" in compiled
    assert "column_names" in compiled
    assert "tags" in compiled
    assert "glossary_terms" in compiled
    assert "description" in compiled
    assert compiled.count("jsonb_array_elements_text") == 2
    assert "CAST(catalog.assets_projection.tags AS VARCHAR)" not in compiled


def test_catalog_projection_writer_defensively_bounds_any_gateway_implementation() -> None:
    bounded = _bounded_scan_asset(
        DataHubScanAsset(
            external_urn="urn:li:dataset:bounded",
            asset_type="TABLE",
            name="bounded",
            description="d" * 10_001,
            platform="postgres",
            domain_ref=None,
            system_ref=None,
            owner_ref=None,
            classification=Classification.PUBLIC,
            source_version="v1",
            tags=tuple("t" * 1_001 for _ in range(101)),
            glossary_terms=tuple("g" * 1_001 for _ in range(101)),
            column_names=tuple("c" * 501 for _ in range(1_001)),
        )
    )

    assert len(bounded.description or "") == 10_000
    assert len(bounded.tags) == 100
    assert max(map(len, bounded.tags)) == 1_000
    assert len(bounded.glossary_terms) == 100
    assert max(map(len, bounded.glossary_terms)) == 1_000
    assert len(bounded.column_names) == 1_000
    assert max(map(len, bounded.column_names)) == 500
    assert bounded.description_truncated is True
    assert bounded.tags_truncated is True
    assert bounded.glossary_terms_truncated is True
    assert bounded.column_names_truncated is True


def test_catalog_projection_writer_rejects_an_oversized_identity() -> None:
    with pytest.raises(ValidationError, match="URN"):
        _bounded_scan_asset(
            DataHubScanAsset(
                external_urn="u" * 4_097,
                asset_type="TABLE",
                name="oversized",
                description=None,
                platform="postgres",
                domain_ref=None,
                system_ref=None,
                owner_ref=None,
                classification=Classification.PUBLIC,
                source_version="v1",
            )
        )


def test_catalog_match_fragments_explain_every_searchable_field() -> None:
    fragments = _match_fragments(
        name="wafer_events",
        description="Yield evidence",
        schema_name="manufacturing",
        column_names=("lot_id", "event_time"),
        tags=("tier:gold",),
        glossary_terms=("quality",),
        query="wafer yield manufacturing lot gold quality",
    )

    assert [fragment.field for fragment in fragments] == [
        "NAME",
        "DESCRIPTION",
        "SCHEMA",
        "COLUMN",
        "TAG",
        "TERM",
    ]
    assert tuple(term for fragment in fragments for term in fragment.matched_terms) == (
        "wafer",
        "yield",
        "manufacturing",
        "lot",
        "gold",
        "quality",
    )
    assert all(len(fragment.text) <= 242 for fragment in fragments)


def test_catalog_match_fragments_never_claim_a_term_outside_bounded_text() -> None:
    fragments = _match_fragments(
        name="unrelated",
        description=None,
        column_names=("first_match", "x" * 300, "last_match"),
        query="first last",
    )

    assert [fragment.field for fragment in fragments] == ["COLUMN", "COLUMN"]
    assert all(
        term.casefold() in fragment.text.casefold()
        for fragment in fragments
        for term in fragment.matched_terms
    )
    assert all(len(fragment.text) <= 240 for fragment in fragments)


def test_catalog_query_terms_are_bounded_before_sql_expansion() -> None:
    with pytest.raises(ValidationError):
        _catalog_query_condition(
            " ".join(f"term-{index}" for index in range(13)),
            search_fields=("TABLE",),
        )
    with pytest.raises(ValidationError):
        _catalog_query_condition("x" * 121, search_fields=("TABLE",))


def test_catalog_long_match_context_uses_bounded_transient_memory() -> None:
    description = f"first {'x' * 200_000} last"
    tracemalloc.start()
    try:
        fragments = _match_fragments(
            name="unrelated",
            description=description,
            query="first last",
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 2_000_000
    assert [fragment.matched_terms for fragment in fragments] == [("first",), ("last",)]


def test_catalog_search_fields_fail_closed_for_unknown_values() -> None:
    with pytest.raises(ValidationError, match="invalid"):
        _search_fields({"search_fields": "TABLE,RAW_GRAPHQL"})
