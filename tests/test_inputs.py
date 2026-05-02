import unittest
from types import SimpleNamespace

from bluetooth_2_usb.inputs.identifier import DeviceIdentifier, DeviceIdentifierType


class DeviceIdentifierTest(unittest.TestCase):
    def test_blank_identifier_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            DeviceIdentifier(" \t ")

    def test_mac_identifier_matches_hyphenated_device_uniq(self) -> None:
        identifier = DeviceIdentifier("aa:bb:cc:dd:ee:ff")
        device = SimpleNamespace(path="/dev/input/event7", uniq="AA-BB-CC-DD-EE-FF", name="keyboard")

        self.assertIs(identifier.type, DeviceIdentifierType.MAC)
        self.assertTrue(identifier.matches(device))

    def test_event_like_name_without_numeric_suffix_matches_by_name(self) -> None:
        identifier = DeviceIdentifier("/dev/input/eventual")
        device = SimpleNamespace(path="/dev/input/event7", uniq="", name="prefix /dev/input/eventual suffix")

        self.assertIs(identifier.type, DeviceIdentifierType.NAME)
        self.assertTrue(identifier.matches(device))

    def test_event_path_identifier_matches_by_path(self) -> None:
        identifier = DeviceIdentifier("/dev/input/event7")
        device = SimpleNamespace(path="/dev/input/event7", uniq="", name="keyboard")

        self.assertIs(identifier.type, DeviceIdentifierType.PATH)
        self.assertTrue(identifier.matches(device))
