import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evdev import ecodes

from bluetooth_2_usb.test_harness import run as run_harness
from bluetooth_2_usb.test_harness_capture import (
    CaptureMismatchError,
    KeyboardSequenceMatcher,
    MouseSequenceMatcher,
    discover_gadget_nodes,
)
from bluetooth_2_usb.test_harness_common import (
    EXIT_PREREQUISITE,
    EXIT_USAGE,
    MOUSE_BUTTON_STEPS,
    MOUSE_REL_STEPS,
    SCENARIOS,
)


def _event(event_type: int, code: int, value: int) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, code=code, value=value)


class ScenarioDefinitionTest(unittest.TestCase):
    def test_combo_scenario_contains_keyboard_and_mouse_sequences(self) -> None:
        combo = SCENARIOS["combo"]

        self.assertEqual(combo.required_nodes, ("keyboard", "mouse"))
        self.assertEqual(len(combo.keyboard_steps), 6)
        self.assertEqual(len(combo.mouse_rel_steps), 2)
        self.assertEqual(len(combo.mouse_button_steps), 2)


class GadgetNodeDiscoveryTest(unittest.TestCase):
    def test_discovery_deduplicates_symlink_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            event4 = root / "event4"
            event5 = root / "event5"
            event4.touch()
            event5.touch()
            (root / "usb-foo_USB_Combo_Device-event-kbd").symlink_to(event4)
            (root / "usb-bar_USB_Combo_Device-event-kbd").symlink_to(event4)
            (root / "usb-foo_USB_Combo_Device-event-mouse").symlink_to(event5)

            nodes = discover_gadget_nodes(by_id_root=root)

        self.assertEqual(nodes.keyboard_node, str(event4.resolve()))
        self.assertEqual(nodes.mouse_node, str(event5.resolve()))

    def test_discovery_rejects_multiple_distinct_keyboard_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            event4 = root / "event4"
            event6 = root / "event6"
            event4.touch()
            event6.touch()
            (root / "usb-a_USB_Combo_Device-event-kbd").symlink_to(event4)
            (root / "usb-b_USB_Combo_Device-event-kbd").symlink_to(event6)

            with self.assertRaisesRegex(Exception, "Multiple keyboard gadget nodes"):
                discover_gadget_nodes(by_id_root=root)

    def test_explicit_override_bypasses_auto_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            keyboard = root / "event8"
            mouse = root / "event9"
            keyboard.touch()
            mouse.touch()

            nodes = discover_gadget_nodes(
                keyboard_node=str(keyboard),
                mouse_node=str(mouse),
            )

        self.assertEqual(nodes.keyboard_node, str(keyboard.resolve()))
        self.assertEqual(nodes.mouse_node, str(mouse.resolve()))


class KeyboardSequenceMatcherTest(unittest.TestCase):
    def test_keyboard_matcher_accepts_expected_sequence(self) -> None:
        matcher = KeyboardSequenceMatcher(SCENARIOS["keyboard"].keyboard_steps)

        for step_event in SCENARIOS["keyboard"].keyboard_steps:
            matcher.handle(
                _event(step_event.event_type, step_event.code, step_event.value)
            )

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_rejects_unexpected_event(self) -> None:
        matcher = KeyboardSequenceMatcher(SCENARIOS["keyboard"].keyboard_steps)

        with self.assertRaises(CaptureMismatchError):
            matcher.handle(_event(ecodes.EV_KEY, ecodes.KEY_A, 0))


class MouseSequenceMatcherTest(unittest.TestCase):
    def test_mouse_matcher_accepts_split_relative_motion_and_button_steps(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, MOUSE_BUTTON_STEPS)

        matcher.handle(_event(ecodes.EV_REL, ecodes.REL_X, 10))
        matcher.handle(_event(ecodes.EV_REL, ecodes.REL_X, 20))
        matcher.handle(_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0))
        matcher.handle(_event(ecodes.EV_REL, ecodes.REL_Y, 5))
        matcher.handle(_event(ecodes.EV_REL, ecodes.REL_Y, 10))
        matcher.handle(_event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1))
        matcher.handle(_event(ecodes.EV_KEY, ecodes.BTN_LEFT, 0))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_rejects_button_before_relative_motion(self) -> None:
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, MOUSE_BUTTON_STEPS)

        with self.assertRaisesRegex(CaptureMismatchError, "before movement"):
            matcher.handle(_event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1))


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
