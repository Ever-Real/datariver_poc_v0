from __future__ import annotations

from collections.abc import Mapping

MANAGED_DATABASE_SCHEMAS = (
    "platform",
    "iam",
    "authz",
    "catalog",
    "governance",
    "integration",
    "knowledge",
    "assistant",
    "sharing",
    "retention",
    "quality",
)
_MANAGED_DATABASE_SCHEMA_SET = frozenset(MANAGED_DATABASE_SCHEMAS)


def include_managed_database_name(
    name: str | None,
    object_type: str,
    parent_names: Mapping[str, str | None],
) -> bool:
    """Limit Alembic reflection to schemas canonically owned by DataRiver.

    Development seed schemas and externally operated databases may share a PostgreSQL instance,
    but they are not application metadata and must never become autogenerate deletion candidates.
    """

    if object_type == "schema":
        return name in _MANAGED_DATABASE_SCHEMA_SET
    schema_name = parent_names.get("schema_name")
    if object_type == "table" and schema_name is not None:
        return schema_name in _MANAGED_DATABASE_SCHEMA_SET
    return True
