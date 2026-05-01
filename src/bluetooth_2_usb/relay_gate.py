from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RelayGateListener(Protocol):
    def __call__(self, active: bool) -> None: ...


@dataclass(slots=True)
class RelayGateState:
    host_configured: bool = False
    user_enabled: bool = True
    write_suspended: bool = False

    @property
    def active(self) -> bool:
        return self.host_configured and self.user_enabled and not self.write_suspended


class RelayGate:
    """
    Tracks why relaying is enabled or disabled.

    Host cable state, user pause state, and HID write suspension are separate
    causes. Keeping them explicit prevents one state transition from
    accidentally overriding another.
    """

    def __init__(self) -> None:
        self._state = RelayGateState()
        self._listeners: list[RelayGateListener] = []

    @property
    def state(self) -> RelayGateState:
        return RelayGateState(
            host_configured=self._state.host_configured,
            user_enabled=self._state.user_enabled,
            write_suspended=self._state.write_suspended,
        )

    @property
    def active(self) -> bool:
        return self._state.active

    def add_listener(self, listener: RelayGateListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: RelayGateListener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def set_host_configured(self, configured: bool) -> None:
        previous_active = self.active
        fresh_configured = configured and not self._state.host_configured
        self._state.host_configured = configured
        if fresh_configured:
            self._state.write_suspended = False
        self._notify_if_changed(previous_active)

    def set_user_enabled(self, enabled: bool) -> None:
        previous_active = self.active
        self._state.user_enabled = enabled
        self._notify_if_changed(previous_active)

    def toggle_user_enabled(self) -> bool:
        self.set_user_enabled(not self._state.user_enabled)
        return self._state.user_enabled

    def suspend_writes(self) -> None:
        previous_active = self.active
        self._state.write_suspended = True
        self._notify_if_changed(previous_active)

    def _notify_if_changed(self, previous_active: bool) -> None:
        active = self.active
        if active == previous_active:
            return
        for listener in list(self._listeners):
            listener(active)
