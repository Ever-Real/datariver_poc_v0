from __future__ import annotations

import csv
import hashlib
import io
import tracemalloc
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from datariver.application.catalog_metadata_upload_parser import (
    CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION,
    CatalogMetadataAspect,
    CatalogMetadataCandidateDraft,
    CatalogMetadataOperation,
    CatalogMetadataParseError,
    CatalogMetadataParseFailureCode,
    CatalogMetadataParseSummary,
    catalog_metadata_candidate_root,
    catalog_metadata_row_hash,
    catalog_metadata_row_root,
    catalog_metadata_semantic_target_hash,
    compile_catalog_metadata_candidates,
    parse_catalog_metadata_rows_csv,
)
from datariver.application.typed_upload_profiles import (
    CATALOG_METADATA_ROWS_CSV_V1,
    CATALOG_METADATA_ROWS_XLSX_V1,
    DATASET_DESCRIPTION_CSV_V1,
    typed_profile_definition,
    validate_upload_profile,
)
from datariver.domain.common import ValidationError
from datariver.domain.registration import UploadContentProfile

HEADERS = (
    "record_kind",
    "asset_id",
    "platform",
    "database_name",
    "schema_name",
    "table_name",
    "field_path",
    "operation",
    "value_text",
    "controlled_ref",
)


async def _chunks(value: bytes, *, width: int = 7) -> AsyncIterator[bytes]:
    for offset in range(0, len(value), width):
        yield value[offset : offset + width]


