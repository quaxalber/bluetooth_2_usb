import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bluetooth_2_usb.evdev import KeyEvent, ecodes, evdev_to_usb_hid, is_consumer_key
from bluetooth_2_usb.gadgets.identity import USB_GADGET_PID_COMBO, USB_GADGET_VID_LINUX
from bluetooth_2_usb.gadgets.layout import (
    HID_FUNC_INDEX_CONSUMER,
    HID_FUNC_INDEX_KEYBOARD,
    HID_FUNC_INDEX_MOUSE,
    USB_PRODUCT_NAME,
    USB_SERIAL_NUMBER,
)
from bluetooth_2_usb.hid.constants import (
    HID_PAGE_CONSUMER,
    HID_PAGE_GENERIC_DESKTOP,
    HID_USAGE_CONSUMER_CONTROL,
    HID_USAGE_KEYBOARD,
    HID_USAGE_MOUSE,
)
from bluetooth_2_usb.loopback import capture_windows
from bluetooth_2_usb.loopback import run as run_loopback
from bluetooth_2_usb.loopback.capture import (
    CaptureMismatchError,
    ConsumerSequenceMatcher,
    KeyboardSequenceMatcher,
    MissingNodeError,
    MouseSequenceMatcher,
    discover_gadget_node_candidates,
    discover_gadget_nodes,
    run_capture,
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
from bluetooth_2_usb.loopback.constants import (
    EXIT_ACCESS,
    EXIT_INTERRUPTED,
    EXIT_PREREQUISITE,
    EXIT_TIMEOUT,
    EXIT_USAGE,
)
from bluetooth_2_usb.loopback.inject import (
    DEFAULT_SERVICE_SETTLE_SEC,
    SERVICE_SETTLE_ENV,
    _consumer_capabilities,
    run_inject,
    service_settle_sec,
    wait_for_service_settle,
)
from bluetooth_2_usb.loopback.result import LoopbackResult
from bluetooth_2_usb.loopback.scenarios import (
    CONSUMER_CODES,
    CONSUMER_STEPS,
    EV_KEY,
    EV_REL,
    EXOTIC_KEYBOARD_CODES,
    EXOTIC_KEYBOARD_STEPS,
    KEY_K,
    KEY_LEFTSHIFT,
    MOUSE_BUTTON_STEPS,
    MOUSE_REL_STEPS,
    NODE_DISCOVERY_CONSUMER_STEPS,
    NODE_DISCOVERY_KEYBOARD_STEPS,
    REL_HWHEEL,
    REL_WHEEL,
    REL_X,
    REL_Y,
    SCENARIOS,
    ExpectedEvent,
    get_scenario,
    scenario_summary,
)
from bluetooth_2_usb.loopback.session import LoopbackBusyError


def _chunk_count(value: int, report_limit: int) -> int:
    return (abs(value) + report_limit - 1) // report_limit


def _mouse_report_count(steps: tuple[ExpectedEvent, ...]) -> int:
    total = 0
    for step in steps:
        report_limit = 127 if step.code in (REL_WHEEL, REL_HWHEEL) else 32767
        total += _chunk_count(step.value, report_limit)
    return total


def _mapped_hid_usage(step: ExpectedEvent) -> int:
    usage, _name = evdev_to_usb_hid(SimpleNamespace(scancode=step.code, keystate=step.value))
    assert usage is not None
    return usage


def _keyboard_report_for_code(code: int, *, key_state: int = KeyEvent.key_down) -> bytes:
    usage = _mapped_hid_usage(ExpectedEvent(EV_KEY, code, key_state))
    return bytes([0x00, 0x00, usage, 0, 0, 0, 0, 0])


def _consumer_report_for_step(step: ExpectedEvent, *, report_id: int = 0x03, width: int = 3) -> bytes:
    usage = _mapped_hid_usage(step) if step.value == KeyEvent.key_down else 0
    if width == 2:
        return bytes([report_id, usage & 0xFF])
    return bytes([report_id, usage & 0xFF, usage >> 8])


SIMPLE_KEYBOARD_STEPS = (ExpectedEvent(EV_KEY, KEY_K, KeyEvent.key_down), ExpectedEvent(EV_KEY, KEY_K, KeyEvent.key_up))

SMALL_MOUSE_REL_STEPS = (
    ExpectedEvent(EV_REL, REL_X, 1),
    ExpectedEvent(EV_REL, REL_X, -1),
    ExpectedEvent(EV_REL, REL_Y, 1),
    ExpectedEvent(EV_REL, REL_Y, -1),
    ExpectedEvent(EV_REL, REL_WHEEL, 1),
    ExpectedEvent(EV_REL, REL_WHEEL, -1),
    ExpectedEvent(EV_REL, REL_HWHEEL, 1),
    ExpectedEvent(EV_REL, REL_HWHEEL, -1),
    ExpectedEvent(EV_REL, REL_X, 2),
    ExpectedEvent(EV_REL, REL_Y, -3),
    ExpectedEvent(EV_REL, REL_HWHEEL, 1),
)


def _hid_entry(
    path: str,
    *,
    device_name: str = f"quaxalber {USB_PRODUCT_NAME}",
    manufacturer: str = "quaxalber",
    serial: str = USB_SERIAL_NUMBER,
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


class _FakeReadableHidDevice:
    def __init__(self, reports_by_path):
        self._reports_by_path = reports_by_path
        self._path = None

    def open_path(self, path):
        self._path = path

    def set_nonblocking(self, enabled):
        del enabled

    def read(self, size):
        del size
        assert self._path is not None
        reports = self._reports_by_path.get(self._path, [])
        if not reports:
            return []
        return reports.pop(0)

    def close(self):
        pass


class _FakeReadableHidModule(_FakeHidModule):
    def __init__(self, entries, reports_by_path):
        super().__init__(entries)
        self._reports_by_path = {path: list(reports) for path, reports in reports_by_path.items()}

    def device(self):
        return _FakeReadableHidDevice(self._reports_by_path)


class ScenarioDefinitionTest(unittest.TestCase):
    def test_public_scenarios_are_small_and_intentional(self) -> None:
        self.assertEqual(set(SCENARIOS), {"keyboard", "mouse", "node-discovery", "consumer", "combo"})

    def test_keyboard_scenario_contains_full_modifier_burst(self) -> None:
        scenario = SCENARIOS["keyboard"]

        self.assertEqual(scenario.required_nodes, ("keyboard",))
        self.assertIn(KEY_LEFTSHIFT, [step.code for step in scenario.keyboard_steps])
        self.assertIn(KEY_K, [step.code for step in scenario.keyboard_steps])
        self.assertTrue(any(step.value == KeyEvent.key_down for step in scenario.keyboard_steps))
        self.assertTrue(any(step.value == KeyEvent.key_up for step in scenario.keyboard_steps))
        self.assertTrue(all(step in scenario.keyboard_steps for step in EXOTIC_KEYBOARD_STEPS))
        self.assertEqual(scenario.default_event_gap_ms, 10)
        self.assertEqual(scenario.default_post_delay_ms, 6000)
        self.assertEqual(scenario.default_capture_timeout_sec, 15.0)

    def test_loopback_keyboard_candidates_are_production_mapped(self) -> None:
        for code in EXOTIC_KEYBOARD_CODES:
            with self.subTest(code=code):
                usage = _mapped_hid_usage(ExpectedEvent(EV_KEY, code, KeyEvent.key_down))
                self.assertIsInstance(usage, int)

    def test_mouse_scenario_contains_fast_motion_and_all_button_bits(self) -> None:
        scenario = SCENARIOS["mouse"]

        self.assertEqual(scenario.required_nodes, ("mouse",))
        self.assertEqual(scenario.mouse_rel_steps, MOUSE_REL_STEPS)
        self.assertEqual(scenario.mouse_button_steps, MOUSE_BUTTON_STEPS)
        self.assertEqual(len(scenario.mouse_button_steps), 16)
        self.assertEqual(scenario.mouse_coalesced_tail_count, 0)
        self.assertEqual(scenario.default_event_gap_ms, 0)
        self.assertEqual(scenario.default_post_delay_ms, 1000)
        self.assertEqual(scenario.default_capture_timeout_sec, 10.0)
        self.assertGreaterEqual(_mouse_report_count(scenario.mouse_rel_steps), 80)

    def test_node_discovery_scenario_contains_minimal_all_role_sequence(self) -> None:
        scenario = SCENARIOS["node-discovery"]

        self.assertEqual(scenario.required_nodes, ("keyboard", "mouse", "consumer"))
        self.assertEqual(scenario.keyboard_steps, NODE_DISCOVERY_KEYBOARD_STEPS)
        self.assertEqual(scenario.mouse_rel_steps, (ExpectedEvent(EV_REL, REL_X, 1), ExpectedEvent(EV_REL, REL_X, -1)))
        self.assertEqual(scenario.mouse_button_steps, ())
        self.assertEqual(scenario.consumer_steps, NODE_DISCOVERY_CONSUMER_STEPS)
        self.assertNotEqual(scenario.consumer_steps, CONSUMER_STEPS)
        self.assertEqual(scenario.default_capture_timeout_sec, 5.0)

    def test_consumer_scenario_contains_representative_consumer_sequence(self) -> None:
        consumer = SCENARIOS["consumer"]

        self.assertEqual(consumer.required_nodes, ("consumer",))
        self.assertEqual(consumer.consumer_steps, CONSUMER_STEPS)
        self.assertEqual(consumer.default_capture_timeout_sec, 10.0)

    def test_loopback_consumer_candidates_are_production_mapped(self) -> None:
        usages = []
        for code in CONSUMER_CODES:
            with self.subTest(code=code):
                event = SimpleNamespace(scancode=code, keystate=KeyEvent.key_down)
                self.assertTrue(is_consumer_key(event))
                usages.append(_mapped_hid_usage(ExpectedEvent(EV_KEY, code, KeyEvent.key_down)))
        self.assertTrue(any(usage > 0xFF for usage in usages))

    def test_combo_scenario_contains_keyboard_mouse_and_consumer_sequences(self) -> None:
        combo = SCENARIOS["combo"]

        self.assertEqual(combo.required_nodes, ("keyboard", "mouse", "consumer"))
        self.assertEqual(combo.keyboard_steps, SCENARIOS["keyboard"].keyboard_steps)
        self.assertEqual(combo.mouse_rel_steps, MOUSE_REL_STEPS)
        self.assertEqual(combo.mouse_button_steps, MOUSE_BUTTON_STEPS)
        self.assertEqual(combo.consumer_steps, CONSUMER_STEPS)
        self.assertEqual(combo.default_capture_timeout_sec, 30.0)

    def test_invalid_scenario_name_is_reported_cleanly(self) -> None:
        with self.assertRaises(ValueError) as error:
            get_scenario("nope")

        self.assertEqual(str(error.exception), f"Unknown scenario 'nope'. Expected one of: {', '.join(SCENARIOS)}")

    def test_scenario_summary_reports_counts_without_full_sequences(self) -> None:
        summary = scenario_summary(SCENARIOS["combo"])

        self.assertEqual(summary["name"], "combo")
        self.assertEqual(summary["keyboard_steps"], len(SCENARIOS["combo"].keyboard_steps))
        self.assertEqual(summary["mouse_rel_steps"], len(SCENARIOS["combo"].mouse_rel_steps))
        self.assertEqual(summary["mouse_button_steps"], len(SCENARIOS["combo"].mouse_button_steps))
        self.assertEqual(summary["consumer_steps"], len(SCENARIOS["combo"].consumer_steps))
        self.assertEqual(
            summary["total_steps"],
            len(SCENARIOS["combo"].keyboard_steps)
            + len(SCENARIOS["combo"].mouse_rel_steps)
            + len(SCENARIOS["combo"].mouse_button_steps)
            + len(SCENARIOS["combo"].consumer_steps),
        )


class GadgetNodeDiscoveryTest(unittest.TestCase):
    def test_discovery_groups_hid_devices_by_input_role(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("kbd0", usage_page=HID_PAGE_GENERIC_DESKTOP, usage=HID_USAGE_KEYBOARD),
                _hid_entry("mouse0", usage_page=HID_PAGE_GENERIC_DESKTOP, usage=HID_USAGE_MOUSE),
                _hid_entry("consumer0", usage_page=HID_PAGE_CONSUMER, usage=HID_USAGE_CONSUMER_CONTROL),
                _hid_entry(
                    "other0",
                    device_name="some other device",
                    usage_page=HID_PAGE_CONSUMER,
                    usage=HID_USAGE_CONSUMER_CONTROL,
                ),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual([info.node for info in candidates.keyboard_nodes], ["kbd0"])
        self.assertEqual([info.node for info in candidates.mouse_nodes], ["mouse0"])
        self.assertEqual([info.node for info in candidates.consumer_nodes], ["consumer0"])

    def test_discovery_returns_multiple_candidates_when_duplicate_devices_exist(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("consumer-b", usage_page=HID_PAGE_CONSUMER, usage=HID_USAGE_CONSUMER_CONTROL),
                _hid_entry("consumer-a", usage_page=HID_PAGE_CONSUMER, usage=HID_USAGE_CONSUMER_CONTROL),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual(candidates.keyboard_nodes, ())
        self.assertEqual(candidates.mouse_nodes, ())
        self.assertEqual([info.node for info in candidates.consumer_nodes], ["consumer-a", "consumer-b"])

    def test_discovery_rejects_multiple_distinct_keyboard_nodes(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("kbd-a", usage_page=HID_PAGE_GENERIC_DESKTOP, usage=HID_USAGE_KEYBOARD),
                _hid_entry("kbd-b", usage_page=HID_PAGE_GENERIC_DESKTOP, usage=HID_USAGE_KEYBOARD),
            ]
        )

        with self.assertRaisesRegex(MissingNodeError, "Multiple keyboard HID devices"):
            discover_gadget_nodes(hid_module=hid_module)

    def test_explicit_override_bypasses_auto_detection(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry("kbd-a", usage_page=HID_PAGE_GENERIC_DESKTOP, usage=HID_USAGE_KEYBOARD),
                _hid_entry("mouse-a", usage_page=HID_PAGE_GENERIC_DESKTOP, usage=HID_USAGE_MOUSE),
                _hid_entry("consumer-a", usage_page=HID_PAGE_CONSUMER, usage=HID_USAGE_CONSUMER_CONTROL),
            ]
        )

        nodes = discover_gadget_nodes(
            keyboard_node="kbd-a", mouse_node="mouse-a", consumer_node="consumer-a", hid_module=hid_module
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
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_KEYBOARD,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.1",
                    device_name="",
                    manufacturer="",
                    serial="",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_MOUSE,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.2",
                    device_name="",
                    manufacturer="",
                    serial="",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_CONSUMER,
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
                    device_name=USB_PRODUCT_NAME,
                    serial=USB_SERIAL_NUMBER,
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_KEYBOARD,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.1",
                    device_name=USB_PRODUCT_NAME,
                    serial=USB_SERIAL_NUMBER,
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_MOUSE,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.2",
                    device_name=USB_PRODUCT_NAME,
                    serial=USB_SERIAL_NUMBER,
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_CONSUMER,
                    usage_page=0,
                    usage=0,
                ),
            ]
        )

        candidates = discover_gadget_node_candidates(hid_module=hid_module)

        self.assertEqual([info.node for info in candidates.keyboard_nodes], ["1-2.1.2:1.0"])
        self.assertEqual([info.node for info in candidates.mouse_nodes], ["1-2.1.2:1.1"])
        self.assertEqual([info.node for info in candidates.consumer_nodes], ["1-2.1.2:1.2"])

    def test_explicit_override_rejects_default_linux_gadget_interface_role_mismatch(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry(
                    "1-2.1.2:1.0",
                    device_name=USB_PRODUCT_NAME,
                    serial=USB_SERIAL_NUMBER,
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_KEYBOARD,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.1",
                    device_name=USB_PRODUCT_NAME,
                    serial=USB_SERIAL_NUMBER,
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_MOUSE,
                    usage_page=0,
                    usage=0,
                ),
                _hid_entry(
                    "1-2.1.2:1.2",
                    device_name=USB_PRODUCT_NAME,
                    serial=USB_SERIAL_NUMBER,
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_CONSUMER,
                    usage_page=0,
                    usage=0,
                ),
            ]
        )

        with self.assertRaisesRegex(MissingNodeError, "Keyboard HID device has role mouse"):
            discover_gadget_nodes(
                keyboard_node="1-2.1.2:1.1",
                mouse_node="1-2.1.2:1.0",
                consumer_node="1-2.1.2:1.2",
                hid_module=hid_module,
            )


