from __future__ import annotations

import json
import os
import signal
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .constants import EXIT_ACCESS, EXIT_INTERRUPTED

LOOPBACK_LOCK_PATH = Path(tempfile.gettempdir()) / "bluetooth_2_usb_loopback.lock"

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class LoopbackBusyError(RuntimeError):
    exit_code = EXIT_ACCESS


class LoopbackInterrupted(KeyboardInterrupt):
    exit_code = EXIT_INTERRUPTED

    def __init__(self, signum: int | None = None) -> None:
        self.signum = signum
        signal_name = None
        if signum is not None:
            try:
                signal_name = signal.Signals(signum).name
            except ValueError:
                signal_name = None
        self.signal_name = signal_name
        message = f"Loopback interrupted by {signal_name}" if signal_name is not None else "Loopback interrupted"
        super().__init__(message)


def _lock_loopback_file(lock_handle) -> None:
    if os.name == "nt":
        lock_handle.seek(0)
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_loopback_file(lock_handle) -> None:
    if os.name == "nt":
        lock_handle.seek(0)
        try:
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _open_loopback_lock_file():
    if os.name == "nt":
        return LOOPBACK_LOCK_PATH.open("a+", encoding="utf-8")

    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(LOOPBACK_LOCK_PATH, flags, 0o600)
    except OSError as exc:
        raise LoopbackBusyError(f"Unable to open loopback lock safely: {LOOPBACK_LOCK_PATH}: {exc}") from exc

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise LoopbackBusyError(f"Loopback lock path is not a regular file: {LOOPBACK_LOCK_PATH}")
        return os.fdopen(fd, "a+", encoding="utf-8")
    except (OSError, LoopbackBusyError):
        os.close(fd)
        raise


@contextmanager
def loopback_session(command: str, scenario: str):
    lock_handle = _open_loopback_lock_file()
    try:
        if lock_handle.tell() == 0:
            lock_handle.write("\n")
            lock_handle.flush()
        try:
            _lock_loopback_file(lock_handle)
        except OSError as exc:
            raise LoopbackBusyError(
                "Another Bluetooth-2-USB loopback session is already running " f"(lock: {LOOPBACK_LOCK_PATH})"
            ) from exc

        metadata = json.dumps({"pid": os.getpid(), "command": command, "scenario": scenario}, sort_keys=True)
        lock_handle.seek(0)
        lock_handle.truncate()
        lock_handle.write(metadata)
        lock_handle.flush()

        handled_signals = [
            sig
            for sig in (
                signal.SIGINT,
                signal.SIGTERM,
                getattr(signal, "SIGHUP", None),
                getattr(signal, "SIGQUIT", None),
            )
            if sig is not None
        ]
        previous_handlers = {handled_signal: signal.getsignal(handled_signal) for handled_signal in handled_signals}

        def _raise_interrupted(received_signal: int, _frame) -> None:
            raise LoopbackInterrupted(received_signal)

        for handled_signal in handled_signals:
            signal.signal(handled_signal, _raise_interrupted)

        try:
            yield
        finally:
            for handled_signal, previous_handler in previous_handlers.items():
                signal.signal(handled_signal, previous_handler)
    finally:
        try:
            _unlock_loopback_file(lock_handle)
        finally:
            lock_handle.close()
