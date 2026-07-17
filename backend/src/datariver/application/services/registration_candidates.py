from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from uuid import UUID

from datariver.application.catalog_security import (
    catalog_classification_access_hash,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    CatalogAssetIndex,
    UploadPreparationReceiptEvidence,
    UploadRegistrationCandidateEvidence,
    UploadRegistrationCandidatePage,
    UploadRegistrationCandidateView,
)
from datariver.application.ports import (
    CatalogCandidateTargetReader,
    CatalogWatermarkReader,
    UploadCandidateReader,
    UploadPreparationRepository,
    UploadRepository,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.registration import UploadNotFound, UploadPreparationNotFound
from datariver.application.typed_upload_parser import (
    DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION,
    DATASET_DESCRIPTION_CANDIDATE_KIND,
    dataset_description_candidate_hash,
    dataset_description_submitted_identity_hash,
)
from datariver.application.typed_upload_profiles import typed_profile_definition
from datariver.domain.authz import (
    Action,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.registration import (
    UploadManifest,
    UploadPreparation,
    UploadPreparationState,
    UploadState,
)


class UploadCandidatePageUnavailable(NotFoundError):
    code = "upload_candidate_page_not_available"


class UploadPreparationNotReady(ConflictError):
    code = "upload_preparation_not_ready"


class UploadPreparationEvidenceUnavailable(ConflictError):
    code = "upload_preparation_evidence_unavailable"


class RegistrationCandidateQueryService:
    """Read immutable typed candidates through current catalog and policy scope."""

    def __init__(
        self,
        *,
        uploads: UploadRepository,
        preparations: UploadPreparationRepository,
        candidates: UploadCandidateReader,
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
    ) -> UploadRegistrationCandidatePage:
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
                "The upload preparation evidence is unavailable."
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
        if after_ordinal >= receipt.item_count:
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
                "The upload preparation evidence is unavailable."
            )

        targets = tuple(
            await self._catalog.get_authorized_assets_by_ids(
                subject=subject,
                access=access,
                asset_ids=tuple(candidate.target_asset_id for candidate in candidates),
            )
        )
        targets_by_id = {target.asset_id: target for target in targets}
        if len(targets_by_id) != len(candidates) or any(
            candidate.target_asset_id not in targets_by_id for candidate in candidates
        ):
            raise UploadCandidatePageUnavailable("The candidate page is not available.")

        resources = tuple(self._target_resource(target) for target in targets)
        catalog_allowed = await self._authorization.filter_authorized(
            subject=subject,
            resources=resources,
            action=Action.CATALOG_READ,
            environment=environment,
            request_id=request_id,
            parent_resource_id=preparation_id,
        )
        change_allowed = await self._authorization.filter_authorized(
            subject=subject,
            resources=resources,
            action=Action.CHANGE_CREATE,
            environment=environment,
            request_id=request_id,
            parent_resource_id=preparation_id,
        )
        if len(catalog_allowed) != len(resources) or len(change_allowed) != len(resources):
            raise UploadCandidatePageUnavailable("The candidate page is not available.")
        if any(
            not self._submitted_identity_matches_current(
                candidate=candidate,
                target=targets_by_id[candidate.target_asset_id],
            )
            for candidate in candidates
        ):
            raise UploadCandidatePageUnavailable("The candidate page is not available.")

        visible = candidates[:limit]
        next_cursor = (
            _wrap_candidate_cursor(
                after_ordinal=visible[-1].ordinal,
                context=cursor_context,
            )
            if len(candidates) > limit and visible
            else None
        )
        return UploadRegistrationCandidatePage(
            items=tuple(
                UploadRegistrationCandidateView(
                    evidence=candidate,
                    current_target=targets_by_id[candidate.target_asset_id],
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

    @staticmethod
    def _receipt_is_consistent(
        *,
        manifest: UploadManifest,
        preparation: UploadPreparation,
        receipt: UploadPreparationReceiptEvidence,
    ) -> bool:
        try:
            definition = typed_profile_definition(manifest.content_profile)
        except ValidationError:
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
            manifest.state is UploadState.ACCEPTED
            and manifest.actual_sha256 == manifest.declared_sha256
            and preparation.workspace_id == manifest.workspace_id == receipt.workspace_id
            and preparation.upload_id == manifest.upload_id == receipt.upload_id
            and preparation.preparation_id == receipt.preparation_id
            and preparation.source_manifest_version == manifest.version == receipt.manifest_version
            and preparation.source_sha256 == manifest.declared_sha256 == receipt.source_sha256
            and receipt.accepted_sha256 == receipt.source_sha256
            and preparation.content_profile.value == receipt.content_profile
            and receipt.content_profile == definition.content_profile.value
            and preparation.configuration_hash == receipt.configuration_hash
            and receipt.configuration_hash == definition.configuration_hash
            and receipt.parser_version == definition.parser_version
            and receipt.schema_version == definition.schema_version
            and bool(receipt.scanner_version.strip())
            and 0 < receipt.item_count <= definition.maximum_rows
            and receipt.rejected_count == 0
            and preparation.rows_processed == receipt.item_count
            and preparation.total_rows == receipt.item_count
            and receipt.candidate_count == receipt.item_count
            and receipt.first_ordinal == 1
            and receipt.last_ordinal == receipt.item_count
            and receipt.legacy_candidate_count == 0
            and all(_is_sha256(value) for value in digests)
        )

    @staticmethod
    def _candidate_page_is_consistent(
        *,
        candidates: Sequence[UploadRegistrationCandidateEvidence],
        receipt: UploadPreparationReceiptEvidence,
        after_ordinal: int,
        maximum_items: int,
    ) -> bool:
        if len(candidates) > maximum_items or (
            not candidates and after_ordinal < receipt.item_count
        ):
            return False
        previous = after_ordinal
        seen_ids: set[UUID] = set()
        seen_targets: set[UUID] = set()
        for candidate in candidates:
            identity_values = (
                candidate.submitted_platform,
                candidate.submitted_database_name,
                candidate.submitted_schema_name,
                candidate.submitted_table_name,
            )
            if (
                candidate.workspace_id != receipt.workspace_id
                or candidate.receipt_id != receipt.receipt_id
                or candidate.ordinal != previous + 1
                or candidate.ordinal > receipt.item_count
                or candidate.candidate_id in seen_ids
                or candidate.target_asset_id in seen_targets
                or candidate.evidence_version != DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION
                or candidate.candidate_kind != DATASET_DESCRIPTION_CANDIDATE_KIND
                or any(not isinstance(value, str) or not value for value in identity_values)
                or candidate.submitted_identity_hash is None
            ):
                return False
            platform, database_name, schema_name, table_name = identity_values
            assert isinstance(platform, str)
            assert isinstance(database_name, str)
            assert isinstance(schema_name, str)
            assert isinstance(table_name, str)
            expected_identity_hash = dataset_description_submitted_identity_hash(
                workspace_id=candidate.workspace_id,
                target_asset_id=candidate.target_asset_id,
                platform=platform,
                database_name=database_name,
                schema_name=schema_name,
                table_name=table_name,
            )
            if candidate.submitted_identity_hash != expected_identity_hash:
                return False
            if candidate.candidate_hash != dataset_description_candidate_hash(
                workspace_id=candidate.workspace_id,
                target_asset_id=candidate.target_asset_id,
                proposed_description=candidate.proposed_description,
                submitted_identity_hash=expected_identity_hash,
            ):
                return False
            previous = candidate.ordinal
            seen_ids.add(candidate.candidate_id)
            seen_targets.add(candidate.target_asset_id)
        return True

    @staticmethod
    def _submitted_identity_matches_current(
        *,
        candidate: UploadRegistrationCandidateEvidence,
        target: CatalogAssetIndex,
    ) -> bool:
        return (
            target.workspace_id == candidate.workspace_id
            and target.asset_id == candidate.target_asset_id
            and target.asset_type == "DATASET"
            and target.lifecycle == "ACTIVE"
            and target.platform == candidate.submitted_platform
            and target.database_name == candidate.submitted_database_name
            and target.schema_name == candidate.submitted_schema_name
            and target.name == candidate.submitted_table_name
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
                "authorization_actions": [Action.CATALOG_READ.value, Action.CHANGE_CREATE.value],
                "candidate_root_hash": receipt.candidate_root_hash,
                "classification_access": access_hash,
                "contract": "upload-registration-candidate-cursor-v1",
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


def _wrap_candidate_cursor(*, after_ordinal: int, context: str) -> str:
    payload = json.dumps(
        {"v": 1, "context": context, "after_ordinal": after_ordinal},
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
            or document.get("v") != 1
            or document.get("context") != expected_context
            or not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal < 1
        ):
            raise ValueError
        return ordinal
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as error:
        raise ValidationError(
            "The candidate cursor is stale or does not match this request."
        ) from error


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
