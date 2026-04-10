from __future__ import annotations

import os
import selectors
import time
from dataclasses import dataclass
from pathlib import Path

from evdev import ecodes

from .test_harness_common import (
    DEFAULT_DEVICE_SUBSTRING,
    EXIT_ACCESS,
    EXIT_MISMATCH,
    EXIT_OK,
    EXIT_PREREQUISITE,
    EXIT_TIMEOUT,
    GadgetNodes,
    HarnessResult,
    ensure_existing_path,
    get_scenario,
)

HIDRAW_ROOT = Path("/sys/class/hidraw")
REPORT_READ_SIZE = 64

HID_KEY_CODES = {
    ecodes.KEY_A: 4,
    ecodes.KEY_B: 5,
    ecodes.KEY_C: 6,
}

CONSUMER_USAGES = {
    ecodes.KEY_VOLUMEUP: 0x00E9,
    ecodes.KEY_VOLUMEDOWN: 0x00EA,
}


class CaptureError(RuntimeError):
    exit_code = EXIT_ACCESS


class MissingNodeError(CaptureError):
    exit_code = EXIT_PREREQUISITE


class CaptureTimeoutError(CaptureError):
    exit_code = EXIT_TIMEOUT


class CaptureMismatchError(CaptureError):
    exit_code = EXIT_MISMATCH


@dataclass(frozen=True, slots=True)
class GadgetNodeCandidates:
    keyboard_nodes: tuple[str, ...]
    mouse_nodes: tuple[str, ...]
    consumer_nodes: tuple[str, ...]

    def matched_nodes(
        self,
        keyboard_node: str | None = None,
        mouse_node: str | None = None,
        consumer_node: str | None = None,
    ) -> GadgetNodes:
        return GadgetNodes(
            keyboard_node=keyboard_node,
            mouse_node=mouse_node,
            consumer_node=consumer_node,
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "keyboard_nodes": list(self.keyboard_nodes),
            "mouse_nodes": list(self.mouse_nodes),
            "consumer_nodes": list(self.consumer_nodes),
        }


@dataclass(frozen=True, slots=True)
class HidrawInfo:
    node: str
    name: str
    phys: str
    uniq: str


@dataclass(slots=True)
class KeyboardSequenceMatcher:
    expected_steps: tuple
    index: int = 0

    def handle(self, report: bytes) -> None:
        payload = _normalize_keyboard_report(report)
        if payload is None:
            raise CaptureMismatchError(
                f"Unexpected keyboard report format: {report.hex(sep=' ')}"
            )
        if self.index >= len(self.expected_steps):
            return

        expected = self.expected_steps[self.index]
        if expected.value == 1:
            hid_code = HID_KEY_CODES[expected.code]
            pressed = tuple(code for code in payload[2:] if code)
            if pressed != (hid_code,):
                raise CaptureMismatchError(
                    f"Unexpected keyboard report {report.hex(sep=' ')}; expected key {hid_code}"
                )
        else:
            if any(payload):
                raise CaptureMismatchError(
                    f"Unexpected keyboard release report {report.hex(sep=' ')}"
                )
        self.index += 1

    @property
    def complete(self) -> bool:
        return self.index >= len(self.expected_steps)


