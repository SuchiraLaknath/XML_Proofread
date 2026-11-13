"""Tests for the LLM clients. No real API is ever called and no API key is needed.

- Most tests give ChatLLM a fake chat model.
- The provider tests build the real LangChain chat model and either check its
  settings or answer its HTTP request with a fake response (offline).
"""

import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage
from dotenv import dotenv_values
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import ModelAuthenticationError, ModelNotFoundError, ModelRateLimitError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from llms import (
    AIError,
    AnthropicLLM,
    ChatLLM,
    FatalAIError,
    OpenAILLM,
    anthropic_llm,
    create_llm,
    openai_llm,
)
from llms.anthropic_llm import FALLBACK_BETA
from llms.llm_invoke import DEFAULT_MAX_ATTEMPTS, DEFAULT_WORKERS
from llms.rate_limit import DEFAULT_RETRIES, DEFAULT_WAIT_SECONDS

REQUEST = httpx2.Request("POST", "https://api.example.com")


def status_error(error_class: type, status: int) -> Exception:
    """Build an SDK error the way the SDK itself would raise it."""
    return error_class("failed", response=httpx2.Response(status, request=REQUEST), body=None)


class FakeChatModel:
    """Stands in for a LangChain chat model: records calls, returns or raises."""

    def __init__(self, reply: AIMessage | None = None, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list] = []

    def invoke(self, messages: list) -> AIMessage:
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.reply


def make_reply(content: Any = '{"errors": []}', stop_reason: str = "end_turn") -> AIMessage:
    return AIMessage(
        content=content,
        response_metadata={"stop_reason": stop_reason},
        usage_metadata={
            "input_tokens": 120,
            "output_tokens": 8,
            "total_tokens": 128,
            "input_token_details": {"cache_read": 100},
        },
    )


# ---------- ChatLLM (shared by both providers) ----------


def test_sends_system_and_user_messages() -> None:
    fake = FakeChatModel(make_reply())
    OpenAILLM(chat_model=fake).ask("SYSTEM", "USER")
    assert fake.calls[0] == [SystemMessage(content="SYSTEM"), HumanMessage(content="USER")]


def test_anthropic_caches_the_system_prompt() -> None:
    fake = FakeChatModel(make_reply())
    AnthropicLLM(chat_model=fake).ask("SYSTEM", "USER")
    block = {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    assert fake.calls[0][0] == SystemMessage(content=[block])


def test_returns_text_and_tokens() -> None:
    answer = OpenAILLM(chat_model=FakeChatModel(make_reply())).ask("S", "U")
    assert answer.text == '{"errors": []}'
    assert (answer.input_tokens, answer.output_tokens, answer.cached_input_tokens) == (120, 8, 100)


def test_keeps_only_text_blocks() -> None:
    content = [
        {"type": "thinking", "thinking": ""},
        {"type": "text", "text": '{"errors": '},
        {"type": "text", "text": "[]}"},
    ]
    answer = AnthropicLLM(chat_model=FakeChatModel(make_reply(content))).ask("S", "U")
    assert answer.text == '{"errors": []}'


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens", "length", "content_filter"])
def test_unusable_stop_reason_raises_ai_error(stop_reason: str) -> None:
    with pytest.raises(AIError):
        ChatLLM("x", "m", FakeChatModel(make_reply(stop_reason=stop_reason))).ask("S", "U")


def test_empty_answer_raises_ai_error() -> None:
    content = [{"type": "thinking", "thinking": ""}]
    with pytest.raises(AIError):
        ChatLLM("x", "m", FakeChatModel(make_reply(content))).ask("S", "U")


@pytest.mark.parametrize(
    "error, expected",
    [
        (ModelAuthenticationError("bad key"), FatalAIError),
        (ModelNotFoundError("unknown model"), FatalAIError),
        (ModelRateLimitError("slow down"), AIError),
        (status_error(anthropic.OverloadedError, 529), AIError),  # SDK error LangChain did not map
        (TypeError("Could not resolve authentication method"), FatalAIError),
    ],
)
def test_errors_are_translated(error: Exception, expected: type) -> None:
    with pytest.raises(expected):
        ChatLLM("x", "m", FakeChatModel(error=error)).ask("S", "U")


def test_fatal_error_is_not_caught_as_ai_error() -> None:
    assert not issubclass(FatalAIError, AIError)


# ---------- OpenAI: real ChatOpenAI, fake HTTP ----------


def openai_llm_with_fake_http(handler: Any) -> OpenAILLM:
    chat_model = ChatOpenAI(
        model="gpt-4.1",
        api_key="test-key",
        base_url="https://fake.invalid/v1",
        max_retries=0,
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}},
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenAILLM(chat_model=chat_model)


