import unittest

from bluetooth_2_usb.evdev.ecodes import ecodes
from bluetooth_2_usb.relay.leds import KeyboardLedMirror


class _LedDevice:
    def __init__(self, path="/dev/input/event1", leds=(ecodes.LED_NUML, ecodes.LED_CAPSL, ecodes.LED_SCROLLL)):
        self.path = path
        self._leds = list(leds)
        self.calls = []

    def capabilities(self, verbose=False):
        return {ecodes.EV_LED: self._leds} if self._leds else {}

    def set_led(self, code, value):
        self.calls.append((code, value))


class KeyboardLedMirrorTest(unittest.TestCase):
    def test_report_is_applied_to_registered_keyboard(self):
        mirror = KeyboardLedMirror(None)
        device = _LedDevice()
        mirror.register(device)

        mirror.handle_report(bytes([0x02]))

        self.assertEqual(device.calls, [(ecodes.LED_NUML, 0), (ecodes.LED_CAPSL, 1), (ecodes.LED_SCROLLL, 0)])

    def test_unchanged_report_is_ignored_and_new_device_gets_current_state(self):
        mirror = KeyboardLedMirror(None)
        mirror.handle_report(bytes([0x01]))
        mirror.handle_report(bytes([0x01]))

        device = _LedDevice(leds=(ecodes.LED_NUML,))
        mirror.register(device)

        self.assertEqual(device.calls, [(ecodes.LED_NUML, 1)])

    def test_devices_without_leds_and_unregistered_devices_are_skipped(self):
        mirror = KeyboardLedMirror(None)
        mouse = _LedDevice(path="/dev/input/event2", leds=())
        keyboard = _LedDevice()
        mirror.register(mouse)
        mirror.register(keyboard)
        mirror.unregister(keyboard.path)

        mirror.handle_report(bytes([0x07]))

        self.assertEqual(mouse.calls, [])
        self.assertEqual(keyboard.calls, [])


if __name__ == "__main__":
    unittest.main()
