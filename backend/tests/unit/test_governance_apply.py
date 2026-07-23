from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
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
    DataHubVocabularyScanPage,
    GovernanceApplyAuthorizationContext,
    GovernanceApplyClaim,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.services.governance_apply import GovernanceApplyWorker
from datariver.domain.authz import Action, Classification
from datariver.domain.common import canonical_json_hash
from datariver.domain.governance import (
    ChangeItem,
    ChangeRequest,
    change_target_binding_hash,
)


class MemoryApplyStore:
    def __init__(self, claim: GovernanceApplyClaim) -> None:
        self.claim: GovernanceApplyClaim | None = claim
        self.applied: tuple[str, str] | None = None
        self.failed: tuple[str, bool] | None = None
        self.lease_renewals = 0

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

    async def renew_lease(self, **_: object) -> bool:
        self.lease_renewals += 1
        return True


class MemoryProviderMutationLock:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    @asynccontextmanager
    async def hold(self, **kwargs: object) -> AsyncIterator[None]:
        self.calls.append(kwargs)
        yield


class MemoryApplyReauthorizer:
    def __init__(
        self,
        *,
        allowed: bool = True,
        error: Exception | None = None,
        deny_on_call: int | None = None,
    ) -> None:
        self.allowed = allowed
        self.error = error
        self.deny_on_call = deny_on_call
        self.calls: list[GovernanceApplyAuthorizationContext] = []

    async def reauthorize(self, *, context: GovernanceApplyAuthorizationContext) -> bool:
        self.calls.append(context)
        if self.error is not None:
            raise self.error
        return self.allowed and len(self.calls) != self.deny_on_call


class MemoryDataHub:
    def __init__(
        self,
        *,
        observed_hash: str,
        before_hash: str = "b" * 64,
        apply_error: ExternalDependencyError | None = None,
    ) -> None:
        self.observed_hash = observed_hash
        self.before_hash = before_hash
        self.apply_error = apply_error
        self.applied = 0
        self.reads = 0

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
        if self.apply_error is not None:
            raise self.apply_error
        return DataHubApplyReceipt("op-1", datetime.now(UTC), "1", "r" * 64)

    async def read_aspect(self, *, external_urn: str, aspect_name: str) -> DataHubAspectSnapshot:
        self.reads += 1
        return DataHubAspectSnapshot(
            external_urn,
            aspect_name,
            self.before_hash if self.reads == 1 else self.observed_hash,
            "v1",
            datetime.now(UTC),
        )

    async def get_asset(self, external_urn: str) -> Any:
        raise NotImplementedError(external_urn)

    async def get_lineage(
        self, *, external_urn: str, direction: str, depth: int
    ) -> DataHubLineagePage:
        raise NotImplementedError(external_urn, direction, depth)

    async def capability(self) -> CapabilityStatus:
        return CapabilityStatus("datahub", "healthy", datetime.now(UTC))

    async def scan_assets(self, *, cursor: str | None, limit: int) -> DataHubScanPage:
        raise NotImplementedError(cursor, limit)

    async def scan_vocabulary(
        self,
        *,
        kind: str,
        cursor: str | None,
        limit: int,
    ) -> DataHubVocabularyScanPage:
        raise NotImplementedError(kind, cursor, limit)

    async def search_vocabulary(self, *, kind: str, query: str, limit: int) -> tuple[str, ...]:
        raise NotImplementedError(kind, query, limit)


