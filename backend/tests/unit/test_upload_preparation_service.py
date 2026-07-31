from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import IdempotencyRecord
from datariver.application.ports import ObjectStore
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.registration import (
    RegistrationService,
    UploadAuthorizationPolicy,
    UploadNotFound,
    upload_authorization_actions,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, DomainEvent, ValidationError, utc_now
from datariver.domain.registration import (
    UploadContentProfile,
    UploadManifest,
    UploadPreparation,
    UploadPreparationState,
    UploadState,
)


class FakeAuthorization:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def authorize(self, *, action: Action, **_: object) -> None:
        self.events.append(f"authorize:{action.value}")


class FakeUploads:
    def __init__(self, manifest: UploadManifest, events: list[str]) -> None:
        self.manifest = manifest
        self.events = events

    async def get_for_update(self, *, workspace_id: UUID, upload_id: UUID) -> UploadManifest | None:
        self.events.append("manifest-lock")
        if workspace_id != self.manifest.workspace_id or upload_id != self.manifest.upload_id:
            return None
        return self.manifest

    async def get(self, *, workspace_id: UUID, upload_id: UUID) -> UploadManifest | None:
        self.events.append("manifest-read")
        if workspace_id != self.manifest.workspace_id or upload_id != self.manifest.upload_id:
            return None
        return self.manifest


class FakePreparations:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.values: dict[UUID, UploadPreparation] = {}

    async def add(self, preparation: UploadPreparation) -> None:
        self.events.append("preparation-add")
        self.values[preparation.preparation_id] = preparation

    async def get(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparation | None:
        value = self.values.get(preparation_id)
        if value is None or value.workspace_id != workspace_id or value.upload_id != upload_id:
            return None
        return value

    async def find_source_configuration(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        source_manifest_version: int,
        content_profile: str,
        configuration_hash: str,
    ) -> UploadPreparation | None:
        self.events.append("preparation-source-read")
        return next(
            (
                value
                for value in self.values.values()
                if value.workspace_id == workspace_id
                and value.upload_id == upload_id
                and value.source_manifest_version == source_manifest_version
                and value.content_profile.value == content_profile
                and value.configuration_hash == configuration_hash
            ),
            None,
        )

    async def list(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        state: str | None,
        limit: int,
    ) -> list[UploadPreparation]:
        return [
            value
            for value in reversed(tuple(self.values.values()))
            if value.workspace_id == workspace_id
            and value.upload_id == upload_id
            and (state is None or value.state.value == state)
        ][:limit]


class FakeIdempotency:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.values: dict[tuple[UUID, str, str], IdempotencyRecord] = {}

    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None:
        return self.values.get((workspace_id, key, operation))

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, Any],
    ) -> None:
        self.events.append("idempotency-save")
        self.values[(workspace_id, key, operation)] = IdempotencyRecord(
            request_hash=request_hash,
            result=result,
        )


class FakeOutbox:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.domain_events: list[DomainEvent] = []

    async def add_events(self, events: list[DomainEvent]) -> None:
        self.events.append("outbox-add")
        self.domain_events.extend(events)


class FakeUnitOfWork:
    def __init__(self, manifest: UploadManifest, events: list[str]) -> None:
        self.uploads = FakeUploads(manifest, events)
        self.preparations = FakePreparations(events)
        self.idempotency = FakeIdempotency(events)
        self.outbox = FakeOutbox(events)
        self.events = events
        self.security_contexts: list[tuple[UUID, UUID]] = []
        self.commits = 0

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        self.security_contexts.append((workspace_id, subject_id))

    async def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1


def _accepted_manifest() -> UploadManifest:
    workspace_id = uuid4()
    upload_id = uuid4()
    return UploadManifest(
        upload_id=upload_id,
        workspace_id=workspace_id,
        owner_id=uuid4(),
        bucket="accepted",
        object_key=f"accepted/{workspace_id}/{upload_id}/validation-v2-attempt-1",
        display_name="dataset-descriptions.csv",
        declared_size_bytes=2048,
        declared_mime="text/csv",
        declared_sha256="a" * 64,
        classification=Classification.INTERNAL,
        multipart_upload_id="multipart-complete",
        expires_at=utc_now() + timedelta(hours=1),
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
        state=UploadState.ACCEPTED,
        version=7,
        actual_size_bytes=2048,
        actual_mime="text/csv",
        actual_sha256="a" * 64,
        validation_summary={
            "validator_version": "integrity-format-v2-low-resource",
            "size_bytes": 2048,
            "sha256": "a" * 64,
            "content_type": "text/csv",
            "coverage": "FULL",
        },
    )


