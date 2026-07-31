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


@dataclass(frozen=True, slots=True)
class IdentityUserProfileDraft:
    email: str
    first_name: str
    last_name: str

    @property
    def display_name(self) -> str:
        return " ".join(value for value in (self.first_name, self.last_name) if value).strip()


@dataclass(frozen=True, slots=True)
class IdentityUserProfile:
    external_subject: str
    username: str
    email: str
    first_name: str
    last_name: str
    enabled: bool
    email_verified: bool
    required_actions: tuple[str, ...]

    @property
    def display_name(self) -> str:
        return " ".join(value for value in (self.first_name, self.last_name) if value).strip()


@dataclass(frozen=True, slots=True)
class IdentityProfileTarget:
    subject_id: UUID
    workspace_id: UUID
    issuer: str
    external_subject: str
    display_name: str
    email: str | None
    department_id: UUID | None
    job_function: str | None
    membership_version: int
    subject_active: bool
    membership_active: bool
    service_account: bool
    access_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkspaceIdentityProfile:
    subject_id: UUID
    username: str
    display_name: str
    email: str
    first_name: str
    last_name: str
    department_id: UUID | None
    job_function: str | None
    membership_version: int
    provider_enabled: bool
    email_verified: bool
    required_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UpdatedWorkspaceIdentityProfile:
    subject_id: UUID
    username: str
    display_name: str
    email: str
    department_id: UUID | None
    job_function: str | None
    membership_version: int


@dataclass(frozen=True, slots=True)
class TemporaryPasswordReset:
    subject_id: UUID
    temporary_password_required: bool = True
    sessions_revoked: bool = True


class IdentityAdministration(Protocol):
    async def ensure_disabled_user(self, draft: IdentityUserDraft) -> ProvisionedIdentity: ...

    async def enable_user(self, *, external_subject: str) -> None: ...

    async def get_user_profile(self, *, external_subject: str) -> IdentityUserProfile: ...

    async def update_user_profile(
        self,
        *,
        external_subject: str,
        draft: IdentityUserProfileDraft,
    ) -> IdentityUserProfile: ...

    async def reset_temporary_password(
        self,
        *,
        external_subject: str,
        temporary_password: str,
    ) -> None: ...

    async def close(self) -> None: ...
