from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import ChatRetentionBinding
from datariver.domain.common import ConflictError
from datariver.infrastructure.db.chat import ACTIVE_RETENTION_BINDING, SqlChatStore
from datariver.infrastructure.db.models.assistant import (
    AssistantRunModel,
    ChatMessageModel,
    ChatSessionModel,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def one_or_none(self) -> object | None:
        return self._value


class _Session:
    def __init__(self, existing: ChatSessionModel | None = None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.flushed: list[tuple[object, ...]] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    def add_all(self, values: list[object]) -> None:
        self.added.extend(values)

    async def flush(self, values: tuple[object, ...]) -> None:
        self.flushed.append(values)

    async def scalars(self, statement: object) -> _ScalarResult:
        del statement
        return _ScalarResult(self.existing)


def _binding(*, days: int = 37) -> ChatRetentionBinding:
    return ChatRetentionBinding(
        policy_id=uuid4(),
        policy_hash="a" * 64,
        binding_basis_at=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        chat_content_days=days,
    )


@pytest.mark.asyncio
async def test_new_session_binds_the_exact_policy_duration_without_committing() -> None:
    session = _Session()
    store = SqlChatStore(cast(AsyncSession, session))
    binding = _binding(days=37)

    await store.save_exchange(
        workspace_id=uuid4(),
        owner_id=uuid4(),
        session_id=None,
        question="governed question",
        answer="검증 불가",
        evidence=(),
        policy_decision_id=uuid4(),
        retention=binding,
    )

    model = next(value for value in session.added if isinstance(value, ChatSessionModel))
    assert model.retention_policy_id == binding.policy_id
    assert model.retention_policy_hash == binding.policy_hash
    assert model.retention_basis_at == binding.binding_basis_at
    assert model.retention_until == binding.binding_basis_at + timedelta(days=37)
    assert model.retention_binding_version == ACTIVE_RETENTION_BINDING
    assert [[type(value) for value in batch] for batch in session.flushed] == [
        [ChatSessionModel],
        [ChatMessageModel, ChatMessageModel],
        [AssistantRunModel],
    ]


@pytest.mark.asyncio
async def test_legacy_session_is_readable_but_append_closed() -> None:
    workspace_id = uuid4()
    owner_id = uuid4()
    existing = ChatSessionModel(
        id=uuid4(),
        workspace_id=workspace_id,
        owner_id=owner_id,
        title="legacy",
        scope={},
        retention_until=datetime(2026, 12, 1, tzinfo=UTC),
        retention_policy_id=None,
        retention_policy_hash=None,
        retention_basis_at=None,
        retention_binding_version="LEGACY_UNBOUND_V1",
        version=1,
    )
    store = SqlChatStore(cast(AsyncSession, _Session(existing)))

    with pytest.raises(ConflictError, match="start a new session"):
        await store.save_exchange(
            workspace_id=workspace_id,
            owner_id=owner_id,
            session_id=existing.id,
            question="append",
            answer="denied",
            evidence=(),
            policy_decision_id=uuid4(),
            retention=_binding(),
        )


def test_migration_and_initial_schema_install_fail_closed_binding_guards() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0018_chat_retention_policy_binding.py").read_text(
        encoding="utf-8"
    )
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")

    assert REQUIRED_DATABASE_REVISION == "0059"
    assert 'down_revision: str | Sequence[str] | None = "0017"' in migration
    for required in (
        "ACTIVE_POLICY_V1",
        "LEGACY_UNBOUND_V1",
        "fk_chat_sessions_retention_policy_binding",
        "enforce_chat_session_retention_binding",
        "enforce_chat_message_retention_binding",
        "transaction_timestamp()",
        "FOR KEY SHARE",
        "The Chat retention binding schema is only partially present.",
        "Chat retention binding privilege contract is invalid",
    ):
        assert required in migration
        if not required.startswith(("The Chat", "Chat retention")):
            assert required in initial or required in generator
    assert "Compatibility bridge: regenerated 0001 owns" in migration
    assert "GRANT UPDATE (version, updated_at) ON assistant.chat_sessions" in migration
    assert "GRANT UPDATE (is_favorite, is_archived, version, updated_at)" in initial
    assert "GRANT UPDATE ON assistant.chat_sessions TO datariver_app" not in initial
    assert "timedelta(days=90)" not in (
        root / "backend/src/datariver/infrastructure/db/chat.py"
    ).read_text(encoding="utf-8")


def test_chat_favorite_migration_preserves_retention_privilege_boundary() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0056_chat_session_favorites.py").read_text(
        encoding="utf-8"
    )
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")

    assert 'revision: str = "0056"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0055"' in migration
    assert "is_favorite" in migration
    assert "display_name" in migration
    assert "description" in migration
    assert "GRANT UPDATE (is_favorite, version, updated_at)" in migration
    for policy in (
        "chat_session_owner_access",
        "chat_message_owner_access",
        "assistant_run_owner_access",
        "evidence_citation_owner_access",
    ):
        assert policy in migration
        assert policy in generator
    assert "AS RESTRICTIVE FOR ALL TO datariver_app" in migration
    assert "normalized_using != expected_expression.lower()" in migration
    assert "required_fragments" not in migration
    assert '" or " in normalized_using' not in migration
    assert "retention_until" in migration
    assert "Chat favorites exist; downgrade would discard user-owned state." in migration
    assert "Chat evidence display data exists; downgrade would discard it." in migration
    assert "GRANT UPDATE (is_favorite, is_archived, version, updated_at)" in generator


def test_chat_history_archive_migration_preserves_retained_content() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0058_chat_session_history_archive.py").read_text(
        encoding="utf-8"
    )
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")

    assert 'revision: str = "0058"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0057"' in migration
    assert "is_archived" in migration
    assert "DELETE ON assistant.chat_sessions" not in migration
    assert "Archived Chat history exists; downgrade would restore deleted items." in migration
    owner_mutation = "GRANT UPDATE (is_favorite, is_archived, version, updated_at)"
    assert owner_mutation in migration
    assert owner_mutation in generator
