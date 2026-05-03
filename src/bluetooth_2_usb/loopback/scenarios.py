from __future__ import annotations

from dataclasses import dataclass

from ..evdev import ecodes

EV_KEY = ecodes.EV_KEY
EV_REL = ecodes.EV_REL

KEY_F13 = ecodes.KEY_F13
KEY_F14 = ecodes.KEY_F14
KEY_F15 = ecodes.KEY_F15
KEY_A = ecodes.KEY_A
KEY_E = ecodes.KEY_E
KEY_K = ecodes.KEY_K
KEY_O = ecodes.KEY_O
KEY_R = ecodes.KEY_R
KEY_T = ecodes.KEY_T
KEY_Y = ecodes.KEY_Y
KEY_B = ecodes.KEY_B
KEY_D = ecodes.KEY_D
KEY_LEFTSHIFT = ecodes.KEY_LEFTSHIFT
KEY_VOLUMEUP = ecodes.KEY_VOLUMEUP
KEY_VOLUMEDOWN = ecodes.KEY_VOLUMEDOWN
KEY_MINUS = ecodes.KEY_MINUS
KEY_SPACE = ecodes.KEY_SPACE
BTN_LEFT = ecodes.BTN_LEFT
BTN_RIGHT = ecodes.BTN_RIGHT
BTN_MIDDLE = ecodes.BTN_MIDDLE
BTN_SIDE = ecodes.BTN_SIDE
BTN_EXTRA = ecodes.BTN_EXTRA
BTN_FORWARD = ecodes.BTN_FORWARD
BTN_BACK = ecodes.BTN_BACK
BTN_TASK = ecodes.BTN_TASK
REL_X = ecodes.REL_X
REL_Y = ecodes.REL_Y
REL_HWHEEL = ecodes.REL_HWHEEL
REL_WHEEL = ecodes.REL_WHEEL
REL_WHEEL_HI_RES = ecodes.REL_WHEEL_HI_RES
REL_HWHEEL_HI_RES = ecodes.REL_HWHEEL_HI_RES

EVENT_TYPE_NAMES = {EV_KEY: "EV_KEY", EV_REL: "EV_REL"}


def _event_code_names(prefixes: tuple[str, ...]) -> dict[int, str]:
    names: dict[int, str] = {}
    for attribute in sorted(dir(ecodes)):
        if not attribute.startswith(prefixes):
            continue
        if any(marker in attribute for marker in ("_MIN", "_MAX", "_CNT")):
            continue
        value = getattr(ecodes, attribute)
        if not isinstance(value, int):
            continue
        names.setdefault(value, attribute)
    return names


EVENT_CODE_NAMES = {EV_KEY: _event_code_names(("KEY_", "BTN_")), EV_REL: _event_code_names(("REL_",))}


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
    mouse_coalesced_tail_count: int = 0
    default_event_gap_ms: int = 40
    default_post_delay_ms: int = 250
    default_capture_timeout_sec: float = 10.0

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


MOUSE_REL_STEPS = (
    ExpectedEvent(EV_REL, REL_X, 180000),
    ExpectedEvent(EV_REL, REL_Y, -180000),
    ExpectedEvent(EV_REL, REL_X, -210000),
    ExpectedEvent(EV_REL, REL_Y, 210000),
    ExpectedEvent(EV_REL, REL_WHEEL, 2400),
    ExpectedEvent(EV_REL, REL_WHEEL, -2400),
    ExpectedEvent(EV_REL, REL_HWHEEL, 2400),
    ExpectedEvent(EV_REL, REL_HWHEEL, -2400),
)

NODE_DISCOVERY_REL_STEPS = (ExpectedEvent(EV_REL, REL_X, 1), ExpectedEvent(EV_REL, REL_X, -1))

MOUSE_BUTTON_STEPS = (
    ExpectedEvent(EV_KEY, BTN_LEFT, 1),
    ExpectedEvent(EV_KEY, BTN_LEFT, 0),
    ExpectedEvent(EV_KEY, BTN_RIGHT, 1),
    ExpectedEvent(EV_KEY, BTN_RIGHT, 0),
    ExpectedEvent(EV_KEY, BTN_MIDDLE, 1),
    ExpectedEvent(EV_KEY, BTN_MIDDLE, 0),
    ExpectedEvent(EV_KEY, BTN_SIDE, 1),
    ExpectedEvent(EV_KEY, BTN_SIDE, 0),
    ExpectedEvent(EV_KEY, BTN_EXTRA, 1),
    ExpectedEvent(EV_KEY, BTN_EXTRA, 0),
    ExpectedEvent(EV_KEY, BTN_FORWARD, 1),
    ExpectedEvent(EV_KEY, BTN_FORWARD, 0),
    ExpectedEvent(EV_KEY, BTN_BACK, 1),
    ExpectedEvent(EV_KEY, BTN_BACK, 0),
    ExpectedEvent(EV_KEY, BTN_TASK, 1),
    ExpectedEvent(EV_KEY, BTN_TASK, 0),
)

