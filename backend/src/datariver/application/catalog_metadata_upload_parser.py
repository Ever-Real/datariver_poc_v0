from __future__ import annotations

import hashlib
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, NAMESPACE_URL, uuid5

from datariver.application.typed_upload_parser import (
    TypedUploadParseError,
    _iter_logical_records,
    _parse_record,
)
from datariver.application.typed_upload_profiles import (
    CATALOG_METADATA_ROWS_CSV_V1,
    TypedUploadProfileDefinition,
)
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.registration import UploadContentProfile

CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION = "CATALOG_METADATA_CANDIDATE_V3"
_ROW_HASH_CONTRACT = "catalog-metadata-row-v3"
_SEMANTIC_TARGET_HASH_CONTRACT = "catalog-metadata-semantic-target-v3"
_GROUP_IDENTITY_HASH_CONTRACT = "catalog-metadata-group-identity-v3"
_GROUP_HASH_CONTRACT = "catalog-metadata-candidate-v3"
_ROW_ROOT_CONTRACT = "catalog-metadata-row-root-v3"
_GROUP_ROOT_CONTRACT = b"datariver-catalog-metadata-root-v3\0"


class CatalogMetadataRecordKind(StrEnum):
    TABLE_DESCRIPTION = "TABLE_DESCRIPTION"
    COLUMN_DESCRIPTION = "COLUMN_DESCRIPTION"
    DATASET_DOMAIN = "DATASET_DOMAIN"
    DATASET_TERM = "DATASET_TERM"
    DATASET_TAG = "DATASET_TAG"
    DATASET_OWNER = "DATASET_OWNER"


class CatalogMetadataOperation(StrEnum):
    SET = "SET"
    CLEAR = "CLEAR"
    ADD = "ADD"


class CatalogMetadataAspect(StrEnum):
    DATASET_PROPERTIES = "datasetProperties"
    SCHEMA_METADATA = "schemaMetadata"
    DOMAINS = "domains"
    GLOSSARY_TERMS = "glossaryTerms"
    GLOBAL_TAGS = "globalTags"
    OWNERSHIP = "ownership"


class CatalogMetadataCandidateKind(StrEnum):
    TABLE_DESCRIPTION_UPDATE = "TABLE_DESCRIPTION_UPDATE"
    COLUMN_DESCRIPTION_UPDATE = "COLUMN_DESCRIPTION_UPDATE"
    DATASET_DOMAIN_UPDATE = "DATASET_DOMAIN_UPDATE"
    DATASET_TERM_ADD = "DATASET_TERM_ADD"
    DATASET_TAG_ADD = "DATASET_TAG_ADD"
    DATASET_OWNER_UPDATE = "DATASET_OWNER_UPDATE"


class CatalogMetadataParseFailureCode(StrEnum):
    EMPTY_FILE = "EMPTY_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    ROW_TOO_LARGE = "ROW_TOO_LARGE"
    INVALID_UTF8 = "INVALID_UTF8"
    INVALID_CSV = "INVALID_CSV"
    INVALID_HEADER = "INVALID_HEADER"
    INVALID_COLUMN_COUNT = "INVALID_COLUMN_COUNT"
    INVALID_ASSET_ID = "INVALID_ASSET_ID"
    INVALID_IDENTITY_FIELD = "INVALID_IDENTITY_FIELD"
    INVALID_RECORD_KIND = "INVALID_RECORD_KIND"
    INVALID_OPERATION = "INVALID_OPERATION"
    INVALID_ROW_SHAPE = "INVALID_ROW_SHAPE"
    INVALID_FIELD_PATH = "INVALID_FIELD_PATH"
    INVALID_DESCRIPTION = "INVALID_DESCRIPTION"
    INVALID_CONTROLLED_REF = "INVALID_CONTROLLED_REF"
    DUPLICATE_SEMANTIC_KEY = "DUPLICATE_SEMANTIC_KEY"
    TOO_MANY_GROUP_OPERATIONS = "TOO_MANY_GROUP_OPERATIONS"
    CONFLICTING_ASSET_IDENTITY = "CONFLICTING_ASSET_IDENTITY"
    TOO_MANY_ROWS = "TOO_MANY_ROWS"
    EMPTY_DATASET = "EMPTY_DATASET"
    SOURCE_HASH_MISMATCH = "SOURCE_HASH_MISMATCH"
    INVALID_XLSX_PACKAGE = "INVALID_XLSX_PACKAGE"


