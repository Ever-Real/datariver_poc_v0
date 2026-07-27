from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select

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

_REQUIRED_CHAT_ACTIONS = frozenset(
    {
        Action.CATALOG_READ,
        Action.CATALOG_SEARCH,
        Action.CHAT_QUERY,
        Action.KG_READ,
    }
)
_LOCAL_CHECKER_SUBJECT_ID = next(
    identity.subject_id for identity in LOCAL_DEMO_IDENTITIES if identity.username == "sua.han"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Grant every active local human membership Chat access to one fully mapped "
            "catalog platform."
        )
    )
    parser.add_argument("--platform", required=True)
    parser.add_argument(
        "--minimum-classification",
        choices=("PUBLIC", "INTERNAL", "CONFIDENTIAL"),
        required=True,
    )
    return parser


def _chat_access_command(
    *,
    membership: WorkspaceMembershipModel,
    system_ids: frozenset[UUID],
    domain_ids: frozenset[UUID],
    minimum_classification: Classification,
) -> MembershipAccessUpdate:
    current = _subject_access(membership)
    return MembershipAccessUpdate(
        workspace_id=membership.workspace_id,
        target_subject_id=membership.subject_id,
        expected_membership_version=membership.version,
        active=membership.active,
        clearance=max(current.clearance, minimum_classification),
        groups=current.groups,
        allowed_actions=current.allowed_actions | _REQUIRED_CHAT_ACTIONS,
        denied_actions=current.denied_actions - _REQUIRED_CHAT_ACTIONS,
        allowed_system_ids=current.allowed_system_ids | system_ids,
        allowed_domain_ids=current.allowed_domain_ids | domain_ids,
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
        allowed_actions=frozenset(
            Action(str(value)) for value in attributes.get("allowed_actions", [])
        ),
        denied_actions=frozenset(
            Action(str(value)) for value in attributes.get("denied_actions", [])
        ),
        allowed_system_ids=frozenset(
            UUID(str(value)) for value in attributes.get("allowed_system_ids", [])
        ),
        allowed_domain_ids=frozenset(
            UUID(str(value)) for value in attributes.get("allowed_domain_ids", [])
        ),
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
                )
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("The local human administrator membership is unavailable.")
        subject = subject_attributes_from_models(subject=row[0], membership=row[1])
    return with_authentication_context(
        subject,
        authentication_time=now,
        authentication_assurance=AuthenticationAssurance.PASSWORD,
    )


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("Local catalog Chat access configuration is development-only.")
    platform = arguments.platform.strip().casefold()
    if not platform or len(platform) > 100:
        raise RuntimeError("The catalog platform selector is invalid.")
    minimum_classification = Classification[arguments.minimum_classification]
    database = Database(
        settings.database_url,
        password=SecretResolver().resolve(settings.database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-local-catalog-chat-access",
    )
    now = utc_now()
    try:
        admin = await _actor(
            database,
            subject_id=LOCAL_SUBJECT_ID,
            now=now,
        )
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
            scope_rows = (
                await session.execute(
                    select(
                        AssetProjectionModel.system_id,
                        AssetProjectionModel.domain_id,
                        func.count().label("asset_count"),
                        func.count()
                        .filter(
                            (AssetProjectionModel.classification != int(minimum_classification))
                            | (AssetProjectionModel.lifecycle != "ACTIVE")
                            | (AssetProjectionModel.system_id.is_(None))
                            | (AssetProjectionModel.domain_id.is_(None))
                        )
                        .label("invalid_count"),
                    )
                    .where(
                        AssetProjectionModel.workspace_id == LOCAL_WORKSPACE_ID,
                        func.lower(AssetProjectionModel.platform) == platform,
                        AssetProjectionModel.deleted_at.is_(None),
                    )
                    .group_by(
                        AssetProjectionModel.system_id,
                        AssetProjectionModel.domain_id,
                    )
                )
            ).all()
            if (
                not scope_rows
                or any(int(row.invalid_count) for row in scope_rows)
                or any(row.system_id is None or row.domain_id is None for row in scope_rows)
            ):
                raise RuntimeError(
                    "Every selected catalog asset must be ACTIVE, fully scoped, and use the "
                    "requested classification before membership access is granted."
                )
            system_ids = frozenset(cast(UUID, row.system_id) for row in scope_rows)
            domain_ids = frozenset(cast(UUID, row.domain_id) for row in scope_rows)
            memberships = list(
                (
                    await session.scalars(
                        select(WorkspaceMembershipModel)
                        .join(
                            SubjectModel,
                            SubjectModel.id == WorkspaceMembershipModel.subject_id,
                        )
                        .where(
                            WorkspaceMembershipModel.workspace_id == LOCAL_WORKSPACE_ID,
                            WorkspaceMembershipModel.active.is_(True),
                            SubjectModel.active.is_(True),
                        )
                        .order_by(WorkspaceMembershipModel.subject_id)
                    )
                ).all()
            )
        human_memberships = [
            membership
            for membership in memberships
            if "service-accounts" not in _subject_access(membership).groups
            and membership.job_function != "SERVICE_ACCOUNT"
        ]
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
        updated = 0
        for membership in human_memberships:
            command = _chat_access_command(
                membership=membership,
                system_ids=system_ids,
                domain_ids=domain_ids,
                minimum_classification=minimum_classification,
            )
            current = _subject_access(membership)
            desired = replace(
                current,
                clearance=command.clearance,
                allowed_actions=command.allowed_actions,
                denied_actions=command.denied_actions,
                allowed_system_ids=command.allowed_system_ids,
                allowed_domain_ids=command.allowed_domain_ids,
            )
            if desired == current:
                continue
            actor = checker if membership.subject_id == admin.subject_id else admin
            request_hash = canonical_json_hash(
                {
                    "operation": "local.catalog.chat-access",
                    "platform": platform,
                    "command": command.command_document(),
                }
            )
            await service.update_membership_with_hardware_key(
                command=command,
                subject=actor,
                environment=EnvironmentAttributes(requested_at=now),
                request_id=f"local-catalog-chat-access-{membership.subject_id}",
                idempotency_key=(
                    f"local-{platform}-chat-{membership.subject_id}-v{membership.version}"
                ),
                request_hash=request_hash,
            )
            updated += 1
        return {
            "workspace_id": str(LOCAL_WORKSPACE_ID),
            "platform": platform,
            "classification": minimum_classification.name,
            "asset_count": sum(int(row.asset_count) for row in scope_rows),
            "system_scope_count": len(system_ids),
            "domain_scope_count": len(domain_ids),
            "human_membership_count": len(human_memberships),
            "updated_membership_count": updated,
            "service_accounts_excluded": len(memberships) - len(human_memberships),
        }
    finally:
        await database.close()


def main() -> None:
    print(json.dumps(asyncio.run(_run(_parser().parse_args())), sort_keys=True))


if __name__ == "__main__":
    main()
