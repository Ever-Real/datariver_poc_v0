from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from datariver.application.dto import KnowledgeStudioSampleRequest
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.domain.knowledge_studio_ingestion import (
    StudioIngestionBindingClaim,
    StudioIngestionClaim,
    StudioIngestionRule,
)
from datariver.infrastructure.knowledge_studio import postgres_source
from datariver.infrastructure.knowledge_studio.postgres_source import (
    KnowledgeStudioSourceManifestError,
    KnowledgeStudioSourceSecretReader,
    build_knowledge_studio_batch_source_reader,
    build_knowledge_studio_sample_reader,
    parse_knowledge_studio_source_manifest,
)

WORKSPACE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
ASSET_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2")
SUBJECT_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3")
SOURCE_REFERENCE_ID = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b4")
NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


def test_batch_reader_hard_limits_match_the_approved_product_bounds() -> None:
    assert postgres_source._MAXIMUM_BATCH_ROWS == 100_000
    assert postgres_source._MAXIMUM_BATCH_BYTES == 256 * 1024 * 1024


def _source_configuration() -> dict[str, object]:
    return {
        "workspace_id": str(WORKSPACE_ID),
        "asset_id": str(ASSET_ID),
        "source_version": "source-v7",
        "projection_source_version": "projection-v11",
        "minimum_clearance": 1,
        "connection_profile_id": "knowledge-hr-v1",
        "connection_profile_version": 1,
        "host": "127.0.0.1",
        "allowed_ips": ["127.0.0.1"],
        "port": 5432,
        "database": "warehouse",
        "schema": "public",
        "relation": "employees",
        "field_map": {
            "employee_id": "employee_id",
            "employee_name": "employee_name",
        },
        "key_fields": ["employee_id"],
        "username": "knowledge_reader",
        "password_secret_ref": "file:/run/secrets/knowledge-source-password",
        "tls_mode": "REQUIRE",
        "statement_timeout_seconds": 10,
        "lock_timeout_seconds": 2,
        "idle_transaction_timeout_seconds": 20,
        "hard_timeout_seconds": 30,
        "batch_size": 500,
        "maximum_rows": 100_000,
        "maximum_bytes": 1_073_741_824,
    }


def _manifest_document() -> dict[str, object]:
    source = _source_configuration()
    source["connection_profile_hash"] = canonical_json_hash(source)
    return {
        "contract_version": "KNOWLEDGE_STUDIO_POSTGRES_SOURCE_MANIFEST_V1",
        "manifest_id": "knowledge-studio-development",
        "manifest_version": 1,
        "sources": [source],
    }


def _subject() -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.CONFIDENTIAL,
        allowed_actions=frozenset({Action.KG_READ, Action.KG_EDIT}),
    )


def test_manifest_pins_exact_non_secret_source_contract() -> None:
    manifest = parse_knowledge_studio_source_manifest(json.dumps(_manifest_document()))

    source = manifest.resolve(workspace_id=WORKSPACE_ID, asset_id=ASSET_ID)
    profile_pin = manifest.resolve_pin(
        workspace_id=WORKSPACE_ID,
        asset_id=ASSET_ID,
        source_version="source-v7",
        projection_source_version="projection-v11",
    )

    assert source is not None
    assert profile_pin is not None
    assert source.field_map == (
        ("employee_id", "employee_id"),
        ("employee_name", "employee_name"),
    )
    assert source.key_fields == ("employee_id",)
    assert source.connection_profile_hash == canonical_json_hash(source.configuration_document())
    assert profile_pin.connection_profile_id == "knowledge-hr-v1"
    assert profile_pin.connection_profile_version == 1
    assert profile_pin.connection_profile_hash == source.connection_profile_hash
    assert "password" not in manifest.document()
    assert (
        manifest.resolve_pin(
            workspace_id=WORKSPACE_ID,
            asset_id=ASSET_ID,
            source_version="source-v8",
            projection_source_version="projection-v11",
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("host", "warehouse.internal", "host is invalid"),
        ("relation", "employees; DROP TABLE users", "relation is invalid"),
        ("tls_mode", "DISABLE", "TLS mode is invalid"),
        ("password_secret_ref", "env:SOURCE_PASSWORD", "mounted file secret"),
    ],
)
def test_manifest_rejects_unapproved_source_coordinates(
    field: str,
    value: object,
    message: str,
) -> None:
    document = _manifest_document()
    source = dict(document["sources"][0])  # type: ignore[index]
    source[field] = value
    source["connection_profile_hash"] = canonical_json_hash(
        {key: item for key, item in source.items() if key != "connection_profile_hash"}
    )
    document["sources"] = [source]

    with pytest.raises(KnowledgeStudioSourceManifestError, match=message):
        parse_knowledge_studio_source_manifest(json.dumps(document))


