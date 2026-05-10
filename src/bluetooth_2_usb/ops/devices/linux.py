from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...evdev.types import InputDevice
from ...inputs.filter import DeviceFilter, parse_devices
from ...inputs.inventory import DeviceEnumerationError, list_input_devices

try:
    import pyudev
except ModuleNotFoundError:
    pyudev = None  # type: ignore[assignment]


class DeviceCaptureError(RuntimeError):
    exit_code = 3


class DeviceSelectionError(DeviceCaptureError):
    exit_code = 2


@dataclass(frozen=True, slots=True)
class BoundedRead:
    path: str
    text: str | None = None
    hex: str | None = None
    truncated: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "text": self.text, "hex": self.hex, "truncated": self.truncated, "error": self.error}


def select_input_devices(devices: str) -> list[InputDevice]:
    try:
        device_filters = [DeviceFilter(device) for device in parse_devices(devices)]
    except ValueError as exc:
        raise DeviceSelectionError("DEVICES must not be empty") from exc
    try:
        input_devices = list_input_devices()
    except DeviceEnumerationError as exc:
        raise DeviceCaptureError(str(exc)) from exc

    matches: list[InputDevice] = []
    nonmatches: list[InputDevice] = []
    for device in input_devices:
        if any(device_filter.matches(device) for device_filter in device_filters):
            matches.append(device)
        else:
            nonmatches.append(device)

    if not matches:
        for device in nonmatches:
            device.close()
        candidates = ", ".join(_device_summary(device) for device in nonmatches) or "<none>"
        raise DeviceSelectionError(f"No input device matched {devices!r}. Candidates: {candidates}")

    for device in nonmatches:
        device.close()
    return matches


def select_input_device(devices: str) -> InputDevice:
    input_devices = select_input_devices(devices)
    if len(input_devices) == 1:
        return input_devices[0]
    for device in input_devices:
        device.close()
    candidates = ", ".join(_device_summary(device) for device in input_devices)
    raise DeviceSelectionError(f"Multiple input devices matched {devices!r}. Candidates: {candidates}")


def input_device_record(device: InputDevice) -> dict[str, object]:
    info = getattr(device, "info", None)
    info_record = {}
    if info is not None:
        info_record = {
            "bustype": getattr(info, "bustype", None),
            "vendor": getattr(info, "vendor", None),
            "product": getattr(info, "product", None),
            "version": getattr(info, "version", None),
        }
    return {
        "record_type": "input_device",
        "path": getattr(device, "path", ""),
        "name": getattr(device, "name", ""),
        "phys": getattr(device, "phys", ""),
        "uniq": getattr(device, "uniq", "") or "",
        "version": getattr(device, "version", None),
        "info": info_record,
    }


def evdev_capabilities_record(device: InputDevice) -> dict[str, object]:
    try:
        verbose = device.capabilities(verbose=True)
    except TypeError:
        verbose = device.capabilities()
    return {"record_type": "evdev_capabilities", "path": getattr(device, "path", ""), "capabilities": verbose}


def evdev_input_properties_record(device: InputDevice) -> dict[str, object]:
    path = getattr(device, "path", "")
    input_props = getattr(device, "input_props", None)
    if input_props is None:
        return {
            "record_type": "evdev_input_properties",
            "path": path,
            "properties": [],
            "error": "input properties unavailable",
        }
    try:
        try:
            properties = input_props(verbose=True)
        except TypeError:
            properties = input_props()
    except Exception as exc:
        return {"record_type": "evdev_input_properties", "path": path, "properties": [], "error": str(exc)}
    return {"record_type": "evdev_input_properties", "path": path, "properties": properties}


def udev_properties_record(device: InputDevice) -> dict[str, object]:
    path = getattr(device, "path", "")
    properties: dict[str, object] = {}
    if pyudev is None:
        return {"record_type": "udev_properties", "path": path, "properties": properties, "error": "pyudev unavailable"}
    try:
        context = pyudev.Context()
        udev_device = pyudev.Devices.from_device_file(context, path)
        properties = dict(udev_device.properties)
    except Exception as exc:
        return {"record_type": "udev_properties", "path": path, "properties": properties, "error": str(exc)}
    return {"record_type": "udev_properties", "path": path, "properties": properties}


