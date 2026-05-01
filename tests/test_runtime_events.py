import unittest

from bluetooth_2_usb.runtime_events import (
    DeviceAdded,
    DeviceRemoved,
    ShutdownRequested,
    UdcState,
    UdcStateChanged,
)


class RuntimeEventTest(unittest.TestCase):
    def test_runtime_events_are_value_objects(self) -> None:
        self.assertEqual(DeviceAdded("/dev/input/event1"), DeviceAdded("/dev/input/event1"))
        self.assertEqual(DeviceRemoved("/dev/input/event2"), DeviceRemoved("/dev/input/event2"))
        self.assertEqual(UdcStateChanged("configured"), UdcStateChanged("configured"))
        self.assertEqual(ShutdownRequested("signal"), ShutdownRequested("signal"))

    def test_udc_state_changed_normalizes_raw_state(self) -> None:
        self.assertIs(UdcStateChanged("not attached").state, UdcState.NOT_ATTACHED)
        self.assertIs(UdcStateChanged("configured\n").state, UdcState.CONFIGURED)
        self.assertIs(UdcStateChanged("unexpected").state, UdcState.UNKNOWN)
