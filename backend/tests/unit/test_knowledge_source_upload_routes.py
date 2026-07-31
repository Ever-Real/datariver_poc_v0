from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Response

from datariver.application.dto import KnowledgeGraphRecord
from datariver.application.services.registration import UploadAuthorizationPolicy
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError, ValidationError, utc_now
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.registration import UploadContentProfile, UploadManifest, UploadState
from datariver.interfaces.http.routes import knowledge
from datariver.interfaces.http.schemas import (
    CompletedPartRequest,
    KnowledgeSourceAnalyzeRequest,
    KnowledgeSourceUploadInitiateRequest,
    UploadCompleteRequest,
    UploadPartRequest,
    UploadResponse,
)


def _subject(workspace_id: UUID, *, can_edit: bool = True) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.KG_EDIT, Action.KG_READ} if can_edit else set()),
    )


def _context(subject: SubjectAttributes) -> Any:
    return SimpleNamespace(
        workspace_id=subject.workspace_id,
        subject=subject,
        environment=EnvironmentAttributes(requested_at=utc_now()),
        request_id="knowledge-source-route-test",
    )


def _graph(
    workspace_id: UUID,
    graph_id: UUID,
    *,
    classification: Classification = Classification.INTERNAL,
) -> KnowledgeGraphRecord:
    return KnowledgeGraphRecord(
        graph_id=graph_id,
        workspace_id=workspace_id,
        slug=f"graph-{graph_id}",
        name="Knowledge graph",
        graph_type="DOMAIN",
        status="DRAFT",
        classification=classification,
        active_release_id=None,
        version=1,
    )


def _manifest(
    *,
    subject: SubjectAttributes,
    graph_id: UUID,
    profile: UploadContentProfile = UploadContentProfile.KNOWLEDGE_SOURCE_DOCUMENT_V1,
) -> UploadManifest:
    return UploadManifest(
        upload_id=uuid4(),
        workspace_id=subject.workspace_id,
        owner_id=subject.subject_id,
        bucket="quarantine",
        object_key=f"quarantine/{uuid4()}",
        display_name="source.pdf",
        declared_size_bytes=23,
        declared_mime="application/pdf",
        declared_sha256="a" * 64,
        classification=Classification.INTERNAL,
        multipart_upload_id="multipart",
        expires_at=utc_now() + timedelta(hours=1),
        content_profile=profile,
        knowledge_source_graph_id=graph_id,
    )


class _GraphService:
    def __init__(self, graph: KnowledgeGraphRecord, *, deny: bool = False) -> None:
        self.graph = graph
        self.deny = deny
        self.authorize_calls = 0

    async def get_graph(self, *, graph_id: UUID, **_: object) -> KnowledgeGraphRecord | None:
        return self.graph if graph_id == self.graph.graph_id else None

    async def authorize_source_analysis(self, **_: object) -> None:
        self.authorize_calls += 1
        if self.deny:
            raise ForbiddenError("kg.edit is required")


class _UploadService:
    def __init__(self, manifest: UploadManifest) -> None:
        self.manifest = manifest
        self.initiate_values: dict[str, object] | None = None
        self.part_calls = 0
        self.complete_calls = 0
        self._completion_request_hash: str | None = None

    async def initiate(self, **values: object) -> UploadManifest:
        self.initiate_values = values
        return self.manifest

    async def get_manifest(self, **_: object) -> UploadManifest:
        return self.manifest

    async def presign_part(self, **_: object) -> tuple[str, int]:
        self.part_calls += 1
        return "https://object.invalid/part", 300

    async def queue_completion(self, **values: object) -> UploadManifest:
        self.complete_calls += 1
        request_hash = cast(str, values["request_hash"])
        if self._completion_request_hash is None:
            self._completion_request_hash = request_hash
            self.manifest.queue_completion(
                parts=cast(list[Any], values["parts"]),
                expected_version=cast(int, values["expected_version"]),
            )
        elif request_hash != self._completion_request_hash:
            raise AssertionError("route replay changed the canonical request hash")
        return self.manifest


