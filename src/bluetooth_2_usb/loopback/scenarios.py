from __future__ import annotations

from dataclasses import dataclass

from ..evdev import ecodes
from ..evdev.types import KeyEvent

EV_KEY = ecodes.EV_KEY
EV_REL = ecodes.EV_REL
KEY_DOWN = KeyEvent.key_down
KEY_UP = KeyEvent.key_up

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

SCENARIO_KEYBOARD = "keyboard"
SCENARIO_MOUSE = "mouse"
SCENARIO_NODE_DISCOVERY = "node-discovery"
SCENARIO_CONSUMER = "consumer"
SCENARIO_COMBO = "combo"

DEFAULT_MOUSE_COALESCED_TAIL_COUNT = 0
DEFAULT_EVENT_GAP_MS = 25
DEFAULT_POST_DELAY_MS = 250
DEFAULT_CAPTURE_TIMEOUT_SEC = 20.0

KEYBOARD_POST_DELAY_MS = 6000
MOUSE_EVENT_GAP_MS = 0
MOUSE_POST_DELAY_MS = 1000
NODE_DISCOVERY_POST_DELAY_MS = DEFAULT_POST_DELAY_MS
NODE_DISCOVERY_CAPTURE_TIMEOUT_SEC = 10.0
COMBO_POST_DELAY_MS = KEYBOARD_POST_DELAY_MS
COMBO_CAPTURE_TIMEOUT_SEC = 60.0

KEYBOARD_TEXT_BURST = "kEyBoArD"
KEYBOARD_TEXT_BURST_REPETITIONS = 9
MOUSE_X_POSITIVE_DELTA = 180000
MOUSE_X_NEGATIVE_DELTA = -210000
MOUSE_Y_POSITIVE_DELTA = 210000
MOUSE_Y_NEGATIVE_DELTA = -180000
MOUSE_WHEEL_DELTA = 2400
NODE_DISCOVERY_MOUSE_DELTA = 1


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
    mouse_coalesced_tail_count: int = DEFAULT_MOUSE_COALESCED_TAIL_COUNT
    default_event_gap_ms: int = DEFAULT_EVENT_GAP_MS
    default_post_delay_ms: int = DEFAULT_POST_DELAY_MS
    default_capture_timeout_sec: float = DEFAULT_CAPTURE_TIMEOUT_SEC

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
    ExpectedEvent(EV_REL, REL_X, MOUSE_X_POSITIVE_DELTA),
    ExpectedEvent(EV_REL, REL_Y, MOUSE_Y_NEGATIVE_DELTA),
    ExpectedEvent(EV_REL, REL_X, MOUSE_X_NEGATIVE_DELTA),
    ExpectedEvent(EV_REL, REL_Y, MOUSE_Y_POSITIVE_DELTA),
    ExpectedEvent(EV_REL, REL_WHEEL, MOUSE_WHEEL_DELTA),
    ExpectedEvent(EV_REL, REL_WHEEL, -MOUSE_WHEEL_DELTA),
    ExpectedEvent(EV_REL, REL_HWHEEL, MOUSE_WHEEL_DELTA),
    ExpectedEvent(EV_REL, REL_HWHEEL, -MOUSE_WHEEL_DELTA),
)

EXOTIC_KEYBOARD_CODES = (
    ecodes.KEY_F13,
    ecodes.KEY_F14,
    ecodes.KEY_F15,
    ecodes.KEY_F24,
    ecodes.KEY_SYSRQ,
    ecodes.KEY_SCROLLLOCK,
    ecodes.KEY_INSERT,
    ecodes.KEY_DELETE,
    ecodes.KEY_HOME,
    ecodes.KEY_END,
    ecodes.KEY_PAGEUP,
    ecodes.KEY_PAGEDOWN,
    ecodes.KEY_UP,
    ecodes.KEY_DOWN,
    ecodes.KEY_LEFT,
    ecodes.KEY_RIGHT,
    ecodes.KEY_COMPOSE,
)

CONSUMER_CODES = (
    ecodes.KEY_VOLUMEUP,
    ecodes.KEY_VOLUMEDOWN,
    ecodes.KEY_PLAYPAUSE,
    ecodes.KEY_NEXTSONG,
    ecodes.KEY_PREVIOUSSONG,
    ecodes.KEY_STOPCD,
    ecodes.KEY_MENU,
    ecodes.KEY_CALC,
    ecodes.KEY_HOMEPAGE,
    ecodes.KEY_SEARCH,
    ecodes.KEY_BACK,
    ecodes.KEY_FORWARD,
    ecodes.KEY_REFRESH,
)


def _press_release_steps(*codes: int) -> tuple[ExpectedEvent, ...]:
    return tuple(
        step for code in codes for step in (ExpectedEvent(EV_KEY, code, KEY_DOWN), ExpectedEvent(EV_KEY, code, KEY_UP))
    )


NODE_DISCOVERY_KEYBOARD_STEPS = _press_release_steps(KEY_F13)
NODE_DISCOVERY_REL_STEPS = (
    ExpectedEvent(EV_REL, REL_X, NODE_DISCOVERY_MOUSE_DELTA),
    ExpectedEvent(EV_REL, REL_X, -NODE_DISCOVERY_MOUSE_DELTA),
)
NODE_DISCOVERY_CONSUMER_STEPS = _press_release_steps(KEY_VOLUMEUP, KEY_VOLUMEDOWN)

