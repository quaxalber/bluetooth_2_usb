from __future__ import annotations

import asyncio
from pathlib import Path

from .logging import get_logger
from .relay_controller import RelayController

logger = get_logger(__name__)

try:
    import pyudev
except ModuleNotFoundError:

    class _MissingPyudevModule:
        class Device:
            device_node = None

        class Context:
            def __init__(self, *_args, **_kwargs) -> None:
                raise ModuleNotFoundError(
                    "pyudev is required for runtime monitoring on this platform."
                )

        class Monitor:
            @staticmethod
            def from_netlink(*_args, **_kwargs):
                raise ModuleNotFoundError(
                    "pyudev is required for runtime monitoring on this platform."
                )

        class MonitorObserver:
            def __init__(self, *_args, **_kwargs) -> None:
                raise ModuleNotFoundError(
                    "pyudev is required for runtime monitoring on this platform."
                )

    pyudev = _MissingPyudevModule()


class RuntimeMonitor:
    """
    Monitors runtime state changes that affect relay liveness.

    This combines UDC polling and udev input hotplug observation so the CLI only
    has one runtime monitor lifecycle to manage.
    """

    def __init__(
        self,
        relay_controller: RelayController,
        relaying_active: asyncio.Event,
        udc_path: Path | None,
        poll_interval: float = 0.5,
    ) -> None:
        self._relay_controller = relay_controller
        self._relaying_active = relaying_active
        self._udc_path = udc_path
        self._poll_interval = poll_interval

        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_state: str | None = None

        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by("input")
        self._observer = pyudev.MonitorObserver(monitor, self._udev_event_callback)

        if self._udc_path is None:
            logger.warning(
                "UDC state file not found. Cable monitoring may be unavailable.",
            )
        elif not self._udc_path.is_file():
            logger.warning(
                "UDC state file %s not found. Cable monitoring may be unavailable.",
                self._udc_path,
            )

    async def __aenter__(self):
        self._stop_event.clear()
        self._last_state = None
        self._observer.start()
        self._task = asyncio.create_task(self._poll_state())
        logger.debug("RuntimeMonitor started.")
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        self._stop_event.set()
        self._observer.stop()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.debug("RuntimeMonitor stopped.")
        return False

    async def _poll_state(self):
        while not self._stop_event.is_set():
            new_state = self._read_udc_state()
            if new_state != self._last_state:
                self._handle_state_change(new_state)
                self._last_state = new_state
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
            except TimeoutError:
                pass

    def _read_udc_state(self) -> str:
        if self._udc_path is None:
            return "not_attached"

        try:
            with open(self._udc_path, encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            logger.debug("Unable to read UDC state from %s", self._udc_path)
            return "not_attached"

    def _handle_state_change(self, new_state: str):
        logger.debug(f"UDC state changed to '{new_state}'")
        if new_state == "configured":
            self._relaying_active.set()
        else:
            self._relaying_active.clear()

    def _udev_event_callback(self, action: str, device: pyudev.Device) -> None:
        device_node = device.device_node
        if not device_node or not device_node.startswith("/dev/input/event"):
            return

        if action == "add":
            logger.debug(f"RuntimeMonitor: Added input => {device_node}")
            self._relay_controller.notify_device_added(device_node)
        elif action == "remove":
            logger.debug(f"RuntimeMonitor: Removed input => {device_node}")
            self._relay_controller.notify_device_removed(device_node)