class CatalogMetadataParseError(ValidationError):
    code = "catalog_metadata_upload_parse_failed"

    def __init__(
        self,
        failure_code: CatalogMetadataParseFailureCode,
        message: str,
        *,
        ordinal: int | None = None,
    ) -> None:
        details: dict[str, object] = {"failure_code": failure_code.value}
        if ordinal is not None:
            details["ordinal"] = ordinal
        super().__init__(message, details=details)
        self.failure_code = failure_code
        self.ordinal = ordinal


@dataclass(frozen=True, slots=True)
class CatalogMetadataRowEvidence:
    workspace_id: UUID
    ordinal: int
    target_asset_id: UUID
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    record_kind: CatalogMetadataRecordKind
    aspect_name: CatalogMetadataAspect
    operation: CatalogMetadataOperation
    field_path: str | None
    value_text: str | None
    controlled_ref: UUID | None
    semantic_key: str
    row_hash: str
    evidence_version: str = CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION


@dataclass(frozen=True, slots=True)
class CatalogMetadataCandidateDraft:
    workspace_id: UUID
    ordinal: int
    target_asset_id: UUID
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    record_kind: CatalogMetadataRecordKind
    candidate_kind: CatalogMetadataCandidateKind
    aspect_name: CatalogMetadataAspect
    rows: tuple[CatalogMetadataRowEvidence, ...]
    submitted_identity_hash: str
    candidate_hash: str
    evidence_version: str = CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION


@dataclass(frozen=True, slots=True)
class CatalogMetadataParseSummary:
    source_sha256: str
    total_bytes: int
    item_count: int
    candidate_count: int
    rejected_count: int
    candidate_root_hash: str
    parser_version: str
    schema_version: str
    configuration_hash: str


@dataclass(frozen=True, slots=True)
class _RowRule:
    aspect_name: CatalogMetadataAspect
    candidate_kind: CatalogMetadataCandidateKind
    allowed_operations: frozenset[CatalogMetadataOperation]


_ROW_RULES = {
    CatalogMetadataRecordKind.TABLE_DESCRIPTION: _RowRule(
        aspect_name=CatalogMetadataAspect.DATASET_PROPERTIES,
        candidate_kind=CatalogMetadataCandidateKind.TABLE_DESCRIPTION_UPDATE,
        allowed_operations=frozenset(
            {CatalogMetadataOperation.SET, CatalogMetadataOperation.CLEAR}
        ),
    ),
    CatalogMetadataRecordKind.COLUMN_DESCRIPTION: _RowRule(
        aspect_name=CatalogMetadataAspect.SCHEMA_METADATA,
        candidate_kind=CatalogMetadataCandidateKind.COLUMN_DESCRIPTION_UPDATE,
        allowed_operations=frozenset(
            {CatalogMetadataOperation.SET, CatalogMetadataOperation.CLEAR}
        ),
    ),
    CatalogMetadataRecordKind.DATASET_DOMAIN: _RowRule(
        aspect_name=CatalogMetadataAspect.DOMAINS,
        candidate_kind=CatalogMetadataCandidateKind.DATASET_DOMAIN_UPDATE,
        allowed_operations=frozenset(
            {CatalogMetadataOperation.SET, CatalogMetadataOperation.CLEAR}
        ),
    ),
    CatalogMetadataRecordKind.DATASET_TERM: _RowRule(
        aspect_name=CatalogMetadataAspect.GLOSSARY_TERMS,
        candidate_kind=CatalogMetadataCandidateKind.DATASET_TERM_ADD,
        allowed_operations=frozenset({CatalogMetadataOperation.ADD}),
    ),
    CatalogMetadataRecordKind.DATASET_TAG: _RowRule(
        aspect_name=CatalogMetadataAspect.GLOBAL_TAGS,
        candidate_kind=CatalogMetadataCandidateKind.DATASET_TAG_ADD,
        allowed_operations=frozenset({CatalogMetadataOperation.ADD}),
    ),
    CatalogMetadataRecordKind.DATASET_OWNER: _RowRule(
        aspect_name=CatalogMetadataAspect.OWNERSHIP,
        candidate_kind=CatalogMetadataCandidateKind.DATASET_OWNER_UPDATE,
        allowed_operations=frozenset({CatalogMetadataOperation.SET, CatalogMetadataOperation.CLEAR}),
    ),
}

