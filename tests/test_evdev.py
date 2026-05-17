import unittest
from types import SimpleNamespace

from bluetooth_2_usb.evdev import (
    ecodes,
    evdev_to_usb_hid,
    event_code,
    event_keystate,
    event_scancode,
    event_type,
    event_value,
)
from bluetooth_2_usb.hid.buttons import MouseButtons


class MouseButtonMappingTest(unittest.TestCase):
    def test_evdev_uses_extended_mouse_button_bits(self) -> None:
        expected_buttons = {
            ecodes.BTN_LEFT: MouseButtons.LEFT,
            ecodes.BTN_RIGHT: MouseButtons.RIGHT,
            ecodes.BTN_MIDDLE: MouseButtons.MIDDLE,
            ecodes.BTN_SIDE: MouseButtons.SIDE,
            ecodes.BTN_EXTRA: MouseButtons.EXTRA,
            ecodes.BTN_FORWARD: MouseButtons.FORWARD,
            ecodes.BTN_BACK: MouseButtons.BACK,
            ecodes.BTN_TASK: MouseButtons.TASK,
        }
        expected_names = {
            ecodes.BTN_LEFT: "LEFT",
            ecodes.BTN_RIGHT: "RIGHT",
            ecodes.BTN_MIDDLE: "MIDDLE",
            ecodes.BTN_SIDE: "SIDE",
            ecodes.BTN_EXTRA: "EXTRA",
            ecodes.BTN_FORWARD: "FORWARD",
            ecodes.BTN_BACK: "BACK",
            ecodes.BTN_TASK: "TASK",
        }

        for scancode, button in expected_buttons.items():
            with self.subTest(scancode=scancode):
                hid_code, hid_name = evdev_to_usb_hid(SimpleNamespace(scancode=scancode, keystate=1))

                self.assertEqual(hid_code, button)
                self.assertEqual(hid_name, expected_names[scancode])


class EventHelperTest(unittest.TestCase):
    def test_event_helpers_read_direct_event_fields(self) -> None:
        event = SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_A, value=1)

        self.assertEqual(event_type(event), ecodes.EV_KEY)
        self.assertEqual(event_code(event), ecodes.KEY_A)
        self.assertEqual(event_value(event), 1)
        self.assertEqual(event_scancode(event), ecodes.KEY_A)
        self.assertEqual(event_keystate(event), 1)

    def test_event_helpers_read_wrapped_event_fields(self) -> None:
        event = SimpleNamespace(event=SimpleNamespace(type=ecodes.EV_ABS, code=ecodes.ABS_X, value=42))

        self.assertEqual(event_type(event), ecodes.EV_ABS)
        self.assertEqual(event_code(event), ecodes.ABS_X)
        self.assertEqual(event_value(event), 42)
        self.assertEqual(event_scancode(event), ecodes.ABS_X)
        self.assertEqual(event_keystate(event), 42)

    def test_key_helpers_prefer_categorized_key_fields(self) -> None:
        event = SimpleNamespace(scancode=ecodes.KEY_B, keystate=0, code=ecodes.KEY_A, value=1)

        self.assertEqual(event_scancode(event), ecodes.KEY_B)
        self.assertEqual(event_keystate(event), 0)
