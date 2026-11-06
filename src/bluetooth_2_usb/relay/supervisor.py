from __future__ import annotations

import asyncio
import errno
from asyncio import TaskGroup
from dataclasses import dataclass
from enum import Enum, auto

from ..evdev.types import InputDevice
from ..gadgets.manager import HidGadgets
from ..inputs.battery import LOW_BATTERY_THRESHOLD_PERCENT, read_device_battery_percent
from ..inputs.filter import DeviceFilter
from ..inputs.mqtt import publish_device_battery
from ..inputs.inventory import (
    DEFAULT_SKIP_NAME_PREFIXES,
    DeviceEnumerationError,
    auto_relay_exclusion_reason,
    list_input_devices,
)
from ..logging import get_logger
from ..runtime.events import DeviceAdded, DeviceRemoved, RuntimeEvent, ShutdownRequested, UdcState, UdcStateChanged
from .gate import RelayGate
from .input import InputRelay
from .leds import KeyboardLedMirror
from .shortcut import ShortcutToggler

logger = get_logger(__name__)

DEVICE_DISCONNECT_ERRNOS = {errno.EBADF, errno.ENODEV, errno.ENOENT}


class _SupervisorState(Enum):
    NEW = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


@dataclass(slots=True)
class _ActiveRelay:
    device: InputDevice
    task: asyncio.Task[None]