def test_manifest_rejects_hash_drift_and_duplicate_json_fields() -> None:
    document = _manifest_document()
    source = dict(document["sources"][0])  # type: ignore[index]
    source["maximum_rows"] = 1
    document["sources"] = [source]

    with pytest.raises(KnowledgeStudioSourceManifestError, match="hash does not match"):
        parse_knowledge_studio_source_manifest(json.dumps(document))

    with pytest.raises(KnowledgeStudioSourceManifestError, match="repeats a JSON field"):
        parse_knowledge_studio_source_manifest(
            '{"contract_version":"KNOWLEDGE_STUDIO_POSTGRES_SOURCE_MANIFEST_V1",'
            '"contract_version":"KNOWLEDGE_STUDIO_POSTGRES_SOURCE_MANIFEST_V1",'
            '"manifest_id":"test","manifest_version":1,"sources":[]}'
        )


def test_secret_reader_rejects_symlink_and_reads_one_bounded_file(tmp_path: Path) -> None:
    secret = tmp_path / "knowledge-source-password"
    secret.write_text("secret-value\n", encoding="utf-8")
    reader = KnowledgeStudioSourceSecretReader(tmp_path)

    assert reader.resolve("file:/run/secrets/knowledge-source-password") == "secret-value"

    secret.unlink()
    secret.symlink_to(tmp_path / "missing")
    with pytest.raises(KnowledgeStudioSourceManifestError, match="secret file is invalid"):
        reader.resolve("file:/run/secrets/knowledge-source-password")


