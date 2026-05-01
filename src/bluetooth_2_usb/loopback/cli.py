from __future__ import annotations

import argparse
import json

from .constants import (
    DEFAULT_CONSUMER_NAME,
    DEFAULT_DEVICE_SUBSTRING,
    DEFAULT_KEYBOARD_NAME,
    DEFAULT_MOUSE_NAME,
    EXIT_INTERRUPTED,
    EXIT_USAGE,
)
from .result import LoopbackResult
from .scenarios import SCENARIO_NAMES
from .session import (
    LOOPBACK_LOCK_PATH,
    LoopbackBusyError,
    LoopbackInterrupted,
    loopback_session,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bluetooth_2_usb loopback",
        description="Loopback validation for Bluetooth-2-USB relay testing.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inject = subparsers.add_parser(
        "inject",
        help="Create virtual input devices on the Pi and inject a deterministic test sequence.",
    )
    inject.add_argument(
        "--scenario",
        choices=SCENARIO_NAMES,
        default="combo",
        help="Deterministic input scenario to inject. Default: combo",
    )
    inject.add_argument(
        "--pre-delay-ms",
        type=int,
        default=1000,
        help="Delay after virtual device creation before injection. Default: 1000",
    )
    inject.add_argument(
        "--event-gap-ms",
        type=int,
        default=None,
        help="Delay between emitted events. Default: scenario-specific",
    )
    inject.add_argument(
        "--post-delay-ms",
        type=int,
        default=None,
        help="Delay after injection before closing virtual devices. Default: scenario-specific",
    )
    inject.add_argument(
        "--keyboard-name",
        default=DEFAULT_KEYBOARD_NAME,
        help=f"Virtual keyboard name. Default: {DEFAULT_KEYBOARD_NAME}",
    )
    inject.add_argument(
        "--mouse-name",
        default=DEFAULT_MOUSE_NAME,
        help=f"Virtual mouse name. Default: {DEFAULT_MOUSE_NAME}",
    )
    inject.add_argument(
        "--consumer-name",
        default=DEFAULT_CONSUMER_NAME,
        help=f"Virtual consumer-control device name. Default: {DEFAULT_CONSUMER_NAME}",
    )
    inject.add_argument(
        "--output", choices=["text", "json"], default="text", help="Output format. Default: text"
    )

    capture = subparsers.add_parser(
        "capture", help="Capture relay reports from the host-side gadget HID devices."
    )
    capture.add_argument(
        "--scenario",
        choices=SCENARIO_NAMES,
        default="combo",
        help="Expected input scenario. Default: combo",
    )
    capture.add_argument(
        "--timeout-sec",
        type=float,
        default=5.0,
        help="Timeout waiting for relay events. Default: 5",
    )
    capture.add_argument(
        "--device-substring",
        default=DEFAULT_DEVICE_SUBSTRING,
        help=f"Substring used to detect gadget HID devices. Default: {DEFAULT_DEVICE_SUBSTRING}",
    )
    capture.add_argument(
        "--keyboard-node", default=None, help="Explicit keyboard HID device path override."
    )
    capture.add_argument(
        "--mouse-node", default=None, help="Explicit mouse HID device path override."
    )
    capture.add_argument(
        "--consumer-node", default=None, help="Explicit consumer-control HID device path override."
    )
    capture.add_argument(
        "--output", choices=["text", "json"], default="text", help="Output format. Default: text"
    )

    return parser


def _validate_args(args: argparse.Namespace) -> LoopbackResult | None:
    if args.command == "inject":
        if args.pre_delay_ms < 0:
            return LoopbackResult(
                command="inject",
                scenario=args.scenario,
                success=False,
                exit_code=EXIT_USAGE,
                message="--pre-delay-ms must be >= 0",
                details={},
            )
        if args.event_gap_ms is not None and args.event_gap_ms < 0:
            return LoopbackResult(
                command="inject",
                scenario=args.scenario,
                success=False,
                exit_code=EXIT_USAGE,
                message="--event-gap-ms must be >= 0",
                details={},
            )
        if args.post_delay_ms is not None and args.post_delay_ms < 0:
            return LoopbackResult(
                command="inject",
                scenario=args.scenario,
                success=False,
                exit_code=EXIT_USAGE,
                message="--post-delay-ms must be >= 0",
                details={},
            )

    if args.command == "capture" and args.timeout_sec <= 0:
        return LoopbackResult(
            command="capture",
            scenario=args.scenario,
            success=False,
            exit_code=EXIT_USAGE,
            message="--timeout-sec must be > 0",
            details={},
        )
    return None


def _print_result(result: LoopbackResult, output: str) -> None:
    if output == "json":
        print(json.dumps(result.to_dict(), sort_keys=True))
    else:
        print(result.to_text())


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    validation_error = _validate_args(args)
    if validation_error is not None:
        _print_result(validation_error, args.output)
        return validation_error.exit_code

    try:
        with loopback_session(args.command, args.scenario):
            if args.command == "inject":
                from .inject import run_inject

                result = run_inject(
                    scenario_name=args.scenario,
                    pre_delay_ms=args.pre_delay_ms,
                    event_gap_ms=args.event_gap_ms,
                    post_delay_ms=args.post_delay_ms,
                    keyboard_name=args.keyboard_name,
                    mouse_name=args.mouse_name,
                    consumer_name=args.consumer_name,
                )
            else:
                from .capture import run_capture

                result = run_capture(
                    scenario_name=args.scenario,
                    timeout_sec=args.timeout_sec,
                    device_substring=args.device_substring,
                    keyboard_node=args.keyboard_node,
                    mouse_node=args.mouse_node,
                    consumer_node=args.consumer_node,
                )
    except LoopbackBusyError as exc:
        result = LoopbackResult(
            command=args.command,
            scenario=args.scenario,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details={"lock_path": str(LOOPBACK_LOCK_PATH)},
        )
    except LoopbackInterrupted as exc:
        details = {}
        if exc.signal_name is not None:
            details["signal"] = exc.signal_name
        result = LoopbackResult(
            command=args.command,
            scenario=args.scenario,
            success=False,
            exit_code=EXIT_INTERRUPTED,
            message=str(exc),
            details=details,
        )
    except KeyboardInterrupt:
        result = LoopbackResult(
            command=args.command,
            scenario=args.scenario,
            success=False,
            exit_code=EXIT_INTERRUPTED,
            message="Loopback interrupted",
            details={},
        )

    _print_result(result, args.output)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(run())
