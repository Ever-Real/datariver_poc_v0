from __future__ import annotations

from collections.abc import Mapping, Sequence

from datariver.application.governance_document_ports import (
    GovernanceDocumentGraphProjector,
)
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.domain.governance_documents import GovernanceDocumentProjectionClaim
from datariver.infrastructure.knowledge.neo4j import CypherStatement, Neo4jQueryExecutor

_REPLACE_VERSION = """
MERGE (document:GovernanceDocument {
  workspace_id: $workspace_id,
  document_id: $document_id
})
SET document.kind = $kind,
    document.category = $category,
    document.classification = $classification
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

_VERIFY_VERSION = """
MATCH (version:GovernanceDocumentVersion {
  workspace_id: $workspace_id,
  version_id: $version_id,
  document_id: $document_id,
  content_sha256: $content_sha256,
  state: 'PUBLISHED'
})
OPTIONAL MATCH (version)-[:HAS_SECTION]->(chunk:GovernanceDocumentChunk)
WITH version, chunk
ORDER BY chunk.ordinal
RETURN count(chunk) AS chunk_count,
       collect(chunk.content_sha256) AS content_hashes
"""


class Neo4jGovernanceDocumentProjector(GovernanceDocumentGraphProjector):
    def __init__(self, executor: Neo4jQueryExecutor) -> None:
        self._executor = executor

    async def replace_version(
        self,
        *,
        claim: GovernanceDocumentProjectionClaim,
        chunks: Sequence[tuple[int, str, str]],
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
                "contract": "GOVERNANCE_DOCUMENT_NEO4J_PROJECTION_V1",
                **scope,
                "chunks": [
                    {"ordinal": row["ordinal"], "content_sha256": row["content_sha256"]}
                    for row in rows
                ],
            }
        )
        await self._executor.write_transaction(
            statements=(
                CypherStatement(query=_REPLACE_VERSION, parameters=scope),
                CypherStatement(
                    query=_CREATE_CHUNKS,
                    parameters={**scope, "chunks": rows},
                ),
            )
        )
        verification = await self._executor.read(
            statement=CypherStatement(query=_VERIFY_VERSION, parameters=scope)
        )
        self._verify(verification, rows)
        return expected_hash

    @staticmethod
    def _verify(
        values: tuple[Mapping[str, object], ...],
        rows: Sequence[dict[str, object]],
    ) -> None:
        if len(values) != 1:
            raise ConflictError("The Governance Document graph receipt is unavailable.")
        value = values[0]
        hashes = value.get("content_hashes")
        if (
            value.get("chunk_count") != len(rows)
            or not isinstance(hashes, list)
            or hashes != [row["content_sha256"] for row in rows]
        ):
            raise ConflictError("The Governance Document graph projection failed verification.")
