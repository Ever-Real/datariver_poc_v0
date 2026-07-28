from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.application.dto import (
    KnowledgeStudioSamplePage,
    KnowledgeStudioSampleRequest,
    KnowledgeStudioSampleScalar,
    KnowledgeStudioSourceProbe,
)
from datariver.domain.authz import EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ConflictError, utc_now


@dataclass(frozen=True, slots=True)
class PhysicalSourceBinding:
    """Operator-registered, exact physical source contract.

    The binding contains no query text or credential. A concrete adapter owns those
    implementation details outside browser-controlled input.
    """

    workspace_id: UUID
    asset_id: UUID
    source_version: str
    projection_source_version: str
    field_paths: frozenset[str]
    minimum_clearance: int
    adapter_id: str


@dataclass(frozen=True, slots=True)
class PhysicalSampleReceipt:
    source_version: str
    projection_source_version: str
    rows: tuple[Mapping[str, KnowledgeStudioSampleScalar], ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PhysicalProbeReceipt:
    source_version: str
    projection_source_version: str
    accessible: bool
    observed_at: datetime


class KnowledgeStudioPhysicalSourceAdapter(Protocol):
    adapter_id: str

    async def sample_rows(
        self,
        *,
        binding: PhysicalSourceBinding,
        field_paths: tuple[str, ...],
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> PhysicalSampleReceipt: ...

    async def probe_access(
        self,
        *,
        binding: PhysicalSourceBinding,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> PhysicalProbeReceipt: ...


@dataclass(frozen=True, slots=True)
class RegisteredPhysicalSource:
    binding: PhysicalSourceBinding
    adapter: KnowledgeStudioPhysicalSourceAdapter


class StaticKnowledgeStudioConnectionRegistry:
    """Immutable process-local registry assembled only by trusted bootstrap code."""

    def __init__(self, sources: tuple[RegisteredPhysicalSource, ...] = ()) -> None:
        registered: dict[tuple[UUID, UUID], RegisteredPhysicalSource] = {}
        for source in sources:
            key = (source.binding.workspace_id, source.binding.asset_id)
            if key in registered:
                raise ValueError("A physical Knowledge Studio source is registered twice.")
            if source.binding.adapter_id != source.adapter.adapter_id:
                raise ValueError("The physical source adapter identity does not match its binding.")
            if not 0 <= source.binding.minimum_clearance <= 3:
                raise ValueError("A physical source binding has an invalid clearance.")
            if not source.binding.field_paths:
                raise ValueError("A physical source binding requires an explicit field allowlist.")
            if (
                not source.binding.source_version
                or len(source.binding.source_version) > 255
                or not source.binding.projection_source_version
                or len(source.binding.projection_source_version) > 255
            ):
                raise ValueError("A physical source binding has an invalid source version.")
            registered[key] = source
        self._sources = registered

    def resolve(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> RegisteredPhysicalSource | None:
        return self._sources.get((workspace_id, asset_id))


class RegistryBackedKnowledgeStudioSampleReader:
    """Application-port adapter that fences every physical read with exact source metadata."""

    def __init__(self, registry: StaticKnowledgeStudioConnectionRegistry) -> None:
        self._registry = registry

    async def sample_rows(
        self,
        *,
        subject: SubjectAttributes,
        source: KnowledgeStudioSampleRequest,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioSamplePage:
        registered = self._require_binding(subject=subject, source=source)
        receipt = await registered.adapter.sample_rows(
            binding=registered.binding,
            field_paths=source.field_paths,
            limit=source.limit,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        self._validate_receipt(
            source=source,
            source_version=receipt.source_version,
            projection_source_version=receipt.projection_source_version,
        )
        if len(receipt.rows) > source.limit:
            raise ConflictError("The physical source adapter exceeded the requested row bound.")
        rows = tuple(
            self._validated_row(
                row=row,
                allowed_fields=frozenset(source.field_paths),
            )
            for row in receipt.rows
        )
        observed_at = receipt.observed_at
        if observed_at.tzinfo is None:
            raise ConflictError("The physical source adapter returned an invalid observation time.")
        return KnowledgeStudioSamplePage(
            source_reference_id=source.source_reference_id,
            source_version=receipt.source_version,
            projection_source_version=receipt.projection_source_version,
            rows=rows,
            observed_at=observed_at,
        )

    async def probe_access(
        self,
        *,
        subject: SubjectAttributes,
        sources: tuple[KnowledgeStudioSampleRequest, ...],
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioSourceProbe, ...]:
        unique: dict[UUID, KnowledgeStudioSampleRequest] = {}
        for source in sources:
            previous = unique.get(source.source_reference_id)
            if previous is not None and previous != source:
                raise ConflictError("A source reference has conflicting physical contracts.")
            unique[source.source_reference_id] = source
        probes: list[KnowledgeStudioSourceProbe] = []
        for source in unique.values():
            try:
                registered = self._require_binding(subject=subject, source=source)
            except ConflictError:
                probes.append(
                    KnowledgeStudioSourceProbe(
                        source_reference_id=source.source_reference_id,
                        source_version=source.source_version,
                        projection_source_version=source.projection_source_version,
                        accessible=False,
                        observed_at=utc_now(),
                    )
                )
                continue
            receipt = await registered.adapter.probe_access(
                binding=registered.binding,
                subject=subject,
                environment=environment,
                request_id=request_id,
            )
            exact_contract = (
                receipt.source_version == source.source_version
                and receipt.projection_source_version == source.projection_source_version
            )
            observed_at = receipt.observed_at
            if observed_at.tzinfo is None:
                raise ConflictError(
                    "The physical source adapter returned an invalid observation time."
                )
            probes.append(
                KnowledgeStudioSourceProbe(
                    source_reference_id=source.source_reference_id,
                    source_version=receipt.source_version,
                    projection_source_version=receipt.projection_source_version,
                    accessible=receipt.accessible and exact_contract,
                    observed_at=observed_at,
                )
            )
        return tuple(probes)

    def _require_binding(
        self,
        *,
        subject: SubjectAttributes,
        source: KnowledgeStudioSampleRequest,
    ) -> RegisteredPhysicalSource:
        if not subject.active:
            raise ConflictError("An inactive subject cannot access physical source rows.")
        if not 5 <= source.limit <= 10:
            raise ConflictError("Physical source samples are bounded to 5 through 10 rows.")
        if not source.field_paths or len(source.field_paths) > 200:
            raise ConflictError("Physical source fields must use a bounded explicit allowlist.")
        registered = self._registry.resolve(
            workspace_id=subject.workspace_id,
            asset_id=source.asset_id,
        )
        if registered is None:
            raise ConflictError("No approved physical source binding is registered.")
        binding = registered.binding
        self._validate_receipt(
            source=source,
            source_version=binding.source_version,
            projection_source_version=binding.projection_source_version,
        )
        if subject.clearance < binding.minimum_clearance:
            raise ConflictError("The subject clearance is below the physical source contract.")
        if not set(source.field_paths).issubset(binding.field_paths):
            raise ConflictError("A requested field is outside the physical source allowlist.")
        return registered

    @staticmethod
    def _validate_receipt(
        *,
        source: KnowledgeStudioSampleRequest,
        source_version: str,
        projection_source_version: str,
    ) -> None:
        if (
            source.source_version != source_version
            or source.projection_source_version != projection_source_version
        ):
            raise ConflictError("The physical source contract version is no longer exact.")

    @staticmethod
    def _validated_row(
        *,
        row: Mapping[str, KnowledgeStudioSampleScalar],
        allowed_fields: frozenset[str],
    ) -> Mapping[str, KnowledgeStudioSampleScalar]:
        if not set(row).issubset(allowed_fields):
            raise ConflictError("The physical source adapter returned an unrequested field.")
        validated: dict[str, KnowledgeStudioSampleScalar] = {}
        for key, value in row.items():
            if not isinstance(key, str) or not key:
                raise ConflictError("The physical source adapter returned an invalid field name.")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ConflictError("The physical source adapter returned an unsupported value.")
            if isinstance(value, float) and not math.isfinite(value):
                raise ConflictError("The physical source adapter returned a non-finite number.")
            validated[key] = value
        return validated


class CsvConnectionAdapterShell:
    """Explicitly unavailable CSV adapter until an operator binds an approved file manifest."""

    adapter_id = "csv-shell-v1"

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
        del binding, field_paths, limit, subject, environment, request_id
        raise ConflictError("The CSV adapter shell has no approved file manifest.")

    async def probe_access(
        self,
        *,
        binding: PhysicalSourceBinding,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> PhysicalProbeReceipt:
        del binding, subject, environment, request_id
        raise ConflictError("The CSV adapter shell has no approved file manifest.")


class SqliteConnectionAdapterShell:
    """Explicitly unavailable SQLite adapter; no browser-supplied SQL is accepted."""

    adapter_id = "sqlite-shell-v1"

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
        del binding, field_paths, limit, subject, environment, request_id
        raise ConflictError("The SQLite adapter shell has no approved connection manifest.")

    async def probe_access(
        self,
        *,
        binding: PhysicalSourceBinding,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> PhysicalProbeReceipt:
        del binding, subject, environment, request_id
        raise ConflictError("The SQLite adapter shell has no approved connection manifest.")
