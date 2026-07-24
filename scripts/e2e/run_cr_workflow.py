from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4, uuid5

import asyncpg  # type: ignore[import-untyped]
import boto3
import httpx
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000100")
ASSET_ID = UUID("019f7e6d-2b3d-7f2f-928c-4cf44b7a4153")
SYSTEM_ID = UUID("389f1c40-3535-5a02-b8ab-3e6f6703e784")
DOMAIN_ID = UUID("66a7df74-cb67-5e90-84f7-c7e95747d193")
E2E_NAMESPACE = UUID("d5bd7db4-7601-4a1c-ae2b-67e0f4963c06")
E2E_CLIENT_ID = "datariver-local-e2e"
E2E_CLIENT_SECRET_PATH = Path("/private/tmp/datariver-local-e2e-client-secret")
KNOWLEDGE_SOURCE_PATH = Path("/private/tmp/samilpwc_semicon-trends-outlook-2026.pdf")
KNOWLEDGE_SOURCE_SHA256 = "6d406f252e7ea42b3ad9a0218b4ff7f87fac762a4395dfc3a19ad3e702c58dea"
KNOWLEDGE_GRAPH_SLUG = "samilpwc-semicon-2026-e2e"


@dataclass(slots=True)
class E2EState:
    subject_ids: dict[str, UUID]
    change_request_ids: list[UUID]
    object_locations: list[tuple[str, str]]
    created_system_id: UUID | None = None
    created_schema_scope_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Persona:
    key: str
    username: str
    display_name: str
    job_function: str
    clearance: int
    groups: tuple[str, ...]
    actions: tuple[str, ...]
    responsibility: str | None = None


