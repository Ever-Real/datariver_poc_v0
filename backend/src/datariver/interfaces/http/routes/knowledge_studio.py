from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    KnowledgeStudioAssetReleaseSource,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioIngestionJobRecord,
    KnowledgeStudioManagedDomainRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioSourceDataset,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioTBoxProposalRecord,
    KnowledgeStudioTBoxRecord,
    KnowledgeStudioValidationEvidence,
)
from datariver.application.knowledge_property_profiles import (
    KnowledgePropertyProfileItem,
    KnowledgePropertyProfileService,
)
from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalJobRecord,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.application.services.knowledge_studio_catalog import (
    CatalogKnowledgeStudioSourceReader,
)
from datariver.application.services.knowledge_studio_preview import (
    KnowledgeStudioPreviewService,
)
from datariver.application.services.knowledge_studio_proposal_jobs import (
    KnowledgeStudioProposalJobService,
    knowledge_studio_proposal_base_tbox_hash,
)
from datariver.application.services.registration import (
    RegistrationService,
    UploadAuthorizationPolicy,
)
from datariver.application.typed_upload_profiles import (
    KNOWLEDGE_STUDIO_DOCUMENT_V1,
)
from datariver.domain.authz import BuiltinPolicyEngine, Classification
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
    utc_now,
)
from datariver.domain.knowledge_property_profiles import KnowledgePropertyProfile
from datariver.domain.knowledge_studio import (
    TBoxElementInput,
    TBoxElementKind,
    TBoxMergeStrategy,
    TBoxOperationInput,
    TBoxOperationKind,
    TBoxProposalMode,
)
from datariver.domain.knowledge_studio_proposal_jobs import (
    KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
    KnowledgeStudioAcceptedUploadPin,
    KnowledgeStudioCatalogFieldMetadataPin,
    KnowledgeStudioCatalogSourcePin,
    KnowledgeStudioProposalInputKind,
    KnowledgeStudioProposalJobPins,
    knowledge_studio_proposal_requester_authorization_hash,
    render_knowledge_studio_catalog_prompt,
)
from datariver.domain.registration import (
    CompletedUploadPart,
    UploadContentProfile,
    UploadManifest,
    UploadState,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.knowledge_property_profiles import (
    SqlKnowledgePropertyProfileRepository,
)
from datariver.infrastructure.db.knowledge_studio import SqlKnowledgeStudioStore
from datariver.infrastructure.db.knowledge_studio_proposal_jobs import (
    SqlKnowledgeStudioProposalJobStore,
)
from datariver.infrastructure.db.registration import SqlUploadUnitOfWork
from datariver.infrastructure.knowledge.runtime import (
    build_knowledge_tbox_schema_runtime,
    resolve_knowledge_runtime_bindings,
    resolve_knowledge_tbox_schema_binding,
)
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    KnowledgePropertyProfileCreateRequest,
    KnowledgePropertyProfileItemResponse,
    KnowledgePropertyProfileListResponse,
    KnowledgePropertyProfileResponse,
    KnowledgePropertyProfileValuesRequest,
    KnowledgeStudioABoxResponse,
    KnowledgeStudioAdvanceRequest,
    KnowledgeStudioAssetReleaseSourcePageResponse,
    KnowledgeStudioAssetReleaseSourceResponse,
    KnowledgeStudioBasicInformationRequest,
    KnowledgeStudioBindingMutationResponse,
    KnowledgeStudioBindingRequest,
    KnowledgeStudioBindingResponse,
    KnowledgeStudioCatalogFieldMetadataResponse,
    KnowledgeStudioDomainOptionResponse,
    KnowledgeStudioDomainOptionsResponse,
    KnowledgeStudioDraftResponse,
    KnowledgeStudioIngestionCancelRequest,
    KnowledgeStudioIngestionJobListResponse,
    KnowledgeStudioIngestionJobResponse,
    KnowledgeStudioManagedDomainListResponse,
    KnowledgeStudioManagedDomainRequest,
    KnowledgeStudioManagedDomainResponse,
    KnowledgeStudioMappingRuleResponse,
    KnowledgeStudioPreflightResponse,
    KnowledgeStudioPreviewEdgeResponse,
    KnowledgeStudioPreviewGraphResponse,
    KnowledgeStudioPreviewNodeResponse,
    KnowledgeStudioPreviewRequest,
    KnowledgeStudioPreviewResponse,
    KnowledgeStudioPublishRequest,
    KnowledgeStudioPublishResponse,
    KnowledgeStudioReleaseResponse,
    KnowledgeStudioSourceDatasetResponse,
    KnowledgeStudioSourceDetailResponse,
    KnowledgeStudioSourcePageResponse,
    KnowledgeStudioSourceUploadInitiateRequest,
    KnowledgeStudioSourceUploadPartResponse,
    KnowledgeStudioTBoxAssetReleaseProposalRequest,
    KnowledgeStudioTBoxBlockCreateRequest,
    KnowledgeStudioTBoxBlockResponse,
    KnowledgeStudioTBoxBlockUpdateRequest,
    KnowledgeStudioTBoxCatalogProposalRequest,
    KnowledgeStudioTBoxElementRequest,
    KnowledgeStudioTBoxElementResponse,
    KnowledgeStudioTBoxOperationsRequest,
    KnowledgeStudioTBoxProposalApplyRequest,
    KnowledgeStudioTBoxProposalConflictResponse,
    KnowledgeStudioTBoxProposalJobCancelRequest,
    KnowledgeStudioTBoxProposalJobListResponse,
    KnowledgeStudioTBoxProposalJobRequest,
    KnowledgeStudioTBoxProposalJobResponse,
    KnowledgeStudioTBoxProposalRequest,
    KnowledgeStudioTBoxProposalResponse,
    KnowledgeStudioTBoxResponse,
    KnowledgeStudioValidationEvidenceResponse,
    PageMeta,
    UploadCompleteRequest,
    UploadPartRequest,
    UploadResponse,
)

router = APIRouter(prefix="/knowledge/studio", tags=["knowledge-studio"])
domains_router = APIRouter(prefix="/knowledge", tags=["knowledge-studio"])
ETAG_RESPONSE = {
    "description": "Knowledge Studio Draft",
    "headers": {"ETag": {"schema": {"type": "string"}}},
}


IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]
IfMatch = Annotated[
    str,
    Header(alias="If-Match", min_length=3, max_length=22),
]


def _service_components(
    request: Request,
    session: SessionDep,
    *,
    administrator_context: bool = False,
) -> tuple[
    SqlKnowledgeStudioStore,
    AuthorizationService,
    CatalogKnowledgeStudioSourceReader,
]:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory),
        development_admin_password_bypass_enabled=(
            administrator_context and container.settings.development_admin_password_bypass_enabled
        ),
        knowledge_studio_intranet_publication_assurance_mode=container.settings.knowledge_studio_intranet_publication_assurance_mode,
        knowledge_studio_intranet_publisher_checker_subject_id=container.settings.knowledge_studio_intranet_publisher_checker_subject_id,
    )
    index = SqlCatalogIndexReader(session)
    catalog = CatalogService(
        index=index,
        discovery=index,
        watermark=index,
        datahub=container.datahub,
        cache=container.cache,
        authorization=authorization,
        detail_cache_ttl_seconds=container.settings.cache_default_ttl_seconds,
        stale_detail_ttl_seconds=container.settings.datahub_stale_ttl_seconds,
        search_cache_ttl_seconds=container.settings.catalog_search_cache_ttl_seconds,
        minimum_query_length=container.settings.catalog_search_minimum_query_length,
        policy_version=BuiltinPolicyEngine.policy_version,
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        telemetry=container.metrics,
        candidate_targets=index,
    )
    return (
        SqlKnowledgeStudioStore(session),
        authorization,
        CatalogKnowledgeStudioSourceReader(catalog),
    )


def _service(request: Request, session: SessionDep) -> KnowledgeStudioService:
    store, authorization, sources = _service_components(request, session)
    return KnowledgeStudioService(
        store=store,
        authorization=authorization,
        intranet_assurance_mode=request.app.state.settings.knowledge_studio_intranet_publication_assurance_mode,
        intranet_publisher_checker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_checker_subject_id,
        intranet_publisher_maker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_maker_subject_id,
        sources=sources,
    )