def _csv(rows: Sequence[Sequence[str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return output.getvalue().encode()


def _row(
    *,
    record_kind: str,
    asset_id: UUID,
    field_path: str = "",
    operation: str,
    value_text: str = "",
    controlled_ref: str = "",
    platform: str = "postgres",
    database_name: str = "fab",
    schema_name: str = "public",
    table_name: str = "wafer",
) -> list[str]:
    return [
        record_kind,
        str(asset_id),
        platform,
        database_name,
        schema_name,
        table_name,
        field_path,
        operation,
        value_text,
        controlled_ref,
    ]


async def _parse(
    value: bytes,
    *,
    workspace_id: UUID | None = None,
    expected_hash: str | None = None,
    chunk_width: int = 7,
) -> tuple[list[CatalogMetadataCandidateDraft], CatalogMetadataParseSummary]:
    candidates: list[CatalogMetadataCandidateDraft] = []

    async def consume(candidate: CatalogMetadataCandidateDraft) -> None:
        candidates.append(candidate)

    summary = await parse_catalog_metadata_rows_csv(
        workspace_id=workspace_id or uuid4(),
        chunks=_chunks(value, width=chunk_width),
        expected_source_sha256=expected_hash or hashlib.sha256(value).hexdigest(),
        consume_candidate=consume,
    )
    return candidates, summary


@pytest.mark.asyncio
async def test_csv_maximum_row_contract_keeps_parser_peak_memory_bounded() -> None:
    workspace_id = uuid4()
    value = _csv(
        [
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=UUID(f"00000000-0000-4000-8000-{ordinal:012d}"),
                operation="SET",
                value_text="x",
            )
            for ordinal in range(1, CATALOG_METADATA_ROWS_CSV_V1.maximum_rows + 1)
        ]
    )
    consumed = 0

    async def consume(_candidate: CatalogMetadataCandidateDraft) -> None:
        nonlocal consumed
        consumed += 1

    tracemalloc.start()
    try:
        summary = await parse_catalog_metadata_rows_csv(
            workspace_id=workspace_id,
            chunks=_chunks(value, width=64 * 1024),
            expected_source_sha256=hashlib.sha256(value).hexdigest(),
            consume_candidate=consume,
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert summary.item_count == CATALOG_METADATA_ROWS_CSV_V1.maximum_rows
    assert summary.candidate_count == consumed == CATALOG_METADATA_ROWS_CSV_V1.maximum_rows
    assert peak_bytes < 64 * 1024 * 1024


def test_two_catalog_metadata_profiles_are_exact_and_v2_hash_is_frozen() -> None:
    assert CATALOG_METADATA_ROWS_CSV_V1.headers == HEADERS
    assert CATALOG_METADATA_ROWS_XLSX_V1.headers == HEADERS
    assert (
        typed_profile_definition(UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1)
        is CATALOG_METADATA_ROWS_CSV_V1
    )
    assert (
        typed_profile_definition(UploadContentProfile.CATALOG_METADATA_ROWS_XLSX_V1)
        is CATALOG_METADATA_ROWS_XLSX_V1
    )
    assert (
        DATASET_DESCRIPTION_CSV_V1.configuration_hash
        == "e840ab65b7c3c1fc89e5b4fc68bafedc2426ac8be2f57b381c07c4569e602ad5"
    )
    validate_upload_profile(
        content_profile=UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
        display_name="catalog-metadata.csv",
        content_type="text/csv",
        size_bytes=1,
    )
    with pytest.raises(ValidationError, match="invalid content type"):
        validate_upload_profile(
            content_profile=UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
            display_name="catalog-metadata.xlsx",
            content_type=CATALOG_METADATA_ROWS_XLSX_V1.content_type,
            size_bytes=1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_width", [1, 2, 7, 4096])
async def test_csv_groups_rows_by_target_and_fixed_aspect_deterministically(
    chunk_width: int,
) -> None:
    workspace_id = uuid4()
    asset_id = uuid4()
    domain_id = uuid4()
    first_term_id = uuid4()
    second_term_id = uuid4()
    first_tag_id = uuid4()
    second_tag_id = uuid4()
    value = _csv(
        [
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=asset_id,
                operation="SET",
                value_text="table description",
            ),
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="lot_id",
                operation="SET",
                value_text="lot description",
            ),
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="obsolete",
                operation="CLEAR",
            ),
            _row(
                record_kind="DATASET_DOMAIN",
                asset_id=asset_id,
                operation="SET",
                controlled_ref=str(domain_id),
            ),
            _row(
                record_kind="DATASET_TERM",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref=str(first_term_id),
            ),
            _row(
                record_kind="DATASET_TERM",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref=str(second_term_id),
            ),
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref=str(first_tag_id),
            ),
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref=str(second_tag_id),
            ),
        ]
    )

    candidates, summary = await _parse(
        value,
        workspace_id=workspace_id,
        chunk_width=chunk_width,
    )
    repeated, repeated_summary = await _parse(
        value,
        workspace_id=workspace_id,
        chunk_width=chunk_width,
    )

    assert candidates == repeated
    assert summary == repeated_summary
    assert [candidate.aspect_name for candidate in candidates] == [
        CatalogMetadataAspect.DATASET_PROPERTIES,
        CatalogMetadataAspect.SCHEMA_METADATA,
        CatalogMetadataAspect.DOMAINS,
        CatalogMetadataAspect.GLOSSARY_TERMS,
        CatalogMetadataAspect.GLOBAL_TAGS,
    ]
    assert [len(candidate.rows) for candidate in candidates] == [1, 2, 1, 2, 2]
    assert candidates[1].rows[0].field_path == "lot_id"
    assert candidates[1].rows[1].operation is CatalogMetadataOperation.CLEAR
    assert candidates[2].rows[0].controlled_ref == domain_id
    assert all(
        candidate.evidence_version == CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION
        for candidate in candidates
    )
    assert summary.item_count == 8
    assert summary.candidate_count == 5
    assert summary.rejected_count == 0
    assert len(summary.candidate_root_hash) == 64


@pytest.mark.asyncio
async def test_csv_merges_noncontiguous_fixed_aspect_rows_with_source_order_evidence() -> None:
    asset_id = uuid4()
    first_reference = uuid4()
    value = _csv(
        [
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="first",
                operation="SET",
                value_text="First",
            ),
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref=str(first_reference),
            ),
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="second",
                operation="SET",
                value_text="Second",
            ),
        ]
    )

    candidates, summary = await _parse(value)

    assert summary.candidate_count == 2
    assert [row.ordinal for row in candidates[0].rows] == [1, 3]
    assert [row.field_path for row in candidates[0].rows] == ["first", "second"]
    assert candidates[1].rows[0].ordinal == 2