CandidateConsumer = Callable[[CatalogMetadataCandidateDraft], Awaitable[None]]


async def parse_catalog_metadata_rows_csv(
    *,
    workspace_id: UUID,
    chunks: AsyncIterable[bytes],
    expected_source_sha256: str,
    consume_candidate: CandidateConsumer,
    definition: TypedUploadProfileDefinition = CATALOG_METADATA_ROWS_CSV_V1,
) -> CatalogMetadataParseSummary:
    """Parse and group one immutable V3 catalog-metadata CSV.

    Candidate publication starts only after the complete source hash and semantic group set have
    been verified. The consumer must still write to attempt-local staging until its caller
    atomically publishes the returned receipt summary.
    """

    _validate_expected_hash(expected_source_sha256)
    if definition.content_profile is not UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1:
        raise ValueError("The catalog-metadata CSV parser requires its exact content profile.")

    source_hasher = hashlib.sha256()
    total_bytes = 0

    async def observed_chunks() -> AsyncIterable[bytes]:
        nonlocal total_bytes
        async for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise TypeError("Typed upload chunks must be bytes.")
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > definition.maximum_file_bytes:
                raise CatalogMetadataParseError(
                    CatalogMetadataParseFailureCode.FILE_TOO_LARGE,
                    "The catalog-metadata upload exceeds its bounded file-size limit.",
                )
            source_hasher.update(chunk)
            yield chunk

    header_seen = False
    row_count = 0
    compilation = CatalogMetadataCandidateAccumulator(
        workspace_id=workspace_id,
        definition=definition,
    )
    try:
        async for record_number, record in _iter_logical_records(
            observed_chunks(),
            maximum_row_bytes=definition.maximum_row_bytes,
        ):
            fields = _parse_record(record, record_number=record_number)
            if not header_seen:
                header_seen = True
                if tuple(fields) != definition.headers:
                    raise CatalogMetadataParseError(
                        CatalogMetadataParseFailureCode.INVALID_HEADER,
                        "The catalog-metadata header does not match the registered schema.",
                    )
                continue
            ordinal = row_count + 1
            if ordinal > definition.maximum_rows:
                raise CatalogMetadataParseError(
                    CatalogMetadataParseFailureCode.TOO_MANY_ROWS,
                    "The catalog-metadata upload exceeds its bounded row limit.",
                    ordinal=ordinal,
                )
            compilation.add_row(ordinal=ordinal, values=fields)
            row_count = ordinal
    except TypedUploadParseError as error:
        raise _translate_csv_error(error) from error

    if not header_seen:
        raise CatalogMetadataParseError(
            CatalogMetadataParseFailureCode.EMPTY_FILE,
            "The catalog-metadata upload is empty.",
        )
    if row_count == 0:
        raise CatalogMetadataParseError(
            CatalogMetadataParseFailureCode.EMPTY_DATASET,
            "The catalog-metadata upload contains no operation rows.",
        )

    source_sha256 = source_hasher.hexdigest()
    if source_sha256 != expected_source_sha256:
        raise CatalogMetadataParseError(
            CatalogMetadataParseFailureCode.SOURCE_HASH_MISMATCH,
            "The catalog-metadata upload bytes do not match the accepted source hash.",
        )

    candidate_root = catalog_metadata_candidate_root(
        workspace_id=workspace_id,
        candidates=compilation.iter_candidates(),
        definition=definition,
    )
    for candidate in compilation.iter_candidates():
        await consume_candidate(candidate)
    return CatalogMetadataParseSummary(
        source_sha256=source_sha256,
        total_bytes=total_bytes,
        item_count=row_count,
        candidate_count=compilation.candidate_count,
        rejected_count=0,
        candidate_root_hash=candidate_root.hex(),
        parser_version=definition.parser_version,
        schema_version=definition.schema_version,
        configuration_hash=definition.configuration_hash,
    )


