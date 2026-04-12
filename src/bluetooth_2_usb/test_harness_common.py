from __future__ import annotations

import json
import os
import signal
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PREREQUISITE = 3
EXIT_ACCESS = 4
EXIT_TIMEOUT = 5
EXIT_MISMATCH = 6
EXIT_INTERRUPTED = 130

EV_KEY = 1
EV_REL = 2

KEY_F13 = 183
KEY_F14 = 184
KEY_F15 = 185
KEY_VOLUMEUP = 115
KEY_VOLUMEDOWN = 114
REL_X = 0
REL_Y = 1

EVENT_TYPE_NAMES = {
    EV_KEY: "EV_KEY",
    EV_REL: "EV_REL",
}

EVENT_CODE_NAMES = {
    EV_KEY: {
        KEY_F13: "KEY_F13",
        KEY_F14: "KEY_F14",
        KEY_F15: "KEY_F15",
        KEY_VOLUMEUP: "KEY_VOLUMEUP",
        KEY_VOLUMEDOWN: "KEY_VOLUMEDOWN",
    },
    EV_REL: {
        REL_X: "REL_X",
        REL_Y: "REL_Y",
    },
}

SCENARIO_NAMES = ("keyboard", "mouse", "combo", "consumer")
DEFAULT_DEVICE_SUBSTRING = "USB_Combo_Device"
DEFAULT_KEYBOARD_NAME = "B2U Test Keyboard"
DEFAULT_MOUSE_NAME = "B2U Test Mouse"
DEFAULT_CONSUMER_NAME = "B2U Test Consumer"
COMBO_MOUSE_DELAY_MS = 150
HARNESS_LOCK_PATH = Path(tempfile.gettempdir()) / "bluetooth_2_usb_test_harness.lock"

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class HarnessBusyError(RuntimeError):
    exit_code = EXIT_ACCESS


class HarnessInterrupted(KeyboardInterrupt):
    exit_code = EXIT_INTERRUPTED

    def __init__(self, signum: int | None = None) -> None:
        self.signum = signum
        signal_name = None
        if signum is not None:
            try:
                signal_name = signal.Signals(signum).name
            except ValueError:
                signal_name = None
        self.signal_name = signal_name
        message = (
            f"Harness interrupted by {signal_name}"
            if signal_name is not None
            else "Harness interrupted"
        )
        super().__init__(message)


def _lock_harness_file(lock_handle) -> None:
    if os.name == "nt":
        lock_handle.seek(0)
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_harness_file(lock_handle) -> None:
    if os.name == "nt":
        lock_handle.seek(0)
        try:
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def harness_session(command: str, scenario: str):
    lock_handle = HARNESS_LOCK_PATH.open("a+", encoding="utf-8")
    try:
        if lock_handle.tell() == 0:
            lock_handle.write("\n")
            lock_handle.flush()
        try:
            _lock_harness_file(lock_handle)
        except OSError as exc:
            raise HarnessBusyError(
                "Another Bluetooth-2-USB test harness session is already running "
                f"(lock: {HARNESS_LOCK_PATH})"
            ) from exc

        metadata = json.dumps(
            {
                "pid": os.getpid(),
                "command": command,
                "scenario": scenario,
            },
            sort_keys=True,
        )
        lock_handle.seek(0)
        lock_handle.truncate()
        lock_handle.write(metadata)
        lock_handle.flush()

        handled_signals = [
            sig
            for sig in (
                signal.SIGINT,
                signal.SIGTERM,
                getattr(signal, "SIGHUP", None),
                getattr(signal, "SIGQUIT", None),
            )
            if sig is not None
        ]
        previous_handlers = {
            handled_signal: signal.getsignal(handled_signal)
            for handled_signal in handled_signals
        }

        def _raise_interrupted(received_signal: int, _frame) -> None:
            raise HarnessInterrupted(received_signal)

        for handled_signal in handled_signals:
            signal.signal(handled_signal, _raise_interrupted)

        try:
            yield
        finally:
            for handled_signal, previous_handler in previous_handlers.items():
                signal.signal(handled_signal, previous_handler)
    finally:
        try:
            _unlock_harness_file(lock_handle)
        finally:
            lock_handle.close()


