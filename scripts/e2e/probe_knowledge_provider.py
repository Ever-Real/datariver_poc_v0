from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from datariver.application.services.knowledge_pipeline import (
    KnowledgeGraphRagService,
    KnowledgeSourcePipeline,
    VerifiedProjectionService,
)
from datariver.domain.authz import Classification
from datariver.domain.knowledge import GraphSnapshot, Ontology, apply_change_operations
from datariver.domain.knowledge_pipeline import (
    PDF_MEDIA_TYPE,
    GraphRagAuditRecord,
    KnowledgeSourceAnalysis,
    KnowledgeSourceSnapshot,
    ModelBinding,
)
from datariver.infrastructure.knowledge.neo4j import (
    BoltNeo4jQueryExecutor,
    CypherStatement,
    Neo4jKnowledgeProjectionAdapter,
    Neo4jScopedEvidenceRetriever,
)
from datariver.infrastructure.knowledge.openai_compatible import (
    HttpxOpenAIJsonTransport,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleKnowledgeAnswerComposer,
    OpenAICompatibleTypedKnowledgeExtractor,
)
from datariver.infrastructure.knowledge.pdf import PypdfPageAwareParser
from datariver.infrastructure.secrets import SecretResolver

_ENTITY_TYPES = frozenset(
    {"Company", "Country", "Market", "Product", "Technology", "ValueChainStage"}
)
_EDGE_TYPES = frozenset({"AFFECTS", "COMPETES_WITH", "LOCATED_IN", "PART_OF", "PRODUCES", "USES"})

_DELETE_E2E_ENTITIES = """
MATCH (node:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
DETACH DELETE node
"""
_DELETE_E2E_PROJECTION = """
MATCH (deployment:KnowledgeProjection {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
DELETE deployment
"""
_COUNT_E2E_ENTITIES = """
MATCH (node:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
RETURN count(node) AS count
"""
_COUNT_E2E_PROJECTIONS = """
MATCH (deployment:KnowledgeProjection {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
RETURN count(deployment) AS count
"""


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"The provider probe requires {name}.")
    return value


def _binding(*, model: str, prompt: str, schema: str, contract: str) -> ModelBinding:
    return ModelBinding.activated(
        provider="ollama-openai-compatible",
        model=model,
        prompt_version=prompt,
        tool_schema_version=schema,
        configuration_version=None,
        configuration_hash=None,
        adapter_contract=contract,
    )


class _FixedSemanticSelector:
    def __init__(self, entity_ids: tuple[UUID, ...]) -> None:
        self._entity_ids = entity_ids

    async def select_seed_ids(self, **_: object) -> tuple[UUID, ...]:
        return self._entity_ids


class _AuditCollector:
    def __init__(self) -> None:
        self.record: GraphRagAuditRecord | None = None

    async def record_success(self, *, record: GraphRagAuditRecord) -> None:
        self.record = record