class KeyboardSequenceMatcherTest(unittest.TestCase):
    def test_keyboard_matcher_accepts_eight_byte_keyboard_reports(self) -> None:
        matcher = KeyboardSequenceMatcher(SIMPLE_KEYBOARD_STEPS)

        reports = (_keyboard_report_for_code(KEY_K), bytes([0x00] * 8))
        for report in reports:
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_accepts_report_id_keyboard_reports(self) -> None:
        matcher = KeyboardSequenceMatcher(SIMPLE_KEYBOARD_STEPS)

        reports = (bytes([0x01]) + _keyboard_report_for_code(KEY_K), bytes([0x01] + [0x00] * 8))
        for report in reports:
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_ignores_single_zero_reports_between_steps(self) -> None:
        matcher = KeyboardSequenceMatcher(SIMPLE_KEYBOARD_STEPS)

        reports = (_keyboard_report_for_code(KEY_K), bytes([0x00]), bytes([0x00] * 8), bytes([0x00]))
        for report in reports:
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_ignores_duplicate_current_state_reports(self) -> None:
        shifted_key_steps = (
            ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, KeyEvent.key_down),
            ExpectedEvent(EV_KEY, KEY_K, KeyEvent.key_down),
            ExpectedEvent(EV_KEY, KEY_K, KeyEvent.key_up),
            ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, KeyEvent.key_up),
        )
        matcher = KeyboardSequenceMatcher(shifted_key_steps)
        k_usage = _mapped_hid_usage(ExpectedEvent(EV_KEY, KEY_K, KeyEvent.key_down))

        reports = (
            bytes([0x02, 0x00, 0, 0, 0, 0, 0, 0]),
            bytes([0x02, 0x00, 0, 0, 0, 0, 0, 0]),
            bytes([0x02, 0x00, k_usage, 0, 0, 0, 0, 0]),
            bytes([0x02, 0x00, k_usage, 0, 0, 0, 0, 0]),
            bytes([0x02, 0x00, 0, 0, 0, 0, 0, 0]),
            bytes([0x02, 0x00, 0, 0, 0, 0, 0, 0]),
            bytes([0x00] * 8),
        )
        for report in reports:
            matcher.handle(report)

        self.assertTrue(matcher.complete)

    def test_keyboard_matcher_rejects_unexpected_report(self) -> None:
        matcher = KeyboardSequenceMatcher(SIMPLE_KEYBOARD_STEPS)

        with self.assertRaises(CaptureMismatchError):
            matcher.handle(bytes([0x00] * 8))