def sysfs_snapshot_record(device: InputDevice, max_bytes: int) -> dict[str, object]:
    event_path = Path("/sys/class/input") / Path(getattr(device, "path", "")).name
    roots = _existing_paths([event_path, event_path / "device", event_path / "device/device"])
    file_names = ("name", "phys", "uniq", "modalias", "uevent", "id/bustype", "id/vendor", "id/product", "id/version")
    files: list[dict[str, object]] = []
    seen: set[Path] = set()
    for root in roots:
        for relative in file_names:
            path = root / relative
            if path in seen:
                continue
            seen.add(path)
            if path.is_file():
                files.append(read_bounded_text(path, max_bytes).to_dict())

    return {
        "record_type": "sysfs_snapshot",
        "path": getattr(device, "path", ""),
        "roots": [str(root) for root in roots],
        "files": files,
    }


def discover_hidraw_nodes(device: InputDevice) -> list[Path]:
    event_path = Path("/sys/class/input") / Path(getattr(device, "path", "")).name
    roots = _existing_paths([event_path / "device", event_path / "device/device"])
    nodes: set[Path] = set()
    for root in roots:
        hidraw_dir = root / "hidraw"
        if hidraw_dir.is_dir():
            for entry in hidraw_dir.iterdir():
                node = _hidraw_device_node(entry)
                if node is not None:
                    nodes.add(node)
        for entry in root.glob("*/hidraw/hidraw*"):
            node = _hidraw_device_node(entry)
            if node is not None:
                nodes.add(node)
        for entry in root.glob("*/hidraw*"):
            node = _hidraw_device_node(entry)
            if node is not None:
                nodes.add(node)
    return sorted(nodes)


def hidraw_node_records(nodes: list[Path], max_bytes: int) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for node in nodes:
        sysfs_root = Path("/sys/class/hidraw") / node.name / "device"
        descriptor_paths = [
            sysfs_root / "report_descriptor",
            sysfs_root / "device/report_descriptor",
            sysfs_root / "uevent",
        ]
        records.append(
            {
                "record_type": "hidraw_node",
                "path": str(node),
                "sysfs_root": str(sysfs_root),
                "files": [
                    read_bounded_bytes(path, max_bytes).to_dict()
                    for path in descriptor_paths
                    if path.is_file() or path.name == "report_descriptor"
                ],
            }
        )
    return records


def open_hidraw_nodes(nodes: list[Path]) -> tuple[list[tuple[Path, int]], list[dict[str, object]]]:
    opened: list[tuple[Path, int]] = []
    warnings: list[dict[str, object]] = []
    for node in nodes:
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            warnings.append(
                {
                    "record_type": "capture_warning",
                    "source": "hidraw",
                    "path": str(node),
                    "message": f"failed to open hidraw node: {exc}",
                }
            )
            continue
        opened.append((node, fd))
    return opened, warnings


def close_hidraw_nodes(opened: list[tuple[Path, int]]) -> None:
    for _path, fd in opened:
        try:
            os.close(fd)
        except OSError:
            pass


def read_hidraw(fd: int, max_bytes: int) -> bytes | None:
    if max_bytes < 0:
        raise ValueError("max_bytes must be >= 0")
    try:
        return os.read(fd, max_bytes + 1)
    except BlockingIOError:
        return None
    except OSError as exc:
        if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        raise


def read_bounded_text(path: Path, max_bytes: int) -> BoundedRead:
    bounded = read_bounded_bytes(path, max_bytes)
    if bounded.hex is None:
        return bounded
    try:
        text = bytes.fromhex(bounded.hex).decode("utf-8", errors="replace").rstrip("\n")
    except ValueError:
        text = None
    return BoundedRead(path=bounded.path, text=text, truncated=bounded.truncated, error=bounded.error)


def read_bounded_bytes(path: Path, max_bytes: int) -> BoundedRead:
    if max_bytes < 0:
        return BoundedRead(path=str(path), error="max_bytes must be >= 0")
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as exc:
        return BoundedRead(path=str(path), error=str(exc))
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return BoundedRead(path=str(path), hex=data.hex(" "), truncated=truncated)


def _existing_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not path.exists():
            continue
        seen.add(resolved)
        result.append(path)
    return result


def _hidraw_device_node(path: Path) -> Path | None:
    suffix = path.name.removeprefix("hidraw")
    if suffix and suffix.isdigit():
        return Path("/dev") / path.name
    return None


def _device_summary(device: Any) -> str:
    return f"{getattr(device, 'path', '<unknown>')} ({getattr(device, 'name', '') or '-'})"
