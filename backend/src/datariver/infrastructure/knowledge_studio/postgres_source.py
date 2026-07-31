# ruff: noqa: S608 -- manifest identifiers are validated and always quoted.
from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import re
import ssl
import stat
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from datariver.application.errors import ExternalDependencyError
from datariver.domain.authz import EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash
from datariver.domain.knowledge_studio_ingestion import (
    StudioIngestionBindingClaim,
    StudioIngestionClaim,
    StudioSourceProfilePin,
    StudioSourceRead,
)
from datariver.infrastructure.knowledge_studio.connections import (
    KnowledgeStudioPhysicalSourceAdapter,
    PhysicalProbeReceipt,
    PhysicalSampleReceipt,
    PhysicalSourceBinding,
    RegisteredPhysicalSource,
    RegistryBackedKnowledgeStudioSampleReader,
    StaticKnowledgeStudioConnectionRegistry,
)

MANIFEST_CONTRACT_VERSION = "KNOWLEDGE_STUDIO_POSTGRES_SOURCE_MANIFEST_V1"
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_SECRET_BYTES = 16 * 1024
_MAX_SOURCES = 1_000
_MAX_FIELDS = 1_000
_MAXIMUM_BATCH_ROWS = 100_000
_MAXIMUM_BATCH_BYTES = 256 * 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]{0,62}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")
_FIELD_ID = re.compile(r"^[A-Za-z0-9가-힣][A-Za-z0-9가-힣_.:/ \-]{0,254}$")
_SECRET_REFERENCE = re.compile(r"^file:/run/secrets/(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]{0,127})$")


class KnowledgeStudioSourceManifestError(ValidationError):
    """Sanitized, fail-closed deployment manifest error."""


@dataclass(frozen=True, slots=True)
class KnowledgeStudioPostgresSource:
    workspace_id: UUID
    asset_id: UUID
    source_version: str
    projection_source_version: str
    minimum_clearance: int
    connection_profile_id: str
    connection_profile_version: int
    connection_profile_hash: str
    host: str
    allowed_ips: tuple[str, ...]
    port: int
    database: str
    schema: str
    relation: str
    field_map: tuple[tuple[str, str], ...]
    key_fields: tuple[str, ...]
    username: str
    password_secret_ref: str
    tls_mode: str
    statement_timeout_seconds: int
    lock_timeout_seconds: int
    idle_transaction_timeout_seconds: int
    hard_timeout_seconds: int
    batch_size: int
    maximum_rows: int
    maximum_bytes: int

    @property
    def adapter_id(self) -> str:
        return f"postgres-manifest-v1:{self.connection_profile_hash[:24]}"

    def configuration_document(self) -> dict[str, object]:
        return {
            "workspace_id": str(self.workspace_id),
            "asset_id": str(self.asset_id),
            "source_version": self.source_version,
            "projection_source_version": self.projection_source_version,
            "minimum_clearance": self.minimum_clearance,
            "connection_profile_id": self.connection_profile_id,
            "connection_profile_version": self.connection_profile_version,
            "host": self.host,
            "allowed_ips": list(self.allowed_ips),
            "port": self.port,
            "database": self.database,
            "schema": self.schema,
            "relation": self.relation,
            "field_map": dict(self.field_map),
            "key_fields": list(self.key_fields),
            "username": self.username,
            "password_secret_ref": self.password_secret_ref,
            "tls_mode": self.tls_mode,
            "statement_timeout_seconds": self.statement_timeout_seconds,
            "lock_timeout_seconds": self.lock_timeout_seconds,
            "idle_transaction_timeout_seconds": self.idle_transaction_timeout_seconds,
            "hard_timeout_seconds": self.hard_timeout_seconds,
            "batch_size": self.batch_size,
            "maximum_rows": self.maximum_rows,
            "maximum_bytes": self.maximum_bytes,
        }

    def document(self) -> dict[str, object]:
        return {
            **self.configuration_document(),
            "connection_profile_hash": self.connection_profile_hash,
        }

    def column_for(self, field_path: str) -> str:
        for candidate, column in self.field_map:
            if candidate == field_path:
                return column
        raise ConflictError(
            "The approved physical source field is unavailable.",
            details={"code": "SOURCE_FIELD_UNAVAILABLE"},
        )


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSourceManifest:
    manifest_id: str
    manifest_version: int
    sources: tuple[KnowledgeStudioPostgresSource, ...]

    @property
    def manifest_hash(self) -> str:
        return canonical_json_hash(self.document())

    def document(self) -> dict[str, object]:
        return {
            "contract_version": MANIFEST_CONTRACT_VERSION,
            "manifest_id": self.manifest_id,
            "manifest_version": self.manifest_version,
            "sources": [source.document() for source in self.sources],
        }

    def resolve(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> KnowledgeStudioPostgresSource | None:
        return next(
            (
                source
                for source in self.sources
                if source.workspace_id == workspace_id and source.asset_id == asset_id
            ),
            None,
        )

    def resolve_pin(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        source_version: str,
        projection_source_version: str,
    ) -> StudioSourceProfilePin | None:
        source = self.resolve(workspace_id=workspace_id, asset_id=asset_id)
        if (
            source is None
            or source.source_version != source_version
            or source.projection_source_version != projection_source_version
        ):
            return None
        pin = StudioSourceProfilePin(
            workspace_id=source.workspace_id,
            asset_id=source.asset_id,
            source_version=source.source_version,
            projection_source_version=source.projection_source_version,
            connection_profile_id=source.connection_profile_id,
            connection_profile_version=source.connection_profile_version,
            connection_profile_hash=source.connection_profile_hash,
        )
        pin.validate()
        return pin


class KnowledgeStudioSourceSecretReader:
    """Resolve one mounted regular-file secret without following a symlink."""

    def __init__(self, root: str | Path) -> None:
        raw_root = Path(root)
        try:
            if raw_root.is_symlink():
                raise KnowledgeStudioSourceManifestError(
                    "The Knowledge Studio source secret root is invalid."
                )
            resolved = raw_root.resolve(strict=True)
        except OSError as error:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source secret root is unavailable."
            ) from error
        if not resolved.is_dir():
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source secret root is invalid."
            )
        self._root = resolved

    def resolve(self, reference: str) -> str:
        match = _SECRET_REFERENCE.fullmatch(reference)
        if match is None:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source password requires one mounted file secret."
            )
        candidate = self._root / match.group("name")
        descriptor = -1
        try:
            if candidate.is_symlink():
                raise KnowledgeStudioSourceManifestError(
                    "The Knowledge Studio source secret file is invalid."
                )
            resolved = candidate.resolve(strict=True)
            if resolved.parent != self._root:
                raise KnowledgeStudioSourceManifestError(
                    "The Knowledge Studio source secret file is outside its root."
                )
            descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_SECRET_BYTES:
                raise KnowledgeStudioSourceManifestError(
                    "The Knowledge Studio source secret file is invalid."
                )
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = -1
                payload = stream.read(_MAX_SECRET_BYTES + 1)
        except KnowledgeStudioSourceManifestError:
            raise
        except OSError as error:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source secret file is unavailable."
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not payload or len(payload) > _MAX_SECRET_BYTES:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source secret file is invalid."
            )
        try:
            value = payload.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source secret file is not UTF-8."
            ) from error
        if not value:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source secret file is empty."
            )
        return value


