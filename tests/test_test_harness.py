import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.test_harness import run as run_harness
from bluetooth_2_usb.test_harness_capture import (
    CaptureMismatchError,
    ConsumerSequenceMatcher,
    KeyboardSequenceMatcher,
    MouseSequenceMatcher,
    _build_candidate_sets,
    discover_gadget_node_candidates,
    discover_gadget_nodes,
)
from bluetooth_2_usb.test_harness_common import (
    CONSUMER_STEPS,
    EXIT_PREREQUISITE,
    EXIT_USAGE,
    MOUSE_REL_STEPS,
    SCENARIOS,
)


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
        self.assertEqual(len(combo.mouse_rel_steps), 4)
        self.assertEqual(len(combo.mouse_button_steps), 0)

    def test_consumer_scenario_contains_volume_sequence(self) -> None:
        consumer = SCENARIOS["consumer"]

        self.assertEqual(consumer.required_nodes, ("consumer",))
        self.assertEqual(consumer.consumer_steps, CONSUMER_STEPS)


class GadgetNodeDiscoveryTest(unittest.TestCase):
    def test_discovery_groups_hid_devices_by_input_role(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("kbd0", usage_page=0x01, usage=0x06),
                _hid_entry("mouse0", usage_page=0x01, usage=0x02),
                _hid_entry("consumer0", usage_page=0x0C, usage=0x01),
                _hid_entry(
                    "other0",
                    device_name="some other device",
                    usage_page=0x0C,
                    usage=0x01,
                ),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual([info.node for info in candidates.keyboard_nodes], ["kbd0"])
        self.assertEqual([info.node for info in candidates.mouse_nodes], ["mouse0"])
        self.assertEqual(
            [info.node for info in candidates.consumer_nodes], ["consumer0"]
        )

    def test_discovery_returns_multiple_candidates_when_duplicate_devices_exist(
        self,
    ) -> None:
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
            [info.node for info in candidates.consumer_nodes],
            ["consumer-a", "consumer-b"],
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

    def test_discovery_accepts_linux_gadget_signature_without_product_strings(
        self,
    ) -> None:
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

        self.assertEqual(
            [info.node for info in candidates.keyboard_nodes], ["1-2.1.2:1.0"]
        )
        self.assertEqual(
            [info.node for info in candidates.mouse_nodes], ["1-2.1.2:1.1"]
        )
        self.assertEqual(
            [info.node for info in candidates.consumer_nodes], ["1-2.1.2:1.2"]
        )

    def test_single_role_candidate_sets_are_split_per_device(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("1-2.1.2:1.1", usage_page=0x01, usage=0x02),
                _hid_entry("1-2.1.3:1.1", usage_page=0x01, usage=0x02),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)
        candidate_sets = _build_candidate_sets("mouse", candidates)

        self.assertEqual(len(candidate_sets), 2)
        self.assertEqual(
            [candidate_set.mouse_nodes[0].node for candidate_set in candidate_sets],
            ["1-2.1.2:1.1", "1-2.1.3:1.1"],
        )
        self.assertTrue(
            all(
                candidate_set.keyboard_nodes == ()
                and candidate_set.consumer_nodes == ()
                for candidate_set in candidate_sets
            )
        )


class KeyboardSequenceMatcherTest(unittest.TestCase):
    def test_keyboard_matcher_accepts_boot_keyboard_reports(self) -> None:
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
    def test_mouse_matcher_accepts_small_relative_motion_only(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, ())

        matcher.handle(bytes([0x02, 0x00, 0x01, 0x00, 0x00]))
        matcher.handle(bytes([0x02, 0x00, 0xFF, 0x00, 0x00]))
        matcher.handle(bytes([0x02, 0x00, 0x00, 0x01, 0x00]))
        matcher.handle(bytes([0x02, 0x00, 0x00, 0xFF, 0x00]))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_compact_report_id_format(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, ())

        matcher.handle(bytes([0x02, 0x00, 0x01, 0x00]))
        matcher.handle(bytes([0x00]))
        matcher.handle(bytes([0x02, 0x00, 0xFF, 0x00]))
        matcher.handle(bytes([0x00]))
        matcher.handle(bytes([0x02, 0x00, 0x00, 0x01]))
        matcher.handle(bytes([0x00]))
        matcher.handle(bytes([0x02, 0x00, 0x00, 0xFF]))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_rejects_unexpected_button_bits(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, ())

        with self.assertRaisesRegex(CaptureMismatchError, "button bits"):
            matcher.handle(bytes([0x02, 0x02, 0, 0, 0]))

    def test_mouse_matcher_rejects_unexpected_motion_order(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, ())

        with self.assertRaisesRegex(CaptureMismatchError, "expected EV_REL/REL_X=1"):
            matcher.handle(bytes([0x02, 0x00, 0xFF, 0x00, 0x00]))


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


class TestHarnessCliTest(unittest.TestCase):
    def test_inject_usage_error_returns_exit_usage(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = run_harness(["inject", "--pre-delay-ms", "-1"])

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

        with patch(
            "bluetooth_2_usb.test_harness_capture.run_capture", return_value=result
        ):
            with redirect_stdout(stdout):
                exit_code = run_harness(["capture", "--output", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue())["details"]["keyboard_steps_seen"], 6
        )

    def test_capture_missing_nodes_returns_prerequisite_exit(self) -> None:
        stdout = io.StringIO()
        hid_module = _FakeHidModule([])

        with patch(
            "bluetooth_2_usb.test_harness_capture._load_hidapi",
            return_value=hid_module,
        ):
            with redirect_stdout(stdout):
                exit_code = run_harness(
                    ["capture", "--keyboard-node", "/definitely/missing/node"]
                )

        self.assertEqual(exit_code, EXIT_PREREQUISITE)
        self.assertIn("Keyboard HID device was not found", stdout.getvalue())
