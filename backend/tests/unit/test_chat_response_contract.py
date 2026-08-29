from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from datariver.application.dto import (
    ChatAuthorizedDiscovery,
    ChatEvidence,
    ChatEvidenceRanking,
    ChatMessageRecord,
)
from datariver.domain.authz import Classification
from datariver.interfaces.http.routes.chat import _discovery_response, _message_response


def _evidence(name: str) -> ChatEvidence:
    return ChatEvidence(
        chunk_id=uuid4(),
        workspace_id=uuid4(),
        resource_id=uuid4(),
        classification=Classification.INTERNAL,
        system_id=None,
        domain_id=None,
        owner_department_id=None,
        name=name,
        description=f"Authorized description for {name}",
        source_locator=f"urn:li:dataset:{name}",
        source_version="v1",
        content_hash="a" * 64,
        effective_from=datetime(2026, 8, 29, tzinfo=UTC),
        effective_until=None,
        extraction_method="CATALOG_PROJECTION_V2",
    )


def test_query_discovery_envelope_is_bounded_without_invented_cardinality() -> None:
    items = tuple(_evidence(f"asset-{index}") for index in range(20))
    discovery = ChatAuthorizedDiscovery(
        items=items,
        rankings=tuple(
            ChatEvidenceRanking(
                chunk_id=item.chunk_id,
                rank=index,
                retrieval_method="VECTOR_RETRIEVAL_V1",
            )
            for index, item in enumerate(items, start=1)
        ),
        returned_count=20,
        limit=20,
        truncated=True,
        retrieved_count=20,
        reranked_count=5,
        answer_context_count=5,
        catalog_search_query="authorized assets",
        catalog_search_fields=("TABLE",),
    )

    payload = _discovery_response(discovery).model_dump(mode="json")

    assert payload["returned_count"] == len(payload["items"]) == 20
    assert payload["limit"] == 20
    assert payload["truncated"] is True
    assert payload["retrieved_count"] == 20
    assert payload["reranked_count"] == 5
    assert payload["answer_context_count"] == 5
    assert payload["catalog_search_query"] == "authorized assets"
    assert payload["catalog_search_fields"] == ["TABLE"]
    assert payload["total"] is None
    assert payload["total_exact"] is False
    assert payload["next_cursor"] is None
    assert [item["rank"] for item in payload["items"]] == list(range(1, 21))


def test_query_discovery_full_result_fields_remain_exact() -> None:
    items = tuple(_evidence(f"authorized-{index}") for index in range(3))
    discovery = ChatAuthorizedDiscovery(
        items=items,
        rankings=tuple(
            ChatEvidenceRanking(
                chunk_id=item.chunk_id,
                rank=index,
                retrieval_method="CATALOG_LEXICAL_V1",
            )
            for index, item in enumerate(items, start=1)
        ),
        returned_count=3,
        limit=8,
        truncated=False,
        retrieved_count=3,
        reranked_count=0,
        answer_context_count=3,
        catalog_search_query="authorized",
        catalog_search_fields=(),
    )

    payload = _discovery_response(discovery).model_dump(mode="json")

    assert [item["chunk_id"] for item in payload["items"]] == [str(item.chunk_id) for item in items]
    assert payload["returned_count"] == payload["retrieved_count"] == 3
    assert payload["limit"] == 8
    assert payload["truncated"] is False
    assert payload["catalog_search_query"] == "authorized"
    assert payload["catalog_search_fields"] == []
    assert payload["total"] is None
    assert payload["total_exact"] is False
    assert payload["next_cursor"] is None


def test_history_keeps_citations_and_omits_unpersisted_discovery() -> None:
    citation = _evidence("cited-asset")
    record = ChatMessageRecord(
        id=uuid4(),
        session_id=uuid4(),
        role="assistant",
        content="Grounded answer",
        evidence=(citation,),
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )

    payload = _message_response(record).model_dump(mode="json")

    assert [item["chunk_id"] for item in payload["evidence_json"]] == [str(citation.chunk_id)]
    assert payload["evidence_json"][0]["retrieval_method"] == "PERSISTED_CITATION_ORDER"
    assert payload["discovery_json"] is None
    assert "performance" not in payload
