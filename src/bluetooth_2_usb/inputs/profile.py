from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..evdev import ecodes
from ..evdev.types import InputDevice


class InputDeviceKind(StrEnum):
    KEYBOARD_MOUSE = "keyboard_mouse"
    TOUCHPAD = "touchpad"
    TABLET_TOUCH = "tablet_touch"
    TABLET_PEN = "tablet_pen"
    TABLET_PAD = "tablet_pad"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class AbsAxisInfo:
    code: int
    minimum: int
    maximum: int
    fuzz: int = 0
    flat: int = 0
    resolution: int = 0


@dataclass(frozen=True, slots=True)
class InputDeviceProfile:
    path: str = ""
    name: str = ""
    kind: InputDeviceKind = InputDeviceKind.UNSUPPORTED
    vendor_id: int | None = None
    product_id: int | None = None
    abs_axes: Mapping[int, AbsAxisInfo] | None = None
    key_codes: frozenset[int] = frozenset()
    input_props: frozenset[int] = frozenset()
    max_contacts: int | None = None

    def axis(self, code: int) -> AbsAxisInfo | None:
        if self.abs_axes is None:
            return None
        return self.abs_axes.get(code)


DEFAULT_PROFILE = InputDeviceProfile(kind=InputDeviceKind.KEYBOARD_MOUSE)


def input_device_profile(device: InputDevice | Any) -> InputDeviceProfile:
    capabilities = _capabilities(device)
    abs_axes = _abs_axes(device, capabilities.get(ecodes.EV_ABS, frozenset()))
    key_codes = capabilities.get(ecodes.EV_KEY, frozenset())
    rel_codes = capabilities.get(ecodes.EV_REL, frozenset())
    input_props = _input_props(device)
    name = str(getattr(device, "name", "") or "")
    kind = _classify(name=name, abs_axes=abs_axes, key_codes=key_codes, rel_codes=rel_codes, input_props=input_props)
    info = getattr(device, "info", None)
    return InputDeviceProfile(
        path=str(getattr(device, "path", "") or ""),
        name=name,
        kind=kind,
        vendor_id=getattr(info, "vendor", None),
        product_id=getattr(info, "product", None),
        abs_axes=abs_axes,
        key_codes=frozenset(key_codes),
        input_props=frozenset(input_props),
        max_contacts=_max_contacts(abs_axes),
    )


def _classify(
    *,
    name: str,
    abs_axes: Mapping[int, AbsAxisInfo],
    key_codes: frozenset[int],
    rel_codes: frozenset[int],
    input_props: frozenset[int],
) -> InputDeviceKind:
    has_mt = {ecodes.ABS_MT_SLOT, ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y}.issubset(abs_axes)
    if has_mt and ecodes.BTN_TOUCH in key_codes:
        normalized_name = name.lower()
        if ecodes.INPUT_PROP_BUTTONPAD in input_props or "trackpad" in normalized_name or "clickpad" in normalized_name:
            return InputDeviceKind.TOUCHPAD
        return InputDeviceKind.TABLET_TOUCH

    has_pen_axes = {ecodes.ABS_X, ecodes.ABS_Y}.issubset(abs_axes)
    if (
        " pad" in f" {name.lower()}"
        and not {
            ecodes.BTN_TOOL_PEN,
            ecodes.BTN_TOOL_RUBBER,
            ecodes.BTN_TOOL_BRUSH,
            ecodes.BTN_TOOL_PENCIL,
            ecodes.BTN_TOOL_AIRBRUSH,
        }
        & key_codes
    ):
        return InputDeviceKind.TABLET_PAD

    pen_keys = {
        ecodes.BTN_DIGI,
        ecodes.BTN_TOOL_PEN,
        ecodes.BTN_TOOL_RUBBER,
        ecodes.BTN_TOOL_BRUSH,
        ecodes.BTN_TOOL_PENCIL,
        ecodes.BTN_TOOL_AIRBRUSH,
        ecodes.BTN_TOOL_MOUSE,
        ecodes.BTN_TOOL_LENS,
        ecodes.BTN_TOUCH,
        ecodes.BTN_STYLUS,
        ecodes.BTN_STYLUS2,
    }
    if has_pen_axes and (key_codes & pen_keys or ecodes.ABS_PRESSURE in abs_axes or ecodes.ABS_DISTANCE in abs_axes):
        return InputDeviceKind.TABLET_PEN

    pad_buttons = set(range(ecodes.BTN_0, ecodes.BTN_0 + 16))
    if key_codes & pad_buttons:
        return InputDeviceKind.TABLET_PAD

    if key_codes or rel_codes:
        return InputDeviceKind.KEYBOARD_MOUSE
    return InputDeviceKind.UNSUPPORTED


def _capabilities(device: InputDevice | Any) -> dict[int, frozenset[int]]:
    try:
        raw = device.capabilities(verbose=False)
    except (AttributeError, OSError):
        return {}
    return {int(event_type): frozenset(_capability_codes(values)) for event_type, values in raw.items()}


def _capability_codes(values: object) -> list[int]:
    codes: list[int] = []
    for value in values or ():
        if isinstance(value, tuple | list):
            codes.append(int(value[0]))
        else:
            codes.append(int(value))
    return codes


def _input_props(device: InputDevice | Any) -> frozenset[int]:
    try:
        values = device.input_props(verbose=False)
    except (AttributeError, OSError):
        return frozenset()
    return frozenset(_capability_codes(values))


def _abs_axes(device: InputDevice | Any, abs_codes: frozenset[int]) -> dict[int, AbsAxisInfo]:
    axes: dict[int, AbsAxisInfo] = {}
    for code in abs_codes:
        info = _absinfo(device, code)
        axes[code] = AbsAxisInfo(
            code=code,
            minimum=int(getattr(info, "min", getattr(info, "minimum", 0))),
            maximum=int(getattr(info, "max", getattr(info, "maximum", 0))),
            fuzz=int(getattr(info, "fuzz", 0)),
            flat=int(getattr(info, "flat", 0)),
            resolution=int(getattr(info, "resolution", 0)),
        )
    return axes


def _absinfo(device: InputDevice | Any, code: int) -> object:
    try:
        return device.absinfo(code)
    except (AttributeError, OSError):
        return _axis_from_capabilities(device, code)


def _axis_from_capabilities(device: InputDevice | Any, code: int) -> object:
    try:
        verbose = device.capabilities(verbose=True).get(ecodes.EV_ABS, ())
    except (AttributeError, OSError):
        verbose = ()
    for item in verbose:
        if not isinstance(item, tuple | list) or len(item) != 2:
            continue
        code_part, info_part = item
        if isinstance(code_part, tuple | list):
            axis_code = int(code_part[1])
        else:
            axis_code = int(code_part)
        if axis_code == code and isinstance(info_part, tuple | list) and len(info_part) >= 6:
            return _SimpleAbsInfo(info_part[1], info_part[2], info_part[3], info_part[4], info_part[5])
    return _SimpleAbsInfo(0, 0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class _SimpleAbsInfo:
    min: int
    max: int
    fuzz: int
    flat: int
    resolution: int


def _max_contacts(abs_axes: Mapping[int, AbsAxisInfo]) -> int | None:
    slot = abs_axes.get(ecodes.ABS_MT_SLOT)
    if slot is None or slot.maximum < slot.minimum:
        return None
    return slot.maximum - slot.minimum + 1
