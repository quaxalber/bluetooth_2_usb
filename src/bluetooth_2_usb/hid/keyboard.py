from __future__ import annotations

import asyncio

from . import timing


class ExtendedKeyboard:
    """Keyboard report writer with short transient write retry."""

    REPORT_WRITE_MAX_TRIES = timing.REPORT_WRITE_MAX_TRIES
    REPORT_WRITE_RETRY_DELAY_SEC = timing.REPORT_WRITE_RETRY_DELAY_SEC

    def __init__(self, devices) -> None:
        from adafruit_hid.keyboard import Keyboard

        self._keyboard = Keyboard(devices)

    def __str__(self):
        return str(self._keyboard)

    async def press(self, keycode: int) -> None:
        await self._write(self._keyboard.press, keycode)

    async def release(self, keycode: int) -> None:
        await self._write(self._keyboard.release, keycode)

    async def release_all(self) -> None:
        await self._write(self._keyboard.release_all)

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
