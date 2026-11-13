"""Tests for utils/prompt_utils/prompt_making_tools.py."""

import re
from pathlib import Path

import pytest

from utils.prompt_utils.prompt_making_tools import get_prompt

PROMPT_DIR = Path(__file__).parent.parent / "prompt_templates" / "xml_proofread"


def test_fills_placeholders_and_keeps_json_braces(tmp_path: Path) -> None:
    path = tmp_path / "prompt.md"
    path.write_bytes(b'Check $language. Answer {"errors": []}. Costs $$5.')
    assert (
        get_prompt(path, mapped_data={"language": "English"})
        == 'Check English. Answer {"errors": []}. Costs $5.'
    )


def test_missing_placeholder_value_raises(tmp_path: Path) -> None:
    path = tmp_path / "prompt.md"
    path.write_bytes(b"Check $language.")
    with pytest.raises(KeyError):
        get_prompt(path, mapped_data={})


def test_without_data_returns_template_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "prompt.md"
    path.write_bytes(b"Hello $name")
    assert get_prompt("prompt.md", prompt_dir=tmp_path) == "Hello $name"


def test_real_system_prompt_fills_cleanly() -> None:
    data = {"language": "English (United States)", "lang": "en-US", "style_guide": "RULES"}
    prompt = get_prompt("system_prompt.md", prompt_dir=PROMPT_DIR, mapped_data=data)
    assert re.search(r"\$[A-Za-z_]", prompt) is None  # every $placeholder was filled
    assert "English (United States)" in prompt and "RULES" in prompt


def test_non_markdown_template_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompt.xml"  # readable, but not text
    path.write_bytes(b"<doc/>")
    with pytest.raises(ValueError, match=r"Markdown \(\.md\)"):
        get_prompt(path)


def test_unsupported_template_extension_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompt.json"
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="supported extensions"):
        get_prompt(path)
