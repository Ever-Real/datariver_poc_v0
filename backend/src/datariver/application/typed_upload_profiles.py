from __future__ import annotations

from dataclasses import dataclass

from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.registration import UploadContentProfile


@dataclass(frozen=True, slots=True)
class TypedUploadProfileDefinition:
    content_profile: UploadContentProfile
    content_type: str
    filename_suffix: str
    encoding: str
    delimiter: str
    headers: tuple[str, ...]
    maximum_file_bytes: int
    maximum_rows: int
    maximum_row_bytes: int
    maximum_platform_characters: int
    maximum_database_name_characters: int
    maximum_schema_name_characters: int
    maximum_table_name_characters: int
    maximum_description_characters: int
    acceptance_validator_version: str
    parser_version: str
    schema_version: str
    profile_contract: str = "dataset-description-v2"
    maximum_field_path_characters: int = 2_000
    maximum_controlled_ref_characters: int = 36
    maximum_column_operations_per_candidate: int = 1_000
    maximum_controlled_operations_per_candidate: int = 100

    @property
    def configuration_hash(self) -> str:
        document: dict[str, object] = {
            "acceptance_validator_version": self.acceptance_validator_version,
            "content_profile": self.content_profile.value,
            "content_type": self.content_type,
            "delimiter": self.delimiter,
            "encoding": self.encoding,
            "filename_suffix": self.filename_suffix,
            "headers": list(self.headers),
            "maximum_description_characters": self.maximum_description_characters,
            "maximum_file_bytes": self.maximum_file_bytes,
            "maximum_database_name_characters": self.maximum_database_name_characters,
            "maximum_platform_characters": self.maximum_platform_characters,
            "maximum_row_bytes": self.maximum_row_bytes,
            "maximum_rows": self.maximum_rows,
            "maximum_schema_name_characters": self.maximum_schema_name_characters,
            "maximum_table_name_characters": self.maximum_table_name_characters,
            "parser_version": self.parser_version,
            "schema_version": self.schema_version,
        }
        if self.profile_contract != "dataset-description-v2":
            document.update(
                {
                    "maximum_controlled_ref_characters": (self.maximum_controlled_ref_characters),
                    "maximum_controlled_operations_per_candidate": (
                        self.maximum_controlled_operations_per_candidate
                    ),
                    "maximum_column_operations_per_candidate": (
                        self.maximum_column_operations_per_candidate
                    ),
                    "maximum_field_path_characters": self.maximum_field_path_characters,
                    "profile_contract": self.profile_contract,
                }
            )
        return canonical_json_hash(document)


DATASET_DESCRIPTION_CSV_V1 = TypedUploadProfileDefinition(
    content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
    content_type="text/csv",
    filename_suffix=".csv",
    encoding="utf-8-sig",
    delimiter=",",
    headers=(
        "asset_id",
        "platform",
        "database_name",
        "schema_name",
        "table_name",
        "description",
    ),
    maximum_file_bytes=16 * 1024 * 1024,
    maximum_rows=10_000,
    maximum_row_bytes=64 * 1024,
    maximum_platform_characters=100,
    maximum_database_name_characters=255,
    maximum_schema_name_characters=255,
    maximum_table_name_characters=500,
    maximum_description_characters=10_000,
    acceptance_validator_version="integrity-format-v2-low-resource",
    parser_version="dataset-description-csv-parser-v3",
    schema_version="dataset-description-csv-schema-v1",
)

DATASET_DESCRIPTION_XLSX_V1 = TypedUploadProfileDefinition(
    content_profile=UploadContentProfile.DATASET_DESCRIPTION_XLSX_V1,
    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    filename_suffix=".xlsx",
    encoding="opc-xml-utf8",
    delimiter="",
    headers=DATASET_DESCRIPTION_CSV_V1.headers,
    maximum_file_bytes=16 * 1024 * 1024,
    maximum_rows=10_000,
    maximum_row_bytes=64 * 1024,
    maximum_platform_characters=100,
    maximum_database_name_characters=255,
    maximum_schema_name_characters=255,
    maximum_table_name_characters=500,
    maximum_description_characters=10_000,
    acceptance_validator_version="integrity-xlsx-v2-low-resource",
    parser_version="dataset-description-xlsx-parser-v2",
    schema_version="dataset-description-xlsx-schema-v1",
)

_CATALOG_METADATA_ROWS_HEADERS = (
    "urn",
    "table_name",
    "table_domain",
    "table_desc",
    "table_owner",
    "table_term",
    "table_tags",
    "col_name",
    "col_desc",
    "col_term",
    "col_tags",
)

CATALOG_METADATA_ROWS_CSV_V1 = TypedUploadProfileDefinition(
    content_profile=UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
    content_type="text/csv",
    filename_suffix=".csv",
    encoding="utf-8-sig",
    delimiter=",",
    headers=_CATALOG_METADATA_ROWS_HEADERS,
    maximum_file_bytes=16 * 1024 * 1024,
    maximum_rows=10_000,
    maximum_row_bytes=64 * 1024,
    maximum_platform_characters=100,
    maximum_database_name_characters=255,
    maximum_schema_name_characters=255,
    maximum_table_name_characters=500,
    maximum_description_characters=10_000,
    acceptance_validator_version="integrity-format-v3-catalog-metadata-rows",
    parser_version="catalog-metadata-rows-csv-parser-v1",
    schema_version="catalog-metadata-rows-schema-v1",
    profile_contract="catalog-metadata-rows-v1",
)

CATALOG_METADATA_ROWS_XLSX_V1 = TypedUploadProfileDefinition(
    content_profile=UploadContentProfile.CATALOG_METADATA_ROWS_XLSX_V1,
    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    filename_suffix=".xlsx",
    encoding="opc-xml-utf8",
    delimiter="",
    headers=_CATALOG_METADATA_ROWS_HEADERS,
    maximum_file_bytes=16 * 1024 * 1024,
    maximum_rows=10_000,
    maximum_row_bytes=64 * 1024,
    maximum_platform_characters=100,
    maximum_database_name_characters=255,
    maximum_schema_name_characters=255,
    maximum_table_name_characters=500,
    maximum_description_characters=10_000,
    acceptance_validator_version="integrity-xlsx-v3-catalog-metadata-rows",
    parser_version="catalog-metadata-rows-xlsx-parser-v1",
    schema_version="catalog-metadata-rows-schema-v1",
    profile_contract="catalog-metadata-rows-v1",
)

TYPED_PROFILE_DEFINITIONS = {
    definition.content_profile: definition
    for definition in (
        CATALOG_METADATA_ROWS_CSV_V1,
        CATALOG_METADATA_ROWS_XLSX_V1,
    )
}


def typed_profile_definition(
    content_profile: UploadContentProfile,
) -> TypedUploadProfileDefinition:
    try:
        return TYPED_PROFILE_DEFINITIONS[content_profile]
    except KeyError as error:
        raise ValidationError("The upload profile has no typed preparation workflow.") from error


def validate_upload_profile(
    *,
    content_profile: UploadContentProfile,
    display_name: str,
    content_type: str,
    size_bytes: int,
) -> None:
    if content_profile is UploadContentProfile.FORMAT_ONLY_V1:
        return
    definition = typed_profile_definition(content_profile)
    if content_type != definition.content_type:
        raise ValidationError("The selected content profile has an invalid content type.")
    if not display_name.lower().endswith(definition.filename_suffix):
        raise ValidationError(
            f"The selected content profile requires a {definition.filename_suffix} filename."
        )
    if size_bytes > definition.maximum_file_bytes:
        raise ValidationError("The selected content profile exceeds its bounded file-size limit.")
