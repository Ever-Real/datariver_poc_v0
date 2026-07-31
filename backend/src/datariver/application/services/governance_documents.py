from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import PurePath
from uuid import UUID

from datariver.application.catalog_security import catalog_permission_scope_hash
from datariver.application.errors import ExternalDependencyError
from datariver.application.governance_document_attachments import (
    GovernanceDocumentAttachmentDownload,
    GovernanceDocumentAttachmentStore,
    GovernanceDocumentAttachmentWrite,
)
from datariver.application.governance_document_blueprints import (
    governance_document_blueprints,
)
from datariver.application.governance_document_formats import (
    PreparedGovernanceDocumentContent,
)
from datariver.application.governance_document_ports import GovernanceDocumentRepository
from datariver.application.knowledge_pipeline_ports import KnowledgeEmbeddingProvider
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    BuiltinPolicyEngine,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.governance_documents import (
    GovernanceDocumentAttachment,
    GovernanceDocumentBlueprint,
    GovernanceDocumentCapability,
    GovernanceDocumentCapabilityAxis,
    GovernanceDocumentCategory,
    GovernanceDocumentDetail,
    GovernanceDocumentKind,
    GovernanceDocumentPage,
    GovernanceDocumentReviewDecision,
    GovernanceDocumentState,
    GovernanceDocumentSummary,
    GovernanceDocumentVersion,
    GovernanceKnowledgeEvidence,
    governance_document_request_hash,
    normalized_bounded_text,
    validate_document_identity,
)
from datariver.domain.knowledge_pipeline import ModelBinding, PdfPage

_AUTHORIZATION_LEASE_SECONDS = 30


@dataclass(frozen=True, slots=True)
class GovernanceDocumentReadContext:
    cache_scope: str
    observed_at: datetime
    authorization_valid_until: datetime


