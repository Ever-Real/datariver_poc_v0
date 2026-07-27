from __future__ import annotations

import math

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.application.dto import CatalogAssetIndex, ChatVectorSearchResult
from datariver.application.errors import ChatExternalAdapterInvocationError
from datariver.application.knowledge_pipeline_ports import KnowledgeEmbeddingProvider
from datariver.application.ports import CatalogIndexReader, ChatVectorCatalogReader
from datariver.domain.authz import SubjectAttributes
from datariver.domain.chat import (
    MAXIMUM_CHAT_VECTOR_CANDIDATES,
    MAXIMUM_CHAT_VECTOR_TEXT_CHARACTERS,
)
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import ModelBinding, PdfPage


class BoundedCatalogVectorReader(ChatVectorCatalogReader):
    """Rank a bounded, authorization-pruned catalog candidate window with real embeddings."""

    def __init__(
        self,
        *,
        catalog_index: CatalogIndexReader,
        embedding: KnowledgeEmbeddingProvider,
        binding: ModelBinding,
    ) -> None:
        self._catalog_index = catalog_index
        self._embedding = embedding
        self._binding = binding

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        question: str,
        limit: int,
    ) -> ChatVectorSearchResult:
        candidate_limit = min(
            max(limit * 4, 8),
            MAXIMUM_CHAT_VECTOR_CANDIDATES,
        )
        page = await self._catalog_index.search(
            subject=subject,
            access=access,
            query="",
            filters={},
            cursor=None,
            limit=candidate_limit,
        )
        candidates = tuple(page.items)
        if not candidates:
            return ChatVectorSearchResult(items=(), provider_invoked=False)
        pages = (
            PdfPage.create(page_number=1, text=question),
            *(
                PdfPage.create(
                    page_number=index + 2,
                    text=self._candidate_text(candidate),
                )
                for index, candidate in enumerate(candidates)
            ),
        )
        try:
            batch = await self._embedding.embed_pages(
                pages=pages,
                binding=self._binding,
            )
            if batch.binding.to_document() != self._binding.to_document():
                raise ValidationError("The vector adapter returned a different embedding binding.")
            if len(batch.embeddings) != len(pages):
                raise ValidationError("The vector adapter returned an incomplete embedding batch.")
            ordered = sorted(batch.embeddings, key=lambda item: item.page_number)
            if tuple(item.page_number for item in ordered) != tuple(range(1, len(pages) + 1)):
                raise ValidationError("The vector adapter returned invalid page indices.")
            query_vector = ordered[0].vector
            scored: list[tuple[float, CatalogAssetIndex]] = []
            for candidate, embedding in zip(
                candidates,
                ordered[1:],
                strict=True,
            ):
                score = self._cosine(query_vector, embedding.vector)
                if math.isfinite(score):
                    scored.append((score, candidate))
            scored.sort(key=lambda item: (-item[0], item[1].asset_id.int))
        except Exception as error:
            raise ChatExternalAdapterInvocationError(stage="embedding") from error
        return ChatVectorSearchResult(
            items=tuple(candidate for _score, candidate in scored[:limit]),
            provider_invoked=True,
        )

    @staticmethod
    def _candidate_text(candidate: CatalogAssetIndex) -> str:
        components = (
            candidate.name,
            candidate.description or "",
            candidate.platform or "",
            candidate.database_name or "",
            candidate.schema_name or "",
            " ".join(candidate.tags),
            " ".join(candidate.glossary_terms),
            " ".join(candidate.column_names[:50]),
        )
        return "\n".join(value for value in components if value)[
            :MAXIMUM_CHAT_VECTOR_TEXT_CHARACTERS
        ]

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if not left or len(left) != len(right):
            raise ValidationError("The vector adapter returned incompatible dimensions.")
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
