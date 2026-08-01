from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from datariver.application.classification_access import (
    ClassificationAccessPosture,
    ClassificationAccessSnapshotReader,
)
from datariver.application.ports import (
    IdempotencyStore,
    MembershipAccessRepository,
    OutboxWriter,
)
from datariver.domain.authz import Classification
from datariver.domain.classification_access import (
    ChatMode,
    ClassificationAccessPolicy,
    RestrictedSearchGrant,
    SearchMode,
)


@dataclass(frozen=True, slots=True)
class ClassificationPolicyPage:
    items: tuple[ClassificationAccessPolicy, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RestrictedSearchGrantPage:
    items: tuple[RestrictedSearchGrant, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ClassificationPolicySummaryRule:
    classification: Classification
    search_mode: SearchMode
    chat_mode: ChatMode


@dataclass(frozen=True, slots=True)
class ClassificationPolicySummary:
    state: ClassificationAccessPosture
    rules: tuple[ClassificationPolicySummaryRule, ...]


class ClassificationPolicyRepository(Protocol):
    async def add(self, policy: ClassificationAccessPolicy) -> None: ...

    async def save(self, policy: ClassificationAccessPolicy) -> None: ...

    async def get(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> ClassificationAccessPolicy | None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> ClassificationAccessPolicy | None: ...

    async def get_active(self, *, workspace_id: UUID) -> ClassificationAccessPolicy | None: ...

    async def get_active_for_update(
        self, *, workspace_id: UUID, excluding_policy_id: UUID | None = None
    ) -> ClassificationAccessPolicy | None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> ClassificationPolicyPage: ...

    async def next_policy_number(self, *, workspace_id: UUID) -> int: ...

    async def assert_provider_rules_eligible(
        self, *, policy: ClassificationAccessPolicy, now: datetime
    ) -> None: ...


class RestrictedSearchGrantRepository(Protocol):
    async def add(self, grant: RestrictedSearchGrant) -> None: ...

    async def save(self, grant: RestrictedSearchGrant) -> None: ...

    async def get(self, *, workspace_id: UUID, grant_id: UUID) -> RestrictedSearchGrant | None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, grant_id: UUID
    ) -> RestrictedSearchGrant | None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID | None,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> RestrictedSearchGrantPage: ...


class ClassificationAccessAdminUnitOfWork(Protocol):
    snapshots: ClassificationAccessSnapshotReader
    policies: ClassificationPolicyRepository
    grants: RestrictedSearchGrantRepository
    memberships: MembershipAccessRepository
    idempotency: IdempotencyStore
    outbox: OutboxWriter

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...

    async def lock_workspace(self, *, workspace_id: UUID) -> None: ...

    async def commit(self) -> None: ...
