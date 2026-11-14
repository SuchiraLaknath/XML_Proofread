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
    """Return the text of a .docx file, one paragraph or table row per line.

    Args:
        file_path: the .docx file.

    Returns:
        The document's text.

    Raises:
        DocxReadError: the file can't be opened or read.
    """
    return "\n".join(block.text for block in read_docx_blocks(file_path))


def read_docx_blocks(file_path: str | Path) -> list[DocxBlock]:
    """Return every paragraph and table row of a .docx file, with its style name.

    Args:
        file_path: the .docx file.

    Returns:
        The blocks in document order.

    Raises:
        DocxReadError: the file can't be opened or read.
    """
    document = open_docx(Path(file_path))
    blocks: list[DocxBlock] = []
    # Paragraphs and tables, in the order they appear in the document.
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            blocks.extend(DocxBlock(line, TABLE_ROW_STYLE) for line in table_to_lines(item))
        else:
            blocks.append(DocxBlock(item.text, style_name(item), is_bold(item)))
    return blocks


def open_docx(file_path: Path) -> Document:
    """Open a .docx file, turning library errors into DocxReadError.

    Args:
        file_path: the .docx file.

    Returns:
        The opened document.

    Raises:
        DocxReadError: the file is missing or is not a valid .docx.
    """
    try:
        return docx.Document(str(file_path))
    except (OSError, OpcError, BadZipFile) as e:
        raise DocxReadError(f"Error loading docx file {file_path}: {e}") from e


def style_name(paragraph: Paragraph) -> str:
    """Return the paragraph's style name.

    Args:
        paragraph: a Word paragraph.

    Returns:
        The style name, e.g. "Heading 1", or "" if it has none.
    """
    style = paragraph.style
    return style.name if style is not None and style.name else ""


def is_bold(paragraph: Paragraph) -> bool:
    """Tell whether every piece of visible text in the paragraph is bold.

    Args:
        paragraph: a Word paragraph.

    Returns:
        True when all of its text is bold.
    """
    runs = [run for run in paragraph.runs if run.text.strip()]
    return bool(runs) and all(run_is_bold(run, paragraph) for run in runs)


def run_is_bold(run: Run, paragraph: Paragraph) -> bool:
    """Tell whether a run (a piece of text with one format) is bold.

    Args:
        run: the run.
        paragraph: the paragraph it belongs to; its style is checked when the run doesn't say.

    Returns:
        True when the run is bold.
    """
    if run.bold is not None:
        return run.bold
    # Not set on the run itself, so it comes from the run's or the paragraph's style.
    for style in (run.style, paragraph.style):
        if style is not None and style.font.bold is not None:
            return style.font.bold
    return False


def table_to_lines(table: Table) -> list[str]:
    """Turn each table row into one line of text.

    Args:
        table: a Word table.

    Returns:
        One line per row, with the cells joined by " | ".
    """
    return [" | ".join(cell.text for cell in row.cells) for row in table.rows]
