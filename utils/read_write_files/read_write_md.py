"""Read and write Markdown (.md) files.

Markdown is kept as plain UTF-8 text. Nothing is parsed or rendered, because the
callers (for example the prompt templates) only need the raw text.
"""

from pathlib import Path


class MdReadError(RuntimeError):
    """Raised when a Markdown file cannot be opened or read."""


class MdWriteError(RuntimeError):
    """Raised when a Markdown file cannot be written."""


def read_md_file(file_path: str | Path) -> str:
    """Return the full text of a Markdown file."""
    file_path = Path(file_path)
    try:
        return file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise MdReadError(f"Error loading Markdown file {file_path}: {e}") from e


def write_md_file(text: str, file_path: str | Path) -> None:
    """Write text to a Markdown file, replacing the file if it exists."""
    file_path = Path(file_path)
    try:
        # newline="" stops Windows from turning "\n" into "\r\n",
        # so the file is the same on every operating system.
        with file_path.open("w", encoding="utf-8", newline="") as f:
            f.write(text)
    except OSError as e:
        raise MdWriteError(f"Error writing Markdown file {file_path}: {e}") from e
