from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError
from datariver.domain.sharing import (
    ApiProduct,
    ApiProductState,
    ConsumerGrant,
    ConsumerGrantState,
)
from datariver.infrastructure.db.models.knowledge import ReleaseModel
from datariver.infrastructure.db.sharing import SqlSharingStore
from datariver.interfaces.http.schemas import ApiProductCreate


def test_api_product_publish_is_owner_and_version_guarded() -> None:
    owner = uuid4()
    product = ApiProduct(
        product_id=uuid4(),
        workspace_id=uuid4(),
        owner_id=owner,
        classification=Classification.CONFIDENTIAL,
    )

    with pytest.raises(ForbiddenError):
        product.publish(actor_id=uuid4(), expected_version=1)

    product.publish(actor_id=owner, expected_version=1)

    assert product.state is ApiProductState.PUBLISHED
    assert product.version == 2
    with pytest.raises(ConflictError):
        product.publish(actor_id=owner, expected_version=1)


def test_consumer_grant_binds_client_scope_time_and_classification() -> None:
    now = datetime.now(UTC)
    grant = ConsumerGrant(
        grant_id=uuid4(),
        workspace_id=uuid4(),
        product_id=uuid4(),
        product_version_id=uuid4(),
        consumer_client_id="analytics-client",
        scopes=frozenset({"neighbors.query"}),
        maximum_classification=Classification.CONFIDENTIAL,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        requests_per_minute=60,
        monthly_quota=1000,
        state=ConsumerGrantState.ACTIVE,
    )

    grant.authorize(
        now=now,
        consumer_client_id="analytics-client",
        requested_scope="neighbors.query",
        product_classification=Classification.CONFIDENTIAL,
    )

    with pytest.raises(ForbiddenError):
        grant.authorize(
            now=now,
            consumer_client_id="another-client",
            requested_scope="neighbors.query",
            product_classification=Classification.CONFIDENTIAL,
        )
    with pytest.raises(ForbiddenError):
        replace(grant, state=ConsumerGrantState.REVOKED).authorize(
            now=now,
            consumer_client_id="analytics-client",
            requested_scope="neighbors.query",
            product_classification=Classification.CONFIDENTIAL,
        )


def test_api_contract_surface_requires_matching_scope() -> None:
    base = {
        "slug": "supply-network",
        "name": "Supply network",
        "description": "Bounded release-pinned neighbor analysis",
        "graph_id": str(uuid4()),
        "release_id": str(uuid4()),
        "surface": "NEIGHBORS",
        "contract": {
            "scopes": ["neighbors.query"],
            "response_schema": {"type": "object"},
            "query_template": "neighbors-v1",
        },
        "maximum_hops": 2,
        "maximum_nodes": 200,
        "timeout_ms": 5000,
    }

    assert ApiProductCreate.model_validate(base).surface == "NEIGHBORS"
    base["contract"] = {
        "scopes": ["snapshot.read"],
        "response_schema": {"type": "object"},
        "query_template": "neighbors-v1",
    }
    with pytest.raises(ValueError):
        ApiProductCreate.model_validate(base)


def test_full_view_api_contract_rejects_release_above_memory_bound() -> None:
    release = ReleaseModel(
        id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        release_no=1,
        ontology_version_id=uuid4(),
        content_hash="a" * 64,
        node_count=257,
        edge_count=279,
        manifest_ref=None,
        published_by=uuid4(),
        published_at=datetime.now(UTC),
        deprecated_at=None,
    )

    with pytest.raises(ValidationError):
        SqlSharingStore._validate_release_bound(
            release=release,
            surface="CHAT",
            maximum_nodes=200,
        )
    SqlSharingStore._validate_release_bound(
        release=release,
        surface="CHAT",
        maximum_nodes=500,
    )
    SqlSharingStore._validate_release_bound(
        release=release,
        surface="NEIGHBORS",
        maximum_nodes=200,
    )
