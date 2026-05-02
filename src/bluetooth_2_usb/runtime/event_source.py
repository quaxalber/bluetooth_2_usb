from __future__ import annotations

import asyncio
from pathlib import Path

from ..logging import get_logger
from .events import DeviceAdded, DeviceRemoved, RuntimeEvent, UdcState, UdcStateChanged

logger = get_logger(__name__)

try:
    import pyudev
except ModuleNotFoundError:

    class _MissingPyudevModule:
        class Device:
            device_node = None

        class Context:
            def __init__(self, *_args, **_kwargs) -> None:
                raise ModuleNotFoundError("pyudev is required for runtime monitoring on this platform.")

        class Monitor:
            @staticmethod
            def from_netlink(*_args, **_kwargs):
                raise ModuleNotFoundError("pyudev is required for runtime monitoring on this platform.")

    pyudev = _MissingPyudevModule()


class RuntimeEventSource:
    """
    Emits runtime events from UDC state polling and udev input hotplug.
    """

    def __init__(self, events: asyncio.Queue[RuntimeEvent], udc_path: Path | None, poll_interval: float = 0.5) -> None:
        self._events = events
        self._udc_path = udc_path
        self._poll_interval = poll_interval

        self._stop_event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_state: UdcState | None = None

        context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(context)
        self._monitor.filter_by("input")

        if self._udc_path is None:
            logger.warning("UDC state file not found. Cable monitoring may be unavailable.")
        elif not self._udc_path.is_file():
            logger.warning("UDC state file %s not found. Cable monitoring may be unavailable.", self._udc_path)

    async def run(self) -> None:
        self._start_monitoring()
        try:
            await self._poll_udc_state()
        finally:
            self._stop_monitoring()

    def stop(self) -> None:
        self._stop_event.set()

    def _start_monitoring(self) -> None:
        self._stop_event.clear()
        self._loop = asyncio.get_running_loop()
        self._last_state = None
        self._monitor.start()
        self._loop.add_reader(self._monitor.fileno(), self._drain_udev_events)
        logger.debug("RuntimeEventSource started.")

    def _stop_monitoring(self) -> None:
        self._stop_event.set()
        if self._loop is not None:
            self._loop.remove_reader(self._monitor.fileno())
        self._loop = None
        logger.debug("RuntimeEventSource stopped.")

    async def _poll_udc_state(self) -> None:
        while not self._stop_event.is_set():
            new_state = self._read_udc_state()
            if new_state != self._last_state:
                await self._events.put(UdcStateChanged(new_state))
                self._last_state = new_state
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    def _read_udc_state(self) -> UdcState:
        if self._udc_path is None:
            return UdcState.NOT_ATTACHED

        try:
            with open(self._udc_path, encoding="utf-8") as handle:
                return UdcState.from_raw(handle.read())
        except OSError:
            logger.debug("Unable to read UDC state from %s", self._udc_path)
            return self._last_state or UdcState.NOT_ATTACHED

    def _drain_udev_events(self) -> None:
        while True:
            try:
                device = self._monitor.poll(timeout=0)
            except OSError:
                logger.debug("Unable to read udev monitor event.", exc_info=True)
                return
            if device is None:
                return
            self._emit_udev_event(device)

    def _emit_udev_event(self, device: pyudev.Device) -> None:
        device_node = device.device_node
        if not device_node or not device_node.startswith("/dev/input/event"):
            return

        action = getattr(device, "action", None)
        if action == "add":
            logger.debug("Input device added: %s", device_node)
            self._events.put_nowait(DeviceAdded(device_node))
        elif action == "remove":
            logger.debug("Input device removed: %s", device_node)
            self._events.put_nowait(DeviceRemoved(device_node))
