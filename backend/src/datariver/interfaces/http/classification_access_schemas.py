from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from datariver.domain.classification_access import (
    ChatMode,
    ClassificationAccessPolicyState,
    RestrictedSearchGrantState,
    RestrictedSearchScope,
    SearchMode,
)
from datariver.domain.inference_provider import (
    InferenceProviderProfileState,
    ProviderKind,
)
from datariver.interfaces.http.schemas import PageMeta


class StrictClassificationAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


ClassificationName = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]


class ClassificationRuleRequest(StrictClassificationAccessRequest):
    classification: ClassificationName
    search_mode: SearchMode
    chat_mode: ChatMode
    provider_profile_version_id: UUID | None = None


class ClassificationPolicyProposalRequest(StrictClassificationAccessRequest):
    required_jurisdiction: str = Field(min_length=1, max_length=64)
    restricted_search_grant_maximum_days: int = Field(ge=1, le=365)
    rules: Annotated[list[ClassificationRuleRequest], Field(min_length=4, max_length=4)]
    reason: str = Field(min_length=1, max_length=4000)


class GovernanceDecisionRequest(StrictClassificationAccessRequest):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=4000)


class RevocationRequest(StrictClassificationAccessRequest):
    reason: str = Field(min_length=1, max_length=4000)


class ClassificationRuleResponse(BaseModel):
    classification: ClassificationName
    search_mode: SearchMode
    chat_mode: ChatMode
    provider_profile_version_id: UUID | None


class ClassificationPolicyResponse(BaseModel):
    policy_id: UUID
    policy_number: int
    required_jurisdiction: str
    restricted_search_grant_maximum_days: int
    rules: list[ClassificationRuleResponse]
    payload_hash: str
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    state: ClassificationAccessPolicyState
    checker_id: UUID | None
    decision_reason: str | None
    decision_policy_decision_id: UUID | None
    decided_at: datetime | None
    superseded_by: UUID | None
    supersede_reason: str | None
    supersede_policy_decision_id: UUID | None
    superseded_at: datetime | None
    version: int


class ClassificationPolicyListResponse(BaseModel):
    items: list[ClassificationPolicyResponse]
    page: PageMeta


class RestrictedSearchGrantProposalRequest(StrictClassificationAccessRequest):
    subject_id: UUID
    scope: RestrictedSearchScope
    scope_id: UUID
    purpose: str = Field(min_length=1, max_length=4000)
    valid_from: datetime
    expires_at: datetime
    reason: str = Field(min_length=1, max_length=4000)


class RestrictedSearchGrantResponse(BaseModel):
    grant_id: UUID
    classification_policy_id: UUID
    classification_policy_hash: str
    subject_id: UUID
    scope: RestrictedSearchScope
    scope_id: UUID
    purpose: str
    valid_from: datetime
    expires_at: datetime
    payload_hash: str
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    state: RestrictedSearchGrantState
    checker_id: UUID | None
    decision_reason: str | None
    decision_policy_decision_id: UUID | None
    decided_at: datetime | None
    revoked_by: UUID | None
    revocation_reason: str | None
    revocation_policy_decision_id: UUID | None
    revoked_at: datetime | None
    version: int


class RestrictedSearchGrantListResponse(BaseModel):
    items: list[RestrictedSearchGrantResponse]
    page: PageMeta


class ProviderAttestationResponse(BaseModel):
    fingerprint: str
    observed_at: datetime
    expires_at: datetime


class InferenceProviderProfileResponse(BaseModel):
    provider_profile_version_id: UUID
    profile_key: str
    profile_version: int
    server_route_key: str
    kind: ProviderKind
    provider_identity: str
    model_identity: str
    deployment_identity: str
    jurisdiction: str
    region: str
    maximum_classification: ClassificationName
    residency_attestation: ProviderAttestationResponse
    zero_retention_attestation: ProviderAttestationResponse
    payload_hash: str
    maker_id: UUID
    proposal_reason: str
    proposal_policy_decision_id: UUID
    proposed_at: datetime
    state: InferenceProviderProfileState
    checker_id: UUID | None
    decision_reason: str | None
    decision_policy_decision_id: UUID | None
    decided_at: datetime | None
    revoked_by: UUID | None
    revocation_reason: str | None
    revocation_policy_decision_id: UUID | None
    revoked_at: datetime | None
    version: int


class InferenceProviderProfileListResponse(BaseModel):
    items: list[InferenceProviderProfileResponse]
    page: PageMeta