class MouseSequenceMatcherTest(unittest.TestCase):
    @staticmethod
    def _extended_mouse_report(buttons: int = 0, x: int = 0, y: int = 0, wheel: int = 0, pan: int = 0) -> bytes:
        return bytes(
            [
                buttons,
                *x.to_bytes(2, "little", signed=True),
                *y.to_bytes(2, "little", signed=True),
                wheel & 0xFF,
                pan & 0xFF,
            ]
        )

    @classmethod
    def _reports_for_rel_step(cls, step: ExpectedEvent) -> list[bytes]:
        reports = []
        remaining = step.value
        report_limit = 127 if step.code in (REL_WHEEL, REL_HWHEEL) else 32767
        while remaining:
            chunk = max(-report_limit, min(report_limit, remaining))
            if step.code == REL_X:
                reports.append(cls._extended_mouse_report(x=chunk))
            elif step.code == REL_Y:
                reports.append(cls._extended_mouse_report(y=chunk))
            elif step.code == REL_WHEEL:
                reports.append(cls._extended_mouse_report(wheel=chunk))
            elif step.code == REL_HWHEEL:
                reports.append(cls._extended_mouse_report(pan=chunk))
            else:
                raise AssertionError(f"Unsupported REL code: {step.code}")
            remaining -= chunk
        return reports

    def test_mouse_matcher_accepts_small_relative_motion_only(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:4], ())

        matcher.handle(self._extended_mouse_report(x=1))
        matcher.handle(self._extended_mouse_report(x=-1))
        matcher.handle(self._extended_mouse_report(y=1))
        matcher.handle(self._extended_mouse_report(y=-1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_zero_prefixed_hidapi_report(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:1], ())

        matcher.handle(bytes([0x00]) + self._extended_mouse_report(x=1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_report_id_prefixed_hidapi_report(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:1], ())

        matcher.handle(bytes([0x02]) + self._extended_mouse_report(x=1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_accepts_two_byte_prefixed_hidapi_report(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:1], ())

        matcher.handle(bytes([0x00, 0x02]) + self._extended_mouse_report(x=1))

        self.assertTrue(matcher.complete)

    def test_mouse_matcher_rejects_unexpected_button_bits(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:4], ())

        with self.assertRaisesRegex(CaptureMismatchError, "button bits"):
            matcher.handle(self._extended_mouse_report(buttons=0x02, x=1))

    def test_mouse_matcher_rejects_button_state_on_motion_before_movement_complete(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:4], MOUSE_BUTTON_STEPS[:2])

        with self.assertRaisesRegex(CaptureMismatchError, "Mouse button report arrived before movement"):
            matcher.handle(self._extended_mouse_report(buttons=0x08, x=1))

    def test_mouse_matcher_rejects_unexpected_motion_order(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:4], ())

        with self.assertRaisesRegex(CaptureMismatchError, "expected REL_X=1"):
            matcher.handle(self._extended_mouse_report(x=-1))

    def test_mouse_matcher_rejects_cross_axis_reordering_between_reports(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS[:4], ())

        with self.assertRaisesRegex(CaptureMismatchError, "expected REL_X=1"):
            matcher.handle(self._extended_mouse_report(y=1))

    def test_mouse_matcher_accepts_extended_motion_wheel_and_pan(self) -> None:
        matcher = MouseSequenceMatcher.create(SMALL_MOUSE_REL_STEPS, ())

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
        matcher = MouseSequenceMatcher.create(MOUSE_REL_STEPS, ())

        reports = [report for step in MOUSE_REL_STEPS for report in self._reports_for_rel_step(step)]
        self.assertGreaterEqual(len(reports), 80)
        for report in reports:
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
    def test_consumer_matcher_accepts_expanded_consumer_sequence(self) -> None:
        matcher = ConsumerSequenceMatcher(SCENARIOS["consumer"].consumer_steps)

        for step in SCENARIOS["consumer"].consumer_steps:
            matcher.handle(_consumer_report_for_step(step))

        self.assertTrue(matcher.complete)

    def test_consumer_matcher_accepts_zero_prefixed_raw_input_reports(self) -> None:
        matcher = ConsumerSequenceMatcher(SCENARIOS["consumer"].consumer_steps)

        for step in SCENARIOS["consumer"].consumer_steps:
            matcher.handle(_consumer_report_for_step(step, report_id=0x00))

        self.assertTrue(matcher.complete)

    def test_consumer_matcher_accepts_compact_report_id_format(self) -> None:
        matcher = ConsumerSequenceMatcher(NODE_DISCOVERY_CONSUMER_STEPS)

        for step in NODE_DISCOVERY_CONSUMER_STEPS:
            matcher.handle(_consumer_report_for_step(step, width=2))

        self.assertTrue(matcher.complete)

    def test_consumer_matcher_accepts_usage_above_one_byte(self) -> None:
        high_usage_step = next(
            step for step in CONSUMER_STEPS if step.value == KeyEvent.key_down and _mapped_hid_usage(step) > 0xFF
        )
        matcher = ConsumerSequenceMatcher(
            (high_usage_step, ExpectedEvent(EV_KEY, high_usage_step.code, KeyEvent.key_up))
        )

        matcher.handle(_consumer_report_for_step(high_usage_step))
        matcher.handle(_consumer_report_for_step(ExpectedEvent(EV_KEY, high_usage_step.code, KeyEvent.key_up)))

        self.assertTrue(matcher.complete)

    def test_consumer_matcher_rejects_unexpected_usage(self) -> None:
        matcher = ConsumerSequenceMatcher(SCENARIOS["consumer"].consumer_steps)

        with self.assertRaises(CaptureMismatchError):
            matcher.handle(bytes([0x03, 0x00, 0x00]))


