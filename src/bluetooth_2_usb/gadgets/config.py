from __future__ import annotations

import os
from pathlib import Path

import usb_hid

from .layout import GadgetHidDevice, GadgetLayout

GADGET_ROOT = Path(usb_hid.gadget_root)
CONFIG_NAME = "c.1"

# USB gadget configfs values are written as text attributes; Linux parses them
# into USB descriptors exposed to the host.
#
# References:
# - Linux USB gadget configfs:
#   https://docs.kernel.org/usb/gadget_configfs.html
# - Linux USB gadget API:
#   https://kernel.org/doc/html/next/driver-api/usb/gadget.html
# - USB device descriptor fields:
#   https://learn.microsoft.com/windows-hardware/drivers/network/device-descriptor
# - USB configuration descriptor fields:
#   https://learn.microsoft.com/windows-hardware/drivers/usbcon/standard-usb-descriptors
# String descriptor language ID: English, United States.
USB_STRING_LANGID_EN_US = "0x409"
# Device descriptor idVendor. 0x1d6b is the Linux Foundation VID commonly used
# by Linux USB gadget examples/defaults.
USB_VENDOR_ID_LINUX_FOUNDATION = "0x1d6b"
# Device descriptor idProduct for the Linux Foundation multifunction composite
# gadget identity used by this project and its host-side discovery/udev rules.
USB_PRODUCT_ID_MULTIFUNCTION_COMPOSITE = "0x0104"
# Device descriptor bcdUSB: USB 2.00 encoded as binary-coded decimal.
USB_SPEC_VERSION_BCD = "0x0200"
# Device descriptor bMaxPacketSize0: 64-byte endpoint-zero control packets.
USB_EP0_MAX_PACKET_SIZE_BYTES = "0x40"
# Manufacturer string descriptor exposed to the host.
USB_MANUFACTURER = "quaxalber"
# Device class 0 means each interface declares its own class/subclass/protocol.
USB_DEVICE_CLASS_PER_INTERFACE = "0x00"
USB_DEVICE_PROTOCOL_NONE = "0x00"
USB_DEVICE_SUBCLASS_NONE = "0x00"


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
    configfs_root = GADGET_ROOT.parent
    if not configfs_root.is_dir():
        return

    gadget_roots = [GADGET_ROOT, *configfs_root.glob("bluetooth_2_usb*")]
    seen: set[Path] = set()
    for gadget_root in gadget_roots:
        if gadget_root in seen:
            continue
        seen.add(gadget_root)
        _remove_gadget_tree(gadget_root)


def _teardown_existing_gadget() -> None:
    _remove_gadget_tree(GADGET_ROOT)


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

    function_root = GADGET_ROOT / "functions"
    config_root = GADGET_ROOT / "configs" / CONFIG_NAME
    gadget_strings = GADGET_ROOT / "strings" / USB_STRING_LANGID_EN_US
    config_strings = config_root / "strings" / USB_STRING_LANGID_EN_US

    function_root.mkdir(parents=True, exist_ok=True)
    config_strings.mkdir(parents=True, exist_ok=True)
    gadget_strings.mkdir(parents=True, exist_ok=True)

    _write_text(GADGET_ROOT / "bcdDevice", layout.bcd_device)
    _write_text(GADGET_ROOT / "bcdUSB", USB_SPEC_VERSION_BCD)
    _write_text(GADGET_ROOT / "bDeviceClass", USB_DEVICE_CLASS_PER_INTERFACE)
    _write_text(GADGET_ROOT / "bDeviceProtocol", USB_DEVICE_PROTOCOL_NONE)
    _write_text(GADGET_ROOT / "bDeviceSubClass", USB_DEVICE_SUBCLASS_NONE)
    _write_text(GADGET_ROOT / "bMaxPacketSize0", USB_EP0_MAX_PACKET_SIZE_BYTES)
    _write_text(GADGET_ROOT / "idProduct", USB_PRODUCT_ID_MULTIFUNCTION_COMPOSITE)
    _write_text(GADGET_ROOT / "idVendor", USB_VENDOR_ID_LINUX_FOUNDATION)
    _write_text(gadget_strings / "serialnumber", layout.serial_number)
    _write_text(gadget_strings / "manufacturer", USB_MANUFACTURER)
    _write_text(gadget_strings / "product", layout.product_name)

    _write_text(config_strings / "configuration", layout.configuration_name)
    _write_text(config_root / "MaxPower", str(layout.max_power))
    _write_text(config_root / "bmAttributes", hex(layout.bm_attributes))
    if layout.max_speed is not None:
        _write_text(GADGET_ROOT / "max_speed", layout.max_speed)

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

    _write_text(GADGET_ROOT / "UDC", _resolve_udc_name())

    usb_hid.devices = list(layout.devices)
    for device in layout.devices:
        try:
            device.path = device.get_device_path()
        except FileNotFoundError:
            device.path = None
    return layout.devices