@dataclass(slots=True)
class MouseSequenceMatcher:
    expected_rel_steps: tuple
    expected_button_steps: tuple
    rel_progress: dict[int, int]
    button_index: int = 0

    @classmethod
    def create(cls, expected_rel_steps: tuple, expected_button_steps: tuple):
        return cls(
            expected_rel_steps=expected_rel_steps,
            expected_button_steps=expected_button_steps,
            rel_progress={step.code: 0 for step in expected_rel_steps},
        )

    def handle(self, report: bytes) -> None:
        parsed = _normalize_mouse_report(report)
        if parsed is None:
            raise CaptureMismatchError(
                f"Unexpected mouse report format: {report.hex(sep=' ')}"
            )
        buttons, rel_x, rel_y, wheel = parsed
        if wheel != 0:
            raise CaptureMismatchError(
                f"Unexpected mouse wheel movement in report {report.hex(sep=' ')}"
            )

        if rel_x:
            self._apply_rel(ecodes.REL_X, rel_x)
        if rel_y:
            self._apply_rel(ecodes.REL_Y, rel_y)

        if buttons not in (0, 1):
            raise CaptureMismatchError(
                f"Unexpected mouse button bits in report {report.hex(sep=' ')}"
            )

        if rel_x == 0 and rel_y == 0:
            if self.button_index >= len(self.expected_button_steps):
                if buttons == 0:
                    return
                raise CaptureMismatchError(
                    f"Unexpected extra mouse button report {report.hex(sep=' ')}"
                )

            if not self.rel_complete:
                if buttons != 0:
                    raise CaptureMismatchError(
                        "Mouse button report arrived before movement"
                    )
                return

            expected = self.expected_button_steps[self.button_index]
            if buttons != expected.value:
                raise CaptureMismatchError(
                    f"Unexpected mouse button report {report.hex(sep=' ')}; expected {expected.describe()}"
                )
            self.button_index += 1

    def _apply_rel(self, code: int, value: int) -> None:
        if code not in self.rel_progress:
            raise CaptureMismatchError(f"Unexpected mouse relative event code {code}")
        self.rel_progress[code] += value
        expected_total = next(
            step.value for step in self.expected_rel_steps if step.code == code
        )
        if self.rel_progress[code] > expected_total:
            raise CaptureMismatchError(
                f"Mouse movement for code {code} exceeded expected total"
            )

    @property
    def rel_complete(self) -> bool:
        for step in self.expected_rel_steps:
            if self.rel_progress.get(step.code, 0) != step.value:
                return False
        return True

    @property
    def complete(self) -> bool:
        return self.rel_complete and self.button_index >= len(
            self.expected_button_steps
        )


@dataclass(slots=True)
class ConsumerSequenceMatcher:
    expected_steps: tuple
    index: int = 0

    def handle(self, report: bytes) -> None:
        usage = _normalize_consumer_report(report)
        if usage is None:
            raise CaptureMismatchError(
                f"Unexpected consumer report format: {report.hex(sep=' ')}"
            )
        if self.index >= len(self.expected_steps):
            return

        expected = self.expected_steps[self.index]
        expected_usage = CONSUMER_USAGES[expected.code] if expected.value == 1 else 0
        if usage != expected_usage:
            raise CaptureMismatchError(
                f"Unexpected consumer usage 0x{usage:04x}; expected 0x{expected_usage:04x}"
            )
        self.index += 1

    @property
    def complete(self) -> bool:
        return self.index >= len(self.expected_steps)


def _normalize_keyboard_report(report: bytes) -> bytes | None:
    if len(report) == 8:
        return report
    if len(report) == 9 and report[0] == 0x01:
        return report[1:]
    return None


def _normalize_mouse_report(report: bytes) -> tuple[int, int, int, int] | None:
    payload = report
    if len(report) == 5 and report[0] == 0x02:
        payload = report[1:]
    elif len(report) != 4:
        return None

    buttons = payload[0]
    rel_x = int.from_bytes(payload[1:2], "little", signed=True)
    rel_y = int.from_bytes(payload[2:3], "little", signed=True)
    wheel = int.from_bytes(payload[3:4], "little", signed=True)
    return buttons, rel_x, rel_y, wheel


def _normalize_consumer_report(report: bytes) -> int | None:
    if len(report) == 3 and report[0] == 0x03:
        return int.from_bytes(report[1:3], "little")
    if len(report) == 2:
        return int.from_bytes(report, "little")
    return None


def _matches_device_substring(device_name: str, substring: str) -> bool:
    candidates = {
        substring.lower(),
        substring.replace("_", " ").lower(),
        substring.replace("_", "-").lower(),
    }
    haystack = device_name.lower()
    return any(candidate and candidate in haystack for candidate in candidates)


