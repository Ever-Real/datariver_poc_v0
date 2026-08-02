from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.services.governance_attachments import (
    AttachmentReconciliationStore,
    AttachmentUploadIntent,
    AttachmentUploadIntentStore,
    FinalizedAttachment,
)
from datariver.domain.authz import SubjectAttributes
from datariver.domain.common import ConflictError
from datariver.domain.governance import ChangeRequest
from datariver.infrastructure.db.authz import SqlSubjectReader, subject_attributes_from_models
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.governance import (
    ChangeItemModel,
    ChangeRequestAttachmentModel,
    ChangeRequestAttachmentUploadIntentModel,
    ChangeRequestRoundItemModel,
    ChangeRequestRoundModel,
)
from datariver.infrastructure.db.models.platform import (
    DataSystemModel,
    SubjectModel,
    SystemAssigneeModel,
    WorkspaceMembershipModel,
)


class SqlGovernanceAttachmentUploadIntentStore(AttachmentUploadIntentStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[UUID, ChangeRequestAttachmentUploadIntentModel] = {}

    async def lock_current_subject(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
    ) -> SubjectAttributes:
        row = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    SubjectModel.id == subject.subject_id,
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                )
                .with_for_update(of=(SubjectModel, WorkspaceMembershipModel))
            )
        ).one_or_none()
        if row is None:
            raise ConflictError(
                "The current workspace membership no longer exists.",
                details={"code": "ATTACHMENT_AUTHORIZATION_REVOKED"},
            )
        current = subject_attributes_from_models(subject=row[0], membership=row[1])
        return replace(
            current,
            authentication_time=subject.authentication_time,
            authentication_assurance=subject.authentication_assurance,
        )

    async def lock_authorization_dependencies(
        self,
        *,
        change_request: ChangeRequest,
        subject_id: UUID,
    ) -> None:
        workspace_id = change_request.workspace_id
        change_request_id = change_request.change_request_id
        round_id = change_request.current_round_id
        locked_round = await self._session.scalar(
            select(ChangeRequestRoundModel.id)
            .where(
                ChangeRequestRoundModel.workspace_id == workspace_id,
                ChangeRequestRoundModel.change_request_id == change_request_id,
                ChangeRequestRoundModel.id == round_id,
            )
            .with_for_update()
        )
        if locked_round is None:
            raise ConflictError(
                "The current change-request round no longer exists.",
                details={"code": "ATTACHMENT_AUTHORIZATION_STALE"},
            )
        stored_item_ids = frozenset(
            await self._session.scalars(
                select(ChangeItemModel.id)
                .join(
                    ChangeRequestRoundItemModel,
                    (ChangeRequestRoundItemModel.workspace_id == ChangeItemModel.workspace_id)
                    & (
                        ChangeRequestRoundItemModel.change_request_id
                        == ChangeItemModel.change_request_id
                    )
                    & (ChangeRequestRoundItemModel.item_id == ChangeItemModel.id),
                )
                .where(
                    ChangeItemModel.workspace_id == workspace_id,
                    ChangeItemModel.change_request_id == change_request_id,
                    ChangeRequestRoundItemModel.round_id == round_id,
                )
            )
        )
        expected_item_ids = frozenset(item.item_id for item in change_request.items)
        if stored_item_ids != expected_item_ids:
            raise ConflictError(
                "The change-request items no longer match the locked aggregate.",
                details={"code": "ATTACHMENT_AUTHORIZATION_STALE"},
            )

        system_ids = tuple(sorted(change_request.required_system_ids(), key=str))
        if system_ids:
            await self._session.scalars(
                select(DataSystemModel.id)
                .where(
                    DataSystemModel.workspace_id == workspace_id,
                    DataSystemModel.id.in_(system_ids),
                )
                .order_by(DataSystemModel.id)
                .with_for_update()
            )
            await self._session.scalars(
                select(SystemAssigneeModel.id)
                .where(
                    SystemAssigneeModel.workspace_id == workspace_id,
                    SystemAssigneeModel.subject_id == subject_id,
                    SystemAssigneeModel.system_id.in_(system_ids),
                )
                .order_by(SystemAssigneeModel.id)
                .with_for_update()
            )

        asset_ids = tuple(
            sorted(
                {
                    item.target_asset_id
                    for item in change_request.items
                    if item.target_asset_id is not None
                },
                key=str,
            )
        )
        if asset_ids:
            await self._session.scalars(
                select(AssetProjectionModel.id)
                .where(
                    AssetProjectionModel.workspace_id == workspace_id,
                    AssetProjectionModel.id.in_(asset_ids),
                )
                .order_by(AssetProjectionModel.id)
                .with_for_update()
            )

    async def refresh_effective_subject(
        self,
        *,
        subject: SubjectAttributes,
        observed_at: datetime,
    ) -> SubjectAttributes:
        return await SqlSubjectReader(self._session).refresh_subject(
            subject=subject,
            now=observed_at,
        )

    async def allocate_serial_number(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        kind: str,
        original_name: str,
    ) -> int:
        finalized_max = int(
            await self._session.scalar(
                select(
                    func.coalesce(func.max(ChangeRequestAttachmentModel.serial_number), 0)
                ).where(
                    ChangeRequestAttachmentModel.workspace_id == workspace_id,
                    ChangeRequestAttachmentModel.change_request_id == change_request_id,
                    ChangeRequestAttachmentModel.kind == kind,
                    ChangeRequestAttachmentModel.original_name == original_name,
                )
            )
            or 0
        )
        intent_max = int(
            await self._session.scalar(
                select(
                    func.coalesce(
                        func.max(ChangeRequestAttachmentUploadIntentModel.serial_number),
                        0,
                    )
                ).where(
                    ChangeRequestAttachmentUploadIntentModel.workspace_id == workspace_id,
                    ChangeRequestAttachmentUploadIntentModel.change_request_id == change_request_id,
                    ChangeRequestAttachmentUploadIntentModel.kind == kind,
                    ChangeRequestAttachmentUploadIntentModel.original_name == original_name,
                )
            )
            or 0
        )
        serial_number = max(finalized_max, intent_max) + 1
        if serial_number > 999_999:
            raise ConflictError("The attachment serial-number capacity is exhausted.")
        return serial_number

    async def add_started(self, intent: AttachmentUploadIntent) -> None:
        if intent.state != "STARTED":
            raise ConflictError("A new attachment upload intent must start in STARTED state.")
        model = ChangeRequestAttachmentUploadIntentModel(
            id=intent.attachment_id,
            workspace_id=intent.workspace_id,
            change_request_id=intent.change_request_id,
            round_id=intent.round_id,
            kind=intent.kind,
            original_name=intent.original_name,
            serial_number=intent.serial_number,
            bucket=intent.bucket,
            object_key=intent.object_key,
            content_type=intent.content_type,
            expected_size_bytes=intent.expected_size_bytes,
            expected_content_sha256=intent.expected_content_sha256,
            state="STARTED",
            size_bytes=None,
            content_sha256=None,
            provider_checksum=None,
            uploaded_by=intent.uploaded_by,
            stored_at=None,
            finalized_at=None,
            failed_at=None,
            failure_code=None,
            version=1,
        )
        self._session.add(model)
        self._tracked[intent.attachment_id] = model

    async def get(
        self,
        *,
        workspace_id: UUID,
        attachment_id: UUID,
    ) -> AttachmentUploadIntent | None:
        model = (
            await self._session.scalars(
                select(ChangeRequestAttachmentUploadIntentModel).where(
                    ChangeRequestAttachmentUploadIntentModel.workspace_id == workspace_id,
                    ChangeRequestAttachmentUploadIntentModel.id == attachment_id,
                )
            )
        ).one_or_none()
        if model is None:
            return None
        self._tracked[model.id] = model
        return _intent(model)

    def _model(self, intent: AttachmentUploadIntent) -> ChangeRequestAttachmentUploadIntentModel:
        model = self._tracked.get(intent.attachment_id)
        if model is None:
            raise RuntimeError("The attachment upload intent was not loaded in this transaction.")
        return model

    async def mark_stored(
        self,
        *,
        intent: AttachmentUploadIntent,
        size_bytes: int,
        content_sha256: str,
        provider_checksum: str | None,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent:
        if (
            size_bytes != intent.expected_size_bytes
            or content_sha256 != intent.expected_content_sha256
        ):
            raise ConflictError(
                "The stored attachment evidence does not match the precommitted intent.",
                details={"code": "ATTACHMENT_STORED_EVIDENCE_MISMATCH"},
            )
        if intent.state in {"STORED", "FINALIZED"}:
            if (
                intent.size_bytes != size_bytes
                or intent.content_sha256 != content_sha256
                or intent.provider_checksum != provider_checksum
            ):
                raise ConflictError(
                    "The attachment upload already has different stored evidence.",
                    details={"code": "ATTACHMENT_STORED_EVIDENCE_CONFLICT"},
                )
            return intent
        if intent.state != "STARTED":
            raise ConflictError(
                "The attachment upload cannot record stored evidence from its current state.",
                details={"code": "ATTACHMENT_UPLOAD_STATE_CONFLICT", "state": intent.state},
            )
        del occurred_at
        if provider_checksum is None:
            raise ConflictError(
                "Independent provider evidence must include a checksum.",
                details={"code": "ATTACHMENT_PROVIDER_CHECKSUM_MISSING"},
            )
        model = self._model(intent)
        await self._session.execute(
            text(
                """
                SELECT governance.attest_attachment_upload_object(
                    :workspace_id,
                    :attachment_id,
                    :size_bytes,
                    :content_sha256,
                    :provider_checksum
                )
                """
            ),
            {
                "workspace_id": intent.workspace_id,
                "attachment_id": intent.attachment_id,
                "size_bytes": size_bytes,
                "content_sha256": content_sha256,
                "provider_checksum": provider_checksum,
            },
        )
        await self._session.refresh(model)
        return _intent(model)

    async def mark_failed(
        self,
        *,
        intent: AttachmentUploadIntent,
        failure_code: str,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent:
        if intent.state == "FAILED":
            if intent.failure_code != failure_code:
                raise ConflictError("The attachment upload already has a different failure.")
            return intent
        if intent.state != "STARTED":
            raise ConflictError(
                "Stored attachment evidence cannot be marked as a rejected create.",
                details={"code": "ATTACHMENT_UPLOAD_STATE_CONFLICT", "state": intent.state},
            )
        del occurred_at
        model = self._model(intent)
        await self._session.execute(
            text(
                """
                SELECT governance.fail_attachment_upload_intent(
                    :workspace_id,
                    :attachment_id,
                    :failure_code
                )
                """
            ),
            {
                "workspace_id": intent.workspace_id,
                "attachment_id": intent.attachment_id,
                "failure_code": failure_code,
            },
        )
        await self._session.refresh(model)
        return _intent(model)

    async def finalize(
        self,
        *,
        intent: AttachmentUploadIntent,
        expected_change_request_version: int,
        occurred_at: datetime,
    ) -> FinalizedAttachment:
        if (
            intent.state not in {"STORED", "FINALIZED"}
            or intent.size_bytes is None
            or intent.content_sha256 is None
            or intent.stored_at is None
        ):
            raise ConflictError(
                "Only reconciled stored evidence can be finalized.",
                details={"code": "ATTACHMENT_UPLOAD_NOT_STORED"},
            )
        del occurred_at
        self._model(intent)
        await self._session.execute(
            text(
                """
                SELECT governance.finalize_attachment_upload_intent(
                    :workspace_id,
                    :attachment_id,
                    :expected_change_request_version
                )
                """
            ),
            {
                "workspace_id": intent.workspace_id,
                "attachment_id": intent.attachment_id,
                "expected_change_request_version": expected_change_request_version,
            },
        )
        attachment = (
            await self._session.scalars(
                select(ChangeRequestAttachmentModel).where(
                    ChangeRequestAttachmentModel.workspace_id == intent.workspace_id,
                    ChangeRequestAttachmentModel.id == intent.attachment_id,
                )
            )
        ).one()
        return FinalizedAttachment(
            id=attachment.id,
            kind=attachment.kind,
            round_id=attachment.round_id,
            original_name=attachment.original_name,
            serial_number=attachment.serial_number,
            content_type=attachment.content_type,
            size_bytes=attachment.size_bytes,
            content_sha256=attachment.content_sha256,
            created_at=attachment.created_at,
        )

    async def list_reconcilable(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID | None,
        round_id: UUID | None,
        states: frozenset[str],
        before_or_at: datetime,
        limit: int,
    ) -> tuple[AttachmentUploadIntent, ...]:
        statement = select(ChangeRequestAttachmentUploadIntentModel).where(
            ChangeRequestAttachmentUploadIntentModel.workspace_id == workspace_id,
            ChangeRequestAttachmentUploadIntentModel.state.in_(states),
            ChangeRequestAttachmentUploadIntentModel.updated_at <= before_or_at,
        )
        if change_request_id is not None:
            statement = statement.where(
                ChangeRequestAttachmentUploadIntentModel.change_request_id == change_request_id
            )
        if round_id is not None:
            statement = statement.where(
                ChangeRequestAttachmentUploadIntentModel.round_id == round_id
            )
        rows = (
            await self._session.scalars(
                statement.order_by(
                    ChangeRequestAttachmentUploadIntentModel.updated_at,
                    ChangeRequestAttachmentUploadIntentModel.id,
                ).limit(limit)
            )
        ).all()
        return tuple(_intent(model) for model in rows)


class SqlGovernanceAttachmentReconciliationStore(AttachmentReconciliationStore):
    """Upload-role persistence boundary; it has no direct UPDATE or attachment INSERT grant."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def next_started(
        self,
        *,
        before_or_at: datetime,
    ) -> AttachmentUploadIntent | None:
        async with self._session_factory() as session, session.begin():
            model = (
                await session.scalars(
                    select(ChangeRequestAttachmentUploadIntentModel).from_statement(
                        text(
                            """
                            SELECT *
                            FROM governance.claim_attachment_upload_reconciliation(
                                :before_or_at
                            )
                            """
                        )
                    ),
                    {"before_or_at": before_or_at},
                )
            ).one_or_none()
            return _intent(model) if model is not None else None

    async def attest_stored(
        self,
        *,
        intent: AttachmentUploadIntent,
        size_bytes: int,
        content_sha256: str,
        provider_checksum: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    SELECT governance.attest_attachment_upload_object(
                        :workspace_id,
                        :attachment_id,
                        :size_bytes,
                        :content_sha256,
                        :provider_checksum
                    )
                    """
                ),
                {
                    "workspace_id": intent.workspace_id,
                    "attachment_id": intent.attachment_id,
                    "size_bytes": size_bytes,
                    "content_sha256": content_sha256,
                    "provider_checksum": provider_checksum,
                },
            )

    async def defer(self, *, intent: AttachmentUploadIntent) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    SELECT governance.defer_attachment_upload_reconciliation(
                        :workspace_id,
                        :attachment_id
                    )
                    """
                ),
                {
                    "workspace_id": intent.workspace_id,
                    "attachment_id": intent.attachment_id,
                },
            )


def _intent(model: ChangeRequestAttachmentUploadIntentModel) -> AttachmentUploadIntent:
    return AttachmentUploadIntent(
        attachment_id=model.id,
        workspace_id=model.workspace_id,
        change_request_id=model.change_request_id,
        round_id=model.round_id,
        kind=model.kind,
        original_name=model.original_name,
        serial_number=model.serial_number,
        bucket=model.bucket,
        object_key=model.object_key,
        content_type=model.content_type,
        expected_size_bytes=model.expected_size_bytes,
        expected_content_sha256=model.expected_content_sha256,
        uploaded_by=model.uploaded_by,
        state=model.state,
        size_bytes=model.size_bytes,
        content_sha256=model.content_sha256,
        provider_checksum=model.provider_checksum,
        stored_at=model.stored_at,
        finalized_at=model.finalized_at,
        failed_at=model.failed_at,
        failure_code=model.failure_code,
    )
