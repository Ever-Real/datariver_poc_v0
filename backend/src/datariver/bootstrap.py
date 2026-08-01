from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.config import get_settings
from datariver.domain.authz import SERVICE_ONLY_ACTIONS, Action, Classification
from datariver.domain.capability_catalog import (
    CANONICAL_ADMIN_CAPABILITY_HASH,
    CANONICAL_ADMIN_ROLE_KEY,
    CAPABILITY_CATALOG_VERSION,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
    AccessRoleKind,
    AccessRoleManagementSource,
)
from datariver.domain.common import utc_now
from datariver.domain.knowledge_studio import (
    DEFAULT_KNOWLEDGE_DOMAINS,
    default_knowledge_domain_id,
)
from datariver.domain.membership_renewal import add_calendar_months
from datariver.infrastructure.db.admin_access import membership_access_payload_hash
from datariver.infrastructure.db.models.platform import (
    AccessRoleModel,
    CanonicalAdminBindingModel,
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.secrets import SecretResolver

LOCAL_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000100")
LOCAL_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000101")
LOCAL_AIRFLOW_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000102")
LOCAL_QUALITY_DISPATCH_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000103")
LOCAL_QUALITY_WORKER_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000104")
LOCAL_KNOWLEDGE_INGESTION_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000108")
LOCAL_KNOWLEDGE_PROPOSAL_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000109")
LOCAL_KEYCLOAK_SUBJECT = "00000000-0000-4000-8000-000000000001"
LOCAL_KEYCLOAK_AIRFLOW_SUBJECT = "00000000-0000-4000-8000-000000000002"
LOCAL_KEYCLOAK_QUALITY_DISPATCH_SUBJECT = "00000000-0000-4000-8000-000000000004"
LOCAL_QUALITY_WORKER_EXTERNAL_SUBJECT = "urn:datariver:service:quality-worker"
LOCAL_KNOWLEDGE_INGESTION_EXTERNAL_SUBJECT = (
    "urn:datariver:service:knowledge-studio-ingestion-worker"
)
LOCAL_KNOWLEDGE_PROPOSAL_EXTERNAL_SUBJECT = "urn:datariver:service:knowledge-studio-proposal-worker"
LOCAL_DEMO_IDENTITIES_PATH = Path("/run/datariver/local-demo-identities.json")
LOCAL_SERVICE_IDENTITIES_PATH = Path("/run/datariver/local-service-identities.json")
LOCAL_HUMAN_DASHBOARD_READ_ACTIONS = (
    Action.DASHBOARD_READ,
    Action.QUALITY_READ,
    Action.QUALITY_PROFILE_READ,
)


@dataclass(frozen=True, slots=True)
class LocalDemoIdentity:
    subject_id: UUID
    username: str
    external_subject: str
    display_name: str
    email: str
    job_function: str
    clearance: Classification
    groups: tuple[str, ...]
    allowed_actions: tuple[Action, ...]


@dataclass(frozen=True, slots=True)
class LocalServiceIdentity:
    subject_id: UUID
    external_subject: str
    display_name: str
    groups: tuple[str, ...]
    allowed_actions: tuple[Action, ...]
    bootstrap_contract: str


LOCAL_DEMO_IDENTITIES = (
    LocalDemoIdentity(
        subject_id=UUID("00000000-0000-4000-8000-000000000105"),
        username="jihoon.choi",
        external_subject="00000000-0000-4000-8000-000000000005",
        display_name="최지훈",
        email="jihoon.choi@localhost.invalid",
        job_function="DATA_ENGINEER",
        clearance=Classification.CONFIDENTIAL,
        groups=("data-engineers",),
        allowed_actions=(
            Action.CATALOG_READ,
            Action.CATALOG_SEARCH,
            Action.CATALOG_SYNC,
            Action.CHANGE_CREATE,
            Action.KG_READ,
        ),
    ),
    LocalDemoIdentity(
        subject_id=UUID("00000000-0000-4000-8000-000000000106"),
        username="sua.han",
        external_subject="00000000-0000-4000-8000-000000000006",
        display_name="한수아",
        email="sua.han@localhost.invalid",
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
        # The local profile needs two independent eligible humans for
        # governed maker/checker initialization. This remains local-only.
        groups=("data-stewards", "security-administrators"),
        allowed_actions=tuple(action for action in Action if action in DEFAULT_HUMAN_ADMIN_ACTIONS),
    ),
    LocalDemoIdentity(
        subject_id=UUID("00000000-0000-4000-8000-000000000107"),
        username="minjae.oh",
        external_subject="00000000-0000-4000-8000-000000000007",
        display_name="오민재",
        email="minjae.oh@localhost.invalid",
        job_function="DATA_ANALYST",
        clearance=Classification.INTERNAL,
        groups=("data-analysts",),
        allowed_actions=(
            Action.CATALOG_READ,
            Action.CATALOG_SEARCH,
            Action.CHAT_QUERY,
            Action.CHANGE_READ,
            Action.KG_READ,
        ),
    ),
)


def _local_human_membership_attributes(
    *,
    groups: tuple[str, ...],
    allowed_actions: tuple[Action, ...],
    bootstrap: str,
    allowed_domain_ids: tuple[UUID, ...] = (),
) -> dict[str, object]:
    """Build the single-Workspace local identity authorization envelope."""

    resolved_actions = tuple(dict.fromkeys((*allowed_actions, *LOCAL_HUMAN_DASHBOARD_READ_ACTIONS)))
    return {
        "groups": list(groups),
        "allowed_actions": [action.value for action in resolved_actions],
        "denied_actions": [],
        "allowed_system_ids": [],
        "allowed_domain_ids": [str(value) for value in allowed_domain_ids],
        "default_workspace": True,
        "bootstrap": bootstrap,
    }


def _local_demo_identities(
    state_path: Path = LOCAL_DEMO_IDENTITIES_PATH,
) -> tuple[LocalDemoIdentity, ...]:
    if not state_path.exists():
        return LOCAL_DEMO_IDENTITIES
    if not state_path.is_file() or state_path.stat().st_size > 4_096:
        raise RuntimeError("The local demo identity state file is invalid.")
    try:
        document = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("The local demo identity state file is invalid.") from error
    usernames = {demo.username for demo in LOCAL_DEMO_IDENTITIES}
    if not isinstance(document, dict) or set(document) != usernames:
        raise RuntimeError("The local demo identity state file is invalid.")
    resolved: list[LocalDemoIdentity] = []
    external_subjects: set[str] = set()
    for demo in LOCAL_DEMO_IDENTITIES:
        value = document.get(demo.username)
        try:
            external_subject = str(UUID(value)) if isinstance(value, str) else ""
        except ValueError as error:
            raise RuntimeError("The local demo identity state file is invalid.") from error
        if not external_subject or external_subject in external_subjects:
            raise RuntimeError("The local demo identity state file is invalid.")
        external_subjects.add(external_subject)
        resolved.append(replace(demo, external_subject=external_subject))
    return tuple(resolved)


def _local_quality_dispatch_external_subject(
    state_path: Path = LOCAL_SERVICE_IDENTITIES_PATH,
) -> str:
    if not state_path.exists():
        return LOCAL_KEYCLOAK_QUALITY_DISPATCH_SUBJECT
    if not state_path.is_file() or state_path.stat().st_size > 1_024:
        raise RuntimeError("The local service identity state file is invalid.")
    try:
        document = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("The local service identity state file is invalid.") from error
    if not isinstance(document, dict) or set(document) != {"quality_dispatch"}:
        raise RuntimeError("The local service identity state file is invalid.")
    value = document["quality_dispatch"]
    if not isinstance(value, str):
        raise RuntimeError("The local service identity state file is invalid.")
    try:
        return str(UUID(value))
    except ValueError as error:
        raise RuntimeError("The local service identity state file is invalid.") from error


def _local_service_identities() -> tuple[LocalServiceIdentity, ...]:
    return (
        LocalServiceIdentity(
            subject_id=LOCAL_QUALITY_DISPATCH_SUBJECT_ID,
            external_subject=_local_quality_dispatch_external_subject(),
            display_name="DataRiver Quality Dispatch Service",
            groups=("service-accounts", "quality-dispatchers"),
            allowed_actions=(Action.QUALITY_DISPATCH,),
            bootstrap_contract="local-quality-service-v1",
        ),
        LocalServiceIdentity(
            subject_id=LOCAL_QUALITY_WORKER_SUBJECT_ID,
            external_subject=LOCAL_QUALITY_WORKER_EXTERNAL_SUBJECT,
            display_name="DataRiver Quality Worker",
            groups=("service-accounts", "quality-workers"),
            allowed_actions=(Action.QUALITY_EXECUTE,),
            bootstrap_contract="local-quality-service-v1",
        ),
        LocalServiceIdentity(
            subject_id=LOCAL_KNOWLEDGE_INGESTION_SUBJECT_ID,
            external_subject=LOCAL_KNOWLEDGE_INGESTION_EXTERNAL_SUBJECT,
            display_name="DataRiver Knowledge Studio Ingestion Worker",
            groups=("service-accounts", "knowledge-ingestion-workers"),
            allowed_actions=(Action.KG_INGEST_EXECUTE,),
            bootstrap_contract="local-knowledge-studio-ingestion-service-v1",
        ),
        LocalServiceIdentity(
            subject_id=LOCAL_KNOWLEDGE_PROPOSAL_SUBJECT_ID,
            external_subject=LOCAL_KNOWLEDGE_PROPOSAL_EXTERNAL_SUBJECT,
            display_name="DataRiver Knowledge Studio Proposal Worker",
            groups=("service-accounts", "knowledge-proposal-workers"),
            allowed_actions=(Action.KG_PROPOSAL_EXECUTE,),
            bootstrap_contract="local-knowledge-studio-proposal-service-v1",
        ),
    )


def _resolve_local_subject(
    fixed_subject: SubjectModel | None,
    identity_subject: SubjectModel | None,
    *,
    label: str,
) -> SubjectModel | None:
    if (
        fixed_subject is not None
        and identity_subject is not None
        and identity_subject is not fixed_subject
    ):
        raise RuntimeError(f"The local {label} identity belongs to another subject.")
    return fixed_subject if fixed_subject is not None else identity_subject


async def bootstrap_local_identity() -> dict[str, object]:
    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("Local identity bootstrap requires APP_ENV=development exactly.")
    resolver = SecretResolver()
    database = Database(
        settings.bootstrap_database_url,
        password=resolver.resolve(settings.bootstrap_database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-local-bootstrap",
    )
    try:
        async with database.session_factory() as session, session.begin():
            workspace = await session.get(WorkspaceModel, LOCAL_WORKSPACE_ID)
            if workspace is None:
                workspace = WorkspaceModel(
                    id=LOCAL_WORKSPACE_ID,
                    slug="local-development",
                    name="Local Development",
                    status="ACTIVE",
                    settings={"bootstrap": "local-identity-v1"},
                    version=1,
                )
                session.add(workspace)
            default_domain_ids = tuple(
                default_knowledge_domain_id(workspace.id, slug)
                for slug, _display_name in DEFAULT_KNOWLEDGE_DOMAINS
            )
            subject = await session.get(SubjectModel, LOCAL_SUBJECT_ID)
            identity_subject = (
                await session.scalars(
                    select(SubjectModel).where(
                        SubjectModel.issuer == settings.oidc_issuer,
                        SubjectModel.external_subject == LOCAL_KEYCLOAK_SUBJECT,
                    )
                )
            ).one_or_none()
            subject = _resolve_local_subject(subject, identity_subject, label="administrator")
            if subject is None:
                subject = SubjectModel(
                    id=LOCAL_SUBJECT_ID,
                    issuer=settings.oidc_issuer,
                    external_subject=LOCAL_KEYCLOAK_SUBJECT,
                    display_name="DataRiver Local Administrator",
                    active=True,
                )
                session.add(subject)
                await session.flush()
            else:
                subject.issuer = settings.oidc_issuer
                subject.external_subject = LOCAL_KEYCLOAK_SUBJECT
                subject.display_name = "DataRiver Local Administrator"
                subject.active = True
            membership = await session.get(
                WorkspaceMembershipModel,
                {"workspace_id": workspace.id, "subject_id": subject.id},
            )
            attributes = _local_human_membership_attributes(
                groups=("security-administrators",),
                allowed_actions=tuple(
                    action for action in Action if action in DEFAULT_HUMAN_ADMIN_ACTIONS
                ),
                bootstrap="local-identity-v1",
                allowed_domain_ids=default_domain_ids,
            )
            if membership is None:
                membership = WorkspaceMembershipModel(
                    workspace_id=workspace.id,
                    subject_id=subject.id,
                    department_id=None,
                    job_function="LOCAL_ADMINISTRATOR",
                    clearance=int(Classification.RESTRICTED),
                    attributes=attributes,
                    active=True,
                    access_expires_at=add_calendar_months(utc_now(), 6),
                )
                session.add(membership)
            else:
                membership.clearance = int(Classification.RESTRICTED)
                membership.attributes = attributes
                membership.active = True
                membership.access_expires_at = add_calendar_months(utc_now(), 6)
            await session.flush()
            await _reconcile_local_canonical_admin_binding(
                session=session,
            )
            airflow_subject = await session.get(SubjectModel, LOCAL_AIRFLOW_SUBJECT_ID)
            identity_airflow_subject = (
                await session.scalars(
                    select(SubjectModel).where(
                        SubjectModel.issuer == settings.oidc_issuer,
                        SubjectModel.external_subject == LOCAL_KEYCLOAK_AIRFLOW_SUBJECT,
                    )
                )
            ).one_or_none()
            airflow_subject = _resolve_local_subject(
                airflow_subject,
                identity_airflow_subject,
                label="Airflow",
            )
            if airflow_subject is None:
                airflow_subject = SubjectModel(
                    id=LOCAL_AIRFLOW_SUBJECT_ID,
                    issuer=settings.oidc_issuer,
                    external_subject=LOCAL_KEYCLOAK_AIRFLOW_SUBJECT,
                    display_name="DataRiver Airflow Service",
                    active=True,
                )
                session.add(airflow_subject)
                await session.flush()
            else:
                airflow_subject.issuer = settings.oidc_issuer
                airflow_subject.external_subject = LOCAL_KEYCLOAK_AIRFLOW_SUBJECT
                airflow_subject.display_name = "DataRiver Airflow Service"
                airflow_subject.active = True
            airflow_membership = await session.get(
                WorkspaceMembershipModel,
                {"workspace_id": workspace.id, "subject_id": airflow_subject.id},
            )
            airflow_attributes = {
                "groups": ["service-accounts", "registration-workers"],
                "allowed_actions": [
                    Action.CATALOG_READ.value,
                    Action.CATALOG_SEARCH.value,
                    Action.CATALOG_SYNC.value,
                ],
                "denied_actions": [],
                "allowed_system_ids": [],
                "allowed_domain_ids": [],
                "bootstrap": "local-airflow-service-v2",
            }
            if airflow_membership is None:
                session.add(
                    WorkspaceMembershipModel(
                        workspace_id=workspace.id,
                        subject_id=airflow_subject.id,
                        department_id=None,
                        job_function="SERVICE_ACCOUNT",
                        clearance=int(Classification.RESTRICTED),
                        attributes=airflow_attributes,
                        active=True,
                        access_expires_at=None,
                    )
                )
            else:
                airflow_membership.clearance = int(Classification.RESTRICTED)
                airflow_membership.attributes = airflow_attributes
                airflow_membership.active = True
            for service_definition in _local_service_identities():
                fixed_service_subject = await session.get(
                    SubjectModel,
                    service_definition.subject_id,
                )
                identity_service_subject = (
                    await session.scalars(
                        select(SubjectModel).where(
                            SubjectModel.issuer == settings.oidc_issuer,
                            SubjectModel.external_subject == service_definition.external_subject,
                        )
                    )
                ).one_or_none()
                service_subject = _resolve_local_subject(
                    fixed_service_subject,
                    identity_service_subject,
                    label=service_definition.display_name,
                )
                if service_subject is None:
                    service_subject = SubjectModel(
                        id=service_definition.subject_id,
                        issuer=settings.oidc_issuer,
                        external_subject=service_definition.external_subject,
                        display_name=service_definition.display_name,
                        active=True,
                    )
                    session.add(service_subject)
                    await session.flush()
                else:
                    service_subject.issuer = settings.oidc_issuer
                    service_subject.external_subject = service_definition.external_subject
                    service_subject.display_name = service_definition.display_name
                    service_subject.active = True
                service_membership = await session.get(
                    WorkspaceMembershipModel,
                    {"workspace_id": workspace.id, "subject_id": service_subject.id},
                )
                service_attributes = {
                    "groups": list(service_definition.groups),
                    "allowed_actions": [
                        action.value for action in service_definition.allowed_actions
                    ],
                    "denied_actions": [],
                    # Empty scopes intentionally restrict the local service to PUBLIC
                    # assets until an operator assigns exact governed scopes.
                    "allowed_system_ids": [],
                    "allowed_domain_ids": [],
                    "bootstrap": service_definition.bootstrap_contract,
                }
                if service_membership is None:
                    session.add(
                        WorkspaceMembershipModel(
                            workspace_id=workspace.id,
                            subject_id=service_subject.id,
                            department_id=None,
                            job_function="SERVICE_ACCOUNT",
                            clearance=int(Classification.RESTRICTED),
                            attributes=service_attributes,
                            active=True,
                            access_expires_at=None,
                        )
                    )
                else:
                    service_membership.job_function = "SERVICE_ACCOUNT"
                    service_membership.clearance = int(Classification.RESTRICTED)
                    service_membership.attributes = service_attributes
                    service_membership.active = True
                    service_membership.access_expires_at = None
            for demo in _local_demo_identities():
                fixed_demo_subject = await session.get(SubjectModel, demo.subject_id)
                identity_demo_subject = (
                    await session.scalars(
                        select(SubjectModel).where(
                            SubjectModel.issuer == settings.oidc_issuer,
                            SubjectModel.external_subject == demo.external_subject,
                        )
                    )
                ).one_or_none()
                demo_subject = _resolve_local_subject(
                    fixed_demo_subject,
                    identity_demo_subject,
                    label=demo.display_name,
                )
                if demo_subject is None:
                    demo_subject = SubjectModel(
                        id=demo.subject_id,
                        issuer=settings.oidc_issuer,
                        external_subject=demo.external_subject,
                        display_name=demo.display_name,
                        email=demo.email,
                        active=True,
                    )
                    session.add(demo_subject)
                    await session.flush()
                else:
                    demo_subject.issuer = settings.oidc_issuer
                    demo_subject.external_subject = demo.external_subject
                    demo_subject.display_name = demo.display_name
                    demo_subject.email = demo.email
                    demo_subject.active = True
                demo_membership = await session.get(
                    WorkspaceMembershipModel,
                    {"workspace_id": workspace.id, "subject_id": demo_subject.id},
                )
                demo_attributes = _local_human_membership_attributes(
                    groups=demo.groups,
                    allowed_actions=demo.allowed_actions,
                    bootstrap="local-demo-identities-v1",
                )
                if demo_membership is None:
                    session.add(
                        WorkspaceMembershipModel(
                            workspace_id=workspace.id,
                            subject_id=demo_subject.id,
                            department_id=None,
                            job_function=demo.job_function,
                            clearance=int(demo.clearance),
                            attributes=demo_attributes,
                            active=True,
                            access_expires_at=add_calendar_months(utc_now(), 6),
                        )
                    )
                else:
                    demo_membership.job_function = demo.job_function
                    demo_membership.clearance = int(demo.clearance)
                    demo_membership.attributes = demo_attributes
                    demo_membership.active = True
                    demo_membership.access_expires_at = add_calendar_months(utc_now(), 6)
        return {
            "workspace_id": str(LOCAL_WORKSPACE_ID),
            "username": "datariver-admin",
            "environment": settings.app_env,
        }
    finally:
        await database.close()


async def _reconcile_local_canonical_admin_binding(
    *,
    session: AsyncSession,
) -> None:
    """Bind the fixed local administrator without accepting any target parameters."""

    workspace = await session.get(WorkspaceModel, LOCAL_WORKSPACE_ID)
    subject = await session.get(SubjectModel, LOCAL_SUBJECT_ID)
    membership = await session.get(
        WorkspaceMembershipModel,
        {"workspace_id": LOCAL_WORKSPACE_ID, "subject_id": LOCAL_SUBJECT_ID},
    )
    if workspace is None or subject is None or membership is None:
        raise RuntimeError("The fixed local Canonical Admin target does not exist.")
    expected_actions = sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS)
    attributes = membership.attributes
    if (
        not subject.active
        or not membership.active
        or membership.job_function == "SERVICE_ACCOUNT"
        or membership.clearance != int(Classification.RESTRICTED)
        or attributes.get("groups") != ["security-administrators"]
        or sorted(attributes.get("allowed_actions", [])) != expected_actions
        or attributes.get("denied_actions") != []
    ):
        raise RuntimeError("The local administrator does not match the canonical human envelope.")
    if not set(expected_actions).isdisjoint(action.value for action in SERVICE_ONLY_ACTIONS):
        raise RuntimeError("The local administrator contains a service-only Action.")

    canonical_role = (
        await session.scalars(
            select(AccessRoleModel).where(
                AccessRoleModel.workspace_id == LOCAL_WORKSPACE_ID,
                AccessRoleModel.role_kind == AccessRoleKind.CANONICAL_ADMIN.value,
            )
        )
    ).one_or_none()
    role_document = {
        "role_key": CANONICAL_ADMIN_ROLE_KEY,
        "role_kind": AccessRoleKind.CANONICAL_ADMIN.value,
        "management_source": AccessRoleManagementSource.SERVER_CANONICAL.value,
        "capability_catalog_version": CAPABILITY_CATALOG_VERSION,
        "name": "Canonical Admin",
        "description": "Server-owned Canonical Admin capability definition.",
        "clearance": int(Classification.RESTRICTED),
        "groups": ["security-administrators"],
        "allowed_actions": expected_actions,
        "denied_actions": [],
        "allowed_system_ids": [],
        "allowed_domain_ids": [],
        "active": True,
        "updated_by": None,
    }
    if canonical_role is None:
        canonical_role = AccessRoleModel(workspace_id=LOCAL_WORKSPACE_ID, **role_document)
        session.add(canonical_role)
        await session.flush()
    else:
        changed = any(getattr(canonical_role, key) != value for key, value in role_document.items())
        if changed:
            for key, value in role_document.items():
                setattr(canonical_role, key, value)
            canonical_role.version += 1
            await session.flush()

    access_hash = membership_access_payload_hash(membership)
    binding = await session.get(
        CanonicalAdminBindingModel,
        {"workspace_id": LOCAL_WORKSPACE_ID, "subject_id": LOCAL_SUBJECT_ID},
    )
    binding_document = {
        "canonical_role_id": canonical_role.id,
        "role_kind": AccessRoleKind.CANONICAL_ADMIN.value,
        "canonical_role_version": canonical_role.version,
        "capability_catalog_version": CAPABILITY_CATALOG_VERSION,
        "capability_hash": CANONICAL_ADMIN_CAPABILITY_HASH,
        "membership_version": membership.version,
        "membership_access_hash": access_hash,
        "state": "ACTIVE",
        "binding_source": "LOCAL_DEVELOPMENT_BOOTSTRAP",
    }
    if binding is None:
        session.add(
            CanonicalAdminBindingModel(
                workspace_id=LOCAL_WORKSPACE_ID,
                subject_id=LOCAL_SUBJECT_ID,
                **binding_document,
            )
        )
        return
    if any(getattr(binding, key) != value for key, value in binding_document.items()):
        for key, value in binding_document.items():
            setattr(binding, key, value)
        binding.version += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap non-production DataRiver resources.")
    parser.add_argument("target", choices=("local-identity",))
    arguments = parser.parse_args()
    if arguments.target != "local-identity":
        parser.error("Unsupported bootstrap target.")
    result = asyncio.run(bootstrap_local_identity())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