class WindowsRawInputHelpersTest(unittest.TestCase):
    def test_extract_device_identities_collapses_windows_hid_paths(self) -> None:
        self.assertEqual(
            capture_windows.extract_device_identities(
                (
                    r"\\?\HID#VID_1D6B&PID_0104&MI_00#9&314c2078&0&0000#{GUID}",
                    r"\\?\hid#vid_1d6b&pid_0104&mi_00#9&314c2078&0&0000#{guid}",
                )
            ),
            (r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",),
        )

    def test_device_matches_candidate_on_same_hid_instance_identity(self) -> None:
        self.assertTrue(
            capture_windows.device_matches_candidate(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                (r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",),
            )
        )

    def test_stable_device_identity_ignores_guid_and_suffix_differences(self) -> None:
        self.assertEqual(
            capture_windows.stable_device_identity(
                r"\\?\HID#VID_1D6B&PID_0104&MI_00#9&314c2078&0&0000#{A5DCBF10-6530-11D2-901F-00C04FB951ED}\KBD"
            ),
            r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",
        )
        self.assertEqual(
            capture_windows.stable_device_identity(
                r"\\?\hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000\{884b96c3-56ef-11d1-bc8c-00a0c91405dd}"
            ),
            r"hid\vid_1d6b&pid_0104&mi_00\9&314c2078&0&0000",
        )

    def test_device_matches_candidate_on_shared_hid_instance_identity(self) -> None:
        self.assertTrue(
            capture_windows.device_matches_candidate(
                r"\\?\hid\vid_1d6b&pid_0104&mi_01\9&2217c3c8&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                (r"hid\vid_1d6b&pid_0104&mi_01\9&2217c3c8&0&0000",),
            )
        )

    def test_device_does_not_match_different_hid_instance_identity(self) -> None:
        self.assertFalse(
            capture_windows.device_matches_candidate(
                r"\\?\hid\vid_1d6b&pid_0104&mi_01\9&2217c3c8&0&0000\{378de44c-56ef-11d1-bc8c-00a0c91405dd}",
                (r"\\?\HID#VID_16D0&PID_092E&MI_00#8&1020304&0&0000#{A5DCBF10-6530-11D2-901F-00C04FB951ED}",),
            )
        )

    def test_keyboard_event_to_report_builds_eight_byte_keyboard_reports(self) -> None:
        self.assertEqual(
            capture_windows.keyboard_event_to_report(capture_windows.VK_F13, is_key_up=False),
            bytes([0x00, 0x00, capture_windows.VK_TO_HID[capture_windows.VK_F13], 0, 0, 0, 0, 0]),
        )
        self.assertEqual(
            capture_windows.keyboard_event_to_report(capture_windows.VK_F13, is_key_up=True), bytes([0x00] * 8)
        )

    def test_keyboard_event_to_report_covers_extended_scenario_keys(self) -> None:
        for vkey in (
            capture_windows.VK_F24,
            capture_windows.VK_SNAPSHOT,
            capture_windows.VK_INSERT,
            capture_windows.VK_DELETE,
            capture_windows.VK_UP,
            capture_windows.VK_APPS,
        ):
            with self.subTest(vkey=vkey):
                self.assertEqual(
                    capture_windows.keyboard_event_to_report(vkey, is_key_up=False),
                    bytes([0x00, 0x00, capture_windows.VK_TO_HID[vkey], 0, 0, 0, 0, 0]),
                )

    def test_keyboard_event_to_report_ignores_unexpected_keys(self) -> None:
        self.assertIsNone(capture_windows.keyboard_event_to_report(0x41, is_key_up=False))

    def test_raw_input_mouse_report_builder_builds_16_bit_xy_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.lLastX = 300
        raw_mouse.lLastY = -300

        self.assertEqual(
            capture_windows.RawInputMouseReportBuilder().reports_for(raw_mouse),
            [bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x00, 0x00])],
        )

    def test_raw_input_mouse_report_builder_clamps_xy_to_descriptor_bounds(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.lLastX = 40000
        raw_mouse.lLastY = -40000

        self.assertEqual(
            capture_windows.RawInputMouseReportBuilder().reports_for(raw_mouse),
            [bytes([0x00, 0xFF, 0x7F, 0x01, 0x80, 0x00, 0x00])],
        )

    def test_raw_input_mouse_report_builder_builds_horizontal_pan_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.ulButtons = RI_MOUSE_HORIZONTAL_WHEEL | (0xFFFF << 16)

        self.assertEqual(
            capture_windows.RawInputMouseReportBuilder().reports_for(raw_mouse),
            [bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF])],
        )

    def test_raw_input_mouse_report_builder_tracks_button_state(self) -> None:
        builder = capture_windows.RawInputMouseReportBuilder()
        left_button_down = RAWMOUSE()
        left_button_down.ulButtons = RI_MOUSE_LEFT_BUTTON_DOWN
        self.assertEqual(builder.reports_for(left_button_down), [bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])])

        move_while_pressed = RAWMOUSE()
        move_while_pressed.lLastX = 1
        self.assertEqual(builder.reports_for(move_while_pressed), [bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])])

        left_button_up = RAWMOUSE()
        left_button_up.ulButtons = RI_MOUSE_LEFT_BUTTON_UP
        self.assertEqual(builder.reports_for(left_button_up), [bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])])

    def test_raw_input_mouse_report_builder_tracks_windows_extra_button_state(self) -> None:
        builder = capture_windows.RawInputMouseReportBuilder()
        button_4_down = RAWMOUSE()
        button_4_down.ulButtons = RI_MOUSE_BUTTON_4_DOWN
        self.assertEqual(builder.reports_for(button_4_down), [bytes([0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])])

        button_5_down = RAWMOUSE()
        button_5_down.ulButtons = RI_MOUSE_BUTTON_5_DOWN
        self.assertEqual(builder.reports_for(button_5_down), [bytes([0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])])

        button_4_up = RAWMOUSE()
        button_4_up.ulButtons = RI_MOUSE_BUTTON_4_UP
        self.assertEqual(builder.reports_for(button_4_up), [bytes([0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])])

        button_5_up = RAWMOUSE()
        button_5_up.ulButtons = RI_MOUSE_BUTTON_5_UP
        self.assertEqual(builder.reports_for(button_5_up), [bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])])

    def test_raw_input_mouse_report_builder_keeps_wheel_and_motion_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.ulButtons = RI_MOUSE_WHEEL | (0x0001 << 16)
        raw_mouse.lLastX = 300
        raw_mouse.lLastY = -300

        self.assertEqual(
            capture_windows.RawInputMouseReportBuilder().reports_for(raw_mouse),
            [bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x01, 0x00])],
        )

    def test_raw_input_mouse_report_builder_keeps_pan_and_motion_reports(self) -> None:
        raw_mouse = RAWMOUSE()
        raw_mouse.ulButtons = RI_MOUSE_HORIZONTAL_WHEEL | (0xFFFF << 16)
        raw_mouse.lLastX = 300
        raw_mouse.lLastY = -300

        self.assertEqual(
            capture_windows.RawInputMouseReportBuilder().reports_for(raw_mouse),
            [bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x00, 0xFF])],
        )

    def test_windows_backend_refuses_non_windows_runtime(self) -> None:
        if sys.platform == "win32":
            self.skipTest("Non-Windows runtime guard is not exercised on Windows")

        with self.assertRaisesRegex(RuntimeError, "only available on Windows"):
            capture_windows.run_raw_input_capture(
                scenario_name="keyboard",
                timeout_sec=1.0,
                candidate_nodes=capture_windows.GadgetNodeCandidates(
                    keyboard_nodes=(), mouse_nodes=(), consumer_nodes=()
                ),
            )

    def test_mouse_button_expectations_skip_buttons_raw_input_cannot_surface(self) -> None:
        steps, skipped = capture_windows.mouse_button_expectations(SCENARIOS["mouse"])

        self.assertEqual(skipped, ("BTN_FORWARD", "BTN_BACK", "BTN_TASK"))
        self.assertEqual(len(steps), 10)
        self.assertTrue(all(step.code in capture_windows.WINDOWS_RAW_INPUT_MOUSE_BUTTON_CODES for step in steps))

    def test_windows_raw_input_success_details_include_matched_keyboard_node(self) -> None:
        debug = capture_windows._RawInputDebug()
        candidate = capture_windows._RawInputCandidate(
            role="keyboard",
            candidate_identities=("hid\\vid_1d6b&pid_0104&mi_00\\instance",),
            matcher=SimpleNamespace(complete=True, index=2),
            matched_name=r"\\?\hid\vid_1d6b&pid_0104&mi_00\instance\{guid}",
        )
        candidate.note_report(_keyboard_report_for_code(ecodes.KEY_F13))

        result = capture_windows._raw_input_success_result(
            SCENARIOS["keyboard"], 15.0, debug, candidate, None, None, ()
        )

        self.assertTrue(result.success)
        self.assertEqual(result.details["capture_backend"], "raw_input")
        self.assertEqual(result.details["keyboard_steps_seen"], 2)
        self.assertEqual(result.details["nodes"]["keyboard_node"], candidate.matched_name)

    def test_windows_raw_input_failure_details_include_compact_progress(self) -> None:
        debug = capture_windows._RawInputDebug()
        candidate = capture_windows._RawInputCandidate(
            role="keyboard",
            candidate_identities=("hid\\vid_1d6b&pid_0104&mi_00\\instance",),
            matcher=KeyboardSequenceMatcher(SCENARIOS["keyboard"].keyboard_steps),
            matched_name=r"\\?\hid\vid_1d6b&pid_0104&mi_00\instance\{guid}",
        )
        candidate.matcher.handle(_keyboard_report_for_code(KEY_K))
        for index in range(20):
            debug.note_event(
                role="keyboard",
                device_name=f"device-{index}",
                device_identity=f"identity-{index}",
                candidate_identities=candidate.candidate_identities,
                matched=True,
                report=_keyboard_report_for_code(KEY_K),
            )

        details = capture_windows._raw_input_failure_details(15.0, debug, (), candidate, None, None)

        self.assertEqual(details["capture_backend"], "raw_input")
        self.assertEqual(details["keyboard_steps_seen"], 1)
        self.assertEqual(details["keyboard_steps_expected"], len(SCENARIOS["keyboard"].keyboard_steps))
        self.assertEqual(details["nodes"]["keyboard_node"], candidate.matched_name)
        self.assertIn("next_expected", details["progress"]["keyboard"][0])
        self.assertEqual(len(details["raw_input_debug"]["sample_events"]), 12)


