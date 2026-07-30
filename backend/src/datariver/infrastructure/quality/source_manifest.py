from __future__ import annotations

import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import UUID

from datariver.domain.common import ValidationError, canonical_json_hash

MANIFEST_CONTRACT_VERSION = "QUALITY_SOURCE_MANIFEST_V1"

_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_SECRET_BYTES = 16 * 1024
_MAX_PROFILES = 1_000
_MAX_WORKLOADS = 100
_MAX_FIELDS = 1_000
_MAX_ALLOWED_IPS = 32
_MAX_HARD_TIMEOUT_SECONDS = 86_400
_MAX_MARGIN_SECONDS = 300
_MAX_LEASE_SECONDS = 90_000
_MAX_ROWS = 10_000_000_000
_MAX_BYTES = 1_099_511_627_776
_MAX_CONCURRENCY = 32

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")
_FIELD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")
_POSTGRES_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]{0,62}$")
_DNS_HOST_PATTERN = re.compile(
    r"(?=.{1,253}\Z)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
_SECRET_REFERENCE_PATTERN = re.compile(
    r"^file:/run/secrets/(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]{0,127})$"
)


class QualitySourceManifestError(ValidationError):
    """A sanitized, fail-closed source-manifest validation failure."""


class PostgresTlsMode(StrEnum):
    REQUIRE = "REQUIRE"
    VERIFY_CA = "VERIFY_CA"
    VERIFY_FULL = "VERIFY_FULL"


@dataclass(frozen=True, slots=True)
class PostgresSourceProfile:
    asset_id: UUID
    system_id: UUID
    platform: str
    source_connection_profile_id: str
    source_connection_profile_version: int
    source_connection_profile_hash: str
    host: str
    port: int
    database: str
    schema: str
    relation: str
    field_map: tuple[tuple[str, str], ...]
    username: str
    password_secret_ref: str
    tls_mode: PostgresTlsMode
    allowed_ips: tuple[str, ...]

    def configuration_document(self) -> dict[str, object]:
        return {
            "asset_id": str(self.asset_id),
            "system_id": str(self.system_id),
            "platform": self.platform,
            "source_connection_profile_id": self.source_connection_profile_id,
            "source_connection_profile_version": self.source_connection_profile_version,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "schema": self.schema,
            "relation": self.relation,
            "field_map": dict(self.field_map),
            "username": self.username,
            "password_secret_ref": self.password_secret_ref,
            "tls_mode": self.tls_mode.value,
            "allowed_ips": list(self.allowed_ips),
        }

    def document(self) -> dict[str, object]:
        return {
            **self.configuration_document(),
            "source_connection_profile_hash": self.source_connection_profile_hash,
        }

    def column_for(self, field_identifier: str) -> str:
        for candidate, column in self.field_map:
            if candidate == field_identifier:
                return column
        raise QualitySourceManifestError(
            "The pinned source field is unavailable.",
            details={"code": "SOURCE_FIELD_UNAVAILABLE"},
        )


@dataclass(frozen=True, slots=True)
class QualityWorkloadProfile:
    workload_profile_id: str
    workload_profile_version: int
    workload_profile_hash: str
    hard_timeout_seconds: int
    statement_timeout_seconds: int
    lock_timeout_seconds: int
    idle_transaction_timeout_seconds: int
    cancel_timeout_seconds: int
    close_timeout_seconds: int
    completion_timeout_seconds: int
    lease_seconds: int
    max_rows: int
    max_bytes: int
    max_concurrency: int

    def configuration_document(self) -> dict[str, object]:
        return {
            "workload_profile_id": self.workload_profile_id,
            "workload_profile_version": self.workload_profile_version,
            "hard_timeout_seconds": self.hard_timeout_seconds,
            "statement_timeout_seconds": self.statement_timeout_seconds,
            "lock_timeout_seconds": self.lock_timeout_seconds,
            "idle_transaction_timeout_seconds": self.idle_transaction_timeout_seconds,
            "cancel_timeout_seconds": self.cancel_timeout_seconds,
            "close_timeout_seconds": self.close_timeout_seconds,
            "completion_timeout_seconds": self.completion_timeout_seconds,
            "lease_seconds": self.lease_seconds,
            "max_rows": self.max_rows,
            "max_bytes": self.max_bytes,
            "max_concurrency": self.max_concurrency,
        }

    def document(self) -> dict[str, object]:
        return {
            **self.configuration_document(),
            "workload_profile_hash": self.workload_profile_hash,
        }


@dataclass(frozen=True, slots=True)
class ResolvedQualitySource:
    source: PostgresSourceProfile
    workload: QualityWorkloadProfile


@dataclass(frozen=True, slots=True)
class QualitySourceManifest:
    profiles: tuple[PostgresSourceProfile, ...]
    workloads: tuple[QualityWorkloadProfile, ...]

    @property
    def manifest_hash(self) -> str:
        return canonical_json_hash(self.document())

    def document(self) -> dict[str, object]:
        return {
            "contract_version": MANIFEST_CONTRACT_VERSION,
            "profiles": [profile.document() for profile in self.profiles],
            "workloads": [workload.document() for workload in self.workloads],
        }

    def resolve(
        self,
        *,
        asset_id: UUID,
        source_connection_profile_id: str,
        source_connection_profile_version: int,
        source_connection_profile_hash: str,
        workload_profile_id: str,
        workload_profile_version: int,
        workload_profile_hash: str,
    ) -> ResolvedQualitySource:
        source = next(
            (
                profile
                for profile in self.profiles
                if profile.asset_id == asset_id
                and profile.source_connection_profile_id == source_connection_profile_id
                and profile.source_connection_profile_version == source_connection_profile_version
            ),
            None,
        )
        if source is None:
            raise QualitySourceManifestError(
                "The pinned source profile is unavailable.",
                details={"code": "SOURCE_PROFILE_UNAVAILABLE"},
            )
        if source.source_connection_profile_hash != source_connection_profile_hash:
            raise QualitySourceManifestError(
                "The pinned source profile has drifted.",
                details={"code": "SOURCE_PROFILE_DRIFT"},
            )
        workload = next(
            (
                profile
                for profile in self.workloads
                if profile.workload_profile_id == workload_profile_id
                and profile.workload_profile_version == workload_profile_version
            ),
            None,
        )
        if workload is None:
            raise QualitySourceManifestError(
                "The pinned workload profile is unavailable.",
                details={"code": "WORKLOAD_PROFILE_UNAVAILABLE"},
            )
        if workload.workload_profile_hash != workload_profile_hash:
            raise QualitySourceManifestError(
                "The pinned workload profile has drifted.",
                details={"code": "WORKLOAD_PROFILE_DRIFT"},
            )
        return ResolvedQualitySource(source=source, workload=workload)


class QualitySourceSecretReader:
    """Read only one basename below a configured deployment-owned secret root."""

    def __init__(self, root: str | Path) -> None:
        raw_root = Path(root)
        if raw_root.is_symlink():
            raise QualitySourceManifestError("The source secret root is invalid.")
        try:
            resolved_root = raw_root.resolve(strict=True)
        except OSError as error:
            raise QualitySourceManifestError("The source secret root is unavailable.") from error
        if not resolved_root.is_dir():
            raise QualitySourceManifestError("The source secret root is invalid.")
        self._root = resolved_root

    def resolve(self, reference: str) -> str:
        match = _SECRET_REFERENCE_PATTERN.fullmatch(reference)
        if match is None:
            raise QualitySourceManifestError(
                "The source password requires one mounted file secret.",
                details={"code": "SOURCE_SECRET_REFERENCE_INVALID"},
            )
        candidate = self._root / match.group("name")
        try:
            if candidate.is_symlink():
                raise QualitySourceManifestError("The source secret file is invalid.")
            resolved = candidate.resolve(strict=True)
            if resolved.parent != self._root:
                raise QualitySourceManifestError("The source secret file is outside its root.")
            descriptor = os.open(
                resolved,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except QualitySourceManifestError:
            raise
        except OSError as error:
            raise QualitySourceManifestError("The source secret file is unavailable.") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_SECRET_BYTES:
                raise QualitySourceManifestError("The source secret file is invalid.")
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = -1
                content = stream.read(_MAX_SECRET_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not content or len(content) > _MAX_SECRET_BYTES:
            raise QualitySourceManifestError("The source secret file is invalid.")
        try:
            value = content.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise QualitySourceManifestError("The source secret file is not UTF-8.") from error
        if not value:
            raise QualitySourceManifestError("The source secret file is empty.")
        return value


def load_quality_source_manifest(path: str | Path) -> QualitySourceManifest:
    manifest_path = Path(path)
    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise QualitySourceManifestError("The source manifest file is invalid.")
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise QualitySourceManifestError("The source manifest file exceeds its size limit.")
        payload = manifest_path.read_bytes()
    except QualitySourceManifestError:
        raise
    except OSError as error:
        raise QualitySourceManifestError("The source manifest file is unavailable.") from error
    return parse_quality_source_manifest(payload)


def parse_quality_source_manifest(payload: bytes | str) -> QualitySourceManifest:
    if isinstance(payload, bytes):
        if len(payload) > _MAX_MANIFEST_BYTES:
            raise QualitySourceManifestError("The source manifest exceeds its size limit.")
        try:
            encoded = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise QualitySourceManifestError("The source manifest is not UTF-8.") from error
    else:
        if len(payload.encode("utf-8")) > _MAX_MANIFEST_BYTES:
            raise QualitySourceManifestError("The source manifest exceeds its size limit.")
        encoded = payload
    try:
        decoded = cast(
            object,
            json.loads(encoded, object_pairs_hook=_reject_duplicate_json_keys),
        )
    except QualitySourceManifestError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise QualitySourceManifestError("The source manifest is not valid JSON.") from error

    document = _object(decoded, "source manifest")
    _exact_keys(document, {"contract_version", "profiles", "workloads"}, "source manifest")
    if document["contract_version"] != MANIFEST_CONTRACT_VERSION:
        raise QualitySourceManifestError("The source manifest contract is unsupported.")

    raw_profiles = _array(document["profiles"], "profiles", 1, _MAX_PROFILES)
    profiles = tuple(_parse_source_profile(value) for value in raw_profiles)
    raw_workloads = _array(document["workloads"], "workloads", 1, _MAX_WORKLOADS)
    workloads = tuple(_parse_workload_profile(value) for value in raw_workloads)

    source_identities = {
        (
            profile.asset_id,
            profile.source_connection_profile_id,
            profile.source_connection_profile_version,
        )
        for profile in profiles
    }
    if len(source_identities) != len(profiles):
        raise QualitySourceManifestError("The source manifest repeats a source identity.")
    workload_identities = {
        (profile.workload_profile_id, profile.workload_profile_version) for profile in workloads
    }
    if len(workload_identities) != len(workloads):
        raise QualitySourceManifestError("The source manifest repeats a workload identity.")
    return QualitySourceManifest(profiles=profiles, workloads=workloads)


def _parse_source_profile(value: object) -> PostgresSourceProfile:
    document = _object(value, "source profile")
    expected_keys = {
        "asset_id",
        "system_id",
        "platform",
        "source_connection_profile_id",
        "source_connection_profile_version",
        "source_connection_profile_hash",
        "host",
        "port",
        "database",
        "schema",
        "relation",
        "field_map",
        "username",
        "password_secret_ref",
        "tls_mode",
        "allowed_ips",
    }
    _exact_keys(document, expected_keys, "source profile")
    if document["platform"] != "POSTGRESQL":
        raise QualitySourceManifestError("Only PostgreSQL source profiles are supported.")

    raw_fields = _object(document["field_map"], "source field map")
    if not 1 <= len(raw_fields) <= _MAX_FIELDS:
        raise QualitySourceManifestError("The source field map is outside its bound.")
    fields: list[tuple[str, str]] = []
    for field_identifier, raw_column in raw_fields.items():
        if _FIELD_ID_PATTERN.fullmatch(field_identifier) is None:
            raise QualitySourceManifestError("The server-owned field identifier is invalid.")
        column = _postgres_identifier(raw_column, "source column")
        fields.append((field_identifier, column))
    fields.sort()
    if len({column for _, column in fields}) != len(fields):
        raise QualitySourceManifestError("The source field map repeats a column.")

    raw_ips = _array(document["allowed_ips"], "allowed IPs", 1, _MAX_ALLOWED_IPS)
    allowed_ips = tuple(_exact_ip(value) for value in raw_ips)
    if len(set(allowed_ips)) != len(allowed_ips):
        raise QualitySourceManifestError("The source profile repeats an allowed IP.")

    host = _host(document["host"])
    try:
        host_ip = str(ipaddress.ip_address(host))
    except ValueError:
        host_ip = None
    if host_ip is not None and host_ip not in allowed_ips:
        raise QualitySourceManifestError("The source host is outside the exact IP allowlist.")

    password_secret_ref = _text(
        document["password_secret_ref"],
        "source password secret reference",
        160,
    )
    if _SECRET_REFERENCE_PATTERN.fullmatch(password_secret_ref) is None:
        raise QualitySourceManifestError("The source password requires one mounted file secret.")
    try:
        tls_mode = PostgresTlsMode(_text(document["tls_mode"], "source TLS mode", 32))
    except ValueError as error:
        raise QualitySourceManifestError("The source TLS mode is invalid.") from error

    profile = PostgresSourceProfile(
        asset_id=_uuid(document["asset_id"], "source asset"),
        system_id=_uuid(document["system_id"], "source system"),
        platform="POSTGRESQL",
        source_connection_profile_id=_opaque_id(
            document["source_connection_profile_id"], "source profile"
        ),
        source_connection_profile_version=_bounded_int(
            document["source_connection_profile_version"],
            "source profile version",
            1,
            2_147_483_647,
        ),
        source_connection_profile_hash=_sha256(
            document["source_connection_profile_hash"], "source profile hash"
        ),
        host=host,
        port=_bounded_int(document["port"], "source port", 1, 65_535),
        database=_postgres_identifier(document["database"], "source database"),
        schema=_postgres_identifier(document["schema"], "source schema"),
        relation=_postgres_identifier(document["relation"], "source relation"),
        field_map=tuple(fields),
        username=_postgres_identifier(document["username"], "source username"),
        password_secret_ref=password_secret_ref,
        tls_mode=tls_mode,
        allowed_ips=allowed_ips,
    )
    if canonical_json_hash(profile.configuration_document()) != (
        profile.source_connection_profile_hash
    ):
        raise QualitySourceManifestError("The source profile hash does not match its content.")
    return profile


def _parse_workload_profile(value: object) -> QualityWorkloadProfile:
    document = _object(value, "workload profile")
    expected_keys = {
        "workload_profile_id",
        "workload_profile_version",
        "workload_profile_hash",
        "hard_timeout_seconds",
        "statement_timeout_seconds",
        "lock_timeout_seconds",
        "idle_transaction_timeout_seconds",
        "cancel_timeout_seconds",
        "close_timeout_seconds",
        "completion_timeout_seconds",
        "lease_seconds",
        "max_rows",
        "max_bytes",
        "max_concurrency",
    }
    _exact_keys(document, expected_keys, "workload profile")
    workload = QualityWorkloadProfile(
        workload_profile_id=_opaque_id(document["workload_profile_id"], "workload profile"),
        workload_profile_version=_bounded_int(
            document["workload_profile_version"],
            "workload profile version",
            1,
            2_147_483_647,
        ),
        workload_profile_hash=_sha256(document["workload_profile_hash"], "workload profile hash"),
        hard_timeout_seconds=_bounded_int(
            document["hard_timeout_seconds"],
            "hard timeout",
            1,
            _MAX_HARD_TIMEOUT_SECONDS,
        ),
        statement_timeout_seconds=_bounded_int(
            document["statement_timeout_seconds"],
            "statement timeout",
            1,
            _MAX_HARD_TIMEOUT_SECONDS,
        ),
        lock_timeout_seconds=_bounded_int(
            document["lock_timeout_seconds"],
            "lock timeout",
            1,
            _MAX_HARD_TIMEOUT_SECONDS,
        ),
        idle_transaction_timeout_seconds=_bounded_int(
            document["idle_transaction_timeout_seconds"],
            "idle transaction timeout",
            1,
            _MAX_HARD_TIMEOUT_SECONDS,
        ),
        cancel_timeout_seconds=_bounded_int(
            document["cancel_timeout_seconds"],
            "cancel timeout",
            1,
            _MAX_MARGIN_SECONDS,
        ),
        close_timeout_seconds=_bounded_int(
            document["close_timeout_seconds"],
            "close timeout",
            1,
            _MAX_MARGIN_SECONDS,
        ),
        completion_timeout_seconds=_bounded_int(
            document["completion_timeout_seconds"],
            "completion timeout",
            1,
            _MAX_MARGIN_SECONDS,
        ),
        lease_seconds=_bounded_int(
            document["lease_seconds"],
            "lease",
            1,
            _MAX_LEASE_SECONDS,
        ),
        max_rows=_bounded_int(document["max_rows"], "maximum rows", 1, _MAX_ROWS),
        max_bytes=_bounded_int(document["max_bytes"], "maximum bytes", 1, _MAX_BYTES),
        max_concurrency=_bounded_int(
            document["max_concurrency"],
            "maximum concurrency",
            1,
            _MAX_CONCURRENCY,
        ),
    )
    if workload.statement_timeout_seconds > workload.hard_timeout_seconds:
        raise QualitySourceManifestError("The statement timeout exceeds the hard timeout.")
    if workload.lock_timeout_seconds > workload.statement_timeout_seconds:
        raise QualitySourceManifestError("The lock timeout exceeds the statement timeout.")
    if workload.idle_transaction_timeout_seconds > workload.hard_timeout_seconds:
        raise QualitySourceManifestError("The idle transaction timeout exceeds the hard timeout.")
    guarded_window = (
        workload.hard_timeout_seconds
        + workload.cancel_timeout_seconds
        + workload.close_timeout_seconds
        + workload.completion_timeout_seconds
    )
    if guarded_window >= workload.lease_seconds:
        raise QualitySourceManifestError(
            "The source-access window and margins must fit strictly inside the lease."
        )
    if canonical_json_hash(workload.configuration_document()) != workload.workload_profile_hash:
        raise QualitySourceManifestError("The workload profile hash does not match its content.")
    return workload


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise QualitySourceManifestError("The source manifest repeats a JSON field.")
        document[key] = value
    return document


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise QualitySourceManifestError(f"The {label} must be a JSON object.")
    return cast(dict[str, object], value)


def _array(
    value: object,
    label: str,
    minimum: int,
    maximum: int,
) -> list[object]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise QualitySourceManifestError(f"The {label} array is outside its bound.")
    return cast(list[object], value)


def _exact_keys(document: dict[str, object], expected: set[str], label: str) -> None:
    if set(document) != expected:
        raise QualitySourceManifestError(f"The {label} fields do not match the contract.")


def _text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise QualitySourceManifestError(f"The {label} is invalid.")
    return value


def _uuid(value: object, label: str) -> UUID:
    raw = _text(value, label, 36)
    try:
        parsed = UUID(raw)
    except ValueError as error:
        raise QualitySourceManifestError(f"The {label} is invalid.") from error
    if raw != str(parsed):
        raise QualitySourceManifestError(f"The {label} is not canonical.")
    return parsed


def _opaque_id(value: object, label: str) -> str:
    raw = _text(value, label, 255)
    if _OPAQUE_ID_PATTERN.fullmatch(raw) is None:
        raise QualitySourceManifestError(f"The {label} ID is invalid.")
    return raw


def _sha256(value: object, label: str) -> str:
    raw = _text(value, label, 64)
    if _SHA256_PATTERN.fullmatch(raw) is None:
        raise QualitySourceManifestError(f"The {label} is invalid.")
    return raw


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise QualitySourceManifestError(f"The {label} is outside its bound.")
    return value


def _postgres_identifier(value: object, label: str) -> str:
    raw = _text(value, label, 63)
    if _POSTGRES_IDENTIFIER_PATTERN.fullmatch(raw) is None:
        raise QualitySourceManifestError(f"The {label} is invalid.")
    return raw


def _host(value: object) -> str:
    raw = _text(value, "source host", 253)
    if any(token in raw for token in ("://", "/", "?", "#", "@", "*")):
        raise QualitySourceManifestError("The source host is invalid.")
    try:
        parsed_ip = str(ipaddress.ip_address(raw))
    except ValueError:
        if raw != raw.lower() or _DNS_HOST_PATTERN.fullmatch(raw) is None:
            raise QualitySourceManifestError("The source host is invalid.") from None
        return raw
    if raw != parsed_ip:
        raise QualitySourceManifestError("The source host IP is not canonical.")
    return parsed_ip


def _exact_ip(value: object) -> str:
    raw = _text(value, "allowed IP", 45)
    if "/" in raw or "*" in raw:
        raise QualitySourceManifestError("The allowed IP must be one exact address.")
    try:
        parsed = str(ipaddress.ip_address(raw))
    except ValueError as error:
        raise QualitySourceManifestError("The allowed IP must be one exact address.") from error
    if raw != parsed:
        raise QualitySourceManifestError("The allowed IP is not canonical.")
    return parsed
