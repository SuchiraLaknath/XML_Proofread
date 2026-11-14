"""Read and write XML files safely, without changing bytes we did not touch.

When lxml saves a file it loses some text outside the root element: it rewrites
the <?xml ...?> line (" becomes '), drops blank lines between top-level nodes,
and drops the final newline. To keep the file identical, we store the raw bytes
before the root element ("head") and after it ("tail") and write them back as-is.

Files are always read and written as bytes, so the encoding and line endings
stay exactly as they were.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)

# Building blocks for the text that may appear outside the root element.
# "(?:(?!-->).)*" means "any text that does not contain -->", so one match
# can never run past the end of its own comment.
_COMMENT = rb"<!--(?:(?!-->).)*-->"
_PROCESSING_INSTRUCTION = rb"<\?(?:(?!\?>).)*\?>"  # includes the <?xml ...?> line
_DOCTYPE = rb"<!DOCTYPE[^\[>]*(?:\[.*?\]\s*)?>"
_UTF8_BOM = rb"(?:\xef\xbb\xbf)?"

HEAD_PATTERN = re.compile(
    _UTF8_BOM + rb"(?:" + _COMMENT + rb"|" + _PROCESSING_INSTRUCTION + rb"|" + _DOCTYPE + rb"|\s)*",
    re.DOTALL,
)
TAIL_PATTERN = re.compile(
    rb"(?:" + _COMMENT + rb"|" + _PROCESSING_INSTRUCTION + rb"|\s)*\Z",
    re.DOTALL,
)

# UTF-16 and UTF-32 byte order marks (UTF-32 LE starts with FF FE as well).
UTF16_32_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")


class XmlReadError(RuntimeError):
    """Raised when an XML file cannot be read or parsed."""


class XmlWriteError(RuntimeError):
    """Raised when an XML file cannot be written."""


@dataclass
class XmlFile:
    """A parsed XML file plus the raw bytes around its root element."""

    tree: etree._ElementTree
    head: bytes  # everything before the root element, e.g. the <?xml ...?> line
    tail: bytes  # everything after the root element, e.g. the final newline
    windows_newlines: bool = False  # True when every line ends with \r\n


def make_parser() -> etree.XMLParser:
    """Return an XML parser that is safe and keeps the text as written.

    Returns:
        The lxml parser.
    """
    return etree.XMLParser(
        resolve_entities=False,  # protection against XXE attacks
        no_network=True,  # never download anything while parsing
        strip_cdata=False,  # keep <![CDATA[...]]> sections
        remove_blank_text=False,  # keep whitespace between tags
    )


def read_xml_file(file_path: str | Path) -> XmlFile:
    """Parse an XML file and remember the bytes around its root element.

    Args:
        file_path: the XML file.

    Returns:
        The parsed file, plus the bytes before and after its root element.

    Raises:
        XmlReadError: the file can't be read or parsed, or is UTF-16/UTF-32.
    """
    file_path = Path(file_path)
    # 1. Read the raw bytes (never text, so encoding and line endings stay as they are).
    try:
        raw = file_path.read_bytes()
    except OSError as e:
        raise XmlReadError(f"Error loading XML file {file_path}: {e}") from e

    # The head/tail patterns work on ASCII-style bytes, which UTF-16/32 is not.
    if raw.startswith(UTF16_32_BOMS) or b"\x00" in raw[:4]:
        raise XmlReadError(f"{file_path}: UTF-16 and UTF-32 files are not supported")

    # 2. Parse the XML safely.
    try:
        root = etree.fromstring(raw, make_parser())
    except etree.XMLSyntaxError as e:
        raise XmlReadError(f"Error parsing XML file {file_path}: {e}") from e

    # 3. Keep the bytes before and after the root element, which lxml would rewrite.
    head = HEAD_PATTERN.match(raw).group()
    tail = TAIL_PATTERN.search(raw).group()
    xml_file = XmlFile(
        tree=root.getroottree(),
        head=head,
        tail=tail,
        windows_newlines=uses_only_windows_newlines(raw),
    )

    # 4. Warn now if saving the file unchanged would not give the same bytes.
    if xml_to_bytes(xml_file) != raw:
        logger.warning(
            "%s uses markup lxml cannot reproduce (for example &#x2019; or "
            "single-quoted attributes); it will be saved as equivalent XML",
            file_path,
        )
    return xml_file


def uses_only_windows_newlines(raw: bytes) -> bool:
    """Tell whether the file has newlines and every one of them is \\r\\n.

    Args:
        raw: the file's bytes.

    Returns:
        True for a file with Windows line endings only.
    """
    return b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")


def xml_to_bytes(xml_file: XmlFile) -> bytes:
    """Turn an XmlFile back into the bytes of a complete XML file.

    Args:
        xml_file: the parsed (and maybe marked) file.

    Returns:
        The bytes to write.
    """
    encoding = xml_file.tree.docinfo.encoding
    body = etree.tostring(xml_file.tree.getroot(), encoding=encoding, xml_declaration=False)
    # The XML standard makes every parser turn \r\n into \n, so put them back.
    if xml_file.windows_newlines:
        body = body.replace(b"\n", b"\r\n")
    return xml_file.head + body + xml_file.tail


def write_xml_file(xml_file: XmlFile, file_path: str | Path) -> None:
    """Save an XmlFile, replacing the file if it exists.

    Args:
        xml_file: the file to save.
        file_path: where to save it.

    Raises:
        XmlWriteError: the file can't be written.
    """
    file_path = Path(file_path)
    try:
        file_path.write_bytes(xml_to_bytes(xml_file))
    except OSError as e:
        raise XmlWriteError(f"Error writing XML file {file_path}: {e}") from e
