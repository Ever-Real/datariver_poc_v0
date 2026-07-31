from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import PurePath

from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import ObjectStore, UploadValidationStore
from datariver.application.typed_upload_profiles import typed_profile_definition
from datariver.domain.authz import Classification
from datariver.domain.common import DomainError, ValidationError
from datariver.domain.registration import UploadContentProfile, UploadManifest

PREVIEW_LIMIT = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Inspection:
    size_bytes: int
    sha256: str
    prefix: bytes
    tail: bytes
    contains_vba: bool
    contains_openxml_external_link: bool = False


class UploadValidationWorker:
    """Performs bounded-memory integrity/format checks before durable promotion."""

    def __init__(
        self,
        *,
        store: UploadValidationStore,
        object_store: ObjectStore,
        accepted_bucket: str,
        lease_seconds: int = 120,
        maximum_attempts: int = 4,
    ) -> None:
        self._store = store
        self._object_store = object_store
        self._accepted_bucket = accepted_bucket
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts

    async def run_once(self) -> bool:
        manifest = await self._store.claim_next(
            lease_seconds=self._lease_seconds,
            maximum_attempts=self._maximum_attempts,
        )
        if manifest is None:
            return False
        source_bucket = manifest.bucket
        source_key = manifest.object_key
        destination_namespace = (
            "knowledge-eligible"
            if (
                manifest.declared_mime == "application/pdf"
                and manifest.classification <= Classification.INTERNAL
            )
            else "accepted"
        )
        destination_key = (
            f"{destination_namespace}/{manifest.workspace_id}/{manifest.upload_id}/"
            f"validation-v{manifest.version}-attempt-{manifest.validation_attempts}"
        )
        destination_created = False
        acceptance_started = False
        try:
            inspection = await self._inspect(manifest)
            summary = self._validate_format(manifest, inspection)
            promoted = await self._object_store.copy_object(
                source_bucket=source_bucket,
                source_key=source_key,
                destination_bucket=self._accepted_bucket,
                destination_key=destination_key,
            )
            destination_created = True
            if (
                promoted.size_bytes != inspection.size_bytes
                or promoted.content_type != manifest.declared_mime
            ):
                raise ExternalDependencyError(
                    "Promoted object metadata did not reconcile.",
                    dependency="object_store",
                    retryable=True,
                    provider_code="PROMOTION_MISMATCH",
                )
            await self._inspect_object(
                manifest,
                bucket=self._accepted_bucket,
                object_key=destination_key,
            )
            acceptance_started = True
            accepted = await self._store.mark_accepted(
                manifest=manifest,
                accepted_bucket=self._accepted_bucket,
                accepted_object_key=destination_key,
                validated_sha256=inspection.sha256,
                validation_summary=summary,
            )
            if not accepted:
                await self._delete_best_effort(
                    bucket=self._accepted_bucket,
                    object_key=destination_key,
                )
                return True
            await self._delete_best_effort(bucket=source_bucket, object_key=source_key)
        except DomainError as error:
            if destination_created and not acceptance_started:
                await self._delete_best_effort(
                    bucket=self._accepted_bucket,
                    object_key=destination_key,
                )
            await self._store.mark_failed(
                manifest=manifest,
                error_code=self._error_code(error),
                retryable=self._retryable(error),
                maximum_attempts=self._maximum_attempts,
            )
        except Exception as error:
            if destination_created and not acceptance_started:
                await self._delete_best_effort(
                    bucket=self._accepted_bucket,
                    object_key=destination_key,
                )
            await self._store.mark_failed(
                manifest=manifest,
                error_code=f"UNEXPECTED_{type(error).__name__}"[:100],
                retryable=True,
                maximum_attempts=self._maximum_attempts,
            )
        return True

    async def _inspect(self, manifest: UploadManifest) -> Inspection:
        return await self._inspect_object(
            manifest,
            bucket=manifest.bucket,
            object_key=manifest.object_key,
        )

    async def _inspect_object(
        self,
        manifest: UploadManifest,
        *,
        bucket: str,
        object_key: str,
    ) -> Inspection:
        digest = hashlib.sha256()
        prefix = bytearray()
        tail = b""
        marker_window = b""
        size = 0
        contains_vba = False
        contains_openxml_external_link = False
        async for chunk in self._object_store.iter_object_chunks(
            bucket=bucket, object_key=object_key
        ):
            size += len(chunk)
            if size > manifest.declared_size_bytes:
                raise ValidationError(
                    "Uploaded object is larger than declared.",
                    details={"code": "SIZE_MISMATCH"},
                )
            digest.update(chunk)
            if len(prefix) < PREVIEW_LIMIT:
                prefix.extend(chunk[: PREVIEW_LIMIT - len(prefix)])
            tail = (tail + chunk)[-8:]
            search_window = marker_window + chunk
            if b"vbaproject.bin" in search_window.lower():
                contains_vba = True
            if b"externallinks/" in search_window.lower():
                contains_openxml_external_link = True
            marker_window = search_window[-256:]
        actual_hash = digest.hexdigest()
        if size != manifest.declared_size_bytes:
            raise ValidationError(
                "Uploaded object size does not match its declaration.",
                details={"code": "SIZE_MISMATCH"},
            )
        if actual_hash != manifest.declared_sha256:
            raise ValidationError(
                "Uploaded object checksum does not match its declaration.",
                details={"code": "CHECKSUM_MISMATCH"},
            )
        return Inspection(
            size,
            actual_hash,
            bytes(prefix),
            tail,
            contains_vba,
            contains_openxml_external_link,
        )

    async def _delete_best_effort(self, *, bucket: str, object_key: str) -> None:
        try:
            await self._object_store.delete_object(bucket=bucket, object_key=object_key)
        except DomainError:
            pass

    @staticmethod
    def _validate_format(manifest: UploadManifest, inspection: Inspection) -> dict[str, object]:
        suffix = PurePath(manifest.display_name).suffix.lower()
        mime = manifest.declared_mime
        expected_suffixes = {
            "application/pdf": {".pdf"},
            "text/csv": {".csv"},
            "text/plain": {".txt"},
            "application/json": {".json"},
            "text/json": {".json"},
            "application/yaml": {".yaml", ".yml"},
            "text/yaml": {".yaml", ".yml"},
            "application/xml": {".xml"},
            "text/xml": {".xml"},
            "text/html": {".html", ".htm"},
            "application/xhtml+xml": {".html", ".htm"},
            "application/x-parquet": {".parquet"},
            "application/vnd.apache.parquet": {".parquet"},
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": {".pptx"},
        }
        accepted_suffixes = expected_suffixes.get(mime)
        if accepted_suffixes is None or suffix not in accepted_suffixes:
            raise ValidationError(
                "Filename extension does not match the declared content type.",
                details={"code": "EXTENSION_MISMATCH"},
            )
        validator_version = (
            (
                "integrity-openxml-v1"
                if mime
                in {
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                }
                else "integrity-format-v1"
            )
            if manifest.content_profile is UploadContentProfile.FORMAT_ONLY_V1
            else typed_profile_definition(manifest.content_profile).acceptance_validator_version
        )
        base: dict[str, object] = {
            "validator_version": validator_version,
            "size_bytes": inspection.size_bytes,
            "sha256": inspection.sha256,
            "content_type": mime,
        }
        if mime == "application/pdf":
            if not inspection.prefix.startswith(b"%PDF-") or b"%%EOF" not in inspection.tail:
                raise ValidationError(
                    "PDF signature is invalid.", details={"code": "PDF_SIGNATURE"}
                )
            return {**base, "coverage": "FULL_SIGNATURE"}
        if mime == "text/csv":
            return {**base, **UploadValidationWorker._validate_csv(inspection)}
        if mime in {"application/json", "text/json"}:
            return {**base, **UploadValidationWorker._validate_json(inspection)}
        if mime in {"application/yaml", "text/yaml"}:
            return {**base, **UploadValidationWorker._validate_yaml(inspection)}
        if mime == "text/plain":
            return {**base, **UploadValidationWorker._validate_utf8_text(inspection)}
        if mime in {"application/xml", "text/xml", "text/html", "application/xhtml+xml"}:
            return {
                **base,
                **UploadValidationWorker._validate_markup(
                    inspection,
                    reject_entities=mime in {"application/xml", "text/xml"},
                ),
            }
        if mime in {"application/x-parquet", "application/vnd.apache.parquet"}:
            if not inspection.prefix.startswith(b"PAR1") or not inspection.tail.endswith(b"PAR1"):
                raise ValidationError(
                    "Parquet signature is invalid.", details={"code": "PARQUET_SIGNATURE"}
                )
            return {**base, "coverage": "FULL_SIGNATURE"}
        if (
            not inspection.prefix.startswith(b"PK\x03\x04")
            or inspection.contains_vba
            or inspection.contains_openxml_external_link
        ):
            raise ValidationError(
                "OpenXML package signature is invalid or contains a macro payload.",
                details={"code": "OPENXML_UNSAFE_PACKAGE"},
            )
        return {**base, "coverage": "FULL_SIGNATURE", "macros_detected": False}

    @staticmethod
    def _validate_utf8_text(inspection: Inspection) -> dict[str, object]:
        try:
            text = inspection.prefix.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValidationError(
                "Text sources must be UTF-8 encoded.",
                details={"code": "TEXT_ENCODING"},
            ) from error
        if "\x00" in text:
            raise ValidationError("Text sources contain NUL bytes.", details={"code": "TEXT_NUL"})
        return {
            "coverage": "FULL_TEXT" if inspection.size_bytes <= PREVIEW_LIMIT else "SAMPLED_TEXT"
        }

    @staticmethod
    def _validate_markup(
        inspection: Inspection,
        *,
        reject_entities: bool,
    ) -> dict[str, object]:
        result = UploadValidationWorker._validate_utf8_text(inspection)
        lowered = inspection.prefix[:8192].lower()
        if reject_entities and (b"<!doctype" in lowered or b"<!entity" in lowered):
            raise ValidationError(
                "XML DTD and entity declarations are not accepted.",
                details={"code": "XML_ENTITY_DECLARATION"},
            )
        return result

    @staticmethod
    def _validate_csv(inspection: Inspection) -> dict[str, object]:
        try:
            text = inspection.prefix.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValidationError(
                "CSV must be UTF-8 encoded.", details={"code": "CSV_ENCODING"}
            ) from error
        if "\x00" in text:
            raise ValidationError("CSV contains NUL bytes.", details={"code": "CSV_NUL"})
        sampled = text if inspection.size_bytes <= PREVIEW_LIMIT else text.rsplit("\n", 1)[0]
        try:
            rows = []
            for index, row in enumerate(csv.reader(io.StringIO(sampled), strict=True)):
                rows.append(row)
                if index >= 100:
                    break
        except csv.Error as error:
            raise ValidationError(
                "CSV structure is invalid.", details={"code": "CSV_STRUCTURE"}
            ) from error
        if not rows or not rows[0] or any(not value.strip() for value in rows[0]):
            raise ValidationError(
                "CSV requires a non-empty header row.", details={"code": "CSV_HEADER"}
            )
        column_count = len(rows[0])
        if any(len(row) != column_count for row in rows[1:]):
            raise ValidationError(
                "CSV sampled rows have inconsistent column counts.",
                details={"code": "CSV_COLUMN_COUNT"},
            )
        return {
            "coverage": "FULL" if inspection.size_bytes <= PREVIEW_LIMIT else "SAMPLED",
            "column_count": column_count,
            "rows_sampled": max(len(rows) - 1, 0),
        }

    @staticmethod
    def _validate_json(inspection: Inspection) -> dict[str, object]:
        if inspection.size_bytes > PREVIEW_LIMIT:
            raise ValidationError(
                "JSON above 8 MiB must be converted to a streaming tabular format.",
                details={"code": "JSON_SIZE_POLICY"},
            )
        try:
            value = json.loads(inspection.prefix)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(
                "JSON structure or UTF-8 encoding is invalid.",
                details={"code": "JSON_STRUCTURE"},
            ) from error
        if not isinstance(value, (dict, list)):
            raise ValidationError(
                "JSON root must be an object or array.", details={"code": "JSON_ROOT"}
            )
        return {"coverage": "FULL", "root_type": "object" if isinstance(value, dict) else "array"}

    @staticmethod
    def _validate_yaml(inspection: Inspection) -> dict[str, object]:
        try:
            text = inspection.prefix.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValidationError(
                "YAML must be UTF-8 encoded.", details={"code": "YAML_ENCODING"}
            ) from error
        lowered = text.lower()
        if "\x00" in text or "!!python" in lowered or "!<tag:yaml.org,2002:python" in lowered:
            raise ValidationError(
                "YAML contains an unsafe tag or NUL byte.",
                details={"code": "YAML_UNSAFE_TAG"},
            )
        return {
            "coverage": "FULL_TEXT" if inspection.size_bytes <= PREVIEW_LIMIT else "SAMPLED_TEXT",
            "safe_loader_required": True,
        }

    @staticmethod
    def _retryable(error: DomainError) -> bool:
        return isinstance(error, ExternalDependencyError) and bool(
            error.details.get("retryable", False)
        )

    @staticmethod
    def _error_code(error: DomainError) -> str:
        return str(error.details.get("code") or error.details.get("provider_code") or error.code)[
            :100
        ]