class PostgresKnowledgeStudioSourceAdapter(KnowledgeStudioPhysicalSourceAdapter):
    """Bounded read-only adapter for one exact manifest source."""

    def __init__(
        self,
        *,
        source: KnowledgeStudioPostgresSource,
        secret_reader: KnowledgeStudioSourceSecretReader,
    ) -> None:
        self._source = source
        self._secret_reader = secret_reader
        self.adapter_id = source.adapter_id

    async def sample_rows(
        self,
        *,
        binding: PhysicalSourceBinding,
        field_paths: tuple[str, ...],
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> PhysicalSampleReceipt:
        del environment, request_id
        self._require_exact(binding=binding, subject=subject)
        if not 5 <= limit <= 10:
            raise ConflictError("Physical source samples are bounded to 5 through 10 rows.")
        if not field_paths or len(field_paths) > 200:
            raise ConflictError("Physical source samples require a bounded field allowlist.")
        columns = tuple(self._source.column_for(field_path) for field_path in field_paths)
        connection: asyncpg.Connection[asyncpg.Record] | None = None
        transaction: asyncpg.Transaction | None = None
        password = self._secret_reader.resolve(self._source.password_secret_ref)
        try:
            async with asyncio.timeout(self._source.hard_timeout_seconds):
                connection = await self._connect(password=password)
                transaction = connection.transaction(isolation="repeatable_read", readonly=True)
                await transaction.start()
                selection = ", ".join(
                    f"{_identifier(column)} AS {_identifier(f'field_{index}')}"
                    for index, column in enumerate(columns)
                )
                ordering = ", ".join(
                    _identifier(self._source.column_for(field)) for field in self._source.key_fields
                )
                records = await connection.fetch(
                    f"SELECT {selection} "
                    f"FROM {_qualified(self._source.schema, self._source.relation)} "
                    f"ORDER BY {ordering} LIMIT $1",
                    limit,
                )
                rows = tuple(
                    {
                        field_path: _sample_scalar(record[f"field_{index}"])
                        for index, field_path in enumerate(field_paths)
                    }
                    for record in records
                )
                return PhysicalSampleReceipt(
                    source_version=self._source.source_version,
                    projection_source_version=self._source.projection_source_version,
                    rows=rows,
                    observed_at=datetime.now(UTC),
                )
        except (TimeoutError, asyncpg.PostgresError, OSError) as error:
            raise ConflictError(
                "The approved physical source is temporarily unavailable.",
                details={"code": "PHYSICAL_SOURCE_UNAVAILABLE"},
            ) from error
        finally:
            password = ""
            await _close(connection=connection, transaction=transaction)

    async def probe_access(
        self,
        *,
        binding: PhysicalSourceBinding,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> PhysicalProbeReceipt:
        del environment, request_id
        self._require_exact(binding=binding, subject=subject)
        connection: asyncpg.Connection[asyncpg.Record] | None = None
        transaction: asyncpg.Transaction | None = None
        password = self._secret_reader.resolve(self._source.password_secret_ref)
        try:
            async with asyncio.timeout(self._source.hard_timeout_seconds):
                connection = await self._connect(password=password)
                transaction = connection.transaction(isolation="repeatable_read", readonly=True)
                await transaction.start()
                key = self._source.column_for(self._source.key_fields[0])
                await connection.fetchval(
                    f"SELECT {_identifier(key)} "
                    f"FROM {_qualified(self._source.schema, self._source.relation)} LIMIT 1"
                )
            accessible = True
        except (TimeoutError, asyncpg.PostgresError, OSError):
            accessible = False
        finally:
            password = ""
            await _close(connection=connection, transaction=transaction)
        return PhysicalProbeReceipt(
            source_version=self._source.source_version,
            projection_source_version=self._source.projection_source_version,
            accessible=accessible,
            observed_at=datetime.now(UTC),
        )

    async def _connect(self, *, password: str) -> asyncpg.Connection[asyncpg.Record]:
        address = str(ipaddress.ip_address(self._source.host))
        if address not in self._source.allowed_ips:
            raise ConflictError("The physical source address is outside its exact allowlist.")
        return await asyncpg.connect(
            host=address,
            port=self._source.port,
            user=self._source.username,
            password=password,
            database=self._source.database,
            ssl=_ssl_context(self._source.tls_mode),
            timeout=min(30, self._source.hard_timeout_seconds),
            command_timeout=self._source.statement_timeout_seconds,
            statement_cache_size=0,
            server_settings={
                "application_name": "datariver-knowledge-studio-preview",
                "statement_timeout": f"{self._source.statement_timeout_seconds * 1000}",
                "lock_timeout": f"{self._source.lock_timeout_seconds * 1000}",
                "idle_in_transaction_session_timeout": (
                    f"{self._source.idle_transaction_timeout_seconds * 1000}"
                ),
                "default_transaction_read_only": "on",
            },
        )

    def _require_exact(
        self,
        *,
        binding: PhysicalSourceBinding,
        subject: SubjectAttributes,
    ) -> None:
        if (
            binding.workspace_id != self._source.workspace_id
            or binding.asset_id != self._source.asset_id
            or binding.source_version != self._source.source_version
            or binding.projection_source_version != self._source.projection_source_version
            or binding.adapter_id != self.adapter_id
            or subject.workspace_id != self._source.workspace_id
            or not subject.active
            or subject.clearance < self._source.minimum_clearance
        ):
            raise ConflictError("The physical source contract is no longer exact.")


class PostgresKnowledgeStudioBatchSourceReader:
    """Read exact released Class bindings through fenced, bounded PostgreSQL batches."""

    def __init__(
        self,
        *,
        manifest: KnowledgeStudioSourceManifest,
        secret_reader: KnowledgeStudioSourceSecretReader,
    ) -> None:
        self._manifest = manifest
        self._secret_reader = secret_reader

    @property
    def manifest_id(self) -> str:
        return self._manifest.manifest_id

    @property
    def manifest_version(self) -> int:
        return self._manifest.manifest_version

    @property
    def manifest_hash(self) -> str:
        return self._manifest.manifest_hash

    async def read(
        self,
        *,
        claim: StudioIngestionClaim,
        statement_fence: Callable[[], Awaitable[None]],
    ) -> tuple[StudioSourceRead, ...]:
        claim.validate()
        self._require_manifest_pin(claim)
        if claim.source_access_deadline is None:
            raise ConflictError(
                "The Studio source-access window is unavailable.",
                details={"code": "SOURCE_ACCESS_NOT_FROZEN", "stale": True},
            )
        if len({binding.pin_id for binding in claim.bindings}) != len(claim.bindings):
            raise ValidationError("The Studio ingestion claim repeats a Binding pin.")

        total_rows = 0
        total_bytes = 0
        source_usage: dict[tuple[UUID, str], tuple[int, int]] = {}
        reads: list[StudioSourceRead] = []
        for binding in claim.bindings:
            source = self._resolve_binding_source(claim=claim, binding=binding)
            source_key = (source.asset_id, source.connection_profile_hash)
            source_rows, source_bytes = source_usage.get(source_key, (0, 0))
            read, row_count, byte_count = await self._read_binding(
                claim=claim,
                binding=binding,
                source=source,
                statement_fence=statement_fence,
                maximum_rows=min(
                    _MAXIMUM_BATCH_ROWS - total_rows,
                    source.maximum_rows - source_rows,
                ),
                maximum_bytes=min(
                    _MAXIMUM_BATCH_BYTES - total_bytes,
                    source.maximum_bytes - source_bytes,
                ),
            )
            total_rows += row_count
            total_bytes += byte_count
            source_usage[source_key] = (source_rows + row_count, source_bytes + byte_count)
            reads.append(read)
        return tuple(reads)

    def _require_manifest_pin(self, claim: StudioIngestionClaim) -> None:
        if (
            claim.manifest_id != self.manifest_id
            or claim.manifest_version != self.manifest_version
            or claim.manifest_hash != self.manifest_hash
        ):
            raise ConflictError(
                "The Studio source manifest no longer matches the ingestion claim.",
                details={"code": "STALE_SOURCE_MANIFEST", "stale": True},
            )

    def _resolve_binding_source(
        self,
        *,
        claim: StudioIngestionClaim,
        binding: StudioIngestionBindingClaim,
    ) -> KnowledgeStudioPostgresSource:
        binding.validate()
        source = self._manifest.resolve(
            workspace_id=claim.workspace_id,
            asset_id=binding.source_asset_id,
        )
        if source is None:
            raise ConflictError(
                "The released Studio source is absent from the deployment manifest.",
                details={"code": "STALE_SOURCE_MANIFEST", "stale": True},
            )
        if (
            binding.source_version != source.source_version
            or binding.projection_source_version != source.projection_source_version
        ):
            raise ConflictError(
                "The Studio source version no longer matches the released Binding.",
                details={"code": "STALE_SOURCE_VERSION", "stale": True},
            )
        if (
            binding.connection_profile_id != source.connection_profile_id
            or binding.connection_profile_version != source.connection_profile_version
            or binding.connection_profile_hash != source.connection_profile_hash
        ):
            raise ConflictError(
                "The Studio connection profile no longer matches the released Binding.",
                details={"code": "STALE_CONNECTION_PROFILE", "stale": True},
            )
        if binding.source_classification > claim.graph_classification:
            raise ConflictError(
                "The released Studio source exceeds the graph classification envelope.",
                details={"code": "STALE_CLASSIFICATION_ENVELOPE", "stale": True},
            )
        return source

    async def _read_binding(
        self,
        *,
        claim: StudioIngestionClaim,
        binding: StudioIngestionBindingClaim,
        source: KnowledgeStudioPostgresSource,
        statement_fence: Callable[[], Awaitable[None]],
        maximum_rows: int,
        maximum_bytes: int,
    ) -> tuple[StudioSourceRead, int, int]:
        field_paths = tuple(dict.fromkeys(rule.source_field_path for rule in binding.rules))
        if not field_paths or len(field_paths) > _MAX_FIELDS:
            raise ValidationError("A Studio ingestion Binding has an invalid field allowlist.")
        columns = tuple(source.column_for(field_path) for field_path in field_paths)
        key_columns = tuple(source.column_for(field_path) for field_path in source.key_fields)
        selection = ", ".join(
            f"{_identifier(column)} AS {_identifier(f'field_{index}')}"
            for index, column in enumerate(columns)
        )
        key_selection = ", ".join(
            f"{_identifier(column)} AS {_identifier(f'key_{index}')}"
            for index, column in enumerate(key_columns)
        )
        ordering = ", ".join(_identifier(column) for column in key_columns)

        connection: asyncpg.Connection[asyncpg.Record] | None = None
        transaction: asyncpg.Transaction | None = None
        password = self._secret_reader.resolve(source.password_secret_ref)
        rows: list[dict[str, str | int | float | bool | None]] = []
        total_bytes = 0
        last_key: tuple[object, ...] | None = None
        try:
            timeout_seconds = _source_timeout_seconds(
                source=source,
                deadline=claim.source_access_deadline,
            )
            async with asyncio.timeout(timeout_seconds):
                connection = await _connect_source(
                    source=source,
                    password=password,
                    application_name="datariver-knowledge-studio-ingestion",
                )
                transaction = connection.transaction(
                    isolation="repeatable_read",
                    readonly=True,
                )
                await transaction.start()
                while True:
                    remaining_rows = maximum_rows - len(rows)
                    fetch_limit = min(source.batch_size, max(1, remaining_rows))
                    query, parameters = _batch_select(
                        source=source,
                        selection=f"{selection}, {key_selection}",
                        ordering=ordering,
                        key_columns=key_columns,
                        last_key=last_key,
                        limit=fetch_limit,
                    )
                    await statement_fence()
                    records = await connection.fetch(query, *parameters)
                    if not records:
                        break
                    if len(records) > fetch_limit:
                        raise ConflictError(
                            "The Studio source returned an oversized batch.",
                            details={"code": "SOURCE_BATCH_LIMIT_EXCEEDED"},
                        )
                    for record in records:
                        if len(rows) >= maximum_rows:
                            raise ConflictError(
                                "The Studio source row budget was exceeded.",
                                details={"code": "SOURCE_ROW_LIMIT_EXCEEDED"},
                            )
                        raw_key = tuple(record[f"key_{index}"] for index in range(len(key_columns)))
                        if any(value is None for value in raw_key) or raw_key == last_key:
                            raise ConflictError(
                                "The Studio source keyset is not a stable unique identity.",
                                details={"code": "SOURCE_KEYSET_INVALID"},
                            )
                        for value in raw_key:
                            _sample_scalar(value)
                        row = {
                            field_path: _sample_scalar(record[f"field_{index}"])
                            for index, field_path in enumerate(field_paths)
                        }
                        row_bytes = _canonical_json_size(row)
                        if total_bytes + row_bytes > maximum_bytes:
                            raise ConflictError(
                                "The Studio source byte budget was exceeded.",
                                details={"code": "SOURCE_BYTE_LIMIT_EXCEEDED"},
                            )
                        rows.append(row)
                        total_bytes += row_bytes
                        last_key = raw_key
                    if len(records) < fetch_limit:
                        break
        except (TimeoutError, asyncpg.PostgresError, OSError) as error:
            raise ExternalDependencyError(
                "The approved Studio PostgreSQL source is temporarily unavailable.",
                dependency="knowledge_studio_postgres_source",
                retryable=True,
                provider_code="PHYSICAL_SOURCE_UNAVAILABLE",
            ) from error
        finally:
            password = ""
            await _close(connection=connection, transaction=transaction)

        row_tuple = tuple(rows)
        receipt = StudioSourceRead(
            binding_pin_id=binding.pin_id,
            rows=row_tuple,
            source_read_receipt_hash=canonical_json_hash(
                {
                    "contract": "STUDIO_DB_SOURCE_READ_V1",
                    "manifest_id": self.manifest_id,
                    "manifest_version": self.manifest_version,
                    "manifest_hash": self.manifest_hash,
                    "job_id": str(claim.job_id),
                    "binding_pin_id": str(binding.pin_id),
                    "binding_version_id": str(binding.binding_version_id),
                    "mapping_hash": binding.mapping_hash,
                    "source_asset_id": str(binding.source_asset_id),
                    "source_version": binding.source_version,
                    "projection_source_version": binding.projection_source_version,
                    "connection_profile_id": binding.connection_profile_id,
                    "connection_profile_version": binding.connection_profile_version,
                    "connection_profile_hash": binding.connection_profile_hash,
                    "field_paths": list(field_paths),
                    "row_count": len(row_tuple),
                    "row_bytes": total_bytes,
                    "rows_hash": canonical_json_hash(row_tuple),
                }
            ),
        )
        receipt.validate()
        return receipt, len(row_tuple), total_bytes


def load_knowledge_studio_source_manifest(
    path: str | Path,
) -> KnowledgeStudioSourceManifest:
    manifest_path = Path(path)
    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source manifest file is invalid."
            )
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source manifest exceeds its size limit."
            )
        payload = manifest_path.read_bytes()
    except KnowledgeStudioSourceManifestError:
        raise
    except OSError as error:
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source manifest is unavailable."
        ) from error
    return parse_knowledge_studio_source_manifest(payload)