class CatalogMetadataCandidateAccumulator:
    """Retain only canonical row evidence while compiling non-contiguous Aspect groups."""

    def __init__(
        self,
        *,
        workspace_id: UUID,
        definition: TypedUploadProfileDefinition,
    ) -> None:
        if definition.content_profile not in {
            UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
            UploadContentProfile.CATALOG_METADATA_ROWS_XLSX_V1,
        }:
            raise ValueError("Catalog metadata rows require a registered V3 content profile.")
        self._workspace_id = workspace_id
        self._definition = definition
        self._asset_identities: dict[UUID, tuple[str, str, str, str]] = {}
        self._groups: dict[
            tuple[UUID, CatalogMetadataAspect],
            dict[str, CatalogMetadataRowEvidence],
        ] = {}
        self._group_rules: dict[tuple[UUID, CatalogMetadataAspect], _RowRule] = {}
        self._row_count = 0

    @property
    def candidate_count(self) -> int:
        return len(self._groups)

    @property
    def row_count(self) -> int:
        return self._row_count

    def add_row(self, *, ordinal: int, values: Sequence[str]) -> None:
        evidences = _row_evidences_from_values(
            workspace_id=self._workspace_id,
            ordinal=ordinal,
            values=values,
            definition=self._definition,
        )
        for evidence, rule in evidences:
            identity = (
                evidence.platform,
                evidence.database_name,
                evidence.schema_name,
                evidence.table_name,
            )
            previous_identity = self._asset_identities.setdefault(evidence.target_asset_id, identity)
            if previous_identity != identity:
                raise CatalogMetadataParseError(
                    CatalogMetadataParseFailureCode.CONFLICTING_ASSET_IDENTITY,
                    "One asset ID has conflicting submitted hierarchy values.",
                    ordinal=ordinal,
                )

            group_key = (evidence.target_asset_id, evidence.aspect_name)
            group = self._groups.setdefault(group_key, {})
            if evidence.semantic_key in group:
                raise CatalogMetadataParseError(
                    CatalogMetadataParseFailureCode.DUPLICATE_SEMANTIC_KEY,
                    "The upload repeats or conflicts with an existing semantic operation.",
                    ordinal=ordinal,
                )
            maximum_group_operations = (
                self._definition.maximum_column_operations_per_candidate
                if evidence.record_kind is CatalogMetadataRecordKind.COLUMN_DESCRIPTION
                else self._definition.maximum_controlled_operations_per_candidate
                if evidence.record_kind
                in {
                    CatalogMetadataRecordKind.DATASET_TAG,
                    CatalogMetadataRecordKind.DATASET_TERM,
                }
                else 1
            )
            if len(group) >= maximum_group_operations:
                raise CatalogMetadataParseError(
                    CatalogMetadataParseFailureCode.TOO_MANY_GROUP_OPERATIONS,
                    "One catalog-metadata candidate exceeds its executable operation limit.",
                    ordinal=ordinal,
                )
            group[evidence.semantic_key] = evidence
            self._group_rules.setdefault(group_key, rule)
        self._row_count += 1

    def iter_candidates(self) -> Iterable[CatalogMetadataCandidateDraft]:
        for group_ordinal, (group_key, grouped_rows) in enumerate(
            self._groups.items(),
            start=1,
        ):
            target_asset_id, aspect_name = group_key
            group_rows = tuple(grouped_rows.values())
            first = group_rows[0]
            rule = self._group_rules[group_key]
            submitted_identity_hash = catalog_metadata_submitted_identity_hash(
                workspace_id=self._workspace_id,
                target_asset_id=target_asset_id,
                platform=first.platform,
                database_name=first.database_name,
                schema_name=first.schema_name,
                table_name=first.table_name,
                aspect_name=aspect_name,
                definition=self._definition,
            )
            candidate_hash = catalog_metadata_candidate_hash(
                workspace_id=self._workspace_id,
                ordinal=group_ordinal,
                target_asset_id=target_asset_id,
                candidate_kind=rule.candidate_kind,
                aspect_name=aspect_name,
                submitted_identity_hash=submitted_identity_hash,
                row_hashes=tuple(row.row_hash for row in group_rows),
                definition=self._definition,
            )
            yield CatalogMetadataCandidateDraft(
                workspace_id=self._workspace_id,
                ordinal=group_ordinal,
                target_asset_id=target_asset_id,
                platform=first.platform,
                database_name=first.database_name,
                schema_name=first.schema_name,
                table_name=first.table_name,
                record_kind=first.record_kind,
                candidate_kind=rule.candidate_kind,
                aspect_name=aspect_name,
                rows=group_rows,
                submitted_identity_hash=submitted_identity_hash,
                candidate_hash=candidate_hash,
            )


