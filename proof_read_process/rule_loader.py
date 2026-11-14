"""Load the house style guide (.docx) as text for the system prompt.

The whole guide is sent in the system prompt, with no RAG: it is small
(about 1,500 words) and a search could miss a rule. It is read once per run.

The guide is turned into light Markdown, using each paragraph's Word style:

    Title                            ->  # Title
    Heading 1 / "PLI_Level 1 Head"   ->  ## Heading
    Heading 2 / "PLI_Level 2 Head"   ->  ### Heading
    "PLI_Sample"                     ->  - Example: ...
    List paragraphs                  ->  - ...
    fully bold paragraphs            ->  **...**
    anything else                    ->  the text as it is

Bold is kept as bold, not turned into a heading: in this guide bold is used
both for section names ("List of Preferred Word Usage") and for short labels
("Note:"), so guessing headings from bold would be wrong.

Headings let the model see which rule a line belongs to, so it can name the
rule in a styleguide error's "reason". Only these markers and whitespace are
changed; the words of the guide never are.
"""

import logging
import re
from pathlib import Path

from utils.read_write_files.read_docx import DocxBlock, DocxReadError, read_docx_blocks

logger = logging.getLogger(__name__)

# Finds the level number in style names like "Heading 1" or "PLI_Level 2 Head".
HEADING_LEVEL = re.compile(r"(?:heading|level)\s*(\d)", re.IGNORECASE)


class StyleGuideError(RuntimeError):
    """Raised when the style guide cannot be loaded."""


def load_style_guide(file_path: str | Path) -> str:
    """Read a .docx style guide and return it as Markdown text.

    Args:
        file_path: the .docx file.

    Returns:
        The whole guide as Markdown; its words are never changed.

    Raises:
        StyleGuideError: the file is not a .docx, can't be read, or has no text.
    """
    file_path = Path(file_path)
    if file_path.suffix.lower() != ".docx":
        raise StyleGuideError(f"The style guide must be a .docx file: {file_path}")
    # Read every paragraph with its Word style, then turn the styles into Markdown.
    try:
        blocks = read_docx_blocks(file_path)
    except DocxReadError as e:
        raise StyleGuideError(f"Could not read the style guide {file_path}: {e}") from e

    text = tidy_whitespace("\n".join(block_to_markdown(block) for block in blocks))
    if not text:
        raise StyleGuideError(f"The style guide {file_path} contains no text")
    logger.info("Loaded style guide %s (%d words)", file_path.name, len(text.split()))
    return text


def block_to_markdown(block: DocxBlock) -> str:
    """Turn one paragraph into a Markdown line, based on its Word style.

    Args:
        block: one paragraph or table row, with its Word style and bold flag.

    Returns:
        The Markdown line, or "" for an empty paragraph.
    """
    text = block.text.strip()
    if not text:
        return ""
    # Check the styles from the most to the least specific.
    level = heading_level(block.style)
    if level is not None:
        return "\n" + "#" * (level + 1) + " " + text  # blank line before each heading
    style = block.style.lower()
    if "sample" in style:
        return f"- Example: {text}"
    if "list" in style:
        return f"- {text}"
    if block.bold:
        return f"**{text}**"
    return text


def heading_level(style: str) -> int | None:
    """Find the heading level of a Word style.

    Args:
        style: the Word style name, e.g. "Heading 2".

    Returns:
        0 for a title, 1, 2, ... for headings, or None for other styles.
    """
    if style.strip().lower() == "title":
        return 0
    match = HEADING_LEVEL.search(style)
    return int(match.group(1)) if match else None


def tidy_whitespace(text: str) -> str:
    """Strip spaces at line ends and allow at most one blank line in a row.

    Args:
        text: the Markdown text.

    Returns:
        The tidied text.
    """
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        # Keep every line with text, and a blank line only if the line before it had text.
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()
