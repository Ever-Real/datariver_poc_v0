from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from datariver.application.errors import ExternalDependencyError
from datariver.domain.common import RateLimitError
from datariver.infrastructure.cache.redis import RedisChatRequestBudgetGuard


class FakeRedis:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *arguments: object) -> object:
        self.calls.append(arguments)
        if self.error is not None:
            raise self.error
        return self.result


def _cache(fake: FakeRedis) -> RedisChatRequestBudgetGuard:
    cache = RedisChatRequestBudgetGuard(
        "redis://127.0.0.1:6379/0",
        password="test-only",
    )
    cache._client = fake  # type: ignore[assignment]  # fixed isolated adapter fake
    return cache


@pytest.mark.asyncio
async def test_chat_budget_reservation_scopes_atomic_keys_and_bounds() -> None:
    fake = FakeRedis([1, 60])
    workspace_id = uuid4()
    subject_id = uuid4()

    await _cache(fake).reserve(
        workspace_id=workspace_id,
        subject_id=subject_id,
        policy_scope=f"governed-{UUID(int=1)}-7-11-{'a' * 64}",
        estimated_tokens=1_200,
        request_limit=30,
        token_limit=120_000,
        window_seconds=60,
    )

    assert len(fake.calls) == 1
    arguments = fake.calls[0]
    assert arguments[1] == 2
    assert str(workspace_id) in str(arguments[2])
    assert str(subject_id) in str(arguments[2])
    assert ":v1:" in str(arguments[2])
    assert f"policy-governed-{UUID(int=1)}-7-11-" + ("a" * 64) in str(arguments[2])
    assert arguments[-4:] == ("1200", "30", "120000", "60")


@pytest.mark.asyncio
async def test_chat_budget_exhaustion_returns_retry_evidence() -> None:
    with pytest.raises(RateLimitError) as captured:
        await _cache(FakeRedis([0, 17])).reserve(
            workspace_id=uuid4(),
            subject_id=uuid4(),
            policy_scope="static-floor-v1",
            estimated_tokens=1_200,
            request_limit=1,
            token_limit=2_048,
            window_seconds=60,
        )

    assert captured.value.details == {"retry_after_seconds": 17}


@pytest.mark.asyncio
async def test_chat_budget_dependency_failure_is_fail_closed() -> None:
    with pytest.raises(ExternalDependencyError) as captured:
        await _cache(FakeRedis(error=RedisConnectionError("offline"))).reserve(
            workspace_id=uuid4(),
            subject_id=uuid4(),
            policy_scope="static-floor-v1",
            estimated_tokens=1_200,
            request_limit=30,
            token_limit=120_000,
            window_seconds=60,
        )

    assert captured.value.details["provider_code"] == "CHAT_BUDGET_UNAVAILABLE"
    assert captured.value.details["retryable"] is True
