"""Read or write a supported file, choosing the helper from the file extension.

    template = read_file("system_prompt.md", directory="prompt_templates/xml_proofread")
    guide_text = read_file("examples/Style_Guide.docx")

The extension check ignores case, so "NOTES.MD" works too.

A .docx file is read as plain text, one paragraph per line, without its
headings. For the style guide use proof_read_process.rule_loader.load_style_guide(),
which keeps the headings so the AI can name the rule it applies.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .read_docx import read_docx_file
from .read_write_md import read_md_file, write_md_file
from .read_write_xml import read_xml_file, write_xml_file

READERS: dict[str, Callable[[Path], Any]] = {
    ".md": read_md_file,
    ".docx": read_docx_file,
    ".xml": read_xml_file,
}

WRITERS: dict[str, Callable[[Any, Path], None]] = {
    ".md": write_md_file,
    ".xml": write_xml_file,
}


def read_file(file_path: str | Path, directory: str | Path | None = None) -> Any:
    """Read a file with the reader that matches its extension.

    Args:
        file_path: the file, e.g. "system_prompt.md".
        directory: the folder that holds it; None means the path is used as given.

    Returns:
        The text for .md and .docx files, or an XmlFile for .xml files.

    Raises:
        ValueError: the extension is not supported.
        MdReadError, DocxReadError or XmlReadError: the file is missing or can't be read.
    """
    path = join_path(file_path, directory)
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"Cannot read {path.name}: supported extensions are {', '.join(READERS)}")
    return reader(path)


def write_file(data: Any, file_path: str | Path, directory: str | Path | None = None) -> None:
    """Write data with the writer that matches the file's extension.

    Args:
        data: the text (.md) or the XmlFile (.xml) to write.
        file_path: the file to write.
        directory: the folder to put it in; None means the path is used as given.

    Raises:
        ValueError: the extension is not supported.
        MdWriteError or XmlWriteError: the file can't be written.
    """
    path = join_path(file_path, directory)
    writer = WRITERS.get(path.suffix.lower())
    if writer is None:
        raise ValueError(f"Cannot write {path.name}: supported extensions are {', '.join(WRITERS)}")
    writer(data, path)


def join_path(file_path: str | Path, directory: str | Path | None) -> Path:
    """Put file_path inside directory, if a directory is given.

    Args:
        file_path: the file.
        directory: the folder, or None.

    Returns:
        The combined path.
    """
    if directory is None:
        return Path(file_path)
    return Path(directory) / file_path
