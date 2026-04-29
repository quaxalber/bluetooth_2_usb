from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceAdded:
    path: str


@dataclass(frozen=True, slots=True)
class DeviceRemoved:
    path: str


@dataclass(frozen=True, slots=True)
class UdcStateChanged:
    state: str


@dataclass(frozen=True, slots=True)
class ShutdownRequested:
    reason: str


RuntimeEvent = DeviceAdded | DeviceRemoved | UdcStateChanged | ShutdownRequested
