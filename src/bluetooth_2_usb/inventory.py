from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any

from .logging import get_logger

_logger = get_logger()

DEFAULT_SKIP_NAME_PREFIXES = (
    "vc4-hdmi",
    "vc4",
    "gpio",
    "pwr_button",
    "raspberrypi-ts",
)


class DeviceEnumerationError(RuntimeError):
    pass


try:
    from evdev import InputDevice, list_devices
    from evdev import ecodes as native_ecodes
except ModuleNotFoundError as exc:
    InputDevice = Any  # type: ignore[assignment]
    list_devices = None  # type: ignore[assignment]
    native_ecodes = SimpleNamespace(EV_KEY=0x01, EV_REL=0x02)
    _EVDEV_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _EVDEV_IMPORT_ERROR = None


EVENT_TYPE_NAMES = {
    native_ecodes.EV_KEY: "EV_KEY",
    native_ecodes.EV_REL: "EV_REL",
}


@dataclass(slots=True)
class InputDeviceMetadata:
    path: str
    name: str
    phys: str
    uniq: str
    capabilities: list[str]
    relay_candidate: bool
    exclusion_reason: str | None

    @property
    def identity(self) -> str:
        return self.uniq or self.phys or "-"

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"identity": self.identity}


def auto_discover_exclusion_reason(
    device: InputDevice,
    skip_name_prefixes: tuple[str, ...] = DEFAULT_SKIP_NAME_PREFIXES,
) -> str | None:
    name = (device.name or "").strip()
    name_lower = name.lower()
    for prefix in skip_name_prefixes:
        if name_lower.startswith(prefix.lower()):
            return f"name prefix {prefix}"

    try:
        capabilities = device.capabilities(verbose=False)
    except OSError as exc:
        return f"failed to read capabilities ({exc})"

    if not any(code in capabilities for code in EVENT_TYPE_NAMES):
        return "missing EV_KEY/EV_REL capabilities"

    return None


def list_input_device_paths() -> list[str]:
    if _EVDEV_IMPORT_ERROR is not None or list_devices is None:
        raise DeviceEnumerationError(
            "python-evdev is required to enumerate input devices on this host"
        ) from _EVDEV_IMPORT_ERROR
    try:
        return list(list_devices())
    except (OSError, FileNotFoundError) as exc:
        raise DeviceEnumerationError(f"failed listing devices: {exc}") from exc
    except Exception as exc:
        raise DeviceEnumerationError("unexpected error listing devices") from exc


def list_input_devices() -> list[InputDevice]:
    devices: list[InputDevice] = []
    for path in list_input_device_paths():
        try:
            devices.append(InputDevice(path))
        except (OSError, FileNotFoundError) as exc:
            raise DeviceEnumerationError(
                f"failed opening input device {path}: {exc}"
            ) from exc
    return devices


def describe_input_devices(
    skip_name_prefixes: tuple[str, ...] = DEFAULT_SKIP_NAME_PREFIXES,
) -> list[InputDeviceMetadata]:
    metadata: list[InputDeviceMetadata] = []
    for device in list_input_devices():
        try:
            capabilities = sorted(
                EVENT_TYPE_NAMES[code]
                for code in device.capabilities(verbose=False)
                if code in EVENT_TYPE_NAMES
            )
        except OSError as exc:
            capabilities = []
            exclusion_reason = f"failed to read capabilities ({exc})"
        else:
            exclusion_reason = auto_discover_exclusion_reason(
                device, skip_name_prefixes
            )

        metadata.append(
            InputDeviceMetadata(
                path=device.path,
                name=device.name,
                phys=device.phys,
                uniq=device.uniq or "",
                capabilities=capabilities,
                relay_candidate=exclusion_reason is None,
                exclusion_reason=exclusion_reason,
            )
        )
        device.close()
    return metadata


def inventory_to_text(devices: list[InputDeviceMetadata]) -> str:
    lines = []
    for device in devices:
        status = "relay" if device.relay_candidate else "skip"
        line = f"{status}\t{device.name}\t{device.identity}\t{device.path}"
        if device.exclusion_reason:
            line = f"{line}\t{device.exclusion_reason}"
        lines.append(line)
    return "\n".join(lines)
