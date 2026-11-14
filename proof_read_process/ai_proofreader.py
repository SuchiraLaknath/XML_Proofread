"""Ask the AI for the mistakes in each paragraph and read its JSON answer.

The AI never rewrites a paragraph. It answers with a JSON list of mistakes:

    {"errors": [{"original": "john", "correction": "John",
                 "type": "capitalization", "reason": "Names start with a capital letter"}]}

parse_ai_answer() turns that answer into Mistake objects. It forgives small
problems (code fences around the JSON, "style guide" instead of "styleguide")
and skips single bad items. It raises ValueError only when the whole answer is
unusable, which makes llms.invoke_llm ask the AI again.

Proofreader.check_all() sends every unique paragraph text to the AI once, in
parallel. main.py builds the Proofreader; tests use a fake one instead.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from llms import ChatLLM, InvokeResult, invoke_llm_parallel

from .prompts import ProofreadPrompts, build_user_prompt

logger = logging.getLogger(__name__)

ERROR_TYPES = ("grammar", "spelling", "punctuation", "capitalization", "clarity", "styleguide")

# Other names the AI sometimes uses, written without spaces, "-" or "_".
TYPE_ALIASES = {
    "styleguide": "styleguide",
    "style": "styleguide",
    "houserule": "styleguide",
    "housestyle": "styleguide",
    "capitalisation": "capitalization",
    "case": "capitalization",
    "spell": "spelling",
    "typo": "spelling",
    "grammatical": "grammar",
    "wordchoice": "grammar",
    "punctuations": "punctuation",
    "readability": "clarity",
    "wordiness": "clarity",
}

CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass(frozen=True)
class Mistake:
    """One mistake the AI found: the exact text, its correction, the type and why."""

    original: str
    correction: str
    type: str
    reason: str = ""


CheckResult = InvokeResult[list[Mistake]]


class Checker(Protocol):
    """Anything that can check many paragraph texts (the real Proofreader or a test fake)."""

    def check_all(self, texts: list[str], workers: int | None = None) -> dict[str, CheckResult]:
        """Check every text and return the results.

        Args:
            texts: the paragraph texts to check.
            workers: requests sent at the same time; None means the default.

        Returns:
            {text: result} for every text.
        """
        ...


class Proofreader:
    """Checks paragraph texts with an LLM. The system prompt is the same for every request."""

    def __init__(self, llm: ChatLLM, prompts: ProofreadPrompts, system_prompt: str) -> None:
        """Store what every request needs.

        Args:
            llm: the client that sends the requests.
            prompts: the templates each user prompt is built from.
            system_prompt: the filled-in system prompt, sent with every request.
        """
        self.llm = llm
        self.prompts = prompts
        # Built once per run (instructions + style guide). Sending the exact same
        # system prompt with every paragraph lets the provider serve it from its cache.
        self.system_prompt = system_prompt

    def check_all(self, texts: list[str], workers: int | None = None) -> dict[str, CheckResult]:
        """Check every unique text once, in parallel.

        Args:
            texts: the paragraph texts to check.
            workers: requests sent at the same time; None means LLM_WORKERS, or 8.

        Returns:
            {text: result}; each result holds the Mistakes, or the error if the request failed.

        Raises:
            FatalAIError: every request would fail (bad API key, unknown model).
        """
        # Step 1: turn each paragraph text into its user prompt. We remember which
        # text each prompt came from, so the answers can be matched back later.
        prompt_to_text = {build_user_prompt(self.prompts, text): text for text in texts}

        # Step 2: send all prompts to the AI at the same time (`workers` at once).
        # parse_ai_answer turns each JSON answer into a list of Mistakes; an answer
        # that can't be read is asked again. A failed request never stops the others.
        results = invoke_llm_parallel(
            self.llm, self.system_prompt, list(prompt_to_text), parse=parse_ai_answer, workers=workers
        )

        # Step 3: key the results by paragraph text instead of by prompt, because
        # the pipeline looks them up by each paragraph's text.
        return {prompt_to_text[prompt]: result for prompt, result in results.items()}


def parse_ai_answer(answer: str) -> list[Mistake]:
    """Turn the AI's answer into Mistakes.

    Args:
        answer: the AI's answer text (JSON).

    Returns:
        The usable mistakes, in the order the AI listed them. Bad items are skipped.

    Raises:
        ValueError: the answer is not JSON or has no "errors" list, so the AI is asked again.
    """
    items = read_error_list(answer)
    # Keep the good items; a bad one is skipped without losing the others.
    mistakes = []
    for item in items:
        mistake = to_mistake(item)
        if mistake is not None:
            mistakes.append(mistake)
    return mistakes


def read_error_list(answer: str) -> list[Any]:
    """Return the list under "errors".

    Args:
        answer: the AI's answer text.

    Returns:
        The raw items of the list (a bare list is accepted too).

    Raises:
        ValueError: the answer is not JSON or has no "errors" list.
    """
    text = CODE_FENCE.sub("", answer.strip())  # some models wrap JSON in ```json ... ```
    data = json.loads(text)  # json.JSONDecodeError is a ValueError
    if isinstance(data, list):  # a bare list is close enough
        return data
    if isinstance(data, dict) and isinstance(data.get("errors"), list):
        return data["errors"]
    raise ValueError('The answer has no "errors" list')


def to_mistake(item: Any) -> Mistake | None:
    """Turn one item of the list into a Mistake.

    Args:
        item: one raw item from the AI's "errors" list.

    Returns:
        The Mistake, or None (with a warning) if the item can't be used.
    """
    problem = find_problem(item)
    if problem is not None:
        logger.warning("Skipped an AI answer item because %s: %r", problem, item)
        return None
    return Mistake(
        original=item["original"],
        correction=item["correction"],
        type=normalize_type(item["type"]),
        reason=(item.get("reason") or "").strip(),
    )


def find_problem(item: Any) -> str | None:
    """Check one item of the AI's list.

    Args:
        item: one raw item from the AI's "errors" list.

    Returns:
        Why the item can't be used, or None when it is fine.
    """
    # Check the shape first, then the values.
    if not isinstance(item, dict):
        return "it is not an object"
    original, correction = item.get("original"), item.get("correction")
    reason = item.get("reason") or ""
    if not isinstance(original, str) or not original:
        return '"original" is missing or empty'
    if not isinstance(correction, str) or not isinstance(reason, str):
        return '"correction" and "reason" must be text'
    if correction == original:  # nothing to fix
        return "the correction is the same as the original"
    error_type = normalize_type(item.get("type"))
    if error_type is None:
        return f"unknown type {item.get('type')!r}"
    if error_type == "styleguide" and not reason.strip():
        return "a styleguide mistake must name the rule in its reason"
    return None


def normalize_type(value: Any) -> str | None:
    """Turn the AI's type name into one of ERROR_TYPES.

    Args:
        value: the type name the AI gave, e.g. "Style Guide".

    Returns:
        The error type, e.g. "styleguide", or None if the name is unknown.
    """
    if not isinstance(value, str):
        return None
    key = re.sub(r"[\s_\-]", "", value.lower())  # "Style Guide" and "style-guide" -> "styleguide"
    if key in ERROR_TYPES:
        return key
    return TYPE_ALIASES.get(key)
