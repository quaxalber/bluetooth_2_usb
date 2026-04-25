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
    from evdev import AbsEvent, InputDevice, InputEvent, KeyEvent, RelEvent, categorize
    from evdev import ecodes as native_ecodes
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

    class AbsEvent:
        pass

    native_ecodes = None  # type: ignore[assignment]

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


def _clamp_hid_i8(value: int) -> int:
    return min(127, max(-127, value))


def _clamp_hid_i16(value: int) -> int:
    return min(32767, max(-32767, value))


class ExtendedMouse:
    """Small mouse report writer with horizontal pan support."""

    LEFT_BUTTON = 1
    RIGHT_BUTTON = 2
    MIDDLE_BUTTON = 4
    BACK_BUTTON = 8
    FORWARD_BUTTON = 16
    BUTTON_6 = 32
    BUTTON_7 = 64
    BUTTON_8 = 128

    def __init__(self, devices) -> None:
        from adafruit_hid import find_device

        self._mouse_device = find_device(devices, usage_page=0x1, usage=0x02)
        if not self._mouse_device:
            raise ValueError("Could not find matching mouse HID device.")
        self.report = bytearray(7)

    def __str__(self):
        return str(self._mouse_device)

    def press(self, buttons: int) -> None:
        self.report[0] |= buttons
        self._send_no_move()

    def release(self, buttons: int) -> None:
        self.report[0] &= ~buttons
        self._send_no_move()

    def release_all(self) -> None:
        self.report[0] = 0
        self._send_no_move()

    def move(self, x: int = 0, y: int = 0, wheel: int = 0, pan: int = 0) -> None:
        while x != 0 or y != 0 or wheel != 0 or pan != 0:
            partial_x = _clamp_hid_i16(x)
            partial_y = _clamp_hid_i16(y)
            partial_wheel = _clamp_hid_i8(wheel)
            partial_pan = _clamp_hid_i8(pan)
            self.report[1:3] = partial_x.to_bytes(2, "little", signed=True)
            self.report[3:5] = partial_y.to_bytes(2, "little", signed=True)
            self.report[5] = partial_wheel & 0xFF
            self.report[6] = partial_pan & 0xFF
            self._mouse_device.send_report(self.report)
            x -= partial_x
            y -= partial_y
            wheel -= partial_wheel
            pan -= partial_pan

    def _send_no_move(self) -> None:
        self.report[1:7] = b"\x00" * 6
        self._mouse_device.send_report(self.report)


class KeyboardLedSync:
    """Best-effort propagation of host keyboard LED OUT reports to input devices."""

    POLL_INTERVAL_SEC = 0.1
    HID_TO_EVDEV_LED = (
        (0x01, "LED_NUML"),
        (0x02, "LED_CAPSL"),
        (0x04, "LED_SCROLLL"),
        (0x08, "LED_COMPOSE"),
        (0x10, "LED_KANA"),
    )

    def __init__(self, gadget_manager: GadgetManager) -> None:
        self._gadget_manager = gadget_manager
        self._devices: dict[str, InputDevice] = {}
        self._last_led_status = b"\x00"
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def register_input_device(self, device: InputDevice) -> None:
        if not self._supports_leds(device):
            return
        self._devices[device.path] = device
        self._apply_led_status(device, self._last_led_status)

    def unregister_input_device(self, device: InputDevice) -> None:
        self._devices.pop(device.path, None)

    async def __aenter__(self) -> KeyboardLedSync:
        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        return False

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.POLL_INTERVAL_SEC
                )
            except TimeoutError:
                pass

    def poll_once(self) -> None:
        keyboard = self._gadget_manager.get_keyboard()
        if keyboard is None or not hasattr(keyboard, "led_status"):
            return
        try:
            led_status = bytes(keyboard.led_status)
        except (BlockingIOError, OSError, ValueError):
            return
        if not led_status or led_status == self._last_led_status:
            return
        self._last_led_status = led_status[:1]
        for device in tuple(self._devices.values()):
            self._apply_led_status(device, self._last_led_status)

    def _supports_leds(self, device: InputDevice) -> bool:
        if not hasattr(device, "set_led"):
            return False
        try:
            capabilities = device.capabilities(verbose=False)
        except (AttributeError, OSError):
            return False
        ev_led = getattr(native_ecodes, "EV_LED", 0x11)
        return ev_led in capabilities

    def _apply_led_status(self, device: InputDevice, led_status: bytes) -> None:
        if not led_status:
            return
        status = led_status[0]
        for hid_mask, evdev_name in self.HID_TO_EVDEV_LED:
            led_code = getattr(native_ecodes, evdev_name, None)
            if led_code is None:
                continue
            try:
                device.set_led(led_code, int(bool(status & hid_mask)))
            except (AttributeError, OSError):
                _logger.debug("Skipping LED update for %s", device.path)


