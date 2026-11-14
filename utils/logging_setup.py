"""Set up logging for the program.

Log messages go to stderr, so stdout stays free for the program's real output
(the final summary). Setting up is safe to repeat: it never adds a second
handler and never removes handlers that other code (for example pytest) added.
"""

import logging
import sys

LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s - %(message)s"
DATE_FORMAT = "%H:%M:%S"
HANDLER_NAME = "app-stderr"  # lets us find our own handler again

# Libraries that log a line for every HTTP request; shown only in debug mode.
NOISY_LOGGERS = ("httpx", "httpx2")


def setup_logging(level: int = logging.INFO) -> None:
    """Send log messages of `level` and above to stderr.

    Args:
        level: the lowest level to show, e.g. logging.INFO or logging.DEBUG.
    """
    root = logging.getLogger()
    root.setLevel(level)
    # One log line per HTTP request is too much, except when debugging.
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET if level <= logging.DEBUG else logging.WARNING)
    if find_our_handler(root) is not None:  # already set up: don't print every line twice
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(handler)


def find_our_handler(logger: logging.Logger) -> logging.Handler | None:
    """Find the handler setup_logging added.

    Args:
        logger: the logger to look in (the root logger).

    Returns:
        That handler, or None if it is not there.
    """
    for handler in logger.handlers:
        if handler.get_name() == HANDLER_NAME:
            return handler
    return None


def get_logger(name: str, debug: bool = False) -> logging.Logger:
    """Return a named logger, setting up logging first if it isn't yet.

    Args:
        name: the logger's name, usually __name__.
        debug: True turns on DEBUG messages for the whole program.

    Returns:
        The logger.
    """
    root = logging.getLogger()
    if debug:
        setup_logging(logging.DEBUG)
    elif find_our_handler(root) is None:
        setup_logging(logging.INFO)
    return logging.getLogger(name)


def log_message(logger: logging.Logger | None, message: str, error: bool = False) -> None:
    """Log a message as INFO, or as ERROR with the current traceback.

    Args:
        logger: the logger to use; None means do nothing.
        message: the text to log.
        error: True logs it as ERROR with the traceback of the exception being handled.
    """
    if logger is None:
        return
    if error:
        # exc_info adds the traceback of the exception being handled, if any.
        logger.error(message, exc_info=True)
    else:
        logger.info(message)
