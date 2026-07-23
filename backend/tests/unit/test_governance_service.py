from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    CatalogMetadataBindingCommand,
    ChangeRequestSummaryRecord,
    ChangeRequestSummaryTarget,
    IdempotencyRecord,
    RegistrationCandidateBindingCommand,
)
from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.governance import GovernanceService
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, DomainEvent, ForbiddenError, ValidationError
from datariver.domain.governance import (
    ApprovalAuthority,
    ApprovalAuthorityKind,
    ApprovalDecision,
    ChangeItem,
    ChangeRequest,
    ChangeState,
    ChangeTestRunState,
    change_target_binding_hash,
)


class MemoryTargetAuthorizer:
    def __init__(self) -> None:
        self.calls = 0
        self.system_id = uuid4()
        self.systems_by_target: dict[str, UUID] = {}
        self.approval_scopes: list[frozenset[UUID]] = []
        self.enforce_full_scope = False
        self.filter_calls = 0

    async def authorize_targets(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        items: Sequence[ChangeItem],
        request_classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ChangeItem, ...]:
        del subject, environment, request_id
        self.calls += 1
        asset_id = uuid4()
        return tuple(
            replace(
                item,
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_system_id=self.systems_by_target.get(item.target_ref, self.system_id),
                target_classification=request_classification,
                target_lifecycle="ACTIVE",
                target_source_version="1",
                target_observed_at=datetime.now(UTC),
                target_binding_hash=change_target_binding_hash(
                    target_ref=item.target_ref,
                    asset_id=asset_id,
                    asset_type="DATASET",
                    system_id=self.systems_by_target.get(item.target_ref, self.system_id),
                    domain_id=None,
                    owner_department_id=None,
                    classification=request_classification,
                    lifecycle="ACTIVE",
                ),
                routing_system_id=self.systems_by_target.get(item.target_ref, self.system_id),
            )
            for item in items
        )

    async def filter_authorized_change_requests(
        self,
        *,
        subject: SubjectAttributes,
        change_requests: Sequence[ChangeRequest],
        **_: object,
    ) -> tuple[ChangeRequest, ...]:
        self.filter_calls += 1
        if not self.enforce_full_scope:
            return tuple(change_requests)
        return tuple(
            change_request
            for change_request in change_requests
            if change_request.required_system_ids() <= subject.allowed_system_ids
        )

    async def filter_authorized_summaries(
        self,
        *,
        subject: SubjectAttributes,
        summaries: Sequence[ChangeRequestSummaryRecord],
        **_: object,
    ) -> tuple[ChangeRequestSummaryRecord, ...]:
        self.filter_calls += 1
        if not self.enforce_full_scope:
            return tuple(summaries)
        return tuple(
            summary
            for summary in summaries
            if {
                target.routing_system_id
                for target in summary.targets
                if target.routing_system_id is not None
            }
            <= subject.allowed_system_ids
        )

    async def authorize_approval_targets(
        self,
        *,
        change_request: ChangeRequest,
        approval_system_ids: frozenset[UUID],
        **_: object,
    ) -> frozenset[UUID]:
        self.approval_scopes.append(approval_system_ids)
        return frozenset(
            item.item_id
            for item in change_request.items
            if item.routing_system_id in approval_system_ids
        )


class MemoryDecisionWriter:
    def __init__(self) -> None:
        self.decisions: list[Decision] = []
        self.actions: list[str] = []

    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del subject_id, workspace_id, resource_id, request_id
        self.decisions.append(decision)
        self.actions.append(action)


