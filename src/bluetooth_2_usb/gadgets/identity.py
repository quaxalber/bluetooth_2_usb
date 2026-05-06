"""Stable host-visible USB identity for the managed Bluetooth-2-USB gadget."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path

from ..logging import get_logger

logger = get_logger(__name__)

USB_GADGET_VID_LINUX = 0x1D6B
"""USB device descriptor idVendor: Linux Foundation VID used by gadget examples."""

USB_GADGET_PID_COMBO = 0x0104
"""USB device descriptor idProduct for this multifunction composite gadget."""

USB_MANUFACTURER = "quaxalber"
"""Manufacturer string descriptor exposed to the host."""

USB_PRODUCT_NAME = "USB Combo Device"
"""Product string descriptor exposed to the host and used by loopback discovery."""

USB_SERIAL_NUMBER = "213374badcafe"
"""Fallback host-visible serial string used when no local identity can be resolved."""

DEFAULT_USB_IDENTITY_PATH = Path("/var/lib/bluetooth_2_usb/usb_identity.json")
"""Persistent per-install USB identity state for the managed service."""

USB_SERIAL_PREFIX = "b2u"
"""Prefix used for generated per-install USB serials."""

USB_SERIAL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
"""Conservative USB serial string policy accepted by Linux, udev, and common hosts."""

USB_PRODUCT_SUFFIX_PATTERN = re.compile(r"^[A-Za-z0-9._ -]{1,48}$")
"""Conservative product suffix policy for readable host-side diagnostics."""


@dataclass(frozen=True, slots=True)
class UsbIdentity:
    product_name: str
    serial_number: str


def usb_configfs_hex_u16(value: int) -> str:
    """Format a 16-bit USB descriptor value for configfs descriptor attributes."""
    return f"0x{value:04x}"


def usb_udev_hex_u16(value: int) -> str:
    """Format a 16-bit USB descriptor value for udev attribute matching."""
    return f"{value:04x}"


def validate_usb_serial(value: str) -> str:
    serial = value.strip()
    if not USB_SERIAL_PATTERN.fullmatch(serial):
        raise ValueError(
            "USB serial must be 1-64 characters and contain only ASCII letters, digits, '.', '_', or '-'."
        )
    return serial


def validate_usb_product_suffix(value: str) -> str:
    suffix = value.strip()
    if not suffix:
        return ""
    if not USB_PRODUCT_SUFFIX_PATTERN.fullmatch(suffix):
        raise ValueError(
            "USB product suffix must be 1-48 characters and contain only ASCII letters, digits, spaces, '.', '_', or '-'."
        )
    return suffix


def product_name_with_suffix(suffix: str) -> str:
    normalized = validate_usb_product_suffix(suffix)
    return f"{USB_PRODUCT_NAME} {normalized}" if normalized else USB_PRODUCT_NAME


def generate_usb_serial() -> str:
    return USB_SERIAL_PREFIX + secrets.token_hex(8)


def _fallback_serial() -> str:
    seed_parts: list[str] = []
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            seed_parts.append(value)
            break
    seed_parts.append(socket.gethostname())
    digest = hashlib.sha256(":".join(seed_parts).encode("utf-8")).hexdigest()[:16]
    return USB_SERIAL_PREFIX + digest


def _read_persisted_serial(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid USB identity file %s: %s", path, exc)
        return None

    serial = data.get("serial_number") if isinstance(data, dict) else None
    if not isinstance(serial, str):
        logger.warning("Ignoring USB identity file %s without serial_number", path)
        return None
    try:
        return validate_usb_serial(serial)
    except ValueError as exc:
        logger.warning("Ignoring invalid USB serial in %s: %s", path, exc)
        return None


def _write_persisted_serial(path: Path, serial: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps({"serial_number": serial}, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    tmp_path.replace(path)


def load_or_create_usb_identity(
    *, serial_override: str = "", product_suffix: str = "", state_path: Path = DEFAULT_USB_IDENTITY_PATH
) -> UsbIdentity:
    if serial_override.strip():
        serial = validate_usb_serial(serial_override)
    else:
        serial = _read_persisted_serial(state_path)
        if serial is None:
            serial = generate_usb_serial()
            try:
                _write_persisted_serial(state_path, serial)
            except OSError as exc:
                serial = _fallback_serial()
                logger.warning(
                    "Could not persist generated USB identity at %s: %s; using deterministic fallback serial %s",
                    state_path,
                    exc,
                    serial,
                )

    return UsbIdentity(product_name=product_name_with_suffix(product_suffix), serial_number=serial)
