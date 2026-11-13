"""Shared test setup."""

import pytest

from llms.anthropic_llm import MAX_TOKENS_ENV
from llms.anthropic_llm import MODEL_ENV as ANTHROPIC_MODEL_ENV
from llms.openai_llm import MODEL_ENV as OPENAI_MODEL_ENV
from llms.openai_llm import REASONING_EFFORT_ENV
from llms.rate_limit import RETRIES_ENV, WAIT_ENV

# Settings that a developer's own .env could change. An empty value means "use the default",
# and a variable that is already set (even to "") is never overwritten by .env.
SETTINGS_TO_RESET = (
    RETRIES_ENV,
    WAIT_ENV,
    OPENAI_MODEL_ENV,
    REASONING_EFFORT_ENV,
    ANTHROPIC_MODEL_ENV,
    MAX_TOKENS_ENV,
)


@pytest.fixture(autouse=True)
def default_settings_and_no_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never really sleep in tests, and ignore the developer's own .env settings."""
    monkeypatch.setattr("llms.rate_limit.sleep", lambda seconds: None)
    for name in SETTINGS_TO_RESET:
        monkeypatch.setenv(name, "")
