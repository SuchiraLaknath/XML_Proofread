"""Build the proofreading prompts from the Markdown templates.

The templates live in prompt_templates/xml_proofread/ and use string.Template
placeholders: $language, $lang and $style_guide in the system prompt, and
$paragraph in the user prompt.

Each template is read from disk once (load_proofread_prompts) and then filled
in many times. The system prompt is built once per run and is identical for
every paragraph, which is what makes prompt caching work.
"""

from dataclasses import dataclass
from pathlib import Path
from string import Template

from utils.prompt_utils.prompt_making_tools import get_prompt

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates" / "xml_proofread"


@dataclass(frozen=True)
class ProofreadPrompts:
    """The two prompt templates, read from disk once."""

    system_template: Template
    user_template: Template


def load_proofread_prompts(prompt_dir: str | Path = PROMPT_DIR) -> ProofreadPrompts:
    """Read system_prompt.md and user_prompt.md.

    Args:
        prompt_dir: the folder that holds the two templates.

    Returns:
        The two templates, ready to be filled in.
    """
    prompt_dir = Path(prompt_dir)
    return ProofreadPrompts(
        system_template=Template(get_prompt("system_prompt.md", prompt_dir=prompt_dir)),
        user_template=Template(get_prompt("user_prompt.md", prompt_dir=prompt_dir)),
    )


def build_system_prompt(prompts: ProofreadPrompts, language: str, lang: str, style_guide: str) -> str:
    """Fill in the system prompt: language name, BCP-47 tag and the style guide text.

    Args:
        prompts: the templates.
        language: the language name, e.g. "English (United States)".
        lang: the BCP-47 tag, e.g. "en-US".
        style_guide: the whole style guide as Markdown.

    Returns:
        The system prompt, the same for every paragraph.
    """
    return prompts.system_template.substitute(language=language, lang=lang, style_guide=style_guide)


def build_user_prompt(prompts: ProofreadPrompts, paragraph: str) -> str:
    """Fill in the user prompt with one paragraph's text.

    Args:
        prompts: the templates.
        paragraph: the paragraph's text, exactly as it is in the XML.

    Returns:
        The user prompt for this paragraph.
    """
    return prompts.user_template.substitute(paragraph=paragraph)
