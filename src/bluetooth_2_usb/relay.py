import asyncio
from asyncio import CancelledError, TaskGroup
import re
from typing import AsyncGenerator, NoReturn, Optional

from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.mouse import Mouse
from evdev import InputDevice, InputEvent, KeyEvent, RelEvent, categorize, list_devices
import pyudev
import usb_hid
from usb_hid import Device

from .evdev import (
    evdev_to_usb_hid,
    get_mouse_movement,
    is_consumer_key,
    is_mouse_button,
)
from .logging import get_logger


_logger = get_logger()
_keyboard_gadget: Optional[Keyboard] = None
_mouse_gadget: Optional[Mouse] = None
_consumer_gadget: Optional[ConsumerControl] = None

PATH = "path"
MAC = "MAC"
NAME = "name"
PATH_REGEX = r"^\/dev\/input\/event.*$"
MAC_REGEX = r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$"


async def async_list_input_devices() -> list[InputDevice]:
    devices = []
    try:
        devices = [InputDevice(path) for path in list_devices()]
    except Exception:
        _logger.exception("Failed listing devices")
        await asyncio.sleep(1)
    return devices


def init_usb_gadgets() -> None:
    _logger.debug("Initializing USB gadgets...")
    usb_hid.enable(
        [
            Device.BOOT_MOUSE,
            Device.KEYBOARD,
            Device.CONSUMER_CONTROL,
        ]  # type: ignore
    )
    global _keyboard_gadget, _mouse_gadget, _consumer_gadget
    enabled_devices: list[Device] = list(usb_hid.devices)  # type: ignore
    _keyboard_gadget = Keyboard(enabled_devices)
    _mouse_gadget = Mouse(enabled_devices)
    _consumer_gadget = ConsumerControl(enabled_devices)
    _logger.debug(f"Enabled USB gadgets: {enabled_devices}")


def all_gadgets_ready() -> bool:
    return all(
        dev is not None for dev in (_keyboard_gadget, _mouse_gadget, _consumer_gadget)
    )


class DeviceIdentifier:
    def __init__(self, device_identifier: str) -> None:
        self._value = device_identifier
        self._type = self._determine_identifier_type()
        self._normalized_value = self._normalize_identifier()

    @property
    def value(self) -> str:
        return self._value

    @property
    def normalized_value(self) -> str:
        return self._normalized_value

    @property
    def type(self) -> str:
        return self._type

    def __str__(self) -> str:
        return f'{self.type} "{self.value}"'

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.value})"

    def _determine_identifier_type(self) -> str:
        if re.match(PATH_REGEX, self.value):
            return PATH
        if re.match(MAC_REGEX, self.value):
            return MAC
        return NAME

    def _normalize_identifier(self) -> str:
        if self.type == PATH:
            return self.value
        if self.type == MAC:
            return self.value.lower().replace("-", ":")
        return self.value.lower()

    def matches(self, device: InputDevice) -> bool:
        if self.type == PATH:
            return self.value == device.path
        if self.type == MAC:
            return self.normalized_value == device.uniq
        return self.normalized_value in device.name.lower()


class DeviceRelay:
    def __init__(self, input_device: InputDevice, grab_device: bool = False) -> None:
        self._input_device = input_device
        self._grab_device = grab_device
        if grab_device:
            self._input_device.grab()
        if not all_gadgets_ready():
            init_usb_gadgets()

    @property
    def input_device(self) -> InputDevice:
        return self._input_device

    def __str__(self) -> str:
        return f"relay for {self.input_device}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.input_device!r}, {self._grab_device})"

    async def async_relay_events_loop(self) -> NoReturn:
        async for event in self.input_device.async_read_loop():
            await self._async_relay_event(event)

    async def _async_relay_event(self, input_event: InputEvent) -> None:
        event = categorize(input_event)
        _logger.debug(f"Received {event} from {self.input_device.name}")

        if isinstance(event, RelEvent):
            _move_mouse(event)
        elif isinstance(event, KeyEvent):
            _send_key(event)


def _move_mouse(event: RelEvent) -> None:
    if _mouse_gadget is None:
        raise RuntimeError("Mouse gadget not initialized")
    x, y, mwheel = get_mouse_movement(event)
    coordinates = f"(x={x}, y={y}, mwheel={mwheel})"
    try:
        _logger.debug(f"Moving {_mouse_gadget} {coordinates}")
        _mouse_gadget.move(x, y, mwheel)
    except Exception:
        _logger.exception(f"Failed moving {_mouse_gadget} {coordinates}")


