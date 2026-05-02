import unittest
from types import SimpleNamespace

from bluetooth_2_usb.evdev import ecodes, evdev_to_usb_hid
from bluetooth_2_usb.hid.buttons import MouseButtons


class ExtendedMouseButtonMappingTest(unittest.TestCase):
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

        for scancode, button in expected_buttons.items():
            with self.subTest(scancode=scancode):
                hid_code, hid_name = evdev_to_usb_hid(SimpleNamespace(scancode=scancode, keystate=1))

                self.assertEqual(hid_code, button)
                self.assertIsNotNone(hid_name)
