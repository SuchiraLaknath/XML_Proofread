"""Tests for the XML read/write helpers."""

import logging
from pathlib import Path

import pytest

from utils.read_write_files.read_write_xml import (
    XmlReadError,
    XmlWriteError,
    read_xml_file,
    write_xml_file,
)

# Each file must come back byte-for-byte identical after read + write.
ROUND_TRIP_FILES = {
    "declaration_comment_cdata_namespaces": (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b"<!-- top comment -->\n"
        b'<doc xmlns="urn:a" xmlns:x="urn:x" x:id="7">\n'
        b'  <p class="intro">Hi <![CDATA[a < b]]> &amp; <x:b>bold</x:b> there.</p>\n'
        b"  <!-- inner -->\n"
        b"</doc>\n"
    ),
    "no_declaration_no_newline": b"<doc><p>No declaration</p></doc>",
    "blank_lines_and_epilog": b'<?xml version="1.0"?>\n\n<doc/>\n<!-- after -->\n<?pi x?>\n\n',
    "latin1": b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<doc>caf\xe9</doc>\n',
    "utf8_bom": b"\xef\xbb\xbf<?xml version='1.0' encoding='utf-8'?>\n<doc>\xc3\xa9</doc>\n",
    "doctype": b'<?xml version="1.0"?>\n<!DOCTYPE doc [\n  <!ELEMENT doc (#PCDATA)>\n]>\n<doc>x</doc>\n',
    "windows_newlines": b'<?xml version="1.0"?>\r\n<doc>\r\n  <p>x</p>\r\n</doc>\r\n',
}


@pytest.mark.parametrize("raw", ROUND_TRIP_FILES.values(), ids=ROUND_TRIP_FILES.keys())
def test_read_then_write_is_byte_identical(tmp_path: Path, raw: bytes) -> None:
    source = tmp_path / "in.xml"
    target = tmp_path / "out.xml"
    source.write_bytes(raw)
    write_xml_file(read_xml_file(source), target)
    assert target.read_bytes() == raw


def test_edit_keeps_everything_else(tmp_path: Path) -> None:
    path = tmp_path / "in.xml"
    path.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n<doc>\n  <p>old</p>\n</doc>\n')
    xml_file = read_xml_file(path)
    xml_file.tree.getroot()[0].text = "new"
    write_xml_file(xml_file, path)
    assert path.read_bytes() == b'<?xml version="1.0" encoding="UTF-8"?>\n<doc>\n  <p>new</p>\n</doc>\n'


def test_external_entities_are_not_resolved(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"TOP SECRET")
    raw = (f'<!DOCTYPE doc [<!ENTITY x SYSTEM "{secret.as_uri()}">]>\n<doc>&x;</doc>\n').encode()
    path = tmp_path / "in.xml"
    path.write_bytes(raw)
    xml_file = read_xml_file(path)
    assert "TOP SECRET" not in "".join(xml_file.tree.getroot().itertext())
    write_xml_file(xml_file, path)
    assert path.read_bytes() == raw


def test_character_reference_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "in.xml"
    path.write_bytes(b"<doc>it&#x2019;s</doc>")
    with caplog.at_level(logging.WARNING):
        read_xml_file(path)
    assert "equivalent XML" in caplog.text


def test_utf16_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "in.xml"
    path.write_bytes('<?xml version="1.0" encoding="UTF-16"?><doc/>'.encode("utf-16"))
    with pytest.raises(XmlReadError, match="UTF-16"):
        read_xml_file(path)


def test_broken_xml_raises_read_error(tmp_path: Path) -> None:
    path = tmp_path / "in.xml"
    path.write_bytes(b"<doc><p>never closed</doc>")
    with pytest.raises(XmlReadError):
        read_xml_file(path)


def test_missing_file_raises_read_error(tmp_path: Path) -> None:
    with pytest.raises(XmlReadError):
        read_xml_file(tmp_path / "missing.xml")


def test_missing_folder_raises_write_error(tmp_path: Path) -> None:
    path = tmp_path / "in.xml"
    path.write_bytes(b"<doc/>")
    with pytest.raises(XmlWriteError):
        write_xml_file(read_xml_file(path), tmp_path / "no_such_folder" / "out.xml")


def test_accepts_str_paths(tmp_path: Path) -> None:
    path = tmp_path / "in.xml"
    path.write_bytes(b"<doc/>\n")
    write_xml_file(read_xml_file(str(path)), str(path))
    assert path.read_bytes() == b"<doc/>\n"