@pytest.mark.asyncio
async def test_csv_preserves_multiline_description_and_uses_clear_as_none() -> None:
    asset_id = uuid4()
    value = _csv(
        [
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=asset_id,
                operation="SET",
                value_text="first,\nsecond",
            ),
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="old_column",
                operation="CLEAR",
            ),
        ]
    )

    candidates, _summary = await _parse(value, chunk_width=1)

    assert candidates[0].rows[0].value_text == "first,\nsecond"
    assert candidates[1].rows[0].value_text is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "failure_code"),
    [
        (
            _row(record_kind="UNKNOWN", asset_id=uuid4(), operation="SET", value_text="x"),
            CatalogMetadataParseFailureCode.INVALID_RECORD_KIND,
        ),
        (
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=uuid4(),
                operation="ADD",
                value_text="x",
            ),
            CatalogMetadataParseFailureCode.INVALID_OPERATION,
        ),
        (
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=uuid4(),
                field_path="not-allowed",
                operation="SET",
                value_text="x",
            ),
            CatalogMetadataParseFailureCode.INVALID_ROW_SHAPE,
        ),
        (
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=uuid4(),
                operation="SET",
                value_text="x",
            ),
            CatalogMetadataParseFailureCode.INVALID_FIELD_PATH,
        ),
        (
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=uuid4(),
                field_path=" exact ",
                operation="SET",
                value_text="x",
            ),
            CatalogMetadataParseFailureCode.INVALID_FIELD_PATH,
        ),
        (
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=uuid4(),
                operation="SET",
            ),
            CatalogMetadataParseFailureCode.INVALID_DESCRIPTION,
        ),
        (
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=uuid4(),
                operation="CLEAR",
                value_text="not-empty",
            ),
            CatalogMetadataParseFailureCode.INVALID_ROW_SHAPE,
        ),
        (
            _row(
                record_kind="DATASET_DOMAIN",
                asset_id=uuid4(),
                operation="SET",
                controlled_ref="urn:li:domain:finance",
            ),
            CatalogMetadataParseFailureCode.INVALID_CONTROLLED_REF,
        ),
        (
            _row(
                record_kind="DATASET_DOMAIN",
                asset_id=uuid4(),
                operation="CLEAR",
                controlled_ref=str(uuid4()),
            ),
            CatalogMetadataParseFailureCode.INVALID_ROW_SHAPE,
        ),
        (
            _row(
                record_kind="DATASET_TERM",
                asset_id=uuid4(),
                operation="REMOVE",
                controlled_ref=str(uuid4()),
            ),
            CatalogMetadataParseFailureCode.INVALID_OPERATION,
        ),
        (
            _row(
                record_kind="DATASET_TAG",
                asset_id=uuid4(),
                operation="ADD",
            ),
            CatalogMetadataParseFailureCode.INVALID_CONTROLLED_REF,
        ),
    ],
)
async def test_csv_rejects_unregistered_operations_and_mixed_row_shapes(
    row: list[str],
    failure_code: CatalogMetadataParseFailureCode,
) -> None:
    with pytest.raises(CatalogMetadataParseError) as captured:
        await _parse(_csv([row]))

    assert captured.value.failure_code is failure_code
    assert captured.value.ordinal == 1


@pytest.mark.asyncio
async def test_controlled_ref_requires_non_nil_canonical_lowercase_local_uuid() -> None:
    asset_id = uuid4()
    reference_id = uuid4()
    for controlled_ref in (
        str(reference_id).upper(),
        str(UUID(int=0)),
        f" {reference_id}",
        "not-a-uuid",
    ):
        value = _csv(
            [
                _row(
                    record_kind="DATASET_TAG",
                    asset_id=asset_id,
                    operation="ADD",
                    controlled_ref=controlled_ref,
                )
            ]
        )
        with pytest.raises(CatalogMetadataParseError) as captured:
            await _parse(value)
        assert captured.value.failure_code is CatalogMetadataParseFailureCode.INVALID_CONTROLLED_REF


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=UUID("00000000-0000-4000-8000-000000000101"),
                field_path="lot_id",
                operation="SET",
                value_text="one",
            ),
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=UUID("00000000-0000-4000-8000-000000000101"),
                field_path="lot_id",
                operation="CLEAR",
            ),
        ],
        [
            _row(
                record_kind="DATASET_DOMAIN",
                asset_id=UUID("00000000-0000-4000-8000-000000000101"),
                operation="SET",
                controlled_ref="00000000-0000-4000-8000-000000000201",
            ),
            _row(
                record_kind="DATASET_DOMAIN",
                asset_id=UUID("00000000-0000-4000-8000-000000000101"),
                operation="SET",
                controlled_ref="00000000-0000-4000-8000-000000000202",
            ),
        ],
        [
            _row(
                record_kind="DATASET_TAG",
                asset_id=UUID("00000000-0000-4000-8000-000000000101"),
                operation="ADD",
                controlled_ref="00000000-0000-4000-8000-000000000201",
            ),
            _row(
                record_kind="DATASET_TAG",
                asset_id=UUID("00000000-0000-4000-8000-000000000101"),
                operation="ADD",
                controlled_ref="00000000-0000-4000-8000-000000000201",
            ),
        ],
    ],
)
async def test_csv_rejects_duplicate_or_conflicting_semantic_keys(
    rows: list[list[str]],
) -> None:
    with pytest.raises(CatalogMetadataParseError) as captured:
        await _parse(_csv(rows))

    assert captured.value.failure_code is CatalogMetadataParseFailureCode.DUPLICATE_SEMANTIC_KEY
    assert captured.value.ordinal == 2