def parse_knowledge_studio_source_manifest(
    payload: bytes | str,
) -> KnowledgeStudioSourceManifest:
    if isinstance(payload, bytes):
        if len(payload) > _MAX_MANIFEST_BYTES:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source manifest exceeds its size limit."
            )
        try:
            encoded = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source manifest is not UTF-8."
            ) from error
    else:
        if len(payload.encode("utf-8")) > _MAX_MANIFEST_BYTES:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source manifest exceeds its size limit."
            )
        encoded = payload
    try:
        raw = cast(object, json.loads(encoded, object_pairs_hook=_reject_duplicate_keys))
    except KnowledgeStudioSourceManifestError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source manifest is not valid JSON."
        ) from error
    document = _object(raw, "source manifest")
    _exact_keys(
        document,
        {"contract_version", "manifest_id", "manifest_version", "sources"},
        "source manifest",
    )
    if document["contract_version"] != MANIFEST_CONTRACT_VERSION:
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source manifest contract is unsupported."
        )
    raw_sources = _array(document["sources"], "sources", minimum=1, maximum=_MAX_SOURCES)
    sources = tuple(_parse_source(value) for value in raw_sources)
    identities = {(source.workspace_id, source.asset_id) for source in sources}
    if len(identities) != len(sources):
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source manifest repeats an Asset identity."
        )
    return KnowledgeStudioSourceManifest(
        manifest_id=_pattern_text(document["manifest_id"], _OPAQUE_ID, "manifest ID"),
        manifest_version=_integer(
            document["manifest_version"],
            "manifest version",
            1,
            2_147_483_647,
        ),
        sources=sources,
    )