class _FakeTransaction:
    async def start(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.closed = False

    def transaction(self, **_: object) -> _FakeTransaction:
        return _FakeTransaction()

    async def fetch(self, query: str, limit: int) -> list[dict[str, object]]:
        self.query = query
        assert limit == 5
        return [{"field_0": 7, "field_1": "홍길동"}]

    async def fetchval(self, query: str) -> int:
        self.query = query
        return 7

    async def close(self, **kwargs: object) -> None:
        assert kwargs["timeout"] == 5
        self.closed = True


@pytest.mark.asyncio
async def test_manifest_reader_executes_only_server_owned_bounded_select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "knowledge-source-password"
    secret.write_text("secret-value", encoding="utf-8")
    manifest = parse_knowledge_studio_source_manifest(json.dumps(_manifest_document()))
    connection = _FakeConnection()

    async def connect(**kwargs: Any) -> _FakeConnection:
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["user"] == "knowledge_reader"
        assert kwargs["password"] == "secret-value"
        assert kwargs["server_settings"]["default_transaction_read_only"] == "on"
        return connection

    monkeypatch.setattr(
        "datariver.infrastructure.knowledge_studio.postgres_source.asyncpg.connect",
        connect,
    )
    reader = build_knowledge_studio_sample_reader(
        manifest=manifest,
        secret_root=tmp_path,
    )

    result = await reader.sample_rows(
        subject=_subject(),
        source=KnowledgeStudioSampleRequest(
            source_reference_id=SOURCE_REFERENCE_ID,
            asset_id=ASSET_ID,
            source_version="source-v7",
            projection_source_version="projection-v11",
            field_paths=("employee_id", "employee_name"),
            limit=5,
        ),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request-1",
    )

    assert result.rows == ({"employee_id": 7, "employee_name": "홍길동"},)
    assert 'FROM "public"."employees"' in connection.query
    assert 'ORDER BY "employee_id" LIMIT $1' in connection.query
    assert connection.closed is True


def _batch_manifest_document() -> dict[str, object]:
    source = _source_configuration()
    source["field_map"] = {
        "employee_id": "employee_id",
        "employee_name": "employee_name",
        "row_sequence": "row_sequence",
    }
    source["key_fields"] = ["row_sequence"]
    source["batch_size"] = 10
    source["connection_profile_hash"] = canonical_json_hash(source)
    return {
        "contract_version": "KNOWLEDGE_STUDIO_POSTGRES_SOURCE_MANIFEST_V1",
        "manifest_id": "knowledge-studio-development",
        "manifest_version": 1,
        "sources": [source],
    }


def _binding_claim(
    *,
    connection_profile_hash: str,
) -> StudioIngestionBindingClaim:
    return StudioIngestionBindingClaim(
        pin_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf401"),
        binding_version_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf402"),
        source_reference_id=SOURCE_REFERENCE_ID,
        source_asset_id=ASSET_ID,
        source_version="source-v7",
        projection_source_version="projection-v11",
        source_classification=1,
        target_class_stable_id="class.employee",
        target_class_canonical_name="Employee",
        mapping_hash="a" * 64,
        connection_profile_id="knowledge-hr-v1",
        connection_profile_version=1,
        connection_profile_hash=connection_profile_hash,
        rules=(
            StudioIngestionRule(
                method="SUBJECT_ID",
                source_field_path="employee_id",
                target_stable_element_id="class.employee",
                target_canonical_name="Employee",
                target_data_type=None,
                target_nullable=None,
                vector_index_enabled=False,
                transform_id="IDENTITY",
                transform_version="1",
            ),
            StudioIngestionRule(
                method="PROPERTY",
                source_field_path="employee_name",
                target_stable_element_id="property.employee.name",
                target_canonical_name="name",
                target_data_type="STRING",
                target_nullable=False,
                vector_index_enabled=False,
                transform_id="IDENTITY",
                transform_version="1",
            ),
        ),
    )


def _ingestion_claim(
    *,
    manifest_hash: str,
    binding: StudioIngestionBindingClaim,
) -> StudioIngestionClaim:
    return StudioIngestionClaim(
        workspace_id=WORKSPACE_ID,
        job_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf403"),
        graph_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf404"),
        draft_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf405"),
        studio_release_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf406"),
        ontology_version_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf407"),
        requested_by=SUBJECT_ID,
        graph_classification=1,
        manifest_id="knowledge-studio-development",
        manifest_version=1,
        manifest_hash=manifest_hash,
        pin_hash="b" * 64,
        embedding_binding=None,
        bindings=(binding,),
        attempt_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf408"),
        attempt_no=1,
        lease_epoch=1,
        worker_fingerprint="worker-1",
        source_access_deadline=datetime.now(UTC) + timedelta(minutes=5),
        lease_token="opaque-lease-token",
    )


class _BatchFakeTransaction:
    def __init__(self) -> None:
        self.started = False
        self.rolled_back = False

    async def start(self) -> None:
        self.started = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _BatchFakeConnection:
    def __init__(
        self,
        *,
        batches: list[list[dict[str, object]]],
        events: list[str],
    ) -> None:
        self.batches = batches
        self.events = events
        self.fetches: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_options: dict[str, object] = {}
        self.transaction_record = _BatchFakeTransaction()
        self.closed = False

    def transaction(self, **options: object) -> _BatchFakeTransaction:
        self.transaction_options = options
        return self.transaction_record

    async def fetch(self, query: str, *parameters: object) -> list[dict[str, object]]:
        self.events.append("select")
        self.fetches.append((query, parameters))
        return self.batches.pop(0)

    async def close(self, **kwargs: object) -> None:
        assert kwargs["timeout"] == 5
        self.closed = True


def _physical_row(sequence: int, name: str) -> dict[str, object]:
    return {
        "field_0": sequence,
        "field_1": name,
        "key_0": sequence,
    }


@pytest.mark.asyncio
async def test_batch_reader_fences_each_parameterized_keyset_select_and_closes_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "knowledge-source-password").write_text("secret-value", encoding="utf-8")
    manifest = parse_knowledge_studio_source_manifest(json.dumps(_batch_manifest_document()))
    source = manifest.resolve(workspace_id=WORKSPACE_ID, asset_id=ASSET_ID)
    assert source is not None
    claim = _ingestion_claim(
        manifest_hash=manifest.manifest_hash,
        binding=_binding_claim(connection_profile_hash=source.connection_profile_hash),
    )
    events: list[str] = []
    first_batch = [_physical_row(index, f"employee-{index}") for index in range(1, 11)]
    last_batch = [_physical_row(11, "employee-11")]
    connections = [
        _BatchFakeConnection(batches=[first_batch.copy(), last_batch.copy()], events=events),
        _BatchFakeConnection(batches=[first_batch.copy(), last_batch.copy()], events=events),
    ]

    async def connect(**kwargs: Any) -> _BatchFakeConnection:
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["password"] == "secret-value"
        assert kwargs["server_settings"]["application_name"] == (
            "datariver-knowledge-studio-ingestion"
        )
        assert kwargs["server_settings"]["default_transaction_read_only"] == "on"
        return connections.pop(0)

    monkeypatch.setattr(
        "datariver.infrastructure.knowledge_studio.postgres_source.asyncpg.connect",
        connect,
    )
    reader = build_knowledge_studio_batch_source_reader(
        manifest=manifest,
        secret_root=tmp_path,
    )

    async def statement_fence() -> None:
        events.append("fence")

    first_connections = connections.copy()
    first = await reader.read(claim=claim, statement_fence=statement_fence)
    second = await reader.read(claim=claim, statement_fence=statement_fence)

    assert len(first) == 1
    assert first[0].rows[0] == {
        "employee_id": 1,
        "employee_name": "employee-1",
    }
    assert all("row_sequence" not in row for row in first[0].rows)
    assert first[0].source_read_receipt_hash == second[0].source_read_receipt_hash
    assert events == ["fence", "select", "fence", "select"] * 2
    assert all(
        connection.transaction_options == {"isolation": "repeatable_read", "readonly": True}
        for connection in first_connections
    )
    assert all(connection.transaction_record.rolled_back for connection in first_connections)
    assert all(connection.closed for connection in first_connections)
    first_query, first_parameters = first_connections[0].fetches[0]
    second_query, second_parameters = first_connections[0].fetches[1]
    assert 'FROM "public"."employees"' in first_query
    assert 'ORDER BY "row_sequence" LIMIT $1' in first_query
    assert first_parameters == (10,)
    assert 'WHERE "row_sequence" > $1' in second_query
    assert "LIMIT $2" in second_query
    assert second_parameters == (10, 10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_change", "error_code"),
    [
        ("manifest", "STALE_SOURCE_MANIFEST"),
        ("profile", "STALE_CONNECTION_PROFILE"),
    ],
)
async def test_batch_reader_rejects_drifted_manifest_and_profile_before_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    claim_change: str,
    error_code: str,
) -> None:
    (tmp_path / "knowledge-source-password").write_text("secret-value", encoding="utf-8")
    manifest = parse_knowledge_studio_source_manifest(json.dumps(_batch_manifest_document()))
    source = manifest.resolve(workspace_id=WORKSPACE_ID, asset_id=ASSET_ID)
    assert source is not None
    claim = _ingestion_claim(
        manifest_hash=manifest.manifest_hash,
        binding=_binding_claim(connection_profile_hash=source.connection_profile_hash),
    )
    if claim_change == "manifest":
        claim = replace(claim, manifest_hash="c" * 64)
    else:
        claim = replace(
            claim,
            bindings=(replace(claim.bindings[0], connection_profile_hash="c" * 64),),
        )

    async def connect_mock(**_: Any) -> _BatchFakeConnection:
        pytest.fail("source connection must not be opened")

    monkeypatch.setattr(
        "datariver.infrastructure.knowledge_studio.postgres_source.asyncpg.connect",
        connect_mock,
    )
    reader = build_knowledge_studio_batch_source_reader(
        manifest=manifest,
        secret_root=tmp_path,
    )

    async def statement_fence() -> None:
        pytest.fail("statement fence must not run before pin validation")

    with pytest.raises(ConflictError) as captured:
        await reader.read(claim=claim, statement_fence=statement_fence)

    assert captured.value.details == {"code": error_code, "stale": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("budget_name", "budget_value", "row", "error_code"),
    [
        (
            "_MAXIMUM_BATCH_ROWS",
            1,
            _physical_row(2, "second"),
            "SOURCE_ROW_LIMIT_EXCEEDED",
        ),
        (
            "_MAXIMUM_BATCH_BYTES",
            32,
            _physical_row(1, "x" * 64),
            "SOURCE_BYTE_LIMIT_EXCEEDED",
        ),
    ],
)
async def test_batch_reader_enforces_cumulative_hard_budgets_and_closes_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget_name: str,
    budget_value: int,
    row: dict[str, object],
    error_code: str,
) -> None:
    (tmp_path / "knowledge-source-password").write_text("secret-value", encoding="utf-8")
    manifest = parse_knowledge_studio_source_manifest(json.dumps(_batch_manifest_document()))
    source = manifest.resolve(workspace_id=WORKSPACE_ID, asset_id=ASSET_ID)
    assert source is not None
    claim = _ingestion_claim(
        manifest_hash=manifest.manifest_hash,
        binding=_binding_claim(connection_profile_hash=source.connection_profile_hash),
    )
    monkeypatch.setattr(
        f"datariver.infrastructure.knowledge_studio.postgres_source.{budget_name}",
        budget_value,
    )
    batches = (
        [[_physical_row(1, "first")], [row]] if budget_name == "_MAXIMUM_BATCH_ROWS" else [[row]]
    )
    connection = _BatchFakeConnection(batches=batches, events=[])

    async def connect(**_: Any) -> _BatchFakeConnection:
        return connection

    monkeypatch.setattr(
        "datariver.infrastructure.knowledge_studio.postgres_source.asyncpg.connect",
        connect,
    )
    reader = build_knowledge_studio_batch_source_reader(
        manifest=manifest,
        secret_root=tmp_path,
    )

    async def statement_fence() -> None:
        return None

    with pytest.raises(ConflictError) as captured:
        await reader.read(claim=claim, statement_fence=statement_fence)

    assert captured.value.details["code"] == error_code
    assert connection.closed is True