class InputFrameAccumulator:
    """Collect evdev events until SYN_REPORT so stateful reports can be coalesced."""

    def __init__(self) -> None:
        self._events: list[InputEvent] = []

    def add(self, event: InputEvent) -> list[InputEvent] | None:
        if self._is_syn_report(event):
            return self.flush()
        self._events.append(event)
        return None

    def flush(self) -> list[InputEvent] | None:
        if not self._events:
            return None
        events = self._events
        self._events = []
        return events

    def clear(self) -> None:
        self._events = []

    def _is_syn_report(self, event: InputEvent) -> bool:
        input_event = getattr(event, "event", event)
        event_type = getattr(input_event, "type", None)
        event_code = getattr(input_event, "code", None)
        ev_syn = getattr(native_ecodes, "EV_SYN", 0)
        syn_report = getattr(native_ecodes, "SYN_REPORT", 0)
        return event_type == ev_syn and event_code == syn_report


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
        led_sync: KeyboardLedSync | None = None,
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
        self._led_sync = led_sync

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
                led_sync=self._led_sync,
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
        led_sync: KeyboardLedSync | None = None,
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
        self._led_sync = led_sync

        self._currently_grabbed = False
        self._hid_write_retries = 0
        self._hid_write_failures = 0
        self._frame_accumulator = InputFrameAccumulator()
        self._touch_active = False
        self._touch_contacts = 0
        self._touch_x: int | None = None
        self._touch_y: int | None = None
        self._last_touch_x: int | None = None
        self._last_touch_y: int | None = None
        self._touch_motion_x_remainder = 0.0
        self._touch_motion_y_remainder = 0.0
        self._touch_pan_remainder = 0.0
        self._touch_wheel_remainder = 0.0
        self._touch_x_scale, self._touch_y_scale = self._detect_touch_scale()
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
        if self._led_sync is not None:
            self._led_sync.register_input_device(self._input_device)
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
        if self._led_sync is not None:
            self._led_sync.unregister_input_device(self._input_device)
        try:
            self._input_device.close()
        except Exception:
            _logger.debug("Ignoring close failure for %s", self._input_device.path)
        return False

    def _should_ignore_ungrab_error(self, ex: Exception) -> bool:
        return isinstance(ex, OSError) and ex.errno in (errno.ENODEV, errno.EBADF)

    def _detect_touch_scale(self) -> tuple[float, float]:
        return (
            self._axis_scale(ecodes.ABS_MT_POSITION_X, ecodes.ABS_X),
            self._axis_scale(ecodes.ABS_MT_POSITION_Y, ecodes.ABS_Y),
        )

    def _axis_scale(self, preferred_code: int, fallback_code: int) -> float:
        for code in (preferred_code, fallback_code):
            try:
                info = self._input_device.absinfo(code)
            except (AttributeError, OSError):
                continue
            minimum = getattr(info, "min", 0)
            maximum = getattr(info, "max", 0)
            axis_range = maximum - minimum
            if axis_range > 0:
                return max(axis_range / 1024.0, 1.0)
        return 16.0

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
        device_disappeared = False
        try:
            async for input_event in self._input_device.async_read_loop():
                event = categorize(input_event)

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
                    self._discard_pending_input_state()
                    continue

                frame = self._frame_accumulator.add(event)
                if frame is not None:
                    await self._process_frame_with_retry(frame)
        except OSError as ex:
            if ex.errno != errno.ENODEV:
                raise
            _logger.debug(
                "Stopping relay loop for %s because the input device disappeared.",
                self._input_device.path,
            )
            device_disappeared = True
            self._discard_pending_input_state()
        if not device_disappeared:
            pending_frame = self._frame_accumulator.flush()
            if pending_frame is not None:
                await self._process_frame_with_retry(pending_frame)
        _logger.debug(
            "Relay stats for %s: hid_write_retries=%s hid_write_failures=%s",
            self._input_device.path,
            self._hid_write_retries,
            self._hid_write_failures,
        )

    async def _process_frame_with_retry(self, frame: list[InputEvent]) -> None:
        rel_x = rel_y = rel_wheel = 0
        rel_pan = 0.0
        rel_seen = False
        touch_seen = False

        for event in frame:
            if isinstance(event, RelEvent):
                x, y, wheel, pan = get_mouse_movement(event)
                rel_x += x
                rel_y += y
                rel_wheel += wheel
                rel_pan += pan
                rel_seen = True
                continue
            if isinstance(event, AbsEvent):
                self._update_touch_abs(event)
                touch_seen = True
                continue
            if isinstance(event, KeyEvent) and self._update_touch_key(event):
                touch_seen = True
                continue
            await self._process_event_with_retry(event)

        if rel_seen:
            rel_pan = self._rel_pan_remainder + rel_pan
            whole_pan = int(rel_pan)
            self._rel_pan_remainder = rel_pan - whole_pan
            await self._process_mouse_delta_with_retry(
                rel_x, rel_y, rel_wheel, whole_pan
            )
        if touch_seen:
            await self._process_touch_frame_with_retry()

    def _discard_pending_input_state(self) -> None:
        self._frame_accumulator.clear()
        self._rel_pan_remainder = 0.0
        self._reset_touch_state()

    def _reset_touch_state(self) -> None:
        self._touch_active = False
        self._touch_contacts = 0
        self._touch_x = None
        self._touch_y = None
        self._last_touch_x = None
        self._last_touch_y = None
        self._touch_motion_x_remainder = 0.0
        self._touch_motion_y_remainder = 0.0
        self._touch_pan_remainder = 0.0
        self._touch_wheel_remainder = 0.0

    def _update_touch_abs(self, event: AbsEvent) -> None:
        input_event = event.event
        if input_event.code in (ecodes.ABS_X, ecodes.ABS_MT_POSITION_X):
            self._touch_x = input_event.value
        elif input_event.code in (ecodes.ABS_Y, ecodes.ABS_MT_POSITION_Y):
            self._touch_y = input_event.value

    def _update_touch_key(self, event: KeyEvent) -> bool:
        scancode = event.scancode
        is_down = event.keystate in (KeyEvent.key_down, KeyEvent.key_hold)
        if scancode == ecodes.BTN_TOUCH:
            self._touch_active = is_down
            if not is_down:
                self._reset_touch_state()
            return True
        contact_counts = {
            ecodes.BTN_TOOL_FINGER: 1,
            ecodes.BTN_TOOL_DOUBLETAP: 2,
            ecodes.BTN_TOOL_TRIPLETAP: 3,
            ecodes.BTN_TOOL_QUADTAP: 4,
            ecodes.BTN_TOOL_QUINTTAP: 5,
        }
        contact_count = contact_counts.get(scancode)
        if contact_count is None:
            return False
        self._touch_contacts = (
            contact_count if is_down else min(self._touch_contacts, contact_count - 1)
        )
        return True

    async def _process_touch_frame_with_retry(self) -> None:
        if not self._touch_active or self._touch_x is None or self._touch_y is None:
            return
        if self._last_touch_x is None or self._last_touch_y is None:
            self._last_touch_x = self._touch_x
            self._last_touch_y = self._touch_y
            return

        delta_x = self._touch_x - self._last_touch_x
        delta_y = self._touch_y - self._last_touch_y
        self._last_touch_x = self._touch_x
        self._last_touch_y = self._touch_y

        if self._touch_contacts >= 2:
            pan = self._accumulate_scaled_touch_delta(
                delta_x, self._touch_x_scale, "_touch_pan_remainder"
            )
            wheel = -self._accumulate_scaled_touch_delta(
                delta_y, self._touch_y_scale, "_touch_wheel_remainder"
            )
            await self._process_mouse_delta_with_retry(0, 0, wheel, pan)
            return

        x = self._accumulate_scaled_touch_delta(
            delta_x, self._touch_x_scale, "_touch_motion_x_remainder"
        )
        y = self._accumulate_scaled_touch_delta(
            delta_y, self._touch_y_scale, "_touch_motion_y_remainder"
        )
        await self._process_mouse_delta_with_retry(x, y, 0, 0)

    def _accumulate_scaled_touch_delta(
        self, delta: int, scale: float, remainder_attr: str
    ) -> int:
        total = getattr(self, remainder_attr) + delta
        steps = int(total / scale)
        setattr(self, remainder_attr, total - (steps * scale))
        return steps

    async def _process_mouse_delta_with_retry(
        self, x: int, y: int, wheel: int, pan: int
    ) -> None:
        if x == 0 and y == 0 and wheel == 0 and pan == 0:
            return
        max_tries = self.HID_WRITE_MAX_TRIES
        retry_delay = self.HID_WRITE_RETRY_DELAY_SEC
        for attempt in range(1, max_tries + 1):
            try:
                move_mouse_delta(x, y, wheel, pan, self._gadget_manager)
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
                _logger.exception("Error processing mouse frame")
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

    x, y, mwheel, pan = get_mouse_movement(event)
    move_mouse_delta(x, y, mwheel, pan, gadget_manager)


def move_mouse_delta(
    x: int, y: int, mwheel: int, pan: int | float, gadget_manager: GadgetManager
) -> None:
    mouse = gadget_manager.get_mouse()
    if mouse is None:
        raise RuntimeError("Mouse gadget not initialized or manager not enabled.")
    mouse.move(x, y, mwheel, int(pan))


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
