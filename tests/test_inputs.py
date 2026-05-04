import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.evdev import ecodes
from bluetooth_2_usb.inputs.identifier import DeviceIdentifier, DeviceIdentifierType
from bluetooth_2_usb.inputs.inventory import auto_discover_exclusion_reason, describe_input_devices, inventory_to_text


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


class _FakeInputDevice:
    def __init__(
        self, *, path: str, name: str, capabilities: dict[int, list[int]] | OSError, phys: str = "", uniq: str = ""
    ) -> None:
        self.path = path
        self.name = name
        self.phys = phys
        self.uniq = uniq
        self._capabilities = capabilities
        self.closed = False

    def capabilities(self, *, verbose: bool):
        self.assert_verbose_false(verbose)
        if isinstance(self._capabilities, OSError):
            raise self._capabilities
        return self._capabilities

    def assert_verbose_false(self, verbose: bool) -> None:
        if verbose:
            raise AssertionError("inventory should request numeric evdev capabilities")

    def close(self) -> None:
        self.closed = True


class InputInventoryTest(unittest.TestCase):
    def test_auto_discover_excludes_default_noise_prefixes_case_insensitively(self) -> None:
        device = _FakeInputDevice(path="/dev/input/event0", name="GPIO Keys", capabilities={ecodes.EV_KEY: []})

        self.assertEqual(auto_discover_exclusion_reason(device), "name prefix gpio")

    def test_describe_input_devices_reports_mixed_candidates_and_closes_devices(self) -> None:
        keyboard = _FakeInputDevice(
            path="/dev/input/event1", name="Keyboard", phys="usb-1", uniq="AA-BB", capabilities={ecodes.EV_KEY: []}
        )
        mouse = _FakeInputDevice(path="/dev/input/event2", name="Mouse", capabilities={ecodes.EV_REL: []})
        broken = _FakeInputDevice(path="/dev/input/event3", name="Broken", capabilities=OSError("permission denied"))

        with patch("bluetooth_2_usb.inputs.inventory.list_input_devices", return_value=[keyboard, mouse, broken]):
            devices = describe_input_devices()

        self.assertEqual(
            [device.path for device in devices], ["/dev/input/event1", "/dev/input/event2", "/dev/input/event3"]
        )
        self.assertEqual([device.capabilities for device in devices], [["EV_KEY"], ["EV_REL"], []])
        self.assertEqual([device.relay_candidate for device in devices], [True, True, False])
        self.assertEqual(devices[0].uniq, "AA-BB")
        self.assertIn("permission denied", devices[2].exclusion_reason or "")
        self.assertTrue(all(device.closed for device in (keyboard, mouse, broken)))

    def test_inventory_text_marks_relay_and_skipped_devices(self) -> None:
        with patch(
            "bluetooth_2_usb.inputs.inventory.list_input_devices",
            return_value=[
                _FakeInputDevice(path="/dev/input/event1", name="Keyboard", capabilities={ecodes.EV_KEY: []}),
                _FakeInputDevice(path="/dev/input/event2", name="vc4 HDMI", capabilities={ecodes.EV_KEY: []}),
            ],
        ):
            text = inventory_to_text(describe_input_devices())

        self.assertIn("relay", text)
        self.assertIn("skip", text)
        self.assertIn("name prefix vc4", text)
