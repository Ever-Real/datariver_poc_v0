from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from datariver.application.dto import (
    GovernanceApplyAuthorizationContext,
    GovernanceApplyClaim,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    DataHubGateway,
    GovernanceApplyReauthorizer,
    GovernanceApplyStore,
    ProviderMutationLock,
)
from datariver.domain.authz import Action
from datariver.domain.common import ConflictError, DomainError, canonical_json_hash
from datariver.domain.governance import ALLOWED_DATAHUB_ASPECTS


class GovernanceApplyWorker:
    """Applies approved typed aspects and only completes after a DataHub re-read."""

    def __init__(
        self,
        *,
        store: GovernanceApplyStore,
        datahub: DataHubGateway,
        provider_mutation_lock: ProviderMutationLock,
        reauthorizer: GovernanceApplyReauthorizer,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int = 120,
        maximum_attempts: int = 8,
    ) -> None:
        self._store = store
        self._datahub = datahub
        self._provider_mutation_lock = provider_mutation_lock
        self._reauthorizer = reauthorizer
        self._worker_id = worker_id
        self._system_actor_id = system_actor_id
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts

    async def run_once(self) -> bool:
        claim = await self._store.claim_next(
            worker_id=self._worker_id,
            system_actor_id=self._system_actor_id,
            lease_seconds=self._lease_seconds,
            maximum_attempts=self._maximum_attempts,
        )
        if claim is None:
            return False
        try:
            expected, observed, item_results = await self._apply_items(claim)
            await self._store.mark_applied(
                claim=claim,
                system_actor_id=self._system_actor_id,
                expected_hash=expected,
                observed_hash=observed,
                item_results=item_results,
            )
        except DomainError as error:
            await self._store.mark_failed(
                claim=claim,
                system_actor_id=self._system_actor_id,
                error_code=self._error_code(error),
                retryable=self._retryable(error),
                maximum_attempts=self._maximum_attempts,
            )
        except Exception as error:
            await self._store.mark_failed(
                claim=claim,
                system_actor_id=self._system_actor_id,
                error_code=f"UNEXPECTED_{type(error).__name__}"[:100],
                retryable=True,
                maximum_attempts=self._maximum_attempts,
            )
        return True

    async def _apply_items(
        self, claim: GovernanceApplyClaim
    ) -> tuple[str, str, list[dict[str, Any]]]:
        items = claim.change_request.items
        if len(items) != 1:
            raise ConflictError(
                "Multi-item apply is disabled until durable item checkpoints exist.",
                details={"code": "MULTI_ITEM_APPLY_DISABLED"},
            )
        expected_items: list[dict[str, str]] = []
        observed_items: list[dict[str, str]] = []
        results: list[dict[str, Any]] = []
        for item in items:
            if (
                item.target_type != "DATAHUB_ASPECT"
                or item.operation != "UPSERT"
                or item.aspect_name not in ALLOWED_DATAHUB_ASPECTS
                or not item.target_ref.startswith("urn:li:dataset:")
                or not item.has_complete_target_binding
                or item.expected_target_binding_hash() != item.target_binding_hash
            ):
                raise ConflictError(
                    "The queued provider change is outside the executable contract.",
                    details={"item_id": str(item.item_id), "code": "UNSAFE_QUEUED_CHANGE"},
                )
            if item.before_hash is None:
                raise ConflictError(
                    "The approved change is missing its source concurrency hash.",
                    details={"item_id": str(item.item_id), "code": "MISSING_BEFORE_HASH"},
                )
            expected_hash = item.after_hash or canonical_json_hash(item.after_document)
            expected_item, observed_item, result = await self._apply_one_item(
                claim=claim,
                item=item,
                expected_hash=expected_hash,
            )
            expected_items.append(expected_item)
            observed_items.append(observed_item)
            results.append(result)
        return (
            canonical_json_hash(expected_items),
            canonical_json_hash(observed_items),
            results,
        )

    async def _apply_one_item(
        self,
        *,
        claim: GovernanceApplyClaim,
        item: Any,
        expected_hash: str,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
        await self._renew_lease(claim)
        async with self._provider_mutation_lock.hold(
            workspace_id=claim.change_request.workspace_id,
            provider="DATAHUB",
            target_ref=item.target_ref,
            aspect_name="*",
            on_wait=lambda: self._renew_lease(claim),
        ):
            await self._renew_lease(claim)
            await self._reauthorize(claim=claim, item=item)
            await self._renew_lease(claim)
            current = await self._datahub.read_aspect(
                external_urn=item.target_ref, aspect_name=item.aspect_name
            )
            if current.content_hash == expected_hash:
                return (
                    {"item_id": str(item.item_id), "content_hash": expected_hash},
                    {"item_id": str(item.item_id), "content_hash": current.content_hash},
                    {
                        "item_id": str(item.item_id),
                        "operation_id": "reconciled-existing",
                        "provider_version": current.source_version,
                        "source_version": current.source_version,
                        "content_hash": current.content_hash,
                    },
                )
            if current.content_hash != item.before_hash:
                raise ConflictError(
                    "DataHub changed after this request was prepared.",
                    details={"item_id": str(item.item_id), "code": "BEFORE_HASH_MISMATCH"},
                )
            await self._renew_lease(claim)
            await self._reauthorize(claim=claim, item=item)
            receipt = await self._datahub.apply_change(
                external_urn=item.target_ref,
                aspect_name=item.aspect_name,
                document=item.after_document,
                idempotency_key=f"{item.item_id}:{expected_hash}",
            )
            await self._renew_lease(claim)
            await self._reauthorize(claim=claim, item=item)
            snapshot = await self._datahub.read_aspect(
                external_urn=item.target_ref, aspect_name=item.aspect_name
            )
            if snapshot.content_hash != expected_hash:
                raise ConflictError(
                    "DataHub did not reconcile to the approved aspect content.",
                    details={"item_id": str(item.item_id), "code": "AFTER_HASH_MISMATCH"},
                )
            await self._renew_lease(claim)
            return (
                {"item_id": str(item.item_id), "content_hash": expected_hash},
                {"item_id": str(item.item_id), "content_hash": snapshot.content_hash},
                {
                    "item_id": str(item.item_id),
                    "operation_id": receipt.operation_id,
                    "provider_version": receipt.provider_version,
                    "source_version": snapshot.source_version,
                    "content_hash": snapshot.content_hash,
                },
            )

    async def _reauthorize(self, *, claim: GovernanceApplyClaim, item: Any) -> None:
        # These assertions are backed by the executable-contract checks in
        # ``_apply_items``. The reauthorizer receives only server-loaded claim
        # state. The worker claim is included only to bind the current
        # database-time lease; it cannot substitute for the initiating human.
        assert item.target_asset_id is not None
        assert item.target_asset_type is not None
        assert item.target_classification is not None
        assert item.target_lifecycle is not None
        assert item.target_source_version is not None
        assert item.target_binding_hash is not None
        assert item.before_hash is not None
        after_hash = item.after_hash or canonical_json_hash(item.after_document)
        context = GovernanceApplyAuthorizationContext(
            workspace_id=claim.change_request.workspace_id,
            change_request_id=claim.change_request.change_request_id,
            change_request_version=claim.change_request.version,
            request_type=claim.change_request.request_type,
            requester_id=claim.change_request.requester_id,
            request_classification=claim.change_request.classification,
            item_id=item.item_id,
            action=Action.CHANGE_CREATE,
            target_type=item.target_type,
            target_ref=item.target_ref,
            operation=item.operation,
            aspect_name=item.aspect_name,
            before_hash=item.before_hash,
            after_hash=after_hash,
            target_asset_id=item.target_asset_id,
            target_asset_type=item.target_asset_type,
            target_system_id=item.target_system_id,
            target_domain_id=item.target_domain_id,
            target_owner_department_id=item.target_owner_department_id,
            target_classification=item.target_classification,
            target_lifecycle=item.target_lifecycle,
            target_source_version=item.target_source_version,
            target_binding_hash=item.target_binding_hash,
            job_id=claim.job_id,
            attempt_id=claim.attempt_id,
            attempt_no=claim.attempt_no,
            worker_subject_id=claim.worker_subject_id,
            lease_token_hash=hashlib.sha256(claim.lease_token.encode()).hexdigest(),
        )
        try:
            allowed = await self._reauthorizer.reauthorize(context=context)
        except Exception as error:
            raise ConflictError(
                "The initiating human and current target policy could not be reauthorized.",
                details={"code": "APPLY_REAUTHORIZATION_FAILED"},
            ) from error
        if not allowed:
            raise ConflictError(
                "The initiating human or current target policy no longer permits this apply.",
                details={"code": "APPLY_REAUTHORIZATION_DENIED"},
            )

    async def _renew_lease(self, claim: GovernanceApplyClaim) -> None:
        if not await self._store.renew_lease(
            claim=claim,
            lease_seconds=self._lease_seconds,
        ):
            raise ConflictError(
                "The governance apply lease was superseded.",
                details={"code": "LEASE_SUPERSEDED"},
            )

    @staticmethod
    def _retryable(error: DomainError) -> bool:
        return isinstance(error, ExternalDependencyError) and bool(
            error.details.get("retryable", False)
        )

    @staticmethod
    def _error_code(error: DomainError) -> str:
        return str(error.details.get("code") or error.details.get("provider_code") or error.code)[
            :100
        ]