def _domain_administration_service(
    request: Request,
    session: SessionDep,
) -> KnowledgeStudioService:
    store, authorization, sources = _service_components(
        request,
        session,
        administrator_context=True,
    )
    return KnowledgeStudioService(
        store=store,
        authorization=authorization,
        intranet_assurance_mode=request.app.state.settings.knowledge_studio_intranet_publication_assurance_mode,
        intranet_publisher_checker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_checker_subject_id,
        intranet_publisher_maker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_maker_subject_id,
        sources=sources,
    )


def _property_profile_service(
    request: Request,
    session: SessionDep,
) -> KnowledgePropertyProfileService:
    container = get_container(request)
    return KnowledgePropertyProfileService(
        repository=SqlKnowledgePropertyProfileRepository(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory),
        ),
    )


def _source_upload_service(request: Request) -> RegistrationService:
    container = get_container(request)
    return RegistrationService(
        uow_factory=lambda: SqlUploadUnitOfWork(container.database.session_factory),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory),
        ),
        object_store=container.object_store,
        quarantine_bucket=container.settings.s3_bucket_quarantine,
        presign_ttl_seconds=container.settings.presigned_url_ttl_seconds,
    )


def _proposal_job_service(session: SessionDep) -> KnowledgeStudioProposalJobService:
    return KnowledgeStudioProposalJobService(
        store=SqlKnowledgeStudioProposalJobStore(session),
    )


async def _commit_proposal_job_mutation(session: SessionDep) -> None:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def _runtime_service(request: Request, session: SessionDep) -> KnowledgeStudioService:
    store, authorization, sources = _service_components(request, session)
    runtime = build_knowledge_tbox_schema_runtime(get_container(request).settings)
    return KnowledgeStudioService(
        store=store,
        authorization=authorization,
        intranet_assurance_mode=request.app.state.settings.knowledge_studio_intranet_publication_assurance_mode,
        intranet_publisher_checker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_checker_subject_id,
        intranet_publisher_maker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_maker_subject_id,
        sources=sources,
        schema_assistant=runtime.assistant,
        schema_binding=runtime.binding,
    )


def _ingestion_service(request: Request, session: SessionDep) -> KnowledgeStudioService:
    store, authorization, sources = _service_components(request, session)
    container = get_container(request)
    try:
        embedding_binding = resolve_knowledge_runtime_bindings(container.settings).embedding
    except ConflictError:
        embedding_binding = None
    return KnowledgeStudioService(
        store=store,
        authorization=authorization,
        intranet_assurance_mode=request.app.state.settings.knowledge_studio_intranet_publication_assurance_mode,
        intranet_publisher_checker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_checker_subject_id,
        intranet_publisher_maker_subject_id=request.app.state.settings.knowledge_studio_intranet_publisher_maker_subject_id,
        sources=sources,
        embedding_binding=embedding_binding,
        ingestion_sources=(
            container.knowledge_studio_source_manifest
            if container.settings.knowledge_studio_ingestion_worker_enabled
            else None
        ),
    )


def _preview_service(
    request: Request,
    session: SessionDep,
) -> KnowledgeStudioPreviewService:
    container = get_container(request)
    store, authorization, sources = _service_components(request, session)
    return KnowledgeStudioPreviewService(
        store=store,
        authorization=authorization,
        sources=sources,
        samples=container.knowledge_studio_samples,
    )


def _expected_version(if_match: str) -> int:
    if len(if_match) < 3 or if_match[0] != '"' or if_match[-1] != '"':
        raise ValidationError('If-Match must be a quoted positive integer such as "3".')
    value = if_match[1:-1]
    if not value or any(character < "0" or character > "9" for character in value):
        raise ValidationError('If-Match must be a quoted positive integer such as "3".')
    version = int(value)
    if version < 1 or str(version) != value:
        raise ValidationError('If-Match must be a quoted positive integer such as "3".')
    return version


def _draft_response(record: KnowledgeStudioDraftRecord) -> KnowledgeStudioDraftResponse:
    return KnowledgeStudioDraftResponse(
        id=record.draft_id,
        author_id=record.author_id,
        kind=record.kind,
        state=record.state,
        current_step=record.current_step,
        name=record.name,
        endpoint_alias=record.endpoint_alias,
        endpoint_aliases=list(record.endpoint_aliases),
        domain_id=record.domain_id,
        domain_source_version=record.domain_source_version,
        classification=record.classification.name,
        last_autosaved_at=record.last_autosaved_at,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        submitted_preflight_check_id=record.submitted_preflight_check_id,
        reviewed_by=record.reviewed_by,
        reviewed_at=record.reviewed_at,
        review_reason=record.review_reason,
        published_by=record.published_by,
        published_at=record.published_at,
        materialized_graph_id=record.materialized_graph_id,
        materialized_ontology_version_id=record.materialized_ontology_version_id,
        published_studio_release_id=record.published_studio_release_id,
        managed_intent=record.managed_intent,
        managed_graph_type=record.managed_graph_type,
        accepted_proposal_id=record.accepted_proposal_id,
        accepted_proposal_hash=record.accepted_proposal_hash,
        source_contract_hash=record.source_contract_hash,
        mapping_contract_hash=record.mapping_contract_hash,
    )


def _source_upload_response(manifest: UploadManifest) -> UploadResponse:
    return UploadResponse(
        id=manifest.upload_id,
        display_name=manifest.display_name,
        state=manifest.state.value,
        size_bytes=manifest.declared_size_bytes,
        content_type=manifest.declared_mime,
        sha256=manifest.declared_sha256,
        classification=manifest.classification.name,
        content_profile=manifest.content_profile.value,
        expires_at=manifest.expires_at,
        version=manifest.version,
        validation_summary=manifest.validation_summary,
        last_error_code=manifest.last_error_code,
    )


def _set_source_upload_headers(response: Response, manifest: UploadManifest) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{manifest.version}"'


def _managed_domain_response(
    record: KnowledgeStudioManagedDomainRecord,
) -> KnowledgeStudioManagedDomainResponse:
    return KnowledgeStudioManagedDomainResponse(
        id=record.domain_id,
        display_name=record.display_name,
        source_version=record.source_version,
        created_by=record.created_by,
        creator_display_name=record.creator_display_name,
        creator_email=record.creator_email,
        asset_count=record.asset_count,
        lifecycle=record.lifecycle,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        managed=True,
    )


def _property_profile_response(
    item: KnowledgePropertyProfileItem,
) -> KnowledgePropertyProfileItemResponse:
    profile = item.profile
    return KnowledgePropertyProfileItemResponse(
        graph_id=item.target.graph_id,
        graph_name=item.target.graph_name,
        studio_release_id=item.target.studio_release_id,
        release_no=item.target.release_no,
        ontology_version_id=item.target.ontology_version_id,
        ontology_element_id=item.target.ontology_element_id,
        stable_property_id=item.target.stable_property_id,
        property_name=item.target.property_name,
        owner_class_id=item.target.owner_class_id,
        data_type=item.target.data_type,
        property_urn=item.target.property_urn,
        profile=(
            KnowledgePropertyProfileResponse(
                id=profile.profile_id,
                description=profile.description,
                unit=profile.unit,
                synonyms=list(profile.synonyms),
                lifecycle=profile.lifecycle.value,
                created_by=profile.created_by,
                updated_by=profile.updated_by,
                archived_by=profile.archived_by,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
                archived_at=profile.archived_at,
                version=profile.version,
            )
            if profile is not None
            else None
        ),
    )


def _profile_value_response(
    profile: KnowledgePropertyProfile,
) -> KnowledgePropertyProfileResponse:
    return KnowledgePropertyProfileResponse(
        id=profile.profile_id,
        description=profile.description,
        unit=profile.unit,
        synonyms=list(profile.synonyms),
        lifecycle=profile.lifecycle.value,
        created_by=profile.created_by,
        updated_by=profile.updated_by,
        archived_by=profile.archived_by,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        archived_at=profile.archived_at,
        version=profile.version,
    )


