from __future__ import annotations

import math
import re
from time import perf_counter

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.application.dto import (
    CatalogAssetIndex,
    CatalogPage,
    ChatCatalogSearchScope,
    ChatVectorSearchResult,
)
from datariver.application.errors import ChatExternalAdapterInvocationError
from datariver.application.knowledge_pipeline_ports import KnowledgeEmbeddingProvider
from datariver.application.ports import (
    CatalogIndexReader,
    ChatRequestPerformanceObserver,
    ChatVectorCatalogReader,
)
from datariver.domain.authz import SubjectAttributes
from datariver.domain.chat import (
    MAXIMUM_CHAT_VECTOR_CANDIDATES,
    MAXIMUM_CHAT_VECTOR_TEXT_CHARACTERS,
    ChatPerformanceMetric,
)
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import ModelBinding, PdfPage

_CATALOG_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+")
_CATALOG_MIXED_LANGUAGE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{2,99}(?=[가-힣])")


class BoundedCatalogVectorReader(ChatVectorCatalogReader):
    """Rank a bounded, authorization-pruned catalog candidate window with real embeddings."""

    def __init__(
        self,
        *,
        catalog_index: CatalogIndexReader,
        embedding: KnowledgeEmbeddingProvider,
        binding: ModelBinding,
        performance_observer: ChatRequestPerformanceObserver | None = None,
    ) -> None:
        self._catalog_index = catalog_index
        self._embedding = embedding
        self._binding = binding
        self._performance_observer = performance_observer

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        question: str,
        limit: int,
    ) -> ChatVectorSearchResult:
        candidate_limit = min(
            max(limit, 8),
            MAXIMUM_CHAT_VECTOR_CANDIDATES,
        )
        catalog_started = perf_counter()
        page, catalog_search_scope = await self._candidate_page(
            subject=subject,
            access=access,
            question=question,
            candidate_limit=candidate_limit,
        )
        self._record(
            ChatPerformanceMetric.CATALOG_DISCOVERY,
            catalog_started,
        )
        # The catalog port is expected to honor its limit, but keep the provider batch bounded
        # even if an implementation returns an oversized page.
        candidates = tuple(page.items[:candidate_limit])
        if not candidates:
            return ChatVectorSearchResult(
                items=(),
                provider_invoked=False,
                catalog_search_scope=catalog_search_scope,
            )
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
            vector_started = perf_counter()
            batch = await self._embedding.embed_pages(
                pages=pages,
                binding=self._binding,
            )
            self._record(ChatPerformanceMetric.VECTOR, vector_started)
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
            catalog_search_scope=catalog_search_scope,
        )

    def _record(self, metric: ChatPerformanceMetric, started: float) -> None:
        if self._performance_observer is None:
            return
        self._performance_observer.record(
            metric=metric,
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
        )

    async def _candidate_page(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        question: str,
        candidate_limit: int,
    ) -> tuple[CatalogPage, ChatCatalogSearchScope]:
        """Prefer a bounded catalog-name window without broadening the access scope."""

        anchor = self._catalog_name_anchor(question)
        if anchor:
            scope = ChatCatalogSearchScope(query=anchor, search_fields=("TABLE",))
            return (
                await self._catalog_index.search(
                    subject=subject,
                    access=access,
                    query=scope.query,
                    filters={"search_fields": ",".join(scope.search_fields)},
                    cursor=None,
                    limit=candidate_limit,
                ),
                scope,
            )
        scope = ChatCatalogSearchScope(query="")
        return (
            await self._catalog_index.search(
                subject=subject,
                access=access,
                query=scope.query,
                filters={},
                cursor=None,
                limit=candidate_limit,
            ),
            scope,
        )

    @staticmethod
    def _catalog_name_anchor(question: str) -> str:
        """Return a bounded catalog-name token; natural-language queries keep vector behavior."""

        identifier_candidates = tuple(
            match.group(0)
            for match in _CATALOG_IDENTIFIER.finditer(question)
            if len(match.group(0)) <= 100
        )
        if identifier_candidates:
            return max(identifier_candidates, key=len)

        # Korean-language questions commonly attach a requested Latin table-name fragment
        # directly to a Korean suffix (for example, "capital이름"). Preserve that
        # fragment as a constrained table-field lookup rather than falling back to
        # an unrelated blank catalog window.
        mixed_language_candidates = tuple(
            match.group(0) for match in _CATALOG_MIXED_LANGUAGE_NAME.finditer(question)
        )
        return max(mixed_language_candidates, key=len, default="")

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