@dataclass(frozen=True, slots=True)
class ExpectedEvent:
    event_type: int
    code: int
    value: int

    @property
    def event_name(self) -> str:
        return EVENT_TYPE_NAMES.get(self.event_type, str(self.event_type))

    @property
    def code_name(self) -> str:
        code_table = EVENT_CODE_NAMES.get(self.event_type, {})
        return code_table.get(self.code, str(self.code))

    def describe(self) -> str:
        return f"{self.event_name}/{self.code_name}={self.value}"


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    name: str
    keyboard_steps: tuple[ExpectedEvent, ...]
    mouse_rel_steps: tuple[ExpectedEvent, ...]
    mouse_button_steps: tuple[ExpectedEvent, ...]
    consumer_steps: tuple[ExpectedEvent, ...]

    @property
    def keyboard_enabled(self) -> bool:
        return bool(self.keyboard_steps)

    @property
    def mouse_enabled(self) -> bool:
        return bool(self.mouse_rel_steps or self.mouse_button_steps)

    @property
    def consumer_enabled(self) -> bool:
        return bool(self.consumer_steps)

    @property
    def required_nodes(self) -> tuple[str, ...]:
        nodes: list[str] = []
        if self.keyboard_enabled:
            nodes.append("keyboard")
        if self.mouse_enabled:
            nodes.append("mouse")
        if self.consumer_enabled:
            nodes.append("consumer")
        return tuple(nodes)


KEYBOARD_STEPS = (
    ExpectedEvent(EV_KEY, KEY_F13, 1),
    ExpectedEvent(EV_KEY, KEY_F13, 0),
    ExpectedEvent(EV_KEY, KEY_F14, 1),
    ExpectedEvent(EV_KEY, KEY_F14, 0),
    ExpectedEvent(EV_KEY, KEY_F15, 1),
    ExpectedEvent(EV_KEY, KEY_F15, 0),
)

MOUSE_REL_STEPS = (
    ExpectedEvent(EV_REL, REL_X, 1),
    ExpectedEvent(EV_REL, REL_X, -1),
    ExpectedEvent(EV_REL, REL_Y, 1),
    ExpectedEvent(EV_REL, REL_Y, -1),
)

CONSUMER_STEPS = (
    ExpectedEvent(EV_KEY, KEY_VOLUMEUP, 1),
    ExpectedEvent(EV_KEY, KEY_VOLUMEUP, 0),
    ExpectedEvent(EV_KEY, KEY_VOLUMEDOWN, 1),
    ExpectedEvent(EV_KEY, KEY_VOLUMEDOWN, 0),
)

SCENARIOS = {
    "keyboard": ScenarioDefinition(
        name="keyboard",
        keyboard_steps=KEYBOARD_STEPS,
        mouse_rel_steps=(),
        mouse_button_steps=(),
        consumer_steps=(),
    ),
    "mouse": ScenarioDefinition(
        name="mouse",
        keyboard_steps=(),
        mouse_rel_steps=MOUSE_REL_STEPS,
        mouse_button_steps=(),
        consumer_steps=(),
    ),
    "combo": ScenarioDefinition(
        name="combo",
        keyboard_steps=KEYBOARD_STEPS,
        mouse_rel_steps=MOUSE_REL_STEPS,
        mouse_button_steps=(),
        consumer_steps=(),
    ),
    "consumer": ScenarioDefinition(
        name="consumer",
        keyboard_steps=(),
        mouse_rel_steps=(),
        mouse_button_steps=(),
        consumer_steps=CONSUMER_STEPS,
    ),
}


@dataclass(frozen=True, slots=True)
class GadgetNodes:
    keyboard_node: str | None
    mouse_node: str | None
    consumer_node: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "keyboard_node": self.keyboard_node,
            "mouse_node": self.mouse_node,
            "consumer_node": self.consumer_node,
        }


@dataclass(slots=True)
class HarnessResult:
    command: str
    scenario: str
    success: bool
    exit_code: int
    message: str
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_text(self) -> str:
        lines = [
            f"command: {self.command}",
            f"scenario: {self.scenario}",
            f"result: {'ok' if self.success else 'error'}",
            f"exit_code: {self.exit_code}",
            f"message: {self.message}",
        ]
        for key, value in sorted(self.details.items()):
            rendered = (
                json.dumps(value, sort_keys=True)
                if isinstance(value, (dict, list))
                else str(value)
            )
            lines.append(f"{key}: {rendered}")
        return "\n".join(lines)


def get_scenario(name: str) -> ScenarioDefinition:
    return SCENARIOS[name]


def event_to_dict(event: ExpectedEvent) -> dict[str, object]:
    return {
        "event_type": event.event_type,
        "event_name": event.event_name,
        "code": event.code,
        "code_name": event.code_name,
        "value": event.value,
    }


def scenario_to_dict(scenario: ScenarioDefinition) -> dict[str, object]:
    return {
        "name": scenario.name,
        "keyboard_steps": [event_to_dict(step) for step in scenario.keyboard_steps],
        "mouse_rel_steps": [event_to_dict(step) for step in scenario.mouse_rel_steps],
        "mouse_button_steps": [
            event_to_dict(step) for step in scenario.mouse_button_steps
        ],
        "consumer_steps": [event_to_dict(step) for step in scenario.consumer_steps],
    }


def ensure_existing_path(path: str | None, label: str) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"{label} does not exist: {candidate}")
    return candidate
