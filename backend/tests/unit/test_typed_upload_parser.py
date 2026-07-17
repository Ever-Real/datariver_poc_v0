from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from datariver.application.typed_upload_parser import (
    DatasetDescriptionCandidateDraft,
    DatasetDescriptionParseSummary,
    TypedUploadParseError,
    TypedUploadParseFailureCode,
    parse_dataset_description_csv,
)
from datariver.application.typed_upload_profiles import (
    DATASET_DESCRIPTION_CSV_V1,
    TypedUploadProfileDefinition,
)
from datariver.domain.registration import UploadContentProfile

HEADER = "asset_id,platform,database_name,schema_name,table_name,description\r\n"


async def _chunks(value: bytes, *, width: int = 7) -> AsyncIterator[bytes]:
    for offset in range(0, len(value), width):
        yield value[offset : offset + width]


async def _parse(
    value: bytes,
    *,
    workspace_id: UUID | None = None,
    expected_sha256: str | None = None,
    definition: TypedUploadProfileDefinition = DATASET_DESCRIPTION_CSV_V1,
    chunk_width: int = 7,
) -> tuple[list[DatasetDescriptionCandidateDraft], DatasetDescriptionParseSummary]:
    candidates: list[DatasetDescriptionCandidateDraft] = []

    async def consume(candidate: DatasetDescriptionCandidateDraft) -> None:
        candidates.append(candidate)

    summary = await parse_dataset_description_csv(
        workspace_id=workspace_id or uuid4(),
        chunks=_chunks(value, width=chunk_width),
        expected_source_sha256=expected_sha256 or hashlib.sha256(value).hexdigest(),
        consume_candidate=consume,
        definition=definition,
    )
    return candidates, summary


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_width", [1, 2, 3, 7, 64, 4096])
async def test_parser_streams_bom_multiline_and_empty_description_deterministically(
    chunk_width: int,
) -> None:
    workspace_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    value = (
        "\ufeff"
        + HEADER
        + f'{first_id},snowflake,rd,public,wafer,"comma, and\nmultiline"\r\n'
        + f"{second_id},postgres,lab,core,lot,\r\n"
    ).encode()

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

    assert [candidate.target_asset_id for candidate in candidates] == [first_id, second_id]
    assert candidates[0].proposed_description == "comma, and\nmultiline"
    assert candidates[1].proposed_description == ""
    assert candidates == repeated
    assert summary == repeated_summary
    assert summary.source_sha256 == hashlib.sha256(value).hexdigest()
    assert summary.total_bytes == len(value)
    assert summary.item_count == 2
    assert summary.rejected_count == 0
    assert len(summary.candidate_root_hash) == 64


@pytest.mark.asyncio
async def test_candidate_hash_binds_workspace_asset_submitted_identity_and_description() -> None:
    asset_id = uuid4()
    workspace_id = uuid4()
    other_workspace = uuid4()
    value = (HEADER + f"{asset_id},p,d,s,t,exact text\n").encode()
    changed = (HEADER + f"{asset_id},p,d,s,t,exact text \n").encode()
    changed_identity = (HEADER + f"{asset_id},p,d,s,other,exact text\n").encode()

    first, _ = await _parse(value, workspace_id=workspace_id)
    other_scope, _ = await _parse(value, workspace_id=other_workspace)
    other_text, _ = await _parse(changed, workspace_id=workspace_id)
    other_identity, _ = await _parse(changed_identity, workspace_id=workspace_id)

    assert first[0].candidate_hash != other_scope[0].candidate_hash
    assert first[0].candidate_hash != other_text[0].candidate_hash
    assert first[0].candidate_hash != other_identity[0].candidate_hash
    assert first[0].submitted_identity_hash != other_identity[0].submitted_identity_hash
    assert len(first[0].submitted_identity_hash) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "failure_code"),
    [
        (b"", TypedUploadParseFailureCode.EMPTY_FILE),
        (HEADER.encode(), TypedUploadParseFailureCode.EMPTY_DATASET),
        (
            b"table_name,asset_id,platform,database_name,schema_name,description\n",
            TypedUploadParseFailureCode.INVALID_HEADER,
        ),
        (
            (HEADER + "not-a-uuid,p,d,s,t,description\n").encode(),
            TypedUploadParseFailureCode.INVALID_ASSET_ID,
        ),
        (
            (HEADER + f"{str(uuid4()).upper()},p,d,s,t,description\n").encode(),
            TypedUploadParseFailureCode.INVALID_ASSET_ID,
        ),
        (
            (HEADER + f"{uuid4()}, p,d,s,t,description\n").encode(),
            TypedUploadParseFailureCode.INVALID_IDENTITY_FIELD,
        ),
        (
            (HEADER + f"{uuid4()},p,d,s,t\n").encode(),
            TypedUploadParseFailureCode.INVALID_COLUMN_COUNT,
        ),
        (
            (HEADER + f'{uuid4()},p,d,s,t,"unterminated\n').encode(),
            TypedUploadParseFailureCode.INVALID_CSV,
        ),
        (
            (HEADER + f'{uuid4()},p,d,s,t,bad"quote"\n').encode(),
            TypedUploadParseFailureCode.INVALID_CSV,
        ),
        (
            (HEADER + f'{uuid4()},p,d,s,t,"quoted"trailing\n').encode(),
            TypedUploadParseFailureCode.INVALID_CSV,
        ),
        (
            (HEADER + f"{uuid4()},p,d,s,t,text\n").replace("\r\n", "\r").encode(),
            TypedUploadParseFailureCode.INVALID_CSV,
        ),
        (
            (HEADER + "\n").encode(),
            TypedUploadParseFailureCode.INVALID_CSV,
        ),
    ],
)
async def test_parser_rejects_invalid_file_shapes(
    value: bytes,
    failure_code: TypedUploadParseFailureCode,
) -> None:
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(value)

    assert captured.value.failure_code is failure_code