class MemoryChangeRequests:
    def __init__(
        self,
        values: dict[UUID, ChangeRequest],
        summaries: Sequence[ChangeRequestSummaryRecord] = (),
    ) -> None:
        self.values = values
        self.summaries = tuple(summaries)
        self.summary_calls: list[dict[str, object]] = []

    async def add(self, change_request: ChangeRequest) -> None:
        self.values[change_request.change_request_id] = change_request

    async def get_for_update(
        self, *, workspace_id: UUID, change_request_id: UUID
    ) -> ChangeRequest | None:
        value = self.values.get(change_request_id)
        return value if value and value.workspace_id == workspace_id else None

    async def save(self, change_request: ChangeRequest) -> None:
        self.values[change_request.change_request_id] = change_request

    async def list_summaries(
        self,
        *,
        workspace_id: UUID,
        maximum_classification: int,
        state: str | None,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[ChangeRequestSummaryRecord]:
        self.summary_calls.append(
            {
                "workspace_id": workspace_id,
                "maximum_classification": maximum_classification,
                "state": state,
                "before_created_at": before_created_at,
                "before_id": before_id,
                "limit": limit,
            }
        )
        values = [
            value
            for value in self.summaries
            if value.classification <= Classification(maximum_classification)
            and (state is None or value.state.value == state)
        ]
        if before_created_at is not None and before_id is not None:
            values = [
                value
                for value in values
                if (value.created_at, value.change_request_id) < (before_created_at, before_id)
            ]
        return tuple(
            sorted(
                values,
                key=lambda value: (value.created_at, value.change_request_id),
                reverse=True,
            )[:limit]
        )


class MemoryOutbox:
    def __init__(self, values: list[DomainEvent]) -> None:
        self.values = values

    async def add_events(self, events: list[DomainEvent]) -> None:
        self.values.extend(events)


class MemoryRegistrationBindings:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self.values = values

    async def verify_and_add(self, **values: object) -> None:
        self.values.append(values)


class MemoryIdempotency:
    def __init__(self, values: dict[tuple[UUID, str, str], IdempotencyRecord]) -> None:
        self.values = values

    async def acquire_key_lock(self, **_: object) -> None:
        return None

    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None:
        return self.values.get((workspace_id, key, operation))

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, object],
    ) -> None:
        self.values[(workspace_id, key, operation)] = IdempotencyRecord(
            request_hash=request_hash, result=result
        )


class MemoryWorkflowAuthorities:
    def __init__(self, state: dict[str, object]) -> None:
        self._state = state

    async def get_authorities(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        system_ids: frozenset[UUID],
    ) -> tuple[ApprovalAuthority, ...]:
        del workspace_id
        configured = cast(
            dict[UUID, tuple[ApprovalAuthority, ...]],
            self._state.get("workflow_authorities", {}),
        )
        if subject_id in configured:
            return configured[subject_id]
        return tuple(
            ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, system_id)
            for system_id in system_ids
        )


class MemoryUnitOfWork:
    def __init__(self, state: dict[str, object]) -> None:
        self.change_requests = MemoryChangeRequests(
            state["requests"],  # type: ignore[arg-type]
            cast(Sequence[ChangeRequestSummaryRecord], state.get("summaries", ())),
        )
        self.registration_content_bindings = MemoryRegistrationBindings(
            cast(list[dict[str, object]], state.setdefault("bindings", []))
        )
        self.registration_metadata_content_bindings = MemoryRegistrationBindings(
            cast(list[dict[str, object]], state.setdefault("metadata_bindings", []))
        )
        self.outbox = MemoryOutbox(state["outbox"])  # type: ignore[arg-type]
        self.idempotency = MemoryIdempotency(state["idempotency"])  # type: ignore[arg-type]
        self.workflow_authorities = MemoryWorkflowAuthorities(state)
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.committed = False

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        del workspace_id, subject_id


def subject(workspace_id: UUID) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.CONFIDENTIAL,
        allowed_actions=frozenset({Action.CHANGE_CREATE}),
        authentication_time=datetime.now(UTC),
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )


def change_request_summary(
    *,
    created_at: datetime,
    system_id: UUID,
) -> ChangeRequestSummaryRecord:
    change_request_id = uuid4()
    asset_id = uuid4()
    return ChangeRequestSummaryRecord(
        change_request_id=change_request_id,
        number=f"CR-{str(change_request_id)[:8]}",
        request_type="CATALOG_METADATA",
        title="Bounded summary",
        state=ChangeState.REGISTERED,
        requester_id=uuid4(),
        requester_department_id=None,
        current_round_number=1,
        created_at=created_at,
        requested_due_date=None,
        priority=None,
        urgency=None,
        classification=Classification.INTERNAL,
        version=1,
        targets=(
            ChangeRequestSummaryTarget(
                item_id=uuid4(),
                target_type="DATAHUB_ASPECT",
                target_ref="urn:li:dataset:bounded",
                aspect_name="datasetProperties",
                operation="UPSERT",
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_system_id=system_id,
                target_domain_id=None,
                target_owner_department_id=None,
                target_classification=Classification.INTERNAL,
                target_lifecycle="ACTIVE",
                target_source_version="projection-1",
                target_observed_at=created_at,
                target_binding_hash="a" * 64,
                routing_system_id=system_id,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_change_request_summary_cursor_is_bounded_and_subject_scoped() -> None:
    workspace_id = uuid4()
    system_id = uuid4()
    actor = replace(
        subject(workspace_id),
        allowed_actions=frozenset({Action.CHANGE_READ}),
        allowed_system_ids=frozenset({system_id}),
    )
    values = tuple(
        change_request_summary(
            created_at=datetime(2026, 7, 23, 10, minute, tzinfo=UTC),
            system_id=system_id,
        )
        for minute in (3, 2, 1)
    )
    state: dict[str, object] = {
        "requests": {},
        "summaries": values,
        "outbox": [],
        "idempotency": {},
    }
    target_authorizer = MemoryTargetAuthorizer()
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        target_authorizer=target_authorizer,
    )

    first = await service.list_change_request_summaries(
        workspace_id=workspace_id,
        state=None,
        cursor=None,
        limit=2,
        subject=actor,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="summary-page-1",
    )
    assert first.items == values[:2]
    assert first.next_cursor is not None

    second = await service.list_change_request_summaries(
        workspace_id=workspace_id,
        state=None,
        cursor=first.next_cursor,
        limit=2,
        subject=actor,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="summary-page-2",
    )
    assert second.items == values[2:]
    assert second.next_cursor is None

    other_actor = replace(actor, subject_id=uuid4())
    with pytest.raises(ValidationError, match="stale or invalid"):
        await service.list_change_request_summaries(
            workspace_id=workspace_id,
            state=None,
            cursor=first.next_cursor,
            limit=2,
            subject=other_actor,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="summary-page-other-subject",
        )


@pytest.mark.asyncio
async def test_create_is_idempotent_and_writes_one_outbox_event() -> None:
    workspace_id = uuid4()
    actor = subject(workspace_id)
    state: dict[str, object] = {"requests": {}, "outbox": [], "idempotency": {}}
    writer = MemoryDecisionWriter()
    uow_factory = cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state))
    target_authorizer = MemoryTargetAuthorizer()
    service = GovernanceService(
        uow_factory,
        AuthorizationService(decision_writer=writer),
        target_authorizer=target_authorizer,
    )
    arguments = {
        "workspace_id": workspace_id,
        "number": "CR-1",
        "request_type": "CATALOG_METADATA",
        "title": "Update",
        "description": "Description",
        "requester_id": actor.subject_id,
        "items": [
            ChangeItem(
                uuid4(),
                "DATAHUB_ASPECT",
                "urn:li:dataset:x",
                "UPSERT",
                {"name": "x"},
                "datasetProperties",
                "b" * 64,
            )
        ],
        "subject": actor,
        "classification": Classification.INTERNAL,
        "environment": EnvironmentAttributes(requested_at=datetime.now(UTC)),
        "request_id": "request-1",
        "idempotency_key": "idempotency-key-0001",
        "request_hash": "a" * 64,
        "require_raw_operator_gate": False,
    }

    first = await service.create_change_request(**arguments)  # type: ignore[arg-type]
    second = await service.create_change_request(**arguments)  # type: ignore[arg-type]

    assert first.change_request_id == second.change_request_id
    assert len(state["requests"]) == 1  # type: ignore[arg-type]
    assert len(state["outbox"]) == 1  # type: ignore[arg-type]
    assert len(writer.decisions) == 2
    assert target_authorizer.calls == 2