def compile_catalog_metadata_candidates(
    *,
    workspace_id: UUID,
    rows: Iterable[tuple[int, Sequence[str]]],
    definition: TypedUploadProfileDefinition,
) -> tuple[CatalogMetadataCandidateDraft, ...]:
    """Compile bounded in-process values for tests and synchronous callers."""

    compilation = CatalogMetadataCandidateAccumulator(
        workspace_id=workspace_id,
        definition=definition,
    )
    for ordinal, values in rows:
        compilation.add_row(ordinal=ordinal, values=values)
    return tuple(compilation.iter_candidates())


def catalog_metadata_submitted_identity_hash(
    *,
    workspace_id: UUID,
    target_asset_id: UUID,
    platform: str,
    database_name: str,
    schema_name: str,
    table_name: str,
    aspect_name: CatalogMetadataAspect,
    definition: TypedUploadProfileDefinition,
) -> str:
    return canonical_json_hash(
        {
            "aspect_name": aspect_name.value,
            "configuration_hash": definition.configuration_hash,
            "content_profile": definition.content_profile.value,
            "contract": _GROUP_IDENTITY_HASH_CONTRACT,
            "database_name": database_name,
            "platform": platform,
            "schema_name": schema_name,
            "schema_version": definition.schema_version,
            "table_name": table_name,
            "target_asset_id": str(target_asset_id),
            "workspace_id": str(workspace_id),
        }
    )


def catalog_metadata_semantic_target_hash(
    *,
    workspace_id: UUID,
    target_asset_id: UUID,
    aspect_name: CatalogMetadataAspect,
    semantic_key: str,
) -> str:
    if not semantic_key:
        raise ValueError("Catalog metadata semantic keys cannot be empty.")
    return canonical_json_hash(
        {
            "aspect_name": aspect_name.value,
            "contract": _SEMANTIC_TARGET_HASH_CONTRACT,
            "semantic_key": semantic_key,
            "target_asset_id": str(target_asset_id),
            "workspace_id": str(workspace_id),
        }
    )


def catalog_metadata_row_hash(
    *,
    workspace_id: UUID,
    ordinal: int,
    target_asset_id: UUID,
    platform: str,
    database_name: str,
    schema_name: str,
    table_name: str,
    record_kind: CatalogMetadataRecordKind,
    aspect_name: CatalogMetadataAspect,
    operation: CatalogMetadataOperation,
    field_path: str | None,
    value_text: str | None,
    controlled_ref: UUID | None,
    definition: TypedUploadProfileDefinition,
) -> str:
    return canonical_json_hash(
        {
            "aspect_name": aspect_name.value,
            "configuration_hash": definition.configuration_hash,
            "content_profile": definition.content_profile.value,
            "contract": _ROW_HASH_CONTRACT,
            "controlled_ref": str(controlled_ref) if controlled_ref is not None else None,
            "database_name": database_name,
            "evidence_version": CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION,
            "field_path": field_path,
            "operation": operation.value,
            "ordinal": ordinal,
            "platform": platform,
            "record_kind": record_kind.value,
            "schema_name": schema_name,
            "schema_version": definition.schema_version,
            "table_name": table_name,
            "target_asset_id": str(target_asset_id),
            "value_text": value_text,
            "workspace_id": str(workspace_id),
        }
    )


def catalog_metadata_candidate_hash(
    *,
    workspace_id: UUID,
    ordinal: int,
    target_asset_id: UUID,
    candidate_kind: CatalogMetadataCandidateKind,
    aspect_name: CatalogMetadataAspect,
    submitted_identity_hash: str,
    row_hashes: tuple[str, ...],
    definition: TypedUploadProfileDefinition,
) -> str:
    return canonical_json_hash(
        {
            "aspect_name": aspect_name.value,
            "candidate_kind": candidate_kind.value,
            "configuration_hash": definition.configuration_hash,
            "content_profile": definition.content_profile.value,
            "contract": _GROUP_HASH_CONTRACT,
            "evidence_version": CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION,
            "group_ordinal": ordinal,
            "ordered_row_hashes": list(row_hashes),
            "schema_version": definition.schema_version,
            "submitted_identity_hash": submitted_identity_hash,
            "target_asset_id": str(target_asset_id),
            "workspace_id": str(workspace_id),
        }
    )


