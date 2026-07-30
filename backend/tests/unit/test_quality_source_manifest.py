from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.quality.source_manifest import (
    AUTHORING_MANIFEST_CONTRACT_VERSION,
    MANIFEST_CONTRACT_VERSION,
    PostgresTlsMode,
    QualitySourceManifest,
    QualitySourceManifestError,
    QualitySourceSecretReader,
    parse_quality_source_manifest,
)

ASSET_ID = "00000000-0000-4000-8000-000000000501"
SYSTEM_ID = "00000000-0000-4000-8000-000000000601"


def _profile(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "asset_id": ASSET_ID,
        "system_id": SYSTEM_ID,
        "platform": "POSTGRESQL",
        "source_connection_profile_id": "warehouse-primary",
        "source_connection_profile_version": 3,
        "host": "warehouse.internal",
        "port": 5432,
        "database": "warehouse",
        "schema": "governed",
        "relation": "quality_input",
        "field_map": {
            "field:amount": "amount",
            "field:created_at": "created_at",
        },
        "username": "quality_reader",
        "password_secret_ref": "file:/run/secrets/warehouse_quality_password",
        "tls_mode": "VERIFY_FULL",
        "allowed_ips": ["10.42.0.15", "fd00::15"],
    }
    document.update(overrides)
    document["source_connection_profile_hash"] = canonical_json_hash(document)
    return document


def _workload(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "workload_profile_id": "full-scan-bounded",
        "workload_profile_version": 2,
        "hard_timeout_seconds": 300,
        "statement_timeout_seconds": 120,
        "lock_timeout_seconds": 5,
        "idle_transaction_timeout_seconds": 180,
        "cancel_timeout_seconds": 10,
        "close_timeout_seconds": 10,
        "completion_timeout_seconds": 20,
        "lease_seconds": 360,
        "max_rows": 1_000_000,
        "max_bytes": 536_870_912,
        "max_concurrency": 2,
    }
    document.update(overrides)
    document["workload_profile_hash"] = canonical_json_hash(document)
    return document


def _manifest(
    *,
    profiles: list[dict[str, object]] | None = None,
    workloads: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "contract_version": MANIFEST_CONTRACT_VERSION,
        "profiles": profiles if profiles is not None else [_profile()],
        "workloads": workloads if workloads is not None else [_workload()],
    }


def _authoring_manifest() -> dict[str, object]:
    profile = _profile(
        field_types={
            "field:amount": "DECIMAL",
            "field:created_at": "TIMESTAMP",
        }
    )
    return {
        "contract_version": AUTHORING_MANIFEST_CONTRACT_VERSION,
        "profiles": [profile],
        "workloads": [_workload()],
        "authoring_bindings": [
            {
                "asset_id": ASSET_ID,
                "source_connection_profile_id": "warehouse-primary",
                "source_connection_profile_version": 3,
                "workload_profile_id": "full-scan-bounded",
                "workload_profile_version": 2,
            }
        ],
    }


def _parse(document: dict[str, object]) -> QualitySourceManifest:
    return parse_quality_source_manifest(json.dumps(document))


def test_manifest_resolves_only_exact_source_and_workload_pins() -> None:
    parsed = _parse(_manifest())
    source = parsed.profiles[0]
    workload = parsed.workloads[0]

    assert source.platform == "POSTGRESQL"
    assert source.tls_mode is PostgresTlsMode.VERIFY_FULL
    assert source.column_for("field:amount") == "amount"
    assert workload.hard_timeout_seconds == 300
    resolved = parsed.resolve(
        asset_id=UUID(ASSET_ID),
        source_connection_profile_id=source.source_connection_profile_id,
        source_connection_profile_version=source.source_connection_profile_version,
        source_connection_profile_hash=source.source_connection_profile_hash,
        workload_profile_id=workload.workload_profile_id,
        workload_profile_version=workload.workload_profile_version,
        workload_profile_hash=workload.workload_profile_hash,
    )
    assert resolved.source is source
    assert resolved.workload is workload
    assert parsed.manifest_hash == canonical_json_hash(parsed.document())

    with pytest.raises(QualitySourceManifestError) as source_drift:
        parsed.resolve(
            asset_id=UUID(ASSET_ID),
            source_connection_profile_id=source.source_connection_profile_id,
            source_connection_profile_version=source.source_connection_profile_version,
            source_connection_profile_hash="f" * 64,
            workload_profile_id=workload.workload_profile_id,
            workload_profile_version=workload.workload_profile_version,
            workload_profile_hash=workload.workload_profile_hash,
        )
    assert source_drift.value.details["code"] == "SOURCE_PROFILE_DRIFT"

    with pytest.raises(QualitySourceManifestError) as missing_workload:
        parsed.resolve(
            asset_id=UUID(ASSET_ID),
            source_connection_profile_id=source.source_connection_profile_id,
            source_connection_profile_version=source.source_connection_profile_version,
            source_connection_profile_hash=source.source_connection_profile_hash,
            workload_profile_id="missing",
            workload_profile_version=1,
            workload_profile_hash="f" * 64,
        )
    assert missing_workload.value.details["code"] == "WORKLOAD_PROFILE_UNAVAILABLE"


