"""Tests for proof_read_process/rule_loader.py and read_docx_blocks()."""

import re
from pathlib import Path

import docx
import pytest

from proof_read_process import build_system_prompt, load_proofread_prompts
from proof_read_process.rule_loader import StyleGuideError, load_style_guide
from utils.read_write_files.read_docx import TABLE_ROW_STYLE, DocxBlock, read_docx_blocks, read_docx_file

STYLE_GUIDE = Path(__file__).parent.parent / "examples" / "Style_Guide.docx"

# Markers rule_loader adds. Removing them must give back exactly the guide's words.
MARKERS = {"#", "##", "###", "-", "Example:"}


def words_without_markers(text: str) -> list[str]:
    return [word.strip("*") for word in text.split() if word not in MARKERS and word.strip("*")]


# ---------- the real style guide ----------


def test_real_guide_keeps_every_word() -> None:
    guide = load_style_guide(STYLE_GUIDE)
    assert words_without_markers(guide) == words_without_markers(read_docx_file(STYLE_GUIDE))


def test_real_guide_structure() -> None:
    guide = load_style_guide(STYLE_GUIDE)
    assert "## Dates (Months, Days, Years)" in guide
    assert "## Hot Spots for Errors" in guide
    assert "### $ and other currency symbols/designations" in guide
    assert "- Example: January 2022 not January, 2022" in guide
    assert "**List of Preferred Word Usage**" in guide
    assert "judgment (not judgement)" in guide


def test_real_guide_whitespace_is_tidy() -> None:
    guide = load_style_guide(STYLE_GUIDE)
    assert "\n\n\n" not in guide
    assert all(line == line.strip() for line in guide.splitlines())
    assert guide == guide.strip()


def test_real_guide_fits_in_the_system_prompt() -> None:
    guide = load_style_guide(STYLE_GUIDE)
    system = build_system_prompt(load_proofread_prompts(), "English", "en", guide)
    assert guide in system  # "$" signs in the guide (like $3,000) are kept as they are
    assert re.search(r"\$[A-Za-z_]", system) is None


# ---------- styles from a made-up document ----------


def make_docx(path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("House Rules", style="Title")
    document.add_paragraph("Dates", style="Heading 1")
    document.add_paragraph("Months", style="Heading 2")
    document.add_paragraph("  No comma before the year.  ")
    document.add_paragraph("")
    document.add_paragraph("")
    document.add_paragraph("Spell out months", style="List Bullet")
    document.add_paragraph().add_run("Note:").bold = True
    mixed = document.add_paragraph()
    mixed.add_run("Partly ").bold = True
    mixed.add_run("bold")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Wrong"
    table.cell(0, 1).text = "Right"
    document.save(str(path))


def test_read_docx_blocks_reports_styles_and_bold(tmp_path: Path) -> None:
    path = tmp_path / "rules.docx"
    make_docx(path)
    blocks = read_docx_blocks(path)
    assert blocks[0] == DocxBlock("House Rules", "Title", False)
    assert blocks[1].style == "Heading 1"
    assert DocxBlock("Note:", "Normal", True) in blocks
    assert DocxBlock("Partly bold", "Normal", False) in blocks
    assert blocks[-1] == DocxBlock("Wrong | Right", TABLE_ROW_STYLE)


def test_styles_become_markdown(tmp_path: Path) -> None:
    path = tmp_path / "rules.docx"
    make_docx(path)
    assert load_style_guide(path) == (
        "# House Rules\n"
        "\n"
        "## Dates\n"
        "\n"
        "### Months\n"
        "No comma before the year.\n"
        "\n"
        "- Spell out months\n"
        "**Note:**\n"
        "Partly bold\n"
        "Wrong | Right"
    )


# ---------- errors ----------


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(StyleGuideError, match="Could not read"):
        load_style_guide(tmp_path / "missing.docx")


def test_not_a_docx_extension(tmp_path: Path) -> None:
    path = tmp_path / "rules.pdf"
    path.write_bytes(b"%PDF")
    with pytest.raises(StyleGuideError, match=r"must be a \.docx"):
        load_style_guide(path)


def test_broken_docx(tmp_path: Path) -> None:
    path = tmp_path / "rules.docx"
    path.write_bytes(b"not a zip file")
    with pytest.raises(StyleGuideError, match="Could not read"):
        load_style_guide(path)


def test_empty_docx(tmp_path: Path) -> None:
    path = tmp_path / "rules.docx"
    document = docx.Document()
    document.add_paragraph("   ")
    document.save(str(path))
    with pytest.raises(StyleGuideError, match="no text"):
        load_style_guide(path)