PERSONAS = (
    Persona(
        key="requester",
        username="datariver-cr-e2e-requester",
        display_name="DataRiver CR E2E Requester",
        job_function="CHANGE_REQUESTER",
        clearance=2,
        groups=("change-requesters",),
        actions=(
            "catalog.search",
            "catalog.read",
            "change.create",
            "change.read",
            "change.edit",
            "kg.create",
            "kg.read",
            "kg.edit",
            "chat.query",
        ),
    ),
    Persona(
        key="developer",
        username="datariver-cr-e2e-developer",
        display_name="DataRiver CR E2E Developer",
        job_function="SYSTEM_DEVELOPER",
        clearance=2,
        groups=("change-developers",),
        actions=("change.read", "change.review", "change.approve", "attachment.download"),
        responsibility="DEVELOPER",
    ),
    Persona(
        key="steward",
        username="datariver-cr-e2e-steward",
        display_name="DataRiver CR E2E Data Steward",
        job_function="DATA_STEWARD",
        clearance=2,
        groups=("data-stewards",),
        actions=("change.read", "change.approve", "kg.read", "kg.review"),
        responsibility="DATA_STEWARD",
    ),
    Persona(
        key="admin",
        username="datariver-cr-e2e-admin",
        display_name="DataRiver CR E2E Global Administrator",
        job_function="SECURITY_ADMINISTRATOR",
        clearance=3,
        groups=("security-administrators",),
        actions=(
            "change.read",
            "change.approve",
            "kg.read",
            "kg.publish",
            "chat.query",
            "admin.manage",
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local CR workflow through FINAL_REVIEW and prove that LoA1 cannot record "
            "FINAL approvals."
        )
    )
    parser.add_argument("--confirm-local-e2e", action="store_true")
    parser.add_argument("--api-base-url", default="http://localhost:38101/api/v1")
    parser.add_argument("--keycloak-base-url", default="http://localhost:18081")
    parser.add_argument("--keycloak-admin-username", default="datariver-bootstrap")
    parser.add_argument("--database-host", default="127.0.0.1")
    parser.add_argument("--database-port", type=int, default=15432)
    parser.add_argument("--database-name", default="datariver")
    parser.add_argument("--database-user", default="datariver_owner")
    parser.add_argument("--s3-endpoint-url", default="http://127.0.0.1:8333")
    args = parser.parse_args()
    if not args.confirm_local_e2e:
        parser.error("--confirm-local-e2e is required because this command creates local fixtures")
    for label, value in (
        ("API", args.api_base_url),
        ("Keycloak", args.keycloak_base_url),
        ("S3", args.s3_endpoint_url),
    ):
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
            parser.error(f"{label} URL must be an HTTP loopback URL")
    if args.database_host not in {"localhost", "127.0.0.1"}:
        parser.error("the database host must be loopback")
    return args


def read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Required local secret file is empty: {path.name}")
    return value


def assert_development_environment() -> None:
    environment_path = ROOT / ".env"
    values: dict[str, str] = {}
    if environment_path.exists():
        for raw_line in environment_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    if values.get("APP_ENV", "development").lower() == "production":
        raise RuntimeError("The CR E2E fixture is disabled in production.")


class KeycloakAdmin:
    def __init__(self, client: httpx.AsyncClient, base_url: str, token: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def request(
        self,
        method: str,
        path: str,
        *,
        expected: set[int],
        json_document: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = await self._client.request(
            method,
            f"{self._base_url}{path}",
            headers=self._headers,
            json=json_document,
            params=params,
        )
        if response.status_code not in expected:
            raise RuntimeError(
                f"Keycloak Admin API returned HTTP {response.status_code} for {method} {path}."
            )
        return response

    async def create_user(self, persona: Persona, password: str) -> str:
        users = await self._find_users(persona.username)
        if users:
            raise RuntimeError(
                f"Reserved local E2E user already exists: {persona.username}. "
                "Refusing to overwrite a Keycloak identity."
            )
        document = {
            "username": persona.username,
            "firstName": "DataRiver",
            "lastName": persona.display_name.removeprefix("DataRiver "),
            "email": f"{persona.username}@localhost.invalid",
            "emailVerified": True,
            "enabled": True,
            "requiredActions": [],
        }
        await self.request(
            "POST",
            "/admin/realms/datariver/users",
            expected={201},
            json_document=document,
        )
        users = await self._find_users(persona.username)
        if len(users) != 1 or not isinstance(users[0].get("id"), str):
            raise RuntimeError(f"Keycloak user provisioning failed for {persona.username}.")
        user_id = str(users[0]["id"])
        await self.request(
            "PUT",
            f"/admin/realms/datariver/users/{user_id}/reset-password",
            expected={204},
            json_document={"type": "password", "value": password, "temporary": False},
        )
        await self.request(
            "POST",
            f"/admin/realms/datariver/users/{user_id}/logout",
            expected={204},
        )
        return user_id

    async def _find_users(self, username: str) -> list[dict[str, Any]]:
        response = await self.request(
            "GET",
            "/admin/realms/datariver/users",
            expected={200},
            params={"username": username, "exact": "true"},
        )
        value = response.json()
        if not isinstance(value, list):
            raise RuntimeError("Keycloak user lookup returned an invalid document.")
        return [item for item in value if isinstance(item, dict)]

    async def _find_clients(self) -> list[dict[str, Any]]:
        response = await self.request(
            "GET",
            "/admin/realms/datariver/clients",
            expected={200},
            params={"clientId": E2E_CLIENT_ID},
        )
        value = response.json()
        if not isinstance(value, list):
            raise RuntimeError("Keycloak client lookup returned an invalid document.")
        return [
            item
            for item in value
            if isinstance(item, dict) and item.get("clientId") == E2E_CLIENT_ID
        ]

    async def create_direct_grant_client(self) -> tuple[str, str]:
        client_document = {
            "clientId": E2E_CLIENT_ID,
            "name": "Local DataRiver E2E",
            "description": "Ephemeral local-only CR E2E direct-grant client; always torn down.",
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "clientAuthenticatorType": "client-secret",
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": True,
            "implicitFlowEnabled": False,
            "serviceAccountsEnabled": False,
            "defaultClientScopes": ["basic", "acr", "profile", "email", "roles"],
        }
        matches = await self._find_clients()
        if matches:
            raise RuntimeError(
                f"Reserved local E2E client already exists: {E2E_CLIENT_ID}. "
                "Refusing to overwrite a Keycloak client."
            )
        await self.request(
            "POST",
            "/admin/realms/datariver/clients",
            expected={201},
            json_document=client_document,
        )
        matches = await self._find_clients()
        if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
            raise RuntimeError("The local E2E Keycloak client could not be resolved.")
        internal_id = str(matches[0]["id"])
        await self.request(
            "POST",
            f"/admin/realms/datariver/clients/{internal_id}/protocol-mappers/models",
            expected={201},
            json_document={
                "name": "datariver-api-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "consentRequired": False,
                "config": {
                    "included.client.audience": "datariver-api",
                    "id.token.claim": "false",
                    "access.token.claim": "true",
                },
            },
        )
        secret_response = await self.request(
            "GET",
            f"/admin/realms/datariver/clients/{internal_id}/client-secret",
            expected={200},
        )
        client_secret = secret_response.json().get("value")
        if not isinstance(client_secret, str) or not client_secret:
            raise RuntimeError("The local E2E client secret is unavailable.")
        write_private_secret(E2E_CLIENT_SECRET_PATH, client_secret)
        return internal_id, client_secret

    async def delete_reserved_fixtures(self) -> dict[str, int]:
        deleted_users = 0
        errors: list[str] = []
        for persona in PERSONAS:
            try:
                users = await self._find_users(persona.username)
                for user in users:
                    user_id = user.get("id")
                    if not isinstance(user_id, str):
                        errors.append(f"{persona.username}: missing Keycloak user id")
                        continue
                    if user.get("email") != f"{persona.username}@localhost.invalid":
                        errors.append(
                            f"{persona.username}: reserved username has a non-E2E email; "
                            "not deleted"
                        )
                        continue
                    await self.request(
                        "POST",
                        f"/admin/realms/datariver/users/{user_id}/logout",
                        expected={204, 404},
                    )
                    await self.request(
                        "DELETE",
                        f"/admin/realms/datariver/users/{user_id}",
                        expected={204, 404},
                    )
                    deleted_users += 1
            except Exception as error:
                errors.append(f"{persona.username}: {type(error).__name__}: {error}")

        deleted_clients = 0
        try:
            for client_document in await self._find_clients():
                internal_id = client_document.get("id")
                description = client_document.get("description")
                if not isinstance(internal_id, str):
                    errors.append(f"{E2E_CLIENT_ID}: missing Keycloak client id")
                    continue
                if not isinstance(description, str) or "E2E" not in description:
                    errors.append(
                        f"{E2E_CLIENT_ID}: reserved client has a non-E2E description; not deleted"
                    )
                    continue
                await self.request(
                    "DELETE",
                    f"/admin/realms/datariver/clients/{internal_id}",
                    expected={204, 404},
                )
                deleted_clients += 1
        except Exception as error:
            errors.append(f"{E2E_CLIENT_ID}: {type(error).__name__}: {error}")

        remaining_users = 0
        for persona in PERSONAS:
            remaining_users += len(await self._find_users(persona.username))
        remaining_clients = len(await self._find_clients())
        if errors or remaining_users or remaining_clients:
            detail = "; ".join(errors) if errors else "fixture remains after DELETE"
            raise RuntimeError(
                "Keycloak E2E teardown was incomplete: "
                f"users={remaining_users}, clients={remaining_clients}; {detail}"
            )
        return {"deleted_users": deleted_users, "deleted_clients": deleted_clients}


async def keycloak_admin_token(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    username: str,
    password: str,
) -> str:
    response = await client.post(
        f"{base_url.rstrip('/')}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"Keycloak admin authentication returned HTTP {response.status_code}.")
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Keycloak admin authentication did not return an access token.")
    return token


async def persona_token(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    client_id: str,
    client_secret: str,
    username: str,
    password: str,
) -> str:
    response = await client.post(
        f"{base_url.rstrip('/')}/realms/datariver/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
            "scope": "openid",
        },
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Temporary direct-grant authentication returned HTTP {response.status_code} "
            f"for {username}."
        )
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"Temporary direct-grant authentication failed for {username}.")
    return token


async def service_token(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    client_secret: str,
) -> str:
    response = await client.post(
        f"{base_url.rstrip('/')}/realms/datariver/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "datariver-airflow",
            "client_secret": client_secret,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Airflow service-account authentication returned HTTP {response.status_code}."
        )
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Airflow service-account authentication returned no access token.")
    return token


def write_private_secret(path: Path, value: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, value.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def configure_database_fixture(
    connection: asyncpg.Connection[Any],
    *,
    issuer: str,
    keycloak_user_ids: dict[str, str],
    state: E2EState,
) -> tuple[dict[str, UUID], dict[str, Any]]:
    async with connection.transaction():
        workspace = await connection.fetchrow(
            "SELECT slug, status FROM platform.workspaces WHERE id = $1 FOR UPDATE",
            WORKSPACE_ID,
        )
        if workspace is None or workspace["slug"] != "local-development":
            raise RuntimeError("The expected local-development workspace is unavailable.")
        if workspace["status"] != "ACTIVE":
            raise RuntimeError("The local-development workspace is not active.")

        asset = await connection.fetchrow(
            """
            SELECT platform, database_name, schema_name, name, external_urn,
                   classification, lifecycle, system_id, domain_id
            FROM catalog.assets_projection
            WHERE workspace_id = $1 AND id = $2
            """,
            WORKSPACE_ID,
            ASSET_ID,
        )
        if asset is None:
            raise RuntimeError("The required real DataHub asset projection is unavailable.")
        if (
            asset["classification"] != 2
            or asset["lifecycle"] != "ACTIVE"
            or asset["system_id"] != SYSTEM_ID
            or asset["domain_id"] != DOMAIN_ID
        ):
            raise RuntimeError(
                "The real DataHub asset binding does not match the approved E2E target."
            )

        system_row = await connection.fetchrow(
            """
            SELECT id, workspace_id, code, active
            FROM platform.data_systems
            WHERE workspace_id = $1 AND id = $2
            """,
            WORKSPACE_ID,
            SYSTEM_ID,
        )
        if system_row is None:
            await connection.execute(
                """
                INSERT INTO platform.data_systems (
                    id, workspace_id, code, name, description, active, version
                ) VALUES (
                    $1, $2, 'SEMICON_E2E', 'Semiconductor E2E',
                    'Ephemeral local CR E2E routing fixture; always torn down.', TRUE, 1
                )
                """,
                SYSTEM_ID,
                WORKSPACE_ID,
            )
            state.created_system_id = SYSTEM_ID
        elif system_row["active"] is not True:
            raise RuntimeError("The target CR System exists but is inactive.")

        schema_scope = await connection.fetchrow(
            """
            SELECT id, system_id, active
            FROM platform.system_schema_scopes
            WHERE workspace_id = $1
              AND platform = $2
              AND database_name = $3
              AND schema_name = $4
            """,
            WORKSPACE_ID,
            asset["platform"],
            asset["database_name"],
            asset["schema_name"],
        )
        if schema_scope is None:
            schema_scope_id = uuid5(
                E2E_NAMESPACE,
                f"schema:{asset['platform']}:{asset['database_name']}:{asset['schema_name']}",
            )
            await connection.execute(
                """
                INSERT INTO platform.system_schema_scopes (
                    id, workspace_id, system_id, platform, database_name, schema_name,
                    active, version
                ) VALUES ($1, $2, $3, $4, $5, $6, TRUE, 1)
                """,
                schema_scope_id,
                WORKSPACE_ID,
                SYSTEM_ID,
                asset["platform"],
                asset["database_name"],
                asset["schema_name"],
            )
            state.created_schema_scope_id = schema_scope_id
        elif schema_scope["system_id"] != SYSTEM_ID or schema_scope["active"] is not True:
            raise RuntimeError("The target asset schema is not actively mapped to its CR System.")

        subject_ids: dict[str, UUID] = {}
        for persona in PERSONAS:
            keycloak_user_id = keycloak_user_ids[persona.key]
            stable_subject_id = uuid5(E2E_NAMESPACE, f"subject:{persona.key}")
            conflict = await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM iam.subjects
                    WHERE id = $1 OR (issuer = $2 AND external_subject = $3)
                )
                """,
                stable_subject_id,
                issuer,
                keycloak_user_id,
            )
            if conflict:
                raise RuntimeError(
                    f"Reserved database subject already exists for {persona.key}; "
                    "refusing to overwrite it."
                )
            await connection.execute(
                """
                INSERT INTO iam.subjects (
                    id, issuer, external_subject, display_name, email, active
                ) VALUES ($1, $2, $3, $4, $5, TRUE)
                """,
                stable_subject_id,
                issuer,
                keycloak_user_id,
                persona.display_name,
                f"{persona.username}@localhost.invalid",
            )
            subject_id = stable_subject_id
            subject_ids[persona.key] = subject_id
            attributes = {
                "groups": list(persona.groups),
                "denied_actions": [],
                "allowed_actions": list(persona.actions),
                "allowed_system_ids": [str(SYSTEM_ID)],
                "allowed_domain_ids": [str(DOMAIN_ID)],
                "default_workspace": "true",
                "e2e_fixture": "CR_WORKFLOW_V1",
            }
            await connection.execute(
                """
                INSERT INTO iam.workspace_memberships (
                    workspace_id, subject_id, department_id, job_function, clearance,
                    attributes, active, access_expires_at, version
                ) VALUES ($1, $2, NULL, $3, $4, $5::jsonb, TRUE,
                          CURRENT_TIMESTAMP + INTERVAL '180 days', 1)
                """,
                WORKSPACE_ID,
                subject_id,
                persona.job_function,
                persona.clearance,
                json.dumps(attributes, separators=(",", ":"), sort_keys=True),
            )

        for persona in PERSONAS:
            if persona.responsibility is None:
                continue
            subject_id = subject_ids[persona.key]
            assignment_id = uuid5(
                E2E_NAMESPACE,
                f"assignee:{SYSTEM_ID}:{subject_id}:{persona.responsibility}",
            )
            await connection.execute(
                """
                INSERT INTO platform.system_assignees (
                    id, workspace_id, system_id, subject_id, responsibility,
                    priority, active, version
                ) VALUES ($1, $2, $3, $4, $5, 1, TRUE, 1)
                """,
                assignment_id,
                WORKSPACE_ID,
                SYSTEM_ID,
                subject_id,
                persona.responsibility,
            )

    return subject_ids, dict(asset)


async def collect_e2e_object_locations(
    connection: asyncpg.Connection[Any], change_request_ids: list[UUID]
) -> list[tuple[str, str]]:
    if not change_request_ids:
        return []
    rows = await connection.fetch(
        """
        SELECT bucket, object_key
        FROM governance.change_request_attachments
        WHERE workspace_id = $1 AND change_request_id = ANY($2::uuid[])
        ORDER BY change_request_id, id
        """,
        WORKSPACE_ID,
        change_request_ids,
    )
    return [(str(row["bucket"]), str(row["object_key"])) for row in rows]


async def discover_e2e_change_request_ids(
    connection: asyncpg.Connection[Any], subject_ids: list[UUID]
) -> list[UUID]:
    if not subject_ids:
        return []
    rows = await connection.fetch(
        """
        SELECT id
        FROM governance.change_requests
        WHERE workspace_id = $1
          AND requester_id = ANY($2::uuid[])
          AND title LIKE 'CR E2E · %'
        ORDER BY created_at, id
        """,
        WORKSPACE_ID,
        subject_ids,
    )
    return [row["id"] for row in rows]


async def delete_e2e_objects(
    *,
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    object_locations: list[tuple[str, str]],
) -> int:
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    deleted = 0
    for bucket, object_key in object_locations:
        await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=object_key)
        try:
            await asyncio.to_thread(client.head_object, Bucket=bucket, Key=object_key)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status != 404:
                raise
        else:
            raise RuntimeError(f"E2E object still exists after DELETE: {bucket}/{object_key}")
        deleted += 1
    return deleted


async def teardown_database_fixture(
    connection: asyncpg.Connection[Any],
    *,
    state: E2EState,
) -> dict[str, int]:
    async with connection.transaction():
        change_request_ids = list(dict.fromkeys(state.change_request_ids))
        subject_ids = list(dict.fromkeys(state.subject_ids.values()))
        deleted_change_requests = 0
        if change_request_ids:
            await connection.execute(
                """
                DELETE FROM governance.registration_content_bindings
                WHERE workspace_id = $1 AND change_request_id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                change_request_ids,
            )
            await connection.execute(
                """
                DELETE FROM governance.change_test_runs
                WHERE workspace_id = $1 AND change_request_id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                change_request_ids,
            )
            await connection.execute(
                """
                DELETE FROM governance.approvals
                WHERE workspace_id = $1 AND change_request_id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                change_request_ids,
            )
            await connection.execute(
                """
                DELETE FROM governance.state_transitions
                WHERE workspace_id = $1 AND change_request_id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                change_request_ids,
            )
            await connection.execute(
                """
                DELETE FROM governance.change_request_attachments
                WHERE workspace_id = $1 AND change_request_id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                change_request_ids,
            )
            await connection.execute(
                """
                DELETE FROM integration.idempotency_keys
                WHERE workspace_id = $1
                  AND result ->> 'change_request_id' = ANY($2::text[])
                """,
                WORKSPACE_ID,
                [str(value) for value in change_request_ids],
            )
            await connection.execute(
                """
                DELETE FROM integration.outbox_events
                WHERE workspace_id = $1 AND aggregate_id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                change_request_ids,
            )
            result = await connection.execute(
                """
                DELETE FROM governance.change_requests
                WHERE workspace_id = $1 AND id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                change_request_ids,
            )
            deleted_change_requests = int(result.rsplit(" ", 1)[-1])

        deleted_subjects = 0
        if subject_ids:
            await connection.execute(
                """
                DELETE FROM platform.system_assignees
                WHERE workspace_id = $1 AND subject_id = ANY($2::uuid[])
                """,
                WORKSPACE_ID,
                subject_ids,
            )
            await connection.execute(
                """
                DELETE FROM iam.workspace_memberships
                WHERE workspace_id = $1 AND subject_id = ANY($2::uuid[])
                  AND attributes ->> 'e2e_fixture' = 'CR_WORKFLOW_V1'
                """,
                WORKSPACE_ID,
                subject_ids,
            )
            result = await connection.execute(
                """
                DELETE FROM iam.subjects
                WHERE id = ANY($1::uuid[])
                  AND email LIKE 'datariver-cr-e2e-%@localhost.invalid'
                """,
                subject_ids,
            )
            deleted_subjects = int(result.rsplit(" ", 1)[-1])

        if state.created_schema_scope_id is not None:
            await connection.execute(
                """
                DELETE FROM platform.system_schema_scopes
                WHERE id = $1 AND workspace_id = $2 AND system_id = $3
                """,
                state.created_schema_scope_id,
                WORKSPACE_ID,
                SYSTEM_ID,
            )
        if state.created_system_id is not None:
            await connection.execute(
                """
                DELETE FROM platform.data_systems
                WHERE id = $1 AND workspace_id = $2 AND code = 'SEMICON_E2E'
                  AND description =
                      'Ephemeral local CR E2E routing fixture; always torn down.'
                """,
                state.created_system_id,
                WORKSPACE_ID,
            )

        remaining_change_requests = (
            await connection.fetchval(
                """
            SELECT count(*)
            FROM governance.change_requests
            WHERE workspace_id = $1 AND id = ANY($2::uuid[])
            """,
                WORKSPACE_ID,
                change_request_ids,
            )
            if change_request_ids
            else 0
        )
        remaining_subjects = (
            await connection.fetchval(
                "SELECT count(*) FROM iam.subjects WHERE id = ANY($1::uuid[])",
                subject_ids,
            )
            if subject_ids
            else 0
        )
        if remaining_change_requests or remaining_subjects:
            raise RuntimeError(
                "Database E2E teardown was incomplete: "
                f"change_requests={remaining_change_requests}, subjects={remaining_subjects}"
            )
    return {
        "deleted_change_requests": deleted_change_requests,
        "deleted_subjects": deleted_subjects,
    }


def request_headers(
    token: str,
    *,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    version: int | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Workspace-Id": str(WORKSPACE_ID),
        "Accept": "application/json",
    }
    if request_id is not None:
        headers["X-Request-Id"] = request_id
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    if version is not None:
        headers["If-Match"] = f'"{version}"'
    return headers


async def api_json(
    client: httpx.AsyncClient,
    *,
    api_base_url: str,
    method: str,
    path: str,
    token: str,
    expected_status: int,
    body: dict[str, Any] | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    version: int | None = None,
) -> dict[str, Any]:
    response = await client.request(
        method,
        f"{api_base_url.rstrip('/')}{path}",
        headers=request_headers(
            token,
            request_id=request_id,
            idempotency_key=idempotency_key,
            version=version,
        ),
        json=body,
    )
    if response.status_code != expected_status:
        raise RuntimeError(
            f"DataRiver API returned HTTP {response.status_code}; expected {expected_status} "
            f"for {method} {path}."
        )
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"DataRiver API returned an invalid JSON document for {path}.")
    return value


