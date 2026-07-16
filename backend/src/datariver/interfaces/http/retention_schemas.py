from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from datariver.domain.retention import (
    GovernanceDecision,
    LegalHoldActionType,
    LegalHoldScope,
    LegalHoldState,
    RetentionDataClass,
    RetentionPolicyState,
)


class StrictRetentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetentionRulesRequest(StrictRetentionRequest):
    completed_operation_days: int = Field(ge=1, le=3650)
    chat_content_days: int = Field(ge=1, le=3650)
    audit_online_months: int = Field(ge=1, le=120)
    immutable_archive_years: int = Field(ge=1, le=100)


class RetentionPolicyProposalRequest(StrictRetentionRequest):
    rules: RetentionRulesRequest
    reason: str = Field(min_length=1, max_length=4000)


class GovernanceDecisionRequest(StrictRetentionRequest):
    decision: GovernanceDecision
    reason: str = Field(min_length=1, max_length=4000)


class RetentionPolicyResponse(BaseModel):
    policy_id: UUID
    policy_number: int
    rules: RetentionRulesRequest
    payload_hash: str
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    state: RetentionPolicyState
    checker_id: UUID | None
    decision_reason: str | None
    decision_policy_decision_id: UUID | None
    decided_at: datetime | None
    superseded_by: UUID | None
    supersede_reason: str | None
    supersede_policy_decision_id: UUID | None
    superseded_at: datetime | None
    version: int
    partition_automation_state: str
    deletion_automation_state: str


class RetentionPolicyListResponse(BaseModel):
    items: list[RetentionPolicyResponse]


class LegalHoldPlaceRequest(StrictRetentionRequest):
    data_class: RetentionDataClass
    scope: LegalHoldScope
    scope_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=4000)


class LegalHoldReleaseRequest(StrictRetentionRequest):
    reason: str = Field(min_length=1, max_length=4000)


class LegalHoldActionResponse(BaseModel):
    action_id: UUID
    action: LegalHoldActionType
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    occurred_at: datetime
    hold_version: int
    payload_hash: str


class LegalHoldResponse(BaseModel):
    hold_id: UUID
    data_class: RetentionDataClass
    scope: LegalHoldScope
    scope_id: UUID | None
    reason: str
    payload_hash: str
    created_by: UUID
    create_policy_decision_id: UUID
    state: LegalHoldState
    release_requested_by: UUID | None
    release_request_reason: str | None
    release_request_policy_decision_id: UUID | None
    release_checker_id: UUID | None
    release_decision_reason: str | None
    release_decision_policy_decision_id: UUID | None
    released_at: datetime | None
    version: int
    actions: list[LegalHoldActionResponse]
    deletion_effect: str


class LegalHoldListResponse(BaseModel):
    items: list[LegalHoldResponse]
