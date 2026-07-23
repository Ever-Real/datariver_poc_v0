from __future__ import annotations

import asyncio

from datariver.config import get_settings
from datariver.infrastructure.object_store.s3 import S3ObjectStore
from datariver.infrastructure.secrets import SecretResolver


async def run() -> None:
    settings = get_settings()
    resolver = SecretResolver()
    store = S3ObjectStore(
        endpoint_url=settings.s3_endpoint_url,
        public_endpoint_url=settings.s3_public_endpoint_url,
        region=settings.s3_region,
        access_key=resolver.resolve(f"file:{settings.s3_access_key_file}"),
        secret_key=resolver.resolve(f"file:{settings.s3_secret_key_file}"),
    )
    allowed_origins = (str(settings.app_public_origin).rstrip("/"),)
    manage_cors = settings.s3_cors_management_mode == "bucket"
    await store.ensure_bucket(
        bucket=settings.s3_bucket_quarantine,
        allowed_origins=allowed_origins,
        manage_cors=manage_cors,
    )
    await store.ensure_bucket(
        bucket=settings.s3_bucket_accepted,
        allowed_origins=allowed_origins,
        manage_cors=manage_cors,
    )
    await store.ensure_bucket(
        bucket=settings.s3_bucket_exports,
        allowed_origins=allowed_origins,
        manage_cors=manage_cors,
    )
    if settings.s3_bucket_filefolder:
        await store.ensure_bucket(
            bucket=settings.s3_bucket_filefolder,
            allowed_origins=allowed_origins,
            manage_cors=manage_cors,
        )
    if settings.s3_bucket_infoschema:
        await store.ensure_bucket(
            bucket=settings.s3_bucket_infoschema,
            allowed_origins=allowed_origins,
            manage_cors=False,
        )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
