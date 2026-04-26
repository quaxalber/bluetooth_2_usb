from __future__ import annotations

from .logging import get_logger

_logger = get_logger()


def _clamp_hid_i8(value: int) -> int:
    return min(127, max(-127, value))


def _clamp_hid_i16(value: int) -> int:
    return min(32767, max(-32767, value))


class ExtendedMouse:
    """Small mouse report writer with horizontal pan support."""

    LEFT = LEFT_BUTTON = 0x01
    RIGHT = RIGHT_BUTTON = 0x02
    MIDDLE = MIDDLE_BUTTON = 0x04
    SIDE = SIDE_BUTTON = 0x08
    EXTRA = EXTRA_BUTTON = 0x10
    FORWARD = FORWARD_BUTTON = 0x20
    BACK = BACK_BUTTON = 0x40
    TASK = TASK_BUTTON = 0x80

    def __init__(self, devices) -> None:
        from adafruit_hid import find_device

        self._mouse_device = find_device(devices, usage_page=0x1, usage=0x02)
        if not self._mouse_device:
            raise ValueError("Could not find matching mouse HID device.")
        self.report = bytearray(7)
        self._pan_remainder = 0.0

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

    def move(self, x: int = 0, y: int = 0, wheel: int = 0, pan: float = 0) -> None:
        pan_total = self._pan_remainder + pan
        pan = int(pan_total)
        self._pan_remainder = pan_total - pan
        while x != 0 or y != 0 or wheel != 0 or pan != 0:
            partial_x = _clamp_hid_i16(x)
            partial_y = _clamp_hid_i16(y)
            partial_wheel = _clamp_hid_i8(wheel)
            partial_pan = _clamp_hid_i8(pan)
            self.report[1:3] = partial_x.to_bytes(2, "little", signed=True)
            self.report[3:5] = partial_y.to_bytes(2, "little", signed=True)
            self.report[5] = partial_wheel & 0xFF
            self.report[6] = partial_pan & 0xFF
            _logger.debug(
                "Sending mouse movement to gadget: buttons=0x%02x x=%s y=%s "
                "wheel=%s pan=%s report=%s",
                self.report[0],
                partial_x,
                partial_y,
                partial_wheel,
                partial_pan,
                self.report.hex(" "),
            )
            self._mouse_device.send_report(self.report)
            x -= partial_x
            y -= partial_y
            wheel -= partial_wheel
            pan -= partial_pan

    def _send_no_move(self) -> None:
        self.report[1:7] = b"\x00" * 6
        self._mouse_device.send_report(self.report)
