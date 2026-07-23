from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from datariver.application.catalog_metadata_upload_parser import (
    CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION,
    CatalogMetadataAspect,
    CatalogMetadataCandidateKind,
    CatalogMetadataOperation,
    CatalogMetadataRecordKind,
    catalog_metadata_candidate_hash,
    catalog_metadata_row_hash,
    catalog_metadata_row_root,
    catalog_metadata_semantic_target_hash,
    catalog_metadata_submitted_identity_hash,
)
from datariver.application.catalog_security import (
    catalog_classification_access_hash,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import (
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
)
from datariver.application.dto import (
    CatalogAssetIndex,
    CatalogMetadataCandidateEvidence,
    CatalogMetadataCandidatePage,
    CatalogMetadataCandidateView,
    CatalogMetadataRowEvidenceRecord,
    UploadPreparationReceiptEvidence,
)
from datariver.application.ports import (
    CatalogCandidateTargetReader,
    CatalogMetadataCandidateReader,
    CatalogWatermarkReader,
    UploadPreparationRepository,
    UploadRepository,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.registration import UploadNotFound, UploadPreparationNotFound
from datariver.application.services.registration_candidates import (
    UploadCandidatePageUnavailable,
    UploadPreparationEvidenceUnavailable,
    UploadPreparationNotReady,
)
from datariver.application.typed_upload_profiles import (
    TypedUploadProfileDefinition,
    typed_profile_definition,
)
from datariver.domain.authz import (
    Action,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog import is_dataset_asset_type
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.registration import (
    UploadContentProfile,
    UploadManifest,
    UploadPreparation,
    UploadPreparationState,
    UploadState,
)

_CATALOG_METADATA_PROFILES = frozenset(
    {
        UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
        UploadContentProfile.CATALOG_METADATA_ROWS_XLSX_V1,
    }
)
_RECORD_CONTRACTS = {
    CatalogMetadataRecordKind.TABLE_DESCRIPTION: (
        CatalogMetadataCandidateKind.TABLE_DESCRIPTION_UPDATE,
        CatalogMetadataAspect.DATASET_PROPERTIES,
    ),
    CatalogMetadataRecordKind.COLUMN_DESCRIPTION: (
        CatalogMetadataCandidateKind.COLUMN_DESCRIPTION_UPDATE,
        CatalogMetadataAspect.SCHEMA_METADATA,
    ),
    CatalogMetadataRecordKind.DATASET_DOMAIN: (
        CatalogMetadataCandidateKind.DATASET_DOMAIN_UPDATE,
        CatalogMetadataAspect.DOMAINS,
    ),
    CatalogMetadataRecordKind.DATASET_TERM: (
        CatalogMetadataCandidateKind.DATASET_TERM_ADD,
        CatalogMetadataAspect.GLOSSARY_TERMS,
    ),
    CatalogMetadataRecordKind.DATASET_TAG: (
        CatalogMetadataCandidateKind.DATASET_TAG_ADD,
        CatalogMetadataAspect.GLOBAL_TAGS,
    ),
}
_MAXIMUM_PAGE_SIZE = 100


class CatalogMetadataCandidateQueryService:
    """Read V3 candidate evidence under a fresh catalog and authorization snapshot."""

    def __init__(
        self,
        *,
        uploads: UploadRepository,
        preparations: UploadPreparationRepository,
        candidates: CatalogMetadataCandidateReader,
        catalog: CatalogCandidateTargetReader,
        watermark: CatalogWatermarkReader,
        classification_access: ClassificationAccessResolver,
        authorization: AuthorizationService,
        policy_version: str,
    ) -> None:
        self._uploads = uploads
        self._preparations = preparations
        self._candidates = candidates
        self._catalog = catalog
        self._watermark = watermark
        self._classification_access = classification_access
        self._authorization = authorization
        self._policy_version = policy_version

    async def list_candidates(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        cursor: str | None,
        limit: int,
    ) -> CatalogMetadataCandidatePage:
        if not 1 <= limit <= _MAXIMUM_PAGE_SIZE:
            raise ValidationError("The catalog-metadata candidate page size is invalid.")
        _manifest, preparation, receipt = await self._load_ready_evidence(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        access = await self._classification_access.resolve(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        projection_version = await self._watermark.get_search_watermark(workspace_id=workspace_id)
        cursor_context = self._cursor_context(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            receipt=receipt,
            subject=subject,
            access_hash=catalog_classification_access_hash(access),
            projection_version=projection_version,
            limit=limit,
        )
        after_ordinal = _unwrap_candidate_cursor(cursor, expected_context=cursor_context)
        if after_ordinal >= receipt.candidate_count:
            raise ValidationError("The candidate cursor is stale or does not match this request.")

        candidates = tuple(
            await self._candidates.list_candidates(
                workspace_id=workspace_id,
                receipt_id=receipt.receipt_id,
                after_ordinal=after_ordinal,
                limit=limit + 1,
            )
        )
        if not self._candidate_page_is_consistent(
            candidates=candidates,
            receipt=receipt,
            after_ordinal=after_ordinal,
            maximum_items=limit + 1,
        ):
            raise UploadPreparationEvidenceUnavailable(
                "The catalog-metadata preparation evidence is unavailable."
            )
        targets_by_id = await self._authorized_targets(
            candidates=candidates,
            preparation=preparation,
            subject=subject,
            environment=environment,
            request_id=request_id,
            access=access,
        )
        visible = candidates[:limit]
        next_cursor = (
            _wrap_candidate_cursor(
                after_ordinal=visible[-1].ordinal,
                context=cursor_context,
            )
            if len(candidates) > limit and visible
            else None
        )
        return CatalogMetadataCandidatePage(
            items=tuple(
                CatalogMetadataCandidateView(
                    evidence=candidate,
                    current_target=_public_target(targets_by_id[candidate.target_asset_id]),
                )
                for candidate in visible
            ),
            next_cursor=next_cursor,
            receipt=receipt,
            projection_version=projection_version,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )

    async def get_candidate(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        candidate_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogMetadataCandidatePage:
        return await self._get_candidate(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            expose_provider_target=False,
        )

    async def get_candidate_for_execution(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        candidate_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogMetadataCandidatePage:
        """Return the same authorized evidence with the server-only provider target intact."""

        return await self._get_candidate(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            expose_provider_target=True,
        )

    async def _get_candidate(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        candidate_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        expose_provider_target: bool,
    ) -> CatalogMetadataCandidatePage:
        _manifest, preparation, receipt = await self._load_ready_evidence(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        candidate = await self._candidates.get_candidate(
            workspace_id=workspace_id,
            receipt_id=receipt.receipt_id,
            candidate_id=candidate_id,
        )
        if candidate is None or not self._candidate_page_is_consistent(
            candidates=(candidate,),
            receipt=receipt,
            after_ordinal=candidate.ordinal - 1,
            maximum_items=1,
        ):
            raise UploadCandidatePageUnavailable("The candidate is not available.")
        access = await self._classification_access.resolve(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        projection_version = await self._watermark.get_search_watermark(workspace_id=workspace_id)
        targets_by_id = await self._authorized_targets(
            candidates=(candidate,),
            preparation=preparation,
            subject=subject,
            environment=environment,
            request_id=request_id,
            access=access,
        )
        return CatalogMetadataCandidatePage(
            items=(
                CatalogMetadataCandidateView(
                    evidence=candidate,
                    current_target=(
                        targets_by_id[candidate.target_asset_id]
                        if expose_provider_target
                        else _public_target(targets_by_id[candidate.target_asset_id])
                    ),
                ),
            ),
            next_cursor=None,
            receipt=receipt,
            projection_version=projection_version,
            policy_version=self._policy_version,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
        )

    async def _load_ready_evidence(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[UploadManifest, UploadPreparation, UploadPreparationReceiptEvidence]:
        manifest = await self._uploads.get(workspace_id=workspace_id, upload_id=upload_id)
        if manifest is None:
            raise UploadNotFound("The upload does not exist.")
        await self._authorization.authorize(
            subject=subject,
            resource=self._upload_resource(manifest),
            action=Action.REGISTRATION_READ,
            environment=environment,
            request_id=request_id,
        )
        preparation = await self._preparations.get(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
        )
        if preparation is None:
            raise UploadPreparationNotFound("The upload preparation does not exist.")
        if preparation.state is not UploadPreparationState.READY:
            raise UploadPreparationNotReady("The upload preparation is not ready.")
        receipt = await self._candidates.get_ready_receipt(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
        )
        if receipt is None or not self._receipt_is_consistent(
            manifest=manifest,
            preparation=preparation,
            receipt=receipt,
        ):
            raise UploadPreparationEvidenceUnavailable(
                "The catalog-metadata preparation evidence is unavailable."
            )
        return manifest, preparation, receipt

    async def _authorized_targets(
        self,
        *,
        candidates: Sequence[CatalogMetadataCandidateEvidence],
        preparation: UploadPreparation,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        access: ClassificationAccessSnapshot,
    ) -> dict[UUID, CatalogAssetIndex]:
        unique_ids = tuple(dict.fromkeys(candidate.target_asset_id for candidate in candidates))
        targets = tuple(
            await self._catalog.get_authorized_assets_by_ids(
                subject=subject,
                access=access,
                asset_ids=unique_ids,
            )
        )
        targets_by_id = {target.asset_id: target for target in targets}
        if len(targets_by_id) != len(unique_ids) or set(targets_by_id) != set(unique_ids):
            raise UploadCandidatePageUnavailable("The candidate page is not available.")
        resources = tuple(self._target_resource(targets_by_id[asset_id]) for asset_id in unique_ids)
        catalog_allowed = await self._authorization.filter_authorized(
            subject=subject,
            resources=resources,
            action=Action.CATALOG_READ,
            environment=environment,
            request_id=request_id,
            parent_resource_id=preparation.preparation_id,
        )
        change_allowed = await self._authorization.filter_authorized(
            subject=subject,
            resources=resources,
            action=Action.CHANGE_CREATE,
            environment=environment,
            request_id=request_id,
            parent_resource_id=preparation.preparation_id,
        )
        if len(catalog_allowed) != len(resources) or len(change_allowed) != len(resources):
            raise UploadCandidatePageUnavailable("The candidate page is not available.")
        if any(
            not self._candidate_matches_current(
                candidate=candidate,
                target=targets_by_id[candidate.target_asset_id],
            )
            for candidate in candidates
        ):
            raise UploadCandidatePageUnavailable("The candidate page is not available.")
        return targets_by_id

    @staticmethod
    def _receipt_is_consistent(
        *,
        manifest: UploadManifest,
        preparation: UploadPreparation,
        receipt: UploadPreparationReceiptEvidence,
    ) -> bool:
        try:
            profile = UploadContentProfile(receipt.content_profile)
            definition = typed_profile_definition(profile)
        except (ValueError, ValidationError):
            return False
        digests = (
            manifest.declared_sha256,
            preparation.source_sha256,
            receipt.source_sha256,
            receipt.accepted_sha256,
            receipt.configuration_hash,
            receipt.candidate_root_hash,
            receipt.receipt_hash,
        )
        return (
            profile in _CATALOG_METADATA_PROFILES
            and manifest.content_profile is profile
            and preparation.content_profile is profile
            and manifest.state is UploadState.ACCEPTED
            and manifest.actual_sha256 == manifest.declared_sha256
            and preparation.workspace_id == manifest.workspace_id == receipt.workspace_id
            and preparation.upload_id == manifest.upload_id == receipt.upload_id
            and preparation.preparation_id == receipt.preparation_id
            and preparation.source_manifest_version == manifest.version == receipt.manifest_version
            and preparation.source_sha256 == manifest.declared_sha256 == receipt.source_sha256
            and receipt.accepted_sha256 == receipt.source_sha256
            and receipt.content_profile == definition.content_profile.value
            and preparation.configuration_hash == receipt.configuration_hash
            and receipt.configuration_hash == definition.configuration_hash
            and receipt.parser_version == definition.parser_version
            and receipt.schema_version == definition.schema_version
            and bool(receipt.scanner_version.strip())
            and 0 < receipt.item_count <= definition.maximum_rows
            and 0 < receipt.candidate_count <= receipt.item_count
            and receipt.rejected_count == 0
            and preparation.rows_processed == receipt.item_count
            and preparation.total_rows == receipt.item_count
            and receipt.first_ordinal == 1
            and receipt.last_ordinal == receipt.candidate_count
            and receipt.legacy_candidate_count == 0
            and all(_is_sha256(value) for value in digests)
        )

    @staticmethod
    def _candidate_page_is_consistent(
        *,
        candidates: Sequence[CatalogMetadataCandidateEvidence],
        receipt: UploadPreparationReceiptEvidence,
        after_ordinal: int,
        maximum_items: int,
    ) -> bool:
        try:
            definition = typed_profile_definition(UploadContentProfile(receipt.content_profile))
        except (ValueError, ValidationError):
            return False
        if len(candidates) > maximum_items or (
            not candidates and after_ordinal < receipt.candidate_count
        ):
            return False
        previous = after_ordinal
        seen_candidate_ids: set[UUID] = set()
        seen_groups: set[tuple[UUID, str]] = set()
        seen_row_ids: set[UUID] = set()
        seen_source_ordinals: set[int] = set()
        for candidate in candidates:
            group_key = (candidate.target_asset_id, candidate.aspect_name)
            if (
                candidate.workspace_id != receipt.workspace_id
                or candidate.receipt_id != receipt.receipt_id
                or candidate.content_profile != receipt.content_profile
                or candidate.evidence_version != CATALOG_METADATA_CANDIDATE_EVIDENCE_VERSION
                or candidate.ordinal != previous + 1
                or candidate.ordinal > receipt.candidate_count
                or candidate.candidate_id in seen_candidate_ids
                or group_key in seen_groups
                or not _candidate_hashes_are_consistent(
                    candidate,
                    definition=definition,
                    maximum_source_ordinal=receipt.item_count,
                    seen_row_ids=seen_row_ids,
                    seen_source_ordinals=seen_source_ordinals,
                )
            ):
                return False
            previous = candidate.ordinal
            seen_candidate_ids.add(candidate.candidate_id)
            seen_groups.add(group_key)
        return True

    @staticmethod
    def _candidate_matches_current(
        *,
        candidate: CatalogMetadataCandidateEvidence,
        target: CatalogAssetIndex,
    ) -> bool:
        if not (
            target.workspace_id == candidate.workspace_id
            and target.asset_id == candidate.target_asset_id
            and is_dataset_asset_type(target.asset_type)
            and target.lifecycle == "ACTIVE"
            and target.platform == candidate.submitted_platform
            and target.database_name == candidate.submitted_database_name
            and target.schema_name == candidate.submitted_schema_name
            and target.name == candidate.submitted_table_name
        ):
            return False
        if candidate.record_kind != CatalogMetadataRecordKind.COLUMN_DESCRIPTION.value:
            return True
        return not target.column_names_truncated and all(
            row.field_path is not None and target.column_names.count(row.field_path) == 1
            for row in candidate.rows
        )

    def _cursor_context(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        receipt: UploadPreparationReceiptEvidence,
        subject: SubjectAttributes,
        access_hash: str,
        projection_version: int,
        limit: int,
    ) -> str:
        return canonical_json_hash(
            {
                "authorization_actions": [
                    Action.CATALOG_READ.value,
                    Action.CHANGE_CREATE.value,
                ],
                "candidate_count": receipt.candidate_count,
                "candidate_root_hash": receipt.candidate_root_hash,
                "classification_access": access_hash,
                "contract": "catalog-metadata-candidate-cursor-v3",
                "item_count": receipt.item_count,
                "limit": limit,
                "permission_scope": catalog_permission_scope_hash(subject),
                "policy_version": self._policy_version,
                "preparation_id": str(preparation_id),
                "projection_version": projection_version,
                "receipt_hash": receipt.receipt_hash,
                "receipt_id": str(receipt.receipt_id),
                "subject_id": str(subject.subject_id),
                "upload_id": str(upload_id),
                "workspace_id": str(workspace_id),
            }
        )

    @staticmethod
    def _upload_resource(manifest: UploadManifest) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=manifest.upload_id,
            workspace_id=manifest.workspace_id,
            resource_type="upload_manifest",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=manifest.classification,
            lifecycle=manifest.state.value,
            requester_id=manifest.owner_id,
            owner_subject_id=manifest.owner_id,
        )

    @staticmethod
    def _target_resource(target: CatalogAssetIndex) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=target.asset_id,
            workspace_id=target.workspace_id,
            resource_type="catalog_asset_change_target",
            owner_department_id=target.owner_department_id,
            system_id=target.system_id,
            domain_id=target.domain_id,
            classification=target.classification,
            lifecycle=target.lifecycle,
        )


def _candidate_hashes_are_consistent(
    candidate: CatalogMetadataCandidateEvidence,
    *,
    definition: TypedUploadProfileDefinition,
    maximum_source_ordinal: int,
    seen_row_ids: set[UUID],
    seen_source_ordinals: set[int],
) -> bool:
    try:
        profile = typed_profile_definition(UploadContentProfile(candidate.content_profile))
        record_kind = CatalogMetadataRecordKind(candidate.record_kind)
        candidate_kind = CatalogMetadataCandidateKind(candidate.candidate_kind)
        aspect_name = CatalogMetadataAspect(candidate.aspect_name)
        expected_candidate_kind, expected_aspect = _RECORD_CONTRACTS[record_kind]
        if candidate_kind is not expected_candidate_kind or aspect_name is not expected_aspect:
            return False
        if (
            profile.configuration_hash != definition.configuration_hash
            or not candidate.rows
            or not _identity_is_valid(candidate, definition=definition)
        ):
            return False
        expected_identity_hash = catalog_metadata_submitted_identity_hash(
            workspace_id=candidate.workspace_id,
            target_asset_id=candidate.target_asset_id,
            platform=candidate.submitted_platform,
            database_name=candidate.submitted_database_name,
            schema_name=candidate.submitted_schema_name,
            table_name=candidate.submitted_table_name,
            aspect_name=aspect_name,
            definition=profile,
        )
        if candidate.submitted_identity_hash != expected_identity_hash:
            return False

        row_hashes: list[str] = []
        previous_source_ordinal = 0
        semantic_hashes: set[str] = set()
        for row in candidate.rows:
            if (
                row.row_id in seen_row_ids
                or row.ordinal in seen_source_ordinals
                or row.ordinal <= previous_source_ordinal
                or row.ordinal > maximum_source_ordinal
                or row.record_kind != record_kind.value
                or row.aspect_name != aspect_name.value
                or not _row_shape_is_consistent(
                    row,
                    record_kind=record_kind,
                    definition=definition,
                )
            ):
                return False
            operation = CatalogMetadataOperation(row.operation)
            expected_row_hash = catalog_metadata_row_hash(
                workspace_id=candidate.workspace_id,
                ordinal=row.ordinal,
                target_asset_id=candidate.target_asset_id,
                platform=candidate.submitted_platform,
                database_name=candidate.submitted_database_name,
                schema_name=candidate.submitted_schema_name,
                table_name=candidate.submitted_table_name,
                record_kind=record_kind,
                aspect_name=aspect_name,
                operation=operation,
                field_path=row.field_path,
                value_text=row.value_text,
                controlled_ref=row.controlled_ref_id,
                definition=profile,
            )
            semantic_key = _semantic_key(row, record_kind=record_kind)
            expected_semantic_hash = catalog_metadata_semantic_target_hash(
                workspace_id=candidate.workspace_id,
                target_asset_id=candidate.target_asset_id,
                aspect_name=aspect_name,
                semantic_key=semantic_key,
            )
            if (
                row.row_hash != expected_row_hash
                or row.semantic_target_hash != expected_semantic_hash
                or expected_semantic_hash in semantic_hashes
            ):
                return False
            row_hashes.append(expected_row_hash)
            semantic_hashes.add(expected_semantic_hash)
            previous_source_ordinal = row.ordinal
        expected_row_root = catalog_metadata_row_root(row_hashes)
        if candidate.row_root_hash != expected_row_root:
            return False
        expected_candidate_hash = catalog_metadata_candidate_hash(
            workspace_id=candidate.workspace_id,
            ordinal=candidate.ordinal,
            target_asset_id=candidate.target_asset_id,
            candidate_kind=candidate_kind,
            aspect_name=aspect_name,
            submitted_identity_hash=expected_identity_hash,
            row_hashes=tuple(row_hashes),
            definition=profile,
        )
        if candidate.candidate_hash != expected_candidate_hash:
            return False
        seen_row_ids.update(row.row_id for row in candidate.rows)
        seen_source_ordinals.update(row.ordinal for row in candidate.rows)
        return True
    except (KeyError, ValueError, ValidationError):
        return False


def _row_shape_is_consistent(
    row: CatalogMetadataRowEvidenceRecord,
    *,
    record_kind: CatalogMetadataRecordKind,
    definition: TypedUploadProfileDefinition,
) -> bool:
    try:
        operation = CatalogMetadataOperation(row.operation)
    except ValueError:
        return False
    if record_kind in {
        CatalogMetadataRecordKind.TABLE_DESCRIPTION,
        CatalogMetadataRecordKind.COLUMN_DESCRIPTION,
    }:
        if operation not in {CatalogMetadataOperation.SET, CatalogMetadataOperation.CLEAR}:
            return False
        if record_kind is CatalogMetadataRecordKind.TABLE_DESCRIPTION:
            if row.field_path is not None:
                return False
        elif (
            row.field_path is None
            or not row.field_path
            or row.field_path != row.field_path.strip()
            or len(row.field_path) > definition.maximum_field_path_characters
            or _contains_forbidden_identity_control(row.field_path)
        ):
            return False
        return (
            row.controlled_ref_id is None
            and row.controlled_kind is None
            and (
                (
                    operation is CatalogMetadataOperation.SET
                    and bool(row.value_text)
                    and len(row.value_text or "") <= definition.maximum_description_characters
                    and not _contains_forbidden_description_control(row.value_text or "")
                )
                or (operation is CatalogMetadataOperation.CLEAR and row.value_text is None)
            )
        )
    if row.field_path is not None or row.value_text is not None:
        return False
    if record_kind is CatalogMetadataRecordKind.DATASET_DOMAIN:
        return (
            operation is CatalogMetadataOperation.SET
            and row.controlled_ref_id is not None
            and row.controlled_kind == "DOMAIN"
        ) or (
            operation is CatalogMetadataOperation.CLEAR
            and row.controlled_ref_id is None
            and row.controlled_kind is None
        )
    expected_kind = "TERM" if record_kind is CatalogMetadataRecordKind.DATASET_TERM else "TAG"
    return (
        operation is CatalogMetadataOperation.ADD
        and row.controlled_ref_id is not None
        and row.controlled_kind == expected_kind
    )


def _identity_is_valid(
    candidate: CatalogMetadataCandidateEvidence,
    *,
    definition: TypedUploadProfileDefinition,
) -> bool:
    values = (
        (candidate.submitted_platform, definition.maximum_platform_characters),
        (
            candidate.submitted_database_name,
            definition.maximum_database_name_characters,
        ),
        (
            candidate.submitted_schema_name,
            definition.maximum_schema_name_characters,
        ),
        (candidate.submitted_table_name, definition.maximum_table_name_characters),
    )
    return all(
        value
        and value == value.strip()
        and len(value) <= maximum_characters
        and not _contains_forbidden_identity_control(value)
        for value, maximum_characters in values
    )


def _semantic_key(
    row: CatalogMetadataRowEvidenceRecord,
    *,
    record_kind: CatalogMetadataRecordKind,
) -> str:
    if record_kind in {
        CatalogMetadataRecordKind.TABLE_DESCRIPTION,
        CatalogMetadataRecordKind.DATASET_DOMAIN,
    }:
        return record_kind.value
    if record_kind is CatalogMetadataRecordKind.COLUMN_DESCRIPTION:
        if row.field_path is None:
            raise ValueError("Column evidence requires a field path.")
        return f"{record_kind.value}:{row.field_path}"
    if row.controlled_ref_id is None:
        raise ValueError("Controlled metadata evidence requires a local reference.")
    return f"{record_kind.value}:{row.controlled_ref_id}"


def _public_target(target: CatalogAssetIndex) -> CatalogAssetIndex:
    """Return only the canonical projection fields needed by the V3 workbench."""

    return replace(
        target,
        external_urn="",
        description=None,
        owner=None,
        domain=None,
        tags=(),
        glossary_terms=(),
        matches=(),
    )


def _wrap_candidate_cursor(*, after_ordinal: int, context: str) -> str:
    payload = json.dumps(
        {"v": 3, "context": context, "after_ordinal": after_ordinal},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _unwrap_candidate_cursor(cursor: str | None, *, expected_context: str) -> int:
    if cursor is None:
        return 0
    try:
        payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        document = json.loads(payload)
        ordinal = document.get("after_ordinal") if isinstance(document, dict) else None
        if (
            not isinstance(document, dict)
            or set(document) != {"v", "context", "after_ordinal"}
            or document.get("v") != 3
            or document.get("context") != expected_context
            or not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal < 1
        ):
            raise ValueError
        return ordinal
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError) as error:
        raise ValidationError(
            "The candidate cursor is stale or does not match this request."
        ) from error


def _is_sha256(value: str | None) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _contains_forbidden_identity_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _contains_forbidden_description_control(value: str) -> bool:
    return any(
        (ord(character) < 32 and character not in {"\t", "\r", "\n"}) or ord(character) == 127
        for character in value
    )