def mutation_key(label: str) -> str:
    return f"cr-e2e-{label}-{uuid4()}"


def json_object(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} is not a JSON object.")
    return {str(key): item for key, item in value.items()}


def json_string_list(value: object, *, label: str) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"{label} is not a JSON string array.")
    return value


async def upload_knowledge_pdf(
    client: httpx.AsyncClient,
    *,
    api_base_url: str,
    token: str,
) -> dict[str, Any]:
    if not KNOWLEDGE_SOURCE_PATH.is_file():
        raise RuntimeError(f"The approved Knowledge PDF is missing: {KNOWLEDGE_SOURCE_PATH}")
    payload = KNOWLEDGE_SOURCE_PATH.read_bytes()
    if hashlib.sha256(payload).hexdigest() != KNOWLEDGE_SOURCE_SHA256:
        raise RuntimeError("The local Knowledge PDF does not match the approved SHA-256.")
    initiated = await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path="/uploads",
        token=token,
        expected_status=201,
        idempotency_key=mutation_key("knowledge-upload"),
        body={
            "display_name": KNOWLEDGE_SOURCE_PATH.name,
            "size_bytes": len(payload),
            "content_type": "application/pdf",
            "sha256": KNOWLEDGE_SOURCE_SHA256,
            "classification": "CONFIDENTIAL",
            "content_profile": "FORMAT_ONLY_V1",
        },
    )
    upload_id = str(initiated["id"])
    part_size = int(initiated["recommended_part_size_bytes"])
    completed: list[dict[str, Any]] = []
    for offset in range(0, len(payload), part_size):
        part_number = len(completed) + 1
        signed = await api_json(
            client,
            api_base_url=api_base_url,
            method="POST",
            path=f"/uploads/{upload_id}/parts",
            token=token,
            expected_status=200,
            body={"part_number": part_number},
        )
        response = await client.put(
            str(signed["url"]), content=payload[offset : offset + part_size]
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"The private object upload returned HTTP {response.status_code}.")
        etag = response.headers.get("etag", "").strip('"')
        if not etag:
            raise RuntimeError("The private object upload returned no ETag.")
        completed.append({"part_number": part_number, "etag": etag})
    queued = await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path=f"/uploads/{upload_id}/complete",
        token=token,
        expected_status=202,
        idempotency_key=mutation_key("knowledge-upload-complete"),
        version=int(initiated["version"]),
        body={"parts": completed},
    )
    for _ in range(120):
        current = await api_json(
            client,
            api_base_url=api_base_url,
            method="GET",
            path=f"/uploads/{upload_id}",
            token=token,
            expected_status=200,
        )
        if current.get("state") == "ACCEPTED":
            validation_summary = current.get("validation_summary")
            if (
                current.get("sha256") != KNOWLEDGE_SOURCE_SHA256
                or not isinstance(validation_summary, dict)
                or validation_summary.get("sha256") != KNOWLEDGE_SOURCE_SHA256
                or validation_summary.get("size_bytes") != len(payload)
            ):
                raise RuntimeError("The accepted Knowledge upload evidence is inconsistent.")
            return current
        if current.get("state") in {"REJECTED", "ABORTED", "EXPIRED"}:
            raise RuntimeError(f"The Knowledge PDF upload ended in {current.get('state')}.")
        await asyncio.sleep(1)
    raise RuntimeError(f"The Knowledge PDF upload did not finish after {queued.get('state')}.")


