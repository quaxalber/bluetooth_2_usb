import asyncio
from asyncio import CancelledError, TaskGroup
import re
from typing import AsyncGenerator, NoReturn

from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.mouse import Mouse
from evdev import (
    InputDevice,
    InputEvent,
    KeyEvent,
    RelEvent,
    categorize,
    list_devices,
)
import usb_hid
from usb_hid import Device

from .evdev import (
    get_mouse_movement,
    is_consumer_key,
    is_mouse_button,
    evdev_to_usb_hid,
)
from .logging import get_logger


_logger = get_logger()

PATH = "path"
MAC = "MAC"
NAME = "name"


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

    def __str__(self):
        return self.value

    def __repr__(self):
        return f'{self.type} "{self.value}"'

    def _determine_identifier_type(self) -> str:
        mac_regex = r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$"
        path_regex = r"^\/dev\/input\/event.*$"
        if re.match(mac_regex, self.value):
            return MAC
        if re.match(path_regex, self.value):
            return PATH
        return NAME

    def _normalize_identifier(self) -> str:
        if self.type == PATH:
            return self.value
        if self.type == NAME:
            return self.value.lower()
        if self.type == MAC:
            return self.value.lower().replace("-", ":")

    def matches(self, device: InputDevice) -> bool:
        if self.type == PATH:
            return self.value == device.path
        if self.type == NAME:
            return self.normalized_value in device.name.lower()
        if self.type == MAC:
            return self.normalized_value == device.uniq


class DeviceRelay:
    def __init__(self, input_device: InputDevice):
        self._input_device = input_device
        self._keyboard_gadget = Keyboard(usb_hid.devices)
        self._mouse_gadget = Mouse(usb_hid.devices)
        self._consumer_gadget = ConsumerControl(usb_hid.devices)

    @property
    def input_device(self) -> InputDevice:
        return self._input_device

    def __str__(self):
        return f"relay for {self.input_device.name}"

    def __repr__(self):
        return f"relay for {self.input_device}"

    async def async_relay_events_loop(self) -> NoReturn:
        async for event in self.input_device.async_read_loop():
            await self._async_relay_event(event)

    async def _async_relay_event(self, input_event: InputEvent) -> None:
        event = categorize(input_event)
        _logger.debug(f"Received {event} from {self.input_device.name}")
        method = None
        if isinstance(event, RelEvent):
            method = self._move_mouse
        elif isinstance(event, KeyEvent):
            method = self._send_key
        if method:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, method, event)

    def _send_key(self, event: KeyEvent) -> None:
        key_id, key_name = evdev_to_usb_hid(event)
        if key_id is None:
            return
        device_out = self._get_output_device(event)
        try:
            if event.keystate == KeyEvent.key_down:
                _logger.debug(f"Pressing {key_name} (0x{key_id:02X}) on {device_out}")
                device_out.press(key_id)
            elif event.keystate == KeyEvent.key_up:
                _logger.debug(f"Releasing {key_name} (0x{key_id:02X}) on {device_out}")
                device_out.release(key_id)
        except Exception:
            _logger.exception(f"Failed sending 0x{key_id:02X} to {device_out}")

    def _get_output_device(self, event: KeyEvent) -> ConsumerControl | Keyboard | Mouse:
        if is_consumer_key(event):
            return self._consumer_gadget
        elif is_mouse_button(event):
            return self._mouse_gadget
        return self._keyboard_gadget

    def _move_mouse(self, event: RelEvent) -> None:
        x, y, mwheel = get_mouse_movement(event)
        coordinates = f"(x={x}, y={y}, mwheel={mwheel})"
        try:
            _logger.debug(f"Moving mouse {self._mouse_gadget} {coordinates}")
            self._mouse_gadget.move(x, y, mwheel)
        except Exception:
            _logger.exception(f"Failed moving mouse {self._mouse_gadget} {coordinates}")


class RelayController:
    """
    This class serves as a HID relay to handle Bluetooth keyboard and mouse events from multiple input devices and translate them to USB.
    """

    def __init__(
        self, device_identifiers: list[str] = None, auto_discover: bool = False
    ) -> None:
        _enable_usb_devices()
        if not device_identifiers:
            device_identifiers = []
        self._device_ids = [DeviceIdentifier(id) for id in device_identifiers]
        self._auto_discover = auto_discover
        self._cancelled = False

    async def async_relay_devices(self) -> NoReturn:
        try:
            async with TaskGroup() as task_group:
                await self._async_discover_devices(task_group)
            _logger.critical("Event loop closed.")
        except* Exception:
            _logger.exception("Error(s) in TaskGroup")

    async def _async_discover_devices(self, task_group: TaskGroup) -> NoReturn:
        async for device in self._async_discover_devices_loop():
            if not self._cancelled:
                self._create_task(device, task_group)

    async def _async_discover_devices_loop(self) -> AsyncGenerator[InputDevice, None]:
        _logger.info("Discovering input devices...")
        if self._auto_discover:
            _logger.debug("Auto-discovery enabled. Relaying all input devices.")
        else:
            all_device_ids = " or ".join(repr(id) for id in self._device_ids)
            _logger.debug(f"Relaying devices with matching {all_device_ids}")
        while True:
            for device in list_readable_devices():
                if self._should_relay(device):
                    yield device
            await asyncio.sleep(1)

    def _should_relay(self, device: InputDevice) -> bool:
        return not self._has_task(device) and self._matches_criteria(device)

    def _has_task(self, device: InputDevice) -> bool:
        return device.path in [task.get_name() for task in asyncio.all_tasks()]

    def _matches_criteria(self, device: InputDevice) -> bool:
        return self._auto_discover or self._matches_any_identifier(device)

    def _matches_any_identifier(self, device: InputDevice) -> bool:
        return any(id.matches(device) for id in self._device_ids)

    def _create_task(self, device: InputDevice, task_group: TaskGroup) -> None:
        task_group.create_task(self._async_relay_events(device), name=device.path)

    async def _async_relay_events(self, device: InputDevice) -> NoReturn:
        try:
            relay = DeviceRelay(device)
            _logger.info(f"Activated {repr(relay)}")
            await relay.async_relay_events_loop()
        except CancelledError:
            self._cancelled = True
            _logger.critical(f"{device.name} was cancelled")
        except (OSError, FileNotFoundError) as ex:
            _logger.critical(f"Connection to {device.name} lost [{repr(ex)}]")
        except Exception:
            _logger.exception(f"{device.name} failed!")
            await asyncio.sleep(2)


def list_readable_devices() -> list[InputDevice]:
    return [InputDevice(path) for path in list_devices()]


def _enable_usb_devices():
    usb_hid.enable(
        [
            Device.MOUSE,
            Device.KEYBOARD,
            Device.CONSUMER_CONTROL,
        ]
    )
    _logger.debug(f"Available USB devices: {usb_hid.devices}")