def make_claim(
    *,
    aspect_name: str = "datasetProperties",
    document: dict[str, Any] | None = None,
    request_type: str = "CATALOG_METADATA",
) -> tuple[GovernanceApplyClaim, str]:
    document = document or {"description": "governed"}
    expected_hash = canonical_json_hash(document)
    asset_id = uuid4()
    target_ref = "urn:li:dataset:test"
    request = ChangeRequest.create(
        workspace_id=uuid4(),
        number="CR-1",
        request_type=request_type,
        title="Update",
        description="",
        requester_id=uuid4(),
        items=[
            ChangeItem(
                item_id=uuid4(),
                target_type="DATAHUB_ASPECT",
                target_ref=target_ref,
                operation="UPSERT",
                after_document=document,
                aspect_name=aspect_name,
                before_hash="b" * 64,
                after_hash=expected_hash,
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_classification=Classification.INTERNAL,
                target_lifecycle="ACTIVE",
                target_source_version="1",
                target_observed_at=datetime.now(UTC),
                target_binding_hash=change_target_binding_hash(
                    target_ref=target_ref,
                    asset_id=asset_id,
                    asset_type="DATASET",
                    system_id=None,
                    domain_id=None,
                    owner_department_id=None,
                    classification=Classification.INTERNAL,
                    lifecycle="ACTIVE",
                ),
            )
        ],
    )
    return GovernanceApplyClaim(request, uuid4(), uuid4(), 1, "lease-token", uuid4()), expected_hash


TYPED_CATALOG_METADATA_ASPECTS = (
    ("datasetProperties", {"description": "governed"}),
    (
        "schemaMetadata",
        {"fields": [{"fieldPath": "event_id", "description": "governed"}]},
    ),
    ("domains", {"domains": ["urn:li:domain:manufacturing"]}),
    ("glossaryTerms", {"terms": [{"urn": "urn:li:glossaryTerm:wafer"}]}),
    ("globalTags", {"tags": [{"tag": "urn:li:tag:governed"}]}),
)


@pytest.mark.asyncio
async def test_worker_only_marks_applied_after_equal_reread_hash() -> None:
    claim, expected_hash = make_claim()
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    provider_lock = MemoryProviderMutationLock()
    reauthorizer = MemoryApplyReauthorizer()
    system_actor_id = uuid4()
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=provider_lock,
        reauthorizer=reauthorizer,
        worker_id="worker-1",
        system_actor_id=system_actor_id,
    )

    assert await worker.run_once() is True
    assert gateway.applied == 1
    assert store.applied is not None
    assert store.applied[0] == store.applied[1]
    assert store.failed is None
    assert store.lease_renewals >= 5
    assert len(provider_lock.calls) == 1
    assert {key: value for key, value in provider_lock.calls[0].items() if key != "on_wait"} == {
        "workspace_id": claim.change_request.workspace_id,
        "provider": "DATAHUB",
        "target_ref": claim.change_request.items[0].target_ref,
        "aspect_name": "*",
    }
    assert callable(provider_lock.calls[0]["on_wait"])
    assert len(reauthorizer.calls) == 3
    authorization_context = reauthorizer.calls[0]
    assert authorization_context.workspace_id == claim.change_request.workspace_id
    assert authorization_context.change_request_id == claim.change_request.change_request_id
    assert authorization_context.requester_id == claim.change_request.requester_id
    assert authorization_context.requester_id != system_actor_id
    assert authorization_context.action is Action.CHANGE_CREATE
    assert authorization_context.item_id == claim.change_request.items[0].item_id
    assert authorization_context.target_asset_id == claim.change_request.items[0].target_asset_id
    assert authorization_context.target_ref == claim.change_request.items[0].target_ref
    assert (
        authorization_context.target_binding_hash
        == claim.change_request.items[0].target_binding_hash
    )
    assert authorization_context.job_id == claim.job_id
    assert authorization_context.attempt_id == claim.attempt_id
    assert authorization_context.attempt_no == claim.attempt_no
    assert authorization_context.worker_subject_id == claim.worker_subject_id
    assert (
        authorization_context.lease_token_hash
        == hashlib.sha256(claim.lease_token.encode()).hexdigest()
    )
    assert reauthorizer.calls[1] == authorization_context
    assert reauthorizer.calls[2] == authorization_context


