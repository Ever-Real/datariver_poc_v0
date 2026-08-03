#!/usr/bin/env python3
"""Classify the fixed Mac production-Web Keycloak invariant without mutation."""

from __future__ import annotations

import sys
from pathlib import Path

from docker_capacity import exclusive_docker_workflow_lock
from platform_workflow import (
    ROOT,
    TOPOLOGY_RECONCILIATION_SECRET_NAMES,
    environment_key_hashes,
    load_applied_state,
    read_env_values,
    require_topology_reconciliation_secrets,
    state_path,
)
from probe_gateway_auth_parity import (
    KeycloakGatewayAuthParityIdentity,
    ProductionWebInvariantPredicate,
    _ProductionWebInvariantEvidence,
    format_production_web_invariant_evidence,
)
from workflow_update_restart import _read_gateway_admin_password

PROFILE = "mac-development"
ENVIRONMENT_FILE = ".env.mac-development"
SECRET_NAMES = TOPOLOGY_RECONCILIATION_SECRET_NAMES


def _unknown_evidence() -> _ProductionWebInvariantEvidence:
    return _ProductionWebInvariantEvidence(
        predicate=ProductionWebInvariantPredicate.UNKNOWN,
        fingerprint=None,
        client_match_count=None,
        mapper_count=None,
        boolean_missing_fields=None,
        boolean_non_bool_fields=None,
    )


def _mac_environment() -> tuple[Path, int]:
    state = load_applied_state(state_path(ROOT, PROFILE))
    expected_environment = (ROOT / ENVIRONMENT_FILE).resolve()
    selected_environment = Path(state.env_file).expanduser()
    if not selected_environment.is_absolute():
        selected_environment = ROOT / selected_environment
    if (
        state.profile != PROFILE
        or state.deployment_mode != "build"
        or state.local_gateway
        or state.local_graph
        or selected_environment.resolve() != expected_environment
    ):
        raise RuntimeError("GATEWAY_PRODUCTION_INVARIANT_CONTEXT_INVALID")
    values = read_env_values(expected_environment)
    if not state.environment_key_hashes or (
        environment_key_hashes(values) != state.environment_key_hashes
    ):
        raise RuntimeError("GATEWAY_PRODUCTION_INVARIANT_CONTEXT_INVALID")
    raw_port = values.get("KEYCLOAK_PORT", "8081")
    if not raw_port.isdecimal():
        raise RuntimeError("GATEWAY_PRODUCTION_INVARIANT_CONTEXT_INVALID")
    port = int(raw_port)
    if not 1 <= port <= 65_535 or str(port) != raw_port:
        raise RuntimeError("GATEWAY_PRODUCTION_INVARIANT_CONTEXT_INVALID")
    return expected_environment, port


def _run_diagnostic() -> _ProductionWebInvariantEvidence:
    identity: KeycloakGatewayAuthParityIdentity | None = None
    password = ""
    with exclusive_docker_workflow_lock(ROOT):
        _environment_file, keycloak_port = _mac_environment()
        with require_topology_reconciliation_secrets(ROOT) as guard:
            guard.revalidate()
            expected_names = set(SECRET_NAMES)
            if (
                len(SECRET_NAMES) != 8
                or set(guard.file_descriptors) != expected_names
                or set(guard.file_identities) != expected_names
            ):
                raise RuntimeError("GATEWAY_PRODUCTION_INVARIANT_CONTEXT_INVALID")
            password = _read_gateway_admin_password(guard)
            guard.revalidate()
            try:
                identity = KeycloakGatewayAuthParityIdentity(
                    base_url=f"http://127.0.0.1:{keycloak_port}",
                    admin_username="datariver-bootstrap",
                    admin_password=password,
                )
                return identity.classify_production_web_invariant()
            finally:
                password = ""
                if identity is not None:
                    identity.release_without_mutation()
                guard.revalidate()


def main() -> int:
    evidence = _unknown_evidence()
    if len(sys.argv) == 1:
        try:
            evidence = _run_diagnostic()
        except BaseException:
            evidence = _unknown_evidence()
    print(format_production_web_invariant_evidence(evidence), flush=True)
    return 0 if evidence.predicate is ProductionWebInvariantPredicate.PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
