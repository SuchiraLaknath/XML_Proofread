"""Make sure marking errors never changed a paragraph's text.

Golden rule: if every <error> tag is removed, each <p> must be exactly as it
was (same characters, same whitespace, same length). Reading the paragraph
again treats <error> as an ordinary inline tag, so its text is simply part of
the paragraph text. If that text differs from the text read before marking,
every change to the paragraph is undone.
"""

import logging

from .error_marker import MarkResult
from .xml_reader import Paragraph, read_paragraph

logger = logging.getLogger(__name__)


def verify_or_undo(paragraph: Paragraph, mark: MarkResult) -> bool:
    """Return True if the paragraph text is unchanged; otherwise undo the marks and return False."""
    text_now = read_paragraph(paragraph.element).text
    if text_now == paragraph.text:
        return True

    logger.error(
        "Safety check failed: marking changed the text of a paragraph (line %s). Undoing it.",
        paragraph.element.sourceline,
    )
    mark.undo.undo()
    if read_paragraph(paragraph.element).text != paragraph.text:
        logger.error("Undo could not restore the paragraph on line %s", paragraph.element.sourceline)
    return False
