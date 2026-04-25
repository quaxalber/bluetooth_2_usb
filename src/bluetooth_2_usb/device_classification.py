from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from evdev import ecodes
except ModuleNotFoundError:
    from .evdev import ecodes  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class AbsAxisInfo:
    code: int
    name: str
    minimum: int | None
    maximum: int | None
    fuzz: int | None
    flat: int | None
    resolution: int | None


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    event_types: tuple[str, ...]
    properties: tuple[str, ...]
    abs_axes: tuple[AbsAxisInfo, ...]
    relay_classes: tuple[str, ...]


GAMEPAD_KEYS = {
    ecodes.BTN_SOUTH,
    ecodes.BTN_EAST,
    ecodes.BTN_NORTH,
    ecodes.BTN_WEST,
    ecodes.BTN_TL,
    ecodes.BTN_TR,
    ecodes.BTN_TL2,
    ecodes.BTN_TR2,
    ecodes.BTN_SELECT,
    ecodes.BTN_START,
    ecodes.BTN_MODE,
    getattr(ecodes, "BTN_THUMBL", 0x13D),
    getattr(ecodes, "BTN_THUMBR", 0x13E),
}

GAMEPAD_ABS = {
    ecodes.ABS_X,
    ecodes.ABS_Y,
    ecodes.ABS_RX,
    ecodes.ABS_RY,
    ecodes.ABS_Z,
    ecodes.ABS_RZ,
    ecodes.ABS_GAS,
    ecodes.ABS_BRAKE,
    ecodes.ABS_HAT0X,
    ecodes.ABS_HAT0Y,
}

TOUCHPAD_KEYS = {
    ecodes.BTN_TOUCH,
    ecodes.BTN_TOOL_FINGER,
    ecodes.BTN_TOOL_DOUBLETAP,
    ecodes.BTN_TOOL_TRIPLETAP,
    ecodes.BTN_TOOL_QUADTAP,
    ecodes.BTN_TOOL_QUINTTAP,
}

TOUCHPAD_ABS = {
    ecodes.ABS_X,
    ecodes.ABS_Y,
    ecodes.ABS_MT_SLOT,
    ecodes.ABS_MT_POSITION_X,
    ecodes.ABS_MT_POSITION_Y,
    ecodes.ABS_MT_TRACKING_ID,
}

TABLET_KEYS = {
    ecodes.BTN_TOOL_PEN,
    ecodes.BTN_TOOL_RUBBER,
    ecodes.BTN_STYLUS,
    ecodes.BTN_STYLUS2,
    ecodes.BTN_STYLUS3,
}

TABLET_ABS = {
    ecodes.ABS_X,
    ecodes.ABS_Y,
    ecodes.ABS_PRESSURE,
    ecodes.ABS_DISTANCE,
    ecodes.ABS_TILT_X,
    ecodes.ABS_TILT_Y,
}


def describe_capabilities(device: Any) -> DeviceCapabilities:
    capabilities = device.capabilities(verbose=False)
    props = _device_properties(device)
    event_types = tuple(
        sorted(_event_type_name(event_type) for event_type in capabilities)
    )
    abs_axes = tuple(
        _abs_axis_info(device, code) for code in _codes(capabilities, ecodes.EV_ABS)
    )
    relay_classes = tuple(sorted(_relay_classes(capabilities, props)))
    return DeviceCapabilities(
        event_types=event_types,
        properties=tuple(sorted(_property_name(prop) for prop in props)),
        abs_axes=abs_axes,
        relay_classes=relay_classes,
    )


def _relay_classes(capabilities: dict[int, list[int]], props: set[int]) -> set[str]:
    classes: set[str] = set()
    keys = set(_codes(capabilities, ecodes.EV_KEY))
    rels = set(_codes(capabilities, ecodes.EV_REL))
    abs_axes = set(_codes(capabilities, ecodes.EV_ABS))

    if keys:
        classes.add("keyboard")
    if rels or keys.intersection(
        {ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE}
    ):
        classes.add("mouse")
    if abs_axes.intersection(GAMEPAD_ABS) and keys.intersection(GAMEPAD_KEYS):
        classes.add("gamepad")
    if _looks_like_touchpad(keys, abs_axes, props):
        classes.add("touchpad")
    if keys.intersection(TABLET_KEYS) or (
        ecodes.ABS_PRESSURE in abs_axes and abs_axes.intersection(TABLET_ABS)
    ):
        classes.add("tablet_pen")
    if ecodes.EV_FF in capabilities:
        classes.add("feedback")
    return classes


def _looks_like_touchpad(keys: set[int], abs_axes: set[int], props: set[int]) -> bool:
    has_touch = bool(keys.intersection(TOUCHPAD_KEYS))
    has_position = {
        ecodes.ABS_MT_POSITION_X,
        ecodes.ABS_MT_POSITION_Y,
    }.issubset(
        abs_axes
    ) or {ecodes.ABS_X, ecodes.ABS_Y}.issubset(abs_axes)
    has_pointer_property = bool(
        props.intersection(
            {
                ecodes.INPUT_PROP_POINTER,
                ecodes.INPUT_PROP_BUTTONPAD,
            }
        )
    )
    return has_touch and has_position and has_pointer_property


def _codes(capabilities: dict[int, list[int]], event_type: int) -> list[int]:
    return list(capabilities.get(event_type, ()))


def _device_properties(device: Any) -> set[int]:
    try:
        return set(device.input_props())
    except (AttributeError, OSError):
        return set()


def _abs_axis_info(device: Any, code: int) -> AbsAxisInfo:
    try:
        info = device.absinfo(code)
    except (AttributeError, OSError):
        info = None
    return AbsAxisInfo(
        code=code,
        name=_code_name("ABS_", code),
        minimum=getattr(info, "min", None),
        maximum=getattr(info, "max", None),
        fuzz=getattr(info, "fuzz", None),
        flat=getattr(info, "flat", None),
        resolution=getattr(info, "resolution", None),
    )


def _event_type_name(event_type: int) -> str:
    return _code_name("EV_", event_type)


def _property_name(prop: int) -> str:
    return _code_name("INPUT_PROP_", prop)


def _code_name(prefix: str, value: int) -> str:
    for name in dir(ecodes):
        if name.startswith(prefix) and getattr(ecodes, name) == value:
            return name
    return str(value)
