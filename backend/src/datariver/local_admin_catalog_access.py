from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from datariver.application.services.admin_access import AdminAccessService
from datariver.application.services.authorization import AuthorizationService
from datariver.bootstrap import (
    LOCAL_DEMO_IDENTITIES,
    LOCAL_SUBJECT_ID,
    LOCAL_WORKSPACE_ID,
)
from datariver.config import get_settings
from datariver.domain.admin_access import MembershipAccessUpdate
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import canonical_json_hash, utc_now
from datariver.infrastructure.db.admin_access import SqlAdminAccessUnitOfWork
from datariver.infrastructure.db.authz import (
    SqlDecisionWriter,
    subject_attributes_from_models,
    with_authentication_context,
)
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.platform import (
    SubjectModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.secrets import SecretResolver

_LOCAL_CHECKER_SUBJECT_ID = next(
    identity.subject_id for identity in LOCAL_DEMO_IDENTITIES if identity.username == "sua.han"
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
    database: Database,
    *,
    subject_id: UUID,
    now: datetime,
) -> SubjectAttributes:
    async with database.session_factory() as session:
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


async def reconcile_local_admin_catalog_access() -> dict[str, object]:
    """Materialize exact ACTIVE catalog scopes for the development administrator."""

    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("Local administrator catalog reconciliation is development-only.")
    database = Database(
        settings.database_url,
        password=SecretResolver().resolve(settings.database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-local-admin-catalog-access",
    )
    now = utc_now()
    try:
        checker = await _actor(
            database,
            subject_id=_LOCAL_CHECKER_SUBJECT_ID,
            now=now,
        )
        async with database.session_factory() as session:
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
                )
            ).one_or_none()
            if membership is None:
                raise RuntimeError("The local administrator membership is unavailable.")
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
                "A non-PUBLIC ACTIVE catalog asset is missing its governed System or Domain scope."
            )
        system_ids = frozenset(row.system_id for row in scope_rows if row.system_id is not None)
        domain_ids = frozenset(row.domain_id for row in scope_rows if row.domain_id is not None)
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
        if updated:
            scope_hash = canonical_json_hash(
                {
                    "system_ids": sorted(str(value) for value in system_ids),
                    "domain_ids": sorted(str(value) for value in domain_ids),
                }
            )
            request_hash = canonical_json_hash(
                {
                    "operation": "local.admin.catalog-access.reconcile",
                    "scope_hash": scope_hash,
                    "command": command.command_document(),
                }
            )
            service = AdminAccessService(
                lambda: SqlAdminAccessUnitOfWork(database.session_factory),
                AuthorizationService(
                    decision_writer=SqlDecisionWriter(database.session_factory),
                    development_admin_password_bypass_enabled=True,
                ),
                fallback_enabled=False,
                fallback_ttl_seconds=300,
                development_admin_password_bypass_enabled=True,
            )
            membership_version = await service.update_membership_with_hardware_key(
                command=command,
                subject=checker,
                environment=EnvironmentAttributes(requested_at=now),
                request_id=f"local-admin-catalog-access-{scope_hash[:16]}",
                idempotency_key=(
                    f"local-admin-catalog-access-v{membership.version}-{scope_hash[:16]}"
                ),
                request_hash=request_hash,
            )
        return {
            "workspace_id": str(LOCAL_WORKSPACE_ID),
            "administrator_subject_id": str(LOCAL_SUBJECT_ID),
            "active_asset_count": active_asset_count,
            "quarantined_asset_count": quarantined_asset_count,
            "system_scope_count": len(system_ids),
            "domain_scope_count": len(domain_ids),
            "updated": updated,
            "membership_version": membership_version,
        }
    finally:
        await database.close()


def main() -> None:
    print(json.dumps(asyncio.run(reconcile_local_admin_catalog_access()), sort_keys=True))


if __name__ == "__main__":
    main()