class LoopbackInjectTest(unittest.TestCase):
    def test_consumer_capabilities_are_derived_from_scenarios(self) -> None:
        capabilities = _consumer_capabilities()

        self.assertEqual(capabilities[ecodes.EV_KEY], sorted({step.code for step in CONSUMER_STEPS}))

    def test_configured_service_settle_accepts_zero_override(self) -> None:
        with patch.dict("os.environ", {SERVICE_SETTLE_ENV: "0"}):
            self.assertEqual(service_settle_sec(), 0)

    def test_configured_service_settle_defaults_for_invalid_values(self) -> None:
        for value in ("not-a-number", "-1", "inf", "nan"):
            with self.subTest(value=value):
                with patch.dict("os.environ", {SERVICE_SETTLE_ENV: value}):
                    self.assertEqual(service_settle_sec(), DEFAULT_SERVICE_SETTLE_SEC)

    def test_wait_for_service_settle_skips_systemctl_when_disabled(self) -> None:
        with patch("bluetooth_2_usb.loopback.inject.subprocess.run") as run:
            wait_for_service_settle(0)

        run.assert_not_called()

    def test_wait_for_service_settle_ignores_missing_systemctl(self) -> None:
        with patch("bluetooth_2_usb.loopback.inject.subprocess.run", side_effect=OSError):
            wait_for_service_settle(1)

    def test_run_inject_rejects_negative_timing_before_sleeping(self) -> None:
        with patch("bluetooth_2_usb.loopback.inject.time.sleep") as sleep:
            result = run_inject("keyboard", pre_delay_ms=-1)

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, EXIT_PREREQUISITE)
        sleep.assert_not_called()

    def test_run_inject_closes_created_devices_when_setup_fails(self) -> None:
        keyboard = Mock()

        with patch("pathlib.Path.exists", return_value=True):
            with patch("bluetooth_2_usb.loopback.inject.wait_for_service_settle"):
                with patch("bluetooth_2_usb.loopback.inject.UInput", side_effect=[keyboard, OSError("mouse failed")]):
                    result = run_inject("combo")

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, EXIT_ACCESS)
        keyboard.close.assert_called_once_with()

    def test_run_inject_uses_scenario_default_event_gap(self) -> None:
        scenario = SCENARIOS["keyboard"]
        keyboard = Mock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("bluetooth_2_usb.loopback.inject.wait_for_service_settle"),
            patch("bluetooth_2_usb.loopback.inject.UInput", return_value=keyboard),
            patch("bluetooth_2_usb.loopback.inject.time.sleep"),
        ):
            result = run_inject("keyboard", pre_delay_ms=0)

        self.assertTrue(result.success)
        self.assertEqual(result.details["event_gap_ms"], scenario.default_event_gap_ms)
        self.assertEqual(result.details["post_delay_ms"], scenario.default_post_delay_ms)
        self.assertEqual(result.details["injected_event_count"], len(scenario.keyboard_steps))
        self.assertEqual(keyboard.write.call_count, result.details["injected_event_count"])
        first_step = scenario.keyboard_steps[0]
        keyboard.write.assert_any_call(first_step.event_type, first_step.code, first_step.value)

    def test_run_inject_uses_compact_expected_summary(self) -> None:
        keyboard = Mock()
        mouse = Mock()
        consumer = Mock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("bluetooth_2_usb.loopback.inject.wait_for_service_settle"),
            patch("bluetooth_2_usb.loopback.inject.UInput", side_effect=[keyboard, mouse, consumer]),
            patch("bluetooth_2_usb.loopback.inject.time.sleep"),
        ):
            result = run_inject("combo", pre_delay_ms=0)

        self.assertTrue(result.success)
        expected = result.details["expected"]
        self.assertEqual(expected["name"], "combo")
        self.assertEqual(expected["keyboard_steps"], len(SCENARIOS["combo"].keyboard_steps))
        self.assertEqual(expected["total_steps"], result.details["injected_event_count"])
        self.assertNotIsInstance(expected["keyboard_steps"], list)
        self.assertNotIn("consumer_steps", [key for key, value in expected.items() if isinstance(value, list)])

    def test_inject_usage_error_returns_exit_usage(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = run_loopback(["inject", "--pre-delay-ms", "-1"])

        self.assertEqual(exit_code, EXIT_USAGE)
        self.assertIn("--pre-delay-ms must be >= 0", stdout.getvalue())

    def test_inject_cli_passes_none_for_scenario_default_event_gap(self) -> None:
        stdout = io.StringIO()
        result = SimpleNamespace(exit_code=0, to_dict=lambda: {}, to_text=lambda: "ok")

        with patch("bluetooth_2_usb.loopback.inject.run_inject", return_value=result) as run:
            with redirect_stdout(stdout):
                exit_code = run_loopback(["inject"])

        self.assertEqual(exit_code, 0)
        run.assert_called_once()
        self.assertIsNone(run.call_args.kwargs["event_gap_ms"])
        self.assertIsNone(run.call_args.kwargs["post_delay_ms"])

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

    def test_capture_cli_uses_scenario_default_timeout(self) -> None:
        result = SimpleNamespace(exit_code=0, to_dict=lambda: {}, to_text=lambda: "ok")

        with patch("bluetooth_2_usb.loopback.capture.run_capture", return_value=result) as run:
            exit_code = run_loopback(["capture", "--scenario", "keyboard"])

        self.assertEqual(exit_code, 0)
        self.assertIsNone(run.call_args.kwargs["timeout_sec"])

    def test_capture_uses_scenario_default_timeout(self) -> None:
        hid_module = _FakeHidModule(
            [
                _hid_entry(
                    "kbd0",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_KEYBOARD,
                    usage_page=HID_PAGE_GENERIC_DESKTOP,
                    usage=HID_USAGE_KEYBOARD,
                )
            ]
        )
        result = LoopbackResult(
            command="capture", scenario="keyboard", success=True, exit_code=0, message="ok", details={}
        )

        with patch("bluetooth_2_usb.loopback.capture._load_hidapi", return_value=hid_module):
            with patch("bluetooth_2_usb.loopback.capture._capture_once", return_value=result) as run:
                capture_result = run_capture("keyboard")

        self.assertIs(capture_result, result)
        self.assertEqual(run.call_args.kwargs["timeout_sec"], 15.0)

    def test_capture_timeout_reports_zero_progress(self) -> None:
        hid_module = _FakeReadableHidModule(
            [
                _hid_entry(
                    "kbd0",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_KEYBOARD,
                    usage_page=HID_PAGE_GENERIC_DESKTOP,
                    usage=HID_USAGE_KEYBOARD,
                )
            ],
            {"kbd0": []},
        )

        with patch("bluetooth_2_usb.loopback.capture._load_hidapi", return_value=hid_module):
            with patch("bluetooth_2_usb.loopback.capture.time.sleep"):
                result = run_capture("keyboard", timeout_sec=0.001)

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, EXIT_TIMEOUT)
        self.assertEqual(result.details["keyboard_steps_seen"], 0)
        self.assertEqual(result.details["keyboard_steps_expected"], len(SCENARIOS["keyboard"].keyboard_steps))
        self.assertEqual(result.details["summary"]["keyboard"], f"0/{len(SCENARIOS['keyboard'].keyboard_steps)}")
        self.assertEqual(result.details["progress"]["keyboard"][0]["node"], "kbd0")
        self.assertIn("next_expected", result.details["progress"]["keyboard"][0])

    def test_capture_timeout_reports_partial_keyboard_progress(self) -> None:
        hid_module = _FakeReadableHidModule(
            [
                _hid_entry(
                    "kbd0",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_KEYBOARD,
                    usage_page=HID_PAGE_GENERIC_DESKTOP,
                    usage=HID_USAGE_KEYBOARD,
                )
            ],
            {"kbd0": [_keyboard_report_for_code(KEY_K)]},
        )

        with patch("bluetooth_2_usb.loopback.capture._load_hidapi", return_value=hid_module):
            with patch("bluetooth_2_usb.loopback.capture.time.sleep"):
                result = run_capture("keyboard", timeout_sec=0.001)

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, EXIT_TIMEOUT)
        self.assertEqual(result.details["keyboard_steps_seen"], 1)
        self.assertIn("next_expected", result.details["progress"]["keyboard"][0])
        self.assertIn("KEY_K", result.details["progress"]["keyboard"][0]["next_expected"])

    def test_combo_timeout_reports_completed_and_incomplete_roles(self) -> None:
        hid_module = _FakeReadableHidModule(
            [
                _hid_entry(
                    "kbd0",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_KEYBOARD,
                    usage_page=HID_PAGE_GENERIC_DESKTOP,
                    usage=HID_USAGE_KEYBOARD,
                ),
                _hid_entry(
                    "mouse0",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_MOUSE,
                    usage_page=HID_PAGE_GENERIC_DESKTOP,
                    usage=HID_USAGE_MOUSE,
                ),
                _hid_entry(
                    "consumer0",
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_CONSUMER,
                    usage_page=HID_PAGE_CONSUMER,
                    usage=HID_USAGE_CONSUMER_CONTROL,
                ),
            ],
            {"kbd0": [_keyboard_report_for_code(ecodes.KEY_F13), bytes([0x00] * 8)], "mouse0": [], "consumer0": []},
        )

        with patch("bluetooth_2_usb.loopback.capture._load_hidapi", return_value=hid_module):
            with patch("bluetooth_2_usb.loopback.capture.time.sleep"):
                result = run_capture("node-discovery", timeout_sec=0.001)

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, EXIT_TIMEOUT)
        self.assertEqual(result.details["nodes"]["keyboard_node"], "kbd0")
        self.assertEqual(result.details["keyboard_steps_seen"], 2)
        self.assertEqual(result.details["mouse_rel_steps_seen"], 0)
        self.assertEqual(result.details["consumer_steps_seen"], 0)
        self.assertIn("complete", result.details["summary"]["keyboard"])
        self.assertIn("REL_X=1", result.details["progress"]["mouse"][0]["next_expected_rel"])

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

        with patch("bluetooth_2_usb.loopback.cli.loopback_session", side_effect=LoopbackBusyError("busy")):
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
                        vendor_id=USB_GADGET_VID_LINUX,
                        product_id=USB_GADGET_PID_COMBO,
                        interface_number=HID_FUNC_INDEX_KEYBOARD,
                        usage_page=HID_PAGE_GENERIC_DESKTOP,
                        usage=HID_USAGE_KEYBOARD,
                    ),
                    _hid_entry(
                        "mouse0",
                        vendor_id=USB_GADGET_VID_LINUX,
                        product_id=USB_GADGET_PID_COMBO,
                        interface_number=HID_FUNC_INDEX_MOUSE,
                        usage_page=HID_PAGE_GENERIC_DESKTOP,
                        usage=HID_USAGE_MOUSE,
                    ),
                    _hid_entry(
                        "consumer0",
                        vendor_id=USB_GADGET_VID_LINUX,
                        product_id=USB_GADGET_PID_COMBO,
                        interface_number=HID_FUNC_INDEX_CONSUMER,
                        usage_page=HID_PAGE_CONSUMER,
                        usage=HID_USAGE_CONSUMER_CONTROL,
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
                            vendor_id=USB_GADGET_VID_LINUX,
                            product_id=USB_GADGET_PID_COMBO,
                            interface_number=HID_FUNC_INDEX_KEYBOARD,
                            usage_page=HID_PAGE_GENERIC_DESKTOP,
                            usage=HID_USAGE_KEYBOARD,
                        ),
                        _hid_entry(
                            "mouse0",
                            vendor_id=USB_GADGET_VID_LINUX,
                            product_id=USB_GADGET_PID_COMBO,
                            interface_number=HID_FUNC_INDEX_MOUSE,
                            usage_page=HID_PAGE_GENERIC_DESKTOP,
                            usage=HID_USAGE_MOUSE,
                        ),
                        _hid_entry(
                            "consumer0",
                            vendor_id=USB_GADGET_VID_LINUX,
                            product_id=USB_GADGET_PID_COMBO,
                            interface_number=HID_FUNC_INDEX_CONSUMER,
                            usage_page=HID_PAGE_CONSUMER,
                            usage=HID_USAGE_CONSUMER_CONTROL,
                        ),
                    ]
                ),
            ):
                with patch(
                    "bluetooth_2_usb.loopback.capture_windows.run_raw_input_capture",
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
                    vendor_id=USB_GADGET_VID_LINUX,
                    product_id=USB_GADGET_PID_COMBO,
                    interface_number=HID_FUNC_INDEX_CONSUMER,
                    usage_page=HID_PAGE_CONSUMER,
                    usage=HID_USAGE_CONSUMER_CONTROL,
                )
            ]
        )

        with patch("bluetooth_2_usb.loopback.capture.sys.platform", "win32"):
            with patch("bluetooth_2_usb.loopback.capture._load_hidapi", return_value=consumer_hid):
                with patch(
                    "bluetooth_2_usb.loopback.capture_windows.run_raw_input_capture",
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


class LoopbackResultTest(unittest.TestCase):
    def test_to_text_renders_non_json_details_deterministically(self) -> None:
        result = LoopbackResult(
            command="capture",
            scenario="combo",
            success=False,
            exit_code=1,
            message="failed",
            details={"nested": {"node": Path("/tmp/hid")}, "paths": {1, "two"}},
        )

        text = result.to_text()

        self.assertIn('nested: {"node": "/tmp/hid"}', text)
        self.assertIn('paths: ["two", 1]', text)

    def test_to_dict_normalizes_details_for_json_output(self) -> None:
        result = LoopbackResult(
            command="capture",
            scenario="combo",
            success=True,
            exit_code=0,
            message="ok",
            details={
                "path": Path("/tmp/hidg0"),
                "nodes": {"keyboard": Path("/dev/hidg0")},
                "values": ("a", Path("/tmp/b")),
                "set": {2, "one"},
                "object": SimpleNamespace(value=Path("/tmp/hid")),
            },
        )

        output = result.to_dict()

        json.dumps(output, sort_keys=True)
        self.assertEqual(output["details"]["path"], "/tmp/hidg0")
        self.assertEqual(output["details"]["nodes"], {"keyboard": "/dev/hidg0"})
        self.assertEqual(output["details"]["values"], ["a", "/tmp/b"])
        self.assertEqual(output["details"]["set"], ["one", 2])
        self.assertEqual(output["details"]["object"], "namespace(value=PosixPath('/tmp/hid'))")