@pytest.mark.asyncio
async def test_initiate_selects_graph_classification_profile_and_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, graph_id = uuid4(), uuid4()
    subject = _subject(workspace_id)
    graph_service = _GraphService(_graph(workspace_id, graph_id))
    upload_service = _UploadService(_manifest(subject=subject, graph_id=graph_id))
    monkeypatch.setattr(knowledge, "_service", lambda *_: graph_service)
    monkeypatch.setattr(knowledge, "_source_upload_service", lambda _: upload_service)
    response = Response()

    result = await knowledge.initiate_knowledge_source_upload(
        graph_id=graph_id,
        payload=KnowledgeSourceUploadInitiateRequest(
            display_name="source.pdf",
            size_bytes=23,
            content_type="application/pdf",
            sha256="a" * 64,
        ),
        request=cast(Any, object()),
        response=response,
        context=_context(subject),
        session=cast(Any, object()),
        idempotency_key="knowledge-source-initiate-1",
    )

    assert isinstance(result, UploadResponse)
    assert result.id == upload_service.manifest.upload_id
    assert upload_service.initiate_values is not None
    assert upload_service.initiate_values["classification"] is Classification.INTERNAL
    assert (
        upload_service.initiate_values["content_profile"]
        is UploadContentProfile.KNOWLEDGE_SOURCE_DOCUMENT_V1
    )
    assert upload_service.initiate_values["knowledge_source_graph_id"] == graph_id
    assert (
        upload_service.initiate_values["authorization_policy"]
        is UploadAuthorizationPolicy.KNOWLEDGE_SOURCE
    )
    assert response.headers["ETag"] == '"1"'
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.asyncio
async def test_upload_denies_missing_kg_edit_before_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, graph_id = uuid4(), uuid4()
    subject = _subject(workspace_id, can_edit=False)
    graph_service = _GraphService(_graph(workspace_id, graph_id), deny=True)
    upload_service = _UploadService(_manifest(subject=subject, graph_id=graph_id))
    monkeypatch.setattr(knowledge, "_service", lambda *_: graph_service)
    monkeypatch.setattr(knowledge, "_source_upload_service", lambda _: upload_service)

    with pytest.raises(ForbiddenError, match=r"kg\.edit"):
        await knowledge.initiate_knowledge_source_upload(
            graph_id=graph_id,
            payload=KnowledgeSourceUploadInitiateRequest(
                display_name="source.pdf",
                size_bytes=23,
                content_type="application/pdf",
                sha256="a" * 64,
            ),
            request=cast(Any, object()),
            response=Response(),
            context=_context(subject),
            session=cast(Any, object()),
            idempotency_key="knowledge-source-denied-1",
        )
    assert upload_service.initiate_values is None


@pytest.mark.asyncio
async def test_confidential_graph_denies_upload_and_analysis_before_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, graph_id = uuid4(), uuid4()
    subject = _subject(workspace_id)
    graph_service = _GraphService(
        _graph(workspace_id, graph_id, classification=Classification.CONFIDENTIAL)
    )
    upload_service = _UploadService(_manifest(subject=subject, graph_id=graph_id))
    monkeypatch.setattr(knowledge, "_service", lambda *_: graph_service)
    monkeypatch.setattr(knowledge, "_source_upload_service", lambda _: upload_service)

    with pytest.raises(ValidationError) as upload_error:
        await knowledge.initiate_knowledge_source_upload(
            graph_id=graph_id,
            payload=KnowledgeSourceUploadInitiateRequest(
                display_name="source.pdf",
                size_bytes=23,
                content_type="application/pdf",
                sha256="a" * 64,
            ),
            request=cast(Any, object()),
            response=Response(),
            context=_context(subject),
            session=cast(Any, object()),
            idempotency_key="knowledge-source-confidential-upload",
        )
    with pytest.raises(ValidationError) as analysis_error:
        await knowledge.analyze_knowledge_document_source(
            graph_id=graph_id,
            upload_id=upload_service.manifest.upload_id,
            payload=KnowledgeSourceAnalyzeRequest(title="Analyze source"),
            request=cast(Any, object()),
            context=_context(subject),
            session=cast(Any, object()),
            idempotency_key="knowledge-source-confidential-analysis",
        )
    assert upload_error.value.details["code"] == "KNOWLEDGE_SOURCE_CLASSIFICATION_NOT_SUPPORTED"
    assert analysis_error.value.details["code"] == "KNOWLEDGE_SOURCE_CLASSIFICATION_NOT_SUPPORTED"
    assert upload_service.initiate_values is None


