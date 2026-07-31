from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

from platform_workflow import read_env_values

from datariver.application.evidence import build_evidence_chunk
from datariver.domain.authz import Classification
from datariver.domain.knowledge_pipeline import ModelBinding, PdfPage
from datariver.infrastructure.knowledge.openai_compatible import (
    HttpxOpenAIJsonTransport,
    OpenAICompatibleEmbeddingProvider,
)
from datariver.infrastructure.llm.ollama import LocalOllamaChatComposer
from datariver.infrastructure.llm.reranker import LocalLlamaCppEvidenceReranker


def _required(values: dict[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise RuntimeError(f"The selected environment requires {name}.")
    return value


def _timeout(values: dict[str, str], name: str) -> float:
    value = float(values.get(name, "60"))
    if not 1 <= value <= 120:
        raise RuntimeError(f"The selected environment has an invalid {name}.")
    return value


def _provider_url(
    values: dict[str, str],
    name: str,
    *,
    source_host: bool,
) -> str:
    value = _required(values, name)
    if not source_host:
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "host.docker.internal"
        or parsed.port not in {11434, 11435}
        or parsed.path.rstrip("/") != "/v1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "Source-host probing can translate only the fixed Docker host-gateway contracts."
        )
    return urlunsplit(("http", f"127.0.0.1:{parsed.port}", "/v1", "", ""))


async def _probe(
    values: dict[str, str],
    *,
    source_host: bool,
) -> dict[str, object]:
    workspace_id = uuid5(NAMESPACE_URL, "datariver:local-chat-probe:workspace")
    evidence = (
        build_evidence_chunk(
            workspace_id=workspace_id,
            resource_id=uuid5(NAMESPACE_URL, "datariver:local-chat-probe:orders"),
            classification=Classification.INTERNAL,
            system_id=None,
            domain_id=None,
            owner_department_id=None,
            name="orders",
            description="Authorized order records used only for a local connectivity probe.",
            source_locator="urn:datariver:probe:orders",
            source_version="probe-v1",
            effective_from=datetime(2026, 7, 26, tzinfo=UTC),
            extraction_method="LOCAL_CONNECTIVITY_PROBE_V1",
        ),
        build_evidence_chunk(
            workspace_id=workspace_id,
            resource_id=uuid5(NAMESPACE_URL, "datariver:local-chat-probe:weather"),
            classification=Classification.INTERNAL,
            system_id=None,
            domain_id=None,
            owner_department_id=None,
            name="weather_archive",
            description="An unrelated archive used only to verify reranking order.",
            source_locator="urn:datariver:probe:weather",
            source_version="probe-v1",
            effective_from=datetime(2026, 7, 26, tzinfo=UTC),
            extraction_method="LOCAL_CONNECTIVITY_PROBE_V1",
        ),
    )
    chat_model = _required(values, "LOCAL_OLLAMA_CHAT_MODEL")
    chat = await LocalOllamaChatComposer(
        base_url=_provider_url(
            values,
            "LOCAL_OLLAMA_CHAT_BASE_URL",
            source_host=source_host,
        ),
        model=chat_model,
        timeout_seconds=_timeout(values, "LOCAL_OLLAMA_CHAT_TIMEOUT_SECONDS"),
        context_tokens=int(_required(values, "LOCAL_OLLAMA_CHAT_CONTEXT_TOKENS")),
        allowed_hosts=frozenset({"127.0.0.1", "host.docker.internal"}),
    ).compose(
        question="Which supplied table contains authorized order records?",
        evidence=evidence,
    )
    if not chat.answer or not chat.cited_chunk_ids:
        raise RuntimeError("The local Chat model did not satisfy the grounded tool contract.")
    evidence_ids = {item.chunk_id for item in evidence}
    if any(chunk_id not in evidence_ids for chunk_id in chat.cited_chunk_ids):
        raise RuntimeError("The local Chat model returned an unknown citation.")

    embedding_model = _required(values, "LOCAL_OLLAMA_EMBEDDING_MODEL")
    binding = ModelBinding.activated(
        provider="ollama-openai-compatible",
        model=embedding_model,
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
        configuration_version=None,
        configuration_hash=None,
        adapter_contract="openai-compatible-embeddings-v1",
    )
    embeddings = await OpenAICompatibleEmbeddingProvider(
        transport=HttpxOpenAIJsonTransport(
            base_url=_provider_url(
                values,
                "LOCAL_OLLAMA_EMBEDDING_BASE_URL",
                source_host=source_host,
            ),
            allowed_hosts=frozenset({"127.0.0.1", "host.docker.internal"}),
            api_key=None,
            timeout_seconds=_timeout(values, "LOCAL_OLLAMA_EMBEDDING_TIMEOUT_SECONDS"),
        )
    ).embed_pages(
        pages=(PdfPage.create(page_number=1, text="governed catalog order records"),),
        binding=binding,
    )
    observed_dimensions = {len(item.vector) for item in embeddings.embeddings}
    if len(observed_dimensions) != 1 or next(iter(observed_dimensions)) < 1:
        raise RuntimeError("The local embedding model returned inconsistent dimensions.")

    reranker_model = _required(values, "LOCAL_LLAMA_CPP_RERANKER_MODEL")
    reranked_ids = await LocalLlamaCppEvidenceReranker(
        base_url=_provider_url(
            values,
            "LOCAL_LLAMA_CPP_RERANKER_BASE_URL",
            source_host=source_host,
        ),
        model=reranker_model,
        timeout_seconds=_timeout(values, "LOCAL_LLAMA_CPP_RERANKER_TIMEOUT_SECONDS"),
        top_n=min(int(_required(values, "LOCAL_LLAMA_CPP_RERANKER_TOP_N")), len(evidence)),
        allowed_hosts=frozenset({"127.0.0.1", "host.docker.internal"}),
    ).rerank(
        question="authorized order records",
        evidence=evidence,
    )
    if not reranked_ids or reranked_ids[0] != evidence[0].chunk_id:
        raise RuntimeError("The local reranker did not rank the relevant probe evidence first.")

    return {
        "chat_model": chat_model,
        "chat_answer_sha256": hashlib.sha256(chat.answer.encode()).hexdigest(),
        "chat_citation_count": len(chat.cited_chunk_ids),
        "embedding_model": embedding_model,
        "embedding_dimensions_observed": sorted(observed_dimensions),
        "reranker_model": reranker_model,
        "reranker_result_count": len(reranked_ids),
        "reranker_relevant_evidence_first": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe the selected development Chat, Embedding and Reranker contracts."
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--confirm-actual-provider-call", action="store_true")
    parser.add_argument(
        "--source-host",
        action="store_true",
        help="Translate only the fixed Docker host-gateway origins to source-host loopback.",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_actual_provider_call:
        raise SystemExit("Refusing to call local providers without explicit confirmation.")
    values = read_env_values(arguments.env_file.resolve())
    required_flags = (
        "LOCAL_OLLAMA_CHAT_ENABLED",
        "LOCAL_OLLAMA_EMBEDDING_ENABLED",
        "LOCAL_LLAMA_CPP_RERANKER_ENABLED",
    )
    if any(values.get(name, "").casefold() != "true" for name in required_flags):
        raise SystemExit(
            "The selected environment does not activate the complete local Chat stack."
        )
    result = asyncio.run(_probe(values, source_host=arguments.source_host))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
