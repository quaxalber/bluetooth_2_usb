from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..args import Arguments


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    device_ids: tuple[str, ...]
    auto_discover: bool
    grab_devices: bool
    interrupt_shortcut: tuple[str, ...]
    log_to_file: bool
    log_path: str
    debug: bool
    usb_serial: str
    usb_product_suffix: str
    udc_path: Path | None


def runtime_config_from_args(args: Arguments, *, udc_path: Path | None) -> RuntimeConfig:
    return RuntimeConfig(
        device_ids=tuple(args.device_ids or ()),
        auto_discover=args.auto_discover,
        grab_devices=args.grab_devices,
        interrupt_shortcut=tuple(args.interrupt_shortcut or ()),
        log_to_file=args.log_to_file,
        log_path=args.log_path,
        debug=args.debug,
        usb_serial=getattr(args, "usb_serial", ""),
        usb_product_suffix=getattr(args, "usb_product_suffix", ""),
        udc_path=udc_path,
    )