def catalog_metadata_row_root(row_hashes: Sequence[str]) -> str:
    if not row_hashes or any(
        len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
        for value in row_hashes
    ):
        raise ValueError("Catalog metadata row hashes must be a non-empty SHA-256 sequence.")
    return canonical_json_hash(
        {
            "contract": _ROW_ROOT_CONTRACT,
            "ordered_row_hashes": list(row_hashes),
        }
    )


def catalog_metadata_candidate_root(
    *,
    workspace_id: UUID,
    candidates: Iterable[CatalogMetadataCandidateDraft],
    definition: TypedUploadProfileDefinition,
) -> bytes:
    current = catalog_metadata_candidate_root_seed(
        workspace_id=workspace_id,
        definition=definition,
    )
    for ordinal, candidate in enumerate(candidates, start=1):
        current = advance_catalog_metadata_candidate_root(
            current=current,
            ordinal=ordinal,
            candidate_hash=candidate.candidate_hash,
        )
    return current


def catalog_metadata_candidate_root_seed(
    *,
    workspace_id: UUID,
    definition: TypedUploadProfileDefinition,
) -> bytes:
    return hashlib.sha256(
        _GROUP_ROOT_CONTRACT
        + bytes.fromhex(
            canonical_json_hash(
                {
                    "configuration_hash": definition.configuration_hash,
                    "content_profile": definition.content_profile.value,
                    "evidence_version": CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION,
                    "schema_version": definition.schema_version,
                    "workspace_id": str(workspace_id),
                }
            )
        )
    ).digest()


def advance_catalog_metadata_candidate_root(
    *,
    current: bytes,
    ordinal: int,
    candidate_hash: str,
) -> bytes:
    if (
        len(current) != hashlib.sha256().digest_size
        or ordinal < 1
        or len(candidate_hash) != 64
        or any(character not in "0123456789abcdef" for character in candidate_hash)
    ):
        raise ValueError("Catalog metadata candidate root evidence is invalid.")
    return hashlib.sha256(
        _GROUP_ROOT_CONTRACT
        + current
        + ordinal.to_bytes(8, byteorder="big", signed=False)
        + bytes.fromhex(candidate_hash)
    ).digest()


