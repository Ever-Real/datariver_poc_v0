from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.common import ConflictError
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)
from datariver.infrastructure.db.models.integration import RegistrationWorkerCallReceiptModel


class SqlRegistrationWorkerCallReceipts:
    """Transaction-local worker call receipt operations.

    Callers deliberately share the canonical claim/terminal transaction's session.  This helper
    must never commit and must never be used around object-store or provider I/O.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock(
        self,
        *,
        workspace_id: UUID,
        identity: RegistrationWorkerCallIdentity,
    ) -> RegistrationWorkerCallReceiptModel | None:
        receipt = await self._session.scalar(
            select(RegistrationWorkerCallReceiptModel)
            .where(
                RegistrationWorkerCallReceiptModel.workspace_id == workspace_id,
                RegistrationWorkerCallReceiptModel.operation == identity.operation,
                RegistrationWorkerCallReceiptModel.key_hash == identity.key_hash,
            )
            .with_for_update()
        )
        if receipt is None:
            return None
        if (
            receipt.request_hash != identity.request_hash
            or receipt.worker_subject_id != identity.worker_subject_id
        ):
            raise ConflictError(
                "The worker run call conflicts with prior durable evidence.",
                details={"code": "WORKER_RUN_CALL_CONFLICT"},
            )
        return receipt

    @staticmethod
    def replay(receipt: RegistrationWorkerCallReceiptModel) -> RegistrationWorkerCallReplay:
        if receipt.state != "COMPLETED" or receipt.result is None:
            raise RuntimeError("The registration worker call receipt is not complete.")
        return RegistrationWorkerCallReplay(result=dict(receipt.result))

    @staticmethod
    def require_reclaimable(
        receipt: RegistrationWorkerCallReceiptModel,
        *,
        now: datetime,
    ) -> None:
        if receipt.state == "COMPLETED":
            return
        if receipt.lease_expires_at is None or receipt.lease_expires_at > now:
            raise ConflictError(
                "The worker run call is still in progress.",
                details={"code": "WORKER_RUN_IN_PROGRESS", "retryable": True},
            )

    async def start(
        self,
        *,
        workspace_id: UUID,
        identity: RegistrationWorkerCallIdentity,
        existing: RegistrationWorkerCallReceiptModel | None,
        work_kind: str,
        work_id: UUID,
        claim_attempt: int,
        raw_claim_token: str,
        lease_expires_at: datetime,
        now: datetime,
    ) -> None:
        token_hash = hashlib.sha256(raw_claim_token.encode()).hexdigest()
        await self._session.scalar(
            select(func.set_config("app.registration_worker_claim_token", raw_claim_token, True))
        )
        if existing is None:
            self._session.add(
                RegistrationWorkerCallReceiptModel(
                    workspace_id=workspace_id,
                    operation=identity.operation,
                    key_hash=identity.key_hash,
                    request_hash=identity.request_hash,
                    worker_subject_id=identity.worker_subject_id,
                    state="RUNNING",
                    work_kind=work_kind,
                    work_id=work_id,
                    claim_attempt=claim_attempt,
                    claim_token_hash=token_hash,
                    lease_expires_at=lease_expires_at,
                    processed=None,
                    result=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        existing.state = "RUNNING"
        existing.work_kind = work_kind
        existing.work_id = work_id
        existing.claim_attempt = claim_attempt
        existing.claim_token_hash = token_hash
        existing.lease_expires_at = lease_expires_at
        existing.processed = None
        existing.result = None
        existing.updated_at = now

    async def complete(
        self,
        *,
        receipt: RegistrationWorkerCallReceiptModel,
        result: dict[str, Any],
        now: datetime,
        raw_claim_token: str | None = None,
    ) -> None:
        if receipt.state == "COMPLETED":
            if receipt.result != result:
                raise ConflictError(
                    "The worker run call terminal result conflicts with prior evidence.",
                    details={"code": "WORKER_RUN_RESULT_CONFLICT"},
                )
            return
        if (
            raw_claim_token is not None
            and receipt.claim_token_hash != hashlib.sha256(raw_claim_token.encode()).hexdigest()
        ):
            raise ConflictError(
                "The worker run call claim is no longer current.",
                details={"code": "WORKER_RUN_CLAIM_SUPERSEDED"},
            )
        if raw_claim_token is not None:
            await self._session.scalar(
                select(
                    func.set_config("app.registration_worker_claim_token", raw_claim_token, True)
                )
            )
        processed = result.get("processed")
        if not isinstance(processed, bool):
            raise RuntimeError("A worker call result must include a boolean processed field.")
        receipt.state = "COMPLETED"
        receipt.processed = processed
        receipt.result = result
        receipt.claim_token_hash = None
        receipt.lease_expires_at = None
        receipt.updated_at = now

    async def complete_superseded_for_newer_claim(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        work_kind: str,
        work_id: UUID,
        newer_claim_attempt: int,
        newer_key_hash: str,
        result: dict[str, Any],
        now: datetime,
    ) -> None:
        """Terminalize expired call evidence once a distinct newer claim is durable."""
        stale_receipts = list(
            await self._session.scalars(
                select(RegistrationWorkerCallReceiptModel)
                .where(
                    RegistrationWorkerCallReceiptModel.workspace_id == workspace_id,
                    RegistrationWorkerCallReceiptModel.worker_subject_id == worker_subject_id,
                    RegistrationWorkerCallReceiptModel.state == "RUNNING",
                    RegistrationWorkerCallReceiptModel.work_kind == work_kind,
                    RegistrationWorkerCallReceiptModel.work_id == work_id,
                    RegistrationWorkerCallReceiptModel.claim_attempt < newer_claim_attempt,
                    RegistrationWorkerCallReceiptModel.key_hash != newer_key_hash,
                    RegistrationWorkerCallReceiptModel.lease_expires_at <= now,
                )
                .order_by(RegistrationWorkerCallReceiptModel.claim_attempt)
                .with_for_update()
            )
        )
        if stale_receipts:
            await self._session.scalar(
                select(func.set_config("app.registration_worker_claim_token", "", True))
            )
        for receipt in stale_receipts:
            await self.complete(receipt=receipt, result=result, now=now)

    async def complete_no_work(
        self,
        *,
        workspace_id: UUID,
        identity: RegistrationWorkerCallIdentity,
        existing: RegistrationWorkerCallReceiptModel | None,
        result: dict[str, Any],
        now: datetime,
    ) -> RegistrationWorkerCallReplay:
        if existing is None:
            existing = RegistrationWorkerCallReceiptModel(
                workspace_id=workspace_id,
                operation=identity.operation,
                key_hash=identity.key_hash,
                request_hash=identity.request_hash,
                worker_subject_id=identity.worker_subject_id,
                state="COMPLETED",
                work_kind=None,
                work_id=None,
                claim_attempt=None,
                claim_token_hash=None,
                lease_expires_at=None,
                processed=False,
                result=result,
                created_at=now,
                updated_at=now,
            )
            self._session.add(existing)
        else:
            await self.complete(receipt=existing, result=result, now=now)
        return RegistrationWorkerCallReplay(result=result)
