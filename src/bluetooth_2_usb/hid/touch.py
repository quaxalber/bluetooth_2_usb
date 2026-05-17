from __future__ import annotations

import asyncio

from ..logging import get_logger
from . import timing
from .absolute import TouchReport
from .constants import (
    HID_PAGE_DIGITIZER,
    HID_USAGE_DIGITIZER_TOUCH_PAD,
    TOUCH_DIGITIZER_CONTACT_COUNT,
    TOUCH_DIGITIZER_IN_REPORT_LENGTH,
    TOUCH_DIGITIZER_REPORT_ID,
)

logger = get_logger(__name__)


class TouchDigitizer:
    """Generic multitouch digitizer report writer."""

    REPORT_WRITE_MAX_TRIES = timing.REPORT_WRITE_MAX_TRIES
    REPORT_WRITE_RETRY_DELAY_SEC = timing.REPORT_WRITE_RETRY_DELAY_SEC

    def __init__(self, devices, report_lock: asyncio.Lock | None = None) -> None:
        from adafruit_hid import find_device

        self._device = find_device(devices, usage_page=HID_PAGE_DIGITIZER, usage=HID_USAGE_DIGITIZER_TOUCH_PAD)
        if not self._device:
            raise ValueError("Could not find matching touch digitizer HID device.")
        self._report_lock = asyncio.Lock() if report_lock is None else report_lock

    def __str__(self) -> str:
        return str(self._device)

    async def send(self, touch_report: TouchReport) -> None:
        async with self._report_lock:
            report = bytearray(TOUCH_DIGITIZER_IN_REPORT_LENGTH)
            for index, contact in enumerate(touch_report.contacts[:TOUCH_DIGITIZER_CONTACT_COUNT]):
                offset = index * 9
                report[offset] = 0x03 if contact.active else 0x00
                report[offset + 1] = contact.report_id & 0xFF
                report[offset + 2 : offset + 4] = contact.x.to_bytes(2, "little")
                report[offset + 4 : offset + 6] = contact.y.to_bytes(2, "little")
                report[offset + 6] = contact.width & 0xFF
                report[offset + 7] = contact.height & 0xFF
                report[offset + 8] = contact.pressure & 0xFF
            report[45] = sum(1 for contact in touch_report.contacts if contact.active) & 0xFF
            report[46] = 0x01 if touch_report.button else 0x00
            report[47:49] = touch_report.scan_time.to_bytes(2, "little")
            logger.debug("Sending touch digitizer report: %s", report.hex(" "))
            await self._send_report(report)

    async def release_all(self) -> None:
        await self.send(TouchReport(contacts=(), button=False, scan_time=0))

    async def _send_report(self, report: bytearray) -> None:
        for attempt in range(1, self.REPORT_WRITE_MAX_TRIES + 1):
            try:
                self._device.send_report(report, TOUCH_DIGITIZER_REPORT_ID)
                return
            except BlockingIOError:
                if attempt >= self.REPORT_WRITE_MAX_TRIES:
                    raise
                await asyncio.sleep(self.REPORT_WRITE_RETRY_DELAY_SEC)