def _fixture() -> tuple[
    RegistrationService,
    FakeUnitOfWork,
    UploadManifest,
    SubjectAttributes,
    EnvironmentAttributes,
    list[str],
]:
    manifest = _accepted_manifest()
    events: list[str] = []
    uow = FakeUnitOfWork(manifest, events)
    service = RegistrationService(
        uow_factory=cast(Any, lambda: uow),
        authorization=cast(AuthorizationService, FakeAuthorization(events)),
        object_store=cast(ObjectStore, object()),
        quarantine_bucket="quarantine",
        presign_ttl_seconds=900,
    )
    subject = SubjectAttributes(
        subject_id=manifest.owner_id,
        workspace_id=manifest.workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.INTERNAL,
    )
    environment = EnvironmentAttributes(requested_at=utc_now())
    return service, uow, manifest, subject, environment, events


async def _create_preparation(
    service: RegistrationService,
    manifest: UploadManifest,
    subject: SubjectAttributes,
    environment: EnvironmentAttributes,
    *,
    idempotency_key: str,
    expected_manifest_version: int | None = None,
    request_id: str = "prepare-test",
) -> UploadPreparation:
    return await service.create_preparation(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        subject=subject,
        expected_manifest_version=(
            manifest.version if expected_manifest_version is None else expected_manifest_version
        ),
        environment=environment,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_only_server_scoped_knowledge_ingress_can_supply_a_graph_binding() -> None:
    service, _, manifest, subject, environment, events = _fixture()
    with pytest.raises(ValidationError, match="Only the Knowledge source ingress"):
        await service.initiate(
            workspace_id=manifest.workspace_id,
            subject=subject,
            display_name="source.txt",
            declared_size_bytes=12,
            declared_mime="text/plain",
            declared_sha256="b" * 64,
            classification=Classification.INTERNAL,
            content_profile=UploadContentProfile.KNOWLEDGE_SOURCE_DOCUMENT_V1,
            environment=environment,
            request_id="source-binding-test",
            idempotency_key="source-binding-test-0001",
            request_hash="c" * 64,
            authorization_policy=UploadAuthorizationPolicy.REGISTRATION,
            knowledge_source_graph_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="server-owned target graph binding"):
        await service.initiate(
            workspace_id=manifest.workspace_id,
            subject=subject,
            display_name="source.txt",
            declared_size_bytes=12,
            declared_mime="text/plain",
            declared_sha256="b" * 64,
            classification=Classification.INTERNAL,
            content_profile=UploadContentProfile.KNOWLEDGE_SOURCE_DOCUMENT_V1,
            environment=environment,
            request_id="source-binding-test",
            idempotency_key="source-binding-test-0001",
            request_hash="c" * 64,
            authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_SOURCE,
            knowledge_source_graph_id=None,
        )
    assert events == []


@pytest.mark.asyncio
async def test_create_preparation_locks_authorizes_and_persists_server_evidence() -> None:
    service, uow, manifest, subject, environment, events = _fixture()

    preparation = await service.create_preparation(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        subject=subject,
        expected_manifest_version=manifest.version,
        environment=environment,
        request_id="prepare-1",
        idempotency_key="typed-preparation-0001",
    )

    assert preparation.state is UploadPreparationState.QUEUED
    assert preparation.source_manifest_version == manifest.version
    assert preparation.source_sha256 == manifest.declared_sha256
    assert preparation.content_profile is UploadContentProfile.DATASET_DESCRIPTION_CSV_V1
    assert len(preparation.configuration_hash) == 64
    assert len(uow.preparations.values) == 1
    assert len(uow.outbox.domain_events) == 1
    assert events == [
        "manifest-lock",
        "authorize:registration.read",
        "authorize:registration.validate",
        "preparation-source-read",
        "preparation-add",
        "outbox-add",
        "idempotency-save",
        "commit",
    ]


@pytest.mark.asyncio
async def test_get_manifest_uses_explicit_knowledge_studio_authorization_policy() -> None:
    service, _, manifest, subject, environment, events = _fixture()

    result = await service.get_manifest(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        subject=subject,
        environment=environment,
        request_id="knowledge-upload-read",
        authorization_policy=UploadAuthorizationPolicy.KNOWLEDGE_STUDIO,
    )

    assert result is manifest
    assert events == ["manifest-read", "authorize:kg.edit"]


def test_upload_authorization_policy_keeps_registration_defaults_and_is_server_owned() -> None:
    registration = upload_authorization_actions(UploadAuthorizationPolicy.REGISTRATION)
    knowledge_policies = (
        upload_authorization_actions(UploadAuthorizationPolicy.KNOWLEDGE_STUDIO),
        upload_authorization_actions(UploadAuthorizationPolicy.KNOWLEDGE_SOURCE),
    )

    assert (
        registration.initiate,
        registration.presign_part,
        registration.read_manifest,
        registration.queue_completion,
    ) == (
        Action.REGISTRATION_CREATE,
        Action.REGISTRATION_CREATE,
        Action.REGISTRATION_READ,
        Action.REGISTRATION_CREATE,
    )
    for knowledge in knowledge_policies:
        assert {
            knowledge.initiate,
            knowledge.presign_part,
            knowledge.read_manifest,
            knowledge.queue_completion,
        } == {Action.KG_EDIT}


@pytest.mark.asyncio
async def test_replay_and_different_keys_converge_on_one_canonical_preparation() -> None:
    service, uow, manifest, subject, environment, _ = _fixture()
    first = await _create_preparation(
        service,
        manifest,
        subject,
        environment,
        idempotency_key="typed-preparation-0002",
        request_id="prepare-replay",
    )
    replay = await _create_preparation(
        service,
        manifest,
        subject,
        environment,
        idempotency_key="typed-preparation-0002",
        request_id="prepare-replay",
    )
    converged = await _create_preparation(
        service,
        manifest,
        subject,
        environment,
        idempotency_key="typed-preparation-0003",
        request_id="prepare-replay",
    )

    assert replay.preparation_id == first.preparation_id
    assert converged.preparation_id == first.preparation_id
    assert len(uow.preparations.values) == 1
    assert len(uow.outbox.domain_events) == 1


@pytest.mark.asyncio
async def test_preparation_rejects_stale_version_state_profile_and_evidence() -> None:
    service, _, manifest, subject, environment, _ = _fixture()
    with pytest.raises(ConflictError, match="modified"):
        await _create_preparation(
            service,
            manifest,
            subject,
            environment,
            idempotency_key="typed-preparation-invalid",
            expected_manifest_version=manifest.version - 1,
            request_id="prepare-invalid",
        )

    manifest.state = UploadState.QUARANTINED
    with pytest.raises(ConflictError, match="accepted"):
        await _create_preparation(
            service,
            manifest,
            subject,
            environment,
            idempotency_key="typed-preparation-invalid",
            request_id="prepare-invalid",
        )
    manifest.state = UploadState.ACCEPTED

    manifest.validation_summary["sha256"] = "b" * 64
    with pytest.raises(ConflictError, match="evidence"):
        await _create_preparation(
            service,
            manifest,
            subject,
            environment,
            idempotency_key="typed-preparation-invalid",
            request_id="prepare-invalid",
        )
    manifest.validation_summary["sha256"] = manifest.declared_sha256

    manifest.actual_sha256 = None
    with pytest.raises(ConflictError, match="metadata"):
        await _create_preparation(
            service,
            manifest,
            subject,
            environment,
            idempotency_key="typed-preparation-invalid",
            request_id="prepare-invalid",
        )
    manifest.actual_sha256 = manifest.declared_sha256

    manifest.content_profile = UploadContentProfile.FORMAT_ONLY_V1
    with pytest.raises(ValidationError, match="no typed preparation"):
        await _create_preparation(
            service,
            manifest,
            subject,
            environment,
            idempotency_key="typed-preparation-invalid",
            request_id="prepare-invalid",
        )


@pytest.mark.asyncio
async def test_get_and_list_preparations_are_upload_scoped_and_authorized() -> None:
    service, _, manifest, subject, environment, events = _fixture()
    preparation = await service.create_preparation(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        subject=subject,
        expected_manifest_version=manifest.version,
        environment=environment,
        request_id="prepare-read-create",
        idempotency_key="typed-preparation-read",
    )
    events.clear()

    loaded = await service.get_preparation(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        preparation_id=preparation.preparation_id,
        subject=subject,
        environment=environment,
        request_id="prepare-read",
    )
    values = await service.list_preparations(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        state=UploadPreparationState.QUEUED,
        limit=20,
        subject=subject,
        environment=environment,
        request_id="prepare-list",
    )

    assert loaded.preparation_id == preparation.preparation_id
    assert [value.preparation_id for value in values] == [preparation.preparation_id]
    assert events == [
        "manifest-read",
        "authorize:registration.read",
        "manifest-read",
        "authorize:registration.read",
    ]
    with pytest.raises(UploadNotFound):
        await service.get_preparation(
            workspace_id=manifest.workspace_id,
            upload_id=uuid4(),
            preparation_id=preparation.preparation_id,
            subject=subject,
            environment=environment,
            request_id="prepare-cross-upload",
        )