def build_knowledge_studio_sample_reader(
    *,
    manifest: KnowledgeStudioSourceManifest,
    secret_root: str | Path,
) -> RegistryBackedKnowledgeStudioSampleReader:
    secret_reader = KnowledgeStudioSourceSecretReader(secret_root)
    registered = tuple(
        RegisteredPhysicalSource(
            binding=PhysicalSourceBinding(
                workspace_id=source.workspace_id,
                asset_id=source.asset_id,
                source_version=source.source_version,
                projection_source_version=source.projection_source_version,
                field_paths=frozenset(field for field, _ in source.field_map),
                minimum_clearance=source.minimum_clearance,
                adapter_id=source.adapter_id,
            ),
            adapter=PostgresKnowledgeStudioSourceAdapter(
                source=source,
                secret_reader=secret_reader,
            ),
        )
        for source in manifest.sources
    )
    return RegistryBackedKnowledgeStudioSampleReader(
        StaticKnowledgeStudioConnectionRegistry(registered)
    )


def build_knowledge_studio_batch_source_reader(
    *,
    manifest: KnowledgeStudioSourceManifest,
    secret_root: str | Path,
) -> PostgresKnowledgeStudioBatchSourceReader:
    return PostgresKnowledgeStudioBatchSourceReader(
        manifest=manifest,
        secret_reader=KnowledgeStudioSourceSecretReader(secret_root),
    )