def openai_body(finish_reason: str = "stop", content: str = '{"errors": []}') -> dict:
    return {
        "id": "c",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4.1",
        "choices": [
            {"index": 0, "finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 8,
            "total_tokens": 128,
            "prompt_tokens_details": {"cached_tokens": 100},
        },
    }


def test_openai_chat_model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default model is a reasoning model: a reasoning effort, no temperature."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    chat_model = OpenAILLM().chat_model
    assert chat_model.model_name == "gpt-6.1-terra"
    assert chat_model.reasoning_effort == "low"
    assert chat_model.temperature is None  # never sent
    assert chat_model.model_kwargs == {"response_format": {"type": "json_object"}}


def test_older_openai_model_uses_temperature_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    chat_model = OpenAILLM("gpt-4.1").chat_model
    assert chat_model.temperature == 0
    assert chat_model.reasoning_effort is None
    assert chat_model.model_kwargs == {"response_format": {"type": "json_object"}}


def test_reasoning_effort_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(openai_llm.REASONING_EFFORT_ENV, " medium ")
    assert OpenAILLM().chat_model.reasoning_effort == "medium"


@pytest.mark.parametrize(
    "model, expected",
    [
        ("gpt-6.1-terra", True),
        ("gpt-6-luna", True),
        ("gpt-5-mini", True),
        ("o3", True),
        ("gpt-5-chat-latest", False),
        ("gpt-4.1", False),
        ("gpt-4o-mini", False),
    ],
)
def test_is_reasoning_model(model: str, expected: bool) -> None:
    assert openai_llm.is_reasoning_model(model) is expected


def test_reasoning_model_request_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request our settings produce: reasoning_effort and JSON mode, never temperature."""
    sent: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=openai_body())

    def chat_openai_with_fake_http(**settings: Any) -> ChatOpenAI:
        return ChatOpenAI(
            **settings,
            api_key="test-key",
            base_url="https://fake.invalid/v1",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        )

    monkeypatch.setattr(openai_llm, "ChatOpenAI", chat_openai_with_fake_http)
    OpenAILLM().ask("SYSTEM", "USER")
    assert sent[0]["model"] == "gpt-6.1-terra"
    assert sent[0]["reasoning_effort"] == "low"
    assert "temperature" not in sent[0]
    assert sent[0]["response_format"] == {"type": "json_object"}


def test_openai_end_to_end_offline() -> None:
    sent: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=openai_body())

    answer = openai_llm_with_fake_http(handler).ask("SYSTEM", "USER")
    assert sent[0]["temperature"] == 0
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert sent[0]["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "USER"},
    ]
    assert answer.text == '{"errors": []}'
    assert (answer.input_tokens, answer.output_tokens, answer.cached_input_tokens) == (120, 8, 100)


def test_openai_cut_off_answer_raises_ai_error() -> None:
    llm = openai_llm_with_fake_http(lambda request: httpx2.Response(200, json=openai_body("length", '{"err')))
    with pytest.raises(AIError):
        llm.ask("S", "U")


@pytest.mark.parametrize(
    "status, expected", [(401, FatalAIError), (403, FatalAIError), (404, FatalAIError), (500, AIError)]
)
def test_openai_http_errors(status: int, expected: type) -> None:
    llm = openai_llm_with_fake_http(lambda request: httpx2.Response(status, json={"error": {"message": "x"}}))
    with pytest.raises(expected):
        llm.ask("S", "U")


def test_openai_missing_key_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    with pytest.raises(FatalAIError):
        OpenAILLM()


# ---------- Anthropic: real ChatAnthropic, fake API response ----------


def test_anthropic_chat_model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    chat_model = AnthropicLLM().chat_model
    assert chat_model.model == "claude-opus-5-5"
    assert chat_model.max_tokens == 16000
    assert chat_model.temperature is None  # never sent
    assert chat_model.betas == [FALLBACK_BETA]
    assert chat_model.model_kwargs == {"fallbacks": "default"}


# ---------- model settings from .env ----------


def test_models_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv(openai_llm.MODEL_ENV, " gpt-4.1-mini ")
    monkeypatch.setenv(anthropic_llm.MODEL_ENV, "claude-sonnet-5-5")
    monkeypatch.setenv(anthropic_llm.MAX_TOKENS_ENV, "8000")
    assert OpenAILLM().chat_model.model_name == "gpt-4.1-mini"
    anthropic_client = AnthropicLLM()
    assert anthropic_client.model == "claude-sonnet-5-5"
    assert anthropic_client.chat_model.max_tokens == 8000


def test_model_argument_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The --model flag is passed as `model` and must beat .env."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(openai_llm.MODEL_ENV, "gpt-4.1-mini")
    assert create_llm("openai", "gpt-4.1-nano").model == "gpt-4.1-nano"


def test_blank_model_setting_uses_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(openai_llm.MODEL_ENV, "   ")
    assert OpenAILLM().model == openai_llm.DEFAULT_MODEL


@pytest.mark.parametrize("bad_value", ["lots", "0", "-5"])
def test_bad_max_tokens_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, bad_value: str
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv(anthropic_llm.MAX_TOKENS_ENV, bad_value)
    assert AnthropicLLM().chat_model.max_tokens == anthropic_llm.DEFAULT_MAX_TOKENS
    assert anthropic_llm.MAX_TOKENS_ENV in caplog.text


def test_anthropic_end_to_end_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only the step that calls the SDK, so LangChain's own request and
    reply handling is tested for real."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    message = BetaMessage.model_validate(
        {
            "id": "m",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "text", "text": '{"errors": []}'},
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 20,
                "output_tokens": 8,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 0,
            },
        }
    )
    sent: list[dict] = []

    class RawResponse:
        headers: dict = {}

        def parse(self) -> BetaMessage:
            return message

    def fake_create(self: ChatAnthropic, payload: dict) -> RawResponse:
        sent.append(payload)
        return RawResponse()

    monkeypatch.setattr(ChatAnthropic, "_create", fake_create)
    answer = AnthropicLLM().ask("SYSTEM", "USER")

    payload = sent[0]
    assert "temperature" not in payload
    assert payload["system"] == [{"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}]
    assert payload["betas"] == [FALLBACK_BETA]
    assert payload["fallbacks"] == "default"
    assert answer.text == '{"errors": []}'
    # Anthropic counts cached tokens apart; LangChain adds them into the input total.
    assert (answer.input_tokens, answer.output_tokens, answer.cached_input_tokens) == (120, 8, 100)


# ---------- create_llm ----------


def test_create_llm_uses_default_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert create_llm().model == "gpt-6.1-terra"
    assert create_llm("anthropic").model == "claude-opus-5-5"


def test_create_llm_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert create_llm("anthropic", "claude-sonnet-5-5").model == "claude-sonnet-5-5"


def test_create_llm_empty_key_is_reported_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_API_KEY= left empty in .env must say "missing", not fail later with a 401."""
    monkeypatch.setenv("OPENAI_API_KEY", "  ")
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    with pytest.raises(FatalAIError, match="Missing credentials"):
        create_llm("openai")


def test_env_example_matches_the_defaults() -> None:
    """Keep .env.example in step with the code: every setting listed, with its real default."""
    example = dotenv_values(Path(__file__).parent.parent / ".env.example")
    assert example == {
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        openai_llm.MODEL_ENV: openai_llm.DEFAULT_MODEL,
        openai_llm.REASONING_EFFORT_ENV: openai_llm.DEFAULT_REASONING_EFFORT,
        anthropic_llm.MODEL_ENV: anthropic_llm.DEFAULT_MODEL,
        anthropic_llm.MAX_TOKENS_ENV: str(anthropic_llm.DEFAULT_MAX_TOKENS),
        "LLM_MAX_ATTEMPTS": str(DEFAULT_MAX_ATTEMPTS),
        "LLM_WORKERS": str(DEFAULT_WORKERS),
        "LLM_RATE_LIMIT_RETRIES": str(DEFAULT_RETRIES),
        "LLM_RATE_LIMIT_WAIT": str(DEFAULT_WAIT_SECONDS),
    }


def test_create_llm_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        create_llm("gemini")
