from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    CatalogAssetIndex,
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
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
    uuid7,
)
from datariver.domain.governance import (
    ChangeItem,
    ChangeRequest,
    change_target_binding_hash,
)

DATASET_PROPERTIES_ASPECT = "datasetProperties"
MAXIMUM_DESCRIPTION_LENGTH = 10_000


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
        )

    async def _read_current(
        self,
        *,
        asset_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
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
            or asset.asset_type != "DATASET"
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
            aspect_name=DATASET_PROPERTIES_ASPECT,
        )
        self._validate_snapshot(asset=asset, snapshot=snapshot)
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
            or current.asset_type != "DATASET"
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

    @staticmethod
    def _validate_snapshot(*, asset: CatalogAssetIndex, snapshot: DataHubAspectSnapshot) -> None:
        if (
            snapshot.urn != asset.external_urn
            or snapshot.aspect_name != DATASET_PROPERTIES_ASPECT
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

    @staticmethod
    def _validate_description(value: str) -> None:
        if len(value) > MAXIMUM_DESCRIPTION_LENGTH or "\x00" in value:
            raise ValidationError("The proposed description is invalid.")

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