@pytest.mark.asyncio
async def test_csv_rejects_conflicting_hierarchy_for_one_asset_id() -> None:
    asset_id = uuid4()
    rows = [
        _row(
            record_kind="TABLE_DESCRIPTION",
            asset_id=asset_id,
            operation="SET",
            value_text="one",
        ),
        _row(
            record_kind="DATASET_TAG",
            asset_id=asset_id,
            operation="ADD",
            controlled_ref=str(uuid4()),
            table_name="other",
        ),
    ]

    with pytest.raises(CatalogMetadataParseError) as captured:
        await _parse(_csv(rows))

    assert captured.value.failure_code is CatalogMetadataParseFailureCode.CONFLICTING_ASSET_IDENTITY


@pytest.mark.asyncio
async def test_csv_rejects_a_group_that_can_never_compile_within_the_fixed_aspect_limit() -> None:
    asset_id = uuid4()
    rows = [
        _row(
            record_kind="DATASET_TAG",
            asset_id=asset_id,
            operation="ADD",
            controlled_ref=str(uuid4()),
        )
        for _ in range(CATALOG_METADATA_ROWS_CSV_V1.maximum_controlled_operations_per_candidate + 1)
    ]

    with pytest.raises(CatalogMetadataParseError) as captured:
        await _parse(_csv(rows))

    assert captured.value.failure_code is CatalogMetadataParseFailureCode.TOO_MANY_GROUP_OPERATIONS
    assert captured.value.ordinal == 101


def test_shared_compiler_hashes_bind_workspace_profile_configuration_and_row_order() -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000001")
    other_workspace_id = UUID("00000000-0000-4000-8000-000000000002")
    asset_id = UUID("00000000-0000-4000-8000-000000000101")
    rows = [
        (
            1,
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref="00000000-0000-4000-8000-000000000201",
            ),
        ),
        (
            2,
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref="00000000-0000-4000-8000-000000000202",
            ),
        ),
    ]

    first = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=rows,
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )
    repeated = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=rows,
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )
    reordered = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=[(1, rows[1][1]), (2, rows[0][1])],
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )
    other_workspace = compile_catalog_metadata_candidates(
        workspace_id=other_workspace_id,
        rows=rows,
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )
    other_profile = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=rows,
        definition=CATALOG_METADATA_ROWS_XLSX_V1,
    )
    other_configuration = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=rows,
        definition=replace(
            CATALOG_METADATA_ROWS_CSV_V1,
            maximum_field_path_characters=1_999,
        ),
    )

    assert first == repeated
    assert first[0].candidate_hash != reordered[0].candidate_hash
    assert first[0].candidate_hash != other_workspace[0].candidate_hash
    assert first[0].candidate_hash != other_profile[0].candidate_hash
    assert first[0].candidate_hash != other_configuration[0].candidate_hash
    assert first[0].rows[0].row_hash != reordered[0].rows[1].row_hash


