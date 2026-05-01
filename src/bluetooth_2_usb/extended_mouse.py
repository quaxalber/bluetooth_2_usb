from __future__ import annotations

import time

from .hid_bounds import clamp_hid_i8, clamp_hid_i16
from .logging import get_logger

logger = get_logger(__name__)


class ExtendedMouse:
    """Small mouse report writer with horizontal pan support."""

    CHUNK_REPORT_INTERVAL_SEC = 0.001

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
        self._wheel_remainder = 0.0
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

    def move(self, x: int = 0, y: int = 0, wheel: float = 0, pan: float = 0) -> None:
        wheel_total = self._wheel_remainder + wheel
        wheel = int(wheel_total)
        self._wheel_remainder = wheel_total - wheel
        pan_total = self._pan_remainder + pan
        pan = int(pan_total)
        self._pan_remainder = pan_total - pan
        while x != 0 or y != 0 or wheel != 0 or pan != 0:
            partial_x = clamp_hid_i16(x)
            partial_y = clamp_hid_i16(y)
            partial_wheel = clamp_hid_i8(wheel)
            partial_pan = clamp_hid_i8(pan)
            self.report[1:3] = partial_x.to_bytes(2, "little", signed=True)
            self.report[3:5] = partial_y.to_bytes(2, "little", signed=True)
            self.report[5:6] = partial_wheel.to_bytes(1, "little", signed=True)
            self.report[6:7] = partial_pan.to_bytes(1, "little", signed=True)
            logger.debug(
                "Sending mouse movement to gadget: buttons=0x%02x x=%s y=%s "
                + "wheel=%s pan=%s report=%s",
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
            if x != 0 or y != 0 or wheel != 0 or pan != 0:
                time.sleep(self.CHUNK_REPORT_INTERVAL_SEC)

    def _send_no_move(self) -> None:
        self.report[1:7] = b"\x00" * 6
        self._mouse_device.send_report(self.report)