async def execute_knowledge_workflow(
    client: httpx.AsyncClient,
    connection: asyncpg.Connection[Any],
    *,
    api_base_url: str,
    tokens: dict[str, str],
) -> dict[str, Any]:
    requester_token = tokens["requester"]
    graphs_response = await client.get(
        f"{api_base_url.rstrip('/')}/knowledge/graphs",
        headers=request_headers(requester_token),
    )
    if graphs_response.status_code != 200 or not isinstance(graphs_response.json(), list):
        raise RuntimeError("The Knowledge graph list is unavailable for the E2E requester.")
    graph = next(
        (
            value
            for value in graphs_response.json()
            if isinstance(value, dict) and value.get("slug") == KNOWLEDGE_GRAPH_SLUG
        ),
        None,
    )
    if graph is None:
        graph = await api_json(
            client,
            api_base_url=api_base_url,
            method="POST",
            path="/knowledge/graphs",
            token=requester_token,
            expected_status=201,
            idempotency_key=mutation_key("knowledge-graph"),
            body={
                "slug": KNOWLEDGE_GRAPH_SLUG,
                "name": "Samil PwC Semiconductor Outlook 2026",
                "graph_type": "CURATED_KNOWLEDGE",
                "classification": "CONFIDENTIAL",
                "ontology": {
                    "entity_types": [
                        "SourceDocument",
                        "Section",
                        "Claim",
                        "Metric",
                        "EndMarket",
                        "ChipCategory",
                        "Technology",
                        "Material",
                        "ValueChainStage",
                        "Region",
                        "RiskOrDriver",
                    ],
                    "edge_types": [
                        "HAS_SECTION",
                        "ASSERTS",
                        "ABOUT",
                        "HAS_METRIC",
                        "DRIVES_DEMAND_FOR",
                        "USES_MATERIAL",
                        "PART_OF_VALUE_CHAIN",
                        "HAS_STRENGTH_IN",
                        "AFFECTED_BY",
                    ],
                },
            },
        )
    graph_id = str(graph["id"])
    upload = await upload_knowledge_pdf(
        client,
        api_base_url=api_base_url,
        token=requester_token,
    )
    analyze_response = await client.post(
        f"{api_base_url.rstrip('/')}/knowledge/graphs/{graph_id}/sources/{upload['id']}/analyze",
        headers=request_headers(
            requester_token,
            idempotency_key=mutation_key("knowledge-source-analysis"),
        ),
        json={"title": "PwC 반도체 전망 2026 PDF 추출 제안"},
    )
    if analyze_response.status_code != 202:
        raise RuntimeError(
            f"Knowledge PDF analysis enqueue returned HTTP {analyze_response.status_code}."
        )
    job = analyze_response.json()
    if not isinstance(job, dict) or not isinstance(job.get("id"), str):
        raise RuntimeError("Knowledge PDF analysis enqueue returned no durable job.")
    job_id = str(job["id"])
    for _ in range(900):
        current_job = await api_json(
            client,
            api_base_url=api_base_url,
            method="GET",
            path=f"/knowledge/graphs/{graph_id}/source-analysis-jobs/{job_id}",
            token=requester_token,
            expected_status=200,
        )
        state = current_job.get("state")
        if state == "SUCCEEDED":
            job = current_job
            break
        if state in {"FAILED", "STALE", "CANCELLED"}:
            raise RuntimeError(
                f"Knowledge PDF analysis ended in {state}: {current_job.get('last_failure_code')}."
            )
        await asyncio.sleep(1)
    else:
        raise RuntimeError("Knowledge PDF analysis durable job did not finish in 900 seconds.")
    raw_result = job.get("result")
    if not isinstance(raw_result, dict):
        raise RuntimeError("Knowledge PDF analysis completed without a typed result.")
    analysis = dict(raw_result)
    analysis["source_snapshot_id"] = job.get("source_snapshot_id")
    if (
        int(analysis.get("page_count", 0)) < 1
        or int(analysis.get("proposed_node_count", 0)) < 1
        or not isinstance(analysis.get("source_snapshot_id"), str)
    ):
        raise RuntimeError("Knowledge PDF analysis returned no grounded proposal.")
    changeset_id = str(analysis["changeset_id"])
    submitted = await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path=f"/knowledge/graphs/{graph_id}/changesets/{changeset_id}/submit",
        token=requester_token,
        expected_status=200,
        version=1,
    )
    reviewed = await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path=f"/knowledge/graphs/{graph_id}/changesets/{changeset_id}/reviews",
        token=tokens["steward"],
        expected_status=200,
        version=int(submitted["version"]),
        body={
            "decision": "APPROVED",
            "reason": "PDF page excerpt/hash와 ontology validation evidence를 독립 검토했습니다.",
        },
    )
    publish_request_id = f"knowledge-e2e-publish-{uuid4()}"
    publish = await client.post(
        f"{api_base_url.rstrip('/')}/knowledge/graphs/{graph_id}/changesets/{changeset_id}/publish",
        headers=request_headers(
            tokens["admin"],
            request_id=publish_request_id,
            idempotency_key=mutation_key("knowledge-publish"),
        ),
    )
    if (
        publish.status_code != 403
        or publish.json().get("remediation", {}).get("kind") != "FIDO2_REQUIRED"
    ):
        raise RuntimeError("LoA1 Knowledge publish did not fail closed at the WebAuthn boundary.")
    source_row = await connection.fetchrow(
        """
        SELECT id, state, content_sha256, byte_size
        FROM knowledge.source_snapshots
        WHERE workspace_id = $1 AND id = $2
        """,
        WORKSPACE_ID,
        UUID(str(analysis["source_snapshot_id"])),
    )
    page_count = await connection.fetchval(
        """
        SELECT count(*) FROM knowledge.source_pages
        WHERE workspace_id = $1 AND source_snapshot_id = $2
        """,
        WORKSPACE_ID,
        UUID(str(analysis["source_snapshot_id"])),
    )
    embedding = await connection.fetchrow(
        """
        SELECT provider, model_identity, dimension, count(*) AS rows
        FROM knowledge.source_page_embeddings
        WHERE workspace_id = $1 AND source_snapshot_id = $2
        GROUP BY provider, model_identity, dimension
        """,
        WORKSPACE_ID,
        UUID(str(analysis["source_snapshot_id"])),
    )
    extraction = await connection.fetchrow(
        """
        SELECT state, input_hash, output_hash, embedding_binding, extraction_binding
        FROM knowledge.extraction_runs
        WHERE workspace_id = $1 AND source_snapshot_id = $2
        """,
        WORKSPACE_ID,
        UUID(str(analysis["source_snapshot_id"])),
    )
    decision = await connection.fetchrow(
        """
        SELECT id, effect, reason_codes
        FROM authz.policy_decisions
        WHERE workspace_id = $1 AND request_id = $2
        ORDER BY decided_at DESC LIMIT 1
        """,
        WORKSPACE_ID,
        publish_request_id,
    )
    if (
        source_row is None
        or source_row["state"] != "ANALYZED"
        or page_count != int(analysis["page_count"])
        or embedding is None
        or int(embedding["rows"]) != page_count
        or extraction is None
        or extraction["state"] != "SUCCEEDED"
        or decision is None
        or "PHISHING_RESISTANT_AUTH_REQUIRED" not in decision["reason_codes"]
    ):
        raise RuntimeError(
            "Knowledge canonical analysis or WebAuthn denial evidence is incomplete."
        )
    return {
        "status": "PASS_UNTIL_WEBAUTHN_GATE",
        "graph_id": graph_id,
        "upload_id": upload["id"],
        "source_snapshot_id": analysis["source_snapshot_id"],
        "changeset_id": changeset_id,
        "changeset_state": reviewed["state"],
        "page_count": page_count,
        "proposed_node_count": analysis["proposed_node_count"],
        "proposed_edge_count": analysis["proposed_edge_count"],
        "evidence_hash": analysis["evidence_hash"],
        "embedding": dict(embedding),
        "extraction": dict(extraction),
        "publish_denial": {
            "http_status": publish.status_code,
            "remediation": "FIDO2_REQUIRED",
            "policy_decision_id": decision["id"],
            "reason_codes": decision["reason_codes"],
        },
    }


