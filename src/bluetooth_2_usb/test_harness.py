from __future__ import annotations

import argparse
import json

from .test_harness_capture import run_capture
from .test_harness_common import (
    DEFAULT_CONSUMER_NAME,
    DEFAULT_DEVICE_SUBSTRING,
    DEFAULT_KEYBOARD_NAME,
    DEFAULT_MOUSE_NAME,
    EXIT_USAGE,
    SCENARIO_NAMES,
    HarnessResult,
)
from .test_harness_inject import run_inject


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Loopback harness for Bluetooth-2-USB relay testing."
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
        default=40,
        help="Delay between emitted events. Default: 40",
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
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format. Default: text",
    )

    capture = subparsers.add_parser(
        "capture",
        help="Capture relay reports from the host-side gadget hidraw nodes.",
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
        help=f"Substring used to detect gadget hidraw nodes from sysfs. Default: {DEFAULT_DEVICE_SUBSTRING}",
    )
    capture.add_argument(
        "--keyboard-node",
        default=None,
        help="Explicit keyboard hidraw node path override.",
    )
    capture.add_argument(
        "--mouse-node",
        default=None,
        help="Explicit mouse hidraw node path override.",
    )
    capture.add_argument(
        "--consumer-node",
        default=None,
        help="Explicit consumer-control hidraw node path override.",
    )
    capture.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format. Default: text",
    )

    return parser


def _validate_args(args: argparse.Namespace) -> HarnessResult | None:
    if args.command == "inject":
        if args.pre_delay_ms < 0:
            return HarnessResult(
                command="inject",
                scenario=args.scenario,
                success=False,
                exit_code=EXIT_USAGE,
                message="--pre-delay-ms must be >= 0",
                details={},
            )
        if args.event_gap_ms < 0:
            return HarnessResult(
                command="inject",
                scenario=args.scenario,
                success=False,
                exit_code=EXIT_USAGE,
                message="--event-gap-ms must be >= 0",
                details={},
            )

    if args.command == "capture" and args.timeout_sec <= 0:
        return HarnessResult(
            command="capture",
            scenario=args.scenario,
            success=False,
            exit_code=EXIT_USAGE,
            message="--timeout-sec must be > 0",
            details={},
        )
    return None


def _print_result(result: HarnessResult, output: str) -> None:
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

    if args.command == "inject":
        result = run_inject(
            scenario_name=args.scenario,
            pre_delay_ms=args.pre_delay_ms,
            event_gap_ms=args.event_gap_ms,
            keyboard_name=args.keyboard_name,
            mouse_name=args.mouse_name,
            consumer_name=args.consumer_name,
        )
    else:
        result = run_capture(
            scenario_name=args.scenario,
            timeout_sec=args.timeout_sec,
            device_substring=args.device_substring,
            keyboard_node=args.keyboard_node,
            mouse_node=args.mouse_node,
            consumer_node=args.consumer_node,
        )

    _print_result(result, args.output)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(run())
