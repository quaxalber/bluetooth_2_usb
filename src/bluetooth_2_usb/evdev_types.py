from __future__ import annotations

from typing import Any

try:
    from evdev import InputDevice, InputEvent, KeyEvent, RelEvent, categorize
except ModuleNotFoundError:
    InputEvent = Any  # type: ignore[assignment]

    class InputDevice:
        """Fallback stand-in for evdev.InputDevice when evdev is unavailable."""

        def __init__(self, path: str = "", name: str = "", phys: str = "", uniq: str = "") -> None:
            """Initialize the evdev fallback input-device placeholder.

            :return: None.
            """
            self.path = path
            self.name = name
            self.phys = phys
            self.uniq = uniq

        async def async_read_loop(self):
            """Yield no events from the evdev fallback input-device placeholder.

            :return: The requested value or status result.
            """
            for event in ():
                yield event
            return

        def close(self) -> None:
            """Close the evdev fallback input-device placeholder.

            :return: None.
            """
            return None

    class KeyEvent:
        """Fallback stand-in for evdev KeyEvent constants."""

        key_down = 1
        key_hold = 2
        key_up = 0

    class RelEvent:
        """Fallback stand-in for evdev relative motion events."""

        pass

    def categorize(event):
        """Return the fallback event unchanged when evdev is unavailable.

        :return: The requested value or status result.
        """
        return event
