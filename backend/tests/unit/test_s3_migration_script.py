from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from botocore.exceptions import ClientError


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "migrate_s3_objects.py"
    spec = importlib.util.spec_from_file_location("migrate_s3_objects", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Body(BytesIO):
    pass


class _Client:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = dict(objects)
        self.uploads = 0

    def head_bucket(self, *, Bucket: str) -> None:
        assert Bucket

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        try:
            value = self.objects[(Bucket, Key)]
        except KeyError as error:
            error_response: Any = {
                "Error": {"Code": "NoSuchKey"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            }
            raise ClientError(
                error_response,
                "HeadObject",
            ) from error
        return {"ContentLength": len(value), "ContentType": "text/plain", "Metadata": {}}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": _Body(self.objects[(Bucket, Key)])}

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, Any] | None,
        Config: Any,
    ) -> None:
        del ExtraArgs, Config
        self.objects[(bucket, key)] = Path(filename).read_bytes()
        self.uploads += 1


def _manifest(objects: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "reference_count": len(objects),
        "object_count": len(objects),
        "malformed_count": 0,
        "conflict_count": 0,
        "objects": objects,
    }
    document.update(overrides)
    return document


def test_manifest_requires_database_reconciliation_counts(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(_manifest([], conflict_count=1)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="conflicting object evidence"):
        module.load_manifest(path)


def test_manifest_refuses_duplicate_object_identity(tmp_path: Path) -> None:
    module = _module()
    digest = hashlib.sha256(b"same").hexdigest()
    item = {"bucket": "accepted", "key": "same.csv", "size_bytes": 4, "sha256": digest}
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(_manifest([item, item], reference_count=2)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate object"):
        module.load_manifest(path)


def test_migration_copies_and_reverifies_manifest_bytes(tmp_path: Path) -> None:
    module = _module()
    value = b"manifest-owned"
    item = module.ManifestObject(
        bucket="accepted",
        key="object.csv",
        size_bytes=len(value),
        sha256=hashlib.sha256(value).hexdigest(),
    )
    source = _Client({("accepted", "object.csv"): value})
    target = _Client({})

    counts = module.migrate_objects(
        source=source,
        target=target,
        objects=(item,),
        apply=True,
        temporary_directory=tmp_path,
    )

    assert counts == {
        "verified_source": 1,
        "verified_existing": 0,
        "copied": 1,
        "planned": 0,
    }
    assert target.objects[("accepted", "object.csv")] == value


def test_migration_refuses_to_overwrite_target_mismatch(tmp_path: Path) -> None:
    module = _module()
    value = b"expected"
    item = module.ManifestObject(
        bucket="accepted",
        key="object.csv",
        size_bytes=len(value),
        sha256=hashlib.sha256(value).hexdigest(),
    )
    source = _Client({("accepted", "object.csv"): value})
    target = _Client({("accepted", "object.csv"): b"tampered"})

    with pytest.raises(ValueError, match="Target object"):
        module.migrate_objects(
            source=source,
            target=target,
            objects=(item,),
            apply=True,
            temporary_directory=tmp_path,
        )

    assert target.uploads == 0
