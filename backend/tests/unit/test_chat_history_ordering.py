from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from datariver.infrastructure.db.chat import SqlChatHistoryStore
from datariver.infrastructure.db.models.assistant import ChatMessageModel


class _EmptyRows:
    def all(self) -> list[object]:
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.statement: Any = None

    async def execute(self, statement: Any) -> _EmptyRows:
        self.statement = statement
        return _EmptyRows()


def _message(*, actor: str, identifier: str, created_at: datetime) -> ChatMessageModel:
    return cast(
        ChatMessageModel,
        SimpleNamespace(actor=actor, id=UUID(identifier), created_at=created_at),
    )


def test_message_history_orders_a_same_timestamp_exchange_as_question_then_answer() -> None:
    timestamp = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    messages = [
        _message(
            actor="ASSISTANT",
            identifier="00000000-0000-7000-8000-000000000001",
            created_at=timestamp,
        ),
        _message(
            actor="USER",
            identifier="ffffffff-ffff-7fff-bfff-ffffffffffff",
            created_at=timestamp,
        ),
    ]

    ordered = sorted(messages, key=SqlChatHistoryStore._chronological_message_key)

    assert [message.actor for message in ordered] == ["USER", "ASSISTANT"]


async def test_context_reader_query_fences_owner_session_and_active_retention() -> None:
    session = _RecordingSession()
    store = SqlChatHistoryStore(cast(Any, session))

    history = await store.read_user_intent_context(
        workspace_id=UUID("00000000-0000-4000-8000-000000000100"),
        owner_id=UUID("00000000-0000-4000-8000-000000000200"),
        session_id=UUID("00000000-0000-4000-8000-000000000300"),
        limit=3,
    )

    statement = str(session.statement)
    assert history.completed_user_turns == 0
    assert history.user_utterances == ()
    assert "chat_sessions.owner_id" in statement
    assert "chat_sessions.is_archived IS false" in statement
    assert "chat_sessions.retention_binding_version" in statement
    assert "chat_sessions.retention_until > now()" in statement
    assert "policy_versions.state" in statement
    assert "assistant_runs.state" in statement
