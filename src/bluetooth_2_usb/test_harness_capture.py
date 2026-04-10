from __future__ import annotations

import os
import selectors
import time
from dataclasses import dataclass
from pathlib import Path

from evdev import InputDevice, ecodes

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

BY_ID_ROOT = Path("/dev/input/by-id")


class CaptureError(RuntimeError):
    exit_code = EXIT_ACCESS


class MissingNodeError(CaptureError):
    exit_code = EXIT_PREREQUISITE


class CaptureTimeoutError(CaptureError):
    exit_code = EXIT_TIMEOUT


class CaptureMismatchError(CaptureError):
    exit_code = EXIT_MISMATCH


@dataclass(slots=True)
class KeyboardSequenceMatcher:
    expected_steps: tuple
    index: int = 0

    def handle(self, event) -> None:
        if event.type == ecodes.EV_SYN:
            return
        if self.index >= len(self.expected_steps):
            return
        expected = self.expected_steps[self.index]
        if event.type != expected.event_type:
            raise CaptureMismatchError(
                f"Unexpected keyboard event type {event.type}; expected {expected.describe()}"
            )
        if event.code != expected.code or event.value != expected.value:
            raise CaptureMismatchError(
                f"Unexpected keyboard event {event}; expected {expected.describe()}"
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

    def handle(self, event) -> None:
        if event.type == ecodes.EV_SYN:
            return

        if event.type == ecodes.EV_REL:
            if event.code not in self.rel_progress:
                raise CaptureMismatchError(
                    f"Unexpected mouse relative event code {event.code}"
                )
            self.rel_progress[event.code] += event.value
            expected_total = next(
                step.value
                for step in self.expected_rel_steps
                if step.code == event.code
            )
            if self.rel_progress[event.code] > expected_total:
                raise CaptureMismatchError(
                    f"Mouse movement for code {event.code} exceeded expected total"
                )
            return

        if event.type != ecodes.EV_KEY:
            raise CaptureMismatchError(f"Unexpected mouse event type {event.type}")

        if not self.rel_complete:
            raise CaptureMismatchError("Mouse button event arrived before movement")

        if self.button_index >= len(self.expected_button_steps):
            raise CaptureMismatchError("Received unexpected extra mouse button event")

        expected = self.expected_button_steps[self.button_index]
        if event.code != expected.code or event.value != expected.value:
            raise CaptureMismatchError(
                f"Unexpected mouse event {event}; expected {expected.describe()}"
            )
        self.button_index += 1

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


def _resolve_candidate_path(path: Path) -> str:
    return os.path.realpath(path)


def _collect_candidates(by_id_root: Path, substring: str) -> GadgetNodes:
    keyboard_candidates: dict[str, str] = {}
    mouse_candidates: dict[str, str] = {}

    for candidate in sorted(by_id_root.iterdir()):
        name = candidate.name
        if substring not in name:
            continue
        real_path = _resolve_candidate_path(candidate)
        if name.endswith("event-kbd"):
            keyboard_candidates[real_path] = str(candidate)
        elif name.endswith("event-mouse"):
            mouse_candidates[real_path] = str(candidate)

    if len(keyboard_candidates) > 1:
        raise MissingNodeError(
            "Multiple keyboard gadget nodes matched: "
            + ", ".join(sorted(keyboard_candidates.values()))
        )
    if len(mouse_candidates) > 1:
        raise MissingNodeError(
            "Multiple mouse gadget nodes matched: "
            + ", ".join(sorted(mouse_candidates.values()))
        )

    keyboard_node = next(iter(keyboard_candidates), None)
    mouse_node = next(iter(mouse_candidates), None)
    return GadgetNodes(keyboard_node=keyboard_node, mouse_node=mouse_node)


def discover_gadget_nodes(
    device_substring: str = DEFAULT_DEVICE_SUBSTRING,
    keyboard_node: str | None = None,
    mouse_node: str | None = None,
    by_id_root: Path = BY_ID_ROOT,
) -> GadgetNodes:
    if keyboard_node is not None or mouse_node is not None:
        keyboard_path = ensure_existing_path(keyboard_node, "keyboard node")
        mouse_path = ensure_existing_path(mouse_node, "mouse node")
        return GadgetNodes(
            keyboard_node=str(keyboard_path.resolve()) if keyboard_path else None,
            mouse_node=str(mouse_path.resolve()) if mouse_path else None,
        )

    if not by_id_root.is_dir():
        raise MissingNodeError(f"Input by-id directory is missing: {by_id_root}")

    nodes = _collect_candidates(by_id_root, device_substring)
    if nodes.keyboard_node is None and nodes.mouse_node is None:
        raise MissingNodeError(
            f"No gadget event nodes matched {device_substring!r} in {by_id_root}"
        )
    return nodes


def _open_input_device(node: str, grab_devices: bool) -> InputDevice:
    try:
        device = InputDevice(node)
    except FileNotFoundError as exc:
        raise MissingNodeError(f"Input node does not exist: {node}") from exc
    except OSError as exc:
        raise CaptureError(f"Failed opening input node {node}: {exc}") from exc

    if grab_devices:
        try:
            device.grab()
        except OSError as exc:
            device.close()
            raise CaptureError(f"Failed grabbing input node {node}: {exc}") from exc
    return device


def run_capture(
    scenario_name: str,
    timeout_sec: float = 5.0,
    device_substring: str = DEFAULT_DEVICE_SUBSTRING,
    keyboard_node: str | None = None,
    mouse_node: str | None = None,
    grab_devices: bool = True,
) -> HarnessResult:
    scenario = get_scenario(scenario_name)
    try:
        nodes = discover_gadget_nodes(
            device_substring=device_substring,
            keyboard_node=keyboard_node,
            mouse_node=mouse_node,
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

    keyboard_matcher = (
        KeyboardSequenceMatcher(scenario.keyboard_steps)
        if scenario.keyboard_enabled
        else None
    )
    mouse_matcher = (
        MouseSequenceMatcher.create(
            scenario.mouse_rel_steps, scenario.mouse_button_steps
        )
        if scenario.mouse_enabled
        else None
    )

    selector = selectors.DefaultSelector()
    devices: list[InputDevice] = []
    try:
        if scenario.keyboard_enabled:
            if nodes.keyboard_node is None:
                raise MissingNodeError("Keyboard gadget node was not found")
            keyboard_device = _open_input_device(nodes.keyboard_node, grab_devices)
            devices.append(keyboard_device)
            selector.register(keyboard_device.fd, selectors.EVENT_READ, "keyboard")

        if scenario.mouse_enabled:
            if nodes.mouse_node is None:
                raise MissingNodeError("Mouse gadget node was not found")
            mouse_device = _open_input_device(nodes.mouse_node, grab_devices)
            devices.append(mouse_device)
            selector.register(mouse_device.fd, selectors.EVENT_READ, "mouse")

        deadline = time.monotonic() + timeout_sec
        while True:
            keyboard_done = keyboard_matcher is None or keyboard_matcher.complete
            mouse_done = mouse_matcher is None or mouse_matcher.complete
            if keyboard_done and mouse_done:
                break

            timeout_remaining = deadline - time.monotonic()
            if timeout_remaining <= 0:
                raise CaptureTimeoutError(
                    f"Timed out waiting for {scenario.name} events after {timeout_sec}s"
                )

            events = selector.select(timeout_remaining)
            if not events:
                continue

            for selector_key, _ in events:
                label = selector_key.data
                device = next(dev for dev in devices if dev.fd == selector_key.fd)
                try:
                    pending_events = device.read()
                except BlockingIOError:
                    continue
                except OSError as exc:
                    raise CaptureError(
                        f"Failed reading events from {device.path}: {exc}"
                    ) from exc

                for event in pending_events:
                    if label == "keyboard" and keyboard_matcher is not None:
                        keyboard_matcher.handle(event)
                    elif label == "mouse" and mouse_matcher is not None:
                        mouse_matcher.handle(event)

    except CaptureError as exc:
        return HarnessResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details={"nodes": nodes.to_dict(), "grab_devices": grab_devices},
        )
    finally:
        for device in devices:
            try:
                if grab_devices:
                    device.ungrab()
            except OSError:
                pass
            try:
                selector.unregister(device.fd)
            except Exception:
                pass
            device.close()
        selector.close()

    details: dict[str, object] = {
        "nodes": nodes.to_dict(),
        "grab_devices": grab_devices,
        "timeout_sec": timeout_sec,
    }
    if keyboard_matcher is not None:
        details["keyboard_steps_seen"] = keyboard_matcher.index
    if mouse_matcher is not None:
        details["mouse_button_steps_seen"] = mouse_matcher.button_index
        details["mouse_rel_totals"] = {
            ecodes.REL.get(code, str(code)): value
            for code, value in sorted(mouse_matcher.rel_progress.items())
        }

    return HarnessResult(
        command="capture",
        scenario=scenario.name,
        success=True,
        exit_code=EXIT_OK,
        message="Observed expected relay events on host gadget nodes",
        details=details,
    )
