from __future__ import annotations

import asyncio
import errno
import os
import re
import stat
import threading
import time
from asyncio import Task, TaskGroup
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from evdev import InputDevice, InputEvent, KeyEvent, RelEvent, categorize
except ModuleNotFoundError:
    InputEvent = Any  # type: ignore[assignment]

    class InputDevice:
        def __init__(self, path: str = "", name: str = "", uniq: str = "") -> None:
            self.path = path
            self.name = name
            self.uniq = uniq

        async def async_read_loop(self):
            if False:
                yield None
            return

        def close(self) -> None:
            return None

    class KeyEvent:
        key_down = 1
        key_hold = 2
        key_up = 0

    class RelEvent:
        pass

    def categorize(event):
        return event


from .evdev import (
    ecodes,
    evdev_to_usb_hid,
    find_key_name,
    get_mouse_movement,
    is_consumer_key,
    is_mouse_button,
)
from .extended_mouse import ExtendedMouse
from .gadget_config import rebuild_gadget
from .hid_layout import build_default_layout
from .inventory import (
    DEFAULT_SKIP_NAME_PREFIXES,
    DeviceEnumerationError,
    auto_discover_exclusion_reason,
    list_input_devices,
)
from .logging import get_logger

_logger = get_logger()

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

if TYPE_CHECKING:
    from adafruit_hid.consumer_control import ConsumerControl
    from adafruit_hid.keyboard import Keyboard


class GadgetManager:
    """
    Manages enabling, disabling, and references to USB HID gadget devices.

    :ivar _gadgets: Internal dictionary mapping device types to HID device objects
    :ivar _enabled: Indicates whether the gadgets have been enabled
    """

    HIDG_NODE_READY_TIMEOUT_SEC = 2.0
    HIDG_NODE_POLL_INTERVAL_SEC = 0.05

    def __init__(self) -> None:
        """
        Initialize without enabling devices. Call enable_gadgets() to enable them.
        """
        self._gadgets = {
            "keyboard": None,
            "mouse": None,
            "consumer": None,
        }
        self._enabled = False

    def _requested_devices(self):
        return list(build_default_layout().devices)

    def _expected_hidg_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(f"/dev/hidg{index}")
            for index, _ in enumerate(self._requested_devices())
        )

    def _prune_stale_hidg_nodes(
        self, *, remove_character_devices: bool = False
    ) -> None:
        for path in self._expected_hidg_paths():
            try:
                mode = path.stat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISCHR(mode) and not remove_character_devices:
                continue
            _logger.warning("Removing stale HID gadget path %s", path)
            path.unlink()

    def _collect_invalid_hidg_nodes(self) -> list[str]:
        invalid_paths: list[str] = []
        for index, path in enumerate(self._expected_hidg_paths()):
            try:
                stats = path.stat()
            except FileNotFoundError:
                invalid_paths.append(f"{path} (missing)")
                continue
            mode = stats.st_mode
            if not stat.S_ISCHR(mode):
                invalid_paths.append(f"{path} (mode=0o{mode:o})")
                continue
            if os.minor(stats.st_rdev) != index:
                invalid_paths.append(
                    f"{path} (minor={os.minor(stats.st_rdev)}, expected={index})"
                )
                continue
            try:
                fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                message = exc.strerror or exc.__class__.__name__
                invalid_paths.append(f"{path} ({message})")
                continue
            os.close(fd)
        return invalid_paths

    def _validate_hidg_nodes(
        self,
        timeout_sec: float | None = None,
        poll_interval_sec: float | None = None,
    ) -> None:
        timeout_sec = (
            self.HIDG_NODE_READY_TIMEOUT_SEC if timeout_sec is None else timeout_sec
        )
        poll_interval_sec = (
            self.HIDG_NODE_POLL_INTERVAL_SEC
            if poll_interval_sec is None
            else poll_interval_sec
        )
        deadline = time.monotonic() + max(timeout_sec, 0.0)

        while True:
            invalid_paths = self._collect_invalid_hidg_nodes()
            if not invalid_paths:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "USB HID gadget nodes are not healthy: " + ", ".join(invalid_paths)
                )
            time.sleep(poll_interval_sec)

    def enable_gadgets(self) -> None:
        """
        Disable and re-enable usb_hid devices, then store references
        to the new Keyboard, Mouse, and ConsumerControl gadgets.
        """
        self._prune_stale_hidg_nodes(remove_character_devices=True)
        enabled_devices = list(rebuild_gadget(build_default_layout()))
        try:
            self._validate_hidg_nodes()
        except RuntimeError:
            _logger.warning(
                "Retrying HID gadget initialization after stale node validation failure"
            )
            self._prune_stale_hidg_nodes(remove_character_devices=True)
            enabled_devices = list(rebuild_gadget(build_default_layout()))
            self._validate_hidg_nodes()

        from adafruit_hid.consumer_control import ConsumerControl
        from adafruit_hid.keyboard import Keyboard

        self._gadgets["keyboard"] = Keyboard(enabled_devices)
        self._gadgets["mouse"] = ExtendedMouse(enabled_devices)
        self._gadgets["consumer"] = ConsumerControl(enabled_devices)
        self._enabled = True

        _logger.debug("USB HID gadgets initialized: %s", enabled_devices)

    def get_keyboard(self) -> Keyboard | None:
        """
        Get the Keyboard gadget.

        :return: A Keyboard object, or None if not initialized
        :rtype: Keyboard | None
        """
        return self._gadgets["keyboard"]

    def get_mouse(self) -> ExtendedMouse | None:
        """
        Get the Mouse gadget.

        :return: A Mouse object, or None if not initialized
        :rtype: Mouse | None
        """
        return self._gadgets["mouse"]

    def get_consumer(self) -> ConsumerControl | None:
        """
        Get the ConsumerControl gadget.

        :return: A ConsumerControl object, or None if not initialized
        :rtype: ConsumerControl | None
        """
        return self._gadgets["consumer"]


