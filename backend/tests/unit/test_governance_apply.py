from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    CapabilityStatus,
    DataHubApplyReceipt,
    DataHubAspectSnapshot,
    DataHubLineagePage,
    DataHubScanPage,
    GovernanceApplyClaim,
)
from datariver.application.services.governance_apply import GovernanceApplyWorker
from datariver.domain.common import canonical_json_hash
from datariver.domain.governance import ChangeItem, ChangeRequest


class MemoryApplyStore:
    def __init__(self, claim: GovernanceApplyClaim) -> None:
        self.claim: GovernanceApplyClaim | None = claim
        self.applied: tuple[str, str] | None = None
        self.failed: tuple[str, bool] | None = None

    async def claim_next(
        self,
        *,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> GovernanceApplyClaim | None:
        del worker_id, system_actor_id, lease_seconds, maximum_attempts
        value, self.claim = self.claim, None
        return value

    async def mark_applied(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        expected_hash: str,
        observed_hash: str,
        item_results: Sequence[dict[str, Any]],
    ) -> None:
        del claim, system_actor_id, item_results
        self.applied = (expected_hash, observed_hash)

    async def mark_failed(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        del claim, system_actor_id, maximum_attempts
        self.failed = (error_code, retryable)


class MemoryDataHub:
    def __init__(self, *, observed_hash: str) -> None:
        self.observed_hash = observed_hash
        self.applied = 0

    async def apply_change(
        self,
        *,
        external_urn: str,
        aspect_name: str,
        document: dict[str, Any],
        idempotency_key: str,
    ) -> DataHubApplyReceipt:
        del external_urn, aspect_name, document, idempotency_key
        self.applied += 1
        return DataHubApplyReceipt("op-1", datetime.now(UTC), "1", "r" * 64)

    async def read_aspect(self, *, external_urn: str, aspect_name: str) -> DataHubAspectSnapshot:
        return DataHubAspectSnapshot(
            external_urn, aspect_name, self.observed_hash, "v1", datetime.now(UTC)
        )

    async def get_asset(self, external_urn: str) -> Any:
        raise NotImplementedError(external_urn)

    async def get_lineage(
        self, *, external_urn: str, direction: str, depth: int
    ) -> DataHubLineagePage:
        raise NotImplementedError(external_urn, direction, depth)

    async def capability(self) -> CapabilityStatus:
        return CapabilityStatus("datahub", "healthy", datetime.now(UTC))

    async def scan_assets(self, *, offset: int, limit: int) -> DataHubScanPage:
        raise NotImplementedError(offset, limit)


def make_claim() -> tuple[GovernanceApplyClaim, str]:
    document = {"description": "governed"}
    expected_hash = canonical_json_hash(document)
    request = ChangeRequest.create(
        workspace_id=uuid4(),
        number="CR-1",
        request_type="CATALOG_METADATA",
        title="Update",
        description="",
        requester_id=uuid4(),
        items=[
            ChangeItem(
                item_id=uuid4(),
                target_type="DATAHUB_ASPECT",
                target_ref="urn:li:dataset:test",
                operation="UPSERT",
                after_document=document,
                aspect_name="datasetProperties",
                after_hash=expected_hash,
            )
        ],
    )
    return GovernanceApplyClaim(request, uuid4(), uuid4(), 1), expected_hash


@pytest.mark.asyncio
async def test_worker_only_marks_applied_after_equal_reread_hash() -> None:
    claim, expected_hash = make_claim()
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert gateway.applied == 1
    assert store.applied is not None
    assert store.applied[0] == store.applied[1]
    assert store.failed is None


@pytest.mark.asyncio
async def test_worker_fails_closed_on_reconciliation_mismatch() -> None:
    claim, _ = make_claim()
    store = MemoryApplyStore(claim)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=MemoryDataHub(observed_hash="0" * 64),
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert store.applied is None
    assert store.failed == ("AFTER_HASH_MISMATCH", False)
