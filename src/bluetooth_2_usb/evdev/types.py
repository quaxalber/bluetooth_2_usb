from __future__ import annotations

from typing import Any

try:
    from evdev import InputDevice, InputEvent, KeyEvent, RelEvent, categorize
except ModuleNotFoundError:
    InputEvent = Any  # type: ignore[assignment]

    class InputDevice:
        def __init__(self, path: str = "", name: str = "", phys: str = "", uniq: str = "") -> None:
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


def _wrapped_event(event: object) -> object:
    return getattr(event, "event", event)


def event_type(event: object, default: int | None = None) -> int | None:
    value = getattr(event, "type", getattr(_wrapped_event(event), "type", default))
    return default if value is None else int(value)


def event_code(event: object, default: int = -1) -> int:
    return int(getattr(event, "code", getattr(_wrapped_event(event), "code", default)))


def event_value(event: object, default: int = 0) -> int:
    return int(getattr(event, "value", getattr(_wrapped_event(event), "value", default)))


def event_scancode(event: object, default: int = -1) -> int:
    return int(getattr(event, "scancode", getattr(event, "code", getattr(_wrapped_event(event), "code", default))))


def event_keystate(event: object, default: int = 0) -> int:
    return int(getattr(event, "keystate", getattr(event, "value", getattr(_wrapped_event(event), "value", default))))