def _parse_source(value: object) -> KnowledgeStudioPostgresSource:
    document = _object(value, "source")
    expected = {
        "workspace_id",
        "asset_id",
        "source_version",
        "projection_source_version",
        "minimum_clearance",
        "connection_profile_id",
        "connection_profile_version",
        "connection_profile_hash",
        "host",
        "allowed_ips",
        "port",
        "database",
        "schema",
        "relation",
        "field_map",
        "key_fields",
        "username",
        "password_secret_ref",
        "tls_mode",
        "statement_timeout_seconds",
        "lock_timeout_seconds",
        "idle_transaction_timeout_seconds",
        "hard_timeout_seconds",
        "batch_size",
        "maximum_rows",
        "maximum_bytes",
    }
    _exact_keys(document, expected, "source")
    raw_field_map = _object(document["field_map"], "field map")
    if not 1 <= len(raw_field_map) <= _MAX_FIELDS:
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source field map is outside its bound."
        )
    field_map = tuple(
        (
            _pattern_text(field, _FIELD_ID, "field path"),
            _pattern_text(column, _IDENTIFIER, "source column"),
        )
        for field, column in raw_field_map.items()
    )
    if len({column for _, column in field_map}) != len(field_map):
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source field map repeats a physical column."
        )
    raw_key_fields = _array(document["key_fields"], "key fields", minimum=1, maximum=8)
    key_fields = tuple(_pattern_text(item, _FIELD_ID, "key field") for item in raw_key_fields)
    known_fields = {field for field, _ in field_map}
    if len(set(key_fields)) != len(key_fields) or not set(key_fields).issubset(known_fields):
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source key fields are invalid."
        )
    host = _ip(document["host"], "host")
    allowed_ips = tuple(
        _ip(item, "allowed IP")
        for item in _array(document["allowed_ips"], "allowed IPs", minimum=1, maximum=32)
    )
    if len(set(allowed_ips)) != len(allowed_ips) or host not in allowed_ips:
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source host is outside its exact IP allowlist."
        )
    tls_mode = _text(document["tls_mode"], "TLS mode", 20)
    if tls_mode not in {"REQUIRE", "VERIFY_CA", "VERIFY_FULL"}:
        raise KnowledgeStudioSourceManifestError("The Knowledge Studio source TLS mode is invalid.")
    source = KnowledgeStudioPostgresSource(
        workspace_id=_uuid(document["workspace_id"], "Workspace"),
        asset_id=_uuid(document["asset_id"], "Asset"),
        source_version=_text(document["source_version"], "source version", 255),
        projection_source_version=_text(
            document["projection_source_version"],
            "projection source version",
            255,
        ),
        minimum_clearance=_integer(document["minimum_clearance"], "minimum clearance", 0, 3),
        connection_profile_id=_pattern_text(
            document["connection_profile_id"],
            _OPAQUE_ID,
            "connection profile ID",
        ),
        connection_profile_version=_integer(
            document["connection_profile_version"],
            "connection profile version",
            1,
            2_147_483_647,
        ),
        connection_profile_hash=_sha256(
            document["connection_profile_hash"],
            "connection profile hash",
        ),
        host=host,
        allowed_ips=allowed_ips,
        port=_integer(document["port"], "port", 1, 65_535),
        database=_pattern_text(document["database"], _IDENTIFIER, "database"),
        schema=_pattern_text(document["schema"], _IDENTIFIER, "schema"),
        relation=_pattern_text(document["relation"], _IDENTIFIER, "relation"),
        field_map=field_map,
        key_fields=key_fields,
        username=_pattern_text(document["username"], _IDENTIFIER, "username"),
        password_secret_ref=_secret_reference(document["password_secret_ref"]),
        tls_mode=tls_mode,
        statement_timeout_seconds=_integer(
            document["statement_timeout_seconds"],
            "statement timeout",
            1,
            3_600,
        ),
        lock_timeout_seconds=_integer(
            document["lock_timeout_seconds"],
            "lock timeout",
            1,
            3_600,
        ),
        idle_transaction_timeout_seconds=_integer(
            document["idle_transaction_timeout_seconds"],
            "idle transaction timeout",
            1,
            3_600,
        ),
        hard_timeout_seconds=_integer(
            document["hard_timeout_seconds"],
            "hard timeout",
            1,
            86_400,
        ),
        batch_size=_integer(document["batch_size"], "batch size", 10, 5_000),
        maximum_rows=_integer(document["maximum_rows"], "maximum rows", 1, 10_000_000),
        maximum_bytes=_integer(
            document["maximum_bytes"],
            "maximum bytes",
            1_024,
            1_099_511_627_776,
        ),
    )
    if (
        source.lock_timeout_seconds > source.statement_timeout_seconds
        or source.idle_transaction_timeout_seconds > source.hard_timeout_seconds
        or source.statement_timeout_seconds > source.hard_timeout_seconds
    ):
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source timeout profile is inconsistent."
        )
    if canonical_json_hash(source.configuration_document()) != source.connection_profile_hash:
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source connection profile hash does not match its content."
        )
    return source