@pytest.mark.asyncio
@pytest.mark.parametrize(("aspect_name", "document"), TYPED_CATALOG_METADATA_ASPECTS)
async def test_each_typed_catalog_metadata_aspect_uses_the_same_readback_fence(
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    claim, expected_hash = make_claim(
        aspect_name=aspect_name,
        document=document,
        request_type="BULK_CATALOG_METADATA",
    )
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=claim.worker_subject_id,
    )

    assert await worker.run_once() is True
    assert gateway.applied == 1
    assert gateway.reads == 2
    assert store.applied is not None
    assert store.failed is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("aspect_name", "document"), TYPED_CATALOG_METADATA_ASPECTS)
async def test_each_typed_catalog_metadata_aspect_rejects_a_stale_before_hash(
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    claim, expected_hash = make_claim(
        aspect_name=aspect_name,
        document=document,
        request_type="BULK_CATALOG_METADATA",
    )
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash, before_hash="0" * 64)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=claim.worker_subject_id,
    )

    assert await worker.run_once() is True
    assert gateway.applied == 0
    assert store.applied is None
    assert store.failed == ("BEFORE_HASH_MISMATCH", False)


@pytest.mark.asyncio
@pytest.mark.parametrize(("aspect_name", "document"), TYPED_CATALOG_METADATA_ASPECTS)
async def test_each_typed_catalog_metadata_aspect_reconciles_an_ambiguous_prior_success(
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    claim, expected_hash = make_claim(
        aspect_name=aspect_name,
        document=document,
        request_type="BULK_CATALOG_METADATA",
    )
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash, before_hash=expected_hash)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=claim.worker_subject_id,
    )

    assert await worker.run_once() is True
    assert gateway.reads == 1
    assert gateway.applied == 0
    assert store.applied is not None
    assert store.failed is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("aspect_name", "document"), TYPED_CATALOG_METADATA_ASPECTS)
async def test_each_typed_catalog_metadata_aspect_classifies_transient_write_for_retry(
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    claim, expected_hash = make_claim(
        aspect_name=aspect_name,
        document=document,
        request_type="BULK_CATALOG_METADATA",
    )
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(
        observed_hash=expected_hash,
        apply_error=ExternalDependencyError(
            "Provider completion is ambiguous.",
            dependency="datahub",
            retryable=True,
        ),
    )
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=claim.worker_subject_id,
    )

    assert await worker.run_once() is True
    assert gateway.applied == 1
    assert store.applied is None
    assert store.failed == ("external_dependency_error", True)


@pytest.mark.asyncio
@pytest.mark.parametrize(("aspect_name", "document"), TYPED_CATALOG_METADATA_ASPECTS)
async def test_worker_fails_closed_on_reconciliation_mismatch(
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    claim, _ = make_claim(
        aspect_name=aspect_name,
        document=document,
        request_type="BULK_CATALOG_METADATA",
    )
    store = MemoryApplyStore(claim)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=MemoryDataHub(observed_hash="0" * 64),
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert store.applied is None
    assert store.failed == ("AFTER_HASH_MISMATCH", False)


@pytest.mark.asyncio
async def test_worker_reconciles_provider_success_after_lost_completion_record() -> None:
    claim, expected_hash = make_claim()
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash, before_hash=expected_hash)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert gateway.reads == 1
    assert gateway.applied == 0
    assert store.applied is not None
    assert store.failed is None


@pytest.mark.asyncio
async def test_worker_rejects_legacy_multi_item_claim_before_provider_read() -> None:
    claim, expected_hash = make_claim()
    claim.change_request.items.append(claim.change_request.items[0])
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert gateway.reads == 0
    assert gateway.applied == 0
    assert store.failed == ("MULTI_ITEM_APPLY_DISABLED", False)


@pytest.mark.asyncio
async def test_worker_revalidates_legacy_queued_item_contract() -> None:
    claim, expected_hash = make_claim()
    original = claim.change_request.items[0]
    claim.change_request.items[0] = ChangeItem(
        item_id=original.item_id,
        target_type=original.target_type,
        target_ref=original.target_ref,
        operation=original.operation,
        after_document=original.after_document,
        aspect_name="unsafeLegacyAspect",
        before_hash=original.before_hash,
        after_hash=original.after_hash,
    )
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert gateway.reads == 0
    assert gateway.applied == 0
    assert store.failed == ("UNSAFE_QUEUED_CHANGE", False)


