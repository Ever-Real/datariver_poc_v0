from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_ID = UUID("383e748a-a1fc-579a-a147-295a7de6ad25")
AIRFLOW_EXTERNAL_SUBJECT = "00000000-0000-4000-8000-000000000002"
SEARCH_ACTION = "catalog.search"


@dataclass(frozen=True, slots=True)
class MembershipSnapshot:
    workspace_id: UUID
    subject_id: UUID
    active: bool
    attributes: dict[str, Any]

    def as_document(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "subject_id": str(self.subject_id),
            "active": self.active,
            "attributes": self.attributes,
        }

    @classmethod
    def from_document(cls, value: dict[str, Any]) -> MembershipSnapshot:
        attributes = value.get("attributes")
        if not isinstance(attributes, dict):
            raise ValueError("Recovery snapshot attributes are invalid.")
        return cls(
            workspace_id=UUID(str(value["workspace_id"])),
            subject_id=UUID(str(value["subject_id"])),
            active=bool(value["active"]),
            attributes=attributes,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure local ABAC revocation reflection with one unchanged OIDC token."
    )
    parser.add_argument("--api-base-url", default="http://127.0.0.1:38101/api/v1")
    parser.add_argument(
        "--token-url",
        default="http://127.0.0.1:18081/realms/datariver/protocol/openid-connect/token",
    )
    parser.add_argument("--database-host", default="127.0.0.1")
    parser.add_argument("--database-port", type=int, default=5432)
    parser.add_argument("--database-name", default="datariver")
    parser.add_argument("--workspace-id", type=UUID, default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--sla-seconds", type=float, default=60.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.05)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.iterations <= 1_000:
        parser.error("--iterations must be between 1 and 1000")
    if not 0 < args.sla_seconds <= 300:
        parser.error("--sla-seconds must be between 0 and 300")
    if not 0.01 <= args.poll_interval_seconds <= 5:
        parser.error("--poll-interval-seconds must be between 0.01 and 5")
    return args


async def main() -> None:
    args = parse_args()
    runtime_directory = ROOT / "runtime" / "policy-probe"
    snapshot_path = runtime_directory / "membership-recovery.json"
    evidence_path = runtime_directory / "last-result.json"
    database_password = _read_secret(ROOT / "secrets" / "postgres_bootstrap_password")
    client_secret = _read_secret(ROOT / "secrets" / "airflow_client_secret")
    connection = await asyncpg.connect(
        host=args.database_host,
        port=args.database_port,
        user="datariver_bootstrap",
        password=database_password,
        database=args.database_name,
        command_timeout=10,
    )
    try:
        if args.recover:
            snapshot = _read_snapshot(snapshot_path)
            await _restore_and_verify(connection, snapshot)
            snapshot_path.unlink()
            print(json.dumps({"status": "RECOVERED"}, sort_keys=True))
            return
        if snapshot_path.exists():
            raise RuntimeError(
                "A recovery snapshot already exists. Run this command with --recover first."
            )
        snapshot = await _load_membership(
            connection,
            workspace_id=args.workspace_id,
            external_subject=AIRFLOW_EXTERNAL_SUBJECT,
        )
        runtime_directory.mkdir(parents=True, exist_ok=True)
        _write_private_json(snapshot_path, snapshot.as_document())
        restored = False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                token = await _service_token(
                    client,
                    token_url=args.token_url,
                    client_secret=client_secret,
                )
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-Workspace-Id": str(args.workspace_id),
                }
                await _assert_search_baseline(client, args.api_base_url, headers)
                measurements: dict[str, list[float]] = {
                    "membership_inactive": [],
                    "explicit_action_deny": [],
                    "scope_shrink": [],
                }
                for iteration in range(args.iterations):
                    for scenario in measurements:
                        await _restore_and_verify(connection, snapshot)
                        await _assert_search_baseline(client, args.api_base_url, headers)
                        request_id = f"policy-probe-{scenario}-{iteration}-{uuid4()}"
                        changed = _scenario_snapshot(snapshot, scenario)
                        started_at = time.perf_counter()
                        await _apply_membership(connection, changed)
                        elapsed_ms = await _wait_for_revocation(
                            client,
                            api_base_url=args.api_base_url,
                            headers={**headers, "X-Request-Id": request_id},
                            scenario=scenario,
                            started_at=started_at,
                            sla_seconds=args.sla_seconds,
                            poll_interval_seconds=args.poll_interval_seconds,
                        )
                        measurements[scenario].append(elapsed_ms)
                await _restore_and_verify(connection, snapshot)
                restored = True
                await _assert_search_baseline(client, args.api_base_url, headers)
            result = {
                "status": "PASS",
                "iterations_per_scenario": args.iterations,
                "sla_ms": round(args.sla_seconds * 1000, 3),
                "same_token": True,
                "scenarios": {
                    scenario: _summary(values) for scenario, values in measurements.items()
                },
            }
            _write_private_json(evidence_path, result)
            snapshot_path.unlink()
            print(json.dumps(result, sort_keys=True))
        finally:
            if not restored:
                try:
                    await _restore_and_verify(connection, snapshot)
                except Exception:
                    # Keep the private recovery snapshot for an explicit --recover run.
                    raise
                else:
                    snapshot_path.unlink(missing_ok=True)
    finally:
        await connection.close()