MOUSE_BUTTON_STEPS = (
    *_press_release_steps(BTN_LEFT),
    *_press_release_steps(BTN_RIGHT),
    *_press_release_steps(BTN_MIDDLE),
    *_press_release_steps(BTN_SIDE),
    *_press_release_steps(BTN_EXTRA),
    *_press_release_steps(BTN_FORWARD),
    *_press_release_steps(BTN_BACK),
    *_press_release_steps(BTN_TASK),
)

EXOTIC_KEYBOARD_STEPS = _press_release_steps(*EXOTIC_KEYBOARD_CODES)
CONSUMER_STEPS = _press_release_steps(*CONSUMER_CODES)


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
            steps.extend((ExpectedEvent(EV_KEY, KEY_SPACE, KEY_DOWN), ExpectedEvent(EV_KEY, KEY_SPACE, KEY_UP)))
            continue
        if char == "_":
            steps.extend(
                (
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, KEY_DOWN),
                    ExpectedEvent(EV_KEY, KEY_MINUS, KEY_DOWN),
                    ExpectedEvent(EV_KEY, KEY_MINUS, KEY_UP),
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, KEY_UP),
                )
            )
            continue

        key_code = key_map[char.lower()]
        if char.isupper():
            steps.extend(
                (
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, KEY_DOWN),
                    ExpectedEvent(EV_KEY, key_code, KEY_DOWN),
                    ExpectedEvent(EV_KEY, key_code, KEY_UP),
                    ExpectedEvent(EV_KEY, KEY_LEFTSHIFT, KEY_UP),
                )
            )
            continue

        steps.extend((ExpectedEvent(EV_KEY, key_code, KEY_DOWN), ExpectedEvent(EV_KEY, key_code, KEY_UP)))


_KEYBOARD_STEPS: list[ExpectedEvent] = []
for _ in range(KEYBOARD_TEXT_BURST_REPETITIONS):
    _append_text_steps(_KEYBOARD_STEPS, KEYBOARD_TEXT_BURST)
TEXT_KEYBOARD_STEPS = tuple(_KEYBOARD_STEPS)
KEYBOARD_STEPS = TEXT_KEYBOARD_STEPS + EXOTIC_KEYBOARD_STEPS

SCENARIOS = {
    SCENARIO_KEYBOARD: ScenarioDefinition(
        name=SCENARIO_KEYBOARD,
        keyboard_steps=KEYBOARD_STEPS,
        mouse_rel_steps=(),
        mouse_button_steps=(),
        consumer_steps=(),
        default_post_delay_ms=KEYBOARD_POST_DELAY_MS,
    ),
    SCENARIO_MOUSE: ScenarioDefinition(
        name=SCENARIO_MOUSE,
        keyboard_steps=(),
        mouse_rel_steps=MOUSE_REL_STEPS,
        mouse_button_steps=MOUSE_BUTTON_STEPS,
        consumer_steps=(),
        default_event_gap_ms=MOUSE_EVENT_GAP_MS,
        default_post_delay_ms=MOUSE_POST_DELAY_MS,
    ),
    SCENARIO_NODE_DISCOVERY: ScenarioDefinition(
        name=SCENARIO_NODE_DISCOVERY,
        keyboard_steps=NODE_DISCOVERY_KEYBOARD_STEPS,
        mouse_rel_steps=NODE_DISCOVERY_REL_STEPS,
        mouse_button_steps=(),
        consumer_steps=NODE_DISCOVERY_CONSUMER_STEPS,
        default_post_delay_ms=NODE_DISCOVERY_POST_DELAY_MS,
        default_capture_timeout_sec=NODE_DISCOVERY_CAPTURE_TIMEOUT_SEC,
    ),
    SCENARIO_CONSUMER: ScenarioDefinition(
        name=SCENARIO_CONSUMER,
        keyboard_steps=(),
        mouse_rel_steps=(),
        mouse_button_steps=(),
        consumer_steps=CONSUMER_STEPS,
    ),
    SCENARIO_COMBO: ScenarioDefinition(
        name=SCENARIO_COMBO,
        keyboard_steps=KEYBOARD_STEPS,
        mouse_rel_steps=MOUSE_REL_STEPS,
        mouse_button_steps=MOUSE_BUTTON_STEPS,
        consumer_steps=CONSUMER_STEPS,
        default_post_delay_ms=COMBO_POST_DELAY_MS,
        default_capture_timeout_sec=COMBO_CAPTURE_TIMEOUT_SEC,
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


def scenario_summary(scenario: ScenarioDefinition) -> dict[str, object]:
    keyboard_steps = len(scenario.keyboard_steps)
    mouse_rel_steps = len(scenario.mouse_rel_steps)
    mouse_button_steps = len(scenario.mouse_button_steps)
    consumer_steps = len(scenario.consumer_steps)
    return {
        "name": scenario.name,
        "keyboard_steps": keyboard_steps,
        "mouse_rel_steps": mouse_rel_steps,
        "mouse_button_steps": mouse_button_steps,
        "consumer_steps": consumer_steps,
        "total_steps": keyboard_steps + mouse_rel_steps + mouse_button_steps + consumer_steps,
        "mouse_coalesced_tail_count": scenario.mouse_coalesced_tail_count,
        "default_event_gap_ms": scenario.default_event_gap_ms,
        "default_post_delay_ms": scenario.default_post_delay_ms,
        "default_capture_timeout_sec": scenario.default_capture_timeout_sec,
    }