def _row_evidences_from_values(
    *,
    workspace_id: UUID,
    ordinal: int,
    values: Sequence[str],
    definition: TypedUploadProfileDefinition,
) -> list[tuple[CatalogMetadataRowEvidence, _RowRule]]:
    if len(values) != len(definition.headers):
        raise CatalogMetadataParseError(
            CatalogMetadataParseFailureCode.INVALID_COLUMN_COUNT,
            "The catalog-metadata row has an invalid column count.",
            ordinal=ordinal,
        )
    (
        urn,
        table_name,
        table_domain,
        table_desc,
        table_owner,
        table_term,
        table_tags,
        col_name,
        col_desc,
        col_term,
        col_tags,
    ) = values

    if not urn.startswith("urn:li:dataset:"):
        raise CatalogMetadataParseError(
            CatalogMetadataParseFailureCode.INVALID_IDENTITY_FIELD,
            "The urn must start with urn:li:dataset:.",
            ordinal=ordinal,
        )

    # Use deterministic UUID5 for target_asset_id since we have no DB session to look up URN
    target_asset_id = uuid5(NAMESPACE_URL, f"urn:datariver:dataset:{urn}")
    
    # We must extract platform/database/schema from URN for identity validation
    platform = "postgres"
    database_name = "db"
    schema_name = "public"
    try:
        if "(" in urn and "," in urn:
            parts = urn.split("(", 1)[1].split(",")
            if len(parts) >= 2:
                platform = parts[0].split(":")[-1] if ":" in parts[0] else parts[0]
                path_parts = parts[1].split(".")
                if len(path_parts) >= 3:
                    database_name = path_parts[0]
                    schema_name = path_parts[1]
    except Exception:
        pass

    evidences = []

    def _add_evidence(record_kind, operation, field_path_text, value_text, controlled_ref_text):
        rule = _ROW_RULES[record_kind]
        field_path, description, controlled_ref, semantic_key = _validate_row_shape(
            record_kind=record_kind,
            operation=operation,
            field_path_text=field_path_text,
            value_text=value_text,
            controlled_ref_text=controlled_ref_text,
            definition=definition,
            ordinal=ordinal,
        )
        row_hash = catalog_metadata_row_hash(
            workspace_id=workspace_id,
            ordinal=ordinal,
            target_asset_id=target_asset_id,
            platform=platform,
            database_name=database_name,
            schema_name=schema_name,
            table_name=table_name,
            record_kind=record_kind,
            aspect_name=rule.aspect_name,
            operation=operation,
            field_path=field_path,
            value_text=description,
            controlled_ref=controlled_ref,
            definition=definition,
        )
        evidences.append((
            CatalogMetadataRowEvidence(
                workspace_id=workspace_id,
                ordinal=ordinal,
                target_asset_id=target_asset_id,
                platform=platform,
                database_name=database_name,
                schema_name=schema_name,
                table_name=table_name,
                record_kind=record_kind,
                aspect_name=rule.aspect_name,
                operation=operation,
                field_path=field_path,
                value_text=description,
                controlled_ref=controlled_ref,
                semantic_key=semantic_key,
                row_hash=row_hash,
            ),
            rule,
        ))

    # table_domain
    if table_domain:
        _add_evidence(CatalogMetadataRecordKind.DATASET_DOMAIN, CatalogMetadataOperation.SET, "", "", table_domain)
    
    # table_desc
    if table_desc:
        _add_evidence(CatalogMetadataRecordKind.TABLE_DESCRIPTION, CatalogMetadataOperation.SET, "", table_desc, "")
        
    # table_owner
    if table_owner:
        _add_evidence(CatalogMetadataRecordKind.DATASET_OWNER, CatalogMetadataOperation.SET, "", "", table_owner)

    # table_term (comma separated, must be UUIDs per _controlled_ref)
    if table_term:
        for term in table_term.split(","):
            if term.strip():
                _add_evidence(CatalogMetadataRecordKind.DATASET_TERM, CatalogMetadataOperation.ADD, "", "", term.strip())

    # table_tags (comma separated)
    if table_tags:
        for tag in table_tags.split(","):
            if tag.strip():
                _add_evidence(CatalogMetadataRecordKind.DATASET_TAG, CatalogMetadataOperation.ADD, "", "", tag.strip())

    # col_desc
    if col_name and col_desc:
        _add_evidence(CatalogMetadataRecordKind.COLUMN_DESCRIPTION, CatalogMetadataOperation.SET, col_name, col_desc, "")

    # col_term (WARNING: No backend RecordKind for Column Terms, mapping to DATASET_TERM as temporary workaround)
    if col_name and col_term:
        for term in col_term.split(","):
            if term.strip():
                _add_evidence(CatalogMetadataRecordKind.DATASET_TERM, CatalogMetadataOperation.ADD, "", "", term.strip())

    # col_tags (WARNING: No backend RecordKind for Column Tags, mapping to DATASET_TAG as temporary workaround)
    if col_name and col_tags:
        for tag in col_tags.split(","):
            if tag.strip():
                _add_evidence(CatalogMetadataRecordKind.DATASET_TAG, CatalogMetadataOperation.ADD, "", "", tag.strip())

    return evidences


