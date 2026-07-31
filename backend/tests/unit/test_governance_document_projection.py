from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from datariver.application.services.governance_document_projection import (
    governance_document_concepts,
)
from datariver.domain.authz import Classification
from datariver.domain.governance_documents import (
    GovernanceDocumentArtifactState,
    GovernanceDocumentCategory,
    GovernanceDocumentConcept,
    GovernanceDocumentConceptKind,
    GovernanceDocumentKind,
    GovernanceDocumentKnowledgeState,
    GovernanceDocumentProjectionClaim,
    GovernanceDocumentSourceFormat,
    GovernanceDocumentVersion,
    GovernanceDocumentVersionState,
)
from datariver.infrastructure.knowledge.governance_documents import (
    Neo4jGovernanceDocumentProjector,
)
from datariver.infrastructure.knowledge.neo4j import CypherStatement

NOW = datetime(2026, 7, 31, tzinfo=UTC)


class _GraphExecutor:
    def __init__(self) -> None:
        self.statements: tuple[CypherStatement, ...] = ()

    async def write_transaction(
        self,
        *,
        statements: Sequence[CypherStatement],
    ) -> tuple[Mapping[str, object], ...]:
        self.statements = tuple(statements)
        return ()

    async def read(
        self,
        *,
        statement: CypherStatement,
    ) -> tuple[Mapping[str, object], ...]:
        assert "GovernancePolicy" in statement.query
        chunk_rows = self.statements[1].parameters["chunks"]
        dataset_rows = self.statements[2].parameters["concepts"]
        term_rows = self.statements[3].parameters["concepts"]
        assert isinstance(chunk_rows, list)
        assert isinstance(dataset_rows, list)
        assert isinstance(term_rows, list)
        concept_rows = [*dataset_rows, *term_rows]
        return (
            {
                "chunk_count": len(chunk_rows),
                "content_hashes": [row["content_sha256"] for row in chunk_rows],
                "concept_count": len(concept_rows),
                "concept_keys": [f"{row['kind']}:{row['reference_hash']}" for row in concept_rows],
            },
        )


def test_author_declared_dataset_and_term_concepts_are_bounded_and_deduplicated() -> None:
    concepts = governance_document_concepts(
        applicability_scope=(
            "dataset:urn:li:dataset:(urn:li:dataPlatform:postgres,finance.orders,PROD), "
            "term:Customer; term: customer"
        ),
        plain_text=(
            "이 정책은 [[Dataset:finance.customer_master]]와 "
            "[[Term:Personal Information]]을 관리한다."
        ),
    )

    assert concepts == (
        GovernanceDocumentConcept(
            kind=GovernanceDocumentConceptKind.DATASET,
            reference="finance.customer_master",
        ),
        GovernanceDocumentConcept(
            kind=GovernanceDocumentConceptKind.DATASET,
            reference="urn:li:dataset:(urn:li:dataPlatform:postgres,finance.orders,PROD)",
        ),
        GovernanceDocumentConcept(
            kind=GovernanceDocumentConceptKind.TERM,
            reference="Customer",
        ),
        GovernanceDocumentConcept(
            kind=GovernanceDocumentConceptKind.TERM,
            reference="Personal Information",
        ),
    )


@pytest.mark.asyncio
async def test_neo4j_projection_creates_governance_policy_governs_dataset_and_term() -> None:
    executor = _GraphExecutor()
    claim = _claim()
    concepts = (
        GovernanceDocumentConcept(
            kind=GovernanceDocumentConceptKind.DATASET,
            reference="finance.orders",
        ),
        GovernanceDocumentConcept(
            kind=GovernanceDocumentConceptKind.TERM,
            reference="Customer",
        ),
    )

    projection_hash = await Neo4jGovernanceDocumentProjector(executor).replace_version(
        claim=claim,
        chunks=((1, "Approved policy", "a" * 64),),
        concepts=concepts,
    )

    assert len(projection_hash) == 64
    assert len(executor.statements) == 4
    assert "GovernancePolicy" in executor.statements[0].query
    assert "GOVERNS" in executor.statements[2].query
    assert "GovernanceDataset:Dataset" in executor.statements[2].query
    assert "GovernanceTerm:Term" in executor.statements[3].query
    dataset_rows = executor.statements[2].parameters["concepts"]
    assert isinstance(dataset_rows, list)
    assert len(dataset_rows) == 1
    assert dataset_rows[0]["kind"] == "DATASET"
    assert dataset_rows[0]["reference"] == "finance.orders"
    assert len(dataset_rows[0]["reference_hash"]) == 64


def _claim() -> GovernanceDocumentProjectionClaim:
    workspace_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    return GovernanceDocumentProjectionClaim(
        version=GovernanceDocumentVersion(
            version_id=version_id,
            workspace_id=workspace_id,
            document_id=document_id,
            version_number=1,
            version_tag="v1",
            state=GovernanceDocumentVersionState.PUBLISHED,
            title="Finance Data Policy",
            summary="Approved policy",
            applicability_scope="dataset:finance.orders, term:Customer",
            sanitized_html="<p>Approved policy</p>",
            plain_text="Approved policy",
            content_sha256="b" * 64,
            size_bytes=22,
            sanitizer_policy_version="GOVERNANCE_HTML_SANITIZER_V2_BLEACH",
            sanitizer_policy_sha256="c" * 64,
            source_format=GovernanceDocumentSourceFormat.HTML,
            source_template_version_id=None,
            parent_document_id=None,
            author_id=uuid4(),
            submitted_at=NOW,
            reviewed_by=uuid4(),
            reviewed_at=NOW,
            published_at=NOW,
            artifact_state=GovernanceDocumentArtifactState.STORED,
            knowledge_state=GovernanceDocumentKnowledgeState.PROJECTING,
            created_at=NOW,
            version=3,
        ),
        kind=GovernanceDocumentKind.DOCUMENT,
        category=GovernanceDocumentCategory.POLICY,
        classification=Classification.INTERNAL,
    )
