from __future__ import annotations

import hashlib
from uuid import uuid4

import orjson

from datariver.interfaces.http.routes.manual_registration import (
    _manual_submission_request_hash,
)
from datariver.interfaces.http.schemas import ManualMetadataSubmissionRequest


def test_legacy_manual_request_hash_remains_byte_compatible() -> None:
    asset_id = uuid4()
    payload = ManualMetadataSubmissionRequest(
        asset_id=asset_id,
        source_version="projection-v1",
        description="description",
        domain="urn:li:domain:finance",
        tags=["urn:li:tag:gold"],
        terms=[],
        columns=[
            {
                "field_path": "z_column",
                "description": "last",
                "tags": [],
                "terms": [],
            },
            {
                "field_path": "a_column",
                "description": "first",
                "tags": [],
                "terms": [],
            },
        ],
    )
    legacy_document = {
        "operation": "registration.manual-metadata.submit.v1",
        "asset_id": str(asset_id),
        "source_version": "projection-v1",
        "description": "description",
        "domain": "urn:li:domain:finance",
        "tags": ["urn:li:tag:gold"],
        "terms": [],
        "columns": [item.model_dump(mode="json") for item in payload.columns or ()],
    }

    assert (
        _manual_submission_request_hash(payload)
        == hashlib.sha256(orjson.dumps(legacy_document, option=orjson.OPT_SORT_KEYS)).hexdigest()
    )


def test_sparse_manual_request_hash_binds_provider_and_is_order_independent() -> None:
    asset_id = uuid4()
    edits = [
        {"field_path": "z_column", "description": "last"},
        {"field_path": "a_column", "description": "first"},
    ]
    base = {
        "asset_id": asset_id,
        "source_version": "projection-v1",
        "provider_source_version": "a" * 64,
        "description": "description",
        "column_edits": edits,
    }
    first = ManualMetadataSubmissionRequest.model_validate(base)
    second = ManualMetadataSubmissionRequest.model_validate(
        {**base, "column_edits": list(reversed(edits))}
    )
    changed_provider = ManualMetadataSubmissionRequest.model_validate(
        {**base, "provider_source_version": "b" * 64}
    )

    assert _manual_submission_request_hash(first) == _manual_submission_request_hash(second)
    assert _manual_submission_request_hash(first) != _manual_submission_request_hash(
        changed_provider
    )
