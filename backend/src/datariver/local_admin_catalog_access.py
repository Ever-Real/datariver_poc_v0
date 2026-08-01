from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from uuid import UUID

from sqlalchemy import and_, func, select

from datariver.bootstrap import (
    LOCAL_SUBJECT_ID,
    LOCAL_WORKSPACE_ID,
    _reconcile_local_canonical_admin_binding,
)
from datariver.config import Settings, get_settings
from datariver.domain.admin_access import MembershipAccessUpdate
from datariver.domain.authz import (
    Action,
    Classification,
    SubjectAttributes,
)
from datariver.domain.common import utc_now
from datariver.infrastructure.db.authz import _canonical_admin_binding_is_current
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


def _apply_local_catalog_scopes(
    *,
    membership: WorkspaceMembershipModel,
    system_ids: frozenset[UUID],
    domain_ids: frozenset[UUID],
) -> bool:
    """Update only fixed local membership scopes; return false for an exact replay."""

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
    if desired == current:
        return False
    if not isinstance(membership.attributes, dict):
        raise RuntimeError("The local administrator membership access is malformed.")
    membership.attributes = {
        **membership.attributes,
        "allowed_system_ids": sorted(str(value) for value in command.allowed_system_ids),
        "allowed_domain_ids": sorted(str(value) for value in command.allowed_domain_ids),
    }
    membership.version += 1
    return True


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
                            AssetProjectionModel.domain_id.is_(None),
                        )
                    )
                )
                or 0
            )
            if invalid_active_count:
                raise RuntimeError(
                    "A non-PUBLIC ACTIVE catalog asset is missing its governed Domain scope."
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
            updated = _apply_local_catalog_scopes(
                membership=membership,
                system_ids=system_ids,
                domain_ids=domain_ids,
            )
            membership_version = membership.version
            if updated:
                await session.flush()
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
            return {
                "workspace_id": str(LOCAL_WORKSPACE_ID),
                "administrator_subject_id": str(LOCAL_SUBJECT_ID),
                "active_asset_count": active_asset_count,
                "quarantined_asset_count": quarantined_asset_count,
                "system_scope_count": len(system_ids),
                "domain_scope_count": len(domain_ids),
                "updated": updated,
                "membership_version": membership_version,
                "binding_version": binding.version,
            }
    finally:
        await bootstrap_database.close()


def main() -> None:
    print(json.dumps(asyncio.run(reconcile_local_admin_catalog_access()), sort_keys=True))


if __name__ == "__main__":
    main()