def test_canonical_profile_and_workload_hashes_are_mandatory() -> None:
    profile = _profile()
    profile["host"] = "changed.internal"
    with pytest.raises(QualitySourceManifestError, match="profile hash"):
        _parse(_manifest(profiles=[profile]))

    workload = _workload()
    workload["max_rows"] = 2
    with pytest.raises(QualitySourceManifestError, match="workload profile hash"):
        _parse(_manifest(workloads=[workload]))


def test_v2_manifest_resolves_one_explicit_authoring_binding_and_typed_schema() -> None:
    parsed = _parse(_authoring_manifest())

    target = parsed.resolve_authoring_target(asset_id=UUID(ASSET_ID))

    assert parsed.contract_version == AUTHORING_MANIFEST_CONTRACT_VERSION
    assert target.source.column_for("field:amount") == "amount"
    assert target.source.logical_type_for("field:amount") == "DECIMAL"
    assert target.fields == (
        ("field:amount", "DECIMAL"),
        ("field:created_at", "TIMESTAMP"),
    )
    assert len(target.schema_hash) == 64
    assert parsed.manifest_hash == canonical_json_hash(parsed.document())


def test_v1_manifest_remains_execution_only_and_cannot_author_rules() -> None:
    parsed = _parse(_manifest())

    with pytest.raises(QualitySourceManifestError) as unavailable:
        parsed.resolve_authoring_target(asset_id=UUID(ASSET_ID))

    assert unavailable.value.details["code"] == "AUTHORING_MANIFEST_UNAVAILABLE"


def test_v2_authoring_bindings_fail_closed_on_schema_or_profile_drift() -> None:
    mismatched_types = _authoring_manifest()
    profile = dict(mismatched_types["profiles"][0])  # type: ignore[index]
    profile["field_types"] = {"field:amount": "DECIMAL"}
    profile["source_connection_profile_hash"] = canonical_json_hash(
        {key: value for key, value in profile.items() if key != "source_connection_profile_hash"}
    )
    mismatched_types["profiles"] = [profile]
    with pytest.raises(QualitySourceManifestError, match="do not match"):
        _parse(mismatched_types)

    missing_profile = _authoring_manifest()
    binding = dict(missing_profile["authoring_bindings"][0])  # type: ignore[index]
    binding["workload_profile_version"] = 99
    missing_profile["authoring_bindings"] = [binding]
    with pytest.raises(QualitySourceManifestError, match="unavailable profile"):
        _parse(missing_profile)

    duplicate = _authoring_manifest()
    duplicate["authoring_bindings"] = [
        duplicate["authoring_bindings"][0],  # type: ignore[index]
        duplicate["authoring_bindings"][0],  # type: ignore[index]
    ]
    with pytest.raises(QualitySourceManifestError, match="repeats an authoring asset"):
        _parse(duplicate)


