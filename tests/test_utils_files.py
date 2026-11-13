"""Tests for read_file() / write_file() in utils/read_write_files/read_write_file.py.

The format helpers themselves have their own tests (test_read_write_md.py,
test_read_write_xml.py, test_read_docx.py); these check the choice by extension.
"""

from pathlib import Path

import docx
import pytest

from utils.read_write_files.read_write_file import read_file, write_file
from utils.read_write_files.read_write_xml import XmlFile


def test_markdown_round_trip_with_directory(tmp_path: Path) -> None:
    write_file("# Title\nCafé\n", "notes.md", directory=tmp_path)
    assert read_file("notes.md", directory=str(tmp_path)) == "# Title\nCafé\n"


def test_xml_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "in.xml"
    source.write_bytes(b'<?xml version="1.0"?>\n<doc><p>Hi</p></doc>\n')
    xml_file = read_file(source)
    assert isinstance(xml_file, XmlFile)
    write_file(xml_file, tmp_path / "out.xml")
    assert (tmp_path / "out.xml").read_bytes() == source.read_bytes()


def test_docx_is_read_as_text(tmp_path: Path) -> None:
    path = tmp_path / "guide.docx"
    document = docx.Document()
    document.add_paragraph("Rule one")
    document.save(str(path))
    assert read_file(path) == "Rule one"


def test_extension_case_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "NOTES.MD"
    path.write_bytes(b"hello")
    assert read_file(path) == "hello"


@pytest.mark.parametrize("name", ["data.json", "image.png", "no_extension"])
def test_unknown_extensions_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="supported extensions"):
        read_file(tmp_path / name)
    with pytest.raises(ValueError, match="supported extensions"):
        write_file("data", tmp_path / name)


def test_docx_cannot_be_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Cannot write"):
        write_file("text", tmp_path / "guide.docx")
