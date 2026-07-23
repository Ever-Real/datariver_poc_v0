from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import GovernanceApplyAuthorizationContext
from datariver.application.ports import GovernanceApplyReauthorizer


class SqlGovernanceApplyReauthorizer(GovernanceApplyReauthorizer):
    """Call the claim-scoped, audited DB policy boundary without broad worker SELECT grants."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reauthorize(self, *, context: GovernanceApplyAuthorizationContext) -> bool:
        parameters = {
            "workspace_id": context.workspace_id,
            "change_request_id": context.change_request_id,
            "change_request_version": context.change_request_version,
            "request_type": context.request_type,
            "requester_id": context.requester_id,
            "request_classification": int(context.request_classification),
            "item_id": context.item_id,
            "action": context.action.value,
            "target_type": context.target_type,
            "target_ref": context.target_ref,
            "operation": context.operation,
            "aspect_name": context.aspect_name,
            "before_hash": context.before_hash,
            "after_hash": context.after_hash,
            "target_asset_id": context.target_asset_id,
            "target_asset_type": context.target_asset_type,
            "target_system_id": context.target_system_id,
            "target_domain_id": context.target_domain_id,
            "target_owner_department_id": context.target_owner_department_id,
            "target_classification": int(context.target_classification),
            "target_lifecycle": context.target_lifecycle,
            "target_source_version": context.target_source_version,
            "target_binding_hash": context.target_binding_hash,
            "job_id": context.job_id,
            "attempt_id": context.attempt_id,
            "attempt_no": context.attempt_no,
            "worker_subject_id": context.worker_subject_id,
            "lease_token_hash": context.lease_token_hash,
        }
        async with self._session_factory() as session, session.begin():
            result = await session.scalar(
                text(
                    """
                    SELECT governance.reauthorize_datahub_apply(
                        :workspace_id,
                        :change_request_id,
                        :change_request_version,
                        :request_type,
                        :requester_id,
                        :request_classification,
                        :item_id,
                        :action,
                        :target_type,
                        :target_ref,
                        :operation,
                        :aspect_name,
                        :before_hash,
                        :after_hash,
                        :target_asset_id,
                        :target_asset_type,
                        :target_system_id,
                        :target_domain_id,
                        :target_owner_department_id,
                        :target_classification,
                        :target_lifecycle,
                        :target_source_version,
                        :target_binding_hash,
                        :job_id,
                        :attempt_id,
                        :attempt_no,
                        :worker_subject_id,
                        :lease_token_hash
                    )
                    """
                ),
                parameters,
            )
        return result is True
