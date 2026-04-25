import unittest
from types import SimpleNamespace

from bluetooth_2_usb.device_classification import describe_capabilities, ecodes


class _FakeDevice:
    def __init__(self, capabilities, props=()) -> None:
        self._capabilities = capabilities
        self._props = set(props)
        self.absinfo_calls = []
        self.capabilities_kwargs = []

    def capabilities(self, **kwargs):
        self.capabilities_kwargs.append(kwargs)
        return self._capabilities

    def input_props(self):
        return self._props

    def absinfo(self, code):
        self.absinfo_calls.append(code)
        return SimpleNamespace(min=0, max=1024, fuzz=1, flat=2, resolution=3)


class DeviceClassificationTest(unittest.TestCase):
    def test_abs_capabilities_are_requested_without_absinfo_tuples(self) -> None:
        device = _FakeDevice(
            {
                ecodes.EV_ABS: [ecodes.ABS_X, ecodes.ABS_Y],
                ecodes.EV_KEY: [ecodes.BTN_SOUTH],
            }
        )

        capabilities = describe_capabilities(device)

        self.assertEqual(
            device.capabilities_kwargs, [{"verbose": False, "absinfo": False}]
        )
        self.assertEqual(device.absinfo_calls, [ecodes.ABS_X, ecodes.ABS_Y])
        self.assertEqual([axis.code for axis in capabilities.abs_axes], [0, 1])

    def test_button_only_devices_are_not_classified_as_keyboards(self) -> None:
        device = _FakeDevice(
            {
                ecodes.EV_ABS: [ecodes.ABS_X, ecodes.ABS_Y],
                ecodes.EV_KEY: [ecodes.BTN_SOUTH, ecodes.BTN_EAST],
            }
        )

        capabilities = describe_capabilities(device)

        self.assertIn("gamepad", capabilities.relay_classes)
        self.assertNotIn("keyboard", capabilities.relay_classes)

    def test_real_key_codes_are_classified_as_keyboard(self) -> None:
        device = _FakeDevice({ecodes.EV_KEY: [ecodes.KEY_A]})

        capabilities = describe_capabilities(device)

        self.assertIn("keyboard", capabilities.relay_classes)


if __name__ == "__main__":
    unittest.main()
