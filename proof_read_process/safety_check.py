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
    """Check that marking did not change the paragraph's text; undo the marks if it did.

    Args:
        paragraph: the paragraph, as read before marking.
        mark: the result of mark_errors(), with its undo record.

    Returns:
        True if the text is unchanged (the marks are kept), False if the marks were undone.
    """
    # Read the paragraph again: the text inside <error> tags counts as paragraph text.
    text_now = read_paragraph(paragraph.element).text
    if text_now == paragraph.text:
        return True

    # The text changed, which must never happen: put the paragraph back.
    logger.error(
        "Safety check failed: marking changed the text of a paragraph (line %s). Undoing it.",
        paragraph.element.sourceline,
    )
    mark.undo.undo()
    # Check that the undo really restored it.
    if read_paragraph(paragraph.element).text != paragraph.text:
        logger.error("Undo could not restore the paragraph on line %s", paragraph.element.sourceline)
    return False
