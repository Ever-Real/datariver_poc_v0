from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from datariver.config import get_settings
from datariver.domain.authz import Action, Classification
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
                "groups": ["service-accounts"],
                "allowed_actions": [
                    Action.CATALOG_READ.value,
                    Action.CATALOG_SEARCH.value,
                    Action.CATALOG_SYNC.value,
                ],
                "denied_actions": [],
                "allowed_system_ids": [],
                "allowed_domain_ids": [],
                "bootstrap": "local-airflow-service-v1",
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
                    )
                )
            else:
                airflow_membership.clearance = int(Classification.RESTRICTED)
                airflow_membership.attributes = airflow_attributes
                airflow_membership.active = True
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
