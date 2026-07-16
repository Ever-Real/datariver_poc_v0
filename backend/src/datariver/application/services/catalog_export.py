from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import timedelta
from uuid import UUID

from datariver.application.catalog_security import (
    catalog_classification_access_hash,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    CatalogExportDownload,
    CatalogExportRecord,
    CatalogExportRequest,
)
from datariver.application.ports import CatalogExportStore, CatalogWatermarkReader, ObjectStore
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError


class CatalogExportService:
    def __init__(
        self,
        *,
        store: CatalogExportStore,
        watermark: CatalogWatermarkReader,
        classification_access: ClassificationAccessResolver,
        authorization: AuthorizationService,
        object_store: ObjectStore,
        minimum_query_length: int,
        policy_version: str,
        csv_safety_version: str,
        access_ttl_seconds: int,
        download_ttl_seconds: int,
        worker_enabled: bool,
    ) -> None:
        self._store = store
        self._watermark = watermark
        self._classification_access = classification_access
        self._authorization = authorization
        self._object_store = object_store
        self._minimum_query_length = minimum_query_length
        self._policy_version = policy_version
        self._csv_safety_version = csv_safety_version
        self._access_ttl_seconds = access_ttl_seconds
        self._download_ttl_seconds = download_ttl_seconds
        self._worker_enabled = worker_enabled

    async def capability(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> bool:
        await self._authorize(
            subject=subject,
            resource_id=subject.workspace_id,
            classification=Classification.PUBLIC,
            environment=environment,
            request_id=request_id,
        )
        return self._worker_enabled

    async def create(
        self,
        *,
        subject: SubjectAttributes,
        request: CatalogExportRequest,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
    ) -> CatalogExportRecord:
        if not self._worker_enabled:
            raise ConflictError(
                "Catalog export is disabled until a separately credentialed worker is provisioned."
            )
        normalized = self._normalized_request(request)
        ceiling = self._classification_ceiling(normalized, subject=subject)
        await self._authorize(
            subject=subject,
            resource_id=subject.workspace_id,
            classification=ceiling,
            environment=environment,
            request_id=request_id,
        )
        access = await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        watermark = await self._watermark.get_search_watermark(workspace_id=subject.workspace_id)
        request_hash = self.request_hash(normalized)
        return await self._store.create(
            workspace_id=subject.workspace_id,
            requested_by=subject.subject_id,
            request=normalized,
            request_hash=request_hash,
            permission_scope_hash=catalog_permission_scope_hash(subject),
            classification_access_hash=catalog_classification_access_hash(access),
            builtin_policy_version=self._policy_version,
            classification_policy_id=access.policy_id,
            classification_policy_hash=access.policy_hash,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
            source_projection_version=watermark,
            classification_ceiling=int(ceiling),
            csv_safety_version=self._csv_safety_version,
            access_until=environment.requested_at + timedelta(seconds=self._access_ttl_seconds),
            idempotency_key=idempotency_key,
        )

    async def get(
        self,
        *,
        subject: SubjectAttributes,
        export_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogExportRecord | None:
        await self._authorize(
            subject=subject,
            resource_id=export_id,
            classification=Classification.PUBLIC,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.get_owned(
            workspace_id=subject.workspace_id,
            export_id=export_id,
            requested_by=subject.subject_id,
        )

    async def download(
        self,
        *,
        subject: SubjectAttributes,
        export_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogExportDownload | None:
        record = await self.get(
            subject=subject,
            export_id=export_id,
            environment=environment,
            request_id=request_id,
        )
        if record is None:
            return None
        if record.job_state != "COMPLETED":
            raise ConflictError("The catalog export is not ready for download.")
        if record.access_until <= environment.requested_at:
            raise ForbiddenError("The catalog export download window has expired.")
        access = await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        current_watermark = await self._watermark.get_search_watermark(
            workspace_id=subject.workspace_id
        )
        if (
            record.builtin_policy_version != self._policy_version
            or record.permission_scope_hash != catalog_permission_scope_hash(subject)
            or record.classification_access_hash != catalog_classification_access_hash(access)
            or record.source_projection_version != current_watermark
        ):
            raise ForbiddenError(
                "The catalog export security or source snapshot is no longer current."
            )
        if (
            record.object_bucket is None
            or record.object_key is None
            or record.size_bytes is None
            or record.content_sha256 is None
        ):
            raise ConflictError("The catalog export artifact is incomplete.")
        metadata = await self._object_store.head_object(
            bucket=record.object_bucket,
            object_key=record.object_key,
        )
        if (
            metadata.size_bytes != record.size_bytes
            or metadata.user_metadata.get("export-id") != str(record.export_id)
            or metadata.user_metadata.get("request-hash") != record.request_hash
            or metadata.user_metadata.get("csv-safety-version") != record.csv_safety_version
            or (
                record.provider_checksum is not None
                and record.provider_checksum.startswith("etag:")
                and metadata.etag != record.provider_checksum.removeprefix("etag:")
            )
        ):
            raise ConflictError("The catalog export artifact failed integrity validation.")
        url = await self._object_store.presign_download(
            bucket=record.object_bucket,
            object_key=record.object_key,
            download_name=record.display_name,
            expires_seconds=self._download_ttl_seconds,
        )
        return CatalogExportDownload(url=url, expires_seconds=self._download_ttl_seconds)

    async def _authorize(
        self,
        *,
        subject: SubjectAttributes,
        resource_id: UUID,
        classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=resource_id,
                workspace_id=subject.workspace_id,
                resource_type="catalog_export",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=classification,
                lifecycle="ACTIVE",
                owner_subject_id=subject.subject_id,
            ),
            action=Action.CATALOG_EXPORT,
            environment=environment,
            request_id=request_id,
        )

    def _normalized_request(self, request: CatalogExportRequest) -> CatalogExportRequest:
        if request.sort != "NAME_ASC" or request.format != "CSV":
            raise ValidationError("The catalog export shape is not supported.")
        unknown_filters = set(request.filters) - {
            "asset_type",
            "platform",
            "classification",
            "lifecycle",
        }
        if unknown_filters:
            raise ValidationError("The catalog export contains unsupported filters.")
        if request.filters.get("lifecycle") not in (None, "ACTIVE"):
            raise ValidationError("Catalog export supports active assets only.")
        query = unicodedata.normalize("NFKC", request.query).strip()
        if query and len(query) < self._minimum_query_length:
            raise ValidationError(
                "The catalog query is shorter than the configured minimum.",
                details={"minimum_query_length": self._minimum_query_length},
            )
        filters = {
            key: unicodedata.normalize("NFKC", value).strip()
            for key, value in request.filters.items()
            if value.strip()
        }
        if filters.get("classification") == "RESTRICTED":
            # The authorization call below records the canonical deny reason.
            return CatalogExportRequest(
                query=query,
                filters=filters,
                sort=request.sort,
                format=request.format,
            )
        return CatalogExportRequest(
            query=query,
            filters=filters,
            sort=request.sort,
            format=request.format,
        )

    @staticmethod
    def _classification_ceiling(
        request: CatalogExportRequest, *, subject: SubjectAttributes
    ) -> Classification:
        requested = request.filters.get("classification")
        if requested is not None:
            try:
                return Classification[requested]
            except KeyError as error:
                raise ValidationError("The catalog classification filter is invalid.") from error
        return Classification(min(int(subject.clearance), int(Classification.CONFIDENTIAL)))

    @staticmethod
    def request_hash(request: CatalogExportRequest) -> str:
        return hashlib.sha256(
            json.dumps(
                request.document(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
