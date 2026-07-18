from __future__ import annotations

import pytest

from datariver.domain.common import ValidationError
from datariver.infrastructure.db.catalog import _catalog_query_condition, _search_fields


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


def test_catalog_search_fields_fail_closed_for_unknown_values() -> None:
    with pytest.raises(ValidationError, match="invalid"):
        _search_fields({"search_fields": "TABLE,RAW_GRAPHQL"})