@pytest.mark.asyncio
async def test_parser_rejects_invalid_utf8_and_forbidden_markers() -> None:
    asset_id = uuid4()
    for value, expected in (
        (
            HEADER.encode() + f"{asset_id},p,d,s,t,".encode() + b"\xff\n",
            TypedUploadParseFailureCode.INVALID_UTF8,
        ),
        (
            (HEADER + f"{asset_id},p,d,s,t,bad\x00text\n").encode(),
            TypedUploadParseFailureCode.INVALID_CSV,
        ),
        (
            (HEADER + f"{asset_id},p,d,s,t,mid\ufefftext\n").encode(),
            TypedUploadParseFailureCode.INVALID_CSV,
        ),
    ):
        with pytest.raises(TypedUploadParseError) as captured:
            await _parse(value)
        assert captured.value.failure_code is expected


@pytest.mark.asyncio
async def test_parser_rejects_duplicate_assets_and_excessive_description() -> None:
    asset_id = uuid4()
    duplicate = (HEADER + f"{asset_id},p,d,s,t,one\n" + f"{asset_id},p,d,s,t,two\n").encode()
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(duplicate)
    assert captured.value.failure_code is TypedUploadParseFailureCode.DUPLICATE_ASSET
    assert captured.value.ordinal == 2

    definition = replace(DATASET_DESCRIPTION_CSV_V1, maximum_description_characters=3)
    excessive = (HEADER + f"{uuid4()},p,d,s,t,four\n").encode()
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(excessive, definition=definition)
    assert captured.value.failure_code is TypedUploadParseFailureCode.INVALID_DESCRIPTION


@pytest.mark.asyncio
async def test_parser_enforces_projection_identity_lengths_and_control_rules() -> None:
    asset_id = uuid4()
    excessive_platform = replace(
        DATASET_DESCRIPTION_CSV_V1,
        maximum_platform_characters=1,
    )
    for value, definition, expected in (
        (
            (HEADER + f"{asset_id},pp,d,s,t,text\n").encode(),
            excessive_platform,
            TypedUploadParseFailureCode.INVALID_IDENTITY_FIELD,
        ),
        (
            (HEADER + f"{asset_id},p\t,d,s,t,text\n").encode(),
            DATASET_DESCRIPTION_CSV_V1,
            TypedUploadParseFailureCode.INVALID_IDENTITY_FIELD,
        ),
        (
            (HEADER + f"{asset_id},p,d,s,t,bad\x7ftext\n").encode(),
            DATASET_DESCRIPTION_CSV_V1,
            TypedUploadParseFailureCode.INVALID_DESCRIPTION,
        ),
    ):
        with pytest.raises(TypedUploadParseError) as captured:
            await _parse(value, definition=definition)
        assert captured.value.failure_code is expected


