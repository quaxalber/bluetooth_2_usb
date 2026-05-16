from __future__ import annotations

import asyncio

from ..logging import get_logger
from . import timing
from .absolute import PadReport, PenReport
from .constants import (
    HID_PAGE_DIGITIZER,
    HID_USAGE_DIGITIZER_PEN,
    HID_USAGE_DIGITIZER_TOUCH_PAD,
    TABLET_PAD_IN_REPORT_LENGTH,
    TABLET_PAD_REPORT_ID,
    TABLET_PEN_IN_REPORT_LENGTH,
    TABLET_PEN_REPORT_ID,
)

logger = get_logger(__name__)


class ExtendedTabletDigitizer:
    """Generic tablet pen and pad report writer."""

    REPORT_WRITE_MAX_TRIES = timing.REPORT_WRITE_MAX_TRIES
    REPORT_WRITE_RETRY_DELAY_SEC = timing.REPORT_WRITE_RETRY_DELAY_SEC

    def __init__(self, devices) -> None:
        from adafruit_hid import find_device

        try:
            self._device = find_device(devices, usage_page=HID_PAGE_DIGITIZER, usage=HID_USAGE_DIGITIZER_PEN)
        except ValueError:
            self._device = None
        if not self._device:
            self._device = find_device(devices, usage_page=HID_PAGE_DIGITIZER, usage=HID_USAGE_DIGITIZER_TOUCH_PAD)
        if not self._device:
            raise ValueError("Could not find matching tablet digitizer HID device.")
        self._report_lock = asyncio.Lock()

    def __str__(self) -> str:
        return str(self._device)

    async def send_pen(self, pen_report: PenReport) -> None:
        async with self._report_lock:
            report = bytearray(TABLET_PEN_IN_REPORT_LENGTH)
            report[0] = (
                (0x01 if pen_report.in_range else 0)
                | (0x02 if pen_report.tip else 0)
                | (0x04 if pen_report.eraser else 0)
                | (0x08 if pen_report.barrel else 0)
                | (0x10 if pen_report.barrel2 else 0)
            )
            report[1:3] = pen_report.x.to_bytes(2, "little")
            report[3:5] = pen_report.y.to_bytes(2, "little")
            report[5:7] = pen_report.pressure.to_bytes(2, "little")
            report[7:9] = pen_report.distance.to_bytes(2, "little")
            report[9] = pen_report.tilt_x.to_bytes(1, "little", signed=True)[0]
            report[10] = pen_report.tilt_y.to_bytes(1, "little", signed=True)[0]
            report[11:15] = pen_report.serial.to_bytes(4, "little")
            logger.debug("Sending tablet pen report: %s", report.hex(" "))
            await self._send_report(report, TABLET_PEN_REPORT_ID)

    async def send_pad(self, pad_report: PadReport) -> None:
        async with self._report_lock:
            report = bytearray(TABLET_PAD_IN_REPORT_LENGTH)
            report[0:2] = pad_report.buttons.to_bytes(2, "little")
            report[2] = pad_report.wheel.to_bytes(1, "little", signed=True)[0]
            logger.debug("Sending tablet pad report: %s", report.hex(" "))
            await self._send_report(report, TABLET_PAD_REPORT_ID)

    async def release_all(self) -> None:
        await self.send_pen(
            PenReport(
                in_range=False,
                tip=False,
                eraser=False,
                barrel=False,
                barrel2=False,
                x=0,
                y=0,
                pressure=0,
                distance=0,
                tilt_x=0,
                tilt_y=0,
                serial=0,
            )
        )
        await self.send_pad(PadReport(buttons=0, wheel=0))

    async def _send_report(self, report: bytearray, report_id: int) -> None:
        target_report_length = getattr(self._device, "configfs_report_length", 0)
        if target_report_length > 1:
            payload_length = target_report_length - 1
            if len(report) < payload_length:
                report = report + bytearray(payload_length - len(report))
        for attempt in range(1, self.REPORT_WRITE_MAX_TRIES + 1):
            try:
                self._device.send_report(report, report_id)
                return
            except BlockingIOError:
                if attempt >= self.REPORT_WRITE_MAX_TRIES:
                    raise
                await asyncio.sleep(self.REPORT_WRITE_RETRY_DELAY_SEC)
