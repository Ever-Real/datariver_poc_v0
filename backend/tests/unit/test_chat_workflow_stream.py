from __future__ import annotations

import asyncio
import json
from typing import Any, cast
from uuid import uuid4

from datariver.application.dto import ChatWorkflowEvent
from datariver.domain.chat import (
    ChatAdapterState,
    ChatPerformanceMetric,
    ChatRetrievalMode,
    ChatRouteReason,
    ChatWorkflowStage,
    ChatWorkflowStatus,
)
from datariver.interfaces.http.routes import chat as chat_routes
from datariver.interfaces.http.schemas import (
    ChatQueryRequest,
    ChatQueryResponse,
    ChatRequestPerformanceResponse,
    ChatRouteResponse,
    ChatWorkflowEventResponse,
)


async def test_chat_workflow_stream_emits_server_events_before_final_result(
    monkeypatch: Any,
) -> None:
    async def fake_query_response(
        *,
        workflow_observer: Any = None,
        **_: Any,
    ) -> ChatQueryResponse:
        assert workflow_observer is not None
        workflow_observer.publish(
            event=ChatWorkflowEvent(
                stage=ChatWorkflowStage.AUTHORIZATION,
                status=ChatWorkflowStatus.IN_PROGRESS,
                detail_code="AUTHORIZATION_IN_PROGRESS",
            )
        )
        await asyncio.sleep(0)
        workflow_observer.publish(
            event=ChatWorkflowEvent(
                stage=ChatWorkflowStage.AUTHORIZATION,
                status=ChatWorkflowStatus.COMPLETED,
                detail_code="CHAT_QUERY_AUTHORIZED",
            )
        )
        return ChatQueryResponse(
            session_id=uuid4(),
            request_message_id=uuid4(),
            response_message_id=uuid4(),
            answer="완료된 답변",
            persistence="PERSISTED",
            route=ChatRouteResponse(
                requested_mode=ChatRetrievalMode.AUTO,
                selected_mode=ChatRetrievalMode.GENERAL,
                reason=ChatRouteReason.GENERAL_DEFAULT,
                adapter_state=ChatAdapterState.READY,
            ),
            workflow=[
                ChatWorkflowEventResponse(
                    stage=ChatWorkflowStage.AUTHORIZATION,
                    status=ChatWorkflowStatus.COMPLETED,
                    detail_code="CHAT_QUERY_AUTHORIZED",
                )
            ],
            evidence=[],
            performance=ChatRequestPerformanceResponse(total_ms=1),
        )

    monkeypatch.setattr(chat_routes, "_query_response", fake_query_response)

    frames = [
        frame
        async for frame in chat_routes._stream_chat_query(
            payload=ChatQueryRequest(question="현재 진행 단계를 알려줘"),
            request=cast(Any, object()),
            context=cast(Any, object()),
            session=cast(Any, object()),
        )
    ]

    def payload(frame: str) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(frame.split("data: ", maxsplit=1)[1]))

    assert [frame.split("\n", maxsplit=1)[0] for frame in frames] == [
        "event: workflow",
        "event: workflow",
        "event: result",
    ]
    assert payload(frames[0])["status"] == "IN_PROGRESS"
    assert payload(frames[1])["status"] == "COMPLETED"
    assert payload(frames[2])["answer"] == "완료된 답변"


def test_chat_request_timing_observer_measures_only_server_observed_stages() -> None:
    ticks = iter((1.0, 1.1, 1.125, 1.2))
    observer = chat_routes._ChatRequestTimingObserver(None, clock=lambda: next(ticks))

    observer.publish(
        event=ChatWorkflowEvent(
            stage=ChatWorkflowStage.ROUTING,
            status=ChatWorkflowStatus.IN_PROGRESS,
            detail_code="ROUTING_IN_PROGRESS",
        )
    )
    observer.record(metric=ChatPerformanceMetric.CATALOG_DISCOVERY, duration_ms=7)
    observer.record(metric=ChatPerformanceMetric.VECTOR, duration_ms=11)
    observer.record(metric=ChatPerformanceMetric.VECTOR, duration_ms=9)
    observer.publish(
        event=ChatWorkflowEvent(
            stage=ChatWorkflowStage.ROUTING,
            status=ChatWorkflowStatus.COMPLETED,
            detail_code="ROUTING_COMPLETED",
        )
    )

    performance = observer.response()

    assert performance.routing_ms == 25
    assert performance.retrieval_ms is None
    assert performance.catalog_discovery_ms == 7
    assert performance.vector_ms == 11
    assert performance.total_ms == 200
