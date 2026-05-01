from __future__ import annotations

import time


class ExtendedKeyboard:
    """Keyboard report writer with pacing for host-visible state transitions."""

    REPORT_WRITE_MAX_TRIES = 3
    REPORT_WRITE_RETRY_DELAY_SEC = 0.001
    REPORT_INTERVAL_SEC = 0.015

    def __init__(self, devices) -> None:
        from adafruit_hid.keyboard import Keyboard

        self._keyboard = Keyboard(devices)

    def __str__(self):
        return str(self._keyboard)

    def press(self, keycode: int) -> None:
        self._write(self._keyboard.press, keycode)
        time.sleep(self.REPORT_INTERVAL_SEC)

    def release(self, keycode: int) -> None:
        self._write(self._keyboard.release, keycode)
        time.sleep(self.REPORT_INTERVAL_SEC)

    def release_all(self) -> None:
        self._write(self._keyboard.release_all)
        time.sleep(self.REPORT_INTERVAL_SEC)

    def _write(self, operation, *args) -> None:
        max_tries = self.REPORT_WRITE_MAX_TRIES
        for attempt in range(1, max_tries + 1):
            try:
                operation(*args)
                return
            except BlockingIOError:
                if attempt >= max_tries:
                    raise
                time.sleep(self.REPORT_WRITE_RETRY_DELAY_SEC)
