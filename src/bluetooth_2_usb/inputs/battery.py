from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

LOW_BATTERY_THRESHOLD_PERCENT = 15
"""Default battery percentage at or below which a low-battery warning is triggered."""

_MAC_PATTERN = re.compile(r"([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})")
_BLUETOOTHCTL_BATTERY_PATTERN = re.compile(r"Battery Percentage:.*?\((\d+)\)|Battery Percentage:\s*(\d+)%")


def extract_bluetooth_mac(device: Any) -> str | None:
    """Return a normalized lowercase colon-separated MAC address from device uniq or phys."""
    for attr in ("uniq", "phys"):
        raw = getattr(device, attr, "") or ""
        match = _MAC_PATTERN.search(raw)
        if match:
            return match.group(1).lower().replace("-", ":")
    return None


def _parse_capacity_file(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def _read_sysfs_input_battery(device_path: str, sys_class_input: Path) -> int | None:
    event_name = Path(device_path).name
    if not event_name.startswith("event"):
        return None
    input_device_dir = sys_class_input / event_name / "device"
    for candidate_root in (input_device_dir / "power_supply", input_device_dir / "device" / "power_supply"):
        try:
            entries = sorted(candidate_root.iterdir())
        except OSError:
            continue
        for entry in entries:
            capacity = _parse_capacity_file(entry / "capacity")
            if capacity is not None:
                return capacity
    return None


def _read_sysfs_mac_battery(mac: str, sys_class_power_supply: Path) -> int | None:
    mac_colon = mac.lower()
    mac_dash = mac_colon.replace(":", "-")
    try:
        supplies = sorted(sys_class_power_supply.iterdir())
    except OSError:
        return None

    for supply in supplies:
        name_lower = supply.name.lower()
        try:
            resolved_lower = str(supply.resolve()).lower()
        except OSError:
            resolved_lower = ""
        if not any(token in text for token in (mac_colon, mac_dash) for text in (name_lower, resolved_lower)):
            continue
        capacity = _parse_capacity_file(supply / "capacity")
        if capacity is not None:
            return capacity
    return None


def _read_bluetoothctl_battery(mac: str) -> int | None:
    cmd = ["bluetoothctl", "info", mac]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    match = _BLUETOOTHCTL_BATTERY_PATTERN.search(completed.stdout)
    if not match:
        return None
    raw_value = match.group(1) or match.group(2)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def read_device_battery_percent(
    device: Any,
    *,
    sys_class_input: Path = Path("/sys/class/input"),
    sys_class_power_supply: Path = Path("/sys/class/power_supply"),
    use_bluetoothctl_fallback: bool = True,
) -> int | None:
    """Read the battery percentage (0-100) for an input device, or None if unavailable."""
    device_path = getattr(device, "path", "") or ""
    if device_path:
        capacity = _read_sysfs_input_battery(device_path, sys_class_input)
        if capacity is not None:
            return capacity

    mac = extract_bluetooth_mac(device)
    if mac is None:
        return None

    capacity = _read_sysfs_mac_battery(mac, sys_class_power_supply)
    if capacity is not None:
        return capacity

    if use_bluetoothctl_fallback:
        return _read_bluetoothctl_battery(mac)
    return None