@pytest.mark.asyncio
async def test_typed_bulk_create_appends_binding_in_same_unit_of_work() -> None:
    workspace_id = uuid4()
    actor = subject(workspace_id)
    state: dict[str, object] = {
        "requests": {},
        "outbox": [],
        "idempotency": {},
        "bindings": [],
    }
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        target_authorizer=MemoryTargetAuthorizer(),
    )
    candidate_id = uuid4()
    candidate_hash = "b" * 64
    binding = RegistrationCandidateBindingCommand(
        workspace_id=workspace_id,
        upload_id=uuid4(),
        preparation_id=uuid4(),
        receipt_id=uuid4(),
        receipt_hash="c" * 64,
        candidate_id=candidate_id,
        candidate_hash=candidate_hash,
        target_asset_id=uuid4(),
        target_source_version="projection-1",
        target_binding_hash="d" * 64,
    )

    created = await service.create_change_request(
        workspace_id=workspace_id,
        number="CR-BULK-1",
        request_type="BULK_DATASET_DESCRIPTION",
        title="Typed BULK update",
        description="Immutable candidate evidence",
        requester_id=actor.subject_id,
        items=[
            ChangeItem(
                uuid4(),
                "DATAHUB_ASPECT",
                "urn:li:dataset:bulk",
                "UPSERT",
                {"description": "updated"},
                "datasetProperties",
                "a" * 64,
            )
        ],
        subject=actor,
        classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="typed-bulk-create",
        idempotency_key="typed-bulk-create-0001",
        request_hash="e" * 64,
        require_raw_operator_gate=False,
        registration_candidate_binding=binding,
    )

    values = cast(list[dict[str, object]], state["bindings"])
    assert len(values) == 1
    assert values[0]["command"] == binding
    assert values[0]["change_request_id"] == created.change_request_id
    assert values[0]["change_item_id"] == created.items[0].item_id
    assert values[0]["created_by"] == actor.subject_id


@pytest.mark.asyncio
async def test_typed_catalog_metadata_create_appends_exact_binding_in_same_unit_of_work() -> None:
    workspace_id = uuid4()
    actor = subject(workspace_id)
    state: dict[str, object] = {
        "requests": {},
        "outbox": [],
        "idempotency": {},
        "metadata_bindings": [],
    }
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        target_authorizer=MemoryTargetAuthorizer(),
    )
    binding = CatalogMetadataBindingCommand(
        workspace_id=workspace_id,
        upload_id=uuid4(),
        preparation_id=uuid4(),
        receipt_id=uuid4(),
        receipt_hash="a" * 64,
        content_profile="CATALOG_METADATA_ROWS_CSV_V1",
        candidate_id=uuid4(),
        candidate_kind="DATASET_TAG_ADD",
        candidate_hash="b" * 64,
        aspect_name="globalTags",
        before_hash="c" * 64,
        after_hash="d" * 64,
        item_contract_hash="e" * 64,
        target_asset_id=uuid4(),
        target_source_version="projection-2",
        target_binding_hash="f" * 64,
    )
    created = await service.create_change_request(
        workspace_id=workspace_id,
        number="CR-METADATA-1",
        request_type="BULK_CATALOG_METADATA",
        title="Typed metadata update",
        description="Immutable grouped candidate evidence",
        requester_id=actor.subject_id,
        items=[
            ChangeItem(
                uuid4(),
                "DATAHUB_ASPECT",
                "urn:li:dataset:metadata",
                "UPSERT",
                {"tags": [{"tag": "urn:li:tag:controlled"}]},
                "globalTags",
                "c" * 64,
                "d" * 64,
                item_contract_hash="e" * 64,
            )
        ],
        subject=actor,
        classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="typed-metadata-create",
        idempotency_key="typed-metadata-create-0001",
        request_hash="1" * 64,
        require_raw_operator_gate=False,
        registration_metadata_binding=binding,
    )

    values = cast(list[dict[str, object]], state["metadata_bindings"])
    assert len(values) == 1
    assert values[0]["command"] == binding
    assert values[0]["change_request_id"] == created.change_request_id
    assert values[0]["change_item_id"] == created.items[0].item_id