class GovernanceDocumentService:
    def __init__(
        self,
        *,
        repository: GovernanceDocumentRepository,
        authorization: AuthorizationService,
        attachment_store: GovernanceDocumentAttachmentStore | None,
        artifact_storage_ready: bool,
        knowledge_projection_ready: bool,
        knowledge_embedding: KnowledgeEmbeddingProvider | None = None,
        knowledge_embedding_binding: ModelBinding | None = None,
        attachment_download_ttl_seconds: int = 300,
    ) -> None:
        if not 60 <= attachment_download_ttl_seconds <= 900:
            raise ValueError("Governance document attachment download TTL is invalid.")
        self._repository = repository
        self._authorization = authorization
        self._attachment_store = attachment_store
        self._artifact_storage_ready = artifact_storage_ready
        self._knowledge_projection_ready = knowledge_projection_ready
        self._knowledge_embedding = knowledge_embedding
        self._knowledge_embedding_binding = knowledge_embedding_binding
        self._attachment_download_ttl_seconds = attachment_download_ttl_seconds
        self._engine = BuiltinPolicyEngine()

    async def capability(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
    ) -> GovernanceDocumentCapability:
        self._require_human(subject)
        context = await self._read_context(subject)
        document_resource = self._workspace_resource(subject, kind=GovernanceDocumentKind.DOCUMENT)
        template_resource = self._workspace_resource(subject, kind=GovernanceDocumentKind.TEMPLATE)

        def allowed(action: Action, *, template: bool = False) -> bool:
            return self._authorization.is_entitled(
                subject=subject,
                resource=template_resource if template else document_resource,
                action=action,
                environment=environment,
            )

        read_allowed = allowed(Action.GOVERNANCE_DOCUMENT_READ)
        create_allowed = allowed(Action.GOVERNANCE_DOCUMENT_CREATE)
        edit_allowed = allowed(Action.GOVERNANCE_DOCUMENT_EDIT)
        review_allowed = allowed(Action.GOVERNANCE_DOCUMENT_REVIEW)
        publish_allowed = allowed(Action.GOVERNANCE_DOCUMENT_PUBLISH)
        archive_allowed = allowed(Action.GOVERNANCE_DOCUMENT_ARCHIVE)
        template_manage_allowed = all(
            (
                allowed(Action.GOVERNANCE_TEMPLATE_PROPOSE, template=True),
                allowed(Action.GOVERNANCE_TEMPLATE_REVIEW, template=True),
                allowed(Action.GOVERNANCE_TEMPLATE_ACTIVATE, template=True),
            )
        )
        return GovernanceDocumentCapability(
            observed_at=context.observed_at,
            valid_until=context.authorization_valid_until,
            cache_scope=context.cache_scope,
            axes=(
                _permission_axis("read", read_allowed, "GOVERNANCE_DOCUMENT_READ_DENIED"),
                _permission_axis("create", create_allowed, "GOVERNANCE_DOCUMENT_CREATE_DENIED"),
                _permission_axis("edit", edit_allowed, "GOVERNANCE_DOCUMENT_EDIT_DENIED"),
                _permission_axis("review", review_allowed, "GOVERNANCE_DOCUMENT_REVIEW_DENIED"),
                _permission_axis(
                    "publish",
                    publish_allowed,
                    "GOVERNANCE_DOCUMENT_PUBLISH_DENIED",
                ),
                _permission_axis(
                    "archive",
                    archive_allowed,
                    "GOVERNANCE_DOCUMENT_ARCHIVE_DENIED",
                ),
                _permission_axis(
                    "template_manage",
                    template_manage_allowed,
                    "GOVERNANCE_TEMPLATE_MANAGE_DENIED",
                ),
                _dependency_axis(
                    "artifact_storage",
                    allowed=edit_allowed,
                    ready=self._artifact_storage_ready,
                    denied_code="GOVERNANCE_DOCUMENT_EDIT_DENIED",
                    unavailable_code="GOVERNANCE_ARTIFACT_STORAGE_UNAVAILABLE",
                ),
                _dependency_axis(
                    "knowledge_projection",
                    allowed=read_allowed,
                    ready=self._knowledge_projection_ready,
                    denied_code="GOVERNANCE_DOCUMENT_READ_DENIED",
                    unavailable_code="GOVERNANCE_KNOWLEDGE_PROJECTION_UNAVAILABLE",
                ),
            ),
        )

    async def list_documents(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        kind: GovernanceDocumentKind | None,
        category: GovernanceDocumentCategory | None,
        include_archived: bool,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[GovernanceDocumentPage, GovernanceDocumentReadContext]:
        self._require_human(subject)
        await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=(
                Action.GOVERNANCE_TEMPLATE_READ
                if kind is GovernanceDocumentKind.TEMPLATE
                else Action.GOVERNANCE_DOCUMENT_READ
            ),
            resource=self._workspace_resource(
                subject,
                kind=kind or GovernanceDocumentKind.DOCUMENT,
            ),
        )
        page = await self._repository.list_documents(
            workspace_id=subject.workspace_id,
            subject=subject,
            kind=kind,
            category=category,
            include_archived=include_archived,
            query=query,
            limit=limit,
            cursor=cursor,
        )
        items = tuple(
            replace(
                item,
                allowed_actions=self._allowed_actions(
                    subject=subject,
                    environment=environment,
                    item=item,
                ),
            )
            for item in page.items
        )
        return (
            GovernanceDocumentPage(items=items, next_cursor=page.next_cursor),
            await self._read_context(subject),
        )

    async def template_blueprints(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[GovernanceDocumentBlueprint, ...]:
        self._require_human(subject)
        await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.GOVERNANCE_TEMPLATE_PROPOSE,
            resource=self._workspace_resource(subject, kind=GovernanceDocumentKind.TEMPLATE),
        )
        return governance_document_blueprints()

    async def get_document(
        self,
        *,
        document_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[GovernanceDocumentDetail, GovernanceDocumentReadContext]:
        self._require_human(subject)
        detail = await self._repository.get_document(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            subject=subject,
        )
        if detail is None:
            raise NotFoundError("The Governance Document is unavailable.")
        await self._authorize_read_detail(
            detail=detail,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return self._with_allowed_actions(detail, subject, environment), await self._read_context(
            subject
        )

    async def create_document(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        kind: GovernanceDocumentKind,
        category: GovernanceDocumentCategory,
        title: str,
        summary: str,
        classification: Classification,
        applicability_scope: str,
        content: PreparedGovernanceDocumentContent,
        source_template_version_id: UUID | None,
    ) -> GovernanceDocumentDetail:
        self._require_human(subject)
        title, summary = validate_document_identity(
            kind=kind,
            category=category,
            title=title,
            summary=summary,
            classification=classification,
        )
        applicability_scope = self._scope(applicability_scope)
        decision = await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=self._create_action(kind),
            resource=self._workspace_resource(subject, kind=kind),
        )
        request_document: dict[str, object] = {
            "kind": kind.value,
            "category": category.value,
            "title": title,
            "summary": summary,
            "classification": int(classification),
            "applicability_scope": applicability_scope,
            "content_sha256": content.content_sha256,
            "source_format": content.source_format.value,
            "source_template_version_id": (
                str(source_template_version_id) if source_template_version_id else None
            ),
        }
        detail = await self._repository.create_document(
            workspace_id=subject.workspace_id,
            actor_id=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=governance_document_request_hash(
                contract="GOVERNANCE_DOCUMENT_CREATE_V1",
                workspace_id=subject.workspace_id,
                actor_id=subject.subject_id,
                document=request_document,
            ),
            kind=kind,
            category=category,
            title=title,
            summary=summary,
            classification=int(classification),
            applicability_scope=applicability_scope,
            sanitized_html=content.sanitized_html,
            plain_text=content.plain_text,
            content_sha256=content.content_sha256,
            sanitizer_policy_version=content.sanitizer_policy_version,
            sanitizer_policy_sha256=content.sanitizer_policy_sha256,
            source_format=content.source_format,
            source_template_version_id=source_template_version_id,
            policy_decision_id=decision.decision_id,
            request_id=request_id,
        )
        return self._with_allowed_actions(detail, subject, environment)

    async def published_template_content(
        self,
        *,
        version_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> PreparedGovernanceDocumentContent:
        self._require_human(subject)
        value = await self._repository.get_published_template_version(
            workspace_id=subject.workspace_id,
            version_id=version_id,
            subject=subject,
        )
        if value is None:
            raise NotFoundError("The Governance Document template version is unavailable.")
        template_detail = await self._required_detail(
            document_id=value.document_id,
            subject=subject,
        )
        await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.GOVERNANCE_TEMPLATE_READ,
            resource=self._resource(template_detail.document),
        )
        return PreparedGovernanceDocumentContent(
            source_format=value.source_format,
            sanitized_html=value.sanitized_html,
            plain_text=value.plain_text,
            content_sha256=value.content_sha256,
            sanitizer_policy_version=value.sanitizer_policy_version,
            sanitizer_policy_sha256=value.sanitizer_policy_sha256,
        )

    async def create_version(
        self,
        *,
        document_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        expected_version: int,
        idempotency_key: str,
        title: str,
        summary: str | None,
        applicability_scope: str,
        content: PreparedGovernanceDocumentContent,
        source_template_version_id: UUID | None,
    ) -> GovernanceDocumentDetail:
        detail = await self._required_detail(document_id=document_id, subject=subject)
        title, normalized_summary = validate_document_identity(
            kind=detail.document.kind,
            category=detail.document.category,
            title=title,
            summary=detail.document.summary if summary is None else summary,
            classification=detail.document.classification,
        )
        applicability_scope = self._scope(applicability_scope)
        decision = await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=self._edit_action(detail.document.kind),
            resource=self._resource(detail.document),
        )
        request_document: dict[str, object] = {
            "document_id": str(document_id),
            "expected_version": expected_version,
            "title": title,
            "summary": normalized_summary,
            "applicability_scope": applicability_scope,
            "content_sha256": content.content_sha256,
            "source_format": content.source_format.value,
            "source_template_version_id": (
                str(source_template_version_id) if source_template_version_id else None
            ),
        }
        value = await self._repository.create_version(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=governance_document_request_hash(
                contract="GOVERNANCE_DOCUMENT_VERSION_CREATE_V1",
                workspace_id=subject.workspace_id,
                actor_id=subject.subject_id,
                document=request_document,
            ),
            title=title,
            summary=normalized_summary,
            applicability_scope=applicability_scope,
            sanitized_html=content.sanitized_html,
            plain_text=content.plain_text,
            content_sha256=content.content_sha256,
            sanitizer_policy_version=content.sanitizer_policy_version,
            sanitizer_policy_sha256=content.sanitizer_policy_sha256,
            source_format=content.source_format,
            source_template_version_id=source_template_version_id,
            policy_decision_id=decision.decision_id,
            request_id=request_id,
        )
        return self._with_allowed_actions(value, subject, environment)

    async def submit_version(
        self,
        *,
        document_id: UUID,
        document_version_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> GovernanceDocumentDetail:
        detail = await self._required_detail(document_id=document_id, subject=subject)
        candidate = self._required_version(detail, document_version_id)
        decision = await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=self._edit_action(detail.document.kind),
            resource=self._resource(detail.document, requester_id=candidate.author_id),
        )
        value = await self._repository.submit_version(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            document_version_id=document_version_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=self._command_hash(
                "GOVERNANCE_DOCUMENT_SUBMIT_V1",
                subject,
                document_id,
                document_version_id,
                expected_version,
            ),
            policy_decision_id=decision.decision_id,
            request_id=request_id,
        )
        return self._with_allowed_actions(value, subject, environment)

    async def review_version(
        self,
        *,
        document_id: UUID,
        document_version_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        expected_version: int,
        idempotency_key: str,
        decision: GovernanceDocumentReviewDecision,
        reason: str,
    ) -> GovernanceDocumentDetail:
        detail = await self._required_detail(document_id=document_id, subject=subject)
        candidate = self._required_version(detail, document_version_id)
        reason = normalized_bounded_text(
            reason,
            label="review reason",
            maximum_characters=2_000,
        )
        resource = self._resource(detail.document, requester_id=candidate.author_id)
        review_decision = await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=self._review_action(detail.document.kind),
            resource=resource,
        )
        if decision is GovernanceDocumentReviewDecision.APPROVE:
            await self._authorize(
                subject=subject,
                environment=environment,
                request_id=request_id,
                action=self._publish_action(detail.document.kind),
                resource=resource,
            )
        value = await self._repository.review_version(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            document_version_id=document_version_id,
            reviewer_id=subject.subject_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=governance_document_request_hash(
                contract="GOVERNANCE_DOCUMENT_REVIEW_V1",
                workspace_id=subject.workspace_id,
                actor_id=subject.subject_id,
                document={
                    "document_id": str(document_id),
                    "document_version_id": str(document_version_id),
                    "expected_version": expected_version,
                    "decision": decision.value,
                    "reason_hash": canonical_json_hash({"reason": reason}),
                },
            ),
            decision=decision,
            reason=reason,
            policy_decision_id=review_decision.decision_id,
            authentication_assurance=subject.authentication_assurance.value,
            request_id=request_id,
        )
        return self._with_allowed_actions(value, subject, environment)

    async def archive_document(
        self,
        *,
        document_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        expected_version: int,
        idempotency_key: str,
        reason: str,
    ) -> GovernanceDocumentDetail:
        detail = await self._required_detail(document_id=document_id, subject=subject)
        reason = normalized_bounded_text(
            reason,
            label="archive reason",
            maximum_characters=2_000,
        )
        decision = await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=self._archive_action(detail.document.kind),
            resource=self._resource(detail.document),
        )
        value = await self._repository.archive_document(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=governance_document_request_hash(
                contract="GOVERNANCE_DOCUMENT_ARCHIVE_V1",
                workspace_id=subject.workspace_id,
                actor_id=subject.subject_id,
                document={
                    "document_id": str(document_id),
                    "expected_version": expected_version,
                    "reason_hash": canonical_json_hash({"reason": reason}),
                },
            ),
            reason=reason,
            policy_decision_id=decision.decision_id,
            request_id=request_id,
        )
        return self._with_allowed_actions(value, subject, environment)

    async def add_attachment(
        self,
        *,
        document_id: UUID,
        document_version_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        expected_version: int,
        idempotency_key: str,
        original_name: str,
        content_type: str,
        content: bytes,
    ) -> GovernanceDocumentAttachment:
        detail = await self._required_detail(document_id=document_id, subject=subject)
        self._required_version(detail, document_version_id)
        if detail.document.version != expected_version:
            raise PreconditionFailedError("The Governance Document version has changed.")
        if self._attachment_store is None:
            raise ExternalDependencyError(
                "Governance Document attachment storage is unavailable.",
                dependency="governance_document_attachment_store",
                retryable=False,
            )
        safe_name = self._attachment_name(original_name)
        safe_content_type = self._attachment_content_type(content_type)
        request_document: dict[str, object] = {
            "document_id": str(document_id),
            "document_version_id": str(document_version_id),
            "expected_version": expected_version,
            "original_name": safe_name,
            "content_type": safe_content_type,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        request_hash = governance_document_request_hash(
            contract="GOVERNANCE_DOCUMENT_ATTACHMENT_ADD_V1",
            workspace_id=subject.workspace_id,
            actor_id=subject.subject_id,
            document=request_document,
        )
        attachment_id = self._attachment_id(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            version_id=document_version_id,
            actor_id=subject.subject_id,
            idempotency_key=idempotency_key,
        )
        decision = await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=self._edit_action(detail.document.kind),
            resource=self._resource(detail.document),
        )
        receipt = await self._attachment_store.ensure_attachment(
            GovernanceDocumentAttachmentWrite(
                workspace_id=subject.workspace_id,
                document_id=document_id,
                version_id=document_version_id,
                attachment_id=attachment_id,
                classification=detail.document.classification.name,
                content=content,
            )
        )
        return await self._repository.add_attachment(
            attachment_id=attachment_id,
            workspace_id=subject.workspace_id,
            document_id=document_id,
            document_version_id=document_version_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            original_name=safe_name,
            content_type=safe_content_type,
            content_sha256=receipt.content_sha256,
            size_bytes=receipt.size_bytes,
            bucket=receipt.bucket,
            object_key=receipt.object_key,
            provider_version_id=receipt.provider_version_id,
            etag=receipt.etag,
            policy_decision_id=decision.decision_id,
            request_id=request_id,
        )

    async def search_knowledge(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        query: str,
        limit: int,
    ) -> tuple[tuple[GovernanceKnowledgeEvidence, ...], GovernanceDocumentReadContext]:
        self._require_human(subject)
        await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.GOVERNANCE_KNOWLEDGE_READ,
            resource=self._workspace_resource(subject, kind=GovernanceDocumentKind.DOCUMENT),
        )
        if self._knowledge_embedding is None or self._knowledge_embedding_binding is None:
            raise ExternalDependencyError(
                "Governance Document vector search is unavailable.",
                dependency="governance_document_embedding",
                retryable=False,
            )
        page = PdfPage.create(page_number=1, text=query)
        batch = await self._knowledge_embedding.embed_pages(
            pages=(page,),
            binding=self._knowledge_embedding_binding,
        )
        if batch.binding != self._knowledge_embedding_binding or len(batch.embeddings) != 1:
            raise ExternalDependencyError(
                "Governance Document query embedding binding has drifted.",
                dependency="governance_document_embedding",
                retryable=False,
            )
        embedding = batch.embeddings[0]
        if embedding.page_number != 1:
            raise ExternalDependencyError(
                "Governance Document query embedding is incomplete.",
                dependency="governance_document_embedding",
                retryable=False,
            )
        embedding.validate(dimensions=len(embedding.vector))
        values = await self._repository.search_knowledge(
            workspace_id=subject.workspace_id,
            subject=subject,
            query=query,
            query_vector=embedding.vector,
            provider=self._knowledge_embedding_binding.provider,
            model=self._knowledge_embedding_binding.model,
            limit=limit,
        )
        return values, await self._read_context(subject)

    async def download_attachment(
        self,
        *,
        document_id: UUID,
        attachment_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> GovernanceDocumentAttachmentDownload:
        self._require_human(subject)
        detail = await self._required_detail(document_id=document_id, subject=subject)
        await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.ATTACHMENT_DOWNLOAD,
            resource=self._resource(detail.document),
        )
        if self._attachment_store is None:
            raise ExternalDependencyError(
                "Governance Document attachment storage is unavailable.",
                dependency="governance_document_attachment_store",
                retryable=False,
            )
        source = await self._repository.get_attachment_source(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            attachment_id=attachment_id,
            subject=subject,
        )
        if source is None:
            raise NotFoundError("The Governance Document attachment is unavailable.")
        url = await self._attachment_store.presign_download(
            source,
            expires_seconds=self._attachment_download_ttl_seconds,
        )
        observed_at = await self._repository.database_now()
        return GovernanceDocumentAttachmentDownload(
            attachment=source.attachment,
            url=url,
            expires_at_epoch_seconds=(
                int(observed_at.timestamp()) + self._attachment_download_ttl_seconds
            ),
        )

    async def get_current_knowledge(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        chunk_ids: tuple[UUID, ...],
    ) -> tuple[GovernanceKnowledgeEvidence, ...]:
        self._require_human(subject)
        await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.GOVERNANCE_KNOWLEDGE_READ,
            resource=self._workspace_resource(subject, kind=GovernanceDocumentKind.DOCUMENT),
        )
        return await self._repository.get_current_knowledge(
            workspace_id=subject.workspace_id,
            subject=subject,
            chunk_ids=chunk_ids,
        )

    async def _required_detail(
        self,
        *,
        document_id: UUID,
        subject: SubjectAttributes,
    ) -> GovernanceDocumentDetail:
        self._require_human(subject)
        value = await self._repository.get_document(
            workspace_id=subject.workspace_id,
            document_id=document_id,
            subject=subject,
        )
        if value is None:
            raise NotFoundError("The Governance Document is unavailable.")
        return value

    async def _authorize_read_detail(
        self,
        *,
        detail: GovernanceDocumentDetail,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorize(
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=self._read_action(
                detail.document.kind,
                state=detail.document.state,
            ),
            resource=self._resource(detail.document),
        )

    async def _authorize(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        action: Action,
        resource: ResourceAttributes,
    ) -> Decision:
        return await self._authorization.authorize(
            subject=subject,
            resource=resource,
            action=action,
            environment=environment,
            request_id=request_id,
        )

    async def _read_context(self, subject: SubjectAttributes) -> GovernanceDocumentReadContext:
        observed_at = await self._repository.database_now()
        valid_until = observed_at + timedelta(seconds=_AUTHORIZATION_LEASE_SECONDS)
        return GovernanceDocumentReadContext(
            cache_scope=canonical_json_hash(
                {
                    "contract": "GOVERNANCE_DOCUMENT_READ_SCOPE_V1",
                    "workspace_id": str(subject.workspace_id),
                    "subject_id": str(subject.subject_id),
                    "permission_scope_hash": catalog_permission_scope_hash(subject),
                }
            ),
            observed_at=observed_at,
            authorization_valid_until=valid_until,
        )

    def _allowed_actions(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        item: GovernanceDocumentSummary,
    ) -> tuple[str, ...]:
        resource = self._resource(item)

        def allowed(action: Action) -> bool:
            return self._authorization.is_entitled(
                subject=subject,
                resource=resource,
                action=action,
                environment=environment,
            )

        actions: list[str] = []
        if allowed(self._read_action(item.kind, state=item.state)):
            actions.append("read")
        if allowed(Action.ATTACHMENT_DOWNLOAD):
            actions.append("download_attachment")
        if item.state is not GovernanceDocumentState.ARCHIVED and allowed(
            self._edit_action(item.kind)
        ):
            actions.extend(("create_version", "submit", "add_attachment"))
        if allowed(self._review_action(item.kind)):
            actions.append("review")
        if allowed(self._publish_action(item.kind)):
            actions.append("publish")
        if item.state is not GovernanceDocumentState.ARCHIVED and allowed(
            self._archive_action(item.kind)
        ):
            actions.append("archive")
        if item.kind is GovernanceDocumentKind.TEMPLATE and allowed(
            Action.GOVERNANCE_DOCUMENT_CREATE
        ):
            actions.append("instantiate_template")
        return tuple(actions)

    def _with_allowed_actions(
        self,
        detail: GovernanceDocumentDetail,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
    ) -> GovernanceDocumentDetail:
        return replace(
            detail,
            document=replace(
                detail.document,
                allowed_actions=self._allowed_actions(
                    subject=subject,
                    environment=environment,
                    item=detail.document,
                ),
            ),
        )

    @staticmethod
    def _required_version(
        detail: GovernanceDocumentDetail,
        version_id: UUID,
    ) -> GovernanceDocumentVersion:
        for value in detail.versions:
            if value.version_id == version_id:
                return value
        raise NotFoundError("The Governance Document version is unavailable.")

    @staticmethod
    def _scope(value: str) -> str:
        return normalized_bounded_text(
            value,
            label="applicability scope",
            maximum_characters=4_000,
            allow_empty=True,
        )

    @staticmethod
    def _command_hash(
        contract: str,
        subject: SubjectAttributes,
        document_id: UUID,
        version_id: UUID,
        expected_version: int,
    ) -> str:
        return governance_document_request_hash(
            contract=contract,
            workspace_id=subject.workspace_id,
            actor_id=subject.subject_id,
            document={
                "document_id": str(document_id),
                "document_version_id": str(version_id),
                "expected_version": expected_version,
            },
        )

    @staticmethod
    def _attachment_id(
        *,
        workspace_id: UUID,
        document_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> UUID:
        digest = bytearray(
            hashlib.sha256(
                (
                    "governance-document-attachment-v1:"
                    f"{workspace_id}:{document_id}:{version_id}:{actor_id}:{idempotency_key}"
                ).encode()
            ).digest()[:16]
        )
        digest[6] = (digest[6] & 0x0F) | 0x50
        digest[8] = (digest[8] & 0x3F) | 0x80
        return UUID(bytes=bytes(digest))

    @staticmethod
    def _attachment_name(value: str) -> str:
        normalized = PurePath(value.replace("\\", "/")).name.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or len(normalized) > 255
            or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
        ):
            raise ValidationError("The Governance Document attachment filename is invalid.")
        return normalized

    @staticmethod
    def _attachment_content_type(value: str) -> str:
        normalized = value.split(";", 1)[0].strip().lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}", normalized):
            return normalized
        return "application/octet-stream"

    @staticmethod
    def _resource(
        item: GovernanceDocumentSummary,
        *,
        requester_id: UUID | None = None,
    ) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=item.document_id,
            workspace_id=item.workspace_id,
            resource_type=(
                "GOVERNANCE_TEMPLATE"
                if item.kind is GovernanceDocumentKind.TEMPLATE
                else "GOVERNANCE_DOCUMENT"
            ),
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=item.classification,
            lifecycle=item.state.value,
            requester_id=requester_id,
        )

    @staticmethod
    def _workspace_resource(
        subject: SubjectAttributes,
        *,
        kind: GovernanceDocumentKind,
    ) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=subject.workspace_id,
            workspace_id=subject.workspace_id,
            resource_type=(
                "GOVERNANCE_TEMPLATE_LIBRARY"
                if kind is GovernanceDocumentKind.TEMPLATE
                else "GOVERNANCE_DOCUMENT_LIBRARY"
            ),
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.PUBLIC,
            lifecycle="ACTIVE",
        )

    @staticmethod
    def _require_human(subject: SubjectAttributes) -> None:
        if subject.job_function == "SERVICE_ACCOUNT" or "service-accounts" in subject.groups:
            raise ForbiddenError("Public Governance Document APIs require a human identity.")

    @staticmethod
    def _read_action(
        kind: GovernanceDocumentKind,
        *,
        state: GovernanceDocumentState | None = None,
    ) -> Action:
        if kind is GovernanceDocumentKind.DOCUMENT and state is GovernanceDocumentState.ARCHIVED:
            return Action.GOVERNANCE_DOCUMENT_HISTORY_READ
        return (
            Action.GOVERNANCE_TEMPLATE_READ
            if kind is GovernanceDocumentKind.TEMPLATE
            else Action.GOVERNANCE_DOCUMENT_READ
        )

    @staticmethod
    def _create_action(kind: GovernanceDocumentKind) -> Action:
        return (
            Action.GOVERNANCE_TEMPLATE_PROPOSE
            if kind is GovernanceDocumentKind.TEMPLATE
            else Action.GOVERNANCE_DOCUMENT_CREATE
        )

    @staticmethod
    def _edit_action(kind: GovernanceDocumentKind) -> Action:
        return (
            Action.GOVERNANCE_TEMPLATE_PROPOSE
            if kind is GovernanceDocumentKind.TEMPLATE
            else Action.GOVERNANCE_DOCUMENT_EDIT
        )

    @staticmethod
    def _review_action(kind: GovernanceDocumentKind) -> Action:
        return (
            Action.GOVERNANCE_TEMPLATE_REVIEW
            if kind is GovernanceDocumentKind.TEMPLATE
            else Action.GOVERNANCE_DOCUMENT_REVIEW
        )

    @staticmethod
    def _publish_action(kind: GovernanceDocumentKind) -> Action:
        return (
            Action.GOVERNANCE_TEMPLATE_ACTIVATE
            if kind is GovernanceDocumentKind.TEMPLATE
            else Action.GOVERNANCE_DOCUMENT_PUBLISH
        )

    @staticmethod
    def _archive_action(kind: GovernanceDocumentKind) -> Action:
        return (
            Action.GOVERNANCE_TEMPLATE_ARCHIVE
            if kind is GovernanceDocumentKind.TEMPLATE
            else Action.GOVERNANCE_DOCUMENT_ARCHIVE
        )


def _permission_axis(
    axis_id: str,
    allowed: bool,
    denied_code: str,
) -> GovernanceDocumentCapabilityAxis:
    return GovernanceDocumentCapabilityAxis(
        id=axis_id,
        state="AVAILABLE" if allowed else "DENIED",
        reason_code=None if allowed else denied_code,
    )


def _dependency_axis(
    axis_id: str,
    *,
    allowed: bool,
    ready: bool,
    denied_code: str,
    unavailable_code: str,
) -> GovernanceDocumentCapabilityAxis:
    if not allowed:
        return GovernanceDocumentCapabilityAxis(
            id=axis_id,
            state="DENIED",
            reason_code=denied_code,
        )
    return GovernanceDocumentCapabilityAxis(
        id=axis_id,
        state="AVAILABLE" if ready else "UNAVAILABLE",
        reason_code=None if ready else unavailable_code,
    )
