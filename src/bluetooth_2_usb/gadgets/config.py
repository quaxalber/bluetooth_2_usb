"""USB gadget configfs writes for the default Bluetooth-2-USB composite device.

USB gadget configfs values are written as text attributes. Linux parses them
into USB descriptors exposed to the host.

References:
- Linux USB gadget configfs:
  https://docs.kernel.org/usb/gadget_configfs.html
- Linux USB gadget API:
  https://kernel.org/doc/html/next/driver-api/usb/gadget.html
- USB device descriptor fields:
  https://learn.microsoft.com/windows-hardware/drivers/network/device-descriptor
- USB configuration descriptor fields:
  https://learn.microsoft.com/windows-hardware/drivers/usbcon/standard-usb-descriptors
"""

from __future__ import annotations

import os
from pathlib import Path

import usb_hid

from .identity import USB_GADGET_PID_COMBO, USB_GADGET_VID_LINUX, usb_configfs_hex_u16
from .layout import GadgetHidDevice, GadgetLayout

USB_GADGET_ROOT = Path(usb_hid.gadget_root)
"""Configfs root path for the managed Bluetooth-2-USB gadget."""

USB_CFG_DIR_NAME = "c.1"
"""Default configfs configuration directory name."""

USB_LANGID_EN_US = "0x409"
"""String descriptor language ID: English, United States."""

USB_SPEC_VERSION_BCD = "0x0200"
"""USB device descriptor bcdUSB: USB 2.00 encoded as binary-coded decimal."""

USB_EP0_MAX_PACKET_SIZE_BYTES = "0x40"
"""USB device descriptor bMaxPacketSize0: 64-byte endpoint-zero control packets."""

USB_MANUFACTURER = "quaxalber"
"""Manufacturer string descriptor exposed to the host."""

USB_DEV_CLASS_PER_INTERFACE = "0x00"
"""USB device class 0: each interface declares its own class/subclass/protocol."""

USB_DEV_PROTOCOL_NONE = "0x00"
"""USB device protocol 0: no device-level protocol."""

USB_DEV_SUBCLASS_NONE = "0x00"
"""USB device subclass 0: no device-level subclass."""


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _safe_rmdir(path: Path) -> None:
    try:
        path.rmdir()
    except FileNotFoundError:
        pass


def _safe_write_text(path: Path, value: str) -> None:
    try:
        path.write_text(value, encoding="utf-8")
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _remove_gadget_tree(gadget_root: Path) -> None:
    if not gadget_root.exists():
        return

    _safe_write_text(gadget_root / "UDC", "\n")

    for symlink in sorted(gadget_root.glob("configs/**/hid.usb*"), reverse=True):
        _safe_unlink(symlink)

    for file_path in sorted(gadget_root.rglob("*"), reverse=True):
        if file_path.is_symlink():
            _safe_unlink(file_path)
            continue
        if file_path.is_file():
            _safe_unlink(file_path)
        elif file_path.is_dir():
            _safe_rmdir(file_path)

    _safe_rmdir(gadget_root)


def remove_owned_gadgets() -> None:
    configfs_root = USB_GADGET_ROOT.parent
    if not configfs_root.is_dir():
        return

    gadget_roots = [USB_GADGET_ROOT, *configfs_root.glob("bluetooth_2_usb*")]
    seen: set[Path] = set()
    for gadget_root in gadget_roots:
        if gadget_root in seen:
            continue
        seen.add(gadget_root)
        _remove_gadget_tree(gadget_root)


def _teardown_existing_gadget() -> None:
    _remove_gadget_tree(USB_GADGET_ROOT)


def _write_text(path: Path, value: str) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")


def _maybe_write_wakeup_on_write(device_root: Path, enabled: bool) -> None:
    wakeup_path = device_root / "wakeup_on_write"
    if not wakeup_path.exists():
        return
    _write_text(wakeup_path, "1" if enabled else "0")


def _resolve_udc_name() -> str:
    override_path = os.environ.get("BLUETOOTH_2_USB_UDC_PATH")
    if override_path:
        candidate = Path(override_path)
        if candidate.name == "state":
            return candidate.parent.name
        return candidate.name

    controllers = sorted(entry.name for entry in Path("/sys/class/udc").iterdir())
    if not controllers:
        raise FileNotFoundError("No UDC controller was found in /sys/class/udc")
    return controllers[0]


def rebuild_gadget(layout: GadgetLayout) -> tuple[GadgetHidDevice, ...]:
    _teardown_existing_gadget()

    function_root = USB_GADGET_ROOT / "functions"
    config_root = USB_GADGET_ROOT / "configs" / USB_CFG_DIR_NAME
    gadget_strings = USB_GADGET_ROOT / "strings" / USB_LANGID_EN_US
    config_strings = config_root / "strings" / USB_LANGID_EN_US

    function_root.mkdir(parents=True, exist_ok=True)
    config_strings.mkdir(parents=True, exist_ok=True)
    gadget_strings.mkdir(parents=True, exist_ok=True)

    _write_text(USB_GADGET_ROOT / "bcdDevice", layout.bcd_device)
    _write_text(USB_GADGET_ROOT / "bcdUSB", USB_SPEC_VERSION_BCD)
    _write_text(USB_GADGET_ROOT / "bDeviceClass", USB_DEV_CLASS_PER_INTERFACE)
    _write_text(USB_GADGET_ROOT / "bDeviceProtocol", USB_DEV_PROTOCOL_NONE)
    _write_text(USB_GADGET_ROOT / "bDeviceSubClass", USB_DEV_SUBCLASS_NONE)
    _write_text(USB_GADGET_ROOT / "bMaxPacketSize0", USB_EP0_MAX_PACKET_SIZE_BYTES)
    _write_text(USB_GADGET_ROOT / "idProduct", usb_configfs_hex_u16(USB_GADGET_PID_COMBO))
    _write_text(USB_GADGET_ROOT / "idVendor", usb_configfs_hex_u16(USB_GADGET_VID_LINUX))
    _write_text(gadget_strings / "serialnumber", layout.serial_number)
    _write_text(gadget_strings / "manufacturer", USB_MANUFACTURER)
    _write_text(gadget_strings / "product", layout.product_name)

    _write_text(config_strings / "configuration", layout.configuration_name)
    _write_text(config_root / "MaxPower", str(layout.max_power))
    _write_text(config_root / "bmAttributes", hex(layout.bm_attributes))
    if layout.max_speed is not None:
        _write_text(USB_GADGET_ROOT / "max_speed", layout.max_speed)

    for device in layout.devices:
        device_root = function_root / f"hid.usb{device.function_index}"
        device_root.mkdir(parents=True, exist_ok=True)
        _write_text(device_root / "protocol", str(device.protocol))
        _write_text(device_root / "subclass", str(device.subclass))
        report_length = device.configfs_report_length or device.in_report_lengths[0]
        _write_text(device_root / "report_length", str(report_length))
        (device_root / "report_desc").write_bytes(bytes(device.descriptor))
        _maybe_write_wakeup_on_write(device_root, device.wakeup_on_write)
        (config_root / f"hid.usb{device.function_index}").symlink_to(device_root)

    _write_text(USB_GADGET_ROOT / "UDC", _resolve_udc_name())

    usb_hid.devices = list(layout.devices)
    for device in layout.devices:
        try:
            device.path = device.get_device_path()
        except FileNotFoundError:
            device.path = None
    return layout.devices
