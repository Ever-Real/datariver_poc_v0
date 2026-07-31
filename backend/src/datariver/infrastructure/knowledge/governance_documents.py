from __future__ import annotations

from collections.abc import Mapping, Sequence

from datariver.application.governance_document_ports import (
    GovernanceDocumentGraphProjector,
)
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.domain.governance_documents import (
    GovernanceDocumentConcept,
    GovernanceDocumentConceptKind,
    GovernanceDocumentProjectionClaim,
)
from datariver.infrastructure.knowledge.neo4j import CypherStatement, Neo4jQueryExecutor

_REPLACE_VERSION = """
MERGE (document:GovernanceDocument {
  workspace_id: $workspace_id,
  document_id: $document_id
})
SET document.kind = $kind,
    document.category = $category,
    document.classification = $classification,
    document.title = $title
MERGE (policy:GovernancePolicy {
  workspace_id: $workspace_id,
  document_id: $document_id
})
SET policy.kind = $kind,
    policy.category = $category,
    policy.classification = $classification,
    policy.title = $title,
    policy.current_version_id = $version_id
MERGE (document)-[:REPRESENTS_POLICY]->(policy)
WITH document, policy
OPTIONAL MATCH (policy)-[old:GOVERNS]->()
DELETE old
WITH document, policy
MERGE (version:GovernanceDocumentVersion {
  workspace_id: $workspace_id,
  version_id: $version_id
})
SET version.document_id = $document_id,
    version.version_number = $version_number,
    version.version_tag = $version_tag,
    version.title = $title,
    version.content_sha256 = $content_sha256,
    version.classification = $classification,
    version.state = 'PUBLISHED'
MERGE (document)-[:HAS_VERSION]->(version)
MERGE (policy)-[:HAS_VERSION]->(version)
WITH version
OPTIONAL MATCH (version)-[:HAS_SECTION]->(old:GovernanceDocumentChunk)
DETACH DELETE old
"""

_CREATE_CHUNKS = """
UNWIND $chunks AS row
MATCH (version:GovernanceDocumentVersion {
  workspace_id: $workspace_id,
  version_id: $version_id
})
CREATE (chunk:GovernanceDocumentChunk {
  workspace_id: $workspace_id,
  document_id: $document_id,
  version_id: $version_id,
  ordinal: row.ordinal,
  content: row.content,
  content_sha256: row.content_sha256,
  classification: $classification
})
CREATE (version)-[:HAS_SECTION]->(chunk)
"""

_CREATE_DATASET_CONCEPTS = """
UNWIND $concepts AS row
MATCH (policy:GovernancePolicy {
  workspace_id: $workspace_id,
  document_id: $document_id
})
MERGE (target:GovernanceDataset:Dataset {
  workspace_id: $workspace_id,
  governance_reference_hash: row.reference_hash
})
SET target.governance_kind = 'DATASET',
    target.reference = row.reference
MERGE (policy)-[edge:GOVERNS]->(target)
SET edge.version_id = $version_id,
    edge.evidence = 'AUTHOR_DECLARED'
"""

_CREATE_TERM_CONCEPTS = """
UNWIND $concepts AS row
MATCH (policy:GovernancePolicy {
  workspace_id: $workspace_id,
  document_id: $document_id
})
MERGE (target:GovernanceTerm:Term {
  workspace_id: $workspace_id,
  governance_reference_hash: row.reference_hash
})
SET target.governance_kind = 'TERM',
    target.reference = row.reference
MERGE (policy)-[edge:GOVERNS]->(target)
SET edge.version_id = $version_id,
    edge.evidence = 'AUTHOR_DECLARED'
"""

_VERIFY_VERSION = """
MATCH (version:GovernanceDocumentVersion {
  workspace_id: $workspace_id,
  version_id: $version_id,
  document_id: $document_id,
  content_sha256: $content_sha256,
  state: 'PUBLISHED'
})
MATCH (policy:GovernancePolicy {
  workspace_id: $workspace_id,
  document_id: $document_id,
  current_version_id: $version_id
})
OPTIONAL MATCH (version)-[:HAS_SECTION]->(chunk:GovernanceDocumentChunk)
WITH version, policy, chunk
ORDER BY chunk.ordinal
WITH version, policy,
     count(chunk) AS chunk_count,
     collect(chunk.content_sha256) AS content_hashes
OPTIONAL MATCH (policy)-[:GOVERNS]->(target)
RETURN chunk_count,
       content_hashes,
       count(target) AS concept_count,
       collect(target.governance_kind + ':' + target.governance_reference_hash)
         AS concept_keys
"""


