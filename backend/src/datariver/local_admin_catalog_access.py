from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.services.authorization import AuthorizationService
from datariver.bootstrap import (
    LOCAL_DEMO_IDENTITIES,
    LOCAL_SUBJECT_ID,
    LOCAL_WORKSPACE_ID,
    _reconcile_local_canonical_admin_binding,
)
from datariver.config import Settings, get_settings
from datariver.domain.admin_access import MembershipAccessUpdate
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import DomainEvent, canonical_json_hash, utc_now
from datariver.infrastructure.db.admin_access import (
    SqlMembershipAccessRepository,
)
from datariver.infrastructure.db.authz import (
    _canonical_admin_binding_is_current,
    subject_attributes_from_models,
    with_authentication_context,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.platform import (
    AccessRoleModel,
    CanonicalAdminBindingModel,
    SubjectModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.secrets import SecretResolver

_LOCAL_CHECKER_SUBJECT_ID = next(
    identity.subject_id for identity in LOCAL_DEMO_IDENTITIES if identity.username == "sua.han"
)
_LOCAL_RECONCILIATION_OPERATION = "local.admin.catalog-access.reconcile"


class _SessionDecisionWriter:
    """Append the local reconciliation decision to its mutation transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        self._session.add(
            PolicyDecisionModel(
                id=decision.decision_id,
                workspace_id=workspace_id,
                subject_id=subject_id,
                resource_id=resource_id,
                action=action,
                effect=decision.effect.value,
                reason_codes=list(decision.reason_codes),
                policy_versions=list(decision.policy_versions),
                evaluation_context={
                    "kind": "local_admin_catalog_access_reconciliation",
                    "authentication_assurance": decision.authentication_assurance.value,
                    "authentication_time": (
                        decision.authentication_time.isoformat()
                        if decision.authentication_time is not None
                        else None
                    ),
                },
                request_id=request_id,
                decided_at=utc_now(),
            )
        )


def _subject_access(membership: WorkspaceMembershipModel) -> SubjectAttributes:
    attributes = membership.attributes if isinstance(membership.attributes, dict) else {}
    return SubjectAttributes(
        subject_id=membership.subject_id,
        workspace_id=membership.workspace_id,
        active=membership.active,
        department_id=membership.department_id,
        groups=frozenset(str(value) for value in attributes.get("groups", [])),
        job_function=membership.job_function,
        clearance=Classification(membership.clearance),
        allowed_actions=frozenset(Action(value) for value in attributes.get("allowed_actions", [])),
        denied_actions=frozenset(Action(value) for value in attributes.get("denied_actions", [])),
        allowed_system_ids=frozenset(
            UUID(str(value)) for value in attributes.get("allowed_system_ids", [])
        ),
        allowed_domain_ids=frozenset(
            UUID(str(value)) for value in attributes.get("allowed_domain_ids", [])
        ),
    )


def admin_catalog_access_command(
    *,
    membership: WorkspaceMembershipModel,
    system_ids: frozenset[UUID],
    domain_ids: frozenset[UUID],
) -> MembershipAccessUpdate:
    """Add exact active-catalog scopes without changing actions or classification authority."""

    current = _subject_access(membership)
    return MembershipAccessUpdate(
        workspace_id=membership.workspace_id,
        target_subject_id=membership.subject_id,
        expected_membership_version=membership.version,
        active=membership.active,
        clearance=current.clearance,
        groups=current.groups,
        allowed_actions=current.allowed_actions,
        denied_actions=current.denied_actions,
        allowed_system_ids=current.allowed_system_ids | system_ids,
        allowed_domain_ids=current.allowed_domain_ids | domain_ids,
    )


async def _actor(
    session: AsyncSession,
    *,
    subject_id: UUID,
    now: datetime,
) -> SubjectAttributes:
    await set_security_context(
        session,
        workspace_id=LOCAL_WORKSPACE_ID,
        subject_id=subject_id,
    )
    row = (
        await session.execute(
            select(SubjectModel, WorkspaceMembershipModel)
            .join(
                WorkspaceMembershipModel,
                WorkspaceMembershipModel.subject_id == SubjectModel.id,
            )
            .where(
                SubjectModel.id == subject_id,
                SubjectModel.active.is_(True),
                WorkspaceMembershipModel.workspace_id == LOCAL_WORKSPACE_ID,
                WorkspaceMembershipModel.active.is_(True),
                or_(
                    WorkspaceMembershipModel.access_expires_at.is_(None),
                    WorkspaceMembershipModel.access_expires_at > now,
                ),
            )
        )
    ).one_or_none()
    if row is None:
        raise RuntimeError("The local administrator reconciliation identity is unavailable.")
    subject = subject_attributes_from_models(
        subject=row[0],
        membership=row[1],
        observed_at=now,
    )
    return with_authentication_context(
        subject,
        authentication_time=now,
        authentication_assurance=AuthenticationAssurance.PASSWORD,
    )


async def _read_active_catalog_scopes(
    *,
    settings: Settings,
    resolver: SecretResolver,
) -> tuple[frozenset[UUID], frozenset[UUID], int, int]:
    """Read the fixed local workspace projection through the ordinary app/RLS role."""

    catalog_database = Database(
        settings.database_url,
        password=resolver.resolve(settings.database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-local-admin-catalog-read",
    )
    try:
        async with catalog_database.session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=LOCAL_WORKSPACE_ID,
                subject_id=LOCAL_SUBJECT_ID,
            )
            active_conditions = (
                AssetProjectionModel.workspace_id == LOCAL_WORKSPACE_ID,
                AssetProjectionModel.deleted_at.is_(None),
                AssetProjectionModel.lifecycle == "ACTIVE",
            )
            scope_rows = (
                await session.execute(
                    select(
                        AssetProjectionModel.system_id,
                        AssetProjectionModel.domain_id,
                    )
                    .where(and_(*active_conditions))
                    .distinct()
                )
            ).all()
            active_asset_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(AssetProjectionModel)
                    .where(and_(*active_conditions))
                )
                or 0
            )
            quarantined_asset_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(AssetProjectionModel)
                    .where(
                        AssetProjectionModel.workspace_id == LOCAL_WORKSPACE_ID,
                        AssetProjectionModel.deleted_at.is_(None),
                        AssetProjectionModel.lifecycle == "QUARANTINED",
                    )
                )
                or 0
            )
            invalid_active_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(AssetProjectionModel)
                    .where(
                        and_(
                            *active_conditions,
                            AssetProjectionModel.classification != int(Classification.PUBLIC),
                            or_(
                                AssetProjectionModel.system_id.is_(None),
                                AssetProjectionModel.domain_id.is_(None),
                            ),
                        )
                    )
                )
                or 0
            )
            if invalid_active_count:
                raise RuntimeError(
                    "A non-PUBLIC ACTIVE catalog asset is missing its governed System or Domain "
                    "scope."
                )
            system_ids = frozenset(row.system_id for row in scope_rows if row.system_id is not None)
            domain_ids = frozenset(row.domain_id for row in scope_rows if row.domain_id is not None)
            return system_ids, domain_ids, active_asset_count, quarantined_asset_count
    finally:
        await catalog_database.close()


async def reconcile_local_admin_catalog_access() -> dict[str, object]:
    """Materialize exact ACTIVE catalog scopes for the development administrator."""

    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("Local administrator catalog reconciliation is development-only.")
    resolver = SecretResolver()
    (
        system_ids,
        domain_ids,
        active_asset_count,
        quarantined_asset_count,
    ) = await _read_active_catalog_scopes(settings=settings, resolver=resolver)
    bootstrap_database = Database(
        settings.bootstrap_database_url,
        password=resolver.resolve(settings.bootstrap_database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-local-admin-catalog-access",
    )
    now = utc_now()
    try:
        async with bootstrap_database.session_factory() as session, session.begin():
            checker = await _actor(
                session,
                subject_id=_LOCAL_CHECKER_SUBJECT_ID,
                now=now,
            )
            await set_security_context(
                session,
                workspace_id=LOCAL_WORKSPACE_ID,
                subject_id=LOCAL_SUBJECT_ID,
            )
            membership = (
                await session.scalars(
                    select(WorkspaceMembershipModel)
                    .join(
                        SubjectModel,
                        SubjectModel.id == WorkspaceMembershipModel.subject_id,
                    )
                    .where(
                        WorkspaceMembershipModel.workspace_id == LOCAL_WORKSPACE_ID,
                        WorkspaceMembershipModel.subject_id == LOCAL_SUBJECT_ID,
                        WorkspaceMembershipModel.active.is_(True),
                        SubjectModel.active.is_(True),
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if membership is None:
                raise RuntimeError("The local administrator membership is unavailable.")
            command = admin_catalog_access_command(
                membership=membership,
                system_ids=system_ids,
                domain_ids=domain_ids,
            )
            current = _subject_access(membership)
            desired = replace(
                current,
                allowed_system_ids=command.allowed_system_ids,
                allowed_domain_ids=command.allowed_domain_ids,
            )
            updated = desired != current
            membership_version = membership.version
            binding_version: int | None = None
            if updated:
                scope_hash = canonical_json_hash(
                    {
                        "system_ids": sorted(str(value) for value in system_ids),
                        "domain_ids": sorted(str(value) for value in domain_ids),
                    }
                )
                request_hash = canonical_json_hash(
                    {
                        "operation": _LOCAL_RECONCILIATION_OPERATION,
                        "scope_hash": scope_hash,
                        "command": command.command_document(),
                    }
                )
                request_id = f"local-admin-catalog-access-{scope_hash[:16]}"
                idempotency_key = (
                    f"local-admin-catalog-access-v{membership.version}-{scope_hash[:16]}"
                )
                idempotency = SqlIdempotencyStore(session)
                existing = await idempotency.get_result(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    key=idempotency_key,
                    operation=_LOCAL_RECONCILIATION_OPERATION,
                )
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise RuntimeError(
                            "The local catalog reconciliation idempotency record is invalid."
                        )
                    return existing.result
                decision = await AuthorizationService(
                    decision_writer=_SessionDecisionWriter(session),
                    development_admin_password_bypass_enabled=True,
                ).authorize(
                    subject=checker,
                    resource=ResourceAttributes(
                        resource_id=LOCAL_SUBJECT_ID,
                        workspace_id=LOCAL_WORKSPACE_ID,
                        resource_type="workspace_membership_access",
                        owner_department_id=None,
                        system_id=None,
                        domain_id=None,
                        classification=Classification.RESTRICTED,
                        lifecycle="ACTIVE",
                        owner_subject_id=LOCAL_SUBJECT_ID,
                    ),
                    action=Action.ADMIN_MANAGE,
                    environment=EnvironmentAttributes(requested_at=now),
                    request_id=request_id,
                )
                membership_version = await SqlMembershipAccessRepository(session).apply(command)
                await _reconcile_local_canonical_admin_binding(session=session)
                await session.flush()
                binding = await session.get(
                    CanonicalAdminBindingModel,
                    {
                        "workspace_id": LOCAL_WORKSPACE_ID,
                        "subject_id": LOCAL_SUBJECT_ID,
                    },
                )
                target = await session.get(SubjectModel, LOCAL_SUBJECT_ID)
                role = (
                    await session.get(AccessRoleModel, binding.canonical_role_id)
                    if binding is not None
                    else None
                )
                if (
                    binding is None
                    or target is None
                    or not _canonical_admin_binding_is_current(
                        subject=target,
                        membership=membership,
                        binding=binding,
                        role=role,
                        now=now,
                    )
                ):
                    raise RuntimeError(
                        "The local Canonical Admin binding did not match the reconciled access."
                    )
                binding_version = binding.version
                await SqlOutboxWriter(session).add_events(
                    [
                        DomainEvent.create(
                            event_type="iam.workspace_membership.access_updated.v1",
                            aggregate_type="workspace_membership",
                            aggregate_id=LOCAL_SUBJECT_ID,
                            workspace_id=LOCAL_WORKSPACE_ID,
                            payload={
                                "actor_id": str(checker.subject_id),
                                "payload_hash": command.payload_hash,
                                "membership_version": membership_version,
                                "policy_decision_id": str(decision.decision_id),
                                "assurance": checker.authentication_assurance.value,
                                "reconciliation": _LOCAL_RECONCILIATION_OPERATION,
                            },
                        )
                    ]
                )
                result: dict[str, object] = {
                    "workspace_id": str(LOCAL_WORKSPACE_ID),
                    "administrator_subject_id": str(LOCAL_SUBJECT_ID),
                    "active_asset_count": active_asset_count,
                    "quarantined_asset_count": quarantined_asset_count,
                    "system_scope_count": len(system_ids),
                    "domain_scope_count": len(domain_ids),
                    "updated": True,
                    "membership_version": membership_version,
                    "binding_version": binding_version,
                }
                await idempotency.save_result(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    key=idempotency_key,
                    operation=_LOCAL_RECONCILIATION_OPERATION,
                    request_hash=request_hash,
                    result=result,
                )
                return result
            return {
                "workspace_id": str(LOCAL_WORKSPACE_ID),
                "administrator_subject_id": str(LOCAL_SUBJECT_ID),
                "active_asset_count": active_asset_count,
                "quarantined_asset_count": quarantined_asset_count,
                "system_scope_count": len(system_ids),
                "domain_scope_count": len(domain_ids),
                "updated": False,
                "membership_version": membership_version,
                "binding_version": binding_version,
            }
    finally:
        await bootstrap_database.close()


def main() -> None:
    print(json.dumps(asyncio.run(reconcile_local_admin_catalog_access()), sort_keys=True))


if __name__ == "__main__":
    main()
