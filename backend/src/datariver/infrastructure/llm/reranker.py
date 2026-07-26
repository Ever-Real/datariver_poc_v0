from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from datariver.application.dto import ChatEvidence
from datariver.application.ports import ChatEvidenceReranker
from datariver.domain.common import ValidationError

MAXIMUM_RERANK_RESPONSE_BYTES = 131_072
MAXIMUM_RERANK_DOCUMENT_CHARACTERS = 2_000


class LocalLlamaCppEvidenceReranker(ChatEvidenceReranker):
    """Use the fixed development llama.cpp `/v1/rerank` contract without redirects or proxies."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        top_n: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "host.docker.internal"}
            or parsed.port != 11435
            or parsed.path.rstrip("/") != "/v1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError("The local reranker endpoint violates the fixed contract.")
        if not model.strip() or not 1 <= top_n <= 100:
            raise ValidationError("The local reranker model or result bound is invalid.")
        self._endpoint = f"{base_url.rstrip('/')}/rerank"
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._top_n = top_n
        self._transport = transport

    async def rerank(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> tuple[UUID, ...]:
        if not evidence:
            return ()
        top_n = min(self._top_n, len(evidence))
        documents = [
            f"{item.name}\n{item.description or ''}"[:MAXIMUM_RERANK_DOCUMENT_CHARACTERS]
            for item in evidence
        ]
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_seconds, connect=3.0),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
        ) as client:
            async with client.stream(
                "POST",
                self._endpoint,
                json={
                    "model": self._model,
                    "query": question,
                    "documents": documents,
                    "top_n": top_n,
                },
            ) as response:
                if response.status_code != 200:
                    raise ValidationError("The local reranker request failed.")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAXIMUM_RERANK_RESPONSE_BYTES:
                        raise ValidationError("The local reranker response exceeded its bound.")
        try:
            document: Any = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError("The local reranker returned invalid JSON.") from error
        if not isinstance(document, dict) or document.get("model") != self._model:
            raise ValidationError("The local reranker returned a different model identity.")
        results = document.get("results")
        if not isinstance(results, list) or len(results) != top_n:
            raise ValidationError("The local reranker returned an invalid result count.")
        indexes: list[int] = []
        scores: list[float] = []
        for item in results:
            if not isinstance(item, dict):
                raise ValidationError("The local reranker returned an invalid result.")
            index = item.get("index")
            score = item.get("relevance_score")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < len(evidence)
                or not isinstance(score, int | float)
                or isinstance(score, bool)
                or not math.isfinite(float(score))
            ):
                raise ValidationError("The local reranker returned invalid rank data.")
            indexes.append(index)
            scores.append(float(score))
        if len(set(indexes)) != len(indexes) or scores != sorted(scores, reverse=True):
            raise ValidationError("The local reranker result order is invalid.")
        return tuple(evidence[index].chunk_id for index in indexes)
