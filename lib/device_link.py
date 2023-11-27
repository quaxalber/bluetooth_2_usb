import asyncio

from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.mouse import Mouse
from evdev import InputDevice

import lib.logger

_logger = lib.logger.get_logger()


class DummyGadget:
    def __init__(self, actual_gadget):
        self._actual_gadget = actual_gadget

    def __repr__(self):
        return repr(self._actual_gadget)

    def __str__(self):
        return str(self._actual_gadget)

    def press(self, *keycodes: int) -> None:
        pass

    def release(self, *keycodes: int) -> None:
        pass

    def release_all(self) -> None:
        pass

    def send(self, *keycodes: int) -> None:
        pass

    @property
    def led_status(self) -> bytes:
        return b"\x00"

    def led_on(self, led_code: int) -> bool:
        return False

    def click(self, buttons: int) -> None:
        pass

    def move(self, x: int = 0, y: int = 0, wheel: int = 0) -> None:
        pass


class DeviceLink:
    def __init__(
        self,
        input_device_path: str,
        keyboard_gadget: Keyboard = None,
        mouse_gadget: Mouse = None,
        consumer_gadget: ConsumerControl = None,
    ):
        self._input_device = None
        self._input_device_name = f"[Disconnected] {input_device_path}"
        self._input_device_path = input_device_path

        self._keyboard_gadget = keyboard_gadget
        self._mouse_gadget = mouse_gadget
        self._consumer_gadget = consumer_gadget

        self.gadgets_enabled = True

        self._active_gadgets: list[ConsumerControl | Keyboard | Mouse | DummyGadget] = [
            gadget
            for gadget in [keyboard_gadget, mouse_gadget, consumer_gadget]
            if gadget is not None
        ]

    def __repr__(self):
        active_gadgets_repr = [repr(g) for g in self._active_gadgets]
        return f"[{self._input_device}] >> [{' + '.join(active_gadgets_repr)}]"

    def __str__(self):
        active_gadgets_str = [str(g) for g in self._active_gadgets]
        return f"[{self._input_device_name}]>>[{'+'.join(active_gadgets_str)}]"

    @property
    def input_device_connected(self) -> bool:
        return not (self._input_device is None)
    
    @property
    def input_device(self) -> InputDevice:
        return self._input_device

    @property
    def path(self) -> str:
        return self._input_device_path

    @property
    def name(self) -> str:
        return self._input_device_name

    def reset_input_device(self) -> None:
        self._input_device = None
        self._input_device_name = f"[Disconnected] {self._input_device_path}"
        self._input_device = InputDevice(self._input_device_path)
        self._input_device_name = self._input_device.name

    async def async_reset_input_device(self) -> None:
        self._input_device = None
        self._input_device_name = f"[Disconnected] {self._input_device_path}"
        while True:
            try:
                self._input_device = InputDevice(self._input_device_path)
                self._input_device_name = self._input_device.name
                break
            except Exception:
                _logger.exception(f"Error resetting input {self._input_device_path}")
                await asyncio.sleep(1)

    @property
    def keyboard_gadget(self) -> Keyboard | DummyGadget | None:
        return self._gadget_or_dummy(self._keyboard_gadget)

    @property
    def mouse_gadget(self) -> Mouse | DummyGadget | None:
        return self._gadget_or_dummy(self._mouse_gadget)

    @property
    def consumer_gadget(self) -> ConsumerControl | DummyGadget | None:
        return self._gadget_or_dummy(self._consumer_gadget)

    def _gadget_or_dummy(
        self, gadget: ConsumerControl | Keyboard | Mouse
    ) -> ConsumerControl | Keyboard | Mouse | DummyGadget | None:
        if self.gadgets_enabled:
            return gadget
        elif gadget is not None:
            return DummyGadget(gadget)
        return None

    @property
    def active_gadgets(self) -> list[ConsumerControl | Keyboard | Mouse | DummyGadget]:
        return self._active_gadgets
