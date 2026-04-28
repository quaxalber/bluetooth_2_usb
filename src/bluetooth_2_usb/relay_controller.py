from __future__ import annotations

import asyncio
import errno
import threading
from asyncio import TaskGroup
from dataclasses import dataclass
from enum import Enum, auto

from .device_identifier import DeviceIdentifier
from .device_relay import DeviceRelay
from .evdev_compat import InputDevice
from .gadget_manager import GadgetManager
from .inventory import (
    DEFAULT_SKIP_NAME_PREFIXES,
    DeviceEnumerationError,
    auto_discover_exclusion_reason,
    list_input_devices,
)
from .logging import get_logger
from .shortcut_toggler import ShortcutToggler

logger = get_logger(__name__)

DEVICE_DISCONNECT_ERRNOS = {errno.EBADF, errno.ENODEV, errno.ENOENT}


class _ControllerState(Enum):
    NEW = auto()
    STARTING = auto()
    RUNNING = auto()
    SHUTTING_DOWN = auto()
    STOPPED = auto()


@dataclass(slots=True)
class _ActiveRelay:
    device: InputDevice
    task: asyncio.Task[None]


class RelayController:
    """
    Controls the creation and lifecycle of per-device relays.
    Monitors add/remove events from udev and includes optional auto-discovery.
    """

    HOTPLUG_ADD_RETRY_DELAY_SEC = 0.2
    HOTPLUG_ADD_MAX_RETRIES = 10

    def __init__(
        self,
        gadget_manager: GadgetManager,
        relaying_active: asyncio.Event,
        device_identifiers: list[str] | None = None,
        auto_discover: bool = False,
        skip_name_prefixes: list[str] | None = None,
        grab_devices: bool = False,
        shortcut_toggler: ShortcutToggler | None = None,
    ) -> None:
        """
        :param gadget_manager: Provides the USB HID gadget devices
        :param device_identifiers: A list of path, MAC, or name fragments to identify devices to relay
        :param auto_discover: If True, relays all valid input devices except those skipped
        :param skip_name_prefixes: A list of device.name prefixes to skip if auto_discover is True
        :param grab_devices: If True, the relay tries to grab exclusive access to each device
        :param relaying_active: asyncio.Event to indicate if relaying is active
        :param shortcut_toggler: ShortcutToggler to allow toggling relaying globally
        """
        self._gadget_manager = gadget_manager
        self._device_identifiers = [
            DeviceIdentifier(identifier) for identifier in (device_identifiers or [])
        ]
        self._auto_discover = auto_discover
        self._skip_name_prefixes = (
            tuple(skip_name_prefixes)
            if skip_name_prefixes is not None
            else DEFAULT_SKIP_NAME_PREFIXES
        )
        self._grab_devices = grab_devices
        self._relaying_active = relaying_active
        self._shortcut_toggler = shortcut_toggler

        self._active_relays: dict[str, _ActiveRelay] = {}
        self._task_group: TaskGroup | None = None
        self._shutdown_event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._state = _ControllerState.NEW
        self._pending_add_paths: set[str] = set()
        self._pending_add_lock = threading.Lock()

    def _shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    async def async_relay_devices(self) -> None:
        """
        Launch a TaskGroup that relays events from all matching devices.
        Dynamically adds or removes tasks when devices appear or disappear.

        :return: Never returns unless an unrecoverable exception or cancellation occurs
        :rtype: None
        """
        if self._state is _ControllerState.STOPPED:
            raise RuntimeError("RelayController cannot be restarted")
        if self._state in (
            _ControllerState.STARTING,
            _ControllerState.RUNNING,
        ):
            raise RuntimeError("RelayController is already running")
        if self._shutdown_requested() or self._state is _ControllerState.SHUTTING_DOWN:
            self._state = _ControllerState.STOPPED
            return

        self._state = _ControllerState.STARTING

        try:
            try:
                initial_devices = list_input_devices()
            except DeviceEnumerationError as exc:
                logger.exception(
                    "RelayController: Failed enumerating input devices: %s", exc
                )
                raise

            async with TaskGroup() as task_group:
                self._task_group = task_group
                self._loop = asyncio.get_running_loop()
                logger.debug("RelayController: TaskGroup started.")

                for device in initial_devices:
                    if self._shutdown_requested():
                        device.close()
                    elif self._device_matches_relay_filters(device):
                        self._start_open_device(device)
                    else:
                        device.close()

                if (
                    not self._shutdown_requested()
                    and self._state is _ControllerState.STARTING
                ):
                    self._state = _ControllerState.RUNNING
                    self._flush_pending_adds()

                await self._shutdown_event.wait()
        except* Exception as exc_grp:
            logger.exception(
                "RelayController: Exception in TaskGroup", exc_info=exc_grp
            )
            raise
        finally:
            self._state = _ControllerState.STOPPED
            self._task_group = None
            self._loop = None
            self._pop_pending_adds()
            for device_path, active_relay in list(self._active_relays.items()):
                self._relay_task_done(device_path, active_relay.task)
            logger.debug("RelayController: TaskGroup exited.")

    def request_shutdown(self) -> None:
        """
        Stop scheduling new relay work and actively unwind existing device tasks.

        This is used during service shutdown and profile restarts so we do not
        wait indefinitely for evdev readers to notice cancellation on their own.
        """
        if self._state in (_ControllerState.SHUTTING_DOWN, _ControllerState.STOPPED):
            return

        self._state = _ControllerState.SHUTTING_DOWN
        self._shutdown_event.set()
        self._pop_pending_adds()

        self._relaying_active.clear()
        self._gadget_manager.release_all_gadgets()

        def _begin_shutdown() -> None:
            for device_path in list(self._active_relays):
                self._cancel_active_relay(device_path)

        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(_begin_shutdown)
                return
            except RuntimeError:
                pass
        _begin_shutdown()

    def notify_device_added(self, device_path: str) -> None:
        if self._state in (_ControllerState.NEW, _ControllerState.STARTING):
            self._queue_pending_add(device_path)
            logger.debug(
                "Queueing add for %s until the relay controller is ready.",
                device_path,
            )
            return
        if self._state in (_ControllerState.SHUTTING_DOWN, _ControllerState.STOPPED):
            logger.debug(
                "Ignoring add for %s; controller is shutting down.", device_path
            )
            return

        loop = self._loop
        if loop is None or self._task_group is None:
            logger.debug(f"Ignoring add for {device_path}; event loop is unavailable.")
            return

        try:
            loop.call_soon_threadsafe(
                self._schedule_probe,
                device_path,
                self.HOTPLUG_ADD_MAX_RETRIES,
            )
        except RuntimeError:
            logger.debug(
                "Ignoring add for %s; controller is shutting down.",
                device_path,
            )

    def _queue_pending_add(self, device_path: str) -> None:
        with self._pending_add_lock:
            self._pending_add_paths.add(device_path)

    def _discard_pending_add(self, device_path: str) -> bool:
        with self._pending_add_lock:
            if device_path not in self._pending_add_paths:
                return False
            self._pending_add_paths.remove(device_path)
            return True

    def _pop_pending_adds(self) -> list[str]:
        with self._pending_add_lock:
            pending = sorted(self._pending_add_paths)
            self._pending_add_paths.clear()
        return pending

    def _flush_pending_adds(self) -> None:
        loop = self._loop
        if (
            self._state is not _ControllerState.RUNNING
            or loop is None
            or self._task_group is None
            or self._shutdown_requested()
        ):
            return
        for device_path in self._pop_pending_adds():
            loop.call_soon(
                self._schedule_probe, device_path, self.HOTPLUG_ADD_MAX_RETRIES
            )

    def _schedule_probe(self, device_path: str, retries_remaining: int) -> None:
        loop = self._loop
        if (
            loop is None
            or self._task_group is None
            or self._state is not _ControllerState.RUNNING
            or self._shutdown_requested()
        ):
            logger.debug(f"Ignoring add for {device_path}; event loop is unavailable.")
            return

        try:
            device = InputDevice(device_path)
        except (OSError, FileNotFoundError):
            if retries_remaining > 0:
                logger.debug(
                    "%s vanished before hotplug filtering; retrying (%s left).",
                    device_path,
                    retries_remaining,
                )
                loop.call_later(
                    self.HOTPLUG_ADD_RETRY_DELAY_SEC,
                    self._schedule_probe,
                    device_path,
                    retries_remaining - 1,
                )
            else:
                logger.debug(f"{device_path} vanished before hotplug filtering.")
            return

        if not self._device_matches_relay_filters(device):
            if retries_remaining > 0:
                logger.debug(
                    "Hotplugged device %s is not ready for relay filters yet; retrying (%s left).",
                    device,
                    retries_remaining,
                )
                loop.call_later(
                    self.HOTPLUG_ADD_RETRY_DELAY_SEC,
                    self._schedule_probe,
                    device_path,
                    retries_remaining - 1,
                )
            else:
                logger.debug(
                    "Skipping hotplugged device %s because it does not match relay filters.",
                    device,
                )
            device.close()
            return

        self._start_open_device(device)

    def notify_device_removed(self, device_path: str) -> None:
        if self._state is _ControllerState.NEW:
            if self._discard_pending_add(device_path):
                logger.debug(
                    "Dropped queued add for %s because the device was removed before startup completed.",
                    device_path,
                )
            return

        if self._state is _ControllerState.STARTING:
            if self._discard_pending_add(device_path):
                logger.debug(
                    "Dropped queued add for %s because the device was removed before startup completed.",
                    device_path,
                )
                return
            if device_path not in self._active_relays:
                return

        if self._state in (_ControllerState.SHUTTING_DOWN, _ControllerState.STOPPED):
            logger.debug(
                "Ignoring remove for %s; controller is shutting down.",
                device_path,
            )
            return
        loop = self._loop
        if loop is None or self._shutdown_requested():
            logger.debug(
                f"Ignoring remove for {device_path}; event loop is unavailable."
            )
            return
        try:
            loop.call_soon_threadsafe(self._cancel_active_relay, device_path)
        except RuntimeError:
            logger.debug(
                "Ignoring remove for %s; controller is shutting down.",
                device_path,
            )

    def _start_open_device(self, device: InputDevice) -> None:
        if self._state not in (_ControllerState.STARTING, _ControllerState.RUNNING):
            logger.debug("Ignoring %s; controller is not running.", device)
            device.close()
            return

        if self._task_group is None:
            logger.critical(f"No TaskGroup available; ignoring {device}.")
            device.close()
            return

        if device.path in self._active_relays:
            logger.debug(f"Device {device} is already active.")
            device.close()
            return

        try:
            task = self._task_group.create_task(
                self._run_device_relay(device), name=device.path
            )
        except RuntimeError:
            logger.debug("Ignoring %s; TaskGroup is shutting down.", device)
            device.close()
            return
        self._active_relays[device.path] = _ActiveRelay(device=device, task=task)
        task.add_done_callback(
            lambda done_task, path=device.path: self._relay_task_done(path, done_task)
        )
        logger.debug(f"Created task for {device}.")

    def _cancel_active_relay(self, device_path: str) -> None:
        active_relay = self._active_relays.get(device_path)
        if active_relay is None:
            logger.debug(f"No active task found for {device_path} to remove.")
            return

        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None

        if active_relay.task.done() or active_relay.task is current_task:
            self._relay_task_done(device_path, active_relay.task)
        else:
            active_relay.task.cancel()
            logger.debug(f"Cancelled relay for {device_path}.")

    def _relay_task_done(
        self,
        device_path: str,
        task: asyncio.Task[None],
    ) -> None:
        active_relay = self._active_relays.get(device_path)
        if active_relay is None or active_relay.task is not task:
            return

        self._active_relays.pop(device_path, None)
        try:
            active_relay.device.close()
        except Exception:
            logger.debug("Ignoring close failure for %s", device_path)

    async def _run_device_relay(self, device: InputDevice) -> None:
        """
        Create a DeviceRelay context, then read events in a loop until cancellation or error.

        :param device: The evdev InputDevice to relay
        """
        try:
            async with DeviceRelay(
                device,
                self._gadget_manager,
                grab_device=self._grab_devices,
                relaying_active=self._relaying_active,
                shortcut_toggler=self._shortcut_toggler,
            ) as relay:
                logger.info(f"Activated {relay}")
                await relay.async_relay_events_loop()
        except OSError as exc:
            if exc.errno not in DEVICE_DISCONNECT_ERRNOS:
                logger.exception("Unhandled OS error in relay for %s.", device)
                raise
            logger.info("Lost connection to %s: %s", device, exc)
        except Exception:
            logger.exception(f"Unhandled exception in relay for {device}.")
            raise

    def _device_matches_relay_filters(self, device: InputDevice) -> bool:
        """
        Decide if a device should be relayed based on auto_discover,
        skip_name_prefixes, or user-specified device_identifiers.

        :param device: The input device to check
        :return: True if we should relay it, False otherwise
        :rtype: bool
        """
        if self._auto_discover:
            exclusion_reason = auto_discover_exclusion_reason(
                device, self._skip_name_prefixes
            )
            if exclusion_reason is not None:
                logger.debug(
                    "Skipping %s during auto-discovery: %s",
                    device,
                    exclusion_reason,
                )
                return False
            return True

        return any(
            identifier.matches(device) for identifier in self._device_identifiers
        )
