from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.authz import Classification, SubjectAttributes
from datariver.infrastructure.db.governance_documents import (
    SqlGovernanceDocumentRepository,
)
from datariver.infrastructure.db.models.governance_documents import (
    GovernanceDocumentKnowledgeChunkModel,
)
from datariver.interfaces.http.routes.governance_documents import rag_router, router

ROOT = Path(__file__).resolve().parents[3]


class _Rows:
    def all(self) -> list[object]:
        return []


class _CapturingSession:
    def __init__(self) -> None:
        self.statement: Any | None = None

    async def execute(self, statement: Any) -> _Rows:
        self.statement = statement
        return _Rows()


def test_governance_chunk_metadata_uses_pgvector_with_dimension_constraint() -> None:
    table = cast(Table, GovernanceDocumentKnowledgeChunkModel.__table__)

    assert isinstance(table.c.embedding_vector.type, VECTOR)
    assert any(
        constraint.name == "ck_document_knowledge_chunks_embedding_vector_dimension_matches"
        and "vector_dims(embedding_vector) = embedding_dimension" in str(constraint.sqltext)
        for constraint in table.constraints
        if hasattr(constraint, "sqltext")
    )


def test_additive_and_canonical_migrations_install_the_same_vector_contract() -> None:
    additive = (ROOT / "backend/alembic/versions/0075_governance_pgvector.py").read_text(
        encoding="utf-8"
    )
    canonical = (ROOT / "backend/alembic/versions/0001_initial_schema.py").read_text(
        encoding="utf-8"
    )

    for migration in (additive, canonical):
        assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
        assert "embedding_vector" in migration
        assert "vector_dims(embedding_vector) = embedding_dimension" in migration
    assert "embedding::text::vector" in additive
    assert "pgvector.sqlalchemy.vector.VECTOR()" in canonical


@pytest.mark.asyncio
async def test_governance_vector_search_orders_in_postgres_after_scope_filters() -> None:
    workspace_id = uuid4()
    session = _CapturingSession()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="DATA_STEWARD",
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset(),
    )

    values = await SqlGovernanceDocumentRepository(cast(AsyncSession, session)).search_knowledge(
        workspace_id=workspace_id,
        subject=subject,
        query="retention policy",
        query_vector=(0.1, 0.2, 0.3),
        provider="approved-provider",
        model="approved-model",
        limit=8,
    )

    assert values == ()
    assert session.statement is not None
    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect()  # type: ignore[no-untyped-call]
        )
    )
    assert "embedding_vector <=>" in sql
    assert "embedding_dimension =" in sql
    assert "current_published_version_id =" in sql
    assert "documents.classification <=" in sql
    assert "document_knowledge_chunks.provider =" in sql
    assert "document_knowledge_chunks.model_identity =" in sql
    assert "ORDER BY" in sql
    assert "LIMIT" in sql


def test_governance_rag_and_exact_attachment_download_routes_are_typed() -> None:
    rag_routes = {
        (route.path, frozenset(route.methods or ()))
        for route in rag_router.routes
        if isinstance(route, APIRoute)
    }
    document_routes = {
        (route.path, frozenset(route.methods or ()))
        for route in router.routes
        if isinstance(route, APIRoute)
    }

    assert (
        "/governance/search/rag",
        frozenset({"POST"}),
    ) in rag_routes
    assert (
        "/governance/documents/{document_id}/attachments/{attachment_id}/download",
        frozenset({"GET"}),
    ) in document_routes
