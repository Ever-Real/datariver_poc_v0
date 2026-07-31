from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from datariver.application.quality_command_contracts import (
    QualityAssetAuthoringDetail,
    QualityAuthoringAsset,
    QualityCommonRuleTemplateCreateCommand,
    QualityCommonRuleTemplateCreateResult,
    QualityDeploymentBinding,
    QualityManualRunResult,
    QualityRuleCommandTarget,
    QualityRuleProposalCommand,
    QualityRuleProposalResult,
    QualityRuleProposalTarget,
    QualityRuleVersionCommandResult,
)
from datariver.application.quality_command_ports import (
    QualityCommandRepository,
    QualityDeploymentDirectory,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.quality import RuleDefinition, RuleKind, RuleSeverity

_MAX_BATCH_TARGETS = 25
_MAX_RULES = 100


class QualityCommandService:
    def __init__(
        self,
        *,
        repository: QualityCommandRepository,
        directory: QualityDeploymentDirectory,
        authorization: AuthorizationService,
        worker_enabled: bool,
    ) -> None:
        self._repository = repository
        self._directory = directory
        self._authorization = authorization
        self._worker_enabled = worker_enabled

    async def authoring_ready(self, *, workspace_id: UUID) -> bool:
        return self._directory.authoring_available and await self._repository.retention_ready(
            workspace_id=workspace_id
        )

    async def manual_execution_ready(self, *, workspace_id: UUID) -> bool:
        return self._worker_enabled and await self.authoring_ready(workspace_id=workspace_id)

    async def asset_detail(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> QualityAssetAuthoringDetail:
        assets = await self._repository.get_authoring_assets(
            workspace_id=workspace_id,
            asset_ids=(asset_id,),
        )
        if not assets:
            raise NotFoundError("The Quality asset was not found.")
        asset = assets[0]
        deployment = self._directory.resolve(asset_id=asset_id)
        if deployment is None:
            return QualityAssetAuthoringDetail(
                state="UNAVAILABLE",
                reason_code="AUTHORING_TARGET_UNAVAILABLE",
                source_version=asset.source_version,
                schema_hash=None,
                fields=(),
            )
        reason = _deployment_drift_reason(asset=asset, deployment=deployment)
        if reason is not None:
            return QualityAssetAuthoringDetail(
                state="UNAVAILABLE",
                reason_code=reason,
                source_version=asset.source_version,
                schema_hash=None,
                fields=(),
            )
        return QualityAssetAuthoringDetail(
            state="READY",
            reason_code=None,
            source_version=asset.source_version,
            schema_hash=deployment.schema_hash,
            fields=deployment.fields,
        )

    async def propose_rule_sets(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        name_prefix: str,
        asset_ids: Sequence[UUID] = (),
        rules: Sequence[Mapping[str, object]] = (),
        target_rules: Sequence[tuple[UUID, Sequence[Mapping[str, object]]]] = (),
        template_id: UUID | None = None,
    ) -> QualityRuleProposalResult:
        if not await self.authoring_ready(workspace_id=subject.workspace_id):
            raise ConflictError(
                "Quality authoring is not deployment-ready.",
                details={"code": "AUTHORING_READINESS_UNAVAILABLE"},
            )
        normalized_name = name_prefix.strip()
        if target_rules:
            if asset_ids or rules:
                raise ValidationError("The Quality Rule proposal target shape is ambiguous.")
            target_asset_ids = tuple(asset_id for asset_id, _ in target_rules)
            rules_by_asset = {asset_id: tuple(values) for asset_id, values in target_rules}
        else:
            target_asset_ids = tuple(asset_ids)
            rules_by_asset = {asset_id: tuple(rules) for asset_id in target_asset_ids}
        unique_asset_ids = tuple(sorted(dict.fromkeys(target_asset_ids), key=str))
        if (
            not 1 <= len(normalized_name) <= 100
            or not 1 <= len(unique_asset_ids) <= _MAX_BATCH_TARGETS
            or len(unique_asset_ids) != len(target_asset_ids)
            or set(rules_by_asset) != set(unique_asset_ids)
            or any(not 1 <= len(values) <= _MAX_RULES for values in rules_by_asset.values())
        ):
            raise ValidationError("The Quality Rule proposal is outside its bounded contract.")
        assets = await self._repository.get_authoring_assets(
            workspace_id=subject.workspace_id,
            asset_ids=unique_asset_ids,
        )
        assets_by_id = {asset.asset_id: asset for asset in assets}
        if set(assets_by_id) != set(unique_asset_ids):
            raise NotFoundError("One or more Quality assets are unavailable.")
        targets: list[QualityRuleProposalTarget] = []
        for asset_id in unique_asset_ids:
            asset = assets_by_id[asset_id]
            await self._authorization.authorize(
                subject=subject,
                resource=_asset_resource(asset, workspace_id=subject.workspace_id),
                action=Action.QUALITY_RULE_PROPOSE,
                environment=environment,
                request_id=request_id,
            )
            deployment = self._directory.resolve(asset_id=asset_id)
            if deployment is None:
                raise ConflictError(
                    "The Quality authoring target is not deployment-ready.",
                    details={"code": "AUTHORING_TARGET_UNAVAILABLE"},
                )
            drift = _deployment_drift_reason(asset=asset, deployment=deployment)
            if drift is not None:
                raise ConflictError(
                    "The Quality authoring target has drifted.",
                    details={"code": drift},
                )
            available_fields = {field.field_identifier: field for field in deployment.fields}
            definitions: list[RuleDefinition] = []
            seen_rule_identities: set[tuple[str, str]] = set()
            for ordinal, raw_rule in enumerate(rules_by_asset[asset_id], start=1):
                field_identifier = _required_text(raw_rule, "field_identifier", 255)
                field = available_fields.get(field_identifier)
                if field is None:
                    raise ValidationError("A Rule references an unavailable field identity.")
                kind = _rule_kind(raw_rule.get("kind"))
                identity = (field_identifier, kind.value)
                if identity in seen_rule_identities:
                    raise ValidationError("A Quality proposal cannot repeat a field and Rule kind.")
                seen_rule_identities.add(identity)
                if kind.value not in field.supported_rule_kinds:
                    raise ValidationError("The Rule kind is incompatible with the field type.")
                severity = _rule_severity(raw_rule.get("severity"))
                parameters = raw_rule.get("parameters")
                if not isinstance(parameters, dict) or any(
                    not isinstance(key, str) for key in parameters
                ):
                    raise ValidationError("The Rule parameters are invalid.")
                definition = RuleDefinition.create(
                    ordinal=ordinal,
                    field_identifier=field_identifier,
                    kind=kind,
                    severity=severity,
                    parameters=dict(parameters),
                )
                if kind is RuleKind.RANGE and definition.parameters.get(
                    "value_type"
                ) != _range_value_type(field.logical_type):
                    raise ValidationError(
                        "The RANGE value type is incompatible with the server field type."
                    )
                definitions.append(definition)
            targets.append(
                QualityRuleProposalTarget(
                    asset=asset,
                    deployment=deployment,
                    rules=tuple(definitions),
                )
            )
        request_hash = canonical_json_hash(
            {
                "contract": "QUALITY_RULE_BATCH_PROPOSAL_V1",
                "workspace_id": str(subject.workspace_id),
                "actor_id": str(subject.subject_id),
                "name_prefix": normalized_name,
                "template_id": str(template_id) if template_id is not None else None,
                "targets": [
                    {
                        "asset_id": str(target.asset.asset_id),
                        "schema_hash": target.deployment.schema_hash,
                        "source_version": target.asset.source_version,
                        "rules": [
                            {
                                "definition_hash": rule.definition_hash,
                                "field_identifier": rule.field_identifier,
                                "kind": rule.kind.value,
                                "ordinal": rule.ordinal,
                                "parameters": rule.parameters,
                                "severity": rule.severity.value,
                            }
                            for rule in target.rules
                        ],
                    }
                    for target in targets
                ],
            }
        )
        return await self._repository.create_rule_sets(
            command=QualityRuleProposalCommand(
                workspace_id=subject.workspace_id,
                actor_id=subject.subject_id,
                name_prefix=normalized_name,
                targets=tuple(targets),
                request_hash=request_hash,
                idempotency_key=idempotency_key,
                template_id=template_id,
            )
        )

    async def create_common_rule_template(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        name: str,
        description: str | None,
        rules: Sequence[Mapping[str, object]],
    ) -> QualityCommonRuleTemplateCreateResult:
        normalized_name = name.strip()
        normalized_description = description.strip() if description else None
        if (
            not 1 <= len(normalized_name) <= 100
            or (normalized_description is not None and len(normalized_description) > 1_000)
            or not 1 <= len(rules) <= _MAX_RULES
        ):
            raise ValidationError("The common Rule template is outside its bounded contract.")
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=subject.workspace_id,
                workspace_id=subject.workspace_id,
                resource_type="QUALITY_COMMON_RULE_TEMPLATE",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.QUALITY_RULE_PROPOSE,
            environment=environment,
            request_id=request_id,
        )
        normalized_rules = _normalized_template_rules(rules)
        request_hash = canonical_json_hash(
            {
                "contract": "QUALITY_COMMON_RULE_TEMPLATE_CREATE_V1",
                "workspace_id": str(subject.workspace_id),
                "actor_id": str(subject.subject_id),
                "name": normalized_name,
                "description": normalized_description,
                "rules": normalized_rules,
            }
        )
        return await self._repository.create_common_rule_template(
            command=QualityCommonRuleTemplateCreateCommand(
                workspace_id=subject.workspace_id,
                actor_id=subject.subject_id,
                name=normalized_name,
                description=normalized_description,
                rules=normalized_rules,
                request_hash=request_hash,
                idempotency_key=idempotency_key,
            )
        )

    async def map_common_rule_template(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        template_id: UUID,
        asset_ids: Sequence[UUID] = (),
        targets: Sequence[tuple[UUID, Sequence[Mapping[str, object]]]] = (),
    ) -> QualityRuleProposalResult:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=template_id,
                workspace_id=subject.workspace_id,
                resource_type="QUALITY_COMMON_RULE_TEMPLATE",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.QUALITY_RULE_PROPOSE,
            environment=environment,
            request_id=request_id,
        )
        template = await self._repository.get_common_rule_template_rules(
            workspace_id=subject.workspace_id,
            template_id=template_id,
        )
        if template is None:
            raise NotFoundError("The Quality common Rule template was not found.")
        name, rules = template
        if bool(asset_ids) == bool(targets):
            raise ValidationError("The common Rule mapping target shape is invalid.")
        target_rules = tuple(
            (
                asset_id,
                _bind_template_rules(template_rules=rules, bindings=bindings),
            )
            for asset_id, bindings in targets
        )
        return await self.propose_rule_sets(
            subject=subject,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            name_prefix=name,
            asset_ids=asset_ids,
            rules=rules if asset_ids else (),
            target_rules=target_rules,
            template_id=template_id,
        )

    async def review_rule_set_version(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        rule_set_id: UUID,
        version_id: UUID,
        decision: str,
        reason: str,
        expected_version: int,
    ) -> QualityRuleVersionCommandResult:
        target = await self._command_target(
            subject=subject,
            rule_set_id=rule_set_id,
            version_id=version_id,
        )
        normalized_decision = decision.strip().upper()
        normalized_reason = reason.strip()
        if (
            normalized_decision not in {"APPROVE", "REJECT"}
            or not 1 <= len(normalized_reason) <= 4000
        ):
            raise ValidationError("The Quality review decision is invalid.")
        auth_decision = await self._authorization.authorize(
            subject=subject,
            resource=_command_resource(target, workspace_id=subject.workspace_id),
            action=Action.QUALITY_RULE_REVIEW,
            environment=environment,
            request_id=request_id,
        )
        request_hash = canonical_json_hash(
            {
                "contract": "QUALITY_RULE_REVIEW_COMMAND_V1",
                "decision": normalized_decision,
                "expected_version": expected_version,
                "reason": normalized_reason,
                "rule_set_id": str(rule_set_id),
                "version_id": str(version_id),
            }
        )
        return await self._repository.review_rule_set_version(
            workspace_id=subject.workspace_id,
            actor_id=subject.subject_id,
            rule_set_id=rule_set_id,
            version_id=version_id,
            decision=normalized_decision,
            reason=normalized_reason,
            expected_version=expected_version,
            policy_decision_id=auth_decision.decision_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def activate_rule_set_version(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        rule_set_id: UUID,
        version_id: UUID,
        expected_version: int,
    ) -> QualityRuleVersionCommandResult:
        target = await self._command_target(
            subject=subject,
            rule_set_id=rule_set_id,
            version_id=version_id,
        )
        auth_decision = await self._authorization.authorize(
            subject=subject,
            resource=_command_resource(target, workspace_id=subject.workspace_id),
            action=Action.QUALITY_RULE_ACTIVATE,
            environment=environment,
            request_id=request_id,
        )
        request_hash = canonical_json_hash(
            {
                "contract": "QUALITY_RULE_ACTIVATE_COMMAND_V1",
                "expected_version": expected_version,
                "rule_set_id": str(rule_set_id),
                "version_id": str(version_id),
            }
        )
        return await self._repository.activate_rule_set_version(
            workspace_id=subject.workspace_id,
            actor_id=subject.subject_id,
            rule_set_id=rule_set_id,
            version_id=version_id,
            expected_version=expected_version,
            policy_decision_id=auth_decision.decision_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def request_manual_run(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        rule_set_id: UUID,
    ) -> QualityManualRunResult:
        if not await self.manual_execution_ready(workspace_id=subject.workspace_id):
            raise ConflictError(
                "Manual Quality execution is not deployment-ready.",
                details={"code": "SOURCE_READINESS_ATTESTATION_UNAVAILABLE"},
            )
        target = await self._command_target(
            subject=subject,
            rule_set_id=rule_set_id,
            version_id=None,
        )
        auth_decision = await self._authorization.authorize(
            subject=subject,
            resource=_command_resource(target, workspace_id=subject.workspace_id),
            action=Action.QUALITY_RUN_REQUEST,
            environment=environment,
            request_id=request_id,
        )
        request_hash = canonical_json_hash(
            {
                "contract": "QUALITY_MANUAL_RUN_REQUEST_V1",
                "rule_set_id": str(rule_set_id),
            }
        )
        return await self._repository.request_manual_run(
            workspace_id=subject.workspace_id,
            actor_id=subject.subject_id,
            rule_set_id=rule_set_id,
            policy_decision_id=auth_decision.decision_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def _command_target(
        self,
        *,
        subject: SubjectAttributes,
        rule_set_id: UUID,
        version_id: UUID | None,
    ) -> QualityRuleCommandTarget:
        target = await self._repository.get_rule_command_target(
            workspace_id=subject.workspace_id,
            rule_set_id=rule_set_id,
            version_id=version_id,
        )
        if target is None:
            raise NotFoundError("The Quality Rule target was not found.")
        return target


def _deployment_drift_reason(
    *,
    asset: QualityAuthoringAsset,
    deployment: QualityDeploymentBinding,
) -> str | None:
    if (
        asset.lifecycle != "ACTIVE"
        or asset.column_names_truncated
        or not asset.column_names
        or set(asset.column_names) != {field.field_identifier for field in deployment.fields}
        or asset.system_id != deployment.system_id
    ):
        return "FIELD_IDENTITY_MAPPING_DRIFT"
    return None


def _normalized_template_rules(
    rules: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for ordinal, raw_rule in enumerate(rules, start=1):
        field_identifier = _required_text(raw_rule, "field_identifier", 255)
        kind = _rule_kind(raw_rule.get("kind"))
        severity = _rule_severity(raw_rule.get("severity"))
        parameters = raw_rule.get("parameters")
        if not isinstance(parameters, dict) or any(not isinstance(key, str) for key in parameters):
            raise ValidationError("The Rule parameters are invalid.")
        identity = (field_identifier, kind.value)
        if identity in identities:
            raise ValidationError("A common Rule template contains a duplicate Rule.")
        identities.add(identity)
        definition = RuleDefinition.create(
            ordinal=ordinal,
            field_identifier=field_identifier,
            kind=kind,
            severity=severity,
            parameters=dict(parameters),
        )
        normalized.append(
            {
                "field_identifier": definition.field_identifier,
                "kind": definition.kind.value,
                "severity": definition.severity.value,
                "parameters": definition.parameters,
            }
        )
    return tuple(normalized)


def _bind_template_rules(
    *,
    template_rules: Sequence[Mapping[str, object]],
    bindings: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    if not 1 <= len(bindings) <= _MAX_RULES:
        raise ValidationError("The common Rule field bindings are outside their bounds.")
    resolved: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for binding in bindings:
        ordinal = binding.get("template_rule_ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise ValidationError("A template Rule ordinal is invalid.")
        if not 1 <= ordinal <= len(template_rules):
            raise ValidationError("A template Rule ordinal is unavailable.")
        field_identifier = _required_text(binding, "field_identifier", 255)
        template_rule = template_rules[ordinal - 1]
        kind = _rule_kind(template_rule.get("kind"))
        severity = _rule_severity(template_rule.get("severity"))
        template_parameters = template_rule.get("parameters")
        override = binding.get("parameters_override")
        parameters = template_parameters if override is None else override
        if not isinstance(parameters, dict) or any(not isinstance(key, str) for key in parameters):
            raise ValidationError("The bound Rule parameters are invalid.")
        identity = (field_identifier, kind.value)
        if identity in identities:
            raise ValidationError("A mapped field cannot repeat the same Rule kind.")
        identities.add(identity)
        definition = RuleDefinition.create(
            ordinal=len(resolved) + 1,
            field_identifier=field_identifier,
            kind=kind,
            severity=severity,
            parameters=dict(parameters),
        )
        resolved.append(
            {
                "field_identifier": definition.field_identifier,
                "kind": definition.kind.value,
                "severity": definition.severity.value,
                "parameters": definition.parameters,
            }
        )
    return tuple(resolved)


def _asset_resource(
    asset: QualityAuthoringAsset,
    *,
    workspace_id: UUID,
) -> ResourceAttributes:
    return ResourceAttributes(
        resource_id=asset.asset_id,
        workspace_id=workspace_id,
        resource_type="QUALITY_RULE_TARGET",
        owner_department_id=None,
        system_id=asset.system_id,
        domain_id=asset.domain_id,
        classification=Classification(asset.classification),
        lifecycle=asset.lifecycle,
    )


def _command_resource(
    target: QualityRuleCommandTarget,
    *,
    workspace_id: UUID,
) -> ResourceAttributes:
    return ResourceAttributes(
        resource_id=target.version_id or target.rule_set_id,
        workspace_id=workspace_id,
        resource_type="QUALITY_RULE_VERSION" if target.version_id else "QUALITY_RULE_SET",
        owner_department_id=None,
        system_id=target.system_id,
        domain_id=target.domain_id,
        classification=Classification(target.classification),
        lifecycle=target.lifecycle,
        requester_id=target.author_id,
    )


def _required_text(value: Mapping[str, object], key: str, maximum: int) -> str:
    candidate = value.get(key)
    if (
        not isinstance(candidate, str)
        or not 1 <= len(candidate) <= maximum
        or candidate != candidate.strip()
    ):
        raise ValidationError(f"The Quality Rule {key} is invalid.")
    return candidate


def _rule_kind(value: object) -> RuleKind:
    try:
        return RuleKind(str(value))
    except ValueError as error:
        raise ValidationError("The Quality Rule kind is invalid.") from error


def _rule_severity(value: object) -> RuleSeverity:
    try:
        return RuleSeverity(str(value))
    except ValueError as error:
        raise ValidationError("The Quality Rule severity is invalid.") from error


def _range_value_type(logical_type: str) -> str | None:
    if logical_type == "INTEGER":
        return "DECIMAL"
    if logical_type in {"DECIMAL", "DATE", "TIMESTAMP"}:
        return logical_type
    return None