def test_contract_arrays_fields_and_identities_are_exact_and_bounded() -> None:
    with pytest.raises(QualitySourceManifestError, match="contract"):
        _parse({**_manifest(), "contract_version": "QUALITY_SOURCE_MANIFEST_V3"})
    with pytest.raises(QualitySourceManifestError, match="fields"):
        _parse({**_manifest(), "dsn": "postgresql://user:secret@database/source"})
    with pytest.raises(QualitySourceManifestError, match="array"):
        _parse(_manifest(profiles=[]))

    duplicate_source = _profile()
    with pytest.raises(QualitySourceManifestError, match="repeats a source identity"):
        _parse(_manifest(profiles=[_profile(), duplicate_source]))
    duplicate_workload = _workload()
    with pytest.raises(QualitySourceManifestError, match="repeats a workload identity"):
        _parse(_manifest(workloads=[_workload(), duplicate_workload]))

    duplicate_json_key = (
        '{"contract_version":"QUALITY_SOURCE_MANIFEST_V1",'
        '"contract_version":"QUALITY_SOURCE_MANIFEST_V1","profiles":[],"workloads":[]}'
    )
    with pytest.raises(QualitySourceManifestError, match="repeats a JSON field"):
        parse_quality_source_manifest(duplicate_json_key)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"host": "postgresql://quality_reader:secret@warehouse"}, "source host"),
        ({"host": "*.internal"}, "source host"),
        ({"host": "warehouse.internal?sslmode=disable"}, "source host"),
        ({"relation": "quality_input WHERE true"}, "source relation"),
        ({"password_secret_ref": "literal-password"}, "mounted file secret"),
        ({"password_secret_ref": "file:/run/secrets/nested/password"}, "mounted file secret"),
        ({"tls_mode": "DISABLE"}, "TLS mode"),
        ({"allowed_ips": ["10.42.0.0/24"]}, "exact address"),
        ({"allowed_ips": ["*"]}, "exact address"),
        ({"allowed_ips": ["10.42.0.15", "10.42.0.15"]}, "repeats an allowed IP"),
        ({"host": "10.42.0.16", "allowed_ips": ["10.42.0.15"]}, "outside"),
        (
            {"field_map": {"field:amount": "amount", "field:other": "amount"}},
            "repeats a column",
        ),
    ),
)
def test_source_profiles_reject_urls_queries_credentials_wildcards_and_ambiguity(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(QualitySourceManifestError, match=message):
        _parse(_manifest(profiles=[_profile(**overrides)]))


@pytest.mark.parametrize(
    "overrides",
    (
        {"hard_timeout_seconds": 0},
        {"statement_timeout_seconds": 301},
        {"lock_timeout_seconds": 121},
        {"idle_transaction_timeout_seconds": 301},
        {"cancel_timeout_seconds": 301},
        {"max_rows": 0},
        {"max_bytes": 0},
        {"max_concurrency": 33},
        {"lease_seconds": True},
    ),
)
def test_workload_profiles_enforce_positive_hard_limits(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(QualitySourceManifestError):
        _parse(_manifest(workloads=[_workload(**overrides)]))


def test_source_window_and_margins_must_fit_strictly_inside_lease() -> None:
    with pytest.raises(QualitySourceManifestError, match="strictly inside"):
        _parse(
            _manifest(
                workloads=[
                    _workload(
                        hard_timeout_seconds=300,
                        cancel_timeout_seconds=10,
                        close_timeout_seconds=10,
                        completion_timeout_seconds=20,
                        lease_seconds=340,
                    )
                ]
            )
        )


def test_dedicated_secret_reader_confines_regular_utf8_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source-secrets"
    root.mkdir()
    secret = root / "warehouse_quality_password"
    secret.write_text("private-password\n", encoding="utf-8")
    reader = QualitySourceSecretReader(root)

    assert reader.resolve("file:/run/secrets/warehouse_quality_password") == "private-password"
    for invalid_reference in (
        "file:/run/secrets/../outside",
        "file:/tmp/password",
        "literal:private-password",
    ):
        with pytest.raises(QualitySourceManifestError):
            reader.resolve(invalid_reference)

    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    link = root / "linked_password"
    link.symlink_to(outside)
    with pytest.raises(QualitySourceManifestError, match="secret file"):
        reader.resolve("file:/run/secrets/linked_password")

    oversized = root / "oversized_password"
    oversized.write_bytes(b"x" * (16 * 1024 + 1))
    with pytest.raises(QualitySourceManifestError, match="secret file"):
        reader.resolve("file:/run/secrets/oversized_password")

    invalid_utf8 = root / "invalid_utf8"
    invalid_utf8.write_bytes(b"\xff")
    with pytest.raises(QualitySourceManifestError, match="UTF-8"):
        reader.resolve("file:/run/secrets/invalid_utf8")
