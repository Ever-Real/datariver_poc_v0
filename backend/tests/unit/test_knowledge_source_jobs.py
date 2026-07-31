from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_source_jobs import (
    KnowledgeSourceJobPins,
    KnowledgeSourceJobState,
    require_knowledge_source_transition,
)
from datariver.infrastructure.db.knowledge_source_jobs import _activated_binding_is_current


def _binding(model: str, configuration_hash: str) -> ModelBinding:
    return ModelBinding(
        provider="ollama-openai-compatible",
        model=model,
        prompt_version="knowledge-pdf-extraction-v1",
        tool_schema_version="knowledge-extraction-schema-v1",
        configuration_source="DEPLOYMENT",
        configuration_version=None,
        configuration_hash=configuration_hash,
    )


def _pins() -> KnowledgeSourceJobPins:
    return KnowledgeSourceJobPins(
        workspace_id=uuid4(),
        graph_id=uuid4(),
        source_snapshot_id=uuid4(),
        upload_id=uuid4(),
        source_storage_version="manifest-v7",
        source_content_sha256="a" * 64,
        source_classification=1,
        source_content_profile="FORMAT_ONLY_V1",
        source_validation_evidence_hash="9" * 64,
        graph_version=5,
        base_release_id=uuid4(),
        base_release_hash="b" * 64,
        ontology_version_id=uuid4(),
        ontology_checksum="c" * 64,
        parser_configuration_hash="d" * 64,
        embedding_binding=_binding("bge-m3:latest", "e" * 64),
        extraction_binding=_binding("gemma4:latest", "f" * 64),
        prepared_at=datetime(2026, 7, 24, 1, 2, tzinfo=UTC),
    )


class _ProfileResult:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def one_or_none(self) -> object | None:
        return self._row


class _ProfileSession:
    def __init__(self, row: object | None) -> None:
        self._row = row

    async def execute(self, _statement: object) -> _ProfileResult:
        return _ProfileResult(self._row)


@pytest.mark.asyncio
async def test_database_model_binding_requires_the_exact_active_available_profile() -> None:
    historical = replace(
        _binding("historical-model", "a" * 64),
        configuration_source="SYSTEM_CONFIGURATION",
        configuration_version=3,
    )

    assert (
        await _activated_binding_is_current(
            cast(AsyncSession, _ProfileSession(object())),
            workspace_id=uuid4(),
            service_key="LLM_CHAT_MODEL",
            binding=historical,
        )
        is True
    )
    assert (
        await _activated_binding_is_current(
            cast(AsyncSession, _ProfileSession(None)),
            workspace_id=uuid4(),
            service_key="LLM_CHAT_MODEL",
            binding=historical,
        )
        is False
    )


def test_knowledge_source_job_pin_hash_binds_every_preparation_dimension() -> None:
    pins = _pins()
    baseline = pins.evidence_hash()

    assert baseline != replace(pins, graph_version=pins.graph_version + 1).evidence_hash()
    assert baseline != replace(pins, base_release_hash="0" * 64).evidence_hash()
    assert baseline != replace(pins, ontology_checksum="1" * 64).evidence_hash()
    assert (
        baseline
        != replace(
            pins,
            extraction_binding=replace(
                pins.extraction_binding,
                configuration_hash="2" * 64,
            ),
        ).evidence_hash()
    )


def test_pin_hash_preserves_legacy_v1_and_binds_new_validation_evidence_in_v2() -> None:
    legacy = _pins()
    legacy_hash = legacy.evidence_hash()

    assert legacy.to_document()["contract"] == "KNOWLEDGE_SOURCE_JOB_PINS_V1"
    assert replace(legacy, source_validation_evidence_hash="8" * 64).evidence_hash() == legacy_hash

    governed = replace(
        legacy,
        source_content_profile="KNOWLEDGE_SOURCE_DOCUMENT_V1",
    )
    assert governed.to_document()["contract"] == "KNOWLEDGE_SOURCE_JOB_PINS_V2"
    assert (
        governed.evidence_hash()
        != replace(
            governed,
            source_validation_evidence_hash="8" * 64,
        ).evidence_hash()
    )


def test_empty_base_is_explicit_and_cannot_carry_a_release_hash() -> None:
    pins = _pins()
    empty = replace(pins, base_release_id=None, base_release_hash=None)

    assert empty.to_document()["base"] == {"kind": "EMPTY"}

    with pytest.raises(ValidationError, match="base release binding"):
        replace(pins, base_release_id=None).validate()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (KnowledgeSourceJobState.QUEUED, KnowledgeSourceJobState.RUNNING),
        (KnowledgeSourceJobState.QUEUED, KnowledgeSourceJobState.CANCELLED),
        (KnowledgeSourceJobState.RUNNING, KnowledgeSourceJobState.RETRY_WAIT),
        (KnowledgeSourceJobState.RUNNING, KnowledgeSourceJobState.CANCEL_REQUESTED),
        (KnowledgeSourceJobState.RUNNING, KnowledgeSourceJobState.SUCCEEDED),
        (KnowledgeSourceJobState.RUNNING, KnowledgeSourceJobState.STALE),
        (KnowledgeSourceJobState.RETRY_WAIT, KnowledgeSourceJobState.RUNNING),
        (KnowledgeSourceJobState.RETRY_WAIT, KnowledgeSourceJobState.CANCELLED),
        (KnowledgeSourceJobState.CANCEL_REQUESTED, KnowledgeSourceJobState.CANCELLED),
    ],
)
def test_knowledge_source_job_state_machine_accepts_declared_transitions(
    current: KnowledgeSourceJobState,
    target: KnowledgeSourceJobState,
) -> None:
    require_knowledge_source_transition(current=current, target=target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (KnowledgeSourceJobState.QUEUED, KnowledgeSourceJobState.SUCCEEDED),
        (KnowledgeSourceJobState.RETRY_WAIT, KnowledgeSourceJobState.SUCCEEDED),
        (KnowledgeSourceJobState.CANCEL_REQUESTED, KnowledgeSourceJobState.SUCCEEDED),
        (KnowledgeSourceJobState.SUCCEEDED, KnowledgeSourceJobState.CANCELLED),
        (KnowledgeSourceJobState.STALE, KnowledgeSourceJobState.RUNNING),
        (KnowledgeSourceJobState.FAILED, KnowledgeSourceJobState.QUEUED),
    ],
)
def test_knowledge_source_job_state_machine_rejects_unsafe_transitions(
    current: KnowledgeSourceJobState,
    target: KnowledgeSourceJobState,
) -> None:
    with pytest.raises(ValidationError, match="transition"):
        require_knowledge_source_transition(current=current, target=target)
