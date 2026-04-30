from __future__ import annotations

import time
from pathlib import Path

from evdev import UInput, ecodes

from .harness_common import (
    COMBO_MOUSE_DELAY_MS,
    DEFAULT_CONSUMER_NAME,
    DEFAULT_KEYBOARD_NAME,
    DEFAULT_MOUSE_NAME,
    EXIT_ACCESS,
    EXIT_OK,
    EXIT_PREREQUISITE,
    SCENARIOS,
    HarnessResult,
    get_scenario,
    scenario_to_dict,
)

UINPUT_PATH = Path("/dev/uinput")


def _send_step(device: UInput, step_event, event_gap_ms: int) -> None:
    device.write(step_event.event_type, step_event.code, step_event.value)
    device.syn()
    time.sleep(event_gap_ms / 1000.0)


_HI_RES_REL_CODES = {
    ecodes.REL_WHEEL: ecodes.REL_WHEEL_HI_RES,
    ecodes.REL_HWHEEL: ecodes.REL_HWHEEL_HI_RES,
}


def _write_mouse_rel_step(device: UInput, step_event) -> None:
    device.write(step_event.event_type, step_event.code, step_event.value)
    hi_res_code = _HI_RES_REL_CODES.get(step_event.code)
    if step_event.event_type == ecodes.EV_REL and hi_res_code is not None:
        device.write(step_event.event_type, hi_res_code, step_event.value * 120)


def _send_mouse_rel_step(device: UInput, step_event, event_gap_ms: int) -> None:
    _write_mouse_rel_step(device, step_event)
    device.syn()
    time.sleep(event_gap_ms / 1000.0)


def _keyboard_capabilities() -> dict[int, list[int]]:
    keyboard_codes = sorted(
        {step.code for scenario in SCENARIOS.values() for step in scenario.keyboard_steps}
    )
    return {ecodes.EV_KEY: keyboard_codes}


def _mouse_capabilities() -> dict[int, list[int]]:
    scenario_button_codes = sorted(
        {step.code for scenario in SCENARIOS.values() for step in scenario.mouse_button_steps}
    )
    return {
        ecodes.EV_KEY: scenario_button_codes,
        ecodes.EV_REL: [
            ecodes.REL_X,
            ecodes.REL_Y,
            ecodes.REL_WHEEL,
            ecodes.REL_WHEEL_HI_RES,
            ecodes.REL_HWHEEL,
            ecodes.REL_HWHEEL_HI_RES,
        ],
    }


def _consumer_capabilities() -> dict[int, list[int]]:
    return {ecodes.EV_KEY: [ecodes.KEY_VOLUMEUP, ecodes.KEY_VOLUMEDOWN]}


def run_inject(
    scenario_name: str,
    pre_delay_ms: int = 1000,
    event_gap_ms: int = 40,
    keyboard_name: str = DEFAULT_KEYBOARD_NAME,
    mouse_name: str = DEFAULT_MOUSE_NAME,
    consumer_name: str = DEFAULT_CONSUMER_NAME,
) -> HarnessResult:
    scenario = get_scenario(scenario_name)

    if not UINPUT_PATH.exists():
        return HarnessResult(
            command="inject",
            scenario=scenario.name,
            success=False,
            exit_code=EXIT_PREREQUISITE,
            message=f"Missing {UINPUT_PATH}",
            details={"uinput_path": str(UINPUT_PATH)},
        )

    if not keyboard_name.strip() or not mouse_name.strip() or not consumer_name.strip():
        return HarnessResult(
            command="inject",
            scenario=scenario.name,
            success=False,
            exit_code=EXIT_PREREQUISITE,
            message="Virtual device names must not be empty",
            details={},
        )

    keyboard = None
    mouse = None
    consumer = None
    try:
        if scenario.keyboard_enabled:
            keyboard = UInput(_keyboard_capabilities(), name=keyboard_name)
        if scenario.mouse_enabled:
            mouse = UInput(_mouse_capabilities(), name=mouse_name)
        if scenario.consumer_enabled:
            consumer = UInput(_consumer_capabilities(), name=consumer_name)
    except PermissionError as exc:
        return HarnessResult(
            command="inject",
            scenario=scenario.name,
            success=False,
            exit_code=EXIT_ACCESS,
            message=f"Cannot access {UINPUT_PATH}: {exc}",
            details={"uinput_path": str(UINPUT_PATH)},
        )
    except OSError as exc:
        return HarnessResult(
            command="inject",
            scenario=scenario.name,
            success=False,
            exit_code=EXIT_ACCESS,
            message=f"Failed creating virtual input devices: {exc}",
            details={"uinput_path": str(UINPUT_PATH)},
        )

    try:
        time.sleep(pre_delay_ms / 1000.0)

        if keyboard is not None:
            for step_event in scenario.keyboard_steps:
                _send_step(keyboard, step_event, event_gap_ms)

        if keyboard is not None and mouse is not None:
            time.sleep(COMBO_MOUSE_DELAY_MS / 1000.0)

        if mouse is not None:
            coalesced_tail_count = scenario.mouse_coalesced_tail_count
            individual_steps = scenario.mouse_rel_steps
            coalesced_steps = ()
            if coalesced_tail_count:
                individual_steps = scenario.mouse_rel_steps[:-coalesced_tail_count]
                coalesced_steps = scenario.mouse_rel_steps[-coalesced_tail_count:]

            for step_event in individual_steps:
                _send_mouse_rel_step(mouse, step_event, event_gap_ms)
            for step_event in coalesced_steps:
                _write_mouse_rel_step(mouse, step_event)
            if coalesced_steps:
                mouse.syn()
                time.sleep(event_gap_ms / 1000.0)
            for step_event in scenario.mouse_button_steps:
                _send_step(mouse, step_event, event_gap_ms)

        if consumer is not None:
            for step_event in scenario.consumer_steps:
                _send_step(consumer, step_event, event_gap_ms)

    except OSError as exc:
        return HarnessResult(
            command="inject",
            scenario=scenario.name,
            success=False,
            exit_code=EXIT_ACCESS,
            message=f"Failed injecting events: {exc}",
            details={
                "uinput_path": str(UINPUT_PATH),
                "keyboard_name": keyboard_name if keyboard is not None else None,
                "mouse_name": mouse_name if mouse is not None else None,
                "consumer_name": consumer_name if consumer is not None else None,
            },
        )
    finally:
        if consumer is not None:
            consumer.close()
        if mouse is not None:
            mouse.close()
        if keyboard is not None:
            keyboard.close()

    injected_events = len(scenario.keyboard_steps) + len(scenario.mouse_rel_steps)
    injected_events += len(scenario.mouse_button_steps)
    injected_events += len(scenario.consumer_steps)
    return HarnessResult(
        command="inject",
        scenario=scenario.name,
        success=True,
        exit_code=EXIT_OK,
        message="Injected virtual input events",
        details={
            "uinput_path": str(UINPUT_PATH),
            "keyboard_name": keyboard_name if scenario.keyboard_enabled else None,
            "mouse_name": mouse_name if scenario.mouse_enabled else None,
            "consumer_name": consumer_name if scenario.consumer_enabled else None,
            "pre_delay_ms": pre_delay_ms,
            "event_gap_ms": event_gap_ms,
            "expected": scenario_to_dict(scenario),
            "injected_event_count": injected_events,
        },
    )
