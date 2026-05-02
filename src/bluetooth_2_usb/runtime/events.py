from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UdcState(StrEnum):
    NOT_ATTACHED = "not_attached"
    ATTACHED = "attached"
    POWERED = "powered"
    DEFAULT = "default"
    ADDRESSED = "addressed"
    CONFIGURED = "configured"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"

    @classmethod
    def from_raw(cls, raw_state: str) -> UdcState:
        normalized = raw_state.strip().lower().replace(" ", "_").replace("-", "_")
        try:
            return cls(normalized)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class DeviceAdded:
    path: str


@dataclass(frozen=True, slots=True)
class DeviceRemoved:
    path: str


@dataclass(frozen=True, slots=True)
class UdcStateChanged:
    state: UdcState

    def __post_init__(self) -> None:
        if not isinstance(self.state, UdcState):
            object.__setattr__(self, "state", UdcState.from_raw(str(self.state)))


@dataclass(frozen=True, slots=True)
class ShutdownRequested:
    reason: str


RuntimeEvent = DeviceAdded | DeviceRemoved | UdcStateChanged | ShutdownRequested
