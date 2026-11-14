"""Call an LLM for one prompt, or for many prompts in parallel.

- invoke_llm: send one prompt, parse the answer, and ask again (up to
  max_attempts) when the answer can't be parsed.
- invoke_llm_parallel: do that for many user prompts at the same time, on
  threads. Each unique prompt is sent only once.

The caller passes in `parse`, a function that turns the answer text into
something useful (for example the list of mistakes) and raises ValueError,
KeyError or TypeError when the answer is unusable. That keeps this module free
of any knowledge about the answer format.

Error rules:
- The SDKs already retry network errors and 5xx, and rate_limit.py waits on
  429. So an AIError is not retried here: that prompt simply fails and the
  caller leaves it unchanged.
- Only an answer that can't be parsed is asked again.
- A FatalAIError (bad API key, unknown model) is never caught here. It stops
  everything, including requests that have not started yet.

Settings (read from the environment or .env, with defaults):
- LLM_MAX_ATTEMPTS: tries per prompt when the answer can't be parsed (default 3)
- LLM_WORKERS: requests sent at the same time (default 8)
Passing max_attempts or workers to a function overrides these.
"""

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Generic, TypeVar

from utils.environmental_variables import get_int_variable

from .base_llm import AIError, ChatLLM, FatalAIError, LLMAnswer

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 3  # first request + 2 re-asks when the answer can't be parsed
DEFAULT_WORKERS = 8  # requests sent at the same time
MAX_ATTEMPTS_ENV = "LLM_MAX_ATTEMPTS"
WORKERS_ENV = "LLM_WORKERS"

# Errors a parse function raises when the answer has the wrong format or shape.
PARSE_ERRORS = (ValueError, KeyError, TypeError)


@dataclass
class InvokeResult(Generic[T]):
    """What happened for one prompt: the parsed value or an error, plus token use."""

    value: T | None = None  # the parsed answer; None when every attempt failed
    error: str | None = None  # why it failed; None on success
    attempts: int = 0
    input_tokens: int = 0  # summed over all attempts
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def ok(self) -> bool:
        """True when the answer was parsed successfully."""
        return self.error is None and self.attempts > 0

    def add_usage(self, answer: LLMAnswer) -> None:
        """Add the token counts of one answer.

        Args:
            answer: one answer from the model.
        """
        self.input_tokens += answer.input_tokens
        self.output_tokens += answer.output_tokens
        self.cached_input_tokens += answer.cached_input_tokens


def get_max_attempts() -> int:
    """Tries per prompt: LLM_MAX_ATTEMPTS from the environment or .env, else 3.

    Returns:
        The number of tries (at least 1).
    """
    return get_int_variable(MAX_ATTEMPTS_ENV, DEFAULT_MAX_ATTEMPTS)


def get_workers() -> int:
    """Requests sent at the same time: LLM_WORKERS from the environment or .env, else 8.

    Returns:
        The number of requests (at least 1).
    """
    return get_int_variable(WORKERS_ENV, DEFAULT_WORKERS)


def invoke_llm(
    llm: ChatLLM,
    system_prompt: str,
    user_prompt: str,
    parse: Callable[[str], T],
    max_attempts: int | None = None,
) -> InvokeResult[T]:
    """Ask the LLM once, and again if the answer can't be parsed.

    Args:
        llm: the client that sends the request.
        system_prompt: the instructions, the same for every request.
        user_prompt: the text to send.
        parse: turns the answer text into a value; it raises ValueError, KeyError or
            TypeError when the answer is unusable.
        max_attempts: the most tries; None means get_max_attempts().

    Returns:
        The parsed value (or the error if every try failed), the number of tries and the tokens used.

    Raises:
        FatalAIError: every request would fail (bad API key, unknown model).
    """
    if max_attempts is None:
        max_attempts = get_max_attempts()
    result: InvokeResult[T] = InvokeResult()
    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        # Send the request. A failed request has already been retried inside ask(), so give up.
        try:
            answer = llm.ask(system_prompt, user_prompt)
        except AIError as e:
            result.error = str(e)
            logger.warning("LLM request failed: %s", e)
            return result
        result.add_usage(answer)
        # Read the answer. If it can't be read, ask again (next loop).
        try:
            result.value = parse(answer.text)
        except PARSE_ERRORS as e:
            result.error = f"Unusable answer after {attempt} attempt(s): {e}"
            logger.warning("Attempt %d/%d: could not parse the answer: %s", attempt, max_attempts, e)
            continue
        result.error = None
        return result
    return result


def invoke_llm_parallel(
    llm: ChatLLM,
    system_prompt: str,
    user_prompts: Iterable[str],
    parse: Callable[[str], T],
    workers: int | None = None,
    max_attempts: int | None = None,
) -> dict[str, InvokeResult[T]]:
    """Run invoke_llm for every unique user prompt, `workers` at a time.

    Args:
        llm: the client that sends the requests.
        system_prompt: the instructions, the same for every request.
        user_prompts: the texts to send; a repeated text is sent only once.
        parse: turns each answer text into a value (see invoke_llm).
        workers: requests sent at the same time; None means get_workers().
        max_attempts: the most tries per prompt; None means get_max_attempts().

    Returns:
        {user_prompt: InvokeResult}, in the order the prompts were given.

    Raises:
        FatalAIError: every request would fail; requests not started yet are cancelled.
    """
    # Read the settings once here, not once per prompt in every thread.
    if workers is None:
        workers = get_workers()
    if max_attempts is None:
        max_attempts = get_max_attempts()
    unique_prompts = list(dict.fromkeys(user_prompts))  # drops repeats, keeps order
    results: dict[str, InvokeResult[T]] = {}
    # Start one task per prompt; at most `workers` run at the same time.
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(invoke_llm, llm, system_prompt, prompt, parse, max_attempts): prompt
            for prompt in unique_prompts
        }
        # Collect each answer as soon as it is ready.
        try:
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        except FatalAIError:
            # Every other request would fail the same way, so don't start them.
            pool.shutdown(cancel_futures=True)
            raise
    return {prompt: results[prompt] for prompt in unique_prompts}  # back in the original order
