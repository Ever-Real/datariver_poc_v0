from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError


class ApiProductState(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ApiProductVersionState(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class ApiSurface(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    NEIGHBORS = "NEIGHBORS"
    CHAT = "CHAT"


class ConsumerGrantState(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(slots=True)
class ApiProduct:
    product_id: UUID
    workspace_id: UUID
    owner_id: UUID
    classification: Classification
    state: ApiProductState = ApiProductState.DRAFT
    version: int = 1

    def publish(self, *, actor_id: UUID, expected_version: int) -> None:
        if self.version != expected_version:
            raise ConflictError("The API product was modified by another request.")
        if self.state is ApiProductState.RETIRED:
            raise ConflictError("A retired API product cannot be published.")
        if actor_id != self.owner_id:
            raise ForbiddenError("Only the API product owner can publish it.")
        self.state = ApiProductState.PUBLISHED
        self.version += 1

    def retire(self, *, actor_id: UUID, expected_version: int) -> None:
        if self.version != expected_version:
            raise ConflictError("The API product was modified by another request.")
        if actor_id != self.owner_id:
            raise ForbiddenError("Only the API product owner can retire it.")
        if self.state is not ApiProductState.PUBLISHED:
            raise ConflictError("Only a published API product can be retired.")
        self.state = ApiProductState.RETIRED
        self.version += 1


@dataclass(frozen=True, slots=True)
class ConsumerGrant:
    grant_id: UUID
    workspace_id: UUID
    product_id: UUID
    product_version_id: UUID
    consumer_client_id: str
    scopes: frozenset[str]
    maximum_classification: Classification
    valid_from: datetime
    expires_at: datetime
    requests_per_minute: int
    monthly_quota: int
    state: ConsumerGrantState

    def authorize(
        self,
        *,
        now: datetime,
        consumer_client_id: str,
        requested_scope: str,
        product_classification: Classification,
    ) -> None:
        if self.state is not ConsumerGrantState.ACTIVE:
            raise ForbiddenError("The API consumer grant is not active.")
        if consumer_client_id != self.consumer_client_id:
            raise ForbiddenError("The token client is not the granted API consumer.")
        if now < self.valid_from or now >= self.expires_at:
            raise ForbiddenError("The API consumer grant is outside its validity period.")
        if requested_scope not in self.scopes:
            raise ForbiddenError("The requested API scope is not granted.")
        if product_classification > self.maximum_classification:
            raise ForbiddenError("The grant classification ceiling is insufficient.")
        if self.requests_per_minute < 1 or self.monthly_quota < 1:
            raise ValidationError("The API consumer quota policy is invalid.")
