from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import usb_hid

# Keep descriptor bytes in two-byte rows to match the Adafruit HID descriptor
# style and make HID item boundaries easier to review.
# fmt: off
DEFAULT_KEYBOARD_DESCRIPTOR = bytes(
    (
        0x05, 0x01,  # Usage Page (Generic Desktop)
        0x09, 0x06,  # Usage (Keyboard)
        0xA1, 0x01,  # Collection (Application)
        0x05, 0x07,  # Usage Page (Keyboard)
        0x19, 0xE0,  # Usage Minimum (Keyboard LeftControl)
        0x29, 0xE7,  # Usage Maximum (Keyboard Right GUI)
        0x15, 0x00,  # Logical Minimum (0)
        0x25, 0x01,  # Logical Maximum (1)
        0x75, 0x01,  # Report Size (1)
        0x95, 0x08,  # Report Count (8)
        0x81, 0x02,  # Input (Data, Variable, Absolute)
        0x95, 0x01,  # Report Count (1)
        0x75, 0x08,  # Report Size (8)
        0x81, 0x01,  # Input (Constant)
        0x95, 0x03,  # Report Count (3)
        0x75, 0x01,  # Report Size (1)
        0x05, 0x08,  # Usage Page (LEDs)
        0x19, 0x01,  # Usage Minimum (Num Lock)
        0x29, 0x03,  # Usage Maximum (Scroll Lock)
        0x91, 0x02,  # Output (Data, Variable, Absolute)
        0x95, 0x05,  # Report Count (5)
        0x75, 0x01,  # Report Size (1)
        0x91, 0x01,  # Output (Constant)
        0x95, 0x06,  # Report Count (6)
        0x75, 0x08,  # Report Size (8)
        0x15, 0x00,  # Logical Minimum (0)
        0x26, 0xFF,  # Logical Maximum (255)
        0x00, 0x05,  # Logical Maximum continuation, Usage Page
        0x07, 0x19,  # Usage Page continuation, Usage Minimum
        0x00, 0x2A,  # Usage Minimum continuation, Usage Maximum
        0xFF, 0x00,  # Usage Maximum continuation
        0x81, 0x00,  # Input (Data, Array)
        0xC0,  # End Collection
    )
)

DEFAULT_MOUSE_DESCRIPTOR = bytes(
    (
        0x05, 0x01,  # Usage Page (Generic Desktop)
        0x09, 0x02,  # Usage (Mouse)
        0xA1, 0x01,  # Collection (Application)
        0x09, 0x01,  # Usage (Pointer)
        0xA1, 0x00,  # Collection (Physical)
        0x05, 0x09,  # Usage Page (Button)
        0x19, 0x01,  # Usage Minimum (Button 1)
        0x29, 0x08,  # Usage Maximum (Button 8)
        0x15, 0x00,  # Logical Minimum (0)
        0x25, 0x01,  # Logical Maximum (1)
        0x95, 0x08,  # Report Count (8)
        0x75, 0x01,  # Report Size (1)
        0x81, 0x02,  # Input (Data, Variable, Absolute)
        0x05, 0x01,  # Usage Page (Generic Desktop)
        0x09, 0x30,  # Usage (X)
        0x09, 0x31,  # Usage (Y)
        0x16, 0x01,  # Logical Minimum (-32767)
        0x80, 0x26,  # Logical Minimum continuation, Logical Maximum
        0xFF, 0x7F,  # Logical Maximum continuation (32767)
        0x75, 0x10,  # Report Size (16)
        0x95, 0x02,  # Report Count (2)
        0x81, 0x06,  # Input (Data, Variable, Relative)
        0x09, 0x38,  # Usage (Wheel)
        0x15, 0x81,  # Logical Minimum (-127)
        0x25, 0x7F,  # Logical Maximum (127)
        0x75, 0x08,  # Report Size (8)
        0x95, 0x01,  # Report Count (1)
        0x81, 0x06,  # Input (Data, Variable, Relative)
        0x05, 0x0C,  # Usage Page (Consumer)
        0x0A, 0x38,  # Usage (AC Pan)
        0x02, 0x15,  # Usage continuation, Logical Minimum
        0x81, 0x25,  # Logical Minimum continuation, Logical Maximum
        0x7F, 0x75,  # Logical Maximum continuation, Report Size
        0x08, 0x95,  # Report Size continuation, Report Count
        0x01, 0x81,  # Report Count continuation, Input
        0x06, 0xC0,  # Input continuation, End Collection
        0xC0,  # End Collection
    )
)
# fmt: on


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
            super().__init__(
                subclass=subclass,
                protocol=protocol,
                **init_kwargs,
            )
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
            descriptor=(
                bytes(base_device.descriptor) if descriptor is None else descriptor
            ),
            usage_page=base_device.usage_page,
            usage=base_device.usage,
            report_ids=(
                tuple(base_device.report_ids)
                if report_ids is None
                else tuple(report_ids)
            ),
            in_report_lengths=(
                tuple(base_device.in_report_lengths)
                if in_report_lengths is None
                else tuple(in_report_lengths)
            ),
            out_report_lengths=(
                tuple(base_device.out_report_lengths)
                if out_report_lengths is None
                else tuple(out_report_lengths)
            ),
            name=base_device.name if name is None else name,
            function_index=function_index,
            protocol=protocol,
            subclass=subclass,
            configfs_report_length=configfs_report_length,
            wakeup_on_write=(
                getattr(base_device, "wakeup_on_write", False)
                if wakeup_on_write is None
                else wakeup_on_write
            ),
        )

    def get_device_path(self, report_id=None):
        function_root = (
            Path(usb_hid.gadget_root) / f"functions/hid.usb{self.function_index}"
        )
        device = function_root.joinpath("dev").read_text(encoding="utf-8").strip()
        return f"/dev/hidg{device.split(':')[1]}"


@dataclass(frozen=True, slots=True)
class GadgetLayout:
    devices: tuple[GadgetHidDevice, ...]
    bcd_device: str
    product_name: str
    serial_number: str
    max_power: int = 250
    bm_attributes: int = 0x80
    configuration_name: str = "Config 1: HID relay"
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
                in_report_lengths=(7,),
                out_report_lengths=(0,),
                # Keep the HID input report at 7 bytes, but make the configfs
                # request size larger so each write is a short packet. On Pi
                # dwc2 this avoids an extra empty interrupt-IN completion after
                # every full-size mouse report.
                configfs_report_length=8,
            ),
            GadgetHidDevice.from_existing(
                usb_hid.Device.CONSUMER_CONTROL,
                function_index=2,
                protocol=0,
                subclass=0,
            ),
        ),
        bcd_device="0x0205",
        product_name="USB Combo Device",
        serial_number="213374badcafe",
        max_power=100,
        bm_attributes=0xA0,
        max_speed="high-speed",
    )
