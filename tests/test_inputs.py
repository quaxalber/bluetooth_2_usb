import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.evdev import ecodes
from bluetooth_2_usb.inputs.filter import DeviceFilter, DeviceFilterType
from bluetooth_2_usb.inputs.inventory import auto_relay_exclusion_reason, describe_input_devices, inventory_to_text
from bluetooth_2_usb.inputs.profile import InputDeviceKind, input_device_profile

INPUTS_INVENTORY = "bluetooth_2_usb.inputs.inventory"


class DeviceFilterTest(unittest.TestCase):
    def test_blank_filter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            DeviceFilter(" \t ")

    def test_filter_value_is_stripped_raw_value(self) -> None:
        device_filter = DeviceFilter(" keyboard ")

        self.assertEqual(device_filter.value, "keyboard")

    def test_mac_filter_matches_hyphenated_device_uniq(self) -> None:
        device_filter = DeviceFilter("aa:bb:cc:dd:ee:ff")
        device = SimpleNamespace(path="/dev/input/event7", uniq="AA-BB-CC-DD-EE-FF", name="keyboard")

        self.assertIs(device_filter.type, DeviceFilterType.MAC)
        self.assertTrue(device_filter.matches(device))

    def test_mac_filter_matches_hyphenated_device_phys(self) -> None:
        device_filter = DeviceFilter("aa:bb:cc:dd:ee:ff")
        device = SimpleNamespace(path="/dev/input/event7", phys="AA-BB-CC-DD-EE-FF", uniq="", name="keyboard")

        self.assertIs(device_filter.type, DeviceFilterType.MAC)
        self.assertTrue(device_filter.matches(device))

    def test_mac_filter_matches_device_phys_with_input_suffix(self) -> None:
        device_filter = DeviceFilter("aa:bb:cc:dd:ee:ff")
        device = SimpleNamespace(path="/dev/input/event7", phys="AA-BB-CC-DD-EE-FF/input0", uniq="", name="keyboard")

        self.assertIs(device_filter.type, DeviceFilterType.MAC)
        self.assertTrue(device_filter.matches(device))

    def test_text_filter_matches_by_uniq(self) -> None:
        device_filter = DeviceFilter("b2u28bc43209b9e4a56")
        device = SimpleNamespace(
            path="/dev/input/event7", phys="usb-1/input0", uniq="b2u28bc43209b9e4a56", name="keyboard"
        )

        self.assertIs(device_filter.type, DeviceFilterType.TEXT)
        self.assertTrue(device_filter.matches(device))

    def test_text_filter_matches_by_phys(self) -> None:
        device_filter = DeviceFilter("usb-1/input0")
        device = SimpleNamespace(path="/dev/input/event7", phys="usb-1/input0", uniq="", name="keyboard")

        self.assertIs(device_filter.type, DeviceFilterType.TEXT)
        self.assertTrue(device_filter.matches(device))

    def test_text_filter_matches_by_name(self) -> None:
        device_filter = DeviceFilter("keyboard")
        device = SimpleNamespace(path="/dev/input/event7", phys="", uniq="", name="Fake Keyboard")

        self.assertIs(device_filter.type, DeviceFilterType.TEXT)
        self.assertTrue(device_filter.matches(device))

    def test_event_path_filter_matches_by_path(self) -> None:
        device_filter = DeviceFilter("/dev/input/event7")
        device = SimpleNamespace(path="/dev/input/event7", uniq="", name="keyboard")

        self.assertIs(device_filter.type, DeviceFilterType.PATH)
        self.assertTrue(device_filter.matches(device))


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


class _FakeProfileInputDevice(_FakeInputDevice):
    def __init__(
        self,
        *,
        path: str = "/dev/input/event7",
        name: str,
        capabilities: dict[int, list[int]],
        props: list[int] | None = None,
        absinfo: dict[int, tuple[int, int]] | None = None,
    ) -> None:
        super().__init__(path=path, name=name, capabilities=capabilities)
        self._props = props or []
        self._absinfo = absinfo or {}
        self.info = SimpleNamespace(vendor=1, product=2)

    def input_props(self, *, verbose: bool):
        if verbose:
            raise AssertionError("profile should request numeric input properties")
        return self._props

    def absinfo(self, code: int):
        minimum, maximum = self._absinfo.get(code, (0, 0))
        return SimpleNamespace(min=minimum, max=maximum, fuzz=0, flat=0, resolution=0)


