"""Tests for llms/llm_invoke.py. A fake LLM is used: no network."""

import json
import threading
from collections import Counter

import pytest

from llms import (
    AIError,
    FatalAIError,
    LLMAnswer,
    invoke_llm,
    invoke_llm_parallel,
)
from llms.llm_invoke import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_WORKERS,
    MAX_ATTEMPTS_ENV,
    WORKERS_ENV,
    get_max_attempts,
    get_workers,
)

MAX_ATTEMPTS = DEFAULT_MAX_ATTEMPTS


@pytest.fixture(autouse=True)
def no_llm_settings_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with the default settings, whatever the developer's .env says."""
    monkeypatch.setenv(MAX_ATTEMPTS_ENV, "")
    monkeypatch.setenv(WORKERS_ENV, "")


class FakeLLM:
    """Answers from a script: each user prompt maps to a list of replies, used in order.

    A reply is answer text, or an exception to raise.
    """

    def __init__(self, script: dict[str, list[str | Exception]]) -> None:
        self.script = {prompt: list(replies) for prompt, replies in script.items()}
        self.calls: Counter[str] = Counter()
        self.lock = threading.Lock()  # invoke_llm_parallel calls ask() from many threads

    def ask(self, system_prompt: str, user_prompt: str) -> LLMAnswer:
        with self.lock:
            self.calls[user_prompt] += 1
            reply = self.script[user_prompt].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMAnswer(text=reply, input_tokens=100, output_tokens=10, cached_input_tokens=90)


GOOD = '{"errors": []}'


def parse(text: str) -> list:
    return json.loads(text)["errors"]


# ---------- invoke_llm ----------


def test_success_on_first_attempt() -> None:
    result = invoke_llm(FakeLLM({"p": [GOOD]}), "S", "p", parse)
    assert result.ok and result.value == [] and result.attempts == 1
    assert (result.input_tokens, result.output_tokens, result.cached_input_tokens) == (100, 10, 90)


@pytest.mark.parametrize("bad_answer", ["not json", '{"no_errors_key": 1}', "[1, 2]"])
def test_unparsable_answer_is_asked_again(bad_answer: str) -> None:
    llm = FakeLLM({"p": [bad_answer, GOOD]})
    result = invoke_llm(llm, "S", "p", parse)
    assert result.ok and result.attempts == 2
    assert result.input_tokens == 200  # tokens of both attempts are counted


def test_gives_up_after_max_attempts() -> None:
    llm = FakeLLM({"p": ["bad"] * MAX_ATTEMPTS})
    result = invoke_llm(llm, "S", "p", parse)
    assert not result.ok and result.value is None
    assert result.attempts == MAX_ATTEMPTS and llm.calls["p"] == MAX_ATTEMPTS
    assert "Unusable answer" in result.error


def test_ai_error_is_not_retried() -> None:
    llm = FakeLLM({"p": [AIError("server down"), GOOD]})
    result = invoke_llm(llm, "S", "p", parse)
    assert not result.ok and result.error == "server down"
    assert llm.calls["p"] == 1


def test_fatal_error_is_raised() -> None:
    with pytest.raises(FatalAIError):
        invoke_llm(FakeLLM({"p": [FatalAIError("bad key")]}), "S", "p", parse)


# ---------- invoke_llm_parallel ----------


def test_parallel_sends_each_unique_prompt_once_and_keeps_order() -> None:
    llm = FakeLLM({"a": [GOOD], "b": [GOOD], "c": [GOOD]})
    results = invoke_llm_parallel(llm, "S", ["c", "a", "c", "b", "a"], parse, workers=3)
    assert list(results) == ["c", "a", "b"]
    assert all(llm.calls[p] == 1 for p in "abc")


def test_parallel_one_failure_does_not_affect_others() -> None:
    llm = FakeLLM({"good": [GOOD], "down": [AIError("timeout")], "messy": ["bad", GOOD]})
    results = invoke_llm_parallel(llm, "S", ["good", "down", "messy"], parse)
    assert results["good"].ok
    assert not results["down"].ok
    assert results["messy"].ok and results["messy"].attempts == 2


def test_parallel_fatal_error_stops_the_run() -> None:
    llm = FakeLLM({"a": [GOOD], "b": [FatalAIError("bad key")]})
    with pytest.raises(FatalAIError):
        invoke_llm_parallel(llm, "S", ["a", "b"], parse, workers=1)


def test_parallel_with_no_prompts() -> None:
    assert invoke_llm_parallel(FakeLLM({}), "S", [], parse) == {}


# ---------- settings from the environment / .env ----------


def test_settings_default_when_not_set() -> None:
    assert get_max_attempts() == DEFAULT_MAX_ATTEMPTS
    assert get_workers() == DEFAULT_WORKERS


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ATTEMPTS_ENV, "5")
    monkeypatch.setenv(WORKERS_ENV, " 2 ")
    assert get_max_attempts() == 5
    assert get_workers() == 2


@pytest.mark.parametrize("bad_value", ["abc", "2.5", "0", "-3"])
def test_bad_settings_fall_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, bad_value: str
) -> None:
    monkeypatch.setenv(WORKERS_ENV, bad_value)
    assert get_workers() == DEFAULT_WORKERS
    assert WORKERS_ENV in caplog.text  # the user is told why


def test_invoke_uses_max_attempts_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ATTEMPTS_ENV, "2")
    llm = FakeLLM({"p": ["bad", "bad", GOOD]})
    result = invoke_llm(llm, "S", "p", parse)
    assert not result.ok and llm.calls["p"] == 2


def test_argument_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ATTEMPTS_ENV, "1")
    llm = FakeLLM({"p": ["bad", GOOD]})
    assert invoke_llm(llm, "S", "p", parse, max_attempts=2).ok
