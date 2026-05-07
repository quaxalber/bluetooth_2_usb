from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..args import Arguments


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    devices: tuple[str, ...]
    auto: bool
    grab: bool
    shortcut: tuple[str, ...]
    debug: bool


def runtime_config_from_args(args: Arguments) -> RuntimeConfig:
    return RuntimeConfig(
        devices=tuple(args.devices or ()),
        auto=args.auto,
        grab=args.grab,
        shortcut=tuple(args.shortcut or ()),
        debug=args.debug,
    )
