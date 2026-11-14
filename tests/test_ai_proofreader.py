"""Tests for parse_ai_answer(), Proofreader.check_all() and parse_language()."""

import json

import pytest

from llms import LLMAnswer
from proof_read_process import (
    LanguageError,
    Mistake,
    Proofreader,
    load_proofread_prompts,
    parse_ai_answer,
    parse_language,
)

# ---------- parse_ai_answer ----------

JOHN = {
    "original": "john",
    "correction": "John",
    "type": "capitalization",
    "reason": "Names start with a capital",
}


def answer(*items: dict) -> str:
    return json.dumps({"errors": list(items)})


def test_reads_a_normal_answer() -> None:
    assert parse_ai_answer(answer(JOHN)) == [
        Mistake("john", "John", "capitalization", "Names start with a capital")
    ]


def test_no_mistakes() -> None:
    assert parse_ai_answer('{"errors": []}') == []


@pytest.mark.parametrize(
    "text",
    [
        "```json\n" + answer(JOHN) + "\n```",  # code fence
        "```\n" + answer(JOHN) + "\n```",
        json.dumps([JOHN]),  # a bare list
        "  " + answer(JOHN) + "\n",
    ],
)
def test_forgives_small_format_problems(text: str) -> None:
    assert parse_ai_answer(text)[0].original == "john"


@pytest.mark.parametrize(
    "ai_type, expected",
    [
        ("Style Guide", "styleguide"),
        ("style-guide", "styleguide"),
        ("capitalisation", "capitalization"),
        ("Typo", "spelling"),
    ],
)
def test_type_aliases(ai_type: str, expected: str) -> None:
    item = {**JOHN, "type": ai_type, "reason": "Rule"}
    assert parse_ai_answer(answer(item))[0].type == expected


@pytest.mark.parametrize(
    "bad_item",
    [
        {**JOHN, "type": "vibes"},  # unknown type
        {**JOHN, "original": ""},  # empty original
        {k: v for k, v in JOHN.items() if k != "original"},  # missing original
        {**JOHN, "correction": "john"},  # same as the original
        {**JOHN, "correction": 5},  # not text
        {**JOHN, "type": "styleguide", "reason": ""},  # styleguide must name the rule
        "just a string",
    ],
)
def test_bad_items_are_skipped_good_ones_kept(bad_item: object) -> None:
    mistakes = parse_ai_answer(answer(bad_item, JOHN))  # type: ignore[arg-type]
    assert mistakes == [Mistake("john", "John", "capitalization", "Names start with a capital")]


def test_missing_reason_is_allowed_for_other_types() -> None:
    item = {k: v for k, v in JOHN.items() if k != "reason"}
    assert parse_ai_answer(answer(item))[0].reason == ""


@pytest.mark.parametrize("text", ["not json", '{"mistakes": []}', '{"errors": "none"}', "42", ""])
def test_unusable_answer_raises_value_error(text: str) -> None:
    with pytest.raises(ValueError):
        parse_ai_answer(text)


# ---------- Proofreader.check_all ----------


class FakeLLM:
    """Answers "john" paragraphs with one mistake, everything else with none."""

    def __init__(self) -> None:
        self.user_prompts: list[str] = []

    def ask(self, system_prompt: str, user_prompt: str) -> LLMAnswer:
        self.user_prompts.append(user_prompt)
        return LLMAnswer(text=answer(JOHN) if "john" in user_prompt else answer())


def test_check_all_returns_results_by_paragraph_text() -> None:
    llm = FakeLLM()
    proofreader = Proofreader(llm, load_proofread_prompts(), "SYSTEM")  # type: ignore[arg-type]
    results = proofreader.check_all(["I am john.", "All good."], workers=2)
    assert results["I am john."].value[0].original == "john"
    assert results["All good."].value == []
    assert any("<paragraph>\nI am john.\n</paragraph>" in prompt for prompt in llm.user_prompts)


# ---------- parse_language ----------


@pytest.mark.parametrize(
    "value, tag, name",
    [
        ("en", "en", "English"),
        ("en-US", "en-US", "English (United States)"),
        ("EN-gb", "en-GB", "English (United Kingdom)"),
        ("fr", "fr", "French"),
    ],
)
def test_valid_languages(value: str, tag: str, name: str) -> None:
    locale = parse_language(value)
    assert (locale.tag, locale.name) == (tag, name)


@pytest.mark.parametrize("value", ["", "english", "xx", "en-ZZ", "und", "en-"])
def test_invalid_languages(value: str) -> None:
    with pytest.raises(LanguageError):
        parse_language(value)
