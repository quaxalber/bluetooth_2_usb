from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UdcState(StrEnum):
    """Enumerate normalized USB device-controller states emitted by the runtime monitor."""

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
        """Build a UdcState from the supplied input.

        :return: The requested value or status result.
        """
        normalized = raw_state.strip().lower().replace(" ", "_").replace("-", "_")
        try:
            return cls(normalized)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class DeviceAdded:
    """Record that an input device path was added by udev hotplug."""

    path: str


@dataclass(frozen=True, slots=True)
class DeviceRemoved:
    """Record that an input device path was removed by udev hotplug."""

    path: str


@dataclass(frozen=True, slots=True)
class UdcStateChanged:
    """Record a normalized USB device-controller state transition."""

    state: UdcState

    def __post_init__(self) -> None:
        """Normalize derived dataclass state after initialization.

        :return: None.
        """
        if not isinstance(self.state, UdcState):
            object.__setattr__(self, "state", UdcState.from_raw(str(self.state)))


@dataclass(frozen=True, slots=True)
class ShutdownRequested:
    """Record a request for graceful runtime shutdown and its source reason."""

    reason: str


RuntimeEvent = DeviceAdded | DeviceRemoved | UdcStateChanged | ShutdownRequested
