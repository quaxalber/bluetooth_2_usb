import importlib
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bluetooth_2_usb import test_harness_capture_windows
from bluetooth_2_usb.test_harness import run as run_harness
from bluetooth_2_usb.test_harness_capture import (
    CaptureMismatchError,
    ConsumerSequenceMatcher,
    KeyboardSequenceMatcher,
    MouseSequenceMatcher,
    discover_gadget_node_candidates,
    discover_gadget_nodes,
)
from bluetooth_2_usb.test_harness_capture_windows import (
    _device_matches_candidate,
    _device_matches_token,
    _extract_device_names,
    _extract_device_token,
    _keyboard_event_to_report,
    _validate_candidate_token_disjointness,
)
from bluetooth_2_usb.test_harness_common import (
    CONSUMER_STEPS,
    EXIT_INTERRUPTED,
    EXIT_PREREQUISITE,
    EXIT_USAGE,
    MOUSE_REL_STEPS,
    SCENARIOS,
    HarnessBusyError,
    HarnessResult,
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
    def test_extract_device_token_reads_vid_pid_and_interface(self) -> None:
        token = _extract_device_token(
            r"\\?\HID#VID_1D6B&PID_0104&MI_00#9&314c2078&0&0000#{...}\KBD"
        )

        self.assertEqual(token, "vid_1d6b&pid_0104&mi_00")

    def test_device_matches_token_accepts_normalized_raw_input_names(self) -> None:
        self.assertTrue(
            _device_matches_token(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000".lower(),
                ("vid_1d6b&pid_0104&mi_00",),
            )
        )

    def test_extract_device_names_normalizes_windows_hid_paths(self) -> None:
        self.assertEqual(
            _extract_device_names(
                (
                    r"\\?\HID#VID_1D6B&PID_0104&MI_00#9&314c2078&0&0000#{GUID}",
                    r"\\?\hid#vid_1d6b&pid_0104&mi_00#9&314c2078&0&0000#{guid}",
                )
            ),
            (r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{guid}",),
        )

    def test_device_matches_candidate_prefers_exact_normalized_hid_paths(self) -> None:
        self.assertTrue(
            _device_matches_candidate(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                (
                    r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                ),
                ("vid_1d6b&pid_0104&mi_01",),
            )
        )

    def test_device_matches_token_uses_simple_vid_pid_interface_tokens(self) -> None:
        self.assertTrue(
            _device_matches_token(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                ("vid_1d6b&pid_0104&mi_00",),
            )
        )
        self.assertTrue(
            _device_matches_token(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&2b6bd27c&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                ("vid_1d6b&pid_0104&mi_00",),
            )
        )

    def test_validate_candidate_token_disjointness_rejects_overlapping_roles(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            CaptureMismatchError,
            "keyboard/mouse=vid_1d6b&pid_0104&mi_00",
        ):
            _validate_candidate_token_disjointness(
                keyboard_tokens=("vid_1d6b&pid_0104&mi_00", "vid_1d6b&pid_0104&mi_01"),
                mouse_tokens=("vid_1d6b&pid_0104&mi_00",),
                consumer_tokens=("vid_1d6b&pid_0104&mi_02",),
            )

    def test_validate_candidate_token_disjointness_accepts_disjoint_roles(self) -> None:
        _validate_candidate_token_disjointness(
            keyboard_tokens=("vid_1d6b&pid_0104&mi_01",),
            mouse_tokens=("vid_1d6b&pid_0104&mi_00",),
            consumer_tokens=("vid_1d6b&pid_0104&mi_02",),
        )

    def test_keyboard_event_to_report_builds_boot_keyboard_reports(self) -> None:
        self.assertEqual(
            _keyboard_event_to_report(0x7C, is_key_up=False),
            bytes([0x00, 0x00, 104, 0, 0, 0, 0, 0]),
        )
        self.assertEqual(
            _keyboard_event_to_report(0x7C, is_key_up=True),
            bytes([0x00] * 8),
        )

    def test_keyboard_event_to_report_ignores_unexpected_keys(self) -> None:
        self.assertIsNone(_keyboard_event_to_report(0x41, is_key_up=False))

    def test_windows_backend_refuses_non_windows_runtime(self) -> None:
        if sys.platform == "win32":
            self.skipTest("Non-Windows runtime guard is not exercised on Windows")

        with self.assertRaisesRegex(RuntimeError, "only available on Windows"):
            test_harness_capture_windows.run_windows_raw_input_capture(
                scenario_name="keyboard",
                timeout_sec=1.0,
                candidate_nodes=test_harness_capture_windows.GadgetNodeCandidates(
                    keyboard_nodes=(),
                    mouse_nodes=(),
                    consumer_nodes=(),
                ),
            )

    def test_windows_backend_imports_with_missing_non_windows_handle_aliases(
        self,
    ) -> None:
        if sys.platform == "win32":
            self.skipTest("Non-Windows import fallback is not exercised on Windows")

        missing_names = ("HCURSOR", "HICON", "HBRUSH")
        original_values = {
            name: getattr(test_harness_capture_windows.wintypes, name)
            for name in missing_names
            if hasattr(test_harness_capture_windows.wintypes, name)
        }
        try:
            for name in missing_names:
                if hasattr(test_harness_capture_windows.wintypes, name):
                    delattr(test_harness_capture_windows.wintypes, name)

            reloaded = importlib.reload(test_harness_capture_windows)

            self.assertIs(reloaded.wintypes.HCURSOR, reloaded.ctypes.c_void_p)
            self.assertIs(reloaded.wintypes.HICON, reloaded.ctypes.c_void_p)
            self.assertIs(reloaded.wintypes.HBRUSH, reloaded.ctypes.c_void_p)
        finally:
            for name in missing_names:
                if hasattr(test_harness_capture_windows.wintypes, name):
                    delattr(test_harness_capture_windows.wintypes, name)
            for name, value in original_values.items():
                setattr(test_harness_capture_windows.wintypes, name, value)
            importlib.reload(test_harness_capture_windows)


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

    def test_harness_reports_busy_lock_cleanly(self) -> None:
        stdout = io.StringIO()

        with patch(
            "bluetooth_2_usb.test_harness.harness_session",
            side_effect=HarnessBusyError("busy"),
        ):
            with redirect_stdout(stdout):
                exit_code = run_harness(["capture"])

        self.assertEqual(exit_code, HarnessBusyError.exit_code)
        self.assertIn("busy", stdout.getvalue())
        self.assertIn("lock_path", stdout.getvalue())

    def test_harness_reports_interrupt_cleanly(self) -> None:
        stdout = io.StringIO()
        fake_inject_module = SimpleNamespace(
            run_inject=Mock(side_effect=KeyboardInterrupt)
        )

        with patch.dict(
            "sys.modules",
            {"bluetooth_2_usb.test_harness_inject": fake_inject_module},
        ):
            with redirect_stdout(stdout):
                exit_code = run_harness(["inject"])

        self.assertEqual(exit_code, EXIT_INTERRUPTED)
        self.assertIn("Harness interrupted", stdout.getvalue())

    def test_windows_capture_uses_raw_input_backend_for_non_consumer_scenarios(
        self,
    ) -> None:
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

        with patch("bluetooth_2_usb.test_harness_capture.sys.platform", "win32"):
            with patch(
                "bluetooth_2_usb.test_harness_capture._load_hidapi",
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
                    "bluetooth_2_usb.test_harness_capture_windows.run_windows_raw_input_capture",
                    return_value=HarnessResult(
                        command="capture",
                        scenario="combo",
                        success=True,
                        exit_code=0,
                        message="ok",
                        details={"nodes": candidate_nodes.matched_nodes().to_dict()},
                    ),
                ) as run_backend:
                    exit_code = run_harness(["capture", "--scenario", "combo"])

        self.assertEqual(exit_code, 0)
        run_backend.assert_called_once()

    def test_windows_capture_uses_raw_input_backend_for_consumer_scenarios(
        self,
    ) -> None:
        consumer_hid = _FakeHidModule(
            [
                _hid_entry(
                    "consumer0",
                    vendor_id=0x1D6B,
                    product_id=0x0104,
                    interface_number=2,
                    usage_page=0x0C,
                    usage=0x01,
                ),
            ]
        )

        with patch("bluetooth_2_usb.test_harness_capture.sys.platform", "win32"):
            with patch(
                "bluetooth_2_usb.test_harness_capture._load_hidapi",
                return_value=consumer_hid,
            ):
                with patch(
                    "bluetooth_2_usb.test_harness_capture_windows.run_windows_raw_input_capture",
                    return_value=HarnessResult(
                        command="capture",
                        scenario="consumer",
                        success=True,
                        exit_code=0,
                        message="ok",
                        details={"capture_backend": "raw_input"},
                    ),
                ) as run_backend:
                    with patch(
                        "bluetooth_2_usb.test_harness_capture._capture_once"
                    ) as capture_once:
                        exit_code = run_harness(["capture", "--scenario", "consumer"])

        self.assertEqual(exit_code, 0)
        run_backend.assert_called_once()
        capture_once.assert_not_called()
