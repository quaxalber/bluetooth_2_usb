from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from .paths import PATHS


class OpsError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def info(message: str) -> None:
    print(f"[i] {message}")


def ok(message: str) -> None:
    print(f"[+] {message}")


def warn(message: str) -> None:
    print(f"[!] {message}")


def fail(message: str, exit_code: int = 1) -> None:
    raise OpsError(message, exit_code)


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
    completed = subprocess.run(
        [str(arg) for arg in args],
        check=False,
        capture_output=capture,
        text=text,
        input=input_text,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        command = " ".join(str(arg) for arg in args)
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
    PATHS.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = PATHS.log_dir / f"{prefix}_{timestamp()}.log"
    log_file = log_path.open("a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, log_file)  # type: ignore[assignment]
    sys.stderr = _Tee(sys.stderr, log_file)  # type: ignore[assignment]
    info(f"Logging to {log_path}")
    return log_path


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
