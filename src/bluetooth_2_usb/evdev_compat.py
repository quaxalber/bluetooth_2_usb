from __future__ import annotations

from typing import Any

try:
    from evdev import InputDevice, InputEvent, KeyEvent, RelEvent, categorize
except ModuleNotFoundError:
    InputEvent = Any  # type: ignore[assignment]

    class InputDevice:
        def __init__(
            self, path: str = "", name: str = "", phys: str = "", uniq: str = ""
        ) -> None:
            self.path = path
            self.name = name
            self.phys = phys
            self.uniq = uniq

        async def async_read_loop(self):
            for event in ():
                yield event
            return

        def close(self) -> None:
            return None

    class KeyEvent:
        key_down = 1
        key_hold = 2
        key_up = 0

    class RelEvent:
        pass

    def categorize(event):
        return event