def _studio_release_response(
    record: KnowledgeStudioReleaseRecord,
) -> KnowledgeStudioReleaseResponse:
    return KnowledgeStudioReleaseResponse(
        id=record.studio_release_id,
        graph_id=record.graph_id,
        ontology_version_id=record.ontology_version_id,
        release_no=record.release_no,
        state=record.state,
        contract_version=record.contract_version,
        contract_hash=record.contract_hash,
        tbox_hash=record.tbox_hash,
        abox_hash=record.abox_hash,
        supersedes_studio_release_id=record.supersedes_studio_release_id,
        reviewed_by=record.reviewed_by,
        published_by=record.published_by,
        published_at=record.published_at,
        archived_studio_release_id=record.archived_studio_release_id,
        managed_intent=record.managed_intent,
        managed_graph_type=record.managed_graph_type,
        accepted_proposal_id=record.accepted_proposal_id,
        accepted_proposal_hash=record.accepted_proposal_hash,
        source_contract_hash=record.source_contract_hash,
        mapping_contract_hash=record.mapping_contract_hash,
    )


def _set_draft_headers(response: Response, record: KnowledgeStudioDraftRecord) -> None:
    response.headers["ETag"] = f'"{record.version}"'
    response.headers["Cache-Control"] = "no-store"