def _read_uevent(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _iter_hidraw_infos(hidraw_root: Path) -> list[HidrawInfo]:
    infos: list[HidrawInfo] = []
    for hidraw_dir in sorted(hidraw_root.glob("hidraw*")):
        uevent_path = hidraw_dir / "device" / "uevent"
        if not uevent_path.is_file():
            continue
        values = _read_uevent(uevent_path)
        infos.append(
            HidrawInfo(
                node=f"/dev/{hidraw_dir.name}",
                name=values.get("HID_NAME", ""),
                phys=values.get("HID_PHYS", ""),
                uniq=values.get("HID_UNIQ", ""),
            )
        )
    return infos


def _role_for_hidraw(info: HidrawInfo) -> str | None:
    if info.phys.endswith("/input0"):
        return "keyboard"
    if info.phys.endswith("/input1"):
        return "mouse"
    if info.phys.endswith("/input2"):
        return "consumer"
    return None


def discover_gadget_node_candidates(
    device_substring: str = DEFAULT_DEVICE_SUBSTRING,
    keyboard_node: str | None = None,
    mouse_node: str | None = None,
    consumer_node: str | None = None,
    hidraw_root: Path = HIDRAW_ROOT,
) -> GadgetNodeCandidates:
    explicit_keyboard = ensure_existing_path(keyboard_node, "keyboard hidraw node")
    explicit_mouse = ensure_existing_path(mouse_node, "mouse hidraw node")
    explicit_consumer = ensure_existing_path(consumer_node, "consumer hidraw node")

    keyboard_nodes: set[str] = (
        {str(explicit_keyboard.resolve())} if explicit_keyboard else set()
    )
    mouse_nodes: set[str] = {str(explicit_mouse.resolve())} if explicit_mouse else set()
    consumer_nodes: set[str] = (
        {str(explicit_consumer.resolve())} if explicit_consumer else set()
    )

    if not hidraw_root.is_dir():
        raise MissingNodeError(f"Hidraw sysfs directory is missing: {hidraw_root}")

    for info in _iter_hidraw_infos(hidraw_root):
        if not _matches_device_substring(info.name, device_substring):
            continue
        role = _role_for_hidraw(info)
        if role == "keyboard" and not explicit_keyboard:
            keyboard_nodes.add(info.node)
        elif role == "mouse" and not explicit_mouse:
            mouse_nodes.add(info.node)
        elif role == "consumer" and not explicit_consumer:
            consumer_nodes.add(info.node)

    if not keyboard_nodes and not mouse_nodes and not consumer_nodes:
        raise MissingNodeError(
            f"No hidraw gadget nodes matched {device_substring!r} in {hidraw_root}"
        )

    return GadgetNodeCandidates(
        keyboard_nodes=tuple(sorted(keyboard_nodes)),
        mouse_nodes=tuple(sorted(mouse_nodes)),
        consumer_nodes=tuple(sorted(consumer_nodes)),
    )


def discover_gadget_nodes(
    device_substring: str = DEFAULT_DEVICE_SUBSTRING,
    keyboard_node: str | None = None,
    mouse_node: str | None = None,
    consumer_node: str | None = None,
    hidraw_root: Path = HIDRAW_ROOT,
) -> GadgetNodes:
    candidates = discover_gadget_node_candidates(
        device_substring=device_substring,
        keyboard_node=keyboard_node,
        mouse_node=mouse_node,
        consumer_node=consumer_node,
        hidraw_root=hidraw_root,
    )
    if len(candidates.keyboard_nodes) > 1:
        raise MissingNodeError(
            "Multiple keyboard hidraw nodes matched: "
            + ", ".join(sorted(candidates.keyboard_nodes))
        )
    if len(candidates.mouse_nodes) > 1:
        raise MissingNodeError(
            "Multiple mouse hidraw nodes matched: "
            + ", ".join(sorted(candidates.mouse_nodes))
        )
    if len(candidates.consumer_nodes) > 1:
        raise MissingNodeError(
            "Multiple consumer hidraw nodes matched: "
            + ", ".join(sorted(candidates.consumer_nodes))
        )

    return GadgetNodes(
        keyboard_node=next(iter(candidates.keyboard_nodes), None),
        mouse_node=next(iter(candidates.mouse_nodes), None),
        consumer_node=next(iter(candidates.consumer_nodes), None),
    )


def _open_hidraw(node: str) -> int:
    try:
        return os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError as exc:
        raise MissingNodeError(f"Hidraw node does not exist: {node}") from exc
    except PermissionError as exc:
        raise CaptureError(
            f"Failed opening hidraw node {node}: {exc}. Install the host rule with "
            "./scripts/install_host_hidraw_udev_rule.sh and ensure the user is in the input group."
        ) from exc
    except OSError as exc:
        raise CaptureError(f"Failed opening hidraw node {node}: {exc}") from exc


@dataclass(slots=True)
class _CandidateMatcher:
    role: str
    node: str
    fd: int
    matcher: KeyboardSequenceMatcher | MouseSequenceMatcher | ConsumerSequenceMatcher
    failed_message: str | None = None

    @property
    def complete(self) -> bool:
        return self.matcher.complete

    @property
    def failed(self) -> bool:
        return self.failed_message is not None


def run_capture(
    scenario_name: str,
    timeout_sec: float = 5.0,
    device_substring: str = DEFAULT_DEVICE_SUBSTRING,
    keyboard_node: str | None = None,
    mouse_node: str | None = None,
    consumer_node: str | None = None,
    grab_devices: bool = True,
) -> HarnessResult:
    scenario = get_scenario(scenario_name)
    try:
        candidate_nodes = discover_gadget_node_candidates(
            device_substring=device_substring,
            keyboard_node=keyboard_node,
            mouse_node=mouse_node,
            consumer_node=consumer_node,
        )
    except FileNotFoundError as exc:
        return HarnessResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=EXIT_PREREQUISITE,
            message=str(exc),
            details={},
        )
    except CaptureError as exc:
        return HarnessResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details={},
        )

    selector = selectors.DefaultSelector()
    fds: list[int] = []
    candidates_by_fd: dict[int, _CandidateMatcher] = {}

    def _active_candidates(role: str) -> list[_CandidateMatcher]:
        return [
            candidate
            for candidate in candidates_by_fd.values()
            if candidate.role == role and not candidate.failed
        ]

    def _completed_candidate(role: str) -> _CandidateMatcher | None:
        for candidate in candidates_by_fd.values():
            if candidate.role == role and candidate.complete:
                return candidate
        return None

    def _register_candidate(
        role: str,
        node: str,
        matcher: (
            KeyboardSequenceMatcher | MouseSequenceMatcher | ConsumerSequenceMatcher
        ),
    ) -> None:
        fd = _open_hidraw(node)
        fds.append(fd)
        candidate = _CandidateMatcher(role=role, node=node, fd=fd, matcher=matcher)
        candidates_by_fd[fd] = candidate
        selector.register(fd, selectors.EVENT_READ)

    def _required_role_done(role: str) -> bool:
        if role == "keyboard":
            return (
                not scenario.keyboard_enabled or _completed_candidate(role) is not None
            )
        if role == "mouse":
            return not scenario.mouse_enabled or _completed_candidate(role) is not None
        if role == "consumer":
            return (
                not scenario.consumer_enabled or _completed_candidate(role) is not None
            )
        raise AssertionError(f"Unexpected role: {role}")

    try:
        if scenario.keyboard_enabled:
            if not candidate_nodes.keyboard_nodes:
                raise MissingNodeError("Keyboard hidraw node was not found")
            for node in candidate_nodes.keyboard_nodes:
                _register_candidate(
                    "keyboard", node, KeyboardSequenceMatcher(scenario.keyboard_steps)
                )

        if scenario.mouse_enabled:
            if not candidate_nodes.mouse_nodes:
                raise MissingNodeError("Mouse hidraw node was not found")
            for node in candidate_nodes.mouse_nodes:
                _register_candidate(
                    "mouse",
                    node,
                    MouseSequenceMatcher.create(
                        scenario.mouse_rel_steps, scenario.mouse_button_steps
                    ),
                )

        if scenario.consumer_enabled:
            if not candidate_nodes.consumer_nodes:
                raise MissingNodeError("Consumer hidraw node was not found")
            for node in candidate_nodes.consumer_nodes:
                _register_candidate(
                    "consumer", node, ConsumerSequenceMatcher(scenario.consumer_steps)
                )

        deadline = time.monotonic() + timeout_sec
        while True:
            if (
                _required_role_done("keyboard")
                and _required_role_done("mouse")
                and _required_role_done("consumer")
            ):
                break

            for role, enabled in (
                ("keyboard", scenario.keyboard_enabled),
                ("mouse", scenario.mouse_enabled),
                ("consumer", scenario.consumer_enabled),
            ):
                if not enabled:
                    continue
                if _active_candidates(role):
                    continue
                messages = [
                    candidate.failed_message
                    for candidate in candidates_by_fd.values()
                    if candidate.role == role and candidate.failed_message
                ]
                raise CaptureMismatchError(
                    f"All {role} hidraw candidates mismatched: " + "; ".join(messages)
                )

            timeout_remaining = deadline - time.monotonic()
            if timeout_remaining <= 0:
                raise CaptureTimeoutError(
                    f"Timed out waiting for {scenario.name} reports after {timeout_sec}s"
                )

            events = selector.select(timeout_remaining)
            if not events:
                continue

            for selector_key, _ in events:
                candidate = candidates_by_fd.get(selector_key.fd)
                if candidate is None or candidate.failed:
                    continue
                try:
                    report = os.read(candidate.fd, REPORT_READ_SIZE)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    raise CaptureError(
                        f"Failed reading hidraw reports from {candidate.node}: {exc}"
                    ) from exc

                if not report:
                    continue

                try:
                    candidate.matcher.handle(report)
                except CaptureMismatchError as exc:
                    candidate.failed_message = f"{candidate.node}: {exc}"
                    try:
                        selector.unregister(candidate.fd)
                    except Exception:
                        pass

    except CaptureError as exc:
        return HarnessResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details={
                "capture_backend": "hidraw",
                "candidates": candidate_nodes.to_dict(),
                "nodes": GadgetNodes(None, None, None).to_dict(),
                "grab_devices_requested": grab_devices,
            },
        )
    finally:
        for fd in fds:
            try:
                selector.unregister(fd)
            except Exception:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
        selector.close()

    keyboard_matcher = _completed_candidate("keyboard")
    mouse_matcher = _completed_candidate("mouse")
    consumer_matcher = _completed_candidate("consumer")
    matched_nodes = candidate_nodes.matched_nodes(
        keyboard_node=keyboard_matcher.node if keyboard_matcher else None,
        mouse_node=mouse_matcher.node if mouse_matcher else None,
        consumer_node=consumer_matcher.node if consumer_matcher else None,
    )
    details: dict[str, object] = {
        "capture_backend": "hidraw",
        "candidates": candidate_nodes.to_dict(),
        "nodes": matched_nodes.to_dict(),
        "grab_devices_requested": grab_devices,
        "timeout_sec": timeout_sec,
    }
    if keyboard_matcher is not None:
        details["keyboard_steps_seen"] = keyboard_matcher.matcher.index
    if mouse_matcher is not None:
        details["mouse_button_steps_seen"] = mouse_matcher.matcher.button_index
        details["mouse_rel_totals"] = {
            ecodes.REL.get(code, str(code)): value
            for code, value in sorted(mouse_matcher.matcher.rel_progress.items())
        }
    if consumer_matcher is not None:
        details["consumer_steps_seen"] = consumer_matcher.matcher.index

    return HarnessResult(
        command="capture",
        scenario=scenario.name,
        success=True,
        exit_code=EXIT_OK,
        message="Observed expected relay reports on gadget hidraw nodes",
        details=details,
    )