async def _verify_neo4j_shadow(
    *,
    analysis: KnowledgeSourceAnalysis,
    chat_transport: HttpxOpenAIJsonTransport,
    answer_binding: ModelBinding,
) -> dict[str, str | int | bool]:
    operations = KnowledgeSourcePipeline.to_typed_operations(analysis)
    snapshot = apply_change_operations(GraphSnapshot(), operations)
    violations = snapshot.validate(
        Ontology(uuid5(NAMESPACE_URL, "datariver:e2e:ontology"), _ENTITY_TYPES, _EDGE_TYPES)
    )
    if violations:
        raise RuntimeError(f"The extracted graph violates its approved ontology: {violations}")

    credential = SecretResolver().resolve(_required_environment("NEO4J_AUTH_SECRET_REF")).strip()
    username, separator, password = credential.partition("/")
    if not separator or not username or not password:
        raise RuntimeError("The Neo4j E2E credential secret is malformed.")
    executor = BoltNeo4jQueryExecutor(
        uri=_required_environment("NEO4J_URI"),
        username=username,
        password=password,
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
        connection_timeout_seconds=float(os.getenv("NEO4J_CONNECTION_TIMEOUT_SECONDS", "30")),
        maximum_connection_pool_size=2,
    )
    page_numbers = ",".join(str(page.page_number) for page in analysis.pages)
    release_seed = f"{analysis.source.content_sha256}:{page_numbers}"
    workspace_id = uuid5(NAMESPACE_URL, "datariver:e2e:knowledge:workspace")
    graph_id = uuid5(NAMESPACE_URL, "datariver:e2e:knowledge:graph")
    release_id = uuid5(NAMESPACE_URL, f"datariver:e2e:knowledge:release:{release_seed}")
    scope = {
        "workspace_id": str(workspace_id),
        "graph_id": str(graph_id),
        "release_id": str(release_id),
    }
    try:
        receipt = await VerifiedProjectionService(
            writer=Neo4jKnowledgeProjectionAdapter(executor=executor)
        ).project_shadow_release(
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
            release_hash=snapshot.content_hash(),
            snapshot=snapshot,
        )
        result: dict[str, str | int | bool] = {
            "neo4j_shadow_verified": receipt.verified,
            "neo4j_release_hash": receipt.release_hash,
            "neo4j_node_count": receipt.node_count,
            "neo4j_edge_count": receipt.edge_count,
        }
        audit = _AuditCollector()
        answer = await KnowledgeGraphRagService(
            retriever=Neo4jScopedEvidenceRetriever(
                executor=executor,
                semantic_selector=_FixedSemanticSelector(tuple(snapshot.nodes)),
            ),
            composer=OpenAICompatibleKnowledgeAnswerComposer(
                transport=chat_transport,
                reasoning_effort="none",
            ),
            audit_writer=audit,
        ).answer(
            request_id=f"e2e-{release_id}",
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
            actor_id=uuid5(NAMESPACE_URL, "datariver:e2e:knowledge:actor"),
            question="Summarize only the relationships supported by this authorized evidence.",
            start_node_id=None,
            direction="BOTH",
            edge_types=_EDGE_TYPES,
            maximum_classification=3,
            maximum_hops=1,
            maximum_nodes=2,
            canonical_snapshot=snapshot,
            binding=answer_binding,
        )
        result.update(
            {
                "graphrag_answer_sha256": hashlib.sha256(answer.answer.encode()).hexdigest(),
                "graphrag_citation_count": len(answer.citations),
                "graphrag_audit_recorded": audit.record is not None,
            }
        )
    finally:
        await executor.write_transaction(
            statements=(
                CypherStatement(_DELETE_E2E_ENTITIES, scope),
                CypherStatement(_DELETE_E2E_PROJECTION, scope),
            )
        )
    entity_rows = await executor.read(statement=CypherStatement(_COUNT_E2E_ENTITIES, scope))
    projection_rows = await executor.read(statement=CypherStatement(_COUNT_E2E_PROJECTIONS, scope))
    await executor.close()
    entity_count = int(str(entity_rows[0]["count"]))
    projection_count = int(str(projection_rows[0]["count"]))
    if entity_count != 0 or projection_count != 0:
        raise RuntimeError("The Neo4j E2E shadow projection cleanup did not complete.")
    result.update(
        {
            "neo4j_cleanup_entity_count": entity_count,
            "neo4j_cleanup_projection_count": projection_count,
        }
    )
    return result