@pytest.mark.asyncio
async def test_candidate_and_ordered_result_chain_match_golden_contract() -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000100")
    rows = (
        "00000000-0000-4000-8000-000000000201,p1,d1,s1,t1,one\r\n",
        '00000000-0000-4000-8000-000000000202,p2,d2,s2,t2,"two, exact"\r\n',
        '00000000-0000-4000-8000-000000000203,p3,d3,s3,t3,"three\nlines"\r\n',
    )
    expected_hashes = (
        "c13c6619e816cd7ad37b96be7dee56aeb86945df45952654b67868efb34b0da7",
        "6dc36a14be02bf9ef4ba22bc447fd3e672b871474e1a1849a7b1b09f643d15f7",
        "ed69b3f50b7f26119fd3620134756b4c5bc542260f1c3321be5d9b6c6dab223c",
    )
    expected_identity_hashes = (
        "84095cd4056048d05c78b0a56425a4c91bcc87c647a5d299d6a35e839b89b0bb",
        "859e9f4f07b4f7e4a554343a414a4d55ccc3df5f2547b590ebb0bc7aa25cb793",
        "e2149deb34bc5268ef50e6f71dae1243cccf2f80898a16a519278916ce7807f4",
    )
    expected_roots = (
        "b7b9f7d35e6875b522b55555cc648b0d4b1a5942118abe1107a97eda5ba96655",
        "4a3d061a45ae972461d9d7d8f19ae08afe41f0bafd612145cadabbe3e664db51",
        "b21e86d193588fa7a89338a2b76839e76d0b24a3f270d065f519732b3bf8479a",
    )

    for count in (1, 2, 3):
        value = ("\ufeff" + HEADER + "".join(rows[:count])).encode()
        for chunk_width in (1, 4096):
            candidates, summary = await _parse(
                value,
                workspace_id=workspace_id,
                chunk_width=chunk_width,
            )
            assert (
                tuple(candidate.candidate_hash for candidate in candidates)
                == expected_hashes[:count]
            )
            assert (
                tuple(candidate.submitted_identity_hash for candidate in candidates)
                == expected_identity_hashes[:count]
            )
            assert summary.candidate_root_hash == expected_roots[count - 1]


@pytest.mark.asyncio
async def test_parser_enforces_file_row_and_candidate_count_bounds() -> None:
    value = (HEADER + f"{uuid4()},p,d,s,t,one\n" + f"{uuid4()},p,d,s,t,two\n").encode()
    cases = (
        (
            replace(DATASET_DESCRIPTION_CSV_V1, maximum_file_bytes=len(value) - 1),
            TypedUploadParseFailureCode.FILE_TOO_LARGE,
        ),
        (
            replace(DATASET_DESCRIPTION_CSV_V1, maximum_row_bytes=20),
            TypedUploadParseFailureCode.ROW_TOO_LARGE,
        ),
        (
            replace(DATASET_DESCRIPTION_CSV_V1, maximum_rows=1),
            TypedUploadParseFailureCode.TOO_MANY_ROWS,
        ),
    )
    for definition, expected in cases:
        with pytest.raises(TypedUploadParseError) as captured:
            await _parse(value, definition=definition)
        assert captured.value.failure_code is expected


@pytest.mark.asyncio
async def test_parser_rejects_source_hash_mismatch_after_attempt_local_consumption() -> None:
    value = (HEADER + f"{uuid4()},p,d,s,t,text\n").encode()
    consumed: list[DatasetDescriptionCandidateDraft] = []

    async def consume(candidate: DatasetDescriptionCandidateDraft) -> None:
        consumed.append(candidate)

    with pytest.raises(TypedUploadParseError) as captured:
        await parse_dataset_description_csv(
            workspace_id=uuid4(),
            chunks=_chunks(value, width=1),
            expected_source_sha256="0" * 64,
            consume_candidate=consume,
        )

    assert captured.value.failure_code is TypedUploadParseFailureCode.SOURCE_HASH_MISMATCH
    assert len(consumed) == 1


@pytest.mark.asyncio
async def test_parser_propagates_staging_failure_without_continuing() -> None:
    value = (HEADER + f"{uuid4()},p,d,s,t,one\n" + f"{uuid4()},p,d,s,t,two\n").encode()
    calls = 0

    async def consume(_: DatasetDescriptionCandidateDraft) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("staging unavailable")

    with pytest.raises(RuntimeError, match="staging unavailable"):
        await parse_dataset_description_csv(
            workspace_id=uuid4(),
            chunks=_chunks(value),
            expected_source_sha256=hashlib.sha256(value).hexdigest(),
            consume_candidate=consume,
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_parser_rejects_invalid_hash_and_wrong_profile_before_consumption() -> None:
    value = (HEADER + f"{uuid4()},p,d,s,t,text\n").encode()

    with pytest.raises(ValueError, match="expected source SHA"):
        await _parse(value, expected_sha256="g" * 64)

    wrong_profile = replace(
        DATASET_DESCRIPTION_CSV_V1,
        content_profile=UploadContentProfile.FORMAT_ONLY_V1,
    )
    with pytest.raises(ValueError, match="exact typed content profile"):
        await _parse(value, definition=wrong_profile)
