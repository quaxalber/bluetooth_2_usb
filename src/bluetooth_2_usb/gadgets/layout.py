from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import usb_hid

from ..hid.descriptors import (
    DEFAULT_KEYBOARD_DESCRIPTOR,
    DEFAULT_MOUSE_DESCRIPTOR,
    MOUSE_CONFIGFS_REPORT_LENGTH,
    MOUSE_IN_REPORT_LENGTH,
)

# Host-visible USB identity/configuration policy for the default composite HID
# gadget. Changing these values can cause host re-enumeration, new cached device
# instances, or different power/wakeup behavior.
#
# References:
# - Linux USB gadget configfs:
#   https://docs.kernel.org/usb/gadget_configfs.html
# - USB device descriptor fields:
#   https://learn.microsoft.com/windows-hardware/drivers/network/device-descriptor
# - USB configuration descriptor fields:
#   https://learn.microsoft.com/windows-hardware/drivers/usbcon/standard-usb-descriptors
# Configuration descriptor bmAttributes: bit 7 must be set, bit 6 would
# advertise self-powered operation, and bit 5 advertises remote wakeup support.
# Leaving bit 6 clear means the default configuration is bus-powered.
USB_CONFIG_REQUIRED_ATTRIBUTES = 0x80
USB_CONFIG_SELF_POWERED = 0x40
USB_CONFIG_REMOTE_WAKEUP = 0x20
DEFAULT_BM_ATTRIBUTES = USB_CONFIG_REQUIRED_ATTRIBUTES
COMBO_BM_ATTRIBUTES = USB_CONFIG_REQUIRED_ATTRIBUTES | USB_CONFIG_REMOTE_WAKEUP
# Device descriptor bcdDevice: device release 2.05 encoded as binary-coded
# decimal. Keep stable unless intentionally changing host-visible USB identity.
DEVICE_RELEASE_BCD = "0x0205"
# Product string descriptor exposed to the host and used by loopback discovery.
USB_PRODUCT_NAME = "USB Combo Device"
# Stable host-visible serial string. Changing it can create a new host-side
# device instance/cache entry.
USB_SERIAL_NUMBER = "213374badcafe"
# Configuration string descriptor exposed to the host for this composite layout.
USB_CONFIGURATION_NAME = "Config 1: HID relay"
# configfs MaxPower is written in mA; Linux encodes the descriptor power units.
USB_CONFIG_MAX_POWER_MA = 100
# Linux gadget speed policy: cap this gadget at USB 2.0 high speed.
USB_GADGET_MAX_SPEED = "high-speed"


class GadgetHidDevice(usb_hid.Device):
    def __init__(
        self,
        *,
        descriptor: bytes,
        usage_page: int,
        usage: int,
        report_ids: Sequence[int],
        in_report_lengths: Sequence[int],
        out_report_lengths: Sequence[int],
        name: str,
        function_index: int,
        protocol: int,
        subclass: int,
        configfs_report_length: int | None = None,
        wakeup_on_write: bool = False,
    ) -> None:
        init_kwargs = {
            "descriptor": descriptor,
            "usage_page": usage_page,
            "usage": usage,
            "report_ids": tuple(report_ids),
            "in_report_lengths": tuple(in_report_lengths),
            "out_report_lengths": tuple(out_report_lengths),
            "name": name,
        }
        try:
            super().__init__(subclass=subclass, protocol=protocol, **init_kwargs)
        except TypeError as exc:
            if "unexpected keyword argument 'subclass'" not in str(exc):
                raise
            super().__init__(**init_kwargs)
        self.function_index = function_index
        self.protocol = protocol
        self.subclass = subclass
        self.configfs_report_length = configfs_report_length
        self.wakeup_on_write = wakeup_on_write

    @classmethod
    def from_existing(
        cls,
        base_device: usb_hid.Device,
        *,
        function_index: int,
        protocol: int,
        subclass: int,
        descriptor: bytes | None = None,
        name: str | None = None,
        report_ids: Sequence[int] | None = None,
        in_report_lengths: Sequence[int] | None = None,
        out_report_lengths: Sequence[int] | None = None,
        configfs_report_length: int | None = None,
        wakeup_on_write: bool | None = None,
    ) -> GadgetHidDevice:
        return cls(
            descriptor=(bytes(base_device.descriptor) if descriptor is None else descriptor),
            usage_page=base_device.usage_page,
            usage=base_device.usage,
            report_ids=(tuple(base_device.report_ids) if report_ids is None else tuple(report_ids)),
            in_report_lengths=(
                tuple(base_device.in_report_lengths) if in_report_lengths is None else tuple(in_report_lengths)
            ),
            out_report_lengths=(
                tuple(base_device.out_report_lengths) if out_report_lengths is None else tuple(out_report_lengths)
            ),
            name=base_device.name if name is None else name,
            function_index=function_index,
            protocol=protocol,
            subclass=subclass,
            configfs_report_length=(
                getattr(base_device, "configfs_report_length", None)
                if configfs_report_length is None
                else configfs_report_length
            ),
            wakeup_on_write=(
                getattr(base_device, "wakeup_on_write", False) if wakeup_on_write is None else wakeup_on_write
            ),
        )

    def get_device_path(self, _report_id=None):
        function_root = Path(usb_hid.gadget_root) / f"functions/hid.usb{self.function_index}"
        device = function_root.joinpath("dev").read_text(encoding="utf-8").strip()
        return f"/dev/hidg{device.split(':')[1]}"


@dataclass(frozen=True, slots=True)
class GadgetLayout:
    devices: tuple[GadgetHidDevice, ...]
    bcd_device: str
    product_name: str
    serial_number: str
    max_power: int = 250
    bm_attributes: int = DEFAULT_BM_ATTRIBUTES
    configuration_name: str = USB_CONFIGURATION_NAME
    max_speed: str | None = None


def build_default_layout() -> GadgetLayout:
    return GadgetLayout(
        devices=(
            GadgetHidDevice.from_existing(
                usb_hid.Device.BOOT_KEYBOARD,
                function_index=0,
                protocol=1,
                subclass=1,
                descriptor=DEFAULT_KEYBOARD_DESCRIPTOR,
                wakeup_on_write=True,
            ),
            GadgetHidDevice.from_existing(
                usb_hid.Device.MOUSE,
                function_index=1,
                protocol=0,
                subclass=0,
                descriptor=DEFAULT_MOUSE_DESCRIPTOR,
                name="mouse gadget",
                report_ids=(0,),
                in_report_lengths=(MOUSE_IN_REPORT_LENGTH,),
                out_report_lengths=(0,),
                configfs_report_length=MOUSE_CONFIGFS_REPORT_LENGTH,
            ),
            GadgetHidDevice.from_existing(usb_hid.Device.CONSUMER_CONTROL, function_index=2, protocol=0, subclass=0),
        ),
        bcd_device=DEVICE_RELEASE_BCD,
        product_name=USB_PRODUCT_NAME,
        serial_number=USB_SERIAL_NUMBER,
        max_power=USB_CONFIG_MAX_POWER_MA,
        bm_attributes=COMBO_BM_ATTRIBUTES,
        max_speed=USB_GADGET_MAX_SPEED,
    )
