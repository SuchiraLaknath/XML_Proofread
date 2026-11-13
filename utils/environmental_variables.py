"""Read single environment variables, loading .env first.

The .env file is loaded the first time a variable is read, not when this module
is imported, so importing it has no side effects. Variables already set in the
environment win over values in .env.
"""

import functools
import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@functools.cache
def load_env_once() -> None:
    """Load .env into the environment (only the first time this is called)."""
    load_dotenv()


def get_variable(name: str, default: str | None = None) -> str | None:
    """Return an environment variable, or default if it is not set."""
    load_env_once()
    return os.environ.get(name, default)


def get_text_variable(name: str, default: str) -> str:
    """Return an environment variable as text, or default when it is not set or empty.

    Spaces around the value are removed, so "OPENAI_MODEL= gpt-4.1 " works too.
    """
    raw = get_variable(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def get_int_variable(name: str, default: int, minimum: int = 1) -> int:
    """Return an environment variable as a whole number, or default.

    The default is used when the variable is not set or empty. A value that is
    not a whole number, or is below minimum, is logged as a warning and the
    default is used, so a typo in .env never stops the program.
    """
    raw = get_variable(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("%s=%r is not a whole number; using the default %d", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%d is below the minimum %d; using the default %d", name, value, minimum, default)
        return default
    return value