def test_v3_row_group_and_root_hashes_match_golden_contract() -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000001")
    asset_id = UUID("00000000-0000-4000-8000-000000000101")
    rows = [
        (
            1,
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="lot_id",
                operation="SET",
                value_text="lot description",
            ),
        ),
        (
            2,
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="old",
                operation="CLEAR",
            ),
        ),
        (
            3,
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref="00000000-0000-4000-8000-000000000201",
            ),
        ),
    ]

    candidates = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=rows,
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )

    assert (
        CATALOG_METADATA_ROWS_CSV_V1.configuration_hash
        == "acb23838627326e2eacdcff11213da62bd2e784c5e381662f1a5c2a66363ec8d"
    )
    assert [row.row_hash for candidate in candidates for row in candidate.rows] == [
        "aaaf3948691810771f8887082355d5c43644ec123e672808a6640eb7944f049c",
        "0b26be2c9948d32a92d4961e65512c590fa55706d58b419ff3316a3a2a4b700d",
        "2157bbd4f78948f675ac74f79c86201718a0fc57250916f00740fe666bdae95a",
    ]
    assert [candidate.submitted_identity_hash for candidate in candidates] == [
        "7b3449ef6467312e7c0aa4299831daa0cea35fdb439889e53f96c12ce1d775c7",
        "e97f83e114de06e960806d753da004946ddff65af406ba26e48a9993c824d513",
    ]
    assert [candidate.candidate_hash for candidate in candidates] == [
        "a29545bf3294802fa2f87183305de71df71d71db766fbef711cb0321e8c3a5b3",
        "e1062d5edcb7f00c3070cd5136e665e8207c68309f65c89be2d81481a6d51ed3",
    ]
    first_row = candidates[0].rows[0]
    assert (
        catalog_metadata_row_hash(
            workspace_id=first_row.workspace_id,
            ordinal=first_row.ordinal,
            target_asset_id=first_row.target_asset_id,
            platform=first_row.platform,
            database_name=first_row.database_name,
            schema_name=first_row.schema_name,
            table_name=first_row.table_name,
            record_kind=first_row.record_kind,
            aspect_name=first_row.aspect_name,
            operation=first_row.operation,
            field_path=first_row.field_path,
            value_text=first_row.value_text,
            controlled_ref=first_row.controlled_ref,
            definition=CATALOG_METADATA_ROWS_CSV_V1,
        )
        == first_row.row_hash
    )
    assert (
        len(
            catalog_metadata_semantic_target_hash(
                workspace_id=first_row.workspace_id,
                target_asset_id=first_row.target_asset_id,
                aspect_name=first_row.aspect_name,
                semantic_key=first_row.semantic_key,
            )
        )
        == 64
    )
    assert len(catalog_metadata_row_root(tuple(row.row_hash for row in candidates[0].rows))) == 64
    with pytest.raises(ValueError):
        catalog_metadata_row_root(())
    assert (
        catalog_metadata_candidate_root(
            workspace_id=workspace_id,
            candidates=candidates,
            definition=CATALOG_METADATA_ROWS_CSV_V1,
        ).hex()
        == "85dcbf090b2e10b00231cf192877d79a32e085ae987e98d92718731711d7cb80"
    )


@pytest.mark.asyncio
async def test_csv_fails_closed_before_consumer_on_bad_source_hash_header_and_empty_body() -> None:
    asset_id = uuid4()
    value = _csv(
        [
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=asset_id,
                operation="SET",
                value_text="description",
            )
        ]
    )
    consumed: list[CatalogMetadataCandidateDraft] = []

    async def consume(candidate: CatalogMetadataCandidateDraft) -> None:
        consumed.append(candidate)

    with pytest.raises(CatalogMetadataParseError) as captured:
        await parse_catalog_metadata_rows_csv(
            workspace_id=uuid4(),
            chunks=_chunks(value),
            expected_source_sha256="0" * 64,
            consume_candidate=consume,
        )
    assert captured.value.failure_code is CatalogMetadataParseFailureCode.SOURCE_HASH_MISMATCH
    assert consumed == []

    for invalid, failure_code in (
        (b"", CatalogMetadataParseFailureCode.EMPTY_FILE),
        (
            ",".join(HEADERS[:-1]).encode() + b"\n",
            CatalogMetadataParseFailureCode.INVALID_HEADER,
        ),
        (
            ",".join(HEADERS).encode() + b"\n",
            CatalogMetadataParseFailureCode.EMPTY_DATASET,
        ),
    ):
        with pytest.raises(CatalogMetadataParseError) as invalid_capture:
            await parse_catalog_metadata_rows_csv(
                workspace_id=uuid4(),
                chunks=_chunks(invalid),
                expected_source_sha256=hashlib.sha256(invalid).hexdigest(),
                consume_candidate=consume,
            )
        assert invalid_capture.value.failure_code is failure_code
