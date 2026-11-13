"""Find the <p> elements of an XML file and read their text as segments.

A <p> can contain inline tags (<b>, <i>, ...), so its text is spread over
several places in the lxml tree: the <p>'s own `.text`, and the `.text` and
`.tail` of the tags inside it. Each of those pieces is a Segment, which
remembers where the piece lives and where it sits in the paragraph's text:

    <p>Hello <b>big</b> world</p>
    Segment(p, "text", 0, 6)    "Hello "
    Segment(b, "text", 6, 9)    "big"
    Segment(b, "tail", 9, 15)   " world"

A mistake can only be wrapped in <error> when it fits inside one segment.

Text inside a nested <p> belongs to that nested <p>, not to the outer one.
Comments, processing instructions and entity references are not text, but
the text after them (their tail) is.

Loading and saving are done by utils/read_write_files/read_write_xml.py, which
parses safely and writes untouched bytes back exactly.
"""

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from utils.read_write_files.read_write_xml import XmlFile, XmlReadError, read_xml_file, write_xml_file

__all__ = [
    "Paragraph",
    "Segment",
    "XmlFile",
    "XmlReadError",
    "find_paragraphs",
    "load_xml",
    "read_paragraph",
    "save_xml",
]

PARAGRAPH_TAG = "p"
CDATA_START = b"<![CDATA["


@dataclass(frozen=True)
class Segment:
    """One piece of a paragraph's text: node.text or node.tail."""

    node: etree._Element
    attr: str  # "text" or "tail"
    start: int  # position of the piece in the paragraph's text
    end: int

    def current_text(self) -> str:
        """The current value of node.text / node.tail ("" when it is None)."""
        return getattr(self.node, self.attr) or ""


@dataclass
class Paragraph:
    """One <p> element and its text, read before anything is changed."""

    element: etree._Element
    text: str
    segments: list[Segment] = field(default_factory=list)
    has_cdata: bool = False  # editing a CDATA section would destroy it, so these are skipped


def load_xml(path: str | Path) -> XmlFile:
    """Parse an XML file safely (raises XmlReadError)."""
    return read_xml_file(path)


def save_xml(xml_file: XmlFile, path: str | Path) -> None:
    """Save the XML, writing every byte we did not change back exactly."""
    write_xml_file(xml_file, path)


def find_paragraphs(xml_file: XmlFile) -> list[Paragraph]:
    """Return every <p> in document order, nested ones included, with its text."""
    root = xml_file.tree.getroot()
    return [read_paragraph(element) for element in root.iter() if is_paragraph(element)]


def is_paragraph(node: etree._Element) -> bool:
    """True for a <p> element, in any namespace."""
    return isinstance(node.tag, str) and etree.QName(node).localname == PARAGRAPH_TAG


def read_paragraph(element: etree._Element) -> Paragraph:
    """Read the text of one <p> as a list of segments."""
    segments: list[Segment] = []
    position = add_segment(segments, element, "text", 0)
    for child in element:
        position = read_child(segments, child, position)
    text = "".join(segment.current_text() for segment in segments)
    return Paragraph(element=element, text=text, segments=segments, has_cdata=contains_cdata(element))


def read_child(segments: list[Segment], child: etree._Element, position: int) -> int:
    """Add the segments of one child of a paragraph; return the new position."""
    # A nested <p> keeps its own text. Comments, processing instructions and
    # entity references have no paragraph text either. Only their tail counts.
    if isinstance(child.tag, str) and not is_paragraph(child):
        position = add_segment(segments, child, "text", position)
        for grandchild in child:
            position = read_child(segments, grandchild, position)
    return add_segment(segments, child, "tail", position)


def add_segment(segments: list[Segment], node: etree._Element, attr: str, position: int) -> int:
    """Add node.text or node.tail as a segment if it holds text; return the new position."""
    value = getattr(node, attr)
    if not value:
        return position
    segments.append(Segment(node, attr, position, position + len(value)))
    return position + len(value)


def contains_cdata(element: etree._Element) -> bool:
    """True when the paragraph holds a <![CDATA[...]]> section."""
    # lxml merges CDATA into .text, so look at the element's own markup instead.
    return CDATA_START in etree.tostring(element, with_tail=False)
