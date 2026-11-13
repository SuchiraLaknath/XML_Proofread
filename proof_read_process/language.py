"""Check the --lang value and turn it into a language name for the prompt.

    "en-US" -> tag "en-US", name "English (United States)"
    "EN-gb" -> tag "en-GB", name "English (United Kingdom)"

The tag must be valid BCP-47 and name a known language (and region, if one is
given). "und", "en-ZZ" or "english" are rejected with a clear error.
"""

from dataclasses import dataclass

import langcodes


class LanguageError(ValueError):
    """Raised when --lang is not a usable BCP-47 language tag."""


@dataclass(frozen=True)
class Locale:
    """A checked language tag and its English name."""

    tag: str  # standard form, e.g. "en-US"
    name: str  # e.g. "English (United States)"


def parse_language(value: str) -> Locale:
    """Check a BCP-47 tag and return its standard form and name."""
    text = value.strip()
    if not text or not langcodes.tag_is_valid(text):
        raise LanguageError(f"--lang {value!r} is not a valid BCP-47 language tag (examples: en, en-US, fr)")
    tag = langcodes.standardize_tag(text)
    name = langcodes.Language.get(tag).display_name()
    if "unknown" in name.lower():
        raise LanguageError(f"--lang {value!r} is not a known language or region ({name})")
    return Locale(tag=tag, name=name)
