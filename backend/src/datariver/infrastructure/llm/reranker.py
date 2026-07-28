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
from datariver.domain.inference import (
    is_safe_inference_api_base_path,
    is_valid_inference_model_identity,
)

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
        allowed_hosts: frozenset[str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        host = (parsed.hostname or "").rstrip(".").lower()
        if (
            parsed.scheme != "http"
            or host not in allowed_hosts
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
        self._headers: dict[str, str] = {}
        self._label = "local"
        self._require_model_echo = True
        self._require_unit_interval = False

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
                headers=self._headers,
                json={
                    "model": self._model,
                    "query": question,
                    "documents": documents,
                    "top_n": top_n,
                },
            ) as response:
                if response.status_code != 200:
                    raise ValidationError(f"The {self._label} reranker request failed.")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAXIMUM_RERANK_RESPONSE_BYTES:
                        raise ValidationError(
                            f"The {self._label} reranker response exceeded its bound."
                        )
        try:
            document: Any = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(
                f"The {self._label} reranker returned invalid JSON."
            ) from error
        if not isinstance(document, dict):
            raise ValidationError(
                f"The {self._label} reranker returned an invalid document."
            )
        returned_model = document.get("model")
        if (
            (self._require_model_echo and returned_model != self._model)
            or (returned_model is not None and returned_model != self._model)
        ):
            raise ValidationError(
                f"The {self._label} reranker returned a different model identity."
            )
        results = document.get("results")
        if not isinstance(results, list) or len(results) != top_n:
            raise ValidationError(
                f"The {self._label} reranker returned an invalid result count."
            )
        indexes: list[int] = []
        scores: list[float] = []
        for item in results:
            if not isinstance(item, dict):
                raise ValidationError(
                    f"The {self._label} reranker returned an invalid result."
                )
            index = item.get("index")
            score = item.get("relevance_score")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < len(evidence)
                or not isinstance(score, int | float)
                or isinstance(score, bool)
                or not math.isfinite(float(score))
                or (
                    self._require_unit_interval
                    and not 0.0 <= float(score) <= 1.0
                )
            ):
                raise ValidationError(
                    f"The {self._label} reranker returned invalid rank data."
                )
            indexes.append(index)
            scores.append(float(score))
        if len(set(indexes)) != len(indexes) or scores != sorted(scores, reverse=True):
            raise ValidationError(
                f"The {self._label} reranker result order is invalid."
            )
        return tuple(evidence[index].chunk_id for index in indexes)


class IntranetEvidenceReranker(LocalLlamaCppEvidenceReranker):
    """Call a fixed private `/rerank` route through an HTTPS gateway prefix."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        top_n: int,
        allowed_hosts: frozenset[str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        host = (parsed.hostname or "").rstrip(".").lower()
        if (
            parsed.scheme != "https"
            or host not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not is_safe_inference_api_base_path(parsed.path)
        ):
            raise ValidationError("The intranet reranker endpoint violates the fixed contract.")
        if (
            not is_valid_inference_model_identity(model)
            or not api_key.strip()
            or not 1 <= top_n <= 100
        ):
            raise ValidationError("The intranet reranker binding is invalid.")
        self._endpoint = f"{base_url.rstrip('/')}/rerank"
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._top_n = top_n
        self._transport = transport
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._label = "intranet"
        self._require_model_echo = False
        self._require_unit_interval = True
