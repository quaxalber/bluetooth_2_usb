from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from .paths import PATHS

_LOG_FILE = None
_PREVIOUS_STDOUT = None
_PREVIOUS_STDERR = None
_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"


def _style(text: str, *styles: str) -> str:
    isatty = getattr(sys.stdout, "isatty", None)
    if isatty is None or not isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{''.join(styles)}{text}{_RESET}"


def bold(message: str) -> str:
    return _style(message, _BOLD)


class OpsError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def info(message: str) -> None:
    print(_style(f"[i] {message}", _CYAN))


def ok(message: str) -> None:
    print(_style(f"[+] {message}", _GREEN))


def warn(message: str) -> None:
    print(_style(f"[!] {message}", _YELLOW))


def warn_fail(message: str) -> None:
    print(_style(f"[!] {message}", _RED))


def ok_final(message: str) -> None:
    print(_style(f"[+] {message}", _BOLD, _GREEN))


def fail_final(message: str) -> None:
    print(_style(f"[!] {message}", _BOLD, _RED))


def fail(message: str, exit_code: int = 1) -> None:
    raise OpsError(_style(message, _RED), exit_code)


def ensure_root() -> None:
    if os.geteuid() != 0:
        fail("Run this command as root.")


def require_commands(commands: Iterable[str]) -> None:
    missing = [command for command in commands if shutil.which(command) is None]
    for command in missing:
        warn(f"Missing command: {command}")
    if missing:
        fail("Install the missing commands and retry.")


def run(
    args: list[str | Path],
    *,
    check: bool = True,
    capture: bool = False,
    text: bool = True,
    input_text: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    command_args = [str(arg) for arg in args]
    command = " ".join(command_args)
    try:
        completed = subprocess.run(
            command_args, check=False, capture_output=capture, text=text, input=input_text, timeout=timeout
        )
    except FileNotFoundError as exc:
        missing = exc.filename or command_args[0]
        fail(f"Required command not found: {missing}\n{exc}")
    except subprocess.TimeoutExpired as exc:
        details = []
        if isinstance(exc.stdout, str) and exc.stdout:
            details.append(exc.stdout.strip())
        if isinstance(exc.stderr, str) and exc.stderr:
            details.append(exc.stderr.strip())
        detail = "\n".join(detail for detail in details if detail)
        message = f"Command timed out after {timeout}s: {command}"
        if detail:
            message = f"{message}\n{detail}"
        fail(message)
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() if completed.stderr else ""
        if detail:
            fail(f"Command failed ({completed.returncode}): {command}\n{detail}")
        fail(f"Command failed ({completed.returncode}): {command}")
    return completed


def output(args: list[str | Path], *, timeout: float | None = None) -> str:
    completed = run(args, capture=True, timeout=timeout)
    return completed.stdout.strip()


def command_ok(args: list[str | Path], *, timeout: float | None = None) -> bool:
    return run(args, check=False, capture=True, timeout=timeout).returncode == 0


def backup_file(path: Path) -> None:
    if path.is_file():
        shutil.copy2(path, path.with_name(f"{path.name}.bak.{timestamp()}"))


def prepare_log(prefix: str) -> Path:
    global _LOG_FILE, _PREVIOUS_STDERR, _PREVIOUS_STDOUT

    close_log()
    PATHS.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = PATHS.log_dir / f"{prefix}_{timestamp()}.log"
    _LOG_FILE = log_path.open("a", encoding="utf-8")
    _PREVIOUS_STDOUT = sys.stdout
    _PREVIOUS_STDERR = sys.stderr
    sys.stdout = _Tee(_PREVIOUS_STDOUT, _LOG_FILE)  # type: ignore[assignment]
    sys.stderr = _Tee(_PREVIOUS_STDERR, _LOG_FILE)  # type: ignore[assignment]
    info(f"Logging to {log_path}")
    return log_path


def close_log() -> None:
    global _LOG_FILE, _PREVIOUS_STDERR, _PREVIOUS_STDOUT

    if _LOG_FILE is None:
        return
    if _PREVIOUS_STDOUT is not None:
        sys.stdout = _PREVIOUS_STDOUT
    if _PREVIOUS_STDERR is not None:
        sys.stderr = _PREVIOUS_STDERR
    _LOG_FILE.close()
    _LOG_FILE = None
    _PREVIOUS_STDOUT = None
    _PREVIOUS_STDERR = None


class _Tee:
    def __init__(self, *streams: object) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)  # type: ignore[attr-defined]
            stream.flush()  # type: ignore[attr-defined]
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()  # type: ignore[attr-defined]

    def isatty(self) -> bool:
        return bool(getattr(self._streams[0], "isatty", lambda: False)())

    def __getattr__(self, name: str):
        return getattr(self._streams[0], name)
