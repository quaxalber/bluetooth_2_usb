from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..logging import get_logger

logger = get_logger(__name__)


class RelayGateListener(Protocol):
    def __call__(self, active: bool) -> None: ...


class RelayInactiveReason(StrEnum):
    HOST_NOT_CONFIGURED = "host_not_configured"
    USER_PAUSED = "user_paused"
    WRITE_SUSPENDED = "write_suspended"


@dataclass(slots=True)
class RelayGateState:
    host_configured: bool = False
    user_enabled: bool = True
    write_suspended: bool = False

    @property
    def active(self) -> bool:
        return self.host_configured and self.user_enabled and not self.write_suspended

    @property
    def inactive_reasons(self) -> tuple[RelayInactiveReason, ...]:
        reasons: list[RelayInactiveReason] = []
        if not self.host_configured:
            reasons.append(RelayInactiveReason.HOST_NOT_CONFIGURED)
        if not self.user_enabled:
            reasons.append(RelayInactiveReason.USER_PAUSED)
        if self.write_suspended:
            reasons.append(RelayInactiveReason.WRITE_SUSPENDED)
        return tuple(reasons)


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
        previous_state = self.state
        fresh_configured = configured and not self._state.host_configured
        self._state.host_configured = configured
        if fresh_configured:
            self._state.write_suspended = False
        self._state_changed(previous_state)

    def set_user_enabled(self, enabled: bool) -> None:
        previous_state = self.state
        self._state.user_enabled = enabled
        self._state_changed(previous_state)

    def toggle_user_enabled(self) -> bool:
        self.set_user_enabled(not self._state.user_enabled)
        return self._state.user_enabled

    def suspend_writes(self) -> bool:
        previous_state = self.state
        self._state.write_suspended = True
        self._state_changed(previous_state)
        return not previous_state.write_suspended

    def resume_writes(self) -> bool:
        previous_state = self.state
        self._state.write_suspended = False
        self._state_changed(previous_state)
        return previous_state.write_suspended

    def _state_changed(self, previous_state: RelayGateState) -> None:
        if previous_state == self._state:
            return
        self._log_state_change(previous_state)
        active = self.active
        if active == previous_state.active:
            return
        for listener in list(self._listeners):
            listener(active)

    def _log_state_change(self, previous_state: RelayGateState) -> None:
        logger.debug(
            "Relay gate changed: active=%s host_configured=%s user_enabled=%s "
            "write_suspended=%s inactive_reasons=%s previous_active=%s",
            self._state.active,
            self._state.host_configured,
            self._state.user_enabled,
            self._state.write_suspended,
            ",".join(reason.value for reason in self._state.inactive_reasons) or "none",
            previous_state.active,
        )
