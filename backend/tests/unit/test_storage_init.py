from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from datariver.workers import storage_init


class _Resolver:
    def resolve(self, _: str) -> str:
        return "secret"


class _Store:
    instances: ClassVar[list[_Store]] = []

    def __init__(self, **_: Any) -> None:
        self.calls: list[dict[str, object]] = []
        self.instances.append(self)

    async def ensure_bucket(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_infoschema_bucket_is_server_only_even_when_bucket_cors_is_managed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        s3_endpoint_url="http://objects:9000",
        s3_public_endpoint_url="http://localhost:9000",
        s3_region="us-east-1",
        s3_access_key_file="/run/secrets/access",
        s3_secret_key_file="/run/secrets/secret",
        app_public_origin="http://localhost:3000/",
        s3_cors_management_mode="bucket",
        s3_bucket_quarantine="quarantine",
        s3_bucket_accepted="accepted",
        s3_bucket_exports="exports",
        s3_bucket_filefolder="filefolder",
        s3_bucket_infoschema="datariver-infoschema",
    )
    _Store.instances.clear()
    monkeypatch.setattr(storage_init, "get_settings", lambda: settings)
    monkeypatch.setattr(storage_init, "SecretResolver", _Resolver)
    monkeypatch.setattr(storage_init, "S3ObjectStore", _Store)

    await storage_init.run()

    calls = _Store.instances[0].calls
    assert [call["bucket"] for call in calls] == [
        "quarantine",
        "accepted",
        "exports",
        "filefolder",
        "datariver-infoschema",
    ]
    assert [call["manage_cors"] for call in calls[:-1]] == [True, True, True, True]
    assert calls[-1]["manage_cors"] is False