async def _load_membership(
    connection: asyncpg.Connection,
    *,
    workspace_id: UUID,
    external_subject: str,
) -> MembershipSnapshot:
    row = await connection.fetchrow(
        """
        SELECT membership.subject_id, membership.active, membership.attributes
        FROM iam.workspace_memberships AS membership
        JOIN iam.subjects AS subject ON subject.id = membership.subject_id
        WHERE membership.workspace_id = $1
          AND subject.external_subject = $2
        """,
        workspace_id,
        external_subject,
    )
    if row is None:
        raise RuntimeError("The local Airflow service membership is not initialized.")
    return MembershipSnapshot(
        workspace_id=workspace_id,
        subject_id=row["subject_id"],
        active=row["active"],
        attributes=_attributes_document(row["attributes"]),
    )


async def _apply_membership(
    connection: asyncpg.Connection,
    snapshot: MembershipSnapshot,
) -> None:
    result = await connection.execute(
        """
        UPDATE iam.workspace_memberships
        SET active = $3, attributes = $4::jsonb
        WHERE workspace_id = $1 AND subject_id = $2
        """,
        snapshot.workspace_id,
        snapshot.subject_id,
        snapshot.active,
        json.dumps(snapshot.attributes, separators=(",", ":"), sort_keys=True),
    )
    if result != "UPDATE 1":
        raise RuntimeError("The policy probe membership update did not affect exactly one row.")


async def _restore_and_verify(
    connection: asyncpg.Connection,
    snapshot: MembershipSnapshot,
) -> None:
    await _apply_membership(connection, snapshot)
    row = await connection.fetchrow(
        """
        SELECT active, attributes
        FROM iam.workspace_memberships
        WHERE workspace_id = $1 AND subject_id = $2
        """,
        snapshot.workspace_id,
        snapshot.subject_id,
    )
    if (
        row is None
        or row["active"] != snapshot.active
        or _attributes_document(row["attributes"]) != snapshot.attributes
    ):
        raise RuntimeError("The policy probe could not verify membership restoration.")


def _scenario_snapshot(
    original: MembershipSnapshot,
    scenario: str,
) -> MembershipSnapshot:
    attributes = json.loads(json.dumps(original.attributes))
    active = original.active
    if scenario == "membership_inactive":
        active = False
    elif scenario == "explicit_action_deny":
        denied = set(str(value) for value in attributes.get("denied_actions", []))
        denied.add(SEARCH_ACTION)
        attributes["denied_actions"] = sorted(denied)
    elif scenario == "scope_shrink":
        attributes["allowed_system_ids"] = []
        attributes["allowed_domain_ids"] = []
    else:
        raise ValueError(f"Unknown policy probe scenario: {scenario}")
    return MembershipSnapshot(
        workspace_id=original.workspace_id,
        subject_id=original.subject_id,
        active=active,
        attributes=attributes,
    )


async def _service_token(
    client: httpx.AsyncClient,
    *,
    token_url: str,
    client_secret: str,
) -> str:
    response = await client.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": "datariver-airflow",
            "client_secret": client_secret,
        },
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Keycloak did not return an access token.")
    return token


async def _assert_search_baseline(
    client: httpx.AsyncClient,
    api_base_url: str,
    headers: dict[str, str],
) -> None:
    response = await client.get(
        f"{api_base_url.rstrip('/')}/catalog/assets",
        params={"q": "wafer", "limit": 5},
        headers=headers,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Baseline authorized search returned HTTP {response.status_code}.")
    items = response.json().get("items")
    if not isinstance(items, list) or not items:
        raise RuntimeError("Baseline authorized search did not return the seeded wafer assets.")


async def _wait_for_revocation(
    client: httpx.AsyncClient,
    *,
    api_base_url: str,
    headers: dict[str, str],
    scenario: str,
    started_at: float,
    sla_seconds: float,
    poll_interval_seconds: float,
) -> float:
    while True:
        response = await client.get(
            f"{api_base_url.rstrip('/')}/catalog/assets",
            params={"q": "wafer", "limit": 5},
            headers=headers,
        )
        elapsed = time.perf_counter() - started_at
        if scenario in {"membership_inactive", "explicit_action_deny"}:
            reflected = response.status_code == 403
        else:
            body = response.json() if response.status_code == 200 else {}
            reflected = response.status_code == 200 and body.get("items") == []
        if reflected:
            return elapsed * 1000
        if elapsed >= sla_seconds:
            raise RuntimeError(
                f"Policy scenario {scenario} exceeded the {sla_seconds:.3f}s reflection SLA."
            )
        await asyncio.sleep(poll_interval_seconds)


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "minimum_ms": round(ordered[0], 3),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(_percentile(ordered, 0.95), 3),
        "p99_ms": round(_percentile(ordered, 0.99), 3),
        "maximum_ms": round(ordered[-1], 3),
    }


def _percentile(ordered: list[float], fraction: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Required local secret is empty: {path.name}")
    return value


def _read_snapshot(path: Path) -> MembershipSnapshot:
    if not path.exists():
        raise RuntimeError("No policy probe recovery snapshot exists.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("The policy probe recovery snapshot is invalid.")
    return MembershipSnapshot.from_document(value)


def _attributes_document(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("The workspace membership attributes are invalid.")
    return dict(value)


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


if __name__ == "__main__":
    asyncio.run(main())
