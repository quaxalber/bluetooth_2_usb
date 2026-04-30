import unittest

from bluetooth_2_usb.runtime_events import (
    DeviceAdded,
    DeviceRemoved,
    ShutdownRequested,
    UdcStateChanged,
)


class RuntimeEventTest(unittest.TestCase):
    def test_runtime_events_are_value_objects(self) -> None:
        self.assertEqual(DeviceAdded("/dev/input/event1"), DeviceAdded("/dev/input/event1"))
        self.assertEqual(DeviceRemoved("/dev/input/event2"), DeviceRemoved("/dev/input/event2"))
        self.assertEqual(UdcStateChanged("configured"), UdcStateChanged("configured"))
        self.assertEqual(ShutdownRequested("signal"), ShutdownRequested("signal"))
