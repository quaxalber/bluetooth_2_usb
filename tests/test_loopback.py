import importlib
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bluetooth_2_usb.loopback import capture_windows
from bluetooth_2_usb.loopback import run as run_loopback
from bluetooth_2_usb.loopback.capture import (
    CaptureMismatchError,
    ConsumerSequenceMatcher,
    KeyboardSequenceMatcher,
    MouseSequenceMatcher,
    discover_gadget_node_candidates,
    discover_gadget_nodes,
)
from bluetooth_2_usb.loopback.capture_windows import (
    RAWMOUSE,
    RI_MOUSE_BUTTON_4_DOWN,
    RI_MOUSE_BUTTON_4_UP,
    RI_MOUSE_BUTTON_5_DOWN,
    RI_MOUSE_BUTTON_5_UP,
    RI_MOUSE_HORIZONTAL_WHEEL,
    RI_MOUSE_LEFT_BUTTON_DOWN,
    RI_MOUSE_LEFT_BUTTON_UP,
    RI_MOUSE_WHEEL,
)
from bluetooth_2_usb.loopback.constants import EXIT_INTERRUPTED, EXIT_PREREQUISITE, EXIT_USAGE
from bluetooth_2_usb.loopback.inject import (
    DEFAULT_SERVICE_SETTLE_SEC,
    SERVICE_SETTLE_ENV,
    _configured_service_settle_sec,
    _wait_for_service_settle,
    run_inject,
)
from bluetooth_2_usb.loopback.result import LoopbackResult
from bluetooth_2_usb.loopback.scenarios import (
    CONSUMER_STEPS,
    EV_REL,
    FAST_MOUSE_REL_STEPS,
    MOUSE_BUTTON_STEPS,
    MOUSE_REL_STEPS,
    REL_HWHEEL,
    REL_WHEEL,
    REL_X,
    REL_Y,
    SAFE_MOUSE_BUTTON_STEPS,
    SCENARIOS,
    TEXT_BURST_STEPS,
    ExpectedEvent,
    get_scenario,
)
from bluetooth_2_usb.loopback.session import LoopbackBusyError


def _hid_entry(
    path: str,
    *,
    device_name: str = "quaxalber USB Combo Device",
    manufacturer: str = "quaxalber",
    serial: str = "213374badcafe",
    vendor_id: int = 0,
    product_id: int = 0,
    interface_number: int = 0,
    usage_page: int,
    usage: int,
) -> dict[str, object]:
    return {
        "path": path,
        "product_string": device_name,
        "manufacturer_string": manufacturer,
        "serial_number": serial,
        "vendor_id": vendor_id,
        "product_id": product_id,
        "interface_number": interface_number,
        "usage_page": usage_page,
        "usage": usage,
    }


class _FakeHidModule:
    def __init__(self, entries):
        self._entries = entries

    def enumerate(self):
        return list(self._entries)


class ScenarioDefinitionTest(unittest.TestCase):
    def test_combo_scenario_contains_keyboard_and_mouse_sequences(self) -> None:
        combo = SCENARIOS["combo"]

        self.assertEqual(combo.required_nodes, ("keyboard", "mouse"))
        self.assertEqual(len(combo.keyboard_steps), 6)
        self.assertEqual(len(combo.mouse_rel_steps), 11)
        self.assertEqual(combo.mouse_button_steps, SAFE_MOUSE_BUTTON_STEPS)
        self.assertEqual(len(combo.mouse_button_steps), 4)
        self.assertEqual(combo.mouse_coalesced_tail_count, 3)

    def test_intrusive_mouse_button_scenario_contains_all_button_bits(self) -> None:
        scenario = SCENARIOS["mouse_buttons_intrusive"]

        self.assertEqual(scenario.required_nodes, ("mouse",))
        self.assertEqual(scenario.mouse_button_steps, MOUSE_BUTTON_STEPS)
        self.assertEqual(len(scenario.mouse_button_steps), 16)

    def test_consumer_scenario_contains_volume_sequence(self) -> None:
        consumer = SCENARIOS["consumer"]

        self.assertEqual(consumer.required_nodes, ("consumer",))
        self.assertEqual(consumer.consumer_steps, CONSUMER_STEPS)

    def test_fast_mouse_scenario_contains_large_relative_motion(self) -> None:
        scenario = SCENARIOS["mouse_fast"]

        self.assertEqual(scenario.required_nodes, ("mouse",))
        self.assertEqual(scenario.mouse_rel_steps, FAST_MOUSE_REL_STEPS)
        self.assertEqual(scenario.mouse_coalesced_tail_count, 0)
        self.assertGreater(max(abs(step.value) for step in scenario.mouse_rel_steps), 32767)

    def test_invalid_scenario_name_is_reported_cleanly(self) -> None:
        with self.assertRaises(ValueError) as error:
            get_scenario("nope")

        self.assertEqual(
            str(error.exception),
            f"Unknown scenario 'nope'. Expected one of: {', '.join(SCENARIOS)}",
        )

    def test_text_burst_scenario_is_keyboard_only_and_contains_shifted_steps(self) -> None:
        scenario = SCENARIOS["text_burst"]

        self.assertEqual(scenario.required_nodes, ("keyboard",))
        self.assertEqual(scenario.keyboard_steps, TEXT_BURST_STEPS)
        self.assertIn(42, [step.code for step in scenario.keyboard_steps])