def _send_key(event: KeyEvent) -> None:
    key_id, key_name = evdev_to_usb_hid(event)
    if key_id is None or key_name is None:
        return
    device_out = _get_output_device(event)
    if device_out is None:
        raise RuntimeError("USB gadget not initialized")
    try:
        if event.keystate == KeyEvent.key_down:
            _logger.debug(f"Pressing {key_name} (0x{key_id:02X}) on {device_out}")
            device_out.press(key_id)
        elif event.keystate == KeyEvent.key_up:
            _logger.debug(f"Releasing {key_name} (0x{key_id:02X}) on {device_out}")
            device_out.release(key_id)
    except Exception:
        _logger.exception(f"Failed sending 0x{key_id:02X} to {device_out}")


def _get_output_device(event: KeyEvent) -> ConsumerControl | Keyboard | Mouse | None:
    if is_consumer_key(event):
        return _consumer_gadget
    elif is_mouse_button(event):
        return _mouse_gadget
    return _keyboard_gadget


class RelayController:
    """
    Manages the TaskGroup of all active DeviceRelay tasks and handles
    add/remove events from UdevEventMonitor.
    """

    def __init__(
        self,
        device_identifiers: Optional[list[str]] = None,
        auto_discover: bool = False,
        grab_devices: bool = False,
    ) -> None:
        if not device_identifiers:
            device_identifiers = []
        self._device_ids = [DeviceIdentifier(id) for id in device_identifiers]
        self._auto_discover = auto_discover
        self._grab_devices = grab_devices
        self._task_group: TaskGroup | None = None
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._cancelled = False

    async def async_relay_devices(self) -> None:
        """
        Main method that opens a TaskGroup and waits forever,
        while device add/remove is handled dynamically.
        """
        try:
            async with TaskGroup() as task_group:
                self._task_group = task_group
                _logger.debug("RelayController: TaskGroup started.")

                for dev in await async_list_input_devices():
                    self.add_device(dev)

                while not self._cancelled:
                    await asyncio.sleep(0.1)
        except* Exception as exc_grp:
            _logger.exception("RelayController: Exception in TaskGroup", exc_info=exc_grp)
        finally:
            self._task_group = None
            _logger.info("RelayController: TaskGroup exited.")

    def add_device(self, device: InputDevice) -> None:
        """
        Called when a new device is detected. Schedules a new relay task if
        the device passes the _should_relay() check and isn't already tracked.
        """
        if not self._should_relay(device):
            _logger.debug(f"Device {device.path} does not match criteria; ignoring.")
            return

        if self._task_group is None:
            _logger.critical(f"No TaskGroup available; ignoring device {device.path}.")
            return

        if device.path not in self._active_tasks:
            task = self._task_group.create_task(
                self._async_relay_events(device),
                name=device.path
            )
            self._active_tasks[device.path] = task
            _logger.debug(f"Created task for {device.path}.")
        else:
            _logger.debug(f"Device {device.path} is already active.")

    def remove_device(self, device_path: str) -> None:
        """
        Called when a device is removed. Cancels the associated relay task if running.
        """
        task = self._active_tasks.pop(device_path, None)
        if task and not task.done():
            _logger.info(f"Cancelling relay for {device_path}.")
            task.cancel()
        else:
            _logger.debug(f"No active task found for {device_path} to remove.")

    async def _async_relay_events(self, device: InputDevice) -> None:
        """
        Creates a DeviceRelay, then loops forever reading events.
        """
        relay = DeviceRelay(device, self._grab_devices)
        _logger.info(f"Activated {relay}")

        try:
            await relay.async_relay_events_loop()
        except CancelledError:
            _logger.debug(f"Relay cancelled for device {device.path}.")
            raise
        except (OSError, FileNotFoundError) as ex:
            _logger.critical(f"Lost connection to {device.path} [{ex!r}].")
        except Exception:
            _logger.exception(f"Unhandled exception in relay for {device.path}.")

    def _should_relay(self, device: InputDevice) -> bool:
        """Return True if we should relay this device (auto_discover or matches)."""
        return self._auto_discover or any(id.matches(device) for id in self._device_ids)



class UdevEventMonitor:
    """
    Watches for new/removed /dev/input/event* devices and notifies RelayController.
    """

    def __init__(self, relay_controller: RelayController, loop: asyncio.AbstractEventLoop):
        self.relay_controller = relay_controller
        self.loop = loop
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='input')

        # Create an observer that calls _udev_event_callback on add/remove
        self.observer = pyudev.MonitorObserver(self.monitor, self._udev_event_callback)
        self.observer.start()
        _logger.debug("UdevEventMonitor started.")

    def _udev_event_callback(self, action: str, device: pyudev.Device) -> None:
        """pyudev callback for device add/remove events."""
        device_node = device.device_node
        if not device_node or not device_node.startswith("/dev/input/event"):
            return

        if action == "add":
            _logger.debug(f"UdevEventMonitor: Added => {device_node}")
            device = InputDevice(device_node)
            self.relay_controller.add_device(device)

        elif action == "remove":
            _logger.debug(f"UdevEventMonitor: Removed => {device_node}")
            self.relay_controller.remove_device(device_node)