class RelaySupervisor:
    """
    Owns selected input devices and their per-device relay tasks.

    The supervisor consumes runtime events directly. Hotplug, cable state, and
    shutdown requests therefore stay in the same asyncio task group as the
    relays they affect.
    """

    HOTPLUG_ADD_RETRY_DELAY_SEC = 0.2
    HOTPLUG_ADD_MAX_RETRIES = 10
    LOW_BATTERY_THRESHOLD_PERCENT = LOW_BATTERY_THRESHOLD_PERCENT
    BATTERY_CHECK_INTERVAL_SEC = 300.0
    BATTERY_INITIAL_RETRY_DELAY_SEC = 5.0
    BATTERY_INITIAL_MAX_RETRIES = 6

    def __init__(
        self,
        hid_gadgets: HidGadgets,
        relay_gate: RelayGate,
        task_group: TaskGroup,
        devices: list[str] | None = None,
        auto_relay: bool = False,
        skip_name_prefixes: list[str] | None = None,
        grab: bool = False,
        shortcut_toggler: ShortcutToggler | None = None,
    ) -> None:
        """
        :param hid_gadgets: Provides the USB HID gadget devices
        :param relay_gate: RelayGate to indicate whether relaying is active
        :param task_group: Runtime task group used for event waiters and relay tasks
        :param devices: A list of path, uniq, phys, MAC, or name fragments to match devices to relay
        :param auto_relay: If True, relays all valid input devices except those skipped
        :param skip_name_prefixes: A list of device.name prefixes to skip if auto_relay is True
        :param grab: If True, the relay tries to grab exclusive access to each device
        :param shortcut_toggler: ShortcutToggler to allow toggling relaying globally
        """
        self._hid_gadgets = hid_gadgets
        self._relay_gate = relay_gate
        self._shortcut_toggler = shortcut_toggler
        self._task_group = task_group

        self._device_filters = [DeviceFilter(device) for device in (devices or [])]
        self._auto_relay = auto_relay
        self._skip_name_prefixes = (
            tuple(skip_name_prefixes) if skip_name_prefixes is not None else DEFAULT_SKIP_NAME_PREFIXES
        )
        if self._auto_relay and self._device_filters:
            logger.warning(
                "Both auto relay and explicit device filters are configured; "
                "device filters are ignored while auto relay is active."
            )

        self._grab = grab

        self._state = _SupervisorState.NEW

        self._active_relays: dict[str, _ActiveRelay] = {}
        self._hotplug_probe_tasks: dict[str, asyncio.Task[None]] = {}
        self._led_mirror = KeyboardLedMirror(getattr(hid_gadgets, "keyboard_hidg_path", None))
        self._led_mirror_task: asyncio.Task[None] | None = None
        self._battery_monitor_task: asyncio.Task[None] | None = None
        self._low_battery_warned_devices: set[str] = set()
        self._pending_battery_retries: dict[str, int] = {}

    def _shutdown_requested(self) -> bool:
        return self._state in (_SupervisorState.STOPPING, _SupervisorState.STOPPED)

    async def run(self, events: asyncio.Queue[RuntimeEvent]) -> None:
        """
        Launch a TaskGroup that relays events from all matching devices.
        Dynamically adds or removes tasks when devices appear or disappear.

        :return: Never returns unless an unrecoverable exception or cancellation occurs
        :rtype: None
        """
        if self._state is _SupervisorState.STOPPED:
            raise RuntimeError("RelaySupervisor cannot be restarted")
        if self._state is _SupervisorState.RUNNING:
            raise RuntimeError("RelaySupervisor is already running")
        if self._shutdown_requested():
            self._state = _SupervisorState.STOPPED
            return

        try:
            try:
                initial_devices = list_input_devices()
            except DeviceEnumerationError as exc:
                logger.exception("Failed enumerating input devices: %s", exc)
                raise

            await self._run(events, initial_devices)
        except Exception:
            logger.exception("Relay supervisor failed.")
            raise
        finally:
            try:
                self._cancel_led_mirror()
                self._cancel_all_pending_hotplug_probes()
                for device_path, active_relay in list(self._active_relays.items()):
                    self._relay_task_done(device_path, active_relay.task)
                self._relay_gate.set_host_configured(False)
                if self._state is not _SupervisorState.STOPPING:
                    await self._hid_gadgets.release_all()
            finally:
                self._state = _SupervisorState.STOPPED
                logger.debug("Task group exited.")

    async def _run(self, events: asyncio.Queue[RuntimeEvent], initial_devices: list[InputDevice]) -> None:
        logger.debug("Task group started.")

        if not self._shutdown_requested():
            self._state = _SupervisorState.RUNNING
            self._start_led_mirror()

        for device in initial_devices:
            if self._shutdown_requested():
                device.close()
            elif self._device_matches_relay_filters(device):
                self._start_open_device(device)
            else:
                device.close()

        await self._consume_events(events)

    async def _consume_events(self, events: asyncio.Queue[RuntimeEvent]) -> None:
        while self._state is _SupervisorState.RUNNING:
            event = await events.get()
            await self._handle_runtime_event(event)

    async def _handle_runtime_event(self, event: RuntimeEvent) -> None:
        if isinstance(event, DeviceAdded):
            self._device_added(event.path)
        elif isinstance(event, DeviceRemoved):
            self._device_removed(event.path)
        elif isinstance(event, UdcStateChanged):
            was_configured = self._relay_gate.state.host_configured
            self._relay_gate.set_host_configured(event.state is UdcState.CONFIGURED)
            if was_configured and event.state is not UdcState.CONFIGURED:
                await self._hid_gadgets.release_all()
        elif isinstance(event, ShutdownRequested):
            logger.debug("Runtime shutdown requested: %s", event.reason)
            await self._begin_shutdown()

    async def _begin_shutdown(self) -> None:
        """
        Stop scheduling new relay work and actively unwind existing device tasks.

        This is used during service shutdown and profile restarts so we do not
        wait indefinitely for evdev readers to notice cancellation on their own.
        """
        if self._state in (_SupervisorState.STOPPING, _SupervisorState.STOPPED):
            return

        self._state = _SupervisorState.STOPPING
        self._cancel_led_mirror()
        self._cancel_all_pending_hotplug_probes()

        was_configured = self._relay_gate.state.host_configured
        self._relay_gate.set_host_configured(False)
        if was_configured:
            await self._hid_gadgets.release_all()

        for device_path in list(self._active_relays):
            self._cancel_active_relay(device_path)

    def _start_led_mirror(self) -> None:
        if self._led_mirror_task is None:
            try:
                self._led_mirror_task = self._task_group.create_task(self._led_mirror.run(), name="keyboard led mirror")
            except RuntimeError:
                logger.debug("Skipping keyboard LED mirroring; TaskGroup is shutting down.")
        if self._battery_monitor_task is None:
            try:
                self._battery_monitor_task = self._task_group.create_task(
                    self._run_battery_monitor(), name="battery monitor"
                )
            except RuntimeError:
                logger.debug("Skipping battery monitor; TaskGroup is shutting down.")

    def _cancel_led_mirror(self) -> None:
        task, self._led_mirror_task = self._led_mirror_task, None
        if task is not None and not task.done():
            task.cancel()
        battery_task, self._battery_monitor_task = self._battery_monitor_task, None
        if battery_task is not None and not battery_task.done():
            battery_task.cancel()

    async def _run_battery_monitor(self) -> None:
        while self._state is _SupervisorState.RUNNING:
            delay = (
                self.BATTERY_INITIAL_RETRY_DELAY_SEC
                if self._pending_battery_retries
                else self.BATTERY_CHECK_INTERVAL_SEC
            )
            await asyncio.sleep(delay)
            for active_relay in list(self._active_relays.values()):
                await self._check_device_battery(active_relay.device)

    async def _check_device_battery(self, device: InputDevice) -> None:
        battery = read_device_battery_percent(device)
        if battery is None:
            remaining = self._pending_battery_retries.get(device.path, 0) - 1
            if remaining > 0:
                self._pending_battery_retries[device.path] = remaining
            else:
                self._pending_battery_retries.pop(device.path, None)
            return
        self._pending_battery_retries.pop(device.path, None)
        publish_device_battery(device, battery)
        if battery > self.LOW_BATTERY_THRESHOLD_PERCENT:
            self._low_battery_warned_devices.discard(device.path)
            return
        if device.path in self._low_battery_warned_devices:
            return
        self._low_battery_warned_devices.add(device.path)
        logger.warning("Low battery on %s (%s): %s%%", device.name or device.path, device.path, battery)
        await self._led_mirror.blink_warning()

    def _device_added(self, device_path: str) -> None:
        if self._state is not _SupervisorState.RUNNING:
            logger.debug("Ignoring add for %s; supervisor is shutting down.", device_path)
            return

        self._schedule_hotplug_probe(device_path)

    def _device_removed(self, device_path: str) -> None:
        if self._state in (_SupervisorState.NEW, _SupervisorState.STOPPING, _SupervisorState.STOPPED):
            logger.debug("Ignoring remove for %s; supervisor is shutting down.", device_path)
            return
        self._cancel_pending_hotplug_probe(device_path)
        self._cancel_active_relay(device_path)

    def _cancel_pending_hotplug_probe(self, device_path: str) -> None:
        task = self._hotplug_probe_tasks.pop(device_path, None)
        if task is not None:
            task.cancel()

    def _cancel_all_pending_hotplug_probes(self) -> None:
        for device_path in list(self._hotplug_probe_tasks):
            self._cancel_pending_hotplug_probe(device_path)

    def _discard_hotplug_probe_task(self, device_path: str, task: asyncio.Task[None]) -> None:
        if self._hotplug_probe_tasks.get(device_path) is task:
            self._hotplug_probe_tasks.pop(device_path, None)

    def _schedule_hotplug_probe(self, device_path: str) -> None:
        if self._state is not _SupervisorState.RUNNING or self._shutdown_requested():
            logger.debug("Ignoring add for %s; event loop is unavailable.", device_path)
            return
        if device_path in self._active_relays:
            logger.debug("Device %s is already active.", device_path)
            return
        if device_path in self._hotplug_probe_tasks:
            logger.debug("Hotplug probe for %s is already pending.", device_path)
            return

        async def _probe() -> None:
            await self._run_hotplug_probe(device_path)

        task = self._task_group.create_task(_probe(), name=f"hotplug probe {device_path}")
        self._hotplug_probe_tasks[device_path] = task
        task.add_done_callback(lambda done_task, path=device_path: self._discard_hotplug_probe_task(path, done_task))

    async def _run_hotplug_probe(self, device_path: str) -> None:
        for retries_remaining in range(self.HOTPLUG_ADD_MAX_RETRIES, -1, -1):
            if self._state is not _SupervisorState.RUNNING or self._shutdown_requested():
                return
            if device_path in self._active_relays:
                return

            try:
                device = InputDevice(device_path)
            except (OSError, FileNotFoundError):
                if retries_remaining > 0:
                    logger.debug(
                        "%s vanished before hotplug filtering; retrying (%s left).", device_path, retries_remaining
                    )
                else:
                    logger.debug("%s vanished before hotplug filtering.", device_path)
                    return
            else:
                if self._device_matches_relay_filters(device):
                    self._start_open_device(device)
                    return
                if retries_remaining > 0:
                    logger.debug(
                        "Hotplugged device %s is not ready for relay filters yet; " + "retrying (%s left).",
                        device,
                        retries_remaining,
                    )
                else:
                    logger.debug("Skipping hotplugged device %s because it does not match relay filters.", device)
                    device.close()
                    return
                device.close()

            await asyncio.sleep(self.HOTPLUG_ADD_RETRY_DELAY_SEC)

    def _start_open_device(self, device: InputDevice) -> None:
        if self._state is not _SupervisorState.RUNNING:
            logger.debug("Ignoring %s; supervisor is not running.", device)
            device.close()
            return

        if device.path in self._active_relays:
            logger.debug("Device %s is already active.", device)
            device.close()
            return

        try:
            task = self._task_group.create_task(self._run_input_relay(device), name=device.path)
        except RuntimeError:
            logger.debug("Ignoring %s; TaskGroup is shutting down.", device)
            device.close()
            return
        self._active_relays[device.path] = _ActiveRelay(device=device, task=task)
        task.add_done_callback(lambda done_task, path=device.path: self._relay_task_done(path, done_task))
        logger.debug("Created task for %s.", device)

    def _cancel_active_relay(self, device_path: str) -> None:
        active_relay = self._active_relays.get(device_path)
        if active_relay is None:
            logger.debug("No active task found for %s to remove.", device_path)
            return

        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None

        if active_relay.task.done() or active_relay.task is current_task:
            self._relay_task_done(device_path, active_relay.task)
        else:
            active_relay.task.cancel()
            logger.debug("Cancelled relay for %s.", device_path)

    def _relay_task_done(self, device_path: str, task: asyncio.Task[None]) -> None:
        active_relay = self._active_relays.get(device_path)
        if active_relay is None or active_relay.task is not task:
            return

        self._active_relays.pop(device_path, None)
        try:
            active_relay.device.close()
        except Exception:
            logger.debug("Ignoring close failure for %s", device_path)

    async def _run_input_relay(self, device: InputDevice) -> None:
        """
        Create a InputRelay context, then read events in a loop until cancellation or error.

        :param device: The evdev InputDevice to relay
        """
        try:
            async with InputRelay(
                device,
                self._hid_gadgets,
                grab=self._grab,
                relay_gate=self._relay_gate,
                shortcut_toggler=self._shortcut_toggler,
            ) as relay:
                logger.info("Activated %s", relay)
                self._led_mirror.register(device)
                self._pending_battery_retries[device.path] = self.BATTERY_INITIAL_MAX_RETRIES
                try:
                    await self._check_device_battery(device)
                    await relay.async_relay_events_loop()
                finally:
                    self._pending_battery_retries.pop(device.path, None)
                    self._low_battery_warned_devices.discard(device.path)
                    self._led_mirror.unregister(device.path)
        except OSError as exc:
            if exc.errno not in DEVICE_DISCONNECT_ERRNOS:
                logger.exception("Unhandled OS error in relay for %s.", device)
                raise
            logger.info("Lost connection to %s: %s", device, exc)
        except Exception:
            logger.exception("Unhandled exception in relay for %s.", device)
            raise

    def _device_matches_relay_filters(self, device: InputDevice) -> bool:
        """
        Decide if a device should be relayed based on auto relay,
        skip_name_prefixes, or user-specified device filters.

        :param device: The input device to check
        :return: True if we should relay it, False otherwise
        :rtype: bool
        """
        if self._auto_relay:
            exclusion_reason = auto_relay_exclusion_reason(device, self._skip_name_prefixes)
            if exclusion_reason is not None:
                logger.debug("Skipping %s during auto relay: %s", device, exclusion_reason)
                return False
            return True

        return any(device_filter.matches(device) for device_filter in self._device_filters)