def _set_version_headers(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"


def _source_response(
    source: KnowledgeStudioSourceDataset,
) -> KnowledgeStudioSourceDatasetResponse:
    return KnowledgeStudioSourceDatasetResponse(
        id=source.asset_id,
        name=source.name,
        asset_type=source.asset_type,
        platform=source.platform,
        database_name=source.database_name,
        schema_name=source.schema_name,
        classification=source.classification.name,
        source_version=source.source_version,
        projection_source_version=source.projection_source_version,
        field_paths=list(source.field_paths),
        fields_truncated=source.fields_truncated,
        domain=source.domain,
        tags=list(source.tags),
        glossary_terms=list(source.glossary_terms),
        description=source.description,
        description_truncated=source.description_truncated,
        field_metadata=[
            KnowledgeStudioCatalogFieldMetadataResponse(
                field_path=item.field_path,
                field_type=item.field_type,
                native_data_type=item.native_data_type,
                description=item.description,
                description_truncated=item.description_truncated,
                tags=list(item.tags),
                tags_truncated=item.tags_truncated,
                glossary_terms=list(item.glossary_terms),
                terms_truncated=item.terms_truncated,
            )
            for item in source.field_metadata
        ],
        selection_fingerprint=source.selection_fingerprint,
    )


def _asset_release_source_response(
    source: KnowledgeStudioAssetReleaseSource,
) -> KnowledgeStudioAssetReleaseSourceResponse:
    return KnowledgeStudioAssetReleaseSourceResponse(
        graph_id=source.graph_id,
        graph_name=source.graph_name,
        graph_slug=source.graph_slug,
        classification=source.classification.name,
        domain_name=source.domain_name,
        studio_release_id=source.studio_release_id,
        release_no=source.release_no,
        state=source.state,
        contract_hash=source.contract_hash,
        tbox_hash=source.tbox_hash,
        published_at=source.published_at,
        class_count=source.class_count,
        property_count=source.property_count,
        relationship_count=source.relationship_count,
    )


def _binding_response(
    binding: KnowledgeStudioBindingRecord,
) -> KnowledgeStudioBindingResponse:
    return KnowledgeStudioBindingResponse(
        id=binding.binding_id,
        target_stable_element_id=binding.target_stable_element_id,
        source_reference_id=binding.source_reference_id,
        source_asset_id=binding.source_asset_id,
        source_name=binding.source_name,
        source_version=binding.source_version,
        projection_source_version=binding.projection_source_version,
        source_classification=binding.source_classification.name,
        readiness=binding.readiness,
        tbox_version=binding.tbox_version,
        version=binding.version,
        rules=[
            KnowledgeStudioMappingRuleResponse(
                id=rule.rule_id,
                ordinal=rule.ordinal,
                method=rule.method,
                source_field_path=rule.source_field_path,
                target_stable_element_id=rule.target_stable_element_id,
                transform_id=rule.transform_id,
                transform_version=rule.transform_version,
                source_unit=rule.source_unit,
                canonical_unit=rule.canonical_unit,
            )
            for rule in binding.rules
        ],
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _tbox_element_response(
    item: KnowledgeStudioTBoxElementRecord,
) -> KnowledgeStudioTBoxElementResponse:
    return KnowledgeStudioTBoxElementResponse(
        stable_element_id=item.stable_element_id,
        kind=item.kind,
        canonical_name=item.canonical_name,
        display_name=item.display_name,
        parent_stable_element_id=item.parent_stable_element_id,
        hierarchy_relation=item.hierarchy_relation,
        source_stable_element_id=item.source_stable_element_id,
        target_stable_element_id=item.target_stable_element_id,
        data_type=item.data_type,
        nullable=item.nullable,
        ordinal=item.ordinal,
        version=item.version,
        block_id=item.block_id,
        definition=item.definition,
        aliases=list(item.aliases),
        unit=item.unit,
        vector_index_enabled=item.vector_index_enabled,
        metadata_reference_id=item.metadata_reference_id,
        metadata_reference_urn=item.metadata_reference_urn,
        locked_by_later_block=item.locked_by_later_block,
        layout_x=item.layout_x,
        layout_y=item.layout_y,
    )


def _public_source_reference(
    value: dict[str, object] | None,
) -> dict[str, object] | None:
    if value is None:
        return None

    def sanitize(item: object) -> object:
        if isinstance(item, dict):
            return {
                str(key): sanitize(child)
                for key, child in item.items()
                if key not in {"bucket", "object_key"}
            }
        if isinstance(item, list):
            return [sanitize(child) for child in item]
        return item

    sanitized = sanitize(value)
    if not isinstance(sanitized, dict):
        raise TypeError("A source reference must be a JSON object.")
    return sanitized


def _tbox_response(record: KnowledgeStudioTBoxRecord) -> KnowledgeStudioTBoxResponse:
    return KnowledgeStudioTBoxResponse(
        draft=_draft_response(record.draft),
        blocks=[
            KnowledgeStudioTBoxBlockResponse(
                id=block.block_id,
                kind=block.kind,
                title=block.title,
                weight=block.weight,
                ordinal=block.ordinal,
                collapsed=block.collapsed,
                version=block.version,
                source_reference=_public_source_reference(block.source_reference),
                elements=[_tbox_element_response(item) for item in block.elements],
                created_at=block.created_at,
                updated_at=block.updated_at,
            )
            for block in record.blocks
        ],
    )


def _tbox_element_input(
    value: KnowledgeStudioTBoxElementRequest,
) -> TBoxElementInput:
    return TBoxElementInput(
        stable_element_id=value.stable_element_id,
        kind=TBoxElementKind(value.kind),
        canonical_name=value.canonical_name,
        display_name=value.display_name,
        parent_stable_element_id=value.parent_stable_element_id,
        hierarchy_relation=value.hierarchy_relation,
        source_stable_element_id=value.source_stable_element_id,
        target_stable_element_id=value.target_stable_element_id,
        data_type=value.data_type,
        nullable=value.nullable,
        definition=value.definition,
        aliases=tuple(value.aliases),
        unit=value.unit,
        vector_index_enabled=value.vector_index_enabled,
        metadata_reference_id=value.metadata_reference_id,
        metadata_reference_urn=value.metadata_reference_urn,
        layout_x=value.layout_x,
        layout_y=value.layout_y,
    )


def _proposal_response(
    record: KnowledgeStudioTBoxProposalRecord,
) -> KnowledgeStudioTBoxProposalResponse:
    return KnowledgeStudioTBoxProposalResponse(
        id=record.proposal_id,
        draft_id=record.draft_id,
        target_block_id=record.target_block_id,
        state=record.state,
        mode=record.mode,
        merge_strategy=record.merge_strategy,
        base_draft_version=record.base_draft_version,
        prompt=record.prompt,
        elements=[_tbox_element_response(item) for item in record.elements],
        conflicts=[
            KnowledgeStudioTBoxProposalConflictResponse(
                conflict_id=item.conflict_id,
                kind=item.kind,
                stable_element_id=item.stable_element_id,
                field=item.field,
                original_value=item.original_value,
                proposed_value=item.proposed_value,
            )
            for item in record.conflicts
        ],
        model_binding=record.model_binding,
        source_reference=_public_source_reference(record.source_reference),
        error_code=record.error_code,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        applied_at=record.applied_at,
        rejected_at=record.rejected_at,
    )


def _proposal_job_response(
    record: KnowledgeStudioProposalJobRecord,
) -> KnowledgeStudioTBoxProposalJobResponse:
    return KnowledgeStudioTBoxProposalJobResponse(
        id=record.job_id,
        draft_id=record.draft_id,
        input_kind=record.input_kind.value,
        mode=record.mode.value,
        target_block_id=record.target_block_id,
        state=record.state.value,
        stage=record.stage.value,
        progress_percent=record.progress_percent,
        attempt_count=record.attempt_count,
        maximum_attempts=record.maximum_attempts,
        last_failure_code=record.last_failure_code,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        result_proposal_id=(record.result.proposal_id if record.result is not None else None),
        result_evidence_hash=(record.result.evidence_hash if record.result is not None else None),
        supersedes_job_id=record.supersedes_job_id,
    )


def _set_proposal_job_headers(
    response: Response,
    record: KnowledgeStudioProposalJobRecord,
) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{record.version}"'


def _ingestion_response(
    record: KnowledgeStudioIngestionJobRecord,
) -> KnowledgeStudioIngestionJobResponse:
    return KnowledgeStudioIngestionJobResponse(
        id=record.job_id,
        draft_id=record.draft_id,
        graph_id=record.graph_id,
        studio_release_id=record.studio_release_id,
        requested_by=record.requested_by,
        state=record.state,
        progress_percent=record.progress_percent,
        current_stage=record.current_stage,
        vector_target_count=record.vector_target_count,
        attempt_count=record.attempt_count,
        maximum_attempts=record.maximum_attempts,
        result_changeset_id=record.result_changeset_id,
        result_evidence_hash=record.result_evidence_hash,
        error_code=record.error_code,
        allowed_actions=list(record.allowed_actions),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _evidence_response(
    item: KnowledgeStudioValidationEvidence,
) -> KnowledgeStudioValidationEvidenceResponse:
    return KnowledgeStudioValidationEvidenceResponse(
        severity=item.severity,
        code=item.code,
        location=item.location,
        message=item.message,
    )


@domains_router.get(
    "/domains",
    response_model=KnowledgeStudioDomainOptionsResponse,
    operation_id="list_knowledge_domains",
)
@router.get(
    "/domains",
    response_model=KnowledgeStudioDomainOptionsResponse,
    operation_id="list_knowledge_studio_domains_compatibility",
)
async def list_knowledge_studio_domains(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    classification: Annotated[
        Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"],
        Query(),
    ] = "INTERNAL",
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> KnowledgeStudioDomainOptionsResponse:
    response.headers["Cache-Control"] = "no-store"
    values = await _service(request, session).list_domains(
        workspace_id=context.workspace_id,
        subject=context.subject,
        classification=Classification[classification],
        query=q,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioDomainOptionsResponse(
        items=[
            KnowledgeStudioDomainOptionResponse(
                id=value.domain_id,
                display_name=value.display_name,
                source_version=value.source_version,
                created_by=value.created_by,
                creator_display_name=value.creator_display_name,
                creator_email=value.creator_email,
                asset_count=value.asset_count,
                lifecycle=value.lifecycle,
                version=value.version,
                created_at=value.created_at,
                updated_at=value.updated_at,
                managed=value.managed,
            )
            for value in values
        ]
    )


@domains_router.get(
    "/domains/manage",
    response_model=KnowledgeStudioManagedDomainListResponse,
    operation_id="list_managed_knowledge_domains",
)
async def list_managed_knowledge_domains(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> KnowledgeStudioManagedDomainListResponse:
    records = await _domain_administration_service(request, session).list_managed_domains(
        workspace_id=context.workspace_id,
        subject=context.subject,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return KnowledgeStudioManagedDomainListResponse(
        items=[_managed_domain_response(record) for record in records]
    )


@domains_router.post(
    "/domains",
    response_model=KnowledgeStudioManagedDomainResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_knowledge_domain",
)
@domains_router.post(
    "/domains/manage",
    response_model=KnowledgeStudioManagedDomainResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_managed_knowledge_domain(
    payload: KnowledgeStudioManagedDomainRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioManagedDomainResponse:
    request_hash = canonical_json_hash(payload.model_dump(mode="json"))
    record = await _service(request, session).create_managed_domain(
        workspace_id=context.workspace_id,
        subject=context.subject,
        display_name=payload.display_name,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{record.version}"'
    return _managed_domain_response(record)


@domains_router.patch(
    "/domains/{domain_id}",
    response_model=KnowledgeStudioManagedDomainResponse,
    operation_id="update_knowledge_domain",
)
@domains_router.patch(
    "/domains/manage/{domain_id}",
    response_model=KnowledgeStudioManagedDomainResponse,
    include_in_schema=False,
)
async def update_managed_knowledge_domain(
    domain_id: UUID,
    payload: KnowledgeStudioManagedDomainRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioManagedDomainResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "domain_id": str(domain_id),
            "display_name": payload.display_name,
            "expected_version": expected_version,
        }
    )
    record = await _domain_administration_service(request, session).update_managed_domain(
        workspace_id=context.workspace_id,
        subject=context.subject,
        domain_id=domain_id,
        display_name=payload.display_name,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{record.version}"'
    return _managed_domain_response(record)


@domains_router.delete(
    "/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="archive_knowledge_domain",
)
@domains_router.delete(
    "/domains/manage/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def delete_managed_knowledge_domain(
    domain_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> None:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "domain_id": str(domain_id),
            "expected_version": expected_version,
            "operation": "ARCHIVE",
        }
    )
    await _domain_administration_service(request, session).archive_managed_domain(
        workspace_id=context.workspace_id,
        subject=context.subject,
        domain_id=domain_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"


@domains_router.get(
    "/property-profiles",
    response_model=KnowledgePropertyProfileListResponse,
    operation_id="list_knowledge_property_profiles",
)
async def list_knowledge_property_profiles(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> KnowledgePropertyProfileListResponse:
    values = await _property_profile_service(request, session).list_items(
        workspace_id=context.workspace_id,
        subject=context.subject,
        query=q,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return KnowledgePropertyProfileListResponse(
        items=[_property_profile_response(item) for item in values]
    )


@domains_router.post(
    "/property-profiles",
    response_model=KnowledgePropertyProfileResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_knowledge_property_profile",
)
async def create_knowledge_property_profile(
    payload: KnowledgePropertyProfileCreateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> KnowledgePropertyProfileResponse:
    request_hash = canonical_json_hash(payload.model_dump(mode="json"))
    profile = await _property_profile_service(request, session).create_profile(
        workspace_id=context.workspace_id,
        subject=context.subject,
        ontology_element_id=payload.ontology_element_id,
        description=payload.description,
        unit=payload.unit,
        synonyms=tuple(payload.synonyms),
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{profile.version}"'
    return _profile_value_response(profile)


@domains_router.patch(
    "/property-profiles/{profile_id}",
    response_model=KnowledgePropertyProfileResponse,
    operation_id="update_knowledge_property_profile",
)
async def update_knowledge_property_profile(
    profile_id: UUID,
    payload: KnowledgePropertyProfileValuesRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgePropertyProfileResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "profile_id": str(profile_id),
            "expected_version": expected_version,
            "values": payload.model_dump(mode="json"),
        }
    )
    profile = await _property_profile_service(request, session).update_profile(
        workspace_id=context.workspace_id,
        subject=context.subject,
        profile_id=profile_id,
        description=payload.description,
        unit=payload.unit,
        synonyms=tuple(payload.synonyms),
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{profile.version}"'
    return _profile_value_response(profile)


@domains_router.delete(
    "/property-profiles/{profile_id}",
    response_model=KnowledgePropertyProfileResponse,
    operation_id="archive_knowledge_property_profile",
)
async def archive_knowledge_property_profile(
    profile_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgePropertyProfileResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "profile_id": str(profile_id),
            "expected_version": expected_version,
            "operation": "ARCHIVE",
        }
    )
    profile = await _property_profile_service(request, session).archive_profile(
        workspace_id=context.workspace_id,
        subject=context.subject,
        profile_id=profile_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{profile.version}"'
    return _profile_value_response(profile)


def _managed_draft_request_hash(intent: str, payload_dict: dict[str, Any]) -> str:
    return canonical_json_hash({"managed_intent": intent, "payload": payload_dict})


@router.post(
    "/managed-drafts/{intent}",
    response_model=KnowledgeStudioDraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: ETAG_RESPONSE},
)
async def create_managed_knowledge_studio_draft(
    intent: str,
    payload: KnowledgeStudioBasicInformationRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioDraftResponse:
    request_hash = _managed_draft_request_hash(intent, payload.model_dump(mode="json"))
    record = await _service(request, session).create_managed_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        name=payload.name,
        endpoint_alias=payload.endpoint_alias,
        endpoint_aliases=tuple(payload.endpoint_aliases or [payload.endpoint_alias]),
        domain_id=payload.domain_id,
        domain_source_version=payload.domain_source_version,
        classification=Classification[payload.classification],
        managed_intent=intent,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts",
    response_model=KnowledgeStudioDraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: ETAG_RESPONSE},
)
async def create_knowledge_studio_draft(
    payload: KnowledgeStudioBasicInformationRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioDraftResponse:
    request_hash = canonical_json_hash(payload.model_dump(mode="json"))
    record = await _service(request, session).create_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        name=payload.name,
        endpoint_alias=payload.endpoint_alias,
        endpoint_aliases=tuple(payload.endpoint_aliases or [payload.endpoint_alias]),
        domain_id=payload.domain_id,
        domain_source_version=payload.domain_source_version,
        classification=Classification[payload.classification],
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/from-asset/{asset_id}",
    response_model=KnowledgeStudioDraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: ETAG_RESPONSE},
)
async def create_knowledge_studio_edit_draft(
    asset_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioDraftResponse:
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_EDIT_DRAFT_V1",
            "asset_id": str(asset_id),
        }
    )
    record = await _service(request, session).create_edit_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        graph_id=asset_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.get(
    "/drafts/resumable",
    response_model=KnowledgeStudioDraftResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_resumable_knowledge_studio_draft(
    endpoint_alias: Annotated[str, Query(min_length=3, max_length=100)],
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioDraftResponse:
    record = await _service(request, session).get_resumable_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        endpoint_alias=endpoint_alias,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.get(
    "/drafts/{draft_id}",
    response_model=KnowledgeStudioDraftResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_knowledge_studio_draft(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioDraftResponse:
    record = await _service(request, session).get_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.get(
    "/drafts/{draft_id}/tbox",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_knowledge_studio_tbox(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioTBoxResponse:
    record = await _service(request, session).get_tbox(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/blocks",
    response_model=KnowledgeStudioTBoxResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: ETAG_RESPONSE},
)
async def create_knowledge_studio_tbox_block(
    draft_id: UUID,
    payload: KnowledgeStudioTBoxBlockCreateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).create_tbox_block(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        kind=payload.kind,
        title=payload.title,
        weight=payload.weight,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.post(
    "/drafts/{draft_id}/source-uploads",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_knowledge_studio_source_upload(
    draft_id: UUID,
    payload: KnowledgeStudioSourceUploadInitiateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> UploadResponse:
    record = await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    if record.draft.classification > Classification.INTERNAL:
        raise ValidationError(
            "Knowledge Studio document sources currently support PUBLIC or INTERNAL Drafts.",
            details={"code": "KNOWLEDGE_SOURCE_CLASSIFICATION_NOT_SUPPORTED"},
        )
    request_hash = canonical_json_hash(
        {
            "contract": "knowledge-studio-source-upload.v1",
            "draft_id": str(draft_id),
            "payload": payload.model_dump(mode="json"),
            "workspace_id": str(context.workspace_id),
        }
    )
    manifest = await _source_upload_service(request).initiate(
        workspace_id=context.workspace_id,
        subject=context.subject,
        display_name=payload.display_name,
        declared_size_bytes=payload.size_bytes,
        declared_mime=payload.content_type,
        declared_sha256=payload.sha256,
        classification=record.draft.classification,
        content_profile=UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
    )
    _set_source_upload_headers(response, manifest)
    return _source_upload_response(manifest)


@router.get(
    "/drafts/{draft_id}/source-uploads/{upload_id}",
    response_model=UploadResponse,
)
async def get_knowledge_studio_source_upload(
    draft_id: UUID,
    upload_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> UploadResponse:
    await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    manifest = await _source_upload_service(request).get_manifest(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
    )
    if manifest.content_profile is not UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1:
        raise ValidationError(
            "The upload is not a Knowledge Studio document source.",
            details={"code": "KNOWLEDGE_SOURCE_PROFILE_MISMATCH"},
        )
    _set_source_upload_headers(response, manifest)
    return _source_upload_response(manifest)


@router.post(
    "/drafts/{draft_id}/source-uploads/{upload_id}/parts",
    response_model=KnowledgeStudioSourceUploadPartResponse,
)
async def presign_knowledge_studio_source_upload_part(
    draft_id: UUID,
    upload_id: UUID,
    payload: UploadPartRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioSourceUploadPartResponse:
    await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    upload_service = _source_upload_service(request)
    manifest = await upload_service.get_manifest(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
    )
    if manifest.content_profile is not UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1:
        raise ValidationError(
            "The upload is not a Knowledge Studio document source.",
            details={"code": "KNOWLEDGE_SOURCE_PROFILE_MISMATCH"},
        )
    url, lifetime = await upload_service.presign_part(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        part_number=payload.part_number,
        checksum_sha256=payload.checksum_sha256,
        environment=context.environment,
        request_id=context.request_id,
        authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
    )
    return KnowledgeStudioSourceUploadPartResponse(
        url=url,
        expires_seconds=lifetime,
    )


@router.post(
    "/drafts/{draft_id}/source-uploads/{upload_id}/complete",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_knowledge_studio_source_upload(
    draft_id: UUID,
    upload_id: UUID,
    payload: UploadCompleteRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> UploadResponse:
    await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    upload_service = _source_upload_service(request)
    manifest = await upload_service.get_manifest(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
    )
    if manifest.content_profile is not UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1:
        raise ValidationError(
            "The upload is not a Knowledge Studio document source.",
            details={"code": "KNOWLEDGE_SOURCE_PROFILE_MISMATCH"},
        )
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "knowledge-studio-source-upload-completion.v1",
            "draft_id": str(draft_id),
            "expected_version": expected_version,
            "parts": [part.model_dump(mode="json") for part in payload.parts],
            "upload_id": str(upload_id),
            "workspace_id": str(context.workspace_id),
        }
    )
    manifest = await upload_service.queue_completion(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        parts=[
            CompletedUploadPart(
                part_number=part.part_number,
                etag=part.etag,
                checksum_sha256=part.checksum_sha256,
            )
            for part in payload.parts
        ],
        expected_version=expected_version,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
    )
    _set_source_upload_headers(response, manifest)
    return _source_upload_response(manifest)


@router.post(
    "/drafts/{draft_id}/tbox/proposal-jobs",
    response_model=KnowledgeStudioTBoxProposalJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_knowledge_studio_tbox_proposal_job(
    draft_id: UUID,
    payload: KnowledgeStudioTBoxProposalJobRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioTBoxProposalJobResponse:
    container = get_container(request)
    if not container.settings.knowledge_studio_proposal_worker_enabled:
        raise ConflictError(
            "Knowledge Studio Proposal processing is not enabled.",
            details={"code": "KNOWLEDGE_PROPOSAL_WORKER_DISABLED"},
        )
    expected_version = _expected_version(if_match)
    mode = TBoxProposalMode(payload.mode)
    studio = _service(request, session)
    tbox = await studio.prepare_tbox_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        target_block_id=payload.target_block_id,
        mode=mode,
        expected_version=expected_version,
        environment=context.environment,
        request_id=context.request_id,
    )

    input_kind = KnowledgeStudioProposalInputKind(payload.input_kind)
    source_pin: KnowledgeStudioAcceptedUploadPin | KnowledgeStudioCatalogSourcePin
    if input_kind is KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA:
        assert payload.source_upload_id is not None
        assert payload.source_manifest_version is not None
        manifest = await _source_upload_service(request).get_manifest(
            workspace_id=context.workspace_id,
            upload_id=payload.source_upload_id,
            subject=context.subject,
            environment=context.environment,
            request_id=context.request_id,
            authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
        )
        if (
            manifest.state is not UploadState.ACCEPTED
            or manifest.version != payload.source_manifest_version
            or manifest.content_profile is not UploadContentProfile.KNOWLEDGE_STUDIO_DOCUMENT_V1
            or manifest.actual_size_bytes is None
            or manifest.actual_mime is None
            or manifest.actual_sha256 is None
            or manifest.classification > Classification.INTERNAL
            or manifest.classification > tbox.draft.classification
            or manifest.validation_summary.get("profile_configuration_hash")
            != KNOWLEDGE_STUDIO_DOCUMENT_V1.configuration_hash
            or manifest.validation_summary.get("parser_version")
            != KNOWLEDGE_STUDIO_DOCUMENT_V1.parser_version
        ):
            raise ConflictError(
                "The accepted Knowledge Studio document pin is unavailable or stale.",
                details={"code": "KNOWLEDGE_SOURCE_PIN_STALE"},
            )
        source_pin = KnowledgeStudioAcceptedUploadPin(
            manifest_id=manifest.upload_id,
            manifest_version=manifest.version,
            content_sha256=manifest.actual_sha256,
            media_type=manifest.actual_mime,
            size_bytes=manifest.actual_size_bytes,
            classification=int(manifest.classification),
            content_profile=manifest.content_profile.value,
            validation_evidence_hash=canonical_json_hash(
                {
                    "contract": "KNOWLEDGE_STUDIO_UPLOAD_VALIDATION_EVIDENCE_V1",
                    "manifest_id": str(manifest.upload_id),
                    "manifest_version": manifest.version,
                    "validation_summary": manifest.validation_summary,
                }
            ),
            filename=manifest.display_name,
        )
        parser_configuration_hash = KNOWLEDGE_STUDIO_DOCUMENT_V1.configuration_hash
    else:
        assert payload.asset_id is not None
        source = await studio.get_tbox_catalog_source(
            workspace_id=context.workspace_id,
            subject=context.subject,
            draft_id=draft_id,
            asset_id=payload.asset_id,
            environment=context.environment,
            request_id=context.request_id,
        )
        if source.stale_at is not None or source.dataset.classification > Classification.INTERNAL:
            raise ConflictError(
                "The Catalog source is stale or outside the inference classification boundary.",
                details={"code": "CATALOG_PROPOSAL_SOURCE_INELIGIBLE"},
            )
        requested_fields = tuple(payload.selected_field_paths)
        if len(set(requested_fields)) != len(requested_fields):
            raise ValidationError("Catalog Proposal field paths must be unique.")
        if source.dataset.selection_fingerprint != payload.expected_selection_fingerprint:
            raise ConflictError(
                "The Catalog metadata changed after it was selected. Reload the source detail.",
                details={"code": "CATALOG_PROPOSAL_SELECTION_STALE"},
            )
        available_fields = set(source.dataset.field_paths)
        if any(field not in available_fields for field in requested_fields):
            raise ValidationError(
                "Catalog Proposal fields must belong to the authorized source version.",
                details={"code": "CATALOG_FIELD_NOT_IN_SOURCE"},
            )
        requested_field_set = set(requested_fields)
        selected_metadata = tuple(
            item for item in source.dataset.field_metadata if item.field_path in requested_field_set
        )
        selected_fields = tuple(item.field_path for item in selected_metadata)
        if len(selected_fields) != len(requested_fields):
            raise ConflictError(
                "The selected Catalog metadata is incomplete.",
                details={"code": "CATALOG_PROPOSAL_METADATA_INCOMPLETE"},
            )
        source_pin = KnowledgeStudioCatalogSourcePin(
            asset_id=source.dataset.asset_id,
            name=source.dataset.name,
            asset_type=source.dataset.asset_type,
            classification=int(source.dataset.classification),
            source_version=source.dataset.source_version,
            projection_source_version=source.dataset.projection_source_version,
            selected_field_paths=selected_fields,
            platform=source.dataset.platform,
            database_name=source.dataset.database_name,
            schema_name=source.dataset.schema_name,
            domain=source.dataset.domain,
            tags=source.dataset.tags,
            glossary_terms=source.dataset.glossary_terms,
            contract_version=KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
            description=source.dataset.description,
            description_truncated=source.dataset.description_truncated,
            field_metadata=tuple(
                KnowledgeStudioCatalogFieldMetadataPin(
                    field_path=item.field_path,
                    field_type=item.field_type,
                    native_data_type=item.native_data_type,
                    description=item.description,
                    description_truncated=item.description_truncated,
                    tags=item.tags,
                    tags_truncated=item.tags_truncated,
                    glossary_terms=item.glossary_terms,
                    terms_truncated=item.terms_truncated,
                )
                for item in selected_metadata
            ),
        ).with_computed_metadata_fingerprint()
        render_knowledge_studio_catalog_prompt(source_pin)
        parser_configuration_hash = canonical_json_hash(
            {
                "contract": "KNOWLEDGE_STUDIO_CATALOG_SCHEMA_PARSER_V2",
                "maximum_fields": 100,
                "maximum_prompt_characters": 4_000,
            }
        )

    schema_binding = resolve_knowledge_tbox_schema_binding(container.settings)
    pins = KnowledgeStudioProposalJobPins(
        workspace_id=context.workspace_id,
        draft_id=draft_id,
        requested_by=context.subject.subject_id,
        input_kind=input_kind,
        mode=mode,
        target_block_id=payload.target_block_id,
        base_draft_version=tbox.draft.version,
        base_tbox_hash=knowledge_studio_proposal_base_tbox_hash(tbox),
        source=source_pin,
        parser_configuration_hash=parser_configuration_hash,
        schema_binding=schema_binding,
        requester_authorization_hash=(
            knowledge_studio_proposal_requester_authorization_hash(context.subject)
        ),
        prepared_at=utc_now(),
    )
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_TBOX_PROPOSAL_JOB_REQUEST_V1",
            "expected_draft_version": expected_version,
            "payload": payload.model_dump(mode="json"),
            "pin_hash": pins.evidence_hash(),
        }
    )
    job = await _proposal_job_service(session).enqueue(
        pins=pins,
        request_hash=request_hash,
        maximum_attempts=(container.settings.knowledge_studio_proposal_job_maximum_attempts),
        idempotency_key=idempotency_key,
    )
    await _commit_proposal_job_mutation(session)
    _set_proposal_job_headers(response, job)
    response.headers["Location"] = (
        f"/api/v1/knowledge/studio/drafts/{draft_id}/tbox/proposal-jobs/{job.job_id}"
    )
    return _proposal_job_response(job)


@router.get(
    "/drafts/{draft_id}/tbox/proposal-jobs",
    response_model=KnowledgeStudioTBoxProposalJobListResponse,
)
async def list_knowledge_studio_tbox_proposal_jobs(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> KnowledgeStudioTBoxProposalJobListResponse:
    await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    page = await _proposal_job_service(session).list_owned(
        workspace_id=context.workspace_id,
        draft_id=draft_id,
        actor_id=context.subject.subject_id,
        limit=limit,
        cursor=cursor,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return KnowledgeStudioTBoxProposalJobListResponse(
        items=[_proposal_job_response(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/drafts/{draft_id}/tbox/proposal-jobs/{job_id}",
    response_model=KnowledgeStudioTBoxProposalJobResponse,
)
async def get_knowledge_studio_tbox_proposal_job(
    draft_id: UUID,
    job_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioTBoxProposalJobResponse:
    await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    job = await _proposal_job_service(session).get_owned(
        workspace_id=context.workspace_id,
        draft_id=draft_id,
        job_id=job_id,
        actor_id=context.subject.subject_id,
    )
    if job is None:
        raise NotFoundError("The Knowledge Studio Proposal job does not exist.")
    _set_proposal_job_headers(response, job)
    return _proposal_job_response(job)


@router.post(
    "/drafts/{draft_id}/tbox/proposal-jobs/{job_id}/cancel",
    response_model=KnowledgeStudioTBoxProposalJobResponse,
)
async def cancel_knowledge_studio_tbox_proposal_job(
    draft_id: UUID,
    job_id: UUID,
    payload: KnowledgeStudioTBoxProposalJobCancelRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioTBoxProposalJobResponse:
    await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_TBOX_PROPOSAL_JOB_CANCEL_V1",
            "draft_id": str(draft_id),
            "expected_job_version": expected_version,
            "job_id": str(job_id),
            "reason": " ".join(payload.reason.split()),
            "workspace_id": str(context.workspace_id),
        }
    )
    job = await _proposal_job_service(session).cancel(
        workspace_id=context.workspace_id,
        draft_id=draft_id,
        job_id=job_id,
        actor_id=context.subject.subject_id,
        expected_version=expected_version,
        reason=payload.reason,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
    )
    await _commit_proposal_job_mutation(session)
    _set_proposal_job_headers(response, job)
    return _proposal_job_response(job)


@router.post(
    "/drafts/{draft_id}/tbox/proposal-jobs/{job_id}/retry",
    response_model=KnowledgeStudioTBoxProposalJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_knowledge_studio_tbox_proposal_job(
    draft_id: UUID,
    job_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioTBoxProposalJobResponse:
    await _service(request, session).authorize_tbox_source_upload(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=None,
        environment=context.environment,
        request_id=context.request_id,
    )
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_TBOX_PROPOSAL_JOB_RETRY_V1",
            "draft_id": str(draft_id),
            "expected_job_version": expected_version,
            "job_id": str(job_id),
            "workspace_id": str(context.workspace_id),
        }
    )
    job = await _proposal_job_service(session).retry(
        workspace_id=context.workspace_id,
        draft_id=draft_id,
        job_id=job_id,
        actor_id=context.subject.subject_id,
        expected_version=expected_version,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
    )
    await _commit_proposal_job_mutation(session)
    _set_proposal_job_headers(response, job)
    response.headers["Location"] = (
        f"/api/v1/knowledge/studio/drafts/{draft_id}/tbox/proposal-jobs/{job.job_id}"
    )
    return _proposal_job_response(job)


@router.post(
    "/drafts/{draft_id}/tbox/proposals",
    response_model=KnowledgeStudioTBoxProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_studio_tbox_proposal(
    draft_id: UUID,
    payload: KnowledgeStudioTBoxProposalRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxProposalResponse:
    expected_version = _expected_version(if_match)
    record = await _runtime_service(request, session).create_tbox_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        target_block_id=payload.target_block_id,
        mode=TBoxProposalMode(payload.mode),
        prompt=payload.prompt,
        expected_version=expected_version,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _proposal_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/catalog-proposals",
    response_model=None,
    status_code=status.HTTP_410_GONE,
    deprecated=True,
)
async def create_knowledge_studio_tbox_catalog_proposal(
    draft_id: UUID,
    payload: KnowledgeStudioTBoxCatalogProposalRequest,
    context: ContextDep,
) -> JSONResponse:
    del draft_id, payload, context
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        media_type="application/problem+json",
        headers={"Cache-Control": "private, no-store"},
        content={
            "type": (
                "https://datariver.invalid/problems/knowledge-studio-synchronous-proposal-retired"
            ),
            "title": "Synchronous Catalog Proposal creation is retired",
            "status": status.HTTP_410_GONE,
            "detail": (
                "Create a CATALOG_SCHEMA job through the Draft-scoped T-Box Proposal jobs endpoint."
            ),
        },
    )


@router.post(
    "/drafts/{draft_id}/tbox/asset-release-proposals",
    response_model=KnowledgeStudioTBoxProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_studio_tbox_asset_release_proposal(
    draft_id: UUID,
    payload: KnowledgeStudioTBoxAssetReleaseProposalRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxProposalResponse:
    record = await _service(request, session).create_tbox_asset_release_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        studio_release_id=payload.studio_release_id,
        tbox_hash=payload.tbox_hash,
        target_block_id=payload.target_block_id,
        mode=TBoxProposalMode(payload.mode),
        expected_version=_expected_version(if_match),
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _proposal_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/document-proposals",
    response_model=None,
    status_code=status.HTTP_410_GONE,
    deprecated=True,
)
async def create_knowledge_studio_document_proposal(
    draft_id: UUID,
    context: ContextDep,
) -> JSONResponse:
    del draft_id, context
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        media_type="application/problem+json",
        headers={"Cache-Control": "private, no-store"},
        content={
            "type": (
                "https://datariver.invalid/problems/knowledge-studio-synchronous-proposal-retired"
            ),
            "title": "Synchronous document Proposal creation is retired",
            "status": status.HTTP_410_GONE,
            "detail": (
                "Upload an accepted Draft source, then create a DOCUMENT_SCHEMA "
                "job through the T-Box Proposal jobs endpoint."
            ),
        },
    )


@router.get(
    "/drafts/{draft_id}/tbox/proposals/{proposal_id}",
    response_model=KnowledgeStudioTBoxProposalResponse,
)
async def get_knowledge_studio_tbox_proposal(
    draft_id: UUID,
    proposal_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioTBoxProposalResponse:
    record = await _service(request, session).get_tbox_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        proposal_id=proposal_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _proposal_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/proposals/{proposal_id}/apply",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def apply_knowledge_studio_tbox_proposal(
    draft_id: UUID,
    proposal_id: UUID,
    payload: KnowledgeStudioTBoxProposalApplyRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "proposal_id": str(proposal_id),
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).apply_tbox_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        proposal_id=proposal_id,
        merge_strategy=TBoxMergeStrategy(payload.merge_strategy),
        resolutions=tuple(
            {
                key: value
                for key, value in item.model_dump(mode="json", exclude_none=True).items()
                if isinstance(value, str)
            }
            for item in payload.resolutions
        ),
        excluded_stable_element_ids=tuple(payload.excluded_stable_element_ids),
        element_overrides=tuple(
            item.model_dump(mode="json", exclude_none=True) for item in payload.element_overrides
        ),
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.patch(
    "/drafts/{draft_id}/tbox/blocks/{block_id}",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def update_knowledge_studio_tbox_block(
    draft_id: UUID,
    block_id: UUID,
    payload: KnowledgeStudioTBoxBlockUpdateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "block_id": str(block_id),
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).update_tbox_block(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        block_id=block_id,
        title=payload.title,
        weight=payload.weight,
        collapsed=payload.collapsed,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.delete(
    "/drafts/{draft_id}/tbox/blocks/{block_id}",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def delete_knowledge_studio_tbox_block(
    draft_id: UUID,
    block_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "block_id": str(block_id),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).delete_tbox_block(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        block_id=block_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/blocks/{block_id}/operations",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def apply_knowledge_studio_tbox_operations(
    draft_id: UUID,
    block_id: UUID,
    payload: KnowledgeStudioTBoxOperationsRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "block_id": str(block_id),
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    operations = tuple(
        TBoxOperationInput(
            operation=TBoxOperationKind(item.operation),
            stable_element_id=item.stable_element_id,
            element=_tbox_element_input(item.element) if item.element is not None else None,
            layout_x=item.layout_x,
            layout_y=item.layout_y,
        )
        for item in payload.operations
    )
    record = await _service(request, session).apply_tbox_operations(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        block_id=block_id,
        operations=operations,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.patch(
    "/drafts/{draft_id}",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def autosave_knowledge_studio_draft(
    draft_id: UUID,
    payload: KnowledgeStudioBasicInformationRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).autosave_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        name=payload.name,
        endpoint_alias=payload.endpoint_alias,
        endpoint_aliases=tuple(payload.endpoint_aliases or [payload.endpoint_alias]),
        domain_id=payload.domain_id,
        domain_source_version=payload.domain_source_version,
        classification=Classification[payload.classification],
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/advance",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def advance_knowledge_studio_draft(
    draft_id: UUID,
    payload: KnowledgeStudioAdvanceRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "target_step": payload.target_step,
            "expected_version": expected_version,
        }
    )
    service = _service(request, session)
    if payload.target_step == "TBOX":
        record = await service.advance_to_tbox(
            workspace_id=context.workspace_id,
            subject=context.subject,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            environment=context.environment,
            request_id=context.request_id,
        )
    else:
        record = await service.advance_to_abox(
            workspace_id=context.workspace_id,
            subject=context.subject,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            environment=context.environment,
            request_id=context.request_id,
        )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/submit-review",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def submit_knowledge_studio_review(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).submit_review(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/discard",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def discard_knowledge_studio_draft(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).discard_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/publish",
    response_model=KnowledgeStudioPublishResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def publish_knowledge_studio_draft(
    draft_id: UUID,
    payload: KnowledgeStudioPublishRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioPublishResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
            "payload": payload.model_dump(mode="json"),
        }
    )
    draft, studio_release = await _service(request, session).publish_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        review_reason=payload.review_reason,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, draft)
    return KnowledgeStudioPublishResponse(
        draft=_draft_response(draft),
        release=_studio_release_response(studio_release),
    )


@router.get(
    "/drafts/{draft_id}/abox",
    response_model=KnowledgeStudioABoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_knowledge_studio_abox(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioABoxResponse:
    record = await _service(request, session).get_abox(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return KnowledgeStudioABoxResponse(
        draft=_draft_response(record.draft),
        tbox_elements=[_tbox_element_response(item) for item in record.tbox_elements],
        bindings=[_binding_response(item) for item in record.bindings],
    )


@router.post(
    "/drafts/{draft_id}/abox/ingestions",
    response_model=KnowledgeStudioIngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_knowledge_studio_ingestion_job(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioIngestionJobResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_INGESTION_REQUEST_V1",
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _ingestion_service(request, session).create_ingestion_job(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _ingestion_response(record)


@router.get(
    "/drafts/{draft_id}/abox/ingestions",
    response_model=KnowledgeStudioIngestionJobListResponse,
)
async def list_knowledge_studio_ingestion_jobs(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> KnowledgeStudioIngestionJobListResponse:
    records = await _service(request, session).list_ingestion_jobs(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return KnowledgeStudioIngestionJobListResponse(
        items=[_ingestion_response(record) for record in records]
    )


@router.get(
    "/drafts/{draft_id}/abox/ingestions/{job_id}",
    response_model=KnowledgeStudioIngestionJobResponse,
)
async def get_knowledge_studio_ingestion_job(
    draft_id: UUID,
    job_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioIngestionJobResponse:
    record = await _service(request, session).get_ingestion_job(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        job_id=job_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _ingestion_response(record)


@router.post(
    "/drafts/{draft_id}/abox/ingestions/{job_id}/cancel",
    response_model=KnowledgeStudioIngestionJobResponse,
)
async def cancel_knowledge_studio_ingestion_job(
    draft_id: UUID,
    job_id: UUID,
    payload: KnowledgeStudioIngestionCancelRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioIngestionJobResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_INGESTION_CANCEL_V1",
            "draft_id": str(draft_id),
            "job_id": str(job_id),
            "expected_version": expected_version,
            "reason": payload.reason.strip(),
        }
    )
    record = await _ingestion_service(request, session).cancel_ingestion_job(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        job_id=job_id,
        expected_version=expected_version,
        reason=payload.reason,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_version_headers(response, record.version)
    response.headers["Cache-Control"] = "no-store"
    return _ingestion_response(record)


@router.post(
    "/drafts/{draft_id}/abox/ingestions/{job_id}/retry",
    response_model=KnowledgeStudioIngestionJobResponse,
)
async def retry_knowledge_studio_ingestion_job(
    draft_id: UUID,
    job_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioIngestionJobResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_INGESTION_RETRY_V1",
            "draft_id": str(draft_id),
            "job_id": str(job_id),
            "expected_version": expected_version,
        }
    )
    record = await _ingestion_service(request, session).retry_ingestion_job(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        job_id=job_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_version_headers(response, record.version)
    response.headers["Cache-Control"] = "no-store"
    return _ingestion_response(record)


@router.get(
    "/drafts/{draft_id}/tbox/asset-releases",
    response_model=KnowledgeStudioAssetReleaseSourcePageResponse,
)
async def list_knowledge_studio_tbox_asset_releases(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=200)] = "",
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> KnowledgeStudioAssetReleaseSourcePageResponse:
    page = await _service(request, session).search_tbox_asset_release_sources(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        query=q,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return KnowledgeStudioAssetReleaseSourcePageResponse(
        items=[_asset_release_source_response(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/drafts/{draft_id}/tbox/catalog-sources",
    response_model=KnowledgeStudioSourcePageResponse,
)
async def list_knowledge_studio_tbox_catalog_sources(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=200)] = "",
    domain: Annotated[str | None, Query(max_length=1_000)] = None,
    search_fields: Annotated[str | None, Query(max_length=100)] = None,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> KnowledgeStudioSourcePageResponse:
    response.headers["Cache-Control"] = "no-store"
    page = await _service(request, session).search_tbox_catalog_sources(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        query=q,
        domain=domain,
        search_fields=search_fields,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioSourcePageResponse(
        items=[_source_response(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/drafts/{draft_id}/tbox/catalog-sources/{asset_id}",
    response_model=KnowledgeStudioSourceDetailResponse,
)
async def get_knowledge_studio_tbox_catalog_source(
    draft_id: UUID,
    asset_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioSourceDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    source = await _service(request, session).get_tbox_catalog_source(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioSourceDetailResponse(
        dataset=_source_response(source.dataset),
        observed_at=source.observed_at,
        stale_at=source.stale_at,
    )


@router.get(
    "/drafts/{draft_id}/abox/sources",
    response_model=KnowledgeStudioSourcePageResponse,
)
async def list_knowledge_studio_abox_sources(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=200)] = "",
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> KnowledgeStudioSourcePageResponse:
    response.headers["Cache-Control"] = "no-store"
    page = await _service(request, session).search_abox_sources(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        query=q,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioSourcePageResponse(
        items=[_source_response(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/drafts/{draft_id}/abox/sources/{asset_id}",
    response_model=KnowledgeStudioSourceDetailResponse,
)
async def get_knowledge_studio_abox_source(
    draft_id: UUID,
    asset_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioSourceDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    source = await _service(request, session).get_abox_source(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioSourceDetailResponse(
        dataset=_source_response(source.dataset),
        observed_at=source.observed_at,
        stale_at=source.stale_at,
    )


@router.patch(
    "/drafts/{draft_id}/abox/bindings/{target_stable_element_id}",
    response_model=KnowledgeStudioBindingMutationResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def patch_knowledge_studio_abox_binding(
    draft_id: UUID,
    target_stable_element_id: str,
    payload: KnowledgeStudioBindingRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioBindingMutationResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "target_stable_element_id": target_stable_element_id,
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    draft, binding = await _service(request, session).save_abox_binding(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        target_stable_element_id=target_stable_element_id,
        source_asset_id=payload.source_asset_id,
        source_version=payload.source_version,
        projection_source_version=payload.projection_source_version,
        rules=tuple(
            (
                rule.method,
                rule.source_field_path,
                rule.target_stable_element_id,
            )
            for rule in payload.rules
        ),
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, draft)
    return KnowledgeStudioBindingMutationResponse(
        draft=_draft_response(draft),
        binding=_binding_response(binding),
    )


@router.post(
    "/drafts/{draft_id}/abox/previews",
    response_model=KnowledgeStudioPreviewResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def preview_knowledge_studio_abox_binding(
    draft_id: UUID,
    payload: KnowledgeStudioPreviewRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
) -> KnowledgeStudioPreviewResponse:
    record = await _preview_service(request, session).preview_binding(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        target_stable_element_id=payload.target_stable_element_id,
        sample_limit=payload.sample_limit,
        expected_version=_expected_version(if_match),
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_version_headers(response, record.draft_version)
    return KnowledgeStudioPreviewResponse(
        status=record.status,
        draft_version=record.draft_version,
        binding_version=record.binding_version,
        target_stable_element_id=record.target_stable_element_id,
        dry_run=True,
        sample_size=record.sample_size,
        graph=KnowledgeStudioPreviewGraphResponse(
            nodes=[
                KnowledgeStudioPreviewNodeResponse(
                    id=item.node_id,
                    stable_element_id=item.stable_element_id,
                    type=item.type_name,
                    identity=item.identity,
                    properties=dict(item.properties),
                )
                for item in record.graph.nodes
            ],
            edges=[
                KnowledgeStudioPreviewEdgeResponse(
                    id=item.edge_id,
                    stable_element_id=item.stable_element_id,
                    type=item.type_name,
                    source_node_id=item.source_node_id,
                    target_node_id=item.target_node_id,
                    properties=dict(item.properties),
                )
                for item in record.graph.edges
            ],
        ),
        evidence=[_evidence_response(item) for item in record.evidence],
    )


@router.post(
    "/drafts/{draft_id}/abox/preflight",
    response_model=KnowledgeStudioPreflightResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def preflight_knowledge_studio_abox(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioPreflightResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _preview_service(request, session).preflight(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    if record.receipt_id is None or record.contract_hash is None:
        raise ValidationError("The durable pre-flight receipt is unavailable.")
    _set_version_headers(response, record.draft_version)
    return KnowledgeStudioPreflightResponse(
        status=record.status,
        valid=record.valid,
        draft_version=record.draft_version,
        checked_at=record.checked_at,
        receipt_id=record.receipt_id,
        contract_hash=record.contract_hash,
        evidence=[_evidence_response(item) for item in record.evidence],
    )
