"""Tests for utils/logging_setup.py."""

import logging
from collections.abc import Iterator

import pytest

from utils.logging_setup import HANDLER_NAME, get_logger, log_message, setup_logging


def our_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME]


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """Undo whatever the test did to the root logger."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_setup_is_safe_to_repeat() -> None:
    setup_logging()
    setup_logging(logging.DEBUG)
    assert len(our_handlers()) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_setup_keeps_other_handlers() -> None:
    other = logging.NullHandler()
    logging.getLogger().addHandler(other)
    setup_logging()
    assert other in logging.getLogger().handlers


def test_logs_go_to_stderr_not_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    for handler in our_handlers():
        logging.getLogger().removeHandler(handler)
    setup_logging()  # created inside the test, so it writes to the captured stderr
    logging.getLogger("demo").warning("careful")
    captured = capsys.readouterr()
    assert "careful" in captured.err
    assert captured.out == ""


def test_http_request_logs_are_hidden_unless_debugging() -> None:
    setup_logging(logging.INFO)
    assert not logging.getLogger("httpx2").isEnabledFor(logging.INFO)
    assert logging.getLogger("httpx2").isEnabledFor(logging.WARNING)
    setup_logging(logging.DEBUG)
    assert logging.getLogger("httpx2").isEnabledFor(logging.DEBUG)


def test_get_logger_does_not_reset_debug_level() -> None:
    get_logger("a", debug=True)
    get_logger("b")
    assert logging.getLogger().level == logging.DEBUG


def test_log_message(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("demo")
    with caplog.at_level(logging.INFO):
        log_message(logger, "hello")
        try:
            raise ValueError("boom")
        except ValueError:
            log_message(logger, "failed", error=True)
        log_message(None, "ignored")
    assert [r.levelname for r in caplog.records] == ["INFO", "ERROR"]
    assert caplog.records[1].exc_info is not None
