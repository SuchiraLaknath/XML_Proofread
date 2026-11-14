"""The OpenAI client (LangChain's ChatOpenAI). OpenAI is the default provider.

Settings:
- JSON mode (response_format), so the answer is always a JSON object.
- Reasoning models (gpt-5, gpt-6, o-series) think before they answer. They don't
  accept temperature=0, so they get a reasoning effort instead (OPENAI_REASONING_EFFORT,
  default "low": enough to tell "a third-party audit" from "a third party", and cheap).
- Older models (gpt-4.1, gpt-4o) get temperature=0, so the same paragraph gets the
  same answer.

Model (first one that is set wins):
1. the --model command-line flag (passed in as `model`)
2. OPENAI_MODEL in the environment or .env
3. DEFAULT_MODEL ("gpt-6.1-terra")

OpenAI caches long prompts by itself, so nothing extra is needed for caching.
The SDK already retries network errors and 5xx, so this module does not
retry. The API key is read from OPENAI_API_KEY.
"""

import openai
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from utils.environmental_variables import get_text_variable

from .base_llm import ChatLLM, FatalAIError

DEFAULT_MODEL = "gpt-6.1-terra"
MODEL_ENV = "OPENAI_MODEL"
DEFAULT_REASONING_EFFORT = "low"
REASONING_EFFORT_ENV = "OPENAI_REASONING_EFFORT"
REASONING_MODEL_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")
JSON_MODE = {"response_format": {"type": "json_object"}}


class OpenAILLM(ChatLLM):
    """ChatLLM set up for OpenAI."""

    def __init__(self, model: str | None = None, chat_model: BaseChatModel | None = None) -> None:
        """Create the OpenAI client.

        Args:
            model: the model name; None means get_model().
            chat_model: only passed by tests (a fake), so they need no network or API key.
        """
        model = model or get_model()
        if chat_model is None:
            chat_model = make_chat_model(model)
        super().__init__(provider="openai", model=model, chat_model=chat_model)


def get_model() -> str:
    """Model name: OPENAI_MODEL from the environment or .env, else gpt-6.1-terra.

    Returns:
        The model name.
    """
    return get_text_variable(MODEL_ENV, DEFAULT_MODEL)


def get_reasoning_effort() -> str:
    """Reasoning effort: OPENAI_REASONING_EFFORT from the environment or .env, else "low".

    Returns:
        The effort, e.g. "low".
    """
    return get_text_variable(REASONING_EFFORT_ENV, DEFAULT_REASONING_EFFORT)


def is_reasoning_model(model: str) -> bool:
    """Tell whether a model thinks before answering (gpt-5, gpt-6, o1, o3, o4).

    Args:
        model: the model name.

    Returns:
        True for a reasoning model, False for others and for "chat" variants.
    """
    name = model.lower()
    return name.startswith(REASONING_MODEL_PREFIXES) and "chat" not in name


def make_chat_model(model: str) -> ChatOpenAI:
    """Create the LangChain chat model with the settings described at the top of this file.

    Args:
        model: the model name.

    Returns:
        The LangChain chat model.

    Raises:
        FatalAIError: the client could not start, for example OPENAI_API_KEY is missing.
    """
    try:
        # Reasoning models reject temperature, so they get a reasoning effort instead.
        if is_reasoning_model(model):
            return ChatOpenAI(model=model, reasoning_effort=get_reasoning_effort(), model_kwargs=JSON_MODE)
        return ChatOpenAI(model=model, temperature=0, model_kwargs=JSON_MODE)
    except openai.OpenAIError as e:  # raised here when OPENAI_API_KEY is missing
        raise FatalAIError(f"OpenAI client could not start: {e}") from e