@pytest.mark.asyncio
async def test_status_workflow_allows_ordinary_authenticated_development_actors() -> None:
    workspace_id = uuid4()
    target_authorizer = MemoryTargetAuthorizer()
    requester = replace(
        subject(workspace_id),
        authentication_assurance=AuthenticationAssurance.PASSWORD,
    )
    reviewer = replace(
        subject(workspace_id),
        allowed_actions=frozenset({Action.CHANGE_REVIEW}),
        allowed_system_ids=frozenset({target_authorizer.system_id}),
        authentication_assurance=AuthenticationAssurance.PASSWORD,
    )
    state: dict[str, object] = {"requests": {}, "outbox": [], "idempotency": {}}
    writer = MemoryDecisionWriter()
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=writer),
        target_authorizer=target_authorizer,
    )
    change_request = await service.create_change_request(
        workspace_id=workspace_id,
        number="CR-DEV-1",
        request_type="CATALOG_METADATA",
        title="Development workflow",
        description="Validate registered-to-review status transitions.",
        requester_id=requester.subject_id,
        items=[
            ChangeItem(
                uuid4(),
                "DATAHUB_ASPECT",
                "urn:li:dataset:development-workflow",
                "UPSERT",
                {"description": "test"},
                "datasetProperties",
                "b" * 64,
            )
        ],
        subject=requester,
        classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="development-create",
        idempotency_key="development-create-0001",
        request_hash="a" * 64,
        require_raw_operator_gate=False,
    )

    in_review = await service.transition(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        target=ChangeState.IN_REVIEW,
        actor_id=reviewer.subject_id,
        reason="Ordinary authenticated review.",
        expected_version=change_request.version,
        subject=reviewer,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="development-review",
        idempotency_key="development-review-0001",
        request_hash="b" * 64,
    )
    reviewed = await service.add_approval(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        stage="REVIEW",
        approval_decision=ApprovalDecision.APPROVED,
        reason="Target-system review approved.",
        expected_version=in_review.version,
        subject=reviewer,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="development-review-approval",
        idempotency_key="development-review-approval-0001",
        request_hash="c" * 64,
    )
    testing = await service.transition(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        target=ChangeState.TESTING,
        actor_id=reviewer.subject_id,
        reason="Review approvals completed.",
        expected_version=reviewed.version,
        subject=reviewer,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="development-testing",
        idempotency_key="development-testing-0001",
        request_hash="d" * 64,
    )
    test_evidence = await service.record_test_run(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        system_id=target_authorizer.system_id,
        attachment_id=uuid4(),
        state=ChangeTestRunState.PASSED,
        plan_hash="1" * 64,
        result_hash="2" * 64,
        bounded_summary={"contract": "CR_TEST_ATTACHMENT_V1"},
        expected_version=testing.version,
        subject=reviewer,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="development-test-evidence",
        idempotency_key="development-test-evidence-0001",
        request_hash="e" * 64,
    )
    tested = await service.add_approval(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        stage="TEST",
        approval_decision=ApprovalDecision.APPROVED,
        reason="Target-system test approved.",
        expected_version=test_evidence.version,
        subject=reviewer,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="development-test-approval",
        idempotency_key="development-test-approval-0001",
        request_hash="e" * 64,
    )
    final_review = await service.transition(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        target=ChangeState.FINAL_REVIEW,
        actor_id=reviewer.subject_id,
        reason="Status workflow verified.",
        expected_version=tested.version,
        subject=reviewer,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="development-final-review",
        idempotency_key="development-final-review-0001",
        request_hash="f" * 64,
    )

    assert final_review.state is ChangeState.FINAL_REVIEW
    assert writer.actions == [
        Action.CHANGE_CREATE.value,
        Action.CHANGE_REVIEW.value,
        Action.CHANGE_REVIEW.value,
        Action.CHANGE_REVIEW.value,
        Action.CHANGE_REVIEW.value,
        Action.CHANGE_REVIEW.value,
        Action.CHANGE_REVIEW.value,
    ]