CONSUMER_STEPS = (
    ExpectedEvent(EV_KEY, KEY_VOLUMEUP, 1),
    ExpectedEvent(EV_KEY, KEY_VOLUMEUP, 0),
    ExpectedEvent(EV_KEY, KEY_VOLUMEDOWN, 1),
    ExpectedEvent(EV_KEY, KEY_VOLUMEDOWN, 0),
)


def _append_text_steps(steps: list[ExpectedEvent], text: str) -> None:
    key_map = {
        "a": KEY_A,
        "b": KEY_B,
        "d": KEY_D,
        "e": KEY_E,
        "k": KEY_K,
        "o": KEY_O,
        "r": KEY_R,
        "t": KEY_T,
        "y": KEY_Y,
    }
    for char in text:
        if char == " ":
            steps.extend((ExpectedEvent(EV_KEY, KEY_SPACE, 1), ExpectedEvent(EV_KEY, KEY_SPACE, 0)))
            continue
        if char == "_":
            steps.extend(
                (
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, 1),
                    ExpectedEvent(EV_KEY, KEY_MINUS, 1),
                    ExpectedEvent(EV_KEY, KEY_MINUS, 0),
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, 0),
                )
            )
            continue

        key_code = key_map[char.lower()]
        if char.isupper():
            steps.extend(
                (
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, 1),
                    ExpectedEvent(EV_KEY, key_code, 1),
                    ExpectedEvent(EV_KEY, key_code, 0),
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, 0),
                )
            )
            continue

        steps.extend((ExpectedEvent(EV_KEY, key_code, 1), ExpectedEvent(EV_KEY, key_code, 0)))


_KEYBOARD_STEPS: list[ExpectedEvent] = []
for _ in range(9):
    _append_text_steps(_KEYBOARD_STEPS, "kEyBoArD")
KEYBOARD_STEPS = tuple(_KEYBOARD_STEPS)

SCENARIOS = {
    "keyboard": ScenarioDefinition(
        name="keyboard",
        keyboard_steps=KEYBOARD_STEPS,
        mouse_rel_steps=(),
        mouse_button_steps=(),
        consumer_steps=(),
        default_event_gap_ms=10,
        default_post_delay_ms=6000,
        default_capture_timeout_sec=15.0,
    ),
    "mouse": ScenarioDefinition(
        name="mouse",
        keyboard_steps=(),
        mouse_rel_steps=MOUSE_REL_STEPS,
        mouse_button_steps=MOUSE_BUTTON_STEPS,
        consumer_steps=(),
        default_event_gap_ms=0,
        default_post_delay_ms=1000,
    ),
    "node-discovery": ScenarioDefinition(
        name="node-discovery",
        keyboard_steps=(),
        mouse_rel_steps=NODE_DISCOVERY_REL_STEPS,
        mouse_button_steps=(),
        consumer_steps=(),
        default_event_gap_ms=20,
        default_post_delay_ms=250,
        default_capture_timeout_sec=5.0,
    ),
    "consumer": ScenarioDefinition(
        name="consumer", keyboard_steps=(), mouse_rel_steps=(), mouse_button_steps=(), consumer_steps=CONSUMER_STEPS
    ),
    "combo": ScenarioDefinition(
        name="combo",
        keyboard_steps=KEYBOARD_STEPS,
        mouse_rel_steps=MOUSE_REL_STEPS,
        mouse_button_steps=MOUSE_BUTTON_STEPS,
        consumer_steps=CONSUMER_STEPS,
        default_event_gap_ms=10,
        default_post_delay_ms=6000,
        default_capture_timeout_sec=30.0,
    ),
}

SCENARIO_NAMES = tuple(SCENARIOS.keys())


def get_scenario(name: str) -> ScenarioDefinition:
    if name not in SCENARIOS:
        valid_names = ", ".join(SCENARIO_NAMES)
        raise ValueError(f"Unknown scenario {name!r}. Expected one of: {valid_names}")
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
        "mouse_button_steps": [event_to_dict(step) for step in scenario.mouse_button_steps],
        "consumer_steps": [event_to_dict(step) for step in scenario.consumer_steps],
        "mouse_coalesced_tail_count": scenario.mouse_coalesced_tail_count,
        "default_event_gap_ms": scenario.default_event_gap_ms,
        "default_post_delay_ms": scenario.default_post_delay_ms,
        "default_capture_timeout_sec": scenario.default_capture_timeout_sec,
    }