async def _close(
    *,
    connection: asyncpg.Connection[asyncpg.Record] | None,
    transaction: asyncpg.Transaction | None,
) -> None:
    if transaction is not None:
        with suppress(BaseException):
            await asyncio.shield(transaction.rollback())
    if connection is not None:
        with suppress(BaseException):
            await asyncio.shield(connection.close(timeout=5))


async def _connect_source(
    *,
    source: KnowledgeStudioPostgresSource,
    password: str,
    application_name: str,
) -> asyncpg.Connection[asyncpg.Record]:
    address = str(ipaddress.ip_address(source.host))
    if address not in source.allowed_ips:
        raise ConflictError("The physical source address is outside its exact allowlist.")
    return await asyncpg.connect(
        host=address,
        port=source.port,
        user=source.username,
        password=password,
        database=source.database,
        ssl=_ssl_context(source.tls_mode),
        timeout=min(30, source.hard_timeout_seconds),
        command_timeout=source.statement_timeout_seconds,
        statement_cache_size=0,
        server_settings={
            "application_name": application_name,
            "statement_timeout": f"{source.statement_timeout_seconds * 1000}",
            "lock_timeout": f"{source.lock_timeout_seconds * 1000}",
            "idle_in_transaction_session_timeout": (
                f"{source.idle_transaction_timeout_seconds * 1000}"
            ),
            "default_transaction_read_only": "on",
        },
    )


