from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from datariver.application.governance_document_blueprints import (
    BLUEPRINT_CATALOG_VERSION,
    governance_document_blueprints,
)
from datariver.application.services.authorization import (
    AuthorizationService,
    NullDecisionWriter,
)
from datariver.application.services.governance_documents import GovernanceDocumentService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import PreconditionFailedError
from datariver.domain.governance_documents import GovernanceDocumentCategory
from datariver.domain.governance_html import sanitize_governance_html
from datariver.domain.knowledge_pipeline import (
    EmbeddingBatch,
    ModelBinding,
    PageEmbedding,
    PdfPage,
)

NOW = datetime(2026, 7, 31, tzinfo=UTC)


class _Repository:
    def __init__(self, detail: object | None = None) -> None:
        self.detail = detail
        self.search_call: dict[str, object] | None = None

    async def database_now(self) -> datetime:
        return NOW

    async def get_document(self, **_: object) -> object | None:
        return self.detail

    async def search_knowledge(self, **values: object) -> tuple[Any, ...]:
        self.search_call = values
        return ()


class _Embedding:
    def __init__(self, binding: ModelBinding) -> None:
        self.binding = binding
        self.pages: tuple[object, ...] = ()

    async def embed_pages(
        self,
        *,
        pages: Sequence[PdfPage],
        binding: ModelBinding,
    ) -> EmbeddingBatch:
        self.pages = tuple(pages)
        assert binding == self.binding
        return EmbeddingBatch(
            binding=binding,
            embeddings=(PageEmbedding(page_number=1, vector=(0.25, -0.5, 0.75)),),
            input_tokens=3,
        )


class _AttachmentStore:
    called = False

    async def ensure_attachment(self, _: object) -> object:
        self.called = True
        raise AssertionError("Stale aggregate state must be rejected before Object Storage.")


def _subject(*actions: Action) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=uuid4(),
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset(actions),
    )


def _service(
    repository: _Repository,
    *,
    attachment_store: object | None = None,
    embedding: _Embedding | None = None,
    binding: ModelBinding | None = None,
) -> GovernanceDocumentService:
    return GovernanceDocumentService(
        repository=cast(Any, repository),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        attachment_store=cast(Any, attachment_store),
        artifact_storage_ready=attachment_store is not None,
        knowledge_projection_ready=embedding is not None,
        knowledge_embedding=embedding,
        knowledge_embedding_binding=binding,
    )


def test_controlled_blueprints_are_sanitized_and_cover_required_categories() -> None:
    values = governance_document_blueprints()

    assert {value.category for value in values} == {
        GovernanceDocumentCategory.POLICY,
        GovernanceDocumentCategory.STANDARD_TERMINOLOGY,
        GovernanceDocumentCategory.SECURITY_GUIDE,
    }
    assert len({value.blueprint_id for value in values}) == 3
    for value in values:
        assert value.blueprint_version == BLUEPRINT_CATALOG_VERSION
        sanitized = sanitize_governance_html(value.sanitized_html)
        assert sanitized.html == value.sanitized_html
        assert sanitized.content_sha256 == value.content_sha256
        assert sanitized.policy_sha256 == value.sanitizer_policy_sha256


@pytest.mark.asyncio
async def test_knowledge_search_embeds_query_with_projection_binding() -> None:
    binding = ModelBinding(
        provider="approved-provider",
        model="embedding-model-v1",
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
    )
    embedding = _Embedding(binding)
    repository = _Repository()
    subject = _subject(Action.GOVERNANCE_KNOWLEDGE_READ)

    values, context = await _service(
        repository,
        embedding=embedding,
        binding=binding,
    ).search_knowledge(
        subject=subject,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="knowledge-search",
        query="접근 통제 정책",
        limit=8,
    )

    assert values == ()
    assert context.observed_at == NOW
    assert len(embedding.pages) == 1
    assert repository.search_call == {
        "workspace_id": subject.workspace_id,
        "subject": subject,
        "query": "접근 통제 정책",
        "query_vector": (0.25, -0.5, 0.75),
        "provider": "approved-provider",
        "model": "embedding-model-v1",
        "limit": 8,
    }


@pytest.mark.asyncio
async def test_stale_attachment_etag_is_rejected_before_object_write() -> None:
    document_id = uuid4()
    version_id = uuid4()
    subject = _subject(Action.GOVERNANCE_DOCUMENT_EDIT)
    detail = SimpleNamespace(
        document=SimpleNamespace(
            document_id=document_id,
            workspace_id=subject.workspace_id,
            kind=SimpleNamespace(value="DOCUMENT"),
            classification=Classification.INTERNAL,
            state=SimpleNamespace(value="DRAFT"),
            version=4,
        ),
        versions=(SimpleNamespace(version_id=version_id),),
    )
    repository = _Repository(detail)
    store = _AttachmentStore()

    with pytest.raises(PreconditionFailedError):
        await _service(repository, attachment_store=store).add_attachment(
            document_id=document_id,
            document_version_id=version_id,
            subject=subject,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="attachment",
            expected_version=3,
            idempotency_key="attachment-key",
            original_name="evidence.pdf",
            content_type="application/pdf",
            content=b"immutable evidence",
        )

    assert store.called is False