class ShortcutToggler:
    """
    Tracks a user-defined shortcut and toggles relaying on/off when the shortcut is pressed.
    """

    def __init__(
        self,
        shortcut_keys: set[str],
        relaying_active: asyncio.Event,
        gadget_manager: GadgetManager,
    ) -> None:
        """
        :param shortcut_keys: A set of evdev-style key names to detect
        :param relaying_active: An asyncio.Event controlling whether relaying is active
        :param gadget_manager: GadgetManager to release keyboard/mouse states on toggle
        """
        self.shortcut_keys = shortcut_keys
        self.relaying_active = relaying_active
        self.gadget_manager = gadget_manager

        self.currently_pressed: set[str] = set()
        self._suppressed_keys: set[str] = set()
        self._shortcut_armed = True

    def handle_key_event(self, event: KeyEvent) -> bool:
        """
        Process a key press or release to detect the toggle shortcut.

        :param event: The incoming KeyEvent from evdev
        :type event: KeyEvent
        """
        key_name = find_key_name(event)
        if key_name is None:
            return False

        if event.keystate == KeyEvent.key_down:
            self.currently_pressed.add(key_name)
        elif event.keystate == KeyEvent.key_up:
            self.currently_pressed.discard(key_name)
            if key_name in self._suppressed_keys:
                self._suppressed_keys.discard(key_name)
                if not self._suppressed_keys:
                    self._shortcut_armed = True
                return True
            if self.shortcut_keys and key_name in self.shortcut_keys:
                self._shortcut_armed = True

        if (
            self._shortcut_armed
            and self.shortcut_keys
            and self.shortcut_keys.issubset(self.currently_pressed)
        ):
            self._shortcut_armed = False
            self._suppressed_keys.update(self.shortcut_keys)
            self.toggle_relaying()
            return True

        return key_name in self._suppressed_keys

    def toggle_relaying(self) -> None:
        """
        Toggle the global relaying state: if it was on, turn it off, otherwise turn it on.
        """
        if self.relaying_active.is_set():
            keyboard = self.gadget_manager.get_keyboard()
            mouse = self.gadget_manager.get_mouse()
            if keyboard:
                keyboard.release_all()
            if mouse:
                mouse.release_all()

            self.relaying_active.clear()
            _logger.info("ShortcutToggler: Relaying is now OFF.")
        else:
            self.relaying_active.set()
            _logger.info("ShortcutToggler: Relaying is now ON.")


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
        device_identifiers: list[str] | None = None,
        auto_discover: bool = False,
        skip_name_prefixes: list[str] | None = None,
        grab_devices: bool = False,
        relaying_active: asyncio.Event | None = None,
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
        self._device_ids = [DeviceIdentifier(id) for id in (device_identifiers or [])]
        self._auto_discover = auto_discover
        self._skip_name_prefixes = (
            tuple(skip_name_prefixes)
            if skip_name_prefixes is not None
            else DEFAULT_SKIP_NAME_PREFIXES
        )
        self._grab_devices = grab_devices
        self._relaying_active = relaying_active
        self._shortcut_toggler = shortcut_toggler

        self._active_tasks: dict[str, Task] = {}
        self._active_devices: dict[str, InputDevice] = {}
        self._task_group: TaskGroup | None = None
        self._shutdown_event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._hotplug_ready = False
        self._pending_add_paths: list[str] = []
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
        try:
            initial_devices = list_input_devices()
        except DeviceEnumerationError as exc:
            _logger.exception(
                "RelayController: Failed enumerating input devices: %s", exc
            )
            raise

        try:
            async with TaskGroup() as task_group:
                self._task_group = task_group
                self._loop = asyncio.get_running_loop()
                _logger.debug("RelayController: TaskGroup started.")

                for device in initial_devices:
                    if self._should_relay(device):
                        self.add_device(device.path)
                    device.close()

                self._hotplug_ready = True
                self._flush_pending_adds()

                await self._shutdown_event.wait()
        except* Exception as exc_grp:
            _logger.exception(
                "RelayController: Exception in TaskGroup", exc_info=exc_grp
            )
        finally:
            self._hotplug_ready = False
            self._task_group = None
            self._loop = None
            _logger.debug("RelayController: TaskGroup exited.")

    def request_shutdown(self) -> None:
        """
        Stop scheduling new relay work and actively unwind existing device tasks.

        This is used during service shutdown and profile restarts so we do not
        wait indefinitely for evdev readers to notice cancellation on their own.
        """
        if self._shutdown_requested():
            return

        self._shutdown_event.set()
        self._hotplug_ready = False
        self._pop_pending_adds()

        if self._relaying_active is not None:
            self._relaying_active.clear()

        def _begin_shutdown() -> None:
            for device_path in list(self._active_tasks):
                self.remove_device(device_path)

        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(_begin_shutdown)
                return
            except RuntimeError:
                pass
        _begin_shutdown()

    def schedule_add_device(self, device_path: str) -> None:
        if self._shutdown_requested():
            _logger.debug(
                "Ignoring add for %s; controller is shutting down.", device_path
            )
            return
        if not self._hotplug_ready:
            self._queue_pending_add(device_path)
            _logger.debug(
                "Queueing add for %s until the relay controller is ready.",
                device_path,
            )
            return

        loop = self._loop
        if loop is None or self._task_group is None:
            _logger.debug(f"Ignoring add for {device_path}; event loop is unavailable.")
            return

        try:
            loop.call_soon_threadsafe(
                self._schedule_add_retry,
                device_path,
                self.HOTPLUG_ADD_MAX_RETRIES,
            )
        except RuntimeError:
            _logger.debug(
                "Ignoring add for %s; controller is shutting down.",
                device_path,
            )

    def _queue_pending_add(self, device_path: str) -> None:
        with self._pending_add_lock:
            if device_path not in self._pending_add_paths:
                self._pending_add_paths.append(device_path)

    def _discard_pending_add(self, device_path: str) -> bool:
        with self._pending_add_lock:
            try:
                self._pending_add_paths.remove(device_path)
            except ValueError:
                return False
            return True

    def _pop_pending_adds(self) -> list[str]:
        with self._pending_add_lock:
            pending = list(self._pending_add_paths)
            self._pending_add_paths.clear()
        return pending

    def _flush_pending_adds(self) -> None:
        loop = self._loop
        if (
            not self._hotplug_ready
            or loop is None
            or self._task_group is None
            or self._shutdown_requested()
        ):
            return
        for device_path in self._pop_pending_adds():
            loop.call_soon(
                self._schedule_add_retry, device_path, self.HOTPLUG_ADD_MAX_RETRIES
            )

    def _schedule_add_retry(self, device_path: str, retries_remaining: int) -> None:
        loop = self._loop
        if loop is None or self._task_group is None or self._shutdown_requested():
            _logger.debug(f"Ignoring add for {device_path}; event loop is unavailable.")
            return

        try:
            device = InputDevice(device_path)
        except (OSError, FileNotFoundError):
            if retries_remaining > 0:
                _logger.debug(
                    "%s vanished before hotplug filtering; retrying (%s left).",
                    device_path,
                    retries_remaining,
                )
                loop.call_later(
                    self.HOTPLUG_ADD_RETRY_DELAY_SEC,
                    self._schedule_add_retry,
                    device_path,
                    retries_remaining - 1,
                )
            else:
                _logger.debug(f"{device_path} vanished before hotplug filtering.")
            return

        try:
            if not self._should_relay(device):
                if retries_remaining > 0:
                    _logger.debug(
                        "Hotplugged device %s is not ready for relay filters yet; retrying (%s left).",
                        device,
                        retries_remaining,
                    )
                    loop.call_later(
                        self.HOTPLUG_ADD_RETRY_DELAY_SEC,
                        self._schedule_add_retry,
                        device_path,
                        retries_remaining - 1,
                    )
                else:
                    _logger.debug(
                        "Skipping hotplugged device %s because it does not match relay filters.",
                        device,
                    )
                return
        finally:
            device.close()
        self.add_device(device_path)

    def schedule_remove_device(self, device_path: str) -> None:
        if not self._hotplug_ready:
            if self._discard_pending_add(device_path):
                _logger.debug(
                    "Dropped queued add for %s because the device was removed before startup completed.",
                    device_path,
                )
            return
        loop = self._loop
        if loop is None or self._shutdown_requested():
            _logger.debug(
                f"Ignoring remove for {device_path}; event loop is unavailable."
            )
            return
        try:
            loop.call_soon_threadsafe(self.remove_device, device_path)
        except RuntimeError:
            _logger.debug(
                "Ignoring remove for %s; controller is shutting down.",
                device_path,
            )

    def add_device(self, device_path: str) -> None:
        """
        Add a device by path. If a TaskGroup is active, create a new relay task.

        :param device_path: The absolute path to the input device (e.g., /dev/input/event5)
        """
        if not Path(device_path).exists():
            _logger.debug(f"{device_path} does not exist.")
            return

        try:
            device = InputDevice(device_path)
        except (OSError, FileNotFoundError):
            _logger.debug(f"{device_path} vanished before opening.")
            return

        if not self._should_relay(device):
            _logger.debug(f"Skipping {device} because it does not match relay filters.")
            device.close()
            return

        if self._task_group is None:
            _logger.critical(f"No TaskGroup available; ignoring {device}.")
            device.close()
            return

        if device.path in self._active_tasks:
            _logger.debug(f"Device {device} is already active.")
            device.close()
            return

        try:
            task = self._task_group.create_task(
                self._async_relay_events(device), name=device.path
            )
        except RuntimeError:
            _logger.debug("Ignoring %s; TaskGroup is shutting down.", device)
            device.close()
            return
        self._active_tasks[device.path] = task
        self._active_devices[device.path] = device
        _logger.debug(f"Created task for {device}.")

    def remove_device(self, device_path: str) -> None:
        """
        Cancel and remove the relay task for a given device path.

        :param device_path: The path of the device to remove
        """
        task = self._active_tasks.pop(device_path, None)
        device = self._active_devices.pop(device_path, None)
        if task and not task.done():
            task.cancel()
            _logger.debug(f"Cancelled relay for {device_path}.")
            return

        _logger.debug(f"No active task found for {device_path} to remove.")
        if device is None:
            return
        try:
            device.close()
        except Exception:
            _logger.debug("Ignoring close failure for %s during removal.", device_path)

    async def _async_relay_events(self, device: InputDevice) -> None:
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
                _logger.info(f"Activated {relay}")
                await relay.async_relay_events_loop()
        except (OSError, FileNotFoundError):
            _logger.info(f"Lost connection to {device}.")
        except Exception:
            _logger.exception(f"Unhandled exception in relay for {device}.")
        finally:
            self.remove_device(device.path)

    def _should_relay(self, device: InputDevice) -> bool:
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
                _logger.debug(
                    "Skipping %s during auto-discovery: %s",
                    device,
                    exclusion_reason,
                )
                return False
            return True

        return any(identifier.matches(device) for identifier in self._device_ids)


