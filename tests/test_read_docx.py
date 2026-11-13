"""Tests for the .docx reader."""

from pathlib import Path

import docx
import pytest

from utils.read_write_files.read_docx import DocxReadError, read_docx_file


def make_docx(path: Path) -> None:
    """Build a small .docx with a paragraph, a table, then another paragraph."""
    document = docx.Document()
    document.add_paragraph("Rule 1: Use “judgment”, not “judgement”.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Wrong"
    table.cell(0, 1).text = "Right"
    table.cell(1, 0).text = "1930's"
    table.cell(1, 1).text = "1930s"
    document.add_paragraph("Rule 2: Write HIPAA, not HIPPA.")
    document.save(str(path))


def test_reads_paragraphs_and_tables_in_order(tmp_path: Path) -> None:
    path = tmp_path / "guide.docx"
    make_docx(path)
    assert read_docx_file(path) == (
        "Rule 1: Use “judgment”, not “judgement”.\n"
        "Wrong | Right\n"
        "1930's | 1930s\n"
        "Rule 2: Write HIPAA, not HIPPA."
    )


def test_accepts_str_paths(tmp_path: Path) -> None:
    path = tmp_path / "guide.docx"
    make_docx(path)
    assert read_docx_file(str(path)).startswith("Rule 1")


def test_missing_file_raises_read_error(tmp_path: Path) -> None:
    with pytest.raises(DocxReadError):
        read_docx_file(tmp_path / "missing.docx")


def test_non_docx_file_raises_read_error(tmp_path: Path) -> None:
    path = tmp_path / "fake.docx"
    path.write_bytes(b"this is not a zip file")
    with pytest.raises(DocxReadError):
        read_docx_file(path)
