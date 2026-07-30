from __future__ import annotations

import json
import re
from collections.abc import Sequence

from datariver.application.errors import ExternalDependencyError
from datariver.application.governance_document_artifacts import (
    GovernanceDocumentArtifactStore,
    GovernanceDocumentArtifactWrite,
)
from datariver.application.governance_document_ports import (
    GovernanceDocumentGraphProjector,
    GovernanceDocumentProjectionRepository,
)
from datariver.application.knowledge_pipeline_ports import KnowledgeEmbeddingProvider
from datariver.domain.common import ConflictError, DomainError
from datariver.domain.governance_documents import (
    MAXIMUM_KNOWLEDGE_CHUNK_CHARACTERS,
    MAXIMUM_KNOWLEDGE_CHUNKS,
    GovernanceDocumentArtifactState,
    GovernanceDocumentProjectionClaim,
    GovernanceDocumentVersionState,
)
from datariver.domain.knowledge_pipeline import ModelBinding, PdfPage


class GovernanceDocumentProjectionService:
    def __init__(
        self,
        *,
        repository: GovernanceDocumentProjectionRepository,
        artifact_store: GovernanceDocumentArtifactStore,
        embedding: KnowledgeEmbeddingProvider,
        embedding_binding: ModelBinding,
        graph: GovernanceDocumentGraphProjector,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._embedding = embedding
        self._embedding_binding = embedding_binding
        self._graph = graph
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        claim = await self._repository.claim_next_projection(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return False
        try:
            if claim.version.artifact_state is not GovernanceDocumentArtifactState.STORED:
                await self._store_artifact(claim)
                return True
            if claim.version.state is not GovernanceDocumentVersionState.PUBLISHED:
                raise ConflictError(
                    "Only a published Governance Document version may be projected."
                )
            await self._project_knowledge(claim)
            return True
        except Exception as error:
            await self._repository.fail_projection(
                version=claim.version,
                failure_code=_failure_code(error),
                retryable=_retryable(error),
            )
            return True

    async def _store_artifact(self, claim: GovernanceDocumentProjectionClaim) -> None:
        version = claim.version
        manifest = json.dumps(
            {
                "contract": "GOVERNANCE_DOCUMENT_ARTIFACT_MANIFEST_V1",
                "workspace_id": str(version.workspace_id),
                "document_id": str(version.document_id),
                "document_version_id": str(version.version_id),
                "version_number": version.version_number,
                "version_tag": version.version_tag,
                "kind": claim.kind.value,
                "category": claim.category.value,
                "classification": claim.classification.name,
                "content_sha256": version.content_sha256,
                "size_bytes": version.size_bytes,
                "sanitizer_policy_version": version.sanitizer_policy_version,
                "sanitizer_policy_sha256": version.sanitizer_policy_sha256,
                "source_format": version.source_format.value,
                "source_template_version_id": (
                    str(version.source_template_version_id)
                    if version.source_template_version_id is not None
                    else None
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        receipt = await self._artifact_store.ensure_version_artifacts(
            GovernanceDocumentArtifactWrite(
                workspace_id=version.workspace_id,
                document_id=version.document_id,
                version_id=version.version_id,
                version_number=version.version_number,
                version_tag=version.version_tag,
                sanitizer_policy_version=version.sanitizer_policy_version,
                sanitizer_policy_sha256=version.sanitizer_policy_sha256,
                classification=claim.classification.name,
                content_html=version.sanitized_html.encode(),
                manifest_json=manifest,
            )
        )
        if receipt.content.content_sha256 != version.content_sha256:
            raise ConflictError("The Governance Document artifact receipt content has drifted.")
        await self._repository.store_artifact_receipt(
            version=version,
            bucket=receipt.content.bucket,
            content_key=receipt.content.object_key,
            content_version_id=receipt.content.provider_version_id,
            content_etag=receipt.content.etag,
            manifest_key=receipt.manifest.object_key,
            manifest_version_id=receipt.manifest.provider_version_id,
            manifest_etag=receipt.manifest.etag,
            manifest_sha256=receipt.manifest.content_sha256,
        )

    async def _project_knowledge(self, claim: GovernanceDocumentProjectionClaim) -> None:
        chunks = _chunks(claim.version.plain_text)
        pages = tuple(
            PdfPage.create(page_number=ordinal, text=content)
            for ordinal, content in enumerate(chunks, start=1)
        )
        batch = await self._embedding.embed_pages(
            pages=pages,
            binding=self._embedding_binding,
        )
        if batch.binding != self._embedding_binding or len(batch.embeddings) != len(pages):
            raise ConflictError("The Governance Document embedding binding has drifted.")
        vectors = {value.page_number: value.vector for value in batch.embeddings}
        if set(vectors) != set(range(1, len(pages) + 1)):
            raise ConflictError("The Governance Document embedding output is incomplete.")
        dimensions: int | None = None
        projected: list[tuple[int, str, str, Sequence[float]]] = []
        graph_chunks: list[tuple[int, str, str]] = []
        for page in pages:
            vector = vectors[page.page_number]
            dimensions = len(vector) if dimensions is None else dimensions
            for embedding in batch.embeddings:
                if embedding.page_number == page.page_number:
                    embedding.validate(dimensions=dimensions)
                    break
            projected.append((page.page_number, page.text, page.content_sha256, vector))
            graph_chunks.append((page.page_number, page.text, page.content_sha256))
        graph_hash = await self._graph.replace_version(
            claim=claim,
            chunks=graph_chunks,
        )
        await self._repository.store_projection(
            version=claim.version,
            chunks=projected,
            provider=self._embedding_binding.provider,
            model=self._embedding_binding.model,
            graph_projection_hash=graph_hash,
        )


def _chunks(value: str) -> tuple[str, ...]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ConflictError("The Governance Document contains no projectable text.")
    pieces: list[str] = []
    for paragraph in re.split(r"\n{2,}", normalized):
        paragraph = re.sub(r"[ \t]+", " ", paragraph).strip()
        while len(paragraph) > MAXIMUM_KNOWLEDGE_CHUNK_CHARACTERS:
            boundary = paragraph.rfind(" ", 0, MAXIMUM_KNOWLEDGE_CHUNK_CHARACTERS + 1)
            if boundary < MAXIMUM_KNOWLEDGE_CHUNK_CHARACTERS // 2:
                boundary = MAXIMUM_KNOWLEDGE_CHUNK_CHARACTERS
            pieces.append(paragraph[:boundary].strip())
            paragraph = paragraph[boundary:].strip()
        if paragraph:
            pieces.append(paragraph)
    chunks: list[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + len(piece) + 2 <= MAXIMUM_KNOWLEDGE_CHUNK_CHARACTERS:
            chunks[-1] = f"{chunks[-1]}\n\n{piece}"
        else:
            chunks.append(piece)
    if not chunks or len(chunks) > MAXIMUM_KNOWLEDGE_CHUNKS:
        raise ConflictError("The Governance Document exceeds its projectable section limit.")
    return tuple(chunks)


def _retryable(error: Exception) -> bool:
    if isinstance(error, ExternalDependencyError):
        return bool(error.details.get("retryable"))
    return not isinstance(error, DomainError)


def _failure_code(error: Exception) -> str:
    if isinstance(error, ExternalDependencyError):
        provider = error.details.get("provider_code")
        if isinstance(provider, str) and provider:
            return provider[:100]
    name = type(error).__name__.upper()
    return re.sub(r"[^A-Z0-9_]", "_", name)[:100] or "PROJECTION_FAILED"
