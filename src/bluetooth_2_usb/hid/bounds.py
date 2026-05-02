from __future__ import annotations

HID_I8_MIN = -127
HID_I8_MAX = 127
HID_I16_MIN = -32767
HID_I16_MAX = 32767


def clamp_hid_i8(value: int) -> int:
    return min(HID_I8_MAX, max(HID_I8_MIN, value))


def clamp_hid_i16(value: int) -> int:
    return min(HID_I16_MAX, max(HID_I16_MIN, value))
