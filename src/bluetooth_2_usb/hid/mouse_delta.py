from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ..evdev import ecodes, get_mouse_movement
from ..evdev.types import RelEvent
from ..logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MouseDelta:
    x: int
    y: int
    wheel: int
    pan: int

    def __iter__(self) -> Iterator[int]:
        yield self.x
        yield self.y
        yield self.wheel
        yield self.pan


class MouseDeltaAccumulator:
    def __init__(self) -> None:
        self._x = 0
        self._y = 0
        self._wheel_low_res = 0.0
        self._wheel_hi_res = 0.0
        self._wheel_hi_res_seen = False
        self._wheel_remainder = 0.0
        self._pan_low_res = 0.0
        self._pan_hi_res = 0.0
        self._pan_hi_res_seen = False
        self._pan_remainder = 0.0

    def add_event(self, event: RelEvent) -> None:
        x, y, wheel, pan = get_mouse_movement(event)
        logger.debug(
            "Mouse REL input: code=%s value=%s -> x=%s y=%s wheel=%s pan=%s",
            event.event.code,
            event.event.value,
            x,
            y,
            wheel,
            pan,
        )
        self._x += x
        self._y += y
        if event.event.code == ecodes.REL_WHEEL_HI_RES:
            self._wheel_hi_res += wheel
            self._wheel_hi_res_seen = True
        elif event.event.code == ecodes.REL_WHEEL:
            self._wheel_low_res += wheel
        if event.event.code == ecodes.REL_HWHEEL_HI_RES:
            self._pan_hi_res += pan
            self._pan_hi_res_seen = True
        elif event.event.code == ecodes.REL_HWHEEL:
            self._pan_low_res += pan

    def flush(self) -> MouseDelta | None:
        x = self._x
        y = self._y
        pending_wheel = self._wheel_hi_res if self._wheel_hi_res_seen else self._wheel_low_res
        wheel_total = self._wheel_remainder + pending_wheel
        wheel = int(wheel_total)
        self._wheel_remainder = wheel_total - wheel
        pending_pan = self._pan_hi_res if self._pan_hi_res_seen else self._pan_low_res
        pan_total = self._pan_remainder + pending_pan
        pan = int(pan_total)
        self._pan_remainder = pan_total - pan
        self._discard_pending_frame()
        if x == 0 and y == 0 and wheel == 0 and pan == 0:
            return None
        return MouseDelta(x=x, y=y, wheel=wheel, pan=pan)

    def discard(self) -> None:
        self._discard_pending_frame()
        self._wheel_remainder = 0.0
        self._pan_remainder = 0.0

    def _discard_pending_frame(self) -> None:
        self._x = 0
        self._y = 0
        self._wheel_low_res = 0.0
        self._wheel_hi_res = 0.0
        self._wheel_hi_res_seen = False
        self._pan_low_res = 0.0
        self._pan_hi_res = 0.0
        self._pan_hi_res_seen = False
