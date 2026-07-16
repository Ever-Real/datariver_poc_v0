from __future__ import annotations

from typing import Any
from uuid import UUID

from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import DataHubGateway, GovernanceApplyStore
from datariver.domain.common import ConflictError, DomainError, canonical_json_hash
from datariver.domain.governance import ALLOWED_DATAHUB_ASPECTS


class GovernanceApplyWorker:
    """Applies approved typed aspects and only completes after a DataHub re-read."""

    def __init__(
        self,
        *,
        store: GovernanceApplyStore,
        datahub: DataHubGateway,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int = 120,
        maximum_attempts: int = 8,
    ) -> None:
        self._store = store
        self._datahub = datahub
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
            expected, observed, item_results = await self._apply_items(claim.change_request.items)
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

    async def _apply_items(self, items: list[Any]) -> tuple[str, str, list[dict[str, Any]]]:
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
            current = await self._datahub.read_aspect(
                external_urn=item.target_ref, aspect_name=item.aspect_name
            )
            if current.content_hash == expected_hash:
                expected_items.append({"item_id": str(item.item_id), "content_hash": expected_hash})
                observed_items.append(
                    {"item_id": str(item.item_id), "content_hash": current.content_hash}
                )
                results.append(
                    {
                        "item_id": str(item.item_id),
                        "operation_id": "reconciled-existing",
                        "provider_version": current.source_version,
                        "source_version": current.source_version,
                        "content_hash": current.content_hash,
                    }
                )
                continue
            if current.content_hash != item.before_hash:
                raise ConflictError(
                    "DataHub changed after this request was prepared.",
                    details={"item_id": str(item.item_id), "code": "BEFORE_HASH_MISMATCH"},
                )
            receipt = await self._datahub.apply_change(
                external_urn=item.target_ref,
                aspect_name=item.aspect_name,
                document=item.after_document,
                idempotency_key=f"{item.item_id}:{expected_hash}",
            )
            snapshot = await self._datahub.read_aspect(
                external_urn=item.target_ref, aspect_name=item.aspect_name
            )
            if snapshot.content_hash != expected_hash:
                raise ConflictError(
                    "DataHub did not reconcile to the approved aspect content.",
                    details={"item_id": str(item.item_id), "code": "AFTER_HASH_MISMATCH"},
                )
            expected_items.append({"item_id": str(item.item_id), "content_hash": expected_hash})
            observed_items.append(
                {"item_id": str(item.item_id), "content_hash": snapshot.content_hash}
            )
            results.append(
                {
                    "item_id": str(item.item_id),
                    "operation_id": receipt.operation_id,
                    "provider_version": receipt.provider_version,
                    "source_version": snapshot.source_version,
                    "content_hash": snapshot.content_hash,
                }
            )
        return (
            canonical_json_hash(expected_items),
            canonical_json_hash(observed_items),
            results,
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
