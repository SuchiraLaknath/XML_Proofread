"""Tests for the Markdown read/write helpers."""

from pathlib import Path

import pytest

from utils.read_write_files.read_write_md import (
    MdReadError,
    MdWriteError,
    read_md_file,
    write_md_file,
)


def test_round_trip_keeps_text_exactly(tmp_path: Path) -> None:
    text = "# Title\n\nCafé – it’s fine.\n"
    path = tmp_path / "note.md"
    write_md_file(text, path)
    assert read_md_file(path) == text


def test_written_file_uses_unix_newlines(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    write_md_file("line one\nline two\n", path)
    assert path.read_bytes() == b"line one\nline two\n"


def test_json_braces_are_kept(tmp_path: Path) -> None:
    text = 'Answer with {"errors": []}\n'
    path = tmp_path / "prompt.md"
    write_md_file(text, path)
    assert read_md_file(path) == text


def test_accepts_str_paths(tmp_path: Path) -> None:
    path = str(tmp_path / "note.md")
    write_md_file("hello\n", path)
    assert read_md_file(path) == "hello\n"


def test_missing_file_raises_read_error(tmp_path: Path) -> None:
    with pytest.raises(MdReadError):
        read_md_file(tmp_path / "missing.md")


def test_missing_folder_raises_write_error(tmp_path: Path) -> None:
    with pytest.raises(MdWriteError):
        write_md_file("hello\n", tmp_path / "no_such_folder" / "note.md")
