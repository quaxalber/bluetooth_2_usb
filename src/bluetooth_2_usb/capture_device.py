from __future__ import annotations

import argparse
import json
import re
import select
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from evdev import InputDevice, categorize
except ModuleNotFoundError as exc:
    InputDevice = None  # type: ignore[assignment]
    categorize = None  # type: ignore[assignment]
    _EVDEV_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _EVDEV_IMPORT_ERROR = None

from .device_classification import describe_capabilities
from .inventory import describe_input_devices

MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")


@dataclass(slots=True)
class CapturedFrame:
    events: list[str] = field(default_factory=list)


def redact(value: str) -> str:
    return MAC_RE.sub("<redacted-mac>", value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture redacted input-device details for Bluetooth-2-USB support."
    )
    parser.add_argument(
        "--device",
        "-d",
        default=None,
        help="Input event path to sample, for example /dev/input/event4.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Seconds to collect live events when --device is set. Default: 10.",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format. Default: json.",
    )
    return parser


def capture(device_path: str | None = None, duration: float = 10.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "inventory": [device.to_dict() for device in describe_input_devices()],
        "sample": None,
    }
    if device_path is None:
        return _redact_jsonable(result)

    if _EVDEV_IMPORT_ERROR is not None or InputDevice is None:
        raise RuntimeError("python-evdev is required to capture live input events")

    device = InputDevice(device_path)
    try:
        result["sample"] = _capture_device_sample(device, duration)
    finally:
        device.close()
    return _redact_jsonable(result)


def _capture_device_sample(device: InputDevice, duration: float) -> dict[str, Any]:
    capabilities = describe_capabilities(device)
    frames: list[CapturedFrame] = []
    current = CapturedFrame()
    deadline = time.monotonic() + max(duration, 0.0)

    while time.monotonic() < deadline:
        timeout = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([device.fd], [], [], timeout)
        if not readable:
            break
        for event in device.read():
            if time.monotonic() >= deadline:
                break
            categorized = categorize(event) if categorize is not None else event
            current.events.append(redact(str(categorized)))
            if event.type == 0 and event.code == 0:
                frames.append(current)
                current = CapturedFrame()
            if len(frames) >= 200:
                break
        if len(frames) >= 200:
            break

    if current.events:
        frames.append(current)

    return {
        "path": device.path,
        "name": redact(device.name or ""),
        "phys": redact(device.phys or ""),
        "uniq": redact(device.uniq or ""),
        "capabilities": {
            "event_types": list(capabilities.event_types),
            "properties": list(capabilities.properties),
            "abs_axes": [
                {
                    "code": axis.code,
                    "name": axis.name,
                    "minimum": axis.minimum,
                    "maximum": axis.maximum,
                    "fuzz": axis.fuzz,
                    "flat": axis.flat,
                    "resolution": axis.resolution,
                }
                for axis in capabilities.abs_axes
            ],
            "relay_classes": list(capabilities.relay_classes),
        },
        "frames": [{"events": frame.events} for frame in frames],
    }


def _redact_jsonable(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_jsonable(item) for key, item in value.items()}
    return value


def _print_text(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.duration < 0:
        parser.error("--duration must be >= 0")

    result = capture(args.device, args.duration)
    if args.output == "json":
        print(json.dumps(result, sort_keys=True))
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
