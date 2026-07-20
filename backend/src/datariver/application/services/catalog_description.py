from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    CatalogAssetIndex,
    CatalogColumnDescriptionPreview,
    CatalogControlledMetadataPreview,
    CatalogDescriptionPreview,
    DataHubAspectSnapshot,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    CatalogChangeTargetReader,
    CatalogIndexReader,
    DataHubGateway,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog import is_dataset_asset_type
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
    uuid7,
)
from datariver.domain.governance import (
    ChangeItem,
    ChangePriority,
    ChangeRequest,
    ChangeUrgency,
    change_target_binding_hash,
)

DATASET_PROPERTIES_ASPECT = "datasetProperties"
SCHEMA_METADATA_ASPECT = "schemaMetadata"
CONTROLLED_METADATA_ASPECTS = frozenset({"domains", "globalTags", "glossaryTerms"})
CONTROLLED_METADATA_URN_PREFIXES = {
    "domains": "urn:li:domain:",
    "globalTags": "urn:li:tag:",
    "glossaryTerms": "urn:li:glossaryTerm:",
}
MAXIMUM_DESCRIPTION_LENGTH = 10_000
MAXIMUM_FIELD_PATH_LENGTH = 2_000
MAXIMUM_CONTROLLED_METADATA_REFS = 100


class GovernedChangeRequestCreator(Protocol):
    async def create_change_request(
        self,
        *,
        workspace_id: UUID,
        number: str,
        request_type: str,
        title: str,
        description: str,
        requester_id: UUID,
        items: list[ChangeItem],
        subject: SubjectAttributes,
        classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
        require_raw_operator_gate: bool,
        requested_due_date: date | None = None,
        priority: ChangePriority | None = None,
        urgency: ChangeUrgency | None = None,
    ) -> ChangeRequest: ...


class CatalogDescriptionAssetNotFound(NotFoundError):
    code = "catalog_asset_not_found"


