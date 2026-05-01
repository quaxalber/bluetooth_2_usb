from __future__ import annotations

import os
from pathlib import Path

import usb_hid

from .hid_gadget_layout import GadgetHidDevice, GadgetLayout

GADGET_ROOT = Path(usb_hid.gadget_root)
CONFIG_NAME = "c.1"
LANGUAGE_ID = "0x409"
DEFAULT_VENDOR_ID = "0x1d6b"
DEFAULT_PRODUCT_ID = "0x0104"
DEFAULT_BCD_USB = "0x0200"
DEFAULT_BMAX_PACKET_SIZE0 = "0x40"
DEFAULT_MANUFACTURER = "quaxalber"


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
    """Remove USB gadget trees owned by this application.

    :return: None.
    """
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
    """Rebuild the configured USB HID gadget layout and return opened HID devices.

    :return: The requested value or status result.
    """
    _teardown_existing_gadget()

    function_root = GADGET_ROOT / "functions"
    config_root = GADGET_ROOT / "configs" / CONFIG_NAME
    gadget_strings = GADGET_ROOT / "strings" / LANGUAGE_ID
    config_strings = config_root / "strings" / LANGUAGE_ID

    function_root.mkdir(parents=True, exist_ok=True)
    config_strings.mkdir(parents=True, exist_ok=True)
    gadget_strings.mkdir(parents=True, exist_ok=True)

    _write_text(GADGET_ROOT / "bcdDevice", layout.bcd_device)
    _write_text(GADGET_ROOT / "bcdUSB", DEFAULT_BCD_USB)
    _write_text(GADGET_ROOT / "bDeviceClass", "0x00")
    _write_text(GADGET_ROOT / "bDeviceProtocol", "0x00")
    _write_text(GADGET_ROOT / "bDeviceSubClass", "0x00")
    _write_text(GADGET_ROOT / "bMaxPacketSize0", DEFAULT_BMAX_PACKET_SIZE0)
    _write_text(GADGET_ROOT / "idProduct", DEFAULT_PRODUCT_ID)
    _write_text(GADGET_ROOT / "idVendor", DEFAULT_VENDOR_ID)
    _write_text(gadget_strings / "serialnumber", layout.serial_number)
    _write_text(gadget_strings / "manufacturer", DEFAULT_MANUFACTURER)
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
