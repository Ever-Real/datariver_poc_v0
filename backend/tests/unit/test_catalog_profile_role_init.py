from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROLE_INIT = ROOT / "infra/postgres/init/010_roles.sh"


def test_catalog_profile_role_is_reconciled_to_projection_only_access() -> None:
    source = ROLE_INIT.read_text(encoding="utf-8")

    assert (
        "catalog_profile_password=$(cat /run/secrets/postgres_catalog_profile_password)"
    ) in source
    assert '--set=catalog_profile_password="$catalog_profile_password"' in source
    assert (
        "ALTER ROLE datariver_catalog_profile WITH LOGIN PASSWORD "
        ":'catalog_profile_password'\n"
        "  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;"
    ) in source
    assert ("pg_has_role('datariver_catalog_profile', candidate.oid, 'MEMBER')") in source
    assert ("pg_has_role(candidate.oid, 'datariver_catalog_profile', 'MEMBER')") in source

    for privilege_family in ("TABLES", "SEQUENCES", "FUNCTIONS"):
        assert (
            "REVOKE ALL PRIVILEGES ON ALL "
            f"{privilege_family} IN SCHEMA catalog, quality "
            "FROM datariver_catalog_profile"
        ) in source
    assert (
        "REVOKE ALL PRIVILEGES ON SCHEMA catalog, quality FROM datariver_catalog_profile"
    ) in source
    assert ("GRANT USAGE ON SCHEMA catalog TO datariver_catalog_profile") in source
    assert "'read_profile_target_v1'" in source
    assert "'project_asset_profile_v1'" in source
    assert ("'GRANT EXECUTE ON FUNCTION %s TO datariver_catalog_profile'") in source
    assert "HAVING count(*) > 1" in source
    assert "'catalog.% must have exactly one canonical signature'" in source

    assert (
        re.search(
            r"GRANT\s+(?:SELECT|INSERT|UPDATE|DELETE|TRUNCATE)\b[^;]*"
            r"\bTO\s+datariver_catalog_profile\b",
            source,
            flags=re.IGNORECASE,
        )
        is None
    )
    assert (
        re.search(
            r"GRANT\s+(?:USAGE|CREATE|ALL(?:\s+PRIVILEGES)?)\s+ON\s+SCHEMA\s+"
            r"quality\b[^;]*\bTO\s+datariver_catalog_profile\b",
            source,
            flags=re.IGNORECASE,
        )
        is None
    )
