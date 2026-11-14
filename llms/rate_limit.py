"""Wait and try again when the provider says "too many requests" (HTTP 429).

The OpenAI and Anthropic SDKs already retry a 429 twice, with short pauses.
When a rate limit lasts longer than that, this module waits longer and tries
again, so the paragraph is not given up too early.

How long to wait before each new try:
1. If the provider says how long (the Retry-After header), wait that long.
2. Otherwise wait LLM_RATE_LIMIT_WAIT seconds, doubling each time:
   10 s, 20 s, 40 s, ...
Every wait is capped at MAX_WAIT_SECONDS.

Settings (read from the environment or .env, with defaults):
- LLM_RATE_LIMIT_RETRIES: how many times to wait and try again (default 3, 0 = never)
- LLM_RATE_LIMIT_WAIT: first wait in seconds when the provider gives none (default 10)
"""

import logging
from collections.abc import Callable
from time import sleep
from typing import TypeVar

import anthropic
import openai
from langchain_core.exceptions import ModelRateLimitError

from utils.environmental_variables import get_int_variable

logger = logging.getLogger(__name__)

T = TypeVar("T")

# LangChain raises ModelRateLimitError; the plain SDK errors are listed too, just in case.
RATE_LIMIT_ERRORS = (ModelRateLimitError, openai.RateLimitError, anthropic.RateLimitError)

DEFAULT_RETRIES = 3
DEFAULT_WAIT_SECONDS = 10
MAX_WAIT_SECONDS = 120
RETRIES_ENV = "LLM_RATE_LIMIT_RETRIES"
WAIT_ENV = "LLM_RATE_LIMIT_WAIT"


def get_rate_limit_retries() -> int:
    """How many times to wait and try again: LLM_RATE_LIMIT_RETRIES, else 3.

    Returns:
        The number of retries (0 means never retry).
    """
    return get_int_variable(RETRIES_ENV, DEFAULT_RETRIES, minimum=0)


def get_rate_limit_wait() -> int:
    """First wait in seconds: LLM_RATE_LIMIT_WAIT, else 10.

    Returns:
        The first wait in seconds (at least 1).
    """
    return get_int_variable(WAIT_ENV, DEFAULT_WAIT_SECONDS, minimum=1)


def call_with_rate_limit_retry(request: Callable[[], T]) -> T:
    """Run request(). If it is rate limited, wait and run it again.

    Args:
        request: a function that sends one request and returns its reply.

    Returns:
        What request() returned.

    Raises:
        ModelRateLimitError (or the SDK's RateLimitError): still rate limited after the
            last retry. Any other error is raised straight away, without waiting.
    """
    max_retries = get_rate_limit_retries()
    first_wait = get_rate_limit_wait()
    retry = 0
    while True:
        try:
            return request()
        except RATE_LIMIT_ERRORS as error:
            if retry >= max_retries:  # out of retries: let the caller handle it
                raise
            retry += 1
            wait = seconds_to_wait(error, first_wait, retry)
            logger.warning(
                "Rate limited by the provider. Waiting %.0f s before retry %d of %d.",
                wait,
                retry,
                max_retries,
            )
            sleep(wait)


def seconds_to_wait(error: Exception, first_wait: int, retry: int) -> float:
    """How long to wait before retry number `retry`.

    Args:
        error: the rate limit error; it may carry the provider's Retry-After header.
        first_wait: the first wait in seconds, used when the provider gives none.
        retry: which retry this is: 1, 2, 3, ...

    Returns:
        The wait in seconds, at most MAX_WAIT_SECONDS.
    """
    # The provider knows best how long to wait, so use its number when it sends one.
    retry_after = read_retry_after(error)
    if retry_after is not None:
        return min(retry_after, MAX_WAIT_SECONDS)
    doubled = first_wait * 2 ** (retry - 1)  # 10, 20, 40, ...
    return min(doubled, MAX_WAIT_SECONDS)


def read_retry_after(error: Exception) -> float | None:
    """Read the Retry-After header of a rate limit error.

    Args:
        error: the rate limit error.

    Returns:
        The wait in seconds, or None if the provider sent none (or sent a date).
    """
    # The header lives on the HTTP response, which LangChain keeps on the error.
    response = getattr(error, "response", None)
    if response is None:
        return None
    value = response.headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:  # Retry-After can also be a date; then use our own wait
        return None
