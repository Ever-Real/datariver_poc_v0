from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import structlog

from datariver.application.services.catalog_profile_collection import (
    CatalogProfileCollectionService,
)
from datariver.config import Settings, get_settings
from datariver.infrastructure.db.catalog_profile import SqlCatalogProfileStore
from datariver.infrastructure.db.rls import set_security_context
from datariver.workers.container import build_catalog_profile_collector_container

LOGGER = structlog.get_logger()


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect one governed DataHub Profile for one local Catalog asset."
    )
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--asset-id", required=True, type=UUID)
    return parser.parse_args(argv)


async def collect_one(
    *,
    workspace_id: UUID,
    asset_id: UUID,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    subject_id = active_settings.catalog_profile_subject_id
    if subject_id is None:
        raise RuntimeError("Catalog Profile collector service Subject is unavailable.")
    container = build_catalog_profile_collector_container(active_settings)
    try:
        async with container.database.session_factory() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=workspace_id,
                    subject_id=subject_id,
                )
                store = SqlCatalogProfileStore(session)
                result = await CatalogProfileCollectionService(
                    datahub=container.datahub,
                    targets=store,
                    projection=store,
                ).collect(
                    workspace_id=workspace_id,
                    asset_id=asset_id,
                )
        response: dict[str, Any] = {
            "asset_id": str(asset_id),
            "availability": result.availability,
            "failure_code": result.failure_code,
            "workspace_id": str(workspace_id),
        }
        if result.projection is not None:
            response.update(
                {
                    "created": result.projection.created,
                    "snapshot_id": str(result.projection.snapshot_id),
                }
            )
        return response
    finally:
        await container.close()


async def _run(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        result = await collect_one(
            workspace_id=args.workspace_id,
            asset_id=args.asset_id,
        )
    except Exception as error:
        await LOGGER.aerror(
            "catalog_profile_collection_failed",
            failure_type=type(error).__name__,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["availability"] == "AVAILABLE" else 2


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
