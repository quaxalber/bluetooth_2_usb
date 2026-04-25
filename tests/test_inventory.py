import unittest
from unittest.mock import patch

from bluetooth_2_usb import inventory
from bluetooth_2_usb.device_classification import DeviceCapabilities


class _FakeDevice:
    path = "/dev/input/event-abs"
    name = "Generic ABS"
    phys = "phys"
    uniq = ""

    def __init__(self) -> None:
        self.closed = False

    def capabilities(self, verbose=False):
        del verbose
        return {inventory.native_ecodes.EV_ABS: [0]}

    def close(self) -> None:
        self.closed = True


class InventoryTest(unittest.TestCase):
    def test_classless_abs_devices_are_not_relay_candidates(self) -> None:
        device = _FakeDevice()
        capabilities = DeviceCapabilities(
            event_types=("EV_ABS",),
            properties=(),
            abs_axes=(),
            relay_classes=(),
        )

        with patch(
            "bluetooth_2_usb.inventory.list_input_devices", return_value=[device]
        ):
            with patch(
                "bluetooth_2_usb.inventory.describe_capabilities",
                return_value=capabilities,
            ):
                devices = inventory.describe_input_devices()

        self.assertFalse(devices[0].relay_candidate)
        self.assertEqual(devices[0].exclusion_reason, "missing supported relay classes")
        self.assertTrue(device.closed)


if __name__ == "__main__":
    unittest.main()
