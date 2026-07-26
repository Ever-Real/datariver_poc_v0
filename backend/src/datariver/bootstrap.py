from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from datariver.config import get_settings
from datariver.domain.authz import Action, Classification
from datariver.domain.common import utc_now
from datariver.domain.membership_renewal import add_calendar_months
from datariver.infrastructure.db.models.platform import (
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.secrets import SecretResolver

LOCAL_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000100")
LOCAL_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000101")
LOCAL_AIRFLOW_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000102")
LOCAL_KEYCLOAK_SUBJECT = "00000000-0000-4000-8000-000000000001"
LOCAL_KEYCLOAK_AIRFLOW_SUBJECT = "00000000-0000-4000-8000-000000000002"
LOCAL_DEMO_IDENTITIES_PATH = Path("/run/datariver/local-demo-identities.json")


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
        allowed_actions=(
            Action.ADMIN_MANAGE,
            Action.CATALOG_READ,
            Action.CATALOG_SEARCH,
            Action.CHANGE_READ,
            Action.CHANGE_REVIEW,
            Action.CHANGE_APPROVE,
            Action.KG_READ,
        ),
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
            Action.CHANGE_READ,
            Action.KG_READ,
        ),
    ),
)


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
    if settings.app_env == "production":
        raise RuntimeError("Local identity bootstrap is forbidden in production mode.")
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
            attributes = {
                "groups": ["security-administrators"],
                "allowed_actions": [
                    action.value for action in Action if action is not Action.CHANGE_RAW_CREATE
                ],
                "denied_actions": [],
                "allowed_system_ids": [],
                "allowed_domain_ids": [],
                "bootstrap": "local-identity-v1",
            }
            if membership is None:
                session.add(
                    WorkspaceMembershipModel(
                        workspace_id=workspace.id,
                        subject_id=subject.id,
                        department_id=None,
                        job_function="LOCAL_ADMINISTRATOR",
                        clearance=int(Classification.RESTRICTED),
                        attributes=attributes,
                        active=True,
                        access_expires_at=add_calendar_months(utc_now(), 6),
                    )
                )
            else:
                membership.clearance = int(Classification.RESTRICTED)
                membership.attributes = attributes
                membership.active = True
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
                demo_attributes = {
                    "groups": list(demo.groups),
                    "allowed_actions": [action.value for action in demo.allowed_actions],
                    "denied_actions": [],
                    "allowed_system_ids": [],
                    "allowed_domain_ids": [],
                    "bootstrap": "local-demo-identities-v1",
                }
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