@pytest.mark.asyncio
async def test_raw_creation_requires_explicit_hardware_human_operator_before_target_access() -> (
    None
):
    workspace_id = uuid4()
    base_actor = subject(workspace_id)
    traces: list[tuple[dict[str, object], MemoryDecisionWriter, MemoryTargetAuthorizer]] = []

    async def attempt(
        *, actor: SubjectAttributes, suffix: str
    ) -> tuple[
        ChangeRequest | None,
        dict[str, object],
        MemoryDecisionWriter,
        MemoryTargetAuthorizer,
    ]:
        state: dict[str, object] = {"requests": {}, "outbox": [], "idempotency": {}}
        writer = MemoryDecisionWriter()
        target_authorizer = MemoryTargetAuthorizer()
        traces.append((state, writer, target_authorizer))
        service = GovernanceService(
            cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
            AuthorizationService(decision_writer=writer),
            target_authorizer=target_authorizer,
        )
        result = await service.create_change_request(
            workspace_id=workspace_id,
            number=f"CR-RAW-{suffix}",
            request_type="CATALOG_METADATA",
            title="Raw update",
            description="Operator controlled raw provider update",
            requester_id=actor.subject_id,
            items=[
                ChangeItem(
                    uuid4(),
                    "DATAHUB_ASPECT",
                    "urn:li:dataset:raw",
                    "UPSERT",
                    {"name": "raw"},
                    "datasetProperties",
                    "b" * 64,
                )
            ],
            subject=actor,
            classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id=f"request-raw-{suffix}",
            idempotency_key=f"idempotency-raw-{suffix}-0001",
            request_hash="c" * 64,
        )
        return result, state, writer, target_authorizer

    with pytest.raises(ForbiddenError):
        await attempt(actor=base_actor, suffix="missing-action")
    denied_state, denied_writer, denied_target_authorizer = traces[-1]
    assert denied_writer.actions == [Action.CHANGE_RAW_CREATE.value]
    assert denied_target_authorizer.calls == 0
    assert denied_state["requests"] == {}

    allowed_actor = replace(
        base_actor,
        allowed_actions=frozenset({Action.CHANGE_CREATE, Action.CHANGE_RAW_CREATE}),
    )
    result, state, writer, target_authorizer = await attempt(
        actor=allowed_actor, suffix="hardware-human"
    )
    assert result is not None
    assert len(state["requests"]) == 1  # type: ignore[arg-type]
    assert writer.actions == [Action.CHANGE_RAW_CREATE.value, Action.CHANGE_CREATE.value]
    assert target_authorizer.calls == 1

    service_actor = replace(
        allowed_actor,
        subject_id=uuid4(),
        groups=frozenset({"stewards", "service-accounts"}),
        job_function="SERVICE_ACCOUNT",
    )
    with pytest.raises(ForbiddenError):
        await attempt(actor=service_actor, suffix="service-account")
    service_state, service_writer, service_target_authorizer = traces[-1]
    assert service_writer.actions == [Action.CHANGE_RAW_CREATE.value]
    assert service_writer.decisions[0].reason_codes == ("HUMAN_ACTOR_REQUIRED",)
    assert service_target_authorizer.calls == 0
    assert service_state["requests"] == {}


@pytest.mark.asyncio
async def test_resubmission_requires_the_requester_and_uses_change_edit_authorization() -> None:
    workspace_id = uuid4()
    requester = replace(subject(workspace_id), allowed_actions=frozenset({Action.CHANGE_EDIT}))
    target_authorizer = MemoryTargetAuthorizer()
    requester = replace(
        requester,
        allowed_system_ids=frozenset({target_authorizer.system_id}),
    )
    items = await target_authorizer.authorize_targets(
        workspace_id=workspace_id,
        subject=requester,
        items=[
            ChangeItem(
                uuid4(),
                "DATAHUB_ASPECT",
                "urn:li:dataset:resubmit",
                "UPSERT",
                {"name": "resubmit"},
                "datasetProperties",
                "b" * 64,
            )
        ],
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-resubmit-bind-1",
    )
    change_request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-FAB-260717-7F2A",
        request_type="CATALOG_METADATA",
        title="Update table description",
        description="Correct the governed description.",
        requester_id=requester.subject_id,
        items=list(items),
    )
    reviewer = uuid4()
    change_request.transition(
        target=ChangeState.IN_REVIEW,
        actor_id=reviewer,
        reason="Review started",
        policy_decision_id=uuid4(),
        expected_version=change_request.version,
    )
    change_request.transition(
        target=ChangeState.CHANGES_REQUESTED,
        actor_id=reviewer,
        reason="Please add test evidence.",
        policy_decision_id=uuid4(),
        expected_version=change_request.version,
    )
    state: dict[str, object] = {
        "requests": {change_request.change_request_id: change_request},
        "outbox": [],
        "idempotency": {},
    }
    writer = MemoryDecisionWriter()
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=writer),
        target_authorizer=target_authorizer,
    )

    result = await service.transition(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        target=ChangeState.REGISTERED,
        actor_id=requester.subject_id,
        reason="Evidence attached and resubmitted.",
        expected_version=change_request.version,
        subject=requester,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-resubmit-1",
        idempotency_key="idempotency-resubmit-0001",
        request_hash="d" * 64,
    )

    assert result.state is ChangeState.REGISTERED
    assert writer.actions == [Action.CHANGE_EDIT.value]