@pytest.mark.asyncio
async def test_other_graph_binding_denies_read_part_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, source_graph_id, path_graph_id = uuid4(), uuid4(), uuid4()
    subject = _subject(workspace_id)
    graph_service = _GraphService(_graph(workspace_id, path_graph_id))
    upload_service = _UploadService(_manifest(subject=subject, graph_id=source_graph_id))
    monkeypatch.setattr(knowledge, "_service", lambda *_: graph_service)
    monkeypatch.setattr(knowledge, "_source_upload_service", lambda _: upload_service)
    request = cast(Any, object())
    context = _context(subject)
    session = cast(Any, object())

    with pytest.raises(ValidationError) as read_error:
        await knowledge.get_knowledge_source_upload(
            path_graph_id,
            upload_service.manifest.upload_id,
            request,
            Response(),
            context,
            session,
        )
    with pytest.raises(ValidationError):
        await knowledge.presign_knowledge_source_upload_part(
            path_graph_id,
            upload_service.manifest.upload_id,
            UploadPartRequest(part_number=1),
            request,
            context,
            session,
        )
    with pytest.raises(ValidationError):
        await knowledge.complete_knowledge_source_upload(
            path_graph_id,
            upload_service.manifest.upload_id,
            UploadCompleteRequest(parts=[CompletedPartRequest(part_number=1, etag="etag")]),
            request,
            Response(),
            context,
            session,
            '"1"',
            "knowledge-source-cross-graph",
        )
    assert read_error.value.details["code"] == "KNOWLEDGE_SOURCE_GRAPH_MISMATCH"
    assert upload_service.part_calls == 0
    assert upload_service.complete_calls == 0


@pytest.mark.asyncio
async def test_other_owner_and_non_knowledge_profile_are_rejected_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, graph_id = uuid4(), uuid4()
    subject = _subject(workspace_id)
    graph_service = _GraphService(_graph(workspace_id, graph_id))

    class _OwnerDeniedService(_UploadService):
        async def get_manifest(self, **_: object) -> UploadManifest:
            raise ForbiddenError("The upload belongs to another owner.")

    owner_denied = _OwnerDeniedService(_manifest(subject=subject, graph_id=graph_id))
    monkeypatch.setattr(knowledge, "_service", lambda *_: graph_service)
    monkeypatch.setattr(knowledge, "_source_upload_service", lambda _: owner_denied)
    with pytest.raises(ForbiddenError, match="another owner"):
        await knowledge.get_knowledge_source_upload(
            graph_id,
            owner_denied.manifest.upload_id,
            cast(Any, object()),
            Response(),
            _context(subject),
            cast(Any, object()),
        )

    profile_mismatch = _UploadService(
        _manifest(
            subject=subject,
            graph_id=graph_id,
            profile=UploadContentProfile.FORMAT_ONLY_V1,
        )
    )
    monkeypatch.setattr(knowledge, "_source_upload_service", lambda _: profile_mismatch)
    with pytest.raises(ValidationError) as profile_error:
        await knowledge.presign_knowledge_source_upload_part(
            graph_id,
            profile_mismatch.manifest.upload_id,
            UploadPartRequest(part_number=1),
            cast(Any, object()),
            _context(subject),
            cast(Any, object()),
        )
    assert profile_error.value.details["code"] == "KNOWLEDGE_SOURCE_PROFILE_MISMATCH"
    assert profile_mismatch.part_calls == 0


