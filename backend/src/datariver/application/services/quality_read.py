from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from datariver.application.catalog_security import (
    catalog_classification_access_hash,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.quality_read_contracts import (
    QualityAssetPage,
    QualityAssetSummary,
    QualityCapability,
    QualityCapabilityAxis,
    QualityIssuePage,
    QualityOverview,
    QualityReadContext,
    QualityResultPage,
    QualityRuleSetDetail,
    QualityRuleSetPage,
    QualityRunPage,
    QualityRunSummary,
)
from datariver.application.quality_read_ports import QualityReadRepository
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    BuiltinPolicyEngine,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError, NotFoundError, canonical_json_hash

_AUTHORIZATION_LEASE_SECONDS = 30


class QualityReadService:
    def __init__(
        self,
        *,
        repository: QualityReadRepository,
        authorization: AuthorizationService,
        classification_access: ClassificationAccessResolver,
    ) -> None:
        self._repository = repository
        self._authorization = authorization
        self._classification_access = classification_access
        self._engine = BuiltinPolicyEngine()

    async def capability(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
    ) -> QualityCapability:
        self._require_human(subject)
        context = await self._context(subject=subject)
        resource = self._workspace_resource(subject)

        def allowed(action: Action) -> bool:
            return self._engine.decide(
                subject=subject,
                resource=resource,
                action=action,
                environment=environment,
            ).allowed

        read_allowed = allowed(Action.QUALITY_READ)
        profile_allowed = allowed(Action.QUALITY_PROFILE_READ)
        propose_allowed = allowed(Action.QUALITY_RULE_PROPOSE)
        activation_allowed = allowed(Action.QUALITY_RULE_ACTIVATE)
        manual_allowed = allowed(Action.QUALITY_RUN_REQUEST)
        operations_allowed = allowed(Action.QUALITY_OPERATIONS_READ)
        axes = (
            QualityCapabilityAxis(
                id="read_access",
                state="AVAILABLE" if read_allowed else "DENIED",
                reason_code=None if read_allowed else "QUALITY_READ_DENIED",
            ),
            QualityCapabilityAxis(
                id="profile_readiness",
                state="AVAILABLE" if profile_allowed else "DENIED",
                reason_code=None if profile_allowed else "QUALITY_PROFILE_READ_DENIED",
            ),
            _dependency_axis(
                "rule_authoring",
                action_allowed=propose_allowed,
                denied_code="QUALITY_RULE_PROPOSE_DENIED",
                unavailable_code="FIELD_IDENTITY_MAPPING_UNAVAILABLE",
            ),
            _dependency_axis(
                "activation",
                action_allowed=activation_allowed,
                denied_code="QUALITY_RULE_ACTIVATE_DENIED",
                unavailable_code="QUALITY_CONTROL_READINESS_ATTESTATION_UNAVAILABLE",
            ),
            _dependency_axis(
                "manual_execution",
                action_allowed=manual_allowed,
                denied_code="QUALITY_RUN_REQUEST_DENIED",
                unavailable_code="SOURCE_READINESS_ATTESTATION_UNAVAILABLE",
            ),
            _dependency_axis(
                "scheduling",
                action_allowed=activation_allowed,
                denied_code="QUALITY_RULE_ACTIVATE_DENIED",
                unavailable_code="SCHEDULE_PROFILE_ATTESTATION_UNAVAILABLE",
            ),
            QualityCapabilityAxis(
                id="operations",
                state="AVAILABLE" if operations_allowed else "DENIED",
                reason_code=None if operations_allowed else "QUALITY_OPERATIONS_READ_DENIED",
            ),
        )
        return QualityCapability(
            observed_at=context.observed_at,
            valid_until=context.authorization_valid_until,
            cache_scope=context.cache_scope,
            axes=axes,
        )

    async def rule_definitions(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[dict[str, object], ...]:
        await self._authorize_read(subject=subject, environment=environment, request_id=request_id)
        return (
            {
                "kind": "NOT_NULL",
                "available": True,
                "parameter_contract": {},
            },
            {
                "kind": "RANGE",
                "available": True,
                "parameter_contract": {
                    "value_type": ["DECIMAL", "DATE", "TIMESTAMP"],
                    "min_value": "string",
                    "max_value": "string",
                    "inclusive_min": "boolean",
                    "inclusive_max": "boolean",
                },
            },
            {
                "kind": "REGEX",
                "available": False,
                "reason_code": "REGEX_SAFETY_GATE_UNAVAILABLE",
                "parameter_contract": {},
            },
        )

    async def overview(
        self,
        *,
        days: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityOverview, QualityReadContext]:
        context = await self._read_context(
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return await self._repository.overview(context=context, days=days), context

    async def list_assets(
        self,
        *,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityAssetPage, QualityReadContext]:
        context = await self._read_context(
            subject=subject,
            environment=environment,
            request_id=request_id,
            include_profile=True,
        )
        return (
            await self._repository.list_assets(context=context, limit=limit, cursor=cursor),
            context,
        )

    async def list_rule_sets(
        self,
        *,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityRuleSetPage, QualityReadContext]:
        context = await self._read_context(
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return (
            await self._repository.list_rule_sets(context=context, limit=limit, cursor=cursor),
            context,
        )

    async def get_asset(
        self,
        *,
        asset_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityAssetSummary, QualityReadContext]:
        context = await self._read_context(
            subject=subject,
            environment=environment,
            request_id=request_id,
            include_profile=True,
        )
        value = await self._repository.get_asset(context=context, asset_id=asset_id)
        if value is None:
            raise NotFoundError("The Quality asset was not found.")
        return value, context

    async def get_rule_set(
        self,
        *,
        rule_set_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityRuleSetDetail, QualityReadContext]:
        context = await self._read_context(
            subject=subject, environment=environment, request_id=request_id
        )
        value = await self._repository.get_rule_set(context=context, rule_set_id=rule_set_id)
        if value is None:
            raise NotFoundError("The Quality Rule Set was not found.")
        return value, context

    async def list_runs(
        self,
        *,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityRunPage, QualityReadContext]:
        context = await self._read_context(
            subject=subject, environment=environment, request_id=request_id
        )
        return (
            await self._repository.list_runs(context=context, limit=limit, cursor=cursor),
            context,
        )

    async def get_run(
        self,
        *,
        run_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityRunSummary, QualityReadContext]:
        context = await self._read_context(
            subject=subject, environment=environment, request_id=request_id
        )
        value = await self._repository.get_run(context=context, run_id=run_id)
        if value is None:
            raise NotFoundError("The Quality validation Run was not found.")
        return value, context

    async def list_results(
        self,
        *,
        run_id: UUID,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityResultPage, QualityReadContext]:
        context = await self._read_context(
            subject=subject, environment=environment, request_id=request_id
        )
        value = await self._repository.list_results(
            context=context,
            run_id=run_id,
            limit=limit,
            cursor=cursor,
        )
        if value is None:
            raise NotFoundError("The Quality validation Run was not found.")
        return value, context

    async def list_issues(
        self,
        *,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[QualityIssuePage, QualityReadContext]:
        context = await self._read_context(
            subject=subject, environment=environment, request_id=request_id
        )
        return (
            await self._repository.list_issues(context=context, limit=limit, cursor=cursor),
            context,
        )

    async def _read_context(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        include_profile: bool = False,
    ) -> QualityReadContext:
        await self._authorize_read(subject=subject, environment=environment, request_id=request_id)
        context = await self._context(subject=subject)
        if not include_profile:
            return context
        profile_decision = self._engine.decide(
            subject=subject,
            resource=self._workspace_resource(subject),
            action=Action.QUALITY_PROFILE_READ,
            environment=environment,
        )
        if not profile_decision.allowed:
            return context
        await self._authorization.authorize(
            subject=subject,
            resource=self._workspace_resource(subject),
            action=Action.QUALITY_PROFILE_READ,
            environment=environment,
            request_id=request_id,
        )
        return replace(context, profile_allowed=True)

    async def _authorize_read(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        self._require_human(subject)
        await self._authorization.authorize(
            subject=subject,
            resource=self._workspace_resource(subject),
            action=Action.QUALITY_READ,
            environment=environment,
            request_id=request_id,
        )

    async def _context(self, *, subject: SubjectAttributes) -> QualityReadContext:
        observed_at = await self._repository.database_now()
        access = await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=observed_at,
        )
        valid_until = observed_at + timedelta(seconds=_AUTHORIZATION_LEASE_SECONDS)
        if (
            access.nearest_validity_boundary is not None
            and access.nearest_validity_boundary < valid_until
        ):
            valid_until = max(observed_at, access.nearest_validity_boundary)
        permission_hash = catalog_permission_scope_hash(subject)
        classification_hash = catalog_classification_access_hash(access)
        cache_scope = canonical_json_hash(
            {
                "contract": "QUALITY_READ_SCOPE_V1",
                "workspace_id": str(subject.workspace_id),
                "subject_id": str(subject.subject_id),
                "permission_scope_hash": permission_hash,
                "classification_access_hash": classification_hash,
            }
        )
        return QualityReadContext(
            subject=subject,
            access=access,
            observed_at=observed_at,
            authorization_valid_until=valid_until,
            cache_scope=cache_scope,
            profile_allowed=False,
        )

    @staticmethod
    def _require_human(subject: SubjectAttributes) -> None:
        if subject.job_function == "SERVICE_ACCOUNT" or "service-accounts" in subject.groups:
            raise ForbiddenError("Public Quality APIs require a human identity.")

    @staticmethod
    def _workspace_resource(subject: SubjectAttributes) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=subject.workspace_id,
            workspace_id=subject.workspace_id,
            resource_type="QUALITY_WORKSPACE",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.PUBLIC,
            lifecycle="ACTIVE",
        )


def _dependency_axis(
    axis_id: str,
    *,
    action_allowed: bool,
    denied_code: str,
    unavailable_code: str,
) -> QualityCapabilityAxis:
    if not action_allowed:
        return QualityCapabilityAxis(id=axis_id, state="DENIED", reason_code=denied_code)
    return QualityCapabilityAxis(
        id=axis_id,
        state="UNAVAILABLE",
        reason_code=unavailable_code,
    )
