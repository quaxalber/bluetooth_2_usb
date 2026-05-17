from __future__ import annotations

from dataclasses import dataclass, field

from ..evdev import ecodes, event_code, event_keystate, event_scancode, event_value
from ..inputs.profile import AbsAxisInfo, InputDeviceProfile
from .constants import TOUCH_DIGITIZER_CONTACT_COUNT

HID_ABS_MAX = 32767
HID_PRESSURE_MAX = 4095
HID_DISTANCE_MAX = 1023
HID_TILT_MIN = -127
HID_TILT_MAX = 127

TABLET_PAD_BUTTONS = {
    ecodes.BTN_LEFT,
    ecodes.BTN_RIGHT,
    ecodes.BTN_FORWARD,
    ecodes.BTN_BACK,
    *range(ecodes.BTN_0, ecodes.BTN_0 + 16),
}


def scale_axis(value: int, axis: AbsAxisInfo | None, target_min: int = 0, target_max: int = HID_ABS_MAX) -> int:
    if axis is None or axis.maximum <= axis.minimum:
        return target_min
    scaled = round((value - axis.minimum) * (target_max - target_min) / (axis.maximum - axis.minimum)) + target_min
    return clamp(scaled, target_min, target_max)


def clamp(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))


@dataclass(slots=True)
class TouchContact:
    slot: int
    tracking_id: int | None = None
    report_id: int | None = None
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    pressure: int = 0
    active: bool = False
    release_pending: bool = False


@dataclass(frozen=True, slots=True)
class TouchReportContact:
    report_id: int
    active: bool
    x: int
    y: int
    width: int
    height: int
    pressure: int


@dataclass(frozen=True, slots=True)
class TouchReport:
    contacts: tuple[TouchReportContact, ...]
    button: bool
    scan_time: int


class TouchAccumulator:
    def __init__(self, profile: InputDeviceProfile, max_report_contacts: int = TOUCH_DIGITIZER_CONTACT_COUNT) -> None:
        self._profile = profile
        self._max_report_contacts = max_report_contacts
        self._slot = 0
        self._contacts: dict[int, TouchContact] = {}
        self._next_report_id = 1
        self._button = False
        self._dirty = False
        self._scan_time = 0

    def discard(self) -> None:
        self._dirty = False

    def release_all(self) -> TouchReport | None:
        contacts = [
            self._report_contact(contact, active=False)
            for contact in self._contacts.values()
            if contact.report_id is not None and contact.active
        ]
        self._contacts.clear()
        self._button = False
        self._dirty = False
        if not contacts:
            return None
        return self._report(tuple(contacts))

    def add_event(self, event: object) -> None:
        code = event_code(event)
        value = event_value(event)
        if code == ecodes.ABS_MT_SLOT:
            self._slot = value
            self._contacts.setdefault(value, TouchContact(slot=value))
            return

        contact = self._contacts.setdefault(self._slot, TouchContact(slot=self._slot))
        if code == ecodes.ABS_MT_TRACKING_ID:
            if value < 0:
                if contact.active:
                    contact.active = False
                    contact.release_pending = contact.report_id is not None
                    self._dirty = True
            else:
                contact.tracking_id = value
                contact.active = True
                contact.release_pending = False
                self._assign_report_id(contact)
                self._dirty = True
            return
        if code in (ecodes.ABS_MT_POSITION_X, ecodes.ABS_X):
            contact.x = scale_axis(value, self._profile.axis(code) or self._profile.axis(ecodes.ABS_MT_POSITION_X))
            self._dirty = True
        elif code in (ecodes.ABS_MT_POSITION_Y, ecodes.ABS_Y):
            contact.y = scale_axis(value, self._profile.axis(code) or self._profile.axis(ecodes.ABS_MT_POSITION_Y))
            self._dirty = True
        elif code == ecodes.ABS_MT_TOUCH_MAJOR:
            contact.width = scale_axis(value, self._profile.axis(code), 0, 255)
            self._dirty = True
        elif code == ecodes.ABS_MT_TOUCH_MINOR:
            contact.height = scale_axis(value, self._profile.axis(code), 0, 255)
            self._dirty = True
        elif code in (ecodes.ABS_MT_PRESSURE, ecodes.ABS_PRESSURE):
            contact.pressure = scale_axis(value, self._profile.axis(code), 0, 255)
            self._dirty = True

    def add_key(self, event: object) -> None:
        scancode = event_scancode(event)
        keystate = event_keystate(event)
        if scancode == ecodes.BTN_LEFT:
            self._button = keystate != 0
            self._dirty = True
            return
        if scancode != ecodes.BTN_TOUCH:
            return
        if keystate:
            contact = self._contacts.setdefault(self._slot, TouchContact(slot=self._slot))
            contact.active = True
            contact.release_pending = False
            self._assign_report_id(contact)
            self._dirty = True
            return
        for contact in self._contacts.values():
            if contact.active:
                contact.active = False
                contact.release_pending = contact.report_id is not None
                self._dirty = True

    def flush(self) -> TouchReport | None:
        if not self._dirty:
            return None
        report_contacts: list[TouchReportContact] = []
        for contact in sorted(self._contacts.values(), key=lambda item: item.report_id or 9999):
            if contact.report_id is None:
                continue
            if contact.release_pending:
                report_contacts.append(self._report_contact(contact, active=False))
            elif contact.active:
                report_contacts.append(self._report_contact(contact, active=True))
        for slot, contact in list(self._contacts.items()):
            if contact.release_pending:
                del self._contacts[slot]
        self._dirty = False
        return self._report(tuple(report_contacts[: self._max_report_contacts]))

    def _assign_report_id(self, contact: TouchContact) -> None:
        if contact.report_id is not None:
            return
        used = {item.report_id for item in self._contacts.values() if item.report_id is not None}
        for candidate in range(1, self._max_report_contacts + 1):
            if candidate not in used:
                contact.report_id = candidate
                return

    def _report_contact(self, contact: TouchContact, *, active: bool) -> TouchReportContact:
        return TouchReportContact(
            report_id=contact.report_id or 0,
            active=active,
            x=contact.x,
            y=contact.y,
            width=contact.width if active else 0,
            height=contact.height if active else 0,
            pressure=contact.pressure if active else 0,
        )

    def _report(self, contacts: tuple[TouchReportContact, ...]) -> TouchReport:
        self._scan_time = (self._scan_time + 1) & 0xFFFF
        return TouchReport(contacts=contacts, button=self._button, scan_time=self._scan_time)


