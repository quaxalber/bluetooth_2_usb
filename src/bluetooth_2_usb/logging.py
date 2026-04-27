import logging
from pathlib import Path

PACKAGE_LOGGER_NAME = "bluetooth_2_usb"

_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%y-%m-%d %H:%M:%S",
)


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
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(_formatter)
    logger.addHandler(file_handler)
