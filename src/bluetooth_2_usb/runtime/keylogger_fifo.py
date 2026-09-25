from __future__ import annotations

import asyncio
import errno
import os
import stat
from pathlib import Path

from ..logging import get_logger

_publisher: KeyloggerFifo | None = None


def set_publisher(publisher: KeyloggerFifo | None) -> None:
    global _publisher
    _publisher = publisher


def publish_key_event(event) -> None:
    if _publisher is not None:
        try:
            serialized = f"InputEvent({event.sec}, {event.usec}, {event.type}, {event.code}, {event.value})\n"
            _publisher.publish(serialized.encode())
        except:
            logger.warning("Error publishing to keylogger fifo: %s", exc)


class KeyloggerFifo:
    def __init__(self, path: str, queue_size: int = 1024) -> None:
        self.path = Path(path)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task[None] | None = None
        self._fd: int | None = None
        self._identity: tuple[int, int] | None = None

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Keylogger FIFO already started")

        # Parent directory must already exist. Never replace another file.
        try:
            os.mkfifo(self.path, 0o600)
        except FileExistsError:
            pass

        info = self.path.lstat()
        if not stat.S_ISFIFO(info.st_mode):
            raise RuntimeError(f"Keylogger path is not a FIFO: {self.path}")
        if info.st_uid != os.geteuid():
            raise RuntimeError(f"Keylogger FIFO has a different owner: {self.path}")

        self._identity = (info.st_dev, info.st_ino)
        self._task = asyncio.create_task(self._write_loop(), name="keylogger FIFO writer")

    def publish(self, record: bytes) -> bool:
        """Enqueue without waiting; return False if unavailable or full."""
        if self._task is None or self._task.done():
            return False
        if not record or len(record) > 4096:
            return False

        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            return False
        return True

    async def _write_loop(self) -> None:
        try:
            while True:
                record = await self._queue.get()
                try:
                    self._write_record(record)
                finally:
                    self._queue.task_done()
        finally:
            self._close_fd()

    def _write_record(self, record: bytes) -> None:
        if self._fd is None:
            try:
                fd = os.open(
                    self.path,
                    os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW,
                )
                info = os.fstat(fd)
                if not stat.S_ISFIFO(info.st_mode) or (
                    info.st_dev, info.st_ino
                ) != self._identity:
                    os.close(fd)
                    return
                self._fd = fd
            except OSError:
                # Observation must never interrupt HID forwarding.
                return

        try:
            os.write(self._fd, record)
        except BlockingIOError:
            pass  # FIFO full: drop this record.
        except OSError:
            # Includes EPIPE when the reader disconnects.
            self._close_fd()

    def _close_fd(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._close_fd()

        if self._identity is not None:
            try:
                info = self.path.lstat()
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISFIFO(info.st_mode) and (
                    info.st_dev, info.st_ino
                ) == self._identity:
                    self.path.unlink()
            self._identity = None