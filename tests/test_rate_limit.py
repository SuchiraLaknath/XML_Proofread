"""Tests for llms/rate_limit.py. Sleeping is faked: the tests record the waits instead."""

import httpx2
import openai
import pytest
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.messages import AIMessage

from llms import AIError, ChatLLM
from llms.rate_limit import (
    DEFAULT_RETRIES,
    MAX_WAIT_SECONDS,
    RETRIES_ENV,
    WAIT_ENV,
    call_with_rate_limit_retry,
)

REQUEST = httpx2.Request("POST", "https://api.example.com")


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every sleep instead of really sleeping."""
    recorded: list[float] = []
    monkeypatch.setattr("llms.rate_limit.sleep", recorded.append)
    return recorded


def rate_limit_error(retry_after: str | None = None) -> Exception:
    """A 429 error as the OpenAI SDK raises it, optionally with a Retry-After header."""
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx2.Response(429, headers=headers, request=REQUEST)
    return openai.RateLimitError("rate limited", response=response, body=None)


class Flaky:
    """A request that fails with the given errors first, then returns "ok"."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def test_no_wait_when_not_rate_limited(waits: list[float]) -> None:
    assert call_with_rate_limit_retry(Flaky()) == "ok"
    assert waits == []


def test_waits_double_each_time(waits: list[float]) -> None:
    request = Flaky(ModelRateLimitError("busy"), ModelRateLimitError("busy"), ModelRateLimitError("busy"))
    assert call_with_rate_limit_retry(request) == "ok"
    assert waits == [10, 20, 40]
    assert request.calls == 4


def test_uses_the_providers_retry_after(waits: list[float]) -> None:
    assert call_with_rate_limit_retry(Flaky(rate_limit_error(retry_after="3"))) == "ok"
    assert waits == [3]


@pytest.mark.parametrize("header", ["Wed, 21 Oct 2026 07:28:00 GMT", ""])
def test_unreadable_retry_after_uses_own_wait(waits: list[float], header: str) -> None:
    call_with_rate_limit_retry(Flaky(rate_limit_error(retry_after=header)))
    assert waits == [10]


def test_long_waits_are_capped(waits: list[float]) -> None:
    call_with_rate_limit_retry(Flaky(rate_limit_error(retry_after="3600")))
    assert waits == [MAX_WAIT_SECONDS]


def test_gives_up_after_the_last_retry(waits: list[float]) -> None:
    request = Flaky(*[ModelRateLimitError("busy")] * (DEFAULT_RETRIES + 1))
    with pytest.raises(ModelRateLimitError):
        call_with_rate_limit_retry(request)
    assert len(waits) == DEFAULT_RETRIES
    assert request.calls == DEFAULT_RETRIES + 1


def test_other_errors_are_not_retried(waits: list[float]) -> None:
    request = Flaky(ValueError("not a rate limit"))
    with pytest.raises(ValueError):
        call_with_rate_limit_retry(request)
    assert waits == [] and request.calls == 1


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch, waits: list[float]) -> None:
    monkeypatch.setenv(RETRIES_ENV, "2")
    monkeypatch.setenv(WAIT_ENV, "1")
    with pytest.raises(ModelRateLimitError):
        call_with_rate_limit_retry(Flaky(*[ModelRateLimitError("busy")] * 3))
    assert waits == [1, 2]


def test_zero_retries_turns_it_off(monkeypatch: pytest.MonkeyPatch, waits: list[float]) -> None:
    monkeypatch.setenv(RETRIES_ENV, "0")
    with pytest.raises(ModelRateLimitError):
        call_with_rate_limit_retry(Flaky(ModelRateLimitError("busy")))
    assert waits == []


# ---------- inside ChatLLM.ask ----------


class FlakyChatModel:
    """A chat model that is rate limited `times` times, then answers."""

    def __init__(self, times: int) -> None:
        self.times = times

    def invoke(self, messages: list) -> AIMessage:
        if self.times > 0:
            self.times -= 1
            raise ModelRateLimitError("busy")
        return AIMessage(content='{"errors": []}', response_metadata={"stop_reason": "end_turn"})


def test_ask_recovers_from_rate_limit(waits: list[float]) -> None:
    answer = ChatLLM("x", "m", FlakyChatModel(times=2)).ask("S", "U")
    assert answer.text == '{"errors": []}'
    assert waits == [10, 20]


def test_ask_gives_up_with_ai_error(waits: list[float]) -> None:
    with pytest.raises(AIError):
        ChatLLM("x", "m", FlakyChatModel(times=DEFAULT_RETRIES + 1)).ask("S", "U")
