"""Read Word (.docx) files.

Paragraphs and tables are read in the order they appear in the document.
Each table row becomes one line with its cells joined by " | ".

- read_docx_blocks: every paragraph / table row with its Word style name
  (for example "Heading 1") and whether it is fully bold, for callers that
  need the document's structure.
- read_docx_file: just the text, one paragraph or table row per line.
"""

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

import docx
from docx.document import Document
from docx.opc.exceptions import OpcError
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

TABLE_ROW_STYLE = "Table Row"  # style name given to table rows, which have no paragraph style


class DocxReadError(RuntimeError):
    """Raised when a .docx file cannot be opened or read."""


@dataclass(frozen=True)
class DocxBlock:
    """One paragraph or table row of a Word document."""

    text: str
    style: str  # Word style name, e.g. "Normal", "Heading 1", or TABLE_ROW_STYLE
    bold: bool = False  # True when all of the paragraph's text is bold


def read_docx_file(file_path: str | Path) -> str:
    """Return the text of a .docx file, one paragraph or table row per line."""
    return "\n".join(block.text for block in read_docx_blocks(file_path))


def read_docx_blocks(file_path: str | Path) -> list[DocxBlock]:
    """Return every paragraph and table row of a .docx file, with its style name."""
    document = open_docx(Path(file_path))
    blocks: list[DocxBlock] = []
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            blocks.extend(DocxBlock(line, TABLE_ROW_STYLE) for line in table_to_lines(item))
        else:
            blocks.append(DocxBlock(item.text, style_name(item), is_bold(item)))
    return blocks


def open_docx(file_path: Path) -> Document:
    """Open a .docx file, turning library errors into DocxReadError."""
    try:
        return docx.Document(str(file_path))
    except (OSError, OpcError, BadZipFile) as e:
        raise DocxReadError(f"Error loading docx file {file_path}: {e}") from e


def style_name(paragraph: Paragraph) -> str:
    """Return the paragraph's style name, or "" if it has none."""
    style = paragraph.style
    return style.name if style is not None and style.name else ""


def is_bold(paragraph: Paragraph) -> bool:
    """True when every piece of visible text in the paragraph is bold."""
    runs = [run for run in paragraph.runs if run.text.strip()]
    return bool(runs) and all(run_is_bold(run, paragraph) for run in runs)


def run_is_bold(run: Run, paragraph: Paragraph) -> bool:
    """True when a run (a piece of text with one format) is bold."""
    if run.bold is not None:
        return run.bold
    # Not set on the run itself, so it comes from the run's or the paragraph's style.
    for style in (run.style, paragraph.style):
        if style is not None and style.font.bold is not None:
            return style.font.bold
    return False


def table_to_lines(table: Table) -> list[str]:
    """Turn each table row into one line of text."""
    return [" | ".join(cell.text for cell in row.cells) for row in table.rows]
