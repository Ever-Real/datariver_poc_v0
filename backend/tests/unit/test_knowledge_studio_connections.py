from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from datariver.application.dto import KnowledgeStudioSampleRequest
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError
from datariver.infrastructure.knowledge_studio.connections import (
    CsvConnectionAdapterShell,
    KnowledgeStudioPhysicalSourceAdapter,
    PhysicalProbeReceipt,
    PhysicalSampleReceipt,
    PhysicalSourceBinding,
    RegisteredPhysicalSource,
    RegistryBackedKnowledgeStudioSampleReader,
    SqliteConnectionAdapterShell,
    StaticKnowledgeStudioConnectionRegistry,
)

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
ASSET_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2")
SOURCE_REFERENCE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b4")
NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


class StaticRowsAdapter:
    adapter_id = "static-test-v1"

    async def sample_rows(self, **_: object) -> PhysicalSampleReceipt:
        return PhysicalSampleReceipt(
            source_version="source-v1",
            projection_source_version="projection-v3",
            rows=({"emp_id": 7, "emp_nm": "Kim"},),
            observed_at=NOW,
        )

    async def probe_access(self, **_: object) -> PhysicalProbeReceipt:
        return PhysicalProbeReceipt(
            source_version="source-v1",
            projection_source_version="projection-v3",
            accessible=True,
            observed_at=NOW,
        )


def _subject() -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.CONFIDENTIAL,
        allowed_actions=frozenset({Action.KG_READ, Action.KG_REVIEW}),
    )


def _request(
    *,
    source_version: str = "source-v1",
    field_paths: tuple[str, ...] = ("emp_id", "emp_nm"),
) -> KnowledgeStudioSampleRequest:
    return KnowledgeStudioSampleRequest(
        source_reference_id=SOURCE_REFERENCE_ID,
        asset_id=ASSET_ID,
        source_version=source_version,
        projection_source_version="projection-v3",
        field_paths=field_paths,
        limit=5,
    )


def _registry(
    adapter: KnowledgeStudioPhysicalSourceAdapter | None = None,
) -> StaticKnowledgeStudioConnectionRegistry:
    selected = adapter or StaticRowsAdapter()
    return StaticKnowledgeStudioConnectionRegistry(
        (
            RegisteredPhysicalSource(
                binding=PhysicalSourceBinding(
                    workspace_id=WORKSPACE_ID,
                    asset_id=ASSET_ID,
                    source_version="source-v1",
                    projection_source_version="projection-v3",
                    field_paths=frozenset({"emp_id", "emp_nm"}),
                    minimum_clearance=int(Classification.INTERNAL),
                    adapter_id=selected.adapter_id,
                ),
                adapter=selected,
            ),
        )
    )


@pytest.mark.asyncio
async def test_registry_reader_returns_only_exact_bounded_typed_rows() -> None:
    reader = RegistryBackedKnowledgeStudioSampleReader(_registry())

    result = await reader.sample_rows(
        subject=_subject(),
        source=_request(),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert result.source_reference_id == SOURCE_REFERENCE_ID
    assert result.source_version == "source-v1"
    assert result.projection_source_version == "projection-v3"
    assert result.rows == ({"emp_id": 7, "emp_nm": "Kim"},)
    assert result.observed_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sample_request", "message"),
    [
        (_request(source_version="source-v2"), "version is no longer exact"),
        (_request(field_paths=("password_hash",)), "outside the physical source allowlist"),
    ],
)
async def test_registry_reader_fails_closed_on_contract_drift(
    sample_request: KnowledgeStudioSampleRequest,
    message: str,
) -> None:
    reader = RegistryBackedKnowledgeStudioSampleReader(_registry())

    with pytest.raises(ConflictError, match=message):
        await reader.sample_rows(
            subject=_subject(),
            source=sample_request,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )


@pytest.mark.asyncio
async def test_probe_marks_an_unregistered_source_inaccessible_without_fabricating_rows() -> None:
    reader = RegistryBackedKnowledgeStudioSampleReader(StaticKnowledgeStudioConnectionRegistry())

    probes = await reader.probe_access(
        subject=_subject(),
        sources=(_request(),),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request",
    )

    assert len(probes) == 1
    assert probes[0].accessible is False
    assert probes[0].source_version == "source-v1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter",
    [CsvConnectionAdapterShell(), SqliteConnectionAdapterShell()],
)
async def test_connection_shells_remain_explicitly_unavailable(
    adapter: KnowledgeStudioPhysicalSourceAdapter,
) -> None:
    reader = RegistryBackedKnowledgeStudioSampleReader(_registry(adapter))

    with pytest.raises(ConflictError, match="no approved"):
        await reader.sample_rows(
            subject=_subject(),
            source=_request(),
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request",
        )


def test_registry_rejects_duplicate_asset_bindings() -> None:
    source = _registry().resolve(workspace_id=WORKSPACE_ID, asset_id=ASSET_ID)
    assert source is not None
    with pytest.raises(ValueError, match="registered twice"):
        StaticKnowledgeStudioConnectionRegistry((source, source))
