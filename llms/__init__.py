"""LLM clients, built on LangChain. Knows nothing about proofreading.

    llm = create_llm("openai")                       # providers.py
    answer = llm.ask(system_prompt, user_prompt)      # base_llm.py -> LLMAnswer
    results = invoke_llm_parallel(llm, system_prompt, user_prompts, parse=my_parser)  # llm_invoke.py

Modules:
    base_llm.py       ChatLLM (one request), LLMAnswer, AIError, FatalAIError
    openai_llm.py     ChatLLM set up for OpenAI
    anthropic_llm.py  ChatLLM set up for Anthropic
    providers.py      create_llm(): pick the client for a --provider name
    llm_invoke.py     invoke_llm / invoke_llm_parallel: parse, re-ask, run in parallel
    rate_limit.py     wait and try again when the provider is rate limiting
"""

from .anthropic_llm import AnthropicLLM
from .base_llm import AIError, ChatLLM, FatalAIError, LLMAnswer
from .llm_invoke import InvokeResult, invoke_llm, invoke_llm_parallel
from .openai_llm import OpenAILLM
from .providers import DEFAULT_PROVIDER, PROVIDERS, create_llm

__all__ = [
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "AIError",
    "AnthropicLLM",
    "ChatLLM",
    "FatalAIError",
    "InvokeResult",
    "LLMAnswer",
    "OpenAILLM",
    "create_llm",
    "invoke_llm",
    "invoke_llm_parallel",
]