@pytest.mark.asyncio
async def test_complete_intake_replay_is_bound_to_the_original_actor() -> None:
    workspace_id = uuid4()
    target_authorizer = MemoryTargetAuthorizer()
    original_actor = replace(
        subject(workspace_id),
        allowed_actions=frozenset({Action.CHANGE_REVIEW}),
        allowed_system_ids=frozenset({target_authorizer.system_id}),
    )
    replay_actor = replace(original_actor, subject_id=uuid4())
    bound = await target_authorizer.authorize_targets(
        workspace_id=workspace_id,
        subject=original_actor,
        items=(
            ChangeItem(
                uuid4(),
                "DATAHUB_INTAKE",
                "urn:li:dataset:intake-replay",
                "REVIEW",
                {"description": "reviewed"},
                "changeIntake",
                "b" * 64,
            ),
        ),
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="bind-intake-replay",
    )
    change_request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-INTAKE-REPLAY",
        request_type="CHANGE_INTAKE",
        title="Intake replay",
        description="Bind completion replay to the original actor.",
        requester_id=uuid4(),
        items=list(bound),
    )
    key = "complete-intake-replay-0001"
    operation = f"change_request.complete_intake:{change_request.change_request_id}"
    state: dict[str, object] = {
        "requests": {change_request.change_request_id: change_request},
        "outbox": [],
        "idempotency": {
            (workspace_id, key, operation): IdempotencyRecord(
                request_hash="a" * 64,
                result={
                    "change_request_id": str(change_request.change_request_id),
                    "actor_id": str(original_actor.subject_id),
                },
            )
        },
    }
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        target_authorizer=target_authorizer,
    )

    with pytest.raises(ConflictError, match="another subject"):
        await service.complete_intake(
            workspace_id=workspace_id,
            change_request_id=change_request.change_request_id,
            actor_id=replay_actor.subject_id,
            reason="Replay",
            expected_version=change_request.version,
            subject=replay_actor,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="complete-intake-replay",
            idempotency_key=key,
            request_hash="a" * 64,
        )


@pytest.mark.asyncio
async def test_complete_intake_replay_rechecks_current_developer_authority() -> None:
    workspace_id = uuid4()
    target_authorizer = MemoryTargetAuthorizer()
    actor = replace(
        subject(workspace_id),
        allowed_actions=frozenset({Action.CHANGE_REVIEW}),
        allowed_system_ids=frozenset({target_authorizer.system_id}),
    )
    bound = await target_authorizer.authorize_targets(
        workspace_id=workspace_id,
        subject=actor,
        items=(
            ChangeItem(
                uuid4(),
                "DATAHUB_INTAKE",
                "urn:li:dataset:intake-revoked",
                "REVIEW",
                {"description": "reviewed"},
                "changeIntake",
                "b" * 64,
            ),
        ),
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="bind-intake-revoked",
    )
    change_request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-INTAKE-REVOKED",
        request_type="CHANGE_INTAKE",
        title="Revoked intake replay",
        description="Fresh authority is required for a replay.",
        requester_id=uuid4(),
        items=list(bound),
    )
    key = "complete-intake-revoked-0001"
    operation = f"change_request.complete_intake:{change_request.change_request_id}"
    state: dict[str, object] = {
        "requests": {change_request.change_request_id: change_request},
        "outbox": [],
        "idempotency": {
            (workspace_id, key, operation): IdempotencyRecord(
                request_hash="a" * 64,
                result={
                    "change_request_id": str(change_request.change_request_id),
                    "actor_id": str(actor.subject_id),
                },
            )
        },
        "workflow_authorities": {actor.subject_id: ()},
    }
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        target_authorizer=target_authorizer,
    )

    with pytest.raises(ForbiddenError, match="Developer assignment"):
        await service.complete_intake(
            workspace_id=workspace_id,
            change_request_id=change_request.change_request_id,
            actor_id=actor.subject_id,
            reason="Replay",
            expected_version=change_request.version,
            subject=actor,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="complete-intake-revoked",
            idempotency_key=key,
            request_hash="a" * 64,
        )
    assert target_authorizer.filter_calls == 1


