"""Shared USB HID-domain constants.

USB gadget identity/configfs policy lives in ``bluetooth_2_usb.gadgets``.
Platform API values, such as Win32 Raw Input constants, stay with their
platform-specific caller. Linux input event values come from ``evdev.ecodes``.
"""

HID_PAGE_GENERIC_DESKTOP = 0x01
"""HID Usage Page: Generic Desktop Controls."""

HID_PAGE_CONSUMER = 0x0C
"""HID Usage Page: Consumer."""

HID_USAGE_POINTER = 0x01
"""Generic Desktop usage: Pointer."""

HID_USAGE_MOUSE = 0x02
"""Generic Desktop usage: Mouse."""

HID_USAGE_KEYBOARD = 0x06
"""Generic Desktop usage: Keyboard."""

HID_USAGE_CONSUMER_CONTROL = 0x01
"""Consumer Page usage: Consumer Control."""

KEYBOARD_IN_REPORT_LENGTH = 8
"""Boot keyboard input report size in bytes."""

KEYBOARD_OUT_REPORT_LENGTH = 1
"""Boot keyboard LED output report size in bytes."""

MOUSE_IN_REPORT_LENGTH = 7
"""Mouse input report size in bytes: buttons, X/Y, wheel, and horizontal pan."""

MOUSE_CONFIGFS_REPORT_LENGTH = 8
"""Configfs mouse report_length used to force short interrupt-IN packets."""

CONSUMER_IN_REPORT_LENGTH = 2
"""Consumer-control input report size in bytes."""

CONSUMER_OUT_REPORT_LENGTH = 0
"""Consumer-control output report size in bytes."""

MOUSE_BUTTON_REPORT_INDEX = 0
"""Mouse report byte index containing the button bitmask."""

MOUSE_X_REPORT_SLICE = slice(1, 3)
"""Mouse report byte slice containing signed 16-bit relative X movement."""

MOUSE_Y_REPORT_SLICE = slice(3, 5)
"""Mouse report byte slice containing signed 16-bit relative Y movement."""

MOUSE_WHEEL_REPORT_SLICE = slice(5, 6)
"""Mouse report byte slice containing signed 8-bit vertical wheel movement."""

MOUSE_PAN_REPORT_SLICE = slice(6, 7)
"""Mouse report byte slice containing signed 8-bit horizontal pan movement."""

MOUSE_MOVEMENT_REPORT_SLICE = slice(1, 7)
"""Mouse report byte slice containing all movement fields."""

MOUSE_MOVEMENT_REPORT_LENGTH = 6
"""Mouse movement field size in bytes."""

HI_RES_WHEEL_UNITS_PER_DETENT = 120
"""Linux high-resolution wheel event units per wheel detent."""
