from __future__ import annotations

import asyncio

from ..logging import get_logger
from . import timing
from .bounds import clamp_hid_i8, clamp_hid_i16
from .constants import (
    HID_PAGE_GENERIC_DESKTOP,
    HID_USAGE_MOUSE,
    MOUSE_BUTTON_REPORT_INDEX,
    MOUSE_IN_REPORT_LENGTH,
    MOUSE_MOVEMENT_REPORT_LENGTH,
    MOUSE_MOVEMENT_REPORT_SLICE,
    MOUSE_PAN_REPORT_SLICE,
    MOUSE_WHEEL_REPORT_SLICE,
    MOUSE_X_REPORT_SLICE,
    MOUSE_Y_REPORT_SLICE,
)

logger = get_logger(__name__)


class ExtendedMouse:
    """Small mouse report writer with horizontal pan support."""

    REPORT_WRITE_MAX_TRIES = timing.REPORT_WRITE_MAX_TRIES
    REPORT_WRITE_RETRY_DELAY_SEC = timing.REPORT_WRITE_RETRY_DELAY_SEC

    def __init__(self, devices) -> None:
        from adafruit_hid import find_device

        self._mouse_device = find_device(devices, usage_page=HID_PAGE_GENERIC_DESKTOP, usage=HID_USAGE_MOUSE)
        if not self._mouse_device:
            raise ValueError("Could not find matching mouse HID device.")
        self.report = bytearray(MOUSE_IN_REPORT_LENGTH)
        self._report_lock = asyncio.Lock()
        self._wheel_remainder = 0.0
        self._pan_remainder = 0.0

    def __str__(self):
        return str(self._mouse_device)

    async def press(self, buttons: int) -> None:
        async with self._report_lock:
            self.report[MOUSE_BUTTON_REPORT_INDEX] |= buttons
            await self._send_no_move()

    async def release(self, buttons: int) -> None:
        async with self._report_lock:
            self.report[MOUSE_BUTTON_REPORT_INDEX] &= ~buttons
            await self._send_no_move()

    async def release_all(self) -> None:
        async with self._report_lock:
            self.report[MOUSE_BUTTON_REPORT_INDEX] = 0
            await self._send_no_move()

    async def move(self, x: int = 0, y: int = 0, wheel: float = 0, pan: float = 0) -> None:
        async with self._report_lock:
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
                self.report[MOUSE_X_REPORT_SLICE] = partial_x.to_bytes(2, "little", signed=True)
                self.report[MOUSE_Y_REPORT_SLICE] = partial_y.to_bytes(2, "little", signed=True)
                self.report[MOUSE_WHEEL_REPORT_SLICE] = partial_wheel.to_bytes(1, "little", signed=True)
                self.report[MOUSE_PAN_REPORT_SLICE] = partial_pan.to_bytes(1, "little", signed=True)
                logger.debug(
                    "Sending mouse movement to gadget: buttons=0x%02x x=%s y=%s " + "wheel=%s pan=%s report=%s",
                    self.report[MOUSE_BUTTON_REPORT_INDEX],
                    partial_x,
                    partial_y,
                    partial_wheel,
                    partial_pan,
                    self.report.hex(" "),
                )
                await self._send_report()
                x -= partial_x
                y -= partial_y
                wheel -= partial_wheel
                pan -= partial_pan

    async def _send_no_move(self) -> None:
        self.report[MOUSE_MOVEMENT_REPORT_SLICE] = b"\x00" * MOUSE_MOVEMENT_REPORT_LENGTH
        await self._send_report()

    async def _send_report(self) -> None:
        max_tries = self.REPORT_WRITE_MAX_TRIES
        for attempt in range(1, max_tries + 1):
            try:
                self._mouse_device.send_report(self.report)
                return
            except BlockingIOError:
                if attempt >= max_tries:
                    raise
                await asyncio.sleep(self.REPORT_WRITE_RETRY_DELAY_SEC)
