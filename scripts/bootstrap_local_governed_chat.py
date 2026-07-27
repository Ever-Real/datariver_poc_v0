#!/usr/bin/env python3
"""Run the explicit local governed-Chat bootstrap and inject only returned UUID bindings."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from uuid import UUID

from platform_workflow import ROOT, compose_arguments, read_env_values, update_env_values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize local governed Chat DB contracts and update one environment file."
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--attestation-evidence-reference", required=True)
    parser.add_argument("--attestation-valid-days", type=int, required=True)
    parser.add_argument("--restricted-search-grant-maximum-days", type=int, required=True)
    parser.add_argument(
        "--maximum-classification",
        choices=("PUBLIC", "INTERNAL", "CONFIDENTIAL"),
        default="INTERNAL",
    )
    parser.add_argument("--completed-operation-days", type=int, required=True)
    parser.add_argument("--chat-content-days", type=int, required=True)
    parser.add_argument("--audit-online-months", type=int, required=True)
    parser.add_argument("--immutable-archive-years", type=int, required=True)
    return parser


def _required_uuid(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"The local governed Chat bootstrap omitted {key}.")
    return str(UUID(value))


def main() -> None:
    arguments = _parser().parse_args()
    env_file = arguments.env_file.expanduser().resolve()
    values = read_env_values(env_file)
    if values.get("APP_ENV") != "development":
        raise RuntimeError("Local governed Chat bootstrap requires APP_ENV=development.")
    module_arguments = (
        "--jurisdiction",
        arguments.jurisdiction,
        "--region",
        arguments.region,
        "--attestation-evidence-reference",
        arguments.attestation_evidence_reference,
        "--attestation-valid-days",
        str(arguments.attestation_valid_days),
        "--restricted-search-grant-maximum-days",
        str(arguments.restricted_search_grant_maximum_days),
        "--maximum-classification",
        arguments.maximum_classification,
        "--completed-operation-days",
        str(arguments.completed_operation_days),
        "--chat-content-days",
        str(arguments.chat_content_days),
        "--audit-online-months",
        str(arguments.audit_online_months),
        "--immutable-archive-years",
        str(arguments.immutable_archive_years),
    )
    command = compose_arguments(
        env_file=env_file,
        compose_files=(ROOT / "compose.yaml", ROOT / "compose.identity.yaml"),
        trailing=(
            "exec",
            "-T",
            "api",
            "/app/.venv/bin/python",
            "-m",
            "datariver.local_governed_chat_bootstrap",
            *module_arguments,
        ),
    )
    completed = subprocess.run(  # noqa: S603 - argv is fixed except validated scalar arguments.
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        errors = [line.strip() for line in completed.stderr.splitlines() if line.strip()]
        detail = errors[-1] if errors else "no diagnostic was returned"
        raise RuntimeError(f"The local governed Chat bootstrap failed: {detail}")
    output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not output_lines:
        raise RuntimeError("The local governed Chat bootstrap returned no result.")
    document = json.loads(output_lines[-1])
    if not isinstance(document, dict):
        raise RuntimeError("The local governed Chat bootstrap result is invalid.")
    updates = {
        "CHAT_COMPOSITION_PROVIDER_PROFILE_VERSION_ID": _required_uuid(
            document, "composition_profile_version_id"
        ),
        "CHAT_EMBEDDING_PROVIDER_PROFILE_VERSION_ID": _required_uuid(
            document, "embedding_profile_version_id"
        ),
        "CHAT_RERANKER_PROVIDER_PROFILE_VERSION_ID": _required_uuid(
            document, "reranker_profile_version_id"
        ),
        "CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED": "false",
    }
    update_env_values(env_file, updates)
    print(
        json.dumps(
            {
                **document,
                "environment_file": str(env_file),
                "injected_keys": sorted(updates),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
