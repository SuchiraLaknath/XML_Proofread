"""Wrap each mistake in an <error> tag, without changing the text.

    <p>My name is john.</p>
    ->  <p>My name is <error type="capitalization" correction="John">john</error>.</p>

Steps for one paragraph:
1. Find where each mistake's "original" text is in the paragraph.
2. Skip it (with a warning) when that is not safe:
   - the text can't be found,
   - it overlaps a mistake that was already placed,
   - it crosses another tag (it does not fit inside one Segment).
3. Split each segment's text around its mistakes and insert the <error> tags.

Every change is written down in an UndoRecord first, so safety_check.py can
put the paragraph back exactly as it was.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

from lxml import etree

from .ai_proofreader import Mistake
from .xml_reader import Paragraph, Segment

logger = logging.getLogger(__name__)

ERROR_TAG = "error"


@dataclass(frozen=True)
class Placement:
    """Where one mistake sits: its segment and its position in the paragraph text."""

    mistake: Mistake
    segment: Segment
    start: int
    end: int


@dataclass(frozen=True)
class OldValue:
    """The value node.text or node.tail had before it was changed."""

    node: etree._Element
    attr: str  # "text" or "tail"
    value: str | None


@dataclass
class UndoRecord:
    """Everything mark_errors changed, so it can be put back."""

    old_values: list[OldValue] = field(default_factory=list)
    inserted: list[etree._Element] = field(default_factory=list)

    def undo(self) -> None:
        """Remove the inserted <error> tags and restore the old text."""
        # Remove the tags first (their text goes with them), then put the old text back.
        for element in self.inserted:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
        for old in self.old_values:
            setattr(old.node, old.attr, old.value)
        self.inserted.clear()
        self.old_values.clear()


@dataclass
class MarkResult:
    """What happened to the mistakes of one paragraph."""

    marked: list[Mistake] = field(default_factory=list)
    skipped: list[tuple[Mistake, str]] = field(default_factory=list)  # (mistake, why)
    undo: UndoRecord = field(default_factory=UndoRecord)


def mark_errors(paragraph: Paragraph, mistakes: list[Mistake]) -> MarkResult:
    """Wrap every mistake that can be placed safely in an <error> tag.

    Args:
        paragraph: the paragraph, as read before any change.
        mistakes: the AI's mistakes, in the order they appear in the text.

    Returns:
        The marked and the skipped mistakes, and an undo record for the safety check.
    """
    result = MarkResult()
    # 1. Decide where each mistake goes (unsafe ones are skipped here).
    placements = place_mistakes(paragraph, mistakes, result)
    tag = error_tag_for(paragraph.element)

    # 2. Group the mistakes by the piece of text (segment) they sit in.
    by_segment: dict[Segment, list[Placement]] = defaultdict(list)
    for placement in placements:
        by_segment[placement.segment].append(placement)

    # 3. Insert the <error> tags, segment by segment, left to right.
    for segment, group in by_segment.items():
        wrap_segment(segment, sorted(group, key=lambda p: p.start), tag, result.undo)
    result.marked = [placement.mistake for placement in placements]
    return result


def place_mistakes(paragraph: Paragraph, mistakes: list[Mistake], result: MarkResult) -> list[Placement]:
    """Find a safe position for each mistake; record the ones that have none.

    Args:
        paragraph: the paragraph, as read before any change.
        mistakes: the AI's mistakes, in the order they appear in the text.
        result: where the skipped mistakes are recorded.

    Returns:
        One Placement for each mistake that can be marked safely.
    """
    placements: list[Placement] = []
    cursor = 0  # the AI lists mistakes in order, so search after the previous one first
    for mistake in mistakes:
        # Where is the mistake's text in the paragraph?
        span = find_text(paragraph.text, mistake.original, cursor)
        if span is None:
            skip(result, mistake, "its text was not found in the paragraph")
            continue
        start, end = span
        # Two <error> tags can't share text.
        if any(start < p.end and p.start < end for p in placements):
            skip(result, mistake, "it overlaps another mistake")
            continue
        # The text must not cross an inline tag such as </b>.
        segment = segment_containing(paragraph.segments, start, end)
        if segment is None:
            skip(result, mistake, "it crosses another tag")
            continue
        placements.append(Placement(mistake, segment, start, end))
        cursor = end
    return placements


def find_text(text: str, original: str, cursor: int) -> tuple[int, int] | None:
    """Find where a mistake's text is in the paragraph.

    Looks after the cursor first, then from the beginning. If there is no exact
    match, line breaks and runs of spaces may differ (the AI often writes one
    space where the XML has a line break and indentation).

    Args:
        text: the paragraph's text.
        original: the mistake's text, as the AI copied it.
        cursor: where to start looking first (the end of the previous mistake).

    Returns:
        (start, end) of the text in the paragraph, or None if it is not there.
    """
    # First try: the exact text.
    for begin in (cursor, 0):
        index = text.find(original, begin)
        if index != -1:
            return index, index + len(original)
    # Second try: the same words, with any whitespace between them.
    words = original.split()
    if not words:
        return None
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
    for begin in (cursor, 0):
        match = pattern.search(text, begin)
        if match:
            return match.start(), match.end()
    return None


def segment_containing(segments: list[Segment], start: int, end: int) -> Segment | None:
    """Find the one segment that holds text[start:end] completely.

    Args:
        segments: the paragraph's segments.
        start: where the mistake starts in the paragraph's text.
        end: where it ends.

    Returns:
        That segment, or None when the text crosses from one segment into another.
    """
    for segment in segments:
        if segment.start <= start and end <= segment.end:
            return segment
    return None


def error_tag_for(paragraph: etree._Element) -> str:
    """Choose the <error> tag name for a paragraph.

    <error> goes in the paragraph's namespace, so no stray xmlns="" is written.

    Args:
        paragraph: the <p> element.

    Returns:
        "error", or "{namespace}error" when the <p> is in a namespace.
    """
    namespace = etree.QName(paragraph).namespace
    return f"{{{namespace}}}{ERROR_TAG}" if namespace else ERROR_TAG


def wrap_segment(segment: Segment, placements: list[Placement], tag: str, undo: UndoRecord) -> None:
    """Split one segment's text around its mistakes and insert the <error> tags.

    Args:
        segment: the piece of text that holds the mistakes.
        placements: the mistakes inside this segment, sorted by position.
        tag: the <error> tag name (see error_tag_for).
        undo: every change is written down here, so it can be undone.
    """
    # node and parent are elements of the document tree itself, so these edits change
    # the XML that will be saved (and UndoRecord can change them back the same way).
    node, attr = segment.node, segment.attr
    value = segment.current_text()
    # Write down the old text first, so the change can be undone.
    undo.old_values.append(OldValue(node, attr, getattr(node, attr)))

    # Positions inside this segment's text.
    spans = [(p.start - segment.start, p.end - segment.start, p.mistake) for p in placements]
    # Keep only the text before the first mistake; the rest moves into the <error> tags.
    setattr(node, attr, value[: spans[0][0]] or None)

    # Text in node.text is followed by node's first child; text in node.tail by node's next sibling.
    parent = node if attr == "text" else node.getparent()
    index = 0 if attr == "text" else parent.index(node) + 1
    # Each <error> holds its mistake's text; its tail holds the text up to the next mistake.
    for number, (start, end, mistake) in enumerate(spans):
        next_start = spans[number + 1][0] if number + 1 < len(spans) else len(value)
        error = make_error(parent, tag, mistake, text=value[start:end], tail=value[end:next_start])
        parent.insert(index + number, error)
        undo.inserted.append(error)


def make_error(parent: etree._Element, tag: str, mistake: Mistake, text: str, tail: str) -> etree._Element:
    """Create <error type=".." correction=".." reason="..">text</error>, attributes in that order.

    Args:
        parent: the element the new tag will belong to.
        tag: the <error> tag name.
        mistake: gives the type, the correction and the reason.
        text: the exact text to wrap, taken from the paragraph.
        tail: the text after the tag, up to the next mistake.

    Returns:
        The new <error> element.
    """
    # SubElement reuses the parent's namespace declarations; insert() then moves it into place.
    error = etree.SubElement(parent, tag)
    error.set("type", mistake.type)
    error.set("correction", mistake.correction)
    if mistake.reason:
        error.set("reason", mistake.reason)
    error.text = text
    error.tail = tail or None
    return error


def skip(result: MarkResult, mistake: Mistake, why: str) -> None:
    """Record and log a mistake that was not marked.

    Args:
        result: where the skipped mistake is recorded.
        mistake: the mistake that was not marked.
        why: the reason, shown in the warning.
    """
    logger.warning("Skipped %r (%s) because %s", mistake.original, mistake.type, why)
    result.skipped.append((mistake, why))