@dataclass(frozen=True, slots=True)
class PenReport:
    in_range: bool
    tip: bool
    eraser: bool
    barrel: bool
    barrel2: bool
    x: int
    y: int
    pressure: int
    distance: int
    tilt_x: int
    tilt_y: int
    serial: int


class PenAccumulator:
    def __init__(self, profile: InputDeviceProfile) -> None:
        self._profile = profile
        self._in_range = False
        self._tip = False
        self._eraser = False
        self._barrel = False
        self._barrel2 = False
        self._x = 0
        self._y = 0
        self._pressure = 0
        self._distance = 0
        self._tilt_x = 0
        self._tilt_y = 0
        self._serial = 0
        self._dirty = False

    def discard(self) -> None:
        self._dirty = False

    def release_all(self) -> PenReport | None:
        if not any((self._in_range, self._tip, self._eraser, self._barrel, self._barrel2)):
            return None
        self._in_range = False
        self._tip = False
        self._eraser = False
        self._barrel = False
        self._barrel2 = False
        self._pressure = 0
        self._dirty = False
        return self._report()

    def add_event(self, event: object) -> None:
        code = event_code(event)
        value = event_value(event)
        if code == ecodes.ABS_X:
            self._x = scale_axis(value, self._profile.axis(code))
        elif code == ecodes.ABS_Y:
            self._y = scale_axis(value, self._profile.axis(code))
        elif code == ecodes.ABS_PRESSURE:
            self._pressure = scale_axis(value, self._profile.axis(code), 0, HID_PRESSURE_MAX)
        elif code == ecodes.ABS_DISTANCE:
            self._distance = scale_axis(value, self._profile.axis(code), 0, HID_DISTANCE_MAX)
        elif code == ecodes.ABS_TILT_X:
            self._tilt_x = scale_axis(value, self._profile.axis(code), HID_TILT_MIN, HID_TILT_MAX)
        elif code == ecodes.ABS_TILT_Y:
            self._tilt_y = scale_axis(value, self._profile.axis(code), HID_TILT_MIN, HID_TILT_MAX)
        else:
            return
        self._dirty = True

    def add_key(self, event: object) -> None:
        scancode = event_scancode(event)
        pressed = event_keystate(event) != 0
        if scancode in (ecodes.BTN_DIGI, ecodes.BTN_TOOL_PEN):
            self._in_range = pressed
        elif scancode == ecodes.BTN_TOOL_RUBBER:
            self._eraser = pressed
            self._in_range = pressed or self._in_range
        elif scancode == ecodes.BTN_TOUCH:
            self._tip = pressed
        elif scancode == ecodes.BTN_STYLUS:
            self._barrel = pressed
        elif scancode == ecodes.BTN_STYLUS2:
            self._barrel2 = pressed
        else:
            return
        self._dirty = True

    def add_misc(self, event: object) -> None:
        if event_code(event) != ecodes.MSC_SERIAL:
            return
        self._serial = event_value(event) & 0xFFFFFFFF
        self._dirty = True

    def flush(self) -> PenReport | None:
        if not self._dirty:
            return None
        self._dirty = False
        return self._report()

    def _report(self) -> PenReport:
        return PenReport(
            in_range=self._in_range,
            tip=self._tip,
            eraser=self._eraser,
            barrel=self._barrel,
            barrel2=self._barrel2,
            x=self._x,
            y=self._y,
            pressure=self._pressure,
            distance=self._distance,
            tilt_x=self._tilt_x,
            tilt_y=self._tilt_y,
            serial=self._serial,
        )


@dataclass(frozen=True, slots=True)
class PadReport:
    buttons: int
    wheel: int = 0


@dataclass(slots=True)
class PadAccumulator:
    _buttons: int = 0
    _wheel: int = 0
    _dirty: bool = False
    _button_map: dict[int, int] = field(
        default_factory=lambda: {
            ecodes.BTN_LEFT: 0,
            ecodes.BTN_RIGHT: 1,
            ecodes.BTN_FORWARD: 2,
            ecodes.BTN_BACK: 3,
            **{ecodes.BTN_0 + index: index for index in range(16)},
        }
    )

    def discard(self) -> None:
        self._dirty = False

    def release_all(self) -> PadReport | None:
        if self._buttons == 0:
            return None
        self._buttons = 0
        self._dirty = False
        return PadReport(buttons=0, wheel=0)

    def add_key(self, event: object) -> None:
        scancode = event_scancode(event)
        if scancode not in self._button_map:
            return
        pressed = event_keystate(event) != 0
        bit = 1 << self._button_map[scancode]
        self._buttons = self._buttons | bit if pressed else self._buttons & ~bit
        self._dirty = True

    def add_event(self, event: object) -> None:
        if event_code(event) == ecodes.ABS_WHEEL:
            self._wheel = clamp(event_value(event), -127, 127)
            self._dirty = True

    def flush(self) -> PadReport | None:
        if not self._dirty:
            return None
        self._dirty = False
        return PadReport(buttons=self._buttons, wheel=self._wheel)
