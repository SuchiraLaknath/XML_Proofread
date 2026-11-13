"""Load prompt templates.

Templates use string.Template placeholders ($language, $paragraph), not
str.format, because the prompts contain JSON examples with { } that
str.format would treat as placeholders. Write $$ for a literal dollar sign.
"""

from pathlib import Path
from string import Template
from typing import Any

from utils.read_write_files.read_write_file import read_file


def get_prompt(
    prompt_template_path: str | Path,
    prompt_dir: str | Path | None = None,
    mapped_data: dict[str, Any] | None = None,
) -> str:
    """Load a text template and fill in its $placeholders from mapped_data.

    Raises KeyError if the template uses a placeholder that mapped_data lacks,
    so a missing value is never sent to the model silently.
    """
    template = read_file(file_path=prompt_template_path, directory=prompt_dir)
    if not isinstance(template, str):
        raise ValueError(f"Prompt template {prompt_template_path} must be a Markdown (.md) file")
    if mapped_data is None:
        return template
    return Template(template).substitute(mapped_data)