class Neo4jGovernanceDocumentProjector(GovernanceDocumentGraphProjector):
    def __init__(self, executor: Neo4jQueryExecutor) -> None:
        self._executor = executor

    async def replace_version(
        self,
        *,
        claim: GovernanceDocumentProjectionClaim,
        chunks: Sequence[tuple[int, str, str]],
        concepts: Sequence[GovernanceDocumentConcept],
    ) -> str:
        version = claim.version
        if not chunks:
            raise ConflictError("A Governance Document graph projection requires sections.")
        rows = [
            {
                "ordinal": ordinal,
                "content": content,
                "content_sha256": content_sha256,
            }
            for ordinal, content, content_sha256 in chunks
        ]
        concept_rows: list[dict[str, object]] = [
            {
                "kind": concept.kind.value,
                "reference": concept.reference,
                "reference_hash": canonical_json_hash(
                    {
                        "contract": "GOVERNANCE_DOCUMENT_CONCEPT_V1",
                        "kind": concept.kind.value,
                        "reference": concept.reference,
                    }
                ),
            }
            for concept in concepts
        ]
        dataset_rows = [
            value
            for value in concept_rows
            if value["kind"] == GovernanceDocumentConceptKind.DATASET.value
        ]
        term_rows = [
            value
            for value in concept_rows
            if value["kind"] == GovernanceDocumentConceptKind.TERM.value
        ]
        scope: dict[str, object] = {
            "workspace_id": str(version.workspace_id),
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "version_number": version.version_number,
            "version_tag": version.version_tag,
            "title": version.title,
            "content_sha256": version.content_sha256,
            "kind": claim.kind.value,
            "category": claim.category.value,
            "classification": int(claim.classification),
        }
        expected_hash = canonical_json_hash(
            {
                "contract": "GOVERNANCE_DOCUMENT_NEO4J_PROJECTION_V2",
                **scope,
                "chunks": [
                    {"ordinal": row["ordinal"], "content_sha256": row["content_sha256"]}
                    for row in rows
                ],
                "concepts": concept_rows,
            }
        )
        await self._executor.write_transaction(
            statements=(
                CypherStatement(query=_REPLACE_VERSION, parameters=scope),
                CypherStatement(
                    query=_CREATE_CHUNKS,
                    parameters={**scope, "chunks": rows},
                ),
                CypherStatement(
                    query=_CREATE_DATASET_CONCEPTS,
                    parameters={**scope, "concepts": dataset_rows},
                ),
                CypherStatement(
                    query=_CREATE_TERM_CONCEPTS,
                    parameters={**scope, "concepts": term_rows},
                ),
            )
        )
        verification = await self._executor.read(
            statement=CypherStatement(query=_VERIFY_VERSION, parameters=scope)
        )
        self._verify(verification, rows, concept_rows)
        return expected_hash

    @staticmethod
    def _verify(
        values: tuple[Mapping[str, object], ...],
        rows: Sequence[dict[str, object]],
        concept_rows: Sequence[dict[str, object]],
    ) -> None:
        if len(values) != 1:
            raise ConflictError("The Governance Document graph receipt is unavailable.")
        value = values[0]
        hashes = value.get("content_hashes")
        concept_keys = value.get("concept_keys")
        expected_concept_keys = sorted(
            f"{row['kind']}:{row['reference_hash']}" for row in concept_rows
        )
        if (
            value.get("chunk_count") != len(rows)
            or not isinstance(hashes, list)
            or hashes != [row["content_sha256"] for row in rows]
            or value.get("concept_count") != len(concept_rows)
            or not isinstance(concept_keys, list)
            or sorted(str(item) for item in concept_keys) != expected_concept_keys
        ):
            raise ConflictError("The Governance Document graph projection failed verification.")