def _source_timeout_seconds(
    *,
    source: KnowledgeStudioPostgresSource,
    deadline: datetime | None,
) -> float:
    if deadline is None or deadline.tzinfo is None or deadline.utcoffset() is None:
        raise ConflictError(
            "The Studio source-access deadline is invalid.",
            details={"code": "SOURCE_ACCESS_NOT_FROZEN", "stale": True},
        )
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise ConflictError(
            "The Studio source-access deadline has expired.",
            details={"code": "SOURCE_ACCESS_DEADLINE_EXPIRED", "stale": True},
        )
    return min(float(source.hard_timeout_seconds), remaining)


def _batch_select(
    *,
    source: KnowledgeStudioPostgresSource,
    selection: str,
    ordering: str,
    key_columns: tuple[str, ...],
    last_key: tuple[object, ...] | None,
    limit: int,
) -> tuple[str, tuple[object, ...]]:
    if not 1 <= limit <= source.batch_size:
        raise ValidationError("The Studio source batch limit is invalid.")
    if last_key is None:
        return (
            f"SELECT {selection} "
            f"FROM {_qualified(source.schema, source.relation)} "
            f"ORDER BY {ordering} LIMIT $1",
            (limit,),
        )
    if len(last_key) != len(key_columns):
        raise ValidationError("The Studio source keyset shape is invalid.")
    if len(key_columns) == 1:
        predicate = f"{_identifier(key_columns[0])} > $1"
    else:
        columns = ", ".join(_identifier(column) for column in key_columns)
        parameters = ", ".join(f"${index}" for index in range(1, len(key_columns) + 1))
        predicate = f"({columns}) > ({parameters})"
    limit_parameter = len(last_key) + 1
    return (
        f"SELECT {selection} "
        f"FROM {_qualified(source.schema, source.relation)} "
        f"WHERE {predicate} ORDER BY {ordering} LIMIT ${limit_parameter}",
        (*last_key, limit),
    )