class CatalogDescriptionService:
    """Prepare one typed dataset description change without exposing provider documents."""

    def __init__(
        self,
        *,
        index: CatalogIndexReader,
        target_reader: CatalogChangeTargetReader,
        classification_access: ClassificationAccessResolver,
        authorization: AuthorizationService,
        datahub: DataHubGateway,
        governance: GovernedChangeRequestCreator,
    ) -> None:
        self._index = index
        self._target_reader = target_reader
        self._classification_access = classification_access
        self._authorization = authorization
        self._datahub = datahub
        self._governance = governance

    async def preview(
        self,
        *,
        asset_id: UUID,
        description: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogDescriptionPreview:
        asset, snapshot = await self._read_current(
            asset_id=asset_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        current_description, proposed_document = self._proposed_document(
            snapshot=snapshot,
            proposed_description=description,
        )
        return CatalogDescriptionPreview(
            asset_id=asset.asset_id,
            target_ref=asset.external_urn,
            aspect_name=DATASET_PROPERTIES_ASPECT,
            current_description=current_description,
            proposed_description=description,
            before_hash=snapshot.content_hash,
            after_hash=canonical_json_hash(proposed_document),
            preview_etag=self._preview_etag(asset=asset, snapshot=snapshot),
            source_version=snapshot.source_version,
            observed_at=snapshot.observed_at,
        )

    async def preview_column_description(
        self,
        *,
        asset_id: UUID,
        field_path: str,
        description: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogColumnDescriptionPreview:
        asset, snapshot = await self._read_current(
            asset_id=asset_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            aspect_name=SCHEMA_METADATA_ASPECT,
        )
        current_description, proposed_document = self._proposed_schema_document(
            snapshot=snapshot,
            field_path=field_path,
            proposed_description=description,
        )
        return CatalogColumnDescriptionPreview(
            asset_id=asset.asset_id,
            target_ref=asset.external_urn,
            aspect_name=SCHEMA_METADATA_ASPECT,
            field_path=field_path,
            current_description=current_description,
            proposed_description=description,
            before_hash=snapshot.content_hash,
            after_hash=canonical_json_hash(proposed_document),
            preview_etag=self._column_preview_etag(
                asset=asset,
                snapshot=snapshot,
                field_path=field_path,
            ),
            source_version=snapshot.source_version,
            observed_at=snapshot.observed_at,
        )

    async def create_change_request(
        self,
        *,
        asset_id: UUID,
        expected_preview_etag: str,
        description: str,
        title: str,
        change_description: str,
        number: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
        requested_due_date: date | None = None,
        priority: ChangePriority | None = None,
        urgency: ChangeUrgency | None = None,
    ) -> ChangeRequest:
        asset, snapshot = await self._read_current(
            asset_id=asset_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        locked_asset = await self._lock_current_target(
            expected=asset,
            subject=subject,
            environment=environment,
        )
        current_preview_etag = self._preview_etag(asset=locked_asset, snapshot=snapshot)
        if current_preview_etag != expected_preview_etag:
            raise ConflictError(
                "The dataset description preview is stale.",
                details={"code": "PREVIEW_ETAG_MISMATCH"},
            )
        _, proposed_document = self._proposed_document(
            snapshot=snapshot,
            proposed_description=description,
        )
        after_hash = canonical_json_hash(proposed_document)
        return await self._governance.create_change_request(
            workspace_id=subject.workspace_id,
            number=number,
            request_type="CATALOG_DESCRIPTION",
            title=title,
            description=change_description,
            requester_id=subject.subject_id,
            items=[
                ChangeItem(
                    item_id=uuid7(),
                    target_type="DATAHUB_ASPECT",
                    target_ref=locked_asset.external_urn,
                    operation="UPSERT",
                    after_document=proposed_document,
                    aspect_name=DATASET_PROPERTIES_ASPECT,
                    before_hash=snapshot.content_hash,
                    after_hash=after_hash,
                )
            ],
            subject=subject,
            classification=locked_asset.classification,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            require_raw_operator_gate=False,
            requested_due_date=requested_due_date,
            priority=priority,
            urgency=urgency,
        )

    async def create_column_description_change_request(
        self,
        *,
        asset_id: UUID,
        expected_preview_etag: str,
        field_path: str,
        description: str,
        title: str,
        change_description: str,
        number: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest:
        asset, snapshot = await self._read_current(
            asset_id=asset_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            aspect_name=SCHEMA_METADATA_ASPECT,
        )
        locked_asset = await self._lock_current_target(
            expected=asset,
            subject=subject,
            environment=environment,
        )
        current_preview_etag = self._column_preview_etag(
            asset=locked_asset,
            snapshot=snapshot,
            field_path=field_path,
        )
        if current_preview_etag != expected_preview_etag:
            raise ConflictError(
                "The column description preview is stale.",
                details={"code": "PREVIEW_ETAG_MISMATCH"},
            )
        _, proposed_document = self._proposed_schema_document(
            snapshot=snapshot,
            field_path=field_path,
            proposed_description=description,
        )
        after_hash = canonical_json_hash(proposed_document)
        return await self._governance.create_change_request(
            workspace_id=subject.workspace_id,
            number=number,
            request_type="CATALOG_COLUMN_DESCRIPTION",
            title=title,
            description=change_description,
            requester_id=subject.subject_id,
            items=[
                ChangeItem(
                    item_id=uuid7(),
                    target_type="DATAHUB_ASPECT",
                    target_ref=locked_asset.external_urn,
                    operation="UPSERT",
                    after_document=proposed_document,
                    aspect_name=SCHEMA_METADATA_ASPECT,
                    before_hash=snapshot.content_hash,
                    after_hash=after_hash,
                )
            ],
            subject=subject,
            classification=locked_asset.classification,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            require_raw_operator_gate=False,
        )

    async def preview_controlled_metadata(
        self,
        *,
        asset_id: UUID,
        aspect_name: str,
        refs: tuple[str, ...],
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogControlledMetadataPreview:
        self._validate_controlled_metadata(aspect_name=aspect_name, refs=refs)
        asset, snapshot = await self._read_current(
            asset_id=asset_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            aspect_name=aspect_name,
        )
        current_refs, proposed_document = self._proposed_controlled_metadata_document(
            snapshot=snapshot,
            aspect_name=aspect_name,
            refs=refs,
        )
        return CatalogControlledMetadataPreview(
            asset_id=asset.asset_id,
            target_ref=asset.external_urn,
            aspect_name=aspect_name,
            current_refs=current_refs,
            proposed_refs=refs,
            before_hash=snapshot.content_hash,
            after_hash=canonical_json_hash(proposed_document),
            preview_etag=self._controlled_metadata_preview_etag(
                asset=asset,
                snapshot=snapshot,
                aspect_name=aspect_name,
            ),
            source_version=snapshot.source_version,
            observed_at=snapshot.observed_at,
        )

    async def create_controlled_metadata_change_request(
        self,
        *,
        asset_id: UUID,
        aspect_name: str,
        refs: tuple[str, ...],
        expected_preview_etag: str,
        title: str,
        change_description: str,
        number: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest:
        self._validate_controlled_metadata(aspect_name=aspect_name, refs=refs)
        asset, snapshot = await self._read_current(
            asset_id=asset_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            aspect_name=aspect_name,
        )
        locked_asset = await self._lock_current_target(
            expected=asset,
            subject=subject,
            environment=environment,
        )
        current_preview_etag = self._controlled_metadata_preview_etag(
            asset=locked_asset,
            snapshot=snapshot,
            aspect_name=aspect_name,
        )
        if current_preview_etag != expected_preview_etag:
            raise ConflictError(
                "The controlled metadata preview is stale.",
                details={"code": "PREVIEW_ETAG_MISMATCH"},
            )
        _, proposed_document = self._proposed_controlled_metadata_document(
            snapshot=snapshot,
            aspect_name=aspect_name,
            refs=refs,
        )
        return await self._governance.create_change_request(
            workspace_id=subject.workspace_id,
            number=number,
            request_type="CATALOG_CONTROLLED_METADATA",
            title=title,
            description=change_description,
            requester_id=subject.subject_id,
            items=[
                ChangeItem(
                    item_id=uuid7(),
                    target_type="DATAHUB_ASPECT",
                    target_ref=locked_asset.external_urn,
                    operation="UPSERT",
                    after_document=proposed_document,
                    aspect_name=aspect_name,
                    before_hash=snapshot.content_hash,
                    after_hash=canonical_json_hash(proposed_document),
                )
            ],
            subject=subject,
            classification=locked_asset.classification,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            require_raw_operator_gate=False,
        )

    async def _read_current(
        self,
        *,
        asset_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        aspect_name: str = DATASET_PROPERTIES_ASPECT,
    ) -> tuple[CatalogAssetIndex, DataHubAspectSnapshot]:
        self._validate_description_request_time(environment)
        access = await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        detail = await self._index.get_authorized_asset(
            subject=subject,
            access=access,
            asset_id=asset_id,
        )
        if detail is None:
            raise CatalogDescriptionAssetNotFound("The catalog asset does not exist.")
        asset = detail.index
        if (
            asset.workspace_id != subject.workspace_id
            or not is_dataset_asset_type(asset.asset_type)
            or asset.lifecycle != "ACTIVE"
            or not asset.external_urn.startswith("urn:li:dataset:")
        ):
            raise CatalogDescriptionAssetNotFound("The catalog asset does not exist.")
        resource = ResourceAttributes(
            resource_id=asset.asset_id,
            workspace_id=asset.workspace_id,
            resource_type="catalog_asset_description_change",
            owner_department_id=asset.owner_department_id,
            system_id=asset.system_id,
            domain_id=asset.domain_id,
            classification=asset.classification,
            lifecycle=asset.lifecycle,
        )
        # Both decisions are made before the first live provider call. Governance repeats
        # CHANGE_CREATE while binding the final request to the current local target snapshot.
        await self._authorization.authorize(
            subject=subject,
            resource=resource,
            action=Action.CATALOG_READ,
            environment=environment,
            request_id=request_id,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=resource,
            action=Action.CHANGE_CREATE,
            environment=environment,
            request_id=request_id,
        )
        snapshot = await self._datahub.read_aspect(
            external_urn=asset.external_urn,
            aspect_name=aspect_name,
        )
        self._validate_snapshot(asset=asset, snapshot=snapshot, aspect_name=aspect_name)
        return asset, snapshot

    async def _lock_current_target(
        self,
        *,
        expected: CatalogAssetIndex,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
    ) -> CatalogAssetIndex:
        access = await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        values = tuple(
            await self._target_reader.get_authorized_assets_by_external_urns(
                subject=subject,
                access=access,
                external_urns=(expected.external_urn,),
                lock_for_share=True,
            )
        )
        if len(values) != 1:
            raise ConflictError(
                "The catalog target changed after the provider snapshot was read.",
                details={"code": "TARGET_BINDING_DRIFT"},
            )
        current = values[0]
        if (
            current.asset_id != expected.asset_id
            or current.workspace_id != subject.workspace_id
            or current.external_urn != expected.external_urn
            or not is_dataset_asset_type(current.asset_type)
            or current.lifecycle != "ACTIVE"
            or self._target_binding_hash(current) != self._target_binding_hash(expected)
        ):
            raise ConflictError(
                "The catalog target changed after the provider snapshot was read.",
                details={"code": "TARGET_BINDING_DRIFT"},
            )
        return current

    @staticmethod
    def _proposed_document(
        *, snapshot: DataHubAspectSnapshot, proposed_description: str
    ) -> tuple[str | None, dict[str, Any]]:
        CatalogDescriptionService._validate_description(proposed_description)
        document = _mutable_json_object(snapshot.document)
        current = document.get("description")
        if current is not None and not isinstance(current, str):
            raise ExternalDependencyError(
                "DataHub returned an invalid datasetProperties description.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        if proposed_description == "":
            if current in {None, ""}:
                raise ValidationError(
                    "The proposed description does not change the current value.",
                    details={"code": "DESCRIPTION_UNCHANGED"},
                )
            document.pop("description", None)
        else:
            if current == proposed_description:
                raise ValidationError(
                    "The proposed description does not change the current value.",
                    details={"code": "DESCRIPTION_UNCHANGED"},
                )
            document["description"] = proposed_description
        return current, document

    @classmethod
    def _proposed_schema_document(
        cls,
        *,
        snapshot: DataHubAspectSnapshot,
        field_path: str,
        proposed_description: str,
    ) -> tuple[str | None, dict[str, Any]]:
        cls._validate_field_path(field_path)
        cls._validate_description(proposed_description)
        document = _mutable_json_object(snapshot.document)
        fields = document.get("fields")
        if not isinstance(fields, list):
            raise ExternalDependencyError(
                "DataHub returned an invalid schemaMetadata fields document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        matches = [
            field
            for field in fields
            if isinstance(field, dict) and field.get("fieldPath") == field_path
        ]
        if len(matches) != 1:
            raise ConflictError(
                "The requested schema field is no longer available in DataHub.",
                details={"code": "SCHEMA_FIELD_DRIFT"},
            )
        field = matches[0]
        current = field.get("description")
        if current is not None and not isinstance(current, str):
            raise ExternalDependencyError(
                "DataHub returned an invalid schema field description.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        if proposed_description == "":
            if current in {None, ""}:
                raise ValidationError(
                    "The proposed column description does not change the current value.",
                    details={"code": "DESCRIPTION_UNCHANGED"},
                )
            field.pop("description", None)
        else:
            if current == proposed_description:
                raise ValidationError(
                    "The proposed column description does not change the current value.",
                    details={"code": "DESCRIPTION_UNCHANGED"},
                )
            field["description"] = proposed_description
        return current, document

    @classmethod
    def _proposed_controlled_metadata_document(
        cls,
        *,
        snapshot: DataHubAspectSnapshot,
        aspect_name: str,
        refs: tuple[str, ...],
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        cls._validate_controlled_metadata(aspect_name=aspect_name, refs=refs)
        document = _mutable_json_object(snapshot.document)
        current_refs = cls._controlled_metadata_refs(
            document=document,
            aspect_name=aspect_name,
        )
        if current_refs == refs:
            raise ValidationError(
                "The proposed controlled metadata does not change the current value.",
                details={"code": "CONTROLLED_METADATA_UNCHANGED"},
            )
        if aspect_name == "domains":
            document["domains"] = [{"urn": ref} for ref in refs]
        elif aspect_name == "globalTags":
            document["tags"] = [{"tag": ref} for ref in refs]
        else:
            document["terms"] = [{"urn": ref} for ref in refs]
        return current_refs, document

    @staticmethod
    def _controlled_metadata_refs(*, document: dict[str, Any], aspect_name: str) -> tuple[str, ...]:
        field_name, nested_name = {
            "domains": ("domains", "urn"),
            "globalTags": ("tags", "tag"),
            "glossaryTerms": ("terms", "urn"),
        }[aspect_name]
        raw_values = document.get(field_name)
        values: list[str] = []
        for raw_value in raw_values if isinstance(raw_values, list) else []:
            candidate: object = raw_value
            if isinstance(raw_value, dict):
                candidate = raw_value.get(nested_name, raw_value.get("urn"))
            if isinstance(candidate, dict):
                candidate = candidate.get("urn")
            if isinstance(candidate, str):
                values.append(candidate)
        return tuple(sorted(set(values)))

    @staticmethod
    def _validate_snapshot(
        *,
        asset: CatalogAssetIndex,
        snapshot: DataHubAspectSnapshot,
        aspect_name: str,
    ) -> None:
        if (
            snapshot.urn != asset.external_urn
            or snapshot.aspect_name != aspect_name
            or not snapshot.source_version
            or snapshot.observed_at.tzinfo is None
            or snapshot.observed_at.utcoffset() is None
        ):
            raise ExternalDependencyError(
                "DataHub returned an invalid datasetProperties snapshot.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        document = _mutable_json_object(snapshot.document)
        if canonical_json_hash(document) != snapshot.content_hash:
            raise ExternalDependencyError(
                "DataHub returned an inconsistent datasetProperties snapshot.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )

    @staticmethod
    def _target_binding_hash(asset: CatalogAssetIndex) -> str:
        return change_target_binding_hash(
            target_ref=asset.external_urn,
            asset_id=asset.asset_id,
            asset_type=asset.asset_type,
            system_id=asset.system_id,
            domain_id=asset.domain_id,
            owner_department_id=asset.owner_department_id,
            classification=asset.classification,
            lifecycle=asset.lifecycle,
        )

    @classmethod
    def _preview_etag(cls, *, asset: CatalogAssetIndex, snapshot: DataHubAspectSnapshot) -> str:
        composite_hash = canonical_json_hash(
            {
                "contract": "catalog-description-preview-v1",
                "workspace_id": str(asset.workspace_id),
                "asset_id": str(asset.asset_id),
                "target_binding_hash": cls._target_binding_hash(asset),
                "aspect_name": DATASET_PROPERTIES_ASPECT,
                "aspect_hash": snapshot.content_hash,
                "provider_source_version": snapshot.source_version,
            }
        )
        return f'"{composite_hash}"'

    @classmethod
    def _column_preview_etag(
        cls,
        *,
        asset: CatalogAssetIndex,
        snapshot: DataHubAspectSnapshot,
        field_path: str,
    ) -> str:
        composite_hash = canonical_json_hash(
            {
                "contract": "catalog-column-description-preview-v1",
                "workspace_id": str(asset.workspace_id),
                "asset_id": str(asset.asset_id),
                "target_binding_hash": cls._target_binding_hash(asset),
                "aspect_name": SCHEMA_METADATA_ASPECT,
                "field_path": field_path,
                "aspect_hash": snapshot.content_hash,
                "provider_source_version": snapshot.source_version,
            }
        )
        return f'"{composite_hash}"'

    @classmethod
    def _controlled_metadata_preview_etag(
        cls,
        *,
        asset: CatalogAssetIndex,
        snapshot: DataHubAspectSnapshot,
        aspect_name: str,
    ) -> str:
        composite_hash = canonical_json_hash(
            {
                "contract": "catalog-controlled-metadata-preview-v1",
                "workspace_id": str(asset.workspace_id),
                "asset_id": str(asset.asset_id),
                "target_binding_hash": cls._target_binding_hash(asset),
                "aspect_name": aspect_name,
                "aspect_hash": snapshot.content_hash,
                "provider_source_version": snapshot.source_version,
            }
        )
        return f'"{composite_hash}"'

    @staticmethod
    def _validate_description(value: str) -> None:
        if len(value) > MAXIMUM_DESCRIPTION_LENGTH or "\x00" in value:
            raise ValidationError("The proposed description is invalid.")

    @staticmethod
    def _validate_field_path(value: str) -> None:
        if not value.strip() or len(value) > MAXIMUM_FIELD_PATH_LENGTH or "\x00" in value:
            raise ValidationError("The requested schema field path is invalid.")

    @staticmethod
    def _validate_controlled_metadata(*, aspect_name: str, refs: tuple[str, ...]) -> None:
        prefix = CONTROLLED_METADATA_URN_PREFIXES.get(aspect_name)
        if prefix is None or aspect_name not in CONTROLLED_METADATA_ASPECTS:
            raise ValidationError("The requested controlled metadata aspect is invalid.")
        if len(refs) > MAXIMUM_CONTROLLED_METADATA_REFS or len(set(refs)) != len(refs):
            raise ValidationError("Controlled metadata references are invalid.")
        if aspect_name == "domains" and len(refs) > 1:
            raise ValidationError("A dataset may have at most one controlled domain reference.")
        if any(not ref.startswith(prefix) or len(ref) > 2_000 or "\x00" in ref for ref in refs):
            raise ValidationError("A controlled metadata reference is invalid.")

    @staticmethod
    def _validate_description_request_time(environment: EnvironmentAttributes) -> None:
        if environment.requested_at.tzinfo is None or environment.requested_at.utcoffset() is None:
            raise ValidationError("The request time must be timezone-aware.")


def _mutable_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _mutable_json(value)
    if not isinstance(result, dict):
        raise ExternalDependencyError(
            "DataHub returned an invalid datasetProperties document.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    return result


def _mutable_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ExternalDependencyError(
                "DataHub returned an invalid datasetProperties document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_mutable_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ExternalDependencyError(
            "DataHub returned an invalid datasetProperties document.",
            dependency="datahub",
            retryable=False,
            provider_code="INVALID_RESPONSE",
        )
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ExternalDependencyError(
        "DataHub returned an invalid datasetProperties document.",
        dependency="datahub",
        retryable=False,
        provider_code="INVALID_RESPONSE",
    )
