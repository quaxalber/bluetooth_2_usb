import asyncio
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bluetooth_2_usb.runtime.keylogger_fifo import KeyloggerFifo, publish_key_event, set_publisher


class KeyloggerFifoTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "events.fifo"
        self.fifo = None
        set_publisher(None)

    async def asyncTearDown(self) -> None:
        set_publisher(None)
        if self.fifo is not None:
            await self.fifo.close()

    def start_fifo(self, *, queue_size=1024):
        self.fifo = KeyloggerFifo(str(self.path), queue_size=queue_size)
        self.fifo.start()
        return self.fifo

    async def test_creates_private_fifo_and_unlinks_on_close(self) -> None:
        fifo = self.start_fifo()
        info = self.path.lstat()
        self.assertTrue(stat.S_ISFIFO(info.st_mode))
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)

        await fifo.close()
        self.fifo = None
        self.assertFalse(self.path.exists())

    async def test_does_not_replace_regular_file(self) -> None:
        self.path.write_text("keep me", encoding="utf-8")
        fifo = KeyloggerFifo(str(self.path))
        with self.assertRaises(RuntimeError):
            fifo.start()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "keep me")

    async def test_publishes_complete_records_in_order(self) -> None:
        fifo = self.start_fifo()
        fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, fd)
        first = b"InputEvent(1, 2, 1, 30, 1)\n"
        second = b"InputEvent(1, 3, 1, 30, 0)\n"

        self.assertTrue(fifo.publish(first))
        self.assertTrue(fifo.publish(second))

        data = bytearray()
        async def read_records():
            while len(data) < len(first) + len(second):
                try:
                    data.extend(os.read(fd, 4096))
                except BlockingIOError:
                    pass
                if len(data) < len(first) + len(second):
                    await asyncio.sleep(0.001)
        await asyncio.wait_for(read_records(), timeout=1)
        self.assertEqual(bytes(data), first + second)

    async def test_full_queue_drops_immediately(self) -> None:
        fifo = self.start_fifo(queue_size=1)
        self.assertTrue(fifo.publish(b"first\n"))
        self.assertFalse(fifo.publish(b"second\n"))

    async def test_helper_preserves_existing_line_format(self) -> None:
        event = Mock(sec=1790353030, usec=940110, type=1, code=46, value=1)
        publisher = Mock()
        set_publisher(publisher)
        publish_key_event(event)
        publisher.publish.assert_called_once_with(b"InputEvent(1790353030, 940110, 1, 46, 1)\n")

    async def test_close_does_not_unlink_replacement(self) -> None:
        fifo = self.start_fifo()
        self.path.unlink()
        self.path.write_text("replacement", encoding="utf-8")

        await fifo.close()
        self.fifo = None
        self.assertEqual(self.path.read_text(encoding="utf-8"), "replacement")
