from __future__ import annotations

import asyncio


class ExtendedConsumerControl:
    """Consumer-control report writer with short transient write retry."""

    REPORT_WRITE_MAX_TRIES = 3
    REPORT_WRITE_RETRY_DELAY_SEC = 0.001

    def __init__(self, devices) -> None:
        from adafruit_hid.consumer_control import ConsumerControl

        self._consumer_control = ConsumerControl(devices)

    def __str__(self):
        return str(self._consumer_control)

    async def press(self, consumer_code: int) -> None:
        await self._write(self._consumer_control.press, consumer_code)

    async def release(self) -> None:
        await self._write(self._consumer_control.release)

    async def _write(self, operation, *args) -> None:
        max_tries = self.REPORT_WRITE_MAX_TRIES
        for attempt in range(1, max_tries + 1):
            try:
                operation(*args)
                return
            except BlockingIOError:
                if attempt >= max_tries:
                    raise
                await asyncio.sleep(self.REPORT_WRITE_RETRY_DELAY_SEC)