async def _probe(
    *, source_path: Path, selected_pages: tuple[int, ...], verify_neo4j_shadow: bool
) -> dict[str, object]:
    payload = source_path.read_bytes()
    pages = PypdfPageAwareParser().parse(payload)
    by_number = {page.page_number: page for page in pages}
    missing = sorted(set(selected_pages) - set(by_number))
    if missing:
        raise RuntimeError(f"Requested PDF pages do not exist: {missing}")
    source_pages = tuple(by_number[number] for number in selected_pages)

    chat_model = _required_environment("LOCAL_OLLAMA_CHAT_MODEL")
    embedding_model = _required_environment("LOCAL_OLLAMA_EMBEDDING_MODEL")
    chat_transport = HttpxOpenAIJsonTransport(
        base_url=_required_environment("LOCAL_OLLAMA_CHAT_BASE_URL"),
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=float(os.getenv("LOCAL_OLLAMA_CHAT_TIMEOUT_SECONDS", "60")),
    )
    embedding_transport = HttpxOpenAIJsonTransport(
        base_url=_required_environment("LOCAL_OLLAMA_EMBEDDING_BASE_URL"),
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=float(os.getenv("LOCAL_OLLAMA_EMBEDDING_TIMEOUT_SECONDS", "60")),
    )
    embedding_binding = _binding(
        model=embedding_model,
        prompt="embedding-v1",
        schema="openai-embeddings-v1",
        contract="openai-compatible-embeddings-v1",
    )
    extraction_binding = _binding(
        model=chat_model,
        prompt="knowledge-pdf-extraction-v1",
        schema="knowledge-extraction-schema-v1",
        contract="openai-compatible-chat-json-schema-v1",
    )
    answer_binding = _binding(
        model=chat_model,
        prompt="knowledge-graphrag-v1",
        schema="knowledge-graphrag-schema-v1",
        contract="openai-compatible-chat-json-schema-v1",
    )
    embeddings = await OpenAICompatibleEmbeddingProvider(transport=embedding_transport).embed_pages(
        pages=source_pages, binding=embedding_binding
    )
    extraction = await OpenAICompatibleTypedKnowledgeExtractor(
        transport=chat_transport,
        reasoning_effort="none",
    ).propose(
        pages=source_pages,
        entity_types=_ENTITY_TYPES,
        edge_types=_EDGE_TYPES,
        binding=extraction_binding,
    )
    extraction.validate(
        entity_types=_ENTITY_TYPES,
        edge_types=_EDGE_TYPES,
        page_numbers=frozenset(selected_pages),
    )
    KnowledgeSourcePipeline._verify_extraction_evidence(
        pages=source_pages,
        extraction=extraction,
    )
    source_sha256 = hashlib.sha256(payload).hexdigest()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid5(NAMESPACE_URL, f"datariver:e2e:knowledge:source:{source_sha256}"),
        workspace_id=uuid5(NAMESPACE_URL, "datariver:e2e:knowledge:workspace"),
        graph_id=uuid5(NAMESPACE_URL, "datariver:e2e:knowledge:graph"),
        bucket="datariver-e2e-private",
        object_key=f"knowledge/e2e/{source_sha256}.pdf",
        storage_version=source_sha256,
        media_type=PDF_MEDIA_TYPE,
        byte_size=len(payload),
        content_sha256=source_sha256,
        classification=int(Classification.RESTRICTED),
    )
    analysis = KnowledgeSourceAnalysis(
        source=source,
        pages=source_pages,
        embeddings=embeddings,
        extraction=extraction,
    )
    dimensions = {len(value.vector) for value in embeddings.embeddings}
    result: dict[str, object] = {
        "source_sha256": source_sha256,
        "total_pdf_pages": len(pages),
        "probed_pages": list(selected_pages),
        "embedding_model": embedding_binding.model,
        "embedding_configuration_hash": embedding_binding.configuration_hash,
        "embedding_dimensions": sorted(dimensions),
        "extraction_model": extraction_binding.model,
        "extraction_configuration_hash": extraction_binding.configuration_hash,
        "proposed_nodes": len(extraction.nodes),
        "proposed_edges": len(extraction.edges),
        "page_bound_evidence_verified": True,
        "input_tokens": extraction.input_tokens,
        "output_tokens": extraction.output_tokens,
    }
    if verify_neo4j_shadow:
        result.update(
            await _verify_neo4j_shadow(
                analysis=analysis,
                chat_transport=chat_transport,
                answer_binding=answer_binding,
            )
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe the real PDF-to-Ollama typed Knowledge provider contract."
    )
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page", action="append", type=int, dest="pages")
    parser.add_argument("--confirm-actual-provider-call", action="store_true")
    parser.add_argument("--verify-neo4j-shadow", action="store_true")
    arguments = parser.parse_args()
    if not arguments.confirm_actual_provider_call:
        raise SystemExit("Refusing to call the provider without --confirm-actual-provider-call.")
    selected_pages = tuple(arguments.pages or (51, 58))
    if not selected_pages or len(selected_pages) > 12 or any(page < 1 for page in selected_pages):
        raise SystemExit("Select between one and twelve positive PDF page numbers.")
    result = asyncio.run(
        _probe(
            source_path=arguments.pdf.resolve(),
            selected_pages=selected_pages,
            verify_neo4j_shadow=arguments.verify_neo4j_shadow,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
