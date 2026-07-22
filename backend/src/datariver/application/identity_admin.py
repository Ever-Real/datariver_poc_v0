from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IdentityUserDraft:
    username: str
    email: str
    first_name: str
    last_name: str
    temporary_password: str
    workspace_id: UUID
    provisioning_reference: str

    @property
    def display_name(self) -> str:
        return " ".join(value for value in (self.first_name, self.last_name) if value).strip()


@dataclass(frozen=True, slots=True)
class ProvisionedIdentity:
    external_subject: str
    username: str
    created: bool


@dataclass(frozen=True, slots=True)
class ProvisionedWorkspaceUser:
    subject_id: UUID
    external_subject: str
    username: str
    display_name: str
    email: str
    workspace_id: UUID
    role_id: UUID | None
    access_expires_at: datetime
    temporary_password_required: bool = True


class IdentityAdministration(Protocol):
    async def ensure_disabled_user(self, draft: IdentityUserDraft) -> ProvisionedIdentity: ...

    async def enable_user(self, *, external_subject: str) -> None: ...

    async def close(self) -> None: ...
