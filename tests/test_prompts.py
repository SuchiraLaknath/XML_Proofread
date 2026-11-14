"""Tests for proof_read_process/prompts.py: building the prompts from the real templates."""

import re

from proof_read_process import build_system_prompt, build_user_prompt, load_proofread_prompts


def test_system_prompt_is_filled_from_the_real_template() -> None:
    prompts = load_proofread_prompts()
    system = build_system_prompt(
        prompts, "English (United States)", "en-US", "No comma between month and year."
    )
    assert "English (United States)" in system
    assert "language tag: en-US" in system
    assert "No comma between month and year." in system
    assert '{"errors": []}' in system  # JSON examples survive
    assert "$3,000,000" in system  # $$ in the template becomes $
    assert re.search(r"\$[A-Za-z_]", system) is None  # no placeholder left


def test_user_prompt_keeps_paragraph_text_exactly() -> None:
    prompts = load_proofread_prompts()
    paragraph = 'It costs $5 {"not": "json"} and $paragraph stays.'
    user = build_user_prompt(prompts, paragraph)
    assert f"<paragraph>\n{paragraph}\n</paragraph>" in user


def test_system_prompt_limits_the_english_style_guide_to_sensible_rules() -> None:
    system = build_system_prompt(load_proofread_prompts(), "French (Canada)", "fr-CA", "RULES")
    assert "only where it makes sense for French (Canada)" in system


def test_system_prompt_is_identical_every_time() -> None:
    """Prompt caching only works when the system prompt never changes."""
    prompts = load_proofread_prompts()
    first = build_system_prompt(prompts, "French", "fr", "RULES")
    second = build_system_prompt(prompts, "French", "fr", "RULES")
    assert first == second
