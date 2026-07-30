from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.catalog_profile_contracts import (
    CatalogProfileProjectionCommand,
    CatalogProfileProjectionResult,
    CatalogProfileTarget,
)
from datariver.application.catalog_profile_ports import (
    CatalogProfileProjection,
    CatalogProfileTargetReader,
)
from datariver.domain.authz import Classification

_READ_TARGET = text(
    """
    SELECT external_urn, source_version, classification, system_id, domain_id
    FROM catalog.read_profile_target_v1(:workspace_id, :asset_id)
    """
)

_PROJECT_PROFILE = text(
    """
    SELECT snapshot_id, snapshot_identity_hash, created, last_observed_at
    FROM catalog.project_asset_profile_v1(
        :workspace_id,
        :asset_id,
        :payload
    )
    """
).bindparams(bindparam("payload", type_=JSONB))


class SqlCatalogProfileStore(CatalogProfileTargetReader, CatalogProfileProjection):
    """Call the collector-only fixed database boundary.

    The collector login has no direct Catalog table privileges.  Both reads and writes therefore
    cross a fixed, security-definer contract that revalidates the transaction-local identity and
    current asset scope.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_target(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> CatalogProfileTarget | None:
        row = (
            await self._session.execute(
                _READ_TARGET,
                {"workspace_id": workspace_id, "asset_id": asset_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return CatalogProfileTarget(
            workspace_id=workspace_id,
            asset_id=asset_id,
            external_urn=str(row.external_urn),
            source_version=str(row.source_version),
            classification=Classification(int(row.classification)),
            system_id=(UUID(str(row.system_id)) if row.system_id is not None else None),
            domain_id=(UUID(str(row.domain_id)) if row.domain_id is not None else None),
        )

    async def project(
        self,
        command: CatalogProfileProjectionCommand,
    ) -> CatalogProfileProjectionResult:
        observation = command.observation
        payload: dict[str, Any] = {
            "asset_source_version": command.target.source_version,
            "classification": int(command.target.classification),
            "column_count": observation.column_count,
            "columns": [
                {
                    "field_path": metric.field_path,
                    "null_count": metric.null_count,
                    "null_proportion": metric.null_proportion,
                    "unique_count": metric.unique_count,
                    "unique_proportion": metric.unique_proportion,
                }
                for metric in observation.columns
            ],
            "completeness": observation.completeness.value,
            "domain_id": (
                str(command.target.domain_id) if command.target.domain_id is not None else None
            ),
            "normalized_payload_hash": observation.normalized_payload_hash,
            "observed_at": observation.observed_at.isoformat(),
            "profile_kind": observation.kind.value,
            "profiled_at": observation.profiled_at.isoformat(),
            "provenance_fingerprint": observation.provenance_fingerprint,
            "provenance_key_id": observation.provenance_key_id,
            "provider_config_hash": observation.provider_config_hash,
            "provider_contract_hash": observation.provider_contract_hash,
            "provider_query_hash": observation.query_hash,
            "provider_version": observation.provider_version,
            "row_count": observation.row_count,
            "size_bytes": observation.size_bytes,
            "source_watermark_hash": command.source_watermark_hash,
            "stale_at": observation.stale_at.isoformat(),
            "system_id": (
                str(command.target.system_id) if command.target.system_id is not None else None
            ),
        }
        row = (
            await self._session.execute(
                _PROJECT_PROFILE,
                {
                    "workspace_id": command.target.workspace_id,
                    "asset_id": command.target.asset_id,
                    "payload": payload,
                },
            )
        ).one()
        return CatalogProfileProjectionResult(
            snapshot_id=UUID(str(row.snapshot_id)),
            snapshot_identity_hash=str(row.snapshot_identity_hash),
            created=bool(row.created),
            last_observed_at=row.last_observed_at,
        )
