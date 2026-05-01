from __future__ import annotations

import time


class ExtendedKeyboard:
    """Keyboard report writer with pacing for host-visible state transitions."""

    REPORT_INTERVAL_SEC = 0.015

    def __init__(self, devices) -> None:
        from adafruit_hid.keyboard import Keyboard

        self._keyboard = Keyboard(devices)

    def __str__(self):
        return str(self._keyboard)

    def press(self, keycode: int) -> None:
        self._keyboard.press(keycode)
        time.sleep(self.REPORT_INTERVAL_SEC)

    def release(self, keycode: int) -> None:
        self._keyboard.release(keycode)
        time.sleep(self.REPORT_INTERVAL_SEC)

    def release_all(self) -> None:
        self._keyboard.release_all()
        time.sleep(self.REPORT_INTERVAL_SEC)
