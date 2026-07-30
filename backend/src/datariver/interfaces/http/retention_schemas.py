from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from datariver.domain.authz import Classification
from datariver.domain.retention import (
    ErasureRequestState,
    ErasureTargetType,
    GovernanceDecision,
    LegalHoldActionType,
    LegalHoldResourceType,
    LegalHoldScope,
    LegalHoldState,
    RetentionArchiveDisposition,
    RetentionDataClass,
    RetentionPeriodUnit,
    RetentionPolicyState,
)
from datariver.interfaces.http.schemas import PageMeta


class StrictRetentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrictRetentionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetentionRulesRequest(StrictRetentionRequest):
    completed_operation_days: int = Field(ge=1, le=3650)
    chat_content_days: int = Field(ge=1, le=3650)
    audit_online_months: int = Field(ge=1, le=120)
    immutable_archive_years: int = Field(ge=1, le=100)


class RetentionClassRuleRequest(StrictRetentionRequest):
    data_class: RetentionDataClass
    unit: RetentionPeriodUnit
    minimum: int = Field(ge=0, le=36_500)
    maximum: int = Field(ge=1, le=36_500)
    archive_disposition: RetentionArchiveDisposition


class RetentionPolicyContractRequest(StrictRetentionRequest):
    contract_version: Literal[
        "POLICY_BOOK_V2",
        "POLICY_BOOK_V3",
        "POLICY_BOOK_V4",
    ] = "POLICY_BOOK_V2"
    effective_from: datetime
    effective_until: datetime | None = None
    execution_authorization_hours: int = Field(ge=1, le=168)
    class_rules: tuple[RetentionClassRuleRequest, ...] = Field(min_length=4, max_length=8)


class RetentionPolicyProposalRequest(StrictRetentionRequest):
    rules: RetentionRulesRequest
    contract: RetentionPolicyContractRequest | None = None
    reason: str = Field(min_length=1, max_length=4000)


class GovernanceDecisionRequest(StrictRetentionRequest):
    decision: GovernanceDecision
    reason: str = Field(min_length=1, max_length=4000)


class RetentionPolicyResponse(BaseModel):
    policy_id: UUID
    policy_number: int
    rules: RetentionRulesRequest
    contract_version: str
    contract: RetentionPolicyContractRequest | None
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
    page: PageMeta


class LegalHoldPlaceRequest(StrictRetentionRequest):
    data_class: RetentionDataClass
    scope: LegalHoldScope
    scope_id: UUID | None = None
    resource_type: LegalHoldResourceType | None = None
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
    resource_type: LegalHoldResourceType | None
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
    action_history_truncated: bool
    deletion_effect: str


class LegalHoldListResponse(BaseModel):
    items: list[LegalHoldResponse]
    page: PageMeta


class ErasureRequestCreate(StrictRetentionRequest):
    target_type: ErasureTargetType
    target_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    review_ttl_seconds: int = Field(ge=300, le=604800)


class ErasureApprovalResponse(BaseModel):
    approval_id: UUID
    decision: GovernanceDecision
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    payload_hash: str
    request_version: int
    occurred_at: datetime


class ErasureRequestResponse(BaseModel):
    erasure_request_id: UUID
    target_type: ErasureTargetType
    target_id: UUID
    target_version: int
    target_owner_id: UUID | None
    classification: Classification
    retention_policy_id: UUID
    retention_policy_hash: str
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    payload_hash: str
    expires_at: datetime
    state: ErasureRequestState
    checker_id: UUID | None
    decision_reason: str | None
    decision_policy_decision_id: UUID | None
    decided_at: datetime | None
    version: int
    approvals: list[ErasureApprovalResponse]
    approval_history_truncated: bool
    execution_state: str


class ErasureRequestListResponse(BaseModel):
    items: list[ErasureRequestResponse]
    page: PageMeta


class RetentionExecutionAttemptResponse(StrictRetentionResponse):
    attempt_no: int = Field(ge=1)
    state: Literal[
        "RUNNING",
        "RETRY_WAIT",
        "BLOCKED",
        "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED",
        "SUPERSEDED",
    ]
    stage: str = Field(min_length=1, max_length=40)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    destructive_effect_count: Literal[0]
    started_at: datetime
    finished_at: datetime | None


class RetentionExecutionEventResponse(StrictRetentionResponse):
    sequence: int = Field(ge=1)
    event_type: Literal[
        "PLANNED",
        "LEASED",
        "RETRY_WAIT",
        "BLOCKED",
        "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED",
    ]
    attempt_no: int | None = Field(default=None, ge=1)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurred_at: datetime


class RetentionArchiveReceiptEvidenceResponse(StrictRetentionResponse):
    receipt_id: UUID
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(gt=0)
    byte_count: int = Field(gt=0)
    retention_until: datetime
    legal_hold: bool
    content_verified_at: datetime
    retention_verified_at: datetime
    verified_at: datetime
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetentionExecutionJobResponse(StrictRetentionResponse):
    job_id: UUID
    erasure_request_version: int = Field(ge=1)
    erasure_request_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_type: Literal["CHAT_SESSION"]
    target_id: UUID
    target_version: int = Field(ge=1)
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    retention_policy_id: UUID
    retention_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_number: int = Field(ge=1)
    execution_authorization_valid_until: datetime
    archive_disposition: Literal["EVIDENCE_ONLY"]
    command_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_retain_until: datetime
    state: Literal[
        "PLANNED",
        "LEASED",
        "RETRY_WAIT",
        "BLOCKED",
        "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED",
    ]
    next_attempt_at: datetime
    attempt_count: int = Field(ge=0, le=20)
    maximum_attempts: int = Field(ge=1, le=20)
    archive_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    destructive_state: Literal["DISABLED_NOT_READY"]
    separation_of_duties_verified: Literal[True]
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    attempts: list[RetentionExecutionAttemptResponse] = Field(max_length=20)
    attempts_truncated: bool
    events: list[RetentionExecutionEventResponse] = Field(max_length=100)
    events_truncated: bool
    receipt: RetentionArchiveReceiptEvidenceResponse | None

    @model_validator(mode="after")
    def verify_archive_only_evidence_shape(self) -> RetentionExecutionJobResponse:
        if self.attempt_count > self.maximum_attempts:
            raise ValueError("The execution attempt count exceeds the configured maximum.")
        if self.receipt is not None and self.archive_manifest_hash != self.receipt.manifest_hash:
            raise ValueError("The archive receipt does not match the execution manifest.")
        if self.state == "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED" and self.receipt is None:
            raise ValueError("A verified terminal execution requires an archive receipt.")
        if self.state not in {"ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED", "BLOCKED"} and (
            self.receipt is not None or self.archive_manifest_hash is not None
        ):
            raise ValueError("Only terminal or post-write blocked execution may expose a receipt.")
        return self


class RetentionExecutionEvidenceResponse(StrictRetentionResponse):
    erasure_request_id: UUID
    availability: Literal["NOT_PLANNED", "AVAILABLE"]
    archive_only: Literal[True]
    deletion_automation_state: Literal["DISABLED_NOT_READY"]
    job: RetentionExecutionJobResponse | None

    @model_validator(mode="after")
    def verify_availability(self) -> RetentionExecutionEvidenceResponse:
        if (self.availability == "AVAILABLE") is not (self.job is not None):
            raise ValueError("Execution availability and evidence must agree.")
        return self