def _canonical_json_size(value: Mapping[str, object]) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    )


def _sample_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConflictError("The physical source returned a non-finite number.")
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConflictError("The physical source returned a timezone-ambiguous timestamp.")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise ConflictError("The physical source returned an unsupported scalar value.")


def _ssl_context(mode: str) -> ssl.SSLContext:
    if mode == "REQUIRE":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    context = ssl.create_default_context()
    context.check_hostname = mode == "VERIFY_FULL"
    return context


def _identifier(value: str) -> str:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValidationError("The server-owned PostgreSQL identifier is invalid.")
    return '"' + value.replace('"', '""') + '"'


def _qualified(schema: str, relation: str) -> str:
    return f"{_identifier(schema)}.{_identifier(relation)}"


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise KnowledgeStudioSourceManifestError(
                "The Knowledge Studio source manifest repeats a JSON field."
            )
        value[key] = item
    return value


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise KnowledgeStudioSourceManifestError(f"The {label} must be a JSON object.")
    return cast(dict[str, object], value)


def _array(
    value: object,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> list[object]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise KnowledgeStudioSourceManifestError(f"The {label} array is outside its bound.")
    return cast(list[object], value)


def _exact_keys(document: dict[str, object], expected: set[str], label: str) -> None:
    if set(document) != expected:
        raise KnowledgeStudioSourceManifestError(f"The {label} fields do not match the contract.")


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise KnowledgeStudioSourceManifestError(f"The {label} is invalid.")
    normalized = value.strip()
    if not 1 <= len(normalized) <= maximum or normalized != value:
        raise KnowledgeStudioSourceManifestError(f"The {label} is invalid.")
    return normalized


def _pattern_text(value: object, pattern: re.Pattern[str], label: str) -> str:
    normalized = _text(value, label, 255)
    if pattern.fullmatch(normalized) is None:
        raise KnowledgeStudioSourceManifestError(f"The {label} is invalid.")
    return normalized


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise KnowledgeStudioSourceManifestError(f"The {label} is invalid.")
    return value


def _uuid(value: object, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise KnowledgeStudioSourceManifestError(f"The {label} ID is invalid.") from error


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise KnowledgeStudioSourceManifestError(f"The {label} is invalid.")
    return value


def _ip(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise KnowledgeStudioSourceManifestError(f"The {label} is invalid.")
    try:
        normalized = str(ipaddress.ip_address(value))
    except ValueError as error:
        raise KnowledgeStudioSourceManifestError(f"The {label} is invalid.") from error
    if normalized != value:
        raise KnowledgeStudioSourceManifestError(f"The {label} is not canonical.")
    return normalized


def _secret_reference(value: object) -> str:
    if not isinstance(value, str) or _SECRET_REFERENCE.fullmatch(value) is None:
        raise KnowledgeStudioSourceManifestError(
            "The Knowledge Studio source password requires one mounted file secret."
        )
    return value