@pytest.mark.asyncio
async def test_completion_preserves_etag_and_idempotency_replay_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, graph_id = uuid4(), uuid4()
    subject = _subject(workspace_id)
    graph_service = _GraphService(_graph(workspace_id, graph_id))
    upload_service = _UploadService(_manifest(subject=subject, graph_id=graph_id))
    monkeypatch.setattr(knowledge, "_service", lambda *_: graph_service)
    monkeypatch.setattr(knowledge, "_source_upload_service", lambda _: upload_service)
    payload = UploadCompleteRequest(
        parts=[CompletedPartRequest(part_number=1, etag="object-etag")]
    )

    responses = [Response(), Response()]
    for response in responses:
        result = await knowledge.complete_knowledge_source_upload(
            graph_id,
            upload_service.manifest.upload_id,
            payload,
            cast(Any, object()),
            response,
            _context(subject),
            cast(Any, object()),
            '"1"',
            "knowledge-source-complete-replay",
        )
        assert isinstance(result, UploadResponse)
        assert result.version == 2
        assert response.headers["ETag"] == '"2"'
    assert upload_service.complete_calls == 2
    assert upload_service.manifest.state is UploadState.COMPLETION_QUEUED


def _binding(model: str, marker: str) -> ModelBinding:
    return ModelBinding(
        provider="openai-compatible",
        model=model,
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_source="DEPLOYMENT",
        configuration_version=None,
        configuration_hash=marker * 64,
    )


@pytest.mark.asyncio
async def test_analysis_propagates_profile_or_evidence_rejection_from_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, graph_id = uuid4(), uuid4()
    subject = _subject(workspace_id)
    graph_service = _GraphService(_graph(workspace_id, graph_id))
    captured: dict[str, object] = {}

    class _RejectingStore:
        def __init__(self, _: object) -> None:
            pass

        async def enqueue(self, **values: object) -> object:
            captured.update(values)
            raise ValidationError(
                "The source validation evidence is stale.",
                details={"code": "KNOWLEDGE_SOURCE_VALIDATION_EVIDENCE_MISMATCH"},
            )

    monkeypatch.setattr(knowledge, "_service", lambda *_: graph_service)
    monkeypatch.setattr(knowledge, "SqlKnowledgeSourceJobStore", _RejectingStore)
    monkeypatch.setattr(
        knowledge,
        "get_container",
        lambda _: SimpleNamespace(
            settings=SimpleNamespace(
                knowledge_source_worker_enabled=True,
                knowledge_source_job_maximum_attempts=3,
            )
        ),
    )
    monkeypatch.setattr(
        knowledge,
        "resolve_knowledge_runtime_bindings",
        lambda _: SimpleNamespace(
            embedding=_binding("embed", "a"), extraction=_binding("extract", "b")
        ),
    )

    upload_id = uuid4()
    with pytest.raises(ValidationError) as error:
        await knowledge.analyze_knowledge_document_source(
            graph_id=graph_id,
            upload_id=upload_id,
            payload=KnowledgeSourceAnalyzeRequest(title="Analyze source"),
            request=cast(Any, object()),
            context=_context(subject),
            session=cast(Any, object()),
            idempotency_key="knowledge-source-evidence-reject",
        )
    assert error.value.details["code"] == "KNOWLEDGE_SOURCE_VALIDATION_EVIDENCE_MISMATCH"
    assert captured["workspace_id"] == workspace_id
    assert captured["graph_id"] == graph_id
    assert captured["upload_id"] == upload_id
    assert captured["idempotency_key"] == "knowledge-source-evidence-reject"
