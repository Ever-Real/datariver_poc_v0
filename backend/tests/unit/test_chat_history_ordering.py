from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from datariver.infrastructure.db.chat import SqlChatHistoryStore
from datariver.infrastructure.db.models.assistant import ChatMessageModel


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
