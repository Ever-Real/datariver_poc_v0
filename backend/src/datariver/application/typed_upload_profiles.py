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

    @property
    def configuration_hash(self) -> str:
        return canonical_json_hash(
            {
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
        )


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
    maximum_file_bytes=512 * 1024 * 1024,
    maximum_rows=50_000,
    maximum_row_bytes=64 * 1024,
    maximum_platform_characters=100,
    maximum_database_name_characters=255,
    maximum_schema_name_characters=255,
    maximum_table_name_characters=500,
    maximum_description_characters=10_000,
    acceptance_validator_version="integrity-format-v1",
    parser_version="dataset-description-csv-parser-v1",
    schema_version="dataset-description-csv-schema-v1",
)


def typed_profile_definition(
    content_profile: UploadContentProfile,
) -> TypedUploadProfileDefinition:
    if content_profile is UploadContentProfile.DATASET_DESCRIPTION_CSV_V1:
        return DATASET_DESCRIPTION_CSV_V1
    raise ValidationError("The upload profile has no typed preparation workflow.")


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
        raise ValidationError("The selected content profile requires text/csv.")
    if not display_name.lower().endswith(definition.filename_suffix):
        raise ValidationError("The selected content profile requires a .csv filename.")
    if size_bytes > definition.maximum_file_bytes:
        raise ValidationError("The selected content profile exceeds its bounded file-size limit.")
