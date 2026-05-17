from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from adafruit_hid.keycode import Keycode

from ..evdev import KeyEvent, evdev_to_usb_hid, is_consumer_key, is_mouse_button
from ..gadgets.identity import USB_GADGET_PID_COMBO, USB_GADGET_VID_LINUX
from ..gadgets.layout import (
    HID_FUNC_INDEX_CONSUMER,
    HID_FUNC_INDEX_DIGITIZER,
    HID_FUNC_INDEX_KEYBOARD,
    HID_FUNC_INDEX_MOUSE,
)
from ..hid.constants import (
    HID_PAGE_CONSUMER,
    HID_PAGE_DIGITIZER,
    HID_PAGE_GENERIC_DESKTOP,
    HID_USAGE_CONSUMER_CONTROL,
    HID_USAGE_DIGITIZER_PEN,
    HID_USAGE_DIGITIZER_TOUCH_PAD,
    HID_USAGE_KEYBOARD,
    HID_USAGE_MOUSE,
)
from ..inputs.filter import DeviceFilter, parse_devices
from .constants import EXIT_ACCESS, EXIT_MISMATCH, EXIT_OK, EXIT_PREREQUISITE, EXIT_TIMEOUT
from .result import GadgetNodes, LoopbackResult
from .scenarios import EV_REL, EVENT_CODE_NAMES, REL_HWHEEL, REL_WHEEL, REL_X, REL_Y, get_scenario

HIDAPI_REPORT_READ_SIZE = 64
HIDAPI_POLL_INTERVAL_SEC = 0.01


class CaptureError(RuntimeError):
    exit_code = EXIT_ACCESS


class MissingNodeError(CaptureError):
    exit_code = EXIT_PREREQUISITE


class CaptureTimeoutError(CaptureError):
    exit_code = EXIT_TIMEOUT


class CaptureMismatchError(CaptureError):
    exit_code = EXIT_MISMATCH


@dataclass(frozen=True, slots=True)
class HidDeviceInfo:
    node: str
    raw_path: bytes | str
    name: str
    manufacturer: str
    serial: str
    physical_path: str
    vendor_id: int
    product_id: int
    interface_number: int
    usage_page: int
    usage: int

    @property
    def path(self) -> str:
        return self.node

    @property
    def phys(self) -> str:
        return self.physical_path

    @property
    def uniq(self) -> str:
        return self.serial


def _rel_name(code: int) -> str:
    return EVENT_CODE_NAMES.get(EV_REL, {}).get(code, str(code))


@dataclass(frozen=True, slots=True)
class GadgetNodeCandidates:
    keyboard_nodes: tuple[HidDeviceInfo, ...]
    mouse_nodes: tuple[HidDeviceInfo, ...]
    consumer_nodes: tuple[HidDeviceInfo, ...]
    digitizer_nodes: tuple[HidDeviceInfo, ...] = ()

    def matched_nodes(
        self,
        keyboard_node: str | None = None,
        mouse_node: str | None = None,
        consumer_node: str | None = None,
        digitizer_node: str | None = None,
    ) -> GadgetNodes:
        return GadgetNodes(
            keyboard_node=keyboard_node,
            mouse_node=mouse_node,
            consumer_node=consumer_node,
            digitizer_node=digitizer_node,
        )

    def to_dict(self) -> dict[str, list[str]]:
        nodes = {
            "keyboard_nodes": [info.node for info in self.keyboard_nodes],
            "mouse_nodes": [info.node for info in self.mouse_nodes],
            "consumer_nodes": [info.node for info in self.consumer_nodes],
        }
        if self.digitizer_nodes:
            nodes["digitizer_nodes"] = [info.node for info in self.digitizer_nodes]
        return nodes