class DeviceRelay:
    """
    Relay a single InputDevice's events to USB HID gadgets.

    - Optionally grabs the device exclusively.
    - Retries HID writes if they raise BlockingIOError.
    """

    HID_WRITE_MAX_TRIES = 3
    HID_WRITE_RETRY_DELAY_SEC = 0.01

    def __init__(
        self,
        input_device: InputDevice,
        gadget_manager: GadgetManager,
        grab_device: bool = False,
        relaying_active: asyncio.Event | None = None,
        shortcut_toggler: ShortcutToggler | None = None,
    ) -> None:
        """
        :param input_device: The evdev input device
        :param gadget_manager: Provides references to Keyboard, Mouse, ConsumerControl
        :param grab_device: Whether to grab the device for exclusive access
        :param relaying_active: asyncio.Event that indicates relaying is on/off
        :param shortcut_toggler: Optional handler for toggling relay via a shortcut
        """
        self._input_device = input_device
        self._gadget_manager = gadget_manager
        self._grab_device = grab_device
        self._relaying_active = relaying_active
        self._shortcut_toggler = shortcut_toggler

        self._currently_grabbed = False
        self._hid_write_retries = 0
        self._hid_write_failures = 0
        self._pending_rel_x = 0
        self._pending_rel_y = 0
        self._pending_rel_wheel = 0
        self._pending_rel_pan = 0.0
        self._rel_pan_remainder = 0.0

    def __str__(self) -> str:
        return f"relay for {self._input_device}"

    @property
    def input_device(self) -> InputDevice:
        """
        The underlying evdev InputDevice being relayed.

        :return: The InputDevice
        :rtype: InputDevice
        """
        return self._input_device

    async def __aenter__(self) -> DeviceRelay:
        """
        Async context manager entry. Grabs the device if requested.

        :return: self
        """
        if self._grab_device:
            try:
                self._input_device.grab()
                self._currently_grabbed = True
            except Exception as ex:
                _logger.warning(f"Could not grab {self._input_device.path}: {ex}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        Async context manager exit. Ungrabs the device if we grabbed it.

        :return: False to propagate exceptions
        """
        if self._grab_device:
            try:
                self._input_device.ungrab()
                self._currently_grabbed = False
            except Exception as ex:
                self._currently_grabbed = False
                if self._should_ignore_ungrab_error(ex):
                    _logger.debug(
                        "Skipping ungrab for %s because the device is no longer available.",
                        self._input_device.path,
                    )
                else:
                    _logger.warning(f"Unable to ungrab {self._input_device.path}: {ex}")
        try:
            self._release_gadget_states()
        except Exception:
            _logger.debug("Ignoring gadget state release failure for %s", self)
        try:
            self._input_device.close()
        except Exception:
            _logger.debug("Ignoring close failure for %s", self._input_device.path)
        return False

    def _should_ignore_ungrab_error(self, ex: Exception) -> bool:
        return isinstance(ex, OSError) and ex.errno in (errno.ENODEV, errno.EBADF)

    def _release_gadget_states(self) -> None:
        keyboard = self._gadget_manager.get_keyboard()
        mouse = self._gadget_manager.get_mouse()
        if keyboard is not None:
            keyboard.release_all()
        if mouse is not None:
            mouse.release_all()

    def _update_grab_state(self, active: bool) -> None:
        if self._grab_device and active and not self._currently_grabbed:
            try:
                self._input_device.grab()
                self._currently_grabbed = True
                _logger.debug(f"Grabbed {self._input_device}")
            except Exception as ex:
                _logger.warning(f"Could not grab {self._input_device}: {ex}")
        elif self._grab_device and not active and self._currently_grabbed:
            try:
                self._input_device.ungrab()
                self._currently_grabbed = False
                _logger.debug(f"Ungrabbed {self._input_device}")
            except Exception as ex:
                self._currently_grabbed = False
                if self._should_ignore_ungrab_error(ex):
                    _logger.debug(
                        "Skipping ungrab for %s because the device is no longer available.",
                        self._input_device.path,
                    )
                else:
                    _logger.warning(f"Could not ungrab {self._input_device}: {ex}")

    async def async_relay_events_loop(self) -> None:
        """
        Continuously read events from the device and relay them
        to the USB HID gadgets. Stops when canceled or on error.

        :return: None
        """
        try:
            async for input_event in self._input_device.async_read_loop():
                event = categorize(input_event)
                is_syn_report = (
                    getattr(input_event, "type", None) == ecodes.EV_SYN
                    and getattr(input_event, "code", None) == ecodes.SYN_REPORT
                )

                if any(isinstance(event, ev_type) for ev_type in [KeyEvent, RelEvent]):
                    _logger.debug(
                        f"Received {event} from {self._input_device.name} ({self._input_device.path})"
                    )

                if self._shortcut_toggler and isinstance(event, KeyEvent):
                    if self._shortcut_toggler.handle_key_event(event):
                        continue

                active = bool(self._relaying_active and self._relaying_active.is_set())
                self._update_grab_state(active)

                if not active:
                    self._discard_pending_mouse_state()
                    continue

                if isinstance(event, RelEvent):
                    self._accumulate_mouse_movement(event)
                    continue

                if is_syn_report:
                    await self._flush_pending_mouse_movement()
                    continue

                await self._flush_pending_mouse_movement()
                await self._process_event_with_retry(event)
        except OSError as ex:
            if ex.errno != errno.ENODEV:
                raise
            _logger.debug(
                "Stopping relay loop for %s because the input device disappeared.",
                self._input_device.path,
            )
            self._discard_pending_mouse_state()
        await self._flush_pending_mouse_movement()
        _logger.debug(
            "Relay stats for %s: hid_write_retries=%s hid_write_failures=%s",
            self._input_device.path,
            self._hid_write_retries,
            self._hid_write_failures,
        )

    def _accumulate_mouse_movement(self, event: RelEvent) -> None:
        x, y, wheel, pan = get_mouse_movement(event)
        self._pending_rel_x += x
        self._pending_rel_y += y
        self._pending_rel_wheel += wheel
        self._pending_rel_pan += pan

    def _discard_pending_mouse_state(self) -> None:
        self._pending_rel_x = 0
        self._pending_rel_y = 0
        self._pending_rel_wheel = 0
        self._pending_rel_pan = 0.0
        self._rel_pan_remainder = 0.0

    async def _flush_pending_mouse_movement(self) -> None:
        x = self._pending_rel_x
        y = self._pending_rel_y
        wheel = self._pending_rel_wheel
        pan_total = self._rel_pan_remainder + self._pending_rel_pan
        pan = int(pan_total)
        self._rel_pan_remainder = pan_total - pan
        self._pending_rel_x = 0
        self._pending_rel_y = 0
        self._pending_rel_wheel = 0
        self._pending_rel_pan = 0.0
        if x == 0 and y == 0 and wheel == 0 and pan == 0:
            return
        await self._process_mouse_delta_with_retry(x, y, wheel, pan)

    async def _process_mouse_delta_with_retry(
        self, x: int, y: int, wheel: int, pan: int
    ) -> None:
        max_tries = self.HID_WRITE_MAX_TRIES
        retry_delay = self.HID_WRITE_RETRY_DELAY_SEC
        for attempt in range(1, max_tries + 1):
            try:
                mouse = self._gadget_manager.get_mouse()
                if mouse is None:
                    raise RuntimeError(
                        "Mouse gadget not initialized or manager not enabled."
                    )
                mouse.move(x, y, wheel, pan)
                return
            except BlockingIOError:
                if attempt < max_tries:
                    self._hid_write_retries += 1
                    _logger.debug(f"HID write blocked ({attempt}/{max_tries})")
                    await asyncio.sleep(retry_delay)
                else:
                    self._hid_write_failures += 1
                    _logger.warning(f"HID write blocked ({attempt}/{max_tries})")
            except BrokenPipeError:
                self._hid_write_failures += 1
                _logger.warning(
                    "BrokenPipeError: USB cable likely disconnected or power-only. "
                    "Pausing relay.\nSee: "
                    "https://github.com/quaxalber/bluetooth_2_usb/blob/main/TROUBLESHOOTING.md"
                )
                if self._relaying_active:
                    self._relaying_active.clear()
                return
            except Exception:
                self._hid_write_failures += 1
                _logger.exception("Error processing mouse movement")
                return

    async def _process_event_with_retry(self, event: InputEvent) -> None:
        """
        Attempt to relay the given event to the appropriate HID gadget.
        Retry on BlockingIOError up to 2 times.

        :param event: The InputEvent to process
        """
        max_tries = self.HID_WRITE_MAX_TRIES
        retry_delay = self.HID_WRITE_RETRY_DELAY_SEC
        for attempt in range(1, max_tries + 1):
            try:
                relay_event(event, self._gadget_manager)
                return
            except BlockingIOError:
                if attempt < max_tries:
                    self._hid_write_retries += 1
                    _logger.debug(f"HID write blocked ({attempt}/{max_tries})")
                    await asyncio.sleep(retry_delay)
                else:
                    self._hid_write_failures += 1
                    _logger.warning(f"HID write blocked ({attempt}/{max_tries})")
            except BrokenPipeError:
                self._hid_write_failures += 1
                _logger.warning(
                    "BrokenPipeError: USB cable likely disconnected or power-only. "
                    "Pausing relay.\nSee: "
                    "https://github.com/quaxalber/bluetooth_2_usb/blob/main/TROUBLESHOOTING.md"
                )
                if self._relaying_active:
                    self._relaying_active.clear()
                return
            except Exception:
                self._hid_write_failures += 1
                _logger.exception(f"Error processing {event}")
                return


class DeviceIdentifier:
    """
    Identifies an input device by path (/dev/input/eventX), MAC address,
    or a substring of the device name.
    """

    def __init__(self, device_identifier: str) -> None:
        """
        :param device_identifier: Path, MAC, or name fragment
        """
        self._value = device_identifier
        self._type = self._determine_identifier_type()
        self._normalized_value = self._normalize_identifier()

    def __str__(self) -> str:
        return f'{self._type} "{self._value}"'

    def _determine_identifier_type(self) -> str:
        if re.match(r"^/dev/input/event.*$", self._value):
            return "path"
        if re.match(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$", self._value):
            return "mac"
        return "name"

    def _normalize_identifier(self) -> str:
        if self._type == "path":
            return self._value
        if self._type == "mac":
            return self._value.lower().replace("-", ":")
        return self._value.lower()

    def matches(self, device: InputDevice) -> bool:
        """
        Check whether this identifier matches the given evdev InputDevice.

        :param device: An evdev InputDevice to compare
        :return: True if matched, False otherwise
        :rtype: bool
        """
        if self._type == "path":
            return self._value == device.path
        if self._type == "mac":
            return self._normalized_value == (device.uniq or "").lower()
        return self._normalized_value in device.name.lower()


async def async_list_input_devices() -> list[InputDevice]:
    """
    Return a list of available /dev/input/event* devices.

    :return: List of InputDevice objects
    :rtype: list[InputDevice]
    """
    return list_input_devices()


def relay_event(event: InputEvent, gadget_manager: GadgetManager) -> None:
    """
    Relay the given event to the appropriate USB HID device.

    :param event: The evdev InputEvent
    :param gadget_manager: GadgetManager with references to HID devices
    :raises BlockingIOError: If HID device write is blocked
    """
    if isinstance(event, RelEvent):
        move_mouse(event, gadget_manager)
    elif isinstance(event, KeyEvent):
        send_key_event(event, gadget_manager)


def move_mouse(event: RelEvent, gadget_manager: GadgetManager) -> None:
    """
    Relay relative mouse movement events to the USB HID Mouse gadget.

    :param event: A RelEvent describing the movement
    :param gadget_manager: GadgetManager with Mouse reference
    :raises RuntimeError: If Mouse gadget is not available
    """
    mouse = gadget_manager.get_mouse()
    if mouse is None:
        raise RuntimeError("Mouse gadget not initialized or manager not enabled.")

    mouse.move(*get_mouse_movement(event))


def send_key_event(event: KeyEvent, gadget_manager: GadgetManager) -> None:
    """
    Relay a key event (press/release) to the appropriate HID gadget.

    :param event: The KeyEvent to process
    :param gadget_manager: GadgetManager with references to the HID devices
    :raises RuntimeError: If no appropriate HID gadget is available
    """
    key_id, key_name = evdev_to_usb_hid(event)
    if key_id is None or key_name is None:
        return

    output_gadget = get_output_device(event, gadget_manager)
    if output_gadget is None:
        raise RuntimeError("No appropriate USB gadget found (manager not enabled?).")

    if event.keystate == KeyEvent.key_down:
        _logger.debug(f"Pressing {key_name} (0x{key_id:02X}) via {output_gadget}")
        output_gadget.press(key_id)
    elif event.keystate == KeyEvent.key_up:
        _logger.debug(f"Releasing {key_name} (0x{key_id:02X}) via {output_gadget}")
        output_gadget.release(key_id)


def get_output_device(
    event: KeyEvent, gadget_manager: GadgetManager
) -> ConsumerControl | Keyboard | ExtendedMouse | None:
    """
    Determine which HID gadget to target for the given key event.

    :param event: The KeyEvent to process
    :param gadget_manager: GadgetManager for HID references
    :return: A ConsumerControl, Mouse, or Keyboard object, or None if not found
    """
    if is_consumer_key(event):
        return gadget_manager.get_consumer()
    if is_mouse_button(event):
        return gadget_manager.get_mouse()
    return gadget_manager.get_keyboard()


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
        udc_path: Path = Path("/sys/class/udc/20980000.usb/state"),
        poll_interval: float = 0.5,
    ) -> None:
        self.relay_controller = relay_controller
        self._relaying_active = relaying_active
        self.udc_path = udc_path
        self.poll_interval = poll_interval

        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_state: str | None = None

        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by("input")
        self.observer = pyudev.MonitorObserver(self.monitor, self._udev_event_callback)

        if not self.udc_path.is_file():
            _logger.warning(
                "UDC state file %s not found. Cable monitoring may be unavailable.",
                self.udc_path,
            )

    async def __aenter__(self):
        self._stop_event.clear()
        self.observer.start()
        self._task = asyncio.create_task(self._poll_state())
        _logger.debug("RuntimeMonitor started.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        self.observer.stop()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        _logger.debug("RuntimeMonitor stopped.")
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
                    timeout=self.poll_interval,
                )
            except TimeoutError:
                pass

    def _read_udc_state(self) -> str:
        try:
            with open(self.udc_path, encoding="utf-8") as handle:
                return handle.read().strip()
        except FileNotFoundError:
            return "not_attached"

    def _handle_state_change(self, new_state: str):
        _logger.debug(f"UDC state changed to '{new_state}'")
        if new_state == "configured":
            self._relaying_active.set()
        else:
            self._relaying_active.clear()

    def _udev_event_callback(self, action: str, device: pyudev.Device) -> None:
        device_node = device.device_node
        if not device_node or not device_node.startswith("/dev/input/event"):
            return

        if action == "add":
            _logger.debug(f"RuntimeMonitor: Added input => {device_node}")
            self.relay_controller.schedule_add_device(device_node)
        elif action == "remove":
            _logger.debug(f"RuntimeMonitor: Removed input => {device_node}")
            self.relay_controller.schedule_remove_device(device_node)
