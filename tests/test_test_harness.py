import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.test_harness import run as run_harness
from bluetooth_2_usb.test_harness_capture import (
    CaptureMismatchError,
    ConsumerSequenceMatcher,
    KeyboardSequenceMatcher,
    MouseSequenceMatcher,
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


def _write_hidraw_uevent(
    root: Path,
    hidraw_name: str,
    *,
    device_name: str = "quaxalber USB Combo Device",
    phys: str,
    uniq: str = "213374badcafe",
) -> None:
    device_dir = root / hidraw_name / "device"
    device_dir.mkdir(parents=True)
    (device_dir / "uevent").write_text(
        "\n".join(
            [
                f"HID_NAME={device_name}",
                f"HID_PHYS={phys}",
                f"HID_UNIQ={uniq}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


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
    def test_discovery_groups_hidraw_nodes_by_input_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_hidraw_uevent(root, "hidraw7", phys="usb-x/input0")
            _write_hidraw_uevent(root, "hidraw8", phys="usb-x/input1")
            _write_hidraw_uevent(root, "hidraw9", phys="usb-x/input2")
            _write_hidraw_uevent(
                root,
                "hidraw10",
                device_name="some other device",
                phys="usb-y/input2",
            )

            candidates = discover_gadget_node_candidates(hidraw_root=root)

        self.assertEqual(candidates.keyboard_nodes, ("/dev/hidraw7",))
        self.assertEqual(candidates.mouse_nodes, ("/dev/hidraw8",))
        self.assertEqual(candidates.consumer_nodes, ("/dev/hidraw9",))

    def test_discovery_returns_multiple_candidates_when_duplicate_hidraws_exist(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_hidraw_uevent(root, "hidraw7", phys="usb-a/input2")
            _write_hidraw_uevent(root, "hidraw12", phys="usb-b/input2")

            candidates = discover_gadget_node_candidates(hidraw_root=root)

        self.assertEqual(candidates.keyboard_nodes, ())
        self.assertEqual(candidates.mouse_nodes, ())
        self.assertEqual(
            candidates.consumer_nodes,
            ("/dev/hidraw12", "/dev/hidraw7"),
        )

    def test_discovery_rejects_multiple_distinct_keyboard_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_hidraw_uevent(root, "hidraw7", phys="usb-a/input0")
            _write_hidraw_uevent(root, "hidraw8", phys="usb-b/input0")

            with self.assertRaisesRegex(Exception, "Multiple keyboard hidraw nodes"):
                discover_gadget_nodes(hidraw_root=root)

    def test_explicit_override_bypasses_auto_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            keyboard = root / "hidraw20"
            mouse = root / "hidraw21"
            consumer = root / "hidraw22"
            keyboard.touch()
            mouse.touch()
            consumer.touch()

            nodes = discover_gadget_nodes(
                keyboard_node=str(keyboard),
                mouse_node=str(mouse),
                consumer_node=str(consumer),
                hidraw_root=root,
            )

        self.assertEqual(nodes.keyboard_node, str(keyboard.resolve()))
        self.assertEqual(nodes.mouse_node, str(mouse.resolve()))
        self.assertEqual(nodes.consumer_node, str(consumer.resolve()))


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

        with patch("bluetooth_2_usb.test_harness.run_capture", return_value=result):
            with redirect_stdout(stdout):
                exit_code = run_harness(["capture", "--output", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue())["details"]["keyboard_steps_seen"], 6
        )

    def test_capture_missing_nodes_returns_prerequisite_exit(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = run_harness(
                ["capture", "--keyboard-node", "/definitely/missing/node"]
            )

        self.assertEqual(exit_code, EXIT_PREREQUISITE)
        self.assertIn("does not exist", stdout.getvalue())