async def transition(
    client: httpx.AsyncClient,
    *,
    api_base_url: str,
    token: str,
    change_request_id: str,
    version: int,
    target: str,
    reason: str,
) -> dict[str, Any]:
    return await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path=f"/change-requests/{change_request_id}/transitions",
        token=token,
        expected_status=200,
        body={"target_state": target, "reason": reason},
        idempotency_key=mutation_key(f"transition-{target.lower()}"),
        version=version,
    )


async def approval(
    client: httpx.AsyncClient,
    *,
    api_base_url: str,
    token: str,
    change_request_id: str,
    version: int,
    stage: str,
    reason: str,
) -> dict[str, Any]:
    return await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path=f"/change-requests/{change_request_id}/approvals",
        token=token,
        expected_status=200,
        body={"stage": stage, "decision": "APPROVED", "reason": reason},
        idempotency_key=mutation_key(f"approval-{stage.lower()}"),
        version=version,
    )


async def execute_workflow(
    client: httpx.AsyncClient,
    connection: asyncpg.Connection[Any],
    *,
    api_base_url: str,
    tokens: dict[str, str],
    service_account_token: str,
    asset_projection: dict[str, Any],
    state: E2EState,
) -> dict[str, Any]:
    requester_token = tokens["requester"]
    developer_token = tokens["developer"]
    asset = await api_json(
        client,
        api_base_url=api_base_url,
        method="GET",
        path=f"/catalog/assets/{ASSET_ID}",
        token=requester_token,
        expected_status=200,
    )
    fields = asset.get("schema_fields")
    if not isinstance(fields, list):
        raise RuntimeError("The real DataHub asset detail contains no schema field list.")
    field = next(
        (
            value
            for value in fields
            if isinstance(value, dict)
            and isinstance(value.get("fieldPath"), str)
            and value["fieldPath"].strip()
        ),
        None,
    )
    if field is None:
        raise RuntimeError("The real DataHub asset has no selectable schema field.")

    systems = await api_json(
        client,
        api_base_url=api_base_url,
        method="GET",
        path="/change-requests/systems",
        token=requester_token,
        expected_status=200,
    )
    items = systems.get("items")
    if not isinstance(items, list) or str(SYSTEM_ID) not in {
        str(value.get("id")) for value in items if isinstance(value, dict)
    }:
        raise RuntimeError("The E2E System is not visible through the CR System API.")

    field_path = str(field["fieldPath"])
    native_type = str(field.get("nativeDataType") or field.get("type") or "")
    source_description = str(field.get("description") or "")
    intake = await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path="/change-requests/intake",
        token=requester_token,
        expected_status=201,
        idempotency_key=mutation_key("intake"),
        body={
            "title": f"CR E2E · {asset_projection['name']} · {datetime.now(UTC).isoformat()}",
            "system_id": str(SYSTEM_ID),
            "request_date": date.today().isoformat(),
            "request_department": "Local E2E QA",
            "request_reason": "실제 DataHub 자산의 변경관리 권한·상태·증거 경계를 검증합니다.",
            "request_content": "Provider mutation 없이 typed CHANGE_INTAKE만 검증합니다.",
            "requested_due_date": None,
            "priority": "NORMAL",
            "urgency": "NORMAL",
            "security_level": "CONFIDENTIAL",
            "targets": [
                {
                    "kind": "EXISTING",
                    "asset_id": str(ASSET_ID),
                    "description": str(asset.get("description") or ""),
                    "requested_change": (
                        "E2E 검증용 설명 변경 제안이며 DataHub에는 적용하지 않습니다."
                    ),
                    "tags": [],
                    "terms": [],
                    "columns": [
                        {
                            "field_path": field_path,
                            "data_type": native_type,
                            "description": source_description,
                            "requested_change": "E2E 컬럼 검토 증거를 기록합니다.",
                            "tags": [],
                            "terms": [],
                        }
                    ],
                }
            ],
        },
    )
    change_request_id = str(intake["id"])
    state.change_request_ids.append(UUID(change_request_id))
    if intake.get("state") != "REGISTERED" or intake.get("version") != 1:
        raise RuntimeError("CR intake did not create the expected REGISTERED version 1 aggregate.")

    current = await transition(
        client,
        api_base_url=api_base_url,
        token=developer_token,
        change_request_id=change_request_id,
        version=1,
        target="IN_REVIEW",
        reason="E2E Developer가 검토를 시작합니다.",
    )
    if current.get("version") != 2:
        raise RuntimeError("IN_REVIEW did not produce aggregate version 2.")

    stale_response = await client.post(
        f"{api_base_url.rstrip('/')}/change-requests/{change_request_id}/approvals",
        headers=request_headers(
            developer_token,
            idempotency_key=mutation_key("stale-review"),
            version=1,
        ),
        json={
            "stage": "REVIEW",
            "decision": "APPROVED",
            "reason": "의도적으로 오래된 aggregate version을 사용합니다.",
        },
    )
    if stale_response.status_code != 409:
        raise RuntimeError(
            f"The stale If-Match negative check returned HTTP {stale_response.status_code}."
        )
    unchanged = await api_json(
        client,
        api_base_url=api_base_url,
        method="GET",
        path=f"/change-requests/{change_request_id}",
        token=developer_token,
        expected_status=200,
    )
    if unchanged.get("version") != 2 or unchanged.get("approvals"):
        raise RuntimeError("The stale version request changed the CR aggregate.")

    current = await approval(
        client,
        api_base_url=api_base_url,
        token=developer_token,
        change_request_id=change_request_id,
        version=2,
        stage="REVIEW",
        reason="실제 target System Developer 검토를 승인합니다.",
    )
    current = await transition(
        client,
        api_base_url=api_base_url,
        token=developer_token,
        change_request_id=change_request_id,
        version=int(current["version"]),
        target="TESTING",
        reason="Developer 검토 증거 완료 후 TESTING으로 이동합니다.",
    )
    if current.get("version") != 4 or current.get("state") != "TESTING":
        raise RuntimeError("The CR did not reach TESTING version 4.")

    test_document = {
        "contract": "CR_E2E_TEST_RESULT_V1",
        "asset_id": str(ASSET_ID),
        "system_id": str(SYSTEM_ID),
        "field_path": field_path,
        "result": "PASSED",
        "checks": ["target binding", "Developer authority", "attachment SHA-256 binding"],
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    test_bytes = json.dumps(
        test_document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    upload = await client.post(
        f"{api_base_url.rstrip('/')}/change-requests/{change_request_id}/attachments",
        headers=request_headers(developer_token),
        data={"kind": "TEST"},
        files={"file": ("cr-e2e-test-result.json", test_bytes, "application/json")},
    )
    if upload.status_code != 200:
        raise RuntimeError(f"The TEST attachment upload returned HTTP {upload.status_code}.")
    attachment = upload.json()
    expected_sha = hashlib.sha256(test_bytes).hexdigest()
    if attachment.get("content_sha256") != expected_sha:
        raise RuntimeError("The TEST attachment receipt SHA-256 does not match the uploaded bytes.")
    attachment_id = str(attachment["id"])

    current = await api_json(
        client,
        api_base_url=api_base_url,
        method="POST",
        path=f"/change-requests/{change_request_id}/test-runs",
        token=developer_token,
        expected_status=200,
        version=4,
        idempotency_key=mutation_key("test-run"),
        body={
            "system_id": str(SYSTEM_ID),
            "attachment_id": attachment_id,
            "state": "PASSED",
            "bounded_summary": {
                "summary": "실제 TEST 첨부파일을 현재 회차와 System에 결합했습니다."
            },
        },
    )
    test_runs = current.get("test_runs")
    if (
        current.get("version") != 5
        or not isinstance(test_runs, list)
        or not test_runs
        or test_runs[-1].get("result_hash") != expected_sha
    ):
        raise RuntimeError("The typed TEST run did not bind the attachment SHA-256.")

    current = await approval(
        client,
        api_base_url=api_base_url,
        token=developer_token,
        change_request_id=change_request_id,
        version=5,
        stage="TEST",
        reason="실제 TEST 첨부 해시와 PASSED 결과를 검토했습니다.",
    )
    current = await transition(
        client,
        api_base_url=api_base_url,
        token=developer_token,
        change_request_id=change_request_id,
        version=int(current["version"]),
        target="FINAL_REVIEW",
        reason="모든 System의 Developer TEST 승인과 PASSED 증거가 완료되었습니다.",
    )
    if current.get("version") != 7 or current.get("state") != "FINAL_REVIEW":
        raise RuntimeError("The CR did not reach FINAL_REVIEW version 7.")

    invalid_final_transition = await client.post(
        f"{api_base_url.rstrip('/')}/change-requests/{change_request_id}/transitions",
        headers=request_headers(
            developer_token,
            idempotency_key=mutation_key("invalid-final-reject"),
            version=7,
        ),
        json={
            "target_state": "REJECTED",
            "reason": "FINAL 일반 transition 거부 경계를 검증합니다.",
        },
    )
    if invalid_final_transition.status_code != 422:
        raise RuntimeError(
            "The ordinary FINAL_REVIEW to REJECTED transition was not rejected with HTTP 422."
        )

    denied_final: list[dict[str, Any]] = []
    for role in ("developer", "steward", "admin"):
        request_id = f"cr-e2e-final-{role}-{uuid4()}"
        response = await client.post(
            f"{api_base_url.rstrip('/')}/change-requests/{change_request_id}/approvals",
            headers=request_headers(
                tokens[role],
                request_id=request_id,
                idempotency_key=mutation_key(f"final-{role}"),
                version=7,
            ),
            json={
                "stage": "FINAL",
                "decision": "APPROVED",
                "reason": f"{role} LoA1 FINAL 승인 거부 경계를 검증합니다.",
            },
        )
        if response.status_code != 403:
            raise RuntimeError(
                f"LoA1 FINAL approval for {role} returned HTTP {response.status_code}."
            )
        problem = response.json()
        if problem.get("remediation", {}).get("kind") != "FIDO2_REQUIRED":
            raise RuntimeError(f"LoA1 FINAL approval for {role} did not require FIDO2 remediation.")
        policy = await connection.fetchrow(
            """
            SELECT id, action, effect, reason_codes, evaluation_context
            FROM authz.policy_decisions
            WHERE workspace_id = $1 AND request_id = $2
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            WORKSPACE_ID,
            request_id,
        )
        reason_codes = json_string_list(
            policy["reason_codes"] if policy is not None else None,
            label=f"{role} FINAL denial reason_codes",
        )
        evaluation_context = json_object(
            policy["evaluation_context"] if policy is not None else None,
            label=f"{role} FINAL denial evaluation_context",
        )
        if (
            policy is None
            or policy["action"] != "change.approve"
            or policy["effect"] != "DENY"
            or "PHISHING_RESISTANT_AUTH_REQUIRED" not in reason_codes
        ):
            raise RuntimeError(f"The persisted FINAL denial evidence is incomplete for {role}.")
        denied_final.append(
            {
                "role": role,
                "http_status": response.status_code,
                "remediation": "FIDO2_REQUIRED",
                "policy_decision_id": policy["id"],
                "reason_codes": reason_codes,
                "authentication_assurance": evaluation_context.get("authentication_assurance"),
            }
        )

    service_request_id = f"cr-e2e-final-service-{uuid4()}"
    service_response = await client.post(
        f"{api_base_url.rstrip('/')}/change-requests/{change_request_id}/approvals",
        headers=request_headers(
            service_account_token,
            request_id=service_request_id,
            idempotency_key=mutation_key("final-airflow-service"),
            version=7,
        ),
        json={
            "stage": "FINAL",
            "decision": "APPROVED",
            "reason": "Service Token으로 FINAL 승인을 시도하는 음성 보안 검증입니다.",
        },
    )
    if service_response.status_code not in {401, 403}:
        raise RuntimeError(
            "The service-token FINAL approval was not rejected with HTTP 401/403; "
            f"received HTTP {service_response.status_code}."
        )
    service_problem = service_response.json()
    service_policy = await connection.fetchrow(
        """
        SELECT id, action, effect, reason_codes, evaluation_context
        FROM authz.policy_decisions
        WHERE workspace_id = $1 AND request_id = $2
        ORDER BY decided_at DESC
        LIMIT 1
        """,
        WORKSPACE_ID,
        service_request_id,
    )
    if (
        service_policy is None
        or service_policy["action"] != "change.approve"
        or service_policy["effect"] != "DENY"
    ):
        raise RuntimeError("The service-token FINAL denial audit evidence is incomplete.")
    service_reason_codes = json_string_list(
        service_policy["reason_codes"], label="service FINAL denial reason_codes"
    )
    service_evaluation_context = json_object(
        service_policy["evaluation_context"],
        label="service FINAL denial evaluation_context",
    )
    service_denial = {
        "principal": "datariver-airflow service account",
        "http_status": service_response.status_code,
        "problem_type": service_problem.get("type"),
        "remediation": service_problem.get("remediation", {}).get("kind"),
        "policy_decision_id": service_policy["id"],
        "reason_codes": service_reason_codes,
        "authentication_assurance": service_evaluation_context.get("authentication_assurance"),
    }

    final_detail = await api_json(
        client,
        api_base_url=api_base_url,
        method="GET",
        path=f"/change-requests/{change_request_id}",
        token=developer_token,
        expected_status=200,
    )
    if final_detail.get("state") != "FINAL_REVIEW" or final_detail.get("version") != 7:
        raise RuntimeError("A denied FINAL operation changed the CR aggregate.")
    if any(item.get("stage") == "FINAL" for item in final_detail.get("approvals", [])):
        raise RuntimeError("A denied LoA1 request persisted a FINAL approval.")

    return await collect_evidence(
        connection,
        change_request_id=UUID(change_request_id),
        attachment_id=UUID(attachment_id),
        expected_sha=expected_sha,
        stale_status=stale_response.status_code,
        invalid_transition_status=invalid_final_transition.status_code,
        denied_final=denied_final,
        service_denial=service_denial,
    )


async def collect_evidence(
    connection: asyncpg.Connection[Any],
    *,
    change_request_id: UUID,
    attachment_id: UUID,
    expected_sha: str,
    stale_status: int,
    invalid_transition_status: int,
    denied_final: list[dict[str, Any]],
    service_denial: dict[str, Any],
) -> dict[str, Any]:
    aggregate = await connection.fetchrow(
        """
        SELECT id, number, request_type, state, version, requester_id,
               current_round_id, current_round_number, created_at
        FROM governance.change_requests
        WHERE workspace_id = $1 AND id = $2
        """,
        WORKSPACE_ID,
        change_request_id,
    )
    items = await connection.fetch(
        """
        SELECT ordinal, target_type, target_ref, routing_system_id,
               target_asset_id, target_binding_hash
        FROM governance.change_request_items
        WHERE workspace_id = $1 AND change_request_id = $2
        ORDER BY ordinal
        """,
        WORKSPACE_ID,
        change_request_id,
    )
    transitions = await connection.fetch(
        """
        SELECT from_state, to_state, actor_id, round_id, occurred_at
        FROM governance.state_transitions
        WHERE workspace_id = $1 AND change_request_id = $2
        ORDER BY occurred_at, id
        """,
        WORKSPACE_ID,
        change_request_id,
    )
    approvals = await connection.fetch(
        """
        SELECT stage, decision, actor_id, round_id, authority_snapshot, occurred_at
        FROM governance.approvals
        WHERE workspace_id = $1 AND change_request_id = $2
        ORDER BY occurred_at, id
        """,
        WORKSPACE_ID,
        change_request_id,
    )
    test_run = await connection.fetchrow(
        """
        SELECT run.id, run.system_id, run.state, run.round_id, run.recorded_by,
               run.plan_hash, run.result_hash, attachment.id AS attachment_id,
               attachment.kind, attachment.content_sha256,
               (run.result_hash = attachment.content_sha256) AS result_bound
        FROM governance.change_test_runs AS run
        JOIN governance.change_request_attachments AS attachment
          ON attachment.workspace_id = run.workspace_id
         AND attachment.change_request_id = run.change_request_id
         AND attachment.round_id = run.round_id
         AND attachment.id = run.attachment_id
        WHERE run.workspace_id = $1
          AND run.change_request_id = $2
          AND attachment.id = $3
        """,
        WORKSPACE_ID,
        change_request_id,
        attachment_id,
    )
    assignees = await connection.fetch(
        """
        SELECT system_id, subject_id, responsibility, priority, active
        FROM platform.system_assignees
        WHERE workspace_id = $1 AND system_id = $2 AND active IS TRUE
        ORDER BY responsibility, priority, subject_id
        """,
        WORKSPACE_ID,
        SYSTEM_ID,
    )
    events = await connection.fetch(
        """
        SELECT event_type, created_at, published_at, dead_lettered_at, attempts, last_error_code
        FROM integration.outbox_events
        WHERE workspace_id = $1 AND aggregate_id = $2
        ORDER BY created_at, id
        """,
        WORKSPACE_ID,
        change_request_id,
    )
    if aggregate is None or aggregate["state"] != "FINAL_REVIEW" or aggregate["version"] != 7:
        raise RuntimeError("The persisted CR aggregate evidence is incomplete.")
    if test_run is None or not test_run["result_bound"] or test_run["result_hash"] != expected_sha:
        raise RuntimeError("The persisted TEST SHA-256 binding evidence is incomplete.")
    if [row["stage"] for row in approvals] != ["REVIEW", "TEST"]:
        raise RuntimeError("Unexpected approval evidence was persisted before WebAuthn FINAL.")
    return {
        "status": "PASS_UNTIL_WEBAUTHN_GATE",
        "workspace_id": WORKSPACE_ID,
        "asset_id": ASSET_ID,
        "system_id": SYSTEM_ID,
        "change_request": dict(aggregate),
        "items": [dict(row) for row in items],
        "transitions": [dict(row) for row in transitions],
        "approvals": [dict(row) for row in approvals],
        "test_evidence": dict(test_run),
        "system_assignees": [dict(row) for row in assignees],
        "negative_checks": {
            "stale_if_match_http_status": stale_status,
            "ordinary_final_rejection_transition_http_status": invalid_transition_status,
            "loa1_final_approvals": denied_final,
            "service_token_final_approval": service_denial,
        },
        "outbox": [dict(row) for row in events],
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (UUID, datetime, date)):
        return value.isoformat() if isinstance(value, (datetime, date)) else str(value)
    return value


async def main() -> None:
    args = parse_args()
    assert_development_environment()
    database_password = read_secret(ROOT / "secrets" / "postgres_password")
    keycloak_password = read_secret(ROOT / "secrets" / "keycloak_admin_password")
    airflow_client_secret = read_secret(ROOT / "secrets" / "airflow_client_secret")
    s3_access_key = read_secret(ROOT / "secrets" / "s3_access_key")
    s3_secret_key = read_secret(ROOT / "secrets" / "s3_secret_key")
    E2E_CLIENT_SECRET_PATH.unlink(missing_ok=True)
    connection = await asyncpg.connect(
        host=args.database_host,
        port=args.database_port,
        user=args.database_user,
        password=database_password,
        database=args.database_name,
        command_timeout=20,
    )
    evidence: dict[str, Any] | None = None
    failure: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    state = E2EState(
        subject_ids={
            persona.key: uuid5(E2E_NAMESPACE, f"subject:{persona.key}") for persona in PERSONAS
        },
        change_request_ids=[],
        object_locations=[],
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        keycloak: KeycloakAdmin | None = None
        passwords = {persona.key: secrets.token_urlsafe(32) for persona in PERSONAS}
        keycloak_user_ids: dict[str, str] = {}
        try:
            admin_token = await keycloak_admin_token(
                client,
                base_url=args.keycloak_base_url,
                username=args.keycloak_admin_username,
                password=keycloak_password,
            )
            keycloak = KeycloakAdmin(client, args.keycloak_base_url, admin_token)
            for persona in PERSONAS:
                keycloak_user_ids[persona.key] = await keycloak.create_user(
                    persona, passwords[persona.key]
                )
            issuer = f"{args.keycloak_base_url.rstrip('/')}/realms/datariver"
            subject_ids, asset_projection = await configure_database_fixture(
                connection,
                issuer=issuer,
                keycloak_user_ids=keycloak_user_ids,
                state=state,
            )
            if subject_ids != state.subject_ids:
                raise RuntimeError("The E2E database subject identities are not deterministic.")
            _, e2e_client_secret = await keycloak.create_direct_grant_client()
            tokens = {
                persona.key: await persona_token(
                    client,
                    base_url=args.keycloak_base_url,
                    client_id=E2E_CLIENT_ID,
                    client_secret=e2e_client_secret,
                    username=persona.username,
                    password=passwords[persona.key],
                )
                for persona in PERSONAS
            }
            airflow_token = await service_token(
                client,
                base_url=args.keycloak_base_url,
                client_secret=airflow_client_secret,
            )
            evidence = await execute_workflow(
                client,
                connection,
                api_base_url=args.api_base_url,
                tokens=tokens,
                service_account_token=airflow_token,
                asset_projection=asset_projection,
                state=state,
            )
            evidence["personas"] = {
                persona.key: {
                    "subject_id": subject_ids[persona.key],
                    "keycloak_user_id": keycloak_user_ids[persona.key],
                    "responsibility": persona.responsibility,
                }
                for persona in PERSONAS
            }
        except BaseException as error:
            failure = error
        finally:
            try:
                discovered = await discover_e2e_change_request_ids(
                    connection, list(state.subject_ids.values())
                )
                state.change_request_ids = list(
                    dict.fromkeys([*state.change_request_ids, *discovered])
                )
                state.object_locations = await collect_e2e_object_locations(
                    connection, state.change_request_ids
                )
                deleted_objects = await delete_e2e_objects(
                    endpoint_url=args.s3_endpoint_url,
                    access_key=s3_access_key,
                    secret_key=s3_secret_key,
                    object_locations=state.object_locations,
                )
            except BaseException as error:
                cleanup_errors.append(error)
                deleted_objects = 0
            try:
                database_cleanup = await teardown_database_fixture(connection, state=state)
            except BaseException as error:
                cleanup_errors.append(error)
                database_cleanup = {}
            if keycloak is not None:
                try:
                    keycloak_cleanup = await keycloak.delete_reserved_fixtures()
                except BaseException as error:
                    cleanup_errors.append(error)
                    keycloak_cleanup = {}
            else:
                keycloak_cleanup = {}
            try:
                E2E_CLIENT_SECRET_PATH.unlink(missing_ok=True)
                if E2E_CLIENT_SECRET_PATH.exists():
                    raise RuntimeError("The temporary E2E client-secret file still exists.")
            except BaseException as error:
                cleanup_errors.append(error)
            try:
                await connection.close()
            except BaseException as error:
                cleanup_errors.append(error)
    if failure is not None or cleanup_errors:
        errors = ([failure] if failure is not None else []) + cleanup_errors
        raise BaseExceptionGroup("CR E2E workflow or teardown failed", errors)
    if evidence is None:
        raise RuntimeError("The CR E2E workflow did not produce evidence.")
    evidence["local_e2e_client"] = {
        "client_id": E2E_CLIENT_ID,
        "credential_method": "ephemeral Keycloak Admin API client-secret (0600)",
        "persistent_for_local_e2e": False,
    }
    evidence["teardown"] = {
        "status": "PASS",
        "database": database_cleanup,
        "keycloak": keycloak_cleanup,
        "deleted_objects": deleted_objects,
        "temporary_secret_removed": True,
        "immutable_policy_decisions_preserved": True,
    }
    print(json.dumps(json_safe(evidence), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
