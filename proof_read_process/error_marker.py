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
    """Wrap every mistake that can be placed safely in an <error> tag."""
    result = MarkResult()
    placements = place_mistakes(paragraph, mistakes, result)
    tag = error_tag_for(paragraph.element)
    by_segment: dict[Segment, list[Placement]] = defaultdict(list)
    for placement in placements:
        by_segment[placement.segment].append(placement)
    for segment, group in by_segment.items():
        wrap_segment(segment, sorted(group, key=lambda p: p.start), tag, result.undo)
    result.marked = [placement.mistake for placement in placements]
    return result


def place_mistakes(paragraph: Paragraph, mistakes: list[Mistake], result: MarkResult) -> list[Placement]:
    """Find a safe position for each mistake; record the ones that have none."""
    placements: list[Placement] = []
    cursor = 0  # the AI lists mistakes in order, so search after the previous one first
    for mistake in mistakes:
        span = find_text(paragraph.text, mistake.original, cursor)
        if span is None:
            skip(result, mistake, "its text was not found in the paragraph")
            continue
        start, end = span
        if any(start < p.end and p.start < end for p in placements):
            skip(result, mistake, "it overlaps another mistake")
            continue
        segment = segment_containing(paragraph.segments, start, end)
        if segment is None:
            skip(result, mistake, "it crosses another tag")
            continue
        placements.append(Placement(mistake, segment, start, end))
        cursor = end
    return placements


def find_text(text: str, original: str, cursor: int) -> tuple[int, int] | None:
    """Return (start, end) of original in text, or None.

    Looks after the cursor first, then from the beginning. If there is no exact
    match, line breaks and runs of spaces may differ (the AI often writes one
    space where the XML has a line break and indentation).
    """
    for begin in (cursor, 0):
        index = text.find(original, begin)
        if index != -1:
            return index, index + len(original)
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
    """Return the one segment that holds text[start:end] completely, or None."""
    for segment in segments:
        if segment.start <= start and end <= segment.end:
            return segment
    return None


def error_tag_for(paragraph: etree._Element) -> str:
    """<error> goes in the paragraph's namespace, so no stray xmlns="" is written."""
    namespace = etree.QName(paragraph).namespace
    return f"{{{namespace}}}{ERROR_TAG}" if namespace else ERROR_TAG


def wrap_segment(segment: Segment, placements: list[Placement], tag: str, undo: UndoRecord) -> None:
    """Split one segment's text around its mistakes and insert the <error> tags."""
    node, attr = segment.node, segment.attr
    value = segment.current_text()
    undo.old_values.append(OldValue(node, attr, getattr(node, attr)))

    # Positions inside this segment's text.
    spans = [(p.start - segment.start, p.end - segment.start, p.mistake) for p in placements]
    setattr(node, attr, value[: spans[0][0]] or None)

    # Text in node.text is followed by node's first child; text in node.tail by node's next sibling.
    parent = node if attr == "text" else node.getparent()
    index = 0 if attr == "text" else parent.index(node) + 1
    for number, (start, end, mistake) in enumerate(spans):
        next_start = spans[number + 1][0] if number + 1 < len(spans) else len(value)
        error = make_error(parent, tag, mistake, text=value[start:end], tail=value[end:next_start])
        parent.insert(index + number, error)
        undo.inserted.append(error)


def make_error(parent: etree._Element, tag: str, mistake: Mistake, text: str, tail: str) -> etree._Element:
    """Create <error type=".." correction=".." reason="..">text</error>, attributes in that order."""
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
    """Record and log a mistake that was not marked."""
    logger.warning("Skipped %r (%s) because %s", mistake.original, mistake.type, why)
    result.skipped.append((mistake, why))
