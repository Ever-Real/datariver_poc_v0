from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

import pytest

from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.sharing_invocation import (
    MAX_CANONICAL_RESULT_BYTES,
    CompletedInvocation,
    InvocationRequestBinding,
    LegacyInvocation,
    canonical_invocation_request_hash,
    execute_or_replay_invocation,
    validate_canonical_result,
)


def _binding() -> InvocationRequestBinding:
    return InvocationRequestBinding(
        workspace_id=uuid4(),
        subject_id=uuid4(),
        consumer_issuer="https://identity.example.test/realms/datariver",
        consumer_client_id="catalog-consumer",
        security_scopes=frozenset({"sharing:invoke", "workspace:read"}),
        grant_id=uuid4(),
        product_id=uuid4(),
        product_version_id=uuid4(),
        graph_id=uuid4(),
        release_id=uuid4(),
        release_content_hash="a" * 64,
        contract_hash="b" * 64,
        effective_classification=2,
        surface="NEIGHBORS",
        operation="READ",
        result_type="NEIGHBOR_ANALYSIS_V1",
        requested_scope="neighbors.query",
        payload_document={
            "node_id": str(uuid4()),
            "direction": "BOTH",
            "edge_types": ["SUPPLIES", "DEPENDS_ON"],
            "maximum_hops": 2,
            "maximum_nodes": 50,
        },
        request_id="request-0001",
        invocation_key="invocation-key-0001",
    )


def test_neighbors_request_hash_treats_edge_types_as_an_unordered_selection() -> None:
    original = _binding()
    reordered = replace(
        original,
        payload_document={
            **original.payload_document,
            "edge_types": ["DEPENDS_ON", "SUPPLIES"],
        },
    )

    assert canonical_invocation_request_hash(original) == canonical_invocation_request_hash(
        reordered
    )


@pytest.mark.parametrize(
    "changed",
    [
        lambda binding: replace(
            binding,
            payload_document={**binding.payload_document, "maximum_hops": 1},
        ),
        lambda binding: replace(binding, subject_id=uuid4()),
        lambda binding: replace(
            binding,
            consumer_issuer="https://another-identity.example.test/realms/datariver",
        ),
        lambda binding: replace(binding, consumer_client_id="another-consumer"),
        lambda binding: replace(
            binding,
            security_scopes=frozenset({"sharing:invoke"}),
        ),
        lambda binding: replace(binding, grant_id=uuid4()),
        lambda binding: replace(binding, product_id=uuid4()),
        lambda binding: replace(binding, product_version_id=uuid4()),
        lambda binding: replace(binding, graph_id=uuid4()),
        lambda binding: replace(binding, release_id=uuid4()),
        lambda binding: replace(binding, release_content_hash="c" * 64),
        lambda binding: replace(binding, contract_hash="d" * 64),
        lambda binding: replace(binding, effective_classification=1),
        lambda binding: replace(binding, surface="SNAPSHOT"),
        lambda binding: replace(binding, operation="EXPORT"),
        lambda binding: replace(binding, result_type="KNOWLEDGE_SNAPSHOT_V1"),
        lambda binding: replace(binding, requested_scope="snapshot.read"),
    ],
    ids=[
        "payload",
        "subject",
        "issuer",
        "client",
        "security-scope",
        "grant",
        "product",
        "version",
        "graph",
        "release",
        "release-content",
        "contract",
        "classification",
        "surface",
        "operation",
        "result-type",
        "scope",
    ],
)
def test_request_hash_binds_every_authorization_and_execution_input(
    changed: Callable[[InvocationRequestBinding], InvocationRequestBinding],
) -> None:
    original = _binding()

    assert canonical_invocation_request_hash(original) != canonical_invocation_request_hash(
        changed(original)
    )


def test_request_hash_excludes_transport_and_observability_identifiers() -> None:
    original = _binding()
    retried = replace(
        original,
        request_id="request-0002",
        invocation_key="invocation-key-0002",
    )

    assert canonical_invocation_request_hash(original) == canonical_invocation_request_hash(retried)


def test_canonical_result_accepts_exactly_one_mib_and_rejects_one_byte_more() -> None:
    assert MAX_CANONICAL_RESULT_BYTES == 1_048_576
    empty_document_bytes = len(
        json.dumps(
            {"payload": ""},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    maximum_document = {"payload": "x" * (MAX_CANONICAL_RESULT_BYTES - empty_document_bytes)}
    oversized_document = {"payload": "x" * (MAX_CANONICAL_RESULT_BYTES - empty_document_bytes + 1)}

    validate_canonical_result(maximum_document)
    with pytest.raises(ValidationError):
        validate_canonical_result(oversized_document)
    with pytest.raises(ValidationError):
        validate_canonical_result(["a JSON array is not a result document"])


@pytest.mark.asyncio
async def test_legacy_invocation_without_a_bound_result_cannot_be_replayed() -> None:
    executor_calls = 0

    async def executor() -> dict[str, object]:
        nonlocal executor_calls
        executor_calls += 1
        return {"status": "must-not-run"}

    with pytest.raises(ConflictError):
        await execute_or_replay_invocation(
            existing=LegacyInvocation(invocation_id=uuid4()),
            request_hash=canonical_invocation_request_hash(_binding()),
            executor=executor,
        )

    assert executor_calls == 0


@pytest.mark.asyncio
async def test_completed_invocation_replays_exact_document_without_executor() -> None:
    executor_calls = 0
    binding = _binding()
    request_hash = canonical_invocation_request_hash(binding)
    stored_document: dict[str, object] = {
        "release": {
            "id": str(binding.release_id),
            "content_hash": "a" * 64,
        },
        "nodes": [
            {
                "id": str(uuid4()),
                "properties": {"name": "Canonical supplier"},
            }
        ],
        "edges": [],
        "truncated": False,
    }

    async def executor() -> dict[str, object]:
        nonlocal executor_calls
        executor_calls += 1
        return {"status": "must-not-run"}

    replayed = await execute_or_replay_invocation(
        existing=CompletedInvocation(
            invocation_id=uuid4(),
            request_hash=request_hash,
            result_document=stored_document,
        ),
        request_hash=request_hash,
        executor=executor,
    )

    assert replayed == stored_document
    assert json.dumps(
        replayed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) == json.dumps(
        stored_document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert executor_calls == 0
