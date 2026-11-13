"""The Anthropic (Claude) client (LangChain's ChatAnthropic).

Settings:
- No temperature: current Claude models reject it. ChatAnthropic leaves it
  out of the request when it is not set.
- The system prompt is cached (cache_control), see ChatLLM.make_system_message.
- Refusal fallback: if a safety check declines a request, the API runs it
  again on a suitable fallback model in the same call (fallbacks="default").

Read from the environment or .env (blank or missing = the default):
- Model: the --model flag (passed in as `model`) wins; then ANTHROPIC_MODEL;
  then DEFAULT_MODEL ("claude-opus-5-5").
- ANTHROPIC_MAX_TOKENS: room for the model's thinking plus the answer (default 16000).

The SDK already retries network errors and 5xx, so this module does not
retry. The API key is read from ANTHROPIC_API_KEY.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from utils.environmental_variables import get_int_variable, get_text_variable

from .base_llm import ChatLLM

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_ENV = "ANTHROPIC_MODEL"

# Room for the model's thinking (always on for Claude Opus 5.5) plus the short JSON answer.
DEFAULT_MAX_TOKENS = 16000
MAX_TOKENS_ENV = "ANTHROPIC_MAX_TOKENS"

# Beta flag that turns on the server-side refusal fallback. Not a setting: it is
# part of the API contract, and a wrong value would make every request fail.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM(ChatLLM):
    """ChatLLM set up for Anthropic."""

    def __init__(self, model: str | None = None, chat_model: BaseChatModel | None = None) -> None:
        """Create the Anthropic client, with system prompt caching on. model defaults to get_model().

        chat_model is only passed by tests (a fake), so they need no network or API key.
        """
        model = model or get_model()
        if chat_model is None:
            chat_model = make_chat_model(model, get_max_tokens())
        super().__init__(provider="anthropic", model=model, chat_model=chat_model, cache_system_prompt=True)


def get_model() -> str:
    """Model name: ANTHROPIC_MODEL from the environment or .env, else claude-opus-5-5."""
    return get_text_variable(MODEL_ENV, DEFAULT_MODEL)


def get_max_tokens() -> int:
    """Answer size limit: ANTHROPIC_MAX_TOKENS from the environment or .env, else 16000."""
    return get_int_variable(MAX_TOKENS_ENV, DEFAULT_MAX_TOKENS)


def make_chat_model(model: str, max_tokens: int) -> ChatAnthropic:
    """Create the LangChain chat model with the settings described at the top of this file."""
    return ChatAnthropic(
        model=model,
        max_tokens=max_tokens,
        betas=[FALLBACK_BETA],
        # ChatAnthropic has no field for this yet, so it goes into the request as-is.
        model_kwargs={"fallbacks": "default"},
    )