class InputInventoryTest(unittest.TestCase):
    def test_auto_relay_excludes_default_noise_prefixes_case_insensitively(self) -> None:
        device = _FakeInputDevice(path="/dev/input/event0", name="GPIO Keys", capabilities={ecodes.EV_KEY: []})

        self.assertEqual(auto_relay_exclusion_reason(device), "name prefix gpio")

    def test_auto_relay_exclusion_reason_uses_general_supported_capabilities_wording(self) -> None:
        device = _FakeInputDevice(path="/dev/input/event0", name="Sensor", capabilities={})

        self.assertEqual(auto_relay_exclusion_reason(device), "missing supported relay capabilities")

    def test_describe_input_devices_reports_mixed_candidates_and_closes_devices(self) -> None:
        keyboard = _FakeInputDevice(
            path="/dev/input/event1", name="Keyboard", phys="usb-1", uniq="AA-BB", capabilities={ecodes.EV_KEY: []}
        )
        mouse = _FakeInputDevice(path="/dev/input/event2", name="Mouse", capabilities={ecodes.EV_REL: []})
        broken = _FakeInputDevice(path="/dev/input/event3", name="Broken", capabilities=OSError("permission denied"))

        with patch(f"{INPUTS_INVENTORY}.list_input_devices", return_value=[keyboard, mouse, broken]):
            devices = describe_input_devices()

        self.assertEqual(
            [device.path for device in devices], ["/dev/input/event1", "/dev/input/event2", "/dev/input/event3"]
        )
        self.assertEqual([device.capabilities for device in devices], [["EV_KEY"], ["EV_REL"], []])
        self.assertEqual([device.relay_candidate for device in devices], [True, True, False])
        self.assertEqual(devices[0].uniq, "AA-BB")
        self.assertIn("permission denied", devices[2].exclusion_reason or "")
        self.assertTrue(all(device.closed for device in (keyboard, mouse, broken)))

    def test_describe_input_devices_reports_absolute_devices_as_relay_candidates(self) -> None:
        tablet = _FakeInputDevice(path="/dev/input/event4", name="Tablet", capabilities={ecodes.EV_ABS: []})

        with patch(f"{INPUTS_INVENTORY}.list_input_devices", return_value=[tablet]):
            devices = describe_input_devices()

        self.assertEqual(devices[0].capabilities, ["EV_ABS"])
        self.assertTrue(devices[0].relay_candidate)

    def test_profile_classifies_buttonpad_trackpad(self) -> None:
        device = _FakeProfileInputDevice(
            name="Apple Inc. Magic Trackpad",
            capabilities={
                ecodes.EV_ABS: [ecodes.ABS_MT_SLOT, ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y],
                ecodes.EV_KEY: [ecodes.BTN_TOUCH],
            },
            props=[ecodes.INPUT_PROP_BUTTONPAD],
            absinfo={ecodes.ABS_MT_SLOT: (0, 15), ecodes.ABS_MT_POSITION_X: (-3678, 3934)},
        )

        profile = input_device_profile(device)

        self.assertEqual(profile.kind, InputDeviceKind.TOUCHPAD)
        self.assertEqual(profile.max_contacts, 16)
        self.assertEqual(profile.vendor_id, 1)
        self.assertEqual(profile.product_id, 2)

    def test_profile_classifies_wacom_pen_and_pad(self) -> None:
        pen = _FakeProfileInputDevice(
            name="Wacom Intuos Pro L Pen",
            capabilities={
                ecodes.EV_ABS: [ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_PRESSURE],
                ecodes.EV_KEY: [ecodes.BTN_TOOL_PEN, ecodes.BTN_TOUCH],
            },
        )
        pad = _FakeProfileInputDevice(
            name="Wacom Intuos Pro L Pad", capabilities={ecodes.EV_KEY: [ecodes.BTN_0, ecodes.BTN_1]}
        )

        self.assertEqual(input_device_profile(pen).kind, InputDeviceKind.TABLET_PEN)
        self.assertEqual(input_device_profile(pad).kind, InputDeviceKind.TABLET_PAD)

    def test_profile_classifies_all_dispatched_pen_tool_keys_as_pen(self) -> None:
        for tool_key in (
            ecodes.BTN_TOOL_BRUSH,
            ecodes.BTN_TOOL_PENCIL,
            ecodes.BTN_TOOL_AIRBRUSH,
            ecodes.BTN_TOOL_MOUSE,
            ecodes.BTN_TOOL_LENS,
        ):
            with self.subTest(tool_key=tool_key):
                pen = _FakeProfileInputDevice(
                    name="Generic Tablet Tool",
                    capabilities={ecodes.EV_ABS: [ecodes.ABS_X, ecodes.ABS_Y], ecodes.EV_KEY: [tool_key]},
                )

                self.assertEqual(input_device_profile(pen).kind, InputDeviceKind.TABLET_PEN)

    def test_profile_classifies_wacom_pt_pad_before_stylus_button_looks_like_pen(self) -> None:
        pad = _FakeProfileInputDevice(
            name="Wacom Intuos PT M Pad",
            capabilities={
                ecodes.EV_ABS: [ecodes.ABS_X, ecodes.ABS_Y],
                ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_BACK, ecodes.BTN_STYLUS],
            },
            absinfo={ecodes.ABS_X: (0, 1), ecodes.ABS_Y: (0, 1)},
        )

        self.assertEqual(input_device_profile(pad).kind, InputDeviceKind.TABLET_PAD)

    def test_inventory_text_marks_relay_and_skipped_devices(self) -> None:
        with patch(
            f"{INPUTS_INVENTORY}.list_input_devices",
            return_value=[
                _FakeInputDevice(path="/dev/input/event1", name="Keyboard", capabilities={ecodes.EV_KEY: []}),
                _FakeInputDevice(path="/dev/input/event2", name="vc4 HDMI", capabilities={ecodes.EV_KEY: []}),
            ],
        ):
            text = inventory_to_text(describe_input_devices())

        self.assertIn("relay", text)
        self.assertIn("skip", text)
        self.assertIn("name prefix vc4", text)