@pytest.mark.asyncio
async def test_worker_rejects_legacy_unbound_item_before_provider_read() -> None:
    claim, expected_hash = make_claim()
    original = claim.change_request.items[0]
    claim.change_request.items[0] = ChangeItem(
        item_id=original.item_id,
        target_type=original.target_type,
        target_ref=original.target_ref,
        operation=original.operation,
        after_document=original.after_document,
        aspect_name=original.aspect_name,
        before_hash=original.before_hash,
        after_hash=original.after_hash,
    )
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=MemoryApplyReauthorizer(),
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert gateway.reads == 0
    assert gateway.applied == 0
    assert store.failed == ("UNSAFE_QUEUED_CHANGE", False)


@pytest.mark.asyncio
async def test_worker_denied_reauthorization_is_terminal_before_provider_access() -> None:
    claim, expected_hash = make_claim()
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    provider_lock = MemoryProviderMutationLock()
    reauthorizer = MemoryApplyReauthorizer(allowed=False)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=provider_lock,
        reauthorizer=reauthorizer,
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert len(reauthorizer.calls) == 1
    assert gateway.reads == 0
    assert gateway.applied == 0
    assert len(provider_lock.calls) == 1
    assert store.applied is None
    assert store.failed == ("APPLY_REAUTHORIZATION_DENIED", False)


@pytest.mark.asyncio
async def test_worker_reauthorization_error_is_terminal_before_provider_access() -> None:
    claim, expected_hash = make_claim()
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    provider_lock = MemoryProviderMutationLock()
    reauthorizer = MemoryApplyReauthorizer(
        error=ExternalDependencyError(
            "Local policy state could not be refreshed.",
            dependency="postgresql",
            retryable=True,
        )
    )
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=provider_lock,
        reauthorizer=reauthorizer,
        worker_id="worker-1",
        system_actor_id=uuid4(),
    )

    assert await worker.run_once() is True
    assert len(reauthorizer.calls) == 1
    assert gateway.reads == 0
    assert gateway.applied == 0
    assert len(provider_lock.calls) == 1
    assert store.applied is None
    assert store.failed == ("APPLY_REAUTHORIZATION_FAILED", False)


@pytest.mark.asyncio
async def test_worker_reauthorizes_again_immediately_before_provider_write() -> None:
    claim, expected_hash = make_claim()
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    reauthorizer = MemoryApplyReauthorizer(deny_on_call=2)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=reauthorizer,
        worker_id="worker-1",
        system_actor_id=claim.worker_subject_id,
    )

    assert await worker.run_once() is True
    assert len(reauthorizer.calls) == 2
    assert gateway.reads == 1
    assert gateway.applied == 0
    assert store.applied is None
    assert store.failed == ("APPLY_REAUTHORIZATION_DENIED", False)


@pytest.mark.asyncio
async def test_worker_reauthorizes_again_immediately_before_provider_readback() -> None:
    claim, expected_hash = make_claim()
    store = MemoryApplyStore(claim)
    gateway = MemoryDataHub(observed_hash=expected_hash)
    reauthorizer = MemoryApplyReauthorizer(deny_on_call=3)
    worker = GovernanceApplyWorker(
        store=store,
        datahub=gateway,
        provider_mutation_lock=MemoryProviderMutationLock(),
        reauthorizer=reauthorizer,
        worker_id="worker-1",
        system_actor_id=claim.worker_subject_id,
    )

    assert await worker.run_once() is True
    assert len(reauthorizer.calls) == 3
    assert gateway.reads == 1
    assert gateway.applied == 1
    assert store.applied is None
    assert store.failed == ("APPLY_REAUTHORIZATION_DENIED", False)
