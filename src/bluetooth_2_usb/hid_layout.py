from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import usb_hid

DEFAULT_KEYBOARD_DESCRIPTOR = bytes.fromhex(
    "05010906a101050719e029e715002501750195088102950175088101"
    "95037501050819012903910295057501910195067508150026ff0005"
    "0719002aff008100c0"
)

DEFAULT_MOUSE_DESCRIPTOR = bytes.fromhex(
    "05010902a1010901a10005091901290815002501950875018102"
    "05010930093116018026ff7f75109502810609381581257f7508"
    "95018106050c0a38021581257f750895018106c0c0"
)


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
                # dwc2/configfs emits an extra empty interrupt-IN completion when
                # report_length exactly matches this full-size mouse payload.
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
