import logging
from pathlib import Path

_logger = logging.getLogger("bluetooth_2_usb")
_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%y-%m-%d %H:%M:%S"
)


def get_logger() -> logging.Logger:
    if not _logger.handlers:
        _logger.setLevel(logging.INFO)
        stdout_handler = logging.StreamHandler()
        stdout_handler.setFormatter(_formatter)
        _logger.addHandler(stdout_handler)
    return _logger


def add_file_handler(log_path: str) -> None:
    resolved = str(Path(log_path).expanduser().resolve())
    for handler in get_logger().handlers:
        if isinstance(handler, logging.FileHandler):
            existing = getattr(handler, "baseFilename", None)
            if existing and str(Path(existing).resolve()) == resolved:
                return
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(_formatter)
    get_logger().addHandler(file_handler)
