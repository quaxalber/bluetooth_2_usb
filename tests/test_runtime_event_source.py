import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.runtime_event_source import RuntimeEventSource
from bluetooth_2_usb.runtime_events import DeviceAdded, DeviceRemoved, UdcStateChanged


class _FakeMonitor:
    def __init__(self, events=None) -> None:
        self.events = list(events or [])
        self.filtered = []
        self.started = False
        self._read_fd, self._write_fd = os.pipe()

    def filter_by(self, *args) -> None:
        self.filtered.append(args)

    def start(self) -> None:
        self.started = True

    def fileno(self) -> int:
        return self._read_fd

    def poll(self, timeout=0):
        del timeout
        if not self.events:
            return None
        return self.events.pop(0)

    def close(self) -> None:
        os.close(self._read_fd)
        os.close(self._write_fd)


class RuntimeEventSourceTest(unittest.IsolatedAsyncioTestCase):
    def _build_source(
        self,
        events: asyncio.Queue,
        *,
        monitor: _FakeMonitor,
        udc_path: Path | None = None,
        poll_interval: float = 0.01,
    ) -> RuntimeEventSource:
        with patch(
            "bluetooth_2_usb.runtime_event_source.pyudev.Context",
            return_value=object(),
        ):
            with patch(
                "bluetooth_2_usb.runtime_event_source.pyudev.Monitor.from_netlink",
                return_value=monitor,
            ):
                return RuntimeEventSource(
                    events,
                    udc_path=udc_path,
                    poll_interval=poll_interval,
                )

    async def test_runtime_event_source_emits_udev_hotplug_events(self) -> None:
        queue = asyncio.Queue()
        monitor = _FakeMonitor(
            [
                SimpleNamespace(action="add", device_node="/dev/input/event7"),
                SimpleNamespace(action="remove", device_node="/dev/input/event7"),
                SimpleNamespace(action="add", device_node="/dev/not-input"),
            ]
        )
        source = self._build_source(queue, monitor=monitor)

        source._drain_udev_events()

        self.assertEqual(await queue.get(), DeviceAdded("/dev/input/event7"))
        self.assertEqual(await queue.get(), DeviceRemoved("/dev/input/event7"))
        self.assertTrue(queue.empty())
        monitor.close()

    async def test_runtime_event_source_emits_udc_state_changes(self) -> None:
        queue = asyncio.Queue()
        monitor = _FakeMonitor()
        with tempfile.TemporaryDirectory() as tmpdir:
            udc_path = Path(tmpdir) / "state"
            udc_path.write_text("not_attached\n", encoding="utf-8")
            source = self._build_source(queue, monitor=monitor, udc_path=udc_path)

            task = asyncio.create_task(source.run())
            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=1),
                UdcStateChanged("not_attached"),
            )

            udc_path.write_text("configured\n", encoding="utf-8")
            self.assertEqual(
                await asyncio.wait_for(queue.get(), timeout=1),
                UdcStateChanged("configured"),
            )

            source.stop()
            await asyncio.wait_for(task, timeout=1)

        self.assertTrue(monitor.started)
        self.assertIsNone(source._loop)
        monitor.close()

    async def test_runtime_event_source_treats_missing_udc_path_as_not_attached(
        self,
    ) -> None:
        queue = asyncio.Queue()
        monitor = _FakeMonitor()
        source = self._build_source(queue, monitor=monitor, udc_path=None)

        task = asyncio.create_task(source.run())
        self.assertEqual(
            await asyncio.wait_for(queue.get(), timeout=1),
            UdcStateChanged("not_attached"),
        )

        source.stop()
        await asyncio.wait_for(task, timeout=1)
        monitor.close()
