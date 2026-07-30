from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)


@dataclass(frozen=True, slots=True)
class QualityDispatchResult:
    created_run_ids: tuple[UUID, ...]
    skipped_window_count: int
    replayed: bool

    def document(self) -> dict[str, object]:
        return {
            "created_run_ids": [str(value) for value in self.created_run_ids],
            "created_run_count": len(self.created_run_ids),
            "skipped_window_count": self.skipped_window_count,
            "replayed": self.replayed,
        }


class QualityDispatchStore(Protocol):
    async def dispatch(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        call_id: str,
        max_due_schedules: int,
        max_created_runs: int,
    ) -> QualityDispatchResult: ...


class QualityDispatchService:
    def __init__(
        self,
        *,
        store: QualityDispatchStore,
        authorization: AuthorizationService,
        max_due_schedules: int,
        max_created_runs: int,
    ) -> None:
        self._store = store
        self._authorization = authorization
        self._max_due_schedules = max_due_schedules
        self._max_created_runs = max_created_runs

    async def dispatch(
        self,
        *,
        workspace_id: UUID,
        call_id: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> QualityDispatchResult:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="QUALITY_DISPATCH",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.QUALITY_DISPATCH,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.dispatch(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            call_id=call_id,
            max_due_schedules=self._max_due_schedules,
            max_created_runs=self._max_created_runs,
        )