@dataclass(slots=True)
class KeyboardSequenceMatcher:
    expected_steps: tuple
    index: int = 0
    _modifier_state: int = 0
    _pressed_keys: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        self._pressed_keys = ()

    def handle(self, report: bytes) -> None:
        payload = _normalize_keyboard_report(report)
        if payload is None:
            if _is_ignorable_empty_report(report):
                return
            raise CaptureMismatchError(f"Unexpected keyboard report format: {report.hex(sep=' ')}")
        if self.index >= len(self.expected_steps):
            return

        if self.index > 0 and payload == self._current_payload():
            return

        expected = self.expected_steps[self.index]
        expected_payload = self._apply_expected_step(expected)
        if payload != expected_payload:
            raise CaptureMismatchError(
                f"Unexpected keyboard report {report.hex(sep=' ')}; expected {expected_payload.hex(sep=' ')}"
            )
        self.index += 1

    def _apply_expected_step(self, expected) -> bytes:
        hid_code = _expected_keyboard_usage(expected)
        modifier = Keycode.modifier_bit(hid_code)
        if expected.value == KeyEvent.key_down:
            if modifier:
                self._modifier_state |= modifier
            elif hid_code not in self._pressed_keys:
                self._pressed_keys = (*self._pressed_keys, hid_code)
        elif expected.value == KeyEvent.key_up:
            if modifier:
                self._modifier_state &= ~modifier
            else:
                self._pressed_keys = tuple(key for key in self._pressed_keys if key != hid_code)

        keys = list(self._pressed_keys[:6])
        keys.extend([0] * (6 - len(keys)))
        return bytes([self._modifier_state, 0, *keys])

    def _current_payload(self) -> bytes:
        keys = list(self._pressed_keys[:6])
        keys.extend([0] * (6 - len(keys)))
        return bytes([self._modifier_state, 0, *keys])

    @property
    def complete(self) -> bool:
        return self.index >= len(self.expected_steps)

    def progress_details(self) -> dict[str, object]:
        details: dict[str, object] = {
            "complete": self.complete,
            "steps_seen": self.index,
            "steps_expected": len(self.expected_steps),
        }
        if not self.complete:
            details["next_expected"] = self.expected_steps[self.index].describe()
        return details