def _validate_row_shape(
    *,
    record_kind: CatalogMetadataRecordKind,
    operation: CatalogMetadataOperation,
    field_path_text: str,
    value_text: str,
    controlled_ref_text: str,
    definition: TypedUploadProfileDefinition,
    ordinal: int,
) -> tuple[str | None, str | None, UUID | None, str]:
    if record_kind in {
        CatalogMetadataRecordKind.TABLE_DESCRIPTION,
        CatalogMetadataRecordKind.COLUMN_DESCRIPTION,
    }:
        field_path = _description_field_path(
            record_kind=record_kind,
            value=field_path_text,
            definition=definition,
            ordinal=ordinal,
        )
        if controlled_ref_text:
            raise _invalid_shape(ordinal)
        if operation is CatalogMetadataOperation.SET:
            if (
                not value_text
                or len(value_text) > definition.maximum_description_characters
                or _contains_forbidden_description_control(value_text)
            ):
                raise CatalogMetadataParseError(
                    CatalogMetadataParseFailureCode.INVALID_DESCRIPTION,
                    "A description SET requires a bounded, valid value_text.",
                    ordinal=ordinal,
                )
            description: str | None = value_text
        else:
            if value_text:
                raise _invalid_shape(ordinal)
            description = None
        semantic_key = (
            record_kind.value if field_path is None else f"{record_kind.value}:{field_path}"
        )
        return field_path, description, None, semantic_key

    if field_path_text or value_text:
        raise _invalid_shape(ordinal)
    if record_kind is CatalogMetadataRecordKind.DATASET_DOMAIN:
        if operation is CatalogMetadataOperation.CLEAR:
            if controlled_ref_text:
                raise _invalid_shape(ordinal)
            return None, None, None, record_kind.value
        controlled_ref = _controlled_ref(
            controlled_ref_text,
            definition=definition,
            ordinal=ordinal,
        )
        return None, None, controlled_ref, record_kind.value

    controlled_ref = _controlled_ref(
        controlled_ref_text,
        definition=definition,
        ordinal=ordinal,
    )
    return (
        None,
        None,
        controlled_ref,
        f"{record_kind.value}:{controlled_ref}",
    )


def _description_field_path(
    *,
    record_kind: CatalogMetadataRecordKind,
    value: str,
    definition: TypedUploadProfileDefinition,
    ordinal: int,
) -> str | None:
    if record_kind is CatalogMetadataRecordKind.TABLE_DESCRIPTION:
        if value:
            raise _invalid_shape(ordinal)
        return None
    if (
        not value
        or value != value.strip()
        or len(value) > definition.maximum_field_path_characters
        or _contains_forbidden_identity_control(value)
    ):
        raise CatalogMetadataParseError(
            CatalogMetadataParseFailureCode.INVALID_FIELD_PATH,
            "A column description requires one exact, bounded field_path.",
            ordinal=ordinal,
        )
    return value


def _controlled_ref(
    value: str,
    *,
    definition: TypedUploadProfileDefinition,
    ordinal: int,
) -> UUID:
    if len(value) > definition.maximum_controlled_ref_characters:
        raise CatalogMetadataParseError(
            CatalogMetadataParseFailureCode.INVALID_CONTROLLED_REF,
            "controlled_ref must be a canonical workspace vocabulary UUID.",
            ordinal=ordinal,
        )
    return _canonical_uuid(
        value,
        failure_code=CatalogMetadataParseFailureCode.INVALID_CONTROLLED_REF,
        message="controlled_ref must be a canonical workspace vocabulary UUID.",
        ordinal=ordinal,
    )


def _canonical_uuid(
    value: str,
    *,
    failure_code: CatalogMetadataParseFailureCode,
    message: str,
    ordinal: int,
) -> UUID:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise CatalogMetadataParseError(
            failure_code,
            message,
            ordinal=ordinal,
        ) from error
    if value != str(parsed) or parsed.int == 0:
        raise CatalogMetadataParseError(
            failure_code,
            message,
            ordinal=ordinal,
        )
    return parsed


def _translate_csv_error(error: TypedUploadParseError) -> CatalogMetadataParseError:
    try:
        failure_code = CatalogMetadataParseFailureCode(error.failure_code.value)
    except ValueError:
        failure_code = CatalogMetadataParseFailureCode.INVALID_CSV
    return CatalogMetadataParseError(
        failure_code,
        str(error),
        ordinal=error.ordinal,
    )


def _invalid_shape(ordinal: int) -> CatalogMetadataParseError:
    return CatalogMetadataParseError(
        CatalogMetadataParseFailureCode.INVALID_ROW_SHAPE,
        "The row contains fields that are not allowed for its kind and operation.",
        ordinal=ordinal,
    )


def _validate_expected_hash(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("The expected source SHA-256 must be lowercase hexadecimal.")


def _contains_forbidden_identity_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _contains_forbidden_description_control(value: str) -> bool:
    return any(
        (ord(character) < 32 and character not in {"\t", "\r", "\n"}) or ord(character) == 127
        for character in value
    )
