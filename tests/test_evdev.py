import unittest
from types import SimpleNamespace

from bluetooth_2_usb.evdev import ecodes, evdev_to_usb_hid
from bluetooth_2_usb.hid.mouse import ExtendedMouse


class ExtendedMouseButtonMappingTest(unittest.TestCase):
    def test_evdev_uses_extended_mouse_button_bits(self) -> None:
        expected_buttons = {
            ecodes.BTN_LEFT: ExtendedMouse.LEFT,
            ecodes.BTN_RIGHT: ExtendedMouse.RIGHT,
            ecodes.BTN_MIDDLE: ExtendedMouse.MIDDLE,
            ecodes.BTN_SIDE: ExtendedMouse.SIDE,
            ecodes.BTN_EXTRA: ExtendedMouse.EXTRA,
            ecodes.BTN_FORWARD: ExtendedMouse.FORWARD,
            ecodes.BTN_BACK: ExtendedMouse.BACK,
            ecodes.BTN_TASK: ExtendedMouse.TASK,
        }

        for scancode, button in expected_buttons.items():
            with self.subTest(scancode=scancode):
                hid_code, hid_name = evdev_to_usb_hid(SimpleNamespace(scancode=scancode, keystate=1))

                self.assertEqual(hid_code, button)
                self.assertIsNotNone(hid_name)