@dataclass(slots=True)
class MouseSequenceMatcher:
    expected_rel_steps: tuple
    expected_button_steps: tuple
    rel_index: int = 0
    button_index: int = 0
    _button_state: int = 0
    _pending_rel_remaining: list[list[int]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._pending_rel_remaining = [[step.code, step.value] for step in self.expected_rel_steps]

    @classmethod
    def create(cls, expected_rel_steps: tuple, expected_button_steps: tuple):
        return cls(expected_rel_steps=expected_rel_steps, expected_button_steps=expected_button_steps)

    def handle(self, report: bytes) -> None:
        parsed = _normalize_mouse_report(report)
        if parsed is None:
            if _is_ignorable_empty_report(report):
                return
            raise CaptureMismatchError(f"Unexpected mouse report format: {report.hex(sep=' ')}")
        buttons, rel_x, rel_y, wheel, pan = parsed
        self._apply_button_report(buttons, report)

        rel_events = []
        if rel_x:
            rel_events.append((REL_X, rel_x))
        if rel_y:
            rel_events.append((REL_Y, rel_y))
        if wheel:
            rel_events.append((REL_WHEEL, wheel))
        if pan:
            rel_events.append((REL_HWHEEL, pan))
        if rel_events:
            self._apply_rel_report(rel_events)

    def _apply_button_report(self, buttons: int, report: bytes) -> None:
        if buttons == self._button_state:
            return
        if self.button_index >= len(self.expected_button_steps):
            raise CaptureMismatchError(f"Unexpected mouse button bits in report {report.hex(sep=' ')}")
        if not self.rel_complete:
            raise CaptureMismatchError("Mouse button report arrived before movement")

        expected = self.expected_button_steps[self.button_index]
        expected_buttons = self._apply_button_step(expected)
        if buttons != expected_buttons:
            raise CaptureMismatchError(
                f"Unexpected mouse button report {report.hex(sep=' ')}; expected {expected.describe()}"
            )
        self.button_index += 1

    def _apply_button_step(self, expected) -> int:
        event = SimpleNamespace(scancode=expected.code, keystate=expected.value)
        if not is_mouse_button(event):
            raise CaptureMismatchError(f"Expected mouse button step {expected.describe()} is not mappable to HID")
        button_bit = _mapped_hid_usage(expected)
        if expected.value == KeyEvent.key_down:
            self._button_state |= button_bit
        elif expected.value == KeyEvent.key_up:
            self._button_state &= ~button_bit
        return self._button_state

    def _apply_rel_report(self, rel_events: list[tuple[int, int]]) -> None:
        report_codes = {code for code, _value in rel_events}
        for code, value in rel_events:
            self._apply_rel(code, value, report_codes)

    def _apply_rel(self, code: int, value: int, report_codes: set[int]) -> None:
        pending_index = self._find_pending_rel_index(code, report_codes)
        if pending_index is None:
            expected = self._pending_rel_remaining[0] if self._pending_rel_remaining else None
            expected_label = f"; expected {_rel_name(expected[0])}={expected[1]}" if expected else ""
            raise CaptureMismatchError(f"Unexpected mouse relative event {_rel_name(code)}={value}{expected_label}")

        remaining = self._pending_rel_remaining[pending_index][1]
        if not _same_direction(remaining, value):
            raise CaptureMismatchError(
                f"Unexpected mouse relative event {_rel_name(code)}={value}; expected {_rel_name(code)}={remaining}"
            )

        if abs(value) > abs(remaining):
            raise CaptureMismatchError(
                f"Unexpected mouse relative event {_rel_name(code)}={value}; "
                f"exceeds pending {_rel_name(code)}={remaining}"
            )

        remaining -= value
        if remaining == 0:
            self.rel_index += 1
            self._pending_rel_remaining.pop(pending_index)
        else:
            self._pending_rel_remaining[pending_index][1] = remaining

    def _find_pending_rel_index(self, code: int, report_codes: set[int]) -> int | None:
        for index, (pending_code, _remaining) in enumerate(self._pending_rel_remaining):
            if pending_code not in report_codes:
                break
            if pending_code == code:
                return index
        return None

    @property
    def rel_complete(self) -> bool:
        return self.rel_index >= len(self.expected_rel_steps)

    @property
    def complete(self) -> bool:
        return self.rel_complete and self.button_index >= len(self.expected_button_steps)

    def progress_details(self) -> dict[str, object]:
        details: dict[str, object] = {
            "complete": self.complete,
            "rel_steps_seen": self.rel_index,
            "rel_steps_expected": len(self.expected_rel_steps),
            "button_steps_seen": self.button_index,
            "button_steps_expected": len(self.expected_button_steps),
        }
        if self._pending_rel_remaining:
            code, remaining = self._pending_rel_remaining[0]
            details["next_expected_rel"] = f"{_rel_name(code)}={remaining}"
        elif self.button_index < len(self.expected_button_steps):
            details["next_expected_button"] = self.expected_button_steps[self.button_index].describe()
        return details


def _same_direction(expected: int, observed: int) -> bool:
    if expected == 0:
        return observed == 0
    return (expected > 0 and observed > 0) or (expected < 0 and observed < 0)


@dataclass(slots=True)
class ConsumerSequenceMatcher:
    expected_steps: tuple
    index: int = 0

    def handle(self, report: bytes) -> None:
        usage = _normalize_consumer_report(report)
        if usage is None:
            if _is_ignorable_empty_report(report):
                return
            raise CaptureMismatchError(f"Unexpected consumer report format: {report.hex(sep=' ')}")
        if self.index >= len(self.expected_steps):
            return

        expected = self.expected_steps[self.index]
        expected_usage = _expected_consumer_usage(expected)
        if usage != expected_usage:
            raise CaptureMismatchError(f"Unexpected consumer usage 0x{usage:04x}; expected 0x{expected_usage:04x}")
        self.index += 1

    @property
    def complete(self) -> bool:
        return self.index >= len(self.expected_steps)

    def progress_details(self) -> dict[str, object]:
        details: dict[str, object] = {
            "complete": self.complete,
            "steps_seen": self.index,
            "steps_expected": len(self.expected_steps),
        }
        if not self.complete:
            details["next_expected"] = self.expected_steps[self.index].describe()
        return details


@dataclass(slots=True)
class DigitizerSequenceMatcher:
    expected_report_ids: tuple[int, ...]
    index: int = 0

    def __post_init__(self) -> None:
        if self.expected_report_ids != (1, 1, 2, 2, 3, 3):
            raise ValueError(
                "DigitizerSequenceMatcher expects the built-in touch, pen, and pad active/release sequence"
            )

    def handle(self, report: bytes) -> None:
        if not report:
            return
        report_id = report[0]
        if report_id == 0:
            return
        if self.complete:
            return
        expected_report_id = self.expected_report_ids[self.index]
        if report_id != expected_report_id:
            raise CaptureMismatchError(
                f"Unexpected digitizer report ID {report_id}; expected {expected_report_id}: {report.hex(sep=' ')}"
            )
        self._validate_payload(report_id, report[1:])
        self.index += 1

    def _validate_payload(self, report_id: int, payload: bytes) -> None:
        release = self.index % 2 == 1
        if report_id == 1:
            self._validate_touch_payload(payload, release=release)
        elif report_id == 2:
            self._validate_pen_payload(payload, release=release)
        elif report_id == 3:
            self._validate_pad_payload(payload, release=release)
        else:
            raise CaptureMismatchError(f"Unexpected digitizer report ID {report_id}")

    def _validate_touch_payload(self, payload: bytes, *, release: bool) -> None:
        if len(payload) < 49:
            raise CaptureMismatchError(f"Touch report is too short: {payload.hex(sep=' ')}")
        flags = payload[0]
        contact_id = payload[1]
        contact_count = payload[45]
        if release:
            if flags & 0x01 or contact_count != 0:
                raise CaptureMismatchError(
                    f"Touch release report still has active contact state: {payload.hex(sep=' ')}"
                )
        elif not flags & 0x01 or contact_id == 0 or contact_count == 0:
            raise CaptureMismatchError(f"Touch active report is missing contact state: {payload.hex(sep=' ')}")

    def _validate_pen_payload(self, payload: bytes, *, release: bool) -> None:
        if len(payload) < 15:
            raise CaptureMismatchError(f"Pen report is too short: {payload.hex(sep=' ')}")
        flags = payload[0]
        pressure = int.from_bytes(payload[5:7], "little")
        if release:
            if flags != 0 or pressure != 0:
                raise CaptureMismatchError(f"Pen release report still has active state: {payload.hex(sep=' ')}")
        elif flags & 0x0B != 0x0B or pressure == 0:
            raise CaptureMismatchError(
                f"Pen active report is missing tip/barrel/pressure state: {payload.hex(sep=' ')}"
            )

    def _validate_pad_payload(self, payload: bytes, *, release: bool) -> None:
        if len(payload) < 3:
            raise CaptureMismatchError(f"Pad report is too short: {payload.hex(sep=' ')}")
        buttons = int.from_bytes(payload[0:2], "little")
        wheel = int.from_bytes(payload[2:3], "little", signed=True)
        if release:
            if buttons != 0 or wheel != 0:
                raise CaptureMismatchError(f"Pad release report still has active state: {payload.hex(sep=' ')}")
        elif buttons == 0 or wheel == 0:
            raise CaptureMismatchError(f"Pad active report is missing button/wheel state: {payload.hex(sep=' ')}")

    @property
    def complete(self) -> bool:
        return self.index >= len(self.expected_report_ids)

    def progress_details(self) -> dict[str, object]:
        details: dict[str, object] = {
            "complete": self.complete,
            "steps_seen": self.index,
            "steps_expected": len(self.expected_report_ids),
        }
        if not self.complete:
            details["next_expected"] = f"digitizer report ID {self.expected_report_ids[self.index]}"
        return details


def _mapped_hid_usage(expected) -> int:
    usage, _name = evdev_to_usb_hid(SimpleNamespace(scancode=expected.code, keystate=expected.value))
    if usage is None:
        raise CaptureMismatchError(f"Expected step {expected.describe()} is not mappable to HID")
    return usage


def _expected_keyboard_usage(expected) -> int:
    event = SimpleNamespace(scancode=expected.code, keystate=expected.value)
    if is_consumer_key(event) or is_mouse_button(event):
        raise CaptureMismatchError(f"Expected keyboard step {expected.describe()} is not a keyboard key")
    return _mapped_hid_usage(expected)


def _expected_consumer_usage(expected) -> int:
    event = SimpleNamespace(scancode=expected.code, keystate=expected.value)
    if not is_consumer_key(event):
        raise CaptureMismatchError(f"Expected consumer step {expected.describe()} is not a consumer key")
    usage = _mapped_hid_usage(expected)
    return usage if expected.value == KeyEvent.key_down else 0


@dataclass(slots=True)
class _CandidateMatcher:
    role: str
    info: HidDeviceInfo
    device: Any
    matcher: KeyboardSequenceMatcher | MouseSequenceMatcher | ConsumerSequenceMatcher | DigitizerSequenceMatcher
    failed_message: str | None = None

    @property
    def node(self) -> str:
        return self.info.node

    @property
    def complete(self) -> bool:
        return self.matcher.complete

    @property
    def failed(self) -> bool:
        return self.failed_message is not None


def matcher_progress_details(
    matcher: KeyboardSequenceMatcher | MouseSequenceMatcher | ConsumerSequenceMatcher | DigitizerSequenceMatcher,
) -> dict[str, object]:
    return matcher.progress_details()


def candidate_progress_details(
    *,
    node: str | None,
    matcher: KeyboardSequenceMatcher | MouseSequenceMatcher | ConsumerSequenceMatcher | DigitizerSequenceMatcher,
    failed_message: str | None = None,
) -> dict[str, object]:
    details: dict[str, object] = {"node": node}
    details.update(matcher_progress_details(matcher))
    if failed_message is not None:
        details["failed_message"] = failed_message
    return details


def _candidate_progress(candidate: _CandidateMatcher) -> dict[str, object]:
    return candidate_progress_details(
        node=candidate.node, matcher=candidate.matcher, failed_message=candidate.failed_message
    )


def _candidate_progress_score(progress: dict[str, object]) -> int:
    if "steps_seen" in progress:
        return int(progress["steps_seen"])
    return int(progress.get("rel_steps_seen", 0)) + int(progress.get("button_steps_seen", 0))


def _progress_by_role(candidates: list[_CandidateMatcher]) -> dict[str, list[dict[str, object]]]:
    progress: dict[str, list[dict[str, object]]] = {}
    for candidate in candidates:
        progress.setdefault(candidate.role, []).append(_candidate_progress(candidate))
    return progress


def _role_summary(role: str, progress_items: list[dict[str, object]]) -> str:
    if not progress_items:
        return "0 candidates"
    progress = max(progress_items, key=_candidate_progress_score)
    if role == "mouse":
        rel_seen = progress["rel_steps_seen"]
        rel_expected = progress["rel_steps_expected"]
        button_seen = progress["button_steps_seen"]
        button_expected = progress["button_steps_expected"]
        suffix = " complete" if progress["complete"] else ""
        return f"{rel_seen}/{rel_expected} rel, {button_seen}/{button_expected} buttons{suffix}"
    suffix = " complete" if progress["complete"] else ""
    return f"{progress['steps_seen']}/{progress['steps_expected']}{suffix}"


def _add_best_progress_counts(details: dict[str, object], role: str, progress_items: list[dict[str, object]]) -> None:
    if not progress_items:
        return
    progress = max(progress_items, key=_candidate_progress_score)
    if role == "keyboard":
        details["keyboard_steps_seen"] = progress["steps_seen"]
        details["keyboard_steps_expected"] = progress["steps_expected"]
    elif role == "mouse":
        details["mouse_rel_steps_seen"] = progress["rel_steps_seen"]
        details["mouse_rel_steps_expected"] = progress["rel_steps_expected"]
        details["mouse_button_steps_seen"] = progress["button_steps_seen"]
        details["mouse_button_steps_expected"] = progress["button_steps_expected"]
    elif role == "consumer":
        details["consumer_steps_seen"] = progress["steps_seen"]
        details["consumer_steps_expected"] = progress["steps_expected"]
    elif role == "digitizer":
        details["digitizer_reports_seen"] = progress["steps_seen"]
        details["digitizer_reports_expected"] = progress["steps_expected"]


def _nodes_from_progress(progress: dict[str, list[dict[str, object]]]) -> GadgetNodes:
    def _completed_node(role: str) -> str | None:
        for candidate in progress.get(role, []):
            if candidate.get("complete"):
                node = candidate.get("node")
                return str(node) if node is not None else None
        return None

    return GadgetNodes(
        keyboard_node=_completed_node("keyboard"),
        mouse_node=_completed_node("mouse"),
        consumer_node=_completed_node("consumer"),
        digitizer_node=_completed_node("digitizer"),
    )


def progress_summary_details(progress: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    details: dict[str, object] = {}
    summary: dict[str, str] = {}
    for role in ("keyboard", "mouse", "consumer", "digitizer"):
        progress_items = progress.get(role, [])
        if not progress_items:
            continue
        summary[role] = _role_summary(role, progress_items)
        _add_best_progress_counts(details, role, progress_items)
    if summary:
        details["summary"] = summary
        details["progress"] = progress
    return details


def _capture_failure_details(
    timeout_sec: float, candidate_nodes: GadgetNodeCandidates, candidates: list[_CandidateMatcher]
) -> dict[str, object]:
    progress = _progress_by_role(candidates)
    details: dict[str, object] = {
        "capture_backend": "hidapi",
        "candidates": candidate_nodes.to_dict(),
        "nodes": _nodes_from_progress(progress).to_dict(),
        "timeout_sec": timeout_sec,
    }
    details.update(progress_summary_details(progress))
    failed_candidates = [candidate.failed_message for candidate in candidates if candidate.failed_message is not None]
    if failed_candidates:
        details["failed_candidates"] = failed_candidates
    return details


def _normalize_keyboard_report(report: bytes) -> bytes | None:
    if len(report) == 8:
        return report
    if len(report) == 9 and report[0] == 0x01:
        return report[1:]
    return None


def _normalize_mouse_report(report: bytes) -> tuple[int, int, int, int, int] | None:
    if len(report) in (8, 9):
        report = report[-7:]
    if len(report) != 7:
        return None

    buttons = report[0]
    rel_x = int.from_bytes(report[1:3], "little", signed=True)
    rel_y = int.from_bytes(report[3:5], "little", signed=True)
    wheel = int.from_bytes(report[5:6], "little", signed=True)
    pan = int.from_bytes(report[6:7], "little", signed=True)
    return buttons, rel_x, rel_y, wheel, pan


def _normalize_consumer_report(report: bytes) -> int | None:
    if len(report) == 3 and report[0] == 0x03:
        return int.from_bytes(report[1:3], "little")
    if len(report) == 3 and report[0] == 0x00:
        return int.from_bytes(report[1:3], "little")
    if len(report) == 2 and report[0] == 0x03:
        return report[1]
    if len(report) == 2:
        return int.from_bytes(report, "little")
    return None


def _is_ignorable_empty_report(report: bytes) -> bool:
    return len(report) == 1 and report[0] == 0


def _load_hidapi() -> Any:
    try:
        import hid  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise MissingNodeError(
            "Host capture requires the Python package 'hidapi' (import name: hid). "
            + "Install it in the host Python environment."
        ) from exc
    return hid


def _render_hidapi_path(path_value: bytes | str) -> str:
    if isinstance(path_value, bytes):
        return path_value.decode("utf-8", errors="backslashreplace")
    return str(path_value)


def _role_for_device(info: HidDeviceInfo) -> str | None:
    if info.usage_page == HID_PAGE_GENERIC_DESKTOP and info.usage == HID_USAGE_KEYBOARD:
        return "keyboard"
    if info.usage_page == HID_PAGE_GENERIC_DESKTOP and info.usage == HID_USAGE_MOUSE:
        return "mouse"
    if info.usage_page == HID_PAGE_CONSUMER and info.usage == HID_USAGE_CONSUMER_CONTROL:
        return "consumer"
    if info.usage_page == HID_PAGE_DIGITIZER and info.usage in (HID_USAGE_DIGITIZER_TOUCH_PAD, HID_USAGE_DIGITIZER_PEN):
        return "digitizer"
    if info.vendor_id == USB_GADGET_VID_LINUX and info.product_id == USB_GADGET_PID_COMBO:
        if info.interface_number == HID_FUNC_INDEX_KEYBOARD:
            return "keyboard"
        if info.interface_number == HID_FUNC_INDEX_MOUSE:
            return "mouse"
        if info.interface_number == HID_FUNC_INDEX_CONSUMER:
            return "consumer"
        if info.interface_number == HID_FUNC_INDEX_DIGITIZER:
            return "digitizer"
    return None


def _iter_hid_infos(hid_module: Any) -> list[HidDeviceInfo]:
    infos: list[HidDeviceInfo] = []
    for entry in hid_module.enumerate():
        raw_path = entry.get("path")
        if raw_path is None:
            continue
        node = _render_hidapi_path(raw_path)
        infos.append(
            HidDeviceInfo(
                node=node,
                raw_path=raw_path,
                name=entry.get("product_string") or "",
                manufacturer=entry.get("manufacturer_string") or "",
                serial=entry.get("serial_number") or "",
                physical_path=_render_hidapi_path(entry.get("phys") or entry.get("physical_path") or node),
                vendor_id=int(entry.get("vendor_id") or 0),
                product_id=int(entry.get("product_id") or 0),
                interface_number=int(entry.get("interface_number") or 0),
                usage_page=int(entry.get("usage_page") or 0),
                usage=int(entry.get("usage") or 0),
            )
        )
    return infos


def discover_gadget_node_candidates(devices: str, hid_module: Any | None = None) -> GadgetNodeCandidates:
    hid_module = _load_hidapi() if hid_module is None else hid_module
    infos = _iter_hid_infos(hid_module)
    if not devices.strip():
        raise MissingNodeError("devices must not be empty")
    try:
        device_filters = [DeviceFilter(device) for device in parse_devices(devices)]
    except ValueError as exc:
        raise MissingNodeError(f"Invalid devices filter {devices!r}: {exc}") from exc

    keyboard_nodes: list[HidDeviceInfo] = []
    mouse_nodes: list[HidDeviceInfo] = []
    consumer_nodes: list[HidDeviceInfo] = []
    digitizer_nodes: list[HidDeviceInfo] = []

    for info in infos:
        role = _role_for_device(info)
        if role is None:
            continue
        if not any(device_filter.matches(info) for device_filter in device_filters):
            continue
        if role == "keyboard":
            keyboard_nodes.append(info)
        elif role == "mouse":
            mouse_nodes.append(info)
        elif role == "consumer":
            consumer_nodes.append(info)
        elif role == "digitizer":
            digitizer_nodes.append(info)

    if not keyboard_nodes and not mouse_nodes and not consumer_nodes and not digitizer_nodes:
        raise MissingNodeError(f"No HID devices matched {devices!r} through hidapi enumeration")

    return GadgetNodeCandidates(
        keyboard_nodes=tuple(sorted(keyboard_nodes, key=lambda info: info.node)),
        mouse_nodes=tuple(sorted(mouse_nodes, key=lambda info: info.node)),
        consumer_nodes=tuple(sorted(consumer_nodes, key=lambda info: info.node)),
        digitizer_nodes=tuple(sorted(digitizer_nodes, key=lambda info: info.node)),
    )


def discover_gadget_nodes(devices: str, hid_module: Any | None = None) -> GadgetNodes:
    candidates = discover_gadget_node_candidates(devices=devices, hid_module=hid_module)
    if len(candidates.keyboard_nodes) > 1:
        raise MissingNodeError(
            "Multiple keyboard HID devices matched: " + ", ".join(info.node for info in candidates.keyboard_nodes)
        )
    if len(candidates.mouse_nodes) > 1:
        raise MissingNodeError(
            "Multiple mouse HID devices matched: " + ", ".join(info.node for info in candidates.mouse_nodes)
        )
    if len(candidates.consumer_nodes) > 1:
        raise MissingNodeError(
            "Multiple consumer-control HID devices matched: "
            + ", ".join(info.node for info in candidates.consumer_nodes)
        )
    if len(candidates.digitizer_nodes) > 1:
        raise MissingNodeError(
            "Multiple digitizer HID devices matched: " + ", ".join(info.node for info in candidates.digitizer_nodes)
        )

    return GadgetNodes(
        keyboard_node=(candidates.keyboard_nodes[0].node if candidates.keyboard_nodes else None),
        mouse_node=candidates.mouse_nodes[0].node if candidates.mouse_nodes else None,
        consumer_node=(candidates.consumer_nodes[0].node if candidates.consumer_nodes else None),
        digitizer_node=(candidates.digitizer_nodes[0].node if candidates.digitizer_nodes else None),
    )


def _open_hid_device(hid_module: Any, info: HidDeviceInfo) -> Any:
    try:
        device = hid_module.device()
        device.open_path(info.raw_path)
        device.set_nonblocking(True)
        return device
    except OSError as exc:
        if info.vendor_id == USB_GADGET_VID_LINUX and info.product_id == USB_GADGET_PID_COMBO:
            raise CaptureError(
                f"Failed opening HID device {info.node}: {exc}. "
                + 'On Linux, run `sudo ./venv/bin/bluetooth_2_usb udev install --repo-root "$PWD"` '
                + "from the repository root, or for a managed install run `sudo bluetooth_2_usb udev install`. "
                + "Reconnect the Pi, and ensure the user is in the input group with "
                + "`sudo usermod -aG input $USER` before starting a new login session."
            ) from exc
        raise CaptureError(f"Failed opening HID device {info.node}: {exc}") from exc
    except Exception as exc:
        raise CaptureError(f"Failed opening HID device {info.node}: {exc}") from exc


def _capture_once(
    scenario_name: str, timeout_sec: float, candidate_nodes: GadgetNodeCandidates, hid_module: Any
) -> LoopbackResult:
    scenario = get_scenario(scenario_name)

    candidates: list[_CandidateMatcher] = []

    def _active_candidates(role: str) -> list[_CandidateMatcher]:
        return [candidate for candidate in candidates if candidate.role == role and not candidate.failed]

    def _completed_candidate(role: str) -> _CandidateMatcher | None:
        for candidate in candidates:
            if candidate.role == role and candidate.complete:
                return candidate
        return None

    def _register_candidate(
        role: str,
        info: HidDeviceInfo,
        matcher: KeyboardSequenceMatcher | MouseSequenceMatcher | ConsumerSequenceMatcher | DigitizerSequenceMatcher,
    ) -> None:
        candidates.append(
            _CandidateMatcher(role=role, info=info, device=_open_hid_device(hid_module, info), matcher=matcher)
        )

    def _required_role_done(role: str) -> bool:
        if role == "keyboard":
            return not scenario.keyboard_enabled or _completed_candidate(role) is not None
        if role == "mouse":
            return not scenario.mouse_enabled or _completed_candidate(role) is not None
        if role == "consumer":
            return not scenario.consumer_enabled or _completed_candidate(role) is not None
        if role == "digitizer":
            return not scenario.digitizer_enabled or _completed_candidate(role) is not None
        raise AssertionError(f"Unexpected role: {role}")

    try:
        if scenario.keyboard_enabled:
            if not candidate_nodes.keyboard_nodes:
                raise MissingNodeError("Keyboard HID device was not found")
            for info in candidate_nodes.keyboard_nodes:
                _register_candidate("keyboard", info, KeyboardSequenceMatcher(scenario.keyboard_steps))

        if scenario.mouse_enabled:
            if not candidate_nodes.mouse_nodes:
                raise MissingNodeError("Mouse HID device was not found")
            for info in candidate_nodes.mouse_nodes:
                _register_candidate(
                    "mouse", info, MouseSequenceMatcher.create(scenario.mouse_rel_steps, scenario.mouse_button_steps)
                )

        if scenario.consumer_enabled:
            if not candidate_nodes.consumer_nodes:
                raise MissingNodeError("Consumer-control HID device was not found")
            for info in candidate_nodes.consumer_nodes:
                _register_candidate("consumer", info, ConsumerSequenceMatcher(scenario.consumer_steps))

        if scenario.digitizer_enabled:
            if not candidate_nodes.digitizer_nodes:
                raise MissingNodeError("Digitizer HID device was not found")
            for info in candidate_nodes.digitizer_nodes:
                _register_candidate("digitizer", info, DigitizerSequenceMatcher(scenario.digitizer_report_ids))

        deadline = time.monotonic() + timeout_sec
        while True:
            if (
                _required_role_done("keyboard")
                and _required_role_done("mouse")
                and _required_role_done("consumer")
                and _required_role_done("digitizer")
            ):
                break

            for role, enabled in (
                ("keyboard", scenario.keyboard_enabled),
                ("mouse", scenario.mouse_enabled),
                ("consumer", scenario.consumer_enabled),
                ("digitizer", scenario.digitizer_enabled),
            ):
                if not enabled:
                    continue
                if _active_candidates(role):
                    continue
                messages = [
                    candidate.failed_message
                    for candidate in candidates
                    if candidate.role == role and candidate.failed_message
                ]
                raise CaptureMismatchError(f"All {role} HID candidates mismatched: " + "; ".join(messages))

            if time.monotonic() >= deadline:
                raise CaptureTimeoutError(f"Timed out waiting for {scenario.name} reports after {timeout_sec}s")

            progress = False
            for candidate in candidates:
                if candidate.failed or candidate.complete:
                    continue
                try:
                    report_values = candidate.device.read(HIDAPI_REPORT_READ_SIZE)
                except OSError as exc:
                    raise CaptureError(f"Failed reading HID reports from {candidate.node}: {exc}") from exc
                except Exception as exc:
                    raise CaptureError(f"Failed reading HID reports from {candidate.node}: {exc}") from exc

                if not report_values:
                    continue

                progress = True
                report = bytes(report_values)
                try:
                    candidate.matcher.handle(report)
                except CaptureMismatchError as exc:
                    candidate.failed_message = f"{candidate.node}: {exc}"

            if not progress:
                time.sleep(HIDAPI_POLL_INTERVAL_SEC)

    except CaptureError as exc:
        return LoopbackResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details=_capture_failure_details(timeout_sec, candidate_nodes, candidates),
        )
    finally:
        for candidate in candidates:
            try:
                candidate.device.close()
            except Exception:
                pass

    keyboard_matcher = _completed_candidate("keyboard")
    mouse_matcher = _completed_candidate("mouse")
    consumer_matcher = _completed_candidate("consumer")
    matched_nodes = candidate_nodes.matched_nodes(
        keyboard_node=keyboard_matcher.node if keyboard_matcher else None,
        mouse_node=mouse_matcher.node if mouse_matcher else None,
        consumer_node=consumer_matcher.node if consumer_matcher else None,
        digitizer_node=(_completed_candidate("digitizer").node if _completed_candidate("digitizer") else None),
    )
    details: dict[str, object] = {
        "capture_backend": "hidapi",
        "candidates": candidate_nodes.to_dict(),
        "nodes": matched_nodes.to_dict(),
        "timeout_sec": timeout_sec,
    }
    if keyboard_matcher is not None:
        details["keyboard_steps_seen"] = keyboard_matcher.matcher.index
    if mouse_matcher is not None:
        details["mouse_rel_steps_seen"] = mouse_matcher.matcher.rel_index
        details["mouse_button_steps_seen"] = mouse_matcher.matcher.button_index
    if consumer_matcher is not None:
        details["consumer_steps_seen"] = consumer_matcher.matcher.index
    digitizer_matcher = _completed_candidate("digitizer")
    if digitizer_matcher is not None:
        details["digitizer_reports_seen"] = digitizer_matcher.matcher.index

    return LoopbackResult(
        command="capture",
        scenario=scenario.name,
        success=True,
        exit_code=EXIT_OK,
        message="Observed expected relay reports on gadget HID devices",
        details=details,
    )


def run_capture(scenario_name: str, devices: str, timeout_sec: float | None = None) -> LoopbackResult:
    scenario = get_scenario(scenario_name)
    resolved_timeout_sec = scenario.default_capture_timeout_sec if timeout_sec is None else timeout_sec

    try:
        hid_module = _load_hidapi()
        candidate_nodes = discover_gadget_node_candidates(devices=devices, hid_module=hid_module)
    except CaptureError as exc:
        return LoopbackResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details={},
        )

    if sys.platform == "win32":
        from .capture_windows import run_raw_input_capture

        result = run_raw_input_capture(
            scenario_name=scenario_name, timeout_sec=resolved_timeout_sec, candidate_nodes=candidate_nodes
        )
        result.details["candidates"] = candidate_nodes.to_dict()
        return result

    result = _capture_once(
        scenario_name=scenario_name,
        timeout_sec=resolved_timeout_sec,
        candidate_nodes=candidate_nodes,
        hid_module=hid_module,
    )
    result.details["candidates"] = candidate_nodes.to_dict()
    return result
