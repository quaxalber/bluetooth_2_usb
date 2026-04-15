from __future__ import annotations

import os
from pathlib import Path

import usb_hid

from .hid_descriptors import GadgetHidDevice, GadgetProfile

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


def _teardown_existing_gadget() -> None:
    if not GADGET_ROOT.exists():
        return

    try:
        (GADGET_ROOT / "UDC").write_text("\n", encoding="utf-8")
    except FileNotFoundError:
        pass
    except OSError:
        pass

    for symlink in sorted(GADGET_ROOT.glob("configs/**/hid.usb*"), reverse=True):
        _safe_unlink(symlink)

    for file_path in sorted(GADGET_ROOT.rglob("*"), reverse=True):
        if file_path.is_file():
            _safe_unlink(file_path)
        elif file_path.is_dir():
            _safe_rmdir(file_path)

    _safe_rmdir(GADGET_ROOT)


def _write_text(path: Path, value: str) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")


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


def rebuild_gadget(profile: GadgetProfile) -> tuple[GadgetHidDevice, ...]:
    _teardown_existing_gadget()

    function_root = GADGET_ROOT / "functions"
    config_root = GADGET_ROOT / "configs" / CONFIG_NAME
    gadget_strings = GADGET_ROOT / "strings" / LANGUAGE_ID
    config_strings = config_root / "strings" / LANGUAGE_ID

    function_root.mkdir(parents=True, exist_ok=True)
    config_strings.mkdir(parents=True, exist_ok=True)
    gadget_strings.mkdir(parents=True, exist_ok=True)

    _write_text(GADGET_ROOT / "bcdDevice", profile.bcd_device)
    _write_text(GADGET_ROOT / "bcdUSB", DEFAULT_BCD_USB)
    _write_text(GADGET_ROOT / "bDeviceClass", "0x00")
    _write_text(GADGET_ROOT / "bDeviceProtocol", "0x00")
    _write_text(GADGET_ROOT / "bDeviceSubClass", "0x00")
    _write_text(GADGET_ROOT / "bMaxPacketSize0", DEFAULT_BMAX_PACKET_SIZE0)
    _write_text(GADGET_ROOT / "idProduct", DEFAULT_PRODUCT_ID)
    _write_text(GADGET_ROOT / "idVendor", DEFAULT_VENDOR_ID)
    _write_text(gadget_strings / "serialnumber", profile.serial_number)
    _write_text(gadget_strings / "manufacturer", DEFAULT_MANUFACTURER)
    _write_text(gadget_strings / "product", profile.product_name)

    _write_text(config_strings / "configuration", profile.configuration_name)
    _write_text(config_root / "MaxPower", str(profile.max_power))
    _write_text(config_root / "bmAttributes", hex(profile.bm_attributes))
    if profile.max_speed is not None:
        _write_text(GADGET_ROOT / "max_speed", profile.max_speed)

    for device in profile.devices:
        device_root = function_root / f"hid.usb{device.function_index}"
        device_root.mkdir(parents=True, exist_ok=True)
        _write_text(device_root / "protocol", str(device.protocol))
        _write_text(device_root / "subclass", str(device.subclass))
        _write_text(device_root / "report_length", str(device.in_report_lengths[0]))
        (device_root / "report_desc").write_bytes(bytes(device.descriptor))
        (config_root / f"hid.usb{device.function_index}").symlink_to(device_root)

    _write_text(GADGET_ROOT / "UDC", _resolve_udc_name())

    usb_hid.devices = list(profile.devices)
    for device in profile.devices:
        try:
            device.path = device.get_device_path()
        except FileNotFoundError:
            device.path = None
    return profile.devices
