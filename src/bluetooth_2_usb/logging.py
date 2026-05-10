import logging
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.text import Text

PACKAGE_LOGGER_NAME = "bluetooth_2_usb"
RICH_STATUS_SPINNER = "dots"
RICH_MIN_TEXT_WIDTH = 140

__all__ = [
    "Console",
    "ConsoleOptions",
    "Live",
    "PACKAGE_LOGGER_NAME",
    "RICH_MIN_TEXT_WIDTH",
    "RICH_STATUS_SPINNER",
    "RenderResult",
    "Text",
    "add_file_handler",
    "device_capture_console",
    "get_logger",
    "live",
    "plain_text_console",
    "status",
    "stderr_console",
    "stdout_console",
]

_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%y-%m-%d %H:%M:%S")


def _root_logger() -> logging.Logger:
    return logging.getLogger(PACKAGE_LOGGER_NAME)


def _ensure_root_logger_configured() -> logging.Logger:
    logger = _root_logger()
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        stdout_handler = logging.StreamHandler()
        stdout_handler.setFormatter(_formatter)
        logger.addHandler(stdout_handler)
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    _ensure_root_logger_configured()
    return logging.getLogger(PACKAGE_LOGGER_NAME if name is None else name)


def add_file_handler(log_path: str) -> None:
    resolved = str(Path(log_path).expanduser().resolve())
    logger = _ensure_root_logger_configured()
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            existing = getattr(handler, "baseFilename", None)
            if existing and str(Path(existing).resolve()) == resolved:
                return
    file_handler = logging.FileHandler(resolved)
    file_handler.setFormatter(_formatter)
    logger.addHandler(file_handler)


def stdout_console(**kwargs: object) -> Console:
    return Console(file=sys.stdout, **kwargs)


def stderr_console(**kwargs: object) -> Console:
    return Console(stderr=True, **kwargs)


def plain_text_console(file: TextIO, *, min_width: int = RICH_MIN_TEXT_WIDTH) -> Console:
    terminal_width = shutil.get_terminal_size(fallback=(min_width, 20)).columns
    return Console(
        file=file, force_terminal=False, no_color=True, color_system=None, width=max(terminal_width, min_width)
    )


@contextmanager
def status(message: str) -> Iterator[None]:
    with stdout_console().status(message, spinner=RICH_STATUS_SPINNER):
        yield


def live(
    renderable: object, *, console: Console | None = None, refresh_per_second: float = 4, transient: bool = False
) -> Live:
    return Live(renderable, console=console, refresh_per_second=refresh_per_second, transient=transient)


def device_capture_console() -> Console:
    return stderr_console(highlight=False)