@pytest.mark.asyncio
async def test_multi_system_review_approval_is_scoped_without_leaking_unrelated_targets() -> None:
    workspace_id = uuid4()
    first_system = uuid4()
    second_system = uuid4()
    target_authorizer = MemoryTargetAuthorizer()
    target_authorizer.systems_by_target = {
        "urn:li:dataset:first": first_system,
        "urn:li:dataset:second": second_system,
    }
    target_authorizer.enforce_full_scope = True
    requester = subject(workspace_id)
    bound = await target_authorizer.authorize_targets(
        workspace_id=workspace_id,
        subject=requester,
        items=(
            ChangeItem(
                uuid4(),
                "DATAHUB_INTAKE",
                "urn:li:dataset:first",
                "REVIEW",
                {"description": "first"},
                "changeIntake",
                "1" * 64,
            ),
            ChangeItem(
                uuid4(),
                "DATAHUB_INTAKE",
                "urn:li:dataset:second",
                "REVIEW",
                {"description": "second"},
                "changeIntake",
                "2" * 64,
            ),
        ),
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="bind-multi-system-review",
    )
    change_request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-MULTI-SYSTEM",
        request_type="CHANGE_INTAKE",
        title="Multi-system review",
        description="Each developer approves only their own system.",
        requester_id=requester.subject_id,
        items=list(bound),
    )
    change_request.transition(
        target=ChangeState.IN_REVIEW,
        actor_id=uuid4(),
        reason="Review started.",
        policy_decision_id=uuid4(),
        expected_version=change_request.version,
    )
    first_actor = replace(
        subject(workspace_id),
        allowed_actions=frozenset({Action.CHANGE_REVIEW}),
        allowed_system_ids=frozenset({first_system}),
    )
    second_actor = replace(
        subject(workspace_id),
        allowed_actions=frozenset({Action.CHANGE_REVIEW}),
        allowed_system_ids=frozenset({second_system}),
    )
    state: dict[str, object] = {
        "requests": {change_request.change_request_id: change_request},
        "outbox": [],
        "idempotency": {},
        "workflow_authorities": {
            first_actor.subject_id: (
                ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, first_system),
            ),
            second_actor.subject_id: (
                ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, second_system),
            ),
        },
    }
    service = GovernanceService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        target_authorizer=target_authorizer,
    )

    first_response = await service.add_approval(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        stage="REVIEW",
        approval_decision=ApprovalDecision.APPROVED,
        reason="First system reviewed.",
        expected_version=change_request.version,
        subject=first_actor,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="approve-first-system",
        idempotency_key="approve-first-system-0001",
        request_hash="3" * 64,
    )
    stored = cast(dict[UUID, ChangeRequest], state["requests"])[change_request.change_request_id]
    second_response = await service.add_approval(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        stage="REVIEW",
        approval_decision=ApprovalDecision.APPROVED,
        reason="Second system reviewed.",
        expected_version=stored.version,
        subject=second_actor,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="approve-second-system",
        idempotency_key="approve-second-system-0001",
        request_hash="4" * 64,
    )

    assert [item.routing_system_id for item in first_response.items] == [first_system]
    assert [item.routing_system_id for item in second_response.items] == [second_system]
    assert target_authorizer.approval_scopes == [
        frozenset({first_system}),
        frozenset({second_system}),
    ]
    assert stored.required_system_ids() == frozenset({first_system, second_system})
    assert [approval.authorities for approval in stored.approvals] == [
        (ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, first_system),),
        (ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, second_system),),
    ]
    coordinator = replace(
        subject(workspace_id),
        allowed_actions=frozenset({Action.CHANGE_REVIEW}),
        allowed_system_ids=frozenset({first_system, second_system}),
    )
    testing = await service.transition(
        workspace_id=workspace_id,
        change_request_id=change_request.change_request_id,
        target=ChangeState.TESTING,
        actor_id=coordinator.subject_id,
        reason="All server-side system approvals are complete.",
        expected_version=stored.version,
        subject=coordinator,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="advance-complete-multi-system-review",
        idempotency_key="advance-complete-multi-system-review-0001",
        request_hash="5" * 64,
    )
    assert testing.state is ChangeState.TESTING