class GadgetNodeDiscoveryTest(unittest.TestCase):
    def test_discovery_groups_hid_devices_by_input_role(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("kbd0", usage_page=0x01, usage=0x06),
                _hid_entry("mouse0", usage_page=0x01, usage=0x02),
                _hid_entry("consumer0", usage_page=0x0C, usage=0x01),
                _hid_entry("other0", device_name="some other device", usage_page=0x0C, usage=0x01),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual([info.node for info in candidates.keyboard_nodes], ["kbd0"])
        self.assertEqual([info.node for info in candidates.mouse_nodes], ["mouse0"])
        self.assertEqual([info.node for info in candidates.consumer_nodes], ["consumer0"])

    def test_discovery_returns_multiple_candidates_when_duplicate_devices_exist(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("consumer-b", usage_page=0x0C, usage=0x01),
                _hid_entry("consumer-a", usage_page=0x0C, usage=0x01),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual(candidates.keyboard_nodes, ())
        self.assertEqual(candidates.mouse_nodes, ())
        self.assertEqual(
            [info.node for info in candidates.consumer_nodes], ["consumer-a", "consumer-b"]
        )

    def test_discovery_rejects_multiple_distinct_keyboard_nodes(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("kbd-a", usage_page=0x01, usage=0x06),
                _hid_entry("kbd-b", usage_page=0x01, usage=0x06),
            ]
        )

        with self.assertRaisesRegex(Exception, "Multiple keyboard HID devices"):
            discover_gadget_nodes(hid_module=hid_module)

    def test_explicit_override_bypasses_auto_detection(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("kbd-a", usage_page=0x01, usage=0x06),
                _hid_entry("mouse-a", usage_page=0x01, usage=0x02),
                _hid_entry("consumer-a", usage_page=0x0C, usage=0x01),
            ]
        )

        nodes = discover_gadget_nodes(
            keyboard_node="kbd-a",
            mouse_node="mouse-a",
            consumer_node="consumer-a",
            hid_module=hid_module,
        )

        self.assertEqual(nodes.keyboard_node, "kbd-a")
        self.assertEqual(nodes.mouse_node, "mouse-a")
        self.assertEqual(nodes.consumer_node, "consumer-a")

    def test_discovery_accepts_linux_gadget_signature_without_product_strings(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry(
                    "1-2.1.2:1.0",
                    device_name="",
                    manufacturer="",
                    serial="",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=0,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.1",
                    device_name="",
                    manufacturer="",
                    serial="",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=1,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.2",
                    device_name="",
                    manufacturer="",
                    serial="",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=2,
                    usage_page=0,
                    usage=0,
                ),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual([info.node for info in candidates.keyboard_nodes], ["1-2.1.2:1.0"])
        self.assertEqual([info.node for info in candidates.mouse_nodes], ["1-2.1.2:1.1"])
        self.assertEqual([info.node for info in candidates.consumer_nodes], ["1-2.1.2:1.2"])

    def test_discovery_maps_default_linux_gadget_interfaces_by_interface_number(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry(
                    "1-2.1.2:1.0",
                    device_name="USB Combo Device",
                    serial="213374badcafe",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=0,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.1",
                    device_name="USB Combo Device",
                    serial="213374badcafe",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=1,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.2",
                    device_name="USB Combo Device",
                    serial="213374badcafe",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=2,
                    usage_page=0,
                    usage=0,
                ),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual([info.node for info in candidates.keyboard_nodes], ["1-2.1.2:1.0"])
        self.assertEqual([info.node for info in candidates.mouse_nodes], ["1-2.1.2:1.1"])
        self.assertEqual([info.node for info in candidates.consumer_nodes], ["1-2.1.2:1.2"])

    def test_explicit_override_accepts_default_linux_gadget_interfaces(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry(
                    "1-2.1.2:1.0",
                    device_name="USB Combo Device",
                    serial="213374badcafe",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=0,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.1",
                    device_name="USB Combo Device",
                    serial="213374badcafe",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=1,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.2",
                    device_name="USB Combo Device",
                    serial="213374badcafe",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=2,
                    usage_page=0,
                    usage=0,
                ),
            ]
        )

        nodes = discover_gadget_nodes(
            keyboard_node="1-2.1.2:1.1",
            mouse_node="1-2.1.2:1.0",
            consumer_node="1-2.1.2:1.2",
            hid_module=hid_module,
        )

        self.assertEqual(nodes.keyboard_node, "1-2.1.2:1.1")
        self.assertEqual(nodes.mouse_node, "1-2.1.2:1.0")
        self.assertEqual(nodes.consumer_node, "1-2.1.2:1.2")


class KeyboardSequenceMatcherTest(unittest.TestCase):
    def test_keyboard_matcher_accepts_eight_byte_keyboard_reports(self) -> None:
        matcher = KeyboardSequenceMatcher(SCENARIOS["keyboard"].keyboard_steps)

        reports = (
            bytes([0x00, 0x00, 0x68, 0, 0, 0, 0, 0]),
            bytes([0x00] * 8),
            bytes([0x00, 0x00, 0x69, 0, 0, 0, 0, 0]),
            bytes([0x00] * 8),
            bytes([0x00, 0x00, 0x6A, 0, 0, 0, 0, 0]),
            bytes([0x00] * 8),
        )
        for report in reports:
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_accepts_report_id_keyboard_reports(self) -> None:
        matcher = KeyboardSequenceMatcher(SCENARIOS["keyboard"].keyboard_steps)

        reports = (
            bytes([0x01, 0x00, 0x00, 0x68, 0, 0, 0, 0, 0]),
            bytes([0x01] + [0x00] * 8),
            bytes([0x01, 0x00, 0x00, 0x69, 0, 0, 0, 0, 0]),
            bytes([0x01] + [0x00] * 8),
            bytes([0x01, 0x00, 0x00, 0x6A, 0, 0, 0, 0, 0]),
            bytes([0x01] + [0x00] * 8),
        )
        for report in reports:
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_ignores_single_zero_reports_between_steps(self) -> None:
        matcher = KeyboardSequenceMatcher(SCENARIOS["keyboard"].keyboard_steps)

        reports = (
            bytes([0x00, 0x00, 0x68, 0, 0, 0, 0, 0]),
            bytes([0x00]),
            bytes([0x00] * 8),
            bytes([0x00]),
            bytes([0x00, 0x00, 0x69, 0, 0, 0, 0, 0]),
            bytes([0x00]),
            bytes([0x00] * 8),
            bytes([0x00]),
            bytes([0x00, 0x00, 0x6A, 0, 0, 0, 0, 0]),
            bytes([0x00]),
            bytes([0x00] * 8),
        )
        for report in reports:
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_rejects_unexpected_report(self) -> None:
        matcher = KeyboardSequenceMatcher(SCENARIOS["keyboard"].keyboard_steps)

        with self.assertRaises(CaptureMismatchError):
            matcher.handle(bytes([0x00] * 8))


class MouseSequenceMatcherTest(unittest.TestCase):
    @staticmethod
    def _extended_mouse_report(
        buttons: int = 0, x: int = 0, y: int = 0, wheel: int = 0, pan: int = 0
    ) -> bytes:
        return bytes(
            [
                buttons,
                *x.to_bytes(2, "little", signed=True),
                *y.to_bytes(2, "little", signed=True),
                wheel & 0xFF,
                pan & 0xFF,
            ]
        )

    def test_mouse_matcher_accepts_small_relative_motion_only(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:4], ())

        matcher.handle(self._extended_mouse_report(x=1))
        matcher.handle(self._extended_mouse_report(x=-1))
        matcher.handle(self._extended_mouse_report(y=1))
        matcher.handle(self._extended_mouse_report(y=-1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_zero_prefixed_hidapi_report(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:1], ())

        matcher.handle(bytes([0x00]) + self._extended_mouse_report(x=1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_report_id_prefixed_hidapi_report(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:1], ())

        matcher.handle(bytes([0x02]) + self._extended_mouse_report(x=1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_two_byte_prefixed_hidapi_report(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:1], ())

        matcher.handle(bytes([0x00, 0x02]) + self._extended_mouse_report(x=1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_rejects_unexpected_button_bits(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:4], ())

        with self.assertRaisesRegex(CaptureMismatchError, "button bits"):
            matcher.handle(self._extended_mouse_report(buttons=0x02, x=1))

    def test_mouse_matcher_rejects_button_state_on_motion_before_movement_complete(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:4], SAFE_MOUSE_BUTTON_STEPS)

        with self.assertRaisesRegex(
            CaptureMismatchError, "Mouse button report arrived before movement"
        ):
            matcher.handle(self._extended_mouse_report(buttons=0x08, x=1))

    def test_mouse_matcher_rejects_unexpected_motion_order(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:4], ())

        with self.assertRaisesRegex(CaptureMismatchError, "expected REL_X=1"):
            matcher.handle(self._extended_mouse_report(x=-1))

    def test_mouse_matcher_rejects_cross_axis_reordering_between_reports(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS[:4], ())

        with self.assertRaisesRegex(CaptureMismatchError, "expected REL_X=1"):
            matcher.handle(self._extended_mouse_report(y=1))

    def test_mouse_matcher_accepts_extended_motion_wheel_and_pan(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, ())

        matcher.handle(bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]))
        matcher.handle(bytes([0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00]))
        matcher.handle(bytes([0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00]))
        matcher.handle(bytes([0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00]))
        matcher.handle(bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00]))
        matcher.handle(bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00]))
        matcher.handle(bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]))
        matcher.handle(bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF]))
        matcher.handle(bytes([0x00, 0x02, 0x00, 0xFD, 0xFF, 0x00, 0x01]))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_chunked_fast_motion(self) -> None:
        matcher = MouseSequenceMatcher.create(FAST_MOUSE_REL_STEPS, ())

        for report in (
            self._extended_mouse_report(x=32767),
            self._extended_mouse_report(x=7233),
            self._extended_mouse_report(y=-32767),
            self._extended_mouse_report(y=-7233),
            self._extended_mouse_report(x=-32767),
            self._extended_mouse_report(x=-12233),
            self._extended_mouse_report(y=32767),
            self._extended_mouse_report(y=12233),
            self._extended_mouse_report(wheel=127),
            self._extended_mouse_report(wheel=127),
            self._extended_mouse_report(wheel=127),
            self._extended_mouse_report(wheel=127),
            self._extended_mouse_report(wheel=92),
            self._extended_mouse_report(wheel=-127),
            self._extended_mouse_report(wheel=-127),
            self._extended_mouse_report(wheel=-127),
            self._extended_mouse_report(wheel=-127),
            self._extended_mouse_report(wheel=-92),
            self._extended_mouse_report(pan=127),
            self._extended_mouse_report(pan=127),
            self._extended_mouse_report(pan=127),
            self._extended_mouse_report(pan=127),
            self._extended_mouse_report(pan=92),
            self._extended_mouse_report(pan=-127),
            self._extended_mouse_report(pan=-127),
            self._extended_mouse_report(pan=-127),
            self._extended_mouse_report(pan=-127),
            self._extended_mouse_report(pan=-92),
        ):
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_combined_chunked_fast_motion(self) -> None:
        matcher = MouseSequenceMatcher.create(
            (
                ExpectedEvent(EV_REL, REL_X, 40000),
                ExpectedEvent(EV_REL, REL_Y, -40000),
                ExpectedEvent(EV_REL, REL_WHEEL, 600),
                ExpectedEvent(EV_REL, REL_HWHEEL, -600),
            ),
            (),
        )

        for report in (
            self._extended_mouse_report(x=32767, y=-32767, wheel=127, pan=-127),
            self._extended_mouse_report(x=7233, y=-7233, wheel=127, pan=-127),
            self._extended_mouse_report(wheel=127, pan=-127),
            self._extended_mouse_report(wheel=127, pan=-127),
            self._extended_mouse_report(wheel=92, pan=-92),
        ):
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_all_extended_button_bits(self) -> None:
        matcher = MouseSequenceMatcher.create((), MOUSE_BUTTON_STEPS)

        for button in (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            matcher.handle(bytes([button, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
            matcher.handle(bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))

        self.assertTrue(matcher.complete)


class ConsumerSequenceMatcherTest(unittest.TestCase):
    def test_consumer_matcher_accepts_volume_sequence(self) -> None:
        matcher = ConsumerSequenceMatcher(SCENARIOS["consumer"].consumer_steps)

        for report in (
            bytes([0x03, 0xE9, 0x00]),
            bytes([0x03, 0x00, 0x00]),
            bytes([0x03, 0xEA, 0x00]),
            bytes([0x03, 0x00, 0x00]),
        ):
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_consumer_matcher_accepts_zero_prefixed_raw_input_reports(self) -> None:
        matcher = ConsumerSequenceMatcher(SCENARIOS["consumer"].consumer_steps)

        for report in (
            bytes([0x00, 0xE9, 0x00]),
            bytes([0x00, 0x00, 0x00]),
            bytes([0x00, 0xEA, 0x00]),
            bytes([0x00, 0x00, 0x00]),
        ):
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_consumer_matcher_accepts_compact_report_id_format(self) -> None:
        matcher = ConsumerSequenceMatcher(SCENARIOS["consumer"].consumer_steps)

        for report in (
            bytes([0x03, 0xE9]),
            bytes([0x00]),
            bytes([0x03, 0x00]),
            bytes([0x00]),
            bytes([0x03, 0xEA]),
            bytes([0x00]),
            bytes([0x03, 0x00]),
        ):
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_consumer_matcher_rejects_unexpected_usage(self) -> None:
        matcher = ConsumerSequenceMatcher(SCENARIOS["consumer"].consumer_steps)

        with self.assertRaises(CaptureMismatchError):
            matcher.handle(bytes([0x03, 0x00, 0x00]))


class WindowsRawInputHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        capture_windows._reset_mouse_button_state()

    def test_extract_device_identities_collapses_windows_hid_paths(self) -> None:
        self.assertEqual(
            capture_windows._extract_device_identities(
                (
                    r"\\?\HID#VID_1D6B&PID_0104&MI_00#9&314c2078&0&0000#{GUID}",
                    r"\\?\hid#vid_1d6b&pid_0104&mi_00#9&314c2078&0&0000#{guid}",
                )
            ),
            (r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",),
        )

    def test_device_matches_candidate_on_same_hid_instance_identity(self) -> None:
        self.assertTrue(
            capture_windows._device_matches_candidate(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                (r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",),
            )
        )

    def test_stable_device_identity_ignores_guid_and_suffix_differences(self) -> None:
        self.assertEqual(
            capture_windows._stable_device_identity(
                r"\\?\HID#VID_1D6B&PID_0104&MI_00#9&314c2078&0&0000#{A5DCBF10-6530-11D2-901F-00C04FB951ED}\KBD"
            ),
            r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",
        )
        self.assertEqual(
            capture_windows._stable_device_identity(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{884b96c3-56ef-11d1-bc8c-00a0c91405dd}"
            ),
            r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",
        )

    def test_device_matches_candidate_on_shared_hid_instance_identity(self) -> None:
        self.assertTrue(
            capture_windows._device_matches_candidate(
                r"\\?\hid\vid_1d6b&pid_0104&mi_01\9&2217c3c8&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                (r"hid\vid_1d6b&pid_0104&mi_01\9&2217c3c8&0&0000",),
            )
        )

    def test_device_does_not_match_different_hid_instance_identity(self) -> None:
        self.assertFalse(
            capture_windows._device_matches_candidate(
                r"\\?\hid\vid_1d6b&pid_0104&mi_01\9&2217c3c8&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                (
                    r"\\?\HID#VID_16D0&PID_092E&MI_00#8&1020304&0&0000#{A5DCBF10-6530-11D2-901F-00C04FB951ED}",
                ),
            )
        )

    def test_keyboard_event_to_report_builds_eight_byte_keyboard_reports(self) -> None:
        self.assertEqual(
            capture_windows._keyboard_event_to_report(0x7C, is_key_up=False),
            bytes([0x00, 0x00, 104, 0, 0, 0, 0, 0]),
        )
        self.assertEqual(
            capture_windows._keyboard_event_to_report(0x7C, is_key_up=True),
            bytes([0x00] * 8),
        )

    def test_keyboard_event_to_report_ignores_unexpected_keys(self) -> None:
        self.assertIsNone(capture_windows._keyboard_event_to_report(0x41, is_key_up=False))

    def test_mouse_event_to_reports_builds_16_bit_xy_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.lLastX = 300
        raw_mouse.lLastY = -300

        self.assertEqual(
            capture_windows._mouse_event_to_reports(raw_mouse),
            [bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x00, 0x00])],
        )

    def test_mouse_event_to_reports_clamps_xy_to_descriptor_bounds(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.lLastX = 40000
        raw_mouse.lLastY = -40000

        self.assertEqual(
            capture_windows._mouse_event_to_reports(raw_mouse),
            [bytes([0x00, 0xFF, 0x7F, 0x01, 0x80, 0x00, 0x00])],
        )

    def test_mouse_event_to_reports_builds_horizontal_pan_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.ulButtons = RI_MOUSE_HORIZONTAL_WHEEL | (0xFFFF << 16)

        self.assertEqual(
            capture_windows._mouse_event_to_reports(raw_mouse),
            [bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF])],
        )

    def test_mouse_event_to_reports_tracks_button_state(self) -> None:
        capture_windows._reset_mouse_button_state()
        left_button_down = RAWMOUSE()
        left_button_down.ulButtons = RI_MOUSE_LEFT_BUTTON_DOWN
        self.assertEqual(
            capture_windows._mouse_event_to_reports(left_button_down),
            [bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

        move_while_pressed = RAWMOUSE()
        move_while_pressed.lLastX = 1
        self.assertEqual(
            capture_windows._mouse_event_to_reports(move_while_pressed),
            [bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

        left_button_up = RAWMOUSE()
        left_button_up.ulButtons = RI_MOUSE_LEFT_BUTTON_UP
        self.assertEqual(
            capture_windows._mouse_event_to_reports(left_button_up),
            [bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

    def test_mouse_event_to_reports_tracks_windows_extra_button_state(self) -> None:
        capture_windows._reset_mouse_button_state()
        button_4_down = RAWMOUSE()
        button_4_down.ulButtons = RI_MOUSE_BUTTON_4_DOWN
        self.assertEqual(
            capture_windows._mouse_event_to_reports(button_4_down),
            [bytes([0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

        button_5_down = RAWMOUSE()
        button_5_down.ulButtons = RI_MOUSE_BUTTON_5_DOWN
        self.assertEqual(
            capture_windows._mouse_event_to_reports(button_5_down),
            [bytes([0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

        button_4_up = RAWMOUSE()
        button_4_up.ulButtons = RI_MOUSE_BUTTON_4_UP
        self.assertEqual(
            capture_windows._mouse_event_to_reports(button_4_up),
            [bytes([0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

        button_5_up = RAWMOUSE()
        button_5_up.ulButtons = RI_MOUSE_BUTTON_5_UP
        self.assertEqual(
            capture_windows._mouse_event_to_reports(button_5_up),
            [bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

    def test_mouse_event_to_reports_keeps_wheel_and_motion_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.ulButtons = RI_MOUSE_WHEEL | (0x0001 << 16)
        raw_mouse.lLastX = 300
        raw_mouse.lLastY = -300

        self.assertEqual(
            capture_windows._mouse_event_to_reports(raw_mouse),
            [bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x01, 0x00])],
        )

    def test_mouse_event_to_reports_keeps_pan_and_motion_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.ulButtons = RI_MOUSE_HORIZONTAL_WHEEL | (0xFFFF << 16)
        raw_mouse.lLastX = 300
        raw_mouse.lLastY = -300

        self.assertEqual(
            capture_windows._mouse_event_to_reports(raw_mouse),
            [bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x00, 0xFF])],
        )

    def test_windows_backend_refuses_non_windows_runtime(self) -> None:
        if sys.platform == "win32":
            self.skipTest("Non-Windows runtime guard is not exercised on Windows")

        with self.assertRaisesRegex(RuntimeError, "only available on Windows"):
            capture_windows.run_windows_raw_input_capture(
                scenario_name="keyboard",
                timeout_sec=1.0,
                candidate_nodes=capture_windows.GadgetNodeCandidates(
                    keyboard_nodes=(), mouse_nodes=(), consumer_nodes=()
                ),
            )

    def test_windows_backend_reports_unsupported_intrusive_mouse_buttons(self) -> None:
        with patch("bluetooth_2_usb.loopback.capture_windows.IS_WINDOWS", True):
            result = capture_windows.run_windows_raw_input_capture(
                scenario_name="mouse_buttons_intrusive",
                timeout_sec=1.0,
                candidate_nodes=capture_windows.GadgetNodeCandidates(
                    keyboard_nodes=(), mouse_nodes=(), consumer_nodes=()
                ),
            )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, EXIT_PREREQUISITE)
        self.assertEqual(
            result.details["unsupported_mouse_buttons"], ["BTN_FORWARD", "BTN_BACK", "BTN_TASK"]
        )

    def test_windows_backend_imports_with_missing_non_windows_handle_aliases(self) -> None:
        if sys.platform == "win32":
            self.skipTest("Non-Windows import fallback is not exercised on Windows")

        missing_names = ("HCURSOR", "HICON", "HBRUSH")
        original_values = {
            name: getattr(capture_windows.wintypes, name)
            for name in missing_names
            if hasattr(capture_windows.wintypes, name)
        }
        try:
            for name in missing_names:
                if hasattr(capture_windows.wintypes, name):
                    delattr(capture_windows.wintypes, name)

            reloaded = importlib.reload(capture_windows)

            self.assertIs(reloaded.wintypes.HCURSOR, reloaded.ctypes.c_void_p)
            self.assertIs(reloaded.wintypes.HICON, reloaded.ctypes.c_void_p)
            self.assertIs(reloaded.wintypes.HBRUSH, reloaded.ctypes.c_void_p)
        finally:
            for name in missing_names:
                if hasattr(capture_windows.wintypes, name):
                    delattr(capture_windows.wintypes, name)
            for name, value in original_values.items():
                setattr(capture_windows.wintypes, name, value)
            importlib.reload(capture_windows)


class LoopbackInjectTest(unittest.TestCase):
    def test_configured_service_settle_accepts_zero_override(self) -> None:
        with patch.dict("os.environ", {SERVICE_SETTLE_ENV: "0"}):
            self.assertEqual(_configured_service_settle_sec(), 0)

    def test_configured_service_settle_defaults_for_invalid_values(self) -> None:
        for value in ("not-a-number", "-1"):
            with self.subTest(value=value):
                with patch.dict("os.environ", {SERVICE_SETTLE_ENV: value}):
                    self.assertEqual(_configured_service_settle_sec(), DEFAULT_SERVICE_SETTLE_SEC)

    def test_wait_for_service_settle_skips_systemctl_when_disabled(self) -> None:
        with patch("bluetooth_2_usb.loopback.inject.subprocess.run") as run:
            _wait_for_service_settle(0)

        run.assert_not_called()

    def test_run_inject_rejects_negative_timing_before_sleeping(self) -> None:
        with patch("bluetooth_2_usb.loopback.inject.time.sleep") as sleep:
            result = run_inject("keyboard", pre_delay_ms=-1)

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, EXIT_PREREQUISITE)
        sleep.assert_not_called()


class LoopbackCliTest(unittest.TestCase):
    def test_old_flat_loopback_modules_are_not_preserved(self) -> None:
        for module_name in (
            "bluetooth_2_usb.loopback_capture",
            "bluetooth_2_usb.loopback_capture_windows",
            "bluetooth_2_usb.loopback_common",
            "bluetooth_2_usb.loopback_inject",
        ):
            with self.subTest(module_name=module_name):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)

    def test_inject_usage_error_returns_exit_usage(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = run_loopback(["inject", "--pre-delay-ms", "-1"])

        self.assertEqual(exit_code, EXIT_USAGE)
        self.assertIn("--pre-delay-ms must be >= 0", stdout.getvalue())

    def test_capture_returns_json_from_result(self) -> None:
        stdout = io.StringIO()
        result = SimpleNamespace(
            exit_code=0,
            to_dict=lambda: {
                "command": "capture",
                "scenario": "combo",
                "success": True,
                "exit_code": 0,
                "message": "ok",
                "details": {"keyboard_steps_seen": 6},
            },
            to_text=lambda: "ignored",
        )

        with patch("bluetooth_2_usb.loopback.capture.run_capture", return_value=result):
            with redirect_stdout(stdout):
                exit_code = run_loopback(["capture", "--output", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["details"]["keyboard_steps_seen"], 6)

    def test_capture_missing_nodes_returns_prerequisite_exit(self) -> None:
        stdout = io.StringIO()
        hid_module = _FakeHidModule([])

        with patch("bluetooth_2_usb.loopback.capture._load_hidapi", return_value=hid_module):
            with redirect_stdout(stdout):
                exit_code = run_loopback(["capture", "--keyboard-node", "/definitely/missing/node"])

        self.assertEqual(exit_code, EXIT_PREREQUISITE)
        self.assertIn("Keyboard HID device was not found", stdout.getvalue())

    def test_reports_busy_lock_cleanly(self) -> None:
        stdout = io.StringIO()

        with patch(
            "bluetooth_2_usb.loopback.cli.loopback_session", side_effect=LoopbackBusyError("busy")
        ):
            with redirect_stdout(stdout):
                exit_code = run_loopback(["capture"])

        self.assertEqual(exit_code, LoopbackBusyError.exit_code)
        self.assertIn("busy", stdout.getvalue())
        self.assertIn("lock_path", stdout.getvalue())

    def test_reports_interrupt_cleanly(self) -> None:
        stdout = io.StringIO()
        fake_inject_module = SimpleNamespace(run_inject=Mock(side_effect=KeyboardInterrupt))

        with patch.dict("sys.modules", {"bluetooth_2_usb.loopback.inject": fake_inject_module}):
            with redirect_stdout(stdout):
                exit_code = run_loopback(["inject"])

        self.assertEqual(exit_code, EXIT_INTERRUPTED)
        self.assertIn("Loopback interrupted", stdout.getvalue())

    def test_windows_capture_uses_raw_input_backend_for_non_consumer_scenarios(self) -> None:
        candidate_nodes = discover_gadget_node_candidates(
            keyboard_node="kbd0",
            mouse_node="mouse0",
            hid_module=_FakeHidModule(
                [
                    _hid_entry(
                        "kbd0",
                        vendor_id=0x1D6B,
                        product_id=0x0104,
                        interface_number=0,
                        usage_page=0x01,
                        usage=0x06,
                    ),
                    _hid_entry(
                        "mouse0",
                        vendor_id=0x1D6B,
                        product_id=0x0104,
                        interface_number=1,
                        usage_page=0x01,
                        usage=0x02,
                    ),
                ]
            ),
        )

        with patch("bluetooth_2_usb.loopback.capture.sys.platform", "win32"):
            with patch(
                "bluetooth_2_usb.loopback.capture._load_hidapi",
                return_value=_FakeHidModule(
                    [
                        _hid_entry(
                            "kbd0",
                            vendor_id=0x1D6B,
                            product_id=0x0104,
                            interface_number=0,
                            usage_page=0x01,
                            usage=0x06,
                        ),
                        _hid_entry(
                            "mouse0",
                            vendor_id=0x1D6B,
                            product_id=0x0104,
                            interface_number=1,
                            usage_page=0x01,
                            usage=0x02,
                        ),
                    ]
                ),
            ):
                with patch(
                    "bluetooth_2_usb.loopback.capture_windows.run_windows_raw_input_capture",
                    return_value=LoopbackResult(
                        command="capture",
                        scenario="combo",
                        success=True,
                        exit_code=0,
                        message="ok",
                        details={"nodes": candidate_nodes.matched_nodes().to_dict()},
                    ),
                ) as run_backend:
                    exit_code = run_loopback(["capture", "--scenario", "combo"])

        self.assertEqual(exit_code, 0)
        run_backend.assert_called_once()

    def test_windows_capture_uses_raw_input_backend_for_consumer_scenarios(self) -> None:
        consumer_hid = _FakeHidModule(
            [
                _hid_entry(
                    "consumer0",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=2,
                    usage_page=0x0C,
                    usage=0x01,
                )
            ]
        )

        with patch("bluetooth_2_usb.loopback.capture.sys.platform", "win32"):
            with patch("bluetooth_2_usb.loopback.capture._load_hidapi", return_value=consumer_hid):
                with patch(
                    "bluetooth_2_usb.loopback.capture_windows.run_windows_raw_input_capture",
                    return_value=LoopbackResult(
                        command="capture",
                        scenario="consumer",
                        success=True,
                        exit_code=0,
                        message="ok",
                        details={"capture_backend": "raw_input"},
                    ),
                ) as run_backend:
                    with patch("bluetooth_2_usb.loopback.capture._capture_once") as capture_once:
                        exit_code = run_loopback(["capture", "--scenario", "consumer"])

        self.assertEqual(exit_code, 0)
        run_backend.assert_called_once()
        capture_once.assert_not_called()
