"""Shared code for the LLM clients in this folder (built on LangChain).

LangChain gives OpenAI and Anthropic the same interface (`chat_model.invoke`),
so one class, ChatLLM, does the work for both:

    llm.provider   # "openai" or "anthropic"
    llm.model      # model name sent to the API
    llm.ask(system_prompt, user_prompt) -> LLMAnswer

openai_llm.py and anthropic_llm.py only set up their LangChain chat model with
the right settings for that provider.

The clients only send text and return text. Building the prompts and reading
the JSON answer is the job of the caller (proof_read_process/ai_proofreader.py).

Errors are sorted into two kinds, so the caller knows what to do:
- AIError: this one request failed; leave that paragraph unchanged and go on.
- FatalAIError: every request will fail (bad API key, unknown model); stop the run.
"""

from dataclasses import dataclass

import anthropic
import openai
from langchain_core.exceptions import (
    ModelAuthenticationError,
    ModelError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .rate_limit import call_with_rate_limit_retry

# These fail on every request (bad API key, no access, unknown model),
# so there is no point in going on with the run.
FATAL_ERRORS = (ModelAuthenticationError, ModelPermissionDeniedError, ModelNotFoundError)

# These fail only the current request. LangChain turns most API errors into
# ModelError, but a few SDK errors come through unchanged (for example OpenAI's
# LengthFinishReasonError when a JSON answer is cut off).
REQUEST_ERRORS = (ModelError, openai.OpenAIError, anthropic.AnthropicError)

# Stop reasons that mean the answer can't be used: the model declined
# (refusal, content_filter) or the answer was cut off (max_tokens, length).
UNUSABLE_STOP_REASONS = {"refusal", "content_filter", "max_tokens", "length"}


@dataclass
class LLMAnswer:
    """The raw text the model returned, plus token counts for the report."""

    text: str
    input_tokens: int = 0  # all input tokens, including the cached ones
    output_tokens: int = 0
    cached_input_tokens: int = 0  # input tokens read from the prompt cache


class AIError(RuntimeError):
    """One request failed. The caller leaves that paragraph unchanged."""


class FatalAIError(RuntimeError):
    """A problem that will fail every request (bad API key, unknown model).

    This is deliberately not a subclass of AIError, so code that catches
    AIError for one paragraph does not swallow it. The caller stops the run.
    """


class ChatLLM:
    """Sends a system prompt and a user prompt to a LangChain chat model."""

    def __init__(
        self,
        provider: str,
        model: str,
        chat_model: BaseChatModel,
        cache_system_prompt: bool = False,
    ) -> None:
        """Wrap a LangChain chat model.

        Args:
            provider: the name shown in messages, e.g. "openai".
            model: the model name, e.g. "gpt-6.1-terra".
            chat_model: the LangChain chat model that sends the request.
            cache_system_prompt: mark the system prompt for prompt caching (Anthropic needs this;
                OpenAI caches long prompts by itself).
        """
        self.provider = provider
        self.model = model
        self.chat_model = chat_model
        self.cache_system_prompt = cache_system_prompt

    def ask(self, system_prompt: str, user_prompt: str) -> LLMAnswer:
        """Send the two prompts and return the model's answer.

        When the provider is rate limiting, this waits and tries again
        (see rate_limit.py) before giving up.

        Args:
            system_prompt: the instructions, the same for every request.
            user_prompt: the text to send.

        Returns:
            The answer text and its token counts.

        Raises:
            AIError: this request failed; the caller leaves that paragraph unchanged.
            FatalAIError: every request would fail (bad API key, no access, unknown model).
        """
        messages = [self.make_system_message(system_prompt), HumanMessage(content=user_prompt)]

        def send_once() -> AIMessage:
            """Send the request one time (call_with_rate_limit_retry may call this again)."""
            return self.chat_model.invoke(messages)

        # Send the request (waiting and retrying while rate limited), then sort any
        # error into "stop the run" or "this request failed".
        try:
            reply = call_with_rate_limit_retry(send_once)
        except FATAL_ERRORS as e:
            raise FatalAIError(f"{self.provider} rejected the request (model {self.model}): {e}") from e
        except REQUEST_ERRORS as e:
            raise AIError(f"{self.provider} request failed: {e}") from e
        except TypeError as e:
            # langchain-anthropic raises TypeError before sending when no API key is found.
            raise FatalAIError(f"{self.provider} request could not be sent: {e}") from e
        return to_answer(reply)

    def make_system_message(self, text: str) -> SystemMessage:
        """Build the system message, marked for prompt caching if asked.

        Args:
            text: the system prompt.

        Returns:
            The LangChain system message.
        """
        if not self.cache_system_prompt:
            return SystemMessage(content=text)
        # The system prompt is the same for every paragraph, so after the
        # first request it is read from the cache (faster and cheaper).
        block = {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}
        return SystemMessage(content=[block])


def to_answer(reply: AIMessage) -> LLMAnswer:
    """Take the text and token counts out of a LangChain reply.

    Args:
        reply: the model's reply.

    Returns:
        The answer text and its token counts.

    Raises:
        AIError: the model refused, the answer was cut off, or it holds no text.
    """
    metadata = reply.response_metadata
    # Anthropic calls it stop_reason, OpenAI calls it finish_reason.
    stop_reason = metadata.get("stop_reason") or metadata.get("finish_reason")
    if stop_reason in UNUSABLE_STOP_REASONS:
        raise AIError(f"The model gave no usable answer (stop reason: {stop_reason})")

    # .text joins the text blocks and skips others, such as thinking blocks.
    text = reply.text
    if not text.strip():
        raise AIError("The model returned no text")

    # LangChain reports the same token fields for every provider.
    usage = reply.usage_metadata or {}
    details = usage.get("input_token_details") or {}
    return LLMAnswer(
        text=text,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cached_input_tokens=details.get("cache_read") or 0,
    )
