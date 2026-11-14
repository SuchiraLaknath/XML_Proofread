"""Choose the LLM client for a --provider name.

    llm = create_llm("anthropic")                       # model from .env, else the default
    llm = create_llm("openai", model="gpt-4.1-mini")    # this model, whatever .env says

To add a provider: write a small ChatLLM subclass (like openai_llm.py) and add
it to PROVIDERS. The command line's --provider choices come from PROVIDERS.
"""

import os

from dotenv import load_dotenv

from .anthropic_llm import AnthropicLLM
from .openai_llm import OpenAILLM

# --provider name -> the client class for it.
PROVIDERS: dict[str, type[OpenAILLM] | type[AnthropicLLM]] = {
    "openai": OpenAILLM,
    "anthropic": AnthropicLLM,
}
DEFAULT_PROVIDER = "openai"

API_KEY_VARIABLES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def create_llm(provider: str = DEFAULT_PROVIDER, model: str | None = None) -> OpenAILLM | AnthropicLLM:
    """Return the client for a provider.

    Args:
        provider: a name from PROVIDERS, e.g. "openai" or "anthropic".
        model: the model name; None means OPENAI_MODEL / ANTHROPIC_MODEL from .env,
            or else the provider's built-in default.

    Returns:
        The client, ready to send requests.

    Raises:
        ValueError: the provider name is unknown.
        FatalAIError: the client could not start, for example the API key is missing.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Choose one of: {', '.join(PROVIDERS)}")

    # API keys may live in .env. Variables already set in the environment win.
    load_dotenv()
    forget_empty_api_keys()
    return PROVIDERS[provider](model=model)


def forget_empty_api_keys() -> None:
    """Treat a key left empty in .env (OPENAI_API_KEY=) as not set.

    Otherwise the SDK would send an empty key and report a confusing "401"
    instead of clearly saying the key is missing.
    """
    for name in API_KEY_VARIABLES:
        if name in os.environ and not os.environ[name].strip():
            del os.environ[name]
